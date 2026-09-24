#!/usr/bin/env python3
"""score_temporal_ground_truth.py — Evidence Pack 时间 Ground Truth 评分器
（SparkSkill Studio 任务 17）

独立、确定性、CPU-only：消费 Task 16 的标准化时间证据（temporal-evidence.json），
**不调用任何模型**，把"流水线完成 / 证据语义正确 / 采样效率"分开评价。

显式参数（缺一不可，禁止从 README/历史 artifacts/目录猜测输入）:

    --manifest     Evidence Pack manifest JSON（输入清单；不含时间真值）
    --predictions  预测集合 JSON（arms[] → samples[] → evidence 相对路径）
    --ground-truth Ground Truth JSON 文件或目录（显式独立真值输入）
    --out          输出目录（唯一写入位置）
    --comparison   可选：双臂公平比较规格 JSON（提供时追加 comparison.json/md）

输出（每个 (sample, arm)）:
    <out>/<sample_id>/<arm_id>/score.json        机器可读评分
    <out>/<sample_id>/<arm_id>/score.md          人类可读摘要
    <out>/<sample_id>/<arm_id>/input-hashes.json 输入文件哈希清单
比较输出（提供 --comparison 时）:
    <out>/comparison.json  <out>/comparison.md

确定性约定: 输出不含墙钟时间戳/主机名/绝对路径；同一输入永远逐字节相同；
排序稳定（时间戳 → sample_id → arm_id）；毫秒 3 位小数、比率 6 位小数、
均值 3 位小数；中位数偶数取中间两值平均；分母为 0 的比率写 "not_applicable"。

退出码: 0 = 全部样本硬门通过并完成评分; 1 = 存在硬门失败（结构化错误，未计分）;
        2 = 用法/IO 错误（含缺少显式 --ground-truth）
"""
import argparse
import hashlib
import importlib.util
import json
import os
import statistics
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCHEMA_DIR = os.path.join(PROJECT_ROOT, "schemas")

SCORER_NAME = "score_temporal_ground_truth.py"
SCORER_VERSION = "1.0.0"
SCORE_SCHEMA_VERSION = "1.0.0"
PREDICTION_SET_SCHEMA_VERSION = "1.0.0"
COMPARISON_SCHEMA_VERSION = "1.0.0"
SUPPORTED_EVIDENCE_VERSIONS = ("1.3.0",)

STRATEGIES = ("uniform", "adaptive_coarse_to_fine")
EVIDENCE_CLASSES = ("confirmed", "not_found", "abstained", "low_confidence", "failed")
DECISIVE_PRED_CLASSES = ("confirmed", "not_found")
NON_DECISIVE_PRED_CLASSES = ("abstained", "low_confidence")
GT_DETERMINATE_STATES = ("confirmed", "not_found")

SEVEN_METRICS = (
    "correct_decisive", "incorrect_decisive", "abstention_on_determinate",
    "failed_on_determinate", "appropriate_abstention", "overclaim_on_uncertain",
    "failed_on_uncertain",
)

VERDICTS = ("IMPROVEMENT", "TRADEOFF", "NO_IMPROVEMENT", "INVALID_COMPARISON")

# 输出落盘前的凭据样式自检（与任务 16 provenance 自检同款）
CREDENTIAL_MARKERS = ("api_key", "api-key", "secret", "token", "password", "passwd",
                      "bearer ", "private_key", "-----begin")


class ScoringError(Exception):
    """用法/IO 级错误（退出码 2）。"""


def load_validator_module():
    path = os.path.join(PROJECT_ROOT, "scripts", "validate_evidence_pack.py")
    spec = importlib.util.spec_from_file_location("validate_evidence_pack", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator = load_validator_module()


# ---------------------------------------------------------------- 基础工具

def round3(value):
    return round(float(value), 3)


def round6(value):
    return round(float(value), 6)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json_file(path, role):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ScoringError(f"无法读取{role} {validator.repo_relative(path)}: {error}")


def resolve_source_video(evidence_path, source_video):
    """解析 evidence.source_video：绝对路径原样使用；相对路径相对 evidence
    文件所在目录解析（fixture 可用相对路径，避免在输入中写绝对路径）。"""
    if not isinstance(source_video, str) or not source_video.strip():
        return None
    if os.path.isabs(source_video):
        return os.path.realpath(source_video)
    return os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(evidence_path)),
                                         source_video))


