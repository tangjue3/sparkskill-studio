#!/usr/bin/env python3
"""build_preregistration.py — 生成任务 18 预注册的数据文件（SparkSkill Studio 任务 18）

从冻结输入确定性生成：
  artifacts/task-18/preregistration/fixture-manifest.json       11 场景媒体/GT/预算清单
  artifacts/task-18/preregistration/ground-truth-manifest.json  11 份 GT 的哈希与区间摘要
  artifacts/task-18/preregistration/frozen-hashes.json          全部预注册/冻结输入的 SHA-256

输入（全部只读）：
  artifacts/task-18/fixtures/{fixture-manifest.json,ground-truth.json,fixtures.sha256.json,videos/*.mp4}
  artifacts/task-18/contracts/{task18-fixture-evidence-pack-manifest.json,ground-truth/*.json,data-cards/*.md}
  artifacts/task-16/fixtures/{fixture-manifest.json,ground-truth.json}
  本目录人工声明文件：evaluation-plan.json / arm-configs.json / verdict-policy.json / README.md
  设计文档：docs/plans/2026-09-22-coverage-aware-adaptive-sampling-design.md

frozen-hashes.json 不自哈希（无法包含自身）；核验脚本对其余文件逐一重算比对。
确定性：同一冻结输入永远得到同一输出。
"""
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TASK18_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "fixtures")
TASK18_CONTRACTS = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "contracts")
TASK16_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
DESIGN_DOC = os.path.join(
    PROJECT_ROOT, "docs", "plans", "2026-09-22-coverage-aware-adaptive-sampling-design.md")

# 场景顺序（预注册固定）：10 个同预算主对照 + 1 个 tight-budget
SCENARIO_ORDER = [
    "present-throughout",
    "appear-midway",
    "disappear-midway",
    "reappear",
    "short-event-between-grid",
    "short-uncertain-between-grid",
    "twin-short-events",
    "absent-throughout",
    "short-event-phase-b",
    "short-uncertain-phase-b",
    "reappear-tight-budget",
]
TIGHT_BUDGET_SCENARIOS = {"reappear-tight-budget"}
SAME_BUDGET = 12
TIGHT_BUDGET = 6

