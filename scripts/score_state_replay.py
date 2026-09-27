#!/usr/bin/env python3
"""score_state_replay.py — Task 28 状态表达力 replay 评分器
（SparkSkill Studio · State Expressiveness Gate）

对**已归档**的模型输出重新解析状态并评分，零模型调用、CPU-only、确定性。

**为什么不复用冻结 scorer 入口**（预注册 §4）：
冻结 `score_temporal_ground_truth.py` 的 G7 要求
`actual_model_calls == len(fresh_call decisions) == len(timeline)`。
诚实地把 256 个历史点标成 `archived_call` 会同时违反两个等式
（Task 21 `REPLAY_UNSCORABLE`，54/54 候选被拒）；唯一"通过"办法是把
已归档调用冒充 `fresh_call`——那是禁止的伪造 provenance。

因此本评分器：

  - 显式声明 `provenance_nature = "archived_replay"`；
  - 用 **G7r** 取代 G7：`len(timeline) == archived_call 决策数 == 评分行数`，
    且**出现任何 `fresh_call` 标注即失败**；
  - 其余硬门（G1–G6、G8）沿用冻结 scorer 同义规则，
    通过加载冻结模块复用其实现（不复制业务逻辑），保证口径不漂移。

**三个轨道（预注册 §3，不得混用）**：

  --oracle O0  恒等基线：只用 legacy classify_entry。
  --oracle O1  信息保持型（主判据）：三态解析，**不得读 GT**——
               实现上本文件在 O1 路径根本不传入 ground_truth。
  --oracle O2  GT 注入型（仅内部诊断）：读 GT 反推，
               并按要求输出 GT-driven / heuristic 拆分。

用法:
    python3 score_state_replay.py --predictions <set.json> --ground-truth <gt|dir> \
        --manifest <manifest.json> --out <dir> --oracle O1
退出码: 0 = 全部完成; 1 = 存在硬门失败; 2 = 用法/IO 错误
"""
import argparse
import hashlib
import importlib.util
import json
import os
import statistics
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPLAY_SCHEMA_VERSION = "1.0.0"
REPLAY_NAME = "score_state_replay.py"
REPLAY_VERSION = "1.0.0"
PROVENANCE_NATURE = "archived_replay"
ORACLES = ("O0", "O1", "O2")

CREDENTIAL_MARKERS = ("api_key", "api-key", "secret", "token", "password", "passwd",
                      "bearer ", "private_key", "-----begin")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


frozen = load_module("score_temporal_ground_truth",
                     os.path.join(PROJECT_ROOT, "scripts",
                                  "score_temporal_ground_truth.py"))
validator = load_module("validate_evidence_pack",
                        os.path.join(PROJECT_ROOT, "scripts",
                                     "validate_evidence_pack.py"))
state_resolver = load_module(
    "state_resolver",
    os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                 "scripts", "state_resolver.py"))

# 理由词表唯一来源 = state_resolver.UNCERTAINTY_REASONS（不在本文件复制，防止漂移）。
UNCERTAIN_REASONS = state_resolver.UNCERTAINTY_REASONS


class ReplayError(Exception):
    """用法/IO 级错误（退出码 2）。"""


def round3(value):
    return round(float(value), 3)


def ratio(numerator, denominator):
    """分母为 0 返回 'not_applicable'（不得写 100%）。"""
    if not denominator:
        return "not_applicable"
    return round(numerator / denominator, 6)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------- 分类与指标

def predicted_class(entry, oracle):
    """按轨道取预测类别。

    O0 → legacy 五类；O1 → 三态 compat_class（confirmed/not_found/low_confidence）；
    O2 → 由 GT 反推（调用方提供）。
    """
    if oracle == "O0":
        return state_resolver.classify_legacy(entry)
    resolved = state_resolver.resolve_entry(entry)
    return resolved["compat_class"]


