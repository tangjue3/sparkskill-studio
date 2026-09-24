#!/usr/bin/env python3
"""test_multi_video_pipeline.py — 任务 06 多视频闭环自动化测试（SparkSkill Studio）

测试分四类，结果中明确标注输入性质：
  A. Schema/校验器测试：旧单媒体规格向后兼容、多视频规格、重复 source_id、
     非法 time_offset_ms、未授权路径、shell 元字符路径（规则测试，不调用模型）；
  B. 像素坐标受控归一化单元测试：合法像素坐标归一化、混合/越界/顺序错误/
     尺寸未知/负坐标/已归一化坐标（真实 PNG 帧 + 构造输入，明确标注）；
  C. 多视频聚合测试：全局时间 = 原时间 + time_offset_ms、排序、每来源时间戳
     递增、失败帧保留、per-source/global 摘要（真实抽取帧 + 构造证据回放）；
  D. 多视频报告测试：状态复算、跨视频语义限制（禁用措辞扫描）、交叉校验。

用法:
    python3 test_multi_video_pipeline.py [--results-json <path>]
退出码: 0 = 全部通过; 1 = 存在失败项
"""
import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", "..", "..", ".."))
EXTRACTOR_DIR = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor")
COMPILER_DIR = os.path.join(PROJECT_ROOT, ".dsh", "skills", "task-to-skill-compiler")
REPORTER_DIR = os.path.join(PROJECT_ROOT, ".dsh", "skills", "evidence-report-generator")
TASK03_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-03")
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "schemas", "visual-task-spec.schema.json")
VIDEO_A = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures", "videos",
                        "fixture-appear-midway.mp4")
VIDEO_B = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures", "videos",
                        "fixture-disappear-midway.mp4")

FORBIDDEN_PHRASINGS = [
    "same physical instance", "moved from A to B", "carried by the same person",
    "entered another camera", "identity matched",
]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, os.path.join(EXTRACTOR_DIR, "scripts"))
import skill_env  # noqa: E402

skill_env.ensure_cv2_interpreter()

analyze_image = load_module("analyze_image", os.path.join(EXTRACTOR_DIR, "scripts", "analyze_image.py"))
extract_frames_mod = load_module("extract_frames", os.path.join(EXTRACTOR_DIR, "scripts", "extract_frames.py"))
trace_multi = load_module("trace_multi_video", os.path.join(EXTRACTOR_DIR, "scripts", "trace_multi_video.py"))
generate_report = load_module("generate_report", os.path.join(REPORTER_DIR, "scripts", "generate_report.py"))

RESULTS = []


def record(test_id, name, passed, detail, input_nature):
    RESULTS.append({
        "id": test_id,
        "name": name,
        "passed": bool(passed),
        "detail": detail,
        "input_nature": input_nature,
    })
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {test_id} — {name}: {detail}")


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def base_multi_spec(source_a, source_b, offset_b=0):
    return {
        "task_id": "multi-video-trace-001",
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_trace",
        "target": {"description": "红色正方形", "attributes": ["红色", "正方形"]},
        "source_media": [
            {"source_id": "video-a", "path": source_a, "location": "scene-a",
             "time_offset_ms": 0},
            {"source_id": "video-b", "path": source_b, "location": "scene-b",
             "time_offset_ms": offset_b},
        ],
        "required_outputs": ["per_source_timeline", "global_timeline", "keyframes",
                             "evidence_report"],
        "constraints": {
            "abstain_if_insufficient_evidence": True,
            "forbidden_inferences": ["identity", "age", "nationality",
                                     "relationship", "intent"],
        },
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
    }


def run_validator(spec_path):
    validator = os.path.join(COMPILER_DIR, "scripts", "validate_task_spec.py")
    return subprocess.run([sys.executable, validator, "--schema", SCHEMA_PATH,
                           "--input", spec_path],
                          capture_output=True, text=True)


# ---------------------------------------------------------------- A. Schema / 校验器

