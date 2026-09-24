#!/usr/bin/env python3
"""task18_scorer_adapter.py — 任务 18 三臂评测评分适配层（SparkSkill Studio）

定位：任务 17 冻结评分器 `scripts/score_temporal_ground_truth.py`（SHA-256 冻结，
文件零改动）的**兼容适配层**。冻结评分器只支持两种策略（其 G7 硬门的策略白名单
`STRATEGIES = ("uniform", "adaptive_coarse_to_fine")`）与双臂比较；任务 18 的第三臂
`coverage_aware_adaptive` 需要进入同一确定性评分口径。

适配方式（硬纪律）：
  - **不修改冻结评分器文件任何字节**；以 importlib 加载冻结模块后，仅在**内存**
    扩展其策略白名单：`scorer.STRATEGIES = scorer.STRATEGIES + ("coverage_aware_adaptive",)`；
  - 全部评分逻辑（8 项硬门、七类采样点计数、事件覆盖、边界一对一匹配、效率指标、
    fairness gate、compute_verdict）逐字复用冻结模块函数——本文件只做编排；
  - 三臂评分：复用冻结 `score_sample` 对每个 (sample, arm) 评分并落盘
    score.json / score.md / input-hashes.json（目录布局与冻结评分器一致）；
  - 两两比较：复用冻结 `evaluate_fairness` / `aggregate_metrics` / `compute_verdict`
    对三个臂对（coverage-vs-uniform / coverage-vs-adaptive / adaptive-vs-uniform）
    计算 fairness gate 与四类 verdict；
  - pack 级三臂 verdict：按 `artifacts/task-18/preregistration/verdict-policy.json`
    预注册规则由聚合指标确定性计算（候选臂 coverage 对两个基线的非回归条件 +
    严格更好项），不预设结果；
  - maximum sampling gap 来自各臂 evidence 的
    `sampling_provenance.max_adjacent_sampling_gap_ms_final`（跨场景取最大值）。

用法:
    python3 scripts/task18_scorer_adapter.py \
        --manifest artifacts/task-18/contracts/task18-fixture-evidence-pack-manifest.json \
        --predictions <prediction-set.json> \
        --ground-truth artifacts/task-18/contracts/ground-truth \
        --out <输出目录> [--comparison-id <id>] [--no-comparison]

prediction-set 格式（与任务 17 相同）：arms[] → {arm_id, samples[] → {sample_id,
evidence 相对路径（相对 prediction-set 文件所在目录）}}；臂数不限（三臂）。
退出码: 0 = 全部硬门通过并完成评分/比较; 1 = 存在硬门失败/契约校验失败; 2 = 用法/IO 错误
"""
import argparse
import importlib.util
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCORER_PATH = os.path.join(PROJECT_ROOT, "scripts", "score_temporal_ground_truth.py")
PREREGISTRATION_POLICY = os.path.join(
    PROJECT_ROOT, "artifacts", "task-18", "preregistration", "verdict-policy.json")

COVERAGE_ARM = "coverage"
BASELINE_ARMS = ("uniform", "adaptive")

# 内存扩展的策略白名单（适配层唯一“扩展点”；冻结文件零改动）
EXTENDED_STRATEGY = "coverage_aware_adaptive"


