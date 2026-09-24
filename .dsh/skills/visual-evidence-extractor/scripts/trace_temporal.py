#!/usr/bin/env python3
"""trace_temporal.py — 目标时序证据 + 粗到细自适应采样执行器（SparkSkill Studio 任务 16）

链路位置：
    自然语言任务 → StepFun 生成 VisualTaskSpec（含可选 sampling_strategy）
    → 本脚本按策略抽帧（uniform 正式 baseline / adaptive_coarse_to_fine）
    → 逐帧复用 analyze_image.py 既有视觉能力（经 trace_video.analyze_frame，
      不重写视觉提示词体系）→ 聚合 + 采样 provenance + 时序证据
    → temporal-evidence.json → evidence-report-generator temporal 报告模式

设计红线（硬约束）:
  - 不重写视觉提示词体系：逐帧分析完全复用 scripts/analyze_image.py 的
    build_prompt / call_ollama / coerce_evidence（经 trace_video.analyze_frame）；
  - 不得凭空生成时间线：timeline 每一项都必须对应一个真实抽取的帧文件；
  - 不得把连续帧自动解释成同一个对象；不做身份跟踪、不做跨镜头关联、
    不做没有证据的路径推断；不输出物体运动路径；不是 ReID / 目标跟踪器 / 实时跟踪；
  - 硬性调用预算：max_model_calls 是真实 Qwen 视觉调用次数上限；重复时间戳
    跳过、已有可复用证据不重复调用、预算耗尽停止细化（且不算“分析成功”）；
  - 资源守卫：统一内存不足时不加载 Qwen，未执行的调用不计入真实视觉调用，
    全部帧标记 failed 并记录真实原因，不用伪造输出冒充真实视觉结果。

用法:
    python3 trace_temporal.py --task-spec <spec.json> --video <path.mp4> \
        --output <temporal-evidence.json> \
        [--strategy uniform|adaptive_coarse_to_fine|coverage_aware_adaptive] \
        [--max-model-calls 12] \
        [--initial-coverage-samples 4] [--target-boundary-precision-ms 500] \
        [--coverage-gap-target-ms 1500] [--coverage-call-reserve 4] \
        [--max-refinement-rounds 4] [--refinement-triggers state_change,abstained] \
        [--interval-ms 1000] [--max-frames 8] [--start-ms 0] [--end-ms N] \
        [--frames-dir <dir>] [--save-raw-dir <dir>] [--model M] [--timeout 300] \
        [--min-available-gib 40] [--allow-low-memory] \
        [--input-nature user_media|technical_fixture]

source_media 为来源对象数组（多段视频）时自动进入多来源模式：每来源独立
执行本链路（保留 source_id 与原视频时间戳），复用 trace_multi_video 的合并
规则生成全局时间线；全局时间线是证据聚合，不是跨摄像头身份追踪。

退出码: 0 = temporal-evidence.json 已生成; 2 = 用法/规格/策略配置错误;
         3 = 抽帧或视频错误
"""
import argparse
import datetime
import importlib.util
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skill_env  # noqa: E402

skill_env.ensure_cv2_interpreter()  # 无 cv2 时切换解释器（execv 后本行不会返回）

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
import adaptive_sampler  # noqa: E402

TEMPORAL_SCHEMA_VERSION = "1.3.0"


