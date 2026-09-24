#!/usr/bin/env python3
"""evidence-report-generator · 最小版本（SparkSkill Studio）

接收 visual-evidence-extractor 产出的证据 JSON，生成最终报告 JSON。

反幻觉规则（硬约束):
  - 没有视觉证据时不得生成任何肯定结论;
  - object_found=false 时不得声称目标存在;
  - abstention_reason 非空时 status 必须为 "abstained";
  - conclusion 只能由输入证据中的字段组成，不得添加输入中不存在的事实;
  - 不推断人物身份、年龄、国籍、关系或意图。

视频模式（任务 04 新增）:
  - 输入 trace_video.py 产出的视频证据时间线（timeline.json）时自动进入视频模式;
  - 输出视频级报告：source_video / duration_ms / sampled_frames / target_query /
    timeline / summary{first/last_confirmed_timestamp_ms, confirmed_frame_count,
    overall_status: completed|abstained|failed};
  - 状态由本引擎按帧条目独立复算，并与 timeline.summary.overall_status 交叉校验，
    不一致时以复算结果为准并记入 warnings（两套实现互检，防单点规则错误）;
  - 严格区分 confirmed / not_found / abstained / failed; 不做身份跟踪与跨镜头关联。

多视频模式（任务 06 新增）:
  - 输入 trace_multi_video.py 产出的全局时间线（global-timeline.json，含
    global_timeline[] 与 sources[]）时自动进入多视频模式;
  - 输出多视频报告：sources[]（每来源独立状态与统计）/ global_summary{} /
    timeline[] / semantic_limitations{} / status / conclusion;
  - 状态由本引擎按全局条目独立复算，并与 global_summary.overall_status 交叉校验;
  - 结论只允许使用 matched target query / visually consistent with target description /
    confirmed in source A / confirmed in source B 等表述；必须显示跨视频语义限制：
    不断言同一个物理实例、不宣称跨视频移动、不做身份匹配;
  - 全部 not_found → completed（负面结论）；无任何 analyzed → failed。

时序证据模式（任务 16 新增）:
  - 输入 trace_temporal.py 产出的时序证据文档（temporal-evidence.json，含
    timeline[] / sampling_provenance{} / temporal_evidence{}）时自动进入 temporal 模式；
    多来源版本（global_timeline[] + sources[] + global_temporal_evidence{}）进入
    temporal-multi 模式;
  - 本引擎按时间线条目独立复算首末 confirmed 观察时间、状态转换、各类计数、
    边界不确定性（两套实现互检，与 adaptive_sampler 独立）；不一致时以复算为准
    并记入 warnings；实际调用数与预算越界也做交叉校验，不重新调用模型掩盖矛盾;
  - 报告必须显示：采样策略、视觉调用预算与实际调用数、是否耗尽预算、是否达到
    目标时间精度，以及“这是采样证据支持的时序结论，不是连续跟踪真值”;
  - 多来源时序报告继续显示跨视频语义限制。

用法:
    python3 generate_report.py --task-spec <spec.json> --evidence <evidence.json> \
        [--output <report.json>] [--mode auto|image|video|multi-video|temporal|temporal-multi]
退出码: 0 = 报告已生成; 2 = 用法/IO 错误; 3 = 输入不合法
"""
import argparse
import datetime
import json
import sys

REPORT_SCHEMA_VERSION = "1.1.0"
VIDEO_REPORT_SCHEMA_VERSION = "1.1.0"


def load_json(path, label):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[错误] 无法读取{label}: {error}", file=sys.stderr)
        raise SystemExit(2)


def as_evidence_list(evidence):
    """接受单条证据对象或证据数组，统一为列表。"""
    if isinstance(evidence, dict):
        return [evidence]
    if isinstance(evidence, list) and all(isinstance(item, dict) for item in evidence):
        return evidence
    raise SystemExit("[错误] --evidence 必须是证据对象或证据对象数组")


def build_report(spec, evidences):
    task_id = spec.get("task_id")
    target = spec.get("target", {}).get("description", "")
    warnings = []

    if not evidences:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "task_id": task_id,
            "status": "failed",
            "conclusion": None,
            "evidence": [],
            "confidence": 0.0,
            "abstention_reason": "未收到任何视觉证据，无法生成结论",
            "warnings": ["输入证据为空"],
        }

    normalized = []
    for item in evidences:
        if not isinstance(item.get("object_found"), bool):
            raise SystemExit("[错误] 证据缺少 object_found(boolean)，拒绝生成报告")
        normalized.append(item)
        for gap in item.get("gaps", []) or []:
            warnings.append(str(gap))

    any_abstain = any(isinstance(item.get("abstention_reason"), str) and item["abstention_reason"].strip()
                      for item in normalized)
    found_items = [item for item in normalized if item.get("object_found") is True]
    threshold = spec.get("confidence_threshold", 0.5)
    sufficient_items = [item for item in found_items
                        if float(item.get("confidence", 0.0)) >= threshold
                        and item.get("evidence_sufficient") is not False]

    if any_abstain:
        reasons = [item["abstention_reason"] for item in normalized
                   if isinstance(item.get("abstention_reason"), str) and item["abstention_reason"].strip()]
        status = "abstained"
        abstention_reason = "；".join(reasons)
        if found_items:
            conclusion = "存在部分待确认线索，但证据不足以下结论"
        else:
            conclusion = "证据不足，拒答：未能确认目标存在"
        confidence = max((float(item.get("confidence", 0.0)) for item in normalized), default=0.0)
    elif sufficient_items:
        status = "completed"
        abstention_reason = None
        best = max(sufficient_items, key=lambda item: float(item.get("confidence", 0.0)))
        conclusion = (
            f"目标「{target}」在 {best.get('source_media')} 中被确认存在："
            f"{best.get('description')}。依据：{best.get('evidence_text')}"
        )
        confidence = float(best.get("confidence", 0.0))
    elif found_items:
        status = "abstained"
        abstention_reason = f"检出线索但置信度低于阈值 {threshold}，证据不足"
        conclusion = "存在部分待确认线索，但证据不足以下结论"
        confidence = max(float(item.get("confidence", 0.0)) for item in found_items)
    else:
        status = "completed"
        abstention_reason = None
        conclusion = f"在给定媒体中未确认目标「{target}」存在（负面结论，非肯定性断言）"
        confidence = 0.0

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "task_id": task_id,
        "status": status,
        "conclusion": conclusion,
        "evidence": normalized,
        "confidence": round(confidence, 4),
        "abstention_reason": abstention_reason,
        "warnings": warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------- 视频模式

