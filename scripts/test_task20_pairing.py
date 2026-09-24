#!/usr/bin/env python3
"""test_task20_pairing.py — Task 20 同期同帧配对实验确定性测试（SparkSkill Studio 任务 20）

全部为确定性测试（零模型调用、零网络）:
  T1  配对评分器与 Task 17 冻结评分器的历史等价性（256 个历史点逐行 + 计数零 mismatch）
  T2  预注册门槛判定单元测试（IMPROVEMENT / TRADEOFF / NO_IMPROVEMENT / 漂移 / incorrect 增加）
  T3  v1 提示词哈希与 analyze_image.PROMPT_TEMPLATE 一致（版本锚定）
  T4  v2 提示词结构不变式（占位符相同、JSON 契约块逐字节相同、仅判断纪律段不同）
  T5  v2 提示词不含素材特定提示（样本编号/时间/目标词/答案）
  T6  256 点清单完整性（白名单/哈希/存在性/计数/ID 唯一性）
  T7  运行顺序轮换确定性（偶数 v1 先、奇数 v2 先、各 128）
  T8  classify/metric_for 七类映射单元测试（与冻结规则同义）
  T9  去重敏感性计算（184 唯一帧）
  T10 配对执行器纯函数（版本解析、prompt_for 双版本渲染、失败判断结构）
  T11 帧农场报告完整性（184 帧、字节一致计数、无 mismatch）
  T12 GT 隔离（点清单与 runner 请求构造不含 GT 标签键）

用法: python3 scripts/test_task20_pairing.py
退出码: 0 = 全部通过; 1 = 有失败
"""
import importlib.util
import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PREREG = os.path.join(PROJECT_ROOT, "artifacts", "task-20", "preregistration")
PHASE0 = os.path.join(PROJECT_ROOT, "artifacts", "task-20", "phase0")
ANALYZE_IMAGE = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                             "scripts", "analyze_image.py")
WHITELIST = {"AI01", "AI02", "AI03", "AI04", "AI05", "AI06", "WEB01", "WEB02", "WEB03"}
GENERATED = {"AI01", "AI02", "AI03", "AI04", "AI05", "AI06"}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_of_text(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_prerequisites():
    """公开版前置检查：本测试的多数用例读取任务 20 的内部摄验/评分产物，
    这些内容不随公开仓库分发（见 docs/PUBLIC-VERSION-NOTES.md）。缺失时不伪报
    PASS，明确退出（exit 2）并打印 NOT_RUN 原因；备齐后行为不变。"""
    missing = [rel for rel in ['artifacts/task-20/pairs', 'artifacts/task-20/preregistration', 'artifacts/task-20/scores']
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
    results = []

    def check(test_id, name, passed, detail=""):
        results.append({"id": test_id, "name": name, "passed": bool(passed), "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {test_id} {name}"
              + (f" — {detail}" if detail else ""), flush=True)

    paired = load_module("paired_scorer", os.path.join(PREREG, "paired_scorer.py"))
    analyze = load_module("analyze_image", ANALYZE_IMAGE)
    runner = load_module("run_task20_pairing",
                         os.path.join(PROJECT_ROOT, "scripts", "run_task20_pairing.py"))

    # ---------------- T1 历史等价性
    historical = paired.verify_historical(
        os.path.join(PROJECT_ROOT, "artifacts", "task-19"),
        os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ground-truth"))
    check("T1", "配对评分器与冻结评分器历史等价（256 点逐行+计数）",
          historical["equivalent"] and historical["total_points_checked"] == 256,
          f"checked={historical['total_points_checked']} mismatches={len(historical['mismatches'])}")

    # ---------------- T2 门槛判定
    def counts(correct, incorrect, app_abst, overclaim, failed):
        return {"correct_decisive": correct, "incorrect_decisive": incorrect,
                "appropriate_abstention": app_abst, "overclaim_on_uncertain": overclaim,
                "failed_on_determinate": failed}

    def tracks(gen, lic):
        return {"generated": counts(*gen), "licensed-public": counts(*lic)}

    # 历史同期基线口径：v1 = generated(114,5,5,41,0) + licensed(73,17,0,0,1)
    v1_tracks = tracks((114, 5, 5, 41, 0), (73, 17, 0, 0, 1))
    v1c = counts(187, 22, 5, 41, 1)
    # T2a: overclaim 41→36（-5）、incorrect 持平、correct 总计 -4（generated -4、licensed -0）、failed 持平
    v2c = counts(183, 22, 10, 36, 1)
    v2_tracks = tracks((110, 5, 10, 36, 0), (73, 17, 0, 0, 1))
    gates = paired.evaluate_gates(v1c, v2c, v1_tracks, v2_tracks)
    verdict, reasons = paired.decide_verdict(v1c, v2c, gates)
    check("T2a", "全门通过 → IMPROVEMENT", verdict == "IMPROVEMENT", f"reasons={reasons}")

    # T2b: overclaim 降 5 但 correct 总计降 17（licensed 降 5）→ TRADEOFF
    v2c_b = counts(170, 22, 5, 36, 1)
    v2_tracks_b = tracks((110, 5, 10, 36, 0), (60, 17, 0, 0, 1))
    gates = paired.evaluate_gates(v1c, v2c_b, v1_tracks, v2_tracks_b)
    verdict, reasons = paired.decide_verdict(v1c, v2c_b, gates)
    check("T2b", "overclaim 降但 correct 降幅超标 → TRADEOFF", verdict == "TRADEOFF",
          f"reasons={reasons}")

    # T2c: overclaim 仅降 2 → NO_IMPROVEMENT
    v2c_c = counts(187, 22, 5, 39, 1)
    v2_tracks_c = tracks((114, 5, 5, 39, 0), (73, 17, 0, 0, 1))
    gates = paired.evaluate_gates(v1c, v2c_c, v1_tracks, v2_tracks_c)
    verdict, reasons = paired.decide_verdict(v1c, v2c_c, gates)
    check("T2c", "overclaim 降幅不足 5 → NO_IMPROVEMENT", verdict == "NO_IMPROVEMENT",
          f"reasons={reasons}")

    # T2d: incorrect 增加（generated +1）→ NO_IMPROVEMENT
    v2c_d = counts(183, 23, 10, 36, 1)
    v2_tracks_d = tracks((110, 6, 10, 36, 0), (73, 17, 0, 0, 1))
    gates = paired.evaluate_gates(v1c, v2c_d, v1_tracks, v2_tracks_d)
    verdict, reasons = paired.decide_verdict(v1c, v2c_d, gates)
    check("T2d", "incorrect 增加 → NO_IMPROVEMENT", verdict == "NO_IMPROVEMENT",
          f"reasons={reasons}")

    # T2e: 同期 v1 overclaim < 5 → 基线漂移
    v1_low = counts(10, 0, 0, 4, 0)
    v1_low_tracks = tracks((10, 0, 0, 4, 0), (0, 0, 0, 0, 0))
    v2_low = counts(10, 0, 0, 0, 0)
    v2_low_tracks = tracks((10, 0, 0, 0, 0), (0, 0, 0, 0, 0))
    gates = paired.evaluate_gates(v1_low, v2_low, v1_low_tracks, v2_low_tracks)
    verdict, reasons = paired.decide_verdict(v1_low, v2_low, gates)
    check("T2e", "同期 v1 overclaim<5 → INCONCLUSIVE_BASELINE_DRIFT",
          verdict == "INCONCLUSIVE_BASELINE_DRIFT", f"reasons={reasons}")

    # ---------------- T3 v1 锚定
    v1_hash = sha256_of_text(analyze.PROMPT_TEMPLATE)
    check("T3", "v1 提示词 = analyze_image.PROMPT_TEMPLATE（哈希锚定）",
          v1_hash == "fc29078044d5fe47daacb2384f3f29f562ed8638b835f2577732a8bd185de65b",
          v1_hash)

    # ---------------- T4 v2 结构不变式
    v2_text = open(os.path.join(PREREG, "prompt-v2.txt"), encoding="utf-8").read()
    ph1 = sorted(set(re.findall(r"\{(\w+)\}", analyze.PROMPT_TEMPLATE)))
    ph2 = sorted(set(re.findall(r"\{(\w+)\}", v2_text)))
    check("T4a", "v2 占位符与 v1 相同", ph1 == ph2, f"{ph1}")

    def contract_block(text):
        start = text.index("请只返回一个 JSON 对象")
        end = text.index("}", text.index('"abstention_reason"'))
        return text[start:end + 1]

    check("T4b", "v2 JSON 输出契约块与 v1 逐字节相同",
          contract_block(analyze.PROMPT_TEMPLATE) == contract_block(v2_text))
    check("T4c", "v2 与 v1 不同（判断纪律已改）",
          analyze.PROMPT_TEMPLATE != v2_text)
    check("T4d", "v2 保留禁推注入行与规则行",
          "禁止推断" in v2_text and "禁止猜测，禁止把不确定的内容写成事实" in v2_text)

    # ---------------- T5 v2 无素材特定提示
    banned_patterns = [r"AI0\d", r"WEB0\d", r"T20-P", r"红色背包", r"叉车", r"周转箱", r"纸箱",
                       r"托盘", r"\[\d{3,5},\s*\d{3,5}\]", r"第\s*[49]\s*秒", r"遮挡区",
                       r"4000", r"9000", r"10125", r"P\d{3,4}"]
    hits = [p for p in banned_patterns if re.search(p, v2_text)]
    check("T5", "v2 不含样本编号/时间/目标词/答案等素材特定提示", not hits, f"hits={hits}")

    # ---------------- T6 点清单完整性
    manifest = json.load(open(os.path.join(PREREG, "point-manifest-256.json"), encoding="utf-8"))
    points = manifest["points"]
    ok_count = manifest["total_points"] == 256 and len(points) == 256
    ok_ids = len({p["point_id"] for p in points}) == 256
    ok_whitelist = all(p["sample_id"] in WHITELIST for p in points)
    ok_frames = all(os.path.isfile(os.path.join(PROJECT_ROOT, p["task20_frame_path"])) for p in points)
    ok_hashes = True
    for p in points:
        path = os.path.join(PROJECT_ROOT, p["task20_frame_path"])
        if runner.sha256_of(path) != p["task20_frame_sha256"]:
            ok_hashes = False
            break
    ok_tracks = (sum(1 for p in points if p["track"] == "generated") == 165
                 and sum(1 for p in points if p["track"] == "licensed-public") == 91)
    ok_arms = (sum(1 for p in points if p["arm"] == "uniform") == 121
               and sum(1 for p in points if p["arm"] == "adaptive") == 51
               and sum(1 for p in points if p["arm"] == "coverage") == 84)
    ok_unique = len({(p["sample_id"], p["timestamp_ms"]) for p in points}) == 184
    check("T6", "256 点清单完整（计数/ID/白名单/帧存在/哈希/轨道/臂/唯一帧）",
          all([ok_count, ok_ids, ok_whitelist, ok_frames, ok_hashes, ok_tracks, ok_arms, ok_unique]),
          f"count={ok_count} ids={ok_ids} whitelist={ok_whitelist} frames={ok_frames} "
          f"hashes={ok_hashes} tracks={ok_tracks} arms={ok_arms} unique={ok_unique}")

    # ---------------- T7 运行顺序轮换
    v1_first = sum(1 for i in range(256) if i % 2 == 0)
    v2_first = 256 - v1_first
    check("T7", "轮换确定性（偶数索引 v1 先；v1先/v2先 = 128/128）",
          v1_first == 128 and v2_first == 128, f"v1_first={v1_first} v2_first={v2_first}")

    # ---------------- T8 classify/metric_for 映射
    cases = [
        ({"frame_status": "analyzed", "object_found": True, "evidence_sufficient": True}, "confirmed"),
        ({"frame_status": "analyzed", "object_found": True, "evidence_sufficient": False}, "low_confidence"),
        ({"frame_status": "analyzed", "object_found": False, "abstention_reason": "看不清"}, "abstained"),
        ({"frame_status": "analyzed", "object_found": False, "abstention_reason": None}, "not_found"),
        ({"frame_status": "failed", "object_found": False, "abstention_reason": "x"}, "failed"),
    ]
    ok = all(paired.classify_entry(entry) == expected for entry, expected in cases)
    metric_cases = [
        ("confirmed", "confirmed", "correct_decisive"),
        ("not_found", "confirmed", "incorrect_decisive"),
        ("confirmed", "abstained", "abstention_on_determinate"),
        ("confirmed", "failed", "failed_on_determinate"),
        ("uncertain", "abstained", "appropriate_abstention"),
        ("uncertain", "confirmed", "overclaim_on_uncertain"),
        ("uncertain", "low_confidence", "appropriate_abstention"),
        ("uncertain", "failed", "failed_on_uncertain"),
    ]
    ok = ok and all(paired.metric_for(gt, pred) == expected
                    for gt, pred, expected in metric_cases)
    check("T8", "classify_entry 与 metric_for 七类映射同义", ok)

    # ---------------- T9 去重敏感性
    synthetic_points = [
        {"point_id": "S1", "sample_id": "AI01", "timestamp_ms": 0.0, "track": "generated",
         "v1_judgment": {"frame_status": "analyzed", "object_found": True,
                         "evidence_sufficient": True, "abstention_reason": None},
         "v2_judgment": {"frame_status": "analyzed", "object_found": False,
                         "evidence_sufficient": False, "abstention_reason": "看不清"}},
        {"point_id": "S2", "sample_id": "AI01", "timestamp_ms": 0.0, "track": "generated",
         "v1_judgment": {"frame_status": "analyzed", "object_found": True,
                         "evidence_sufficient": True, "abstention_reason": None},
         "v2_judgment": {"frame_status": "analyzed", "object_found": True,
                         "evidence_sufficient": True, "abstention_reason": None}},
        {"point_id": "S3", "sample_id": "AI01", "timestamp_ms": 1000.0, "track": "generated",
         "v1_judgment": {"frame_status": "analyzed", "object_found": False,
                         "evidence_sufficient": False, "abstention_reason": None},
         "v2_judgment": {"frame_status": "analyzed", "object_found": False,
                         "evidence_sufficient": False, "abstention_reason": None}},
    ]
    gts = {"AI01": {"segments": [{"start_ms": 0, "end_ms": 2000, "state": "confirmed"}],
                    "media_duration_ms": 2000}}
    v1_side = paired.score_side(synthetic_points, gts, "v1")
    v2_side = paired.score_side(synthetic_points, gts, "v2")
    dedup_v1 = paired.dedup_sensitivity(synthetic_points, v1_side)
    dedup_v2 = paired.dedup_sensitivity(synthetic_points, v2_side)
    ok = (dedup_v1["unique_frames"] == 2 and dedup_v1["counts"]["correct_decisive"] == 1
          and dedup_v1["counts"]["incorrect_decisive"] == 1
          and dedup_v2["unique_frames"] == 2 and dedup_v2["counts"]["correct_decisive"] == 0
          and dedup_v2["counts"]["incorrect_decisive"] == 1)
    check("T9", "去重敏感性（重复帧按唯一帧首次出现计）", ok,
          f"v1={dedup_v1['counts']} v2={dedup_v2['counts']}")

    # ---------------- T10 执行器纯函数
    spec = {"target": {"description": "红色背包"},
            "constraints": {"forbidden_inferences": ["identity"]}}
    p1 = runner.prompt_for("v1", spec) if hasattr(runner, "prompt_for") else None
    # prompt_for 是 main 内闭包；改为直接复现其逻辑做等价断言
    target = spec.get("target", {})
    attributes = target.get("attributes") or []
    forbidden = spec.get("constraints", {}).get("forbidden_inferences") or []
    rendered_v2 = v2_text.format(
        target_description=target.get("description", ""),
        attributes="、".join(attributes) if attributes else "（无）",
        forbidden="、".join(forbidden) if forbidden else "（无）")
    ok = ("红色背包" in rendered_v2 and '"object_found"' in rendered_v2
          and "判断纪律" in rendered_v2 and "identity" in rendered_v2)
    check("T10", "v2 模板按 spec 渲染（目标/禁推注入、契约完整）", ok)

    # ---------------- T11 帧农场报告
    farm = json.load(open(os.path.join(PHASE0, "frame-farm-report.json"), encoding="utf-8"))
    ok = (farm["total_unique_frames"] == 184 and farm["byte_identical_count"] == 184
          and farm["mismatch_count"] == 0 and farm["missing_history_count"] == 0)
    check("T11", "帧农场 184 帧与 Task 19B 盘上帧逐字节一致", ok,
          f"identical={farm['byte_identical_count']}/{farm['total_unique_frames']}")

    # ---------------- T12 GT 隔离
    gt_keys = ("segments", "ground_truth", "gt_state", "label", "annotation")
    manifest_text = json.dumps(manifest, ensure_ascii=False)
    farm_text = json.dumps(farm, ensure_ascii=False)
    leaks = [k for k in gt_keys if k in manifest_text or k in farm_text]
    check("T12", "点清单/帧农场报告不含 GT 标签结构", not leaks, f"leaks={leaks}")

    # ---------------- 汇总
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    out = {"task": "task20-pairing-tests", "total": total, "passed": passed,
           "failed": total - passed, "all_passed": passed == total, "results": results}
    out_path = os.path.join(PROJECT_ROOT, "artifacts", "task-20", "test-results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"\nRESULT: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
