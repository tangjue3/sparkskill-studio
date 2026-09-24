#!/usr/bin/env python3
"""extract_frames.py — 短视频关键帧抽取（SparkSkill Studio 任务 04）

职责（严格限定，仅三件事）:
  1. 读取视频元数据：帧率、总帧数、宽高、时长；
  2. 按可配置采样策略抽取关键帧，保存为稳定命名图片；
  3. 输出帧索引与时间戳 JSON（供 trace_video.py 逐帧分析与审计追溯）。

设计红线:
  - OpenCV 仅作底层工具（读视频/抽帧/存图），绝不是项目核心能力或卖点；
  - 不安装依赖：cv2 缺失时经 skill_env 自动切换到本机已有 cv2 的解释器；
  - 不修改原视频；只读；
  - 第一版只面向短视频，顺序解码保证时间戳准确，不追求实时；
  - 时间戳必须单调递增（由帧序号推导，连续解码保证）。

用法:
    python3 extract_frames.py --video <path.mp4> --output-dir <dir> \
        [--metadata-json <path.json>] [--interval-ms 1000] [--max-frames 8] \
        [--start-ms 0] [--end-ms N] [--image-format png] [--prefix name]

退出码: 0 = 成功; 2 = 用法/IO 错误; 3 = 视频不可读或抽帧失败
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import skill_env  # noqa: E402

skill_env.ensure_cv2_interpreter()  # 无 cv2 时切换解释器（execv 后本行不会返回）

import cv2  # noqa: E402

SCHEMA_VERSION = "1.0.0"


class ExtractionError(Exception):
    """视频不可读或抽帧失败（非敏感错误，消息中不含任何凭据）。"""


def read_metadata(cap):
    """从已打开的视频捕获对象读取元数据；不可信字段视为失败。"""
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if fps <= 0.0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise ExtractionError(
            f"视频元数据不可信（fps={fps}, frame_count={frame_count}, "
            f"width={width}, height={height}），拒绝抽帧"
        )
    return {
        "fps": round(fps, 6),
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_ms": round(frame_count / fps * 1000.0, 3),
    }


def plan_sample_times(duration_ms, interval_ms, max_frames, start_ms, end_ms):
    """确定性采样计划：优先按时间间隔网格，超出 max_frames 时在区间内均匀取样。

    返回按时间升序、去重、含端点的采样时间列表（毫秒）。
    """
    if max_frames < 1:
        raise ExtractionError("max_frames 必须 >= 1")
    start = max(0.0, float(start_ms))
    end = duration_ms if end_ms is None else min(float(end_ms), duration_ms)
    if end < start:
        raise ExtractionError(f"采样区间非法：end_ms({end}) < start_ms({start})")
    span = end - start

    def uniform(count):
        if count <= 1:
            return [start]
        step = span / (count - 1)
        return [start + i * step for i in range(count)]

    if interval_ms and interval_ms > 0:
        grid_count = int(span // interval_ms) + 1
        times = ([start + i * interval_ms for i in range(grid_count)]
                 if grid_count <= max_frames else uniform(max_frames))
    else:
        times = uniform(max_frames)

    rounded = sorted({round(t, 3) for t in times})
    return [t for t in rounded if start <= t <= end]


def extract_frames(video_path, output_dir, prefix=None, interval_ms=1000,
                   max_frames=8, start_ms=0, end_ms=None, image_format="png"):
    """读取视频、按计划抽帧、落盘；返回结构化结果（含帧索引与时间戳）。"""
    video_path = os.path.abspath(video_path)
    if not os.path.isfile(video_path):
        raise ExtractionError(f"视频文件不存在: {video_path}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise ExtractionError(f"无法打开视频（格式不支持或文件损坏）: {video_path}")
    try:
        metadata = read_metadata(cap)
        fps = metadata["fps"]
        frame_count = metadata["frame_count"]
        duration_ms = metadata["duration_ms"]

        sample_times = plan_sample_times(duration_ms, interval_ms, max_frames,
                                         start_ms, end_ms)
        # 采样时间 -> 目标帧序号（确定性映射，去重后升序）
        target_indices = sorted({
            min(frame_count - 1, max(0, round(t / 1000.0 * fps)))
            for t in sample_times
        })

        os.makedirs(output_dir, exist_ok=True)
        prefix = prefix or os.path.splitext(os.path.basename(video_path))[0]
        ext = image_format.lstrip(".").lower()
        if ext not in ("png", "jpg", "jpeg"):
            raise ExtractionError(f"不支持的图片格式: {image_format}")

        frames = []
        warnings = []
        next_target = 0
        pos = 0
        prev_ts = None
        # 顺序解码：保证每帧时间戳由真实帧序号推导（H.264 随机 seek 不可靠）
        while next_target < len(target_indices):
            ok, frame = cap.read()
            if not ok:
                break
            if pos == target_indices[next_target]:
                ts_ms = round(pos / fps * 1000.0, 3)
                if prev_ts is not None and ts_ms <= prev_ts:
                    raise ExtractionError("时间戳未单调递增（内部错误，拒绝输出）")
                prev_ts = ts_ms
                filename = f"{prefix}_f{pos:05d}_t{int(round(ts_ms)):08d}ms.{ext}"
                frame_path = os.path.join(os.path.abspath(output_dir), filename)
                if not cv2.imwrite(frame_path, frame):
                    raise ExtractionError(f"帧保存失败: {frame_path}")
                if not os.path.isfile(frame_path):
                    raise ExtractionError(f"帧保存后未找到文件: {frame_path}")
                frames.append({
                    "index": len(frames),
                    "frame_number": pos,
                    "timestamp_ms": ts_ms,
                    "frame_path": frame_path,
                })
                next_target += 1
            pos += 1

        missing = len(target_indices) - len(frames)
        if missing > 0:
            warnings.append(
                f"计划抽取 {len(target_indices)} 帧，实际解码到第 {pos} 帧，"
                f"有 {missing} 个采样点超出实际可解码范围（元数据帧数可能高估）"
            )
        if not frames:
            raise ExtractionError("未能抽取任何帧（视频可能损坏或采样参数不当）")
    finally:
        cap.release()

    return {
        "schema_version": SCHEMA_VERSION,
        "source_video": video_path,
        "backend": "opencv",
        "opencv_version": cv2.__version__,
        "metadata": metadata,
        "sampling": {
            "strategy": "interval-grid-or-uniform",
            "interval_ms": interval_ms,
            "max_frames": max_frames,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "image_format": ext,
            "planned_sample_times_ms": sample_times,
            "planned_frame_count": len(target_indices),
        },
        "frames": frames,
        "warnings": warnings,
        "extracted_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="短视频关键帧抽取（OpenCV 仅作底层工具）")
    parser.add_argument("--video", required=True, help="输入视频路径（只读，不修改）")
    parser.add_argument("--output-dir", required=True, help="帧图片输出目录")
    parser.add_argument("--metadata-json", help="元数据+帧索引 JSON 输出路径（默认打印到 stdout）")
    parser.add_argument("--interval-ms", type=float, default=1000, help="采样时间间隔（毫秒，默认 1000）")
    parser.add_argument("--max-frames", type=int, default=8, help="最大帧数（默认 8）")
    parser.add_argument("--start-ms", type=float, default=0, help="采样起始时间（毫秒，默认 0）")
    parser.add_argument("--end-ms", type=float, default=None, help="采样结束时间（毫秒，默认视频结尾）")
    parser.add_argument("--image-format", default="png", help="帧图片格式：png/jpg（默认 png）")
    parser.add_argument("--prefix", default=None, help="帧文件名前缀（默认视频主名）")
    args = parser.parse_args()

    try:
        result = extract_frames(
            args.video, args.output_dir, prefix=args.prefix,
            interval_ms=args.interval_ms, max_frames=args.max_frames,
            start_ms=args.start_ms, end_ms=args.end_ms,
            image_format=args.image_format,
        )
    except ExtractionError as error:
        print(f"[错误] 抽帧失败: {error}", file=sys.stderr)
        return 3
    except Exception as error:  # 未预期错误同样只报类型与消息，不透出敏感内容
        print(f"[错误] 未预期错误: {type(error).__name__}: {error}", file=sys.stderr)
        return 3

    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.metadata_json:
        with open(args.metadata_json, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"[完成] 元数据与帧索引已写入 {args.metadata_json}；"
              f"共抽取 {len(result['frames'])} 帧 -> {os.path.abspath(args.output_dir)}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