def ground_truth_path_for(ground_truths, sample_id, gt_arg):
    """定位样本 GT 文件路径（用于输入哈希清单；目录输入时按 sample_id 匹配文件名）。"""
    if os.path.isfile(gt_arg):
        return gt_arg
    for name in sorted(os.listdir(gt_arg)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(gt_arg, name)
        try:
            with open(path, encoding="utf-8") as handle:
                if json.load(handle).get("sample_id") == sample_id:
                    return path
        except (OSError, json.JSONDecodeError):
            continue
    return gt_arg


def dump_json(obj, path):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def ratio(numerator, denominator):
    """比率：分母为 0 时返回字符串 not_applicable（不得写 100%）。"""
    if not denominator:
        return "not_applicable"
    return round6(numerator / denominator)


def classify_entry(entry):
    """帧分类规则：与 adaptive_sampler.classify_entry（任务 16）逐条一致。

    frame_status != analyzed → failed；object_found=true → confirmed/low_confidence
    （按 evidence_sufficient）；有 abstention_reason → abstained；否则 not_found。
    评分器内置同规则实现（运行期不依赖 Skill 代码，保证评分确定性）；
    与 Skill 规则的一致性由 test_temporal_ground_truth_scoring.py 断言。
    """
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    if isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
        return "abstained"
    return "not_found"


def gt_state_at(ground_truth, timestamp_ms):
    """GT 区间判定：普通段左闭右开 [start, end)；最后一段包含媒体终点。"""
    segments = ground_truth["segments"]
    for index, segment in enumerate(segments):
        start, end = segment["start_ms"], segment["end_ms"]
        if start <= timestamp_ms < end:
            return segment["state"]
        if index == len(segments) - 1 and timestamp_ms == end:
            return segment["state"]
    return None


def error_stats(errors):
    """边界误差统计（保留原始分母：匹配数）。"""
    if not errors:
        return {"matched_count": 0, "max_ms": "not_applicable", "min_ms": "not_applicable",
                "median_ms": "not_applicable", "mean_ms": "not_applicable"}
    return {
        "matched_count": len(errors),
        "max_ms": round3(max(errors)),
        "min_ms": round3(min(errors)),
        "median_ms": round3(statistics.median(errors)),
        "mean_ms": round3(statistics.fmean(errors)),
    }


# ---------------------------------------------------------------- 输入加载

def load_prediction_set(path):
    doc = load_json_file(path, "预测集合")
    if not isinstance(doc, dict):
        raise ScoringError("预测集合必须是 JSON 对象")
    if doc.get("schema_version") != PREDICTION_SET_SCHEMA_VERSION:
        raise ScoringError(
            f"不支持的预测集合 schema_version {doc.get('schema_version')!r}"
            f"（仅支持 {PREDICTION_SET_SCHEMA_VERSION}）")
    arms = doc.get("arms")
    if not isinstance(arms, list) or not arms:
        raise ScoringError("预测集合必须包含非空 arms[]")
    base_dir = os.path.dirname(os.path.abspath(path))
    normalized = {}
    for arm in arms:
        if not isinstance(arm, dict):
            raise ScoringError("预测集合 arms[] 元素必须是对象")
        arm_id = arm.get("arm_id")
        if not isinstance(arm_id, str) or not arm_id.strip():
            raise ScoringError("预测集合 arm 缺少合法 arm_id")
        samples = arm.get("samples")
        if not isinstance(samples, list):
            raise ScoringError(f"臂 {arm_id!r} 缺少 samples[]")
        entries = {}
        for sample in samples:
            if not isinstance(sample, dict):
                raise ScoringError(f"臂 {arm_id!r} 的 samples[] 元素必须是对象")
            sample_id = sample.get("sample_id")
            evidence_ref = sample.get("evidence")
            if not isinstance(sample_id, str) or not isinstance(evidence_ref, str):
                raise ScoringError(f"臂 {arm_id!r} 的样本缺少 sample_id/evidence")
            if sample_id in entries:
                raise ScoringError(f"臂 {arm_id!r} 内样本 {sample_id!r} 重复")
            entries[sample_id] = os.path.abspath(os.path.join(base_dir, evidence_ref))
        normalized[arm_id] = entries
    return doc, normalized


def load_comparison_spec(path):
    doc = load_json_file(path, "比较规格")
    if not isinstance(doc, dict):
        raise ScoringError("比较规格必须是 JSON 对象")
    if doc.get("schema_version") != COMPARISON_SCHEMA_VERSION:
        raise ScoringError(
            f"不支持的比较规格 schema_version {doc.get('schema_version')!r}"
            f"（仅支持 {COMPARISON_SCHEMA_VERSION}）")
    for field in ("comparison_id", "sample_ids", "arm_a", "arm_b", "fairness_attestation"):
        if field not in doc:
            raise ScoringError(f"比较规格缺少必填字段 {field!r}")
    sample_ids = doc["sample_ids"]
    if not isinstance(sample_ids, list) or not sample_ids:
        raise ScoringError("比较规格 sample_ids 必须是非空数组")
    for arm_key in ("arm_a", "arm_b"):
        arm = doc[arm_key]
        if not isinstance(arm, dict) or not isinstance(arm.get("arm_id"), str):
            raise ScoringError(f"比较规格 {arm_key} 必须是含 arm_id 的对象")
    if doc["arm_a"]["arm_id"] == doc["arm_b"]["arm_id"]:
        raise ScoringError("比较规格两臂 arm_id 必须不同")
    attestation = doc["fairness_attestation"]
    if not isinstance(attestation, dict):
        raise ScoringError("比较规格 fairness_attestation 必须是对象")
    for field in ("no_single_side_retry", "no_extra_context"):
        if not isinstance(attestation.get(field), bool):
            raise ScoringError(
                f"公平比较要求显式声明 fairness_attestation.{field} 为布尔值"
                "（不可从产物观测的条件由调用方显式声明；声明 false 时 fairness gate "
                "将失败并判 INVALID_COMPARISON）")
    return doc


# ---------------------------------------------------------------- 硬门

def run_hard_gates(sample, ground_truth, evidence, evidence_path, manifest_path):
    """评分前硬门；返回 (gates, errors)。gates 每项 {id, passed, detail}。"""
    gates = []
    errors = []
    sample_id = sample["sample_id"]
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))

    def gate(gate_id, passed, detail, error_code=None):
        gates.append({"id": gate_id, "passed": bool(passed), "detail": detail})
        if not passed:
            errors.append({"code": error_code or gate_id, "sample_id": sample_id,
                           "location": detail.get("location") if isinstance(detail, dict) else None,
                           "message": detail if isinstance(detail, str) else str(detail)})

    # G1 样本一致（manifest/GT/prediction-set 三方 sample_id 对齐在加载期保证；
    #    此处核验 evidence 文档形态与目标查询载体存在）
    target_query = evidence.get("target_query")
    gate("G1-sample-identity", isinstance(target_query, str) and bool(target_query.strip()),
         "evidence.target_query 存在且非空" if isinstance(target_query, str)
         else "evidence 缺少 target_query", "missing_prediction_field")

    # G2 媒体冻结：实际文件 SHA-256 == manifest == ground truth
    media_abs = os.path.abspath(os.path.join(manifest_dir, sample["media_path"]))
    if not os.path.isfile(media_abs):
        gate("G2-media-hash-freeze", False,
             f"媒体文件不存在: {validator.repo_relative(media_abs)}", "media_file_missing")
    else:
        actual_hash = sha256_of(media_abs)
        manifest_hash = sample.get("media_sha256")
        gt_hash = ground_truth.get("media_sha256")
        if actual_hash == manifest_hash == gt_hash:
            gate("G2-media-hash-freeze", True,
                 f"媒体 SHA-256 三方一致（manifest/GT/实际文件）: {actual_hash[:16]}…")
        else:
            gate("G2-media-hash-freeze", False, {
                "location": f"samples[{sample_id}].media_sha256",
                "actual": actual_hash, "manifest": manifest_hash, "ground_truth": gt_hash,
                "message": "媒体 SHA-256 不一致（manifest / GT / 实际文件）",
            }, "media_hash_mismatch")

    # G3 目标查询一致
    manifest_query = sample.get("target_query")
    gt_query = ground_truth.get("target_query")
    if manifest_query == gt_query == target_query:
        gate("G3-target-query", True, "target_query 三方一致（manifest/GT/evidence）")
    else:
        gate("G3-target-query", False, {
            "location": f"samples[{sample_id}].target_query",
            "manifest": manifest_query, "ground_truth": gt_query,
            "evidence": target_query, "message": "target_query 不一致",
        }, "target_query_mismatch")

    # G4 媒体时长一致
    manifest_duration = sample.get("media_duration_ms")
    gt_duration = ground_truth.get("media_duration_ms")
    evidence_duration = evidence.get("duration_ms")
    if (isinstance(evidence_duration, (int, float)) and not isinstance(evidence_duration, bool)
            and round3(manifest_duration) == round3(gt_duration) == round3(evidence_duration)):
        gate("G4-media-duration", True,
             f"媒体时长一致（manifest/GT/evidence）: {round3(evidence_duration)} ms")
    else:
        gate("G4-media-duration", False, {
            "location": f"samples[{sample_id}].media_duration_ms",
            "manifest": manifest_duration, "ground_truth": gt_duration,
            "evidence": evidence_duration, "message": "媒体时长不一致",
        }, "duration_mismatch")

    # G5 GT 时间线合法
    timeline_problems = validator.check_ground_truth_timeline(ground_truth)
    if not timeline_problems:
        gate("G5-ground-truth-timeline", True,
             "GT 时间线合法（排序/覆盖/不重叠/不留隙/正长度/相邻合并）")
    else:
        gate("G5-ground-truth-timeline", False, {
            "location": f"ground_truth[{sample_id}].segments",
            "problems": [item.as_dict() for item in timeline_problems],
            "message": "GT 时间线不合法",
        }, timeline_problems[0].code)

    # G6 预测时间戳位于媒体范围（空时间线是合法的极端空分母情形：跳过范围检查，
    #    由 semantic_score_status=not_applicable 处理）
    timeline = evidence.get("timeline")
    duration = evidence_duration if isinstance(evidence_duration, (int, float)) else None
    if isinstance(timeline, list) and duration is not None:
        if not timeline:
            gate("G6-prediction-timestamps-in-range", True,
                 "时间线为空：无采样点（语义评分将置 not_applicable）")
        else:
            out_of_range = [entry.get("timestamp_ms") for entry in timeline
                            if not isinstance(entry, dict)
                            or not isinstance(entry.get("timestamp_ms"), (int, float))
                            or isinstance(entry.get("timestamp_ms"), bool)
                            or entry["timestamp_ms"] < 0 or entry["timestamp_ms"] > duration]
            if not out_of_range:
                gate("G6-prediction-timestamps-in-range", True,
                     f"全部 {len(timeline)} 个采样时间戳位于 [0, {round3(duration)}] ms")
            else:
                gate("G6-prediction-timestamps-in-range", False, {
                    "location": f"evidence[{sample_id}].timeline",
                    "out_of_range": out_of_range[:10],
                    "message": "存在越界采样时间戳",
                }, "prediction_timestamp_out_of_range")
    else:
        gate("G6-prediction-timestamps-in-range", False,
             "evidence.timeline 必须是数组且 duration_ms 可读", "missing_prediction_field")

    # G7 provenance 自洽（实际调用数 / 预算 / 时间戳 / 五类计数复算）
    provenance_problems = check_provenance_consistency(evidence)
    if not provenance_problems:
        gate("G7-provenance-self-consistency", True,
             "provenance 自洽（调用数=新鲜调用=时间线条目；预算未超；"
             "时间戳集合一致；五类计数复算一致）")
    else:
        gate("G7-provenance-self-consistency", False, {
            "location": f"evidence[{sample_id}].sampling_provenance",
            "problems": provenance_problems,
            "message": "provenance 自洽检查失败",
        }, provenance_problems[0]["code"])

    # G8 预测形态受支持（单来源文档）
    if "timeline" in evidence and "global_timeline" not in evidence:
        gate("G8-prediction-shape", True, "单来源时序证据文档（顶层 timeline）")
    else:
        gate("G8-prediction-shape", False, {
            "location": f"evidence[{sample_id}]",
            "message": "v1 评分器仅支持单来源 temporal-evidence 文档"
                       "（多来源 global_timeline 不支持）",
        }, "unsupported_prediction_shape")

    return gates, errors