def load_scorer():
    """加载冻结评分器模块并在内存扩展策略白名单（不修改文件）。"""
    spec = importlib.util.spec_from_file_location("score_temporal_ground_truth", SCORER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if EXTENDED_STRATEGY not in module.STRATEGIES:
        module.STRATEGIES = tuple(module.STRATEGIES) + (EXTENDED_STRATEGY,)
    return module


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def max_sampling_gap_of(evidence):
    """单来源 evidence 的最大相邻采样间隔（最终值）；缺失返回 None。"""
    if not isinstance(evidence, dict):
        return None
    if "global_timeline" in evidence:
        return None  # 多来源文档不参与 gap 比较（v1 结构化限制）
    provenance = evidence.get("sampling_provenance") or {}
    value = provenance.get("max_adjacent_sampling_gap_ms_final")
    return value if isinstance(value, (int, float)) else None


def pack_level_verdict(aggregates, gap_max_by_arm):
    """pack 级三臂 verdict（预注册规则；候选臂 coverage 对两个基线）。

    非回归：coverage 对 uniform 且 对 adaptive 的 5 项条件全部满足。
    严格更好（至少一项，均相对两个基线同时成立）：
      fewer_model_calls_than_both / smaller_mean_boundary_error_than_both /
      more_boundaries_within_tolerance_than_both / smaller_max_sampling_gap_than_both /
      fewer_unreached_uncertain_than_both（仅当两基线均 >0 时计入）。
    """
    coverage = aggregates[COVERAGE_ARM]
    baselines = {arm: aggregates[arm] for arm in BASELINE_ARMS}

    non_regression = {}
    for arm, base in baselines.items():
        non_regression[f"coverage_vs_{arm}"] = {
            "incorrect_decisive_not_worse": (
                coverage["incorrect_decisive"] <= base["incorrect_decisive"]),
            "overclaim_on_uncertain_not_worse": (
                coverage["overclaim_on_uncertain"] <= base["overclaim_on_uncertain"]),
            "missed_confirmed_events_not_worse": (
                coverage["missed_confirmed_events"] <= base["missed_confirmed_events"]),
            "missed_gt_boundaries_not_worse": (
                coverage["missed_gt_boundaries"] <= base["missed_gt_boundaries"]),
            "unreached_uncertain_not_worse": (
                coverage["unreached_uncertain_segments"]
                <= base["unreached_uncertain_segments"]),
        }
    non_regression_ok = all(all(item.values()) for item in non_regression.values())

    strict = []
    if all(coverage["actual_model_calls"] < base["actual_model_calls"]
           for base in baselines.values()):
        strict.append("fewer_model_calls_than_both")
    cov_stats = coverage["boundary_error_stats"]
    if cov_stats["matched_count"] >= 1 and all(
            base["boundary_error_stats"]["matched_count"] >= 1
            for base in baselines.values()):
        if all(cov_stats["mean_ms"] < base["boundary_error_stats"]["mean_ms"]
               for base in baselines.values()):
            strict.append("smaller_mean_boundary_error_than_both")
    if all(coverage["within_tolerance_boundaries"] > base["within_tolerance_boundaries"]
           for base in baselines.values()):
        strict.append("more_boundaries_within_tolerance_than_both")
    if (gap_max_by_arm.get(COVERAGE_ARM) is not None
            and all(gap_max_by_arm.get(arm) is not None for arm in BASELINE_ARMS)
            and gap_max_by_arm[COVERAGE_ARM] < gap_max_by_arm["uniform"]
            and gap_max_by_arm[COVERAGE_ARM] < gap_max_by_arm["adaptive"]):
        strict.append("smaller_max_sampling_gap_than_both")
    if all(base["unreached_uncertain_segments"] > 0 for base in baselines.values()) and all(
            coverage["unreached_uncertain_segments"] < base["unreached_uncertain_segments"]
            for base in baselines.values()):
        strict.append("fewer_unreached_uncertain_than_both")

    regressions = []
    for arm, base in baselines.items():
        if coverage["incorrect_decisive"] > base["incorrect_decisive"]:
            regressions.append(f"more_incorrect_decisive_vs_{arm}")
        if coverage["overclaim_on_uncertain"] > base["overclaim_on_uncertain"]:
            regressions.append(f"more_overclaim_on_uncertain_vs_{arm}")
        if coverage["missed_confirmed_events"] > base["missed_confirmed_events"]:
            regressions.append(f"more_missed_confirmed_events_vs_{arm}")
        if coverage["missed_gt_boundaries"] > base["missed_gt_boundaries"]:
            regressions.append(f"more_missed_gt_boundaries_vs_{arm}")
        if coverage["unreached_uncertain_segments"] > base["unreached_uncertain_segments"]:
            regressions.append(f"more_unreached_uncertain_segments_vs_{arm}")
        if (gap_max_by_arm.get(COVERAGE_ARM) is not None
                and gap_max_by_arm.get(arm) is not None
                and gap_max_by_arm[COVERAGE_ARM] > gap_max_by_arm[arm]):
            regressions.append(f"larger_max_sampling_gap_vs_{arm}")

    strict_ok = bool(strict)
    if non_regression_ok and strict_ok:
        verdict = "IMPROVEMENT"
        reason = (f"非回归条件全部满足（对两个基线），且至少一项严格更好（{strict}）")
    elif non_regression_ok and not strict_ok:
        verdict = "NO_IMPROVEMENT"
        reason = "非回归条件全部满足（对两个基线），但没有任何严格更好的项"
    elif not non_regression_ok and strict_ok:
        verdict = "TRADEOFF"
        reason = (f"有严格改进（{strict}）但非回归条件被违反（{regressions}）："
                  "省调用/缩边界/缩间隔的同时增加了漏检、过度断言或未触达 uncertain")
    else:
        verdict = "NO_IMPROVEMENT"
        reason = (f"没有严格改进，且非回归条件被违反（{regressions}）；"
                  "NO_IMPROVEMENT 不表示三臂等价，违反项已在差异字段完整披露")
    return {
        "verdict": verdict,
        "reason": reason,
        "reason_codes": strict + regressions,
        "strict_improvements": strict,
        "regressions": regressions,
        "non_regression_conditions": non_regression,
    }


def score_three_arms(scorer, manifest_path, predictions_path, ground_truth_arg, out_dir,
                     comparison_id=None, run_pairwise=True, fairness_attestation=None,
                     comparison_sample_ids=None):
    """三臂评分 + 两两公平比较 + pack 级 verdict。返回比较文档（可落盘）。

    comparison_sample_ids: 参与两两比较与 pack verdict 的样本范围（预注册
    verdict-policy.json：同预算主对照场景；预算不足场景只评分不比较）。
    缺省 = 全部已评分样本。
    """
    validator = scorer.validator
    manifest, manifest_problems = validator.load_manifest(manifest_path)
    if manifest is None:
        raise scorer.ScoringError(f"manifest 无法加载: {manifest_path}")
    ground_truths, gt_problems = validator.load_ground_truths(ground_truth_arg)
    prediction_doc, prediction_arms = scorer.load_prediction_set(predictions_path)
    if manifest_problems or gt_problems:
        problems = list(manifest_problems) + list(gt_problems)
        raise scorer.ScoringError("manifest/Ground Truth 契约校验失败: "
                                  + "；".join(problems))
    samples_by_id = {sample["sample_id"]: sample for sample in manifest["samples"]}

    arm_scores = {}
    evidence_docs = {}
    evidence_docs_paths = {}
    any_hard_gate_failed = False
    os.makedirs(out_dir, exist_ok=True)
    for arm_id in sorted(prediction_arms):
        arm_scores[arm_id] = {}
        evidence_docs_paths[arm_id] = {}
        for sample_id in sorted(prediction_arms[arm_id]):
            if sample_id not in samples_by_id:
                raise scorer.ScoringError(
                    f"臂 {arm_id!r} 引用未知样本 {sample_id!r}（不在 manifest）")
            if sample_id not in ground_truths:
                raise scorer.ScoringError(
                    f"臂 {arm_id!r} 引用样本 {sample_id!r} 缺少 Ground Truth 输入")
            sample = samples_by_id[sample_id]
            ground_truth = ground_truths[sample_id]
            evidence_path = prediction_arms[arm_id][sample_id]
            evidence = scorer.load_json_file(evidence_path, "预测证据")
            evidence_docs[(arm_id, sample_id)] = evidence
            evidence_docs_paths[arm_id][sample_id] = evidence_path
            score = scorer.score_sample(
                sample, ground_truth, evidence, evidence_path,
                manifest_path, predictions_path,
                scorer.ground_truth_path_for(ground_truths, sample_id, ground_truth_arg),
                arm_id)
            score["pack_id"] = manifest.get("pack_id")
            if not score["validation"]["all_passed"]:
                any_hard_gate_failed = True
            arm_scores[arm_id][sample_id] = score
            sample_dir = os.path.join(out_dir, sample_id, arm_id)
            os.makedirs(sample_dir, exist_ok=True)
            scorer.assert_output_safe(score)
            scorer.dump_json(score, os.path.join(sample_dir, "score.json"))
            with open(os.path.join(sample_dir, "score.md"), "w", encoding="utf-8") as handle:
                handle.write(scorer.render_score_md(score))
            scorer.dump_json({
                "schema_version": scorer.SCORE_SCHEMA_VERSION,
                "sample_id": sample_id,
                "arm_id": arm_id,
                "inputs": score["input_hashes"],
            }, os.path.join(sample_dir, "input-hashes.json"))
            print(f"[评分] {sample_id}/{arm_id}: execution_status="
                  f"{score['execution_status']} semantic_score_status="
                  f"{score['semantic_score_status']}")

    arm_ids = sorted(arm_scores)
    all_sample_ids = sorted({sample_id for arm_id in arm_ids
                             for sample_id in arm_scores[arm_id]})
    if comparison_sample_ids is None:
        comparison_sample_ids = all_sample_ids
    comparison_sample_ids = [sample_id for sample_id in comparison_sample_ids
                             if sample_id in set(all_sample_ids)]
    excluded = [sample_id for sample_id in all_sample_ids
                if sample_id not in set(comparison_sample_ids)]
    aggregates = {arm_id: scorer.aggregate_metrics(
        [arm_scores[arm_id][sample_id] for sample_id in comparison_sample_ids
         if sample_id in arm_scores[arm_id]])
        for arm_id in arm_ids}
    gap_max_by_arm = {}
    for arm_id in arm_ids:
        gaps = [max_sampling_gap_of(evidence_docs[(arm_id, sample_id)])
                for sample_id in comparison_sample_ids
                if (arm_id, sample_id) in evidence_docs]
        gaps = [gap for gap in gaps if gap is not None]
        gap_max_by_arm[arm_id] = max(gaps) if gaps else None

    document = {
        "schema_version": "1.0.0",
        "scorer": scorer.SCORER_NAME,
        "scorer_version": scorer.SCORER_VERSION,
        "adapter": "scripts/task18_scorer_adapter.py",
        "adapter_note": ("兼容适配层：冻结评分器文件零改动；仅在内存扩展策略白名单 "
                         "（+coverage_aware_adaptive）；评分/公平门/verdict 逻辑逐字复用"),
        "comparison_id": comparison_id or "task18-three-arm-comparison",
        "pack_id": manifest.get("pack_id"),
        "sample_ids": all_sample_ids,
        "comparison_sample_ids": comparison_sample_ids,
        "comparison_excluded_sample_ids": excluded,
        "comparison_exclusion_reason": (
            "预算不足场景（三臂统一预算与主对照不同）只评分不参与两两比较与 pack "
            "verdict（预注册 verdict-policy.json：pairwise sample_scope=同预算主对照）"),
        "arms": arm_ids,
        "metrics": {arm_id: {"aggregate": aggregates[arm_id]} for arm_id in arm_ids},
        "max_sampling_gap_ms": gap_max_by_arm,
        "pairwise": {},
        "per_sample_table": {
            arm_id: {sample_id: arm_scores[arm_id][sample_id]
                     for sample_id in sorted(arm_scores[arm_id])}
            for arm_id in arm_ids},
    }

    if run_pairwise and COVERAGE_ARM in arm_scores:
        pairs = [(COVERAGE_ARM, "uniform"), (COVERAGE_ARM, "adaptive"),
                 ("adaptive", "uniform")]
        attestation = fairness_attestation or {
            "no_single_side_retry": True,
            "no_extra_context": True,
            "attested_by": "task18-adapter",
            "attestation_basis": ("任务 18 预注册协议：相同场景/媒体/查询/Ground Truth/"
                                  "模型/预算/超时/分类规则；固定执行顺序；无单侧重试、"
                                  "无额外上下文、无人工修正、不删除失败场景"),
        }
        for candidate, baseline in pairs:
            if baseline not in arm_scores:
                continue
            pair_id = f"{candidate}-vs-{baseline}"
            comparison = {
                "schema_version": "1.0.0",
                "comparison_id": f"{document['comparison_id']}-{pair_id}",
                "sample_ids": comparison_sample_ids,
                "arm_a": {"arm_id": baseline, "role": "baseline"},
                "arm_b": {"arm_id": candidate, "role": "candidate"},
                "fairness_attestation": attestation,
            }
            # fairness gate 按比较范围核验（冻结评分器的 same_sample_ids /
            # same_call_budget 以传入的 arm_scores 键集合与 sample_ids 为准）：
            # 传入比较范围过滤后的臂评分，预算不足场景不进入 gate。
            scoped_arm_scores = {
                arm_id: {sample_id: arm_scores[arm_id][sample_id]
                         for sample_id in comparison_sample_ids
                         if sample_id in arm_scores[arm_id]}
                for arm_id in (baseline, candidate)}
            conditions, gate_passed = scorer.evaluate_fairness(
                comparison, manifest, ground_truths, scoped_arm_scores, evidence_docs,
                evidence_docs_paths, manifest_path)
            base_metrics = scorer.aggregate_metrics(
                [arm_scores[baseline][sample_id]
                 for sample_id in comparison_sample_ids
                 if sample_id in arm_scores[baseline]])
            cand_metrics = scorer.aggregate_metrics(
                [arm_scores[candidate][sample_id]
                 for sample_id in comparison_sample_ids
                 if sample_id in arm_scores[candidate]])
            if gate_passed:
                verdict = scorer.compute_verdict(base_metrics, cand_metrics)
            else:
                verdict = {
                    "verdict": "INVALID_COMPARISON",
                    "reason": "fairness gate 未全部通过：比较条件不满足，不计算 verdict",
                    "reason_codes": ["fairness_gate_failed"],
                    "strict_improvements": [],
                    "regressions": [],
                    "non_regression_conditions": {},
                }
            document["pairwise"][pair_id] = {
                "baseline": baseline,
                "candidate": candidate,
                "fairness_gate": {"conditions": conditions, "all_passed": gate_passed},
                "metrics": {baseline: {"aggregate": base_metrics},
                            candidate: {"aggregate": cand_metrics}},
                "verdict": verdict,
            }
            print(f"[比较] {pair_id}: fairness_gate={'PASS' if gate_passed else 'FAIL'} "
                  f"verdict={verdict['verdict']} reason_codes={verdict['reason_codes']}")

    if COVERAGE_ARM in aggregates and all(arm in aggregates for arm in BASELINE_ARMS):
        document["pack_verdict"] = pack_level_verdict(aggregates, gap_max_by_arm)
        print(f"[pack] verdict={document['pack_verdict']['verdict']} "
              f"reason_codes={document['pack_verdict']['reason_codes']}")

    scorer.assert_output_safe(document)
    scorer.dump_json(document, os.path.join(out_dir, "three-arm-comparison.json"))
    if any_hard_gate_failed:
        raise scorer.ScoringError("存在硬门失败的样本（未计分）；详见各 score.json")
    return document


def main():
    parser = argparse.ArgumentParser(
        description="任务 18 三臂评测评分适配层（复用任务 17 冻结评分器）")
    parser.add_argument("--manifest", required=True, help="Evidence Pack manifest JSON 路径")
    parser.add_argument("--predictions", required=True, help="预测集合 JSON（arms[]，臂数不限）")
    parser.add_argument("--ground-truth", required=True,
                        help="Ground Truth JSON 文件或目录（必显参数）")
    parser.add_argument("--out", required=True, help="输出目录（唯一写入位置）")
    parser.add_argument("--comparison-id", default=None, help="比较标识（可选）")
    parser.add_argument("--no-comparison", action="store_true",
                        help="只评分，不做两两比较与 pack verdict")
    parser.add_argument("--sample-scope", default=None,
                        help="逗号分隔的比较样本范围（缺省=全部已评分样本；"
                             "预算不足场景按预注册排除）")
    args = parser.parse_args()
    sample_scope = None
    if args.sample_scope:
        sample_scope = [item.strip() for item in args.sample_scope.split(",")
                        if item.strip()]

    for label, path in (("manifest", args.manifest), ("predictions", args.predictions),
                        ("ground truth", args.ground_truth)):
        if not os.path.exists(path):
            print(f"[用法错误] 找不到{label}输入: {path}", file=sys.stderr)
            return 2

    try:
        scorer = load_scorer()
        score_three_arms(scorer, args.manifest, args.predictions, args.ground_truth,
                         args.out, comparison_id=args.comparison_id,
                         run_pairwise=not args.no_comparison,
                         comparison_sample_ids=sample_scope)
    except scorer.ScoringError as error:
        print(f"[评分错误] {error}", file=sys.stderr)
        return 1
    print("RESULT: SCORED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
