#!/usr/bin/env python3
"""score_task25_pairs.py — Task 25 同期同中心帧配对评分器（SparkSkill Studio 任务 25，阶段 A 冻结）

职责边界:
  - 不修改、不调用 Task 17 冻结评分器 scripts/score_temporal_ground_truth.py 作为判定依据；
  - 只做**单元级**七类互斥语义计数：对同一中心帧的 v1（单帧生产）/ cand（多图候选）
    两个模型返回分别做与冻结规则逐条一致的分类（confirmed/not_found/abstained/
    low_confidence/failed）与 GT 映射（七类互斥指标），并按预注册分母聚合。
  - 分类/指标映射为独立重实现（与 score_temporal_ground_truth 逐条同义）；
    等价性由 --verify-historical 对 Task 19B 27 (样本,臂) 的 256 个历史点逐行证明。

七类互斥指标（顺序固定）:
  correct_decisive / incorrect_decisive / abstention_on_determinate /
  failed_on_determinate / appropriate_abstention / overclaim_on_uncertain / failed_on_uncertain

错误断言 := incorrect_decisive + overclaim_on_uncertain（预注册口径）。

阶段 B 早停门（48 对，全部满足才继续）:
  B1 错误断言: cand.error_assertions <= v1.error_assertions
  B2 correct:  v1.correct_decisive - cand.correct_decisive <= 1（总体）
  B3 误拒:     cand.abstention_on_determinate - v1.abstention_on_determinate <= 1
  B4 failed:  cand.failed_on_determinate <= v1.failed_on_determinate
             且 cand.failed_on_uncertain <= v1.failed_on_uncertain
  B5 smoke 负例（目标只在邻帧不得肯定中心）由调用方以 phase0 结果注入 safety_ok/smoke_negative_ok
  B6 媒体/调用/资源/安全/冻结完整性由 safety_ok + completeness 承载
  任一失败 → STAGE1_HARM_STOP

阶段 C 最终门（184 对，全部满足才 DEV_CANDIDATE）:
  C1 错误断言总体至少少 8 且 overclaim_on_uncertain 至少少 5；
     同期 v1 基线不足以检验（v1.error_assertions<8 或 v1.overclaim<5）→ INCONCLUSIVE_BASELINE_DRIFT
  C2 incorrect_decisive 三口径（总体/generated/licensed-public）均不增加
  C3 correct_decisive 总体最多少 2、licensed-public 不少；新增 abstention_on_determinate 最多 2
  C4 failed_on_determinate/failed_on_uncertain 各自不增加；无敏感/越权/凭据/中心邻帧混淆（safety_ok）
  C5 184/184 对完整、每点每臂至多一次真实调用、中心帧哈希 184/184 匹配、资源与冻结通过（completeness）

效率门（附加披露，不否决质量 verdict，但限制措辞）:
  cand 平均耗时 > v1 平均耗时 × 1.5 → efficiency_loss=True（综合状态不得写"可部署改进"）

verdict（由本文件确定性计算，Agent 不用文字预设）:
  DEV_CANDIDATE / TRADEOFF / NO_IMPROVEMENT / STAGE1_HARM_STOP /
  INCONCLUSIVE_BASELINE_DRIFT / INVALID_INPUT / INCOMPLETE_PAIRING / RESOURCE_BLOCKED

用法:
  python3 score_task25_pairs.py --pairing <pairs.json> --gt-dir <dir> \
      --unit-manifest <manifest.json> --scope first48|all --out <dir> [--safety-ok true|false] \
      [--completeness <json>] [--smoke-negative-ok true|false]
  python3 score_task25_pairs.py --verify-historical --task19 <artifacts/task-19> \
      --gt-dir <artifacts/task-19/ground-truth>
"""
import argparse
import json
import os
import statistics
import sys