def check_provenance_consistency(evidence):
    """G7：调用数/预算/时间戳/五类计数自洽；返回问题列表（空 = 通过）。"""
    problems = []
    timeline = evidence.get("timeline")
    provenance = evidence.get("sampling_provenance")
    temporal_evidence = evidence.get("temporal_evidence")
    if not isinstance(timeline, list) or not isinstance(provenance, dict) \
            or not isinstance(temporal_evidence, dict):
        return [{"code": "missing_prediction_field",
                 "message": "evidence 缺少 timeline/sampling_provenance/temporal_evidence"}]
    if evidence.get("schema_version") not in SUPPORTED_EVIDENCE_VERSIONS:
        problems.append({"code": "unsupported_evidence_version",
                         "message": f"不支持的 temporal-evidence schema_version "
                                    f"{evidence.get('schema_version')!r}"
                                    f"（支持 {list(SUPPORTED_EVIDENCE_VERSIONS)}）"})
    strategy = evidence.get("sampling_strategy")
    if strategy not in STRATEGIES:
        problems.append({"code": "invalid_strategy",
                         "message": f"sampling_strategy 必须属于 {list(STRATEGIES)}，"
                                    f"得到 {strategy!r}"})
    decisions = provenance.get("decisions")
    if not isinstance(decisions, list):
        problems.append({"code": "provenance_inconsistent",
                         "message": "sampling_provenance.decisions 必须是数组"})
        return problems
    fresh_calls = [item for item in decisions if item.get("cache_status") == "fresh_call"]
    actual = provenance.get("actual_model_calls")
    if not isinstance(actual, int) or isinstance(actual, bool):
        problems.append({"code": "provenance_inconsistent",
                         "message": f"actual_model_calls 必须为整数，得到 {actual!r}"})
        return problems
    if actual != len(fresh_calls):
        problems.append({"code": "provenance_inconsistent",
                         "message": f"actual_model_calls({actual}) 与 fresh_call 决策数"
                                    f"({len(fresh_calls)}) 不一致"})
    resource_blocked = provenance.get("resource_blocked") is True
    natures = [entry.get("evidence_nature") for entry in timeline]
    if resource_blocked:
        if actual != 0:
            problems.append({"code": "provenance_inconsistent",
                             "message": f"资源阻塞时真实调用必须为 0，得到 {actual}"})
        if any(nature != "backend_not_called" for nature in natures):
            problems.append({"code": "provenance_inconsistent",
                             "message": "资源阻塞时全部时间线条目必须为 backend_not_called"})
    else:
        if actual != len(timeline):
            problems.append({"code": "provenance_inconsistent",
                             "message": f"actual_model_calls({actual}) 与时间线条目数"
                                        f"({len(timeline)}) 不一致（每个已分析采样点一次调用）"})
        allowed = ("real_model_output", "backend_call_failed", "constructed_fixture_evidence")
        bad = sorted({nature for nature in natures if nature not in allowed})
        if bad:
            problems.append({"code": "provenance_inconsistent",
                             "message": f"时间线条目 evidence_nature 非法: {bad}"})
    configured = provenance.get("configured_budget")
    if configured is not None:
        if not isinstance(configured, int) or isinstance(configured, bool) or configured < 1:
            problems.append({"code": "provenance_inconsistent",
                             "message": f"configured_budget 必须为正整数，得到 {configured!r}"})
        elif actual > configured:
            problems.append({"code": "provenance_inconsistent",
                             "message": f"actual_model_calls({actual}) 超出 configured_budget"
                                        f"({configured})"})
    analyzed = provenance.get("analyzed_timestamps")
    expected_ts = sorted({round3(entry["timestamp_ms"]) for entry in timeline
                          if isinstance(entry, dict)
                          and isinstance(entry.get("timestamp_ms"), (int, float))
                          and not isinstance(entry.get("timestamp_ms"), bool)})
    if not isinstance(analyzed, list) or sorted(round3(item) for item in analyzed) != expected_ts:
        problems.append({"code": "provenance_inconsistent",
                         "message": "analyzed_timestamps 与时间线时间戳集合不一致"})
    recomputed = {name: 0 for name in EVIDENCE_CLASSES}
    for entry in timeline:
        recomputed[classify_entry(entry)] += 1
    reported = temporal_evidence.get("class_counts")
    if not isinstance(reported, dict) or any(
            reported.get(name) != recomputed[name] for name in EVIDENCE_CLASSES):
        problems.append({"code": "provenance_inconsistent",
                         "message": f"五类计数复算不一致：评分器复算 {recomputed}，"
                                    f"产物自报 {reported}"})
    reported_calls = temporal_evidence.get("actual_model_calls")
    if reported_calls != actual:
        problems.append({"code": "provenance_inconsistent",
                         "message": f"temporal_evidence.actual_model_calls({reported_calls}) "
                                    f"与 provenance({actual}) 不一致"})
    return problems


# ---------------------------------------------------------------- 语义评分

def metric_for(gt_state, pred_class):
    if gt_state in GT_DETERMINATE_STATES:
        if pred_class in DECISIVE_PRED_CLASSES:
            return "correct_decisive" if pred_class == gt_state else "incorrect_decisive"
        if pred_class in NON_DECISIVE_PRED_CLASSES:
            return "abstention_on_determinate"
        return "failed_on_determinate"
    # gt_state == "uncertain"
    if pred_class in NON_DECISIVE_PRED_CLASSES:
        return "appropriate_abstention"
    if pred_class in DECISIVE_PRED_CLASSES:
        return "overclaim_on_uncertain"
    return "failed_on_uncertain"


def score_sample_points(timeline, ground_truth):
    counts = {name: 0 for name in SEVEN_METRICS}
    rows = []
    determinate_total = 0
    uncertain_total = 0
    for entry in sorted(timeline, key=lambda item: item["timestamp_ms"]):
        pred_class = classify_entry(entry)
        state = gt_state_at(ground_truth, entry["timestamp_ms"])
        metric = metric_for(state, pred_class)
        counts[metric] += 1
        if state in GT_DETERMINATE_STATES:
            determinate_total += 1
        else:
            uncertain_total += 1
        rows.append({"timestamp_ms": round3(entry["timestamp_ms"]),
                     "prediction_class": pred_class, "ground_truth_state": state,
                     "metric": metric})
    total = len(rows)
    metrics = {}
    for name in SEVEN_METRICS:
        # 每项比率的分母取对应类别分母：determinate 指标用 determinate 采样数，
        # uncertain 指标用 uncertain 采样数；分母为 0 → not_applicable
        denominator = determinate_total if name in (
            "correct_decisive", "incorrect_decisive", "abstention_on_determinate",
            "failed_on_determinate") else uncertain_total
        metrics[name] = {"passed": counts[name], "total": denominator,
                         "ratio": ratio(counts[name], denominator)}
    return {
        "denominator_analyzed_samples": total,
        "denominator_determinate_samples": determinate_total,
        "denominator_uncertain_samples": uncertain_total,
        "metrics": metrics,
        "per_sample_rows": rows,
    }


def score_events(timeline, ground_truth):
    samples = [(round3(entry["timestamp_ms"]), classify_entry(entry))
               for entry in sorted(timeline, key=lambda item: item["timestamp_ms"])]
    segments = ground_truth["segments"]

    def classes_inside(segment):
        start, end = segment["start_ms"], segment["end_ms"]
        inside = []
        for index, (timestamp, _) in enumerate(samples):
            last = index == len(segments) - 1
            if start <= timestamp < end or (last and timestamp == end):
                inside.append(samples[index][1])
        return inside

    confirmed_total = 0
    confirmed_covered = 0
    not_found_total = 0
    not_found_covered = 0
    uncertain_segments = []
    for segment in segments:
        inside = classes_inside(segment)
        if segment["state"] == "confirmed":
            confirmed_total += 1
            if "confirmed" in inside:
                confirmed_covered += 1
        elif segment["state"] == "not_found":
            not_found_total += 1
            if "not_found" in inside:
                not_found_covered += 1
        else:  # uncertain
            uncertain_segments.append({
                "start_ms": round3(segment["start_ms"]),
                "end_ms": round3(segment["end_ms"]),
                "reached": bool(inside),
                "sample_count_inside": len(inside),
                "appropriate_abstention_achieved": any(
                    cls in NON_DECISIVE_PRED_CLASSES for cls in inside),
            })
    unreached_uncertain = sum(1 for item in uncertain_segments if not item["reached"])
    return {
        "gt_confirmed_segments": confirmed_total,
        "covered_confirmed_events": confirmed_covered,
        "missed_confirmed_events": confirmed_total - confirmed_covered,
        "gt_not_found_segments": not_found_total,
        "covered_not_found_segments": not_found_covered,
        "missed_not_found_segments": not_found_total - not_found_covered,
        "gt_uncertain_segments": len(uncertain_segments),
        "uncertain_segments": uncertain_segments,
        "unreached_uncertain_segments": unreached_uncertain,
    }


def direction_compatible(gt_state, pred_class):
    """边界方向兼容：GT 确定状态要求预测同类确定类别；
    GT uncertain 要求预测为非确定类别（abstained/low_confidence/failed）。
    decisive→decisive 不得匹配涉及 uncertain 的 GT 边界。"""
    if gt_state == "uncertain":
        return pred_class in NON_DECISIVE_PRED_CLASSES or pred_class == "failed"
    return pred_class == gt_state


def maximum_matching(num_left, candidates):
    """Kuhn 增广路最大二分匹配（确定性：左侧按序、候选按预定序）。"""
    match_left = {}
    match_right = {}

    def augment(left, visited):
        for right in candidates[left]:
            if right in visited:
                continue
            visited.add(right)
            if right not in match_right or augment(match_right[right], visited):
                match_right[right] = left
                match_left[left] = right
                return True
        return False

    for left in range(num_left):
        augment(left, set())
    return match_left, match_right


