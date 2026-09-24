#!/usr/bin/env python3
"""build_frozen_hashes.py — Task 25 阶段 A 冻结哈希清单生成（SparkSkill Studio 任务 25）

在全部 Task 25 阶段 A 文件定稿后运行，生成 artifacts/task-25/preregistration/frozen-hashes.json。
执行器 run_task25_pairing.py 在发起任何正式 dev 调用前逐条复核；运行后全量重算必须一致。
frozen-hashes.json 自身不列入（自引用不可能）。
"""
import hashlib
import json
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
OUT = os.path.join(PROJECT_ROOT, "artifacts", "task-25", "preregistration", "frozen-hashes.json")

# (相对路径, 用途)
ENTRIES = [
    # Task 25 预注册/执行/测试/验证
    ("artifacts/task-25/preregistration/design.md", "task25 预注册设计文档"),
    ("artifacts/task-25/preregistration/evaluation-plan.json", "task25 预注册评估计划"),
    ("artifacts/task-25/preregistration/prompt-candidate.txt", "task25 候选提示词（多图有序+只判中心帧）"),
    ("artifacts/task-25/preregistration/unit-manifest-184.json", "task25 184 唯一中心帧清单"),
    ("artifacts/task-25/preregistration/first-batch-48.json", "task25 首批 48 单元（确定性抽样）"),
    ("scripts/run_task25_pairing.py", "task25 配对执行器"),
    ("scripts/score_task25_pairs.py", "task25 配对评分器"),
    ("scripts/task25_build_units.py", "task25 单元构建+邻帧抽取"),
    ("scripts/run_task25_smoke.py", "task25 阶段 0 多图技术 smoke"),
    ("scripts/test_task25_gate.py", "task25 确定性测试"),
    ("scripts/verify_task25.py", "task25 交付验证"),
    ("artifacts/task-25/smoke/smoke-report.json", "task25 阶段 0 smoke 报告"),
    ("artifacts/task-25/smoke/call-log.jsonl", "task25 阶段 0 smoke 调用日志"),
    # 生产 v1 与冻结评分器（必须零改动）
    (".dsh/skills/visual-evidence-extractor/scripts/analyze_image.py", "生产 v1（PROMPT_TEMPLATE 所在文件）"),
    (".dsh/skills/visual-evidence-extractor/SKILL.md", "visual-evidence-extractor SKILL.md（生产 Skill 未改）"),
    (".dsh/skills/visual-evidence-extractor/skill-card.md", "visual-evidence-extractor skill-card"),
    ("scripts/score_temporal_ground_truth.py", "Task 17 冻结评分器"),
    ("scripts/task18_scorer_adapter.py", "Task 18 适配层"),
    ("scripts/score_tier3_eval_v2.py", "Tier-3 v2 评分器"),
    # Task 19B GT（九份）
    *[(f"artifacts/task-19/ground-truth/{s}.json", f"Task 19B GT {s}")
      for s in ("AI01", "AI02", "AI03", "AI04", "AI05", "AI06", "WEB01", "WEB02", "WEB03")],
    # 帧同一性基础与 256 点来源
    ("artifacts/task-20/phase0/frame-farm-report.json", "帧农场报告（184 唯一帧字节一致）"),
    ("artifacts/task-22/preregistration/point-manifest-256.json", "Task 22 冻结 256 点清单（去重来源）"),
    ("artifacts/task-22/preregistration/paired_scorer.py", "Task 22 配对评分器（同义参考）"),
    ("artifacts/task-19/run-summary.md", "Task 19B 运行摘要"),
    ("artifacts/task-19/known-limitations.md", "Task 19B 已知限制"),
    ("artifacts/task-19/verification.json", "Task 19B 交付验证"),
    # schema（未改）
    ("schemas/visual-task-spec.schema.json", "VisualTaskSpec schema"),
    ("schemas/temporal-ground-truth.schema.json", "temporal-ground-truth schema"),
    ("schemas/evidence-pack-manifest.schema.json", "evidence-pack-manifest schema"),
]


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    entries = {}
    missing = []
    for rel, purpose in ENTRIES:
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path):
            missing.append(rel)
            continue
        entries[rel] = {"path": rel, "sha256": sha256_of(path), "purpose": purpose}
    doc = {
        "schema_version": "1.0.0",
        "plan": "task25-frozen-hashes",
        "note": "Task 25 阶段 A 冻结哈希清单：实现/运行后全量重算必须一致。frozen-hashes.json 自身不列入。"
                "覆盖 Task 25 预注册/执行器/评分器/测试/验证/阶段0 smoke、生产 v1、Task 17 冻结评分器、"
                "Task 18 适配层、Tier-3 v2、九份 GT、帧农场报告、Task 22 256 点来源与 schema。",
        "entry_count": len(entries),
        "entries": entries,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"entry_count": len(entries), "missing": missing}, ensure_ascii=False))
    if missing:
        print("[警告] 有缺失文件（若为尚未创建的测试/验证/design，请先创建再重跑）")


if __name__ == "__main__":
    main()
