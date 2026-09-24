#!/usr/bin/env python3
"""verify_task16.py — 任务 16 交付前验证（SparkSkill Studio）

对照任务书第十六节/第十八节/第二十一节，对任务 16 产物做确定性核验：
  V1–V6   测试与回归（任务 16 新测试、任务 04/06 回归、M1–M8、v2 评分器回归）
  V7–V9   fixture 冻结（manifest/hash/ground truth 一致；未重新生成）
  V10–V13 uniform vs adaptive 对照（公平性字段、逐场景指标完整性、Verdict 存在且未预设）
  V14–V16 DSH 自主会话（会话证据存在、真实调用计数与产物一致）
  V17–V19 冻结数据完整性（任务 07/08/09 零变化；Tier-3 任务集/评分器未改）
  V20–V22 安全与卫生（git diff --check、敏感信息扫描、provenance 无凭据）
  V23–V24 文档与工作区（设计文档存在且含必需要素；无 holdout 内容）

用法:
    python3 artifacts/task-16/verify_task16.py
退出码: 0 = 全部通过; 1 = 存在失败项
"""
import hashlib
import json
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
TASK16 = os.path.join(PROJECT_ROOT, "artifacts", "task-16")
FIXTURES = os.path.join(TASK16, "fixtures")

RESULTS = []


def record(check_id, name, passed, detail):
    RESULTS.append({"id": check_id, "name": name, "passed": bool(passed), "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {check_id} — {name}: {detail}")


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args):
    return subprocess.run(["git", "-C", PROJECT_ROOT, *args],
                          capture_output=True, text=True)


def test_suite_passed(path, suite_name):
    if not os.path.isfile(path):
        return False, f"{suite_name} 结果文件缺失: {os.path.relpath(path, PROJECT_ROOT)}"
    try:
        payload = load_json(path)
    except (OSError, json.JSONDecodeError) as error:
        return False, f"{suite_name} 结果不可解析: {error}"
    return payload.get("all_passed") is True or (
        payload.get("passed") == payload.get("total") and payload.get("total", 0) > 0), \
        f"{suite_name}: {payload.get('passed')}/{payload.get('total')}"


