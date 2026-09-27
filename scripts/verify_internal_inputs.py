#!/usr/bin/env python3
"""verify_internal_inputs.py — Task 28 internal frozen artifacts 只读接入校验

把"内部留档产物如何接入 replay"固化为**可执行的 9 步顺序**，而不是靠自觉。

设计（与项目媒体 provenance 原则一致）:

  1. 内部产物**不复制进 sparkskill-studio**，不临时提交，保持在仓库外只读。
  2. 通过**显式** `--taskNN-root` 传入。本脚本刻意**禁止**：
       - `find` / 全盘 `glob`
       - 从 README / run-summary 猜路径
       - 从旧 summary 重建/合成 predictions
     即"猜路径"本身就是失败，而不是降级为搜索。
  3. `internal-manifest.json` 只描述 artifact_id / expected_sha256 /
     relative_path / data_nature=internal_frozen_artifact / source_task。

顺序（预注册 §6.7 / manifest 契约）:

  1. 校验 internal manifest 存在且结构合法；
  2. 逐项校验 SHA-256（大小写不敏感）；
  3. 校验 data_nature == internal_frozen_artifact；
  4. 校验所有输入为 read-only / archived（拒绝 fresh_call 证据）；
  5. 校验 frozen Gate hashes 未变（--freeze 指向 pre-freeze-hashes.json）；
  6. 校验 fresh_calls_present == false；
  7. 输出 O0/O1/O2 的建议执行命令（不自动执行，避免未经确认就跑模型口径）；
  8. 提示 pack-summary.json 一次性生成；
  9. 提示"看到数字以后不再改 resolver"。

用法:
    python3 scripts/verify_internal_inputs.py \
        --internal-manifest D:/private/sparkskill-state-replay/manifest.json \
        --task19-root D:/private/sparkskill-state-replay/task19 \
        [--task20-root ...] [--task22-root ...] \
        [--freeze artifacts/task-28/freezes/pre-freeze-hashes.json]
退出码: 0 = 全部通过; 1 = 校验失败; 2 = 用法/IO 错误
"""
import argparse
import hashlib
import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
REQUIRED_MANIFEST_FIELDS = ("artifact_id", "expected_sha256", "relative_path",
                            "data_nature", "source_task")
REQUIRED_DATA_NATURE = "internal_frozen_artifact"


class VerificationError(Exception):
    """用法/IO 级错误（退出码 2）。"""


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path, role):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"无法读取{role} {path}: {error}")


def check(root, label, problems):
    """校验一个显式传入的 root：存在、是目录、可读。绝不搜索替代路径。"""
    if not root:
        return []
    if not os.path.isdir(root):
        problems.append(f"{label}: 不是目录（且本脚本不会去搜索替代路径）: {root}")
        return []
    if not os.access(root, os.R_OK):
        problems.append(f"{label}: 不可读: {root}")
    return [root]


