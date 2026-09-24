#!/usr/bin/env python3
"""run_task21_replay.py — Task 21 固定采样时序重放（SparkSkill Studio 任务 21，阶段 C）

性质：**fixed_sample_replay**。沿 Task 19B 已选定的九个样本 × 三个 arm 的原时间戳，
用 Task 20 已存档的同期 v1/v2 逐帧判断重建时间序列，并在 Task 17 冻结规则下做
规则级、可复核的转换与边界诊断。

硬纪律:
  - **零新模型调用**：唯一模型输出来源是 artifacts/task-20/pairs/points/ 的存档判断；
    不调用 Qwen/StepFun/DSH，不抽帧、不联网、不写任何输入文件；
  - **不去重代表行**：相同 (样本, 时间戳) 在不同 arm 的存档输出可能不同，每个 arm
    的时间序列只用该 arm 自身的存档判断；
  - **失败点保持 failed**：v2 的 uncertain 契约失败点不得改写为拒答；
  - **规则零改动**：只读导入 Task 17 冻结 scorer 与冻结采样器的纯函数
    （classify_entry / gt_state_at / metric_for / score_sample_points / score_events /
     score_boundaries / check_provenance_consistency / build_temporal_evidence），
    不修改 Task 17 scorer、Task 18/19 适配器或任何历史 artifacts；
  - **不伪造 provenance**：正式 Task 17 评分需要"本轮新鲜调用"自洽；本 replay 本轮
    零调用，因此以冻结 check_provenance_consistency 实证正式评分阻塞，并把正式评分
    标记为 REPLAY_UNSCORABLE（详见产物 scoreability 段）；
  - 确定性：输出不含墙钟时间戳/主机名/绝对用户路径；同一输入两次运行逐字节相同。

用法:
    python3 scripts/run_task21_replay.py [--out artifacts/task-21/replay]
退出码: 0 = 重放完成; 2 = 输入映射失败（INVALID_INPUT，不产出重放结论）
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCORER_PATH = os.path.join(PROJECT_ROOT, "scripts", "score_temporal_ground_truth.py")
SAMPLER_PATH = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                            "scripts", "adaptive_sampler.py")
TASK19 = os.path.join(PROJECT_ROOT, "artifacts", "task-19")
TASK20 = os.path.join(PROJECT_ROOT, "artifacts", "task-20")
TASK21 = os.path.join(PROJECT_ROOT, "artifacts", "task-21")
GT_DIR = os.path.join(TASK19, "ground-truth")
POINTS_DIR = os.path.join(TASK20, "pairs", "points")

SAMPLES = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06", "WEB01", "WEB02", "WEB03"]
ARMS = ("uniform", "adaptive", "coverage")
VERSIONS = ("v1", "v2")
VERSION_LABELS = {"v1": "同期 v1（Task 20 存档）", "v2": "同期 v2（Task 20 存档）"}
ARM_STRATEGY = {"uniform": "uniform",
                "adaptive": "adaptive_coarse_to_fine",
                "coverage": "coverage_aware_adaptive"}
EXPECTED_ARM_POINTS = {"uniform": 121, "adaptive": 51, "coverage": 84}
GT_BOUNDARY_SAMPLES = {"AI02": 2, "AI03": 2, "AI04": 2, "WEB01": 2}  # 8 个不同 GT 边界


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def round3(value):
    return round(float(value), 3)


# ---------------------------------------------------------------- 输入加载与映射核验

def load_inputs():
    point_paths = sorted(glob.glob(os.path.join(POINTS_DIR, "T20-P*.json")))
    if len(point_paths) != 256:
        raise SystemExit(f"[INVALID_INPUT] Task 20 逐点文件数 {len(point_paths)} != 256")
    points = [load_json(path) for path in point_paths]
    ids = [p["point_id"] for p in points]
    if len(set(ids)) != 256:
        raise SystemExit("[INVALID_INPUT] point_id 不唯一")
    ground_truths = {}
    for sample_id in SAMPLES:
        ground_truths[sample_id] = load_json(os.path.join(GT_DIR, f"{sample_id}.json"))
    task19_timelines = {}
    for sample_id in SAMPLES:
        for arm in ARMS:
            evidence = load_json(os.path.join(
                TASK19, "predictions", sample_id, arm, "temporal-evidence.json"))
            task19_timelines[(sample_id, arm)] = sorted(
                round3(entry["timestamp_ms"]) for entry in evidence["timeline"])
    return points, ground_truths, task19_timelines


def verify_mapping(points, task19_timelines):
    """256 点 ↔ 27 运行一一对应；返回问题列表（空 = 通过）。

    口径：27 个 (样本, 臂) 分组各非空且时间戳序列与 Task 19B timeline 逐项相等；
    每臂点数（跨 9 样本求和）为 uniform 121 / adaptive 51 / coverage 84；总点数 256。
    """
    problems = []
    groups = {}
    for point in points:
        key = (point["sample_id"], point["arm"])
        groups.setdefault(key, []).append(point)
    if len(groups) != 27:
        problems.append(f"(样本,臂) 分组数 {len(groups)} != 27")
    arm_totals = {arm: 0 for arm in ARMS}
    for sample_id in SAMPLES:
        for arm in ARMS:
            key = (sample_id, arm)
            group = groups.get(key, [])
            if not group:
                problems.append(f"{sample_id}/{arm} 无采样点")
                continue
            arm_totals[arm] += len(group)
            sequence = sorted(round3(p["timestamp_ms"]) for p in group)
            if sequence != task19_timelines[key]:
                problems.append(f"{sample_id}/{arm} 时间戳序列与 Task 19B timeline 不一致")
    for arm in ARMS:
        if arm_totals[arm] != EXPECTED_ARM_POINTS[arm]:
            problems.append(f"臂 {arm} 总点数 {arm_totals[arm]} != "
                            f"{EXPECTED_ARM_POINTS[arm]}")
    total = sum(len(group) for group in groups.values())
    if total != 256:
        problems.append(f"总点数 {total} != 256")
    return problems


# ---------------------------------------------------------------- 重放核心

def arm_points(points, sample_id, arm):
    return sorted((p for p in points if p["sample_id"] == sample_id and p["arm"] == arm),
                  key=lambda p: round3(p["timestamp_ms"]))


def replay_run(scorer, sampler, points, ground_truths, sample_id, arm, version):
    """对单个 (样本, 臂, 版本) 重建时间序列并应用冻结规则。"""
    selected = arm_points(points, sample_id, arm)
    # 时间线条目 = 存档判断原样 + 点级 timestamp_ms（浅拷贝注入，存档判断字段零改动）；
    # 冻结 build_temporal_evidence / score_* 均以 entry["timestamp_ms"] 为键。
    timeline = [dict(point["judgments"][version], timestamp_ms=round3(point["timestamp_ms"]))
                for point in selected]
    gt = ground_truths[sample_id]
    duration_ms = gt["media_duration_ms"]

    # 状态转换：冻结 build_temporal_evidence（相邻类别变化；不伪造精确瞬间）
    temporal = sampler.build_temporal_evidence(
        timeline, actual_model_calls=len(timeline), duration_ms=duration_ms)
    evidence_doc = {"temporal_evidence": temporal}

    sample_points = scorer.score_sample_points(timeline, gt)
    events = scorer.score_events(timeline, gt)
    boundaries = scorer.score_boundaries(timeline, gt, evidence_doc)

    status_sequence = [
        {"timestamp_ms": round3(point["timestamp_ms"]),
         "class": scorer.classify_entry(point["judgments"][version]),
         "point_id": point["point_id"],
         "evidence_nature": point["judgments"][version].get("evidence_nature")}
        for point in selected]
    failed_points = [item["point_id"] for item in status_sequence if item["class"] == "failed"]

    return {
        "sample_id": sample_id,
        "arm": arm,
        "version": version,
        "strategy_name": ARM_STRATEGY[arm],
        "point_count": len(selected),
        "status_sequence": status_sequence,
        "state_transitions": temporal["state_transitions"],
        "class_counts": temporal["class_counts"],
        "sample_point_scores": {
            "denominator_analyzed_samples": sample_points["denominator_analyzed_samples"],
            "denominator_determinate_samples":
                sample_points["denominator_determinate_samples"],
            "denominator_uncertain_samples": sample_points["denominator_uncertain_samples"],
            "metrics": sample_points["metrics"],
            "per_sample_rows": sample_points["per_sample_rows"],
        },
        "event_scores": events,
        "boundary_scores": boundaries,
        "max_adjacent_sampling_gap_ms_final":
            temporal["coverage"]["max_adjacent_sampling_gap_ms_final"],
        "failed_points": failed_points,
        "scoreability": scoreability_check(scorer, timeline, ARM_STRATEGY[arm],
                                           temporal["class_counts"]),
    }


def candidate_replay_evidence(timeline, strategy_name, class_counts, cache_status):
    """构造候选 replay temporal-evidence 文档（仅用于冻结 provenance 检查，不落盘）。

    timeline：该 (样本, 臂, 版本) 的重放时间线（存档判断 + timestamp_ms 浅拷贝），
    分类字段完整，供冻结 check_provenance_consistency 复算五类计数。
    """
    n = len(timeline)
    return {
        "schema_version": "1.3.0",
        "sampling_strategy": strategy_name,
        "timeline": timeline,
        "sampling_provenance": {
            "actual_model_calls": n,
            "configured_budget": None,
            "decisions": [{"timestamp_ms": entry["timestamp_ms"],
                           "cache_status": cache_status} for entry in timeline],
            "analyzed_timestamps": [entry["timestamp_ms"] for entry in timeline],
        },
        "temporal_evidence": {"class_counts": class_counts,
                              "actual_model_calls": n},
    }


def scoreability_check(scorer, timeline, strategy_name, class_counts):
    """用冻结 check_provenance_consistency 实证正式评分阻塞（单个运行）。

    诚实变体：决策标记 archived_call（本轮零新调用的事实）；
    伪造变体：决策标记 fresh_call（把 Task 20 已存档调用冒充本轮新鲜调用——禁止）。
    """
    result = {}
    for variant, cache_status in (("honest", "archived_call"),
                                  ("fabricated", "fresh_call")):
        doc = candidate_replay_evidence(timeline, strategy_name, class_counts, cache_status)
        problems = scorer.check_provenance_consistency(doc)
        result[variant] = sorted({item["code"] for item in problems})
    return result


def scoreability_analysis(runs):
    """汇总 54 个 (版本, 样本, 臂) 的冻结 provenance 检查，得出正式可评分性结论。"""
    honest = {}
    fabricated = {}
    for run in runs:
        key = f"{run['version']}/{run['sample_id']}/{run['arm']}"
        honest[key] = run["scoreability"]["honest"]
        fabricated[key] = run["scoreability"]["fabricated"]
    honest_all_fail = all(bool(codes) for codes in honest.values())
    fabricated_uniform_adaptive_pass = all(
        not codes for key, codes in fabricated.items() if not key.endswith("/coverage"))
    if honest_all_fail:
        conclusion = (
            "REPLAY_UNSCORABLE：冻结 Task 17 scorer 的 G7 provenance 自洽要求 "
            "actual_model_calls == fresh_call 决策数 == 时间线条目数。诚实标注（archived_call，"
            "本轮零新调用）在全部 54 个 (版本,样本,臂) 候选文档上均判 provenance_inconsistent"
            "（coverage 臂另带 invalid_strategy）。唯一可让其通过的方式是把 Task 20 已存档调用"
            "冒充为本轮 fresh_call——属于伪造 provenance，明令禁止；即便对 uniform/adaptive 臂"
            "伪造后 G7 可通过，coverage 臂还需 Task 18/19 适配层的内存策略白名单扩展"
            "（既揭惯例、非文件修改），但该惯例不能拯救 provenance 伪造。"
            "故正式评分不可执行，保留 Task 17 规则级转换与边界诊断。")
    else:
        conclusion = "UNEXPECTED：诚实变体未全部被 G7 拒绝，需人工复核。"
    return {
        "honest": honest,
        "fabricated": fabricated,
        "honest_variant_all_g7_failed": honest_all_fail,
        "fabricated_uniform_adaptive_g7_passed": fabricated_uniform_adaptive_pass,
        "conclusion": conclusion,
    }


def aggregate(scorer, runs):
    """每版汇总：七类计数、边界暴露（8 个不同边界 × 3 臂 = 24 次暴露）、事件覆盖等。"""
    summary = {}
    for version in VERSIONS:
        selected = [run for run in runs if run["version"] == version]
        totals = {name: 0 for name in scorer.SEVEN_METRICS}
        determinate_total = 0
        uncertain_total = 0
        for run in selected:
            metrics = run["sample_point_scores"]["metrics"]
            for name in scorer.SEVEN_METRICS:
                totals[name] += metrics[name]["passed"]
            determinate_total += run["sample_point_scores"]["denominator_determinate_samples"]
            uncertain_total += run["sample_point_scores"]["denominator_uncertain_samples"]
        # 边界：8 个不同 GT 边界，每臂一次暴露（共 24 次暴露，不是 24 个独立边界）
        boundary_exposures = []
        distinct_matched = set()
        for run in selected:
            for detail in run["boundary_scores"]["matched_boundary_details"]:
                distinct_matched.add(detail["gt_boundary_at_ms"])
            boundary_exposures.append({
                "sample_id": run["sample_id"], "arm": run["arm"],
                "gt_boundaries_total": run["boundary_scores"]["gt_boundaries_total"],
                "matched_boundaries": run["boundary_scores"]["matched_boundaries"],
                "missed_gt_boundaries": run["boundary_scores"]["missed_gt_boundaries"],
                "within_tolerance_boundaries":
                    run["boundary_scores"]["within_tolerance_boundaries"],
                "unmatched_predicted_transitions":
                    run["boundary_scores"]["unmatched_predicted_transitions"],
            })
        matched_exposures = sum(item["matched_boundaries"] for item in boundary_exposures)
        total_exposures = sum(item["gt_boundaries_total"] for item in boundary_exposures)
        # 逐边界（8 个不同 GT 边界）× 三臂暴露矩阵
        boundary_matrix = []
        for sample_id, count in sorted(GT_BOUNDARY_SAMPLES.items()):
            gt = None
            runs_for_sample = [run for run in selected if run["sample_id"] == sample_id]
            boundaries = runs_for_sample[0]["boundary_scores"]["gt_boundaries"] if runs_for_sample else []
            for boundary in boundaries:
                row = {"sample_id": sample_id, "at_ms": boundary["at_ms"],
                       "from_state": boundary["from_state"], "to_state": boundary["to_state"],
                       "per_arm": {}}
                for run in runs_for_sample:
                    matched = [d for d in run["boundary_scores"]["matched_boundary_details"]
                               if d["gt_boundary_at_ms"] == boundary["at_ms"]]
                    row["per_arm"][run["arm"]] = (
                        {"matched": True,
                         "bracket_left_ms": matched[0]["bracket_left_ms"],
                         "bracket_right_ms": matched[0]["bracket_right_ms"],
                         "bracket_midpoint_ms": matched[0]["bracket_midpoint_ms"],
                         "midpoint_abs_error_ms": matched[0]["midpoint_abs_error_ms"],
                         "within_tolerance": matched[0]["within_tolerance"]}
                        if matched else {"matched": False})
                boundary_matrix.append(row)
        events = {
            "gt_confirmed_segments": sum(run["event_scores"]["gt_confirmed_segments"]
                                         for run in selected),
            "covered_confirmed_events": sum(run["event_scores"]["covered_confirmed_events"]
                                            for run in selected),
            "missed_confirmed_events": sum(run["event_scores"]["missed_confirmed_events"]
                                           for run in selected),
            "unreached_uncertain_segments": sum(
                run["event_scores"]["unreached_uncertain_segments"] for run in selected),
        }
        by_arm = {}
        for arm in ARMS:
            arm_runs = [run for run in selected if run["arm"] == arm]
            by_arm[arm] = {
                "runs": len(arm_runs),
                "points": sum(run["point_count"] for run in arm_runs),
                "seven_metrics": {
                    name: sum(run["sample_point_scores"]["metrics"][name]["passed"]
                              for run in arm_runs) for name in scorer.SEVEN_METRICS},
                "matched_boundary_exposures": sum(
                    run["boundary_scores"]["matched_boundaries"] for run in arm_runs),
                "gt_boundary_exposures": sum(
                    run["boundary_scores"]["gt_boundaries_total"] for run in arm_runs),
                "unmatched_predicted_transitions": sum(
                    run["boundary_scores"]["unmatched_predicted_transitions"]
                    for run in arm_runs),
                "failed_points": sum(len(run["failed_points"]) for run in arm_runs),
            }
        summary[version] = {
            "label": VERSION_LABELS[version],
            "runs": len(selected),
            "points": sum(run["point_count"] for run in selected),
            "seven_metrics": totals,
            "denominator_determinate_samples": determinate_total,
            "denominator_uncertain_samples": uncertain_total,
            "distinct_gt_boundaries_total": 8,
            "gt_boundary_exposures_total": total_exposures,
            "matched_boundary_exposures": matched_exposures,
            "missed_boundary_exposures": total_exposures - matched_exposures,
            "distinct_gt_boundaries_matched": sorted(distinct_matched),
            "distinct_gt_boundaries_matched_count": len(distinct_matched),
            "boundary_matrix": boundary_matrix,
            "boundary_exposures": boundary_exposures,
            "events": events,
            "by_arm": by_arm,
            "failed_points": [run["failed_points"] for run in selected
                              if run["failed_points"]],
        }
    return summary


# ---------------------------------------------------------------- 报告

def render_report(doc):
    lines = []
    lines.append("# Task 21 固定采样时序重放报告（fixed_sample_replay，CPU-only）")
    lines.append("")
    lines.append("- 性质：**固定采样反事实重放**。沿 Task 19B 已选定的 9 样本 × 3 臂原时间戳，")
    lines.append("  用 Task 20 已存档的同期 v1/v2 逐帧判断重建时间序列；**新模型调用 0**。")
    lines.append("- 正式 Task 17 评分：**REPLAY_UNSCORABLE**（冻结 scorer 的 G7 provenance 自洽")
    lines.append("  无法在诚实标注下满足；唯一通过方式为伪造本轮新鲜调用，明令禁止）。")
    lines.append("  以下为 Task 17 **规则级**转换与边界诊断（冻结纯函数直接计算）。")
    lines.append("")
    lines.append("## 1. 三种证据并列（不可互替）")
    lines.append("")
    lines.append("| 证据 | 标签 | 来源 | 边界成绩 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append("| Task 19B v1 动态三臂 | historical_dynamic_run | Task 19B（256 次当时新鲜调用）"
                 " | 0/8/臂（24 次暴露全 missed） |")
    for version in VERSIONS:
        s = doc["summary"][version]
        lines.append(f"| Task 21 {s['label']} | fixed_sample_replay | Task 20 存档判断"
                     f"（0 新调用） | 匹配暴露 {s['matched_boundary_exposures']}/"
                     f"{s['gt_boundary_exposures_total']}（不同边界 "
                     f"{s['distinct_gt_boundaries_matched_count']}/8） |")
    lines.append("| Task 20 同期同帧配对 | same_period_fixed_frame | Task 20 pairs/"
                 "（512 次当时新鲜调用） | 动态边界 not_measured（阶段 C 未运行） |")
    lines.append("")
    lines.append("## 2. 每版汇总（27 运行 / 256 点 / 各臂 121/51/84）")
    lines.append("")
    for version in VERSIONS:
        s = doc["summary"][version]
        m = s["seven_metrics"]
        lines.append(f"### {s['label']}")
        lines.append("")
        lines.append(f"- 七类计数：correct_decisive {m['correct_decisive']} / "
                     f"incorrect_decisive {m['incorrect_decisive']} / "
                     f"abstention_on_determinate {m['abstention_on_determinate']} / "
                     f"failed_on_determinate {m['failed_on_determinate']} / "
                     f"appropriate_abstention {m['appropriate_abstention']} / "
                     f"overclaim_on_uncertain {m['overclaim_on_uncertain']} / "
                     f"failed_on_uncertain {m['failed_on_uncertain']}"
                     f"（合计 {sum(m.values())}）")
        lines.append(f"- 分母：determinate {s['denominator_determinate_samples']} / "
                     f"uncertain {s['denominator_uncertain_samples']}")
        lines.append(f"- 边界：8 个不同 GT 边界 × 3 臂 = {s['gt_boundary_exposures_total']} 次暴露；"
                     f"匹配 {s['matched_boundary_exposures']} 次；"
                     f"不同边界命中 {s['distinct_gt_boundaries_matched_count']}/8"
                     f"（{s['distinct_gt_boundaries_matched'] or '无'}）")
        lines.append(f"- 事件覆盖：confirmed 段 {s['events']['covered_confirmed_events']}/"
                     f"{s['events']['gt_confirmed_segments']}；"
                     f"未触达 uncertain 段 {s['events']['unreached_uncertain_segments']}")
        failed = [item for group in s["failed_points"] for item in group]
        lines.append(f"- 失败点：{failed if failed else '无'}")
        lines.append("- 逐臂：")
        for arm in ARMS:
            a = s["by_arm"][arm]
            lines.append(f"  - {arm}：{a['runs']} 运行 / {a['points']} 点；"
                         f"边界暴露 {a['matched_boundary_exposures']}/{a['gt_boundary_exposures']}；"
                         f"多余转换 {a['unmatched_predicted_transitions']}；"
                         f"失败点 {a['failed_points']}")
        lines.append("")
    lines.append("## 3. 逐样本 × 逐臂明细（每版 27 运行）")
    lines.append("")
    lines.append("| 版本 | 样本/臂 | 点数 | 转换数 | 匹配/漏掉边界 | 多余转换 | "
                 "confirmed 覆盖 | 未触达 uncertain | 失败点 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for version in VERSIONS:
        for run in [r for r in doc["runs"] if r["version"] == version]:
            b = run["boundary_scores"]
            e = run["event_scores"]
            lines.append(
                f"| {version} | {run['sample_id']}/{run['arm']} | {run['point_count']} | "
                f"{len(run['state_transitions'])} | "
                f"{b['matched_boundaries']}/{b['missed_gt_boundaries']} | "
                f"{b['unmatched_predicted_transitions']} | "
                f"{e['covered_confirmed_events']}/{e['gt_confirmed_segments']} | "
                f"{e['unreached_uncertain_segments']} | "
                f"{','.join(run['failed_points']) if run['failed_points'] else '0'} |")
    lines.append("")
    lines.append("## 4. 逐边界 × 三臂暴露矩阵")
    lines.append("")
    lines.append("| 样本 | 边界 at_ms | 方向 | uniform | adaptive | coverage |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for version in VERSIONS:
        lines.append(f"| **{doc['summary'][version]['label']}** | | | | | |")
        for row in doc["summary"][version]["boundary_matrix"]:
            cells = []
            for arm in ARMS:
                cell = row["per_arm"][arm]
                cells.append("matched" if cell["matched"] else "missed")
            lines.append(f"| {row['sample_id']} | {row['at_ms']} | "
                         f"{row['from_state']}→{row['to_state']} | "
                         + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## 5. 不可互替原因")
    lines.append("")
    lines.append("- 历史动态运行的边界成绩只反映 Task 19B 当时的新鲜调用与动态选点；")
    lines.append("- 同期固定帧判断只反映同帧语义配对，没有动态时间线；")
    lines.append("- 本重放只反映**这些已选时间点 + 已存档返回**在 Task 17 规则下能否形成匹配转换，")
    lines.append("  **不证明 v2 动态采样会选这些点，也不构成 v2 上线或通过 Task 20 门槛**。")
    lines.append("- Task 20 verdict=TRADEOFF 与本重放结论是两个正交状态。")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- 主流程

def main():
    parser = argparse.ArgumentParser(description="Task 21 固定采样时序重放（CPU-only）")
    parser.add_argument("--out", default=os.path.join(TASK21, "replay"))
    args = parser.parse_args()

    scorer = load_module("score_temporal_ground_truth", SCORER_PATH)
    sampler = load_module("adaptive_sampler", SAMPLER_PATH)

    points, ground_truths, task19_timelines = load_inputs()
    problems = verify_mapping(points, task19_timelines)
    if problems:
        failure = {"status": "INVALID_INPUT", "problems": problems}
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "replay-results.json"), "w",
                  encoding="utf-8") as handle:
            handle.write(json.dumps(failure, ensure_ascii=False, indent=2) + "\n")
        print("[INVALID_INPUT] 256 点与 27 运行不能一一对应，拒绝产出重放结论")
        for item in problems[:20]:
            print("  -", item)
        return 2

    runs = []
    for version in VERSIONS:
        for sample_id in SAMPLES:
            for arm in ARMS:
                runs.append(replay_run(scorer, sampler, points, ground_truths,
                                       sample_id, arm, version))

    scoreability = scoreability_analysis(runs)
    summary = aggregate(scorer, runs)

    point_digest = hashlib.sha256()
    for point in points:
        point_digest.update(json.dumps(point, sort_keys=True,
                                       ensure_ascii=False).encode("utf-8"))

    doc = {
        "schema_version": "1.0.0",
        "task": "task21-fixed-sample-replay",
        "mode": "fixed_sample_replay",
        "evidence_label": "fixed_sample_replay",
        "new_model_calls": 0,
        "call_budget_note": ("唯一模型输出来源为 Task 20 已存档配对调用"
                             "（artifacts/task-20/pairs/points/，512 次正式调用的逐点存档）；"
                             "本 replay 未调用 Qwen/StepFun/DSH，未抽帧、未联网。"),
        "mapping_verification": {
            "points": len(points), "runs_per_version": 27,
            "arm_points": EXPECTED_ARM_POINTS,
            "timestamp_sequences_identical_to_task19b": True,
            "problems": problems,
        },
        "inputs": {
            "task20_points_digest_sha256": point_digest.hexdigest(),
            "task20_points_count": len(points),
            "ground_truth_dir": "artifacts/task-19/ground-truth",
            "task19_timelines": "artifacts/task-19/predictions/<sample>/<arm>/temporal-evidence.json",
            "frozen_scorer_sha256": sha256_of(SCORER_PATH),
            "frozen_sampler_sha256": sha256_of(SAMPLER_PATH),
        },
        "runs": runs,
        "summary": summary,
        "scoreability": scoreability,
        "formal_scoring_status": ("REPLAY_UNSCORABLE" if scoreability[
            "honest_variant_all_g7_failed"] else "NEEDS_HUMAN_REVIEW"),
        "no_extrapolation_statement": (
            "固定采样反事实重放：只证明这些已选择时间点和已存档模型返回在 Task 17 冻结规则下"
            "可以/不可以形成匹配转换；不证明 v2 动态采样会选这些点，不构成 v2 上线或通过 "
            "Task 20 门槛；dev 小样本 + 单次运行：不得给出统计显著性、不得外推真实仓储准确率。"),
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "replay-results.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    with open(os.path.join(args.out, "replay-report.md"), "w", encoding="utf-8") as handle:
        handle.write(render_report(doc))
    metadata = {
        "schema_version": "1.0.0",
        "task": "task21-replay-metadata",
        "mode": "fixed_sample_replay",
        "status": "COMPLETED",
        "new_model_calls": 0,
        "versions": list(VERSIONS),
        "runs_per_version": 27,
        "points_per_version": 256,
        "formal_scoring_status": doc["formal_scoring_status"],
        "outputs": ["replay-results.json", "replay-report.md"],
        "determinism": "输出不含墙钟时间戳/主机名/绝对用户路径；同一输入两次运行逐字节相同",
    }
    with open(os.path.join(args.out, "run-metadata.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    print(f"[ok] 重放完成：{len(runs)} 条运行（2 版本 × 27）；正式评分 "
          f"{doc['formal_scoring_status']}")
    for version in VERSIONS:
        s = summary[version]
        print(f"  {version}: 七类合计 {sum(s['seven_metrics'].values())}；"
              f"边界匹配暴露 {s['matched_boundary_exposures']}/"
              f"{s['gt_boundary_exposures_total']}；"
              f"不同边界 {s['distinct_gt_boundaries_matched_count']}/8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