def score_boundaries(timeline, ground_truth, evidence):
    segments = ground_truth["segments"]
    boundaries = []
    for index in range(len(segments) - 1):
        boundaries.append({
            "at_ms": round3(segments[index + 1]["start_ms"]),
            "from_state": segments[index]["state"],
            "to_state": segments[index + 1]["state"],
        })
    transitions = evidence.get("temporal_evidence", {}).get("state_transitions")
    if not isinstance(transitions, list):
        transitions = []
    normalized_transitions = []
    for index, transition in enumerate(transitions):
        if not isinstance(transition, dict):
            continue
        left, right = transition.get("left_ms"), transition.get("right_ms")
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            continue
        width = transition.get("uncertainty_width_ms")
        if not isinstance(width, (int, float)) or isinstance(width, bool):
            width = right - left
        normalized_transitions.append({
            "index": index, "left_ms": round3(left), "right_ms": round3(right),
            "from_class": transition.get("from_class"),
            "to_class": transition.get("to_class"),
            "uncertainty_width_ms": round3(width),
        })
    normalized_transitions.sort(key=lambda item: (item["uncertainty_width_ms"],
                                                  item["left_ms"], item["index"]))
    candidates = []
    for boundary in boundaries:
        boundary_candidates = []
        for transition in normalized_transitions:
            if not (transition["left_ms"] <= boundary["at_ms"] <= transition["right_ms"]):
                continue
            if (direction_compatible(boundary["from_state"], transition["from_class"])
                    and direction_compatible(boundary["to_state"], transition["to_class"])):
                boundary_candidates.append(transition["index"])
        candidates.append(boundary_candidates)
    match_left, match_right = maximum_matching(len(boundaries), candidates)
    transition_by_index = {item["index"]: item for item in normalized_transitions}

    tolerance = ground_truth["boundary_tolerance_ms"]
    matched = []
    for boundary_index, boundary in enumerate(boundaries):
        transition_index = match_left.get(boundary_index)
        if transition_index is None:
            continue
        transition = transition_by_index[transition_index]
        midpoint = round3((transition["left_ms"] + transition["right_ms"]) / 2.0)
        error = round3(abs(midpoint - boundary["at_ms"]))
        matched.append({
            "gt_boundary_at_ms": boundary["at_ms"],
            "gt_from_state": boundary["from_state"],
            "gt_to_state": boundary["to_state"],
            "predicted_transition_index": transition_index,
            "bracket_left_ms": transition["left_ms"],
            "bracket_right_ms": transition["right_ms"],
            "bracket_width_ms": transition["uncertainty_width_ms"],
            "bracket_midpoint_ms": midpoint,
            "midpoint_abs_error_ms": error,
            "within_tolerance": bool(error <= tolerance),
        })
    matched_boundary_times = {item["gt_boundary_at_ms"] for item in matched}
    matched_transition_indices = {item["predicted_transition_index"] for item in matched}
    all_transition_indices = {item["index"] for item in normalized_transitions}
    errors = [item["midpoint_abs_error_ms"] for item in matched]
    stats = error_stats(errors)
    within_tolerance = sum(1 for item in matched if item["within_tolerance"])
    return {
        "gt_boundaries_total": len(boundaries),
        "matched_boundaries": len(matched),
        "missed_gt_boundaries": len(boundaries) - len(matched),
        "unmatched_predicted_transitions": len(normalized_transitions) - len(matched),
        "within_tolerance_boundaries": within_tolerance,
        "boundary_tolerance_ms": round3(tolerance),
        "boundary_error_stats": stats,
        "matched_boundary_details": matched,
        "gt_boundaries": boundaries,
        "predicted_transitions_total": len(normalized_transitions),
        "matched_gt_boundary_times": sorted(matched_boundary_times),
        "unmatched_predicted_transition_indices": sorted(
            all_transition_indices - matched_transition_indices),
    }


def score_efficiency(evidence, sample_points, events, boundaries):
    provenance = evidence.get("sampling_provenance", {})
    timing = provenance.get("timing", {}) if isinstance(provenance.get("timing"), dict) else {}
    actual_calls = provenance.get("actual_model_calls")
    correct_decisive = sample_points["metrics"]["correct_decisive"]["passed"]
    covered_events = events["covered_confirmed_events"]
    matched_boundaries = boundaries["matched_boundaries"]
    return {
        "configured_budget": provenance.get("configured_budget"),
        "actual_model_calls": actual_calls,
        "unique_analyzed_timestamps": len(provenance.get("analyzed_timestamps") or []),
        "reused_evidence_count": provenance.get("reused_evidence_count"),
        "duplicate_skips": len(provenance.get("skipped_duplicate_timestamps") or []),
        "budget_exhausted": provenance.get("budget_exhausted"),
        "stop_reasons": provenance.get("stop_reasons"),
        "timing": {
            "extraction_ms": timing.get("extraction_ms"),
            "analysis_ms": timing.get("analysis_ms"),
            "aggregation_ms": timing.get("aggregation_ms"),
            "total_ms": timing.get("total_ms"),
        },
        "calls_per_correct_decisive_sample": ratio(actual_calls, correct_decisive),
        "calls_per_covered_confirmed_event": ratio(actual_calls, covered_events),
        "calls_per_matched_boundary": ratio(actual_calls, matched_boundaries),
        "caveat": "效率指标不抵消语义错误：调用少不等于效果好",
    }


def known_limitations_for(sample, evidence):
    limitations = [
        "completed（execution_status）不等于语义正确；语义正确只由七类计数定义",
        "时序结论是采样证据支持的结论，不是连续跟踪真值；采样点之间不断言连续存在",
        "单次运行 + 小样本：不构成统计显著性，不得外推",
    ]
    if sample.get("source_type") == "technical_fixture":
        limitations.append("technical_fixture 为合成技术测试输入；不得外推为真实仓储/园区准确率")
    if evidence.get("evidence_nature") == "constructed_fixture_evidence":
        limitations.append("构造证据（非模型输出）：调用数为分析调用计数，不是真实视觉调用")
    return limitations


def score_sample(sample, ground_truth, evidence, evidence_path, manifest_path,
                 prediction_set_path, ground_truth_path, arm_id):
    """评分单个 (sample, arm)。"""
    gates, errors = run_hard_gates(sample, ground_truth, evidence, evidence_path,
                                   manifest_path)
    all_passed = not errors
    timeline = evidence.get("timeline") if isinstance(evidence.get("timeline"), list) else []
    provenance = evidence.get("sampling_provenance", {})
    summary = evidence.get("summary", {}) if isinstance(evidence.get("summary"), dict) else {}

    input_hashes = {
        "manifest": {"path": validator.repo_relative(manifest_path),
                     "sha256": sha256_of(manifest_path)},
        "prediction_set": {"path": validator.repo_relative(prediction_set_path),
                           "sha256": sha256_of(prediction_set_path)},
        "ground_truth": {"path": validator.repo_relative(ground_truth_path),
                         "sha256": sha256_of(ground_truth_path)},
        "prediction_evidence": {"path": validator.repo_relative(evidence_path),
                                "sha256": sha256_of(evidence_path)},
        "media": {"path": sample["media_path"],
                  "sha256": sample.get("media_sha256")},
    }

    score = {
        "schema_version": SCORE_SCHEMA_VERSION,
        "scorer": SCORER_NAME,
        "scorer_version": SCORER_VERSION,
        "pack_id": None,
        "sample_id": sample["sample_id"],
        "arm_id": arm_id,
        "split": sample.get("split"),
        "source_type": sample.get("source_type"),
        "execution_status": summary.get("overall_status"),
        "semantic_score_status": "scored" if all_passed else "invalid_input",
        "validation": {
            "hard_gates": gates,
            "all_passed": all_passed,
            "errors": errors,
        },
        "prediction_summary": {
            "strategy": evidence.get("sampling_strategy"),
            "evidence_nature": evidence.get("evidence_nature"),
            "input_nature": evidence.get("input_nature"),
            "sampled_frames": evidence.get("sampled_frames"),
            "duration_ms": evidence.get("duration_ms"),
            "target_query": evidence.get("target_query"),
            "backend_model": (evidence.get("backend") or {}).get("model"),
            "vision_backend": (evidence.get("backend") or {}).get("vision_backend"),
        },
        "known_limitations": known_limitations_for(sample, evidence),
        "input_hashes": input_hashes,
    }

    if all_passed and timeline:
        sample_points = score_sample_points(timeline, ground_truth)
        events = score_events(timeline, ground_truth)
        boundaries = score_boundaries(timeline, ground_truth, evidence)
        efficiency = score_efficiency(evidence, sample_points, events, boundaries)
        score["sample_point_scores"] = sample_points
        score["event_scores"] = events
        score["boundary_scores"] = boundaries
        score["efficiency"] = efficiency
        if sample.get("split") == "holdout":
            score["ground_truth"] = {
                "included": False,
                "holdout_gt_excluded": True,
                "gt_sha256": input_hashes["ground_truth"]["sha256"],
                "gt_segment_count": len(ground_truth["segments"]),
                "gt_states_digest": sha256_of_text(json.dumps(
                    [segment["state"] for segment in ground_truth["segments"]],
                    ensure_ascii=False)),
                "note": "holdout Ground Truth 内容不进入任何输出文件",
            }
        else:
            score["ground_truth"] = {
                "included": True,
                "gt_sha256": input_hashes["ground_truth"]["sha256"],
                "annotation_version": ground_truth.get("annotation_version"),
                "boundary_tolerance_ms": round3(ground_truth["boundary_tolerance_ms"]),
                "segment_count": len(ground_truth["segments"]),
                "states": [segment["state"] for segment in ground_truth["segments"]],
                "boundary_count": len(ground_truth["segments"]) - 1,
            }
        revisions_after_run = [item for item in ground_truth.get("revision_history", [])
                               if item.get("after_model_run")]
        if revisions_after_run:
            score["warnings"] = [{
                "code": "ground_truth_revised_after_model_run",
                "message": f"{len(revisions_after_run)} 项标签修订发生在模型运行之后"
                           "（公平比较将判 INVALID_COMPARISON）",
            }]
    elif all_passed and not timeline:
        score["semantic_score_status"] = "not_applicable"
        score["sample_point_scores"] = {
            "denominator_analyzed_samples": 0,
            "denominator_determinate_samples": 0,
            "denominator_uncertain_samples": 0,
            "metrics": {name: {"passed": 0, "total": 0, "ratio": "not_applicable"}
                        for name in SEVEN_METRICS},
            "per_sample_rows": [],
        }
        score["event_scores"] = {
            "gt_confirmed_segments": len([s for s in ground_truth["segments"]
                                          if s["state"] == "confirmed"]),
            "covered_confirmed_events": 0,
            "missed_confirmed_events": 0,
            "gt_not_found_segments": 0, "covered_not_found_segments": 0,
            "missed_not_found_segments": 0, "gt_uncertain_segments": 0,
            "uncertain_segments": [], "unreached_uncertain_segments": 0,
            "note": "时间线为空：无已分析采样点，语义评分 not_applicable",
        }
        score["boundary_scores"] = {
            "gt_boundaries_total": len(ground_truth["segments"]) - 1,
            "matched_boundaries": 0, "missed_gt_boundaries": len(ground_truth["segments"]) - 1,
            "unmatched_predicted_transitions": 0, "within_tolerance_boundaries": 0,
            "boundary_error_stats": error_stats([]),
            "matched_boundary_details": [], "gt_boundaries": [],
            "predicted_transitions_total": 0,
        }
        score["efficiency"] = score_efficiency(evidence, score["sample_point_scores"],
                                               score["event_scores"],
                                               score["boundary_scores"])
    return score


