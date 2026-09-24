#!/usr/bin/env python3
"""build_task21_input_hashes.py — Task 21 阶段 A 输入清单与 SHA-256 清单生成器

确定性、CPU-only、零模型调用：按显式声明的只读输入清单（Task 20 配对实验存档、
Task 19B 冻结基线与 GT、Task 17/18/19 冻结代码、人类可读入口文档）逐文件计算
SHA-256，写出 `artifacts/task-21/plan/input-hashes.json`。

纪律:
  - 只读：不写入、不修改任何被哈希文件；唯一写入位置是 --out 指定的清单文件；
  - 显式清单：不从目录猜测输入；每个条目带用途说明；
  - 缺失文件 = 硬失败（退出码 1），与任务书"缺失输入即停止"一致；
  - 输出确定性：排序稳定、JSON indent=2、无墙钟时间。

用法:
    python3 scripts/build_task21_input_hashes.py \
        [--out artifacts/task-21/plan/input-hashes.json]
"""
import argparse
import glob
import hashlib
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TASK19 = os.path.join(PROJECT_ROOT, "artifacts", "task-19")
TASK20 = os.path.join(PROJECT_ROOT, "artifacts", "task-20")
TASK21_PLAN = os.path.join(PROJECT_ROOT, "artifacts", "task-21", "plan")

SAMPLES = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06", "WEB01", "WEB02", "WEB03"]
ARMS = ("uniform", "adaptive", "coverage")


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path):
    return os.path.relpath(path, PROJECT_ROOT)


