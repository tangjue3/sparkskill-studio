#!/usr/bin/env python3
"""test_task21_replay.py — Task 21 固定采样时序重放确定性测试（SparkSkill Studio 任务 21）

全部为确定性测试（零模型调用、零网络、CPU-only）:
  T1  256 点 ↔ 27 运行映射完整（每臂 121/51/84；时间戳序列与 Task 19B 逐项相等）
  T2  每版 27/27 运行、256 点（重放产物结构）
  T3  七类账 256/256（v1/v2；与 paired-rows.json 独立复算一致）
  T4  时间戳排序（每 arm 状态序列严格升序）
  T5  失败点保留（T20-P0152 v2 = failed；不得改写为拒答；failed_on_uncertain=1）
  T6  边界方向兼容（冻结 direction_compatible 行为锚点 + 重放零匹配的一致性）
  T7  无 GT 边界样本 not_applicable（AI01/AI05/AI06/WEB02/WEB03；误差统计全 not_applicable）
  T8  八个不同边界与三臂重复暴露的分母区分（8 ≠ 24；矩阵 8 行/版）
  T9  跨臂同帧不同输出不被去重覆盖（AI06 t=10083.333 v1、t=0 v2 各臂保持自身输出）
  T10 输入 JSON 零写入与结果确定性（两次子进程运行逐字节相同；输入哈希不变）
  T11 正式评分阻塞实证（诚实 provenance 全被 G7 拒 → REPLAY_UNSCORABLE；
      伪造 fresh_call 后 uniform/adaptive 可通过——唯一差别即伪造，明令禁止）
  T12 冻结代码零改动（scorer/sampler/adapter/analyze_image 哈希与 frozen-hashes.json 一致）
      与输出安全（重放产物不含绝对用户路径/墙钟字段）

用法: python3 scripts/test_task21_replay.py
退出码: 0 = 全部通过; 1 = 有失败
"""
import glob
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REPLAY_SCRIPT = os.path.join(PROJECT_ROOT, "scripts", "run_task21_replay.py")
REPLAY_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-21", "replay")
SCORER_PATH = os.path.join(PROJECT_ROOT, "scripts", "score_temporal_ground_truth.py")
FROZEN_HASHES = os.path.join(PROJECT_ROOT, "artifacts", "task-20", "preregistration",
                             "frozen-hashes.json")
POINTS_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-20", "pairs", "points")
GT_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ground-truth")
NO_BOUNDARY_SAMPLES = {"AI01", "AI05", "AI06", "WEB02", "WEB03"}
BOUNDARY_SAMPLES = {"AI02": 2, "AI03": 2, "AI04": 2, "WEB01": 2}
ARMS = ("uniform", "adaptive", "coverage")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def check_prerequisites():
    """公开版前置检查：本测试的多数用例读取任务 21 的内部摄验/评分产物，
    这些内容不随公开仓库分发（见 docs/PUBLIC-VERSION-NOTES.md）。缺失时不伪报
    PASS，明确退出（exit 2）并打印 NOT_RUN 原因；备齐后行为不变。"""
    missing = [rel for rel in ['artifacts/task-19/ground-truth', 'artifacts/task-20/pairs', 'artifacts/task-21/replay']
               if not os.path.exists(os.path.join(PROJECT_ROOT, rel))]
    if missing:
        print("[NOT_RUN] 本测试的前置产物不在公开仓库中：")
        for rel in missing:
            print(f"  - 缺失: {rel}")
        print("说明：上述内容为内部留档（媒体授权与开发机路径原因，不随公开仓库分发）。")
        return False
    return True


