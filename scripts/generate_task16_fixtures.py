#!/usr/bin/env python3
"""generate_task16_fixtures.py — 任务 16 technical fixture 生成与冻结（SparkSkill Studio）

生成**明确标注为 synthetic technical fixture** 的小型测试视频，供任务 16 的
uniform vs adaptive 对照与规则测试使用。纪律（硬约束）：

  - fixture 是合成技术测试输入，**不是真实行业视频**，不作为视觉准确率或行业落地结论；
  - 生成参数与 ground truth 在第一次评测前冻结：manifest + ground-truth + SHA-256
    落盘后不得重新生成或修改标签迁就模型输出（校验函数 verify_fixtures() 供评测前复核）；
  - 不依赖新增软件包（仅用本机已有 OpenCV，经 skill_env 复用 vLLM 环境）；
  - 不进入用户保留的 holdout 集；
  - 若 Qwen 不能可靠理解某个 fixture，如实记录，不得修改标签。

用法:
    python3 scripts/generate_task16_fixtures.py            # 生成并冻结
    python3 scripts/generate_task16_fixtures.py --verify   # 只校验（不重新生成）
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

FIXTURE_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
VIDEO_DIR = os.path.join(FIXTURE_DIR, "videos")
FROZEN_AT_NOTE = "synthetic technical fixture（合成技术测试输入；非真实行业素材；不得外推）"

# 固定生成参数（冻结）：640x360、24 fps、8000 ms / 192 帧、mp4v、红色正方形 80x80 居中
WIDTH, HEIGHT, FPS, DURATION_MS = 640, 360, 24, 8000
FRAME_COUNT = int(DURATION_MS / 1000.0 * FPS)
SQUARE_SIZE = 80
TARGET_DESCRIPTION = "红色正方形"
BACKGROUND_BGR = (200, 200, 200)
SQUARE_BGR = (0, 0, 220)          # 红色（BGR）
SQUARE_LOW_CONTRAST_BGR = (214, 214, 214)  # 低对比度红方块（abstain-zone fixture 专用）

# fixture 定义：segments 按时间顺序覆盖 [0, DURATION_MS]；
# state ∈ present（清晰可见）/ absent（不存在）/ present_low_contrast（存在但低对比度，
# ground truth 仍是 present，该区间预期模型可能 abstained/low_confidence——如实记录，
# 不因此修改标签）
FIXTURES = [
    {
        "id": "present-throughout",
        "file": "fixture-present-throughout.mp4",
        "purpose": "持续正向 + 无状态变化（目标全程清晰存在；adaptive 应 0 次细化）",
        "segments": [{"start_ms": 0, "end_ms": DURATION_MS, "state": "present"}],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [],
            "note": "无状态变化：任何策略都应只有初始覆盖采样，细化轮数=0",
        },
    },
    {
        "id": "appear-midway",
        "file": "fixture-appear-midway.mp4",
        "purpose": "中途出现（目标在 3200 ms 进入画面）",
        "segments": [
            {"start_ms": 0, "end_ms": 3200, "state": "absent"},
            {"start_ms": 3200, "end_ms": DURATION_MS, "state": "present"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [{"at_ms": 3200, "from": "absent", "to": "present"}],
            "note": "adaptive 应把出现边界细化到目标精度内；uniform 只能给出固定网格边界",
        },
    },
    {
        "id": "disappear-midway",
        "file": "fixture-disappear-midway.mp4",
        "purpose": "中途消失（目标在 4800 ms 离开画面）",
        "segments": [
            {"start_ms": 0, "end_ms": 4800, "state": "present"},
            {"start_ms": 4800, "end_ms": DURATION_MS, "state": "absent"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [{"at_ms": 4800, "from": "present", "to": "absent"}],
            "note": "adaptive 应把消失边界细化到目标精度内",
        },
    },
    {
        "id": "reappear",
        "file": "fixture-reappear.mp4",
        "purpose": "出现、消失、再次出现（两次进入 + 两次离开）",
        "segments": [
            {"start_ms": 0, "end_ms": 2000, "state": "present"},
            {"start_ms": 2000, "end_ms": 4000, "state": "absent"},
            {"start_ms": 4000, "end_ms": 6000, "state": "present"},
            {"start_ms": 6000, "end_ms": DURATION_MS, "state": "absent"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [
                {"at_ms": 2000, "from": "present", "to": "absent"},
                {"at_ms": 4000, "from": "absent", "to": "present"},
                {"at_ms": 6000, "from": "present", "to": "absent"},
            ],
            "note": "多状态转换：考验细化轮次分配与预算控制",
        },
    },
    {
        "id": "abstain-zone",
        "file": "fixture-abstain-zone.mp4",
        "purpose": "abstained / low-confidence 区间（3000–5000 ms 目标低对比度，难以可靠确认）",
        "segments": [
            {"start_ms": 0, "end_ms": 3000, "state": "present"},
            {"start_ms": 3000, "end_ms": 5000, "state": "present_low_contrast"},
            {"start_ms": 5000, "end_ms": DURATION_MS, "state": "present"},
        ],
        "expected": {
            "target_present": True,
            "transitions_ground_truth": [],
            "uncertain_window_ms": [3000, 5000],
            "note": ("ground truth 为全程存在；低对比度区间预期模型可能 abstained 或 "
                     "low_confidence——如实记录，不得修改标签迁就模型输出"),
        },
    },
]

MULTI_SOURCE_PAIR = {
    "id": "multi-source-pair",
    "sources": [
        {"source_id": "video-a", "file": "fixture-appear-midway.mp4",
         "location": "scene-a", "time_offset_ms": 0},
        {"source_id": "video-b", "file": "fixture-disappear-midway.mp4",
         "location": "scene-b", "time_offset_ms": 5000},
    ],
    "note": "多来源输入 fixture：两段合成视频，source_id 与原视频时间戳必须保留",
}


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
    """确定性渲染一个 fixture 视频（无随机性；同一参数永远得到同一字节流内容）。"""
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
    ground_truth = {
        "suite": "task-16-technical-fixtures",
        "nature": FROZEN_AT_NOTE,
        "target_description": TARGET_DESCRIPTION,
        "frozen_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "generation_params": {
            "width": WIDTH, "height": HEIGHT, "fps": FPS,
            "duration_ms": DURATION_MS, "frame_count": FRAME_COUNT,
            "square_size": SQUARE_SIZE, "codec": "mp4v",
            "background_bgr": list(BACKGROUND_BGR),
            "square_bgr": list(SQUARE_BGR),
            "square_low_contrast_bgr": list(SQUARE_LOW_CONTRAST_BGR),
            "deterministic": True,
        },
        "fixtures": {},
        "multi_source_pair": MULTI_SOURCE_PAIR,
        "rule_level_fixtures": [
            {"id": "single-frame-failed",
             "nature": "规则级 fixture（构造结构化证据，非模型输出）",
             "purpose": "单帧 failed：时间线中一帧 frame_status=failed，不得折算为 not_found"},
            {"id": "budget-exhaustion",
             "nature": "规则级 fixture（构造结构化证据 + 极小预算）",
             "purpose": "预算耗尽：max_model_calls 不足以覆盖全部细化候选时停止细化并如实报告"},
        ],
        "red_lines": [
            "fixture 结果不得外推为真实仓储准确率",
            "Qwen 不能可靠理解某个 fixture 时如实记录，不得修改标签",
            "fixture 不进入用户 holdout 集",
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
        "suite": "task-16-technical-fixtures",
        "nature": FROZEN_AT_NOTE,
        "generated_at": ground_truth["frozen_at"],
        "video_count": len(FIXTURES),
        "videos": {fixture["id"]: {
            "file": fixture["file"],
            "path": os.path.join("artifacts", "task-16", "fixtures", "videos", fixture["file"]),
            "sha256": hashes[fixture["file"]],
            "purpose": fixture["purpose"],
        } for fixture in FIXTURES},
        "ground_truth": "artifacts/task-16/fixtures/ground-truth.json",
        "hashes": "artifacts/task-16/fixtures/fixtures.sha256.json",
        "multi_source_pair": MULTI_SOURCE_PAIR,
        "freeze_rule": ("第一次评测前冻结；manifest/hash 落盘后不得重新生成或修改标签；"
                        "评测前用 --verify 复核 SHA-256 与元数据"),
    }
    with open(os.path.join(FIXTURE_DIR, "fixture-manifest.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def verify():
    """评测前复核：manifest/hash/ground-truth 存在且一致，视频元数据符合冻结参数。"""
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
    return problems


def main():
    parser = argparse.ArgumentParser(description="任务 16 technical fixture 生成与冻结")
    parser.add_argument("--verify", action="store_true", help="只校验冻结状态，不重新生成")
    args = parser.parse_args()

    if args.verify:
        problems = verify()
        if problems:
            for problem in problems:
                print(f"[校验失败] {problem}", file=sys.stderr)
            return 1
        print(f"RESULT: FROZEN_OK（{len(FIXTURES)} 个 fixture 的 SHA-256 与元数据均与冻结值一致）")
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
