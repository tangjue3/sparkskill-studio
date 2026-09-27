#!/usr/bin/env python3
"""state_resolver.py — 证据状态解析器（SparkSkill Studio Task 28 · State Expressiveness Gate）

把模型既有输出字段解析成**显式的三态观测 + 正交的不确定原因**：

    ObservationState : decided(confirmed / not_found) | uncertain
    UncertaintyReason: transition / occlusion / low_light / ambiguity /
                       insufficient_visual_evidence

**这不是第四平级状态**。`uncertain` 回答"这一帧能不能下定论"，
`UncertaintyReason` 回答"为什么不能定论"。两者正交，理由不是状态。

设计红线（预注册 docs/plans/2026-09-25-state-expressiveness-gate.md §3）:

  - **O1 路径不读 Ground Truth**：本模块的函数签名不接收 GT，
    实现中不得 import/引用任何 GT 结构（测试静态断言）。
  - **O1 路径不跨帧**：无时间邻域、无相邻采样点、无全局状态；
    每个 timeline entry 独立解析。跨帧共识须另立实验。
  - **O1 路径不读媒体**：不 open 帧文件、不解码、不重跑模型。
  - O0 恒等：`classify_legacy()` 必须与冻结 scorer 的 classify_entry
    逐条等价（测试对 Task 17 30 个 fixture e2e 断言）。
  - 不猜：理由无法从既有文本推出时置 None，不填默认值。

用法:
    python3 state_resolver.py --timeline <temporal-evidence.json> [--format json|md]
    python3 state_resolver.py --audit            # 自检（确定性 fixture，零模型调用）
"""
import argparse
import json
import os
import re
import sys

SCHEMA_VERSION = "1.0.0"
RESOLVER_NAME = "state_resolver.py"

# ---------------------------------------------------------------- 词汇表

# 状态：decided 的两侧 + 单数 uncertain。没有第四种 decided 状态。
# 三态语义 + 独立的执行失败类（H5）。`failed` **不是** uncertain：
# failed = 执行不完整（backend 未调用/调用失败/契约拒绝），uncertain = 画面不可判定。
# 二者不得互相转换。
OBSERVATION_STATES = ("confirmed", "not_found", "uncertain")
EXECUTION_FAILED_STATE = "failed"

# 若历史输出带执行失败子类型，出现这些字段即视为执行失败；
# 它们**不得**被解释为语义 uncertain（H5）。
EXECUTION_FAILED_FIELDS = ("backend_not_called", "backend_call_failed",
                           "contract_rejected", "extraction_failed")

# 与 GT uncertain 无关；只描述"为什么这一帧不可判定"。
UNCERTAINTY_REASONS = (
    "transition",             # 正在出现/消失，画面本身处在中间态
    "occlusion",              # 被遮挡/部分可见/被切断
    "low_light",              # 过暗/过曝/低对比
    "ambiguity",              # 相似物体干扰/疑似但不确定/难以区分
    "insufficient_visual_evidence",  # 过小/过远/模糊/超出识别能力/无把握
)

# 与冻结 scorer 的类别集合兼容（classify_entry 的产出域）。
LEGACY_CLASSES = ("confirmed", "not_found", "abstained", "low_confidence", "failed")

# reason → 关键词。仅匹配 model 自己写的文本，不做语义推理。
_REASON_KEYWORDS = (
    ("transition", (
        "transition", "正在出现", "正在消失", "出现过程", "进入画面", "离开画面",
        "部分进入", "部分离开", "in transition", "appearing", "disappearing",
    )),
    ("occlusion", (
        "遮挡", "被挡", "遮住", "挡住", "部分可见", "被其它", "被物体挡住",
        "截断", "被裁切", "occlu", "hidden", "blocked", "partially visible",
    )),
    ("low_light", (
        "过暗", "太暗", "昏暗", "低照度", "光线不足", "背光", "反光", "过曝",
        "对比度低", "亮度过低", "low light", "too dark", "dim", "underexposed",
        "overexposed", "low contrast",
    )),
    ("ambiguity", (
        "相似", "类似", "难以区分", "无法区分", "混淆", "疑似", "不确定是否是",
        "可能是其它", "同类物体", "similar", "ambiguous", "cannot distinguish",
        "hard to tell apart",
    )),
    ("insufficient_visual_evidence", (
        "太小", "过小", "过远", "模糊", "成像不清晰", "不清楚", "无法确认",
        "无法辨认", "看不清", "看不清目标", "超出识别能力", "视野外",
        "无把握", "分辨率不足", "too small", "too far", "blurry", "blurred",
        "unclear", "indistinct", "out of frame", "insufficient",
    )),
)

_WORD_RE = re.compile(r"[0-9a-z_\-]+")


