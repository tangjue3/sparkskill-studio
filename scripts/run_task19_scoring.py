#!/usr/bin/env python3
"""run_task19_scoring.py — Task 19B 评分与汇总（SparkSkill Studio）

使用任务 17 冻结评分器（scripts/score_temporal_ground_truth.py，零改动）经任务 18
已提交适配层（scripts/task18_scorer_adapter.py，零改动）对三臂预测评分，并按预注册
verdict-policy.json 的范围分别计算：

  scores/generated/         AI01–AI06（generated track；查询与预算同质，冻结双臂
                            公平门十条件全部可观测）
  scores/licensed-public/   WEB01–WEB03（licensed-public track）
  scores/all-dev/           九样本汇总（仅作为补充）
  scores/per-sample/<ID>/   单样本范围（冻结公平门在单样本范围内逐条件可观测：
                            同查询、同预算逐样本成立）

每个范围输出逐 (样本,臂) score.json/score.md/input-hashes.json +
three-arm-comparison.json（三臂指标 + 三对 pairwise fairness gate 与 verdict + pack 级
verdict + 最大采样间隔）。

**多查询/多预算包的公平门口径（如实披露）**：冻结双臂公平门的 same_target_query 与
same_call_budget 条件在实现上要求比较范围内取值单一。本包按任务书预算政策
（clamp(ceil(duration/1000),12,24)）跨样本预算不同（12/12/12/12/12/12/19/12/18），
且 licensed-public 轨道有三个不同 target query——因此 licensed-public 与 all-dev
范围的 pack 级双臂公平门在冻结实现下判 FAIL（INVALID_COMPARISON）。本脚本同时：
  (a) 对每个样本单独跑一次冻结公平门（同查询/同预算在样本内成立）——九样本 × 三对
      全部 PASS 的证据落盘 scores/per-sample/；
  (b) 用冻结 compute_verdict 对轨道汇总指标计算 pooled pairwise verdict（非回归与
      严格更好条件均在汇总计数上判定，纪律不变），并在 comparisons 文档中与 (a) 的
      逐样本门结果并列披露。

最后汇总 comparisons/task19-three-scope-verdicts.json|md。

硬门失败（隔离/哈希/公平）即 INVALID_EVALUATION 信号：本脚本记录并以退出码 1 结束，
不虚构分数。

用法:
    python3 scripts/run_task19_scoring.py [--predictions artifacts/task-19/predictions/prediction-set.json]
退出码: 0 = 三范围全部评分且无硬门失败; 1 = 存在硬门失败/评分错误
"""
import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TASK19 = os.path.join(PROJECT_ROOT, "artifacts", "task-19")
PREREGISTRATION = os.path.join(TASK19, "preregistration")
INGESTION = os.path.join(TASK19, "ingestion")
GROUND_TRUTH = os.path.join(TASK19, "ground-truth")
PREDICTIONS = os.path.join(TASK19, "predictions")
SCORES = os.path.join(TASK19, "scores")
COMPARISONS = os.path.join(TASK19, "comparisons")
ADAPTER = os.path.join(PROJECT_ROOT, "scripts", "task18_scorer_adapter.py")
SCORER = os.path.join(PROJECT_ROOT, "scripts", "score_temporal_ground_truth.py")
MANIFEST = os.path.join(INGESTION, "evidence-pack-manifest.json")

WHITELIST = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06",
             "WEB01", "WEB02", "WEB03"]
