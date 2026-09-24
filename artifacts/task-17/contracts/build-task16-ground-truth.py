#!/usr/bin/env python3
"""build-task16-ground-truth.py — 从冻结的任务 16 fixture Ground Truth 派生
任务 17 契约格式的时间 Ground Truth（SparkSkill Studio 任务 17）

只读输入（不修改任何任务 16 文件）：
  artifacts/task-16/fixtures/fixture-manifest.json  （冻结 manifest：SHA-256/时长）
  artifacts/task-16/fixtures/ground-truth.json       （冻结 ground truth）

输出（artifacts/task-17/contracts/ground-truth/<sample_id>.temporal-ground-truth.json）：
  任务 17 temporal-ground-truth 契约（schema 1.0.0）。

状态映射（记录在每份 GT 的 label_frozen.derivation 中，可复算）：
  present              -> confirmed
  absent               -> not_found
  present_low_contrast  -> uncertain（低对比度区间：无法可靠确认，既非确定存在也非确定不存在）

边界容差：boundary_tolerance_ms = 250。理由：合成 fixture 由确定性渲染生成
（24fps，单帧 41.667ms），标注边界按百毫秒取整；250ms 覆盖标注取整误差与帧量化
误差，并对应任务 16 目标边界精度 500ms 的一半。该值写入 GT 文件，评分可复算。

确定性：输出只来自冻结输入与固定映射；同一输入永远得到同一输出。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TASK16_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
OUT_DIR = os.path.join(HERE, "ground-truth")

STATE_MAP = {
    "present": "confirmed",
    "absent": "not_found",
    "present_low_contrast": "uncertain",
}
BOUNDARY_TOLERANCE_MS = 250
DERIVATION = (
    "由 artifacts/task-16/fixtures/ground-truth.json（冻结于 2026-09-22T08:00:27Z）"
    "按固定映射派生：present->confirmed，absent->not_found，"
    "present_low_contrast->uncertain（低对比度区间无法可靠确认）；"
    "boundary_tolerance_ms=250（覆盖 24fps 帧量化与百毫秒标注取整，"
    "对应任务 16 目标边界精度 500ms 的一半）；未修改任何源标签"
)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def main():
    manifest = load_json(os.path.join(TASK16_FIXTURES, "fixture-manifest.json"))
    source_gt = load_json(os.path.join(TASK16_FIXTURES, "ground-truth.json"))
    frozen_at = source_gt.get("frozen_at", "2026-09-22T08:00:27.356200+00:00")
    os.makedirs(OUT_DIR, exist_ok=True)

    written = []
    for sample_id in sorted(source_gt["fixtures"]):
        fixture = source_gt["fixtures"][sample_id]
        video = manifest["videos"][sample_id]
        segments = []
        for segment in fixture["segments"]:
            state = STATE_MAP[segment["state"]]
            entry = {"start_ms": segment["start_ms"], "end_ms": segment["end_ms"],
                     "state": state}
            if state == "uncertain":
                entry["reason"] = ("低对比度区间（present_low_contrast）：目标难以可靠确认，"
                                   "标注为 uncertain")
            segments.append(entry)
        doc = {
            "schema_version": "1.0.0",
            "sample_id": sample_id,
            "media_sha256": video["sha256"],
            "media_duration_ms": source_gt["generation_params"]["duration_ms"],
            "target_query": source_gt["target_description"],
            "annotation_version": "1.0.0",
            "annotated_at": frozen_at,
            "annotator_id": "task16-fixture-freeze",
            "boundary_tolerance_ms": BOUNDARY_TOLERANCE_MS,
            "segments": segments,
            "label_frozen": {
                "frozen": True,
                "frozen_at": frozen_at,
                "derived_from": DERIVATION,
                "freeze_note": "派生自任务 16 冻结 fixture ground truth；"
                               "technical fixture，不得外推为真实素材结论",
            },
            "revision_history": [],
            "notes": fixture.get("purpose", ""),
        }
        path = os.path.join(OUT_DIR, f"{sample_id}.temporal-ground-truth.json")
        dump_json(path, doc)
        written.append(os.path.relpath(path, PROJECT_ROOT))
    for path in written:
        print(f"派生 Ground Truth: {path}")
    print(f"共 {len(written)} 份（状态映射 {STATE_MAP}，容差 {BOUNDARY_TOLERANCE_MS} ms）")


if __name__ == "__main__":
    main()