def build_entries():
    """显式输入清单：(repo 相对路径, 用途)。顺序即输出顺序（分组稳定）。"""
    entries = []

    def add(pattern, purpose, base=PROJECT_ROOT):
        matched = sorted(glob.glob(os.path.join(base, pattern)))
        if not matched:
            raise SystemExit(f"[缺失输入] glob 无匹配: {pattern} (base={base})")
        for path in matched:
            entries.append((rel(path), purpose))

    # ---- Task 20 预注册与阶段 0（口径冻结来源）
    add("artifacts/task-20/preregistration/design.md", "task20 预注册设计文档（口径冻结）")
    add("artifacts/task-20/preregistration/evaluation-plan.json", "task20 预注册评估计划")
    add("artifacts/task-20/preregistration/prompt-v2.txt", "task20 v2 提示词（候选版本定义）")
    add("artifacts/task-20/preregistration/paired_scorer.py", "task20 配对评分器（阶段 A 冻结）")
    add("artifacts/task-20/preregistration/point-manifest-256.json", "task20 256 点预注册清单")
    add("artifacts/task-20/preregistration/frozen-hashes.json", "task20 冻结哈希清单（33 条）")
    add("artifacts/task-20/phase0/sample-points-256.json", "task20 256 点→19B 一一映射")
    add("artifacts/task-20/phase0/recompute-historical.json", "task20 历史独立复算")
    add("artifacts/task-20/phase0/error-points.json", "task20 阶段 0 错误归因点")
    add("artifacts/task-20/phase0/attribution-matrix.md", "task20 阶段 0 归因矩阵")
    add("artifacts/task-20/phase0/frame-farm-report.json", "task20 帧农场报告（184 帧字节一致）")

    # ---- Task 20 正式运行存档（重放的唯一模型输出来源）
    add("artifacts/task-20/pairs/run-metadata.json", "task20 正式运行元数据（512 调用记账）")
    add("artifacts/task-20/pairs/pairing-results.json", "task20 配对结果（256 点结构化）")
    add("artifacts/task-20/pairs/call-log.jsonl", "task20 逐笔记调用日志（513 条）")
    add("artifacts/task-20/pairs/points/T20-P*.json", "task20 逐点存档（v1/v2 原始判断+调用顺序）")
    add("artifacts/task-20/scores/paired-score.json", "task20 配对评分（五类主表+门槛+verdict）")
    add("artifacts/task-20/scores/paired-rows.json", "task20 逐点配对行（含两类补充 metric）")
    add("artifacts/task-20/scores/paired-report.md", "task20 人读配对报告")
    add("artifacts/task-20/run-summary.md", "task20 运行摘要（人类可读入口）")
    add("artifacts/task-20/verification.json", "task20 交付验证（20 项）")
    add("artifacts/task-20/test-results.json", "task20 测试结果（19/19）")
    add("artifacts/task-20/smoke/run-metadata.json", "task20 smoke 自证元数据（不计入正式）")
    add("artifacts/task-20/smoke/pairing-results.json", "task20 smoke 自证结果")
    add("artifacts/task-20/smoke/call-log.jsonl", "task20 smoke 自证调用日志")
    add("artifacts/task-20/smoke/points/SMOKE-*.json", "task20 smoke 自证逐点记录")

    # ---- Task 19B 冻结基线（采样时间线/GT/历史评分来源）
    add("artifacts/task-19/ground-truth/*.json", "task19 GT（九段，标签冻结）")
    add("artifacts/task-19/execution-manifests/*/*.json", "task19 27 条运行元数据")
    add("artifacts/task-19/predictions/*/*/temporal-evidence.json", "task19 27 条采样时间线与证据")
    add("artifacts/task-19/predictions/run-metadata.json", "task19 批量运行元数据")
    add("artifacts/task-19/predictions/prediction-set.json", "task19 预测集合")
    add("artifacts/task-19/scores/all-dev/*/*/score.json", "task19 冻结评分（27 份）")
    add("artifacts/task-19/scores/all-dev/three-arm-comparison.json", "task19 all-dev 三臂比较")
    add("artifacts/task-19/scores/generated/three-arm-comparison.json", "task19 generated 三臂比较")
    add("artifacts/task-19/scores/licensed-public/three-arm-comparison.json", "task19 licensed 三臂比较")
    add("artifacts/task-19/comparisons/task19-three-scope-verdicts.json", "task19 三范围 verdict")
    add("artifacts/task-19/preregistration/evaluation-plan.json", "task19 预注册评估计划")
    add("artifacts/task-19/preregistration/verdict-policy.json", "task19 verdict 政策")
    add("artifacts/task-19/preregistration/frozen-hashes.json", "task19 冻结哈希清单")
    add("artifacts/task-19/run-summary.md", "task19 运行摘要")
    add("artifacts/task-19/known-limitations.md", "task19 已知限制")
    add("artifacts/task-19/verification.json", "task19 交付验证")

    # ---- 冻结代码（只读引用；重放规则来源）
    add("scripts/score_temporal_ground_truth.py", "task17 冻结 scorer（边界/七类规则来源）")
    add("scripts/task18_scorer_adapter.py", "task18 适配层（内存扩展策略白名单）")
    add("scripts/run_task19_scoring.py", "task19 评分驱动（冻结 scorer 调用方式）")
    add(".dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py",
        "冻结采样器（build_temporal_evidence/转换构建规则）")
    add(".dsh/skills/visual-evidence-extractor/scripts/analyze_image.py",
        "v1 生产提示词所在文件（零改动锚点）")
    add("scripts/run_task20_pairing.py", "task20 配对执行器（存档产生者）")
    add("scripts/test_task20_pairing.py", "task20 测试（回归对照）")
    add("artifacts/task-20/render_paired_report.py", "task20 报告渲染器")
    add("artifacts/task-20/verify_task20.py", "task20 验证脚本")

    # ---- 人类可读入口（勘误前哈希，供勘误提交审计差异）
    add("README.md", "人类可读入口（勘误前哈希备案）")
    add("PROJECT_CONTEXT.md", "人类可读入口（勘误前哈希备案）")
    add("BENCHMARK.md", "人类可读入口（勘误前哈希备案）")
    add("docs/DEVELOPMENT_STATUS.md", "人类可读入口（勘误前哈希备案）")
    return entries


def main():
    parser = argparse.ArgumentParser(description="Task 21 阶段 A 输入哈希清单生成")
    parser.add_argument("--out", default=os.path.join(TASK21_PLAN, "input-hashes.json"))
    args = parser.parse_args()

    entries = build_entries()
    seen = set()
    records = []
    for path, purpose in entries:
        if path in seen:
            raise SystemExit(f"[清单缺陷] 重复条目: {path}")
        seen.add(path)
        absolute = os.path.join(PROJECT_ROOT, path)
        if not os.path.isfile(absolute):
            raise SystemExit(f"[缺失输入] 文件不存在: {path}")
        records.append({"path": path, "sha256": sha256_of(absolute), "purpose": purpose})

    doc = {
        "schema_version": "1.0.0",
        "task": "task21-input-hashes",
        "note": ("Task 21 阶段 A 只读输入清单与 SHA-256。重放与勘误仅允许消费本清单所列文件；"
                 "清单外数据（含九段之外的隔离数据、原始视频内容）不在读取范围。"
                 "本文件自身不列入（自引用不可能）。"),
        "entry_count": len(records),
        "entries": records,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    print(f"[ok] {len(records)} 个输入已哈希 -> {rel(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