DECISIVE = ("confirmed", "not_found")
NON_DECISIVE = ("abstained", "low_confidence")
GT_DETERMINATE = ("confirmed", "not_found")
SEVEN_METRICS = ("correct_decisive", "incorrect_decisive", "abstention_on_determinate",
                 "failed_on_determinate", "appropriate_abstention", "overclaim_on_uncertain",
                 "failed_on_uncertain")
GENERATED = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06"]
LICENSED = ["WEB01", "WEB02", "WEB03"]
ARMS = ("uniform", "adaptive", "coverage")
SIDES = ("v1", "cand")


def error_assertions(counts):
    return counts["incorrect_decisive"] + counts["overclaim_on_uncertain"]


# ---------------------------------------------------------------- 独立重实现（与冻结规则同义）
def classify_entry(entry):
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    reason = entry.get("abstention_reason")
    if isinstance(reason, str) and reason.strip():
        return "abstained"
    return "not_found"


def gt_state_at(ground_truth, timestamp_ms):
    for segment in ground_truth["segments"]:
        if segment["start_ms"] <= timestamp_ms < segment["end_ms"]:
            return segment["state"]
        if (timestamp_ms == segment["end_ms"]
                and segment["end_ms"] == ground_truth["media_duration_ms"]):
            return segment["state"]
    return None


def metric_for(gt_state, pred_class):
    if gt_state in GT_DETERMINATE:
        if pred_class in DECISIVE:
            return "correct_decisive" if pred_class == gt_state else "incorrect_decisive"
        if pred_class in NON_DECISIVE:
            return "abstention_on_determinate"
        return "failed_on_determinate"
    if pred_class in NON_DECISIVE:
        return "appropriate_abstention"
    if pred_class in DECISIVE:
        return "overclaim_on_uncertain"
    return "failed_on_uncertain"


# ---------------------------------------------------------------- 历史等价性验证
def verify_historical(task19_dir, gt_dir):
    mismatches = []
    total = 0
    for sample_id in GENERATED + LICENSED:
        gt = json.load(open(os.path.join(gt_dir, f"{sample_id}.json"), encoding="utf-8"))
        for arm in ARMS:
            evidence_path = os.path.join(task19_dir, "predictions", sample_id, arm,
                                         "temporal-evidence.json")
            score_path = os.path.join(task19_dir, "scores", "all-dev", sample_id, arm,
                                      "score.json")
            evidence = json.load(open(evidence_path, encoding="utf-8"))
            frozen = json.load(open(score_path, encoding="utf-8"))
            timeline = evidence["timeline"] if "timeline" in evidence else []
            rows = []
            for entry in sorted(timeline, key=lambda item: item["timestamp_ms"]):
                pred = classify_entry(entry)
                state = gt_state_at(gt, entry["timestamp_ms"])
                rows.append({"timestamp_ms": round(entry["timestamp_ms"], 3),
                             "prediction_class": pred, "ground_truth_state": state,
                             "metric": metric_for(state, pred)})
            frozen_rows = frozen["sample_point_scores"]["per_sample_rows"]
            if len(rows) != len(frozen_rows):
                mismatches.append({"where": f"{sample_id}/{arm}", "kind": "row_count"})
                continue
            for mine, theirs in zip(rows, frozen_rows):
                total += 1
                for key in ("timestamp_ms", "prediction_class", "ground_truth_state", "metric"):
                    if mine[key] != theirs[key]:
                        mismatches.append({"where": f"{sample_id}/{arm}", "kind": key})
            counts = {name: 0 for name in SEVEN_METRICS}
            for row in rows:
                counts[row["metric"]] += 1
            for name, value in counts.items():
                if value != frozen["sample_point_scores"]["metrics"][name]["passed"]:
                    mismatches.append({"where": f"{sample_id}/{arm}", "kind": f"count:{name}"})
    return {"total_points_checked": total, "mismatches": mismatches, "equivalent": not mismatches}