def _normalize(text):
    """小写化 + 统一空白，仅用于中英混排的子串匹配。"""
    if not isinstance(text, str):
        return ""
    return " ".join(text.lower().split())


def extract_reasons(entry):
    """从**单帧**既有文本推断不确定原因。

    输入字段（只读，不修改）：`abstention_reason`、`evidence_text`、`description`。
    返回去重、按 UNCERTAINTY_REASONS 顺序排列的列表（可能为空）。
    """
    haystack = _normalize(" ".join([
        entry.get("abstention_reason") or "",
        entry.get("evidence_text") or "",
        entry.get("description") or "",
    ]))
    if not haystack.strip():
        return []
    # 按 reason 的声明顺序收集，保证确定性输出（与字段书写顺序无关）。
    found = []
    for reason, keywords in _REASON_KEYWORDS:
        for keyword in keywords:
            needle = _normalize(keyword)
            if not needle:
                continue
            if " " in needle or _WORD_RE.fullmatch(needle):
                if needle in haystack:
                    found.append(reason)
                    break
            elif needle in haystack:
                found.append(reason)
                break
    return found


# ---------------------------------------------------------------- O0 恒等分类

def classify_legacy(entry):
    """O0：与冻结 score_temporal_ground_truth.classify_entry 逐条等价。

    帧分类规则: frame_status != analyzed → failed；
    object_found=true → confirmed/low_confidence（按 evidence_sufficient）；
    有 abstention_reason → abstained；否则 not_found。
    """
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    if isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
        return "abstained"
    return "not_found"


# ---------------------------------------------------------------- O1 三态解析

def observation_state(entry):
    """O1 三态：confirmed / not_found / uncertain（**外加独立的 failed**）。

    只在**单帧字段**上决策；不看 GT、不看邻帧、不读媒体。

    **H4 只收窄、不放开**：confirmed 必须同时满足既有置信度门
    （`evidence_sufficient`）且帧自身没有自陈不确定理由。
    `O1 confirmed ⟹ legacy confirmed` 由测试硬断言。

    **H5 失败保留（本轮新增）**：legacy `failed` 必须原样保留为 `failed`，
    **不得**被重解释为语义 `uncertain`。理由：failed 表示执行不完整
    （backend 未调用/调用失败/契约拒绝），不是"画面看不清"。
    把它洗成 uncertain 会人为制造 transition，从而虚高边界恢复率。
    """
    if is_execution_failed(entry):
        return EXECUTION_FAILED_STATE
    if entry.get("object_found") is True:
        # 尊重既有置信度门（H-expression 的靶心在"文字自陈不确定"，
        # 不在"把模型自己压成 low_confidence 的帧重新提升为 confirmed"）。
        if entry.get("evidence_sufficient") is not True:
            return "uncertain"
        if _has_explicit_uncertainty(entry):
            return "uncertain"
        return "confirmed"
    if isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
        return "uncertain"          # 自陈无法判断 → uncertain（不是 not_found）
    if _has_explicit_uncertainty(entry):
        return "uncertain"
    return "not_found"


def is_execution_failed(entry):
    """H5：该帧是否为**执行失败**而非视觉不确定。

    判据与 legacy classify_entry 同源：`frame_status != "analyzed"` 即 failed。
    另外，若输出带执行失败子类型字段（backend_not_called / backend_call_failed /
    contract_rejected / extraction_failed 中任一出现且为真），同样判为 failed。
    这些子类型**不得**降级为语义 uncertain。
    """
    if entry.get("frame_status") != "analyzed":
        return True
    for field in EXECUTION_FAILED_FIELDS:
        if field in entry and entry.get(field):
            return True
    return False


def _has_explicit_uncertainty(entry):
    """帧自身是否自陈不确定（本轮只认模型自己写下的理由）。"""
    return bool(extract_reasons(entry))


def resolve_entry(entry):
    """单帧完整解析：三态 + 理由 + 兼容冻结类别的映射。

    H5：`observation_state == "failed"` 时 `uncertainty_reasons` 必须为空——
    执行失败没有"视觉不确定理由"，不得借理由字段伪装成语义不确定。
    """
    state = observation_state(entry)
    reasons = extract_reasons(entry) if state == "uncertain" else []
    return {
        "observation_state": state,
        "uncertainty_reasons": reasons,
        "legacy_class": classify_legacy(entry),
        # 兼容层：三态如何回落成冻结 scorer 可判定/非可判定类别。
        "compat_class": _compat_class(state, reasons),
        "confidence": entry.get("confidence"),
        "timestamp_ms": entry.get("timestamp_ms"),
    }