def metric_for(gt_state, pred_class):
    """与冻结 scorer 的 metric_for 同义（GT determinate/uncertain ×
    预测 decisive/non-decisive → 七类）。"""
    if gt_state in frozen.GT_DETERMINATE_STATES:
        if pred_class in frozen.DECISIVE_PRED_CLASSES:
            return ("correct_decisive" if pred_class == gt_state
                    else "incorrect_decisive")
        if pred_class in frozen.NON_DECISIVE_PRED_CLASSES:
            return "abstention_on_determinate"
        return "failed_on_determinate"
    if pred_class in frozen.NON_DECISIVE_PRED_CLASSES:
        return "appropriate_abstention"
    if pred_class in frozen.DECISIVE_PRED_CLASSES:
        return "overclaim_on_uncertain"
    return "failed_on_uncertain"


def score_points(timeline, ground_truth, oracle):
    counts = {name: 0 for name in frozen.SEVEN_METRICS}
    rows = []
    determinate_total = uncertain_total = 0
    for entry in sorted(timeline, key=lambda item: item["timestamp_ms"]):
        gt_state = frozen.gt_state_at(ground_truth, entry["timestamp_ms"])
        if oracle == "O2":
            pred_class = state_resolver.oracle_gt_injected(
                entry, lambda ts: frozen.gt_state_at(ground_truth, ts))
        else:
            pred_class = predicted_class(entry, oracle)
        metric = metric_for(gt_state, pred_class)
        counts[metric] += 1
        if gt_state in frozen.GT_DETERMINATE_STATES:
            determinate_total += 1
        else:
            uncertain_total += 1
        rows.append({
            "timestamp_ms": round3(entry["timestamp_ms"]),
            "prediction_class": pred_class,
            "ground_truth_state": gt_state,
            "metric": metric,
        })
        if oracle == "O1":
            rows[-1]["uncertainty_reasons"] = state_resolver.extract_reasons(entry)

    metrics = {}
    for name in frozen.SEVEN_METRICS:
        denominator = (determinate_total if name in (
            "correct_decisive", "incorrect_decisive", "abstention_on_determinate",
            "failed_on_determinate") else uncertain_total)
        metrics[name] = {"passed": counts[name], "total": denominator,
                         "ratio": ratio(counts[name], denominator)}
    return {
        "counts": counts,
        "metrics": metrics,
        "denominator_determinate_samples": determinate_total,
        "denominator_uncertain_samples": uncertain_total,
        "per_sample_rows": rows,
    }


def gt_unique_boundaries(ground_truth):
    """unique GT boundary times（主分母，预注册 §6.2）。

    "unique" 指**边界时刻去重后的集合**：同一批 GT 边界在三臂中重复出现只算一个。
    调用方须按样本汇总成 pack 级分母（Task 19B = 8）。
    """
    times = set()
    for segment in ground_truth["segments"]:
        start = segment.get("start_ms")
        end = segment.get("end_ms")
        if isinstance(start, (int, float)) and not isinstance(start, bool):
            times.add(round3(start))
        if isinstance(end, (int, float)) and not isinstance(end, bool):
            times.add(round3(end))
    # 段起点 0 与媒体起点通常不是"过渡边界"；这里按冻结 scorer 的边界口径取内部接缝：
    # 只保留出现在两个相邻段之间的时刻。
    seams = set()
    for index in range(len(ground_truth["segments"]) - 1):
        seam = ground_truth["segments"][index]["end_ms"]
        if isinstance(seam, (int, float)) and not isinstance(seam, bool):
            seams.add(round3(seam))
    return sorted(seams)


def score_unique_boundaries(timeline, ground_truth, oracle, tolerance_ms=250.0):
    """unique-boundary 恢复（主判据 G1）。

    预测边界 = 相邻帧预测类别变化处（与该臂的 exposure 无关）。
    命中 = 存在 GT unique boundary 落在 tolerance 内。
    分母 = unique boundary 数（不是臂暴露数）。
    """
    ordered = sorted(timeline, key=lambda item: item["timestamp_ms"])
    classes = []
    for entry in ordered:
        if oracle == "O2":
            classes.append(state_resolver.oracle_gt_injected(
                entry, lambda ts, gt=ground_truth: frozen.gt_state_at(gt, ts)))
        else:
            classes.append(predicted_class(entry, oracle))

    predicted = []
    for index in range(1, len(classes)):
        if classes[index] != classes[index - 1]:
            predicted.append(round3((ordered[index]["timestamp_ms"]
                                     + ordered[index - 1]["timestamp_ms"]) / 2.0))

    boundaries = gt_unique_boundaries(ground_truth)
    matched = []
    for boundary in boundaries:
        for prediction in predicted:
            if abs(prediction - boundary) <= tolerance_ms:
                matched.append(boundary)
                break
    return {
        "unique_gt_boundaries_total": len(boundaries),
        "matched_unique_boundaries": len(matched),
        "matched_unique_boundary_times": sorted(matched),
        "arm_level_boundary_matches": len(predicted),
        "boundary_tolerance_ms": round3(tolerance_ms),
        "note": ("primary denominator = unique GT boundaries；"
                 "arm_level_boundary_matches 仅作 secondary diagnostic，"
                 "不得单独引用或当恢复率分子"),
    }


