#!/usr/bin/env python3
"""task25_analyze.py — Task 25 结果分析（SparkSkill Studio 任务 25，确定性，零模型调用）

消费合并后的配对结果，产出:
  - 总体 / generated / licensed-public / 逐样本 / 逐臂 / 逐 stratum / 2-3图 的 v1 vs cand 七类账
  - 邻帧目标误投射中心实例：cand 对中心作肯定断言（confirmed）而 GT 判定中心无目标
    （not_found→incorrect_decisive 或 uncertain→overclaim_on_uncertain），且相对同期 v1 为新增/恶化
  - 逐点变化表（v1_metric != cand_metric）
  - AI01/AI04/AI06/WEB01/WEB03 聚焦切片

用法:
  python3 task25_analyze.py --stage-b <dir> [--stage-c <dir>] --out <dir>
"""
import argparse
import importlib.util
import json
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCORER = os.path.join(PROJECT_ROOT, "scripts", "score_task25_pairs.py")
UNIT_MANIFEST = os.path.join(PROJECT_ROOT, "artifacts", "task-25", "preregistration",
                             "unit-manifest-184.json")
GT_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ground-truth")
SEVEN = ("correct_decisive", "incorrect_decisive", "abstention_on_determinate",
         "failed_on_determinate", "appropriate_abstention", "overclaim_on_uncertain",
         "failed_on_uncertain")
FOCUS = ["AI01", "AI04", "AI06", "WEB01", "WEB03"]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description="Task 25 结果分析")
    parser.add_argument("--stage-b", required=True)
    parser.add_argument("--stage-c", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    scorer = load_module("score_task25_pairs", SCORER)
    unit_manifest = load_json(UNIT_MANIFEST)
    meta = {u["unit_id"]: u for u in unit_manifest["units"]}
    gt = {}
    for name in os.listdir(GT_DIR):
        if name.endswith(".json"):
            gt[name[:-5]] = load_json(os.path.join(GT_DIR, name))

    merged = {}
    for src in (args.stage_b, args.stage_c):
        if not src:
            continue
        pr = load_json(os.path.join(src, "pairing-results.json"))
        pr_points = pr.get("points") if pr.get("points") is not None else pr.get("units", [])
        for p in pr_points:
            merged[p["unit_id"]] = p

    points = []
    for uid, p in merged.items():
        m = meta[uid]
        points.append({
            "unit_id": uid, "sample_id": p["sample_id"],
            "center_timestamp_ms": p["center_timestamp_ms"], "track": p["track"],
            "stratum": m.get("stratum"), "source_arms": m.get("source_arms", []),
            "image_count": p.get("image_count"),
            "v1_judgment": p["v1_judgment"], "cand_judgment": p["cand_judgment"],
            "center_frame_sha256": p.get("center_frame_sha256"),
        })

    v1 = scorer.score_side(points, gt, "v1")
    cand = scorer.score_side(points, gt, "cand")

    # 逐点 paired rows + 变化
    paired = []
    for rv, rc in zip(v1["rows"], cand["rows"]):
        paired.append({
            "unit_id": rv["unit_id"], "sample_id": rv["sample_id"],
            "center_timestamp_ms": rv["center_timestamp_ms"], "track": rv["track"],
            "stratum": rv["stratum"], "image_count":
                next(p["image_count"] for p in points if p["unit_id"] == rv["unit_id"]),
            "ground_truth_state": rv["ground_truth_state"],
            "v1_class": rv["prediction_class"], "v1_metric": rv["metric"],
            "cand_class": rc["prediction_class"], "cand_metric": rc["metric"],
            "changed": rv["metric"] != rc["metric"]})

    # 邻帧目标误投射中心实例：cand 对中心作肯定断言(confirmed)而 GT 判中心无目标
    # （not_found/uncertain），且相对 v1 为新增误报/过度断言（v1 非同类错误）。
    misproj = []
    for row in paired:
        if row["cand_class"] == "confirmed" and row["ground_truth_state"] in ("not_found",
                                                                               "uncertain"):
            v1_was_error = row["v1_metric"] in ("incorrect_decisive", "overclaim_on_uncertain")
            misproj.append({
                "unit_id": row["unit_id"], "sample_id": row["sample_id"],
                "center_timestamp_ms": row["center_timestamp_ms"],
                "ground_truth_state": row["ground_truth_state"],
                "v1_metric": row["v1_metric"], "cand_metric": row["cand_metric"],
                "new_center_false_assertion": not v1_was_error,
                "note": "cand 判中心 confirmed 而 GT 判中心无目标；若该目标仅见于 ±500ms 邻帧，"
                        "即邻帧目标被误投射到中心帧"})

    # 2/3 图分层
    def by_image_count(side_rows):
        out = {"three": {n: 0 for n in SEVEN}, "two": {n: 0 for n in SEVEN}}
        for row in side_rows:
            key = "three" if row.get("image_count") == 3 else "two"
            out[key][row["metric"]] += 1
        return out
    v1_by_img = by_image_count(v1["rows"])
    cand_by_img = by_image_count(cand["rows"])

    # focus 样本
    focus = {}
    for sid in FOCUS:
        v1s = {n: 0 for n in SEVEN}
        cs = {n: 0 for n in SEVEN}
        for rv, rc in zip(v1["rows"], cand["rows"]):
            if rv["sample_id"] == sid:
                v1s[rv["metric"]] += 1
                cs[rc["metric"]] += 1
        focus[sid] = {"v1": v1s, "cand": cs}

    report = {
        "task": "task25-analysis",
        "unit_count": len(points),
        "totals": {"v1": v1["counts"], "cand": cand["counts"]},
        "error_assertions": {"v1": scorer.error_assertions(v1["counts"]),
                             "cand": scorer.error_assertions(cand["counts"])},
        "by_track": {"v1": v1["by_track"], "cand": cand["by_track"]},
        "by_sample": {"v1": v1["by_sample"], "cand": cand["by_sample"]},
        "by_arm": {"v1": v1["by_arm"], "cand": cand["by_arm"]},
        "by_stratum": {"v1": v1["by_stratum"], "cand": cand["by_stratum"]},
        "by_image_count": {"v1": v1_by_img, "cand": cand_by_img},
        "focus_samples": focus,
        "neighbor_misprojection_instances": misproj,
        "neighbor_misprojection_new_count": sum(1 for m in misproj if m["new_center_false_assertion"]),
        "changed_points": [r for r in paired if r["changed"]],
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "analysis.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "unit_count": len(points),
        "totals_v1": v1["counts"], "totals_cand": cand["counts"],
        "error_assertions": report["error_assertions"],
        "neighbor_misprojection_total": len(misproj),
        "neighbor_misprojection_new": report["neighbor_misprojection_new_count"],
        "changed_points": len(report["changed_points"]),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
