#!/usr/bin/env python3
"""adaptive_sampler.py — 目标时序证据与粗到细自适应采样（SparkSkill Studio 任务 16）

纯逻辑模块：不导入 cv2、不发起网络/模型调用，可同时被
`trace_temporal.py`（视觉证据执行器）与 `test_temporal_evidence.py`（规则测试）
导入，保证 uniform 与 adaptive 两条路径使用同一套采样规划、预算与语义规则。

职责：
  1. 解析/规范化 `sampling_strategy` 配置（与 validate_task_spec.py 同口径，
     执行期纵深防御：不支持组合同样拒绝）；
  2. 规划初始覆盖采样（adaptive 的均匀覆盖网格；uniform legacy 规划由
     extract_frames.plan_sample_times 提供，两者公式一致性有专项测试）；
  3. 依据触发器计算细化候选区间（对状态边界做二分细化）；
  4. 硬性调用预算账本（max_model_calls 硬限 / 时间戳缓存 / 重复跳过 / 复用计数）；
  5. 时序证据推导（首末确认、状态转换、边界不确定性、状态片段、无法确认片段）。

语义红线（本模块与整个任务 16 的硬约束）：
  - “首个 confirmed 采样时间”不等于目标真实首次进入时间；“最后 confirmed
    采样时间”不等于目标真实离开时间；
  - 两个 confirmed 采样点之间不得自动断言目标连续存在；
  - 状态变化只能定位到左右采样点形成的时间范围，不得伪造精确瞬间；
  - failed / abstained 不得折算成 not_found；
  - 不做跨帧身份一致性、不做跨摄像头实例关联、不输出物体运动路径；
  - 本功能不是 ReID、不是目标跟踪器、不是实时跟踪。
"""
import json

STRATEGIES = ("uniform", "adaptive_coarse_to_fine", "coverage_aware_adaptive")
EVIDENCE_CLASSES = ("confirmed", "not_found", "abstained", "low_confidence", "failed")
DEFINITIVE_CLASSES = ("confirmed", "not_found")  # 确定性类别
TRIGGER_VALUES = ("state_change", "abstained", "low_confidence", "failed")
DEFAULT_TRIGGERS = ("state_change", "abstained", "low_confidence", "failed")
ADAPTIVE_REQUIRED_FIELDS = (
    "max_model_calls", "initial_coverage_samples",
    "target_boundary_precision_ms", "max_refinement_rounds",
)
UNIFORM_FORBIDDEN_FIELDS = (
    "initial_coverage_samples", "target_boundary_precision_ms",
    "max_refinement_rounds", "refinement_triggers",
)
# 任务 18：coverage_aware_adaptive 专属字段（覆盖目标 + 覆盖调用储备）。
# 这两个字段对 uniform 与 adaptive_coarse_to_fine 均属“不支持组合”。
COVERAGE_ONLY_FIELDS = ("coverage_gap_target_ms", "coverage_call_reserve")
COVERAGE_REQUIRED_FIELDS = ADAPTIVE_REQUIRED_FIELDS + COVERAGE_ONLY_FIELDS

COVERAGE_LIMITATIONS = {
    "arbitrary_short_event_detection_guaranteed": False,
    "events_shorter_than_max_sampling_gap_may_be_missed": True,
    "coverage_statement": (
        "覆盖探索只保证不存在宽度超过最大相邻采样间隔的完全未观测时间窗口；"
        "不保证事件被视觉模型正确判定，不保证任意短事件必检，"
        "不表示采样点之间目标连续存在"),
}

TEMPORAL_SEMANTICS = {
    "nature": "sampling_evidence_supported_temporal_conclusion",
    "is_not_continuous_tracking_truth": True,
    "first_confirmed_semantics": (
        "first_confirmed_observed_ms 是首个被观察为 confirmed 的采样时间，"
        "不等于目标真实首次进入时间"),
    "last_confirmed_semantics": (
        "last_confirmed_observed_ms 是最后一个被观察为 confirmed 的采样时间，"
        "不等于目标真实离开时间"),
    "no_continuity_assertion": (
        "两个 confirmed 采样点之间不得自动断言目标连续存在；"
        "采样点之间的时间只有“未采样/未知”，没有连续性事实"),
    "boundary_semantics": (
        "状态变化只能定位到左右相邻采样点形成的时间范围 [left_ms, right_ms]，"
        "uncertainty_width_ms = right_ms - left_ms，不得伪造精确瞬间"),
    "no_inference_collapse": (
        "abstained / low_confidence / failed 独立计数，不得折算为 not_found；"
        "not_found 仅表示确定性负面结论"),
    "forbidden_capabilities": (
        "不做跨帧身份一致性、不做跨摄像头实例关联、不输出物体运动路径；"
        "本功能不是 ReID、不是目标跟踪器、不是实时跟踪"),
}