def split_correct_decisive(points, timeline, sample):
    """correct_decisive 的 total / licensed-public 分层（预注册 G2/G3）。

    分层依据：sample.source_type（licensed-public vs generated）。
    未见该字段时不猜测，返回 total only 并在 stratified 中明示不可用。
    """
    rows = points.get("per_sample_rows") or []
    source_type = sample.get("source_type")
    total = points["counts"].get("correct_decisive", 0)
    licensed = sum(1 for row in rows
                   if row.get("metric") == "correct_decisive"
                   and _row_is_licensed_public(row, timeline, source_type))
    return {
        "source_type": source_type,
        "correct_decisive_total": total,
        "correct_decisive_licensed_public": (
            licensed if source_type == "licensed_public" else "not_applicable"),
        "note": ("G2 看 total 降幅 ≤4；G3 看 licensed_public 降幅 ≤1。"
                 "缺失 source_type 时分层记 not_applicable，不得以 total 冒充分层"),
    }


def _row_is_licensed_public(row, timeline, source_type):
    """按样本级 source_type 判定；未提供时保守返回 False（宁可少算，不多算）。"""
    if source_type != "licensed_public":
        return False
    return True


def score_events(timeline, ground_truth, oracle):
    """事件覆盖：与冻结 score_events 同义（段内出现同类别即覆盖）。"""
    samples = [(round3(entry["timestamp_ms"]), None) for entry in
               sorted(timeline, key=lambda item: item["timestamp_ms"])]
    classes = []
    for entry in sorted(timeline, key=lambda item: item["timestamp_ms"]):
        if oracle == "O2":
            classes.append(state_resolver.oracle_gt_injected(
                entry, lambda ts, gt=ground_truth: frozen.gt_state_at(gt, ts)))
        else:
            classes.append(predicted_class(entry, oracle))
    samples = list(zip([s[0] for s in samples], classes))
    segments = ground_truth["segments"]

    def inside(segment):
        start, end = segment["start_ms"], segment["end_ms"]
        result = []
        for index, (timestamp, _) in enumerate(samples):
            last = index == len(segments) - 1
            if start <= timestamp < end or (last and timestamp == end):
                result.append(samples[index][1])
        return result

    confirmed_total = confirmed_covered = not_found_total = not_found_covered = 0
    uncertain_segments = []
    for segment in segments:
        contained = inside(segment)
        if segment["state"] == "confirmed":
            confirmed_total += 1
            confirmed_covered += 1 if "confirmed" in contained else 0
        elif segment["state"] == "not_found":
            not_found_total += 1
            not_found_covered += 1 if "not_found" in contained else 0
        else:
            uncertain_segments.append({
                "start_ms": round3(segment["start_ms"]),
                "end_ms": round3(segment["end_ms"]),
                "reached": bool(contained),
                "sample_count_inside": len(contained),
                "appropriate_abstention_achieved": any(
                    cls in frozen.NON_DECISIVE_PRED_CLASSES for cls in contained),
            })
    return {
        "gt_confirmed_segments": confirmed_total,
        "covered_confirmed_events": confirmed_covered,
        "missed_confirmed_events": confirmed_total - confirmed_covered,
        "gt_not_found_segments": not_found_total,
        "covered_not_found_segments": not_found_covered,
        "missed_not_found_segments": not_found_total - not_found_covered,
        "gt_uncertain_segments": len(uncertain_segments),
        "uncertain_segments": uncertain_segments,
        "unreached_uncertain_segments": sum(1 for item in uncertain_segments
                                            if not item["reached"]),
    }


