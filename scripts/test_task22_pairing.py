#!/usr/bin/env python3
"""test_task22_pairing.py — Task 22 同期同帧配对实验确定性测试（SparkSkill Studio 任务 22）

全部为确定性测试（零模型调用、零网络）:
  T1  配对评分器与 Task 17 冻结评分器的历史等价性（256 个历史点逐行 + 计数零 mismatch）
  T2  预注册门槛/verdict 单元测试（IMPROVEMENT / TRADEOFF / NO_IMPROVEMENT / 漂移 /
      G2 incorrect 增加 / G4 误拒门 / G5 failed 门 / G3 licensed-public 不得减少）
  T3  v1 提示词哈希与 analyze_image.PROMPT_TEMPLATE 一致（版本锚定）
  T4  c3 结构不变式（占位符相同、核心 JSON 契约块逐字节相同、c3≠v1、保留禁推/规则行）
  T5  c3 不含素材特定提示（样本编号/时间/目标词/答案/GT 时间段/难度标签）
  T6  c3 可见性非机械拒答纪律 + 三类区分（确定性负面 vs 拒答）关键句存在
  T7  256 点清单完整性（计数/ID/白名单/帧存在/哈希/轨道/臂/唯一帧=184 by frame_sha256）
  T8  运行顺序轮换确定性（偶数 v1 先、奇数 c3 先、各 128）
  T9  classify/metric_for 七类映射（真假阳性/真实拒答/误拒/失败）
  T10 c3 coercer 契约（核心字段校验复用 analyze_image；分项宽松抽取；缺项记录不猜补；
      真假阳性/真实拒答/误拒/失败/跨轨分层/哈希漂移 fixture）
  T11 去重敏感性按 frame_sha256（含哈希漂移检测 fixture）
  T12 帧农场报告完整性（184 帧、字节一致计数、无 mismatch）
  T13 GT 隔离（点清单/帧农场/评分器输入不含 GT 标签结构）

用法: python3 scripts/test_task22_pairing.py
退出码: 0 = 全部通过; 1 = 有失败
"""
import hashlib
import importlib.util
import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PREREG = os.path.join(PROJECT_ROOT, "artifacts", "task-22", "preregistration")
PHASE0 = os.path.join(PROJECT_ROOT, "artifacts", "task-22", "phase0")
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
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_prerequisites():
    """公开版前置检查：本测试的多数用例读取任务 22 的内部摄验/评分产物，
    这些内容不随公开仓库分发（见 docs/PUBLIC-VERSION-NOTES.md）。缺失时不伪报
    PASS，明确退出（exit 2）并打印 NOT_RUN 原因；备齐后行为不变。"""
    missing = [rel for rel in ['artifacts/task-20/frames', 'artifacts/task-22/pairs', 'artifacts/task-22/preregistration']
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
    runner = load_module("run_task22_pairing",
                         os.path.join(PROJECT_ROOT, "scripts", "run_task22_pairing.py"))

    # ---------------- T1 历史等价性
    historical = paired.verify_historical(
        os.path.join(PROJECT_ROOT, "artifacts", "task-19"),
        os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ground-truth"))
    check("T1", "配对评分器与冻结评分器历史等价（256 点逐行+计数）",
          historical["equivalent"] and historical["total_points_checked"] == 256,
          f"checked={historical['total_points_checked']} mismatches={len(historical['mismatches'])}")

    # ---------------- T2 门槛/verdict
    def counts(correct, incorrect, abst_det, failed_det, app_abst, overclaim, failed_unc):
        return {"correct_decisive": correct, "incorrect_decisive": incorrect,
                "abstention_on_determinate": abst_det, "failed_on_determinate": failed_det,
                "appropriate_abstention": app_abst, "overclaim_on_uncertain": overclaim,
                "failed_on_uncertain": failed_unc}

    def tracks(gen, lic):
        return {"generated": counts(*gen), "licensed-public": counts(*lic)}

    # 同期 v1 基线口径（与阶段 0 复算一致：v1=186/24/0/0/6/40/0；generated 114/5/0/0/6/40/0, licensed 72/19/0/0/0/0/0）
    v1c = counts(186, 24, 0, 0, 6, 40, 0)
    v1_tracks = tracks((114, 5, 0, 0, 6, 40, 0), (72, 19, 0, 0, 0, 0, 0))

    # T2a: 全门通过 → IMPROVEMENT（overclaim -6; incorrect 持平; correct -2 total, licensed 0; abst +2; failed 持平）
    c3c = counts(184, 24, 2, 0, 8, 34, 0)
    c3_tracks = tracks((112, 5, 2, 0, 8, 34, 0), (72, 19, 0, 0, 0, 0, 0))
    gates = paired.evaluate_gates(v1c, c3c, v1_tracks, c3_tracks)
    verdict, reasons = paired.decide_verdict(v1c, c3c, gates)
    check("T2a", "G1-G6 全过 → IMPROVEMENT", verdict == "IMPROVEMENT", f"reasons={reasons}")

    # T2b: overclaim 降但 correct 总降 5（>2）→ TRADEOFF
    c3c_b = counts(181, 24, 5, 0, 11, 34, 0)
    c3_tracks_b = tracks((109, 5, 5, 0, 11, 34, 0), (72, 19, 0, 0, 0, 0, 0))
    gates = paired.evaluate_gates(v1c, c3c_b, v1_tracks, c3_tracks_b)
    verdict, reasons = paired.decide_verdict(v1c, c3c_b, gates)
    check("T2b", "overclaim 降但 correct 降幅超 2 → TRADEOFF", verdict == "TRADEOFF",
          f"reasons={reasons}")

    # T2b2: overclaim 降、correct 降 1 但 licensed-public 降 1（不得减少）→ TRADEOFF
    c3c_b2 = counts(185, 24, 1, 0, 7, 34, 0)
    c3_tracks_b2 = tracks((114, 5, 1, 0, 7, 34, 0), (71, 19, 0, 0, 0, 0, 0))
    gates = paired.evaluate_gates(v1c, c3c_b2, v1_tracks, c3_tracks_b2)
    verdict, reasons = paired.decide_verdict(v1c, c3c_b2, gates)
    check("T2b2", "licensed-public correct 减少 → TRADEOFF（G3 fail）", verdict == "TRADEOFF",
          f"reasons={reasons}")

    # T2c: overclaim 仅降 3 → NO_IMPROVEMENT
    c3c_c = counts(186, 24, 0, 0, 6, 37, 0)
    c3_tracks_c = tracks((114, 5, 0, 0, 6, 37, 0), (72, 19, 0, 0, 0, 0, 0))
    gates = paired.evaluate_gates(v1c, c3c_c, v1_tracks, c3_tracks_c)
    verdict, reasons = paired.decide_verdict(v1c, c3c_c, gates)
    check("T2c", "overclaim 降幅不足 5 → NO_IMPROVEMENT", verdict == "NO_IMPROVEMENT",
          f"reasons={reasons}")

    # T2d: incorrect 增加（generated +1）→ NO_IMPROVEMENT
    c3c_d = counts(184, 25, 2, 0, 8, 34, 0)
    c3_tracks_d = tracks((113, 6, 2, 0, 8, 34, 0), (72, 19, 0, 0, 0, 0, 0))
    gates = paired.evaluate_gates(v1c, c3c_d, v1_tracks, c3_tracks_d)
    verdict, reasons = paired.decide_verdict(v1c, c3c_d, gates)
    check("T2d", "incorrect 增加 → NO_IMPROVEMENT", verdict == "NO_IMPROVEMENT",
          f"reasons={reasons}")

    # T2e: 同期 v1 overclaim < 5 → 基线漂移
    v1_low = counts(10, 0, 0, 0, 0, 4, 0)
    v1_low_tracks = tracks((10, 0, 0, 0, 0, 4, 0), (0, 0, 0, 0, 0, 0, 0))
    c3_low = counts(10, 0, 0, 0, 0, 0, 0)
    c3_low_tracks = tracks((10, 0, 0, 0, 0, 0, 0), (0, 0, 0, 0, 0, 0, 0))
    gates = paired.evaluate_gates(v1_low, c3_low, v1_low_tracks, c3_low_tracks)
    verdict, reasons = paired.decide_verdict(v1_low, c3_low, gates)
    check("T2e", "同期 v1 overclaim<5 → INCONCLUSIVE_BASELINE_DRIFT",
          verdict == "INCONCLUSIVE_BASELINE_DRIFT", f"reasons={reasons}")

    # T2f: G4 误拒门——abstention_on_determinate 增 3（>2）→ TRADEOFF（overclaim 仍降、correct 降 3 也超）
    c3c_f = counts(183, 24, 3, 0, 9, 34, 0)
    c3_tracks_f = tracks((111, 5, 3, 0, 9, 34, 0), (72, 19, 0, 0, 0, 0, 0))
    gates = paired.evaluate_gates(v1c, c3c_f, v1_tracks, c3_tracks_f)
    check("T2f-G4", "abstention_on_determinate 增 3 → G4 FAIL",
          gates["G4_abstention_on_determinate_increase_le_2"]["passed"] is False)
    verdict, reasons = paired.decide_verdict(v1c, c3c_f, gates)
    check("T2f", "G4 失败 → TRADEOFF", verdict == "TRADEOFF", f"reasons={reasons}")

    # T2g: G5 failed 门——failed_on_uncertain 增 1（correct 未超容忍）→ NO_IMPROVEMENT
    c3c_g = counts(184, 24, 0, 0, 6, 34, 1)
    c3_tracks_g = tracks((112, 5, 0, 0, 6, 34, 0), (72, 19, 0, 0, 0, 0, 1))
    gates = paired.evaluate_gates(v1c, c3c_g, v1_tracks, c3_tracks_g)
    check("T2g-G5", "failed_on_uncertain 增 1 → G5 FAIL",
          gates["G5_failed_not_increased"]["passed"] is False)
    verdict, reasons = paired.decide_verdict(v1c, c3c_g, gates)
    check("T2g", "G5 失败 → NO_IMPROVEMENT", verdict == "NO_IMPROVEMENT", f"reasons={reasons}")

    # ---------------- T3 v1 锚定
    v1_hash = sha256_of_text(analyze.PROMPT_TEMPLATE)
    check("T3", "v1 提示词 = analyze_image.PROMPT_TEMPLATE（哈希锚定）",
          v1_hash == "fc29078044d5fe47daacb2384f3f29f562ed8638b835f2577732a8bd185de65b",
          v1_hash)

    # ---------------- T4 c3 结构不变式
    c3_text = open(os.path.join(PREREG, "prompt-c3.txt"), encoding="utf-8").read()
    ph1 = sorted(set(re.findall(r"\{(\w+)\}", analyze.PROMPT_TEMPLATE)))
    ph3 = sorted(set(re.findall(r"\{(\w+)\}", c3_text)))
    check("T4a", "c3 占位符与 v1 相同", ph1 == ph3, f"{ph1}")

    def contract_block(text):
        # 核心字段契约：从"请只返回一个 JSON 对象"到 abstention_reason 字段定义结尾（含）。
        # c3 在该字段后追加逗号与 6 个分项支持字段（允许），故只断言核心字段定义逐字节相同，
        # 不含 c3 为追加分项而引入的尾部逗号。
        start = text.index("请只返回一个 JSON 对象")
        field = '"abstention_reason": "string 或 null"'
        end = text.index(field) + len(field)
        return text[start:end]

    check("T4b", "c3 核心 JSON 字段契约（至 abstention_reason 定义）与 v1 逐字节相同",
          contract_block(analyze.PROMPT_TEMPLATE) == contract_block(c3_text))
    check("T4c", "c3 与 v1 不同（判断纪律已改）", analyze.PROMPT_TEMPLATE != c3_text)
    check("T4d", "c3 保留禁推注入行与规则行",
          "禁止推断" in c3_text and "禁止猜测，禁止把不确定的内容写成事实" in c3_text)
    # c3 必须包含全部 6 个分项支持字段
    itemized_keys = ["target_category", "category_match", "necessary_attributes",
                     "target_relationship", "visibility", "visibility_impedes_judgment"]
    check("T4e", "c3 请求全部 6 个分项支持字段",
          all(k in c3_text for k in itemized_keys),
          f"missing={[k for k in itemized_keys if k not in c3_text]}")

    # ---------------- T5 c3 无素材特定提示
    banned_patterns = [r"AI0\d", r"WEB0\d", r"T2[012]-P", r"红色背包", r"叉车", r"周转箱", r"纸箱",
                       r"托盘", r"拣选车", r"\[\d{3,5},\s*\d{3,5}\]", r"第\s*[49]\s*秒",
                       r"遮挡区", r"\b4000\b", r"\b9000\b", r"\b10125\b", r"\b17480\b",
                       r"\b666\b", r" uncertain 区", r"难度", r"overclaim", r"v1", r"v2", r"c3"]
    hits = [p for p in banned_patterns if re.search(p, c3_text)]
    check("T5", "c3 不含样本编号/时间/目标词/答案/GT 时段/难度/旧版本号等素材特定提示",
          not hits, f"hits={hits}")

    # ---------------- T6 c3 可见性非机械拒答纪律 + 三类区分
    has_non_mechanical = ("不是" in c3_text and "拒答开关" in c3_text)
    has_determinate_neg = "确定性负面" in c3_text and "画面里没有目标" in c3_text
    has_abstain = "拒答" in c3_text and "画面不足以判断" in c3_text
    has_confirmed = "确认存在" in c3_text
    check("T6", "c3 可见性非机械拒答纪律 + 三类（确认/确定性负面/拒答）区分关键句齐全",
          has_non_mechanical and has_determinate_neg and has_abstain and has_confirmed,
          f"non_mechanical={has_non_mechanical} det_neg={has_determinate_neg} "
          f"abstain={has_abstain} confirmed={has_confirmed}")

    # ---------------- T7 256 点清单完整性
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
    ok_unique = len({p["task20_frame_sha256"] for p in points}) == 184
    check("T7", "256 点清单完整（计数/ID/白名单/帧存在/哈希/轨道/臂/唯一帧=184 by frame_sha256）",
          all([ok_count, ok_ids, ok_whitelist, ok_frames, ok_hashes, ok_tracks, ok_arms, ok_unique]),
          f"count={ok_count} ids={ok_ids} whitelist={ok_whitelist} frames={ok_frames} "
          f"hashes={ok_hashes} tracks={ok_tracks} arms={ok_arms} unique={ok_unique}")

    # ---------------- T8 运行顺序轮换
    v1_first = sum(1 for i in range(256) if i % 2 == 0)
    c3_first = 256 - v1_first
    check("T8", "轮换确定性（偶数索引 v1 先；v1先/c3先 = 128/128）",
          v1_first == 128 and c3_first == 128, f"v1_first={v1_first} c3_first={c3_first}")

    # ---------------- T9 classify/metric_for 七类映射
    cases = [
        ({"frame_status": "analyzed", "object_found": True, "evidence_sufficient": True}, "confirmed"),
        ({"frame_status": "analyzed", "object_found": True, "evidence_sufficient": False}, "low_confidence"),
        ({"frame_status": "analyzed", "object_found": False, "abstention_reason": "看不清"}, "abstained"),
        ({"frame_status": "analyzed", "object_found": False, "abstention_reason": None}, "not_found"),
        ({"frame_status": "failed", "object_found": False, "abstention_reason": "x"}, "failed"),
    ]
    ok = all(paired.classify_entry(entry) == expected for entry, expected in cases)
    metric_cases = [
        ("confirmed", "confirmed", "correct_decisive"),      # 真阳性
        ("not_found", "confirmed", "incorrect_decisive"),    # 假阳性
        ("confirmed", "abstained", "abstention_on_determinate"),  # 误拒
        ("confirmed", "failed", "failed_on_determinate"),    # 失败（确定）
        ("uncertain", "abstained", "appropriate_abstention"),  # 真实拒答
        ("uncertain", "confirmed", "overclaim_on_uncertain"),  # uncertain 过度断言
        ("uncertain", "low_confidence", "appropriate_abstention"),
        ("uncertain", "failed", "failed_on_uncertain"),      # 失败（uncertain）
        ("not_found", "not_found", "correct_decisive"),      # 真阴性
    ]
    ok = ok and all(paired.metric_for(gt, pred) == expected
                    for gt, pred, expected in metric_cases)
    check("T9", "classify_entry 与 metric_for 七类映射同义（真假阳性/拒答/误拒/失败）", ok)

    # ---------------- T10 c3 coercer 契约
    spec = {"task_id": "t", "task_type": "object_trace",
            "target": {"description": "红色背包"},
            "constraints": {"forbidden_inferences": ["identity"]},
            "confidence_threshold": 0.5, "requires_visual_input": True}
    # 用 Task 20 帧农场里一个真实存在的帧做 coercer 输入（不调用模型，仅解析）
    frame_path = os.path.join(PROJECT_ROOT, "artifacts/task-20/frames/AI01/AI01_f00000_t00000000ms.png")
    # (a) 完整分项 + 确认存在
    raw_full = {"object_found": True, "description": "d", "bounding_box": None, "confidence": 0.9,
                "evidence_text": "e", "abstention_reason": None,
                "target_category": "背包", "category_match": True,
                "necessary_attributes": ["红色"], "target_relationship": "在货架上",
                "visibility": "clear", "visibility_impedes_judgment": False}
    ev_full = runner.coerce_c3(analyze, raw_full, spec, frame_path, "m")
    ok_full = (ev_full["itemized_support_complete"] is True
               and ev_full["itemized_support_gaps"] == []
               and ev_full["object_found"] is True and ev_full["evidence_sufficient"] is True
               and paired.classify_entry({**ev_full, "frame_status": "analyzed"}) == "confirmed")
    check("T10a", "c3 coercer 完整分项 + 确认存在 → itemized_complete + confirmed", ok_full)

    # (b) 缺分项（模型未提供 category_match / necessary_attributes）→ 记录 gaps、不猜补、核心不变
    raw_missing = {"object_found": False, "description": "d", "bounding_box": None,
                   "confidence": 0.9, "evidence_text": "e", "abstention_reason": None}
    ev_missing = runner.coerce_c3(analyze, raw_missing, spec, frame_path, "m")
    ok_missing = (ev_missing["itemized_support_complete"] is False
                  and set(ev_missing["itemized_support_gaps"]) ==
                  {"target_category", "category_match", "necessary_attributes",
                   "target_relationship", "visibility", "visibility_impedes_judgment"}
                  and ev_missing["itemized_support"]["category_match"] is None
                  and paired.classify_entry({**ev_missing, "frame_status": "analyzed"}) == "not_found")
    check("T10b", "c3 coercer 缺分项 → gaps 记录、置 null 不猜补、核心分类不变（not_found）", ok_missing)

    # (c) 真实拒答：object_found=false + abstention_reason 非空
    raw_abstain = {"object_found": False, "description": "d", "bounding_box": None,
                   "confidence": 0.4, "evidence_text": "e", "abstention_reason": "目标被遮挡无法分辨",
                   "visibility": "obscured", "visibility_impedes_judgment": True,
                   "target_category": "none", "category_match": False,
                   "necessary_attributes": [], "target_relationship": "none"}
    ev_abstain = runner.coerce_c3(analyze, raw_abstain, spec, frame_path, "m")
    ok_abstain = paired.classify_entry({**ev_abstain, "frame_status": "analyzed"}) == "abstained"
    check("T10c", "c3 coercer 真实拒答 → abstained", ok_abstain)

    # (d) 核心字段缺失（缺 description）→ 与 v1 同样抛 ValueError（失败面一致）
    raised = False
    try:
        runner.coerce_c3(analyze, {"object_found": True, "bounding_box": None, "confidence": 0.9,
                                   "evidence_text": "e", "abstention_reason": None},
                         spec, frame_path, "m")
    except ValueError:
        raised = True
    check("T10d", "c3 coercer 核心字段缺失 → ValueError（与 v1 失败面一致）", raised)

    # (e) 跨轨分层：score_side by_track 分开 generated / licensed-public
    strat_points = [
        {"point_id": "S1", "sample_id": "AI01", "arm": "uniform", "timestamp_ms": 0.0,
         "track": "generated", "frame_sha256": "h1",
         "v1_judgment": {"frame_status": "analyzed", "object_found": True,
                         "evidence_sufficient": True, "abstention_reason": None},
         "c3_judgment": {"frame_status": "analyzed", "object_found": True,
                         "evidence_sufficient": True, "abstention_reason": None}},
        {"point_id": "S2", "sample_id": "WEB01", "arm": "uniform", "timestamp_ms": 0.0,
         "track": "licensed-public", "frame_sha256": "h2",
         "v1_judgment": {"frame_status": "analyzed", "object_found": True,
                         "evidence_sufficient": True, "abstention_reason": None},
         "c3_judgment": {"frame_status": "analyzed", "object_found": False,
                         "evidence_sufficient": False, "abstention_reason": "看不清"}},
    ]
    gts = {"AI01": {"segments": [{"start_ms": 0, "end_ms": 1000, "state": "confirmed"}],
                    "media_duration_ms": 1000},
           "WEB01": {"segments": [{"start_ms": 0, "end_ms": 1000, "state": "uncertain"}],
                     "media_duration_ms": 1000}}
    c3_side = paired.score_side(strat_points, gts, "c3")
    ok_strat = (c3_side["by_track"]["generated"]["correct_decisive"] == 1
                and c3_side["by_track"]["licensed-public"]["appropriate_abstention"] == 1)
    check("T10e", "跨轨分层：generated correct=1 / licensed-public appropriate_abstention=1", ok_strat)

    # ---------------- T11 去重敏感性按 frame_sha256（含哈希漂移检测）
    # 两个点同一 frame_sha256 → 去重为 1；不同 frame_sha256 → 2
    dedup_points = [
        {"point_id": "D1", "sample_id": "AI01", "timestamp_ms": 0.0, "track": "generated",
         "frame_sha256": "same", "v1_judgment": {"frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
         "c3_judgment": {"frame_status": "analyzed", "object_found": False,
         "evidence_sufficient": False, "abstention_reason": "x"}},
        {"point_id": "D2", "sample_id": "AI01", "timestamp_ms": 0.0, "track": "generated",
         "frame_sha256": "same", "v1_judgment": {"frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
         "c3_judgment": {"frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None}},
        {"point_id": "D3", "sample_id": "AI01", "timestamp_ms": 500.0, "track": "generated",
         "frame_sha256": "other", "v1_judgment": {"frame_status": "analyzed", "object_found": False,
         "evidence_sufficient": False, "abstention_reason": None},
         "c3_judgment": {"frame_status": "analyzed", "object_found": False,
         "evidence_sufficient": False, "abstention_reason": None}},
    ]
    dgts = {"AI01": {"segments": [{"start_ms": 0, "end_ms": 1000, "state": "confirmed"}],
                     "media_duration_ms": 1000}}
    v1_side = paired.score_side(dedup_points, dgts, "v1")
    c3_side2 = paired.score_side(dedup_points, dgts, "c3")
    dv1 = paired.dedup_sensitivity(dedup_points, v1_side)
    dc3 = paired.dedup_sensitivity(dedup_points, c3_side2)
    ok_dedup = (dv1["unique_frames"] == 2 and dv1["dedup_key"] == "frame_sha256"
                and dv1["counts"]["correct_decisive"] == 1 and dv1["counts"]["incorrect_decisive"] == 1
                and dc3["unique_frames"] == 2 and dc3["counts"]["abstention_on_determinate"] == 1
                and dc3["counts"]["incorrect_decisive"] == 1)
    check("T11", "去重按 frame_sha256（同哈希合并、异哈希分开；误拒计入 abstention_on_determinate）",
          ok_dedup, f"v1={dv1['counts']} c3={dc3['counts']}")

    # ---------------- T12 帧农场报告
    farm = json.load(open(os.path.join(PROJECT_ROOT, "artifacts", "task-20", "phase0",
                                       "frame-farm-report.json"), encoding="utf-8"))
    ok = (farm["total_unique_frames"] == 184 and farm["byte_identical_count"] == 184
          and farm["mismatch_count"] == 0 and farm["missing_history_count"] == 0)
    check("T12", "帧农场 184 帧与 Task 19B 盘上帧逐字节一致", ok,
          f"identical={farm['byte_identical_count']}/{farm['total_unique_frames']}")

    # ---------------- T13 GT 隔离
    gt_keys = ("segments", "ground_truth", "gt_state", "label", "annotation")
    manifest_text = json.dumps(manifest, ensure_ascii=False)
    farm_text = json.dumps(farm, ensure_ascii=False)
    leaks = [k for k in gt_keys if k in manifest_text or k in farm_text]
    check("T13", "点清单/帧农场报告不含 GT 标签结构", not leaks, f"leaks={leaks}")

    # ---------------- 汇总
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    out = {"task": "task22-pairing-tests", "total": total, "passed": passed,
           "failed": total - passed, "all_passed": passed == total, "results": results}
    out_path = os.path.join(PROJECT_ROOT, "artifacts", "task-22", "test-results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"\nRESULT: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