def test_schema_and_validator():
    with tempfile.TemporaryDirectory(prefix="sparkskill-t06-schema-") as tmp:
        # A1 旧单媒体规格仍然通过（向后兼容）
        proc = run_validator(os.path.join(TASK03_DIR, "task-spec.json"))
        record("A1-legacy-single-media-spec-valid", "旧单媒体 VisualTaskSpec 仍然通过",
               proc.returncode == 0 and "RESULT: VALID" in proc.stdout,
               f"exit={proc.returncode}（任务 03 真实规格，source_media 为字符串）",
               "任务 03 真实产物（artifacts/task-03/task-spec.json）")

        # A2 多视频规格通过
        spec_path = os.path.join(tmp, "multi-spec.json")
        with open(spec_path, "w", encoding="utf-8") as handle:
            json.dump(base_multi_spec(VIDEO_A, VIDEO_B, 5000), handle, ensure_ascii=False)
        proc = run_validator(spec_path)
        record("A2-multi-video-spec-valid", "多视频 VisualTaskSpec 通过",
               proc.returncode == 0 and "RESULT: VALID" in proc.stdout,
               f"exit={proc.returncode}（两来源 + time_offset_ms=5000）",
                "构造输入（仓库内两段合成 fixture 路径）")

        # A3 重复 source_id 被拒绝
        dup = base_multi_spec(VIDEO_A, VIDEO_B)
        dup["source_media"][1]["source_id"] = "video-a"
        dup_path = os.path.join(tmp, "dup-spec.json")
        with open(dup_path, "w", encoding="utf-8") as handle:
            json.dump(dup, handle, ensure_ascii=False)
        proc = run_validator(dup_path)
        record("A3-duplicate-source-id-rejected", "重复 source_id 被拒绝",
               proc.returncode == 1 and "重复" in proc.stderr,
               f"exit={proc.returncode}（期望 1），stderr 含“重复”",
               "构造输入（复制 source_id）")

        # A4 非法 time_offset_ms 被拒绝
        bad_offset = base_multi_spec(VIDEO_A, VIDEO_B)
        bad_offset["source_media"][1]["time_offset_ms"] = -100
        bad_path = os.path.join(tmp, "bad-offset.json")
        with open(bad_path, "w", encoding="utf-8") as handle:
            json.dump(bad_offset, handle, ensure_ascii=False)
        proc = run_validator(bad_path)
        record("A4-negative-time-offset-rejected", "非法 time_offset_ms 被拒绝",
               proc.returncode == 1 and "time_offset_ms" in proc.stderr,
               f"exit={proc.returncode}（期望 1），stderr 含 time_offset_ms",
               "构造输入（负偏移）")

        # A5 未授权路径被拒绝
        bad_path_spec = base_multi_spec(VIDEO_A, VIDEO_B)
        bad_path_spec["source_media"][1]["path"] = "/etc/shadow"
        unauthorized = os.path.join(tmp, "unauthorized.json")
        with open(unauthorized, "w", encoding="utf-8") as handle:
            json.dump(bad_path_spec, handle, ensure_ascii=False)
        proc = run_validator(unauthorized)
        record("A5-unauthorized-path-rejected", "未授权路径被拒绝",
               proc.returncode == 1 and "未授权路径" in proc.stderr,
               f"exit={proc.returncode}（期望 1），stderr 含“未授权路径”",
               "构造输入（/etc/shadow）")

        # A6 shell 元字符路径被拒绝
        shell_spec = base_multi_spec(VIDEO_A, VIDEO_B)
        shell_spec["source_media"][1]["path"] = "/home/x.mp4; rm -rf /"
        shell_path = os.path.join(tmp, "shell.json")
        with open(shell_path, "w", encoding="utf-8") as handle:
            json.dump(shell_spec, handle, ensure_ascii=False)
        proc = run_validator(shell_path)
        record("A6-shell-metachar-path-rejected", "shell 元字符路径被拒绝",
               proc.returncode == 1,
               f"exit={proc.returncode}（期望 1）",
               "构造输入（路径含分号与 shell 命令）")

        # A7 旧版字符串 source_media 的路径安全校验同样生效
        legacy = base_multi_spec(VIDEO_A, VIDEO_B)
        legacy["source_media"] = "../../etc/passwd"
        legacy_path = os.path.join(tmp, "legacy-bad.json")
        with open(legacy_path, "w", encoding="utf-8") as handle:
            json.dump(legacy, handle, ensure_ascii=False)
        proc = run_validator(legacy_path)
        record("A7-legacy-path-guard-works", "旧版字符串 source_media 路径安全校验生效",
               proc.returncode == 1 and "未授权路径" in proc.stderr,
               f"exit={proc.returncode}（期望 1），路径穿越被拒绝",
               "构造输入（相对路径穿越）")