# ---------------------------------------------------------------- G7r provenance

def check_replay_provenance(evidence):
    """G7r：replay 专用 provenance 自洽。

    要求：
      1. decisions 存在且全部标注为 archived_call；
      2. 出现任何 fresh_call → 失败（禁止把归档调用冒充新调用）；
      3. archived 决策数 == 时间线条目数 == 评分行数；
      4. 时间戳集合一致（顺序无关）。
    """
    problems = []
    decisions = evidence.get("sampling_provenance", {}).get("decisions")
    timeline = evidence.get("timeline")

    if not isinstance(timeline, list) or not isinstance(decisions, list):
        return [{"code": "replay_provenance_inconsistent",
                 "message": "evidence 缺少 timeline / sampling_provenance.decisions"}]

    fresh = [item for item in decisions if item.get("cache_status") == "fresh_call"]
    archived = [item for item in decisions if item.get("cache_status") == "archived_call"]
    if fresh:
        problems.append({
            "code": "replay_provenance_fresh_call_present",
            "message": (f"replay 输入不得包含 fresh_call 标注（发现 {len(fresh)} 个）；"
                        "归档调用必须如实标注为 archived_call")})
    if len(archived) != len(decisions):
        problems.append({
            "code": "replay_provenance_inconsistent",
            "message": (f"decisions 中存在既非 fresh 也非 archived 的条目："
                        f"{len(decisions) - len(archived) - len(fresh)} 个")})
    if len(archived) != len(timeline):
        problems.append({
            "code": "replay_provenance_inconsistent",
            "message": (f"archived_call 决策数({len(archived)})与时间线条目数"
                        f"({len(timeline)})不一致")})

    decision_times = sorted(round3(item["timestamp_ms"]) for item in decisions
                            if isinstance(item.get("timestamp_ms"), (int, float)))
    timeline_times = sorted(round3(entry["timestamp_ms"]) for entry in timeline
                            if isinstance(entry.get("timestamp_ms"), (int, float)))
    if decision_times != timeline_times:
        problems.append({
            "code": "replay_provenance_inconsistent",
            "message": "decisions 与 timeline 的时间戳集合不一致"})
    return problems


# ---------------------------------------------------------------- O2 拆分（3.1）

def o2_decomposition(timeline, ground_truth):
    """O2 的对称护栏拆分（预注册 §3.1）。

    对每个可行边界，判断它是否**仅凭单帧启发式**（不读 GT）就能承接，
    还是**必须读 GT** 才能得到。回测幻觉的量化来源。

    H5：**执行失败点被排除**。failed 不是视觉不确定，不得参与
    heuristic_reachable 计数——否则一次 backend 失败就能"制造"一个边界。
    排除数量显式报告在 `excluded_execution_failures`。
    """
    ordered = sorted(timeline, key=lambda item: item["timestamp_ms"])
    classes = [predicted_class(entry, "O1") for entry in ordered]
    resolved_states = [state_resolver.observation_state(entry) for entry in ordered]
    execution_failed = [state_resolver.is_execution_failed(entry) for entry in ordered]

    boundaries = []
    for index in range(1, len(classes)):
        if classes[index] != classes[index - 1]:
            boundaries.append(round3((ordered[index]["timestamp_ms"]
                                      + ordered[index - 1]["timestamp_ms"]) / 2.0))

    # 启发式可达：这一侧或那侧已被 O1 判为 uncertain，且**两侧都不是执行失败**。
    heuristic_reachable = []
    for index in range(1, len(resolved_states)):
        if execution_failed[index] or execution_failed[index - 1]:
            continue
        if (resolved_states[index] == "uncertain"
                or resolved_states[index - 1] == "uncertain"):
            heuristic_reachable.append(round3((ordered[index]["timestamp_ms"]
                                               + ordered[index - 1]["timestamp_ms"])
                                              / 2.0))
    return {
        "o2_boundaries_total": len(boundaries),
        "o2_boundary_times": sorted(boundaries),
        "o2_boundaries_heuristic_reachable": len(
            set(heuristic_reachable) & set(boundaries)),
        "excluded_execution_failures": sum(1 for flag in execution_failed if flag),
        "note": ("拆分用于防止回测幻觉：只报 o2_boundaries_total 而不报 "
                 "heuristic_reachable 会高估状态模型扩展的收益。"
                 "执行失败点（H5）已排除，不计入 heuristic_reachable"),
    }


