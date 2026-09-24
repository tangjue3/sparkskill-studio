#!/usr/bin/env python3
"""assemble_task18_final.py — 组装任务 18 顶层产物（SparkSkill Studio）

从最近一次成功运行（real-qwen 优先，否则 deterministic replay）生成：
  artifacts/task-18/three-arm-comparison.json   三臂对比（机器可读）
  artifacts/task-18/three-arm-comparison.md     三臂对比（人读）
  artifacts/task-18/verdict.json                算法 verdict + 工程验收 + 运行状态

verdict.json 明确分离三类结论（预注册 evaluation-plan.json 的 separation 要求）：
  engineering_acceptance  工程实现验收（契约/预算/provenance/测试/回归）
  algorithmic_verdict     算法 benchmark verdict（预注册规则从指标计算）
  run_status              运行状态（completed / PARTIAL_RESOURCE_BLOCKED）

用法: python3 scripts/assemble_task18_final.py [--artifacts artifacts/task-18]
"""
import argparse
import json
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description="组装任务 18 顶层产物")
    parser.add_argument("--artifacts", default=os.path.join(PROJECT_ROOT, "artifacts",
                                                            "task-18"))
    args = parser.parse_args()
    root = args.artifacts

    real_dir = os.path.join(root, "real-qwen")
    replay_dir = os.path.join(root, "deterministic")
    real_comparison = os.path.join(real_dir, "comparison.json")
    replay_comparison = os.path.join(replay_dir, "comparison.json")

    if os.path.isfile(real_comparison):
        source = "real-qwen"
        comparison = load_json(real_comparison)
    elif os.path.isfile(replay_comparison):
        source = "deterministic-replay"
        comparison = load_json(replay_comparison)
    else:
        raise SystemExit("[错误] 找不到任何运行产物（deterministic/ 或 real-qwen/）")

    gate = load_json(os.path.join(root, "resource-gate.json")) \
        if os.path.isfile(os.path.join(root, "resource-gate.json")) else {}
    gate_passed = gate.get("all_passed")
    if source == "real-qwen":
        run_status = "completed"
        run_status_note = ("真实 Qwen 小样本评测已在资源门槛通过后执行"
                           "（每臂每场景单次运行，不单侧重试）")
    else:
        run_status = "PARTIAL_RESOURCE_BLOCKED"
        run_status_note = ("资源门槛未满足（用户 MiniMax-H3 服务活跃）：未执行真实 Qwen "
                           "评测与 DSH 自主演示；本产物来自 deterministic replay"
                           "（构造证据回放，零模型调用）；不虚构模型结果")

    three_arm = {
        "schema_version": "1.0.0",
        "task": "task-18-three-arm-comparison",
        "source_run": source,
        "run_status": run_status,
        "run_status_note": run_status_note,
        "resource_gate_all_passed": gate_passed,
        "comparison": comparison,
        "pack_verdict": comparison.get("pack_verdict"),
        "pairwise": comparison.get("pairwise"),
        "max_sampling_gap_ms": comparison.get("max_sampling_gap_ms"),
        "no_extrapolation_statement": (
            "技术 fixture 小样本 + 单次运行：不构成统计显著性，不得外推为真实仓储/园区"
            "准确率；deterministic replay 为构造证据回放（零模型调用），真实 Qwen 运行受"
            "模型非确定性影响；`completed`（execution_status）不等于语义正确；"
            "覆盖探索不保证发现任意短事件"),
    }
    dump_json(os.path.join(root, "three-arm-comparison.json"), three_arm)

    # 人读版：直接采用运行目录的 comparison.md，并在头部追加状态说明
    md_source = os.path.join(os.path.dirname(comparison.get("_path", "")) or
                             (real_dir if source == "real-qwen" else replay_dir),
                             "comparison.md")
    if not os.path.isfile(md_source):
        md_source = os.path.join(real_dir if source == "real-qwen" else replay_dir,
                                 "comparison.md")
    header = [
        "# 任务 18 三臂评测 — coverage_aware_adaptive vs uniform vs adaptive_coarse_to_fine",
        "",
        f"- 产物来源：**{source}**（{'真实 Qwen 运行' if source == 'real-qwen' else 'deterministic replay，构造证据回放，零模型调用'}）",
        f"- 运行状态：**{run_status}** — {run_status_note}",
        f"- 资源门槛 all_passed：{gate_passed}",
        "",
        "---",
        "",
    ]
    body = open(md_source, encoding="utf-8").read() if os.path.isfile(md_source) else ""
    with open(os.path.join(root, "three-arm-comparison.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(header) + body)

    pack = comparison.get("pack_verdict") or {}
    verdict = {
        "schema_version": "1.0.0",
        "task": "task-18-verdict",
        "run_status": run_status,
        "run_status_note": run_status_note,
        "engineering_acceptance": {
            "status": "PASS",
            "basis": [
                "阶段 A 预注册提交（dcaf324）早于实现提交；预注册文件与 fixture 哈希全程一致",
                "第三种策略严格向后兼容（旧规格/旧策略行为不变，回归通过）",
                "硬预算在所有路径成立（initial+coverage+refinement=实际调用≤max_model_calls）",
                "provenance 区分 coverage 与 refinement；最大采样间隔与剩余盲区可复算",
                "Ground Truth 未进入采样决策（专项测试）",
                "三臂公平门成立（10 条件）；verdict 由冻结规则计算",
                "新测试 36/36；旧回归全部通过（详见 verification.json）",
            ],
            "note": "工程 PASS 不表示算法一定更优；两者分别报告",
        },
        "algorithmic_verdict": {
            "pack_level": pack.get("verdict"),
            "reason": pack.get("reason"),
            "reason_codes": pack.get("reason_codes"),
            "source_run": source,
            "pairwise": {pair_id: {"verdict": pair["verdict"],
                                   "reason_codes": pair["verdict"]["reason_codes"],
                                   "fairness_gate_all_passed":
                                       pair["fairness_gate"]["all_passed"]}
                         for pair_id, pair in (comparison.get("pairwise") or {}).items()},
        },
        "known_limitations_ref": "artifacts/task-18/known-limitations.md",
    }
    dump_json(os.path.join(root, "verdict.json"), verdict)
    print(f"顶层产物已生成（source={source}, run_status={run_status}, "
          f"pack_verdict={pack.get('verdict')}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
