#!/usr/bin/env python3
"""test_task18_coverage_sampling.py — 任务 18 coverage_aware_adaptive 测试
（SparkSkill Studio；35 项，对应任务书第十节要求的覆盖清单）

覆盖（C01–C35）：
  C01–C06   Schema/校验器：旧规格兼容、旧策略行为不变、新策略合法、缺失必填、
             非法预算/间隔/轮次/精度、coverage 与 refinement 不突破总预算；
  C07–C14   采样与预算行为：无状态变化仍覆盖探索、状态变化后边界细化、覆盖与细化
             竞争预算、预算在覆盖/细化阶段耗尽、重复时间戳跳过、缓存复用账本、
             最大相邻间隔可复算；
  C15–C20   场景行为：网格间短事件、网格间短 uncertain、相位移动短事件、多个短事件、
             全程 confirmed、全程 not_found；
  C21–C23   五类分支与 uncertain 评分：failed/abstained/low_confidence、触达 uncertain
             但过度断言、未触达 uncertain；
  C24–C29   安全与 provenance：Ground Truth 不进入采样决策、输入只读、输出无凭据/
             敏感路径、单来源 provenance 自洽、多来源预算与时间戳、资源守卫零调用；
  C30–C34   verdict 纪律：公平门失败 INVALID_COMPARISON、省调用但增漏检 TRADEOFF、
             覆盖更好但 overclaim 增 TRADEOFF、无实质改进 NO_IMPROVEMENT、严格条件
             IMPROVEMENT；
  C35       预注册文件与 fixture 哈希和阶段 A 提交一致。

输入性质逐项标注；构造证据回放明确标记 constructed_fixture_evidence，不计为 Qwen
调用；除 C30（复用 deterministic replay 已存产物做适配层端到端核验）外无任何真实
模型调用。

用法:
    python3 test_task18_coverage_sampling.py [--results-json <path>]
退出码: 0 = 全部通过; 1 = 存在失败项
"""
import argparse
import hashlib
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
TASK16_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
TASK18_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "fixtures")
TASK18_CONTRACTS = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "contracts")
TASK18_PREREG = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "preregistration")
ADAPTER = os.path.join(PROJECT_ROOT, "scripts", "task18_scorer_adapter.py")
SCORER = os.path.join(PROJECT_ROOT, "scripts", "score_temporal_ground_truth.py")

FORBIDDEN_PHRASINGS = [
    "same physical instance", "moved from A to B", "carried by the same person",
    "entered another camera", "identity matched",
]
CREDENTIAL_MARKERS = ("api_key", "bearer ", "password", "token=", "-----begin")


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
generate_report = load_module("generate_report",
                              os.path.join(REPORTER_DIR, "scripts", "generate_report.py"))
frozen_scorer = load_module("score_temporal_ground_truth", SCORER)
# 适配层同款内存扩展（测试内直接复用冻结评分函数；不修改文件）
frozen_scorer.STRATEGIES = tuple(frozen_scorer.STRATEGIES) + ("coverage_aware_adaptive",)

RESULTS = []


def record(test_id, name, passed, detail, input_nature):
    RESULTS.append({"id": test_id, "name": name, "passed": bool(passed),
                    "detail": detail, "input_nature": input_nature})
    print(f"[{'PASS' if passed else 'FAIL'}] {test_id} — {name}: {detail}")


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def t16_video(name):
    return os.path.join(TASK16_FIXTURES, "videos", name)


def t18_video(name):
    return os.path.join(TASK18_FIXTURES, "videos", name)


def t16_gt():
    return load_json(os.path.join(TASK16_FIXTURES, "ground-truth.json"))


def t18_gt():
    return load_json(os.path.join(TASK18_FIXTURES, "ground-truth.json"))


def state_at(segments, timestamp_ms):
    for segment in segments:
        if segment["start_ms"] <= timestamp_ms < segment["end_ms"]:
            return segment["state"]
    return segments[-1]["state"] if segments else "absent"