# ---------------------------------------------------------------- 硬门

def run_replay_gates(sample, ground_truth, evidence, evidence_path, manifest_path):
    """G1–G6、G8 复用冻结实现（通过冻结模块调用），G7 用 G7r 取代。

    复用方式：调用冻结 run_hard_gates 后**剔除 G7 项**并追加 G7r。
    这保证规则不漂移，同时不把归档 replay 判成"伪造 provenance"。
    """
    gates, errors = frozen.run_hard_gates(sample, ground_truth, evidence,
                                          evidence_path, manifest_path)
    kept = [gate for gate in gates if gate["id"] != "G7-provenance-self-consistency"]
    errors = [item for item in errors if item.get("code") not in (
        "provenance_inconsistent",)]
    replay_problems = check_replay_provenance(evidence)
    kept.append({
        "id": "G7r-replay-provenance",
        "passed": not replay_problems,
        "detail": ("replay provenance 自洽（时间线=archived 决策=评分行；"
                   "无 fresh_call 冒充）" if not replay_problems else replay_problems),
    })
    for problem in replay_problems:
        errors.append({"code": problem["code"],
                       "sample_id": sample["sample_id"],
                       "message": problem["message"]})
    return kept, errors


# ---------------------------------------------------------------- 审计

def score_sample(sample, ground_truth, evidence, oracle, paths):
    timeline = evidence.get("timeline") if isinstance(evidence.get("timeline"), list) else []
    points = score_points(timeline, ground_truth, oracle)
    events = score_events(timeline, ground_truth, oracle)
    unique_boundaries = score_unique_boundaries(timeline, ground_truth, oracle)
    stratified = split_correct_decisive(points, timeline, sample)
    provenance = evidence.get("sampling_provenance", {})

    replay_provenance = {
        "provenance_nature": PROVENANCE_NATURE,
        "archived_decisions": sum(1 for item in provenance.get("decisions", [])
                                  if item.get("cache_status") == "archived_call"),
        "fresh_calls_present": any(item.get("cache_status") == "fresh_call"
                                   for item in provenance.get("decisions", [])),
        "new_model_calls": 0,
        "note": ("replay 不产生任何新视觉调用；archived_call 数即时间线条目数。"
                 "严禁把归档调用标注为 fresh_call"),
    }

    doc = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "scorer": REPLAY_NAME,
        "scorer_version": REPLAY_VERSION,
        "oracle": oracle,
        "pack_id": None,
        "sample_id": sample["sample_id"],
        "arm_id": paths.get("arm_id"),
        "provenance_nature": PROVENANCE_NATURE,
        "target_query": evidence.get("target_query"),
        "metrics": points["metrics"],
        "seven_class_counts": points["counts"],
        "events": events,
        "unique_boundaries": unique_boundaries,
        "stratified_correct_decisive": stratified,
        "replay_provenance": replay_provenance,
        "input_hashes": {
            "manifest": {"path": validator.repo_relative(paths["manifest"]),
                         "sha256": sha256_of(paths["manifest"])},
            "predictions": {"path": validator.repo_relative(paths["predictions"]),
                            "sha256": sha256_of(paths["predictions"])},
            "ground_truth": {"path": validator.repo_relative(paths["ground_truth"]),
                             "sha256": sha256_of(paths["ground_truth"])},
            "prediction_evidence": {"path": validator.repo_relative(paths["evidence"]),
                                    "sha256": sha256_of(paths["evidence"])},
        },
        "known_limitations": [
            "replay 评分：零新模型调用；分数描述『换一种状态解释』的效果，不是新证据",
            "O1 不读 GT、不看时间邻域、不读媒体；只重解析模型既有输出",
            f"oracle={oracle}：" + {
                "O0": "恒等基线（必须复现历史口径，不产生新结论）",
                "O1": "信息保持型主判据（禁止读 GT）",
                "O2": "GT 注入型内部诊断（不得进入交付叙事）",
            }[oracle],
            "小样本 + 单次运行：不构成统计显著性，不得外推真实仓储准确率",
        ],
    }

    if oracle == "O1":
        counts = {reason: sum(1 for row in points["per_sample_rows"]
                              if reason in row.get("uncertainty_reasons", []))
                  for reason in UNCERTAIN_REASONS}
        doc["uncertainty_reason_counts"] = counts
    if oracle == "O2":
        doc["o2_decomposition"] = o2_decomposition(timeline, ground_truth)

    gates, errors = run_replay_gates(sample, ground_truth, evidence,
                                     paths["evidence"], paths["manifest"])
    doc["validation"] = {"hard_gates": gates, "all_passed": not errors, "errors": errors}
    doc["semantic_score_status"] = "scored" if not errors else "invalid_input"
    return doc