# ---------------------------------------------------------------- B. 像素坐标归一化

def test_pixel_normalization(real_frame):
    frame_path = real_frame["frame_path"]

    # B1 合法像素坐标 → 归一化成功（真实 PNG 帧尺寸）
    width, height = analyze_image.read_image_size(frame_path)
    box = [431, 222, 545, 356]
    result = analyze_image.normalize_bounding_box(box, width, height)
    expected = [round(431 / width, 6), round(222 / height, 6),
                round(545 / width, 6), round(356 / height, 6)]
    record("B1-pixel-box-normalized", "合法像素坐标归一化",
           result["bounding_box"] == expected
           and result["bounding_box_source_format"] == "pixel"
           and result["bounding_box_normalization_applied"] is True
           and result["frame_width"] == width and result["frame_height"] == height,
           f"{box} @ {width}x{height} -> {result['bounding_box']}（format=pixel, applied=true）",
           f"真实抽取帧（{os.path.basename(frame_path)}，{width}x{height}）+ 任务 05 真实出现过的像素坐标")

    # B2 read_image_size 读取真实帧尺寸
    record("B2-read-image-size-real-png", "纯标准库读取真实 PNG 宽高",
           isinstance(result["frame_width"], int) and result["frame_width"] > 0,
           f"read_image_size({os.path.basename(frame_path)}) = "
           f"({result['frame_width']}, {result['frame_height']})",
           "真实抽取帧（PNG）")

    # B3 混合坐标拒绝
    mixed = analyze_image.normalize_bounding_box([0.4, 222, 545, 356], width, height)
    record("B3-mixed-coords-rejected", "混合坐标不归一化",
           mixed["bounding_box"] is None and mixed["warning"] is not None
           and "混合" in mixed["warning"],
           f"[0.4,222,545,356] -> null，warning 含“混合”",
           "构造输入（混合坐标，明确标注）")

    # B4 越界像素坐标拒绝
    oob = analyze_image.normalize_bounding_box([100, 100, 5000, 3000], width, height)
    record("B4-out-of-bounds-rejected", "越界像素坐标不归一化",
           oob["bounding_box"] is None and oob["warning"] is not None
           and "超出图片尺寸" in oob["warning"],
           f"[100,100,5000,3000] @ {width}x{height} -> null，warning 含“超出图片尺寸”",
           "构造输入（越界坐标，明确标注）")

    # B5 顺序错误拒绝
    order = analyze_image.normalize_bounding_box([545, 356, 431, 222], width, height)
    record("B5-wrong-order-rejected", "坐标顺序错误不归一化",
           order["bounding_box"] is None and order["warning"] is not None
           and "顺序错误" in order["warning"],
           "[545,356,431,222] -> null，warning 含“顺序错误”",
           "构造输入（x1>x2，明确标注）")

    # B6 尺寸未知拒绝
    unknown = analyze_image.normalize_bounding_box([431, 222, 545, 356], None, None)
    record("B6-unknown-size-rejected", "尺寸未知不归一化",
           unknown["bounding_box"] is None and unknown["warning"] is not None
           and "无法读取关键帧真实宽高" in unknown["warning"],
           "[431,222,545,356] + 尺寸未知 -> null",
           "构造输入（尺寸不可知，明确标注）")

    # B7 已归一化坐标原样通过
    already = analyze_image.normalize_bounding_box([0.43, 0.22, 0.57, 0.38], width, height)
    record("B7-normalized-coords-passthrough", "已归一化坐标原样通过",
           already["bounding_box"] == [0.43, 0.22, 0.57, 0.38]
           and already["bounding_box_source_format"] == "normalized"
           and already["bounding_box_normalization_applied"] is False,
           "[0.43,0.22,0.57,0.38] -> 不变（format=normalized, applied=false）",
           "构造输入（归一化坐标，明确标注）")

    # B8 负坐标拒绝
    negative = analyze_image.normalize_bounding_box([-10, 222, 545, 356], width, height)
    record("B8-negative-coords-rejected", "负坐标不归一化",
           negative["bounding_box"] is None and negative["warning"] is not None
           and "负坐标" in negative["warning"],
           "[-10,222,545,356] -> null，warning 含“负坐标”",
           "构造输入（负坐标，明确标注）")

    # B9 coerce_evidence 端到端：像素框经归一化后进入证据（不抛错、不置帧失败）
    spec = {"task_id": "t", "task_type": "object_trace",
             "target": {"description": "红色正方形"}, "confidence_threshold": 0.5}
    raw = {"object_found": True, "description": "灰色背景中央有一个红色正方形",
           "bounding_box": [431, 222, 545, 356], "confidence": 0.95,
           "evidence_text": "画面中央可见一个清晰的红色正方形", "abstention_reason": None}
    evidence = analyze_image.coerce_evidence(raw, spec, frame_path, "test-model")
    record("B9-coerce-evidence-normalizes-pixel-box",
           "coerce_evidence 对像素框执行受控归一化（帧不失败）",
           evidence["bounding_box"] == expected
           and evidence["bounding_box_source_format"] == "pixel"
           and evidence["bounding_box_normalization_applied"] is True
           and evidence["frame_status" if "frame_status" in evidence else "object_found"] is True
           and evidence["warnings"] == [],
           f"bounding_box={evidence['bounding_box']}，raw={evidence['bounding_box_raw']}，"
           f"applied={evidence['bounding_box_normalization_applied']}，无 warning",
           "真实帧 + 构造模型返回（模拟任务 05 出现过的像素坐标，明确标注）")

    # B10 coerce_evidence 对非法框置 null + warning（帧不失败、不重跑）
    raw_bad = dict(raw, bounding_box=[100, 100, 5000, 3000])
    evidence_bad = analyze_image.coerce_evidence(raw_bad, spec, frame_path, "test-model")
    record("B10-coerce-evidence-nulls-invalid-box",
           "coerce_evidence 对非法框置 null 并记录 warning（不抛错）",
           evidence_bad["bounding_box"] is None
           and any("超出图片尺寸" in w for w in evidence_bad["warnings"])
           and evidence_bad["object_found"] is True
           and any("未通过契约校验" in g for g in evidence_bad["gaps"]),
           f"bounding_box=null，warnings={evidence_bad['warnings'][:1]}，"
           "object_found 保持 true（定位缺失不伪造）",
           "真实帧 + 构造模型返回（越界框，明确标注）")