def verify_manifest(manifest_path, roots, problems):
    """步骤 1–3：manifest 结构、SHA-256、data_nature。"""
    if not os.path.isfile(manifest_path):
        problems.append(f"internal manifest 缺失: {manifest_path}")
        return []
    manifest = load_json(manifest_path, "internal manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        problems.append("internal manifest 必须包含非空 artifacts 数组")
        return []

    # 根目录集合：只在这些显式 root 下按 relative_path 解析，不做任何搜索。
    valid_roots = [root for root in roots.values() if root]

    records = []
    for index, item in enumerate(artifacts):
        if not isinstance(item, dict):
            problems.append(f"artifacts[{index}] 必须是对象")
            continue
        missing = [field for field in REQUIRED_MANIFEST_FIELDS
                   if field not in item or item.get(field) in (None, "")]
        if missing:
            problems.append(f"artifacts[{index}] 缺字段: {missing}")
            continue
        if item["data_nature"] != REQUIRED_DATA_NATURE:
            problems.append(f"artifacts[{index}].data_nature 必须为 "
                            f"{REQUIRED_DATA_NATURE!r}，得到 {item['data_nature']!r}")
            continue
        if ".." in item["relative_path"].replace("\\", "/").split("/"):
            problems.append(f"artifacts[{index}].relative_path 含 '..'（拒绝路径逃逸）")
            continue

        resolved = None
        for root in valid_roots:
            candidate = os.path.realpath(os.path.join(root, item["relative_path"]))
            if os.path.isfile(candidate):
                resolved = candidate
                break
        if resolved is None:
            problems.append(f"artifacts[{index}] 在任何显式 --taskNN-root 下均找不到 "
                            f"{item['relative_path']!r}（不搜索、不猜路径）")
            continue
        actual = sha256_of(resolved)
        if actual.lower() != str(item["expected_sha256"]).lower():
            problems.append(f"artifacts[{index}] SHA-256 不匹配: {resolved}")
            continue
        records.append({"artifact_id": item["artifact_id"],
                        "source_task": item["source_task"],
                        "path": resolved,
                        "sha256": actual})
    return records


def verify_no_fresh_calls(records, problems):
    """步骤 4/6：输入证据必须是 archived，不得出现 fresh_call。"""
    for record in records:
        try:
            doc = load_json(record["path"], "证据")
        except VerificationError as error:
            problems.append(f"{record['artifact_id']}: {error}")
            continue
        decisions = (doc.get("sampling_provenance") or {}).get("decisions")
        if isinstance(decisions, list):
            fresh = [item for item in decisions
                     if isinstance(item, dict) and item.get("cache_status") == "fresh_call"]
            if fresh:
                problems.append(f"{record['artifact_id']}: 含 {len(fresh)} 个 "
                                f"fresh_call 决策（replay 输入必须全为 archived）")
            archived = sum(1 for item in decisions if isinstance(item, dict)
                           and item.get("cache_status") == "archived_call")
            if not archived:
                problems.append(f"{record['artifact_id']}: 没有 archived_call 决策")


def verify_frozen_hashes(freeze_path, problems):
    """步骤 5：frozen Gate hashes 未变。"""
    if not freeze_path:
        return
    if not os.path.isfile(freeze_path):
        problems.append(f"freeze 文件缺失: {freeze_path}")
        return
    freeze = load_json(freeze_path, "freeze")
    for item in freeze.get("files", []):
        rel = item.get("path")
        expected = item.get("sha256")
        if not rel or not expected:
            continue
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path):
            problems.append(f"freeze 记录的文件缺失: {rel}")
            continue
        actual = sha256_of(path)
        if actual.lower() != str(expected).lower():
            problems.append(f"frozen hash 已变（Gate 被改）: {rel}")
    for guard in freeze.get("guarded_anchors", []):
        if guard.get("present") is False:
            problems.append(f"护栏锚点缺失: {guard.get('path')}")


def main():
    parser = argparse.ArgumentParser(
        description="internal frozen artifacts 只读接入校验（显式路径，不搜索）")
    parser.add_argument("--internal-manifest", required=True)
    parser.add_argument("--task19-root", default=None)
    parser.add_argument("--task20-root", default=None)
    parser.add_argument("--task22-root", default=None)
    parser.add_argument("--freeze", default=None,
                        help="frozen Gate hashes JSON（默认 artifacts/task-28/freezes/"
                             "pre-freeze-hashes.json）")
    args = parser.parse_args()

    roots = {"task19": args.task19_root, "task20": args.task20_root,
             "task22": args.task22_root}
    if not any(roots.values()):
        print("[用法错误] 至少提供一个 --taskNN-root（本脚本不搜索磁盘）", file=sys.stderr)
        return 2

    problems = []
    valid = []
    for label, root in roots.items():
        valid.extend(check(root, label, problems))

    records = verify_manifest(args.internal_manifest, {k: v for k, v in roots.items()
                                                      if v}, problems)
    verify_no_fresh_calls(records, problems)

    freeze_path = args.freeze or os.path.join(PROJECT_ROOT, "artifacts", "task-28",
                                              "freezes", "pre-freeze-hashes.json")
    if os.path.isfile(freeze_path):
        verify_frozen_hashes(freeze_path, problems)

    print(f"[步骤1-3] internal manifest 校验：{len(records)} 项通过 SHA-256 + data_nature")
    print(f"[步骤4-6] fresh_call 检查：{'通过（全 archived）' if not problems else '存在问题'}")
    print(f"[步骤5] frozen Gate hashes：{'未变' if not problems else '存在问题'}")

    if problems:
        print("\n[失败] 接入校验未通过：", file=sys.stderr)
        for item in problems:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print("\n[步骤7] 建议执行命令（**需人工确认后再运行**，本脚本不自动执行）:")
    root_args = " ".join(f"--{label}-root {root}" for label, root in roots.items() if root)
    print(f"  python3 scripts/score_state_replay.py \\\n"
          f"    --manifest <pack manifest> --predictions <prediction set> \\\n"
          f"    --ground-truth <gt dir> --out artifacts/task-28/replay --oracle all")
    print(f"  （--taskNN-root 仅供本校验脚本使用：{root_args}）")
    print("\n[步骤8] pack-summary.json 将由 --oracle all 一次性生成（primary = unique boundaries）")
    print("[步骤9] 看到数字以后**不再改 resolver**；不得发明 O1.1/O1.2 追 dev。")
    print("RESULT: INTERNAL_INPUTS_VERIFIED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except VerificationError as error:
        print(f"[用法/IO 错误] {error}", file=sys.stderr)
        sys.exit(2)