class SamplingConfigError(Exception):
    """采样策略配置错误（任务 16）：与 validate_task_spec.py 同口径。"""


# ---------------------------------------------------------------- 配置解析

def parse_strategy_config(spec, overrides=None):
    """从 spec['sampling_strategy']（可选）+ CLI overrides 得到规范化配置。

    返回 dict：
      strategy: 'uniform' | 'adaptive_coarse_to_fine'
      max_model_calls: int | None（None = 旧版 uniform 无显式预算，沿用
        interval/max-frames 行为；此时仍如实记录实际调用数）
      initial_coverage_samples / target_boundary_precision_ms / max_refinement_rounds:
        仅 adaptive 有意义
      refinement_triggers: tuple
      require_sampling_provenance / require_temporal_evidence: bool（缺省 true）

    overrides（CLI）只能是显式键值覆盖；执行期与校验器同口径拒绝不支持组合。
    """
    overrides = dict(overrides or {})
    block = spec.get("sampling_strategy")
    if block is not None and not isinstance(block, dict):
        raise SamplingConfigError("sampling_strategy 必须是对象")
    config = dict(block or {})
    config.update({k: v for k, v in overrides.items() if v is not None})

    strategy = config.get("strategy", "uniform")
    if strategy not in STRATEGIES:
        raise SamplingConfigError(
            f"未知采样策略 {strategy!r}（仅允许 {list(STRATEGIES)}）")

    normalized = {
        "strategy": strategy,
        "max_model_calls": config.get("max_model_calls"),
        "require_sampling_provenance": bool(config.get("require_sampling_provenance", True)),
        "require_temporal_evidence": bool(config.get("require_temporal_evidence", True)),
        "refinement_triggers": tuple(config.get("refinement_triggers") or DEFAULT_TRIGGERS),
    }

    if strategy == "uniform":
        for field in UNIFORM_FORBIDDEN_FIELDS + COVERAGE_ONLY_FIELDS:
            if config.get(field) is not None:
                raise SamplingConfigError(
                    f"uniform 策略不接受细化/覆盖参数 '{field}'（不支持组合："
                    "uniform 是正式 baseline，不做粗到细细化与覆盖探索）")
        # uniform 下细化/覆盖参数无意义（置 None）；max_model_calls 保留为硬上限
        for field in ("initial_coverage_samples", "target_boundary_precision_ms",
                      "max_refinement_rounds") + COVERAGE_ONLY_FIELDS:
            normalized[field] = None
    else:
        if strategy == "adaptive_coarse_to_fine":
            for field in COVERAGE_ONLY_FIELDS:
                if config.get(field) is not None:
                    raise SamplingConfigError(
                        f"adaptive_coarse_to_fine 策略不接受 coverage 专属字段 "
                        f"'{field}'（不支持组合：覆盖探索属于 coverage_aware_adaptive）")
        else:  # coverage_aware_adaptive
            for field in COVERAGE_ONLY_FIELDS:
                if config.get(field) is None:
                    raise SamplingConfigError(
                        f"coverage_aware_adaptive 策略缺少必填字段 '{field}'")
                normalized[field] = config[field]
        for field in ADAPTIVE_REQUIRED_FIELDS:
            if config.get(field) is None:
                raise SamplingConfigError(
                    f"{strategy} 策略缺少必填字段 '{field}'")
            normalized[field] = config[field]
        budget = normalized["max_model_calls"]
        initial = normalized["initial_coverage_samples"]
        precision = normalized["target_boundary_precision_ms"]
        rounds = normalized["max_refinement_rounds"]
        if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
            raise SamplingConfigError(
                f"max_model_calls 必须是正整数（硬性预算），得到 {budget!r}")
        if not isinstance(initial, int) or isinstance(initial, bool) or initial < 1:
            raise SamplingConfigError(
                f"initial_coverage_samples 必须是正整数，得到 {initial!r}")
        if not isinstance(precision, (int, float)) or isinstance(precision, bool) or precision <= 0:
            raise SamplingConfigError(
                f"target_boundary_precision_ms 必须 > 0，得到 {precision!r}")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
            raise SamplingConfigError(
                f"max_refinement_rounds 必须是正整数，得到 {rounds!r}")
        if initial > budget:
            raise SamplingConfigError(
                f"initial_coverage_samples({initial}) 超过 "
                f"max_model_calls({budget})：初始覆盖不得超出硬预算")
        if strategy == "coverage_aware_adaptive":
            gap_target = normalized["coverage_gap_target_ms"]
            reserve = normalized["coverage_call_reserve"]
            if (not isinstance(gap_target, (int, float)) or isinstance(gap_target, bool)
                    or gap_target <= 0):
                raise SamplingConfigError(
                    f"coverage_gap_target_ms 必须 > 0，得到 {gap_target!r}")
            if not isinstance(reserve, int) or isinstance(reserve, bool) or reserve < 1:
                raise SamplingConfigError(
                    f"coverage_call_reserve 必须是正整数，得到 {reserve!r}")
            if initial + reserve > budget:
                raise SamplingConfigError(
                    f"initial_coverage_samples({initial}) + "
                    f"coverage_call_reserve({reserve}) 超过 "
                    f"max_model_calls({budget})：覆盖配置之和不得超出硬性调用预算")
        for trigger in normalized["refinement_triggers"]:
            if trigger not in TRIGGER_VALUES:
                raise SamplingConfigError(f"未知细化触发器 {trigger!r}")

    budget = normalized.get("max_model_calls")
    if budget is not None and (not isinstance(budget, int) or isinstance(budget, bool)
                               or budget < 1):
        raise SamplingConfigError(f"max_model_calls 必须是正整数，得到 {budget!r}")
    return normalized