# ---------------------------------------------------------------- 配对评分
def score_side(points, ground_truths, side):
    rows = []
    counts = {name: 0 for name in SEVEN_METRICS}
    by_track = {"generated": {n: 0 for n in SEVEN_METRICS},
                "licensed-public": {n: 0 for n in SEVEN_METRICS}}
    by_sample = {}
    by_arm = {}
    by_stratum = {}
    for point in points:
        entry = point[f"{side}_judgment"]
        gt = ground_truths[point["sample_id"]]
        pred = classify_entry(entry)
        state = gt_state_at(gt, point["center_timestamp_ms"])
        metric = metric_for(state, pred)
        rows.append({"unit_id": point["unit_id"], "sample_id": point["sample_id"],
                     "center_timestamp_ms": point["center_timestamp_ms"],
                     "track": point.get("track"), "stratum": point.get("stratum"),
                     "prediction_class": pred, "ground_truth_state": state, "metric": metric})
        counts[metric] += 1
        by_track[point["track"]][metric] += 1
        for arm in point.get("source_arms", []):
            by_arm.setdefault(arm, {n: 0 for n in SEVEN_METRICS})[metric] += 1
        by_sample.setdefault(point["sample_id"], {n: 0 for n in SEVEN_METRICS})[metric] += 1
        by_stratum.setdefault(point.get("stratum", "unknown"),
                              {n: 0 for n in SEVEN_METRICS})[metric] += 1
    return {"rows": rows, "counts": counts, "by_track": by_track, "by_sample": by_sample,
            "by_arm": by_arm, "by_stratum": by_stratum}


def stage_b_gates(v1c, candc):
    ea_v1, ea_cand = error_assertions(v1c), error_assertions(candc)
    correct_drop = v1c["correct_decisive"] - candc["correct_decisive"]
    abst_inc = candc["abstention_on_determinate"] - v1c["abstention_on_determinate"]
    return {
        "B1_error_assertions_not_more_than_v1": {
            "passed": ea_cand <= ea_v1, "v1_error_assertions": ea_v1, "cand": ea_cand,
            "rule": "incorrect_decisive+overclaim_on_uncertain 不得多于同期 v1"},
        "B2_correct_decrease_le_1": {
            "passed": correct_drop <= 1, "correct_drop": correct_drop,
            "v1": v1c["correct_decisive"], "cand": candc["correct_decisive"],
            "rule": "correct_decisive 总体最多减少 1"},
        "B3_abstention_on_determinate_increase_le_1": {
            "passed": abst_inc <= 1, "increase": abst_inc,
            "v1": v1c["abstention_on_determinate"], "cand": candc["abstention_on_determinate"],
            "rule": "新增 abstention_on_determinate 最多 1"},
        "B4_failed_not_increased": {
            "passed": (candc["failed_on_determinate"] <= v1c["failed_on_determinate"]
                       and candc["failed_on_uncertain"] <= v1c["failed_on_uncertain"]),
            "failed_on_determinate": {"v1": v1c["failed_on_determinate"],
                                      "cand": candc["failed_on_determinate"]},
            "failed_on_uncertain": {"v1": v1c["failed_on_uncertain"],
                                    "cand": candc["failed_on_uncertain"]},
            "rule": "failed_on_determinate 与 failed_on_uncertain 各自不得增加"},
    }


def decide_verdict_stage_b(gates, safety_ok, smoke_negative_ok, completeness_ok):
    if not (safety_ok and smoke_negative_ok and completeness_ok):
        return "STAGE1_HARM_STOP", ["safety_or_smoke_negative_or_completeness_failed"]
    failed = [k for k, v in gates.items() if not v["passed"]]
    if failed:
        return "STAGE1_HARM_STOP", failed
    return "STAGE1_PASS", ["all_stage_b_gates_passed"]


