#!/usr/bin/env python3
"""test_temporal_ground_truth_scoring.py — 任务 17 评分器测试（SparkSkill Studio）

覆盖任务书第十五节要求的 30 类用例（fixtures 由
artifacts/task-17/fixtures/build_fixtures.py 确定性生成），另加：

  X1 评分器分类规则与 adaptive_sampler.classify_entry 在全部冻结 Task 16
     时间线上一致（运行期独立、规则不漂移）；
  X2 确定性：同一输入两次运行，输出逐字节相同；
  X3 输入只读：评分运行前后全部输入文件哈希不变；
  X4 输出卫生：输出不含绝对用户路径与凭据样式内容。

测试断言具体字段与具体计数（不止断言退出码）。无任何模型调用。

用法:
    python3 scripts/test_temporal_ground_truth_scoring.py [--results-json <path>]
退出码: 0 = 全部通过; 1 = 存在失败项
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FIXTURES_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-17", "fixtures")
SCORER = os.path.join(PROJECT_ROOT, "scripts", "score_temporal_ground_truth.py")
VALIDATOR = os.path.join(PROJECT_ROOT, "scripts", "validate_evidence_pack.py")
EXTRACTOR_SCRIPTS = os.path.join(PROJECT_ROOT, ".dsh", "skills",
                                 "visual-evidence-extractor", "scripts")
TASK16_COMPARISON = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "comparison")

CREDENTIAL_MARKERS = ("api_key", "api-key", "secret", "token", "password", "passwd",
                      "bearer ", "private_key", "-----begin")
SENSITIVE_PATHS = ("/home/", "/root/", "/etc/")

RESULTS = []


def record(test_id, name, passed, detail):
    RESULTS.append({"id": test_id, "name": name, "passed": bool(passed),
                    "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {test_id} — {name}: {detail}")


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def get_path(doc, dotted):
    node = doc
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return None, False
        node = node[key]
    return node, True


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_inputs(case_dir):
    hashes = {}
    for root, _, files in os.walk(case_dir):
        for name in sorted(files):
            path = os.path.join(root, name)
            hashes[os.path.relpath(path, case_dir)] = sha256_of(path)
    return hashes


def run_command(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


# ---------------------------------------------------------------- 断言

def check_expectations(expect, score_doc=None, comparison_doc=None, proc=None):
    """按 expected.json 断言；返回 (passed, detail)。"""
    failures = []

    if "exit_code" in expect and proc is not None:
        if proc.returncode != expect["exit_code"]:
            failures.append(f"exit_code 期望 {expect['exit_code']}，得到 {proc.returncode}"
                            f"（stderr: {proc.stderr[-300:]}）")
    for text in expect.get("stderr_contains", []):
        if proc is None or text not in (proc.stderr or ""):
            failures.append(f"stderr 缺少 {text!r}")
    if "semantic_score_status" in expect and score_doc is not None:
        actual = score_doc.get("semantic_score_status")
        if actual != expect["semantic_score_status"]:
            failures.append(f"semantic_score_status 期望 "
                            f"{expect['semantic_score_status']}，得到 {actual}")
    if "execution_status" in expect and score_doc is not None:
        actual = score_doc.get("execution_status")
        if actual != expect["execution_status"]:
            failures.append(f"execution_status 期望 {expect['execution_status']}，"
                            f"得到 {actual}")
    if "hard_gate_failed" in expect and score_doc is not None:
        gate = next((item for item in score_doc["validation"]["hard_gates"]
                     if item["id"] == expect["hard_gate_failed"]), None)
        if gate is None or gate["passed"]:
            failures.append(f"硬门 {expect['hard_gate_failed']} 应为失败")
    if "error_code" in expect and score_doc is not None:
        errors = score_doc["validation"]["errors"]
        if not errors or errors[0]["code"] != expect["error_code"]:
            failures.append(f"errors[0].code 期望 {expect['error_code']}，"
                            f"得到 {errors[0]['code'] if errors else '<空>'}")
    for section, expected_metrics in expect.get("metrics", {}).items():
        if score_doc is None:
            failures.append(f"metrics.{section}: score_doc 缺失")
            continue
        actual = (score_doc.get("sample_point_scores") or {}).get("metrics", {}).get(section)
        if actual is None:
            failures.append(f"metrics.{section} 缺失")
            continue
        for key, value in expected_metrics.items():
            if actual.get(key) != value:
                failures.append(f"metrics.{section}.{key} 期望 {value}，得到 {actual.get(key)}")
    if expect.get("metrics_all_zero"):
        points = (score_doc or {}).get("sample_point_scores")
        if not points:
            failures.append("metrics_all_zero: sample_point_scores 缺失")
        else:
            for name, metric in points["metrics"].items():
                if metric["passed"] != 0:
                    failures.append(f"metrics.{name}.passed 期望 0，得到 {metric['passed']}")
    for section, expected_values in expect.get("events", {}).items():
        if score_doc is None:
            failures.append(f"events.{section}: score_doc 缺失")
            continue
        actual = (score_doc.get("event_scores") or {}).get(section)
        if actual != expected_values:
            failures.append(f"events.{section} 期望 {expected_values}，得到 {actual}")
    for section, expected_values in expect.get("boundaries", {}).items():
        if score_doc is None:
            failures.append(f"boundaries.{section}: score_doc 缺失")
            continue
        actual = (score_doc.get("boundary_scores") or {}).get(section)
        if isinstance(expected_values, dict) and isinstance(actual, dict):
            # 字典期望按子集比较（actual 可含更多键，如误差统计的 min/median）
            for key, value in expected_values.items():
                if actual.get(key) != value:
                    failures.append(f"boundaries.{section}.{key} 期望 {value}，"
                                    f"得到 {actual.get(key)}")
        elif actual != expected_values:
            failures.append(f"boundaries.{section} 期望 {expected_values}，得到 {actual}")
    for section, expected_values in expect.get("efficiency", {}).items():
        if score_doc is None:
            failures.append(f"efficiency.{section}: score_doc 缺失")
            continue
        actual = (score_doc.get("efficiency") or {}).get(section)
        if actual != expected_values:
            failures.append(f"efficiency.{section} 期望 {expected_values}，得到 {actual}")
    for dotted in expect.get("not_applicable_fields", []):
        doc = score_doc if dotted.startswith(("sample_point_scores", "efficiency")) \
            else comparison_doc
        value, found = get_path(doc or {}, dotted)
        if not found or value != "not_applicable":
            failures.append(f"{dotted} 期望 not_applicable，得到 {value!r}（found={found}）")
    if expect.get("holdout_gt_excluded") and score_doc is not None:
        gt = score_doc.get("ground_truth") or {}
        if gt.get("holdout_gt_excluded") is not True or gt.get("included") is not False:
            failures.append("holdout 样本必须标记 holdout_gt_excluded=true 且 included=false")
        for key in expect.get("output_absent_keys", []):
            if key in score_doc:
                failures.append(f"score.json 不得包含 holdout 真值键 {key!r}")
            if key in json.dumps(score_doc.get("ground_truth", {}), ensure_ascii=False):
                failures.append(f"ground_truth 节不得包含 {key!r}")
        for key in expect.get("output_present_keys", []):
            if key not in gt:
                failures.append(f"holdout ground_truth 节缺少 {key!r}")
    if "verdict" in expect and comparison_doc is not None:
        actual = comparison_doc.get("verdict", {}).get("verdict")
        if actual != expect["verdict"]:
            failures.append(f"verdict 期望 {expect['verdict']}，得到 {actual}")
    if "strict_improvements" in expect and comparison_doc is not None:
        actual = comparison_doc.get("verdict", {}).get("strict_improvements")
        if actual != expect["strict_improvements"]:
            failures.append(f"strict_improvements 期望 {expect['strict_improvements']}，"
                            f"得到 {actual}")
    if "regressions" in expect and comparison_doc is not None:
        actual = comparison_doc.get("verdict", {}).get("regressions")
        if actual != expect["regressions"]:
            failures.append(f"regressions 期望 {expect['regressions']}，得到 {actual}")
    if "fairness_failed" in expect and comparison_doc is not None:
        condition = next((item for item in comparison_doc["fairness_gate"]["conditions"]
                          if item["id"] == expect["fairness_failed"]), None)
        if condition is None or condition["passed"]:
            failures.append(f"fairness 条件 {expect['fairness_failed']} 应为失败")
    return (not failures), "; ".join(failures) if failures else "全部断言通过"


# ---------------------------------------------------------------- 用例执行

def run_fixture_case(case_id):
    case_dir = os.path.join(FIXTURES_DIR, case_id)
    expected = load_json(os.path.join(case_dir, "expected.json"))
    expect = expected["expect"]
    mode = expected["mode"]
    out_dir = tempfile.mkdtemp(prefix=f"task17-{case_id}-")
    try:
        if mode == "validate":
            proc = run_command([sys.executable, VALIDATOR,
                                "--manifest", os.path.join(case_dir, "manifest.json")])
            passed, detail = check_expectations(expect, proc=proc)
        elif mode == "cli_missing_gt":
            proc = run_command([sys.executable, SCORER,
                                "--manifest", os.path.join(case_dir, "manifest.json"),
                                "--predictions", os.path.join(case_dir, "prediction-set.json"),
                                "--out", out_dir])
            passed, detail = check_expectations(expect, proc=proc)
        elif mode == "cli":
            proc = run_command([sys.executable, SCORER,
                                "--manifest", os.path.join(case_dir, "manifest.json"),
                                "--predictions", os.path.join(case_dir, "prediction-set.json"),
                                "--ground-truth", os.path.join(case_dir, "ground-truth.json"),
                                "--out", out_dir])
            passed, detail = check_expectations(expect, proc=proc)
        elif mode == "score":
            proc = run_command([sys.executable, SCORER,
                                "--manifest", os.path.join(case_dir, "manifest.json"),
                                "--predictions", os.path.join(case_dir, "prediction-set.json"),
                                "--ground-truth", os.path.join(case_dir, "ground-truth.json"),
                                "--out", out_dir])
            score_doc = None
            if proc.returncode in (0, 1):
                manifest = load_json(os.path.join(case_dir, "manifest.json"))
                prediction_set = load_json(os.path.join(case_dir, "prediction-set.json"))
                arm_id = prediction_set["arms"][0]["arm_id"]
                sample_id = manifest["samples"][0]["sample_id"]
                score_path = os.path.join(out_dir, sample_id, arm_id, "score.json")
                if os.path.isfile(score_path):
                    score_doc = load_json(score_path)
            passed, detail = check_expectations(expect, score_doc=score_doc, proc=proc)
        elif mode == "compare":
            proc = run_command([sys.executable, SCORER,
                                "--manifest", os.path.join(case_dir, "manifest.json"),
                                "--predictions", os.path.join(case_dir, "prediction-set.json"),
                                "--ground-truth", os.path.join(case_dir, "ground-truth.json"),
                                "--out", out_dir,
                                "--comparison", os.path.join(case_dir, "comparison-spec.json")])
            comparison_doc = None
            comparison_path = os.path.join(out_dir, "comparison.json")
            if os.path.isfile(comparison_path):
                comparison_doc = load_json(comparison_path)
            passed, detail = check_expectations(expect, comparison_doc=comparison_doc,
                                                proc=proc)
        else:
            passed, detail = False, f"未知 mode {mode!r}"
        record(case_id, expected.get("name", case_id), passed, detail)
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def test_classifier_agreement():
    """X1：评分器分类规则与 adaptive_sampler.classify_entry 在冻结 Task 16
    时间线上逐条一致（运行期独立实现，规则不漂移）。"""
    scorer = load_module("score_temporal_ground_truth", SCORER)
    adaptive_sampler = load_module("adaptive_sampler",
                                   os.path.join(EXTRACTOR_SCRIPTS, "adaptive_sampler.py"))
    checked = 0
    mismatches = []
    for scenario in sorted(os.listdir(TASK16_COMPARISON)):
        scenario_dir = os.path.join(TASK16_COMPARISON, scenario)
        if not os.path.isdir(scenario_dir):
            continue
        for arm in sorted(os.listdir(scenario_dir)):
            evidence_path = os.path.join(scenario_dir, arm, "temporal-evidence.json")
            if not os.path.isfile(evidence_path):
                continue
            evidence = load_json(evidence_path)
            for entry in evidence.get("timeline", []):
                checked += 1
                mine = scorer.classify_entry(entry)
                theirs = adaptive_sampler.classify_entry(entry)
                if mine != theirs:
                    mismatches.append(f"{scenario}/{arm}@{entry.get('timestamp_ms')}: "
                                      f"{mine} != {theirs}")
    passed = checked > 0 and not mismatches
    record("X1-classifier-agreement", "评分器分类规则与 Task 16 classify_entry 一致",
           passed, f"核对 {checked} 个冻结时间线条目，不一致 {len(mismatches)} 项"
                   + (f"（{mismatches[:3]}）" if mismatches else ""))


def test_determinism():
    """X2：同一输入两次运行，全部输出逐字节相同。"""
    case_dir = os.path.join(FIXTURES_DIR, "t22-improvement-fewer-calls")
    out_a = tempfile.mkdtemp(prefix="task17-det-a-")
    out_b = tempfile.mkdtemp(prefix="task17-det-b-")
    try:
        for out_dir in (out_a, out_b):
            proc = run_command([sys.executable, SCORER,
                                "--manifest", os.path.join(case_dir, "manifest.json"),
                                "--predictions", os.path.join(case_dir, "prediction-set.json"),
                                "--ground-truth", os.path.join(case_dir, "ground-truth.json"),
                                "--out", out_dir,
                                "--comparison", os.path.join(case_dir, "comparison-spec.json")])
            if proc.returncode != 0:
                record("X2-determinism", "评分器确定性（两次运行逐字节相同）", False,
                       f"评分器退出码 {proc.returncode}")
                return
        differences = []
        for root, _, files in os.walk(out_a):
            for name in files:
                path_a = os.path.join(root, name)
                path_b = os.path.join(out_b, os.path.relpath(path_a, out_a))
                if not os.path.isfile(path_b):
                    differences.append(f"缺少 {os.path.relpath(path_a, out_a)}")
                elif sha256_of(path_a) != sha256_of(path_b):
                    differences.append(f"内容不同 {os.path.relpath(path_a, out_a)}")
        passed = not differences
        record("X2-determinism", "评分器确定性（两次运行逐字节相同）", passed,
               "全部输出逐字节一致" if passed else f"差异: {differences[:5]}")
    finally:
        shutil.rmtree(out_a, ignore_errors=True)
        shutil.rmtree(out_b, ignore_errors=True)


def test_inputs_readonly():
    """X3：评分运行前后全部输入文件哈希不变（输入只读）。"""
    case_dir = os.path.join(FIXTURES_DIR, "t22-improvement-fewer-calls")
    before = hash_inputs(case_dir)
    out_dir = tempfile.mkdtemp(prefix="task17-ro-")
    try:
        run_command([sys.executable, SCORER,
                     "--manifest", os.path.join(case_dir, "manifest.json"),
                     "--predictions", os.path.join(case_dir, "prediction-set.json"),
                     "--ground-truth", os.path.join(case_dir, "ground-truth.json"),
                     "--out", out_dir,
                     "--comparison", os.path.join(case_dir, "comparison-spec.json")])
        after = hash_inputs(case_dir)
        passed = before == after
        record("X3-inputs-readonly", "评分器不修改输入文件", passed,
               f"{len(before)} 个输入文件哈希全部不变" if passed else "输入文件被修改")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def test_output_hygiene():
    """X4：输出不含绝对用户路径与凭据样式内容。"""
    case_dir = os.path.join(FIXTURES_DIR, "t01-all-correct")
    out_dir = tempfile.mkdtemp(prefix="task17-hygiene-")
    try:
        run_command([sys.executable, SCORER,
                     "--manifest", os.path.join(case_dir, "manifest.json"),
                     "--predictions", os.path.join(case_dir, "prediction-set.json"),
                     "--ground-truth", os.path.join(case_dir, "ground-truth.json"),
                     "--out", out_dir])
        problems = []
        for root, _, files in os.walk(out_dir):
            for name in files:
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as handle:
                    text = handle.read()
                lowered = text.lower()
                for marker in CREDENTIAL_MARKERS:
                    if marker in lowered:
                        problems.append(f"{name}: 凭据标记 {marker!r}")
                for sensitive in SENSITIVE_PATHS:
                    if sensitive in text:
                        problems.append(f"{name}: 敏感路径 {sensitive!r}")
        passed = not problems
        record("X4-output-hygiene", "输出不含绝对路径/凭据内容", passed,
               "输出卫生检查通过" if passed else f"问题: {problems[:5]}")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="任务 17 评分器测试")
    parser.add_argument("--results-json", default=None, help="测试结果落盘路径")
    args = parser.parse_args()

    case_ids = sorted(name for name in os.listdir(FIXTURES_DIR)
                      if os.path.isdir(os.path.join(FIXTURES_DIR, name)))
    for case_id in case_ids:
        run_fixture_case(case_id)
    test_classifier_agreement()
    test_determinism()
    test_inputs_readonly()
    test_output_hygiene()

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    payload = {
        "suite": "task-17-temporal-ground-truth-scoring",
        "all_passed": passed == total,
        "passed": passed,
        "total": total,
        "tests": RESULTS,
        "notes": "确定性 JSON fixtures（artifacts/task-17/fixtures/）；无任何模型调用；"
                 "断言具体字段与具体计数",
    }
    if args.results_json:
        with open(args.results_json, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        print(f"结果已写入 {args.results_json}")
    print(f"RESULT: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
