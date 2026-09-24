#!/usr/bin/env python3
"""build_task19_ground_truth.py — Task 19B Ground Truth 确定性派生（SparkSkill Studio）

唯一标签来源：dev 包内九张 transfer-safe card（已由 task19_ingest.py 字节 identical
复制到 artifacts/task-19/ingestion/data-cards/；源卡与 dev 包只读，不被修改）。

派生规则（结构规范化，不改变任何状态判定；任务 17 时间线契约）：
  N1 相邻同状态区间合并（任务 17 契约第 5 条；原人工原因以"；"连接完整保留）；
  N2 末段 end_ms 对齐实测时长（cv2 read_metadata 公式 round(frames/fps*1000, 3)，
     与流水线 evidence.duration_ms 同一口径；仅改末段终点数值，不改变状态与边界）；
  N3 校验：状态覆盖未改变（按状态累计时长前后一致）、边界语义未新增（状态变化点
     集合前后一致）、无重叠/无空隙/从 0 开始/覆盖到实测终点/每段长度为正。

输出：
  artifacts/task-19/ground-truth/<sample_id>.json   九份任务 17 契约 GT（确定性）
  artifacts/task-19/preregistration/ground-truth-normalization-report.json  规范化报告

本脚本不调用任何模型、不联网、不修改源卡。任何样本规范化校验失败即退出码 1。
用法:
    python3 scripts/build_task19_ground_truth.py
"""
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
INGESTION = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ingestion")
CARDS_DIR = os.path.join(INGESTION, "data-cards")
LINK_MAP = os.path.join(INGESTION, "media-link-map.json")
GROUND_TRUTH_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ground-truth")
# 规范化报告属预注册证据（任务书第五节"预注册至少包含 … Ground Truth normalization
# report"）；不放 ground-truth/ 目录——评分器 --ground-truth 目录输入会加载其中全部
# *.json，GT 目录必须只含九份 GT。
PREREGISTRATION = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "preregistration")
NORMALIZATION_REPORT = os.path.join(PREREGISTRATION,
                                    "ground-truth-normalization-report.json")

WHITELIST = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06",
             "WEB01", "WEB02", "WEB03"]
GT_SCHEMA_VERSION = "1.0.0"
ANNOTATION_VERSION = "task19-dev-gt-1.0.0"
ANNOTATED_AT = "2026-09-22"
ANNOTATOR_ID = "总控（人工观察）"
# dev 包素材冻结时间 2026-09-22 21:12:24 +08:00 = 2026-09-22T13:12:24Z（固定值，保证确定性）
SOURCE_FREEZE_UTC = "2026-09-22T13:12:24Z"


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def merge_adjacent_same_state(segments):
    """N1：合并相邻同状态区间；原人工原因以'；'连接保留。返回 (merged, merge_records)。"""
    merged = []
    records = []
    for segment in segments:
        if merged and merged[-1]["state"] == segment["state"]:
            previous = merged[-1]
            records.append({
                "action": "merge_adjacent_same_state",
                "state": segment["state"],
                "merged_from": [
                    {"start_ms": previous["start_ms"], "end_ms": previous["end_ms"]},
                    {"start_ms": segment["start_ms"], "end_ms": segment["end_ms"]},
                ],
                "merged_into": {"start_ms": previous["start_ms"],
                                "end_ms": segment["end_ms"]},
                "reasons_preserved": [previous.get("reason"), segment.get("reason")],
            })
            previous["end_ms"] = segment["end_ms"]
            reasons = [previous.get("reason"), segment.get("reason")]
            previous["reason"] = "；".join(reason for reason in reasons if reason)
        else:
            merged.append({
                "start_ms": segment["start_ms"],
                "end_ms": segment["end_ms"],
                "state": segment["state"],
                **({"reason": segment["reason"]} if segment.get("reason") else {}),
            })
    return merged, records


def state_coverage(segments, clip_end_ms=None):
    """按状态累计覆盖时长（毫秒）；clip_end_ms 给定时期末段裁剪到实测媒体终点
    （卡片标称时长可能略长于实测时长，超出部分在媒体中不存在）。"""
    coverage = {}
    for segment in segments:
        end = segment["end_ms"]
        if clip_end_ms is not None:
            end = min(end, clip_end_ms)
        coverage[segment["state"]] = (coverage.get(segment["state"], 0.0)
                                      + max(0.0, end - segment["start_ms"]))
    return coverage