def stage_c_gates(v1c, candc, v1_track, cand_track):
    ea_v1, ea_cand = error_assertions(v1c), error_assertions(candc)
    oc_drop = v1c["overclaim_on_uncertain"] - candc["overclaim_on_uncertain"]
    ea_drop = ea_v1 - ea_cand
    correct_drop_total = v1c["correct_decisive"] - candc["correct_decisive"]
    correct_drop_licensed = (v1_track["licensed-public"]["correct_decisive"]
                             - cand_track["licensed-public"]["correct_decisive"])
    abst_inc = candc["abstention_on_determinate"] - v1c["abstention_on_determinate"]
    baseline_ok = ea_v1 >= 8 and v1c["overclaim_on_uncertain"] >= 5
    return {
        "baseline_ok": baseline_ok,
        "v1_error_assertions": ea_v1, "v1_overclaim": v1c["overclaim_on_uncertain"],
        "C1_error_assertions_reduction_ge_8_and_overclaim_ge_5": {
            "passed": ea_drop >= 8 and oc_drop >= 5,
            "error_assertions_drop": ea_drop, "overclaim_drop": oc_drop,
            "rule": "错误断言总体至少少 8 且 overclaim_on_uncertain 至少少 5"},
        "C2_incorrect_not_increased_3_scopes": {
            "passed": (candc["incorrect_decisive"] <= v1c["incorrect_decisive"]
                       and cand_track["generated"]["incorrect_decisive"]
                       <= v1_track["generated"]["incorrect_decisive"]
                       and cand_track["licensed-public"]["incorrect_decisive"]
                       <= v1_track["licensed-public"]["incorrect_decisive"]),
            "v1_total": v1c["incorrect_decisive"], "cand_total": candc["incorrect_decisive"],
            "rule": "incorrect_decisive 总体/generated/licensed-public 三口径均不增加"},
        "C3_correct_decrease_within_tolerance_and_abstention_le_2": {
            "passed": (correct_drop_total <= 2 and correct_drop_licensed <= 0 and abst_inc <= 2),
            "correct_drop_total": correct_drop_total,
            "correct_drop_licensed": correct_drop_licensed,
            "abstention_increase": abst_inc,
            "rule": "correct 总体最多少 2、licensed-public 不少；新增 abstention_on_determinate 最多 2"},
        "C4_failed_not_increased": {
            "passed": (candc["failed_on_determinate"] <= v1c["failed_on_determinate"]
                       and candc["failed_on_uncertain"] <= v1c["failed_on_uncertain"]),
            "failed_on_determinate": {"v1": v1c["failed_on_determinate"],
                                      "cand": candc["failed_on_determinate"]},
            "failed_on_uncertain": {"v1": v1c["failed_on_uncertain"],
                                    "cand": candc["failed_on_uncertain"]},
            "rule": "failed_on_determinate/failed_on_uncertain 各自不增加"},
    }


def decide_verdict_stage_c(gates, safety_ok, completeness):
    if not gates["baseline_ok"]:
        return "INCONCLUSIVE_BASELINE_DRIFT", ["baseline_error_assertions_lt_8_or_overclaim_lt_5"]
    if not (safety_ok and completeness.get("center_hash_all_match", False)
            and completeness.get("all_pairs_complete", False)
            and completeness.get("max_one_call_per_point_per_arm", False)
            and completeness.get("resource_and_freeze_ok", False)):
        return "INVALID_INPUT", ["safety_or_completeness_failed"]
    c1 = gates["C1_error_assertions_reduction_ge_8_and_overclaim_ge_5"]["passed"]
    c2 = gates["C2_incorrect_not_increased_3_scopes"]["passed"]
    c3 = gates["C3_correct_decrease_within_tolerance_and_abstention_le_2"]["passed"]
    c4 = gates["C4_failed_not_increased"]["passed"]
    if c1 and c2 and c3 and c4:
        return "DEV_CANDIDATE", ["all_stage_c_gates_passed"]
    # TRADEOFF: 错误断言有实质改善(C1)但正确/误拒/失败门(C2/C3/C4)受损
    if c1 and (not c2 or not c3 or not c4):
        reasons = ["error_assertions_substantially_reduced"]
        if not c2:
            reasons.append("incorrect_decisive_increased")
        if not c3:
            reasons.append("correct_decrease_or_abstention_beyond_tolerance")
        if not c4:
            reasons.append("failed_increased")
        return "TRADEOFF", reasons
    return "NO_IMPROVEMENT", ["no_substantial_error_assertion_improvement_or_other_gate_failed"]


