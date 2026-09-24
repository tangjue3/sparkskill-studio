#!/usr/bin/env python3
"""test_temporal_evidence.py — 任务 16 目标时序证据与粗到细自适应采样测试（SparkSkill Studio）

覆盖任务书第十六节要求的 24 项新测试（T1–T24），输入性质逐项标注：

  T1–T6   Schema/校验器：旧规格兼容、uniform 合法、adaptive 合法、未知策略拒绝、
          非法预算拒绝、负时间精度拒绝（规则测试，subprocess 校验器）；
  T7–T16  采样与预算：实际调用不超预算、重复时间戳不重复调用、时间戳严格递增、
          初始/细化可区分、状态变化左右边界、边界不确定宽度、预算耗尽停止、
          abstained/failed 不退化为 not_found、无状态变化不无意义细化、
          uniform 与 adaptive 相同分类规则（真实 fixture 视频抽取 + 脚本化构造证据回放，
          明确标注非模型输出；无任何真实 Qwen 调用）；
  T17–T19  报告：独立复算、上下游不一致 warning（构造注入）；
  T20–T21  多来源：source_id 与原时间戳保留、无跨视频身份断言；
  T22      资源守卫阻塞时零真实 Qwen 调用（真实视频抽取 + 高内存阈值，无模型调用）；
  T23      provenance 不含凭据；
  T24      technical fixture 与真实模型输出明确区分。

用法:
    python3 test_temporal_evidence.py [--results-json <path>]
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
COMPILER_DIR = os.path.join(PROJECT_ROOT, ".dsh", "skills", "task-to-skill-compiler")
REPORTER_DIR = os.path.join(PROJECT_ROOT, ".dsh", "skills", "evidence-report-generator")
TASK03_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-03")
SCHEMA_PATH = os.path.join(PROJECT_ROOT, "schemas", "visual-task-spec.schema.json")
FIXTURE_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
FIXTURE_VIDEOS = os.path.join(FIXTURE_DIR, "videos")

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

adaptive_sampler = load_module("adaptive_sampler",
                               os.path.join(EXTRACTOR_DIR, "scripts", "adaptive_sampler.py"))
trace_temporal = load_module("trace_temporal",
                             os.path.join(EXTRACTOR_DIR, "scripts", "trace_temporal.py"))
trace_video = load_module("trace_video",
                          os.path.join(EXTRACTOR_DIR, "scripts", "trace_video.py"))
extract_frames_mod = load_module("extract_frames",
                                 os.path.join(EXTRACTOR_DIR, "scripts", "extract_frames.py"))
generate_report = load_module("generate_report",
                              os.path.join(REPORTER_DIR, "scripts", "generate_report.py"))

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


def fixture_path(name):
    return os.path.join(FIXTURE_VIDEOS, name)


def fixture_ground_truth():
    return load_json(os.path.join(FIXTURE_DIR, "ground-truth.json"))


def state_at(segments, timestamp_ms):
    for segment in segments:
        if segment["start_ms"] <= timestamp_ms < segment["end_ms"]:
            return segment["state"]
    return segments[-1]["state"] if segments else "absent"


def make_scripted_analyzer(segments_by_video, fail_at=None, low_confidence_at=None):
    """脚本化构造证据分析器（规则测试专用）：按 fixture ground truth 时间轴生成
    确定的 frame 级证据。**这是构造结构化证据，不是模型输出**（evidence_nature
    由 trace_temporal 标记为 constructed_fixture_evidence，不计为 Qwen 调用）。

    - segments_by_video: {视频文件名主干: segments}（ground truth 来自冻结 fixture）
    - fail_at: {视频主干: [timestamp_ms,...]} 这些时间戳抛出异常 → 帧 failed
    - low_confidence_at: {视频主干: [timestamp_ms,...]} 这些时间戳 object_found=true
      但 confidence=0.2（低于默认阈值 0.5）→ low_confidence
    """
    fail_at = fail_at or {}
    low_confidence_at = low_confidence_at or {}

    def analyze(spec, frame):
        video_stem = None
        for stem in segments_by_video:
            if stem in os.path.basename(frame["frame_path"]):
                video_stem = stem
                break
        segments = segments_by_video.get(video_stem, [])
        timestamp_ms = frame["timestamp_ms"]
        if timestamp_ms in fail_at.get(video_stem, []):
            raise ValueError("构造的单帧失败（规则 fixture：模拟后端调用异常）")
        state = state_at(segments, timestamp_ms)
        low_confidence = timestamp_ms in low_confidence_at.get(video_stem, [])
        if state == "absent":
            return {
                "timestamp_ms": timestamp_ms,
                "frame_path": frame["frame_path"],
                "object_found": False,
                "description": "构造证据：画面中无红色正方形",
                "bounding_box": None,
                "bounding_box_raw": None,
                "bounding_box_source_format": None,
                "bounding_box_normalization_applied": False,
                "frame_width": None,
                "frame_height": None,
                "confidence": 0.9,
                "evidence_text": "构造证据（规则测试，非模型输出）",
                "abstention_reason": None,
                "frame_status": "analyzed",
                "evidence_sufficient": False,
                "gaps": ["目标未被确认存在"],
                "warnings": [],
            }
        if state == "present_low_contrast":
            return {
                "timestamp_ms": timestamp_ms,
                "frame_path": frame["frame_path"],
                "object_found": False,
                "description": "构造证据：低对比度区间，无法可靠确认",
                "bounding_box": None,
                "bounding_box_raw": None,
                "bounding_box_source_format": None,
                "bounding_box_normalization_applied": False,
                "frame_width": None,
                "frame_height": None,
                "confidence": 0.3,
                "evidence_text": "构造证据（规则测试，非模型输出）",
                "abstention_reason": "目标对比度过低，无法可靠确认（构造拒答）",
                "frame_status": "analyzed",
                "evidence_sufficient": False,
                "gaps": ["证据不足，无法可靠确认"],
                "warnings": [],
            }
        confidence = 0.2 if low_confidence else 0.95
        return {
            "timestamp_ms": timestamp_ms,
            "frame_path": frame["frame_path"],
            "object_found": True,
            "description": "构造证据：红色正方形出现",
            "bounding_box": [0.44, 0.39, 0.56, 0.61],
            "bounding_box_raw": None,
            "bounding_box_source_format": "normalized",
            "bounding_box_normalization_applied": False,
            "frame_width": None,
            "frame_height": None,
            "confidence": confidence,
            "evidence_text": "构造证据（规则测试，非模型输出）",
            "abstention_reason": None,
            "frame_status": "analyzed",
            "evidence_sufficient": confidence >= 0.5,
            "gaps": [] if confidence >= 0.5 else ["置信度低于阈值"],
            "warnings": [],
        }

    return analyze


def base_spec(video, sampling_strategy=None):
    spec = {
        "task_id": "task16-temporal-rule-test",
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_trace",
        "target": {"description": "红色正方形", "attributes": ["红色", "正方形"]},
        "source_media": video,
        "required_outputs": ["object_found", "description", "bounding_box",
                             "confidence", "evidence_text"],
        "constraints": {
            "abstain_if_insufficient_evidence": True,
            "forbidden_inferences": ["identity", "age", "nationality",
                                     "relationship", "intent"],
        },
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
    }
    if sampling_strategy is not None:
        spec["sampling_strategy"] = sampling_strategy
    return spec


def adaptive_block(**overrides):
    block = {
        "strategy": "adaptive_coarse_to_fine",
        "max_model_calls": 16,
        "initial_coverage_samples": 4,
        "target_boundary_precision_ms": 500,
        "max_refinement_rounds": 6,
    }
    block.update(overrides)
    return block


def run_validator(spec_path):
    return subprocess.run(
        [sys.executable, os.path.join(COMPILER_DIR, "scripts", "validate_task_spec.py"),
         "--schema", SCHEMA_PATH, "--input", spec_path],
        capture_output=True, text=True)


def write_spec(tmp, name, spec):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, ensure_ascii=False)
    return path


def run_temporal(spec, tmp, out_name, analyze, frames_name="frames",
                 allow_low_memory=True, **kwargs):
    out = os.path.join(tmp, out_name)
    doc = trace_temporal.trace_temporal(
        spec, out, allow_low_memory=allow_low_memory, analyze_fn=analyze,
        input_nature="technical_fixture",
        frames_dir=os.path.join(tmp, frames_name), **kwargs)
    return doc


# ---------------------------------------------------------------- T1–T6 Schema/校验器

def test_schema():
    gt = fixture_ground_truth()
    appear = fixture_path("fixture-appear-midway.mp4")
    with tempfile.TemporaryDirectory(prefix="sparkskill-t16-schema-") as tmp:
        # T1 旧 VisualTaskSpec 继续有效（无 sampling_strategy）
        proc = run_validator(os.path.join(TASK03_DIR, "task-spec.json"))
        record("T1-legacy-spec-still-valid", "旧 VisualTaskSpec（无采样策略）继续有效",
               proc.returncode == 0 and "RESULT: VALID" in proc.stdout,
               f"exit={proc.returncode}（任务 03 真实规格原样校验）",
               "任务 03 真实产物（artifacts/task-03/task-spec.json）")

        # T2 uniform 策略合法
        path = write_spec(tmp, "uniform.json",
                          base_spec(appear, {"strategy": "uniform", "max_model_calls": 12}))
        proc = run_validator(path)
        record("T2-uniform-strategy-valid", "uniform 采样策略合法",
               proc.returncode == 0 and "RESULT: VALID" in proc.stdout,
               f"exit={proc.returncode}（strategy=uniform + max_model_calls=12）",
               "构造输入（合法 uniform 策略规格）")

        # T3 adaptive 策略合法
        path = write_spec(tmp, "adaptive.json", base_spec(appear, adaptive_block()))
        proc = run_validator(path)
        record("T3-adaptive-strategy-valid", "adaptive_coarse_to_fine 策略合法",
               proc.returncode == 0 and "RESULT: VALID" in proc.stdout,
               f"exit={proc.returncode}（预算/初始覆盖/精度/轮数/触发器齐全）",
               "构造输入（合法 adaptive 策略规格）")

        # T4 未知策略拒绝
        path = write_spec(tmp, "unknown.json",
                          base_spec(appear, {"strategy": "magic_sampling"}))
        proc = run_validator(path)
        record("T4-unknown-strategy-rejected", "未知采样策略被拒绝",
               proc.returncode == 1 and "strategy" in proc.stderr,
               f"exit={proc.returncode}（期望 1）",
               "构造输入（strategy=magic_sampling）")

        # T5 非法调用预算拒绝（0 / 负数 / 非整数）
        rejections = []
        for name, budget in (("zero", 0), ("negative", -3),
                             ("non-integer", 12.5), ("string", "12")):
            path = write_spec(tmp, f"budget-{name}.json",
                              base_spec(appear, adaptive_block(max_model_calls=budget)))
            proc = run_validator(path)
            rejections.append((name, proc.returncode == 1))
        record("T5-illegal-budget-rejected", "非法调用预算被拒绝（0/负数/非整数）",
               all(ok for _, ok in rejections),
               "；".join(f"{name}: exit={'1' if ok else '0(未拒绝)'}"
                         for (name, ok) in rejections),
               "构造输入（max_model_calls=0/-3/12.5/'12'）")

        # T6 负/零时间精度拒绝
        path = write_spec(tmp, "neg-precision.json",
                          base_spec(appear, adaptive_block(target_boundary_precision_ms=-500)))
        proc_neg = run_validator(path)
        path = write_spec(tmp, "zero-precision.json",
                          base_spec(appear, adaptive_block(target_boundary_precision_ms=0)))
        proc_zero = run_validator(path)
        record("T6-negative-precision-rejected", "负/零时间边界精度被拒绝",
               proc_neg.returncode == 1 and proc_zero.returncode == 1,
               f"负精度 exit={proc_neg.returncode}；零精度 exit={proc_zero.returncode}（期望均 1）",
               "构造输入（target_boundary_precision_ms=-500 / 0）")

        # 附带：uniform + 细化参数（不支持组合）拒绝；adaptive 缺必填拒绝
        path = write_spec(tmp, "uniform-plus-refine.json",
                          base_spec(appear, {"strategy": "uniform", "max_model_calls": 12,
                                             "initial_coverage_samples": 4}))
        proc = run_validator(path)
        record("T6b-uniform-refinement-combo-rejected",
               "uniform + 细化参数（不支持组合）被拒绝",
               proc.returncode == 1 and "不支持组合" in proc.stderr,
               f"exit={proc.returncode}（期望 1）",
               "构造输入（uniform 策略带 initial_coverage_samples）")
        path = write_spec(tmp, "adaptive-missing.json",
                          base_spec(appear, {"strategy": "adaptive_coarse_to_fine",
                                             "initial_coverage_samples": 4,
                                             "target_boundary_precision_ms": 500,
                                             "max_refinement_rounds": 4}))
        proc = run_validator(path)
        record("T6c-adaptive-missing-required-rejected",
               "adaptive 缺少 max_model_calls（必填）被拒绝",
               proc.returncode == 1 and "max_model_calls" in proc.stderr,
               f"exit={proc.returncode}（期望 1）",
               "构造输入（adaptive 缺硬预算字段）")
    del gt


# ---------------------------------------------------------------- T7–T16 采样与预算

def test_sampling_and_budget():
    gt = fixture_ground_truth()
    appear_segments = gt["fixtures"]["appear-midway"]["segments"]
    reappear_segments = gt["fixtures"]["reappear"]["segments"]
    abstain_segments = gt["fixtures"]["abstain-zone"]["segments"]
    throughout_segments = gt["fixtures"]["present-throughout"]["segments"]

    with tempfile.TemporaryDirectory(prefix="sparkskill-t16-run-") as tmp:
        # T7 实际调用数不超过预算（adaptive 预算 8 + uniform 预算 5）
        doc = run_temporal(base_spec(fixture_path("fixture-reappear.mp4"),
                                     adaptive_block(max_model_calls=8)),
                           tmp, "t7-adaptive.json",
                           make_scripted_analyzer({"fixture-reappear": reappear_segments}))
        adaptive_actual = doc["sampling_provenance"]["actual_model_calls"]
        doc_u = run_temporal(base_spec(fixture_path("fixture-reappear.mp4"),
                                       {"strategy": "uniform", "max_model_calls": 5}),
                             tmp, "t7-uniform.json",
                             make_scripted_analyzer({"fixture-reappear": reappear_segments}),
                             frames_name="frames-u")
        uniform_actual = doc_u["sampling_provenance"]["actual_model_calls"]
        record("T7-actual-calls-within-budget", "实际调用数不超过硬预算",
               adaptive_actual <= 8 and uniform_actual <= 5,
               f"adaptive 实际={adaptive_actual}≤8；uniform 实际={uniform_actual}≤5",
               "构造证据回放（真实 fixture 视频抽取 + 脚本化证据，非模型输出）")

        # T8 重复时间戳不重复调用（极小目标精度：细化收敛到帧间隔内，
        # 中点命中已有帧 → skipped_duplicate，不得第二次调用模型）
        doc = run_temporal(base_spec(fixture_path("fixture-appear-midway.mp4"),
                                     adaptive_block(max_model_calls=24,
                                                    target_boundary_precision_ms=1,
                                                    max_refinement_rounds=12)),
                           tmp, "t8.json",
                           make_scripted_analyzer({"fixture-appear-midway": appear_segments}),
                           frames_name="frames-8")
        provenance = doc["sampling_provenance"]
        analyzed = provenance["analyzed_timestamps"]
        record("T8-duplicate-timestamp-no-recall", "重复时间戳不重复调用模型",
               len(analyzed) == len(set(analyzed))
               and provenance["actual_model_calls"] == len(analyzed)
               and len(provenance["skipped_duplicate_timestamps"]) > 0
               and "refinement_converged_no_new_sample" in provenance["stop_reasons"],
               f"实际调用={provenance['actual_model_calls']}，唯一时间戳={len(set(analyzed))}，"
               f"跳过重复={len(provenance['skipped_duplicate_timestamps'])}，"
               f"停止原因={provenance['stop_reasons']}",
               "构造证据回放（目标精度 1ms 迫使中点命中已有帧）")

        # T9 时间戳严格递增
        record("T9-timestamps-strictly-increasing", "时间戳严格递增",
               all(b > a for a, b in zip(analyzed, analyzed[1:])),
               f"时间戳={analyzed}",
               "构造证据回放（T8 运行产物）")

        # T10 初始采样与细化采样可区分
        phases = [d["phase"] for d in provenance["decisions"]]
        fresh = [d for d in provenance["decisions"] if d["cache_status"] == "fresh_call"]
        record("T10-initial-vs-refinement-distinguishable", "初始采样与细化采样可区分",
               set(phases) == {"initial_coverage", "refinement"}
               and provenance["initial_samples"] == len(
                   [d for d in fresh if d["phase"] == "initial_coverage"])
               and provenance["refinement_samples"] == len(
                   [d for d in fresh if d["phase"] == "refinement"])
               and all(d["refinement_round"] is None for d in fresh
                       if d["phase"] == "initial_coverage")
               and all(d["refinement_round"] is not None for d in fresh
                       if d["phase"] == "refinement"),
               f"初始={provenance['initial_samples']}，细化={provenance['refinement_samples']}，"
               f"轮数={provenance['refinement_rounds']}",
               "构造证据回放（T8 运行产物）")

        # T11 状态变化生成左右边界
        doc = run_temporal(base_spec(fixture_path("fixture-appear-midway.mp4"),
                                     adaptive_block(max_model_calls=16)),
                           tmp, "t11.json",
                           make_scripted_analyzer({"fixture-appear-midway": appear_segments}),
                           frames_name="frames-11")
        transitions = doc["temporal_evidence"]["state_transitions"]
        ok = (len(transitions) == 1
              and transitions[0]["from_class"] == "not_found"
              and transitions[0]["to_class"] == "confirmed"
              and transitions[0]["left_ms"] < 3200 < transitions[0]["right_ms"])
        record("T11-state-change-boundaries", "状态变化生成左右时间边界",
               ok,
               f"转换={[(t['left_ms'], t['right_ms'], t['from_class'], t['to_class']) for t in transitions]}"
               "（ground truth 边界 3200 ms 落在区间内）",
               "构造证据回放（fixture-appear-midway，ground truth 来自冻结 fixture）")

        # T12 边界不确定宽度正确（width == right-left，且细化后 ≤ 目标精度）
        widths_ok = all(abs(t["uncertainty_width_ms"]
                            - round(t["right_ms"] - t["left_ms"], 3)) < 1e-9
                        for t in transitions)
        boundary = doc["temporal_evidence"]["boundary_uncertainty"]
        record("T12-boundary-uncertainty-width-correct", "边界不确定宽度正确",
               widths_ok and boundary["target_precision_reached"] is True
               and boundary["max_ms"] <= 500,
               f"宽度={[t['uncertainty_width_ms'] for t in transitions]}，"
               f"max={boundary['max_ms']}，目标={boundary['target_ms']}，"
               f"达到={boundary['target_precision_reached']}",
               "构造证据回放（T11 运行产物）")

        # T13 预算耗尽时停止（reappear 3 个转换，预算 5）
        doc = run_temporal(base_spec(fixture_path("fixture-reappear.mp4"),
                                     adaptive_block(max_model_calls=5)),
                           tmp, "t13.json",
                           make_scripted_analyzer({"fixture-reappear": reappear_segments}),
                           frames_name="frames-13")
        provenance = doc["sampling_provenance"]
        temporal = doc["temporal_evidence"]
        record("T13-budget-exhaustion-stops-refinement", "预算耗尽时停止细化并如实报告",
               provenance["actual_model_calls"] == 5
               and provenance["budget_exhausted"] is True
               and "budget_exhausted" in provenance["stop_reasons"]
               and temporal["stopped_by_budget"] is True
               and temporal["state_transition_count"] >= 1,
               f"实际={provenance['actual_model_calls']}，耗尽={provenance['budget_exhausted']}，"
               f"停止原因={provenance['stop_reasons']}，未解析转换数="
               f"{temporal['state_transition_count']}",
               "构造证据回放（fixture-reappear，预算 5 < 所需细化）")

        # T14 abstained 不退化为 not_found（abstain-zone fixture；初始覆盖 6 个采样点
        # 确保低对比度区间 [3000,5000) 被采到）
        doc = run_temporal(base_spec(fixture_path("fixture-abstain-zone.mp4"),
                                     adaptive_block(max_model_calls=24,
                                                    initial_coverage_samples=6,
                                                    max_refinement_rounds=8)),
                           tmp, "t14.json",
                           make_scripted_analyzer({"fixture-abstain-zone": abstain_segments}),
                           frames_name="frames-14")
        counts = doc["temporal_evidence"]["class_counts"]
        abstained_entries = [e for e in doc["timeline"]
                             if e.get("abstention_reason")]
        record("T14-abstained-not-collapsed-to-not-found", "abstained 不退化为 not_found",
               counts["abstained"] == len(abstained_entries) and counts["abstained"] > 0
               and counts["not_found"] == 0
               and all(e["frame_status"] == "analyzed" for e in abstained_entries)
               and len(doc["temporal_evidence"]["unconfirmed_intervals"]) > 0,
               f"abstained={counts['abstained']}，not_found={counts['not_found']}，"
               f"无法确认片段={len(doc['temporal_evidence']['unconfirmed_intervals'])}",
               "构造证据回放（fixture-abstain-zone，低对比度区间构造为 abstained）")

        # T15 failed 不退化为 not_found（单帧失败注入）
        doc = run_temporal(base_spec(fixture_path("fixture-appear-midway.mp4"),
                                     adaptive_block(max_model_calls=16)),
                           tmp, "t15.json",
                           make_scripted_analyzer({"fixture-appear-midway": appear_segments},
                                                  fail_at={"fixture-appear-midway": [3000.0]}),
                           frames_name="frames-15")
        counts = doc["temporal_evidence"]["class_counts"]
        failed_entries = [e for e in doc["timeline"] if e["frame_status"] == "failed"]
        analyzed = [e for e in doc["timeline"] if e["frame_status"] == "analyzed"]
        expected_not_found = len([e for e in analyzed
                                  if state_at(appear_segments, e["timestamp_ms"]) == "absent"])
        expected_confirmed = len([e for e in analyzed
                                  if state_at(appear_segments, e["timestamp_ms"]) == "present"])
        record("T15-failed-not-collapsed-to-not-found", "failed 不退化为 not_found",
               counts["failed"] == 1 and len(failed_entries) == 1
               and failed_entries[0]["evidence_nature"] == "backend_not_called"
               and "帧分析失败" in (failed_entries[0].get("abstention_reason") or "")
               and counts["not_found"] == expected_not_found
               and counts["confirmed"] == expected_confirmed
               and any("未获得视觉证据" in w for w in doc["warnings"]),
               f"failed={counts['failed']}，not_found={counts['not_found']}"
               f"（ground truth 复算={expected_not_found}），"
               f"confirmed={counts['confirmed']}（复算={expected_confirmed}），"
               f"warnings 含失败记录={any('未获得视觉证据' in w for w in doc['warnings'])}",
               "构造证据回放（3000ms 单帧注入后端异常，规则级 fixture）")

        # T16 无状态变化时不进行无意义细化（present-throughout）
        doc = run_temporal(base_spec(fixture_path("fixture-present-throughout.mp4"),
                                     adaptive_block(max_model_calls=16)),
                           tmp, "t16.json",
                           make_scripted_analyzer(
                               {"fixture-present-throughout": throughout_segments}),
                           frames_name="frames-16")
        provenance = doc["sampling_provenance"]
        record("T16-no-pointless-refinement", "没有状态变化时不进行无意义细化",
               provenance["refinement_rounds"] == 0
               and provenance["refinement_samples"] == 0
               and provenance["actual_model_calls"] == 4
               and provenance["stop_reasons"] == ["no_refinable_interval"]
               and doc["temporal_evidence"]["state_transition_count"] == 0,
               f"细化轮数={provenance['refinement_rounds']}，实际调用="
               f"{provenance['actual_model_calls']}（=初始覆盖 4），"
               f"停止原因={provenance['stop_reasons']}",
               "构造证据回放（fixture-present-throughout，全程 confirmed）")


# ---------------------------------------------------------------- T17 相同分类规则

def test_classification_rules_identical():
    entries = [
        {"timestamp_ms": 0, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
        {"timestamp_ms": 1, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": False, "abstention_reason": None},
        {"timestamp_ms": 2, "frame_status": "analyzed", "object_found": False,
         "evidence_sufficient": False, "abstention_reason": None},
        {"timestamp_ms": 3, "frame_status": "analyzed", "object_found": False,
         "evidence_sufficient": False, "abstention_reason": "无法确认"},
        {"timestamp_ms": 4, "frame_status": "failed", "object_found": False,
         "evidence_sufficient": False, "abstention_reason": "后端失败"},
    ]
    extractor_classes = [trace_video.frame_class(e) for e in entries]
    sampler_classes = [adaptive_sampler.classify_entry(e) for e in entries]
    reporter_classes = [generate_report.classify_frame(e) for e in entries]
    expected = ["confirmed", "low_confidence", "not_found", "abstained", "failed"]
    # uniform 初始覆盖规划公式与 extract_frames 的 uniform 分支一致
    grid_a = adaptive_sampler.uniform_grid(0.0, 8000.0, 6)
    grid_b = extract_frames_mod.plan_sample_times(8000.0, None, 6, 0, None)
    record("T17-same-classification-rules", "uniform 与 adaptive 使用相同分类规则",
           extractor_classes == sampler_classes == reporter_classes == expected
           and grid_a == grid_b,
           f"extractor={extractor_classes}；sampler={sampler_classes}；"
           f"reporter={reporter_classes}；uniform 公式一致={grid_a == grid_b}（{grid_a}）",
           "构造输入（5 类帧状态矩阵 + 规划公式比对，非模型输出）")


# ---------------------------------------------------------------- T18–T19 报告复算

def test_report_recompute():
    gt = fixture_ground_truth()
    appear_segments = gt["fixtures"]["appear-midway"]["segments"]
    with tempfile.TemporaryDirectory(prefix="sparkskill-t16-report-") as tmp:
        doc = run_temporal(base_spec(fixture_path("fixture-appear-midway.mp4"),
                                     adaptive_block(max_model_calls=16)),
                           tmp, "t18.json",
                           make_scripted_analyzer({"fixture-appear-midway": appear_segments}),
                           frames_name="frames-18")
        spec = base_spec(fixture_path("fixture-appear-midway.mp4"),
                         adaptive_block(max_model_calls=16))
        report = generate_report.build_temporal_report(spec, doc)

        # 独立复算：报告 summary 与按 timeline 手工复算一致
        entries = sorted(doc["timeline"], key=lambda e: e["timestamp_ms"])
        classes = [generate_report.classify_frame(e) for e in entries]
        confirmed = [e for e, c in zip(entries, classes) if c == "confirmed"]
        recomputed_ok = (
            report["summary"]["confirmed_sample_count"] == len(confirmed)
            and report["summary"]["first_confirmed_observed_ms"]
            == confirmed[0]["timestamp_ms"]
            and report["summary"]["last_confirmed_observed_ms"]
            == confirmed[-1]["timestamp_ms"]
            and report["summary"]["class_counts"]["not_found"] == classes.count("not_found")
            and report["status"] == "completed")
        record("T18-report-independent-recompute", "报告引擎独立复算时序证据",
               recomputed_ok,
               f"报告 confirmed={report['summary']['confirmed_sample_count']}，"
               f"首/末确认={report['summary']['first_confirmed_observed_ms']}/"
               f"{report['summary']['last_confirmed_observed_ms']}",
               "构造证据回放（报告复算与手工复算比对）")

        # T19 上下游不一致产生 warning（向上游 temporal_evidence 注入错误首确认时间）
        tampered = json.loads(json.dumps(doc))
        tampered["temporal_evidence"]["first_confirmed_observed_ms"] = -999
        tampered["temporal_evidence"]["state_transition_count"] = 42
        report_t = generate_report.build_temporal_report(spec, tampered)
        mismatch_warned = any("交叉校验不一致" in w for w in report_t["warnings"])
        recompute_wins = (report_t["summary"]["first_confirmed_observed_ms"]
                          == report["summary"]["first_confirmed_observed_ms"])
        record("T19-upstream-mismatch-warns", "上下游不一致产生 warning 且以复算为准",
               mismatch_warned and recompute_wins,
               f"warnings 含“交叉校验不一致”={mismatch_warned}；复算首确认="
               f"{report_t['summary']['first_confirmed_observed_ms']}（未被上游 -999 污染）",
               "构造输入（注入错误上游摘要；复算纠正是规则行为）")

        # T19b 预算越界也记 warning（上游谎报未超预算但实际超出）
        over = json.loads(json.dumps(doc))
        over["sampling_provenance"]["actual_model_calls"] = 999
        report_o = generate_report.build_temporal_report(spec, over)
        record("T19b-budget-overrun-warns", "实际调用超过配置预算时报告 warning",
               any("调用预算异常" in w or "交叉校验不一致" in w
                   for w in report_o["warnings"]),
               f"warnings={[w for w in report_o['warnings'] if '预算' in w or '交叉' in w]}",
               "构造输入（注入超预算计数）")


# ---------------------------------------------------------------- T20–T21 多来源

def test_multi_source():
    gt = fixture_ground_truth()
    appear_segments = gt["fixtures"]["appear-midway"]["segments"]
    disappear_segments = gt["fixtures"]["disappear-midway"]["segments"]
    spec = {
        "task_id": "task16-temporal-multi",
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_trace",
        "target": {"description": "红色正方形", "attributes": ["红色", "正方形"]},
        "source_media": [
            {"source_id": "video-a", "path": fixture_path("fixture-appear-midway.mp4"),
             "location": "scene-a", "time_offset_ms": 0},
            {"source_id": "video-b", "path": fixture_path("fixture-disappear-midway.mp4"),
             "location": "scene-b", "time_offset_ms": 5000},
        ],
        "required_outputs": ["object_found", "description", "bounding_box",
                             "confidence", "evidence_text"],
        "constraints": {
            "abstain_if_insufficient_evidence": True,
            "forbidden_inferences": ["identity", "age", "nationality",
                                     "relationship", "intent"],
        },
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
        "sampling_strategy": adaptive_block(max_model_calls=24),
    }
    analyze = make_scripted_analyzer({
        "fixture-appear-midway": appear_segments,
        "fixture-disappear-midway": disappear_segments,
    })
    with tempfile.TemporaryDirectory(prefix="sparkskill-t16-multi-") as tmp:
        out = os.path.join(tmp, "multi-temporal.json")
        doc = trace_temporal.trace_temporal(
            spec, out, allow_low_memory=True, analyze_fn=analyze,
            input_nature="technical_fixture")
        entries = doc["global_timeline"]
        ids = {e["source_id"] for e in entries}
        original_ok = all(0 <= e["timestamp_ms"] < 8000 for e in entries)
        offset_ok = all(
            abs(e["global_timestamp_ms"] - (e["timestamp_ms"] + e["source_time_offset_ms"])) < 1e-9
            for e in entries)
        sorted_ok = all(a["global_timestamp_ms"] <= b["global_timestamp_ms"]
                        for a, b in zip(entries, entries[1:]))
        record("T20-multi-source-ids-and-timestamps",
               "多来源保持 source_id 和原视频时间戳",
               ids == {"video-a", "video-b"} and original_ok and offset_ok and sorted_ok
               and len(entries) > 0,
               f"来源={sorted(ids)}，原时间戳范围保持={original_ok}，"
               f"global=local+offset={offset_ok}，排序非降={sorted_ok}，条目数={len(entries)}",
               "构造证据回放（两段 fixture + time_offset_ms=5000，非模型输出）")

        report = generate_report.build_temporal_multi_report(spec, doc)
        conclusion = report["conclusion"]
        forbidden_hits = [p for p in FORBIDDEN_PHRASINGS if p in conclusion]
        limitations = doc.get("semantic_limitations") or {}
        record("T21-no-cross-video-identity-assertion", "不产生跨视频身份断言",
               not forbidden_hits
               and limitations.get("cross_video_identity_asserted") is False
               and "matched target query" in conclusion
               and "confirmed in source video-a" in conclusion
               and "confirmed in source video-b" in conclusion
               and "不是跨摄像头身份追踪" in conclusion,
               f"禁用措辞命中={forbidden_hits}；cross_video_identity_asserted="
               f"{limitations.get('cross_video_identity_asserted')}；允许措辞齐全=True",
               "构造证据回放（多来源报告结论扫描）")


# ---------------------------------------------------------------- T22 资源守卫

def test_resource_guard_zero_calls():
    with tempfile.TemporaryDirectory(prefix="sparkskill-t16-guard-") as tmp:
        doc = run_temporal(base_spec(fixture_path("fixture-appear-midway.mp4"),
                                     adaptive_block(max_model_calls=16)),
                           tmp, "t22.json",
                           make_scripted_analyzer({}),
                           frames_name="frames-22",
                           allow_low_memory=False,
                           min_available_gib=10 ** 9)
        provenance = doc["sampling_provenance"]
        entries = doc["timeline"]
        record("T22-resource-guard-zero-qwen-calls", "资源守卫阻塞时零真实 Qwen 调用",
               provenance["actual_model_calls"] == 0
               and provenance["budget_exhausted"] is False
               and len(entries) > 0
               and all(e["frame_status"] == "failed" for e in entries)
               and all(e["evidence_nature"] == "backend_not_called" for e in entries)
               and doc["backend"]["resource_blocked"] is True
               and doc["evidence_nature"] == "resource_blocked",
               f"实际调用={provenance['actual_model_calls']}，全部帧 failed="
               f"{all(e['frame_status'] == 'failed' for e in entries)}，"
               f"资源阻塞={doc['backend']['resource_blocked']}",
               "真实 fixture 视频抽取 + 资源守卫阈值 1e9 GiB（未调用任何模型）")


# ---------------------------------------------------------------- T23 provenance 安全

def test_provenance_no_credentials():
    gt = fixture_ground_truth()
    appear_segments = gt["fixtures"]["appear-midway"]["segments"]
    with tempfile.TemporaryDirectory(prefix="sparkskill-t16-sec-") as tmp:
        doc = run_temporal(base_spec(fixture_path("fixture-appear-midway.mp4"),
                                     adaptive_block(max_model_calls=16)),
                           tmp, "t23.json",
                           make_scripted_analyzer({"fixture-appear-midway": appear_segments}),
                           frames_name="frames-23")
        hits = adaptive_sampler.provenance_free_of_credentials(doc["sampling_provenance"])
        text = json.dumps(doc, ensure_ascii=False)
        # 精确凭据标记：sk- 只匹配“长令牌”样式（sk- 后跟 16 位以上字母数字），
        # 避免把任务名 task-16 之类的普通子串误报为凭据
        credential_markers = [m for m in ("api_key", "bearer ", "password",
                                          "token=", "-----begin")
                              if m in text.lower()]
        if __import__("re").search(r"sk-[A-Za-z0-9]{16,}", text):
            credential_markers.append("sk-<long-token>")
        record("T23-provenance-no-credentials", "采样 provenance 不含凭据",
               not hits and not credential_markers,
               f"provenance 凭据扫描命中={hits}；整文档凭据标记命中={credential_markers}",
               "构造证据回放（T11 同配置运行产物 + 全文扫描）")


# ---------------------------------------------------------------- T24 fixture 区分

def test_fixture_distinction():
    gt = fixture_ground_truth()
    appear_segments = gt["fixtures"]["appear-midway"]["segments"]
    with tempfile.TemporaryDirectory(prefix="sparkskill-t16-nature-") as tmp:
        doc = run_temporal(base_spec(fixture_path("fixture-appear-midway.mp4"),
                                     adaptive_block(max_model_calls=16)),
                           tmp, "t24.json",
                           make_scripted_analyzer({"fixture-appear-midway": appear_segments}),
                           frames_name="frames-24")
        spec = base_spec(fixture_path("fixture-appear-midway.mp4"),
                         adaptive_block(max_model_calls=16))
        report = generate_report.build_temporal_report(spec, doc)
        record("T24-fixture-vs-model-output-distinguished",
               "technical fixture 与真实模型输出明确区分",
               doc["input_nature"] == "technical_fixture"
               and doc["evidence_nature"] == "constructed_fixture_evidence"
               and all(e["evidence_nature"] == "constructed_fixture_evidence"
                       for e in doc["timeline"])
               and report["input_nature"] == "technical_fixture"
               and report["evidence_nature"] == "constructed_fixture_evidence"
               and "technical_fixture" in json.dumps(report, ensure_ascii=False),
               f"doc.evidence_nature={doc['evidence_nature']}，"
               f"report.input_nature={report['input_nature']}（构造证据不计为 Qwen 调用）",
               "构造证据回放（脚本化证据 → evidence_nature 标记 → 报告透传）")


def main():
    parser = argparse.ArgumentParser(description="任务 16 时序证据与自适应采样测试")
    parser.add_argument("--results-json", default=None, help="测试结果 JSON 输出路径")
    args = parser.parse_args()

    test_schema()
    test_sampling_and_budget()
    test_classification_rules_identical()
    test_report_recompute()
    test_multi_source()
    test_resource_guard_zero_calls()
    test_provenance_no_credentials()
    test_fixture_distinction()

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    print(f"\n小计：{passed}/{total} 通过"
          f"（输入性质：构造证据回放/规则测试/真实 fixture 视频抽取，无真实 Qwen 调用）")
    if args.results_json:
        payload = {
            "suite": "task-16-temporal-evidence-adaptive-sampling",
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).isoformat(),
            "passed": passed,
            "total": total,
            "all_passed": passed == total,
            "no_real_model_calls": True,
            "results": RESULTS,
        }
        with open(args.results_json, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        print(f"结果已写入 {args.results_json}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
