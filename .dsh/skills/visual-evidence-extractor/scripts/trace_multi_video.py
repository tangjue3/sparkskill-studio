#!/usr/bin/env python3
"""trace_multi_video.py — 多段视频统一证据时间线（SparkSkill Studio 任务 06）

链路位置：
    自然语言任务 → StepFun 生成多媒体 VisualTaskSpec → 本脚本对 source_media
    中每个视频依次调用 trace_video.trace()（任务 04 单段视频能力原样复用）
    → 每段独立时间线 → 按 time_offset_ms 计算全局排序时间 → 统一全局时间线
    → 跨视频证据摘要（不含跨视频身份断言）。

设计红线（硬约束）:
  - 禁止重写第二套视觉提示词或视频处理逻辑：逐帧分析完全复用
    scripts/trace_video.py（其内部再复用 scripts/analyze_image.py）；
  - 不得凭空生成时间线：全局时间线每一项都必须对应某个来源真实抽取的帧文件；
  - 保留 source_id、原视频时间戳、全局排序时间；失败/拒答/未发现帧一律保留，不丢弃；
  - 不伪造跨视频关系：同一目标查询在多段视频中分别得到视觉匹配，
    不得自动得出"同一个物理对象从 A 移动到 B"的结论；
  - 资源守卫：统一内存不足时不强行加载 Qwen，如实降级为 failed。

用法:
    python3 trace_multi_video.py --task-spec <spec.json> --output <global-timeline.json> \
        [--interval-ms 1000] [--max-frames 6] [--per-source-dir <dir>] \
        [--save-raw-dir <dir>] [--min-available-gib 40] [--allow-low-memory] [--timeout 300]

退出码: 0 = global-timeline.json 已生成（整体状态见 global_summary.overall_status）;
         2 = 用法/规格错误; 3 = 抽帧或来源处理失败
"""
import argparse
import datetime
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skill_env  # noqa: E402

skill_env.ensure_cv2_interpreter()  # 无 cv2 时切换解释器（execv 后本行不会返回）

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
EXTRACTOR_DIR = os.path.dirname(SCRIPT_DIR)
COMPILER_SCRIPTS = os.path.abspath(os.path.join(EXTRACTOR_DIR, "..",
                                                "task-to-skill-compiler", "scripts"))
GLOBAL_TIMELINE_SCHEMA_VERSION = "1.2.0"
LEGACY_SOURCE_ID = "media-0"


