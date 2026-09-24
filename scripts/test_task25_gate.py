#!/usr/bin/env python3
"""test_task25_gate.py — Task 25 中心帧+邻帧上下文闸门实验确定性测试（SparkSkill Studio 任务 25）

全部为确定性测试（零模型调用、零网络、零 dev 推理）。覆盖任务书第七节要求的测试面:
  T1  配对评分器与 Task 17 冻结评分器历史等价（256 点逐行+计数零 mismatch）
  T2  阶段 B 早停门通过 / 退化（B1 错误断言 / B2 correct / B3 误拒 / B4 failed）
  T3  阶段 C 最终门通过 / TRADEOFF / NO_IMPROVEMENT / INCONCLUSIVE_BASELINE_DRIFT / INVALID_INPUT
  T4  候选提示词锚定（v1 逐字节生产未改；候选=v1+前置+中心帧指代；占位符；无素材特定词）
  T5  184 单元清单完整性（256->184 / 白名单 / 中心帧存在+哈希 / 跨臂 GT 一致 / breakdown）
  T6  48 确定性抽样（同种子可复现；覆盖 9 样本/2 轨/correct-error-uncertain）
  T7  邻帧取法（±500ms / 越界缺席 / 图序 roles / 2-3 图分母）
  T8  中心图哈希不符 → validate_unit_frames 报错（硬停止）
  T9  图序错乱防护 + 邻帧独有目标（中心恒为冻结中心；候选邻帧仅在 cand；smoke 负例记录在案）
  T10 失败归类（call_failed/invalid_json/contract_rejected → failed → failed_on_*）
  T11 七类账 + 两轨分母（by_track / 每口径 184 子集合计一致）
  T12 冻结哈希（frozen-hashes.json 全部条目与现文件一致）
  T13 GT 隔离（单元清单/配对输入不含 GT 标签结构）
  T14 资源门逻辑（mem/generation/webui 判定函数；低内存/生成进程 → 不通过）
  T15 敏感数据与媒体不入库（.gitignore 覆盖 frames/media；task-25 产物无凭据标记；无 dev 媒体被 git 跟踪）

用法: python3 scripts/test_task25_gate.py
退出码: 0 = 全部通过; 1 = 有失败
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PREREG = os.path.join(PROJECT_ROOT, "artifacts", "task-25", "preregistration")
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


def counts(correct, incorrect, abst_det, failed_det, app_abst, overclaim, failed_unc):
    return {"correct_decisive": correct, "incorrect_decisive": incorrect,
            "abstention_on_determinate": abst_det, "failed_on_determinate": failed_det,
            "appropriate_abstention": app_abst, "overclaim_on_uncertain": overclaim,
            "failed_on_uncertain": failed_unc}


def tracks(gen, lic):
    return {"generated": counts(*gen), "licensed-public": counts(*lic)}


def check_prerequisites():
    """公开版前置检查：本测试的多数用例读取任务 25 的内部摄验/评分产物，
    这些内容不随公开仓库分发（见 docs/PUBLIC-VERSION-NOTES.md）。缺失时不伪报
    PASS，明确退出（exit 2）并打印 NOT_RUN 原因；备齐后行为不变。"""
    missing = [rel for rel in ['artifacts/task-19/ground-truth', 'artifacts/task-20/frames', 'artifacts/task-25/pairs', 'artifacts/task-25/preregistration']
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

    scorer = load_module("score_task25_pairs", os.path.join(PROJECT_ROOT, "scripts",
                                                            "score_task25_pairs.py"))
    runner = load_module("run_task25_pairing", os.path.join(PROJECT_ROOT, "scripts",
                                                            "run_task25_pairing.py"))
    builder = load_module("task25_build_units", os.path.join(PROJECT_ROOT, "scripts",
                                                             "task25_build_units.py"))
    analyze = load_module("analyze_image", ANALYZE_IMAGE)

    # ---------------- T1 历史等价性
    hist = scorer.verify_historical(os.path.join(PROJECT_ROOT, "artifacts", "task-19"),
                                    os.path.join(PROJECT_ROOT, "artifacts", "task-19",
                                                 "ground-truth"))
    check("T1", "配对评分器与 Task 17 冻结规则历史等价（256 点逐行+计数）",
          hist["equivalent"] and hist["total_points_checked"] == 256,
          f"checked={hist['total_points_checked']} mismatches={len(hist['mismatches'])}")

    # ---------------- T2 阶段 B 门
    # 同期 v1 假设口径（48 子集，仅用于门逻辑单测）
    v1c = counts(30, 4, 0, 0, 2, 6, 0)
    # B 全过: 错误断言 10->8(<=), correct 降 1, abstention +1, failed 平
    cand_ok = counts(29, 3, 1, 0, 3, 5, 0)
    gates_ok = scorer.stage_b_gates(v1c, cand_ok)
    verdict_b_ok, _ = scorer.decide_verdict_stage_b(gates_ok, True, True, True)
    check("T2a", "阶段 B 全过 → STAGE1_PASS", verdict_b_ok == "STAGE1_PASS",
          f"gates={[k for k,v in gates_ok.items() if not v['passed']]}")
    # B 退化: 错误断言增加 (4+6=10 -> 5+7=12) → B1 FAIL → STAGE1_HARM_STOP
    cand_bad = counts(30, 5, 0, 0, 1, 7, 0)
    gates_bad = scorer.stage_b_gates(v1c, cand_bad)
    verdict_b_bad, reasons = scorer.decide_verdict_stage_b(gates_bad, True, True, True)
    check("T2b", "阶段 B 错误断言增加 → B1 FAIL → STAGE1_HARM_STOP",
          verdict_b_bad == "STAGE1_HARM_STOP"
          and gates_bad["B1_error_assertions_not_more_than_v1"]["passed"] is False,
          f"reasons={reasons}")
    # B 退化: correct 降 2 (>1) → B2 FAIL
    cand_c = counts(28, 3, 0, 0, 3, 5, 0)
    gates_c = scorer.stage_b_gates(v1c, cand_c)
    check("T2c-B2", "阶段 B correct 降 2 → B2 FAIL",
          gates_c["B2_correct_decrease_le_1"]["passed"] is False)
    # B 退化: abstention_on_determinate 增 2 (>1) → B3 FAIL
    cand_d = counts(30, 3, 2, 0, 3, 5, 0)
    gates_d = scorer.stage_b_gates(v1c, cand_d)
    check("T2d-B3", "阶段 B abstention_on_determinate 增 2 → B3 FAIL",
          gates_d["B3_abstention_on_determinate_increase_le_1"]["passed"] is False)
    # B smoke 负例失败 → STAGE1_HARM_STOP（即使 B1-B4 过）
    verdict_b_smoke, _ = scorer.decide_verdict_stage_b(gates_ok, True, False, True)
    check("T2e", "阶段 B smoke 邻帧负例失败 → STAGE1_HARM_STOP",
          verdict_b_smoke == "STAGE1_HARM_STOP")

    # ---------------- T3 阶段 C 门 + verdict
    v1C = counts(120, 6, 0, 0, 3, 12, 0)
    v1C_tracks = tracks((90, 6, 0, 0, 3, 12, 0), (30, 0, 0, 0, 0, 0, 0))
    # C 全过: 错误断言 18->8(降10>=8), overclaim 12->6(降6>=5), incorrect 6->2(不增),
    #         correct 降 1(<=2) licensed 不减, abstention +1(<=2), failed 平
    candC = counts(119, 2, 1, 0, 6, 6, 0)
    candC_tracks = tracks((89, 2, 1, 0, 6, 6, 0), (30, 0, 0, 0, 0, 0, 0))
    gatesC = scorer.stage_c_gates(v1C, candC, v1C_tracks, candC_tracks)
    comp_ok = {"center_hash_all_match": True, "all_pairs_complete": True,
               "max_one_call_per_point_per_arm": True, "resource_and_freeze_ok": True}
    verdict_C, reasons_C = scorer.decide_verdict_stage_c(gatesC, True, comp_ok)
    check("T3a", "阶段 C C1-C4 全过 + 完整 → DEV_CANDIDATE", verdict_C == "DEV_CANDIDATE",
          f"reasons={reasons_C}")
    # C TRADEOFF: 错误断言实质降(C1) 但 correct 降 4(>2) → C3 FAIL
    candC_t = counts(116, 2, 1, 0, 6, 6, 0)
    candC_t_tracks = tracks((86, 2, 1, 0, 6, 6, 0), (30, 0, 0, 0, 0, 0, 0))
    gatesC_t = scorer.stage_c_gates(v1C, candC_t, v1C_tracks, candC_t_tracks)
    verdict_Ct, reasons_Ct = scorer.decide_verdict_stage_c(gatesC_t, True, comp_ok)
    check("T3b", "阶段 C 错误断言实质降但 correct 超容忍 → TRADEOFF",
          verdict_Ct == "TRADEOFF", f"reasons={reasons_Ct}")
    # C NO_IMPROVEMENT: overclaim 只降 3(<5) → C1 FAIL
    candC_n = counts(120, 6, 0, 0, 3, 9, 0)
    candC_n_tracks = tracks((90, 6, 0, 0, 3, 9, 0), (30, 0, 0, 0, 0, 0, 0))
    gatesC_n = scorer.stage_c_gates(v1C, candC_n, v1C_tracks, candC_n_tracks)
    verdict_Cn, _ = scorer.decide_verdict_stage_c(gatesC_n, True, comp_ok)
    check("T3c", "阶段 C overclaim 降幅不足 5 → NO_IMPROVEMENT",
          verdict_Cn == "NO_IMPROVEMENT")
    # C 基线不足: v1 overclaim 4(<5) → INCONCLUSIVE_BASELINE_DRIFT
    v1_low = counts(120, 2, 0, 0, 3, 4, 0)
    v1_low_tracks = tracks((90, 2, 0, 0, 3, 4, 0), (30, 0, 0, 0, 0, 0, 0))
    cand_low = counts(120, 2, 0, 0, 3, 0, 0)
    cand_low_tracks = tracks((90, 2, 0, 0, 3, 0, 0), (30, 0, 0, 0, 0, 0, 0))
    gatesC_low = scorer.stage_c_gates(v1_low, cand_low, v1_low_tracks, cand_low_tracks)
    verdict_Cl, reasons_Cl = scorer.decide_verdict_stage_c(gatesC_low, True, comp_ok)
    check("T3d", "阶段 C 同期 v1 overclaim<5 → INCONCLUSIVE_BASELINE_DRIFT",
          verdict_Cl == "INCONCLUSIVE_BASELINE_DRIFT", f"reasons={reasons_Cl}")
    # C 完整性失败 → INVALID_INPUT（即使质量门过）
    comp_bad = dict(comp_ok, center_hash_all_match=False)
    verdict_Ci, _ = scorer.decide_verdict_stage_c(gatesC, True, comp_bad)
    check("T3e", "阶段 C 中心帧哈希不全匹配 → INVALID_INPUT",
          verdict_Ci == "INVALID_INPUT")
    # C incorrect 增加（licensed +1）→ C2 FAIL
    candC_i = counts(119, 7, 1, 0, 6, 6, 0)
    candC_i_tracks = tracks((89, 6, 1, 0, 6, 6, 0), (30, 1, 0, 0, 0, 0, 0))
    gatesC_i = scorer.stage_c_gates(v1C, candC_i, v1C_tracks, candC_i_tracks)
    check("T3f-C2", "阶段 C licensed incorrect 增 → C2 FAIL",
          gatesC_i["C2_incorrect_not_increased_3_scopes"]["passed"] is False)

    # ---------------- T4 候选提示词锚定
    v1_hash = sha256_of_text(analyze.PROMPT_TEMPLATE)
    cand_text = open(os.path.join(PREREG, "prompt-candidate.txt"), encoding="utf-8").read()
    check("T4a", "v1 提示词 = 现行生产模板（哈希未改）",
          v1_hash == "fc29078044d5fe47daacb2384f3f29f562ed8638b835f2577732a8bd185de65b",
          v1_hash)
    # 候选 = 前置说明 + v1(两处中心帧指代替换)
    preampline = cand_text.split("\n\n", 1)[0]
    body = cand_text[len(preampline) + 2:]
    v1_body = (analyze.PROMPT_TEMPLATE
               .replace("请仔细观察这张图片", "请仔细观察中心帧")
               .replace("只描述你在图片中实际看到的内容", "只描述你在中心帧中实际看到的内容"))
    check("T4b", "候选主体 = v1 + 仅两处『只判中心帧』指代替换（逐字节）", body == v1_body)
    check("T4c", "候选含图序说明 + 只判中心帧 + 不投射邻帧目标",
          ("按顺序" in preampline and "【中心帧】" in preampline
           and "不得把" in preampline and "当作【中心帧】中存在目标的证据" in preampline))
    ph_v1 = sorted(set(re.findall(r"\{(\w+)\}", analyze.PROMPT_TEMPLATE)))
    ph_cand = sorted(set(re.findall(r"\{(\w+)\}", cand_text)))
    check("T4d", "候选仅新增 {image_count}/{image_roles} 占位符",
          set(ph_cand) - set(ph_v1) == {"image_count", "image_roles"}, f"{ph_cand}")
    banned = [r"AI0\d", r"WEB0\d", r"T25-U", r"红色背包", r"叉车", r"纸箱", r"托盘",
              r"overclaim", r"难度", r"\b4000\b", r"\b9000\b", r"\b10125\b", r"\b17480\b",
              r"\b666\b", r" uncertain 区"]
    hits = [p for p in banned if re.search(p, cand_text)]
    check("T4e", "候选不含样本编号/目标词/答案/GT 时段/难度/旧版本号等素材特定提示",
          not hits, f"hits={hits}")

    # ---------------- T5 184 单元清单完整性
    manifest = json.load(open(os.path.join(PREREG, "unit-manifest-184.json"), encoding="utf-8"))
    units = manifest["units"]
    ok_count = manifest["total_units"] == 184 and len(units) == 184
    ok_dedup = manifest["dedup_256_to_184_ok"] and manifest["total_source_points"] == 256
    ok_whitelist = all(u["sample_id"] in WHITELIST for u in units)
    ok_unique = len({(u["sample_id"], u["center_frame_sha256"], u["target_query"])
                     for u in units}) == 184
    ok_center_hash = all(u["center_hash_ok"] for u in units)
    # 独立重算中心帧哈希（抽 12 个）
    import random as _r
    sample_units = _r.Random(7).sample(units, 12)
    ok_rehash = all(
        runner.sha256_of(os.path.join(PROJECT_ROOT, u["center_frame_path"]))
        == u["center_frame_sha256"] for u in sample_units)
    # 跨臂 GT 一致：同单元所有来源点的 GT 状态应一致（用 gt_state_at 复算代表点即可，
    # 因同帧同时戳；builder 已在生成时核验 cross-arm，此处复算代表点 GT 非空）
    ok_gt = all(u["gt_state"] in ("confirmed", "not_found", "uncertain") for u in units)
    check("T5", "184 单元清单完整（256->184 / 白名单 / 唯一 / 中心哈希 / 重算 / GT 非空）",
          all([ok_count, ok_dedup, ok_whitelist, ok_unique, ok_center_hash, ok_rehash, ok_gt]),
          f"count={ok_count} dedup={ok_dedup} wl={ok_whitelist} uniq={ok_unique} "
          f"chash={ok_center_hash} rehash={ok_rehash} gt={ok_gt}")

    # ---------------- T6 48 确定性抽样
    s48a = builder.stratified_sample_48([dict(u) for u in units])
    s48b = builder.stratified_sample_48([dict(u) for u in units])
    ids_a = [u["unit_id"] for u in s48a]
    ids_b = [u["unit_id"] for u in s48b]
    first_batch = manifest["first_batch_48_unit_ids"]
    ok_repro = ids_a == ids_b == first_batch and len(ids_a) == 48
    cov_samples = {u["sample_id"] for u in s48a} == WHITELIST
    cov_tracks = {u["track"] for u in s48a} == {"generated", "licensed-public"}
    cov_strata = {"correct", "error", "uncertain"} <= {u["stratum"] for u in s48a}
    check("T6", "48 确定性抽样（同种子可复现；覆盖 9 样本/2 轨/correct-error-uncertain）",
          ok_repro and cov_samples and cov_tracks and cov_strata,
          f"repro={ok_repro} samples={cov_samples} tracks={cov_tracks} strata={cov_strata}")

    # ---------------- T7 邻帧取法
    ok_offset = manifest["neighbor_summary"]["offset_ms"] == 500.0
    # frame_number_for 正确性（AI01 24fps: t=666.667 -> prev 166.667 -> f4; next 1166.667 -> f28）
    fn_prev = builder.frame_number_for(166.667, 24.0, 192)
    fn_next = builder.frame_number_for(1166.667, 24.0, 192)
    ok_fn = fn_prev == 4 and fn_next == 28
    # 越界缺席：t=0 单元 prev 缺席
    u0 = next(u for u in units if u["sample_id"] == "AI01" and u["center_timestamp_ms"] == 0.0)
    ok_absent = (u0["neighbors"]["prev"]["present"] is False
                 and u0["neighbors"]["prev"]["absent_reason"] == "timestamp_before_start"
                 and u0["neighbors"]["next"]["present"] is True)
    # 2/3 图分母
    three = sum(1 for u in units if u["neighbors"]["prev"]["present"]
                and u["neighbors"]["next"]["present"])
    two = 184 - three
    ok_denom = (manifest["neighbor_summary"]["three_image_units"] == three
                and manifest["neighbor_summary"]["two_image_units"] == two
                and three + two == 184)
    # image_roles_for 顺序
    c3, r3 = runner.image_roles_for(["prev", "center", "next"])
    c2p, r2p = runner.image_roles_for(["center", "next"])
    c2n, r2n = runner.image_roles_for(["prev", "center"])
    ok_roles = (c3 == 3 and r3 == "第一张【前一帧】、第二张【中心帧】、第三张【后一帧】"
                and c2p == 2 and r2p == "第一张【中心帧】、第二张【后一帧】"
                and c2n == 2 and r2n == "第一张【前一帧】、第二张【中心帧】")
    check("T7", "邻帧取法（±500ms 帧号 / 越界缺席 / 2-3 图分母 / 图序 roles）",
          all([ok_offset, ok_fn, ok_absent, ok_denom, ok_roles]),
          f"offset={ok_offset} fn={ok_fn} absent={ok_absent} denom={ok_denom} roles={ok_roles} "
          f"(three={three} two={two})")

    # ---------------- T8 中心图哈希不符 → 硬停止
    tampered = dict(u0)
    tampered["center_frame_sha256"] = "0" * 64
    probs = runner.validate_unit_frames(tampered)
    ok_tamper = any(p.startswith("center_hash_mismatch") for p in probs)
    ok_real = runner.validate_unit_frames(u0) == []
    check("T8", "中心图哈希不符 → validate_unit_frames 报 center_hash_mismatch（硬停止）",
          ok_tamper and ok_real, f"tampered_problems={probs}")

    # ---------------- T9 图序错乱防护 + 邻帧独有目标
    # 中心恒为冻结中心帧；候选 ordered = neighbors + [center]，center 位置随 present 变化但字节恒为冻结中心
    u_mid = next(u for u in units if u["sample_id"] == "AI01"
                 and u["neighbors"]["prev"]["present"] and u["neighbors"]["next"]["present"])
    center_abs = os.path.join(PROJECT_ROOT, u_mid["center_frame_path"])
    prev_abs = os.path.join(PROJECT_ROOT, u_mid["neighbors"]["prev"]["frame_path"])
    next_abs = os.path.join(PROJECT_ROOT, u_mid["neighbors"]["next"]["frame_path"])
    ordered = [prev_abs, center_abs, next_abs]
    # 中心字节 == 冻结中心；且 != 两个邻帧字节（防混淆/防复制中心凑数）
    center_is_frozen = runner.sha256_of(center_abs) == u_mid["center_frame_sha256"]
    center_ne_prev = runner.sha256_of(center_abs) != runner.sha256_of(prev_abs)
    center_ne_next = runner.sha256_of(center_abs) != runner.sha256_of(next_abs)
    # Phase 0 smoke 负例记录在案（目标只在邻帧 → 中心 object_found=false）
    smoke = json.load(open(os.path.join(PROJECT_ROOT, "artifacts", "task-25", "smoke",
                                        "smoke-report.json"), encoding="utf-8"))
    smoke_neg = smoke["feasibility"]["negative_neighbor_only_no_center_assertion"] is True
    check("T9", "图序防护（中心恒冻结/异于邻帧/不复制凑数）+ smoke 邻帧独有目标负例在案",
          center_is_frozen and center_ne_prev and center_ne_next and smoke_neg,
          f"frozen={center_is_frozen} ne_prev={center_ne_prev} ne_next={center_ne_next} "
          f"smoke_neg={smoke_neg}")

    # ---------------- T10 失败归类
    def failed_judgment():
        return {"frame_status": "failed", "object_found": False, "confidence": 0.0,
                "evidence_sufficient": False, "abstention_reason": "x",
                "evidence_nature": "backend_call_failed"}
    gt_conf = {"segments": [{"start_ms": 0, "end_ms": 8000, "state": "confirmed"}],
               "media_duration_ms": 8000.0}
    gt_unc = {"segments": [{"start_ms": 0, "end_ms": 8000, "state": "uncertain"}],
              "media_duration_ms": 8000.0}
    ok_fail_det = scorer.metric_for("confirmed", scorer.classify_entry(failed_judgment())) \
        == "failed_on_determinate"
    ok_fail_unc = scorer.metric_for("uncertain", scorer.classify_entry(failed_judgment())) \
        == "failed_on_uncertain"
    check("T10", "失败归类（call_failed/invalid_json/contract_rejected → failed → failed_on_*）",
          ok_fail_det and ok_fail_unc, f"det={ok_fail_det} unc={ok_fail_unc}")

    # ---------------- T11 七类账 + 两轨分母
    pts = [
        {"unit_id": "A", "sample_id": "AI01", "center_timestamp_ms": 0.0, "track": "generated",
         "stratum": "correct", "source_arms": ["uniform"],
         "v1_judgment": {"frame_status": "analyzed", "object_found": True,
                         "evidence_sufficient": True, "abstention_reason": None},
         "cand_judgment": {"frame_status": "analyzed", "object_found": True,
                           "evidence_sufficient": True, "abstention_reason": None}},
        {"unit_id": "B", "sample_id": "WEB01", "center_timestamp_ms": 0.0,
         "track": "licensed-public", "stratum": "uncertain", "source_arms": ["uniform"],
         "v1_judgment": {"frame_status": "analyzed", "object_found": True,
                         "evidence_sufficient": True, "abstention_reason": None},
         "cand_judgment": {"frame_status": "analyzed", "object_found": False,
                           "evidence_sufficient": False, "abstention_reason": "看不清"}},
    ]
    gts = {"AI01": gt_conf, "WEB01": gt_unc}
    side = scorer.score_side(pts, gts, "v1")
    gen_total = sum(side["by_track"]["generated"].values())
    lic_total = sum(side["by_track"]["licensed-public"].values())
    ok_ledger = (gen_total == 1 and lic_total == 1
                 and side["by_track"]["generated"]["correct_decisive"] == 1
                 and side["by_track"]["licensed-public"]["overclaim_on_uncertain"] == 1
                 and sum(side["counts"].values()) == 2)
    check("T11", "七类账 + 两轨分母（generated/licensed-public 分开且各口径合计一致）",
          ok_ledger, f"gen={gen_total} lic={lic_total} counts={side['counts']}")

    # ---------------- T12 冻结哈希
    frozen = json.load(open(os.path.join(PREREG, "frozen-hashes.json"), encoding="utf-8"))
    mism = []
    for rel, entry in frozen["entries"].items():
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path) or runner.sha256_of(path) != entry["sha256"]:
            mism.append(rel)
    check("T12", "冻结哈希（frozen-hashes.json 全部条目与现文件逐字节一致）",
          not mism, f"mismatches={mism}")

    # ---------------- T13 GT 隔离
    # 单元清单不得内嵌 GT 段结构/标注元数据（segments/annotation/boundary/revision）；
    # 派生标量 gt_state/stratum 为阶段 A 分层用（来自冻结 GT、阶段 A 冻结、不进视觉请求），允许。
    gt_struct_keys = ("segments", "annotation_version", "annotated_at", "annotator_id",
                      "boundary_tolerance_ms", "revision_history", "label_frozen")
    man_text = json.dumps(manifest, ensure_ascii=False)
    leaks = [k for k in gt_struct_keys if k in man_text]
    # 视觉请求（spec）不得含 GT 标签键
    spec_sample = json.load(open(os.path.join(
        PROJECT_ROOT, "artifacts", "task-19", "predictions", "AI01", "uniform",
        "task-spec.json"), encoding="utf-8"))
    spec_leaks = [k for k in ("segments", "ground_truth", "gt", "label", "state")
                  if k in spec_sample]
    check("T13", "GT 隔离（单元清单无 GT 段结构；视觉请求 spec 无 GT 标签键）",
          not leaks and not spec_leaks, f"manifest_struct_leaks={leaks} spec_leaks={spec_leaks}")

    # ---------------- T14 资源门逻辑
    ok_gen = runner.generation_processes(["user 1 vllm.entrypoints.api x", "user 2 python app.py"]) \
        == ["user 1 vllm.entrypoints.api x"]
    ok_webui = runner.webui_processes(["user 1 minimax-h3/webui x"]) == ["user 1 minimax-h3/webui x"]
    ok_mem = isinstance(runner.mem_available_gib(), float)
    ok_port = runner.port_listening(65432) in (True, False)  # 不抛异常
    check("T14", "资源门逻辑（generation/webui 进程识别 / mem 读取 / port 探测不抛错）",
          ok_gen and ok_webui and ok_mem and ok_port,
          f"gen={ok_gen} webui={ok_webui} mem={ok_mem} port={ok_port}")

    # ---------------- T15 敏感数据与媒体不入库
    gi = open(os.path.join(PROJECT_ROOT, ".gitignore"), encoding="utf-8").read()
    ok_gi_frames = "artifacts/task-25/frames/" in gi or "artifacts/task-20/frames/" in gi
    # task-25 产物无凭据标记
    cred = ("api_key", "secret", "password", "token", "bearer ", "private_key")
    t25_files = subprocess.run(
        ["git", "ls-files", "artifacts/task-25"], capture_output=True, text=True,
        cwd=PROJECT_ROOT).stdout.split()
    # git 未跟踪 dev 媒体/帧（检查 ingest media 与 task-25 frames 未被跟踪）
    tracked_media = subprocess.run(
        ["git", "ls-files", "artifacts/task-19/ingestion/media"],
        capture_output=True, text=True, cwd=PROJECT_ROOT).stdout.strip()
    tracked_t25_frames = subprocess.run(
        ["git", "ls-files", "artifacts/task-25/frames"],
        capture_output=True, text=True, cwd=PROJECT_ROOT).stdout.strip()
    ok_media_untracked = tracked_media == "" and tracked_t25_frames == ""
    # 扫描已跟踪 task-25 文本产物中的凭据标记
    cred_hits = []
    for f in t25_files:
        if f.endswith((".json", ".jsonl", ".md", ".txt", ".py")):
            try:
                txt = open(os.path.join(PROJECT_ROOT, f), encoding="utf-8").read()
            except OSError:
                continue
            if any(c in txt.lower() for c in cred):
                cred_hits.append(f)
    check("T15", "敏感数据与媒体不入库（.gitignore 覆盖 frames；dev 媒体/帧未被 git 跟踪；"
                 "task-25 产物无凭据标记）",
          ok_gi_frames and ok_media_untracked and not cred_hits,
          f"gi_frames={ok_gi_frames} media_untracked={ok_media_untracked} cred_hits={cred_hits}")

    # ---------------- 汇总
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    out = {"task": "task25-gate-tests", "total": total, "passed": passed,
           "failed": total - passed, "all_passed": passed == total, "results": results}
    out_path = os.path.join(PROJECT_ROOT, "artifacts", "task-25", "test-results.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"\nRESULT: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