def make_scripted_analyzer(segments_by_video, fail_at=None, low_confidence_at=None,
                           overclaim_uncertain=False):
    """构造证据分析器（规则测试专用）：按冻结 GT 时间轴生成确定帧级证据。

    evidence_nature 由 trace_temporal 标记为 constructed_fixture_evidence，
    不计为 Qwen 调用。overclaim_uncertain=True 时在低对比度区间返回确定性
    负面（模拟任务 16 记录过的真实 Qwen 过度断言行为）。
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
        if state == "present_low_contrast":
            if overclaim_uncertain:
                # 过度断言：确定性负面（object_found=false 且无 abstention_reason）
                return {
                    "timestamp_ms": timestamp_ms, "frame_path": frame["frame_path"],
                    "object_found": False, "description": "构造证据：确定性负面（过度断言）",
                    "bounding_box": None, "bounding_box_raw": None,
                    "bounding_box_source_format": None,
                    "bounding_box_normalization_applied": False,
                    "frame_width": None, "frame_height": None, "confidence": 0.9,
                    "evidence_text": "构造证据（规则测试，非模型输出）",
                    "abstention_reason": None, "frame_status": "analyzed",
                    "evidence_sufficient": False, "gaps": [], "warnings": [],
                }
            return {
                "timestamp_ms": timestamp_ms, "frame_path": frame["frame_path"],
                "object_found": False, "description": "构造证据：低对比度区间，无法可靠确认",
                "bounding_box": None, "bounding_box_raw": None,
                "bounding_box_source_format": None,
                "bounding_box_normalization_applied": False,
                "frame_width": None, "frame_height": None, "confidence": 0.3,
                "evidence_text": "构造证据（规则测试，非模型输出）",
                "abstention_reason": "目标对比度过低，无法可靠确认（构造拒答）",
                "frame_status": "analyzed", "evidence_sufficient": False,
                "gaps": ["证据不足，无法可靠确认"], "warnings": [],
            }
        if state == "absent":
            return {
                "timestamp_ms": timestamp_ms, "frame_path": frame["frame_path"],
                "object_found": False, "description": "构造证据：画面中无红色正方形",
                "bounding_box": None, "bounding_box_raw": None,
                "bounding_box_source_format": None,
                "bounding_box_normalization_applied": False,
                "frame_width": None, "frame_height": None, "confidence": 0.9,
                "evidence_text": "构造证据（规则测试，非模型输出）",
                "abstention_reason": None, "frame_status": "analyzed",
                "evidence_sufficient": False, "gaps": ["目标未被确认存在"],
                "warnings": [],
            }
        confidence = 0.2 if low_confidence else 0.95
        return {
            "timestamp_ms": timestamp_ms, "frame_path": frame["frame_path"],
            "object_found": True, "description": "构造证据：红色正方形出现",
            "bounding_box": [0.44, 0.39, 0.56, 0.61], "bounding_box_raw": None,
            "bounding_box_source_format": "normalized",
            "bounding_box_normalization_applied": False,
            "frame_width": None, "frame_height": None, "confidence": confidence,
            "evidence_text": "构造证据（规则测试，非模型输出）",
            "abstention_reason": None, "frame_status": "analyzed",
            "evidence_sufficient": confidence >= 0.5,
            "gaps": [] if confidence >= 0.5 else ["置信度低于阈值"], "warnings": [],
        }
    return analyze


def base_spec(video, sampling_strategy):
    return {
        "task_id": "task18-coverage-rule-test",
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
        "sampling_strategy": sampling_strategy,
    }


def coverage_block(**overrides):
    block = {
        "strategy": "coverage_aware_adaptive",
        "max_model_calls": 12,
        "initial_coverage_samples": 4,
        "coverage_gap_target_ms": 1500,
        "coverage_call_reserve": 4,
        "target_boundary_precision_ms": 500,
        "max_refinement_rounds": 6,
    }
    block.update(overrides)
    return block


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


def run_temporal(spec, tmp, out_name, analyze, frames_name="frames", **kwargs):
    out = os.path.join(tmp, out_name)
    options = {"allow_low_memory": True, "analyze_fn": analyze,
               "input_nature": "technical_fixture",
               "frames_dir": os.path.join(tmp, frames_name)}
    options.update(kwargs)
    doc = trace_temporal.trace_temporal(spec, out, **options)
    return doc


def contract_gt(sample_id):
    return load_json(os.path.join(
        TASK18_CONTRACTS, "ground-truth", f"{sample_id}.temporal-ground-truth.json"))


# ---------------------------------------------------------------- C01–C06 Schema/校验器

def test_schema_and_validator():
    with tempfile.TemporaryDirectory(prefix="sparkskill-t18-schema-") as tmp:
        # C01 旧 VisualTaskSpec 继续有效
        proc = run_validator(os.path.join(TASK03_DIR, "task-spec.json"))
        record("C01-legacy-spec-still-valid", "旧 VisualTaskSpec（无采样策略）继续有效",
               proc.returncode == 0 and "RESULT: VALID" in proc.stdout,
               f"exit={proc.returncode}（任务 03 真实规格原样校验）",
               "任务 03 真实产物（artifacts/task-03/task-spec.json）")

        # C02 旧两种策略输出行为不变（与任务 16 冻结行为逐项一致）
        reappear = t16_gt()["fixtures"]["reappear"]["segments"]
        throughout = t16_gt()["fixtures"]["present-throughout"]["segments"]
        appear = t16_gt()["fixtures"]["appear-midway"]["segments"]
        doc_u = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"),
                      {"strategy": "uniform", "max_model_calls": 5}),
            tmp, "c02-uniform.json",
            make_scripted_analyzer({"fixture-reappear": reappear}),
            frames_name="frames-c02u", interval_ms=700, max_frames=12)
        p_u = doc_u["sampling_provenance"]
        uniform_ok = (
            p_u["actual_model_calls"] == 5
            and p_u["uniform_sampling_truncated_to_budget"] is True
            and p_u["coverage_exploration_calls"] == 0
            and p_u["boundary_refinement_calls"] == 0
            and p_u["initial_coverage_calls"] == 5
            and all(d["phase"] == "initial_coverage" and d["purpose"] == "initial_coverage"
                    and d["candidate_interval"] is None for d in p_u["decisions"])
            and p_u["stop_reasons"] == [])
        doc_a = run_temporal(
            base_spec(t16_video("fixture-present-throughout.mp4"),
                      adaptive_block(max_model_calls=16)),
            tmp, "c02-adaptive.json",
            make_scripted_analyzer({"fixture-present-throughout": throughout}),
            frames_name="frames-c02a")
        p_a = doc_a["sampling_provenance"]
        adaptive_ok = (
            p_a["actual_model_calls"] == 4
            and p_a["refinement_rounds"] == 0
            and p_a["stop_reasons"] == ["no_refinable_interval"]
            and p_a["coverage_exploration_calls"] == 0
            and doc_a["temporal_evidence"]["state_transition_count"] == 0)
        doc_b = run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"),
                      adaptive_block(max_model_calls=16)),
            tmp, "c02-adaptive2.json",
            make_scripted_analyzer({"fixture-appear-midway": appear}),
            frames_name="frames-c02b")
        transitions = doc_b["temporal_evidence"]["state_transitions"]
        boundary = doc_b["temporal_evidence"]["boundary_uncertainty"]
        adaptive2_ok = (
            len(transitions) == 1
            and transitions[0]["left_ms"] < 3200 < transitions[0]["right_ms"]
            and boundary["target_precision_reached"] is True
            and boundary["max_ms"] <= 500)
        record("C02-old-strategies-behavior-unchanged", "旧 uniform/adaptive 策略输出行为不变",
               uniform_ok and adaptive_ok and adaptive2_ok,
               f"uniform 预算5→实际{p_u['actual_model_calls']}(截断={p_u['uniform_sampling_truncated_to_budget']},"
               f"无覆盖/细化调用)；adaptive 无变化→{p_a['actual_model_calls']}调用/"
               f"停止{p_a['stop_reasons']}；adaptive 出现场景→1 转换括号含 3200ms、"
               f"精度达成={boundary['target_precision_reached']}",
               "构造证据回放（真实 fixture 视频抽取 + 脚本化证据，非模型输出）")

        # C03 新策略合法规格（预注册配置逐字）
        path = write_spec(tmp, "coverage.json",
                          base_spec(t18_video("fixture-short-event-between-grid.mp4"),
                                    coverage_block()))
        proc = run_validator(path)
        record("C03-coverage-strategy-valid", "coverage_aware_adaptive 策略合法",
               proc.returncode == 0 and "RESULT: VALID" in proc.stdout,
               f"exit={proc.returncode}（预注册 arm-configs.json 的 coverage 配置逐字）",
               "构造输入（合法 coverage 策略规格）")

        # C04 缺失必填字段逐一拒绝
        missing = []
        for field in ("max_model_calls", "initial_coverage_samples",
                      "coverage_gap_target_ms", "coverage_call_reserve",
                      "target_boundary_precision_ms", "max_refinement_rounds"):
            block = coverage_block()
            del block[field]
            path = write_spec(tmp, f"missing-{field}.json",
                              base_spec(t18_video("fixture-short-event-between-grid.mp4"),
                                        block))
            proc = run_validator(path)
            missing.append((field, proc.returncode == 1 and field in proc.stderr))
        record("C04-coverage-missing-required-rejected", "新策略缺失必填参数被拒绝",
               all(ok for _, ok in missing),
               "；".join(f"{field}: {'拒绝' if ok else '未拒绝'}" for field, ok in missing),
               "构造输入（逐一删除 6 个必填字段）")

        # C05 非法预算/间隔/轮次/精度/储备拒绝
        cases = [
            ("gap-target-zero", coverage_block(coverage_gap_target_ms=0)),
            ("gap-target-negative", coverage_block(coverage_gap_target_ms=-100)),
            ("gap-target-string", coverage_block(coverage_gap_target_ms="1500")),
            ("reserve-zero", coverage_block(coverage_call_reserve=0)),
            ("reserve-negative", coverage_block(coverage_call_reserve=-1)),
            ("reserve-non-integer", coverage_block(coverage_call_reserve=2.5)),
            ("reserve-over-budget", coverage_block(coverage_call_reserve=9)),
            ("budget-zero", coverage_block(max_model_calls=0)),
            ("precision-zero", coverage_block(target_boundary_precision_ms=0)),
            ("rounds-zero", coverage_block(max_refinement_rounds=0)),
        ]
        rejections = []
        for name, block in cases:
            path = write_spec(tmp, f"illegal-{name}.json",
                              base_spec(t18_video("fixture-short-event-between-grid.mp4"),
                                        block))
            proc = run_validator(path)
            rejections.append((name, proc.returncode == 1))
        over = [name for name, ok in rejections if not ok]
        record("C05-coverage-illegal-values-rejected",
               "非法预算/间隔/轮次/精度/储备被拒绝", not over,
               f"{len(rejections) - len(over)}/{len(rejections)} 个非法值被拒绝"
               + (f"；未拒绝: {over}" if over else
                  "（含 initial(4)+reserve(9)=13>预算12 的覆盖配置越界）"),
               "构造输入（10 类非法值）")

        # C06 coverage 与 refinement 不突破总预算（运行时不变式）
        doc = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"), coverage_block()),
            tmp, "c06.json",
            make_scripted_analyzer({"fixture-reappear": reappear}),
            frames_name="frames-c06")
        p = doc["sampling_provenance"]
        budget_ok = (
            p["actual_model_calls"] <= 12
            and p["coverage_exploration_calls"] <= 4
            and p["initial_coverage_calls"] + p["coverage_exploration_calls"]
            + p["boundary_refinement_calls"] == p["actual_model_calls"])
        # tight-budget 派生（初始 4 + 储备 2 = 6）：覆盖调用 ≤ 2
        tight_block = coverage_block(max_model_calls=6, coverage_call_reserve=2,
                                     initial_coverage_samples=4)
        doc_t = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"), tight_block),
            tmp, "c06-tight.json",
            make_scripted_analyzer({"fixture-reappear": reappear}),
            frames_name="frames-c06t")
        p_t = doc_t["sampling_provenance"]
        tight_ok = (p_t["actual_model_calls"] <= 6
                    and p_t["coverage_exploration_calls"] <= 2
                    and p_t["boundary_refinement_calls"] <= 2)
        record("C06-coverage-refinement-within-budget",
               "coverage 与 refinement 不能突破总预算", budget_ok and tight_ok,
               f"预算12：实际={p['actual_model_calls']}≤12，覆盖={p['coverage_exploration_calls']}≤4，"
               f"三类调用之和=实际；预算6：实际={p_t['actual_model_calls']}≤6，"
               f"覆盖={p_t['coverage_exploration_calls']}≤2",
               "构造证据回放（fixture-reappear，预算 12/6）")


# ---------------------------------------------------------------- C07–C14 采样与预算

def test_sampling_and_budget():
    t16 = t16_gt()
    reappear = t16["fixtures"]["reappear"]["segments"]
    appear = t16["fixtures"]["appear-midway"]["segments"]
    throughout = t16["fixtures"]["present-throughout"]["segments"]

    with tempfile.TemporaryDirectory(prefix="sparkskill-t18-run-") as tmp:
        # C07 无状态变化仍执行覆盖探索
        doc = run_temporal(
            base_spec(t16_video("fixture-present-throughout.mp4"), coverage_block()),
            tmp, "c07.json",
            make_scripted_analyzer({"fixture-present-throughout": throughout}),
            frames_name="frames-c07")
        p = doc["sampling_provenance"]
        record("C07-coverage-without-state-change",
               "没有状态变化时仍执行覆盖探索",
               p["coverage_exploration_calls"] == 3
               and p["max_adjacent_sampling_gap_ms_final"]
               < p["max_adjacent_sampling_gap_ms_initial"]
               and "coverage_gap_target_reached" in p["stop_reasons"]
               and p["underobserved_intervals"] == []
               and doc["temporal_evidence"]["state_transition_count"] == 0,
               f"覆盖调用={p['coverage_exploration_calls']}，最大间隔 "
               f"{p['max_adjacent_sampling_gap_ms_initial']}→"
               f"{p['max_adjacent_sampling_gap_ms_final']} ms，"
               f"停止={p['stop_reasons']}",
               "构造证据回放（fixture-present-throughout，全程 confirmed 无转换）")

        # C08 出现状态变化后执行边界细化
        doc = run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"), coverage_block()),
            tmp, "c08.json",
            make_scripted_analyzer({"fixture-appear-midway": appear}),
            frames_name="frames-c08")
        p = doc["sampling_provenance"]
        refinement_decisions = [d for d in p["decisions"]
                                if d["phase"] == "refinement"
                                and d["cache_status"] == "fresh_call"]
        transitions = doc["temporal_evidence"]["state_transitions"]
        record("C08-refinement-after-state-change",
               "出现状态变化后执行边界细化",
               p["boundary_refinement_calls"] >= 1
               and len(refinement_decisions) >= 1
               and all(d["purpose"] == "boundary_refinement"
                       and d["trigger_interval"] is not None
                       for d in refinement_decisions)
               and len(transitions) == 1
               and transitions[0]["left_ms"] < 3200 < transitions[0]["right_ms"],
               f"细化调用={p['boundary_refinement_calls']}，"
               f"转换括号={[(t['left_ms'], t['right_ms']) for t in transitions]}（含 GT 3200ms）",
               "构造证据回放（fixture-appear-midway）")

        # C09 覆盖与细化竞争预算（reappear 预算 6：初始 4 + 覆盖储备 2）
        doc_c = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"),
                      coverage_block(max_model_calls=6, coverage_call_reserve=2)),
            tmp, "c09-cov.json",
            make_scripted_analyzer({"fixture-reappear": reappear}),
            frames_name="frames-c09c")
        doc_a = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"),
                      adaptive_block(max_model_calls=6)),
            tmp, "c09-ada.json",
            make_scripted_analyzer({"fixture-reappear": reappear}),
            frames_name="frames-c09a")
        doc_u = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"),
                      {"strategy": "uniform", "max_model_calls": 6}),
            tmp, "c09-uni.json",
            make_scripted_analyzer({"fixture-reappear": reappear}),
            frames_name="frames-c09u", interval_ms=700, max_frames=12)
        p_c, p_a, p_u = (doc_c["sampling_provenance"], doc_a["sampling_provenance"],
                         doc_u["sampling_provenance"])
        record("C09-coverage-refinement-budget-contention",
               "覆盖与细化竞争预算（确定性分配）",
               p_c["actual_model_calls"] == 6 and p_c["coverage_exploration_calls"] == 2
               and p_c["boundary_refinement_calls"] == 0 and p_c["budget_exhausted"] is True
               and p_a["actual_model_calls"] == 6 and p_a["coverage_exploration_calls"] == 0
               and p_a["boundary_refinement_calls"] == 2
               and p_u["actual_model_calls"] == 6
               and p_u["uniform_sampling_truncated_to_budget"] is True,
               f"预算6：coverage 初始4+覆盖2+细化0；adaptive 初始4+细化2；"
               f"uniform 截断至 6 点（三类分配均为确定性结果）",
               "构造证据回放（fixture-reappear，三臂统一预算 6）")

        # C10 预算在覆盖阶段耗尽
        doc = run_temporal(
            base_spec(t16_video("fixture-present-throughout.mp4"),
                      coverage_block(max_model_calls=6, coverage_call_reserve=2)),
            tmp, "c10.json",
            make_scripted_analyzer({"fixture-present-throughout": throughout}),
            frames_name="frames-c10")
        p = doc["sampling_provenance"]
        record("C10-budget-exhausted-in-coverage", "预算在覆盖阶段耗尽",
               p["actual_model_calls"] == 6 and p["coverage_exploration_calls"] == 2
               and p["boundary_refinement_calls"] == 0
               and "budget_exhausted" in p["stop_reasons"]
               and p["budget_exhausted"] is True,
               f"实际={p['actual_model_calls']}/6，覆盖={p['coverage_exploration_calls']}，"
               f"细化={p['boundary_refinement_calls']}，停止={p['stop_reasons']}",
               "构造证据回放（present-throughout，覆盖需要 3 次但预算仅剩 2）")

        # C11 预算在边界细化阶段耗尽
        doc = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"), coverage_block()),
            tmp, "c11.json",
            make_scripted_analyzer({"fixture-reappear": reappear}),
            frames_name="frames-c11")
        p = doc["sampling_provenance"]
        record("C11-budget-exhausted-in-refinement", "预算在边界细化阶段耗尽",
               p["actual_model_calls"] == 12 and p["coverage_exploration_calls"] == 3
               and p["boundary_refinement_calls"] == 5
               and "budget_exhausted" in p["stop_reasons"]
               and doc["temporal_evidence"]["state_transition_count"] == 3,
               f"实际={p['actual_model_calls']}/12（覆盖3+细化5），"
               f"转换={doc['temporal_evidence']['state_transition_count']}，"
               f"停止={p['stop_reasons']}",
               "构造证据回放（fixture-reappear，3 个转换的细化超出剩余预算）")

        # C12 重复时间戳跳过且不调用模型（覆盖目标 1ms 迫使收敛到帧分辨率）
        doc = run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"),
                      coverage_block(max_model_calls=128, coverage_call_reserve=100,
                                     coverage_gap_target_ms=1,
                                     target_boundary_precision_ms=1,
                                     max_refinement_rounds=12)),
            tmp, "c12.json",
            make_scripted_analyzer({"fixture-appear-midway": appear}),
            frames_name="frames-c12")
        p = doc["sampling_provenance"]
        fresh = [d for d in p["decisions"] if d["cache_status"] == "fresh_call"]
        record("C12-duplicate-timestamp-no-recall", "重复时间戳跳过且不调用模型",
               len(p["skipped_duplicate_timestamps"]) >= 1
               and len(p["analyzed_timestamps"]) == len(set(p["analyzed_timestamps"]))
               and p["actual_model_calls"] == len(fresh) == len(p["analyzed_timestamps"])
               and any(r in ("coverage_reserve_exhausted", "coverage_no_refinable_gap")
                       for r in p["stop_reasons"]),
               f"跳过重复={len(p['skipped_duplicate_timestamps'])}，唯一时间戳="
               f"{len(set(p['analyzed_timestamps']))}=实际调用={p['actual_model_calls']}，"
               f"停止={p['stop_reasons']}",
               "构造证据回放（覆盖目标 1ms + 储备 100，中点收敛到帧分辨率）")

        # C13 缓存证据正确复用（预算账本语义）
        budget = adaptive_sampler.CallBudget(8)
        budget.record_entry(1000.0, {"timestamp_ms": 1000.0}, fresh=True)
        ledger_ok = (
            budget.has_analyzed(1000.0) is True
            and budget.has_analyzed(1000.0004) is True  # 毫秒级四舍五入同一采样点
            and budget.has_analyzed(2000.0) is False)
        budget.register_duplicate(1000.0)
        budget.register_reuse()
        snapshot = budget.snapshot()
        ledger_ok = ledger_ok and (
            snapshot["reused_evidence_count"] == 1
            and snapshot["skipped_duplicate_timestamps"] == [1000.0]
            and snapshot["actual_model_calls"] == 0)  # 复用不计入新鲜调用
        # 执行器层：同一时间戳第二次出现 → skipped_duplicate，不第二次调用
        doc = run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"),
                      coverage_block(max_model_calls=128, coverage_call_reserve=100,
                                     coverage_gap_target_ms=1,
                                     target_boundary_precision_ms=1,
                                     max_refinement_rounds=12)),
            tmp, "c13.json",
            make_scripted_analyzer({"fixture-appear-midway": appear}),
            frames_name="frames-c13")
        p = doc["sampling_provenance"]
        duplicates = [d for d in p["decisions"] if d["cache_status"] == "skipped_duplicate"]
        executor_ok = (len(duplicates) >= 1
                       and all(d["model_call_seq"] is None for d in duplicates)
                       and p["actual_model_calls"] == len(p["analyzed_timestamps"]))
        record("C13-cached-evidence-reused", "缓存证据正确复用", ledger_ok and executor_ok,
               f"账本：has_analyzed/复用计数/重复跳过语义正确（复用不计调用）；"
               f"执行器：{len(duplicates)} 个重复决策均未产生模型调用",
               "构造输入（CallBudget 单元 + C12 同配置运行产物）")

        # C14 最大相邻采样间隔可复算
        doc = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"), coverage_block()),
            tmp, "c14.json",
            make_scripted_analyzer({"fixture-reappear": reappear}),
            frames_name="frames-c14")
        p = doc["sampling_provenance"]
        duration = doc["duration_ms"]
        analyzed = p["analyzed_timestamps"]
        recomputed_final = adaptive_sampler.max_adjacent_gap_ms(analyzed, duration)
        initial_ts = [d["timestamp_ms"] for d in p["decisions"]
                      if d["phase"] == "initial_coverage"]
        recomputed_initial = adaptive_sampler.max_adjacent_gap_ms(initial_ts, duration)
        coverage_block_doc = doc["temporal_evidence"]["coverage"]
        record("C14-max-gap-recomputable", "最大相邻采样间隔可复算",
               recomputed_final == p["max_adjacent_sampling_gap_ms_final"]
               == coverage_block_doc["max_adjacent_sampling_gap_ms_final"]
               and recomputed_initial == p["max_adjacent_sampling_gap_ms_initial"]
               == coverage_block_doc["max_adjacent_sampling_gap_ms_initial"],
               f"复算最终={recomputed_final}（provenance/temporal_evidence 一致）；"
               f"复算初始={recomputed_initial}（由初始覆盖时间戳复算）",
               "构造证据回放（fixture-reappear）")


# ---------------------------------------------------------------- C15–C20 场景行为

def test_scenarios():
    t18 = t18_gt()
    t16 = t16_gt()
    short_event = t18["fixtures"]["short-event-between-grid"]["segments"]
    short_uncertain = t18["fixtures"]["short-uncertain-between-grid"]["segments"]
    phase_b = t18["fixtures"]["short-event-phase-b"]["segments"]
    twin = t18["fixtures"]["twin-short-events"]["segments"]
    throughout = t16["fixtures"]["present-throughout"]["segments"]
    absent = t18["fixtures"]["absent-throughout"]["segments"]

    def samples_inside(doc, start, end):
        return [ts for ts in doc["sampling_provenance"]["analyzed_timestamps"]
                if start <= ts < end]

    with tempfile.TemporaryDirectory(prefix="sparkskill-t18-scenario-") as tmp:
        # C15 短事件落在旧 coarse 网格之间
        doc_cov = run_temporal(
            base_spec(t18_video("fixture-short-event-between-grid.mp4"), coverage_block()),
            tmp, "c15-cov.json",
            make_scripted_analyzer({"fixture-short-event-between-grid": short_event}),
            frames_name="frames-c15c")
        doc_ada = run_temporal(
            base_spec(t18_video("fixture-short-event-between-grid.mp4"),
                      adaptive_block(max_model_calls=12)),
            tmp, "c15-ada.json",
            make_scripted_analyzer({"fixture-short-event-between-grid": short_event}),
            frames_name="frames-c15a")
        cov_inside = samples_inside(doc_cov, 3500, 4100)
        ada_inside = samples_inside(doc_ada, 3500, 4100)
        gt = contract_gt("short-event-between-grid")
        cov_events = frozen_scorer.score_events(doc_cov["timeline"], gt)
        ada_events = frozen_scorer.score_events(doc_ada["timeline"], gt)
        record("C15-short-event-between-coarse-grid",
               "短事件落在旧 coarse 网格之间（coverage 发现、adaptive 漏检）",
               len(cov_inside) >= 1 and len(ada_inside) == 0
               and cov_events["missed_confirmed_events"] == 0
               and ada_events["missed_confirmed_events"] == 1,
               f"事件 [3500,4100)：coverage 采样落入 {cov_inside}（漏检="
               f"{cov_events['missed_confirmed_events']}）；adaptive 落入 {ada_inside}"
               f"（漏检={ada_events['missed_confirmed_events']}）",
               "构造证据回放（fixture-short-event-between-grid，冻结 GT 来自 contracts）")

        # C16 短 uncertain 区域落在旧 coarse 网格之间
        doc_cov = run_temporal(
            base_spec(t18_video("fixture-short-uncertain-between-grid.mp4"),
                      coverage_block()),
            tmp, "c16-cov.json",
            make_scripted_analyzer({"fixture-short-uncertain-between-grid": short_uncertain}),
            frames_name="frames-c16c")
        doc_ada = run_temporal(
            base_spec(t18_video("fixture-short-uncertain-between-grid.mp4"),
                      adaptive_block(max_model_calls=12)),
            tmp, "c16-ada.json",
            make_scripted_analyzer({"fixture-short-uncertain-between-grid": short_uncertain}),
            frames_name="frames-c16a")
        cov_abstained = [e["timestamp_ms"] for e in doc_cov["timeline"]
                         if e.get("abstention_reason") and 3500 <= e["timestamp_ms"] < 4100]
        ada_abstained = [e["timestamp_ms"] for e in doc_ada["timeline"]
                         if e.get("abstention_reason") and 3500 <= e["timestamp_ms"] < 4100]
        gt = contract_gt("short-uncertain-between-grid")
        cov_events = frozen_scorer.score_events(doc_cov["timeline"], gt)
        ada_events = frozen_scorer.score_events(doc_ada["timeline"], gt)
        record("C16-short-uncertain-between-coarse-grid",
               "短 uncertain 区域落在旧 coarse 网格之间（coverage 触达、adaptive 未触达）",
               len(cov_abstained) >= 1 and len(ada_abstained) == 0
               and cov_events["unreached_uncertain_segments"] == 0
               and ada_events["unreached_uncertain_segments"] == 1,
               f"uncertain [3500,4100)：coverage 拒答采样 {cov_abstained}（未触达="
               f"{cov_events['unreached_uncertain_segments']}）；adaptive {ada_abstained}"
               f"（未触达={ada_events['unreached_uncertain_segments']}，任务 17 盲区复现）",
               "构造证据回放（fixture-short-uncertain-between-grid）")

        # C17 相位移动后的短事件
        doc_cov = run_temporal(
            base_spec(t18_video("fixture-short-event-phase-b.mp4"), coverage_block()),
            tmp, "c17-cov.json",
            make_scripted_analyzer({"fixture-short-event-phase-b": phase_b}),
            frames_name="frames-c17c")
        doc_ada = run_temporal(
            base_spec(t18_video("fixture-short-event-phase-b.mp4"),
                      adaptive_block(max_model_calls=12)),
            tmp, "c17-ada.json",
            make_scripted_analyzer({"fixture-short-event-phase-b": phase_b}),
            frames_name="frames-c17a")
        cov_inside = samples_inside(doc_cov, 6200, 6800)
        ada_inside = samples_inside(doc_ada, 6200, 6800)
        gt = contract_gt("short-event-phase-b")
        cov_events = frozen_scorer.score_events(doc_cov["timeline"], gt)
        record("C17-phase-shifted-short-event", "相位移动后的短事件（coverage 仍能发现）",
               len(cov_inside) >= 1 and len(ada_inside) == 0
               and cov_events["missed_confirmed_events"] == 0,
               f"事件 [6200,6800)：coverage 落入 {cov_inside}（漏检=0）；"
               f"adaptive 落入 {ada_inside}（漏检=1）",
               "构造证据回放（fixture-short-event-phase-b，与 C15 语义同、相位不同）")

        # C18 多个短事件（诚实记录：600ms 事件小于 1333ms 覆盖间隔 → 漏检）
        doc_cov = run_temporal(
            base_spec(t18_video("fixture-twin-short-events.mp4"), coverage_block()),
            tmp, "c18-cov.json",
            make_scripted_analyzer({"fixture-twin-short-events": twin}),
            frames_name="frames-c18c")
        doc_ada = run_temporal(
            base_spec(t18_video("fixture-twin-short-events.mp4"),
                      adaptive_block(max_model_calls=12)),
            tmp, "c18-ada.json",
            make_scripted_analyzer({"fixture-twin-short-events": twin}),
            frames_name="frames-c18a")
        doc_uni = run_temporal(
            base_spec(t18_video("fixture-twin-short-events.mp4"),
                      {"strategy": "uniform", "max_model_calls": 12}),
            tmp, "c18-uni.json",
            make_scripted_analyzer({"fixture-twin-short-events": twin}),
            frames_name="frames-c18u", interval_ms=700, max_frames=12)
        gt = contract_gt("twin-short-events")
        cov_events = frozen_scorer.score_events(doc_cov["timeline"], gt)
        ada_events = frozen_scorer.score_events(doc_ada["timeline"], gt)
        uni_events = frozen_scorer.score_events(doc_uni["timeline"], gt)
        record("C18-multiple-short-events",
               "多个短事件（诚实记录漏检：事件短于最大相邻间隔）",
               cov_events["missed_confirmed_events"] == 2
               and ada_events["missed_confirmed_events"] == 2
               and uni_events["missed_confirmed_events"] == 0
               and doc_cov["sampling_provenance"][
                   "max_adjacent_sampling_gap_ms_final"] > 600,
               f"两个 600ms 事件：coverage 漏检={cov_events['missed_confirmed_events']}、"
               f"adaptive 漏检={ada_events['missed_confirmed_events']}（最终间隔 "
               f"{doc_cov['sampling_provenance']['max_adjacent_sampling_gap_ms_final']}ms "
               f"> 事件宽度，符合'事件短于最大相邻采样间隔可能被漏检'声明）；"
               f"uniform 12 点网格漏检={uni_events['missed_confirmed_events']}",
               "构造证据回放（fixture-twin-short-events；预注册对抗场景，不改标签）")

        # C19 全程 confirmed
        doc = run_temporal(
            base_spec(t16_video("fixture-present-throughout.mp4"), coverage_block()),
            tmp, "c19.json",
            make_scripted_analyzer({"fixture-present-throughout": throughout}),
            frames_name="frames-c19")
        counts = doc["temporal_evidence"]["class_counts"]
        record("C19-throughout-confirmed", "全程 confirmed（无状态转换）",
               counts == {"confirmed": doc["sampling_provenance"]["actual_model_calls"],
                          "not_found": 0, "abstained": 0, "low_confidence": 0, "failed": 0}
               and doc["temporal_evidence"]["state_transition_count"] == 0
               and doc["summary"]["overall_status"] == "completed",
               f"五类计数={counts}，转换=0，整体状态=completed",
               "构造证据回放（fixture-present-throughout）")

        # C20 全程 not_found
        doc = run_temporal(
            base_spec(t18_video("fixture-absent-throughout.mp4"), coverage_block()),
            tmp, "c20.json",
            make_scripted_analyzer({"fixture-absent-throughout": absent}),
            frames_name="frames-c20")
        counts = doc["temporal_evidence"]["class_counts"]
        record("C20-throughout-not-found", "全程 not_found（无目标/无转换）",
               counts["confirmed"] == 0 and counts["failed"] == 0
               and counts["not_found"] == doc["sampling_provenance"]["actual_model_calls"]
               and doc["temporal_evidence"]["state_transition_count"] == 0
               and doc["summary"]["overall_status"] == "completed",
               f"五类计数={counts}，转换=0，整体状态=completed（负面结论）",
               "构造证据回放（fixture-absent-throughout）")


# ---------------------------------------------------------------- C21–C23 五类分支与 uncertain 评分

def test_evidence_classes():
    t18 = t18_gt()
    short_uncertain = t18["fixtures"]["short-uncertain-between-grid"]["segments"]

    with tempfile.TemporaryDirectory(prefix="sparkskill-t18-classes-") as tmp:
        # C21 failed / abstained / low_confidence 分支互不折算
        # 注入点必须是该策略真实采样到的时间戳（1333.333/2666.667 为覆盖探索采样点）
        doc = run_temporal(
            base_spec(t18_video("fixture-short-uncertain-between-grid.mp4"),
                      coverage_block()),
            tmp, "c21.json",
            make_scripted_analyzer(
                {"fixture-short-uncertain-between-grid": short_uncertain},
                fail_at={"fixture-short-uncertain-between-grid": [1333.333]},
                low_confidence_at={"fixture-short-uncertain-between-grid": [2666.667]}),
            frames_name="frames-c21")
        counts = doc["temporal_evidence"]["class_counts"]
        failed_entries = [e for e in doc["timeline"] if e["frame_status"] == "failed"]
        low_entries = [e for e in doc["timeline"]
                       if e["frame_status"] == "analyzed" and e.get("object_found")
                       and not e.get("evidence_sufficient")]
        # 注意：failed 帧的 abstention_reason 记录的是失败原因（分类属 failed），
        # abstained 只统计 analyzed 且带拒答原因的帧（与 classify_entry 规则一致）。
        abstained_entries = [e for e in doc["timeline"]
                             if e["frame_status"] == "analyzed" and e.get("abstention_reason")]
        record("C21-five-class-branches", "failed、abstained、low_confidence 分支互不折算",
               counts["failed"] == 1 and len(failed_entries) == 1
               and counts["low_confidence"] == len(low_entries) == 1
               and counts["abstained"] == len(abstained_entries) >= 1
               and counts["not_found"] == 0 and counts["confirmed"] >= 1
               and all(e["frame_status"] == "analyzed" for e in low_entries)
               and any("未获得视觉证据" in w for w in doc["warnings"]),
               f"failed={counts['failed']}，abstained={counts['abstained']}，"
               f"low_confidence={counts['low_confidence']}，confirmed={counts['confirmed']}，"
               f"not_found={counts['not_found']}（该 fixture 无 absent 区：三类非确定/失败"
               f"证据均未折算为 not_found；注入失败帧触发 failed 触发器属预期行为）",
               "构造证据回放（1333.333ms 注入单帧失败 + 2666.667ms 低置信 + uncertain 区间拒答）")

        # C22 触达 uncertain 但模型 decisive overclaim（评分器口径）
        doc = run_temporal(
            base_spec(t18_video("fixture-short-uncertain-between-grid.mp4"),
                      coverage_block()),
            tmp, "c22.json",
            make_scripted_analyzer(
                {"fixture-short-uncertain-between-grid": short_uncertain},
                overclaim_uncertain=True),
            frames_name="frames-c22")
        gt = contract_gt("short-uncertain-between-grid")
        points = frozen_scorer.score_sample_points(doc["timeline"], gt)
        metrics = points["metrics"]
        reached = frozen_scorer.score_events(doc["timeline"], gt)
        record("C22-overclaim-on-uncertain",
               "触达 uncertain 但模型 decisive overclaim（计为过度断言，不算覆盖成功）",
               metrics["overclaim_on_uncertain"]["passed"] >= 1
               and metrics["appropriate_abstention"]["passed"] == 0
               and reached["unreached_uncertain_segments"] == 0,
               f"uncertain 采样点被确定性判定 → overclaim_on_uncertain="
               f"{metrics['overclaim_on_uncertain']['passed']}/"
               f"{metrics['overclaim_on_uncertain']['total']}，"
               f"appropriate_abstention={metrics['appropriate_abstention']['passed']}，"
               f"未触达={reached['unreached_uncertain_segments']}（触达≠语义正确）",
               "构造证据回放（模拟任务 16 记录过的真实 Qwen 确定性负面行为）")

        # C23 未触达 uncertain（adaptive 覆盖盲区）
        doc = run_temporal(
            base_spec(t18_video("fixture-short-uncertain-between-grid.mp4"),
                      adaptive_block(max_model_calls=12)),
            tmp, "c23.json",
            make_scripted_analyzer({"fixture-short-uncertain-between-grid": short_uncertain}),
            frames_name="frames-c23")
        points = frozen_scorer.score_sample_points(doc["timeline"], gt)
        reached = frozen_scorer.score_events(doc["timeline"], gt)
        record("C23-unreached-uncertain", "未触达 uncertain（与触达后过度断言是不同失败）",
               reached["unreached_uncertain_segments"] == 1
               and points["metrics"]["overclaim_on_uncertain"]["total"] == 0
               and points["metrics"]["appropriate_abstention"]["total"] == 0,
               f"adaptive 初始 4 点全部落在 uncertain 区外 → 未触达="
               f"{reached['unreached_uncertain_segments']}；uncertain 指标分母=0"
               f"（未触达不计入过度断言）",
               "构造证据回放（fixture-short-uncertain-between-grid，adaptive 臂）")


# ---------------------------------------------------------------- C24–C29 安全与 provenance

def test_security_and_provenance():
    t18 = t18_gt()
    t16 = t16_gt()
    appear = t16["fixtures"]["appear-midway"]["segments"]
    disappear = t16["fixtures"]["disappear-midway"]["segments"]

    with tempfile.TemporaryDirectory(prefix="sparkskill-t18-sec-") as tmp:
        # C24 Ground Truth 不进入采样决策
        source_ok = True
        for rel in (".dsh/skills/visual-evidence-extractor/scripts/trace_temporal.py",
                    ".dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py"):
            text = open(os.path.join(PROJECT_ROOT, rel), encoding="utf-8").read()
            if "ground_truth" in text or "ground-truth" in text:
                source_ok = False
        # 纯函数性：next_coverage_candidate 只依赖 (gaps, target, excluded)
        gaps = adaptive_sampler.adjacent_gaps([0.0, 2666.667, 5333.333, 7958.333], 8000.0)
        first = adaptive_sampler.next_coverage_candidate(gaps, 1500)
        second = adaptive_sampler.next_coverage_candidate(
            [dict(gap) for gap in gaps], 1500)
        pure_ok = first == second and first["left_ms"] == 0.0
        # 行为等同：GT 驱动分析器 vs 恒定 not_found 分析器 → 覆盖阶段时间戳完全一致
        doc_gt = run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"), coverage_block()),
            tmp, "c24-gt.json",
            make_scripted_analyzer({"fixture-appear-midway": appear}),
            frames_name="frames-c24a")

        def constant_analyzer(spec, frame):
            entry = make_scripted_analyzer({})(spec, frame)
            entry["object_found"] = False
            entry["evidence_sufficient"] = False
            entry["confidence"] = 0.9
            entry["abstention_reason"] = None
            entry["description"] = "构造证据：恒定阴性（GT 盲）"
            return entry

        doc_blind = run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"), coverage_block()),
            tmp, "c24-blind.json", constant_analyzer, frames_name="frames-c24b")
        coverage_ts_gt = [d["timestamp_ms"] for d in doc_gt["sampling_provenance"]["decisions"]
                          if d["phase"] == "coverage_exploration"]
        coverage_ts_blind = [d["timestamp_ms"]
                             for d in doc_blind["sampling_provenance"]["decisions"]
                             if d["phase"] == "coverage_exploration"]
        record("C24-ground-truth-not-in-sampling",
               "Ground Truth 不进入采样决策",
               source_ok and pure_ok and coverage_ts_gt == coverage_ts_blind
               and len(coverage_ts_gt) >= 1,
               f"源码无 ground_truth 引用={source_ok}；next_coverage_candidate 纯函数="
               f"{pure_ok}；GT 驱动与 GT 盲分析器的覆盖阶段时间戳完全一致"
               f"（{coverage_ts_gt}）",
               "构造证据回放（两种分析器对比 + 源码扫描 + 纯函数断言）")

        # C25 输入文件只读
        inputs = ([os.path.join(TASK18_FIXTURES, "videos", name)
                   for name in os.listdir(os.path.join(TASK18_FIXTURES, "videos"))]
                  + [os.path.join(TASK16_FIXTURES, "videos", name)
                     for name in os.listdir(os.path.join(TASK16_FIXTURES, "videos"))]
                  + [os.path.join(TASK18_CONTRACTS, "ground-truth", name)
                     for name in os.listdir(os.path.join(TASK18_CONTRACTS, "ground-truth"))])
        before = {path: hashlib.sha256(open(path, "rb").read()).hexdigest()
                  for path in inputs}
        run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"), coverage_block()),
            tmp, "c25.json",
            make_scripted_analyzer({"fixture-appear-midway": appear}),
            frames_name="frames-c25")
        after = {path: hashlib.sha256(open(path, "rb").read()).hexdigest()
                 for path in inputs}
        record("C25-inputs-readonly", "输入文件只读", before == after,
               f"{len(inputs)} 个输入文件（fixture 视频 + Ground Truth）运行前后 SHA-256 一致",
               "构造证据回放（运行前后输入哈希比对）")

        # C26 输出不含凭据或敏感绝对路径
        doc = run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"), coverage_block()),
            tmp, "c26.json",
            make_scripted_analyzer({"fixture-appear-midway": appear}),
            frames_name="frames-c26")
        spec = base_spec(t16_video("fixture-appear-midway.mp4"), coverage_block())
        report = generate_report.build_temporal_report(spec, doc)
        text = json.dumps({"doc": doc, "report": report}, ensure_ascii=False)
        lowered = text.lower()
        hits = [marker for marker in CREDENTIAL_MARKERS if marker in lowered]
        import re as _re
        if _re.search(r"sk-[A-Za-z0-9]{16,}", text):
            hits.append("sk-<long-token>")
        system_sensitive = [p for p in ("/root/", "/etc/", "/proc/", "/var/log")
                            if p in text]
        # /home/ 只允许出现在媒体/帧可追溯字段（source_video/frame_path），
        # 与任务 16 已提交产物的审计轨迹惯例一致；其余字段必须为仓库相对路径。
        source_video = doc.get("source_video") or ""
        sanitized_report = dict(report)
        sanitized_report.pop("evidence", None)
        sanitized_report.pop("source_video", None)
        if source_video and isinstance(sanitized_report.get("conclusion"), str):
            # conclusion 中引用的视频路径同属媒体可追溯信息（任务 16 惯例），
            # 净化后参与扫描
            sanitized_report["conclusion"] = sanitized_report["conclusion"].replace(
                source_video, "<media>")
        sanitized = json.dumps(
            {"doc": {k: v for k, v in doc.items()
                     if k not in ("source_video", "timeline")},
             "report": sanitized_report},
            ensure_ascii=False)
        leaked = [p for p in ("/home/", "/root/", "/etc/") if p in sanitized]
        record("C26-output-no-credentials-or-sensitive-paths",
               "输出不含凭据或敏感绝对路径",
               not hits and not system_sensitive and not leaked,
               f"凭据标记命中={hits or '无'}；系统敏感路径命中={system_sensitive or '无'}；"
               f"非媒体字段用户路径泄露={leaked or '无'}（source_video/frame_path 的绝对路径"
               f"为帧可追溯审计轨迹，与任务 16 已提交产物惯例一致）",
               "构造证据回放（temporal-evidence + temporal-report 分层扫描）")

        # C27 单来源 provenance 自洽（任务 17 G7 同口径 + 覆盖字段）
        doc = run_temporal(
            base_spec(t16_video("fixture-reappear.mp4"), coverage_block()),
            tmp, "c27.json",
            make_scripted_analyzer({"fixture-reappear":
                                    t16["fixtures"]["reappear"]["segments"]}),
            frames_name="frames-c27")
        p = doc["sampling_provenance"]
        temporal = doc["temporal_evidence"]
        fresh = [d for d in p["decisions"] if d["cache_status"] == "fresh_call"]
        recomputed = {name: 0 for name in adaptive_sampler.EVIDENCE_CLASSES}
        for entry in doc["timeline"]:
            recomputed[adaptive_sampler.classify_entry(entry)] += 1
        self_consistent = (
            p["actual_model_calls"] == len(fresh) == len(doc["timeline"])
            and sorted(p["analyzed_timestamps"])
            == sorted(e["timestamp_ms"] for e in doc["timeline"])
            and all(recomputed[name] == temporal["class_counts"][name]
                    for name in recomputed)
            and temporal["actual_model_calls"] == p["actual_model_calls"]
            and p["actual_model_calls"] <= p["configured_budget"]
            and p["coverage_exploration_calls"] <= p["coverage_call_reserve"]
            and p["initial_coverage_calls"] + p["coverage_exploration_calls"]
            + p["boundary_refinement_calls"] == p["actual_model_calls"])
        record("C27-single-source-provenance-self-consistent",
               "单来源 provenance 自洽", self_consistent,
               f"实际调用={p['actual_model_calls']}=新鲜调用=时间线条目；五类计数复算一致；"
               f"覆盖调用 {p['coverage_exploration_calls']}≤储备 "
               f"{p['coverage_call_reserve']}；总调用≤预算",
               "构造证据回放（fixture-reappear，coverage 臂）")

        # C28 多来源预算和时间戳语义
        spec = base_spec([
            {"source_id": "video-a", "path": t16_video("fixture-appear-midway.mp4"),
             "location": "scene-a", "time_offset_ms": 0},
            {"source_id": "video-b", "path": t16_video("fixture-disappear-midway.mp4"),
             "location": "scene-b", "time_offset_ms": 5000},
        ], coverage_block(max_model_calls=24))
        out = os.path.join(tmp, "c28-multi.json")
        doc = trace_temporal.trace_temporal(
            spec, out, allow_low_memory=True,
            analyze_fn=make_scripted_analyzer({
                "fixture-appear-midway": appear,
                "fixture-disappear-midway": disappear}),
            input_nature="technical_fixture")
        shared = doc["shared_budget"]
        per_source = doc["sources"]
        entries = doc["global_timeline"]
        ids = {e["source_id"] for e in entries}
        offset_ok = all(abs(e["global_timestamp_ms"]
                            - (e["timestamp_ms"] + e["source_time_offset_ms"])) < 1e-9
                        for e in entries)
        sorted_ok = all(a["global_timestamp_ms"] <= b["global_timestamp_ms"]
                        for a, b in zip(entries, entries[1:]))
        original_ok = all(0 <= e["timestamp_ms"] < 8000 for e in entries)
        # 注意：多来源时每来源 provenance.actual_model_calls 是共享账本累计值
        # （任务 16 既有行为）；每来源新鲜采样数应以该来源时间线条目计。
        budget_ok = (shared["actual_model_calls"] <= 24
                     and sum(len(s["timeline"]) for s in per_source)
                     == shared["actual_model_calls"] == len(entries)
                     and all(s["sampling_provenance"]["coverage_exploration_calls"] <= 4
                             for s in per_source))
        report = generate_report.build_temporal_multi_report(spec, doc)
        forbidden_hits = [phrase for phrase in FORBIDDEN_PHRASINGS
                          if phrase in (report.get("conclusion") or "")]
        record("C28-multi-source-budget-and-timestamps",
               "多来源预算和时间戳语义（共享硬预算）",
               ids == {"video-a", "video-b"} and original_ok and offset_ok and sorted_ok
               and budget_ok and not forbidden_hits,
               f"来源={sorted(ids)}；原时间戳保持={original_ok}；global=local+offset="
               f"{offset_ok}；共享预算 {shared['actual_model_calls']}/24=各来源时间线条目之和；"
               f"每来源覆盖调用≤4；跨视频禁用措辞命中={forbidden_hits}",
               "构造证据回放（两段 fixture + time_offset_ms=5000，coverage 策略）")

        # C29 资源守卫阻塞时零模型调用
        doc = run_temporal(
            base_spec(t16_video("fixture-appear-midway.mp4"), coverage_block()),
            tmp, "c29.json", make_scripted_analyzer({}), frames_name="frames-c29",
            allow_low_memory=False, min_available_gib=10 ** 9)
        p = doc["sampling_provenance"]
        record("C29-resource-guard-zero-calls", "资源守卫阻塞时零模型调用",
               p["actual_model_calls"] == 0 and p["budget_exhausted"] is False
               and len(doc["timeline"]) > 0
               and all(e["frame_status"] == "failed" for e in doc["timeline"])
               and all(e["evidence_nature"] == "backend_not_called" for e in doc["timeline"])
               and doc["backend"]["resource_blocked"] is True
               and p["coverage_exploration_calls"] == 0
               and doc["evidence_nature"] == "resource_blocked",
               f"实际调用={p['actual_model_calls']}，全部帧 failed（backend_not_called），"
               f"覆盖调用={p['coverage_exploration_calls']}",
               "真实 fixture 视频抽取 + 资源守卫阈值 1e9 GiB（未调用任何模型）")


# ---------------------------------------------------------------- C30–C34 verdict 纪律

def _synthetic_aggregate(calls, incorrect=0, overclaim=0, missed_events=0,
                         missed_bounds=0, unreached=0, within_tol=0, matched=0,
                         mean_error=None):
    return {
        "correct_decisive": 0, "incorrect_decisive": incorrect,
        "abstention_on_determinate": 0, "failed_on_determinate": 0,
        "appropriate_abstention": 0, "overclaim_on_uncertain": overclaim,
        "failed_on_uncertain": 0, "denominator_analyzed_samples": 0,
        "gt_confirmed_segments": 0, "covered_confirmed_events": 0,
        "missed_confirmed_events": missed_events, "gt_boundaries_total": 0,
        "matched_boundaries": matched, "missed_gt_boundaries": missed_bounds,
        "unmatched_predicted_transitions": 0,
        "within_tolerance_boundaries": within_tol,
        "unreached_uncertain_segments": unreached, "actual_model_calls": calls,
        "boundary_error_stats": {
            "matched_count": matched,
            "max_ms": mean_error, "min_ms": mean_error, "median_ms": mean_error,
            "mean_ms": mean_error if mean_error is not None else "not_applicable",
        },
    }


def test_verdict_discipline():
    adapter = load_module("task18_scorer_adapter", ADAPTER)

    # C30 三臂公平门任一条件失败时 INVALID_COMPARISON（适配层端到端）
    with tempfile.TemporaryDirectory(prefix="sparkskill-t18-verdict-") as tmp:
        prediction_set = os.path.join(
            PROJECT_ROOT, "artifacts", "task-18", "deterministic", "prediction-set.json")
        if not os.path.isfile(prediction_set):
            record("C30-fairness-gate-invalid-comparison",
                   "三臂公平门任一条件失败时 INVALID_COMPARISON", False,
                   "缺少 deterministic replay 产物（先运行 run_task18_comparison.py --mode replay）",
                   "适配层端到端（需 replay 产物）")
        else:
            proc = subprocess.run(
                [sys.executable, ADAPTER,
                 "--manifest", os.path.join(TASK18_CONTRACTS,
                                            "task18-fixture-evidence-pack-manifest.json"),
                 "--predictions", prediction_set,
                 "--ground-truth", os.path.join(TASK18_CONTRACTS, "ground-truth"),
                 "--out", os.path.join(tmp, "scores"),
                 "--comparison-id", "c30-mixed-budget",
                 "--sample-scope", "present-throughout,reappear-tight-budget"],
                capture_output=True, text=True)
            doc = load_json(os.path.join(tmp, "scores", "three-arm-comparison.json"))
            pairs = doc.get("pairwise") or {}
            invalid_all = bool(pairs) and all(
                pair["verdict"]["verdict"] == "INVALID_COMPARISON" for pair in pairs.values())
            budget_failed = all(
                any(not condition["passed"] and condition["id"] == "same_call_budget"
                    for condition in pair["fairness_gate"]["conditions"])
                for pair in pairs.values())
            record("C30-fairness-gate-invalid-comparison",
                   "三臂公平门任一条件失败时 INVALID_COMPARISON",
                   proc.returncode == 0 and invalid_all and budget_failed,
                   f"混合预算（12/6）进入比较范围 → 三对比较全部 INVALID_COMPARISON，"
                   f"失败条件均为 same_call_budget（exit={proc.returncode}，"
                   f"比较本身不算分但评分照常完成）",
                   "适配层端到端（复用 deterministic replay 产物，零新模型调用）")

        # C31 节省调用但增加漏检 → TRADEOFF（pack 级预注册规则）
        aggregates = {
            "uniform": _synthetic_aggregate(calls=12, missed_events=0, matched=3,
                                            mean_error=150.0),
            "adaptive": _synthetic_aggregate(calls=8, missed_events=1, matched=3,
                                             mean_error=140.0),
            "coverage": _synthetic_aggregate(calls=6, missed_events=2, matched=3,
                                             mean_error=120.0),
        }
        verdict = adapter.pack_level_verdict(
            aggregates, {"uniform": 700.0, "adaptive": 1300.0, "coverage": 1300.0})
        record("C31-tradeoff-fewer-calls-more-misses",
               "新策略节省调用但增加漏检时 TRADEOFF",
               verdict["verdict"] == "TRADEOFF"
               and "fewer_model_calls_than_both" in verdict["strict_improvements"]
               and any("more_missed_confirmed_events" in code
                       for code in verdict["reason_codes"]),
               f"verdict={verdict['verdict']}；strict={verdict['strict_improvements']}；"
               f"reason_codes={verdict['reason_codes']}",
               "构造指标（pack 级预注册规则的确定性单元验证）")

        # C32 覆盖更好但 overclaim 增加 → TRADEOFF
        aggregates = {
            "uniform": _synthetic_aggregate(calls=12, overclaim=0, matched=3,
                                            mean_error=150.0),
            "adaptive": _synthetic_aggregate(calls=8, overclaim=0, matched=3,
                                             mean_error=140.0),
            "coverage": _synthetic_aggregate(calls=6, overclaim=3, matched=3,
                                             mean_error=120.0),
        }
        verdict = adapter.pack_level_verdict(
            aggregates, {"uniform": 700.0, "adaptive": 1300.0, "coverage": 600.0})
        record("C32-tradeoff-better-coverage-more-overclaim",
               "新策略覆盖更好但 overclaim 增加时 TRADEOFF",
               verdict["verdict"] == "TRADEOFF"
               and any("more_overclaim_on_uncertain" in code
                       for code in verdict["reason_codes"]),
               f"verdict={verdict['verdict']}；reason_codes={verdict['reason_codes']}"
               "（触达更多 uncertain 但产生更多 decisive overclaim）",
               "构造指标（pack 级预注册规则的确定性单元验证）")

        # C33 无实质改进 → NO_IMPROVEMENT
        aggregates = {
            "uniform": _synthetic_aggregate(calls=12, matched=3, mean_error=150.0),
            "adaptive": _synthetic_aggregate(calls=8, matched=3, mean_error=140.0),
            "coverage": _synthetic_aggregate(calls=12, matched=3, mean_error=150.0),
        }
        verdict = adapter.pack_level_verdict(
            aggregates, {"uniform": 700.0, "adaptive": 1300.0, "coverage": 1300.0})
        record("C33-no-improvement", "无实质改进时 NO_IMPROVEMENT",
               verdict["verdict"] == "NO_IMPROVEMENT"
               and verdict["strict_improvements"] == [],
               f"verdict={verdict['verdict']}；strict={verdict['strict_improvements']}；"
               f"reason={verdict['reason'][:80]}",
               "构造指标（pack 级预注册规则的确定性单元验证）")

        # C34 满足严格条件才允许 IMPROVEMENT
        aggregates = {
            "uniform": _synthetic_aggregate(calls=12, matched=3, mean_error=150.0),
            "adaptive": _synthetic_aggregate(calls=8, matched=3, mean_error=140.0),
            "coverage": _synthetic_aggregate(calls=6, matched=3, mean_error=120.0),
        }
        verdict = adapter.pack_level_verdict(
            aggregates, {"uniform": 700.0, "adaptive": 1300.0, "coverage": 600.0})
        record("C34-improvement-only-under-strict-conditions",
               "满足严格条件时才允许 IMPROVEMENT",
               verdict["verdict"] == "IMPROVEMENT"
               and "fewer_model_calls_than_both" in verdict["strict_improvements"]
               and verdict["regressions"] == [],
               f"verdict={verdict['verdict']}；strict={verdict['strict_improvements']}；"
               f"非回归条件全部满足（对两个基线）",
               "构造指标（pack 级预注册规则的确定性单元验证）")

        # C34b pairwise 四类 verdict 由冻结评分器 compute_verdict 复算（适配层复用）
        base = _synthetic_aggregate(calls=12, matched=3, mean_error=150.0)
        better = _synthetic_aggregate(calls=8, matched=3, mean_error=140.0)
        worse_miss = _synthetic_aggregate(calls=8, missed_events=2, matched=3,
                                          mean_error=140.0)
        pairwise_ok = (
            frozen_scorer.compute_verdict(base, better)["verdict"] == "IMPROVEMENT"
            and frozen_scorer.compute_verdict(base, worse_miss)["verdict"] == "TRADEOFF"
            and frozen_scorer.compute_verdict(base, base)["verdict"] == "NO_IMPROVEMENT")
        record("C34b-pairwise-verdict-classes", "pairwise 四类 verdict 规则可用",
               pairwise_ok,
               "compute_verdict：严格更好→IMPROVEMENT；省调用但增漏检→TRADEOFF；"
               "等同→NO_IMPROVEMENT（INVALID_COMPARISON 由 C30 覆盖）",
               "构造指标（冻结评分器 compute_verdict 单元验证）")


# ---------------------------------------------------------------- C35 预注册哈希一致性

def test_preregistration_hashes():
    """C35：预注册文件/fixture/GT 哈希与阶段 A 提交（dcaf324）一致。

    直接重算 frozen-hashes.json 全部条目 + 用 git 比对 4 份人工声明文件与阶段 A
    提交中的 blob + fixture 冻结复核。不调用 self_check.py 的 S8（“实现尚未开始”
    是阶段 A 纯洁性检查，实现完成后按设计不再适用）。
    """
    frozen = load_json(os.path.join(TASK18_PREREG, "frozen-hashes.json"))
    mismatches = []

    def sha256_of(path):
        return hashlib.sha256(open(path, "rb").read()).hexdigest()

    for group in ("preregistration_declarations", "preregistration_data", "fixtures",
                  "ground_truth", "contracts", "design_doc"):
        for key, entry in frozen.get(group, {}).items():
            path = os.path.join(PROJECT_ROOT, entry["path"])
            if not os.path.isfile(path):
                mismatches.append(f"{group}/{key}: 文件缺失")
            elif sha256_of(path) != entry["sha256"]:
                mismatches.append(f"{group}/{key}: SHA-256 不一致")
    # 阶段 A 提交 blob 比对（4 份人工声明文件）。
    # 公开版适配：公开仓库为独立 Git 根，不含内部阶段 A 提交 dcaf324；
    # 此时该项记 NOT_RUN（不作为不一致），一致性以 frozen-hashes.json 的
    # 41 条目逐一重算 + fixture 冻结复核为准（ frozen-hashes.json 本身是
    # 阶段 A 冻结记录，随公开版原样分发）。提交存在时行为不变（不一致即记 mismatches）。
    phase_a_available = subprocess.run(
        ["git", "-C", PROJECT_ROOT, "cat-file", "-e", "dcaf324"],
        capture_output=True).returncode == 0
    git_blob_note = ""
    if phase_a_available:
        for name in ("evaluation-plan.json", "arm-configs.json", "verdict-policy.json",
                     "README.md"):
            committed = subprocess.run(
                ["git", "-C", PROJECT_ROOT, "show",
                 f"dcaf324:artifacts/task-18/preregistration/{name}"],
                capture_output=True)
            current = open(os.path.join(TASK18_PREREG, name), "rb").read()
            if committed.returncode != 0 or committed.stdout != current:
                mismatches.append(f"{name}: 与阶段 A 提交 dcaf324 内容不一致")
    else:
        git_blob_note = ("；git 阶段 A 提交 dcaf324 不在公开仓库（独立 Git 根），"
                         "该项 NOT_RUN，以 frozen-hashes.json 重算为准")
    # fixture 冻结复核
    verify = subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, "scripts",
                                      "generate_task18_fixtures.py"), "--verify"],
        capture_output=True, text=True)
    if verify.returncode != 0:
        mismatches.append("fixture 冻结复核失败")
    entry_count = sum(len(frozen.get(group, {})) for group in
                      ("preregistration_declarations", "preregistration_data", "fixtures",
                       "ground_truth", "contracts", "design_doc"))
    record("C35-preregistration-hashes-consistent",
           "预注册文件和 fixture 哈希与阶段 A 提交一致",
           not mismatches and entry_count >= 40,
           f"frozen-hashes.json {entry_count} 个条目逐一重算一致；fixture 冻结复核 FROZEN_OK"
           + ("" if phase_a_available else git_blob_note)
           + (f"；异常: {mismatches}" if mismatches else ""),
           "确定性核验（哈希重算 + git blob 比对 + fixture 冻结复核）")


def main():
    parser = argparse.ArgumentParser(description="任务 18 coverage_aware_adaptive 测试")
    parser.add_argument("--results-json", default=None, help="测试结果 JSON 输出路径")
    args = parser.parse_args()

    test_schema_and_validator()
    test_sampling_and_budget()
    test_scenarios()
    test_evidence_classes()
    test_security_and_provenance()
    test_verdict_discipline()
    test_preregistration_hashes()

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    print(f"\n小计：{passed}/{total} 通过"
          "（输入性质：构造证据回放/规则测试/真实 fixture 视频抽取；"
          "除 C30 复用 replay 产物外无任何模型调用）")
    if args.results_json:
        payload = {
            "suite": "task-18-coverage-aware-adaptive-sampling",
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