# ---------------------------------------------------------------- IO

def load_json(path, role):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ReplayError(f"无法读取{role} {validator.repo_relative(path)}: {error}")


def load_prediction_set(path):
    doc = load_json(path, "预测集合")
    if not isinstance(doc, dict) or not isinstance(doc.get("samples"), dict):
        raise ReplayError("预测集合必须是包含 samples 对象的 JSON"
                          "（{sample_id: evidence 相对路径}）")
    if "arms" in doc:
        raise ReplayError("replay 评分器仅支持单轨 samples 映射，"
                          "不支持 arms 公平比较规格（公平比较仍用冻结 scorer）")
    return doc


def assert_output_safe(doc):
    text = json.dumps(doc, ensure_ascii=False).lower()
    for marker in CREDENTIAL_MARKERS:
        if marker in text:
            raise ReplayError(f"输出包含凭据样式内容: {marker!r}")


def aggregate_pack(sample_docs):
    """pack 级汇总：把 (sample, oracle) 评分聚合成 unique-boundary 主分母口径。

    为什么必须跨臂去重：三臂暴露同一批 GT 边界。若直接把三臂的
    `matched_unique_boundaries` 相加，会把同一边界算三次。
    本函数按 boundary time 求并集，因此 pack 级分母天然是 unique 数。
    """
    per_oracle = {}
    for oracle in ORACLES:
        docs = [doc for doc in sample_docs if doc.get("oracle") == oracle]
        if not docs:
            continue
        unique_total = matched = arm_level = 0
        matched_times = set()
        correct_total = correct_licensed = 0
        overclaim = 0
        for doc in docs:
            boundaries = doc.get("unique_boundaries") or {}
            unique_total = max(unique_total, boundaries.get(
                "unique_gt_boundaries_total", 0) or 0)
            matched_times.update(boundaries.get("matched_unique_boundary_times") or [])
            arm_level += boundaries.get("arm_level_boundary_matches", 0) or 0
            correct_total += doc["seven_class_counts"].get("correct_decisive", 0)
            overclaim += doc["seven_class_counts"].get("overclaim_on_uncertain", 0)
            # licensed-public 分层：样本级标记（内部留档 pack 才有意义）
            stratified = doc.get("stratified_correct_decisive") or {}
            if isinstance(stratified.get("correct_decisive_licensed_public"), int):
                correct_licensed += stratified["correct_decisive_licensed_public"]
        per_oracle[oracle] = {
            "unique_boundary_recovery": f"{len(matched_times)}/{unique_total}",
            "matched_unique_boundaries": len(matched_times),
            "unique_gt_boundaries_total": unique_total,
            "arm_level_boundary_matches": arm_level,
            "arm_level_denominator_note": "secondary diagnostic；不得当主分母",
            "correct_decisive_total": correct_total,
            "overclaim_on_uncertain_total": overclaim,
        }
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "scorer": REPLAY_NAME,
        "provenance_nature": PROVENANCE_NATURE,
        "per_oracle": per_oracle,
        "note": ("primary = unique GT boundary 并集；三臂重复暴露已去重。"
                 "G1 只读 matched_unique_boundaries 的 Δ（阈值 +2）。"),
    }


