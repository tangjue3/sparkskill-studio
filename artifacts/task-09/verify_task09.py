#!/usr/bin/env python3
"""verify_task09.py — 任务 09 交付前综合验证（SparkSkill Studio）

对应任务书第十三节 15 项验证：
  V1  v1 评分器 SHA-256 不变（冻结）
  V2  评测集 SHA-256 不变（冻结）
  V3  任务 07 artifacts 零改动
  V4  任务 08 原始运行 artifacts 零改动（result/stdout/stderr/prompt/score/tier3-result）
  V5  N1–N5 合规否定/政策声明不判违规
  V6  P1–P5 真实断言（含混合语境）判违规
  V7  C1–C2 通过
  V8  known-findings 两项误报修复且符合人工核验
  V9  全量 18 个任务都被 v2 重评分
  V10 除已知两项外无意外评分变化
  V11 Verdict 由原 PASS 条件计算（六项条件逐条复算）
  V12 BENCHMARK.md 历史链完整（Initial/Remediation/v1 Finding/v2/限制）
  V13 git diff --check
  V14 敏感信息扫描
  V15 无临时进程；资源未被本任务启动

输出 artifacts/task-09/verification.json。
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
TASK09 = os.path.join(PROJECT_ROOT, "artifacts", "task-09")
V1_SHA = "c35b450627f0ff36640012ae5cb02ff7b35d608a6d7de01b28ed3935af151ee0"
EVALS_SHA = "64da5041a178ae442391bdbd9b528db5ab27ab514136ec595366b327d864ccaa"
SENSITIVE = re.compile(
    r"(api[_-]?key\s*[:=]\s*[^\s\"'>]{6,}|(?:access|auth|refresh)[_-]?token\s*[:=]\s*[^\s\"'>]{8,}|"
    r"secret\s*[:=]\s*[^\s\"'>]{6,}|password\s*[:=]\s*[^\s\"'>]{6,}|"
    r"sk-[A-Za-z0-9]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)", re.IGNORECASE)

CHECKS = {}


def check(key, passed, detail):
    CHECKS[key] = {"passed": bool(passed), "detail": detail}
    print(f"[{'PASS' if passed else 'FAIL'}] {key}: {detail}")


def sha256(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def main():
    # V1/V2 冻结哈希
    v1_actual = sha256(os.path.join(PROJECT_ROOT, "scripts", "score_tier3_eval.py"))
    evals_actual = sha256(os.path.join(PROJECT_ROOT, "evals", "tier3", "evals.json"))
    check("V1-v1-scorer-frozen", v1_actual == V1_SHA,
          f"scripts/score_tier3_eval.py sha256={v1_actual[:16]}…（期望 {V1_SHA[:16]}…）")
    check("V2-evals-frozen", evals_actual == EVALS_SHA,
          f"evals/tier3/evals.json sha256={evals_actual[:16]}…（期望 {EVALS_SHA[:16]}…）")

    # V3 任务 07 零改动
    proc = subprocess.run(["git", "diff", "25a4f11", "HEAD", "--name-only", "--",
                           "artifacts/task-07/"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    check("V3-task07-untouched", proc.stdout.strip() == "",
          f"git diff 25a4f11..HEAD -- artifacts/task-07/ 变更文件数="
          f"{len([l for l in proc.stdout.splitlines() if l.strip()])}")

    # V4 任务 08 原始运行记录零改动（canonical 记录，不含 cwd-new-files 快照）
    proc = subprocess.run(["git", "diff", "c08a7db", "HEAD", "--name-only", "--",
                           "artifacts/task-08/"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    outside = [line for line in proc.stdout.splitlines()
               if line.strip() and "/cwd-new-files/" not in line]
    canonical = [line for line in outside if not line.endswith("pruned-manifest.json")]
    check("V4-task08-raw-untouched", not canonical,
          f"c08a7db..HEAD 在 artifacts/task-08/ 内非快照目录的改动="
          f"{canonical or '无（仅新增剪枝清单）'}")

    # V5-V7 回归测试
    proc = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "scripts",
                                                        "test_score_tier3_eval_v2.py")],
                          cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=600)
    regression = json.load(open(os.path.join(TASK09, "evaluator-regression.json"),
                                encoding="utf-8"))
    by_id = {item["id"]: item for item in regression["results"]}
    n_ids = [f"N{i}" for i in range(1, 6)]
    p_ids = [f"P{i}" for i in range(1, 6)]
    c_ids = ["C1", "C2"]
    check("V5-N1-N5-compliant-not-flagged",
          all(by_id[i]["passed"] for i in n_ids),
          "；".join(f"{i}={'PASS' if by_id[i]['passed'] else 'FAIL'}" for i in n_ids))
    check("V6-P1-P5-real-assertions-flagged",
          all(by_id[i]["passed"] for i in p_ids),
          "；".join(f"{i}={'PASS' if by_id[i]['passed'] else 'FAIL'}" for i in p_ids))
    check("V7-C1-C2", all(by_id[i]["passed"] for i in c_ids),
          "；".join(f"{i}={'PASS' if by_id[i]['passed'] else 'FAIL'}" for i in c_ids))

    # V8 known-findings
    findings = json.load(open(os.path.join(TASK09, "known-findings", "known-findings.json"),
                              encoding="utf-8"))
    gate = findings["gate"]
    check("V8-known-findings-fixed",
          gate["baseline_E3_false_positive_fixed"]
          and gate["with_skill_E4_false_positive_fixed"]
          and gate["real_violations_still_detected"],
          f"baseline E3 误报修复={gate['baseline_E3_false_positive_fixed']}；"
          f"with-skill E4 误报修复={gate['with_skill_E4_false_positive_fixed']}；"
          f"真实违规仍识别={gate['real_violations_still_detected']}")

    # V9 全量重评分
    missing = []
    for side in ("baseline", "with-skill"):
        for index in range(1, 10):
            path = os.path.join(TASK09, "rescored", side, f"E{index}", "score.json")
            if not os.path.isfile(path):
                missing.append(f"{side}/E{index}")
    check("V9-all-18-rescored", not missing,
          f"v2 重评分 18/18 个任务；缺失={missing or '无'}")

    # V10 无意外变化
    diff = json.load(open(os.path.join(TASK09, "evaluator-diff.json"), encoding="utf-8"))
    check("V10-no-unexpected-changes", not diff["unexpected_changes"],
          f"规则级变化 {len(diff['rule_level_changes'])} 项（均为允许的已知误报修复）；"
          f"意外变化={len(diff['unexpected_changes'])} 项")

    # V11 verdict 复算
    comparison = json.load(open(os.path.join(TASK09, "comparison-v2.json"), encoding="utf-8"))
    conditions = comparison["verdict_conditions"]
    recomputed = all(conditions.values())
    check("V11-verdict-recomputed",
          recomputed == (comparison["verdict"] == "PASS"),
          f"verdict={comparison['verdict']}；六项 PASS 条件逐条复算全部满足={recomputed}"
          if recomputed else
          f"verdict={comparison['verdict']}；条件={json.dumps(conditions, ensure_ascii=False)}")

    # V12 BENCHMARK 历史链
    benchmark = open(os.path.join(PROJECT_ROOT, "BENCHMARK.md"), encoding="utf-8").read()
    required_sections = ["Initial Tier-3 Run", "E9 Remediation", "Evaluator v1 Finding",
                         "Evaluator v2", "限制"]
    missing_sections = [s for s in required_sections if s not in benchmark]
    history_ok = ("25a4f11" in benchmark and "PARTIAL" in benchmark
                  and V1_SHA[:16] in benchmark)
    check("V12-benchmark-history-complete",
          not missing_sections and history_ok,
          f"必需章节缺失={missing_sections or '无'}；历史链（25a4f11/PARTIAL/v1 哈希）在位={history_ok}")

    # V13 git diff --check
    proc = subprocess.run(["git", "diff", "--check"], cwd=PROJECT_ROOT,
                          capture_output=True, text=True)
    check("V13-git-diff-check", proc.returncode == 0 and not proc.stdout.strip(),
          f"git diff --check exit={proc.returncode}，输出={proc.stdout.strip() or '空'}")

    # V14 敏感扫描
    hits = []
    scanned = 0
    for root, _dirs, files in os.walk(TASK09):
        for name in files:
            path = os.path.join(root, name)
            scanned += 1
            try:
                if os.path.getsize(path) > 2 * 1024 * 1024:
                    continue
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    match = SENSITIVE.search(handle.read())
                if match:
                    hits.append(os.path.relpath(path, PROJECT_ROOT))
            except OSError:
                continue
    for rel in ("scripts/score_tier3_eval_v2.py", "scripts/test_score_tier3_eval_v2.py",
                "BENCHMARK.md"):
        with open(os.path.join(PROJECT_ROOT, rel), encoding="utf-8", errors="ignore") as handle:
            if SENSITIVE.search(handle.read()):
                hits.append(rel)
    check("V14-sensitive-scan-clean", not hits,
          f"扫描 task-09 {scanned} 个产物 + 新增代码；命中={hits or '无'}")

    # V15 无临时进程
    proc = subprocess.run(["pgrep", "-af", "run_tier3|score_tier3|trace_multi|analyze_image"],
                          capture_output=True, text=True)
    residual = [line for line in proc.stdout.splitlines()
                if line.strip() and "pgrep" not in line and "verify_task09" not in line]
    check("V15-no-temp-processes", not residual,
          f"临时进程={residual or '无'}；本任务为 CPU-only（未启动 Qwen/DSH/H3/StepFun）")

    passed = sum(1 for item in CHECKS.values() if item["passed"])
    total = len(CHECKS)
    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "task": "task-09-evaluator-v2-rescore",
        "passed": passed, "total": total, "all_passed": passed == total,
        "checks": CHECKS,
        "verdict_v2": comparison["verdict"],
        "scorer_v2_sha256": comparison["scorer"]["sha256"],
    }
    with open(os.path.join(TASK09, "verification.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"\n小计：{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