def boundary_set(segments):
    """状态变化点集合（取右段 start_ms；不含媒体终点）。"""
    return {segments[index]["start_ms"] for index in range(1, len(segments))
            if segments[index]["state"] != segments[index - 1]["state"]}


def derive_ground_truth(card, measured_duration_ms):
    """从单张 transfer-safe 卡派生 GT；返回 (gt_doc, normalization_record)。"""
    sample_id = card["sample_id"]
    original = [dict(segment) for segment in card["expected_timeline"]]
    merged, merge_records = merge_adjacent_same_state(original)

    # N2 末段 end_ms 对齐实测时长
    tail_records = []
    card_duration = card["media"]["duration_ms"]
    last = merged[-1]
    if round(float(last["end_ms"]), 3) != round(float(measured_duration_ms), 3):
        tail_records.append({
            "action": "align_last_segment_end_to_measured_duration",
            "from_end_ms": last["end_ms"],
            "to_end_ms": measured_duration_ms,
            "card_nominal_duration_ms": card_duration,
            "measured_duration_ms": measured_duration_ms,
            "note": ("卡片标称时长与 cv2 实测时长存在毫秒级差异；末段终点对齐实测时长"
                     "（与流水线 evidence.duration_ms 同一公式），状态与边界语义不变"),
        })
        last["end_ms"] = measured_duration_ms

    # N3 结构校验（状态覆盖未改变 / 边界语义未新增 / 时间线合法）
    # 状态覆盖在实测媒体范围 [0, measured_duration_ms] 内比较：卡片标称时长可能
    # 略长于实测时长（WEB01 -8.133ms / WEB02 -16.433ms），超出部分在媒体中不存在，
    # 不属于任何状态覆盖。
    coverage_before = state_coverage(original, clip_end_ms=measured_duration_ms)
    coverage_after = state_coverage(merged)
    boundaries_before = boundary_set(original)
    boundaries_after = boundary_set(merged)
    problems = []
    if {state: round(value, 6) for state, value in coverage_before.items()} != \
            {state: round(value, 6) for state, value in coverage_after.items()}:
        problems.append("状态覆盖被改变")
    if boundaries_before != boundaries_after:
        problems.append("边界集合被改变")
    if merged[0]["start_ms"] != 0:
        problems.append("时间线未从 0 开始")
    if round(float(merged[-1]["end_ms"]), 3) != round(float(measured_duration_ms), 3):
        problems.append("时间线未覆盖到实测终点")
    for index in range(1, len(merged)):
        if merged[index]["start_ms"] != merged[index - 1]["end_ms"]:
            problems.append(f"相邻段在索引 {index} 处不连续")
    for index, segment in enumerate(merged):
        if segment["end_ms"] <= segment["start_ms"]:
            problems.append(f"段 {index} 长度非正")
    if problems:
        raise SystemExit(f"[错误] {sample_id} 规范化校验失败: {problems}")

    gt = {
        "schema_version": GT_SCHEMA_VERSION,
        "sample_id": sample_id,
        "media_sha256": card["media"]["sha256"].lower(),
        "media_duration_ms": round(float(measured_duration_ms), 3),
        "target_query": card["task"]["target_query"],
        "annotation_version": ANNOTATION_VERSION,
        "annotated_at": ANNOTATED_AT,
        "annotator_id": ANNOTATOR_ID,
        "boundary_tolerance_ms": card["task"]["boundary_tolerance_ms"],
        "segments": merged,
        "label_frozen": {
            "frozen": True,
            "frozen_at": SOURCE_FREEZE_UTC,
            "derived_from": (f"task19-dev-pack-v1/data-cards/transfer-safe/{sample_id}.json"
                             f"（transfer-safe 卡 SHA-256 {card['lineage']['source_card_sha256']}"
                             f" 的派生卡；唯一标签来源；源卡与 dev 包只读未修改）"),
            "freeze_note": ("标签由总控 2026-09-22 人工观察给出；本 GT 为确定性结构派生"
                            "（相邻同状态合并 + 末段终点对齐实测时长），未改变任何状态判定、"
                            "边界语义或人工原因；模型运行前冻结，运行后不得修订"),
        },
        "revision_history": [],
        "notes": (f"派生自 transfer-safe 卡 {sample_id}.json；源卡标称时长 "
                  f"{card_duration}ms，实测时长 {measured_duration_ms}ms；"
                  f"合并 {len(merge_records)} 处相邻同状态区间，末段终点对齐 "
                  f"{'是' if tail_records else '否'}；状态覆盖与边界集合经校验未改变。"),
    }
    record = {
        "sample_id": sample_id,
        "source_card": {
            "path": f"artifacts/task-19/ingestion/data-cards/{sample_id}.json",
            "pack_relative_path": f"data-cards/transfer-safe/{sample_id}.json",
            "sha256": None,  # 由调用方填充（复制的卡哈希）
            "source_card_path": card["lineage"]["source_card_path"],
            "source_card_sha256": card["lineage"]["source_card_sha256"],
            "core_fields_unchanged": card["lineage"]["core_fields_unchanged"],
        },
        "original_segments": original,
        "merged_segments": merged,
        "merge_records": merge_records,
        "tail_alignment_records": tail_records,
        "state_coverage_before": coverage_before,
        "state_coverage_after": coverage_after,
        "state_coverage_comparison_range_ms": [0, round(float(measured_duration_ms), 3)],
        "state_coverage_note": ("在实测媒体范围 [0, measured_duration_ms] 内比较；"
                                "卡片标称时长超出实测时长的部分在媒体中不存在"),
        "state_coverage_unchanged": (
            {k: round(v, 6) for k, v in coverage_before.items()}
            == {k: round(v, 6) for k, v in coverage_after.items()}),
        "boundaries_before": sorted(boundaries_before),
        "boundaries_after": sorted(boundaries_after),
        "boundary_semantics_unchanged": boundaries_before == boundaries_after,
        "human_reasons_preserved": [
            segment.get("reason") for segment in original if segment.get("reason")],
        "gt_sha256": None,  # 由调用方填充
    }
    return gt, record