# ---------------------------------------------------------------- 采样规划

def uniform_grid(start_ms, end_ms, count):
    """区间内均匀覆盖 count 个采样点（含端点），升序去重。

    与 extract_frames.plan_sample_times 的 uniform(count) 分支公式一致
    （一致性由 test_temporal_evidence.py 专项断言）。
    """
    start = float(start_ms)
    end = float(end_ms)
    if count <= 1 or end <= start:
        return [round(start, 3)]
    step = (end - start) / (count - 1)
    times = [round(start + i * step, 3) for i in range(count)]
    return sorted({t for t in times})


def timestamp_key(timestamp_ms):
    """时间戳缓存键：毫秒级四舍五入，保证同一采样点只调用一次模型。"""
    return int(round(float(timestamp_ms) * 1000)) / 1000.0


# ---------------------------------------------------------------- 预算账本

class CallBudget:
    """硬性视觉调用预算账本。

    - max_model_calls 为 None 时表示旧版 uniform 无显式预算（仍如实计数）；
    - 同一时间戳（按来源命名空间隔离）不得重复调用模型：第二次起 cache hit
      （多来源任务共享同一个预算上限，但每来源的视频与时间轴相互独立）；
    - 预算耗尽后任何细化请求一律拒绝（预算耗尽不是“分析成功”的证据）。
    """

    def __init__(self, max_model_calls=None):
        self.max_model_calls = max_model_calls
        self.actual_model_calls = 0
        self.reused_evidence_count = 0
        self.skipped_duplicate_timestamps = []
        self._analyzed = {}  # (namespace, timestamp_key) -> entry

    @property
    def remaining(self):
        if self.max_model_calls is None:
            return None
        return max(0, self.max_model_calls - self.actual_model_calls)

    def exhausted(self):
        return self.max_model_calls is not None and self.actual_model_calls >= self.max_model_calls

    def register_call(self):
        self.actual_model_calls += 1

    def register_duplicate(self, timestamp_ms):
        self.skipped_duplicate_timestamps.append(timestamp_key(timestamp_ms))

    def register_reuse(self):
        self.reused_evidence_count += 1

    def has_analyzed(self, timestamp_ms, namespace="default"):
        return (namespace, timestamp_key(timestamp_ms)) in self._analyzed

    def record_entry(self, timestamp_ms, entry, fresh, namespace="default"):
        self._analyzed[(namespace, timestamp_key(timestamp_ms))] = entry

    def snapshot(self):
        return {
            "max_model_calls": self.max_model_calls,
            "actual_model_calls": self.actual_model_calls,
            "reused_evidence_count": self.reused_evidence_count,
            "remaining_calls": self.remaining,
            "budget_exhausted": self.exhausted(),
            "skipped_duplicate_timestamps": list(self.skipped_duplicate_timestamps),
        }


