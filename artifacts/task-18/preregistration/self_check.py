#!/usr/bin/env python3
"""self_check.py — 任务 18 阶段 A 预注册自检（SparkSkill Studio）

在实现开始前核验：
  S1  设计文档存在且覆盖任务书第六节 18 个必答问题；
  S2  预注册 7 份文件齐全（evaluation-plan/arm-configs/verdict-policy/
      fixture-manifest/ground-truth-manifest/frozen-hashes/README）；
  S3  预注册 JSON 全部可解析且必备字段齐全；
  S4  frozen-hashes.json 与当前文件逐一一致（含 fixture 媒体、GT、契约、设计文档）；
  S5  fixture 冻结复核（generate_task18_fixtures.py --verify 逻辑：SHA-256/元数据/复用一致性）；
  S6  Evidence Pack 契约校验（validate_evidence_pack.py，manifest + ground truth）；
  S7  预注册文件不含凭据样式或敏感绝对路径；
  S8  预注册内容先于实现（本检查在设计文档中声明；由 Git 提交顺序证明）。

退出码: 0 = 全部通过; 1 = 存在失败项
"""
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TASK18_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "fixtures")
TASK18_CONTRACTS = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "contracts")
TASK16_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
DESIGN_DOC = os.path.join(
    PROJECT_ROOT, "docs", "plans", "2026-09-22-coverage-aware-adaptive-sampling-design.md")

REQUIRED_FILES = [
    "evaluation-plan.json", "fixture-manifest.json", "ground-truth-manifest.json",
    "arm-configs.json", "verdict-policy.json", "frozen-hashes.json", "README.md",
]

# 设计文档必须回答的 18 个问题（任务书第六节；以章节锚点核验）
DESIGN_SECTIONS = [
    ("覆盖盲区", "任务 17 暴露了什么覆盖盲区"),
    ("触发式边界细化无法发现", "为什么触发式边界细化无法发现完全未采样的窄事件"),
    ("职责分离", "覆盖探索与边界细化的职责如何分离"),
    ("预算", "硬调用预算如何在两类职责之间分配"),
    ("最大相邻采样间隔", "如何定义“最大相邻采样间隔”"),
    ("覆盖分辨率", "覆盖分辨率能说明什么，不能说明什么"),
    ("任意短事件", "为什么不能保证发现任意短事件"),
    ("旧策略行为不变", "新策略如何保持旧策略行为不变"),
    ("向后兼容", "新配置如何保持旧 VisualTaskSpec 向后兼容"),
    ("公平条件", "三臂比较的公平条件"),
    ("预注册", "预注册的 fixture、Ground Truth、查询、预算、顺序与 verdict 规则"),
    ("非确定性", "真实模型非确定性如何记录"),
    ("校准", "coverage 与模型语义校准为何必须分开"),
    ("过度断言", "uncertain 被触达但模型过度断言时如何评分"),
    ("职责", "DSH/StepFun/Qwen 的真实职责"),
    ("资源守卫", "资源守卫与阻塞行为"),
    ("回归范围", "回归范围、冻结范围与允许修改范围"),
    ("非目标", "非目标与对外声明红线"),
]

CREDENTIAL_MARKERS = ("api_key", "api-key", "secret", "token=", "password", "passwd",
                      "bearer ", "private_key", "-----begin")

RESULTS = []