# ---------------------------------------------------------------- Markdown 输出

def metric_row(name, metric):
    return f"| {name} | {metric['passed']} | {metric['total']} | {metric['ratio']} |"


def render_score_md(score):
    lines = []
    lines.append(f"# 语义评分 — {score['sample_id']} / {score['arm_id']}")
    lines.append("")
    lines.append(f"- pack sample: `{score['sample_id']}`（split={score['split']}, "
                 f"source_type={score['source_type']}）")
    lines.append(f"- **execution_status**: `{score['execution_status']}`（流水线是否完成）")
    lines.append(f"- **semantic_score_status**: `{score['semantic_score_status']}`"
                 "（语义评分是否可算；completed ≠ 语义正确）")
    lines.append(f"- 预测策略: `{score['prediction_summary']['strategy']}`；"
                 f"evidence_nature: `{score['prediction_summary']['evidence_nature']}`；"
                 f"采样点: {score['prediction_summary']['sampled_frames']}")
    lines.append("")
    lines.append("## 输入验证（硬门）")
    lines.append("")
    lines.append("| 门 | 通过 | 说明 |")
    lines.append("| --- | --- | --- |")
    for gate in score["validation"]["hard_gates"]:
        detail = gate["detail"]
        if isinstance(detail, dict):
            detail = detail.get("message", json.dumps(detail, ensure_ascii=False))
        lines.append(f"| {gate['id']} | {'是' if gate['passed'] else '否'} | {detail} |")
    lines.append("")
    if not score["validation"]["all_passed"]:
        lines.append("## 结构化错误（未计分）")
        lines.append("")
        for error in score["validation"]["errors"]:
            lines.append(f"- `{error['code']}`: {error['message']}")
        lines.append("")
    if "sample_point_scores" in score and score["semantic_score_status"] == "scored":
        points = score["sample_point_scores"]
        lines.append("## 采样点语义评分")
        lines.append("")
        lines.append(f"- 分母（已分析采样点）: {points['denominator_analyzed_samples']}"
                     f"（determinate {points['denominator_determinate_samples']} / "
                     f"uncertain {points['denominator_uncertain_samples']}）")
        lines.append("")
        lines.append("| 指标 | 通过 | 总数 | 比率 |")
        lines.append("| --- | --- | --- | --- |")
        for name in SEVEN_METRICS:
            lines.append(metric_row(name, points["metrics"][name]))
        lines.append("")
        events = score["event_scores"]
        lines.append("## 事件覆盖")
        lines.append("")
        lines.append(f"- GT confirmed segments: {events['gt_confirmed_segments']}；"
                     f"覆盖: {events['covered_confirmed_events']}；"
                     f"漏掉: {events['missed_confirmed_events']}")
        lines.append(f"- GT not_found segments: {events['gt_not_found_segments']}；"
                     f"覆盖: {events['covered_not_found_segments']}；"
                     f"漏掉: {events['missed_not_found_segments']}")
        lines.append(f"- GT uncertain segments: {events['gt_uncertain_segments']}；"
                     f"未触达: {events['unreached_uncertain_segments']}")
        for item in events["uncertain_segments"]:
            lines.append(f"  - [{item['start_ms']}, {item['end_ms']}] ms："
                         f"reached={item['reached']}，"
                         f"appropriate_abstention={item['appropriate_abstention_achieved']}，"
                         f"段内采样点={item['sample_count_inside']}")
        lines.append("")
        boundaries = score["boundary_scores"]
        lines.append("## 状态转换与边界")
        lines.append("")
        lines.append(f"- GT 边界总数: {boundaries['gt_boundaries_total']}；"
                     f"匹配: {boundaries['matched_boundaries']}；"
                     f"漏掉: {boundaries['missed_gt_boundaries']}；"
                     f"多余预测 transition: {boundaries['unmatched_predicted_transitions']}")
        lines.append(f"- 容差（{boundaries['boundary_tolerance_ms']} ms）内边界: "
                     f"{boundaries['within_tolerance_boundaries']}")
        stats = boundaries["boundary_error_stats"]
        lines.append(f"- 边界误差（分母=匹配数 {stats['matched_count']}）："
                     f"max={stats['max_ms']} min={stats['min_ms']} "
                     f"median={stats['median_ms']} mean={stats['mean_ms']}")
        if boundaries["matched_boundary_details"]:
            lines.append("")
            lines.append("| GT 边界 (ms) | 方向 | bracket [left, right] | width | midpoint | 误差 | 容差内 |")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |")
            for item in boundaries["matched_boundary_details"]:
                lines.append(
                    f"| {item['gt_boundary_at_ms']} "
                    f"| {item['gt_from_state']}→{item['gt_to_state']} "
                    f"| [{item['bracket_left_ms']}, {item['bracket_right_ms']}] "
                    f"| {item['bracket_width_ms']} | {item['bracket_midpoint_ms']} "
                    f"| {item['midpoint_abs_error_ms']} | {item['within_tolerance']} |")
        lines.append("")
        efficiency = score["efficiency"]
        lines.append("## 效率（不抵消语义错误）")
        lines.append("")
        lines.append(f"- configured_budget={efficiency['configured_budget']}；"
                     f"actual_model_calls={efficiency['actual_model_calls']}；"
                     f"unique_analyzed_timestamps={efficiency['unique_analyzed_timestamps']}；"
                     f"reused_evidence={efficiency['reused_evidence_count']}；"
                     f"duplicate_skips={efficiency['duplicate_skips']}；"
                     f"budget_exhausted={efficiency['budget_exhausted']}")
        timing = efficiency["timing"]
        lines.append(f"- 耗时: total={timing['total_ms']} ms"
                     f"（extraction={timing['extraction_ms']}，"
                     f"analysis={timing['analysis_ms']}，"
                     f"aggregation={timing['aggregation_ms']}）")
        lines.append(f"- 每正确 decisive 采样调用: "
                     f"{efficiency['calls_per_correct_decisive_sample']}；"
                     f"每覆盖 confirmed event 调用: "
                     f"{efficiency['calls_per_covered_confirmed_event']}；"
                     f"每匹配边界调用: {efficiency['calls_per_matched_boundary']}")
        lines.append("")
        gt = score["ground_truth"]
        if gt.get("included"):
            lines.append("## Ground Truth（dev，可审计）")
            lines.append("")
            lines.append(f"- annotation_version={gt['annotation_version']}；"
                         f"段数={gt['segment_count']}；边界数={gt['boundary_count']}；"
                         f"容差={gt['boundary_tolerance_ms']} ms")
            lines.append(f"- 状态序列: {' → '.join(gt['states'])}")
        else:
            lines.append("## Ground Truth（holdout，内容不进入输出）")
            lines.append("")
            lines.append(f"- gt_sha256={gt['gt_sha256'][:16]}…；"
                         f"gt_segment_count={gt['gt_segment_count']}")
        lines.append("")
    lines.append("## 输入文件哈希")
    lines.append("")
    for role, item in score["input_hashes"].items():
        lines.append(f"- {role}: `{item['path']}` → `{item['sha256'][:16]}…`")
    lines.append("")
    lines.append("## 已知限制")
    lines.append("")
    for item in score["known_limitations"]:
        lines.append(f"- {item}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 比较

FAIRNESS_CONDITIONS = (
    "same_sample_ids", "same_media_hash", "same_target_query", "same_ground_truth_version",
    "same_model_and_backend", "same_call_budget", "no_single_side_retry_or_extra_context",
    "prediction_input_complete", "same_evidence_nature", "ground_truth_not_revised_after_run",
)


def aggregate_metrics(per_sample_scores):
    """把每样本评分聚合为比较用指标（ sums + 跨样本边界误差统计）。"""
    aggregate = {
        "correct_decisive": 0, "incorrect_decisive": 0, "abstention_on_determinate": 0,
        "failed_on_determinate": 0, "appropriate_abstention": 0,
        "overclaim_on_uncertain": 0, "failed_on_uncertain": 0,
        "denominator_analyzed_samples": 0,
        "gt_confirmed_segments": 0, "covered_confirmed_events": 0,
        "missed_confirmed_events": 0,
        "gt_boundaries_total": 0, "matched_boundaries": 0, "missed_gt_boundaries": 0,
        "unmatched_predicted_transitions": 0, "within_tolerance_boundaries": 0,
        "unreached_uncertain_segments": 0,
        "actual_model_calls": 0,
    }
    errors = []
    for score in per_sample_scores:
        points = score.get("sample_point_scores")
        if not points:
            continue
        for name in SEVEN_METRICS:
            aggregate[name] += points["metrics"][name]["passed"]
        aggregate["denominator_analyzed_samples"] += points["denominator_analyzed_samples"]
        events = score.get("event_scores") or {}
        for key in ("gt_confirmed_segments", "covered_confirmed_events",
                    "missed_confirmed_events", "unreached_uncertain_segments"):
            aggregate[key] += events.get(key, 0)
        boundaries = score.get("boundary_scores") or {}
        for key in ("gt_boundaries_total", "matched_boundaries", "missed_gt_boundaries",
                    "unmatched_predicted_transitions", "within_tolerance_boundaries"):
            aggregate[key] += boundaries.get(key, 0)
        for item in boundaries.get("matched_boundary_details", []):
            errors.append(item["midpoint_abs_error_ms"])
        aggregate["actual_model_calls"] += (score.get("efficiency") or {}).get(
            "actual_model_calls") or 0
    aggregate["boundary_error_stats"] = error_stats(errors)
    return aggregate


def evaluate_fairness(comparison, manifest, ground_truths, arm_scores, evidence_docs,
                      evidence_docs_paths, manifest_path):
    """公平比较 gate；返回 (conditions, all_passed)。"""
    conditions = []
    arm_a_id = comparison["arm_a"]["arm_id"]
    arm_b_id = comparison["arm_b"]["arm_id"]
    sample_ids = comparison["sample_ids"]
    attestation = comparison["fairness_attestation"]

    def add(condition_id, passed, detail):
        conditions.append({"id": condition_id, "passed": bool(passed), "detail": detail})

    samples_by_id = {sample["sample_id"]: sample for sample in manifest["samples"]}

    # 1 相同 sample ID 集合
    a_ids = set(arm_scores[arm_a_id])
    b_ids = set(arm_scores[arm_b_id])
    expected = set(sample_ids)
    add("same_sample_ids", a_ids == b_ids == expected,
        f"两臂样本集合与比较规格一致（{len(expected)} 个）"
        if a_ids == b_ids == expected else
        f"样本集合不一致：arm_a={sorted(a_ids)} arm_b={sorted(b_ids)} "
        f"expected={sorted(expected)}")

    # 2 相同媒体哈希（同一 manifest 样本 + evidence.source_video 与 manifest 媒体同文件）
    media_ok = True
    media_detail = "两臂媒体文件与 manifest 一致"
    for sample_id in sample_ids:
        sample = samples_by_id.get(sample_id)
        if sample is None:
            media_ok = False
            media_detail = f"样本 {sample_id!r} 不在 manifest 中"
            break
        manifest_media = os.path.realpath(os.path.join(
            os.path.dirname(os.path.abspath(manifest_path)), sample["media_path"]))
        for arm_id in (arm_a_id, arm_b_id):
            evidence = evidence_docs.get((arm_id, sample_id))
            if evidence is None:
                continue
            source_video = resolve_source_video(
                evidence_docs_paths.get(arm_id, {}).get(sample_id),
                evidence.get("source_video"))
            if source_video is None or source_video != manifest_media:
                media_ok = False
                media_detail = (f"样本 {sample_id!r} 臂 {arm_id!r} 的 evidence.source_video "
                                f"与 manifest 媒体不是同一文件")
    add("same_media_hash", media_ok, media_detail)

    # 3 相同 target query
    queries = set()
    for arm_id in (arm_a_id, arm_b_id):
        for sample_id in sample_ids:
            score = arm_scores[arm_id].get(sample_id)
            if score:
                queries.add(score["prediction_summary"]["target_query"])
    add("same_target_query", len(queries) == 1,
        f"两臂 target_query 一致: {sorted(queries)}" if len(queries) == 1
        else f"target_query 不一致: {sorted(queries)}")

    # 4 相同 Ground Truth 版本
    versions = {ground_truths[sample_id].get("annotation_version")
                for sample_id in sample_ids if sample_id in ground_truths}
    add("same_ground_truth_version", len(versions) == 1,
        f"Ground Truth annotation_version 一致: {sorted(versions)}" if len(versions) == 1
        else f"Ground Truth 版本不一致: {sorted(versions)}")

    # 5 相同模型与后端
    models = set()
    backends = set()
    for arm_id in (arm_a_id, arm_b_id):
        for sample_id in sample_ids:
            score = arm_scores[arm_id].get(sample_id)
            if score:
                models.add(score["prediction_summary"]["backend_model"])
                backends.add(score["prediction_summary"]["vision_backend"])
    add("same_model_and_backend", len(models) == 1 and len(backends) == 1,
        f"模型/后端一致: {sorted(models)} / {sorted(backends)}"
        if len(models) == 1 and len(backends) == 1
        else f"模型或后端不一致: models={sorted(models, key=str)} "
             f"backends={sorted(backends, key=str)}")

    # 6 相同调用预算
    budgets = set()
    for arm_id in (arm_a_id, arm_b_id):
        for sample_id in sample_ids:
            score = arm_scores[arm_id].get(sample_id)
            if score:
                budgets.add((score.get("efficiency") or {}).get("configured_budget"))
    add("same_call_budget", len(budgets) == 1,
        f"两臂 configured_budget 一致: {sorted(budgets, key=str)}" if len(budgets) == 1
        else f"调用预算不一致: {sorted(budgets, key=str)}")

    # 7 没有单侧重试或额外上下文（调用方声明，不可从产物观测）
    declared = (attestation.get("no_single_side_retry") is True
                and attestation.get("no_extra_context") is True)
    add("no_single_side_retry_or_extra_context", declared,
        f"调用方声明（不可从产物观测）: no_single_side_retry="
        f"{attestation.get('no_single_side_retry')}, no_extra_context="
        f"{attestation.get('no_extra_context')}; 依据: "
        f"{attestation.get('attestation_basis', '<未提供>')}")
    # 8 prediction 输入完整（两臂每样本均存在且硬门全过）
    complete = True
    incomplete = []
    for arm_id in (arm_a_id, arm_b_id):
        for sample_id in sample_ids:
            score = arm_scores[arm_id].get(sample_id)
            if score is None:
                complete = False
                incomplete.append(f"{arm_id}/{sample_id}:missing")
            elif not score["validation"]["all_passed"]:
                complete = False
                incomplete.append(f"{arm_id}/{sample_id}:hard_gate_failed")
    add("prediction_input_complete", complete,
        "两臂全部样本的预测输入完整且硬门通过" if complete
        else f"输入不完整: {incomplete}")

    # 9 相同 evidence_nature（防止一臂真实调用一臂构造证据的伪比较）
    natures = set()
    for arm_id in (arm_a_id, arm_b_id):
        for sample_id in sample_ids:
            score = arm_scores[arm_id].get(sample_id)
            if score:
                natures.add(score["prediction_summary"]["evidence_nature"])
    add("same_evidence_nature", len(natures) == 1,
        f"两臂 evidence_nature 一致: {sorted(natures, key=str)}" if len(natures) == 1
        else f"evidence_nature 不一致（禁止真实/构造混合比较）: "
             f"{sorted(natures, key=str)}")

    # 10 GT 未在模型运行后修订
    revised = []
    for sample_id in sample_ids:
        gt = ground_truths.get(sample_id)
        if gt and any(item.get("after_model_run")
                      for item in gt.get("revision_history", [])):
            revised.append(sample_id)
    add("ground_truth_not_revised_after_run", not revised,
        "全部样本 GT 无模型运行后修订" if not revised
        else f"以下样本的 GT 在模型运行后修订（违反'看到结果后不改 ground truth'）: {revised}")

    return conditions, all(item["passed"] for item in conditions)


def compute_verdict(uniform_metrics, adaptive_metrics):
    """四类 verdict 判定（确定性；不预设结果）。"""
    non_regression = {
        "incorrect_decisive_not_worse": (
            adaptive_metrics["incorrect_decisive"] <= uniform_metrics["incorrect_decisive"]),
        "overclaim_on_uncertain_not_worse": (
            adaptive_metrics["overclaim_on_uncertain"]
            <= uniform_metrics["overclaim_on_uncertain"]),
        "missed_confirmed_events_not_worse": (
            adaptive_metrics["missed_confirmed_events"]
            <= uniform_metrics["missed_confirmed_events"]),
        "missed_gt_boundaries_not_worse": (
            adaptive_metrics["missed_gt_boundaries"]
            <= uniform_metrics["missed_gt_boundaries"]),
        "unreached_uncertain_not_worse": (
            adaptive_metrics["unreached_uncertain_segments"]
            <= uniform_metrics["unreached_uncertain_segments"]),
    }
    strict = []
    if adaptive_metrics["actual_model_calls"] < uniform_metrics["actual_model_calls"]:
        strict.append("fewer_model_calls")
    a_stats = adaptive_metrics["boundary_error_stats"]
    u_stats = uniform_metrics["boundary_error_stats"]
    if a_stats["matched_count"] >= 1 and u_stats["matched_count"] >= 1:
        if a_stats["max_ms"] < u_stats["max_ms"]:
            strict.append("smaller_max_boundary_error")
        if a_stats["mean_ms"] < u_stats["mean_ms"]:
            strict.append("smaller_mean_boundary_error")
    if adaptive_metrics["within_tolerance_boundaries"] > \
            uniform_metrics["within_tolerance_boundaries"]:
        strict.append("more_boundaries_within_tolerance")

    regressions = []
    if adaptive_metrics["incorrect_decisive"] > uniform_metrics["incorrect_decisive"]:
        regressions.append("more_incorrect_decisive")
    if adaptive_metrics["overclaim_on_uncertain"] > uniform_metrics["overclaim_on_uncertain"]:
        regressions.append("more_overclaim_on_uncertain")
    if adaptive_metrics["missed_confirmed_events"] > uniform_metrics["missed_confirmed_events"]:
        regressions.append("more_missed_confirmed_events")
    if adaptive_metrics["missed_gt_boundaries"] > uniform_metrics["missed_gt_boundaries"]:
        regressions.append("more_missed_gt_boundaries")
    if adaptive_metrics["unreached_uncertain_segments"] > \
            uniform_metrics["unreached_uncertain_segments"]:
        regressions.append("more_unreached_uncertain_segments")

    non_regression_ok = all(non_regression.values())
    strict_ok = bool(strict)
    if non_regression_ok and strict_ok:
        verdict = "IMPROVEMENT"
        reason = ("非回归条件全部满足，且至少一项严格更好"
                  f"（{strict}）")
    elif non_regression_ok and not strict_ok:
        verdict = "NO_IMPROVEMENT"
        reason = "非回归条件全部满足，但没有任何严格更好的项"
    elif not non_regression_ok and strict_ok:
        verdict = "TRADEOFF"
        reason = (f"有严格改进（{strict}）但非回归条件被违反（{regressions}）："
                  "省调用/缩边界的同时增加了漏检、过度断言或未触达 uncertain")
    else:
        verdict = "NO_IMPROVEMENT"
        reason = (f"没有严格改进，且非回归条件被违反（{regressions}）；"
                  "NO_IMPROVEMENT 不表示两臂等价，违反项已在差异字段完整披露")
    return {
        "verdict": verdict,
        "reason": reason,
        "reason_codes": strict + regressions,
        "strict_improvements": strict,
        "regressions": regressions,
        "non_regression_conditions": non_regression,
    }


def difference_table(uniform_metrics, adaptive_metrics):
    differences = {}
    for key in ("correct_decisive", "incorrect_decisive", "abstention_on_determinate",
                "failed_on_determinate", "appropriate_abstention",
                "overclaim_on_uncertain", "failed_on_uncertain",
                "denominator_analyzed_samples", "gt_confirmed_segments",
                "covered_confirmed_events", "missed_confirmed_events",
                "gt_boundaries_total", "matched_boundaries", "missed_gt_boundaries",
                "unmatched_predicted_transitions", "within_tolerance_boundaries",
                "unreached_uncertain_segments", "actual_model_calls"):
        differences[key] = {"uniform": uniform_metrics[key],
                            "adaptive": adaptive_metrics[key],
                            "delta_adaptive_minus_uniform": (
                                adaptive_metrics[key] - uniform_metrics[key])}
    for key in ("max_ms", "min_ms", "median_ms", "mean_ms", "matched_count"):
        differences[f"boundary_error_{key}"] = {
            "uniform": uniform_metrics["boundary_error_stats"][key],
            "adaptive": adaptive_metrics["boundary_error_stats"][key],
            "delta_adaptive_minus_uniform": (
                "not_applicable" if (adaptive_metrics["boundary_error_stats"][key]
                                     == "not_applicable"
                                     or uniform_metrics["boundary_error_stats"][key]
                                     == "not_applicable")
                else round3(adaptive_metrics["boundary_error_stats"][key]
                            - uniform_metrics["boundary_error_stats"][key])),
        }
    return differences


def render_comparison_md(comparison):
    lines = []
    lines.append(f"# 公平比较 — {comparison['comparison_id']}")
    lines.append("")
    lines.append(f"- 基线臂（arm_a）: `{comparison['arms']['baseline']['arm_id']}`；"
                 f"候选臂（arm_b）: `{comparison['arms']['candidate']['arm_id']}`")
    lines.append(f"- 样本: {', '.join(comparison['sample_ids'])}")
    lines.append("")
    lines.append("## Fairness gate")
    lines.append("")
    lines.append("| 条件 | 通过 | 说明 |")
    lines.append("| --- | --- | --- |")
    for condition in comparison["fairness_gate"]["conditions"]:
        lines.append(f"| {condition['id']} | {'是' if condition['passed'] else '否'} "
                     f"| {condition['detail']} |")
    lines.append("")
    lines.append(f"fairness gate 全部通过: {comparison['fairness_gate']['all_passed']}")
    lines.append("")
    lines.append("## 指标对比（aggregate）")
    lines.append("")
    lines.append("| 指标 | uniform（arm_a） | adaptive（arm_b） | Δ(adaptive−uniform) |")
    lines.append("| --- | --- | --- | --- |")
    for key, item in comparison["differences"].items():
        lines.append(f"| {key} | {item['uniform']} | {item['adaptive']} "
                     f"| {item['delta_adaptive_minus_uniform']} |")
    lines.append("")
    verdict = comparison["verdict"]
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**{verdict['verdict']}** — {verdict['reason']}")
    lines.append("")
    lines.append(f"- 严格更好项: {verdict['strict_improvements'] or '无'}")
    lines.append(f"- 回归项: {verdict['regressions'] or '无'}")
    lines.append(f"- 非回归条件: {json.dumps(verdict['non_regression_conditions'], ensure_ascii=False)}")
    lines.append("")
    lines.append("## 不得外推的声明")
    lines.append("")
    lines.append(f"- {comparison['no_extrapolation_statement']}")
    lines.append("")
    lines.append("## 逐样本指标")
    lines.append("")
    lines.append("| 样本 | uniform 正确 decisive | adaptive 正确 decisive | "
                 "uniform overclaim | adaptive overclaim | uniform 调用 | adaptive 调用 | "
                 "uniform 漏边界 | adaptive 漏边界 | uniform 未触达 uncertain | "
                 "adaptive 未触达 uncertain |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for row in comparison["per_sample_table"]:
        lines.append(
            f"| {row['sample_id']} | {row['uniform_correct_decisive']} "
            f"| {row['adaptive_correct_decisive']} "
            f"| {row['uniform_overclaim_on_uncertain']} "
            f"| {row['adaptive_overclaim_on_uncertain']} "
            f"| {row['uniform_calls']} | {row['adaptive_calls']} "
            f"| {row['uniform_missed_gt_boundaries']} "
            f"| {row['adaptive_missed_gt_boundaries']} "
            f"| {row['uniform_unreached_uncertain']} "
            f"| {row['adaptive_unreached_uncertain']} |")
    lines.append("")
    return "\n".join(lines)


def per_sample_row(sample_id, uniform_score, adaptive_score):
    def pick(score, path, default="not_applicable"):
        if score is None:
            return default
        node = score
        for key in path:
            node = (node or {}).get(key)
            if node is None:
                return default
        return node

    return {
        "sample_id": sample_id,
        "uniform_correct_decisive": pick(uniform_score, ["sample_point_scores", "metrics",
                                                         "correct_decisive", "passed"], 0),
        "adaptive_correct_decisive": pick(adaptive_score, ["sample_point_scores", "metrics",
                                                           "correct_decisive", "passed"], 0),
        "uniform_overclaim_on_uncertain": pick(uniform_score, ["sample_point_scores", "metrics",
                                                               "overclaim_on_uncertain",
                                                               "passed"], 0),
        "adaptive_overclaim_on_uncertain": pick(adaptive_score, ["sample_point_scores",
                                                                 "metrics",
                                                                 "overclaim_on_uncertain",
                                                                 "passed"], 0),
        "uniform_calls": pick(uniform_score, ["efficiency", "actual_model_calls"], 0),
        "adaptive_calls": pick(adaptive_score, ["efficiency", "actual_model_calls"], 0),
        "uniform_missed_gt_boundaries": pick(uniform_score, ["boundary_scores",
                                                             "missed_gt_boundaries"], 0),
        "adaptive_missed_gt_boundaries": pick(adaptive_score, ["boundary_scores",
                                                               "missed_gt_boundaries"], 0),
        "uniform_unreached_uncertain": pick(uniform_score, ["event_scores",
                                                            "unreached_uncertain_segments"], 0),
        "adaptive_unreached_uncertain": pick(adaptive_score, ["event_scores",
                                                              "unreached_uncertain_segments"], 0),
    }


# ---------------------------------------------------------------- 输出安全

def assert_output_safe(obj):
    """输出落盘前自检：不含凭据样式、不含绝对用户路径。"""
    text = json.dumps(obj, ensure_ascii=False)
    lowered = text.lower()
    for marker in CREDENTIAL_MARKERS:
        if marker in lowered:
            raise ScoringError(f"输出安全自检失败：疑似凭据内容 {marker!r}")
    for sensitive in ("/home/", "/root/", "/etc/", PROJECT_ROOT + os.sep):
        if sensitive in text:
            raise ScoringError(f"输出安全自检失败：包含敏感路径 {sensitive!r}")
    return True


# ---------------------------------------------------------------- 主流程

def main():
    parser = argparse.ArgumentParser(
        description="Evidence Pack 时间 Ground Truth 评分器（确定性、CPU-only、无模型调用）")
    parser.add_argument("--manifest", required=True, help="Evidence Pack manifest JSON 路径")
    parser.add_argument("--predictions", required=True, help="预测集合 JSON 路径")
    parser.add_argument("--ground-truth", required=True,
                        help="Ground Truth JSON 文件或目录（必显参数；"
                             "禁止从 README/历史 artifacts/目录猜测）")
    parser.add_argument("--out", required=True, help="输出目录（唯一写入位置）")
    parser.add_argument("--comparison", default=None,
                        help="可选：双臂公平比较规格 JSON（提供时输出 comparison.json/md）")
    args = parser.parse_args()

    for label, path in (("manifest", args.manifest), ("predictions", args.predictions),
                        ("ground truth", args.ground_truth)):
        if not os.path.exists(path):
            print(f"[用法错误] 找不到{label}输入: {path}", file=sys.stderr)
            return 2

    os.makedirs(args.out, exist_ok=True)

    try:
        manifest, manifest_problems = validator.load_manifest(args.manifest)
        if manifest is None:
            return 2
        ground_truths, gt_problems = validator.load_ground_truths(args.ground_truth)
        prediction_doc, prediction_arms = load_prediction_set(args.predictions)
        comparison = load_comparison_spec(args.comparison) if args.comparison else None
    except ScoringError as error:
        print(f"[用法/IO 错误] {error}", file=sys.stderr)
        return 2

    if manifest_problems:
        for item in manifest_problems:
            print(f"[manifest 校验失败] {item}", file=sys.stderr)
        print("[错误] manifest 未通过契约校验，拒绝评分", file=sys.stderr)
        return 1
    if gt_problems:
        for item in gt_problems:
            print(f"[ground truth 校验失败] {item}", file=sys.stderr)
        print("[错误] Ground Truth 未通过契约校验，拒绝评分", file=sys.stderr)
        return 1

    samples_by_id = {sample["sample_id"]: sample for sample in manifest["samples"]}

    # 预测集合引用的样本必须存在于 manifest 与 GT
    reference_problems = []
    for arm_id, entries in sorted(prediction_arms.items()):
        for sample_id in sorted(entries):
            if sample_id not in samples_by_id:
                reference_problems.append(
                    f"臂 {arm_id!r} 引用未知样本 {sample_id!r}（不在 manifest）")
            if sample_id not in ground_truths:
                reference_problems.append(
                    f"臂 {arm_id!r} 引用样本 {sample_id!r} 缺少 Ground Truth 输入")
    if reference_problems:
        for line in reference_problems:
            print(f"[样本一致性失败] {line}", file=sys.stderr)
        print("RESULT: INVALID (样本/真值不一致，拒绝评分)", file=sys.stderr)
        return 1

    # ---- 逐 (sample, arm) 评分（每个证据文档只加载一次）
    arm_scores = {}
    evidence_docs = {}
    any_hard_gate_failed = False
    for arm_id in sorted(prediction_arms):
        arm_scores[arm_id] = {}
        for sample_id in sorted(prediction_arms[arm_id]):
            sample = samples_by_id[sample_id]
            ground_truth = ground_truths[sample_id]
            evidence_path = prediction_arms[arm_id][sample_id]
            evidence = load_json_file(evidence_path, "预测证据")
            evidence_docs[(arm_id, sample_id)] = evidence
            score = score_sample(sample, ground_truth, evidence, evidence_path,
                                 args.manifest, args.predictions,
                                 ground_truth_path_for(ground_truths, sample_id,
                                                       args.ground_truth),
                                 arm_id)
            score["pack_id"] = manifest.get("pack_id")
            if not score["validation"]["all_passed"]:
                any_hard_gate_failed = True
            arm_scores[arm_id][sample_id] = score

            sample_dir = os.path.join(args.out, sample_id, arm_id)
            os.makedirs(sample_dir, exist_ok=True)
            assert_output_safe(score)
            dump_json(score, os.path.join(sample_dir, "score.json"))
            with open(os.path.join(sample_dir, "score.md"), "w", encoding="utf-8") as handle:
                handle.write(render_score_md(score))
            input_hashes_doc = {
                "schema_version": SCORE_SCHEMA_VERSION,
                "sample_id": sample_id,
                "arm_id": arm_id,
                "inputs": score["input_hashes"],
            }
            dump_json(input_hashes_doc, os.path.join(sample_dir, "input-hashes.json"))
            status = score["semantic_score_status"]
            print(f"[评分] {sample_id}/{arm_id}: execution_status="
                  f"{score['execution_status']} semantic_score_status={status}")

    # ---- 公平比较（可选）
    if comparison is not None:
        arm_a_id = comparison["arm_a"]["arm_id"]
        arm_b_id = comparison["arm_b"]["arm_id"]
        for arm_id in (arm_a_id, arm_b_id):
            if arm_id not in arm_scores:
                print(f"[用法错误] 比较规格引用的臂 {arm_id!r} 不在预测集合中",
                      file=sys.stderr)
                return 2
        conditions, gate_passed = evaluate_fairness(
            comparison, manifest, ground_truths, arm_scores, evidence_docs,
            prediction_arms, args.manifest)
        uniform_scores = [arm_scores[arm_a_id][sample_id]
                          for sample_id in comparison["sample_ids"]
                          if sample_id in arm_scores[arm_a_id]]
        adaptive_scores = [arm_scores[arm_b_id][sample_id]
                           for sample_id in comparison["sample_ids"]
                           if sample_id in arm_scores[arm_b_id]]
        uniform_metrics = aggregate_metrics(uniform_scores)
        adaptive_metrics = aggregate_metrics(adaptive_scores)
        if gate_passed:
            verdict = compute_verdict(uniform_metrics, adaptive_metrics)
        else:
            verdict = {
                "verdict": "INVALID_COMPARISON",
                "reason": "fairness gate 未全部通过：比较条件不满足，不计算 verdict",
                "reason_codes": ["fairness_gate_failed"],
                "strict_improvements": [],
                "regressions": [],
                "non_regression_conditions": {},
            }
        comparison_doc = {
            "schema_version": COMPARISON_SCHEMA_VERSION,
            "scorer": SCORER_NAME,
            "scorer_version": SCORER_VERSION,
            "comparison_id": comparison["comparison_id"],
            "pack_id": manifest.get("pack_id"),
            "sample_ids": list(comparison["sample_ids"]),
            "arms": {"baseline": comparison["arm_a"], "candidate": comparison["arm_b"]},
            "fairness_gate": {"conditions": conditions, "all_passed": gate_passed},
            "metrics": {arm_a_id: {"aggregate": uniform_metrics},
                        arm_b_id: {"aggregate": adaptive_metrics}},
            "differences": difference_table(uniform_metrics, adaptive_metrics),
            "verdict": verdict,
            "per_sample_table": [
                per_sample_row(sample_id,
                               arm_scores[arm_a_id].get(sample_id),
                               arm_scores[arm_b_id].get(sample_id))
                for sample_id in comparison["sample_ids"]],
            "no_extrapolation_statement": (
                "技术 fixture 小样本 + 单次运行：不构成统计显著性，不得外推为真实仓储/园区"
                "准确率；verdict 只反映本次冻结产物在严格 ground truth 口径下的对照结果"),
            "fairness_attestation": comparison["fairness_attestation"],
            "input_hashes": {
                "manifest": {"path": validator.repo_relative(args.manifest),
                             "sha256": sha256_of(args.manifest)},
                "prediction_set": {"path": validator.repo_relative(args.predictions),
                                   "sha256": sha256_of(args.predictions)},
                "comparison_spec": {"path": validator.repo_relative(args.comparison),
                                    "sha256": sha256_of(args.comparison)},
            },
        }
        for arm_id in (arm_a_id, arm_b_id):
            comparison_doc["input_hashes"][f"evidence_{arm_id}"] = {
                "sha256": sha256_of_text(json.dumps(
                    sorted((sample_id, sha256_of(prediction_arms[arm_id][sample_id]))
                           for sample_id in sorted(prediction_arms[arm_id])),
                    ensure_ascii=False))}
        assert_output_safe(comparison_doc)
        dump_json(comparison_doc, os.path.join(args.out, "comparison.json"))
        with open(os.path.join(args.out, "comparison.md"), "w", encoding="utf-8") as handle:
            handle.write(render_comparison_md(comparison_doc))
        print(f"[比较] verdict={verdict['verdict']} "
              f"reason_codes={verdict['reason_codes']}")

    if any_hard_gate_failed:
        print("RESULT: INVALID (存在硬门失败的样本，未计分)", file=sys.stderr)
        return 1
    print("RESULT: SCORED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
