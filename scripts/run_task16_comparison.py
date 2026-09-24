#!/usr/bin/env python3
"""run_task16_comparison.py — 任务 16 uniform vs adaptive 小样本对照（SparkSkill Studio）

独立于 Tier-3 冻结评测的任务 16 对照。公平性纪律（硬约束）：

  - 相同 fixture 视频、相同目标查询、相同 Qwen Vision 模型、相同资源窗口、
    相同状态分类规则（同一 trace_temporal.py 代码路径与 frame_class）、
    相同最大调用预算（除显式标注的“更少调用”场景）、相同超时；
  - 不单侧重试、不删除失败样本、不在看到结果后修改 ground truth；
  - 不修改 Tier-3 任务集或 PASS 条件；
  - 不预设 adaptive 必须 PASS：无改善时 Verdict 写 PARTIAL / NO_IMPROVEMENT；
  - 技术 fixture 结果不得外推为真实仓储准确率。

用法:
    python3 scripts/run_task16_comparison.py [--out artifacts/task-16] \
        [--budget 12] [--precision-ms 500] [--timeout 300]
退出码: 0 = 对照完成（Verdict 见 comparison.json）; 1 = 前置校验失败
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TRACE_TEMPORAL = os.path.join(
    PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor", "scripts", "trace_temporal.py")
GENERATE_REPORT = os.path.join(
    PROJECT_ROOT, ".dsh", "skills", "evidence-report-generator", "scripts", "generate_report.py")
FIXTURE_GENERATOR = os.path.join(PROJECT_ROOT, "scripts", "generate_task16_fixtures.py")
FIXTURES_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")

TARGET_QUERY = "红色正方形"
DEFAULT_MODEL = "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest"

# 对照场景：5 个视频 fixture（same-budget 主对照）+ 1 个预算耗尽场景（显式标注少预算）
# + 1 个多来源场景（共享预算）
COMPARISON_FIXTURES = [
    "present-throughout", "appear-midway", "disappear-midway", "reappear", "abstain-zone",
]
BUDGET_SCENARIOS = [
    {"id": "reappear-adaptive-budget-6", "fixture": "reappear", "strategy": "adaptive",
     "max_model_calls": 6,
     "purpose": "预算耗尽场景（显式少于主对照预算，验证停止细化与如实报告）"},
]
MULTI_SOURCE_SCENARIO = {
    "id": "multi-source-pair",
    "sources": [
        {"source_id": "video-a", "fixture": "appear-midway", "time_offset_ms": 0},
        {"source_id": "video-b", "fixture": "disappear-midway", "time_offset_ms": 5000},
    ],
    "max_model_calls": 24,
    "purpose": "多来源输入（共享预算；验证 source_id/原时间戳保留与全局时序证据）",
}


def mem_available_gib():
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 1024.0 / 1024.0, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def ollama_reachable(timeout=5):
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout):
            return True
    except Exception:
        return False


def resource_snapshot(samples=3, min_gib=45.0):
    """资源门槛：MemAvailable 连续 samples 次采样均 >= min_gib；Ollama 可达。"""
    readings = []
    for _ in range(samples):
        readings.append(mem_available_gib())
        time.sleep(1)
    return {
        "mem_available_gib_samples": readings,
        "mem_available_min_required_gib": min_gib,
        "mem_gate_passed": all(r is not None and r >= min_gib for r in readings),
        "ollama_reachable": ollama_reachable(),
    }


def load_fixtures():
    manifest_path = os.path.join(FIXTURES_DIR, "fixture-manifest.json")
    gt_path = os.path.join(FIXTURES_DIR, "ground-truth.json")
    if not os.path.isfile(manifest_path) or not os.path.isfile(gt_path):
        raise SystemExit("[错误] fixture 未冻结（缺少 manifest/ground-truth），先运行 "
                         "python3 scripts/generate_task16_fixtures.py")
    return json.load(open(manifest_path, encoding="utf-8")), \
        json.load(open(gt_path, encoding="utf-8"))


def base_spec(task_id, source_media):
    return {
        "task_id": task_id,
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_trace",
        "target": {"description": TARGET_QUERY, "attributes": ["红色", "正方形"]},
        "source_media": source_media,
        "required_outputs": ["object_found", "description", "bounding_box",
                             "confidence", "evidence_text"],
        "constraints": {
            "abstain_if_insufficient_evidence": True,
            "forbidden_inferences": ["identity", "age", "nationality",
                                     "relationship", "intent"],
        },
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
    }


def run_arm(spec, out_dir, arm, budget, precision_ms, timeout, input_nature):
    """执行一个对照臂（uniform/adaptive）。返回 (doc, report, elapsed_s)。"""
    os.makedirs(out_dir, exist_ok=True)
    spec_path = os.path.join(out_dir, "task-spec.json")
    with open(spec_path, "w", encoding="utf-8") as handle:
        json.dump(spec, handle, ensure_ascii=False)
    evidence_path = os.path.join(out_dir, "temporal-evidence.json")
    report_path = os.path.join(out_dir, "temporal-report.json")
    cmd = [sys.executable, TRACE_TEMPORAL,
           "--task-spec", spec_path,
           "--output", evidence_path,
           "--timeout", str(timeout),
           "--input-nature", input_nature,
           "--save-raw-dir", os.path.join(out_dir, "raw")]
    if arm == "uniform":
        # 相同预算：interval 700ms × max 12 → 8s fixture 恰好 12 个采样点
        cmd += ["--strategy", "uniform", "--max-model-calls", str(budget),
                "--interval-ms", "700", "--max-frames", str(budget)]
    else:
        cmd += ["--strategy", "adaptive_coarse_to_fine",
                "--max-model-calls", str(budget),
                "--initial-coverage-samples", "4",
                "--target-boundary-precision-ms", str(precision_ms),
                "--max-refinement-rounds", "6"]
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = round(time.monotonic() - started, 3)
    if proc.returncode != 0:
        raise SystemExit(f"[错误] {arm} 臂执行失败（exit={proc.returncode}）:\n"
                         f"{proc.stderr[-2000:]}")
    doc = json.load(open(evidence_path, encoding="utf-8"))
    report_proc = subprocess.run(
        [sys.executable, GENERATE_REPORT,
         "--task-spec", spec_path,
         "--evidence", evidence_path,
         "--output", report_path,
         "--mode", "temporal" if "global_timeline" not in doc else "temporal-multi"],
        capture_output=True, text=True)
    if report_proc.returncode != 0:
        raise SystemExit(f"[错误] {arm} 臂报告生成失败:\n{report_proc.stderr[-2000:]}")
    report = json.load(open(report_path, encoding="utf-8"))
    return doc, report, elapsed


NEGATION_MARKERS = ("未断言", "不得断言", "不断言", "不是", "未", "不", "非", "无", "禁止")
CONTINUITY_PHRASES = ("持续存在", "始终存在", "一直存在", "连续存在")


def suspicious_continuity_phrases(conclusion):
    """虚假连续性断言扫描（否定语境感知）。

    免责声明中的“未断言连续存在 / 不得断言连续存在”是合规表述；
    只把**非否定语境**下声称连续/持续存在的措辞计为可疑。
    """
    hits = []
    for phrase in CONTINUITY_PHRASES:
        start = 0
        while True:
            index = conclusion.find(phrase, start)
            if index == -1:
                break
            context = conclusion[max(0, index - 8):index]
            if not any(marker in context for marker in NEGATION_MARKERS):
                hits.append(phrase)
                break
            start = index + 1
    return hits


def metrics_from(doc, report, elapsed_s):
    """从真实运行产物提取对照指标（不引入任何估计值）。"""
    provenance = doc.get("sampling_provenance") or doc.get("shared_budget") or {}
    temporal = doc.get("temporal_evidence") or doc.get("global_temporal_evidence") or {}
    summary = doc.get("summary") or doc.get("global_summary") or {}
    timing = provenance.get("timing") or {}
    actual_calls = provenance.get("actual_model_calls", 0)
    analysis_ms = timing.get("analysis_ms")
    per_call_ms = round(analysis_ms / actual_calls, 1) if actual_calls and analysis_ms else None
    conclusion = report.get("conclusion") or ""
    suspicious = suspicious_continuity_phrases(conclusion)
    return {
        "strategy": doc.get("sampling_strategy"),
        "final_status": summary.get("overall_status"),
        "first_confirmed_observed_ms": temporal.get("first_confirmed_observed_ms"),
        "last_confirmed_observed_ms": temporal.get("last_confirmed_observed_ms"),
        "confirmed_sample_count": temporal.get("confirmed_sample_count"),
        "state_transition_count": temporal.get("state_transition_count"),
        "state_transitions": temporal.get("state_transitions"),
        "max_uncertainty_width_ms": (temporal.get("boundary_uncertainty") or {}).get("max_ms"),
        "target_precision_reached": (temporal.get("boundary_uncertainty") or {}).get(
            "target_precision_reached"),
        "class_counts": temporal.get("class_counts"),
        "actual_model_calls": actual_calls,
        "configured_budget": provenance.get("configured_budget",
                                            provenance.get("max_model_calls")),
        "budget_exhausted": provenance.get("budget_exhausted"),
        "wall_time_s": elapsed_s,
        "pipeline_total_ms": timing.get("total_ms"),
        "per_call_ms": per_call_ms,
        "evidence_nature": doc.get("evidence_nature"),
        "report_has_temporal_disclaimer": "不是连续跟踪真值" in conclusion,
        "suspicious_continuity_phrases": suspicious,
        "resource_blocked": doc.get("backend", {}).get("resource_blocked"),
        "warnings": report.get("warnings") or [],
    }


def gt_checks(fixture_gt, doc):
    """对照冻结 ground truth 的确定性检查（规则级，不用模型当裁判）。"""
    expected = fixture_gt["expected"]
    temporal = doc.get("temporal_evidence") or doc.get("global_temporal_evidence") or {}
    confirmed = temporal.get("confirmed_sample_count") or 0
    checks = {
        "target_presence_correct": (confirmed > 0) == bool(expected.get("target_present")),
        "confirmed_sample_count": confirmed,
    }
    transitions = temporal.get("state_transitions") or []
    covered = []
    widths = []
    for gt_transition in expected.get("transitions_ground_truth", []):
        at_ms = gt_transition["at_ms"]
        hits = [t for t in transitions if t["left_ms"] <= at_ms <= t["right_ms"]]
        covered.append({
            "gt_at_ms": at_ms,
            "gt_from": gt_transition["from"],
            "gt_to": gt_transition["to"],
            "covered": bool(hits),
            "observed": [{"left_ms": t["left_ms"], "right_ms": t["right_ms"],
                          "from_class": t["from_class"], "to_class": t["to_class"],
                          "uncertainty_width_ms": t["uncertainty_width_ms"]}
                         for t in hits],
        })
        widths.extend(t["uncertainty_width_ms"] for t in hits)
    checks["gt_transitions_total"] = len(expected.get("transitions_ground_truth", []))
    checks["gt_transitions_covered"] = sum(1 for c in covered if c["covered"])
    checks["gt_transition_details"] = covered
    if widths:
        checks["gt_boundary_max_width_ms"] = max(widths)
    return checks


def load_arm_from_artifacts(out_dir):
    """从已保存产物加载一个对照臂（不调用模型）。"""
    doc = json.load(open(os.path.join(out_dir, "temporal-evidence.json"), encoding="utf-8"))
    report = json.load(open(os.path.join(out_dir, "temporal-report.json"), encoding="utf-8"))
    provenance = doc.get("sampling_provenance") or doc.get("shared_budget") or {}
    total_ms = (provenance.get("timing") or {}).get("total_ms")
    elapsed_s = round(total_ms / 1000.0, 3) if isinstance(total_ms, (int, float)) else None
    return doc, report, elapsed_s


def rebuild_from_artifacts(args):
    """不重新调用模型：用同一指标/Verdict 代码路径从已存产物重建对照。"""
    manifest, gt = load_fixtures()
    comparison = {
        "task": "task-16-uniform-vs-adaptive-comparison",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "input_nature": "real_qwen_model_output_on_synthetic_technical_fixture",
        "rebuild_note": ("本文件由 --from-artifacts 从已保存的真实运行产物重建"
                         "（未重新调用任何模型；wall_time_s 取产物内 pipeline total_ms）"),
        "fairness": {
            "same_video": True,
            "same_target_query": TARGET_QUERY,
            "same_model": "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest（本地 Ollama）",
            "same_resource_window": "真实运行见 artifacts/task-16/resource-gate.json",
            "same_status_rules": "同一 trace_temporal.py 代码路径与 frame_class 分类规则",
            "same_max_model_calls": args.budget,
            "exception": ("BUDGET_SCENARIOS 中的 reappear-adaptive-budget-6 为显式的"
                          "“更少调用”预算耗尽场景，不参与同预算主对照"),
            "same_timeout_s": args.timeout,
            "no_single_side_retry": True,
            "no_sample_removal": True,
            "ground_truth_not_modified_after_results": True,
            "tier3_untouched": True,
        },
        "fixture_manifest_sha256_verified": True,
        "scenarios": {},
        "verdict_inputs": {},
    }
    for fixture_id in COMPARISON_FIXTURES:
        fixture = gt["fixtures"][fixture_id]
        scenario = {"fixture": fixture_id, "video": fixture["file"],
                    "purpose": fixture["purpose"], "budget": args.budget, "arms": {}}
        for arm in ("uniform", "adaptive"):
            out_dir = os.path.join(args.out, "comparison", fixture_id, arm)
            doc, report, elapsed = load_arm_from_artifacts(out_dir)
            metrics = metrics_from(doc, report, elapsed)
            metrics["ground_truth_checks"] = gt_checks(fixture, doc)
            scenario["arms"][arm] = {
                "artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                "metrics": metrics,
            }
        comparison["scenarios"][f"same-budget-{fixture_id}"] = scenario
    for scenario_def in BUDGET_SCENARIOS:
        fixture = gt["fixtures"][scenario_def["fixture"]]
        out_dir = os.path.join(args.out, "comparison", scenario_def["id"], "adaptive")
        doc, report, elapsed = load_arm_from_artifacts(out_dir)
        metrics = metrics_from(doc, report, elapsed)
        metrics["ground_truth_checks"] = gt_checks(fixture, doc)
        comparison["scenarios"][scenario_def["id"]] = {
            "fixture": scenario_def["fixture"], "purpose": scenario_def["purpose"],
            "budget": scenario_def["max_model_calls"],
            "arms": {"adaptive": {"artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                                  "metrics": metrics}},
        }
    ms = MULTI_SOURCE_SCENARIO
    out_dir = os.path.join(args.out, "comparison", ms["id"], "adaptive")
    doc, report, elapsed = load_arm_from_artifacts(out_dir)
    metrics = metrics_from(doc, report, elapsed)
    comparison["scenarios"][ms["id"]] = {
        "fixture": [s["fixture"] for s in ms["sources"]], "purpose": ms["purpose"],
        "budget": ms["max_model_calls"],
        "arms": {"adaptive": {"artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                              "metrics": metrics}},
    }
    verdict = compute_verdict(comparison)
    comparison["verdict"] = verdict
    with open(os.path.join(args.out, "comparison.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
    write_comparison_md(os.path.join(args.out, "comparison.md"), comparison)
    print(f"[Verdict] {verdict['verdict']} — {verdict['reason']}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="任务 16 uniform vs adaptive 对照")
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "artifacts", "task-16"),
                        help="artifacts/task-16 目录")
    parser.add_argument("--budget", type=int, default=12, help="相同最大调用预算（默认 12）")
    parser.add_argument("--precision-ms", type=float, default=500,
                        help="adaptive 目标时间边界精度（毫秒，默认 500）")
    parser.add_argument("--timeout", type=int, default=300, help="单帧调用超时秒数")
    parser.add_argument("--from-artifacts", action="store_true",
                        help="不重新调用模型：从已保存的 comparison/<scenario>/<arm>/ 产物"
                             "重建 comparison.json/md（指标与 Verdict 用同一代码路径复算）")
    args = parser.parse_args()

    # 0) fixture 冻结复核（评测前必须通过）
    verify = subprocess.run([sys.executable, FIXTURE_GENERATOR, "--verify"],
                            capture_output=True, text=True)
    if verify.returncode != 0:
        print(verify.stderr, file=sys.stderr)
        return 1
    print(f"[fixture 冻结复核] {verify.stdout.strip()}")

    if args.from_artifacts:
        return rebuild_from_artifacts(args)

    # 1) 资源门槛
    gate = resource_snapshot()
    print(f"[资源门槛] {json.dumps(gate, ensure_ascii=False)}")
    if not gate["mem_gate_passed"] or not gate["ollama_reachable"]:
        blocked = {
            "task": "task-16-comparison",
            "status": "resource_blocked",
            "resource_gate": gate,
            "note": ("资源门槛不满足（MemAvailable 连续三次采样需 ≥45 GiB 且 Ollama 可达）；"
                     "未执行任何真实 Qwen 调用；规则测试结果不受影响。"),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "comparison.json"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(blocked, ensure_ascii=False, indent=2) + "\n")
        return 1

    manifest, gt = load_fixtures()
    comparison = {
        "task": "task-16-uniform-vs-adaptive-comparison",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "input_nature": "real_qwen_model_output_on_synthetic_technical_fixture",
        "fairness": {
            "same_video": True,
            "same_target_query": TARGET_QUERY,
            "same_model": "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest（本地 Ollama）",
            "same_resource_window": gate,
            "same_status_rules": "同一 trace_temporal.py 代码路径与 frame_class 分类规则",
            "same_max_model_calls": args.budget,
            "exception": ("BUDGET_SCENARIOS 中的 reappear-adaptive-budget-6 为显式的"
                          "“更少调用”预算耗尽场景，不参与同预算主对照"),
            "same_timeout_s": args.timeout,
            "no_single_side_retry": True,
            "no_sample_removal": True,
            "ground_truth_not_modified_after_results": True,
            "tier3_untouched": True,
        },
        "fixture_manifest_sha256_verified": True,
        "scenarios": {},
        "verdict_inputs": {},
    }

    # 2) 主对照：每个 fixture 两臂同预算
    for fixture_id in COMPARISON_FIXTURES:
        fixture = gt["fixtures"][fixture_id]
        video = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures", "videos",
                             fixture["file"])
        scenario = {"fixture": fixture_id, "video": fixture["file"],
                    "purpose": fixture["purpose"], "budget": args.budget, "arms": {}}
        for arm in ("uniform", "adaptive"):
            spec = base_spec(f"task16-cmp-{fixture_id}-{arm}", video)
            if arm == "adaptive":
                spec["sampling_strategy"] = {
                    "strategy": "adaptive_coarse_to_fine",
                    "max_model_calls": args.budget,
                    "initial_coverage_samples": 4,
                    "target_boundary_precision_ms": args.precision_ms,
                    "max_refinement_rounds": 6,
                }
            else:
                spec["sampling_strategy"] = {"strategy": "uniform",
                                             "max_model_calls": args.budget}
            out_dir = os.path.join(args.out, "comparison", fixture_id, arm)
            doc, report, elapsed = run_arm(spec, out_dir, arm, args.budget,
                                           args.precision_ms, args.timeout,
                                           "technical_fixture")
            metrics = metrics_from(doc, report, elapsed)
            metrics["ground_truth_checks"] = gt_checks(fixture, doc)
            scenario["arms"][arm] = {
                "artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                "metrics": metrics,
            }
            print(f"[{fixture_id}/{arm}] 状态={metrics['final_status']} "
                  f"调用={metrics['actual_model_calls']}/{args.budget} "
                  f"转换={metrics['state_transition_count']} "
                  f"最大边界宽度={metrics['max_uncertainty_width_ms']} "
                  f"耗时={metrics['wall_time_s']}s")
        comparison["scenarios"][f"same-budget-{fixture_id}"] = scenario

    # 3) 预算耗尽场景（显式更少预算）
    for scenario_def in BUDGET_SCENARIOS:
        fixture = gt["fixtures"][scenario_def["fixture"]]
        video = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures", "videos",
                             fixture["file"])
        spec = base_spec(f"task16-cmp-{scenario_def['id']}", video)
        spec["sampling_strategy"] = {
            "strategy": "adaptive_coarse_to_fine",
            "max_model_calls": scenario_def["max_model_calls"],
            "initial_coverage_samples": 4,
            "target_boundary_precision_ms": args.precision_ms,
            "max_refinement_rounds": 6,
        }
        out_dir = os.path.join(args.out, "comparison", scenario_def["id"], "adaptive")
        doc, report, elapsed = run_arm(spec, out_dir, "adaptive",
                                       scenario_def["max_model_calls"], args.precision_ms,
                                       args.timeout, "technical_fixture")
        metrics = metrics_from(doc, report, elapsed)
        metrics["ground_truth_checks"] = gt_checks(fixture, doc)
        comparison["scenarios"][scenario_def["id"]] = {
            "fixture": scenario_def["fixture"], "purpose": scenario_def["purpose"],
            "budget": scenario_def["max_model_calls"],
            "arms": {"adaptive": {"artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                                  "metrics": metrics}},
        }
        print(f"[{scenario_def['id']}] 调用={metrics['actual_model_calls']}/"
              f"{scenario_def['max_model_calls']} 耗尽={metrics['budget_exhausted']}")

    # 4) 多来源场景（共享预算）
    ms = MULTI_SOURCE_SCENARIO
    sources = []
    for source in ms["sources"]:
        fixture = gt["fixtures"][source["fixture"]]
        sources.append({
            "source_id": source["source_id"],
            "path": os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures", "videos",
                                 fixture["file"]),
            "location": f"scene-{source['source_id']}",
            "time_offset_ms": source["time_offset_ms"],
        })
    spec = base_spec(f"task16-cmp-{ms['id']}", sources)
    spec["sampling_strategy"] = {
        "strategy": "adaptive_coarse_to_fine",
        "max_model_calls": ms["max_model_calls"],
        "initial_coverage_samples": 4,
        "target_boundary_precision_ms": args.precision_ms,
        "max_refinement_rounds": 6,
    }
    out_dir = os.path.join(args.out, "comparison", ms["id"], "adaptive")
    doc, report, elapsed = run_arm(spec, out_dir, "adaptive", ms["max_model_calls"],
                                   args.precision_ms, args.timeout, "technical_fixture")
    metrics = metrics_from(doc, report, elapsed)
    comparison["scenarios"][ms["id"]] = {
        "fixture": [s["fixture"] for s in ms["sources"]], "purpose": ms["purpose"],
        "budget": ms["max_model_calls"],
        "arms": {"adaptive": {"artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                              "metrics": metrics}},
    }
    print(f"[{ms['id']}] 全局调用={metrics['actual_model_calls']}/{ms['max_model_calls']}")

    # 5) Verdict 计算（不预设 adaptive 必须 PASS）
    verdict = compute_verdict(comparison)
    comparison["verdict"] = verdict
    with open(os.path.join(args.out, "comparison.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
    write_comparison_md(os.path.join(args.out, "comparison.md"), comparison)
    print(f"[Verdict] {verdict['verdict']} — {verdict['reason']}")
    return 0


def compute_verdict(comparison):
    """对照 Verdict：基于真实指标逐项比较，不预设结论。

    判定维度（同预算主对照）：
      A. 正确性：两臂 target_presence_correct 是否都成立；
      B. 边界定位：adaptive 的 gt 转换覆盖率与最大边界宽度是否优于 uniform；
      C. 调用效率：adaptive 实际调用是否少于 uniform（相同正确性下）；
      D. 拒答/失败纪律：abstained/failed 是否被正确保留（两臂都不退化为 not_found）。
    Verdict: IMPROVEMENT / PARTIAL / NO_IMPROVEMENT（附逐项证据）。
    """
    items = []
    for key, scenario in comparison["scenarios"].items():
        if not key.startswith("same-budget-"):
            continue
        uniform = scenario["arms"]["uniform"]["metrics"]
        adaptive = scenario["arms"]["adaptive"]["metrics"]
        u_gt = uniform["ground_truth_checks"]
        a_gt = adaptive["ground_truth_checks"]
        items.append({
            "scenario": key,
            "uniform_correct": u_gt["target_presence_correct"],
            "adaptive_correct": a_gt["target_presence_correct"],
            "uniform_calls": uniform["actual_model_calls"],
            "adaptive_calls": adaptive["actual_model_calls"],
            "uniform_gt_covered": u_gt["gt_transitions_covered"],
            "adaptive_gt_covered": a_gt["gt_transitions_covered"],
            "uniform_max_width": u_gt.get("gt_boundary_max_width_ms"),
            "adaptive_max_width": a_gt.get("gt_boundary_max_width_ms"),
            "uniform_precision_reached": uniform["target_precision_reached"],
            "adaptive_precision_reached": adaptive["target_precision_reached"],
        })
    if not items:
        return {"verdict": "NO_DATA", "reason": "没有同预算主对照场景"}
    both_correct = all(i["uniform_correct"] and i["adaptive_correct"] for i in items)
    adaptive_not_worse_correct = all(i["adaptive_correct"] for i in items)
    boundary_better = []
    calls_fewer = []
    for item in items:
        u_w, a_w = item["uniform_max_width"], item["adaptive_max_width"]
        if u_w is not None and a_w is not None:
            boundary_better.append(a_w <= u_w)
        elif item["adaptive_gt_covered"] >= item["uniform_gt_covered"]:
            boundary_better.append(True)
        if item["adaptive_calls"] <= item["uniform_calls"]:
            calls_fewer.append(True)
        else:
            calls_fewer.append(False)
    transitions_scenarios = [i for i in items if i["uniform_gt_covered"] is not None]
    boundary_improved = (all(boundary_better) if boundary_better else False)
    calls_improved = all(calls_fewer) if calls_fewer else False
    precision_hits = sum(1 for i in items if i["adaptive_precision_reached"] is True)
    if both_correct and boundary_improved and (calls_improved or precision_hits > 0):
        verdict = "IMPROVEMENT"
        reason = (f"同预算主对照 {len(items)} 个场景：两臂最终状态均正确；"
                  f"adaptive 边界定位不劣于 uniform（最大边界宽度均不高于 uniform），"
                  f"且调用数不高于 uniform 或达到目标边界精度；"
                  f"详细逐项数据见 scenarios")
    elif adaptive_not_worse_correct and (boundary_improved or calls_improved):
        verdict = "PARTIAL"
        reason = (f"同预算主对照 {len(items)} 个场景：adaptive 正确性保持，"
                  f"部分维度改善（边界或调用），但不满足全部改善条件")
    else:
        verdict = "NO_IMPROVEMENT"
        reason = (f"同预算主对照 {len(items)} 个场景：adaptive 未证明相对 uniform 的改善"
                  f"（正确性/边界/调用逐项见 scenarios）；如实记录，不伪造提升")
    return {
        "verdict": verdict,
        "reason": reason,
        "scenarios_compared": len(items),
        "both_arms_correct_all": both_correct,
        "adaptive_boundary_not_worse_all": boundary_improved,
        "adaptive_calls_not_more_all": calls_improved,
        "adaptive_precision_reached_count": precision_hits,
        "small_sample_caveat": ("技术 fixture 小样本；结果不得外推为真实仓储准确率；"
                                "单次运行，Agent/模型行为非确定性"),
        "items": items,
    }


def write_comparison_md(path, comparison):
    lines = [
        "# 任务 16 uniform vs adaptive 对照（technical fixture，真实 Qwen 调用）",
        "",
        f"- 生成时间：{comparison['generated_at']}",
        f"- 输入性质：{comparison['input_nature']}",
        "- **本对照使用合成技术 fixture，不是真实行业视频；结果不得外推为真实仓储准确率。**",
        "",
        "## 公平性",
        "",
    ]
    for key, value in comparison["fairness"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## 逐场景结果", ""]
    for key, scenario in comparison["scenarios"].items():
        lines.append(f"### {key}")
        lines.append("")
        lines.append(f"- fixture: {scenario.get('fixture')}；预算: {scenario.get('budget')}")
        lines.append(f"- 目的: {scenario.get('purpose')}")
        lines.append("")
        lines.append("| 指标 | uniform | adaptive |")
        lines.append("| --- | --- | --- |")
        arms = scenario["arms"]
        uniform = arms.get("uniform", {}).get("metrics", {})
        adaptive = arms.get("adaptive", {}).get("metrics", {})
        rows = [
            ("最终状态", "final_status"),
            ("首次 confirmed 采样(ms)", "first_confirmed_observed_ms"),
            ("最后 confirmed 采样(ms)", "last_confirmed_observed_ms"),
            ("confirmed 采样数", "confirmed_sample_count"),
            ("状态转换数", "state_transition_count"),
            ("最大边界不确定宽度(ms)", "max_uncertainty_width_ms"),
            ("达到目标边界精度", "target_precision_reached"),
            ("实际 Qwen 调用数", "actual_model_calls"),
            ("配置预算", "configured_budget"),
            ("耗尽预算", "budget_exhausted"),
            ("总耗时(s)", "wall_time_s"),
            ("单次调用耗时(ms)", "per_call_ms"),
            ("abstained 数", None),
            ("failed 数", None),
            ("证据性质", "evidence_nature"),
        ]
        for label, field in rows:
            if field is None:
                if label.startswith("abstained"):
                    u_value = (uniform.get("class_counts") or {}).get("abstained")
                    a_value = (adaptive.get("class_counts") or {}).get("abstained")
                else:
                    u_value = (uniform.get("class_counts") or {}).get("failed")
                    a_value = (adaptive.get("class_counts") or {}).get("failed")
            else:
                u_value = uniform.get(field)
                a_value = adaptive.get(field)
            lines.append(f"| {label} | {u_value} | {a_value} |")
        for arm in ("uniform", "adaptive"):
            gt_checks = arms.get(arm, {}).get("metrics", {}).get("ground_truth_checks")
            if gt_checks:
                lines.append(f"- {arm} ground truth 检查：存在性正确="
                             f"{gt_checks['target_presence_correct']}，"
                             f"GT 转换覆盖 {gt_checks['gt_transitions_covered']}/"
                             f"{gt_checks['gt_transitions_total']}")
        lines.append("")
    verdict = comparison.get("verdict") or {}
    lines += [
        "## Verdict",
        "",
        f"**{verdict.get('verdict')}** — {verdict.get('reason')}",
        "",
        f"- 小样本声明：{verdict.get('small_sample_caveat')}",
        "",
    ]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