def _compat_class(state, reasons):
    """三态（+failed）→ 冻结类别集合。

    confirmed/not_found 保持确定类别；uncertain 映射为非确定类别
    （`low_confidence`）；**failed 必须映射回 `failed`**（H5）——
    它不是 low_confidence，把它压成 low_confidence 会让执行失败
    看起来像"模型表达了不确定"，从而虚高边界恢复率。
    理由不改变可判定性：带理由与不带理由的 uncertain 同样非确定。
    """
    if state in ("confirmed", "not_found"):
        return state
    if state == EXECUTION_FAILED_STATE:
        return EXECUTION_FAILED_STATE
    return "low_confidence"


# ---------------------------------------------------------------- O2 诊断（内部）

def oracle_gt_injected(entry, gt_state_at_ms):
    """O2（仅内部诊断，**禁止进入交付叙事**）：用 GT 状态反推每帧最优类别。

    接受 `gt_state_at_ms(timestamp_ms)` 回调以显式标注"这里读了 GT"，
    避免隐式依赖。调用方须按预注册 §3.1 同时报告 GT-driven / heuristic 拆分。
    """
    state = gt_state_at_ms(entry["timestamp_ms"])
    if state == "confirmed":
        return "confirmed"
    if state == "not_found":
        return "not_found"
    return "low_confidence"   # GT uncertain → 非确定类别承接


# ---------------------------------------------------------------- 审计

def audit():
    """确定性自检（fixtures 内联，零模型调用、零 IO）。返回 (passed, rows)。"""
    rows = []
    base = {
        "frame_status": "analyzed", "object_found": True,
        "confidence": 0.95, "evidence_sufficient": True,
        "evidence_text": "clear view",
        "abstention_reason": None, "bounding_box": None, "timestamp_ms": 1000.0,
    }

    def make(**overrides):
        item = dict(base)
        item.update(overrides)
        return item

    cases = [
        # (id, entry, expect_state, expect_reasons, expect_compat)
        ("clear-confirmed", make(), "confirmed", [], "confirmed"),
        ("failed-frame", make(frame_status="failed"), "failed", [],
         "failed"),
        ("backend-not-called", make(backend_not_called=True), "failed", [],
         "failed"),
        ("contract-rejected", make(frame_status="analyzed",
                                   contract_rejected=True), "failed", [],
         "failed"),
        ("low-confidence-view", make(evidence_sufficient=False),
         "uncertain", [], "low_confidence"),
        ("occluded", make(object_found=False, evidence_text="目标被遮挡",
                          abstention_reason="被遮挡，无法判断"), "uncertain",
         ["occlusion"], "low_confidence"),
        ("dark", make(object_found=False, abstention_reason="画面过暗"),
         "uncertain", ["low_light"], "low_confidence"),
        ("ambiguous", make(object_found=False, abstention_reason="有相似物体干扰"),
         "uncertain", ["ambiguity"], "low_confidence"),
        ("too-small", make(object_found=False, abstention_reason="目标太小无法确认"),
         "uncertain", ["insufficient_visual_evidence"], "low_confidence"),
        ("clear-negative", make(object_found=False, confidence=0.9,
                                abstention_reason=None, evidence_text="画面无该目标"),
         "not_found", [], "not_found"),
        ("overclaim-on-uncertain", make(object_found=True, confidence=0.92,
                                        evidence_sufficient=True,
                                        abstention_reason=None,
                                        evidence_text="目标是红色背包，清晰可见"),
         "confirmed", [], "confirmed"),
        ("no-reason-no-evidence", make(object_found=False, evidence_text="",
                                       abstention_reason=None),
         "not_found", [], "not_found"),
    ]
    for case_id, entry, expected_state, expected_reasons, expected_compat in cases:
        resolved = resolve_entry(entry)
        legacy = classify_legacy(entry)
        ok = (resolved["observation_state"] == expected_state
              and resolved["uncertainty_reasons"] == expected_reasons
              and resolved["compat_class"] == expected_compat)
        rows.append({
            "id": case_id,
            "passed": ok,
            "observation_state": resolved["observation_state"],
            "uncertainty_reasons": resolved["uncertainty_reasons"],
            "compat_class": resolved["compat_class"],
            "legacy_class": legacy,
            "detail": "" if ok else (
                f"期望 state={expected_state}/{expected_reasons}/compat={expected_compat}，"
                f"得到 {resolved['observation_state']}/"
                f"{resolved['uncertainty_reasons']}/{resolved['compat_class']}"),
        })

    # legacy 与三态的关系必须是**单方蕴含**：O1 只收窄，不放开。
    #   O1 confirmed ⟹ legacy confirmed；O1 not_found ⟹ legacy not_found。
    # 反向不成立（差异正是本实验要测量的量）。
    for case_id, entry, expected_state, _, expected_compat in cases:
        resolved = resolve_entry(entry)
        state = resolved["observation_state"]
        legacy = classify_legacy(entry)
        if state in ("confirmed", "not_found"):
            if resolved["compat_class"] != legacy:
                rows.append({"id": f"compat-strict-{case_id}", "passed": False,
                             "detail": f"三态 {state} 的兼容类 {resolved['compat_class']} "
                                       f"必须与 legacy {legacy} 一致（只收窄）"})
            else:
                rows.append({"id": f"compat-strict-{case_id}", "passed": True,
                             "detail": f"确定性三态 {state} 的兼容类与 legacy 一致"})
        else:
            if state == EXECUTION_FAILED_STATE:
                if resolved["compat_class"] != EXECUTION_FAILED_STATE:
                    rows.append({"id": f"compat-strict-{case_id}", "passed": False,
                                 "detail": f"failed 必须映射回 failed，得到 "
                                           f"{resolved['compat_class']}"})
                else:
                    rows.append({"id": f"compat-strict-{case_id}", "passed": True,
                                 "detail": "failed 保留为 failed（H5）"})
            elif resolved["compat_class"] in ("confirmed", "not_found"):
                rows.append({"id": f"compat-strict-{case_id}", "passed": False,
                             "detail": f"uncertain 不得回落成确定类别 "
                                       f"{resolved['compat_class']}"})
            else:
                rows.append({"id": f"compat-strict-{case_id}", "passed": True,
                             "detail": "uncertain 回落为非确定类别"})

    # 词表回归：每个 reason 至少有一个关键词被识别（防止词表被清空却仍 PASS）。
    for reason in UNCERTAINTY_REASONS:
        probe = make(object_found=False,
                     abstention_reason=f"probe for {reason} / "
                                       f"{_REASON_KEYWORDS[[r for r, _ in _REASON_KEYWORDS].index(reason)][1][0]}",
                     evidence_text="")
        matched = extract_reasons(probe)
        rows.append({"id": f"lexicon-{reason}", "passed": reason in matched,
                     "detail": f"关键词探针 → {matched}"})

    return all(row["passed"] for row in rows), rows