def classify_frame(entry):
    """帧分类（与 trace_video.aggregate 相同规则，独立实现用于交叉校验）。"""
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    if isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
        return "abstained"
    return "not_found"


def derive_video_status(timeline):
    """按帧条目独立复算视频级状态与统计（不做任何视觉推理，只应用规则）。"""
    entries = timeline if isinstance(timeline, list) else []
    classes = [classify_frame(entry) for entry in entries]
    confirmed = [entry for entry, cls in zip(entries, classes) if cls == "confirmed"]
    counts = {name: classes.count(name) for name in
              ("confirmed", "not_found", "abstained", "low_confidence", "failed")}
    analyzed = counts["confirmed"] + counts["not_found"] + counts["abstained"] + counts["low_confidence"]
    if analyzed == 0:
        status = "failed"
    elif confirmed:
        status = "completed"
    elif counts["abstained"] or counts["low_confidence"]:
        status = "abstained"
    else:
        status = "completed"  # 全部确定性负面（not_found）：负面结论也是完成态
    stats = {
        "first_confirmed_timestamp_ms": confirmed[0].get("timestamp_ms") if confirmed else None,
        "last_confirmed_timestamp_ms": confirmed[-1].get("timestamp_ms") if confirmed else None,
        "confirmed_frame_count": counts["confirmed"],
        "not_found_frame_count": counts["not_found"],
        "abstained_frame_count": counts["abstained"],
        "low_confidence_frame_count": counts["low_confidence"],
        "failed_frame_count": counts["failed"],
        "analyzed_frame_count": analyzed,
        "overall_status": status,
    }
    return status, stats, confirmed