# ---------------------------------------------------------------- 帧分类（与 trace_video.frame_class 同规则）

def classify_entry(entry):
    """帧分类规则：与 trace_video.frame_class / trace_multi_video.frame_class
    逐条一致（confirmed / not_found / abstained / low_confidence / failed）。

    此处保留一份同规则实现的原因：report-generator 需要不依赖 cv2 的分类能力；
    与 extractor 侧规则的一致性由 test_temporal_evidence.py T17 专项断言。
    """
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    if isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
        return "abstained"
    return "not_found"


# ---------------------------------------------------------------- 细化候选区间

def refinement_intervals(entries, triggers, precision_ms):
    """从已分析样本（按 timestamp_ms 升序）计算值得细化的区间。

    每条候选：{left_ms, right_ms, width_ms, trigger, class_left, class_right, reason}
    规则（同时满足才细化）：
      1. width_ms > precision_ms（已达到目标边界精度的区间不再细化）；
      2. 命中至少一个启用触发器：
         - state_change：class_left != class_right（定位状态边界）；
         - abstained / low_confidence / failed：任一侧样本是该类别
           （证据缺口邻域，补充采样帮助确定局部状态）。
    没有状态变化、没有拒答/低置信/失败样本时，不产生任何候选
    （“没有状态变化时不进行无意义细化”）。
    """
    triggers = set(triggers or ())
    intervals = []
    ordered = sorted(entries, key=lambda item: item["timestamp_ms"])
    for left, right in zip(ordered, ordered[1:]):
        width = round(right["timestamp_ms"] - left["timestamp_ms"], 3)
        if width <= float(precision_ms):
            continue
        class_left = classify_entry(left)
        class_right = classify_entry(right)
        matched = None
        if "state_change" in triggers and class_left != class_right:
            matched = ("state_change",
                       f"相邻采样状态变化 {class_left}({left['timestamp_ms']}ms) → "
                       f"{class_right}({right['timestamp_ms']}ms)，需细化定位边界")
        elif class_right in ("abstained", "low_confidence", "failed") and class_right in triggers:
            matched = (class_right,
                       f"右侧采样 {right['timestamp_ms']}ms 为 {class_right}"
                       "（证据缺口），需细化补充证据")
        elif class_left in ("abstained", "low_confidence", "failed") and class_left in triggers:
            matched = (class_left,
                       f"左侧采样 {left['timestamp_ms']}ms 为 {class_left}"
                       "（证据缺口），需细化补充证据")
        if matched:
            intervals.append({
                "left_ms": left["timestamp_ms"],
                "right_ms": right["timestamp_ms"],
                "width_ms": width,
                "trigger": matched[0],
                "class_left": class_left,
                "class_right": class_right,
                "reason": matched[1],
            })
    return intervals


def midpoint_of(interval):
    """细化采样点：候选区间的中点（二分查找边界）。"""
    return round((interval["left_ms"] + interval["right_ms"]) / 2.0, 3)


# ---------------------------------------------------------------- 覆盖探索（任务 18）

def round3(value):
    """毫秒值统一舍入到 3 位小数（与产物其它毫秒字段一致）。"""
    return round(float(value), 3)


def observed_points(timestamps, duration_ms):
    """观测点集：已分析时间戳 + 媒体边界 [0, duration_ms]（升序去重）。

    媒体边界纳入的理由：初始覆盖被预算截断时，[0, 首个采样] 与 [末个采样, D]
    同样是未观测区间；纳入后“最大相邻采样间隔”是最大未观测时间窗口的保守度量，
    并可由 (analyzed_timestamps, duration_ms) 精确复算。
    """
    points = {0.0}
    if duration_ms is not None:
        points.add(round3(duration_ms))
    for ts in timestamps:
        points.add(timestamp_key(ts))
    return sorted(points)


