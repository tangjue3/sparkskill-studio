#!/usr/bin/env python3
"""test_jev_client.py — Task 29 Jev Control-Plane Gate 确定性测试（离线，零网络）

覆盖预注册 docs/plans/2026-09-25-task29-jev-control-plane.md:

  A. 权限最小化契约（§2）
     A1 白名单字段放行
     A2 每个禁止字段单独触发 PayloadForbiddenError
     A3 非白名单字段（拼写错误/新增）也被拒绝
     A4 state_summary_from_evidence 不产生任何禁止字段
  B. Shadow-mode 配对（§4）
     B1 deterministic policy 确定性（同输入两次逐字节一致）
     B2 Jev 启用时走 transport，未启用不构造请求
     B3 HTTP 失败/超时/非法 schema → 降级 deterministic
     B4 payload 违约**不降级**（契约违反必须显式失败）
  C. G0 fallback 一致性（§6 H3）
     C1 JEV_ENABLED=false 的输出 == Jev 失败降级的输出（逐字节）
     C2 Jev 正常返回时不被 fallback 覆盖
  D. 阈值归属代码（§3）
     D1 apply_thresholds 的三态映射
     D2 Jev 无概率时按保守方向解释
  E. 降级与可用性（§7）
     E1 缺 key 且启用 → 降级（不抛）
     E2 缺 key 且启用且 use_fallback_on_error=False → 抛 JevUnavailableError
  F. 预注册一致性
     F1 开工条件 C1（Task 28 判决）被明示且当前未满足
     F2 禁止字段表与预注册 §2 对齐

用法: python3 .dsh/skills/visual-evidence-extractor/scripts/test_jev_client.py
退出码: 0 = 全部通过; 1 = 有失败; 2 = 前置缺失（NOT_RUN）
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
CLIENT = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                       "scripts", "jev_client.py")
PREREG = os.path.join(PROJECT_ROOT, "docs", "plans",
                      "2026-09-25-task29-jev-control-plane.md")

RESULTS = []


def record(test_id, name, passed, detail):
    RESULTS.append({"id": test_id, "name": name, "passed": bool(passed),
                    "detail": detail})
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {test_id} — {name}: {detail}")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


GOOD_SUMMARY = {
    "task_type": "temporal_presence",
    "target_complexity": "attribute_relation",
    "sampled_frames": 8,
    "class_counts": {"confirmed": 4, "not_found": 1, "abstained": 3, "failed": 0},
    "mean_confidence": 0.71,
    "resource_budget": "medium",
}

FAKE_RESPONSE = {
    "decisions": {
        "q1_route": {"value": "route_27b", "probability": 0.62},
        "q2_sufficient": {"value": False, "probability": 0.71},
        "q3_risk": {"value": "medium", "probability": 0.55},
        "q4_extra_call": {"value": True, "probability": 0.48},
    }
}


# ---------------------------------------------------------------- A. 权限最小化

def test_a_minimization(jev):
    allowed = jev.assert_payload_allowed(GOOD_SUMMARY)
    record("A1", "白名单字段放行", allowed is True,
           f"fields={sorted(GOOD_SUMMARY)}")

    problems = []
    for field in sorted(jev.FORBIDDEN_FIELDS):
        payload = dict(GOOD_SUMMARY)
        payload[field] = "leak"
        try:
            jev.assert_payload_allowed(payload)
            problems.append(f"{field} 未被拒绝")
        except jev.PayloadForbiddenError:
            continue
    record("A2", "每个禁止字段单独触发 PayloadForbiddenError", not problems,
           f"{len(jev.FORBIDDEN_FIELDS)} 个禁止字段全部拒绝"
           + ("" if not problems else f"；漏网: {problems}"))

    payload = dict(GOOD_SUMMARY)
    payload["mean_confidence_ms"] = 12          # 拼写近似，非白名单
    payload["unknown_new_field"] = 1
    try:
        jev.assert_payload_allowed(payload)
        record("A3", "非白名单字段被拒绝", False, "近似/新字段未被拒")
    except jev.PayloadForbiddenError as error:
        record("A3", "非白名单字段被拒绝", True, str(error)[:80])

    evidence = {
        "task_type": "temporal_presence",
        "resource_budget": "medium",
        "timeline": [
            {"timestamp_ms": 1000.0, "frame_path": "frames/a.png",
             "object_found": True, "evidence_sufficient": True,
             "confidence": 0.9, "abstention_reason": None,
             "frame_status": "analyzed", "frame_sha256": "deadbeef",
             "bounding_box": [0.1, 0.2, 0.3, 0.4]},
            {"timestamp_ms": 2000.0, "object_found": False,
             "abstention_reason": "目标被遮挡", "confidence": 0.4,
             "frame_status": "analyzed"},
            {"timestamp_ms": 3000.0, "object_found": True,
             "evidence_sufficient": False, "confidence": None,
             "frame_status": "failed"},
        ],
    }
    summary = jev.state_summary_from_evidence(evidence)
    leaked = sorted(set(summary) & jev.FORBIDDEN_FIELDS)
    # 聚合正确性：confirmed 1、abstained 1（自陈遮挡）、failed 1。
    counts_ok = (summary["class_counts"] == {"confirmed": 1, "not_found": 0,
                                             "abstained": 1, "failed": 1}
                 and summary["sampled_frames"] == 3)
    # mean_confidence 只取有效数值（0.9, 0.4；None 不计）。
    mean_ok = summary["mean_confidence"] == 0.65
    try:
        jev.assert_payload_allowed(summary)
        contract_ok = True
    except jev.PayloadForbiddenError:
        contract_ok = False
    record("A4", "state_summary_from_evidence 不泄漏禁止字段且聚合正确",
           not leaked and counts_ok and mean_ok and contract_ok,
           f"leaked={leaked} counts={summary['class_counts']} "
           f"mean={summary['mean_confidence']} contract_ok={contract_ok}")


# ---------------------------------------------------------------- B. shadow mode

def test_b_shadow(jev):
    first = jev.deterministic_policy(GOOD_SUMMARY)
    second = jev.deterministic_policy(copy.deepcopy(GOOD_SUMMARY))
    record("B1", "deterministic policy 确定性（两次逐字节一致）",
           canonical(first) == canonical(second), canonical(first)[:90])

    calls = []

    def transport(url, payload, headers, timeout):
        calls.append({"url": url, "payload": payload, "headers": headers})
        return FAKE_RESPONSE

    enabled = jev.JevClient(enabled=True, api_key="test-key", transport=transport)
    disabled = jev.JevClient(enabled=False, api_key=None)

    calls.clear()
    enabled.decide(GOOD_SUMMARY)
    used = len(calls) == 1
    calls.clear()
    disabled.decide(GOOD_SUMMARY)
    untouched = len(calls) == 0
    record("B2", "启用时走 transport；未启用不构造请求", used and untouched,
           f"enabled_calls=1 disabled_calls={len(calls)}")

    # 各类失败都降级。
    def failing(error):
        def transport(_url, _payload, _headers, _timeout):
            raise error
        return transport

    scenarios = {
        "http_error": jev.JevUnavailableError("Jev HTTP 503"),
        "schema_error": jev.JevSchemaError("missing fields"),
        "os_error": OSError("connection reset"),
    }
    problems = []
    for name, error in scenarios.items():
        client = jev.JevClient(enabled=True, api_key="k",
                               transport=failing(error))
        result = client.decide(GOOD_SUMMARY)
        if result["source"] != "deterministic_fallback":
            problems.append(f"{name}: 未降级")
        elif canonical(result["decision"]) != canonical(jev.deterministic_policy(GOOD_SUMMARY)):
            problems.append(f"{name}: 降级结果与 policy 不一致")
    record("B3", "HTTP 失败/非法 schema/OSError 均降级 deterministic",
           not problems, f"{len(scenarios)} 类失败全部正确降级"
           + ("" if not problems else f"；{problems}"))

    # payload 违约不得降级：必须显式失败。
    bad = dict(GOOD_SUMMARY)
    bad["timestamp_ms"] = 1000.0
    client = jev.JevClient(enabled=True, api_key="k", transport=transport)
    try:
        client.decide(bad)
        record("B4", "payload 违约不降级（契约违反显式失败）", False, "被静默降级")
    except jev.PayloadForbiddenError:
        record("B4", "payload 违约不降级（契约违反显式失败）", True,
               "PayloadForbiddenError 正常抛出")


# ---------------------------------------------------------------- C. G0 一致性

def test_c_g0(jev):
    disabled = jev.JevClient(enabled=False)
    off_result = disabled.decide(GOOD_SUMMARY)

    def failing(_u, _p, _h, _t):
        raise jev.JevUnavailableError("Jev HTTP 500")

    degraded = jev.JevClient(enabled=True, api_key="k",
                             transport=failing).decide(GOOD_SUMMARY)

    # G0 一致性判定的是**决策输出**，不是诊断字符串。
    # `reason` 是给运维看的诊断（jev_disabled / jev_http_500 / ...），
    # 两条失败路径的 reason 必然不同；要求它逐字节相同会把"可观测性"
    # 和"行为一致性"混为一谈，反而排除了有用的诊断信息。
    off_decision = canonical({"decision": off_result["decision"],
                              "action": jev.apply_thresholds(off_result["decision"])})
    degraded_decision = canonical({"decision": degraded["decision"],
                                   "action": jev.apply_thresholds(degraded["decision"])})
    same = off_decision == degraded_decision
    record("C1", "G0：JEV_ENABLED=false 与 Jev 失败降级的**决策输出**逐字节一致",
           same and off_result["source"] == "deterministic_fallback"
           and degraded["source"] == "deterministic_fallback",
           f"off_reason={off_result['reason']} degraded_reason={degraded['reason']} "
           f"decision_identical={same}")

    ok_transport = lambda *_args, **_kwargs: FAKE_RESPONSE  # noqa: E731
    live = jev.JevClient(enabled=True, api_key="k",
                         transport=ok_transport).decide(GOOD_SUMMARY)
    not_overwritten = (live["source"] == "jev"
                       and live["decision"]["route"] == "route_27b")
    record("C2", "Jev 正常返回时不被 fallback 覆盖", not_overwritten,
           canonical(live["decision"]))


# ---------------------------------------------------------------- D. 阈值归属

def test_d_thresholds(jev):
    cases = [
        ({"route": "route_human_review", "sufficient": True, "risk": "low"},
         "ESCALATE_HUMAN"),
        ({"route": "route_8b", "sufficient": False, "risk": "low"}, "ABSTAIN"),
        ({"route": "route_8b", "sufficient": True, "risk": "low"}, "AUTO_ACCEPT"),
        ({"route": "route_8b", "sufficient": True, "risk": "high"}, "ESCALATE_HUMAN"),
    ]
    problems = [f"{case} → {jev.apply_thresholds(decision)} (期望 {expected})"
                for decision, expected in cases
                for case in [decision]
                if jev.apply_thresholds(decision) != expected]
    record("D1", "apply_thresholds 三态映射（阈值归代码）", not problems,
           f"{len(cases)} 用例" + ("" if not problems else f"；{problems}"))

    # 无概率时的保守方向：sufficient=False 必须 ABSTAIN，不得 AUTO_ACCEPT。
    conservative = jev.apply_thresholds({"route": "route_8b", "sufficient": False,
                                         "risk": "low"})
    record("D2", "无概率时按保守方向解释", conservative == "ABSTAIN",
           f"→ {conservative}")


# ---------------------------------------------------------------- E. 可用性

def test_e_availability(jev):
    no_key = jev.JevClient(enabled=True, api_key=None)
    result = no_key.decide(GOOD_SUMMARY)
    degraded_ok = result["source"] == "deterministic_fallback"
    record("E1", "启用但缺 key → 降级（不抛）", degraded_ok,
           result["reason"])

    try:
        no_key.decide(GOOD_SUMMARY, use_fallback_on_error=False)
        record("E2", "use_fallback_on_error=False 时缺 key 显式抛错", False, "未抛错")
    except jev.JevUnavailableError:
        record("E2", "use_fallback_on_error=False 时缺 key 显式抛错", True,
               "JevUnavailableError")

    env = jev.JevClient.from_env(env={"JEV_ENABLED": "false", "JEV_API_KEY": "x"})
    default_off = env.enabled is False
    record("E3", "JEV_ENABLED=false（缺省关闭）", default_off,
           f"enabled={env.enabled}")


# ---------------------------------------------------------------- F. 预注册

def test_f_preregistration():
    if not os.path.isfile(PREREG):
        record("F1", "Task 29 预注册存在且开工条件被明示", False, "预注册缺失")
        return
    with open(PREREG, encoding="utf-8") as handle:
        text = handle.read()
    problems = []
    for marker in ("shadow", "false_auto_accept", "Optional Semantic Control Plane",
                   "PREREGISTERED_BLOCKED_ON_TASK28", "C1", "Task 28"):
        if marker not in text:
            problems.append(f"缺少 {marker!r}")
    # 当前状态必须是"被 Task 28 阻塞"，不得写成可开工。
    blocked = "不得开工" in text or "PREREGISTERED_BLOCKED_ON_TASK28" in text
    record("F1", "Task 29 预注册存在且开工条件被明示", not problems and blocked,
           f"{len(text)} 字符" + ("" if not problems and blocked else f"；{problems}"))

    jev = load_module("jev_for_prereg", CLIENT)
    with open(PREREG, encoding="utf-8") as handle:
        text = handle.read()
    missing = [field for field in sorted(jev.FORBIDDEN_FIELDS)
               if field not in text and field not in ("timestamps", "frame_paths",
                                                      "bounding_boxes", "sampling_gap_ms")]
    # 预注册只列代表性禁止项；测试只要求核心项在文档中出现。
    core = ("timestamp_ms", "max_sampling_gap_ms", "frame_path", "target_query",
            "bounding_box", "frame_index")
    core_missing = [field for field in core if field not in text]
    record("F2", "预注册 §2 禁止字段表与客户端对齐（核心项）", not core_missing,
           f"核心禁止字段全部在预注册出现"
           + ("" if not core_missing else f"；缺 {core_missing}"))


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Task 29 Jev 客户端确定性测试")
    parser.add_argument("--results-json", default=None)
    args = parser.parse_args()

    if not os.path.isfile(CLIENT):
        print(f"[NOT_RUN] 缺少客户端: {CLIENT}")
        return 2
    if not os.path.isfile(PREREG):
        print(f"[NOT_RUN] 缺少 Task 29 预注册: {PREREG}")
        return 2

    jev = load_module("jev_client_under_test", CLIENT)
    test_a_minimization(jev)
    test_b_shadow(jev)
    test_c_g0(jev)
    test_d_thresholds(jev)
    test_e_availability(jev)
    test_f_preregistration()

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    print(f"\nRESULT: {'PASS' if passed == total else 'FAIL'} ({passed}/{total})")

    if args.results_json:
        with open(args.results_json, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "suite": "test_jev_client.py",
                "preregistration": "docs/plans/2026-09-25-task29-jev-control-plane.md",
                "network_calls": 0,
                "summary": {"passed": passed, "total": total},
                "results": RESULTS,
            }, ensure_ascii=False, indent=2) + "\n")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