def load_sibling_module(name, filename):
    path = os.path.join(SCRIPT_DIR, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trace_video = load_sibling_module("trace_video", "trace_video.py")
extract_frames_mod = load_sibling_module("extract_frames", "extract_frames.py")
trace_multi_video = load_sibling_module("trace_multi_video", "trace_multi_video.py")


class TraceError(Exception):
    """用法/规格/抽帧/策略配置类错误（非敏感）。"""


# ---------------------------------------------------------------- 资源守卫（复用 trace_video）

mem_available_gib = trace_video.mem_available_gib
resource_guard = trace_video.resource_guard


# ---------------------------------------------------------------- 帧采样器

class FrameSampler:
    """按任意时间戳顺序解码抽帧（顺序解码 + 缓存，时间戳由真实帧序号推导）。

    - 每个时间戳（毫秒键）至多抽取并落盘一次；重复时间戳返回缓存帧；
    - 需要回退到更早帧时重新打开视频从头解码（短视频下代价可忽略）；
    - 帧文件稳定命名 <前缀>_f<帧序号>_t<毫秒>ms.png（与 trace_video 一致）。
    """

    def __init__(self, video_path, frames_dir):
        import cv2
        self.cv2 = cv2
        self.video_path = os.path.abspath(video_path)
        if not os.path.isfile(self.video_path):
            raise extract_frames_mod.ExtractionError(f"视频文件不存在: {self.video_path}")
        self.frames_dir = frames_dir
        os.makedirs(frames_dir, exist_ok=True)
        self.prefix = os.path.splitext(os.path.basename(self.video_path))[0]
        self._open()
        self._cache = {}
        self._index = 0
        self.extractions = 0

    def _open(self):
        cap = self.cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            cap.release()
            raise extract_frames_mod.ExtractionError(
                f"无法打开视频（格式不支持或文件损坏）: {self.video_path}")
        self.cap = cap
        self.metadata = extract_frames_mod.read_metadata(cap)
        self.fps = self.metadata["fps"]
        self.frame_count = self.metadata["frame_count"]
        self.duration_ms = self.metadata["duration_ms"]
        self._pos = 0

    def frame_at(self, timestamp_ms):
        """返回 (frame_dict, reused_from_cache)。时间戳取真实帧序号推导值。"""
        key = adaptive_sampler.timestamp_key(timestamp_ms)
        if key in self._cache:
            return self._cache[key], True
        target_index = min(self.frame_count - 1,
                           max(0, int(round(float(timestamp_ms) / 1000.0 * self.fps))))
        if target_index < self._pos:
            # 需要回退：重新打开视频从头顺序解码（不随机 seek）
            self.cap.release()
            self._open()
        frame = None
        while self._pos <= target_index:
            ok, image = self.cap.read()
            if not ok:
                break
            if self._pos == target_index:
                frame = image
            self._pos += 1
        if frame is None:
            raise extract_frames_mod.ExtractionError(
                f"未能解码到采样点对应帧（目标帧序号 {target_index}，"
                f"视频帧数 {self.frame_count}）")
        ts_ms = round(target_index / self.fps * 1000.0, 3)
        frame_key = adaptive_sampler.timestamp_key(ts_ms)
        if frame_key in self._cache:
            return self._cache[frame_key], True
        filename = f"{self.prefix}_f{target_index:05d}_t{int(round(ts_ms)):08d}ms.png"
        frame_path = os.path.join(os.path.abspath(self.frames_dir), filename)
        if not self.cv2.imwrite(frame_path, frame):
            raise extract_frames_mod.ExtractionError(f"帧保存失败: {frame_path}")
        if not os.path.isfile(frame_path):
            raise extract_frames_mod.ExtractionError(f"帧保存后未找到文件: {frame_path}")
        entry = {
            "index": self._index,
            "frame_number": target_index,
            "timestamp_ms": ts_ms,
            "frame_path": frame_path,
        }
        self._index += 1
        self.extractions += 1
        self._cache[frame_key] = entry
        self._cache[key] = entry
        return entry, False

    def close(self):
        try:
            self.cap.release()
        except Exception:
            pass


# ---------------------------------------------------------------- 规格守卫

def guard_spec(spec):
    if spec.get("requires_visual_input") is not True:
        raise TraceError("任务规格 requires_visual_input 必须为 true")
    if spec.get("task_type") not in ("object_trace", "object_presence"):
        raise TraceError(f"不支持的 task_type: {spec.get('task_type')!r}")
    if not spec.get("target", {}).get("description"):
        raise TraceError("任务规格缺少 target.description")


def normalize_sources(spec):
    """source_media 规范化为来源对象列表（与 trace_multi_video 同规则：
    字符串 = 旧版单媒体，包装为 media-0）。"""
    source_media = spec.get("source_media")
    if isinstance(source_media, str):
        return [{
            "source_id": "media-0",
            "path": source_media,
            "location": None,
            "time_offset_ms": 0,
        }]
    if not isinstance(source_media, list) or not source_media:
        raise TraceError(
            "任务规格 source_media 必须是非空来源数组（多段视频）或单个路径字符串")
    sources = []
    seen = set()
    for index, item in enumerate(source_media):
        if not isinstance(item, dict):
            raise TraceError(f"source_media[{index}] 必须是对象")
        source_id = item.get("source_id")
        path = item.get("path")
        if not isinstance(source_id, str) or not source_id.strip():
            raise TraceError(f"source_media[{index}] 缺少合法 source_id")
        if source_id in seen:
            raise TraceError(f"source_id {source_id!r} 在同一任务内重复（必须唯一）")
        seen.add(source_id)
        if not isinstance(path, str) or not path.strip():
            raise TraceError(f"source_media[{index}] 缺少合法 path")
        offset = item.get("time_offset_ms", 0)
        if not isinstance(offset, (int, float)) or isinstance(offset, bool) or offset < 0:
            raise TraceError(f"source_media[{index}] time_offset_ms 必须为非负数")
        location = item.get("location")
        if location is not None and not isinstance(location, str):
            raise TraceError(f"source_media[{index}] location 必须是字符串或缺失")
        sources.append({
            "source_id": source_id,
            "path": path,
            "location": location,
            "time_offset_ms": offset,
        })
    return sources


def guard_source_paths(sources):
    """执行期路径安全复核（复用 task-to-skill-compiler 的路径规则，纵深防御）。"""
    try:
        validator = trace_multi_video.load_validator_module()
    except Exception as error:
        raise TraceError(f"无法加载路径安全校验器，拒绝执行: {type(error).__name__}")
    for source in sources:
        problems = validator.check_media_path(source["path"], f"source {source['source_id']}")
        if problems:
            raise TraceError("；".join(problems))


# ---------------------------------------------------------------- 单来源时序证据执行

def stop_reason_when_no_candidates(entries, triggers, precision_ms):
    """无细化候选时的停止原因：已达目标精度 / 无可细化区间。"""
    ordered = sorted(entries, key=lambda item: item["timestamp_ms"])
    above_precision = any(
        round(right["timestamp_ms"] - left["timestamp_ms"], 3) > float(precision_ms)
        for left, right in zip(ordered, ordered[1:]))
    return "no_refinable_interval" if above_precision else "target_precision_reached"


def run_source_temporal(spec, source, config, options, budget):
    """对单个来源执行 uniform/adaptive 采样 + 逐帧分析 + 时序证据推导。

    budget 为任务级共享账本（多来源时预算是整个任务的硬上限）。
    返回 (temporal_doc, decisions)。不调用模型之外的网络；analyze_options
    中的 analyze_fn 仅供规则测试注入构造证据（明确不计为 Qwen 调用）。
    """
    video_path = source["path"]
    frames_dir = options["frames_dir"]
    model = options["model"] or trace_video.analyze_image.DEFAULT_MODEL
    timeout = options["timeout"]
    raw_dir = options["save_raw_dir"]
    analyze_fn = options.get("analyze_fn")

    timings = {"extraction_ms": 0.0, "analysis_ms": 0.0, "aggregation_ms": 0.0}
    started = time.monotonic()
    sampler = FrameSampler(video_path, frames_dir)
    timings["extraction_ms"] = round((time.monotonic() - started) * 1000, 3)
    duration_ms = sampler.duration_ms

    blocked, guard_info = (False, {"blocked": False}) if options["allow_low_memory"] \
        else resource_guard(options["min_available_gib"])

    entries = []
    decisions = []
    warnings = []
    extracted_planned = set()
    namespace = source["source_id"]  # 预算缓存按来源隔离（多来源共享预算上限）

    def process_sample(timestamp_ms, phase, round_no, reason, trigger_interval=None,
                       trigger_reason=None, observed=None, purpose=None,
                       candidate_interval=None):
        """抽取并分析一个采样点；返回 'new' | 'duplicate' | 'budget_stop' | 'blocked'。

        purpose: 'initial_coverage' | 'temporal_coverage'（覆盖探索，任务 18） |
                 'boundary_refinement'（边界细化）；缺省按 phase 推导。
        candidate_interval: 覆盖探索时为被压缩的候选间隔 {left_ms, right_ms}（任务 18）。
        """
        if blocked:
            # 资源守卫阻塞：未执行任何视觉调用（不计入真实 Qwen 调用）
            frame, _ = sampler.frame_at(timestamp_ms)
            decisions.append({
                "sample_index": len(decisions),
                "timestamp_ms": frame["timestamp_ms"],
                "phase": phase,
                "refinement_round": round_no,
                "purpose": purpose or ("boundary_refinement" if phase == "refinement"
                                       else ("temporal_coverage"
                                             if phase == "coverage_exploration"
                                             else "initial_coverage")),
                "candidate_interval": candidate_interval,
                "reason": reason,
                "trigger_interval": trigger_interval,
                "trigger_reason": trigger_reason,
                "observed_states_at_decision": observed,
                "model_call_seq": None,
                "cache_status": "resource_blocked",
                "budget_state": budget.snapshot(),
            })
            return "blocked"
        frame, reused_frame = sampler.frame_at(timestamp_ms)
        actual_ts = frame["timestamp_ms"]
        if budget.exhausted():
            decisions.append({
                "sample_index": len(decisions),
                "timestamp_ms": actual_ts,
                "phase": phase,
                "refinement_round": round_no,
                "reason": reason,
                "trigger_interval": trigger_interval,
                "trigger_reason": trigger_reason,
                "observed_states_at_decision": observed,
                "model_call_seq": None,
                "cache_status": "budget_blocked",
                "budget_state": budget.snapshot(),
                "purpose": purpose or ("boundary_refinement" if phase == "refinement"
                                       else ("temporal_coverage"
                                             if phase == "coverage_exploration"
                                             else "initial_coverage")),
                "candidate_interval": candidate_interval,
            })
            return "budget_stop"
        if budget.has_analyzed(actual_ts, namespace) or actual_ts in extracted_planned:
            budget.register_duplicate(actual_ts)
            decisions.append({
                "sample_index": len(decisions),
                "timestamp_ms": actual_ts,
                "phase": phase,
                "refinement_round": round_no,
                "reason": reason,
                "trigger_interval": trigger_interval,
                "trigger_reason": trigger_reason,
                "observed_states_at_decision": observed,
                "model_call_seq": None,
                "cache_status": "skipped_duplicate",
                "budget_state": budget.snapshot(),
                "purpose": purpose or ("boundary_refinement" if phase == "refinement"
                                       else ("temporal_coverage"
                                             if phase == "coverage_exploration"
                                             else "initial_coverage")),
                "candidate_interval": candidate_interval,
            })
            return "duplicate"
        extracted_planned.add(actual_ts)
        if reused_frame:
            # 同一真实帧被不同计划时间命中：帧已落盘，但不重复调用模型
            pass
        try:
            if analyze_fn is not None:
                entry = analyze_fn(spec, frame)
                entry["evidence_nature"] = "constructed_fixture_evidence"
            else:
                analysis_started = time.monotonic()
                entry = trace_video.analyze_frame(
                    spec, frame, model, timeout, raw_dir)
                timings["analysis_ms"] += round((time.monotonic() - analysis_started) * 1000, 3)
                entry["evidence_nature"] = "real_model_output"
        except Exception as error:
            entry = trace_video.failed_entry(
                frame, f"帧分析失败：{type(error).__name__}: {error}")
            # 真实模型调用已发生但返回不合法/超时 → backend_call_failed（计为一次真实调用）；
            # 构造分析器异常 → 未获得证据且未调用任何模型 → backend_not_called
            entry["evidence_nature"] = ("backend_call_failed" if analyze_fn is None
                                        else "backend_not_called")
        budget.register_call()
        budget.record_entry(actual_ts, entry, fresh=True, namespace=namespace)
        entries.append(entry)
        decisions.append({
            "sample_index": len(decisions),
            "timestamp_ms": actual_ts,
            "phase": phase,
            "refinement_round": round_no,
            "reason": reason,
            "trigger_interval": trigger_interval,
            "trigger_reason": trigger_reason,
            "observed_states_at_decision": observed,
            "model_call_seq": budget.actual_model_calls,
            "cache_status": "fresh_call",
            "budget_state": budget.snapshot(),
            "purpose": purpose or ("boundary_refinement" if phase == "refinement"
                                   else ("temporal_coverage"
                                         if phase == "coverage_exploration"
                                         else "initial_coverage")),
            "candidate_interval": candidate_interval,
        })
        return "new"

    stop_reasons = []
    precision = config.get("target_boundary_precision_ms")
    strategy = config["strategy"]
    initial_count = config.get("initial_coverage_samples")

    # ---- 阶段 1：初始覆盖采样
    if strategy in ("adaptive_coarse_to_fine", "coverage_aware_adaptive"):
        initial_times = adaptive_sampler.uniform_grid(0.0, duration_ms, initial_count)
    else:
        # uniform 正式 baseline：与 trace_video 相同的规划（interval 网格或区间均匀）
        initial_times = extract_frames_mod.plan_sample_times(
            duration_ms, options["interval_ms"], options["max_frames"],
            options["start_ms"], options["end_ms"])
    truncated_to_budget = False
    if budget.max_model_calls is not None:
        initial_times = [t for t in initial_times
                         if not budget.has_analyzed(t, namespace)]
        if len(initial_times) > budget.max_model_calls:
            initial_times = initial_times[:budget.max_model_calls]
            truncated_to_budget = True
    for timestamp_ms in initial_times:
        if budget.exhausted():
            stop_reasons.append("budget_exhausted")
            truncated_to_budget = True
            break
        outcome = process_sample(
            timestamp_ms, phase="initial_coverage", round_no=None,
            reason=(f"{strategy} 初始覆盖采样（策略：{strategy}）"),
            observed={"analyzed_so_far": len(entries)},
        )
        if outcome == "budget_stop":
            stop_reasons.append("budget_exhausted")
            break
        if outcome == "blocked":
            continue

    # ---- 阶段 1.5：初始覆盖完成后的最大相邻采样间隔（覆盖几何基线）
    max_gap_initial = adaptive_sampler.max_adjacent_gap_ms(
        [entry["timestamp_ms"] for entry in entries], duration_ms)

    # ---- 阶段 2：覆盖探索（coverage_aware_adaptive：与证据语义无关的时间覆盖职责）
    # largest-gap-first 二分压缩尚未充分观测的时间间隔；与阶段 3 的边界细化
    # 共享同一硬预算，但职责与 provenance 相位明确分离。
    coverage_calls_used = 0
    coverage_reserve = config.get("coverage_call_reserve")
    coverage_gap_target = config.get("coverage_gap_target_ms")
    if strategy == "coverage_aware_adaptive":
        if blocked:
            stop_reasons.append("resource_blocked")
        else:
            coverage_stop = None
            excluded_gaps = []
            while True:
                if budget.exhausted():
                    coverage_stop = "budget_exhausted"
                    break
                if coverage_calls_used >= coverage_reserve:
                    coverage_stop = "coverage_reserve_exhausted"
                    break
                gaps = adaptive_sampler.adjacent_gaps(
                    [entry["timestamp_ms"] for entry in entries], duration_ms)
                candidate = adaptive_sampler.next_coverage_candidate(
                    gaps, coverage_gap_target, excluded_gaps)
                if candidate is None:
                    coverage_stop = ("coverage_no_refinable_gap"
                                     if adaptive_sampler.coverage_candidates(
                                         gaps, coverage_gap_target)
                                     else "coverage_gap_target_reached")
                    break
                outcome = process_sample(
                    adaptive_sampler.midpoint_of(candidate),
                    phase="coverage_exploration", round_no=None,
                    purpose="temporal_coverage",
                    candidate_interval={"left_ms": candidate["left_ms"],
                                        "right_ms": candidate["right_ms"]},
                    reason=(f"覆盖探索：压缩最大未观测间隔 "
                            f"[{candidate['left_ms']}, {candidate['right_ms']}] ms"
                            f"（宽度 {candidate['width_ms']} ms > 覆盖目标 "
                            f"{coverage_gap_target} ms；最大相邻间隔 "
                            f"{adaptive_sampler.max_adjacent_gap_ms([e['timestamp_ms'] for e in entries], duration_ms)} ms）"),
                    observed={"max_adjacent_gap_ms": adaptive_sampler.max_adjacent_gap_ms(
                                  [e["timestamp_ms"] for e in entries], duration_ms),
                              "coverage_gap_target_ms": coverage_gap_target,
                              "analyzed_so_far": len(entries)},
                )
                if outcome == "new":
                    coverage_calls_used += 1
                elif outcome == "duplicate":
                    # 间隔已窄于帧分辨率（中点命中已有帧）：排除该间隔，
                    # 不重复调用模型，也不计入覆盖调用
                    excluded_gaps.append((candidate["left_ms"], candidate["right_ms"]))
                elif outcome == "budget_stop":
                    coverage_stop = "budget_exhausted"
                    break
            if coverage_stop:
                stop_reasons.append(coverage_stop)

    # ---- 阶段 3：adaptive/coverage 边界细化（二分查找状态边界）
    refinement_rounds = 0
    if strategy in ("adaptive_coarse_to_fine", "coverage_aware_adaptive"):
        if blocked:
            stop_reasons.append("resource_blocked")
        else:
            max_rounds = config["max_refinement_rounds"]
            while refinement_rounds < max_rounds:
                intervals = adaptive_sampler.refinement_intervals(
                    entries, config["refinement_triggers"], precision)
                if not intervals:
                    stop_reasons.append(
                        stop_reason_when_no_candidates(
                            entries, config["refinement_triggers"], precision))
                    break
                if budget.exhausted():
                    stop_reasons.append("budget_exhausted")
                    break
                refinement_rounds += 1
                new_samples = 0
                for interval in intervals:
                    if budget.exhausted():
                        stop_reasons.append("budget_exhausted")
                        break
                    outcome = process_sample(
                        adaptive_sampler.midpoint_of(interval),
                        phase="refinement", round_no=refinement_rounds,
                        reason=interval["reason"],
                        trigger_interval={"left_ms": interval["left_ms"],
                                          "right_ms": interval["right_ms"]},
                        trigger_reason=interval["trigger"],
                        observed={"class_left": interval["class_left"],
                                  "class_right": interval["class_right"],
                                  "analyzed_so_far": len(entries)},
                    )
                    if outcome == "new":
                        new_samples += 1
                    elif outcome == "budget_stop":
                        stop_reasons.append("budget_exhausted")
                        break
                if new_samples == 0 and not budget.exhausted():
                    # 候选区间窄于单帧间隔，无法再产出新采样点（细化收敛）
                    stop_reasons.append("refinement_converged_no_new_sample")
                    break
            if (refinement_rounds >= config["max_refinement_rounds"]
                    and not any(r in ("budget_exhausted", "resource_blocked",
                                      "refinement_converged_no_new_sample",
                                      "target_precision_reached",
                                      "no_refinable_interval") for r in stop_reasons)):
                remaining = adaptive_sampler.refinement_intervals(
                    entries, config["refinement_triggers"], precision)
                if remaining:
                    stop_reasons.append("max_refinement_rounds_reached")

    if blocked:
        for frame_ts in initial_times:
            frame, _ = sampler.frame_at(frame_ts)
            if not any(e["timestamp_ms"] == frame["timestamp_ms"] for e in entries):
                failed = trace_video.failed_entry(frame, guard_info["reason"])
                failed["evidence_nature"] = "backend_not_called"
                entries.append(failed)
        if not entries:
            # 连初始覆盖都未能抽取（极端情况）：保持 entries 空，聚合如实降级
            pass

    # stop_reasons 去重（保序）：同一原因可能在多个分支被记录
    deduped_stop_reasons = []
    for reason in stop_reasons:
        if reason not in deduped_stop_reasons:
            deduped_stop_reasons.append(reason)
    stop_reasons = deduped_stop_reasons

    # ---- 聚合与时序证据

    def fresh_calls(phase):
        return len([d for d in decisions if d["phase"] == phase
                    and d["cache_status"] == "fresh_call"])

    aggregation_started = time.monotonic()
    ordered = sorted(entries, key=lambda item: item["timestamp_ms"])
    timestamps = [item["timestamp_ms"] for item in ordered]
    if any(b <= a for a, b in zip(timestamps, timestamps[1:])):
        sampler.close()
        raise TraceError("聚合失败：时间戳未严格单调递增")
    try:
        _, state_changes, summary = trace_video.aggregate(ordered)
    except TraceError:
        sampler.close()
        raise
    except Exception as error:
        sampler.close()
        raise TraceError(f"聚合失败：{type(error).__name__}: {error}")
    temporal_evidence = adaptive_sampler.build_temporal_evidence(
        ordered,
        target_precision_ms=precision,
        stopped_by_budget=budget.exhausted(),
        stop_reasons=stop_reasons,
        actual_model_calls=budget.actual_model_calls,
        duration_ms=duration_ms,
        coverage_gap_target_ms=coverage_gap_target,
        max_gap_initial_ms=max_gap_initial,
        coverage_calls=fresh_calls("coverage_exploration"),
        coverage_call_reserve=coverage_reserve,
    )
    timings["aggregation_ms"] = round((time.monotonic() - aggregation_started) * 1000, 3)
    timings["total_ms"] = round((time.monotonic() - started) * 1000, 3)

    if summary["failed_frame_count"]:
        warnings.append(
            f"{summary['failed_frame_count']} 帧未获得视觉证据（失败原因见各帧 "
            "abstention_reason），不计入确认，未伪造任何结论")
    for entry in ordered:
        for message in entry.get("warnings") or []:
            warnings.append(f"帧 {entry.get('timestamp_ms')}ms: {message}")
    if blocked:
        warnings.append("真实视频视觉调用被资源条件阻塞（详见 backend.resource_guard.reason）")

    analyzed_ts = [item["timestamp_ms"] for item in ordered]
    max_gap_final = adaptive_sampler.max_adjacent_gap_ms(analyzed_ts, duration_ms)
    underobserved = (adaptive_sampler.underobserved_intervals(
        analyzed_ts, duration_ms, coverage_gap_target)
        if coverage_gap_target is not None else None)

    provenance = {
        "strategy": strategy,
        "configured_budget": budget.max_model_calls,
        "actual_model_calls": budget.actual_model_calls,
        "reused_evidence_count": budget.reused_evidence_count,
        "budget_exhausted": budget.exhausted(),
        "initial_samples": fresh_calls("initial_coverage"),
        "refinement_samples": fresh_calls("refinement"),
        "refinement_rounds": refinement_rounds,
        "uniform_sampling_truncated_to_budget": truncated_to_budget,
        # 覆盖 vs 细化的调用区分（任务 18；旧策略下覆盖调用为 0，结构保持一致）
        "initial_coverage_calls": fresh_calls("initial_coverage"),
        "coverage_exploration_calls": fresh_calls("coverage_exploration"),
        "boundary_refinement_calls": fresh_calls("refinement"),
        "coverage_call_reserve": coverage_reserve,
        "coverage_gap_target_ms": coverage_gap_target,
        "max_adjacent_sampling_gap_ms_initial": max_gap_initial,
        "max_adjacent_sampling_gap_ms_final": max_gap_final,
        "underobserved_intervals": underobserved,
        "arbitrary_short_event_detection_guaranteed": False,
        "events_shorter_than_max_sampling_gap_may_be_missed": True,
        "decisions": decisions,
        "analyzed_timestamps": [item["timestamp_ms"] for item in ordered],
        "skipped_duplicate_timestamps": list(budget.skipped_duplicate_timestamps),
        "stop_reasons": stop_reasons,
        "resource_guard": guard_info,
        "resource_blocked": blocked,
        "timing": timings,
    }
    if adaptive_sampler.provenance_free_of_credentials(provenance):
        sampler.close()
        raise TraceError("采样 provenance 安全自检失败：疑似凭据内容")

    doc = {
        "schema_version": TEMPORAL_SCHEMA_VERSION,
        "task_id": spec.get("task_id"),
        "target_query": spec.get("target", {}).get("description", ""),
        "input_nature": options["input_nature"],
        "evidence_nature": ("real_model_output"
                            if any(e.get("evidence_nature") == "real_model_output"
                                   for e in ordered)
                            else ("resource_blocked" if blocked else "constructed_fixture_evidence")),
        "source_video": sampler.video_path,
        "duration_ms": duration_ms,
        "sampled_frames": len(ordered),
        "sampling_strategy": strategy,
        "strategy_config": config,
        "timeline": ordered,
        "state_changes": state_changes,
        "summary": summary,
        "sampling_provenance": provenance,
        "temporal_evidence": temporal_evidence,
        "video_metadata": sampler.metadata,
        "backend": {
            "vision_backend": "ollama",
            "model": model,
            "analysis_logic": "scripts/analyze_image.py（任务 03 图片能力经 "
                              "trace_video.analyze_frame 原样复用，未重写提示词体系）",
            "frame_extraction": "scripts/extract_frames.py（opencv，仅作底层抽帧工具）",
            "adaptive_sampling": "scripts/adaptive_sampler.py（任务 16 纯逻辑："
                                 "规划/预算/provenance/时序证据）",
            "resource_guard": guard_info,
            "resource_blocked": blocked,
        },
        "warnings": warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    sampler.close()
    return doc, decisions


# ---------------------------------------------------------------- 主入口

def trace_temporal(spec, output_path, strategy=None, max_model_calls=None,
                   initial_coverage_samples=None, target_boundary_precision_ms=None,
                   max_refinement_rounds=None, refinement_triggers=None,
                   coverage_gap_target_ms=None, coverage_call_reserve=None,
                   interval_ms=1000, max_frames=8, start_ms=0, end_ms=None,
                   frames_dir=None, model=None, timeout=300,
                   min_available_gib=trace_video.DEFAULT_MIN_AVAILABLE_GIB,
                   allow_low_memory=False, save_raw_dir=None,
                   input_nature="user_media", analyze_fn=None, budget=None):
    """单视频/多来源时序证据主流程。返回写入 output_path 的文档。"""
    guard_spec(spec)
    sources = normalize_sources(spec)
    guard_source_paths(sources)

    overrides = {
        "strategy": strategy,
        "max_model_calls": max_model_calls,
        "initial_coverage_samples": initial_coverage_samples,
        "target_boundary_precision_ms": target_boundary_precision_ms,
        "max_refinement_rounds": max_refinement_rounds,
        "refinement_triggers": tuple(refinement_triggers) if refinement_triggers else None,
        "coverage_gap_target_ms": coverage_gap_target_ms,
        "coverage_call_reserve": coverage_call_reserve,
    }
    try:
        config = adaptive_sampler.parse_strategy_config(spec, overrides)
    except adaptive_sampler.SamplingConfigError as error:
        raise TraceError(str(error))

    output_path = os.path.abspath(output_path)
    if budget is None:
        budget = adaptive_sampler.CallBudget(config["max_model_calls"])

    options = {
        "interval_ms": interval_ms,
        "max_frames": max_frames,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "model": model,
        "timeout": timeout,
        "min_available_gib": min_available_gib,
        "allow_low_memory": allow_low_memory,
        "save_raw_dir": save_raw_dir,
        "input_nature": input_nature,
        "analyze_fn": analyze_fn,
    }

    if len(sources) == 1:
        source = sources[0]
        frames_dir = frames_dir or os.path.join(
            os.path.dirname(output_path), "frames", source["source_id"])
        options["frames_dir"] = frames_dir
        doc, _ = run_source_temporal(spec, source, config, options, budget)
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        return doc

    # ---- 多来源：每来源独立执行（共享同一预算账本），合并全局时间线
    base_dir = os.path.join(os.path.dirname(output_path), "per-source")
    os.makedirs(base_dir, exist_ok=True)
    per_source_docs = []
    per_source_entries = []
    for source in sources:
        source_id = source["source_id"]
        options["frames_dir"] = os.path.join(base_dir, "keyframes", source_id)
        options["save_raw_dir"] = (os.path.join(save_raw_dir, source_id)
                                   if save_raw_dir else None)
        doc, _ = run_source_temporal(spec, source, config, options, budget)
        per_source_docs.append(doc)
        per_source_entries.append({
            "source_id": source_id,
            "path": source["path"],
            "location": source["location"],
            "time_offset_ms": source["time_offset_ms"],
            "timeline": doc["timeline"],
        })

    merged = trace_multi_video.merge_global_timeline(per_source_entries)
    per_source_summaries = {sources[i]["source_id"]: per_source_docs[i]["summary"]
                            for i in range(len(sources))}
    global_summary = trace_multi_video.summarize_global(merged, per_source_summaries)
    global_temporal_evidence = adaptive_sampler.build_temporal_evidence(
        merged,
        target_precision_ms=config.get("target_boundary_precision_ms"),
        stopped_by_budget=budget.exhausted(),
        stop_reasons=["multi_source_shared_budget"],
        actual_model_calls=budget.actual_model_calls,
    )

    result = {
        "schema_version": TEMPORAL_SCHEMA_VERSION,
        "task_id": spec.get("task_id"),
        "target_query": spec.get("target", {}).get("description", ""),
        "input_nature": input_nature,
        "evidence_nature": ("real_model_output"
                            if any(d["evidence_nature"] == "real_model_output"
                                   for d in per_source_docs)
                            else ("resource_blocked"
                                  if any(d["evidence_nature"] == "resource_blocked"
                                         for d in per_source_docs)
                                  else "constructed_fixture_evidence")),
        "sampling_strategy": config["strategy"],
        "strategy_config": config,
        "sources": [{
            "source_id": sources[i]["source_id"],
            "path": sources[i]["path"],
            "location": sources[i]["location"],
            "time_offset_ms": sources[i]["time_offset_ms"],
            "source_video": per_source_docs[i]["source_video"],
            "duration_ms": per_source_docs[i]["duration_ms"],
            "sampled_frames": per_source_docs[i]["sampled_frames"],
            "timeline": per_source_docs[i]["timeline"],
            "summary": per_source_docs[i]["summary"],
            "sampling_provenance": per_source_docs[i]["sampling_provenance"],
            "temporal_evidence": per_source_docs[i]["temporal_evidence"],
            "warnings": per_source_docs[i]["warnings"],
            "resource_blocked": per_source_docs[i]["backend"]["resource_blocked"],
        } for i in range(len(sources))],
        "global_timeline": merged,
        "global_summary": global_summary,
        "global_temporal_evidence": global_temporal_evidence,
        "shared_budget": budget.snapshot(),
        "semantic_limitations": trace_multi_video.SEMANTIC_LIMITATIONS,
        "backend": {
            "vision_backend": "ollama",
            "model": model or trace_video.analyze_image.DEFAULT_MODEL,
            "analysis_logic": "scripts/trace_temporal.py（每来源复用 trace_video.analyze_frame，"
                              "未重写视觉提示词体系）",
            "multi_source_aggregation": "scripts/trace_multi_video.py merge 规则（任务 06）",
            "resource_blocked": any(doc["backend"]["resource_blocked"]
                                    for doc in per_source_docs),
        },
        "warnings": [f"来源 {sources[i]['source_id']}: {message}"
                     for i in range(len(sources))
                     for message in per_source_docs[i]["warnings"]],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="目标时序证据 + 粗到细自适应采样（复用任务 03/04 视觉能力）")
    parser.add_argument("--task-spec", required=True, help="VisualTaskSpec JSON 路径")
    parser.add_argument("--video", default=None,
                        help="单视频输入（source_media 为字符串时可不传；多来源规格不需要）")
    parser.add_argument("--output", required=True, help="temporal-evidence.json 输出路径")
    parser.add_argument("--strategy", choices=list(adaptive_sampler.STRATEGIES), default=None,
                        help="覆盖规格中的采样策略")
    parser.add_argument("--max-model-calls", type=int, default=None,
                        help="硬性视觉模型调用预算（覆盖规格）")
    parser.add_argument("--initial-coverage-samples", type=int, default=None,
                        help="adaptive 初始覆盖采样数（覆盖规格）")
    parser.add_argument("--target-boundary-precision-ms", type=float, default=None,
                        help="adaptive 目标时间边界精度毫秒（覆盖规格）")
    parser.add_argument("--max-refinement-rounds", type=int, default=None,
                        help="adaptive 最大细化轮数（覆盖规格）")
    parser.add_argument("--coverage-gap-target-ms", type=float, default=None,
                        help="coverage_aware_adaptive 覆盖目标：最大相邻采样间隔目标值"
                             "（毫秒，必须 > 0；覆盖规格）")
    parser.add_argument("--coverage-call-reserve", type=int, default=None,
                        help="coverage_aware_adaptive 覆盖调用储备：初始覆盖之外的最大"
                             "覆盖探索调用次数（正整数；覆盖规格）")
    parser.add_argument("--refinement-triggers", default=None,
                        help="逗号分隔的细化触发器（覆盖规格），如 state_change,abstained")
    parser.add_argument("--interval-ms", type=float, default=1000,
                        help="uniform 策略采样间隔（毫秒，默认 1000）")
    parser.add_argument("--max-frames", type=int, default=8,
                        help="uniform 策略最大帧数（默认 8）")
    parser.add_argument("--start-ms", type=float, default=0, help="采样起始时间（毫秒）")
    parser.add_argument("--end-ms", type=float, default=None, help="采样结束时间（毫秒）")
    parser.add_argument("--frames-dir", default=None, help="帧输出目录")
    parser.add_argument("--save-raw-dir", default=None, help="模型原始返回存档目录（审计用）")
    parser.add_argument("--model", default=None, help="Ollama 模型名（默认同 analyze_image.py）")
    parser.add_argument("--timeout", type=int, default=300, help="单帧调用超时秒数")
    parser.add_argument("--min-available-gib", type=float,
                        default=trace_video.DEFAULT_MIN_AVAILABLE_GIB,
                        help="资源守卫：调用视觉模型所需的最低可用内存（GiB，默认 40）")
    parser.add_argument("--allow-low-memory", action="store_true",
                        help="覆盖资源守卫强制调用（仅在确认资源窗口时使用，有 OOM 风险）")
    parser.add_argument("--input-nature",
                        choices=["user_media", "technical_fixture"],
                        default="user_media",
                        help="输入性质标记（technical_fixture=合成技术 fixture，"
                             "不得外推为真实行业素材结论）")
    args = parser.parse_args()

    try:
        with open(args.task_spec, encoding="utf-8") as handle:
            spec = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[错误] 无法读取任务规格: {error}", file=sys.stderr)
        return 2

    if isinstance(spec.get("source_media"), str) and args.video:
        spec = dict(spec)
        spec["source_media"] = args.video

    triggers = None
    if args.refinement_triggers:
        triggers = tuple(item.strip() for item in args.refinement_triggers.split(",")
                         if item.strip())

    try:
        result = trace_temporal(
            spec, args.output,
            strategy=args.strategy, max_model_calls=args.max_model_calls,
            initial_coverage_samples=args.initial_coverage_samples,
            target_boundary_precision_ms=args.target_boundary_precision_ms,
            max_refinement_rounds=args.max_refinement_rounds,
            coverage_gap_target_ms=args.coverage_gap_target_ms,
            coverage_call_reserve=args.coverage_call_reserve,
            refinement_triggers=triggers,
            interval_ms=args.interval_ms, max_frames=args.max_frames,
            start_ms=args.start_ms, end_ms=args.end_ms,
            frames_dir=args.frames_dir, model=args.model, timeout=args.timeout,
            min_available_gib=args.min_available_gib,
            allow_low_memory=args.allow_low_memory,
            save_raw_dir=args.save_raw_dir, input_nature=args.input_nature,
        )
    except TraceError as error:
        print(f"[错误] {error}", file=sys.stderr)
        return 2
    except extract_frames_mod.ExtractionError as error:
        print(f"[错误] 抽帧失败: {error}", file=sys.stderr)
        return 3

    provenance = result.get("sampling_provenance") or result.get("shared_budget")
    summary = result.get("summary") or result.get("global_summary") or {}
    print(f"[完成] 时序证据已写入 {args.output}")
    print(f"  策略={result.get('sampling_strategy')} "
          f"采样点={result.get('sampled_frames', len(result.get('global_timeline', [])))} "
          f"整体状态={summary.get('overall_status')}")
    if provenance:
        print(f"  预算={provenance.get('max_model_calls', provenance.get('configured_budget'))} "
              f"实际调用={provenance.get('actual_model_calls')} "
              f"耗尽预算={provenance.get('budget_exhausted')}")
    if result.get("backend", {}).get("resource_blocked"):
        print("  [资源阻塞] 真实视觉调用被资源条件阻塞", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