def load_sibling_module(name, filename):
    path = os.path.join(SCRIPT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_validator_module():
    """加载 task-to-skill-compiler 的校验器（复用其路径安全规则，不重复实现）。"""
    path = os.path.join(COMPILER_SCRIPTS, "validate_task_spec.py")
    spec = importlib.util.spec_from_file_location("validate_task_spec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trace_video = load_sibling_module("trace_video", "trace_video.py")
extract_frames_mod = load_sibling_module("extract_frames", "extract_frames.py")


class MultiTraceError(Exception):
    """用法/规格类错误（非敏感）。"""


# ---------------------------------------------------------------- 规格解析

def normalize_sources(spec):
    """把 source_media 规范化为来源对象列表。

    - 数组（多段视频，任务 06）：每项必须有 source_id 与 path；time_offset_ms 默认 0；
    - 字符串（旧版单媒体任务，向后兼容）：包装为单一来源（source_id=media-0）。
    """
    source_media = spec.get("source_media")
    if isinstance(source_media, str):
        return [{
            "source_id": "media-0",
            "path": source_media,
            "location": None,
            "time_offset_ms": 0,
        }]
    if not isinstance(source_media, list) or not source_media:
        raise MultiTraceError(
            "任务规格 source_media 必须是非空来源数组（多段视频）或单个路径字符串（旧版兼容）")
    sources = []
    seen = set()
    for index, item in enumerate(source_media):
        if not isinstance(item, dict):
            raise MultiTraceError(f"source_media[{index}] 必须是对象")
        source_id = item.get("source_id")
        path = item.get("path")
        if not isinstance(source_id, str) or not source_id.strip():
            raise MultiTraceError(f"source_media[{index}] 缺少合法 source_id")
        if source_id in seen:
            raise MultiTraceError(f"source_id {source_id!r} 在同一任务内重复（必须唯一）")
        seen.add(source_id)
        if not isinstance(path, str) or not path.strip():
            raise MultiTraceError(f"source_media[{index}] 缺少合法 path")
        offset = item.get("time_offset_ms", 0)
        if not isinstance(offset, (int, float)) or isinstance(offset, bool) or offset < 0:
            raise MultiTraceError(
                f"source_media[{index}] time_offset_ms 必须为非负数，得到 {offset!r}")
        location = item.get("location")
        if location is not None and not isinstance(location, str):
            raise MultiTraceError(f"source_media[{index}] location 必须是字符串或缺失")
        sources.append({
            "source_id": source_id,
            "path": path,
            "location": location,
            "time_offset_ms": offset,
        })
    return sources


def guard_spec(spec):
    """规格最小守卫（与 trace_video.py 一致；完整校验由 validate_task_spec.py 负责）。"""
    if spec.get("requires_visual_input") is not True:
        raise MultiTraceError("任务规格 requires_visual_input 必须为 true")
    if spec.get("task_type") not in ("object_trace", "object_presence"):
        raise MultiTraceError(f"不支持的 task_type: {spec.get('task_type')!r}")
    if not spec.get("target", {}).get("description"):
        raise MultiTraceError("任务规格缺少 target.description")


def guard_source_paths(sources):
    """执行期路径安全复核（复用 task-to-skill-compiler 的路径规则，纵深防御）。"""
    try:
        validator = load_validator_module()
    except Exception as error:  # 校验器不可用时拒绝执行（宁可拒答不可放行）
        raise MultiTraceError(f"无法加载路径安全校验器，拒绝执行: {type(error).__name__}")
    for source in sources:
        problems = validator.check_media_path(source["path"], f"source {source['source_id']}")
        if problems:
            raise MultiTraceError("；".join(problems))


# ---------------------------------------------------------------- 聚合

def frame_class(entry):
    """帧分类规则与 trace_video.frame_class 完全一致（confirmed/not_found/abstained/
    low_confidence/failed），保证多视频聚合与单视频聚合同规则。"""
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    if isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
        return "abstained"
    return "not_found"


GLOBAL_ENTRY_FIELDS = (
    "timestamp_ms", "frame_path", "object_found", "description", "bounding_box",
    "bounding_box_raw", "bounding_box_source_format", "bounding_box_normalization_applied",
    "frame_width", "frame_height", "confidence", "evidence_text", "abstention_reason",
    "frame_status", "evidence_sufficient", "gaps", "warnings",
)


def merge_global_timeline(per_source_entries):
    """合并各来源帧条目为统一全局时间线。

    - global_timestamp_ms = 原视频 timestamp_ms + 来源 time_offset_ms；
    - 按 (global_timestamp_ms, source_id) 排序；允许不同来源全局时间相同（不要求跨来源严格递增）；
    - 每个条目保留 source_id / source_path / source_time_offset_ms / 原 timestamp_ms，
      可回溯到来源视频与关键帧；
    - 不丢弃任何帧（failed/abstained/not_found 全部保留）；
    - 不做任何跨视频同一性断言。
    """
    merged = []
    for source in per_source_entries:
        offset = source["time_offset_ms"]
        for entry in source["timeline"]:
            record = {
                "global_timestamp_ms": round(entry["timestamp_ms"] + offset, 3),
                "source_id": source["source_id"],
                "source_path": source["path"],
                "source_location": source["location"],
                "source_time_offset_ms": offset,
            }
            for field in GLOBAL_ENTRY_FIELDS:
                record[field] = entry.get(field)
            merged.append(record)
    merged.sort(key=lambda item: (item["global_timestamp_ms"], item["source_id"]))

    times = [item["global_timestamp_ms"] for item in merged]
    if any(b < a for a, b in zip(times, times[1:])):
        raise MultiTraceError("全局时间线排序失败（内部错误，拒绝输出）")
    return merged


def summarize_global(merged, per_source_summaries):
    """全局摘要：首次/最后确认（全局时间）、分类计数、每来源统计、整体状态。

    状态规则与单视频聚合一致：无任何 analyzed → failed；有 confirmed → completed；
    无 confirmed 但有 abstained/low_confidence → abstained；全部 not_found →
    completed（负面结论也是完成态）。
    """
    classes = [frame_class(entry) for entry in merged]
    confirmed = [entry for entry, cls in zip(merged, classes) if cls == "confirmed"]
    counts = {name: classes.count(name) for name in
              ("confirmed", "not_found", "abstained", "low_confidence", "failed")}
    analyzed = (counts["confirmed"] + counts["not_found"]
                + counts["abstained"] + counts["low_confidence"])

    if analyzed == 0:
        overall = "failed"
    elif confirmed:
        overall = "completed"
    elif counts["abstained"] or counts["low_confidence"]:
        overall = "abstained"
    else:
        overall = "completed"

    per_source = {}
    for source_id, summary in per_source_summaries.items():
        per_source[source_id] = {
            "first_confirmed_timestamp_ms": summary.get("first_confirmed_timestamp_ms"),
            "last_confirmed_timestamp_ms": summary.get("last_confirmed_timestamp_ms"),
            "confirmed_frame_count": summary.get("confirmed_frame_count", 0),
            "not_found_frame_count": summary.get("not_found_frame_count", 0),
            "abstained_frame_count": summary.get("abstained_frame_count", 0),
            "low_confidence_frame_count": summary.get("low_confidence_frame_count", 0),
            "failed_frame_count": summary.get("failed_frame_count", 0),
            "analyzed_frame_count": summary.get("analyzed_frame_count", 0),
            "overall_status": summary.get("overall_status"),
        }

    return {
        "first_confirmed_global_timestamp_ms": (
            confirmed[0]["global_timestamp_ms"] if confirmed else None),
        "last_confirmed_global_timestamp_ms": (
            confirmed[-1]["global_timestamp_ms"] if confirmed else None),
        "first_confirmed_source_id": confirmed[0]["source_id"] if confirmed else None,
        "last_confirmed_source_id": confirmed[-1]["source_id"] if confirmed else None,
        "confirmed_entry_count": counts["confirmed"],
        "sources_with_confirmation": sorted({
            entry["source_id"] for entry in confirmed}),
        "class_counts": counts,
        "analyzed_entry_count": analyzed,
        "per_source": per_source,
        "overall_status": overall,
    }


SEMANTIC_LIMITATIONS = {
    "cross_video_identity_asserted": False,
    "statement_policy": (
        "matched target query / visually consistent with target description / "
        "confirmed in source A / confirmed in source B"),
    "allowed_phrasings": [
        "matched target query",
        "visually consistent with target description",
        "confirmed in source A",
        "confirmed in source B",
    ],
    "forbidden_phrasings": [
        "same physical instance",
        "moved from A to B",
        "carried by the same person",
        "entered another camera",
        "identity matched",
    ],
    "note": (
        "同一目标查询在多段视频中分别得到视觉匹配，仅此而已；不得自动得出"
        "“同一个物理对象从视频 A 移动到视频 B”的结论。除非未来存在可靠的跨摄像头"
        "身份或实例关联证据，本流水线不输出任何跨视频身份断言。"),
}


# ---------------------------------------------------------------- 主流程

def trace_multi(spec, output_path, interval_ms=1000, max_frames=8,
                per_source_dir=None, model=None, timeout=300,
                min_available_gib=trace_video.DEFAULT_MIN_AVAILABLE_GIB,
                allow_low_memory=False, save_raw_dir=None):
    model = model or trace_video.analyze_image.DEFAULT_MODEL
    guard_spec(spec)
    sources = normalize_sources(spec)
    guard_source_paths(sources)

    output_path = os.path.abspath(output_path)
    base_dir = per_source_dir or os.path.join(os.path.dirname(output_path), "per-source")
    os.makedirs(base_dir, exist_ok=True)

    per_source_entries = []
    source_reports = []
    all_warnings = []

    for source in sources:
        source_id = source["source_id"]
        timeline_path = os.path.join(base_dir, f"{source_id}-timeline.json")
        frames_dir = os.path.join(base_dir, "keyframes", source_id)
        raw_dir = os.path.join(save_raw_dir, source_id) if save_raw_dir else None
        try:
            timeline_doc = trace_video.trace(
                spec, source["path"], timeline_path,
                interval_ms=interval_ms, max_frames=max_frames,
                frames_dir=frames_dir, model=model, timeout=timeout,
                min_available_gib=min_available_gib,
                allow_low_memory=allow_low_memory, save_raw_dir=raw_dir,
            )
        except trace_video.TraceError as error:
            raise MultiTraceError(f"来源 {source_id} 处理失败: {error}")
        except extract_frames_mod.ExtractionError as error:
            raise MultiTraceError(f"来源 {source_id} 抽帧失败: {error}")

        per_source_entries.append({
            "source_id": source_id,
            "path": source["path"],
            "location": source["location"],
            "time_offset_ms": source["time_offset_ms"],
            "timeline": timeline_doc["timeline"],
        })
        source_reports.append({
            "source_id": source_id,
            "path": timeline_doc["source_video"],
            "location": source["location"],
            "time_offset_ms": source["time_offset_ms"],
            "duration_ms": timeline_doc["duration_ms"],
            "sampled_frames": timeline_doc["sampled_frames"],
            "timeline_path": timeline_path,
            "keyframes_dir": frames_dir,
            "summary": timeline_doc["summary"],
            "warnings": timeline_doc["warnings"],
            "resource_blocked": timeline_doc["backend"]["resource_blocked"],
        })
        all_warnings.extend(f"来源 {source_id}: {message}"
                            for message in timeline_doc["warnings"])

    merged = merge_global_timeline(per_source_entries)
    per_source_summaries = {item["source_id"]: item["summary"] for item in source_reports}
    global_summary = summarize_global(merged, per_source_summaries)

    result = {
        "schema_version": GLOBAL_TIMELINE_SCHEMA_VERSION,
        "task_id": spec.get("task_id"),
        "target_query": spec.get("target", {}).get("description", ""),
        "sources": source_reports,
        "global_timeline": merged,
        "global_summary": global_summary,
        "semantic_limitations": SEMANTIC_LIMITATIONS,
        "backend": {
            "vision_backend": "ollama",
            "model": model,
            "analysis_logic": "scripts/trace_video.py（任务 04 单段视频能力原样复用，"
                              "其内部再复用 scripts/analyze_image.py 任务 03 图片能力，"
                              "未重写视觉提示词体系）",
            "frame_extraction": "scripts/extract_frames.py（opencv，仅作底层抽帧工具）",
            "multi_source_aggregation": "scripts/trace_multi_video.py（任务 06）",
            "resource_blocked": any(item["resource_blocked"] for item in source_reports),
        },
        "warnings": all_warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="多段视频统一证据时间线（复用 trace_video.py 单段能力）")
    parser.add_argument("--task-spec", required=True, help="多媒体 VisualTaskSpec JSON 路径")
    parser.add_argument("--output", required=True, help="global-timeline.json 输出路径")
    parser.add_argument("--interval-ms", type=float, default=1000, help="每来源采样间隔（毫秒，默认 1000）")
    parser.add_argument("--max-frames", type=int, default=8, help="每来源最大帧数（默认 8）")
    parser.add_argument("--per-source-dir", default=None,
                        help="每来源时间线/关键帧目录（默认 <output 目录>/per-source）")
    parser.add_argument("--save-raw-dir", default=None, help="模型原始返回存档目录（审计用）")
    parser.add_argument("--model", default=None, help="Ollama 模型名（默认同 analyze_image.py）")
    parser.add_argument("--timeout", type=int, default=300, help="单帧调用超时秒数")
    parser.add_argument("--min-available-gib", type=float,
                        default=trace_video.DEFAULT_MIN_AVAILABLE_GIB,
                        help="资源守卫：调用视觉模型所需的最低可用内存（GiB，默认 40）")
    parser.add_argument("--allow-low-memory", action="store_true",
                        help="覆盖资源守卫强制调用（仅在确认资源窗口时使用，有 OOM 风险）")
    args = parser.parse_args()

    try:
        with open(args.task_spec, encoding="utf-8") as handle:
            spec = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[错误] 无法读取任务规格: {error}", file=sys.stderr)
        return 2

    try:
        result = trace_multi(
            spec, args.output,
            interval_ms=args.interval_ms, max_frames=args.max_frames,
            per_source_dir=args.per_source_dir, model=args.model, timeout=args.timeout,
            min_available_gib=args.min_available_gib,
            allow_low_memory=args.allow_low_memory, save_raw_dir=args.save_raw_dir,
        )
    except MultiTraceError as error:
        print(f"[错误] {error}", file=sys.stderr)
        return 2
    except extract_frames_mod.ExtractionError as error:
        print(f"[错误] 抽帧失败: {error}", file=sys.stderr)
        return 3

    summary = result["global_summary"]
    print(f"[完成] 全局时间线已写入 {args.output}")
    print(f"  来源数={len(result['sources'])} 全局条目数={len(result['global_timeline'])} "
          f"确认条目={summary['confirmed_entry_count']} 整体状态={summary['overall_status']}")
    print(f"  首次确认（全局）={summary['first_confirmed_global_timestamp_ms']} ms "
          f"最后确认（全局）={summary['last_confirmed_global_timestamp_ms']} ms")
    print("  跨视频语义限制：不断言同一物理实例（详见 semantic_limitations）")
    if result["backend"]["resource_blocked"]:
        print("  [资源阻塞] 至少一个来源的真实视觉调用被资源条件阻塞", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