def main():
    parser = argparse.ArgumentParser(
        description="状态表达力 replay 评分器（archived_replay；G7r 取代 G7）")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--ground-truth", required=True,
                        help="Ground Truth JSON 文件或目录（必显参数）")
    parser.add_argument("--out", required=True)
    parser.add_argument("--oracle", choices=ORACLES + ("all",), required=True,
                        help="O0=恒等基线 / O1=信息保持主判据 / "
                             "O2=GT注入内部诊断 / all=三轨一次跑完并出 pack 汇总")
    args = parser.parse_args()

    oracles = list(ORACLES) if args.oracle == "all" else [args.oracle]
    for label, path in (("manifest", args.manifest), ("predictions", args.predictions),
                        ("ground truth", args.ground_truth)):
        if not os.path.exists(path):
            print(f"[用法错误] 找不到{label}输入: {path}", file=sys.stderr)
            return 2

    manifest, manifest_problems = validator.load_manifest(args.manifest)
    if manifest is None:
        return 2
    ground_truths, gt_problems = validator.load_ground_truths(args.ground_truth)
    prediction_doc = load_prediction_set(args.predictions)

    if manifest_problems:
        print("[错误] manifest 未通过契约校验，拒绝评分", file=sys.stderr)
        return 1
    if gt_problems:
        print("[错误] Ground Truth 未通过契约校验，拒绝评分", file=sys.stderr)
        return 1

    samples_by_id = {sample["sample_id"]: sample for sample in manifest["samples"]}
    any_failed = False
    all_docs = []

    for oracle in oracles:
        for sample_id in sorted(prediction_doc["samples"]):
            if sample_id not in samples_by_id:
                print(f"[样本一致性失败] 未知样本 {sample_id!r}", file=sys.stderr)
                return 1
            if sample_id not in ground_truths:
                print(f"[样本一致性失败] 样本 {sample_id!r} 缺少 Ground Truth", file=sys.stderr)
                return 1

            sample = samples_by_id[sample_id]
            ground_truth = ground_truths[sample_id]
            evidence_path = prediction_doc["samples"][sample_id]
            evidence = load_json(evidence_path, "预测证据")

            doc = score_sample(sample, ground_truth, evidence, oracle, {
                "manifest": args.manifest,
                "predictions": args.predictions,
                "ground_truth": (args.ground_truth if os.path.isfile(args.ground_truth)
                                 else os.path.join(args.ground_truth, f"{sample_id}.json")),
                "evidence": evidence_path,
                "arm_id": oracle,
            })
            doc["pack_id"] = manifest.get("pack_id")
            if not doc["validation"]["all_passed"]:
                any_failed = True
            all_docs.append(doc)

            sample_dir = os.path.join(args.out, oracle, sample_id)
            os.makedirs(sample_dir, exist_ok=True)
            assert_output_safe(doc)
            with open(os.path.join(sample_dir, "score.json"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

            counts = doc["seven_class_counts"]
            boundaries = doc.get("unique_boundaries") or {}
            print(f"[replay {oracle}] {sample_id}: "
              f"correct={counts['correct_decisive']} "
              f"incorrect={counts['incorrect_decisive']} "
              f"overclaim={counts['overclaim_on_uncertain']} "
              f"unique={boundaries.get('matched_unique_boundaries')}/"
              f"{boundaries.get('unique_gt_boundaries_total')} "
              f"arm_level={boundaries.get('arm_level_boundary_matches')} "
              f"status={doc['semantic_score_status']}")

    if len(oracles) > 1:
        pack = aggregate_pack(all_docs)
        with open(os.path.join(args.out, "pack-summary.json"), "w",
                  encoding="utf-8") as handle:
            handle.write(json.dumps(pack, ensure_ascii=False, indent=2) + "\n")
        for oracle, summary in pack["per_oracle"].items():
            print(f"[pack {oracle}] unique_boundary_recovery="
                  f"{summary['unique_boundary_recovery']} "
                  f"arm_level={summary['arm_level_boundary_matches']} "
                  f"correct_decisive_total={summary['correct_decisive_total']} "
                  f"overclaim_total={summary['overclaim_on_uncertain_total']}")
        print("[pack] primary denominator = unique GT boundaries；"
              "arm_level 为 secondary diagnostic")

    print(f"RESULT: replay oracle={args.oracle} "
          f"provenance={PROVENANCE_NATURE} "
          f"{'HAS_GATE_FAILURES' if any_failed else 'OK'}")
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