def main():
    if not check_prerequisites():
        return 2
    scorer = load_module("score_temporal_ground_truth", SCORER_PATH)
    results = []

    def check(test_id, name, passed, detail):
        results.append({"id": test_id, "name": name, "passed": bool(passed),
                        "detail": detail})
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {test_id} {name} — {detail}")

    # ---- 输入加载
    point_paths = sorted(glob.glob(os.path.join(POINTS_DIR, "T20-P*.json")))
    points = [load_json(path) for path in point_paths]
    ground_truths = {name: load_json(os.path.join(GT_DIR, f"{name}.json"))
                     for name in sorted(NO_BOUNDARY_SAMPLES | set(BOUNDARY_SAMPLES))}
    doc = load_json(os.path.join(REPLAY_DIR, "replay-results.json"))
    runs = doc["runs"]

    # T1 映射完整
    groups = {}
    for point in points:
        groups.setdefault((point["sample_id"], point["arm"]), []).append(point)
    arm_totals = {arm: 0 for arm in ARMS}
    sequences_ok = True
    for (sample_id, arm), group in groups.items():
        arm_totals[arm] += len(group)
        evidence = load_json(os.path.join(
            PROJECT_ROOT, "artifacts", "task-19", "predictions", sample_id, arm,
            "temporal-evidence.json"))
        expected = sorted(round(entry["timestamp_ms"], 3) for entry in evidence["timeline"])
        actual = sorted(round(p["timestamp_ms"], 3) for p in group)
        if expected != actual:
            sequences_ok = False
    mapping_ok = (len(points) == 256 and len(groups) == 27
                  and arm_totals == {"uniform": 121, "adaptive": 51, "coverage": 84}
                  and sequences_ok and not doc["mapping_verification"]["problems"])
    check("T1", "256 点 ↔ 27 运行映射完整", mapping_ok,
          f"points={len(points)} groups={len(groups)} arm_totals={arm_totals} "
          f"sequences_identical={sequences_ok}")

    # T2 每版 27 运行 / 256 点
    per_version_ok = True
    for version in ("v1", "v2"):
        selected = [run for run in runs if run["version"] == version]
        if len(selected) != 27 or sum(run["point_count"] for run in selected) != 256:
            per_version_ok = False
        arms = {}
        for run in selected:
            arms.setdefault(run["arm"], 0)
            arms[run["arm"]] += run["point_count"]
        if arms != {"uniform": 121, "adaptive": 51, "coverage": 84}:
            per_version_ok = False
    check("T2", "每版 27/27 运行、256 点、各臂 121/51/84", per_version_ok,
          f"runs={len(runs)} (2 版本 × 27)")

    # T3 七类账 256/256，与 paired-rows 独立复算一致
    paired_rows = load_json(os.path.join(
        PROJECT_ROOT, "artifacts", "task-20", "scores", "paired-rows.json"))
    ledger_ok = True
    detail = {}
    for version in ("v1", "v2"):
        recount = {name: 0 for name in scorer.SEVEN_METRICS}
        for row in paired_rows:
            metric = row[f"{version}_metric"]
            if metric in recount:
                recount[metric] += 1
        replay_counts = doc["summary"][version]["seven_metrics"]
        if sum(recount.values()) != 256 or recount != replay_counts:
            ledger_ok = False
        detail[version] = {"sum": sum(recount.values()),
                           "matches_replay": recount == replay_counts}
    check("T3", "七类账 256/256（v1/v2，与 paired-rows 复算一致）", ledger_ok,
          json.dumps(detail, ensure_ascii=False))

    # T4 时间戳排序
    ordering_ok = True
    for run in runs:
        stamps = [item["timestamp_ms"] for item in run["status_sequence"]]
        if stamps != sorted(stamps) or len(set(stamps)) != len(stamps):
            ordering_ok = False
    check("T4", "每 arm 状态序列时间戳严格升序且无重复", ordering_ok,
          f"checked={len(runs)} runs")

    # T5 失败点保留
    target = [run for run in runs if run["version"] == "v2" and run["sample_id"] == "AI06"
              and run["arm"] == "adaptive"][0]
    failed_entries = [item for item in target["status_sequence"] if item["class"] == "failed"]
    failed_ok = (failed_entries and failed_entries[0]["point_id"] == "T20-P0152"
                 and target["failed_points"] == ["T20-P0152"]
                 and target["sample_point_scores"]["metrics"]["failed_on_uncertain"]["passed"] == 1
                 and target["sample_point_scores"]["metrics"]["appropriate_abstention"]["passed"]
                 == target["class_counts"]["abstained"])
    check("T5", "失败点保持 failed（不得改写为拒答）", failed_ok,
          f"failed_points={target['failed_points']} "
          f"failed_on_uncertain={target['sample_point_scores']['metrics']['failed_on_uncertain']['passed']}")

    # T6 边界方向兼容锚点 + 重放零匹配一致
    dc = scorer.direction_compatible
    anchors = (dc("uncertain", "abstained") is True and dc("uncertain", "low_confidence") is True
               and dc("uncertain", "failed") is True and dc("uncertain", "confirmed") is False
               and dc("uncertain", "not_found") is False
               and dc("confirmed", "confirmed") is True and dc("confirmed", "not_found") is False
               and dc("not_found", "not_found") is True)
    zero_match_consistent = True
    for run in runs:
        for boundary in run["boundary_scores"]["gt_boundaries"]:
            for transition in run["state_transitions"]:
                bracketed = (transition["left_ms"] <= boundary["at_ms"]
                             <= transition["right_ms"])
                compatible = (dc(boundary["from_state"], transition["from_class"])
                              and dc(boundary["to_state"], transition["to_class"]))
                if bracketed and compatible:
                    zero_match_consistent = False
    all_zero = all(run["boundary_scores"]["matched_boundaries"] == 0 for run in runs)
    check("T6", "边界方向兼容锚点 + 重放零匹配一致", anchors and zero_match_consistent
          and all_zero, f"anchors={anchors} no_compatible_bracket={zero_match_consistent} "
          f"all_matched_zero={all_zero}")

    # T7 无 GT 边界样本 not_applicable
    t7_ok = True
    for run in runs:
        if run["sample_id"] in NO_BOUNDARY_SAMPLES:
            b = run["boundary_scores"]
            if (b["gt_boundaries_total"] != 0 or b["matched_boundaries"] != 0
                    or b["boundary_error_stats"]["matched_count"] != 0
                    or b["boundary_error_stats"]["max_ms"] != "not_applicable"):
                t7_ok = False
    exposures = sum(run["boundary_scores"]["gt_boundaries_total"] for run in runs
                    if run["version"] == "v1")
    check("T7", "无 GT 边界样本分母 0 → not_applicable", t7_ok and exposures == 24,
          f"no_boundary_samples={sorted(NO_BOUNDARY_SAMPLES)} v1_exposures={exposures}")

    # T8 八个不同边界 vs 24 次暴露
    matrix = doc["summary"]["v1"]["boundary_matrix"]
    distinct = {(row["sample_id"], row["at_ms"]) for row in matrix}
    exposures_total = doc["summary"]["v1"]["gt_boundary_exposures_total"]
    matched_exposures = doc["summary"]["v1"]["matched_boundary_exposures"]
    check("T8", "8 个不同边界与 24 次暴露分母区分", len(distinct) == 8
          and exposures_total == 24 and matched_exposures == 0,
          f"distinct={len(distinct)} exposures={exposures_total} "
          f"matched={matched_exposures} (24 ≠ 8：三臂重复暴露)")

    # T9 跨臂同帧不同输出不被去重覆盖
    def arm_class(sample_id, arm, timestamp_ms, version):
        for run in runs:
            if (run["version"] == version and run["sample_id"] == sample_id
                    and run["arm"] == arm):
                for item in run["status_sequence"]:
                    if item["timestamp_ms"] == timestamp_ms:
                        return item["class"]
        return None
    frame_a = {arm: arm_class("AI06", arm, 10083.333, "v1") for arm in ARMS}
    frame_b = {arm: arm_class("AI06", arm, 0.0, "v2") for arm in ARMS}
    t9_ok = (len(set(frame_a.values())) > 1 and len(set(frame_b.values())) > 1
             and frame_a == {"uniform": "confirmed", "adaptive": "confirmed",
                             "coverage": "abstained"}
             and frame_b == {"uniform": "not_found", "adaptive": "not_found",
                             "coverage": "abstained"})
    check("T9", "跨臂同帧不同输出保持各臂自身结果（不去重代表行）", t9_ok,
          f"AI06 t=10083.333 v1={frame_a}；AI06 t=0 v2={frame_b}")

    # T10 输入零写入 + 确定性（子进程两次运行）
    input_files = point_paths + sorted(glob.glob(os.path.join(GT_DIR, "*.json")))
    before = {path: sha256_of(path) for path in input_files}
    outputs = []
    for _ in range(2):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, REPLAY_SCRIPT, "--out", os.path.join(tmp, "replay")],
                capture_output=True, text=True)
            if proc.returncode != 0:
                outputs.append(None)
                continue
            with open(os.path.join(tmp, "replay", "replay-results.json"), "rb") as handle:
                outputs.append(handle.read())
    after = {path: sha256_of(path) for path in input_files}
    t10_ok = (outputs[0] is not None and outputs[0] == outputs[1] and before == after)
    check("T10", "输入 JSON 零写入 + 两次运行逐字节确定", t10_ok,
          f"inputs_unchanged={before == after} deterministic={outputs[0] == outputs[1]}")

    # T11 正式评分阻塞实证
    sa = doc["scoreability"]
    t11_ok = (sa["honest_variant_all_g7_failed"] is True
              and sa["fabricated_uniform_adaptive_g7_passed"] is True
              and doc["formal_scoring_status"] == "REPLAY_UNSCORABLE")
    check("T11", "冻结 G7 阻塞实证 → REPLAY_UNSCORABLE", t11_ok,
          f"honest_all_failed={sa['honest_variant_all_g7_failed']} "
          f"fabricated_uniform_adaptive_passed={sa['fabricated_uniform_adaptive_g7_passed']} "
          f"formal={doc['formal_scoring_status']}")

    # T12 冻结代码零改动 + 输出安全
    frozen = load_json(FROZEN_HASHES)["entries"]
    t21_inputs = {entry["path"]: entry["sha256"] for entry in load_json(os.path.join(
        PROJECT_ROOT, "artifacts", "task-21", "plan", "input-hashes.json"))["entries"]}
    code_paths = ["scripts/score_temporal_ground_truth.py",
                  ".dsh/skills/visual-evidence-extractor/scripts/analyze_image.py"]
    code_ok = all(sha256_of(os.path.join(PROJECT_ROOT, p)) == frozen[p]["sha256"]
                  for p in code_paths)
    adapter_path = os.path.join(PROJECT_ROOT, "scripts", "task18_scorer_adapter.py")
    adapter_ok = sha256_of(adapter_path) == frozen["scripts/task18_scorer_adapter.py"]["sha256"]
    sampler_path = os.path.join(PROJECT_ROOT,
                                ".dsh/skills/visual-evidence-extractor/scripts",
                                "adaptive_sampler.py")
    sampler_rel = ".dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py"
    sampler_ok = sha256_of(sampler_path) == t21_inputs[sampler_rel]
    blob = open(os.path.join(REPLAY_DIR, "replay-results.json"), encoding="utf-8").read()
    safe_ok = ("/home/" not in blob and "generated_at" not in blob)
    check("T12", "冻结代码零改动 + 重放产物无绝对路径/墙钟字段",
          code_ok and adapter_ok and sampler_ok and safe_ok,
          f"scorer/analyze_image={code_ok} adapter={adapter_ok} sampler={sampler_ok} "
          f"output_safe={safe_ok}")

    passed = sum(1 for item in results if item["passed"])
    total = len(results)
    print(f"\nTask 21 重放测试: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