# ---------------------------------------------------------------- CLI

def main():
    parser = argparse.ArgumentParser(
        description="证据状态解析器（三态 + 正交不确定原因；O1 不读 GT/邻域/媒体）")
    parser.add_argument("--timeline", help="temporal-evidence JSON 路径")
    parser.add_argument("--audit", action="store_true", help="运行确定性自检")
    parser.add_argument("--format", choices=("json", "md"), default="json")
    args = parser.parse_args()

    if args.audit:
        passed, rows = audit()
        for row in rows:
            status = "PASS" if row["passed"] else "FAIL"
            print(f"[{status}] {row['id']}: {row.get('detail', '')}")
        print(f"RESULT: {'PASS' if passed else 'FAIL'} "
              f"({sum(1 for r in rows if r['passed'])}/{len(rows)})")
        return 0 if passed else 1

    if not args.timeline:
        parser.error("需要 --timeline 或 --audit")

    if not os.path.isfile(args.timeline):
        print(f"[用法错误] 找不到 timeline 输入: {args.timeline}", file=sys.stderr)
        return 2

    with open(args.timeline, encoding="utf-8") as handle:
        evidence = json.load(handle)

    timeline = evidence.get("timeline")
    if not isinstance(timeline, list):
        print("[用法错误] 输入必须是 temporal-evidence JSON（顶层 timeline 为数组）",
              file=sys.stderr)
        return 2

    resolved = [resolve_entry(entry) for entry in timeline]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "resolver": RESOLVER_NAME,
        "input": os.path.basename(args.timeline),
        "points": len(resolved),
        "state_counts": {name: sum(1 for item in resolved
                                   if item["observation_state"] == name)
                         for name in OBSERVATION_STATES + (EXECUTION_FAILED_STATE,)},
        "reason_counts": {reason: sum(1 for item in resolved
                                      if reason in item["uncertainty_reasons"])
                          for reason in UNCERTAINTY_REASONS},
        "resolved": resolved,
        "limitations": [
            "O1：不读 GT、不看时间邻域、不读媒体、不重跑模型",
            "uncertain 不是与 confirmed 平级的第四状态；原因与状态正交",
            "compat_class 仅供与冻结 scorer 比读，不是新证据契约",
        ],
    }

    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("| timestamp_ms | observation_state | reasons | compat | legacy |")
        print("| --- | --- | --- | --- | --- |")
        for item in resolved:
            print(f"| {item['timestamp_ms']} | {item['observation_state']} | "
                  f"{'|'.join(item['uncertainty_reasons']) or '-'} | "
                  f"{item['compat_class']} | {item['legacy_class']} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