def record(check_id, name, passed, detail):
    RESULTS.append({"id": check_id, "name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {check_id} — {name}: {detail}")


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    # S1 设计文档
    if not os.path.isfile(DESIGN_DOC):
        record("S1-design-doc", "设计文档存在且覆盖 18 个必答问题", False,
               f"缺少 {os.path.relpath(DESIGN_DOC, PROJECT_ROOT)}")
    else:
        text = open(DESIGN_DOC, encoding="utf-8").read()
        missing = [f"{anchor}" for anchor, _ in DESIGN_SECTIONS if anchor not in text]
        record("S1-design-doc", "设计文档存在且覆盖 18 个必答问题", not missing,
               f"{len(DESIGN_SECTIONS) - len(missing)}/{len(DESIGN_SECTIONS)} 个章节锚点命中"
               + (f"；缺失: {missing}" if missing else ""))

    # S2 预注册文件齐全
    missing_files = [name for name in REQUIRED_FILES
                     if not os.path.isfile(os.path.join(HERE, name))]
    record("S2-preregistration-files", "预注册 7 份文件齐全", not missing_files,
           f"{len(REQUIRED_FILES) - len(missing_files)}/{len(REQUIRED_FILES)}"
           + (f"；缺失: {missing_files}" if missing_files else ""))

    # S3 JSON 可解析且必备字段齐全
    json_problems = []
    plan = load_json(os.path.join(HERE, "evaluation-plan.json"))
    for key in ("arms", "scenarios", "budgets", "execution_order", "runs", "scoring",
                "fairness_gate", "separation", "non_goals"):
        if key not in plan:
            json_problems.append(f"evaluation-plan.json 缺少 {key}")
    arms = load_json(os.path.join(HERE, "arm-configs.json"))
    arm_ids = [arm["arm_id"] for arm in arms.get("arms", [])]
    if arm_ids != ["uniform", "adaptive", "coverage"]:
        json_problems.append(f"arm-configs.json 臂配置异常: {arm_ids}")
    policy = load_json(os.path.join(HERE, "verdict-policy.json"))
    if set(policy.get("allowed_verdicts", [])) != {
            "IMPROVEMENT", "TRADEOFF", "NO_IMPROVEMENT", "INVALID_COMPARISON"}:
        json_problems.append("verdict-policy.json 允许 verdict 集合异常")
    fixture_manifest = load_json(os.path.join(HERE, "fixture-manifest.json"))
    if len(fixture_manifest.get("scenarios", {})) != 11:
        json_problems.append("fixture-manifest.json 场景数不为 11")
    gt_manifest = load_json(os.path.join(HERE, "ground-truth-manifest.json"))
    if len(gt_manifest.get("samples", {})) != 11:
        json_problems.append("ground-truth-manifest.json GT 数不为 11")
    frozen = load_json(os.path.join(HERE, "frozen-hashes.json"))
    for key in ("preregistration_declarations", "preregistration_data", "fixtures",
                "ground_truth", "contracts", "design_doc"):
        if key not in frozen:
            json_problems.append(f"frozen-hashes.json 缺少 {key}")
    record("S3-preregistration-json", "预注册 JSON 可解析且必备字段齐全",
           not json_problems, "；".join(json_problems) if json_problems
           else "evaluation-plan/arm-configs/verdict-policy/fixture-manifest/"
                "ground-truth-manifest/frozen-hashes 结构与必备字段齐全")

    # S4 frozen-hashes 一致性
    mismatches = []

    def check_group(group, label):
        for key, entry in frozen.get(group, {}).items():
            path = os.path.join(PROJECT_ROOT, entry["path"])
            if not os.path.isfile(path):
                mismatches.append(f"{label}/{key}: 文件缺失")
            elif sha256_of(path) != entry["sha256"]:
                mismatches.append(f"{label}/{key}: SHA-256 不一致")

    for group in ("preregistration_declarations", "preregistration_data", "fixtures",
                  "ground_truth", "contracts", "design_doc"):
        check_group(group, group)
    record("S4-frozen-hashes", "frozen-hashes.json 与当前文件逐一一致", not mismatches,
           f"{sum(len(frozen.get(g, {})) for g in ('preregistration_declarations', 'preregistration_data', 'fixtures', 'ground_truth', 'contracts', 'design_doc'))} 个条目核验"
           + (f"；不一致: {mismatches}" if mismatches else ""))

    # S5 fixture 冻结复核
    proc = subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, "scripts",
                                      "generate_task18_fixtures.py"), "--verify"],
        capture_output=True, text=True)
    record("S5-fixture-freeze", "fixture 冻结复核（SHA-256/元数据/复用一致性）",
           proc.returncode == 0 and "FROZEN_OK" in proc.stdout,
           proc.stdout.strip().splitlines()[-1] if proc.stdout.strip()
           else proc.stderr.strip()[-200:])

    # S6 Evidence Pack 契约校验
    proc = subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, "scripts",
                                      "validate_evidence_pack.py"),
         "--manifest", os.path.join(TASK18_CONTRACTS,
                                    "task18-fixture-evidence-pack-manifest.json"),
         "--ground-truth", os.path.join(TASK18_CONTRACTS, "ground-truth")],
        capture_output=True, text=True)
    record("S6-evidence-pack-contract", "Evidence Pack manifest + Ground Truth 契约校验",
           proc.returncode == 0 and "RESULT: VALID" in proc.stdout,
           proc.stdout.strip().splitlines()[-1] if proc.stdout.strip()
           else proc.stderr.strip()[-200:])

    # S7 预注册文件安全扫描（跳过扫描脚本自身：其模式定义必然包含标记字面量；
    # 与任务 17 verify_task17.py 的“跳过脚本自身”同一处置）
    security_problems = []
    scanner_name = os.path.basename(os.path.abspath(__file__))
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name == scanner_name:
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, PROJECT_ROOT)
            if name.endswith((".png", ".mp4")):
                continue
            text = open(path, encoding="utf-8", errors="replace").read()
            lowered = text.lower()
            for marker in CREDENTIAL_MARKERS:
                if marker in lowered:
                    security_problems.append(f"{rel}: 疑似凭据标记 {marker!r}")
            if re.search(r"sk-[A-Za-z0-9]{16,}", text):
                security_problems.append(f"{rel}: 疑似长令牌")
            for sensitive in ("/home/", "/root/", "/etc/"):
                if sensitive in text:
                    security_problems.append(f"{rel}: 敏感绝对路径 {sensitive!r}")
    record("S7-preregistration-security", "预注册文件不含凭据或敏感绝对路径",
           not security_problems, "；".join(security_problems) if security_problems
           else "凭据标记/长令牌/敏感绝对路径扫描 0 命中")

    # S8 实现尚未开始（本仓库中 coverage_aware_adaptive 只允许出现在预注册/设计文档）
    impl_hits = []
    for rel_path in ("schemas/visual-task-spec.schema.json",
                     ".dsh/skills/task-to-skill-compiler/scripts/validate_task_spec.py",
                     ".dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py",
                     ".dsh/skills/visual-evidence-extractor/scripts/trace_temporal.py"):
        path = os.path.join(PROJECT_ROOT, rel_path)
        if os.path.isfile(path) and "coverage_aware_adaptive" in open(
                path, encoding="utf-8").read():
            impl_hits.append(rel_path)
    record("S8-implementation-not-started", "实现尚未开始（策略枚举中无 coverage_aware_adaptive）",
           not impl_hits, "；".join(impl_hits) if impl_hits
           else "schema/校验器/sampler/executor 均未包含新策略（阶段 A 纯洁性）")

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    print(f"\n小计：{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