def adjacent_gaps(timestamps, duration_ms):
    """相邻采样间隔列表（含媒体边界）：每项 {left_ms, right_ms, width_ms}，升序。"""
    points = observed_points(timestamps, duration_ms)
    return [{"left_ms": a, "right_ms": b, "width_ms": round(b - a, 3)}
            for a, b in zip(points, points[1:])]


def max_adjacent_gap_ms(timestamps, duration_ms):
    """最大相邻采样间隔（可复算：观测点相邻差的最大值；空时间列返回 0.0）。"""
    gaps = adjacent_gaps(timestamps, duration_ms)
    return max((gap["width_ms"] for gap in gaps), default=0.0)


def coverage_candidates(gaps, target_ms, excluded=()):
    """值得覆盖探索的间隔：宽度 > target_ms 且未被排除。

    excluded: [(left_ms, right_ms), ...] 已排除间隔（中点命中已有帧、
    间隔已窄于帧分辨率时排除，避免对同一间隔无限二分）。
    """
    excluded_keys = {(round3(item[0]), round3(item[1])) for item in excluded}
    candidates = []
    for gap in gaps:
        key = (round3(gap["left_ms"]), round3(gap["right_ms"]))
        if key in excluded_keys:
            continue
        if gap["width_ms"] > float(target_ms):
            candidates.append(gap)
    return candidates


def next_coverage_candidate(gaps, target_ms, excluded=()):
    """确定性选择下一个覆盖探索间隔：宽度最大；并列取 left_ms 最小；再并列取 right_ms 最小。

    纯函数：只依赖 (gaps, target_ms, excluded)——不读取 Ground Truth、fixture
    文件名、预期结果或历史模型返回（专项测试断言）。
    """
    candidates = coverage_candidates(gaps, target_ms, excluded)
    if not candidates:
        return None
    return sorted(candidates,
                  key=lambda gap: (-gap["width_ms"], gap["left_ms"], gap["right_ms"]))[0]


def underobserved_intervals(timestamps, duration_ms, target_ms):
    """尚未充分观测的区间：结束时仍宽于覆盖目标的相邻间隔（剩余盲区清单）。"""
    return coverage_candidates(adjacent_gaps(timestamps, duration_ms), target_ms)


# ---------------------------------------------------------------- 时序证据推导