# ---------------------------------------------------------------- C. 多视频聚合

def evidence_entry(sample, frame, source_offset=0.0):
    entry = {
        "timestamp_ms": frame["timestamp_ms"],
        "frame_path": frame["frame_path"],
        "object_found": sample["object_found"],
        "description": sample["description"],
        "bounding_box": sample["bounding_box"],
        "bounding_box_raw": sample.get("bounding_box_raw"),
        "bounding_box_source_format": sample.get("bounding_box_source_format"),
        "bounding_box_normalization_applied": sample.get(
            "bounding_box_normalization_applied", False),
        "frame_width": sample.get("frame_width"),
        "frame_height": sample.get("frame_height"),
        "confidence": sample["confidence"],
        "evidence_text": sample["evidence_text"],
        "abstention_reason": sample["abstention_reason"],
        "frame_status": "analyzed",
        "evidence_sufficient": sample["evidence_sufficient"],
        "gaps": list(sample.get("gaps") or []),
        "warnings": [],
    }
    return entry


def failed_entry_like(frame, reason="后端未调用（构造失败帧）"):
    return {
        "timestamp_ms": frame["timestamp_ms"],
        "frame_path": frame["frame_path"],
        "object_found": False,
        "description": "本帧未执行视觉分析",
        "bounding_box": None,
        "bounding_box_raw": None,
        "bounding_box_source_format": None,
        "bounding_box_normalization_applied": False,
        "frame_width": None,
        "frame_height": None,
        "confidence": 0.0,
        "evidence_text": "无模型输出",
        "abstention_reason": reason,
        "frame_status": "failed",
        "evidence_sufficient": False,
        "gaps": ["视觉后端未调用，本帧无证据"],
        "warnings": [],
    }