def build_video_report(spec, timeline_doc):
    """视频级报告：结论只能由 timeline 字段组成，不得添加输入外事实。"""
    target = spec.get("target", {}).get("description", "")
    timeline = timeline_doc.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        raise SystemExit("[错误] 视频模式输入缺少非空 timeline 数组，拒绝生成报告")

    status, stats, confirmed = derive_video_status(timeline)
    warnings = [str(item) for item in (timeline_doc.get("warnings") or [])]

    # 与 trace_video 的 summary 交叉校验（两套独立实现互检）
    incoming = timeline_doc.get("summary") or {}
    for key in ("first_confirmed_timestamp_ms", "last_confirmed_timestamp_ms",
                "confirmed_frame_count", "overall_status"):
        if key in incoming and incoming[key] != stats[key]:
            warnings.append(
                f"状态交叉校验不一致：timeline.summary.{key}={incoming[key]!r}，"
                f"本引擎复算={stats[key]!r}；以复算结果为准")

    for entry in timeline:
        for gap in entry.get("gaps") or []:
            warnings.append(f"帧 {entry.get('timestamp_ms')}ms: {gap}")

    confidence = max((float(entry.get("confidence", 0.0)) for entry in confirmed), default=0.0)
    if status == "completed" and confirmed:
        conclusion = (
            f"目标「{target}」在视频 {timeline_doc.get('source_video')} 中被确认出现："
            f"首次确认于 {stats['first_confirmed_timestamp_ms']} ms，"
            f"最后确认于 {stats['last_confirmed_timestamp_ms']} ms，"
            f"共 {stats['confirmed_frame_count']} 帧确认；"
            f"结论可回溯至 timeline 中对应帧（frame_path）"
        )
        abstention_reason = None
    elif status == "completed":
        conclusion = (
            f"在已抽样的 {stats['analyzed_frame_count']} 帧中未确认目标「{target}」存在"
            f"（负面结论，非肯定性断言；未发现与无法确认已严格区分）"
        )
        abstention_reason = None
    elif status == "abstained":
        reasons = [entry["abstention_reason"] for entry in timeline
                   if isinstance(entry.get("abstention_reason"), str)
                   and entry["abstention_reason"].strip()]
        low = stats["low_confidence_frame_count"]
        conclusion = (
            f"证据不足，拒答：{stats['abstained_frame_count']} 帧无法确认"
            + (f"，{low} 帧置信度不足" if low else "")
            + f"，未能确认目标「{target}」存在"
        )
        abstention_reason = "；".join(reasons) if reasons else "证据不足，未能确认目标存在"
    else:  # failed
        reasons = [entry.get("abstention_reason") for entry in timeline
                   if entry.get("frame_status") == "failed"
                   and isinstance(entry.get("abstention_reason"), str)
                   and entry["abstention_reason"].strip()]
        conclusion = (
            f"视频视觉分析未获得任何有效证据（{stats['failed_frame_count']} 帧失败），"
            f"不对目标「{target}」作任何存在性断言"
        )
        abstention_reason = "；".join(reasons[:3]) if reasons else "所有帧均未获得视觉证据"

    return {
        "schema_version": VIDEO_REPORT_SCHEMA_VERSION,
        "report_type": "video_timeline",
        "task_id": spec.get("task_id"),
        "source_video": timeline_doc.get("source_video"),
        "duration_ms": timeline_doc.get("duration_ms"),
        "sampled_frames": timeline_doc.get("sampled_frames"),
        "target_query": timeline_doc.get("target_query") or target,
        "status": status,
        "conclusion": conclusion,
        "confidence": round(confidence, 4),
        "abstention_reason": abstention_reason,
        "summary": stats,
        "evidence": timeline,
        "warnings": warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def looks_like_video_timeline(payload):
    return (isinstance(payload, dict) and isinstance(payload.get("timeline"), list)
            and "source_video" in payload)


# ---------------------------------------------------------------- 多视频模式（任务 06）

MULTI_VIDEO_REPORT_SCHEMA_VERSION = "1.2.0"

SEMANTIC_LIMITATION_NOTE = (
    "跨视频语义限制：同一目标查询在多段视频中分别得到视觉匹配（matched target query；"
    "分别 visually consistent with target description；confirmed in source A / "
    "confirmed in source B）。本报告不断言两来源中的目标是同一个物理实例"
    "（same physical instance），不断言其从来源 A 移动到来源 B（moved from A to B），"
    "不做身份匹配（identity matched）；除非未来存在可靠的跨摄像头身份或实例关联证据。"
    "全局时间线是证据聚合，不是跨摄像头身份追踪。"
)


def looks_like_multi_video_timeline(payload):
    return (isinstance(payload, dict) and isinstance(payload.get("global_timeline"), list)
            and isinstance(payload.get("sources"), list))


def classify_global_entry(entry):
    """全局条目分类（与 trace_multi_video.frame_class 相同规则，独立实现用于交叉校验）。"""
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    if isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
        return "abstained"
    return "not_found"


def derive_multi_video_status(doc):
    """按全局条目独立复算多视频级状态与统计（不做任何视觉推理，只应用规则）。"""
    entries = doc.get("global_timeline") or []
    classes = [classify_global_entry(entry) for entry in entries]
    confirmed = [entry for entry, cls in zip(entries, classes) if cls == "confirmed"]
    counts = {name: classes.count(name) for name in
              ("confirmed", "not_found", "abstained", "low_confidence", "failed")}
    analyzed = (counts["confirmed"] + counts["not_found"]
                + counts["abstained"] + counts["low_confidence"])
    if analyzed == 0:
        status = "failed"
    elif confirmed:
        status = "completed"
    elif counts["abstained"] or counts["low_confidence"]:
        status = "abstained"
    else:
        status = "completed"  # 全部确定性负面（not_found）：负面结论也是完成态
    stats = {
        "first_confirmed_global_timestamp_ms": (
            confirmed[0].get("global_timestamp_ms") if confirmed else None),
        "last_confirmed_global_timestamp_ms": (
            confirmed[-1].get("global_timestamp_ms") if confirmed else None),
        "first_confirmed_source_id": confirmed[0].get("source_id") if confirmed else None,
        "last_confirmed_source_id": confirmed[-1].get("source_id") if confirmed else None,
        "confirmed_entry_count": counts["confirmed"],
        "sources_with_confirmation": sorted({e.get("source_id") for e in confirmed}),
        "class_counts": counts,
        "analyzed_entry_count": analyzed,
    }
    return status, stats, confirmed


def build_multi_video_report(spec, doc):
    """多视频报告：结论只能由 global_timeline / sources 字段组成，不得添加输入外事实；
    必须显示跨视频语义限制；不做任何跨视频身份断言。"""
    target = spec.get("target", {}).get("description", "")
    entries = doc.get("global_timeline")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("[错误] 多视频模式输入缺少非空 global_timeline 数组，拒绝生成报告")

    status, stats, confirmed = derive_multi_video_status(doc)
    warnings = [str(item) for item in (doc.get("warnings") or [])]

    # 与 trace_multi_video 的 global_summary 交叉校验（两套独立实现互检）
    incoming = doc.get("global_summary") or {}
    for key in ("first_confirmed_global_timestamp_ms", "last_confirmed_global_timestamp_ms",
                "confirmed_entry_count", "overall_status"):
        # overall_status 的复算值是 derive_multi_video_status 返回的 status（不在 stats 中）
        recomputed = status if key == "overall_status" else stats.get(key)
        if key in incoming and incoming[key] != recomputed:
            warnings.append(
                f"状态交叉校验不一致：global_summary.{key}={incoming[key]!r}，"
                f"本引擎复算={recomputed!r}；以复算结果为准")

    per_source_reports = []
    for source in doc.get("sources") or []:
        source_summary = source.get("summary") or {}
        per_source_reports.append({
            "source_id": source.get("source_id"),
            "path": source.get("path"),
            "location": source.get("location"),
            "time_offset_ms": source.get("time_offset_ms"),
            "duration_ms": source.get("duration_ms"),
            "sampled_frames": source.get("sampled_frames"),
            "timeline_path": source.get("timeline_path"),
            "summary": source_summary,
            "status": source_summary.get("overall_status"),
            "resource_blocked": source.get("resource_blocked"),
        })

    confidence = max((float(entry.get("confidence", 0.0)) for entry in confirmed), default=0.0)
    source_ids_with_confirmation = stats["sources_with_confirmation"]
    all_source_ids = [item.get("source_id") for item in (doc.get("sources") or [])]
    not_confirmed_sources = [sid for sid in all_source_ids
                             if sid not in source_ids_with_confirmation]

    if status == "completed" and confirmed:
        segments = []
        for source_id in source_ids_with_confirmation:
            entries_in_source = [e for e in confirmed if e.get("source_id") == source_id]
            segments.append(
                f"confirmed in source {source_id}（首次确认于全局 "
                f"{entries_in_source[0].get('global_timestamp_ms')} ms / 原视频 "
                f"{entries_in_source[0].get('timestamp_ms')} ms，最后确认于全局 "
                f"{entries_in_source[-1].get('global_timestamp_ms')} ms，"
                f"共 {len(entries_in_source)} 帧确认）")
        conclusion = (
            f"目标查询「{target}」为 matched target query："
            + "；".join(segments)
            + "。各来源的视觉匹配分别与目标描述 visually consistent with target description；"
            + (f"来源 {'、'.join(not_confirmed_sources)} 未确认（not_found）。"
               if not_confirmed_sources else "")
            + "本报告不断言上述目标是同一个物理实例（无跨摄像头身份或实例关联证据）。"
        )
        abstention_reason = None
    elif status == "completed":
        conclusion = (
            f"在所有已抽样来源中未确认目标查询「{target}」（matched target query 未成立）："
            f"共 {stats['analyzed_entry_count']} 帧分析均为 not_found"
            "（负面结论，非肯定性断言；未发现与无法确认已严格区分）"
        )
        abstention_reason = None
    elif status == "abstained":
        reasons = [entry["abstention_reason"] for entry in entries
                   if isinstance(entry.get("abstention_reason"), str)
                   and entry["abstention_reason"].strip()]
        low = stats["class_counts"]["low_confidence"]
        conclusion = (
            f"证据不足，拒答：{stats['class_counts']['abstained']} 帧无法确认"
            + (f"，{low} 帧置信度不足" if low else "")
            + f"，未能确认目标查询「{target}」在多段视频中的存在"
        )
        abstention_reason = "；".join(reasons) if reasons else "证据不足，未能确认目标存在"
    else:  # failed
        reasons = [entry.get("abstention_reason") for entry in entries
                   if entry.get("frame_status") == "failed"
                   and isinstance(entry.get("abstention_reason"), str)
                   and entry.get("abstention_reason").strip()]
        conclusion = (
            f"多视频视觉分析未获得任何有效证据（{stats['class_counts']['failed']} 帧失败），"
            f"不对目标查询「{target}」作任何存在性断言"
        )
        abstention_reason = "；".join(reasons[:3]) if reasons else "所有帧均未获得视觉证据"

    for entry in entries:
        for gap in entry.get("gaps") or []:
            warnings.append(f"帧 全局{entry.get('global_timestamp_ms')}ms "
                            f"来源{entry.get('source_id')}: {gap}")

    return {
        "schema_version": MULTI_VIDEO_REPORT_SCHEMA_VERSION,
        "report_type": "multi_video_timeline",
        "task_id": spec.get("task_id"),
        "target_query": doc.get("target_query") or target,
        "status": status,
        "conclusion": conclusion,
        "confidence": round(confidence, 4),
        "abstention_reason": abstention_reason,
        "sources": per_source_reports,
        "global_summary": stats,
        "semantic_limitations": doc.get("semantic_limitations") or {
            "cross_video_identity_asserted": False,
            "note": SEMANTIC_LIMITATION_NOTE,
        },
        "semantic_limitation_note": SEMANTIC_LIMITATION_NOTE,
        "evidence": entries,
        "warnings": warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------- 时序证据模式（任务 16）

TEMPORAL_REPORT_SCHEMA_VERSION = "1.3.0"

TEMPORAL_LIMITATION_NOTE = (
    "时序结论语义限制：本报告的目标时序结论是“采样证据支持的时序结论”"
    "（temporal presence evidence / evidence-supported state transition / "
    "boundary uncertainty），不是连续跟踪真值。first/last confirmed 是采样观察时间，"
    "不等于目标真实进入/离开时间；两个 confirmed 采样点之间不得断言目标连续存在；"
    "状态变化只定位到左右相邻采样点形成的时间范围。本报告不做跨帧身份一致性、"
    "不做跨摄像头实例关联、不输出物体运动路径；不是 ReID、不是目标跟踪器、不是实时跟踪。"
)

REAL_MODEL_EVIDENCE_NATURES = ("real_model_output", "backend_call_failed")


def looks_like_temporal_multi_timeline(payload):
    """多来源时序证据（trace_temporal.py 多来源模式产出）。"""
    return (isinstance(payload, dict) and isinstance(payload.get("global_timeline"), list)
            and isinstance(payload.get("sources"), list)
            and isinstance(payload.get("global_temporal_evidence"), dict))


def looks_like_temporal_timeline(payload):
    """单来源时序证据（trace_temporal.py 单视频模式产出）。"""
    return (isinstance(payload, dict) and isinstance(payload.get("timeline"), list)
            and isinstance(payload.get("sampling_provenance"), dict)
            and isinstance(payload.get("temporal_evidence"), dict))


def derive_temporal_evidence(timeline):
    """按时间线条目独立复算时序证据（本引擎自有实现，不导入 extractor 模块；
    与 adaptive_sampler.build_temporal_evidence 两套实现互检）。

    只应用规则，不做任何视觉推理；全部字段可由 timeline 复算。
    """
    entries = sorted((e for e in (timeline or []) if isinstance(e, dict)),
                     key=lambda item: item.get("timestamp_ms", 0))
    classes = [classify_frame(entry) for entry in entries]
    confirmed = [entry for entry, cls in zip(entries, classes) if cls == "confirmed"]
    counts = {name: classes.count(name) for name in
              ("confirmed", "not_found", "abstained", "low_confidence", "failed")}
    analyzed = counts["confirmed"] + counts["not_found"] + counts["abstained"] + counts["low_confidence"]
    transitions = []
    for left, right, cls_l, cls_r in zip(entries, entries[1:], classes, classes[1:]):
        if cls_l != cls_r:
            transitions.append({
                "left_ms": left.get("timestamp_ms"),
                "right_ms": right.get("timestamp_ms"),
                "from_class": cls_l,
                "to_class": cls_r,
                "uncertainty_width_ms": round(right.get("timestamp_ms", 0)
                                              - left.get("timestamp_ms", 0), 3),
            })
    widths = [t["uncertainty_width_ms"] for t in transitions]
    if analyzed == 0:
        status = "failed"
    elif confirmed:
        status = "completed"
    elif counts["abstained"] or counts["low_confidence"]:
        status = "abstained"
    else:
        status = "completed"  # 全部确定性负面（not_found）
    stats = {
        "first_confirmed_observed_ms": confirmed[0].get("timestamp_ms") if confirmed else None,
        "last_confirmed_observed_ms": confirmed[-1].get("timestamp_ms") if confirmed else None,
        "confirmed_sample_count": counts["confirmed"],
        "class_counts": counts,
        "analyzed_sample_count": analyzed,
        "analyzed_ratio": round(analyzed / len(entries), 6) if entries else 0.0,
        "state_transitions": transitions,
        "state_transition_count": len(transitions),
        "max_uncertainty_width_ms": max(widths) if widths else None,
        "overall_status": status,
    }
    return status, stats


def crosscheck_temporal(doc, stats, warnings):
    """与上游 temporal_evidence / sampling_provenance 交叉校验（两套实现互检）。

    不一致时以本引擎复算结果为准并记入 warnings；不静默接受上游摘要，
    不重新调用模型掩盖矛盾。预算越界（实际调用 > 配置预算）也记 warning。
    """
    incoming = doc.get("temporal_evidence") or {}
    checks = [
        ("first_confirmed_observed_ms", incoming.get("first_confirmed_observed_ms")
         if "first_confirmed_observed_ms" in incoming else None,
         stats["first_confirmed_observed_ms"]),
        ("last_confirmed_observed_ms", incoming.get("last_confirmed_observed_ms")
         if "last_confirmed_observed_ms" in incoming else None,
         stats["last_confirmed_observed_ms"]),
        ("confirmed_sample_count", incoming.get("confirmed_sample_count")
         if "confirmed_sample_count" in incoming else None,
         stats["confirmed_sample_count"]),
        ("state_transition_count", incoming.get("state_transition_count")
         if "state_transition_count" in incoming else None,
         stats["state_transition_count"]),
    ]
    for key, upstream, recomputed in checks:
        if upstream is not None and upstream != recomputed:
            warnings.append(
                f"时序证据交叉校验不一致：temporal_evidence.{key}={upstream!r}，"
                f"本引擎复算={recomputed!r}；以复算结果为准")
    provenance = doc.get("sampling_provenance") or {}
    configured = provenance.get("configured_budget")
    actual = provenance.get("actual_model_calls")
    if isinstance(configured, int) and isinstance(actual, int) and actual > configured:
        warnings.append(
            f"调用预算异常：实际视觉调用 {actual} 超过配置预算 {configured}"
            "（硬性预算被突破，以复算记录为准）")
    if isinstance(actual, int):
        entries = doc.get("timeline") or []
        real_calls = len([e for e in entries
                          if e.get("evidence_nature") in REAL_MODEL_EVIDENCE_NATURES])
        constructed = len([e for e in entries
                           if e.get("evidence_nature") == "constructed_fixture_evidence"])
        if constructed == 0 and real_calls != actual:
            # 仅在“全部证据都来自真实模型调用”时做计数交叉校验；
            # 构造 fixture 证据（规则级测试注入）不计为 Qwen 调用，不参与该校验
            warnings.append(
                f"调用计数交叉校验不一致：provenance.actual_model_calls={actual}，"
                f"按 timeline 中真实模型证据条目复算={real_calls}；以复算记录为准")


def build_temporal_report(spec, doc):
    """时序证据报告（任务 16）：依据采样证据独立复算时序结论。

    必须显示：采样策略、视觉调用预算与实际调用数、是否耗尽预算、是否达到目标
    时间精度、“这是采样证据支持的时序结论，不是连续跟踪真值”。
    """
    target = spec.get("target", {}).get("description", "")
    timeline = doc.get("timeline")
    if not isinstance(timeline, list) or not timeline:
        raise SystemExit("[错误] 时序证据模式输入缺少非空 timeline 数组，拒绝生成报告")

    status, stats = derive_temporal_evidence(timeline)
    warnings = [str(item) for item in (doc.get("warnings") or [])]
    crosscheck_temporal(doc, stats, warnings)
    for entry in timeline:
        for gap in entry.get("gaps") or []:
            warnings.append(f"帧 {entry.get('timestamp_ms')}ms: {gap}")

    provenance = doc.get("sampling_provenance") or {}
    temporal = doc.get("temporal_evidence") or {}
    boundary = temporal.get("boundary_uncertainty") or {}
    strategy = doc.get("sampling_strategy")
    budget = provenance.get("configured_budget")
    actual_calls = provenance.get("actual_model_calls")
    budget_exhausted = provenance.get("budget_exhausted")
    precision_target = boundary.get("target_ms")
    precision_reached = boundary.get("target_precision_reached")
    residual = boundary.get("residual_uncertainty_ms")
    resource_blocked = bool(doc.get("backend", {}).get("resource_blocked"))

    # 覆盖几何（任务 18：coverage_aware_adaptive 的 provenance/时序证据附加块；
    # 旧策略下对应字段为 0/None，报告结构保持一致）
    coverage_block = temporal.get("coverage") or {}
    coverage_summary = {
        "coverage_exploration_calls": provenance.get("coverage_exploration_calls"),
        "boundary_refinement_calls": provenance.get("boundary_refinement_calls"),
        "initial_coverage_calls": provenance.get("initial_coverage_calls"),
        "coverage_call_reserve": provenance.get("coverage_call_reserve"),
        "coverage_gap_target_ms": provenance.get("coverage_gap_target_ms"),
        "max_adjacent_sampling_gap_ms_initial": provenance.get(
            "max_adjacent_sampling_gap_ms_initial"),
        "max_adjacent_sampling_gap_ms_final": provenance.get(
            "max_adjacent_sampling_gap_ms_final"),
        "underobserved_intervals": provenance.get("underobserved_intervals"),
        "arbitrary_short_event_detection_guaranteed": coverage_block.get(
            "arbitrary_short_event_detection_guaranteed"),
        "events_shorter_than_max_sampling_gap_may_be_missed": coverage_block.get(
            "events_shorter_than_max_sampling_gap_may_be_missed"),
    }
    coverage_sentence = (
        f"时间覆盖：最大相邻采样间隔 {coverage_summary['max_adjacent_sampling_gap_ms_final']} ms"
        f"（初始 {coverage_summary['max_adjacent_sampling_gap_ms_initial']} ms，"
        f"覆盖目标 {coverage_summary['coverage_gap_target_ms']} ms），"
        f"覆盖探索调用 {coverage_summary['coverage_exploration_calls']} 次、"
        f"边界细化调用 {coverage_summary['boundary_refinement_calls']} 次；"
        "不保证发现任意短事件，宽度小于最大相邻采样间隔的事件可能被漏检。"
    )

    confidence = max((float(entry.get("confidence", 0.0))
                      for entry in timeline if classify_frame(entry) == "confirmed"),
                     default=0.0)
    confirmed = stats["confirmed_sample_count"]
    if status == "completed" and confirmed:
        conclusion = (
            f"目标「{target}」在视频 {doc.get('source_video')} 的采样证据中被确认出现："
            f"首次 confirmed 采样时间 {stats['first_confirmed_observed_ms']} ms，"
            f"最后 confirmed 采样时间 {stats['last_confirmed_observed_ms']} ms，"
            f"共 {confirmed} 帧确认；检测到 {stats['state_transition_count']} 个"
            f"证据支持的状态转换，最大边界不确定宽度 "
            f"{stats['max_uncertainty_width_ms']} ms。"
            f"（采样策略 {strategy}；视觉调用预算 {budget}，实际调用 {actual_calls}，"
            f"耗尽预算={budget_exhausted}；目标边界精度 {precision_target} ms，"
            f"是否达到={precision_reached}）"
            "这是采样证据支持的时序结论，不是连续跟踪真值：采样点之间未断言连续存在。"
            + coverage_sentence
        )
        abstention_reason = None
    elif status == "completed":
        conclusion = (
            f"在已分析的 {stats['analyzed_sample_count']} 个采样点中未确认目标「{target}」"
            f"存在（负面结论，非肯定性断言；未发现与无法确认已严格区分）。"
            f"（采样策略 {strategy}；视觉调用预算 {budget}，实际调用 {actual_calls}，"
            f"耗尽预算={budget_exhausted}）"
            + coverage_sentence
        )
        abstention_reason = None
    elif status == "abstained":
        reasons = [entry["abstention_reason"] for entry in timeline
                   if isinstance(entry.get("abstention_reason"), str)
                   and entry["abstention_reason"].strip()]
        low = stats["class_counts"]["low_confidence"]
        conclusion = (
            f"证据不足，拒答：{stats['class_counts']['abstained']} 个采样点无法确认"
            + (f"，{low} 个采样点置信度不足" if low else "")
            + f"，未能确认目标「{target}」的存在（采样策略 {strategy}；"
            f"视觉调用预算 {budget}，实际调用 {actual_calls}）"
        )
        abstention_reason = "；".join(reasons) if reasons else "证据不足，未能确认目标存在"
    else:  # failed
        reasons = [entry.get("abstention_reason") for entry in timeline
                   if entry.get("frame_status") == "failed"
                   and isinstance(entry.get("abstention_reason"), str)
                   and entry["abstention_reason"].strip()]
        conclusion = (
            f"视频视觉分析未获得任何有效证据"
            f"（{stats['class_counts']['failed']} 个采样点失败"
            + ("；真实视觉调用被资源条件阻塞" if resource_blocked else "")
            + f"），不对目标「{target}」作任何存在性断言"
        )
        abstention_reason = "；".join(reasons[:3]) if reasons else "所有采样点均未获得视觉证据"

    return {
        "schema_version": TEMPORAL_REPORT_SCHEMA_VERSION,
        "report_type": "temporal_evidence",
        "task_id": spec.get("task_id"),
        "target_query": doc.get("target_query") or target,
        "source_video": doc.get("source_video"),
        "input_nature": doc.get("input_nature"),
        "evidence_nature": doc.get("evidence_nature"),
        "sampling_strategy": strategy,
        "vision_call_budget": budget,
        "actual_model_calls": actual_calls,
        "budget_exhausted": budget_exhausted,
        "target_boundary_precision_ms": precision_target,
        "target_precision_reached": precision_reached,
        "residual_uncertainty_ms": residual,
        "resource_blocked": resource_blocked,
        "coverage_summary": coverage_summary,
        "duration_ms": doc.get("duration_ms"),
        "sampled_frames": doc.get("sampled_frames"),
        "status": status,
        "conclusion": conclusion,
        "confidence": round(confidence, 4),
        "abstention_reason": abstention_reason,
        "summary": stats,
        "sampling_provenance": provenance,
        "temporal_evidence": temporal,
        "semantic_limitation_note": TEMPORAL_LIMITATION_NOTE,
        "evidence": timeline,
        "warnings": warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def build_temporal_multi_report(spec, doc):
    """多来源时序证据报告：每来源独立复算 + 全局复算；必须显示跨视频语义限制
    与“采样证据支持的时序结论，不是连续跟踪真值”。"""
    target = spec.get("target", {}).get("description", "")
    entries = doc.get("global_timeline")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("[错误] 多来源时序证据模式输入缺少非空 global_timeline 数组，拒绝生成报告")

    status, stats = derive_temporal_evidence(entries)
    warnings = [str(item) for item in (doc.get("warnings") or [])]
    incoming = doc.get("global_temporal_evidence") or {}
    for key, recomputed in [
        ("first_confirmed_observed_ms", stats["first_confirmed_observed_ms"]),
        ("last_confirmed_observed_ms", stats["last_confirmed_observed_ms"]),
        ("confirmed_sample_count", stats["confirmed_sample_count"]),
        ("state_transition_count", stats["state_transition_count"]),
    ]:
        if key in incoming and incoming[key] != recomputed:
            warnings.append(
                f"全局时序证据交叉校验不一致：global_temporal_evidence.{key}="
                f"{incoming[key]!r}，本引擎复算={recomputed!r}；以复算结果为准")

    per_source_reports = []
    for source in doc.get("sources") or []:
        source_timeline = source.get("timeline") or []
        source_status, source_stats = derive_temporal_evidence(source_timeline)
        per_source_reports.append({
            "source_id": source.get("source_id"),
            "location": source.get("location"),
            "time_offset_ms": source.get("time_offset_ms"),
            "sampled_frames": source.get("sampled_frames"),
            "status": source_status,
            "summary": source_stats,
            "sampling_provenance": source.get("sampling_provenance"),
        })

    shared_budget = doc.get("shared_budget") or {}
    configured = shared_budget.get("max_model_calls")
    actual_calls = shared_budget.get("actual_model_calls")
    if (isinstance(configured, int) and isinstance(actual_calls, int)
            and actual_calls > configured):
        warnings.append(
            f"调用预算异常：全局实际视觉调用 {actual_calls} 超过配置预算 {configured}")
    strategy = doc.get("sampling_strategy")

    if status == "completed" and stats["confirmed_sample_count"]:
        conclusion = (
            f"目标查询「{target}」为 matched target query："
            + "；".join(
                f"confirmed in source {item['source_id']}（首次 confirmed 采样时间 "
                f"{item['summary']['first_confirmed_observed_ms']} ms / 全局 "
                f"{(item['summary']['first_confirmed_observed_ms'] or 0) + (item.get('time_offset_ms') or 0)} ms，"
                f"最后 confirmed 采样时间 {item['summary']['last_confirmed_observed_ms']} ms，"
                f"共 {item['summary']['confirmed_sample_count']} 帧确认）"
                for item in per_source_reports
                if item["summary"]["confirmed_sample_count"])
            + f"；全局检测到 {stats['state_transition_count']} 个证据支持的状态转换，"
            f"最大边界不确定宽度 {stats['max_uncertainty_width_ms']} ms。"
            f"（采样策略 {strategy}；全局视觉调用预算 {configured}，实际调用 {actual_calls}）"
            "各来源的视觉匹配分别与目标描述 visually consistent with target description；"
            "本报告不断言上述目标是同一个物理实例（无跨摄像头身份或实例关联证据）。"
            "全局时间线是证据聚合，不是跨摄像头身份追踪；时序结论是采样证据支持的结论，"
            "不是连续跟踪真值。"
        )
        abstention_reason = None
    elif status == "completed":
        conclusion = (
            f"在所有已抽样来源中未确认目标查询「{target}（matched target query 未成立）："
            f"共 {stats['analyzed_sample_count']} 个全局条目分析均为 not_found"
            "（负面结论，非肯定性断言；未发现与无法确认已严格区分）"
        )
        abstention_reason = None
    elif status == "abstained":
        reasons = [entry["abstention_reason"] for entry in entries
                   if isinstance(entry.get("abstention_reason"), str)
                   and entry["abstention_reason"].strip()]
        low = stats["class_counts"]["low_confidence"]
        conclusion = (
            f"证据不足，拒答：{stats['class_counts']['abstained']} 个全局条目无法确认"
            + (f"，{low} 个置信度不足" if low else "")
            + f"，未能确认目标查询「{target}」在多段视频中的存在"
        )
        abstention_reason = "；".join(reasons) if reasons else "证据不足，未能确认目标存在"
    else:
        reasons = [entry.get("abstention_reason") for entry in entries
                   if entry.get("frame_status") == "failed"
                   and isinstance(entry.get("abstention_reason"), str)
                   and entry["abstention_reason"].strip()]
        conclusion = (
            f"多视频视觉分析未获得任何有效证据"
            f"（{stats['class_counts']['failed']} 个全局条目失败），"
            f"不对目标查询「{target}」作任何存在性断言"
        )
        abstention_reason = "；".join(reasons[:3]) if reasons else "所有条目均未获得视觉证据"

    return {
        "schema_version": TEMPORAL_REPORT_SCHEMA_VERSION,
        "report_type": "temporal_multi_video",
        "task_id": spec.get("task_id"),
        "target_query": doc.get("target_query") or target,
        "input_nature": doc.get("input_nature"),
        "evidence_nature": doc.get("evidence_nature"),
        "sampling_strategy": strategy,
        "vision_call_budget": configured,
        "actual_model_calls": actual_calls,
        "budget_exhausted": shared_budget.get("budget_exhausted"),
        "sources": per_source_reports,
        "global_summary": stats,
        "global_temporal_evidence": incoming,
        "shared_budget": shared_budget,
        "semantic_limitations": doc.get("semantic_limitations") or {
            "cross_video_identity_asserted": False,
            "note": SEMANTIC_LIMITATION_NOTE,
        },
        "semantic_limitation_note": SEMANTIC_LIMITATION_NOTE,
        "temporal_limitation_note": TEMPORAL_LIMITATION_NOTE,
        "status": status,
        "conclusion": conclusion,
        "abstention_reason": abstention_reason,
        "evidence": entries,
        "warnings": warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="生成证据链报告")
    parser.add_argument("--task-spec", required=True, help="VisualTaskSpec JSON 路径")
    parser.add_argument("--evidence", required=True, help="证据 JSON（对象/数组/视频时间线）路径")
    parser.add_argument("--output", help="报告 JSON 输出路径（默认打印到 stdout）")
    parser.add_argument("--mode",
                        choices=["auto", "image", "video", "multi-video",
                                 "temporal", "temporal-multi"],
                        default="auto",
                        help="auto=按输入结构自动判别（默认）；temporal=单来源时序证据报告；"
                             "temporal-multi=多来源时序证据报告")
    args = parser.parse_args()

    spec = load_json(args.task_spec, "任务规格")
    evidence_payload = load_json(args.evidence, "证据")

    if args.mode == "temporal-multi" or (args.mode == "auto"
                                         and looks_like_temporal_multi_timeline(evidence_payload)):
        report = build_temporal_multi_report(spec, evidence_payload)
    elif args.mode == "temporal" or (args.mode == "auto"
                                     and looks_like_temporal_timeline(evidence_payload)):
        report = build_temporal_report(spec, evidence_payload)
    elif args.mode == "multi-video" or (args.mode == "auto"
                                        and looks_like_multi_video_timeline(evidence_payload)):
        report = build_multi_video_report(spec, evidence_payload)
    elif args.mode == "video" or (args.mode == "auto" and looks_like_video_timeline(evidence_payload)):
        report = build_video_report(spec, evidence_payload)
    else:
        evidences = as_evidence_list(evidence_payload)
        report = build_report(spec, evidences)

    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"[完成] 报告已写入 {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
