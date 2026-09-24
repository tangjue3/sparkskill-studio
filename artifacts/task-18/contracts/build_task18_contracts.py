#!/usr/bin/env python3
"""build_task18_contracts.py — 生成任务 18 三臂评测的 Evidence Pack 契约
（manifest + 时间 Ground Truth + 数据卡；SparkSkill Studio 任务 18）

只读输入（不修改任何任务 16/18 冻结文件）：
  artifacts/task-18/fixtures/fixture-manifest.json  （任务 18 冻结 manifest：6 段新 fixture）
  artifacts/task-18/fixtures/ground-truth.json       （任务 18 冻结 ground truth）
  artifacts/task-16/fixtures/fixture-manifest.json   （任务 16 冻结 manifest：4 段复用 fixture）
  artifacts/task-16/fixtures/ground-truth.json       （任务 16 冻结 ground truth）

输出：
  artifacts/task-18/contracts/task18-fixture-evidence-pack-manifest.json
  artifacts/task-18/contracts/ground-truth/<sample_id>.temporal-ground-truth.json（11 份）
  artifacts/task-18/contracts/data-cards/<sample_id>.md（11 份）

纪律（与任务 17 一致）：
  - manifest 只声明输入清单与媒体身份（相对路径 + 冻结 SHA-256 + 时长），
    **不含任何时间真值**（Ground Truth 是显式独立输入）；
  - 媒体相对路径指向冻结视频（不复制、不修改）；
  - 全部样本 split=dev、source_type=technical_fixture（合成技术测试输入，
    不得外推为真实仓储/园区准确率）；
  - public_demo_allowed=false / raw_file_public_git_allowed=false（保守默认）；
  - 状态映射（与任务 17 逐条一致，记录在每份 GT 的 label_frozen.derivation）：
    present -> confirmed；absent -> not_found；present_low_contrast -> uncertain；
  - boundary_tolerance_ms=250（覆盖 24fps 帧量化与百毫秒标注取整）；
  - 确定性：输出只来自冻结输入与固定映射；同一输入永远得到同一输出。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TASK18_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "fixtures")
TASK16_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
GT_OUT_DIR = os.path.join(HERE, "ground-truth")
DATA_CARD_DIR = os.path.join(HERE, "data-cards")
OUT_PATH = os.path.join(HERE, "task18-fixture-evidence-pack-manifest.json")

TASK18_MEDIA_PREFIX = "../fixtures/videos/"
TASK16_MEDIA_PREFIX = "../../task-16/fixtures/videos/"

STATE_MAP = {
    "present": "confirmed",
    "absent": "not_found",
    "present_low_contrast": "uncertain",
}
BOUNDARY_TOLERANCE_MS = 250

# 场景目录：主对照场景（三臂统一预算 12）+ 预算不足场景（三臂统一预算 6，显式标注）。
# 复用任务 16 的 4 段冻结 fixture + 任务 18 新增的 6 段 fixture。
SCENARIOS = [
    # (sample_id, 来源, fixture_id, 用途类别)
    ("present-throughout", "task16", "present-throughout", "目标全程存在/无状态转换"),
    ("appear-midway", "task16", "appear-midway", "中途出现"),
    ("disappear-midway", "task16", "disappear-midway", "中途消失"),
    ("reappear", "task16", "reappear", "出现—消失—再次出现"),
    ("short-event-between-grid", "task18", "short-event-between-grid",
     "coarse 初始网格之间的短 confirmed 事件"),
    ("short-uncertain-between-grid", "task18", "short-uncertain-between-grid",
     "coarse 初始网格之间的短 uncertain 区域"),
    ("twin-short-events", "task18", "twin-short-events", "两个间隔较短的事件"),
    ("absent-throughout", "task18", "absent-throughout", "无目标/无状态转换"),
    ("short-event-phase-b", "task18", "short-event-phase-b", "相位移动的短 confirmed 事件"),
    ("short-uncertain-phase-b", "task18", "short-uncertain-phase-b",
     "相位移动的短 uncertain 区域"),
    ("reappear-tight-budget", "task16", "reappear",
     "预算不足以同时完成覆盖与全部边界细化（三臂统一预算 6）"),
]


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def source_of(origin):
    if origin == "task18":
        return (load_json(os.path.join(TASK18_FIXTURES, "fixture-manifest.json")),
                load_json(os.path.join(TASK18_FIXTURES, "ground-truth.json")),
                TASK18_MEDIA_PREFIX, "scripts/generate_task18_fixtures.py",
                "artifacts/task-18/fixtures/ground-truth.json#generation_params",
                "artifacts/task-18/fixtures/fixtures.sha256.json")
    return (load_json(os.path.join(TASK16_FIXTURES, "fixture-manifest.json")),
            load_json(os.path.join(TASK16_FIXTURES, "ground-truth.json")),
            TASK16_MEDIA_PREFIX, "scripts/generate_task16_fixtures.py",
            "artifacts/task-16/fixtures/ground-truth.json#generation_params",
            "artifacts/task-16/fixtures/fixtures.sha256.json")


def main():
    os.makedirs(GT_OUT_DIR, exist_ok=True)
    os.makedirs(DATA_CARD_DIR, exist_ok=True)

    samples = []
    gt_written = []
    cards_written = []
    for sample_id, origin, fixture_id, category in SCENARIOS:
        manifest, source_gt, media_prefix, generator_ref, params_ref, freeze_ref = \
            source_of(origin)
        fixture = source_gt["fixtures"][fixture_id]
        video = manifest["videos"][fixture_id]
        duration_ms = source_gt["generation_params"]["duration_ms"]
        frozen_at = manifest.get("generated_at", "2026-09-22T08:00:27.356200+00:00")
        target_query = source_gt["target_description"]

        samples.append({
            "sample_id": sample_id,
            "split": "dev",
            "source_type": "technical_fixture",
            "media_path": media_prefix + video["file"],
            "media_sha256": video["sha256"],
            "media_duration_ms": duration_ms,
            "data_card": "data-cards/" + f"{sample_id}.md",
            "target_query": target_query,
            "task_type": "temporal_presence_evidence",
            "public_demo_allowed": False,
            "raw_file_public_git_allowed": False,
            "source_provenance": {
                "source_type": "technical_fixture",
                "fixture_generator_ref": generator_ref,
                "generation_params_ref": params_ref,
                "freeze_record_ref": freeze_ref,
                "notes": f"{category}；{fixture.get('purpose', '')}",
            },
        })

        # Ground Truth（任务 17 temporal-ground-truth 契约）
        segments = []
        for segment in fixture["segments"]:
            state = STATE_MAP[segment["state"]]
            entry = {"start_ms": segment["start_ms"], "end_ms": segment["end_ms"],
                     "state": state}
            if state == "uncertain":
                entry["reason"] = ("低对比度区间（present_low_contrast）：目标难以可靠确认，"
                                   "标注为 uncertain")
            segments.append(entry)
        derivation = (
            f"由 {params_ref.split('#')[0]}（冻结 manifest + ground truth）按固定映射派生："
            "present->confirmed，absent->not_found，present_low_contrast->uncertain；"
            "boundary_tolerance_ms=250（覆盖 24fps 帧量化与百毫秒标注取整，"
            "对应任务 16 目标边界精度 500ms 的一半）；未修改任何源标签"
        )
        gt_doc = {
            "schema_version": "1.0.0",
            "sample_id": sample_id,
            "media_sha256": video["sha256"],
            "media_duration_ms": duration_ms,
            "target_query": target_query,
            "annotation_version": "1.0.0",
            "annotated_at": frozen_at,
            "annotator_id": "task18-fixture-freeze",
            "boundary_tolerance_ms": BOUNDARY_TOLERANCE_MS,
            "segments": segments,
            "label_frozen": {
                "frozen": True,
                "frozen_at": frozen_at,
                "derived_from": derivation,
                "freeze_note": ("任务 18 三臂评测 fixture ground truth；"
                                "technical fixture，不得外推为真实素材结论"),
            },
            "revision_history": [],
            "notes": f"{category}；{fixture.get('purpose', '')}",
        }
        gt_path = os.path.join(GT_OUT_DIR, f"{sample_id}.temporal-ground-truth.json")
        dump_json(gt_path, gt_doc)
        gt_written.append(os.path.relpath(gt_path, PROJECT_ROOT))

        # 数据卡（人读；与任务 17 数据卡同结构）
        segment_lines = []
        for segment in gt_doc["segments"]:
            segment_lines.append(
                f"  - [{segment['start_ms']}, {segment['end_ms']}) ms → {segment['state']}")
        card = [
            f"# 数据卡 — {sample_id}",
            "",
            "- 性质：synthetic technical fixture（合成技术测试输入；"
            "**非真实行业素材；不得外推为真实仓储/园区准确率**）",
            f"- 用途：{category}；{fixture.get('purpose', '')}",
            f"- 媒体：`{video['file']}`（SHA-256 `{video['sha256']}`，"
            f"{'复用任务 16 冻结 fixture' if origin == 'task16' else '任务 18 新增冻结 fixture'}）",
            "- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染",
            f"- 目标查询：{target_query}",
            f"- 时间真值（任务 17 契约，详见 `ground-truth/{sample_id}.temporal-ground-truth.json`）：",
            *segment_lines,
            "",
        ]
        card_path = os.path.join(DATA_CARD_DIR, f"{sample_id}.md")
        with open(card_path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(card))
        cards_written.append(os.path.relpath(card_path, PROJECT_ROOT))

    doc = {
        "schema_version": "1.0.0",
        "pack_id": "task18-technical-fixtures",
        "profile": "task18-technical-fixtures",
        "created_at": samples[0] and load_json(
            os.path.join(TASK18_FIXTURES, "fixture-manifest.json"))["generated_at"],
        "frozen_at": load_json(
            os.path.join(TASK18_FIXTURES, "fixture-manifest.json"))["generated_at"],
        "samples": samples,
    }
    dump_json(OUT_PATH, doc)
    print(f"Evidence Pack manifest 已生成: "
          f"{os.path.relpath(OUT_PATH, PROJECT_ROOT)}（{len(samples)} 个样本）")
    for path in gt_written:
        print(f"派生 Ground Truth: {path}")
    for path in cards_written:
        print(f"数据卡: {path}")


if __name__ == "__main__":
    main()