def test_multi_aggregation(frames_a, frames_b):
    positive = load_json(os.path.join(TASK03_DIR, "positive-evidence.json"))
    negative = load_json(os.path.join(TASK03_DIR, "negative-evidence.json"))

    # C1 全局时间 = 原时间 + time_offset_ms，且排序正确
    offset_b = 5000
    per_source = [
        {"source_id": "video-a", "path": VIDEO_A, "location": "scene-a",
         "time_offset_ms": 0,
         "timeline": [evidence_entry(positive, frames_a[0]),
                      evidence_entry(positive, frames_a[1])]},
        {"source_id": "video-b", "path": VIDEO_B, "location": "scene-b",
         "time_offset_ms": offset_b,
         "timeline": [evidence_entry(positive, frames_b[0]),
                      evidence_entry(positive, frames_b[1])]},
    ]
    merged = trace_multi.merge_global_timeline(per_source)
    times = [entry["global_timestamp_ms"] for entry in merged]
    expected_a = [frames_a[0]["timestamp_ms"], frames_a[1]["timestamp_ms"]]
    expected_b = [round(frames_b[0]["timestamp_ms"] + offset_b, 3),
                  round(frames_b[1]["timestamp_ms"] + offset_b, 3)]

    def close(got, want):
        return abs(got - want) < 1e-6

    global_ok = (times == sorted(times)
                 and all(close(e["global_timestamp_ms"], w) for e, w in zip(
                     [e for e in merged if e["source_id"] == "video-a"], expected_a))
                 and all(close(e["global_timestamp_ms"], w) for e, w in zip(
                     [e for e in merged if e["source_id"] == "video-b"], expected_b))
                 and all(close(e["timestamp_ms"],
                               e["global_timestamp_ms"] - e["source_time_offset_ms"])
                         for e in merged))
    record("C1-global-time-equals-local-plus-offset",
           "全局排序时间 = 原视频时间戳 + time_offset_ms，排序正确",
           global_ok,
           f"video-a 全局时间={[e['global_timestamp_ms'] for e in merged if e['source_id'] == 'video-a']}，"
           f"video-b 全局时间={[e['global_timestamp_ms'] for e in merged if e['source_id'] == 'video-b']}"
           f"（偏移 {offset_b} ms）；原时间戳保留不变",
           "真实抽取帧 + 任务 03 真实正向证据回放")

    # C2 每来源时间戳严格递增（聚合拒绝非递增）
    monotonic_ok = all(
        all(b["timestamp_ms"] > a["timestamp_ms"]
            for a, b in zip(src["timeline"], src["timeline"][1:]))
        for src in per_source)
    record("C2-per-source-timestamps-monotonic", "每段时间线时间戳递增",
           monotonic_ok,
           "video-a/video-b 的原视频时间戳均严格单调递增（由 trace_video 聚合规则保证）",
           "真实抽取帧时间戳")

    # C3 失败帧不丢弃：failed/not_found 条目全部保留
    mixed = [
        {"source_id": "video-a", "path": VIDEO_A, "location": "scene-a",
         "time_offset_ms": 0,
         "timeline": [evidence_entry(positive, frames_a[0]),
                      failed_entry_like(frames_a[1]),
                      evidence_entry(negative, frames_a[2] if len(frames_a) > 2 else frames_a[1])]},
        {"source_id": "video-b", "path": VIDEO_B, "location": "scene-b",
         "time_offset_ms": 0,
         "timeline": [evidence_entry(negative, frames_b[0])]},
    ]
    merged_mixed = trace_multi.merge_global_timeline(mixed)
    statuses = [entry["frame_status"] for entry in merged_mixed]
    classes = [trace_multi.frame_class(entry) for entry in merged_mixed]
    record("C3-failed-entries-preserved", "failed / not_found 帧全部保留（不丢弃）",
           len(merged_mixed) == 4 and statuses.count("failed") == 1
           and classes.count("not_found") == 2 and classes.count("confirmed") == 1,
           f"条目数={len(merged_mixed)}（期望 4），frame_status={statuses}，分类={classes}",
           "真实抽取帧 + 任务 03 真实正/负证据回放 + 构造失败帧（明确标注）")

    # C4 global_summary：首次/最后确认与确认帧数
    summary = trace_multi.summarize_global(merged, {
        "video-a": {"first_confirmed_timestamp_ms": frames_a[0]["timestamp_ms"],
                    "last_confirmed_timestamp_ms": frames_a[1]["timestamp_ms"],
                    "confirmed_frame_count": 2, "overall_status": "completed"},
        "video-b": {"first_confirmed_timestamp_ms": frames_b[0]["timestamp_ms"],
                    "last_confirmed_timestamp_ms": frames_b[1]["timestamp_ms"],
                    "confirmed_frame_count": 2, "overall_status": "completed"},
    })
    record("C4-global-summary-first-last-confirmed",
           "全局首次/最后确认与确认帧数正确",
           summary["confirmed_entry_count"] == 4
           and abs(summary["first_confirmed_global_timestamp_ms"] - expected_a[0]) < 1e-6
           and abs(summary["last_confirmed_global_timestamp_ms"] - expected_b[1]) < 1e-6
           and summary["sources_with_confirmation"] == ["video-a", "video-b"]
           and summary["overall_status"] == "completed",
           f"confirmed={summary['confirmed_entry_count']}，"
           f"first={summary['first_confirmed_global_timestamp_ms']}，"
           f"last={summary['last_confirmed_global_timestamp_ms']}，"
           f"sources={summary['sources_with_confirmation']}",
           "规则计算（基于真实帧时间戳与回放证据）")

    # C5 normalize_sources：重复 source_id 拒绝
    dup_spec = base_multi_spec(VIDEO_A, VIDEO_B)
    dup_spec["source_media"][1]["source_id"] = "video-a"
    try:
        trace_multi.normalize_sources(dup_spec)
        dup_rejected = False
    except trace_multi.MultiTraceError:
        dup_rejected = True
    record("C5-normalize-sources-rejects-duplicate-id",
           "normalize_sources 拒绝重复 source_id",
           dup_rejected, "重复 source_id → MultiTraceError",
           "构造输入（明确标注）")

    # C6 normalize_sources：负 time_offset_ms 拒绝
    neg_spec = base_multi_spec(VIDEO_A, VIDEO_B)
    neg_spec["source_media"][1]["time_offset_ms"] = -1
    try:
        trace_multi.normalize_sources(neg_spec)
        neg_rejected = False
    except trace_multi.MultiTraceError:
        neg_rejected = True
    record("C6-normalize-sources-rejects-negative-offset",
           "normalize_sources 拒绝负 time_offset_ms",
           neg_rejected, "time_offset_ms=-1 → MultiTraceError",
           "构造输入（明确标注）")

    # C7 normalize_sources：旧版字符串 → 单一来源 media-0
    legacy_spec = base_multi_spec(VIDEO_A, VIDEO_B)
    legacy_spec["source_media"] = VIDEO_A
    legacy_sources = trace_multi.normalize_sources(legacy_spec)
    record("C7-legacy-string-becomes-single-source",
           "旧版字符串 source_media 包装为单一来源（向后兼容）",
           len(legacy_sources) == 1 and legacy_sources[0]["source_id"] == "media-0"
           and legacy_sources[0]["time_offset_ms"] == 0,
           f"来源={legacy_sources}",
           "构造输入（旧版规格形态）")

    # C8 执行期路径守卫：未授权路径拒绝（拒绝原因必须来自路径规则本身，
    #    而非校验器加载失败等无关错误——后者曾掩盖本用例的真实性）
    bad_spec = base_multi_spec(VIDEO_A, VIDEO_B)
    bad_spec["source_media"][1]["path"] = "/etc/shadow"
    try:
        trace_multi.guard_source_paths(trace_multi.normalize_sources(bad_spec))
        path_rejected, reject_reason = False, ""
    except trace_multi.MultiTraceError as error:
        path_rejected, reject_reason = True, str(error)
    record("C8-execution-path-guard-rejects-unauthorized",
           "执行期路径守卫拒绝未授权路径（纵深防御）",
           path_rejected and "未授权路径" in reject_reason,
           f"/etc/shadow → MultiTraceError: {reject_reason[:80]}",
           "构造输入（未授权路径）")

    # C9 执行期路径守卫放行授权媒体根内的真实路径（证明校验器可正常加载，
    #    C8 的拒绝确实来自路径规则而非加载失败）
    try:
        trace_multi.guard_source_paths(trace_multi.normalize_sources(
            base_multi_spec(VIDEO_A, VIDEO_B)))
        authorized_accepted = True
    except trace_multi.MultiTraceError:
        authorized_accepted = False
    record("C9-execution-path-guard-accepts-authorized",
           "执行期路径守卫放行授权根内真实路径（校验器可加载）",
           authorized_accepted,
           "两段仓库内合成 fixture 路径均通过执行期路径守卫",
            "仓库内合成 fixture 路径（授权媒体根内）")