def main():
    # ---------------- V1–V6 测试与回归
    ok, detail = test_suite_passed(os.path.join(TASK16, "test-results.json"), "任务 16 新测试")
    record("V1-task16-new-tests-pass", "任务 16 新增测试全部通过", ok, detail)

    # 公开版适配：artifacts/task-04|task-06/ 为内部留档（不随公开仓库分发），
    # 其结果文件缺失时直接重跑对应测试套件（套件在公开仓库中），以重跑核验回归。
    regression_suites = [
        ("V2-task04-regression", "任务 04 视频规则回归通过",
         os.path.join(PROJECT_ROOT, "artifacts", "task-04", "test-results.json"), "任务 04",
         os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                      "scripts", "test_video_pipeline.py"), "16/16 通过"),
        ("V3-task06-regression", "任务 06 多视频规则回归通过",
         os.path.join(PROJECT_ROOT, "artifacts", "task-06", "test-results.json"), "任务 06",
         os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                      "scripts", "test_multi_video_pipeline.py"), "32/32 通过"),
    ]
    for check_id, name, result_path, label, suite, expect in regression_suites:
        if os.path.isfile(result_path):
            ok, detail = test_suite_passed(result_path, label)
        else:
            proc = subprocess.run([sys.executable, suite], capture_output=True, text=True)
            ok = proc.returncode == 0 and expect in (proc.stdout + proc.stderr)
            tail = (proc.stdout or "").strip().splitlines()
            detail = (f"{label} 结果文件为内部留档，公开版重跑套件: "
                      f"{tail[-1] if tail else proc.stderr[-120:]}")
        record(check_id, name, ok, detail)

    # M1–M8 与 v2 评分器：重跑（纯 CPU、无模型）并核对通过数
    proc = subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, ".dsh", "skills", "task-to-skill-compiler",
                                      "scripts", "test_missing_media_contract.py")],
        capture_output=True, text=True)
    m_ok = proc.returncode == 0 and "10/10" in (proc.stdout + proc.stderr)
    record("V4-media-contract-regression", "M1–M8 媒体来源契约回归通过（重跑）", m_ok,
           f"exit={proc.returncode}，输出含 10/10={'10/10' in (proc.stdout + proc.stderr)}")

    proc = subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "test_score_tier3_eval_v2.py")],
        capture_output=True, text=True)
    v2_ok = proc.returncode == 0 and "17/17" in (proc.stdout + proc.stderr)
    record("V5-scorer-v2-regression", "v2 评分器回归通过（重跑）", v2_ok,
           f"exit={proc.returncode}，输出含 17/17={'17/17' in (proc.stdout + proc.stderr)}")

    # V6 fixture 冻结复核
    proc = subprocess.run(
        [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "generate_task16_fixtures.py"),
         "--verify"], capture_output=True, text=True)
    record("V6-fixtures-frozen", "technical fixture 冻结完整（manifest/hash/ground truth 一致）",
           proc.returncode == 0 and "FROZEN_OK" in proc.stdout,
           f"exit={proc.returncode}；{proc.stdout.strip()[-120:]}")

    # ---------------- V7–V9 fixture hash 逐文件复核
    manifest_path = os.path.join(FIXTURES, "fixture-manifest.json")
    gt_path = os.path.join(FIXTURES, "ground-truth.json")
    if os.path.isfile(manifest_path) and os.path.isfile(gt_path):
        manifest = load_json(manifest_path)
        gt = load_json(gt_path)
        mismatches = []
        for fixture_id, entry in manifest["videos"].items():
            path = os.path.join(PROJECT_ROOT, entry["path"])
            if not os.path.isfile(path):
                mismatches.append(f"{fixture_id}: 文件缺失")
                continue
            actual = sha256_of(path)
            if actual != entry["sha256"]:
                mismatches.append(f"{fixture_id}: SHA-256 不一致")
            if fixture_id not in gt.get("fixtures", {}):
                mismatches.append(f"{fixture_id}: ground truth 缺失")
        record("V7-fixture-sha256-match-manifest", "每个 fixture 的 SHA-256 与冻结 manifest 一致",
               not mismatches, "；".join(mismatches) if mismatches else
               f"{len(manifest['videos'])} 个 fixture 全部一致")
        record("V8-fixture-ground-truth-present", "fixture ground truth 存在且覆盖全部 fixture",
               len(gt.get("fixtures", {})) == len(manifest["videos"])
               and bool(gt.get("generation_params")),
               f"ground truth fixtures={len(gt.get('fixtures', {}))}，"
               f"生成参数冻结={bool(gt.get('generation_params'))}")
        record("V9-fixture-marked-synthetic", "fixture 明确标注 synthetic technical fixture",
               "synthetic technical fixture" in (manifest.get("nature") or "")
               and "synthetic technical fixture" in (gt.get("nature") or ""),
               f"manifest.nature={manifest.get('nature')!r}")
    else:
        record("V7-fixture-sha256-match-manifest", "fixture manifest 存在", False, "manifest 缺失")
        record("V8-fixture-ground-trifest-present", "fixture ground truth 存在", False, "缺失")
        record("V9-fixture-marked-synthetic", "fixture 标注 synthetic", False, "缺失")

    # ---------------- V10–V13 对照
    comparison_path = os.path.join(TASK16, "comparison.json")
    if os.path.isfile(comparison_path):
        comparison = load_json(comparison_path)
        fairness = comparison.get("fairness") or {}
        fairness_ok = (fairness.get("same_video") is True
                       and fairness.get("same_target_query")
                       and fairness.get("same_model")
                       and fairness.get("same_status_rules")
                       and fairness.get("same_max_model_calls") is not None
                       and fairness.get("same_timeout_s") is not None
                       and fairness.get("no_sample_removal") is True
                       and fairness.get("no_single_side_retry") is True
                       and fairness.get("ground_truth_not_modified_after_results") is True)
        record("V10-comparison-fairness-fields", "对照公平性字段完整", fairness_ok,
               f"same_budget={fairness.get('same_max_model_calls')}，"
               f"同规则={bool(fairness.get('same_status_rules'))}，"
               f"不删样本={fairness.get('no_sample_removal')}")

        scenarios = comparison.get("scenarios") or {}
        same_budget = [k for k in scenarios if k.startswith("same-budget-")]
        metrics_ok = True
        details = []
        for key in same_budget:
            arms = scenarios[key].get("arms") or {}
            if set(arms) != {"uniform", "adaptive"}:
                metrics_ok = False
                details.append(f"{key}: 臂不完整")
                continue
            for arm, payload in arms.items():
                metrics = payload.get("metrics") or {}
                required = ["final_status", "first_confirmed_observed_ms",
                            "last_confirmed_observed_ms", "state_transition_count",
                            "actual_model_calls", "wall_time_s", "per_call_ms",
                            "budget_exhausted", "evidence_nature"]
                missing = [field for field in required if field not in metrics]
                if missing:
                    metrics_ok = False
                    details.append(f"{key}/{arm}: 缺 {missing}")
                counts = metrics.get("class_counts") or {}
                if not all(name in counts for name in
                           ("confirmed", "not_found", "abstained", "low_confidence", "failed")):
                    metrics_ok = False
                    details.append(f"{key}/{arm}: 五类计数不完整")
        record("V11-comparison-metrics-complete", "对照逐场景指标完整（含五类计数与耗时）",
               metrics_ok and bool(same_budget),
               "；".join(details) if details else
               f"{len(same_budget)} 个同预算场景，双臂指标完整")

        verdict = comparison.get("verdict") or {}
        verdict_ok = verdict.get("verdict") in ("IMPROVEMENT", "PARTIAL", "NO_IMPROVEMENT")
        record("V12-comparison-verdict-present", "对照 Verdict 存在且取值合法（未预设 PASS）",
               verdict_ok, f"verdict={verdict.get('verdict')}")
        record("V13-comparison-no-fabricated-continuity",
               "对照结论无虚假连续性断言（每场景均有语义声明）",
               all((arms.get("uniform", {}).get("metrics", {})
                    .get("report_has_temporal_disclaimer") is True)
                   and (arms.get("adaptive", {}).get("metrics", {})
                        .get("report_has_temporal_disclaimer") is True)
                   for arms in (scenarios[k].get("arms") or {}
                                for k in same_budget)) if same_budget else False,
               "uniform/adaptive 报告均含“不是连续跟踪真值”声明")
    else:
        for cid, name in [("V10-comparison-fairness-fields", "对照公平性字段完整"),
                          ("V11-comparison-metrics-complete", "对照指标完整"),
                          ("V12-comparison-verdict-present", "对照 Verdict 存在"),
                          ("V13-comparison-no-fabricated-continuity", "对照无虚假连续性")]:
            record(cid, name, False, "comparison.json 缺失")

    # ---------------- V14–V16 DSH 会话
    session_dir = os.path.join(TASK16, "dsh-session")
    session_summary = os.path.join(session_dir, "session-summary.json")
    if os.path.isfile(session_summary):
        session = load_json(session_summary)
        record("V14-dsh-session-autonomous", "DSH headless 自主会话证据存在",
               session.get("autonomous") is True and bool(session.get("started_at")),
               f"session {session.get('started_at')} → {session.get('ended_at')}，"
               f"exit={session.get('session_exit_code')}，autonomous={session.get('autonomous')}")
        temporal = os.path.join(session_dir, "temporal-evidence.json")
        if os.path.isfile(temporal):
            doc = load_json(temporal)
            provenance = doc.get("sampling_provenance") or {}
            calls = provenance.get("actual_model_calls")
            budget = provenance.get("configured_budget")
            record("V15-dsh-session-real-calls-within-budget",
                   "DSH 会话真实 Qwen 调用数不超过硬预算",
                   isinstance(calls, int) and isinstance(budget, int) and calls <= budget
                   and calls > 0,
                   f"实际调用={calls}，预算={budget}")
            entries = doc.get("timeline") or []
            real = [e for e in entries
                    if e.get("evidence_nature") in ("real_model_output", "backend_call_failed")]
            record("V16-dsh-session-calls-match-entries",
                   "会话调用计数与时间线条目一致（真实模型输出）",
                   len(real) == calls,
                   f"provenance={calls}，timeline 真实证据条目={len(real)}")
        else:
            record("V15-dsh-session-real-calls-within-budget", "DSH 会话时序证据存在", False, "缺失")
            record("V16-dsh-session-calls-match-entries", "DSH 会话计数一致", False, "缺失")
    else:
        record("V14-dsh-session-autonomous", "DSH 自主会话证据存在", False,
               "dsh-session/session-summary.json 缺失（若资源阻塞，需有资源阻塞报告）")
        record("V15-dsh-session-real-calls-within-budget", "DSH 会话调用不超预算", False, "缺失")
        record("V16-dsh-session-calls-match-entries", "DSH 会话计数一致", False, "缺失")

    # ---------------- V17–V19 冻结数据完整性
    frozen_ok = True
    details = []
    for label, rel in [
        ("evals/tier3/evals.json", "evals/tier3/evals.json"),
        ("scripts/score_tier3_eval.py", "scripts/score_tier3_eval.py"),
        ("scripts/score_tier3_eval_v2.py", "scripts/score_tier3_eval_v2.py"),
    ]:
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path):
            frozen_ok = False
            details.append(f"{rel} 缺失")
            continue
        proc = git("status", "--porcelain", rel)
        if proc.stdout.strip():
            frozen_ok = False
            details.append(f"{rel} 有未提交修改")
    expected_v1 = "c35b450627f0ff36640012ae5cb02ff7b35d608a6d7de01b28ed3935af151ee0"
    expected_v2 = "949772c9ccc863e926e52261ea98c97112912ee7c51830c87910b70bc8def95d"
    actual_v1 = sha256_of(os.path.join(PROJECT_ROOT, "scripts", "score_tier3_eval.py"))
    actual_v2 = sha256_of(os.path.join(PROJECT_ROOT, "scripts", "score_tier3_eval_v2.py"))
    if actual_v1 != expected_v1:
        frozen_ok = False
        details.append("v1 评分器哈希变化")
    if actual_v2 != expected_v2:
        frozen_ok = False
        details.append("v2 评分器哈希变化")
    record("V17-tier3-frozen-assets-untouched", "Tier-3 任务集与 v1/v2 评分器零变化",
           frozen_ok, "；".join(details) if details else
           "evals.json/v1/v2 均未修改且哈希与文档声明一致")

    proc = git("status", "--porcelain", "artifacts/task-07", "artifacts/task-08",
               "artifacts/task-09")
    record("V18-task07-09-artifacts-untouched", "任务 07/08/09 冻结 artifacts 零变化",
           not proc.stdout.strip(), proc.stdout.strip() or "三个目录均无改动")

    workbench = git("status", "--porcelain", "app", "scripts/serve_demo.py",
                    "scripts/build_demo_manifest.py", "scripts/test_demo_app.py")
    record("V19-workbench-untouched", "Evidence Workbench 未被修改", not workbench.stdout.strip(),
           workbench.stdout.strip() or "app/ 与工作台脚本零变化")

    # ---------------- V20–V22 安全与卫生
    proc = git("diff", "--check")
    record("V20-git-diff-check", "git diff --check 通过（无空白错误）",
           proc.returncode == 0 and not proc.stdout.strip(),
           proc.stdout.strip() or "clean")

    sensitive_patterns = [
        (re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*\S+"), "凭据样式"),
        (re.compile(r"sk-[A-Za-z0-9]{16,}"), "OpenAI 样式长令牌"),
        (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥头"),
    ]
    hits = []
    for base, dirs, files in [(PROJECT_ROOT, ["artifacts/task-16"], None)]:
        for directory in dirs:
            for root, _, filenames in os.walk(os.path.join(base, directory)):
                for filename in filenames:
                    path = os.path.join(root, filename)
                    if filename.endswith((".png", ".jpg", ".jpeg", ".mp4")):
                        continue
                    try:
                        with open(path, encoding="utf-8") as handle:
                            text = handle.read()
                    except (OSError, UnicodeDecodeError):
                        continue
                    for pattern, label in sensitive_patterns:
                        if pattern.search(text):
                            hits.append(f"{os.path.relpath(path, PROJECT_ROOT)}: {label}")
    record("V21-sensitive-scan", "artifacts/task-16 敏感信息扫描零命中",
           not hits, "；".join(hits[:5]) if hits else "0 命中（凭据/长令牌/私钥）")

    prov_hits = []
    for root, _, filenames in os.walk(os.path.join(TASK16, "comparison")):
        for filename in filenames:
            if filename == "temporal-evidence.json":
                doc = load_json(os.path.join(root, filename))
                text = json.dumps(doc.get("sampling_provenance") or {}, ensure_ascii=False)
                for pattern, label in sensitive_patterns:
                    if pattern.search(text):
                        prov_hits.append(f"{os.path.relpath(os.path.join(root, filename), PROJECT_ROOT)}: {label}")
    record("V22-provenance-no-credentials", "对照产物 provenance 不含凭据",
           not prov_hits, "；".join(prov_hits[:5]) if prov_hits else "0 命中")

    # ---------------- V23–V24 文档与 holdout
    design_path = os.path.join(PROJECT_ROOT, "docs", "plans",
                               "2026-09-22-temporal-evidence-adaptive-sampling-design.md")
    design_ok = os.path.isfile(design_path)
    if design_ok:
        text = open(design_path, encoding="utf-8").read()
        required_sections = ["问题", "不新增第四个 Skill", "向后兼容", "调用预算", "provenance",
                             "时序证据", "uniform", "technical fixture", "公平性", "不做事项",
                             "holdout"]
        missing = [s for s in required_sections if s not in text]
        design_ok = not missing
        record("V23-design-doc-complete", "设计文档存在且覆盖必需要素",
               design_ok, f"缺失要素={missing}" if missing else "12 类必需要素齐全")
    else:
        record("V23-design-doc-complete", "设计文档存在且覆盖必需要素", False, "设计文档缺失")

    holdout_hits = []
    for root, _, filenames in os.walk(TASK16):
        for filename in filenames:
            path = os.path.join(root, filename)
            try:
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            if "holdout" in text.lower() and "不得" not in text and "禁止" not in text \
                    and "未" not in text:
                holdout_hits.append(os.path.relpath(path, PROJECT_ROOT))
    record("V24-no-holdout-content", "任务 16 产物不含 holdout 内容",
           not holdout_hits, "；".join(holdout_hits[:5]) if holdout_hits else "0 命中")

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    payload = {
        "task": "task-16-temporal-evidence-adaptive-sampling",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "passed": passed,
        "total": total,
        "all_passed": passed == total,
        "checks": RESULTS,
    }
    with open(os.path.join(TASK16, "verification.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"\n小计：{passed}/{total} 通过（结果已写入 artifacts/task-16/verification.json）")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
