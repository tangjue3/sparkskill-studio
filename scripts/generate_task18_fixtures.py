#!/usr/bin/env python3
"""generate_task18_fixtures.py — 任务 18 technical fixture 生成与冻结（SparkSkill Studio）

为 coverage_aware_adaptive 三臂评测生成**明确标注为 synthetic technical fixture** 的小型
测试视频。纪律（硬约束，与任务 16 一致）：

  - fixture 是合成技术测试输入，**不是真实行业视频**，不作为视觉准确率或行业落地结论；
  - 生成参数与 ground truth 在第一次评测前冻结：manifest + ground-truth + SHA-256
    落盘后不得重新生成或修改标签迁就模型输出（verify_fixtures() 供评测前复核）；
  - 不依赖新增软件包（仅用本机已有 OpenCV，经 skill_env 复用 vLLM 环境）；
  - 不进入用户保留的 holdout 集；
  - 若 Qwen 不能可靠理解某个 fixture，如实记录，不得修改标签。

与任务 16 fixture 的关系：生成参数逐项相同（640x360、24 fps、8000 ms / 192 帧、mp4v、
80x80 红色正方形、背景 (200,200,200)、低对比度 (214,214,214)、确定性渲染）；任务 18
只新增 6 段针对"coarse 初始网格之间窄事件/窄不确定区"的 fixture。任务 16 的 5 段冻结
fixture 由三臂评测以相对路径复用（不复制、不重新生成）。

用法:
    python3 scripts/generate_task18_fixtures.py            # 生成并冻结
    python3 scripts/generate_task18_fixtures.py --verify   # 只校验（不重新生成）
退出码: 0 = 成功/校验通过; 1 = 校验失败; 2 = 用法/IO 错误
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKILL_SCRIPTS = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor", "scripts")
sys.path.insert(0, SKILL_SCRIPTS)
import skill_env  # noqa: E402

skill_env.ensure_cv2_interpreter()  # 无 cv2 时切换解释器（execv 后本行不返回）

FIXTURE_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "fixtures")
VIDEO_DIR = os.path.join(FIXTURE_DIR, "videos")
FROZEN_AT_NOTE = "synthetic technical fixture（合成技术测试输入；非真实行业素材；不得外推）"

# 固定生成参数（冻结；与任务 16 逐项一致，保证跨任务可比）
WIDTH, HEIGHT, FPS, DURATION_MS = 640, 360, 24, 8000
FRAME_COUNT = int(DURATION_MS / 1000.0 * FPS)
SQUARE_SIZE = 80
TARGET_DESCRIPTION = "红色正方形"
BACKGROUND_BGR = (200, 200, 200)
SQUARE_BGR = (0, 0, 220)                 # 红色（BGR）
SQUARE_LOW_CONTRAST_BGR = (214, 214, 214)  # 低对比度红方块（uncertain fixture 专用）

# coarse 初始网格（initial_coverage_samples=4 时的采样点）：0 / 2666.667 / 5333.333 / 8000
# 新增 fixture 的窄事件/窄不确定区全部落在这些网格点之间的间隔内。
COARSE_GRID_MS = [0.0, 2666.667, 5333.333, 8000.0]

# fixture 定义：segments 按时间顺序覆盖 [0, DURATION_MS]；
# state ∈ present（清晰可见）/ absent（不存在）/ present_low_contrast（存在但低对比度，
# ground truth 仍记为存在，该区间预期模型可能 abstained/low_confidence——如实记录，
# 不因此修改标签；任务 17 GT 契约映射为 uncertain）
FIXTURES = [
    {
        "id": "short-event-between-grid",
        "file": "fixture-short-event-between-grid.mp4",
        "purpose": "coarse 初始网格之间的短 confirmed 事件（3500–4100 ms，落在 2666.667/5333.333 两个初始采样点之间；adaptive 无触发信号必然漏检）",
        "segments": [
            {"start_ms": 0, "end_ms": 3500, "state": "absent"},
            {"start_ms": 3500, "end_ms": 4100, "state": "present"},
            {"start_ms": 4100, "end_ms": DURATION_MS, "state": "absent"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [
                {"at_ms": 3500, "from": "absent", "to": "present"},
                {"at_ms": 4100, "from": "present", "to": "absent"},
            ],
            "note": "600ms 窄事件：宽度小于 coarse 网格间隔（2666.667ms）；"
                    "coverage 探索（gap 目标 1500ms）应至少有一个采样点落入事件内",
        },
    },
    {
        "id": "short-uncertain-between-grid",
        "file": "fixture-short-uncertain-between-grid.mp4",
        "purpose": "coarse 初始网格之间的短 uncertain 区域（3500–4100 ms 低对比度，落在两个初始采样点之间；对应任务 17 量化的 adaptive 覆盖盲区）",
        "segments": [
            {"start_ms": 0, "end_ms": 3500, "state": "present"},
            {"start_ms": 3500, "end_ms": 4100, "state": "present_low_contrast"},
            {"start_ms": 4100, "end_ms": DURATION_MS, "state": "present"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [
                {"at_ms": 3500, "from": "present", "to": "present_low_contrast"},
                {"at_ms": 4100, "from": "present_low_contrast", "to": "present"},
            ],
            "uncertain_window_ms": [3500, 4100],
            "note": ("ground truth 为全程存在；低对比度区间预期模型可能 abstained 或 "
                     "low_confidence——如实记录，不得修改标签迁就模型输出；"
                     "任务 17 GT 契约映射为 uncertain"),
        },
    },
    {
        "id": "twin-short-events",
        "file": "fixture-twin-short-events.mp4",
        "purpose": "两个间隔较短的事件（1600–2200 ms 与 3000–3600 ms，各 600ms，均落在 coarse 网格间隔内）",
        "segments": [
            {"start_ms": 0, "end_ms": 1600, "state": "absent"},
            {"start_ms": 1600, "end_ms": 2200, "state": "present"},
            {"start_ms": 2200, "end_ms": 3000, "state": "absent"},
            {"start_ms": 3000, "end_ms": 3600, "state": "present"},
            {"start_ms": 3600, "end_ms": DURATION_MS, "state": "absent"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [
                {"at_ms": 1600, "from": "absent", "to": "present"},
                {"at_ms": 2200, "from": "present", "to": "absent"},
                {"at_ms": 3000, "from": "absent", "to": "present"},
                {"at_ms": 3600, "from": "present", "to": "absent"},
            ],
            "note": ("两个 600ms 事件可同时落在覆盖探索后的同一量级间隔内："
                    "本场景用于证明'事件短于最大相邻采样间隔时可能被漏检'的诚实限制，"
                    "任何臂漏检均如实记录，不改标签"),
        },
    },
    {
        "id": "absent-throughout",
        "file": "fixture-absent-throughout.mp4",
        "purpose": "无目标/无状态转换（目标全程不存在；验证确定性负面与覆盖探索不产生虚假事件）",
        "segments": [
            {"start_ms": 0, "end_ms": DURATION_MS, "state": "absent"},
        ],
        "expected": {
            "target_present": False,
            "transitions_ground_truth": [],
            "note": "全程 not_found：任何策略都不得产生 confirmed 或虚假状态转换",
        },
    },
    {
        "id": "short-event-phase-b",
        "file": "fixture-short-event-phase-b.mp4",
        "purpose": "相位移动的短 confirmed 事件（6200–6800 ms；与 short-event-between-grid 语义相同、时间相位不同，防止只对单一时间位置调参）",
        "segments": [
            {"start_ms": 0, "end_ms": 6200, "state": "absent"},
            {"start_ms": 6200, "end_ms": 6800, "state": "present"},
            {"start_ms": 6800, "end_ms": DURATION_MS, "state": "absent"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [
                {"at_ms": 6200, "from": "absent", "to": "present"},
                {"at_ms": 6800, "from": "present", "to": "absent"},
            ],
            "note": "与 short-event-between-grid 语义相同、相位不同（事件位于 5333.333/8000 间隔）",
        },
    },
    {
        "id": "short-uncertain-phase-b",
        "file": "fixture-short-uncertain-phase-b.mp4",
        "purpose": "相位移动的短 uncertain 区域（6200–6800 ms 低对比度；与 short-uncertain-between-grid 语义相同、时间相位不同）",
        "segments": [
            {"start_ms": 0, "end_ms": 6200, "state": "present"},
            {"start_ms": 6200, "end_ms": 6800, "state": "present_low_contrast"},
            {"start_ms": 6800, "end_ms": DURATION_MS, "state": "present"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [
                {"at_ms": 6200, "from": "present", "to": "present_low_contrast"},
                {"at_ms": 6800, "from": "present_low_contrast", "to": "present"},
            ],
            "uncertain_window_ms": [6200, 6800],
            "note": ("与 short-uncertain-between-grid 语义相同、相位不同；"
                    "任务 17 GT 契约映射为 uncertain"),
        },
    },
]

# 复用任务 16 冻结 fixture（不复制、不重新生成；以相对路径引用并核验 SHA-256）
REUSED_TASK16_FIXTURES = [
    {"id": "present-throughout", "file": "fixture-present-throughout.mp4",
     "relpath": "../../task-16/fixtures/videos/fixture-present-throughout.mp4",
     "purpose": "持续正向 + 无状态变化（复用任务 16 冻结 fixture）"},
    {"id": "appear-midway", "file": "fixture-appear-midway.mp4",
     "relpath": "../../task-16/fixtures/videos/fixture-appear-midway.mp4",
     "purpose": "中途出现 3200ms（复用任务 16 冻结 fixture）"},
    {"id": "disappear-midway", "file": "fixture-disappear-midway.mp4",
     "relpath": "../../task-16/fixtures/videos/fixture-disappear-midway.mp4",
     "purpose": "中途消失 4800ms（复用任务 16 冻结 fixture）"},
    {"id": "reappear", "file": "fixture-reappear.mp4",
     "relpath": "../../task-16/fixtures/videos/fixture-reappear.mp4",
     "purpose": "出现/消失/再次出现（复用任务 16 冻结 fixture）"},
]


def state_at(segments, timestamp_ms):
    for segment in segments:
        if segment["start_ms"] <= timestamp_ms < segment["end_ms"]:
            return segment["state"]
    return segments[-1]["state"] if segments else "absent"


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_fixture(fixture):
    """确定性渲染一个 fixture 视频（无随机性；与任务 16 渲染逻辑同参数）。"""
    import cv2
    path = os.path.join(VIDEO_DIR, fixture["file"])
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    if not writer.isOpened():
        raise RuntimeError(f"无法创建视频写入器: {path}")
    x0 = (WIDTH - SQUARE_SIZE) // 2
    y0 = (HEIGHT - SQUARE_SIZE) // 2
    for index in range(FRAME_COUNT):
        timestamp_ms = index / FPS * 1000.0
        state = state_at(fixture["segments"], timestamp_ms)
        frame = [[BACKGROUND_BGR] * WIDTH for _ in range(HEIGHT)]  # 纯色背景（确定性）
        import numpy as np
        image = np.array(frame, dtype=np.uint8)
        if state in ("present", "present_low_contrast"):
            color = SQUARE_BGR if state == "present" else SQUARE_LOW_CONTRAST_BGR
            cv2.rectangle(image, (x0, y0), (x0 + SQUARE_SIZE, y0 + SQUARE_SIZE),
                          color, -1)
        writer.write(image)
    writer.release()
    return path


def read_back_metadata(path):
    import cv2
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"fixture 视频无法读回: {path}")
    metadata = {
        "fps": float(cap.get(cv2.CAP_PROP_FPS) or 0.0),
        "frame_count": int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0),
        "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
    }
    cap.release()
    return metadata


def generate():
    os.makedirs(VIDEO_DIR, exist_ok=True)
    frozen_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    ground_truth = {
        "suite": "task-18-technical-fixtures",
        "nature": FROZEN_AT_NOTE,
        "target_description": TARGET_DESCRIPTION,
        "frozen_at": frozen_at,
        "generation_params": {
            "width": WIDTH, "height": HEIGHT, "fps": FPS,
            "duration_ms": DURATION_MS, "frame_count": FRAME_COUNT,
            "square_size": SQUARE_SIZE, "codec": "mp4v",
            "background_bgr": list(BACKGROUND_BGR),
            "square_bgr": list(SQUARE_BGR),
            "square_low_contrast_bgr": list(SQUARE_LOW_CONTRAST_BGR),
            "deterministic": True,
            "coarse_initial_grid_ms": COARSE_GRID_MS,
        },
        "fixtures": {},
        "reused_task16_fixtures": {item["id"]: {
            "file": item["file"], "relpath": item["relpath"], "purpose": item["purpose"],
        } for item in REUSED_TASK16_FIXTURES},
        "red_lines": [
            "fixture 结果不得外推为真实仓储准确率",
            "Qwen 不能可靠理解某个 fixture 时如实记录，不得修改标签",
            "fixture 不进入用户 holdout 集",
            "任务 16 冻结 fixture 只复用不复制；其 SHA-256 以任务 16 冻结 manifest 为权威",
        ],
    }
    for fixture in FIXTURES:
        path = render_fixture(fixture)
        metadata = read_back_metadata(path)
        if (metadata["fps"] != FPS or metadata["frame_count"] != FRAME_COUNT
                or metadata["width"] != WIDTH or metadata["height"] != HEIGHT):
            raise RuntimeError(f"fixture 读回元数据不符: {fixture['id']} -> {metadata}")
        ground_truth["fixtures"][fixture["id"]] = {
            "file": fixture["file"],
            "purpose": fixture["purpose"],
            "segments": fixture["segments"],
            "expected": fixture["expected"],
            "metadata_readback": metadata,
        }

    with open(os.path.join(FIXTURE_DIR, "ground-truth.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(ground_truth, ensure_ascii=False, indent=2) + "\n")

    hashes = {}
    for fixture in FIXTURES:
        path = os.path.join(VIDEO_DIR, fixture["file"])
        hashes[fixture["file"]] = sha256_of(path)
    with open(os.path.join(FIXTURE_DIR, "fixtures.sha256.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(hashes, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    manifest = {
        "suite": "task-18-technical-fixtures",
        "nature": FROZEN_AT_NOTE,
        "generated_at": frozen_at,
        "video_count": len(FIXTURES),
        "videos": {fixture["id"]: {
            "file": fixture["file"],
            "path": os.path.join("artifacts", "task-18", "fixtures", "videos", fixture["file"]),
            "sha256": hashes[fixture["file"]],
            "purpose": fixture["purpose"],
        } for fixture in FIXTURES},
        "ground_truth": "artifacts/task-18/fixtures/ground-truth.json",
        "hashes": "artifacts/task-18/fixtures/fixtures.sha256.json",
        "reused_task16_fixtures": {item["id"]: {
            "file": item["file"], "relpath": item["relpath"], "purpose": item["purpose"],
        } for item in REUSED_TASK16_FIXTURES},
        "freeze_rule": ("第一次评测前冻结；manifest/hash 落盘后不得重新生成或修改标签；"
                        "评测前用 --verify 复核 SHA-256 与元数据"),
    }
    with open(os.path.join(FIXTURE_DIR, "fixture-manifest.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def verify():
    """评测前复核：manifest/hash/ground-truth 存在且一致；新视频元数据符合冻结参数；
    复用的任务 16 视频存在且 SHA-256 与任务 16 冻结 manifest 一致。"""
    problems = []
    manifest_path = os.path.join(FIXTURE_DIR, "fixture-manifest.json")
    hashes_path = os.path.join(FIXTURE_DIR, "fixtures.sha256.json")
    gt_path = os.path.join(FIXTURE_DIR, "ground-truth.json")
    for path in (manifest_path, hashes_path, gt_path):
        if not os.path.isfile(path):
            problems.append(f"缺少冻结文件: {path}")
    if problems:
        return problems
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    hashes = json.load(open(hashes_path, encoding="utf-8"))
    ground_truth = json.load(open(gt_path, encoding="utf-8"))
    for fixture_id, entry in manifest["videos"].items():
        path = os.path.join(PROJECT_ROOT, entry["path"])
        if not os.path.isfile(path):
            problems.append(f"fixture 视频缺失: {path}")
            continue
        actual = sha256_of(path)
        if actual != entry["sha256"] or hashes.get(entry["file"]) != actual:
            problems.append(f"{fixture_id}: SHA-256 与冻结 manifest 不一致（疑似重新生成）")
        metadata = read_back_metadata(path)
        expected = ground_truth["fixtures"][fixture_id]["metadata_readback"]
        if metadata != expected:
            problems.append(f"{fixture_id}: 读回元数据 {metadata} 与冻结值 {expected} 不一致")
    # 复用 fixture：核验存在性与任务 16 冻结 SHA-256
    task16_manifest_path = os.path.join(
        PROJECT_ROOT, "artifacts", "task-16", "fixtures", "fixture-manifest.json")
    if not os.path.isfile(task16_manifest_path):
        problems.append("缺少任务 16 冻结 manifest（复用 fixture 的权威哈希来源）")
    else:
        task16_manifest = json.load(open(task16_manifest_path, encoding="utf-8"))
        for fixture_id, entry in manifest.get("reused_task16_fixtures", {}).items():
            path = os.path.join(FIXTURE_DIR, entry["relpath"])
            if not os.path.isfile(path):
                problems.append(f"复用 fixture 视频缺失: {path}")
                continue
            actual = sha256_of(path)
            expected_hash = task16_manifest["videos"].get(fixture_id, {}).get("sha256")
            if expected_hash is None:
                problems.append(f"任务 16 manifest 中找不到复用 fixture {fixture_id!r}")
            elif actual != expected_hash:
                problems.append(
                    f"{fixture_id}: 与任务 16 冻结 SHA-256 不一致（疑似被改动）")
    return problems


def main():
    parser = argparse.ArgumentParser(description="任务 18 technical fixture 生成与冻结")
    parser.add_argument("--verify", action="store_true", help="只校验冻结状态，不重新生成")
    args = parser.parse_args()

    if args.verify:
        problems = verify()
        if problems:
            for problem in problems:
                print(f"[校验失败] {problem}", file=sys.stderr)
            return 1
        print(f"RESULT: FROZEN_OK（{len(FIXTURES)} 个新 fixture 的 SHA-256 与元数据均与冻结值"
              f"一致；{len(REUSED_TASK16_FIXTURES)} 个复用 fixture 与任务 16 冻结一致）")
        return 0

    manifest = generate()
    problems = verify()
    if problems:
        for problem in problems:
            print(f"[校验失败] {problem}", file=sys.stderr)
        return 1
    print(f"[完成] 已生成并冻结 {manifest['video_count']} 个 synthetic technical fixture")
    print(f"  目录: {VIDEO_DIR}")
    print(f"  manifest: {os.path.join(FIXTURE_DIR, 'fixture-manifest.json')}")
    print(f"  ground truth: {os.path.join(FIXTURE_DIR, 'ground-truth.json')}")
    print("RESULT: FROZEN_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