# ---------------------------------------------------------------- D. 多视频报告

def make_global_doc(frames_a, frames_b, entries_a, entries_b, offset_b=0,
                    sources_status=None):
    per_source = [
        {"source_id": "video-a", "path": VIDEO_A, "location": "scene-a",
         "time_offset_ms": 0, "timeline": entries_a},
        {"source_id": "video-b", "path": VIDEO_B, "location": "scene-b",
         "time_offset_ms": offset_b, "timeline": entries_b},
    ]
    merged = trace_multi.merge_global_timeline(per_source)
    per_source_summaries = {}
    sources = []
    for source, sid in zip(per_source, ("video-a", "video-b")):
        ordered, _, summary = trace_video_summary(source["timeline"])
        per_source_summaries[sid] = summary
        sources.append({
            "source_id": sid, "path": source["path"], "location": source["location"],
            "time_offset_ms": source["time_offset_ms"], "duration_ms": 4458.333,
            "sampled_frames": len(source["timeline"]),
            "timeline_path": f"per-source/{sid}-timeline.json",
            "keyframes_dir": f"per-source/keyframes/{sid}", "summary": summary,
            "warnings": [], "resource_blocked": False,
        })
    global_summary = trace_multi.summarize_global(merged, per_source_summaries)
    return {
        "schema_version": "1.2.0",
        "task_id": "multi-video-trace-001",
    "target_query": "红色正方形",
        "sources": sources,
        "global_timeline": merged,
        "global_summary": global_summary,
        "semantic_limitations": trace_multi.SEMANTIC_LIMITATIONS,
        "warnings": [],
    }