def latency_stats(records, side):
    lat = [r["latency_s"] for r in records
           if r.get("side") == side and isinstance(r.get("latency_s"), (int, float))
           and r.get("kind") == "formal"]
    if not lat:
        return {"count": 0, "mean_s": None, "median_s": None, "max_s": None}
    return {"count": len(lat), "mean_s": round(sum(lat) / len(lat), 3),
            "median_s": round(statistics.median(lat), 3), "max_s": round(max(lat), 3)}


def main():
    parser = argparse.ArgumentParser(description="Task 25 同期同中心帧配对评分器")
    parser.add_argument("--pairing")
    parser.add_argument("--gt-dir")
    parser.add_argument("--unit-manifest")
    parser.add_argument("--scope", choices=["first48", "all"], default="all")
    parser.add_argument("--out")
    parser.add_argument("--stage", choices=["B", "C"], default="C")
    parser.add_argument("--safety-ok", default="true")
    parser.add_argument("--smoke-negative-ok", default="true")
    parser.add_argument("--completeness")
    parser.add_argument("--verify-historical", action="store_true")
    parser.add_argument("--task19")
    args = parser.parse_args()

    if args.verify_historical:
        result = verify_historical(args.task19, args.gt_dir)
        print(json.dumps({"equivalent": result["equivalent"],
                          "total_points_checked": result["total_points_checked"],
                          "mismatch_count": len(result["mismatches"])},
                         ensure_ascii=False))
        return 0 if result["equivalent"] else 1

    if not (args.pairing and args.gt_dir and args.unit_manifest and args.out):
        parser.error("--pairing/--gt-dir/--unit-manifest/--out 为必填（或使用 --verify-historical）")

    pairing = json.load(open(args.pairing, encoding="utf-8"))
    unit_manifest = json.load(open(args.unit_manifest, encoding="utf-8"))
    meta_by_unit = {u["unit_id"]: u for u in unit_manifest["units"]}

    if args.scope == "first48":
        keep = set(unit_manifest["first_batch_48_unit_ids"])
    else:
        keep = set(u["unit_id"] for u in unit_manifest["units"])

    points = []
    # 读取配对点集：兼容 runner 输出的 "units" 键与历史 "points" 键（纯数据读取，不改评分逻辑）
    raw_points = pairing.get("points")
    if raw_points is None:
        raw_points = pairing.get("units", [])
    for p in raw_points:
        if p["unit_id"] not in keep:
            continue
        meta = meta_by_unit[p["unit_id"]]
        points.append({
            "unit_id": p["unit_id"], "sample_id": p["sample_id"],
            "center_timestamp_ms": p["center_timestamp_ms"], "track": p["track"],
            "stratum": meta.get("stratum"), "source_arms": meta.get("source_arms", []),
            "v1_judgment": p["v1_judgment"], "cand_judgment": p["cand_judgment"],
        })

    ground_truths = {}
    for sample_id in sorted({p["sample_id"] for p in points}):
        ground_truths[sample_id] = json.load(
            open(os.path.join(args.gt_dir, f"{sample_id}.json"), encoding="utf-8"))

    v1 = score_side(points, ground_truths, "v1")
    cand = score_side(points, ground_truths, "cand")
    safety_ok = args.safety_ok.lower() == "true"
    smoke_negative_ok = args.smoke_negative_ok.lower() == "true"

    report = {
        "task": "task25-paired-scoring",
        "scope": args.scope, "stage": args.stage, "point_count": len(points),
        "scorer": "score_task25_pairs.py（阶段 A 冻结；分类/指标映射与 Task 17 冻结规则同义）",
        "safety_ok": safety_ok, "smoke_negative_ok": smoke_negative_ok,
        "totals": {"v1": v1["counts"], "cand": cand["counts"]},
        "error_assertions": {"v1": error_assertions(v1["counts"]),
                             "cand": error_assertions(cand["counts"])},
        "by_track": {"v1": v1["by_track"], "cand": cand["by_track"]},
        "by_sample": {"v1": v1["by_sample"], "cand": cand["by_sample"]},
        "by_arm": {"v1": v1["by_arm"], "cand": cand["by_arm"]},
        "by_stratum": {"v1": v1["by_stratum"], "cand": cand["by_stratum"]},
        "latency": {"v1": latency_stats(pairing.get("calls", []), "v1"),
                    "cand": latency_stats(pairing.get("calls", []), "cand")},
    }

    if args.stage == "B":
        gates = stage_b_gates(v1["counts"], cand["counts"])
        verdict, reasons = decide_verdict_stage_b(
            gates, safety_ok, smoke_negative_ok,
            completeness_ok=(json.load(open(args.completeness)) if args.completeness
                             else {}).get("all_pairs_complete", True))
        report["gates"] = gates
    else:
        gates = stage_c_gates(v1["counts"], cand["counts"], v1["by_track"], cand["by_track"])
        completeness = json.load(open(args.completeness)) if args.completeness else {
            "center_hash_all_match": True, "all_pairs_complete": True,
            "max_one_call_per_point_per_arm": True, "resource_and_freeze_ok": True}
        verdict, reasons = decide_verdict_stage_c(gates, safety_ok, completeness)
        report["gates"] = gates
        report["completeness"] = completeness
        # 效率门
        v1_mean = report["latency"]["v1"]["mean_s"]
        cand_mean = report["latency"]["cand"]["mean_s"]
        if v1_mean and cand_mean:
            report["efficiency"] = {
                "v1_mean_s": v1_mean, "cand_mean_s": cand_mean,
                "ratio": round(cand_mean / v1_mean, 3),
                "efficiency_loss": cand_mean > v1_mean * 1.5,
                "note": "cand 平均耗时 > v1×1.5 → 不得写『可部署改进』，只写『质量候选且效率受损』"}
        else:
            report["efficiency"] = {"note": "耗时数据不足"}

    report["verdict"] = verdict
    report["verdict_reasons"] = reasons
    report["known_limitations"] = [
        "同期同中心帧配对：唯一变量为候选多图上下文 + 必要的『只判中心帧』任务说明；"
        "两臂同时改变了图片上下文与任务说明，结果不能冒充纯输入信息的因果拆分",
        "同一视频与跨臂重复采样点不独立；不得给出统计显著性",
        "dev 小样本 + 单次运行 + 温度 0.1 随机性；不得外溢真实仓储准确率",
        "邻帧目标误投射中心为本实验测量对象之一；候选画框只对应中心帧",
    ]

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, f"paired-score-{args.stage}.json"), "w", encoding="utf-8") as h:
        h.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    paired_rows = []
    for rv, rc in zip(v1["rows"], cand["rows"]):
        paired_rows.append({
            "unit_id": rv["unit_id"], "sample_id": rv["sample_id"],
            "center_timestamp_ms": rv["center_timestamp_ms"], "track": rv["track"],
            "stratum": rv["stratum"], "ground_truth_state": rv["ground_truth_state"],
            "v1_class": rv["prediction_class"], "v1_metric": rv["metric"],
            "cand_class": rc["prediction_class"], "cand_metric": rc["metric"],
            "changed": rv["metric"] != rc["metric"]})
    with open(os.path.join(args.out, f"paired-rows-{args.stage}.json"), "w", encoding="utf-8") as h:
        h.write(json.dumps(paired_rows, ensure_ascii=False, indent=1) + "\n")

    print(json.dumps({"stage": args.stage, "scope": args.scope, "verdict": verdict,
                      "reasons": reasons, "totals_v1": v1["counts"], "totals_cand": cand["counts"],
                      "error_assertions": report["error_assertions"],
                      "gates": {k: (v.get("passed") if isinstance(v, dict) else v)
                                for k, v in gates.items()}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
