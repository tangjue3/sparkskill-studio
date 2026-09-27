#!/usr/bin/env python3
"""jev_client.py — Jev / System One 类型化决策客户端（SparkSkill Studio Task 29）

Task 29 预注册：docs/plans/2026-09-25-task29-jev-control-plane.md

定位：**Optional Semantic Control Plane** 的客户端。Jev 只做路由/风险/升级判断，
**不拥有最终事实判定权**（那是确定性规则的职责）。

设计红线（预注册 §2 / §7）：

  - **权限最小化**：只发送脱敏聚合状态。禁止字段（timestamp_ms / max_sampling_gap_ms /
    frame_path / *_sha256 / target_query / bounding_box / frame_index / sample_index）
    在构造 payload 时即被拒绝，不是发出前才检查。
  - **媒体不离开设备**：不发送图片、帧、bbox、目标描述词。
  - **默认关闭**：JEV_ENABLED=false（缺省）时 `decide()` 直接返回 fallback，
    不构造任何网络请求、不要求 key。
  - **可用性**：HTTP 失败 / 超时 / 非法 schema → 单次降级 deterministic，
    不重试、不阻塞 pipeline。
  - key 不入 Git：只从环境变量 `JEV_API_KEY` 读取。

端点：官方默认 `https://api.typesafe.ai/v1/systemone`（可用 JEV_BASE_URL 覆盖）。
模型名从 `JEV_MODEL` 读，缺省 `typesafe/systemone`。

本模块**不主动发起任何调用**；调用只发生在 `decide()` 且 `JEV_ENABLED` 为真时。
测试通过注入 transport 离线验证全部路径，不触网。

用法（库）:
    from jev_client import JevClient, decision_from_state
    client = JevClient.from_env()
    result = client.decide(state_summary)

用法（CLI 连通性探针，默认 dry-run，不触网）:
    python3 jev_client.py --probe --dry-run
    python3 jev_client.py --state <summary.json> --dry-run
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

CLIENT_NAME = "jev_client.py"
CLIENT_VERSION = "1.0.0"

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "typesafe/systemone"
DEFAULT_TIMEOUT_S = 30.0

# 禁止随请求外传的字段（预注册 §2）。出现即抛 PayloadForbiddenError。
FORBIDDEN_FIELDS = frozenset({
    "timestamp_ms", "timestamps", "max_sampling_gap_ms", "sampling_gap_ms",
    "sampling_strategy", "frame_path", "frame_paths", "frame_sha256",
    "media_sha256", "target_query", "target_description", "bounding_box",
    "bounding_boxes", "bbox", "frame_index", "sample_index", "media_path",
    "image", "images", "video", "frames",
})

# 允许外传的字段白名单（预注册 §2）。
ALLOWED_FIELDS = frozenset({
    "task_type", "target_complexity", "sampled_frames", "class_counts",
    "mean_confidence", "resource_budget",
})

VALID_ROUTES = ("route_8b", "route_27b", "route_human_review")
VALID_RISK = ("low", "medium", "high")


class JevError(Exception):
    """Jev 客户端基类错误。"""


class PayloadForbiddenError(JevError):
    """payload 含禁止外传字段（违反权限最小化契约）。"""


class JevSchemaError(JevError):
    """Jev 返回不符合预期 schema。"""


class JevUnavailableError(JevError):
    """Jev 不可用（未启用 / 缺 key / HTTP 失败 / 超时）。"""


def build_decision_questions():
    """预注册 §3 的四个类型化问题（Choice / Bool / Score / Bool）。"""
    return [
        {"id": "q1_route", "type": "choice",
         "question": "选择视觉后端路由",
         "choices": list(VALID_ROUTES)},
        {"id": "q2_sufficient", "type": "bool",
         "question": "现有证据是否足以自动形成结论？"},
        {"id": "q3_risk", "type": "choice",
         "question": "证据风险等级",
         "choices": list(VALID_RISK)},
        {"id": "q4_extra_call", "type": "bool",
         "question": "是否值得追加一次昂贵视觉调用？"},
    ]


def assert_payload_allowed(payload):
    """硬断言：payload 只含白名单字段，且不含任何禁止字段。

    在构造阶段即拒绝，而不是"发出前才检查"——这样测试可以在不触网的情况下
    证明契约成立。
    """
    if not isinstance(payload, dict):
        raise PayloadForbiddenError("payload 必须是 JSON 对象")
    unknown = sorted(set(payload) - ALLOWED_FIELDS)
    if unknown:
        raise PayloadForbiddenError(
            f"payload 含非白名单字段 {unknown}（只允许 {sorted(ALLOWED_FIELDS)}）")
    forbidden = sorted(set(payload) & FORBIDDEN_FIELDS)
    if forbidden:
        raise PayloadForbiddenError(f"payload 含禁止外传字段 {forbidden}")
    return True


def state_summary_from_evidence(evidence):
    """从 temporal-evidence 文档构造**脱敏**聚合状态（Task 28 定版 schema 的下游）。

    只取聚合量：帧数、类别计数、平均置信度。**不取**任何时间戳/路径/哈希/目标词。
    """
    timeline = evidence.get("timeline") if isinstance(evidence, dict) else None
    if not isinstance(timeline, list):
        raise JevSchemaError("evidence.timeline 必须是数组")

    counts = {"confirmed": 0, "not_found": 0, "abstained": 0, "failed": 0}
    confidences = []
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        if entry.get("frame_status") != "analyzed":
            counts["failed"] += 1
            continue
        if entry.get("object_found") is True:
            key = "confirmed" if entry.get("evidence_sufficient") is True else "abstained"
            counts[key] += 1
        elif isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
            counts["abstained"] += 1
        else:
            counts["not_found"] += 1
        value = entry.get("confidence")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            confidences.append(float(value))

    mean_confidence = round(sum(confidences) / len(confidences), 6) if confidences else None
    return {
        "task_type": evidence.get("task_type") or "temporal_presence",
        "target_complexity": evidence.get("target_complexity") or "unknown",
        "sampled_frames": len(timeline),
        "class_counts": counts,
        "mean_confidence": mean_confidence,
        "resource_budget": evidence.get("resource_budget") or "medium",
    }


def _coerce_bool(value):
    return bool(value) if isinstance(value, bool) else None


def parse_decision(response):
    """把 Jev 返回解析为规范化决策。

    预期 schema（宽松接受嵌套）:
        {"decisions": {"q1_route": {...}, "q2_sufficient": ...,
                       "q3_risk": ..., "q4_extra_call": ...}}
    也接受平铺 {"route": ..., "sufficient": ..., "risk": ..., "extra_call": ...}。

    任何字段缺失/非法即抛 JevSchemaError（调用方降级，不猜）。
    """
    if not isinstance(response, dict):
        raise JevSchemaError("Jev 响应必须是 JSON 对象")
    decisions = response.get("decisions")
    if not isinstance(decisions, dict):
        decisions = response

    route = _pick_choice(decisions, ("q1_route", "route", "route_choice"),
                         VALID_ROUTES)
    sufficient = _pick_bool(decisions, ("q2_sufficient", "sufficient",
                                        "sufficient_for_auto_conclusion"))
    risk = _pick_choice(decisions, ("q3_risk", "risk", "risk_level"), VALID_RISK)
    extra_call = _pick_bool(decisions, ("q4_extra_call", "extra_call",
                                        "worth_extra_expensive_call"))

    missing = [name for name, value in (("route", route), ("sufficient", sufficient),
                                        ("risk", risk), ("extra_call", extra_call))
               if value is None]
    if missing:
        raise JevSchemaError(f"Jev 响应缺少/非法字段: {missing}")

    return {"route": route, "sufficient": sufficient,
            "risk": risk, "extra_call": extra_call}


def _pick_choice(decisions, keys, valid):
    for key in keys:
        if key not in decisions:
            continue
        raw = decisions[key]
        value = raw.get("value") if isinstance(raw, dict) else raw
        if isinstance(value, str) and value in valid:
            return value
    return None


def _pick_bool(decisions, keys):
    for key in keys:
        if key not in decisions:
            continue
        raw = decisions[key]
        value = raw.get("value") if isinstance(raw, dict) else raw
        if isinstance(value, bool):
            return value
    return None


def deterministic_policy(state_summary):
    """A 组：现有 deterministic policy（shadow mode 的对照，逐字节确定）。

    规则与项目既有"拒答纪律"同向：任何 abstained/failed 帧或低平均置信度
    都不得自动接受。阈值集中在此，便于测试断言。
    """
    counts = state_summary.get("class_counts") or {}
    abstained = counts.get("abstained", 0)
    failed = counts.get("failed", 0)
    mean_confidence = state_summary.get("mean_confidence")

    if failed:
        return {"route": "route_human_review", "sufficient": False,
                "risk": "high", "extra_call": False}
    if abstained:
        return {"route": "route_human_review", "sufficient": False,
                "risk": "medium", "extra_call": False}
    if mean_confidence is None or mean_confidence < 0.75:
        return {"route": "route_27b", "sufficient": False,
                "risk": "medium", "extra_call": True}
    return {"route": "route_8b", "sufficient": True,
            "risk": "low", "extra_call": False}


def apply_thresholds(decision):
    """§3：阈值留给代码。把 Jev 概率转成 AUTO_ACCEPT / ABSTAIN / ESCALATE_HUMAN。

    Jev 若不返回概率，退化为按 `route` 字段解释（保守方向）。
    """
    route = decision.get("route")
    if route == "route_human_review":
        return "ESCALATE_HUMAN"
    if decision.get("sufficient") is not True:
        return "ABSTAIN"
    if decision.get("risk") == "high":
        return "ESCALATE_HUMAN"
    return "AUTO_ACCEPT"


class JevClient:
    """Jev 客户端。默认关闭；只有显式启用才可能触网。"""

    def __init__(self, enabled=False, api_key=None, base_url=DEFAULT_BASE_URL,
                 model=DEFAULT_MODEL, timeout_s=DEFAULT_TIMEOUT_S,
                 transport=None):
        self.enabled = bool(enabled)
        self.api_key = api_key
        self.base_url = base_url or DEFAULT_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.timeout_s = float(timeout_s or DEFAULT_TIMEOUT_S)
        # transport: 可注入 (url, payload, headers, timeout) -> dict；测试用，不触网。
        self._transport = transport

    @classmethod
    def from_env(cls, env=None, transport=None):
        """从环境变量构造。缺省 **未启用**（JEV_ENABLED 不为真）。"""
        env = env if env is not None else os.environ
        enabled = str(env.get("JEV_ENABLED", "")).strip().lower() in ("1", "true", "yes", "on")
        return cls(
            enabled=enabled,
            api_key=env.get("JEV_API_KEY"),
            base_url=env.get("JEV_BASE_URL") or DEFAULT_BASE_URL,
            model=env.get("JEV_MODEL") or DEFAULT_MODEL,
            timeout_s=float(env.get("JEV_TIMEOUT_S") or DEFAULT_TIMEOUT_S),
            transport=transport,
        )

    # ---------------------------------------------------------------- 决策

    def decide(self, state_summary, use_fallback_on_error=True):
        """对一个脱敏状态求决策。

        - 未启用 → 直接 deterministic fallback（不构造请求、不要求 key）；
        - payload 违约 → 抛 PayloadForbiddenError（**不降级**：这是契约违反，
          必须显式失败，不能默默 fallback 掩盖bug）；
        - HTTP 失败 / 超时 / 非法 schema → use_fallback_on_error=True 时降级。
        """
        assert_payload_allowed(state_summary)

        if not self.enabled:
            return {"source": "deterministic_fallback",
                    "reason": "jev_disabled",
                    "decision": deterministic_policy(state_summary)}

        if not self.api_key:
            if use_fallback_on_error:
                return {"source": "deterministic_fallback",
                        "reason": "jev_api_key_missing",
                        "decision": deterministic_policy(state_summary)}
            raise JevUnavailableError("JEV_ENABLED 为真但缺少 JEV_API_KEY")

        request_payload = self._build_request(state_summary)

        try:
            raw = self._send(request_payload)
            decision = parse_decision(raw)
        except (JevSchemaError, JevUnavailableError, OSError) as error:
            if use_fallback_on_error:
                return {"source": "deterministic_fallback",
                        "reason": type(error).__name__,
                        "decision": deterministic_policy(state_summary)}
            raise

        return {"source": "jev", "reason": None, "decision": decision}

    def _build_request(self, state_summary):
        return {
            "model": self.model,
            "questions": build_decision_questions(),
            "state": state_summary,
        }

    def _send(self, payload):
        if self._transport is not None:
            return self._transport(self.base_url, payload, self._headers(), self.timeout_s)

        request = urllib.request.Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise JevUnavailableError(f"Jev HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise JevUnavailableError(f"Jev 网络错误: {error.reason}") from error
        except TimeoutError as error:
            raise JevUnavailableError("Jev 超时") from error

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}" if self.api_key else "",
        }


# ---------------------------------------------------------------- CLI

def main():
    parser = argparse.ArgumentParser(
        description="Jev 类型化决策客户端（默认关闭；--dry-run 不触网）")
    parser.add_argument("--probe", action="store_true", help="连通性/契约自检")
    parser.add_argument("--state", help="脱敏状态 summary JSON 路径")
    parser.add_argument("--dry-run", action="store_true",
                        help="不实际调用 Jev，只打印将发送的 payload 与 fallback 决策")
    args = parser.parse_args()

    if args.probe:
        sample = {
            "task_type": "temporal_presence",
            "target_complexity": "attribute_relation",
            "sampled_frames": 8,
            "class_counts": {"confirmed": 4, "not_found": 1, "abstained": 3, "failed": 0},
            "mean_confidence": 0.71,
            "resource_budget": "medium",
        }
        print(json.dumps({
            "client": CLIENT_NAME, "version": CLIENT_VERSION,
            "enabled": JevClient.from_env().enabled,
            "endpoint": JevClient.from_env().base_url,
            "questions": build_decision_questions(),
            "sample_state": sample,
            "fallback_decision": deterministic_policy(sample),
            "fallback_action": apply_thresholds(deterministic_policy(sample)),
        }, ensure_ascii=False, indent=2))
        return 0

    if not args.state:
        parser.error("需要 --probe 或 --state")

    if not os.path.isfile(args.state):
        print(f"[用法错误] 找不到状态文件: {args.state}", file=sys.stderr)
        return 2
    with open(args.state, encoding="utf-8") as handle:
        summary = json.load(handle)

    client = JevClient.from_env()
    if args.dry_run or not client.enabled:
        assert_payload_allowed(summary)
        print(json.dumps({
            "dry_run": True,
            "would_send": client._build_request(summary),
            "fallback_decision": deterministic_policy(summary),
            "fallback_action": apply_thresholds(deterministic_policy(summary)),
            "jev_enabled": client.enabled,
        }, ensure_ascii=False, indent=2))
        return 0

    result = client.decide(summary)
    result["action"] = apply_thresholds(result["decision"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