def build_temporal_evidence(entries, target_precision_ms=None, stopped_by_budget=False,
                            stop_reasons=None, actual_model_calls=0,
                            duration_ms=None, coverage_gap_target_ms=None,
                            max_gap_initial_ms=None, coverage_calls=None,
                            coverage_call_reserve=None):
    """从已分析时间线（升序、未去重）推导可复算的时序证据结构。

    输入 entries：timeline[]（每条有 timestamp_ms 与分类所需字段）。
    不调用模型、不做视觉推理，只应用规则；所有字段可由 entries 复算。

    覆盖参数（任务 18；duration_ms/coverage_gap_target_ms 提供时附加 coverage 块：
    最大相邻采样间隔初始/最终值、覆盖调用数、剩余盲区与限制声明——全部可由
    (entries, duration_ms, coverage_gap_target_ms) 复算）。
    """
    ordered = sorted(entries, key=lambda item: item["timestamp_ms"])
    classes = [classify_entry(entry) for entry in ordered]
    counts = {name: classes.count(name) for name in EVIDENCE_CLASSES}
    confirmed_entries = [e for e, c in zip(ordered, classes) if c == "confirmed"]
    analyzed = (counts["confirmed"] + counts["not_found"]
                + counts["abstained"] + counts["low_confidence"])

    # 状态转换：相邻采样类别不同 → 左右边界 + 不确定宽度（不伪造精确瞬间）
    transitions = []
    for left, right, cls_left, cls_right in zip(ordered, ordered[1:], classes, classes[1:]):
        if cls_left != cls_right:
            transitions.append({
                "left_ms": left["timestamp_ms"],
                "right_ms": right["timestamp_ms"],
                "from_class": cls_left,
                "to_class": cls_right,
                "uncertainty_width_ms": round(right["timestamp_ms"] - left["timestamp_ms"], 3),
            })

    if transitions:
        widths = [t["uncertainty_width_ms"] for t in transitions]
        boundary = {
            "target_ms": target_precision_ms,
            "max_ms": max(widths),
            "min_ms": min(widths),
            "target_precision_reached": (
                None if target_precision_ms is None
                else all(w <= float(target_precision_ms) for w in widths)),
            "residual_uncertainty_ms": max(widths),
        }
    else:
        boundary = {
            "target_ms": target_precision_ms,
            "max_ms": None,
            "min_ms": None,
            "target_precision_reached": (None if target_precision_ms is None else True),
            "residual_uncertainty_ms": None,
        }

    # 证据支持的状态片段：相邻同类采样的最大连续段（只覆盖采样点自身）
    segments = []
    for entry, cls in zip(ordered, classes):
        if segments and segments[-1]["state_class"] == cls:
            segments[-1]["end_ms"] = entry["timestamp_ms"]
            segments[-1]["sample_count"] += 1
        else:
            segments.append({
                "start_ms": entry["timestamp_ms"],
                "end_ms": entry["timestamp_ms"],
                "state_class": cls,
                "sample_count": 1,
            })
    for segment in segments:
        segment["note"] = "证据支持的状态片段仅覆盖已采样点，不声称片段内未采样时间的连续事实"

    # 无法确认的时间片段：相邻采样对中任一侧不是确定性类别
    unconfirmed = []
    for left, right, cls_left, cls_right in zip(ordered, ordered[1:], classes, classes[1:]):
        gap_classes = [c for c in (cls_left, cls_right) if c not in DEFINITIVE_CLASSES]
        if gap_classes:
            unconfirmed.append({
                "left_ms": left["timestamp_ms"],
                "right_ms": right["timestamp_ms"],
                "uncertainty_width_ms": round(right["timestamp_ms"] - left["timestamp_ms"], 3),
                "non_definitive_classes": sorted(set(gap_classes)),
                "reason": "该区间内至少一侧采样不是确定性类别"
                          "（confirmed/not_found），无法给出确定性结论",
            })

    return {
        "first_confirmed_observed_ms": (
            confirmed_entries[0]["timestamp_ms"] if confirmed_entries else None),
        "last_confirmed_observed_ms": (
            confirmed_entries[-1]["timestamp_ms"] if confirmed_entries else None),
        "confirmed_sample_count": counts["confirmed"],
        "class_counts": counts,
        "analyzed_sample_count": analyzed,
        "analyzed_ratio": (round(analyzed / len(ordered), 6) if ordered else 0.0),
        "state_transitions": transitions,
        "state_transition_count": len(transitions),
        "boundary_uncertainty": boundary,
        "evidence_supported_segments": segments,
        "unconfirmed_intervals": unconfirmed,
        "stopped_by_budget": bool(stopped_by_budget),
        "stop_reasons": list(stop_reasons or []),
        "actual_model_calls": actual_model_calls,
        "semantics": TEMPORAL_SEMANTICS,
        "coverage": {
            "max_adjacent_sampling_gap_ms_initial": max_gap_initial_ms,
            "max_adjacent_sampling_gap_ms_final": (
                max_adjacent_gap_ms([e["timestamp_ms"] for e in ordered], duration_ms)
                if duration_ms is not None else None),
            "coverage_gap_target_ms": coverage_gap_target_ms,
            "coverage_calls": coverage_calls,
            "coverage_call_reserve": coverage_call_reserve,
            "underobserved_intervals": (
                underobserved_intervals([e["timestamp_ms"] for e in ordered],
                                        duration_ms, coverage_gap_target_ms)
                if (duration_ms is not None and coverage_gap_target_ms is not None)
                else None),
            **COVERAGE_LIMITATIONS,
        },
    }


def provenance_free_of_credentials(provenance):
    """provenance 安全自检：序列化后不含凭据样式内容（任务 16 专项测试用）。"""
    text = json.dumps(provenance, ensure_ascii=False)
    lowered = text.lower()
    markers = ("api_key", "api-key", "secret", "token", "password", "passwd",
               "bearer ", "private_key", "-----begin")
    return [marker for marker in markers if marker in lowered]