SCOPES = [
    ("generated", "AI01,AI02,AI03,AI04,AI05,AI06"),
    ("licensed-public", "WEB01,WEB02,WEB03"),
    ("all-dev", ",".join(WHITELIST)),
]
PAIRS = [("coverage", "uniform"), ("coverage", "adaptive"), ("adaptive", "uniform")]


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def load_scorer():
    spec = importlib.util.spec_from_file_location("score_temporal_ground_truth", SCORER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if "coverage_aware_adaptive" not in module.STRATEGIES:
        module.STRATEGIES = tuple(module.STRATEGIES) + ("coverage_aware_adaptive",)
    return module


def run_adapter(out_dir, comparison_id, sample_scope, predictions_path=None):
    os.makedirs(out_dir, exist_ok=True)
    return subprocess.run(
        [sys.executable, ADAPTER,
         "--manifest", MANIFEST,
         "--predictions", predictions_path or os.path.join(PREDICTIONS,
                                                           "prediction-set.json"),
         "--ground-truth", GROUND_TRUTH,
         "--out", out_dir,
         "--comparison-id", comparison_id,
         "--sample-scope", sample_scope],
        capture_output=True, text=True)


def write_single_sample_prediction_set(sample_id):
    """仅含一个样本的 prediction-set（供逐样本公平门调用；相对 prediction-set
    所在目录解析 evidence 路径，保持与主 prediction-set 一致的相对引用）。"""
    base = load_json(os.path.join(PREDICTIONS, "prediction-set.json"))
    arms = []
    for arm in base["arms"]:
        samples = [item for item in arm["samples"]
                   if item["sample_id"] == sample_id]
        arms.append({"arm_id": arm["arm_id"], "samples": samples})
    doc = {"schema_version": base["schema_version"],
           "pack_id": base["pack_id"], "arms": arms}
    path = os.path.join(PREDICTIONS, f"prediction-set-{sample_id}.json")
    dump_json(path, doc)
    return path


def pooled_pairwise_verdicts(scorer, scope_sample_ids):
    """用冻结 compute_verdict 对轨道汇总指标计算 pooled pairwise verdict。

    汇总指标由冻结 aggregate_metrics 对同范围逐样本 score.json 聚合（计数求和 +
    跨样本边界误差统计）；非回归与严格更好条件在汇总计数上判定（冻结纪律不变）。
    返回 {pair_id: verdict_doc}。
    """
    arm_scores = {}
    for arm_id in ("uniform", "adaptive", "coverage"):
        docs = []
        for sample_id in scope_sample_ids:
            path = os.path.join(SCORES, "all-dev", sample_id, arm_id, "score.json")
            if os.path.isfile(path):
                docs.append(load_json(path))
        arm_scores[arm_id] = docs
    verdicts = {}
    for candidate, baseline in PAIRS:
        pair_id = f"{candidate}-vs-{baseline}"
        base_metrics = scorer.aggregate_metrics(arm_scores[baseline])
        cand_metrics = scorer.aggregate_metrics(arm_scores[candidate])
        verdicts[pair_id] = {
            "baseline": baseline, "candidate": candidate,
            "verdict": scorer.compute_verdict(base_metrics, cand_metrics),
            "metrics": {baseline: {"aggregate": base_metrics},
                        candidate: {"aggregate": cand_metrics}},
        }
    return verdicts


def main():
    parser = argparse.ArgumentParser(description="Task 19B 三范围评分与 verdict 汇总")
    parser.add_argument("--predictions",
                        default=os.path.join(PREDICTIONS, "prediction-set.json"))
    args = parser.parse_args()
    if not os.path.isfile(args.predictions):
        print(f"[用法错误] 找不到预测集合: {args.predictions}", file=sys.stderr)
        return 2
    os.makedirs(COMPARISONS, exist_ok=True)

    summary = {
        "task": "task-19b-scoring",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scorer": "scripts/score_temporal_ground_truth.py（任务 17 冻结，零改动）",
        "adapter": "scripts/task18_scorer_adapter.py（任务 18 已提交适配层，零改动）",
        "manifest": os.path.relpath(MANIFEST, PROJECT_ROOT),
        "ground_truth": os.path.relpath(GROUND_TRUTH, PROJECT_ROOT),
        "predictions": os.path.relpath(args.predictions, PROJECT_ROOT),
        "fairness_gate_note": (
            "冻结双臂公平门的 same_target_query / same_call_budget 条件在实现上要求"
            "比较范围内取值唯一。本包按预注册预算政策跨样本预算不同（12×7、WEB01=19、"
            "WEB03=18）且 licensed-public 轨道有三个 target query：generated 范围"
            "（查询与预算同质）十条件全部通过；licensed-public 与 all-dev 范围该两条件"
            "在冻结实现下 FAIL（判 INVALID_COMPARISON，如实保留）。逐样本公平门"
            "（同查询/同预算在样本内成立）见 scores/per-sample/；pooled pairwise "
            "verdict 用冻结 compute_verdict 对汇总指标计算（纪律不变），与逐样本门"
            "证据并列披露。"),
        "scopes": {},
        "per_sample": {},
    }
    any_failure = False

    # ---- 三范围评分 + 冻结适配层 pairwise/pack verdict
    for scope_name, sample_scope in SCOPES:
        out_dir = os.path.join(SCORES, scope_name)
        proc = run_adapter(out_dir, f"task19-three-arm-{scope_name}", sample_scope)
        print(f"=== 范围 {scope_name}（exit={proc.returncode}）===")
        print(proc.stdout.strip()[-1800:])
        if proc.returncode != 0:
            any_failure = True
            print(proc.stderr[-1500:], file=sys.stderr)
        comparison_path = os.path.join(out_dir, "three-arm-comparison.json")
        entry = {
            "sample_scope": sample_scope.split(","),
            "exit_code": proc.returncode,
            "comparison": os.path.relpath(comparison_path, PROJECT_ROOT)
            if os.path.isfile(comparison_path) else None,
        }
        if os.path.isfile(comparison_path):
            doc = load_json(comparison_path)
            entry["pairwise_frozen_gate"] = {
                pair_id: {
                    "fairness_gate_all_passed": pair["fairness_gate"]["all_passed"],
                    "failed_conditions": [c["id"] for c in
                                          pair["fairness_gate"]["conditions"]
                                          if not c["passed"]],
                    "verdict": pair["verdict"]["verdict"],
                    "reason_codes": pair["verdict"]["reason_codes"],
                } for pair_id, pair in (doc.get("pairwise") or {}).items()}
            entry["pack_verdict"] = (doc.get("pack_verdict") or {}).get("verdict")
            entry["pack_reason_codes"] = (doc.get("pack_verdict") or {}).get("reason_codes")
            entry["max_sampling_gap_ms"] = doc.get("max_sampling_gap_ms")
            entry["aggregate_metrics"] = doc.get("metrics")
        summary["scopes"][scope_name] = entry

    # ---- 逐样本冻结公平门（同查询/同预算在样本内成立）
    scorer = load_scorer()
    per_sample_gates = {}
    for sample_id in WHITELIST:
        out_dir = os.path.join(SCORES, "per-sample", sample_id)
        single_set = write_single_sample_prediction_set(sample_id)
        proc = run_adapter(out_dir, f"task19-three-arm-{sample_id}", sample_id,
                           predictions_path=single_set)
        comparison_path = os.path.join(out_dir, "three-arm-comparison.json")
        entry = {"exit_code": proc.returncode}
        if os.path.isfile(comparison_path):
            doc = load_json(comparison_path)
            entry["pairwise"] = {
                pair_id: {
                    "fairness_gate_all_passed": pair["fairness_gate"]["all_passed"],
                    "failed_conditions": [c["id"] for c in
                                          pair["fairness_gate"]["conditions"]
                                          if not c["passed"]],
                    "verdict": pair["verdict"]["verdict"],
                    "reason_codes": pair["verdict"]["reason_codes"],
                } for pair_id, pair in (doc.get("pairwise") or {}).items()}
        if proc.returncode != 0:
            any_failure = True
        per_sample_gates[sample_id] = entry
        print(f"[逐样本门] {sample_id}: "
              + ", ".join(f"{pid}={'PASS' if v['fairness_gate_all_passed'] else 'FAIL'}"
                          for pid, v in entry.get("pairwise", {}).items()))
    summary["per_sample"] = per_sample_gates
    summary["per_sample_gates_all_passed"] = all(
        all(p["fairness_gate_all_passed"] for p in entry.get("pairwise", {}).values())
        for entry in per_sample_gates.values())

    # ---- pooled pairwise verdict（冻结 compute_verdict + aggregate_metrics）
    for scope_name, sample_scope in SCOPES:
        ids = sample_scope.split(",")
        verdicts = pooled_pairwise_verdicts(scorer, ids)
        summary["scopes"][scope_name]["pairwise_pooled_verdict"] = {
            pair_id: {
                "baseline": doc["baseline"], "candidate": doc["candidate"],
                "verdict": doc["verdict"]["verdict"],
                "reason": doc["verdict"]["reason"],
                "reason_codes": doc["verdict"]["reason_codes"],
            } for pair_id, doc in verdicts.items()}
        print(f"[pooled pairwise] {scope_name}: "
              + ", ".join(f"{pid}={doc['verdict']['verdict']}"
                          for pid, doc in verdicts.items()))

    dump_json(os.path.join(COMPARISONS, "task19-three-scope-verdicts.json"), summary)
    write_comparisons_md(os.path.join(COMPARISONS, "task19-three-scope-verdicts.md"),
                         summary)
    print(f"\n[汇总] {os.path.relpath(os.path.join(COMPARISONS, 'task19-three-scope-verdicts.json'), PROJECT_ROOT)}")
    if any_failure:
        print("[评分失败] 存在硬门失败或评分错误（INVALID_EVALUATION 信号）；详见各范围输出",
              file=sys.stderr)
        return 1
    print("RESULT: SCORED")
    return 0


def write_comparisons_md(path, summary):
    lines = [
        "# Task 19B 三范围 verdict 汇总",
        "",
        f"- 生成时间：{summary['generated_at']}",
        f"- 评分器：{summary['scorer']}",
        f"- 适配层：{summary['adapter']}",
        "- **licensed-public 轨道只有三段：小样本真实域观察，不得外推为真实仓储准确率、"
        "统计显著性 or 生产可用性。**",
        "",
        "## 公平门口径（多查询/多预算包）",
        "",
        summary["fairness_gate_note"],
        "",
        f"逐样本公平门（九样本 × 三对）全部通过："
        f"{'是' if summary.get('per_sample_gates_all_passed') else '否'}",
        "",
    ]
    for scope_name, entry in summary["scopes"].items():
        lines.append(f"## 范围 {scope_name}（{len(entry['sample_scope'])} 样本）")
        lines.append("")
        lines.append("### 冻结适配层 pairwise（公平门十条件）")
        lines.append("")
        for pair_id, pair in (entry.get("pairwise_frozen_gate") or {}).items():
            failed = pair["failed_conditions"]
            lines.append(
                f"- {pair_id}: fairness_gate="
                f"{'PASS' if pair['fairness_gate_all_passed'] else 'FAIL(' + ','.join(failed) + ')'}"
                f" verdict=**{pair['verdict']}** reason_codes={pair['reason_codes']}")
        lines.append("")
        lines.append("### pooled pairwise verdict（冻结 compute_verdict 对汇总指标）")
        lines.append("")
        for pair_id, pair in (entry.get("pairwise_pooled_verdict") or {}).items():
            lines.append(f"- {pair_id}: **{pair['verdict']}** — {pair['reason']}")
        lines.append("")
        lines.append(f"### pack 级 verdict")
        lines.append("")
        lines.append(f"- **{entry.get('pack_verdict')}** reason_codes="
                     f"{entry.get('pack_reason_codes')}")
        lines.append(f"- 最大相邻采样间隔（跨样本最大值，按臂）: "
                     f"{entry.get('max_sampling_gap_ms')}")
        lines.append("")
    lines += [
        "## 逐样本公平门与 pairwise verdict",
        "",
        "| 样本 | coverage-vs-uniform | coverage-vs-adaptive | adaptive-vs-uniform |",
        "| --- | --- | --- | --- |",
    ]
    for sample_id, entry in (summary.get("per_sample") or {}).items():
        cells = []
        for pair_id in ("coverage-vs-uniform", "coverage-vs-adaptive",
                        "adaptive-vs-uniform"):
            pair = (entry.get("pairwise") or {}).get(pair_id) or {}
            gate = "PASS" if pair.get("fairness_gate_all_passed") else "FAIL"
            cells.append(f"{gate} / {pair.get('verdict')}")
        lines.append(f"| {sample_id} | {cells[0]} | {cells[1]} | {cells[2]} |")
    lines += [
        "",
        "## 不得外推的声明",
        "",
        "- 小样本 + 单次运行：不构成统计显著性；generated 轨道为 MiniMax-H3 生成受控测试"
        "视频，licensed-public 轨道为 Pexels 真实素材小样本观察；",
        "- 真实 Qwen 运行受模型非确定性影响；效率指标（调用/耗时/间隔）不能抵消语义错误；",
        "- `completed`（execution_status）不等于语义正确；覆盖探索不保证发现任意短事件。",
        "",
    ]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
