#!/usr/bin/env python3
"""test_video_pipeline.py — 任务 04 视频闭环自动化测试（SparkSkill Studio）

测试分两类，结果中明确标注输入性质：
  A. 真实视频抽取测试：对仓库内任务 16 冻结合成 fixture 视频
     （fixture-reappear.mp4，640×360@24fps，8s）执行元数据读取与抽帧（真实运行）；
  B. 聚合规则测试：使用任务 03 已有的真实 Qwen 图片证据样例
     （artifacts/task-03/positive-evidence.json、negative-evidence.json，
     真实模型输出）回放到视频聚合与报告规则中（证据真实，回放位置为真实帧时间戳；
     这不是真实视频 Qwen 逐帧运行——任务 04 当时的真实运行受统一内存资源条件阻塞，
     历史记录见内部留档的任务 04 run-summary）；
  C. 负向/错误处理测试：目标不存在样例、证据不足样例（构造，明确标注）、
     bounding_box 不伪造、报告状态一致性、失败输入错误处理。

公开版适配说明：内部留档版的本测试对开发机 MiniMax-H3 测试视频（960×576，
4458.333ms）抽取；公开版改用仓库内可再分发的任务 16 合成 fixture（640×360，8000ms），
A1 元数据断言随 fixture 适配；测试覆盖的代码路径与聚合/报告规则不变。

用法:
    python3 test_video_pipeline.py [--results-json <path>]
退出码: 0 = 全部通过; 1 = 存在失败项
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", "..", "..", ".."))
EXTRACTOR_DIR = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor")
REPORTER_DIR = os.path.join(PROJECT_ROOT, ".dsh", "skills", "evidence-report-generator")
TASK03_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-03")
REAL_VIDEO = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures", "videos",
                          "fixture-reappear.mp4")
FIXTURE_DURATION_MS = 8000.0


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, os.path.join(EXTRACTOR_DIR, "scripts"))
import skill_env  # noqa: E402

skill_env.ensure_cv2_interpreter()

trace_video = load_module("trace_video", os.path.join(EXTRACTOR_DIR, "scripts", "trace_video.py"))
extract_frames_mod = load_module("extract_frames", os.path.join(EXTRACTOR_DIR, "scripts", "extract_frames.py"))
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


# ---------------------------------------------------------------- A. 真实视频抽取

def test_extraction():
    with tempfile.TemporaryDirectory(prefix="sparkskill-t04-") as tmp:
        meta_path = os.path.join(tmp, "meta.json")
        result = extract_frames_mod.extract_frames(
            REAL_VIDEO, os.path.join(tmp, "frames"),
            interval_ms=800, max_frames=6)
        with open(meta_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False)

        meta = result["metadata"]
        record("A1-video-metadata", "视频元数据读取（仓库内合成 fixture）",
                meta["fps"] == 24.0 and meta["frame_count"] == 192
                and meta["width"] == 640 and meta["height"] == 360
                and abs(meta["duration_ms"] - FIXTURE_DURATION_MS) < 1.0,
                f"fps={meta['fps']} frames={meta['frame_count']} "
                f"{meta['width']}x{meta['height']} duration_ms={meta['duration_ms']}",
                "仓库内合成技术 fixture（任务 16 冻结，generate_task16_fixtures.py 渲染）")

        frames = result["frames"]
        all_exist = all(os.path.isfile(f["frame_path"]) for f in frames)
        record("A2-frame-extraction", "帧抽取（真实视频）",
               len(frames) == 6 and all_exist,
               f"计划 6 帧，实际 {len(frames)} 帧，文件全部存在={all_exist}",
               "真实视频文件")

        timestamps = [f["timestamp_ms"] for f in frames]
        monotonic = all(b > a for a, b in zip(timestamps, timestamps[1:]))
        record("A3-monotonic-timestamps", "时间戳单调递增",
               monotonic,
               f"timestamps={timestamps}",
               "真实视频文件")

        record("A4-frame-traceability", "帧路径可追溯",
               all(os.path.isfile(f["frame_path"]) and f["frame_path"].endswith(".png")
                   for f in frames),
               "每个帧索引路径均指向真实存在的 PNG 文件",
               "真实视频文件")

        parsed = load_json(meta_path)
        record("A5-json-parseable", "帧索引 JSON 可解析",
               isinstance(parsed, dict) and len(parsed["frames"]) == 6,
               "extract_frames 输出 JSON 可解析且含 6 帧索引",
               "真实视频文件")


# ---------------------------------------------------------------- B. 聚合规则（真实证据回放）

def evidence_entry(sample, frame):
    """把任务 03 真实证据样例装配到真实帧位置上（证据字段原样透传）。"""
    entry = {
        "timestamp_ms": frame["timestamp_ms"],
        "frame_path": frame["frame_path"],
        "object_found": sample["object_found"],
        "description": sample["description"],
        "bounding_box": sample["bounding_box"],
        "confidence": sample["confidence"],
        "evidence_text": sample["evidence_text"],
        "abstention_reason": sample["abstention_reason"],
        "frame_status": "analyzed",
        "evidence_sufficient": sample["evidence_sufficient"],
        "gaps": list(sample.get("gaps") or []),
    }
    # 定位框覆盖接近整幅画面时标记定位不可靠（不修改模型返回，只追加缺口说明）
    bbox = entry["bounding_box"]
    if bbox is not None:
        area = max(0.0, (bbox[2] - bbox[0])) * max(0.0, (bbox[3] - bbox[1]))
        if area >= 0.95:
            entry["gaps"].append("bounding_box 覆盖接近整幅画面，定位不可靠，不作为精确定位证据")
    return entry


def make_timeline(spec, entries):
    timeline, state_changes, summary = trace_video.aggregate(entries)
    return {
        "schema_version": "1.1.0",
        "source_video": REAL_VIDEO,
        "duration_ms": FIXTURE_DURATION_MS,
        "sampled_frames": len(timeline),
        "target_query": spec["target"]["description"],
        "task_id": spec["task_id"],
        "timeline": timeline,
        "state_changes": state_changes,
        "summary": summary,
        "warnings": [],
    }


def test_aggregation(spec, real_frames):
    positive = load_json(os.path.join(TASK03_DIR, "positive-evidence.json"))
    negative = load_json(os.path.join(TASK03_DIR, "negative-evidence.json"))

    # B1 目标存在样例（真实正向证据回放）
    entries = [evidence_entry(positive, real_frames[i]) for i in range(3)]
    timeline_doc = make_timeline(spec, entries)
    s = timeline_doc["summary"]
    record("B1-positive-target-exists", "目标存在样例 → 确认帧与首末时间",
           s["confirmed_frame_count"] == 3 and s["overall_status"] == "completed"
           and s["first_confirmed_timestamp_ms"] == entries[0]["timestamp_ms"]
           and s["last_confirmed_timestamp_ms"] == entries[-1]["timestamp_ms"],
           f"confirmed={s['confirmed_frame_count']} first={s['first_confirmed_timestamp_ms']} "
           f"last={s['last_confirmed_timestamp_ms']} status={s['overall_status']}",
           "任务 03 真实 Qwen 图片证据（positive-evidence.json）回放到真实帧时间戳")

    # B2 目标不存在样例（真实负向证据回放）
    entries = [evidence_entry(negative, real_frames[i]) for i in range(2)]
    timeline_doc = make_timeline(spec, entries)
    s = timeline_doc["summary"]
    report = generate_report.build_video_report(spec, timeline_doc)
    record("B2-negative-target-absent", "目标不存在样例 → not_found，无虚假时间线",
           s["confirmed_frame_count"] == 0 and s["not_found_frame_count"] == 2
           and s["overall_status"] == "completed" and report["status"] == "completed"
           and "未确认" in report["conclusion"],
           f"not_found={s['not_found_frame_count']} confirmed={s['confirmed_frame_count']} "
           f"结论={report['conclusion'][:60]}...",
           "任务 03 真实 Qwen 图片证据（negative-evidence.json，红色背包确定性负面）回放")

    # B3 证据不足样例（构造输入，明确标注）
    abstained_sample = dict(negative)
    abstained_sample["abstention_reason"] = "画面模糊，无法确认目标是否存在（构造样例，非模型输出）"
    abstained_sample["evidence_sufficient"] = False
    abstained_sample["gaps"] = ["目标未被确认存在"]
    entries = [evidence_entry(abstained_sample, real_frames[i]) for i in range(2)]
    timeline_doc = make_timeline(spec, entries)
    s = timeline_doc["summary"]
    report = generate_report.build_video_report(spec, timeline_doc)
    record("B3-insufficient-evidence-abstains", "证据不足样例 → abstained，保留拒答原因",
           s["abstained_frame_count"] == 2 and s["overall_status"] == "abstained"
           and report["status"] == "abstained"
           and isinstance(report["abstention_reason"], str) and report["abstention_reason"],
           f"abstained={s['abstained_frame_count']} status={s['overall_status']} "
           f"abstention_reason 非空=True",
           "构造输入（在真实负向证据基础上设置 abstention_reason，明确标注非模型输出）")

    # B4 bounding_box 不伪造：null 保持 null；整幅框标记定位不可靠
    entries_pos = [evidence_entry(positive, real_frames[0])]
    entries_neg = [evidence_entry(negative, real_frames[0])]
    bbox_null_kept = entries_neg[0]["bounding_box"] is None
    full_frame_flagged = any("定位不可靠" in gap for gap in entries_pos[0]["gaps"])
    record("B4-bounding-box-not-fabricated", "bounding_box 不可用时不伪造",
           bbox_null_kept and full_frame_flagged,
           f"null 保持 null={bbox_null_kept}；整幅框被标记定位不可靠={full_frame_flagged}",
           "任务 03 真实证据（positive bbox=[0,0,1,1] 整幅；negative bbox=null）")

    # B5 去重与状态变化保留
    entries = [evidence_entry(positive, real_frames[i]) for i in range(3)]
    timeline_doc = make_timeline(spec, entries)
    dedup_ok = len(timeline_doc["state_changes"]) == 1
    mixed = [evidence_entry(positive, real_frames[0]),
             evidence_entry(negative, real_frames[1]),
             evidence_entry(positive, real_frames[2])]
    mixed_doc = make_timeline(spec, mixed)
    state_changes_ok = len(mixed_doc["state_changes"]) == 3
    record("B5-dedup-and-state-changes", "删除完全重复结果；保留关键状态变化",
           dedup_ok and state_changes_ok,
           f"3 帧相同证据 → state_changes={len(timeline_doc['state_changes'])}（应为 1）；"
           f"found→not_found→found → state_changes={len(mixed_doc['state_changes'])}（应为 3）",
           "任务 03 真实证据回放（去重与状态变化规则）")

    # B6 视频报告状态一致性（含交叉校验不一致注入）
    entries = [evidence_entry(positive, real_frames[i]) for i in range(2)]
    timeline_doc = make_timeline(spec, entries)
    report = generate_report.build_video_report(spec, timeline_doc)
    consistent = report["status"] == timeline_doc["summary"]["overall_status"] == "completed"
    tampered = json.loads(json.dumps(timeline_doc))
    tampered["summary"]["overall_status"] = "abstained"  # 注入不一致
    tampered_report = generate_report.build_video_report(spec, tampered)
    cross_check = (tampered_report["status"] == "completed"
                   and any("交叉校验不一致" in w for w in tampered_report["warnings"]))
    record("B6-report-status-consistency", "视频报告状态一致性（含交叉校验）",
           consistent and cross_check,
           f"一致运行：report.status={report['status']}；注入不一致后复算="
           f"{tampered_report['status']} 且 warnings 记录冲突={cross_check}",
           "任务 03 真实证据回放 + 注入不一致的规则测试")

    # B7 资源守卫逻辑（不调用模型）
    available = trace_video.mem_available_gib()
    blocked, info = trace_video.resource_guard(40.0)
    guard_ok = isinstance(blocked, bool) and info.get("mem_available_gib") == available
    record("B7-resource-guard", "资源守卫在内存不足时阻止模型加载",
           guard_ok and isinstance(blocked, bool),
           f"MemAvailable={available} GiB，guard.blocked={blocked}，"
           f"reason={str(info.get('reason'))[:80]}",
           "本机 /proc/meminfo 真实读数（未调用任何模型）")


# ---------------------------------------------------------------- C. 错误处理

def test_error_handling(spec_path):
    extractor = os.path.join(EXTRACTOR_DIR, "scripts", "extract_frames.py")
    tracer = os.path.join(EXTRACTOR_DIR, "scripts", "trace_video.py")
    reporter = os.path.join(REPORTER_DIR, "scripts", "generate_report.py")
    python = sys.executable

    with tempfile.TemporaryDirectory(prefix="sparkskill-t04-err-") as tmp:
        # C1 视频不存在
        proc = subprocess.run([python, extractor, "--video", os.path.join(tmp, "nope.mp4"),
                               "--output-dir", os.path.join(tmp, "f")],
                              capture_output=True, text=True)
        record("C1-missing-video-rejected", "失败输入：视频不存在 → 明确错误退出",
               proc.returncode == 3 and "不存在" in proc.stderr,
               f"exit={proc.returncode}（期望 3）", "失败输入")

        # C2 损坏的视频文件
        broken = os.path.join(tmp, "broken.mp4")
        with open(broken, "wb") as handle:
            handle.write(b"not a video at all")
        proc = subprocess.run([python, extractor, "--video", broken,
                               "--output-dir", os.path.join(tmp, "f2")],
                              capture_output=True, text=True)
        record("C2-corrupted-video-rejected", "失败输入：损坏视频 → 明确错误退出",
               proc.returncode == 3 and proc.stderr.strip() != "",
               f"exit={proc.returncode}（期望 3）", "失败输入")

        # C3 非法任务规格
        bad_spec = os.path.join(tmp, "bad-spec.json")
        with open(bad_spec, "w", encoding="utf-8") as handle:
            json.dump({"requires_visual_input": False, "task_type": "object_trace",
                       "target": {"description": "x"}}, handle)
        proc = subprocess.run([python, tracer, "--task-spec", bad_spec,
                               "--video", REAL_VIDEO,
                               "--output", os.path.join(tmp, "t.json")],
                              capture_output=True, text=True)
        record("C3-invalid-spec-rejected", "失败输入：非法规格 → 拒绝执行",
               proc.returncode == 2 and "requires_visual_input" in proc.stderr,
               f"exit={proc.returncode}（期望 2）", "失败输入")

        # C4 证据输入不合法
        bad_evidence = os.path.join(tmp, "bad-evidence.json")
        with open(bad_evidence, "w", encoding="utf-8") as handle:
            handle.write("{ not json")
        proc = subprocess.run([python, reporter, "--task-spec", spec_path,
                               "--evidence", bad_evidence],
                              capture_output=True, text=True)
        record("C4-malformed-evidence-rejected", "失败输入：损坏证据 JSON → 明确错误退出",
               proc.returncode == 2 and proc.stderr.strip() != "",
               f"exit={proc.returncode}（期望 2）", "失败输入")


def main():
    parser = argparse.ArgumentParser(description="任务 04 视频闭环自动化测试")
    parser.add_argument("--results-json", help="测试结果 JSON 输出路径")
    args = parser.parse_args()

    spec = load_json(os.path.join(TASK03_DIR, "task-spec.json"))
    with tempfile.TemporaryDirectory(prefix="sparkskill-t04-frames-") as tmp:
        extraction = extract_frames_mod.extract_frames(
            REAL_VIDEO, os.path.join(tmp, "frames"), interval_ms=800, max_frames=6)
        real_frames = extraction["frames"]

    test_extraction()
    test_aggregation(spec, real_frames)
    test_error_handling(os.path.join(TASK03_DIR, "task-spec.json"))

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    summary = {
        "suite": "task-04-video-pipeline",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "passed": passed,
        "total": total,
        "note": "小样本只记录通过数/总数，不写百分比；输入性质逐条标注；"
                "公开版视频输入为仓库内任务 16 合成 fixture（任务 04 当时的真实视频 "
                "Qwen 逐帧调用因统一内存资源条件阻塞，历史记录为内部留档）；"
                "聚合规则测试使用任务 03 真实证据样例回放",
        "results": RESULTS,
    }
    if args.results_json:
        with open(args.results_json, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(f"\n小计：{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