def main():
    if not os.path.isfile(LINK_MAP):
        raise SystemExit("[错误] 缺少 media-link-map.json：请先运行 scripts/task19_ingest.py")
    link_map = load_json(LINK_MAP)["links"]
    os.makedirs(GROUND_TRUTH_DIR, exist_ok=True)

    import hashlib

    def sha256_of(path):
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # 复用任务 17 冻结校验器（不修改）：每份 GT 必须通过契约校验
    sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "validate_evidence_pack",
        os.path.join(PROJECT_ROOT, "scripts", "validate_evidence_pack.py"))
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    report = {
        "task": "task-19b-ground-truth-derivation",
        "label_source": "dev 包 transfer-safe card（唯一标签来源；源卡只读未修改）",
        "rules": [
            "N1 相邻同状态区间按任务 17 契约合并；原人工原因以'；'连接完整保留",
            "N2 末段 end_ms 对齐 cv2 实测时长（与流水线 evidence.duration_ms 同一公式）",
            "N3 状态覆盖未改变、边界语义未新增、时间线合法性七条全部满足",
        ],
        "samples": {},
    }
    for sample_id in WHITELIST:
        card = load_json(os.path.join(CARDS_DIR, f"{sample_id}.json"))
        measured = link_map[sample_id]["measured_duration_ms"]
        gt, record = derive_ground_truth(card, measured)
        gt_path = os.path.join(GROUND_TRUTH_DIR, f"{sample_id}.json")
        dump_json(gt_path, gt)
        problems = validator.validate_ground_truth(gt)
        if problems:
            raise SystemExit(f"[错误] {sample_id} GT 未通过任务 17 契约校验: "
                             + "；".join(str(item) for item in problems))
        card_copy = os.path.join(CARDS_DIR, f"{sample_id}.json")
        record["source_card"]["sha256"] = sha256_of(card_copy)
        record["gt_sha256"] = sha256_of(gt_path)
        report["samples"][sample_id] = record
        print(f"[GT] {sample_id}: {len(record['original_segments'])} 段 → "
              f"{len(gt['segments'])} 段（合并 {len(record['merge_records'])} 处，"
              f"末段对齐 {'是' if record['tail_alignment_records'] else '否'}）")

    dump_json(NORMALIZATION_REPORT, report)
    print(f"\n[GT 派生完成] 九份 GT 通过任务 17 契约校验；规范化报告: "
          f"{os.path.relpath(NORMALIZATION_REPORT, PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
