#!/usr/bin/env python3
"""build-task16-evidence-pack.py — 生成任务 16 technical fixture 的
Evidence Pack manifest（SparkSkill Studio 任务 17）

只读输入（不修改任何任务 16 文件）：
  artifacts/task-16/fixtures/fixture-manifest.json  （冻结 manifest）
  artifacts/task-16/fixtures/ground-truth.json       （冻结 ground truth：时长/查询）

输出：artifacts/task-17/contracts/task16-fixture-evidence-pack-manifest.json
  （任务 17 evidence-pack-manifest 契约，schema 1.0.0；profile=task16-technical-fixtures）

纪律：
  - manifest 只声明输入清单与媒体身份（相对路径 + 冻结 SHA-256 + 时长），
    **不含任何时间真值**（Ground Truth 是显式独立输入，见
    artifacts/task-17/contracts/ground-truth/）；
  - 媒体相对路径指向任务 16 冻结视频（不复制、不修改）；
  - 5 个样本全部 split=dev、source_type=technical_fixture（合成技术测试输入，
    不得外推为真实仓储/园区准确率）；
  - public_demo_allowed=false / raw_file_public_git_allowed=false（保守默认）。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TASK16_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
OUT_PATH = os.path.join(HERE, "task16-fixture-evidence-pack-manifest.json")

MEDIA_PREFIX = "../../task-16/fixtures/videos/"
DATA_CARD_PREFIX = "data-cards/"


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def main():
    manifest = load_json(os.path.join(TASK16_FIXTURES, "fixture-manifest.json"))
    source_gt = load_json(os.path.join(TASK16_FIXTURES, "ground-truth.json"))
    duration_ms = source_gt["generation_params"]["duration_ms"]
    frozen_at = manifest.get("generated_at", "2026-09-22T08:00:27.356200+00:00")

    samples = []
    for sample_id in sorted(manifest["videos"]):
        video = manifest["videos"][sample_id]
        samples.append({
            "sample_id": sample_id,
            "split": "dev",
            "source_type": "technical_fixture",
            "media_path": MEDIA_PREFIX + video["file"],
            "media_sha256": video["sha256"],
            "media_duration_ms": duration_ms,
            "data_card": DATA_CARD_PREFIX + f"{sample_id}.md",
            "target_query": source_gt["target_description"],
            "task_type": "temporal_presence_evidence",
            "public_demo_allowed": False,
            "raw_file_public_git_allowed": False,
            "source_provenance": {
                "source_type": "technical_fixture",
                "fixture_generator_ref": "scripts/generate_task16_fixtures.py",
                "generation_params_ref": ("artifacts/task-16/fixtures/ground-truth.json"
                                          "#generation_params"),
                "freeze_record_ref": "artifacts/task-16/fixtures/fixtures.sha256.json",
                "notes": video.get("purpose", ""),
            },
        })

    doc = {
        "schema_version": "1.0.0",
        "pack_id": "task16-technical-fixtures",
        "profile": "task16-technical-fixtures",
        "created_at": frozen_at,
        "frozen_at": frozen_at,
        "samples": samples,
    }
    dump_json(OUT_PATH, doc)
    print(f"Evidence Pack manifest 已生成: "
          f"{os.path.relpath(OUT_PATH, PROJECT_ROOT)}（{len(samples)} 个样本）")


if __name__ == "__main__":
    main()