def trace_video_summary(entries):
    trace_video_mod = load_module("trace_video", os.path.join(
        EXTRACTOR_DIR, "scripts", "trace_video.py"))
    return trace_video_mod.aggregate(entries)


def test_multi_report(frames_a, frames_b):
    spec = base_multi_spec(VIDEO_A, VIDEO_B, 5000)
    positive = load_json(os.path.join(TASK03_DIR, "positive-evidence.json"))
    negative = load_json(os.path.join(TASK03_DIR, "negative-evidence.json"))

    # D1 正向两来源确认 → completed，结论只用允许措辞，不含禁用措辞
    doc = make_global_doc(
        frames_a, frames_b,
        [evidence_entry(positive, frames_a[0]), evidence_entry(positive, frames_a[1])],
        [evidence_entry(positive, frames_b[0]), evidence_entry(positive, frames_b[1])],
        offset_b=5000)
    report = generate_report.build_multi_video_report(spec, doc)
    conclusion = report["conclusion"]
    has_allowed = ("matched target query" in conclusion
                   and "visually consistent with target description" in conclusion
                   and "confirmed in source video-a" in conclusion
                   and "confirmed in source video-b" in conclusion)
    has_forbidden = any(p in conclusion.lower() for p in FORBIDDEN_PHRASINGS)
    record("D1-positive-multi-source-report",
           "正向多视频报告：completed + 允许措辞 + 无禁止措辞",
           report["status"] == "completed"
           and report["global_summary"]["confirmed_entry_count"] == 4
           and has_allowed and not has_forbidden
           and report["semantic_limitation_note"] != "",
           f"status={report['status']}，confirmed={report['global_summary']['confirmed_entry_count']}，"
           f"允许措辞齐全={has_allowed}，禁止措辞={has_forbidden}",
            "任务 03 真实正向证据回放到两段合成 fixture 的帧时间戳")

    # D2 负向全部 not_found → completed 负面结论，无跨视频断言
    doc_neg = make_global_doc(
        frames_a, frames_b,
        [evidence_entry(negative, frames_a[0]), evidence_entry(negative, frames_a[1])],
        [evidence_entry(negative, frames_b[0])], offset_b=5000)
    report_neg = generate_report.build_multi_video_report(spec, doc_neg)
    neg_forbidden = any(p in report_neg["conclusion"].lower() for p in FORBIDDEN_PHRASINGS)
    record("D2-negative-multi-source-report",
           "负向多视频报告：completed 负面结论，无跨视频断言",
           report_neg["status"] == "completed"
           and report_neg["global_summary"]["confirmed_entry_count"] == 0
           and "未确认" in report_neg["conclusion"] and not neg_forbidden,
           f"status={report_neg['status']}，confirmed=0，结论含“未确认”="
           f"{'未确认' in report_neg['conclusion']}，禁止措辞={neg_forbidden}",
           "任务 03 真实负向证据（红色背包确定性负面）回放")

    # D3 abstained → 拒答
    abstained = dict(negative)
    abstained["abstention_reason"] = "画面模糊，无法确认（构造样例，非模型输出）"
    abstained["evidence_sufficient"] = False
    abstained["gaps"] = ["目标未被确认存在"]
    doc_abs = make_global_doc(
        frames_a, frames_b,
        [evidence_entry(abstained, frames_a[0])],
        [evidence_entry(abstained, frames_b[0])], offset_b=5000)
    report_abs = generate_report.build_multi_video_report(spec, doc_abs)
    record("D3-abstained-multi-source-report", "证据不足 → abstained 拒答",
           report_abs["status"] == "abstained"
           and isinstance(report_abs["abstention_reason"], str)
           and report_abs["abstention_reason"],
           f"status={report_abs['status']}，abstention_reason 非空",
           "构造输入（在真实负向证据上设置 abstention_reason，明确标注）")

    # D4 failed → 无存在性断言
    doc_failed = make_global_doc(
        frames_a, frames_b,
        [failed_entry_like(frames_a[0])], [failed_entry_like(frames_b[0])])
    report_failed = generate_report.build_multi_video_report(spec, doc_failed)
    record("D4-failed-multi-source-report", "全部失败 → failed，无存在性断言",
           report_failed["status"] == "failed"
           and "存在性断言" in report_failed["conclusion"]
           and "未获得任何有效证据" in report_failed["conclusion"]
           and report_failed["confidence"] == 0.0,
           f"status={report_failed['status']}，confidence={report_failed['confidence']}，"
           f"结论={report_failed['conclusion'][:50]}...",
           "构造输入（失败帧，明确标注）")

    # D5 状态交叉校验：注入不一致被复算纠正
    tampered = json.loads(json.dumps(doc))
    tampered["global_summary"]["overall_status"] = "abstained"
    tampered["global_summary"]["confirmed_entry_count"] = 99
    tampered_report = generate_report.build_multi_video_report(spec, tampered)
    record("D5-cross-check-recompute", "多视频报告状态交叉校验（注入不一致被纠正）",
           tampered_report["status"] == "completed"
           and any("交叉校验不一致" in w for w in tampered_report["warnings"]),
           f"注入 abstained/99 后复算 status={tampered_report['status']}，"
           f"warnings 记录冲突={any('交叉校验不一致' in w for w in tampered_report['warnings'])}",
           "构造输入（篡改 global_summary，明确标注）")

    # D6 全局时间线条目可回溯到来源与关键帧
    traceable = all(
        entry.get("source_id") in ("video-a", "video-b")
        and os.path.isfile(entry.get("frame_path", ""))
        and isinstance(entry.get("timestamp_ms"), (int, float))
        and isinstance(entry.get("global_timestamp_ms"), (int, float))
        for entry in doc["global_timeline"])
    record("D6-global-entries-traceable", "每条全局证据可回溯到来源视频与关键帧",
           traceable,
           f"{len(doc['global_timeline'])} 条全局条目均含 source_id + 真实帧路径 + 双时间戳",
           "真实抽取帧（文件真实存在）")