CATEGORY = {
    "present-throughout": "目标全程存在/无状态转换",
    "appear-midway": "中途出现",
    "disappear-midway": "中途消失",
    "reappear": "出现—消失—再次出现",
    "short-event-between-grid": "coarse 初始网格之间的短 confirmed 事件",
    "short-uncertain-between-grid": "coarse 初始网格之间的短 uncertain 区域",
    "twin-short-events": "两个间隔较短的事件",
    "absent-throughout": "无目标/无状态转换",
    "short-event-phase-b": "相位移动的短 confirmed 事件（对抗样本）",
    "short-uncertain-phase-b": "相位移动的短 uncertain 区域（对抗样本）",
    "reappear-tight-budget": "预算不足以同时完成覆盖与全部边界细化",
}


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    t18_manifest = load_json(os.path.join(TASK18_FIXTURES, "fixture-manifest.json"))
    t18_gt = load_json(os.path.join(TASK18_FIXTURES, "ground-truth.json"))
    t16_manifest = load_json(os.path.join(TASK16_FIXTURES, "fixture-manifest.json"))
    t16_gt = load_json(os.path.join(TASK16_FIXTURES, "ground-truth.json"))
    pack = load_json(os.path.join(
        TASK18_CONTRACTS, "task18-fixture-evidence-pack-manifest.json"))

    # ---- fixture-manifest.json（11 场景）
    scenarios = {}
    for sample_id in SCENARIO_ORDER:
        sample = next(item for item in pack["samples"] if item["sample_id"] == sample_id)
        origin_fixture = "reappear" if sample_id == "reappear-tight-budget" else sample_id
        if origin_fixture in t18_manifest["videos"]:
            origin = "task18-new"
            media_rel = "artifacts/task-18/fixtures/videos/" + t18_manifest["videos"][
                origin_fixture]["file"]
            media_sha = t18_manifest["videos"][origin_fixture]["sha256"]
        else:
            origin = "task16-reused"
            media_rel = "artifacts/task-16/fixtures/videos/" + t16_manifest["videos"][
                origin_fixture]["file"]
            media_sha = t16_manifest["videos"][origin_fixture]["sha256"]
        budget = TIGHT_BUDGET if sample_id in TIGHT_BUDGET_SCENARIOS else SAME_BUDGET
        gt_path = os.path.join(
            TASK18_CONTRACTS, "ground-truth", f"{sample_id}.temporal-ground-truth.json")
        gt_doc = load_json(gt_path)
        scenarios[sample_id] = {
            "category": CATEGORY[sample_id],
            "origin": origin,
            "media_file": os.path.basename(media_rel),
            "media_path": media_rel,
            "media_sha256": media_sha,
            "media_duration_ms": sample["media_duration_ms"],
            "target_query": sample["target_query"],
            "ground_truth": os.path.relpath(gt_path, PROJECT_ROOT),
            "ground_truth_sha256": sha256_of(gt_path),
            "max_model_calls_all_arms": budget,
            "in_same_budget_main_comparison": sample_id not in TIGHT_BUDGET_SCENARIOS,
        }
    fixture_manifest = {
        "schema_version": "1.0.0",
        "suite": "task-18-three-arm-fixtures",
        "nature": ("synthetic technical fixture（合成技术测试输入；非真实行业素材；"
                   "不得外推为真实仓储/园区准确率）"),
        "target_query": "红色正方形",
        "generation_params": t18_gt["generation_params"],
        "scenario_order": SCENARIO_ORDER,
        "scenarios": scenarios,
        "freeze_rule": ("第一次评测前冻结；场景、媒体、SHA-256、Ground Truth 与预算在本目录"
                        "冻结后不得修改；评测前核验 frozen-hashes.json"),
    }
    dump_json(os.path.join(HERE, "fixture-manifest.json"), fixture_manifest)

    # ---- ground-truth-manifest.json（11 份 GT 的哈希与区间摘要）
    gt_entries = {}
    gt_dir = os.path.join(TASK18_CONTRACTS, "ground-truth")
    for name in sorted(os.listdir(gt_dir)):
        if not name.endswith(".temporal-ground-truth.json"):
            continue
        path = os.path.join(gt_dir, name)
        doc = load_json(path)
        gt_entries[doc["sample_id"]] = {
            "path": os.path.relpath(path, PROJECT_ROOT),
            "sha256": sha256_of(path),
            "annotation_version": doc["annotation_version"],
            "boundary_tolerance_ms": doc["boundary_tolerance_ms"],
            "segments": [{"start_ms": item["start_ms"], "end_ms": item["end_ms"],
                          "state": item["state"]} for item in doc["segments"]],
            "label_frozen": doc["label_frozen"]["frozen"],
            "revision_history_after_model_run": any(
                item.get("after_model_run") for item in doc["revision_history"]),
        }
    ground_truth_manifest = {
        "schema_version": "1.0.0",
        "suite": "task-18-ground-truth",
        "contract": "schemas/temporal-ground-truth.schema.json（任务 17，schema 1.0.0）",
        "derivation": ("由冻结 fixture ground truth 按固定映射派生：present->confirmed，"
                       "absent->not_found，present_low_contrast->uncertain；"
                       "boundary_tolerance_ms=250；未修改任何源标签"),
        "samples": gt_entries,
    }
    dump_json(os.path.join(HERE, "ground-truth-manifest.json"), ground_truth_manifest)

    # ---- frozen-hashes.json（预注册文件 + fixture + GT + 契约 + 设计文档）
    def rel(path):
        return os.path.relpath(path, PROJECT_ROOT)

    frozen = {
        "schema_version": "1.0.0",
        "suite": "task-18-preregistration-freeze",
        "note": ("实现前后哈希一致性核验依据；本文件不自哈希；"
                 "任何预注册/冻结输入的改动都会使核验失败"),
        "preregistration_declarations": {},
        "preregistration_data": {},
        "fixtures": {},
        "ground_truth": {},
        "contracts": {},
        "design_doc": {},
    }
    for name in ("evaluation-plan.json", "arm-configs.json", "verdict-policy.json",
                 "README.md"):
        path = os.path.join(HERE, name)
        frozen["preregistration_declarations"][name] = {
            "path": rel(path), "sha256": sha256_of(path)}
    for name in ("fixture-manifest.json", "ground-truth-manifest.json"):
        path = os.path.join(HERE, name)
        frozen["preregistration_data"][name] = {"path": rel(path), "sha256": sha256_of(path)}
    t18_hashes = load_json(os.path.join(TASK18_FIXTURES, "fixtures.sha256.json"))
    for fixture_id, entry in t18_manifest["videos"].items():
        path = os.path.join(PROJECT_ROOT, entry["path"])
        frozen["fixtures"][fixture_id] = {
            "path": rel(path), "sha256": sha256_of(path),
            "matches_freeze_record": sha256_of(path) == t18_hashes.get(entry["file"])}
    for fixture_id, entry in t16_manifest["videos"].items():
        path = os.path.join(PROJECT_ROOT, entry["path"])
        frozen["fixtures"][f"task16-reused/{fixture_id}"] = {
            "path": rel(path), "sha256": sha256_of(path),
            "matches_freeze_record": sha256_of(path) == entry["sha256"]}
    for sample_id, entry in gt_entries.items():
        path = os.path.join(PROJECT_ROOT, entry["path"])
        frozen["ground_truth"][sample_id] = {"path": entry["path"],
                                             "sha256": sha256_of(path)}
    frozen["contracts"]["evidence_pack_manifest"] = {
        "path": rel(os.path.join(TASK18_CONTRACTS,
                                 "task18-fixture-evidence-pack-manifest.json")),
        "sha256": sha256_of(os.path.join(
            TASK18_CONTRACTS, "task18-fixture-evidence-pack-manifest.json"))}
    for name in sorted(os.listdir(os.path.join(TASK18_CONTRACTS, "data-cards"))):
        path = os.path.join(TASK18_CONTRACTS, "data-cards", name)
        frozen["contracts"][f"data-card/{name}"] = {
            "path": rel(path), "sha256": sha256_of(path)}
    frozen["design_doc"]["coverage-aware-adaptive-sampling-design"] = {
        "path": rel(DESIGN_DOC), "sha256": sha256_of(DESIGN_DOC)}
    dump_json(os.path.join(HERE, "frozen-hashes.json"), frozen)

    print(f"预注册数据文件已生成（{len(scenarios)} 个场景、{len(gt_entries)} 份 GT）")
    print(f"  fixture-manifest.json / ground-truth-manifest.json / frozen-hashes.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
