#!/usr/bin/env python3
"""trace_video.py — 短视频视觉证据时间线（SparkSkill Studio 任务 04）

链路位置：
    自然语言任务 → StepFun 生成 VisualTaskSpec → extract_frames.py 抽帧
    → 逐帧调用 analyze_image.py（任务 03 已有图片分析能力）→ 聚合 → timeline.json

设计红线:
  - 禁止重新实现一套独立的视觉提示词体系：逐帧分析完全复用
    scripts/analyze_image.py 的 build_prompt / call_ollama / coerce_evidence；
  - 不得凭空生成时间线：timeline 中每一项都必须对应一个真实抽取的帧文件；
  - 不得把连续帧自动解释成同一个对象：时间线只记录逐帧独立结论，
    不做身份跟踪、不做跨镜头关联、不做没有证据的路径推断；
  - bounding_box 不可靠时保持 null，禁止把整幅图片框成目标框；
  - 证据不足时必须保留 abstention_reason；
  - 资源守卫：统一内存不足时不强行加载 Qwen（避免 OOM 影响 MiniMax-H3），
    该情况如实降级为 failed 并记录原因，不用伪造输出冒充真实视觉结果。

用法:
    python3 trace_video.py --task-spec <spec.json> --video <path.mp4> \
        --output <timeline.json> [--interval-ms 1000] [--max-frames 8] \
        [--start-ms 0] [--end-ms N] [--frames-dir <dir>] [--save-raw-dir <dir>] \
        [--min-available-gib 40] [--allow-low-memory] [--timeout 300]

退出码: 0 = timeline.json 已生成（整体状态见 summary.overall_status）;
        2 = 用法/规格/视频错误; 3 = 抽帧失败
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
TIMELINE_SCHEMA_VERSION = "1.1.0"
DEFAULT_MIN_AVAILABLE_GIB = 40.0  # Qwen3.8-27B 加载约需 34.6 GB，留出系统余量


def load_sibling_module(name, filename):
    path = os.path.join(SCRIPT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analyze_image = load_sibling_module("analyze_image", "analyze_image.py")
extract_frames_mod = load_sibling_module("extract_frames", "extract_frames.py")


class TraceError(Exception):
    """用法/规格/抽帧类错误（非敏感）。"""


# ---------------------------------------------------------------- 资源守卫

def mem_available_gib():
    """读取 /proc/meminfo 的 MemAvailable（GiB）；读不到返回 None。"""
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 1024.0 / 1024.0, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def ollama_reachable(timeout=5):
    """仅探测 Ollama 服务是否可达（GET /api/tags 不会加载模型）。"""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout):
            return True
    except Exception:
        return False


def resource_guard(min_available_gib):
    """返回 (blocked, info)。blocked=True 时禁止调用视觉模型。"""
    available = mem_available_gib()
    info = {
        "mem_available_gib": available,
        "min_available_gib": min_available_gib,
        "ollama_reachable": ollama_reachable(),
    }
    if not info["ollama_reachable"]:
        info["blocked"] = True
        info["reason"] = "Ollama 服务不可达（127.0.0.1:11434），未执行任何视觉调用"
        return True, info
    if available is None:
        info["blocked"] = True
        info["reason"] = "无法读取 MemAvailable，按资源不可知处理，拒绝调用视觉模型"
        return True, info
    if available < min_available_gib:
        info["blocked"] = True
        info["reason"] = (
            f"统一内存可用量 {available} GiB 低于阈值 {min_available_gib} GiB"
            "（Qwen Vision 加载约需 34.6 GB；MiniMax-H3 运行中），"
            "为避免 OOM 未加载模型，本轮不执行真实视觉调用"
        )
        return True, info
    info["blocked"] = False
    return False, info


# ---------------------------------------------------------------- 逐帧分析

def failed_entry(frame, reason):
    """帧级失败条目：不伪造任何视觉结论，只记录失败原因。"""
    return {
        "timestamp_ms": frame["timestamp_ms"],
        "frame_path": frame["frame_path"],
        "object_found": False,
        "description": "本帧未执行视觉分析（后端未调用）",
        "bounding_box": None,
        "bounding_box_raw": None,
        "bounding_box_source_format": None,
        "bounding_box_normalization_applied": False,
        "frame_width": None,
        "frame_height": None,
        "confidence": 0.0,
        "evidence_text": "无模型输出；本帧仅完成抽取，未获得任何视觉证据",
        "abstention_reason": reason,
        "frame_status": "failed",
        "evidence_sufficient": False,
        "gaps": ["视觉后端未调用，本帧无证据"],
        "warnings": [],
    }


def analyze_frame(spec, frame, model, timeout, raw_dir=None):
    """对单帧执行真实视觉分析（完全复用 analyze_image.py 的任务 03 逻辑）。"""
    prompt = analyze_image.build_prompt(spec)
    body = analyze_image.call_ollama(model, prompt, frame["frame_path"], timeout)
    raw_text = body.get("response", "")
    if raw_dir:
        os.makedirs(raw_dir, exist_ok=True)
        raw_name = f"frame_{frame['index']:05d}_t{int(round(frame['timestamp_ms'])):08d}ms.raw.json"
        with open(os.path.join(raw_dir, raw_name), "w", encoding="utf-8") as handle:
            handle.write(raw_text)
    raw = json.loads(raw_text)
    evidence = analyze_image.coerce_evidence(raw, spec, frame["frame_path"], model)
    return {
        "timestamp_ms": frame["timestamp_ms"],
        "frame_path": frame["frame_path"],
        "object_found": evidence["object_found"],
        "description": evidence["description"],
        "bounding_box": evidence["bounding_box"],
        "bounding_box_raw": evidence.get("bounding_box_raw"),
        "bounding_box_source_format": evidence.get("bounding_box_source_format"),
        "bounding_box_normalization_applied": evidence.get("bounding_box_normalization_applied", False),
        "frame_width": evidence.get("frame_width"),
        "frame_height": evidence.get("frame_height"),
        "confidence": evidence["confidence"],
        "evidence_text": evidence["evidence_text"],
        "abstention_reason": evidence["abstention_reason"],
        "frame_status": "analyzed",
        "evidence_sufficient": evidence["evidence_sufficient"],
        "gaps": evidence["gaps"],
        "warnings": list(evidence.get("warnings") or []),
    }


# ---------------------------------------------------------------- 聚合

def frame_class(entry):
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    if isinstance(entry.get("abstention_reason"), str) and entry["abstention_reason"].strip():
        return "abstained"
    return "not_found"


def dedup_key(entry):
    return json.dumps({
        "object_found": entry.get("object_found"),
        "description": entry.get("description"),
        "bounding_box": entry.get("bounding_box"),
        "confidence": entry.get("confidence"),
        "evidence_text": entry.get("evidence_text"),
        "abstention_reason": entry.get("abstention_reason"),
        "frame_status": entry.get("frame_status"),
    }, ensure_ascii=False, sort_keys=True)


def aggregate(entries):
    """第一版聚合策略：按时间戳排序；删除连续完全重复结果；保留关键状态变化；
    记录首次/最后确认与确认帧数量；严格区分 not_found 与 abstained；
    不做身份跟踪、不做跨镜头关联、不做没有证据的路径推断。"""
    ordered = sorted(entries, key=lambda item: item["timestamp_ms"])
    timestamps = [item["timestamp_ms"] for item in ordered]
    if any(b <= a for a, b in zip(timestamps, timestamps[1:])):
        raise TraceError("聚合失败：时间戳未严格单调递增")

    state_changes = []
    for entry in ordered:
        key = dedup_key(entry)
        if not state_changes or state_changes[-1]["state_key"] != key:
            record = {field: entry[field] for field in (
                "timestamp_ms", "frame_path", "object_found", "description",
                "bounding_box", "confidence", "evidence_text",
                "abstention_reason", "frame_status")}
            record["state_key"] = key
            state_changes.append(record)
    for record in state_changes:
        record.pop("state_key", None)

    classes = [frame_class(entry) for entry in ordered]
    confirmed = [entry for entry, cls in zip(ordered, classes) if cls == "confirmed"]
    counts = {name: classes.count(name) for name in
              ("confirmed", "not_found", "abstained", "low_confidence", "failed")}
    analyzed_count = counts["confirmed"] + counts["not_found"] + counts["abstained"] + counts["low_confidence"]

    if analyzed_count == 0:
        overall = "failed"
    elif confirmed:
        overall = "completed"
    elif counts["abstained"] or counts["low_confidence"]:
        overall = "abstained"
    else:
        overall = "completed"  # 全部为确定性负面结论（not_found），负面结论也是完成态

    summary = {
        "first_confirmed_timestamp_ms": confirmed[0]["timestamp_ms"] if confirmed else None,
        "last_confirmed_timestamp_ms": confirmed[-1]["timestamp_ms"] if confirmed else None,
        "confirmed_frame_count": counts["confirmed"],
        "not_found_frame_count": counts["not_found"],
        "abstained_frame_count": counts["abstained"],
        "low_confidence_frame_count": counts["low_confidence"],
        "failed_frame_count": counts["failed"],
        "analyzed_frame_count": analyzed_count,
        "overall_status": overall,
    }
    return ordered, state_changes, summary


# ---------------------------------------------------------------- 主流程

def trace(spec, video_path, output_path, interval_ms=1000, max_frames=8,
          start_ms=0, end_ms=None, frames_dir=None, model=None, timeout=300,
          min_available_gib=DEFAULT_MIN_AVAILABLE_GIB, allow_low_memory=False,
          save_raw_dir=None):
    model = model or analyze_image.DEFAULT_MODEL

    # 规格最小守卫（与 analyze_image.py 一致；完整校验由 validate_task_spec.py 负责）
    if spec.get("requires_visual_input") is not True:
        raise TraceError("任务规格 requires_visual_input 必须为 true")
    if spec.get("task_type") not in ("object_trace", "object_presence"):
        raise TraceError(f"不支持的 task_type: {spec.get('task_type')!r}")
    if not spec.get("target", {}).get("description"):
        raise TraceError("任务规格缺少 target.description")

    frames_dir = frames_dir or os.path.join(
        os.path.dirname(os.path.abspath(output_path)), "frames",
        os.path.splitext(os.path.basename(video_path))[0])

    extraction = extract_frames_mod.extract_frames(
        video_path, frames_dir, interval_ms=interval_ms, max_frames=max_frames,
        start_ms=start_ms, end_ms=end_ms)

    blocked, guard_info = (False, {"blocked": False}) if allow_low_memory \
        else resource_guard(min_available_gib)

    entries = []
    warnings = list(extraction["warnings"])
    for frame in extraction["frames"]:
        if blocked:
            entries.append(failed_entry(frame, guard_info["reason"]))
            continue
        try:
            entries.append(analyze_frame(spec, frame, model, timeout, save_raw_dir))
        except Exception as error:
            # 单帧失败不中断整条时间线；错误信息只含类型与消息，不含凭据
            entries.append(failed_entry(
                frame, f"帧分析失败：{type(error).__name__}: {error}"))

    timeline, state_changes, summary = aggregate(entries)
    if summary["failed_frame_count"]:
        warnings.append(
            f"{summary['failed_frame_count']} 帧未获得视觉证据（失败原因见各帧 abstention_reason），"
            "不计入确认，未伪造任何结论")
    for entry in timeline:
        for message in entry.get("warnings") or []:
            warnings.append(f"帧 {entry.get('timestamp_ms')}ms: {message}")
    if blocked:
        warnings.append("真实视频视觉调用被资源条件阻塞（详见 backend.resource_guard.reason）")

    result = {
        "schema_version": TIMELINE_SCHEMA_VERSION,
        "source_video": extraction["source_video"],
        "duration_ms": extraction["metadata"]["duration_ms"],
        "sampled_frames": len(timeline),
        "target_query": spec.get("target", {}).get("description", ""),
        "task_id": spec.get("task_id"),
        "timeline": timeline,
        "state_changes": state_changes,
        "summary": summary,
        "video_metadata": extraction["metadata"],
        "sampling": extraction["sampling"],
        "backend": {
            "vision_backend": "ollama",
            "model": model,
            "analysis_logic": "scripts/analyze_image.py（任务 03 图片能力原样复用，未重写提示词体系）",
            "frame_extraction": f"scripts/extract_frames.py（opencv {extraction['opencv_version']}，仅作底层抽帧工具）",
            "resource_guard": guard_info,
            "resource_blocked": blocked,
        },
        "warnings": warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description="短视频视觉证据时间线（复用任务 03 图片分析能力）")
    parser.add_argument("--task-spec", required=True, help="VisualTaskSpec JSON 路径")
    parser.add_argument("--video", required=True, help="输入短视频路径（只读）")
    parser.add_argument("--output", required=True, help="timeline.json 输出路径")
    parser.add_argument("--interval-ms", type=float, default=1000, help="采样间隔（毫秒，默认 1000）")
    parser.add_argument("--max-frames", type=int, default=8, help="最大帧数（默认 8）")
    parser.add_argument("--start-ms", type=float, default=0, help="采样起始时间（毫秒）")
    parser.add_argument("--end-ms", type=float, default=None, help="采样结束时间（毫秒，默认视频结尾）")
    parser.add_argument("--frames-dir", default=None, help="帧输出目录（默认 <output 目录>/frames/<视频名>）")
    parser.add_argument("--save-raw-dir", default=None, help="模型原始返回存档目录（审计用）")
    parser.add_argument("--model", default=None, help="Ollama 模型名（默认同 analyze_image.py）")
    parser.add_argument("--timeout", type=int, default=300, help="单帧调用超时秒数")
    parser.add_argument("--min-available-gib", type=float, default=DEFAULT_MIN_AVAILABLE_GIB,
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
        result = trace(
            spec, args.video, args.output,
            interval_ms=args.interval_ms, max_frames=args.max_frames,
            start_ms=args.start_ms, end_ms=args.end_ms, frames_dir=args.frames_dir,
            model=args.model, timeout=args.timeout,
            min_available_gib=args.min_available_gib, allow_low_memory=args.allow_low_memory,
            save_raw_dir=args.save_raw_dir,
        )
    except TraceError as error:
        print(f"[错误] {error}", file=sys.stderr)
        return 2
    except extract_frames_mod.ExtractionError as error:
        print(f"[错误] 抽帧失败: {error}", file=sys.stderr)
        return 3

    summary = result["summary"]
    print(f"[完成] 时间线已写入 {args.output}")
    print(f"  采样帧数={result['sampled_frames']} 确认帧数={summary['confirmed_frame_count']} "
          f"未发现={summary['not_found_frame_count']} 拒答={summary['abstained_frame_count']} "
          f"失败={summary['failed_frame_count']} 整体状态={summary['overall_status']}")
    if result["backend"]["resource_blocked"]:
        print(f"  [资源阻塞] {result['backend']['resource_guard'].get('reason', '')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
