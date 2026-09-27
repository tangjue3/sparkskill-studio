#!/usr/bin/env python3
"""freeze_task28_hashes.py — 冻结 Task 28 State Expressiveness Gate 的预注册与实现 hash

把 FINAL 预注册（docs/plans/2026-09-25-state-expressiveness-gate.md）与三个实现脚本的
SHA-256 写入 `artifacts/task-28/freezes/pre-freeze-hashes.json`。

纪律:
  - **先于任何 dev 数据 replay**。本次只记录 hash，不读取 dev 模型输出、不产生任何
    Oracle 数字。
  - 冻结后若实现脚本再变，必须重跑本脚本并保留旧文件（不得覆盖历史）。
  - 若同一路径已存在冻结记录且内容不同，默认拒绝覆盖（--force 需显式声明）。

用法: python3 scripts/freeze_task28_hashes.py [--out <dir>] [--force]
退出码: 0 = 冻结写入; 1 = 已存在不同冻结且未 --force; 2 = 用法/IO 错误
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# 冻结清单：(仓库相对路径, 角色说明)
# 注意：**不含 freeze_task28_hashes.py 自身**——它的内容会随清单/逻辑演进而变化，
# 把它自己写进冻结会把"改冻结脚本"和"改 Gate 实现"混为一类，导致无法区分。
# 冻结脚本本身的版本由 Git 历史与 archive/ 目录承担。
FROZEN_PATHS = (
    ("docs/plans/2026-09-25-state-expressiveness-gate.md", "预注册（FINAL，含 R1/R2 修订记录）"),
    (".dsh/skills/visual-evidence-extractor/scripts/state_resolver.py",
     "三态 + UncertaintyReason 解析器（含 H5 failed 保留）"),
    ("scripts/score_state_replay.py", "replay 评分器（archived_replay / G7r / H5 排除）"),
    ("scripts/test_state_expressiveness_gate.py", "Gate 确定性测试"),
    ("scripts/verify_internal_inputs.py", "internal-only 输入接入校验（显式路径，不搜索）"),
)

# 反向护栏：这些路径必须保持冻结（内容锚点检查，防止在 Gate 前顺手改掉）。
GUARDED_ANCHORS = (
    ("scripts/score_temporal_ground_truth.py", "G7-provenance-self-consistency"),
    (".dsh/skills/visual-evidence-extractor/scripts/analyze_image.py", "PROMPT_TEMPLATE"),
)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="冻结 Task 28 Gate 预注册与实现 hash")
    parser.add_argument("--out", default=None,
                        help="输出目录（默认 artifacts/task-28/freezes）")
    parser.add_argument("--force", action="store_true",
                        help="允许覆盖已存在的不同冻结记录")
    args = parser.parse_args()

    out_dir = args.out or os.path.join(PROJECT_ROOT, "artifacts", "task-28", "freezes")
    out_path = os.path.join(out_dir, "pre-freeze-hashes.json")

    missing = [rel for rel, _ in FROZEN_PATHS
               if not os.path.isfile(os.path.join(PROJECT_ROOT, rel))]
    if missing:
        print("[错误] 待冻结文件缺失：", file=sys.stderr)
        for rel in missing:
            print(f"  - {rel}", file=sys.stderr)
        return 2

    if os.path.isfile(out_path) and not args.force:
        with open(out_path, encoding="utf-8") as handle:
            existing = json.load(handle)
        existing_paths = {item["path"]: item["sha256"] for item in existing.get("files", [])}
        changed = []
        for rel, _ in FROZEN_PATHS:
            current = sha256_of(os.path.join(PROJECT_ROOT, rel))
            if existing_paths.get(rel) not in (None, current):
                changed.append(rel)
        if changed:
            print("[拒绝] 已存在冻结记录且以下文件已变化（--force 才会覆盖）：", file=sys.stderr)
            for rel in changed:
                print(f"  - {rel}", file=sys.stderr)
            return 1

    os.makedirs(out_dir, exist_ok=True)

    files = []
    for rel, role in FROZEN_PATHS:
        path = os.path.join(PROJECT_ROOT, rel)
        files.append({
            "path": rel,
            "role": role,
            "bytes": os.path.getsize(path),
            "sha256": sha256_of(path),
        })

    guards = []
    for rel, anchor in GUARDED_ANCHORS:
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path):
            guards.append({"path": rel, "anchor": anchor, "present": False})
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read(20000)
        guards.append({"path": rel, "anchor": anchor, "present": anchor in text})

    doc = {
        "schema_version": "1.0.0",
        "freeze_name": "task28-state-expressiveness-gate-pre-freeze",
        "frozen_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "scope": "预注册 FINAL + 实现脚本；**先于任何 dev 数据 replay**",
        "model_calls_at_freeze": 0,
        "files": files,
        "guarded_anchors": guards,
        "notes": [
            "冻结后修改实现须重跑本脚本；旧冻结文件不得覆盖。",
            "本冻结不触及 dev 模型输出、GT、holdout。",
            "primary denominator = 8 unique GT boundary times（三臂 24 暴露为 secondary）。",
        ],
    }

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")

    print(f"[冻结] {os.path.relpath(out_path, PROJECT_ROOT)}")
    for item in files:
        print(f"  - {item['path']}: {item['sha256'][:16]}… ({item['bytes']} B)")
    bad = [item for item in guards if not item["present"]]
    if bad:
        print("[警告] 以下护栏锚点缺失（可能被就地改写）：", file=sys.stderr)
        for item in bad:
            print(f"  - {item['path']} 缺 {item['anchor']!r}", file=sys.stderr)
        return 1
    print("RESULT: FROZEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