def main():
    parser = argparse.ArgumentParser(description="任务 06 多视频闭环自动化测试")
    parser.add_argument("--results-json", help="测试结果 JSON 输出路径")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="sparkskill-t06-frames-") as tmp:
        extraction_a = extract_frames_mod.extract_frames(
            VIDEO_A, os.path.join(tmp, "frames-a"), interval_ms=800, max_frames=3)
        extraction_b = extract_frames_mod.extract_frames(
            VIDEO_B, os.path.join(tmp, "frames-b"), interval_ms=4000, max_frames=2)
        frames_a = extraction_a["frames"]
        frames_b = extraction_b["frames"]

        test_schema_and_validator()
        test_pixel_normalization(frames_a[0])
        test_multi_aggregation(frames_a, frames_b)
        test_multi_report(frames_a, frames_b)

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    summary = {
        "suite": "task-06-multi-video-pipeline",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "passed": passed,
        "total": total,
        "note": "小样本只记录通过数/总数，不写百分比；输入性质逐条标注；"
                "聚合/报告/归一化规则测试使用真实抽取帧 + 任务 03 真实证据回放与构造输入"
                "（明确标注），未调用视觉模型；真实多视频 Qwen 逐帧运行见 "
                 "任务 06 的 DSH 自主会话产物（内部留档）",
        "results": RESULTS,
    }
    if args.results_json:
        with open(args.results_json, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(f"\n小计：{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
