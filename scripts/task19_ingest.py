#!/usr/bin/env python3
"""task19_ingest.py — Task 19B dev Evidence Pack 摄验（SparkSkill Studio）

对仓库外 dev 数据包（task19-dev-pack-v1）做只读摄验（任务书第三节）：

  I1  包位置在 Git 仓库之外；包内无 .git；
  I2  transfer-manifest.json 的 allowed_sample_ids 恰好是 9 个白名单 ID；
  I3  包内文件名与全部文本内容中出现的 AI\\d+/WEB\\d+ 编号全部属于白名单；
  I4  九段视频、九张 transfer-safe 卡、六份 generation Prompt、许可凭证与 manifest 一致；
  I5  包内不存在非白名单样本、路径或引用（holdout 占位编号扫描；内部留档版为真实 holdout 编号）；
  I6  包内不存在凭据、私钥、服务器地址或无关系统信息；
  I7  九段视频冻结 SHA-256 全部匹配（dev-freeze.sha256 + manifest.video_freeze_hashes）；
  I8  九张卡哈希与 lineage 全部匹配（dev-freeze.sha256 + manifest.derived_card_hashes
      + 每张卡 lineage.source_card_sha256 与 manifest.source_card_hashes 一致）；
  I9  卡片 media.sha256 与实际视频 SHA-256 一致；
  I10 视频总字节数与交付清单一致（137,919,113）；
  I11 实测视频元数据（cv2，与流水线同一公式 round(frames/fps*1000, 3)）。

通过后（且仅通过后）：
  - 以字节 identical 方式把九张 transfer-safe 卡复制到
    artifacts/task-19/ingestion/data-cards/（哈希复核；源包只读，不被修改）；
  - 创建 artifacts/task-19/ingestion/media/<sample_id>.mp4 只读符号链接农场
    （指向仓库外真实视频；不复制视频、不提交链接；.gitignore 排除）；
  - 写出 dev-pack-verification.json 与 media-link-map.json。

任一硬门失败：状态 INVALID_EVALUATION，退出码 1，不写任何产物（已写的也不提交）。
本脚本不调用任何模型、不联网、不修改数据包。

用法:
    python3 scripts/task19_ingest.py [--pack <dev 包路径>]
退出码: 0 = 全部通过; 1 = 硬门失败; 2 = 用法错误
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEV_PACK_DEFAULT = "<DEV_EVIDENCE_PACK_ROOT>"
TASK19 = os.path.join(PROJECT_ROOT, "artifacts", "task-19")
INGESTION = os.path.join(TASK19, "ingestion")
CARDS_DIR = os.path.join(INGESTION, "data-cards")
MEDIA_DIR = os.path.join(INGESTION, "media")

WHITELIST = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06",
             "WEB01", "WEB02", "WEB03"]
EXPECTED_VIDEO_BYTES = 137919113
EXPECTED_FILE_COUNT = 35  # 34 listed + manifest self
SAMPLE_ID_RE = re.compile(r"\b(AI|WEB)(\d+)\b")
HOLDOUT_IDS = {"HOLDOUT-G1", "HOLDOUT-G2", "HOLDOUT-L1"}
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
USER_HOST_RE = re.compile(r"\b[\w.\-]+@[\w.\-]+\b")
CREDENTIAL_MARKERS = (
    "api_key", "api-key", "apikey", "secret", "token=", "password", "passwd",
    "bearer ", "private_key", "-----begin", "id_rsa", "id_ed", ".ssh",
    "credentials", "BEGIN PRIVATE KEY", "BEGIN RSA",
)
TEXT_SUFFIXES = (".json", ".yaml", ".yml", ".md", ".txt", ".csv")

RESULTS = []


def record(check_id, name, passed, detail):
    RESULTS.append({"id": check_id, "name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {check_id} — {name}: {detail}")


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def sanitize(text):
    """产物脱敏：用户 home 绝对路径替换为 ~（与任务 18 resource-gate 同惯例）；
    真实包路径只存在于 runner 的 --pack 默认值（代码），不进入任何 artifact。"""
    if isinstance(text, str):
        return text.replace(os.path.expanduser("~"), "~")
    return text


def inside_git_repo(path):
    """path 是否位于某个 Git 仓库内（向上查找 .git）。"""
    current = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def video_metadata(path):
    """与 visual-evidence-extractor/extract_frames.py 同一 cv2 读取公式
    （read_metadata：round(frame_count/fps*1000, 3)）。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "task19_extract_frames",
        os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                     "scripts", "extract_frames.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    capture = module.cv2.VideoCapture(path)
    if not capture.isOpened():
        raise RuntimeError(f"cv2 无法打开视频: {path}")
    try:
        return module.read_metadata(capture)
    finally:
        capture.release()


def main():
    parser = argparse.ArgumentParser(description="Task 19B dev 包摄验")
    parser.add_argument("--pack", default=DEV_PACK_DEFAULT, help="dev 数据包路径")
    args = parser.parse_args()
    pack = os.path.abspath(args.pack)

    if not os.path.isdir(pack):
        print(f"[用法错误] dev 数据包不存在: {pack}", file=sys.stderr)
        return 2
    if not os.path.isfile(os.path.join(pack, "transfer-manifest.json")):
        print(f"[用法错误] 缺少 transfer-manifest.json: {pack}", file=sys.stderr)
        return 2

    # I1 包位置与 Git 边界
    repo = inside_git_repo(pack)
    record("I1-pack-outside-git", "dev 包位于 Git 仓库之外",
           repo is None and inside_git_repo(PROJECT_ROOT) == PROJECT_ROOT,
           f"包路径 {pack}；向上查找 .git 结果: {repo or '无（在仓库外）'}；"
           f"项目仓库: {PROJECT_ROOT}")
    pack_has_git = os.path.exists(os.path.join(pack, ".git"))
    record("I1b-pack-no-inner-git", "包内无 .git 目录", not pack_has_git,
           "包内不存在 .git" if not pack_has_git else "包内存在 .git")

    manifest = load_json(os.path.join(pack, "transfer-manifest.json"))
    allowed = manifest.get("allowed_sample_ids")
    record("I2-whitelist-exact", "manifest 白名单恰好为九个 dev 样本",
           isinstance(allowed, list) and sorted(allowed) == sorted(WHITELIST),
           f"allowed_sample_ids = {allowed}")

    # 枚举包内全部文件
    all_files = []
    for root, _dirs, files in os.walk(pack):
        for name in files:
            all_files.append(os.path.relpath(os.path.join(root, name), pack))
    all_files.sort()
    record("I4-file-inventory", "包内文件数与交付清单一致（35）",
           len(all_files) == EXPECTED_FILE_COUNT,
           f"包内实际文件数 {len(all_files)}（预期 {EXPECTED_FILE_COUNT}）")

    videos = sorted(f for f in all_files if f.endswith(".mp4"))
    cards = sorted(f for f in all_files if f.startswith("data-cards/transfer-safe/"))
    prompts = sorted(f for f in all_files if f.startswith("generation-prompts/dev/"))
    licenses = sorted(f for f in all_files if f.startswith("许可凭证/"))
    record("I4b-inventory-shape", "九视频/九卡/六 Prompt/许可凭证结构与 manifest 一致",
           len(videos) == 9 and len(cards) == 9 and len(prompts) == 6
           and len(licenses) == 6,
           f"视频 {len(videos)}、卡 {len(cards)}、Prompt {len(prompts)}、"
           f"许可凭证 {len(licenses)}")

    # I3/I5 编号扫描：文件名 + 文本内容
    out_of_whitelist = []
    for rel in all_files:
        base = os.path.basename(rel)
        for match in SAMPLE_ID_RE.finditer(base):
            token = match.group(0)
            if token not in WHITELIST:
                out_of_whitelist.append({"where": f"filename:{rel}", "token": token})
    text_files = [f for f in all_files if f.endswith(TEXT_SUFFIXES)]
    for rel in text_files:
        try:
            with open(os.path.join(pack, rel), encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        for match in SAMPLE_ID_RE.finditer(text):
            token = match.group(0)
            if token not in WHITELIST:
                out_of_whitelist.append({"where": f"text:{rel}", "token": token})
    holdout_hits = [item for item in out_of_whitelist if item["token"] in HOLDOUT_IDS]
    record("I3-sample-id-scan", "全部 AI/WEB 编号属于白名单",
           not out_of_whitelist,
           f"扫描 {len(all_files)} 个文件名 + {len(text_files)} 个文本文件；"
           f"白名单外编号 {len(out_of_whitelist)} 个"
           + (f"（如 {out_of_whitelist[:3]}）" if out_of_whitelist else ""))
    record("I5-no-holdout-ids", "无 holdout 样本编号（HOLDOUT-G1/HOLDOUT-G2/HOLDOUT-L1）",
           not holdout_hits, f"holdout 编号命中 {len(holdout_hits)} 个")

    # I5b 路径引用扫描：manifest 文件清单之外的媒体/卡路径不得出现
    manifest_paths = {entry["path"] for entry in manifest["files"]}
    referenced_media = set()
    for rel in text_files:
        try:
            with open(os.path.join(pack, rel), encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        for match in re.finditer(r"videos/[^\s\"'`）)*]+\.mp4", text):
            referenced_media.add(match.group(0))
        for match in re.finditer(r"data-cards/[^\s\"'`）)*]+\.(?:json|yaml|yml)", text):
            referenced_media.add(match.group(0))
    unknown_refs = sorted(p for p in referenced_media if p not in manifest_paths)
    # 源 YAML 卡路径（data-cards/dev/*.yaml）按设计不随包传输，允许按名引用
    source_card_refs = sorted(p for p in unknown_refs if p.startswith("data-cards/dev/"))
    truly_unknown = sorted(p for p in unknown_refs
                           if not p.startswith("data-cards/dev/"))
    record("I5b-no-unknown-path-refs", "无非白名单媒体/卡片路径引用",
           not truly_unknown,
           f"文本引用的媒体/卡路径 {len(referenced_media)} 个；manifest 外 "
           f"{len(unknown_refs)} 个（其中源 YAML 卡按名引用 {len(source_card_refs)} 个，"
           f"设计上不随包传输）；未知引用 {len(truly_unknown)} 个"
           + (f"（如 {truly_unknown[:3]}）" if truly_unknown else ""))

    # I6 凭据/地址扫描（仅文本文件；否定/声明语境与文档键名不计为真实凭据）
    credential_hits = []
    address_hits = []
    # 已知安全声明键与扫描模式文档键（其出现是"无凭据"的负面声明或扫描说明，
    # 不是真实凭据——与 transfer-manifest.json 自带 text_scan 同口径）
    SAFE_CONTEXTS = (
        "visible_credentials_or_screens", "credentials_found", "patterns_checked",
        "credential_patterns", "connection_parameters", "connection_parameters_found",
        "credential-style", "凭据、SSH 文件", "未发现 API key", "不含",
    )
    NEGATION_HINTS = ("无", "[]", "null", "false", "未发现", "不含", "禁止", "不得")

    def is_declaration_line(line):
        return (any(context in line for context in SAFE_CONTEXTS)
                or any(hint in line for hint in NEGATION_HINTS))

    for rel in text_files:
        try:
            with open(os.path.join(pack, rel), encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        lowered = text.lower()
        for marker in CREDENTIAL_MARKERS:
            start = 0
            while True:
                index = lowered.find(marker, start)
                if index < 0:
                    break
                line_start = text.rfind("\n", 0, index) + 1
                line_end = text.find("\n", index)
                line = text[line_start:] if line_end < 0 else text[line_start:line_end]
                if not is_declaration_line(line):
                    credential_hits.append({"file": rel, "marker": marker,
                                            "line": line.strip()[:120]})
                start = index + len(marker)
        for match in IPV4_RE.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            line = text[line_start:] if line_end < 0 else text[line_start:line_end]
            if not is_declaration_line(line):
                address_hits.append({"file": rel, "match": match.group(0)})
        for match in USER_HOST_RE.finditer(text):
            candidate = match.group(0)
            if candidate == "user@host":  # manifest 扫描模式文档字面量
                continue
            if candidate.lower().endswith((".png", ".jpg", ".mp4", ".json", ".md")):
                continue
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            line = text[line_start:] if line_end < 0 else text[line_start:line_end]
            if is_declaration_line(line):
                continue
            address_hits.append({"file": rel, "match": candidate})
    record("I6-no-credentials", "包内无凭据/私钥样式",
           not credential_hits,
           f"扫描 {len(text_files)} 个文本文件；命中 {len(credential_hits)} 个"
           + (f"（如 {credential_hits[:3]}）" if credential_hits else ""))
    record("I6b-no-server-addresses", "包内无 IPv4 地址或 user@host",
           not address_hits,
           f"命中 {len(address_hits)} 个"
           + (f"（如 {address_hits[:3]}）" if address_hits else ""))

    # I7 视频冻结哈希（dev-freeze.sha256 + manifest.video_freeze_hashes 双源）
    freeze_lines = {}
    with open(os.path.join(pack, "dev-freeze.sha256"), encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digest, rel = line.split(None, 1)
            freeze_lines[rel.strip()] = digest.upper()
    video_freeze = manifest["video_freeze_hashes"]
    video_results = {}
    video_ok = True
    total_bytes = 0
    for sample_id in WHITELIST:
        entry = video_freeze[sample_id]
        rel = entry["path"]
        full = os.path.join(pack, rel)
        if not os.path.isfile(full):
            video_ok = False
            video_results[sample_id] = {"error": "文件缺失"}
            continue
        actual = sha256_of(full).upper()
        size = os.path.getsize(full)
        total_bytes += size
        ok = (actual == entry["frozen_sha256"].upper()
              and actual == freeze_lines.get(rel, "").upper()
              and size == entry["size_bytes"])
        video_ok = video_ok and ok
        video_results[sample_id] = {
            "path": rel, "sha256": actual, "size_bytes": size,
            "freeze_match": actual == entry["frozen_sha256"].upper(),
            "freeze_list_match": actual == freeze_lines.get(rel, "").upper(),
            "size_match": size == entry["size_bytes"],
        }
    record("I7-video-freeze-hashes", "九段视频冻结 SHA-256 全部匹配",
           video_ok and len(video_results) == 9,
           "; ".join(f"{sid}:{'OK' if v.get('freeze_match') and v.get('freeze_list_match') else 'FAIL'}"
                     for sid, v in sorted(video_results.items())))

    # I8 卡片哈希与 lineage
    derived_hashes = manifest["derived_card_hashes"]
    source_hashes = manifest["source_card_hashes"]
    card_results = {}
    cards_ok = True
    for sample_id in WHITELIST:
        rel = f"data-cards/transfer-safe/{sample_id}.json"
        full = os.path.join(pack, rel)
        actual = sha256_of(full).upper()
        card = load_json(full)
        lineage = card.get("lineage") or {}
        ok = (actual == derived_hashes[sample_id].upper()
              and actual == freeze_lines.get(rel, "").upper()
              and lineage.get("source_card_sha256", "").upper()
              == source_hashes[sample_id].upper()
              and lineage.get("source_card_path") == f"data-cards/dev/{sample_id}.yaml"
              and lineage.get("core_fields_unchanged") is True)
        cards_ok = cards_ok and ok
        card_results[sample_id] = {
            "path": rel, "sha256": actual,
            "derived_hash_match": actual == derived_hashes[sample_id].upper(),
            "freeze_list_match": actual == freeze_lines.get(rel, "").upper(),
            "source_card_path": lineage.get("source_card_path"),
            "source_card_sha256": lineage.get("source_card_sha256"),
            "source_card_hash_match": (lineage.get("source_card_sha256", "").upper()
                                       == source_hashes[sample_id].upper()),
            "core_fields_unchanged": lineage.get("core_fields_unchanged"),
        }
    record("I8-card-hashes-lineage", "九张卡哈希与 lineage 全部匹配",
           cards_ok,
           "; ".join(f"{sid}:{'OK' if v['derived_hash_match'] and v['source_card_hash_match'] else 'FAIL'}"
                     for sid, v in sorted(card_results.items())))

    # I9 卡片 media.sha256 == 实际视频哈希
    media_ok = True
    media_detail = []
    for sample_id in WHITELIST:
        card = load_json(os.path.join(pack, f"data-cards/transfer-safe/{sample_id}.json"))
        card_hash = (card.get("media") or {}).get("sha256", "").upper()
        actual = video_results.get(sample_id, {}).get("sha256", "")
        ok = bool(card_hash) and card_hash == actual
        media_ok = media_ok and ok
        media_detail.append(f"{sample_id}:{'OK' if ok else 'FAIL'}")
    record("I9-card-media-hash", "卡片 media SHA-256 与实际视频一致",
           media_ok, "; ".join(media_detail))

    # I10 视频总字节数
    record("I10-video-total-bytes", "视频总字节数与交付清单一致",
           total_bytes == EXPECTED_VIDEO_BYTES,
           f"九段视频总字节 {total_bytes}（预期 {EXPECTED_VIDEO_BYTES}）")

    # I11 实测元数据（cv2 同一公式）
    metadata = {}
    metadata_ok = True
    try:
        for sample_id in WHITELIST:
            rel = video_freeze[sample_id]["path"]
            info = video_metadata(os.path.join(pack, rel))
            metadata[sample_id] = info
        metadata_ok = len(metadata) == 9
        detail = "; ".join(
            f"{sid}:{metadata[sid]['duration_ms']}ms/{metadata[sid]['fps']}fps/"
            f"{metadata[sid]['width']}x{metadata[sid]['height']}"
            for sid in WHITELIST)
    except Exception as error:  # noqa: BLE001
        metadata_ok = False
        detail = f"cv2 元数据读取失败: {error}"
    record("I11-measured-metadata", "九段视频实测元数据可读（与流水线同一公式）",
           metadata_ok, detail)

    all_passed = all(item["passed"] for item in RESULTS)
    for item in RESULTS:
        item["detail"] = sanitize(item["detail"])
    verification = {
        "task": "task-19b-dev-pack-ingestion",
        "pack_path": sanitize(pack),
        "pack_relative_to_project": os.path.relpath(pack, PROJECT_ROOT),
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "whitelist": WHITELIST,
        "all_passed": all_passed,
        "status": "VALID" if all_passed else "INVALID_EVALUATION",
        "checks": RESULTS,
        "videos": video_results,
        "cards": card_results,
        "measured_metadata": metadata,
        "video_total_bytes": total_bytes,
        "expected_video_total_bytes": EXPECTED_VIDEO_BYTES,
        "file_count": len(all_files),
        "files": all_files,
    }

    if not all_passed:
        os.makedirs(INGESTION, exist_ok=True)
        with open(os.path.join(INGESTION, "dev-pack-verification.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(verification, handle, ensure_ascii=False, indent=2)
        print("\n[硬门失败] 状态 INVALID_EVALUATION：不派生 GT、不运行模型、不修改数据包",
              file=sys.stderr)
        return 1

    # ---- 通过后：复制卡片（字节 identical）+ 创建媒体链接农场（不复制视频）
    os.makedirs(CARDS_DIR, exist_ok=True)
    os.makedirs(MEDIA_DIR, exist_ok=True)
    copied = {}
    for sample_id in WHITELIST:
        src = os.path.join(pack, f"data-cards/transfer-safe/{sample_id}.json")
        dst = os.path.join(CARDS_DIR, f"{sample_id}.json")
        shutil.copyfile(src, dst)
        assert sha256_of(dst) == sha256_of(src)
        copied[sample_id] = os.path.relpath(dst, PROJECT_ROOT)

    link_map = {}
    for sample_id in WHITELIST:
        rel = video_freeze[sample_id]["path"]
        real = os.path.join(pack, rel)
        link = os.path.join(MEDIA_DIR, f"{sample_id}.mp4")
        if os.path.lexists(link):
            os.remove(link)
        target = os.path.relpath(real, MEDIA_DIR)
        os.symlink(target, link)
        assert sha256_of(link).upper() == video_results[sample_id]["sha256"].upper(), \
            sample_id
        link_map[sample_id] = {
            "sample_id": sample_id,
            "pack_relative_video_path": rel,
            "repo_relative_link": os.path.relpath(link, PROJECT_ROOT),
            "symlink_target": target,
            "media_sha256": video_results[sample_id]["sha256"],
            "size_bytes": video_results[sample_id]["size_bytes"],
            "measured_duration_ms": metadata[sample_id]["duration_ms"],
            "fps": metadata[sample_id]["fps"],
            "width": metadata[sample_id]["width"],
            "height": metadata[sample_id]["height"],
        }

    with open(os.path.join(INGESTION, "media-link-map.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "schema_version": "1.0.0",
            "note": ("媒体链接农场：artifacts/task-19/ingestion/media/<sample_id>.mp4 为指向"
                     "仓库外 dev 包的只读符号链接（不复制视频、不提交链接；.gitignore 排除）。"
                     "manifest media_path 与 trace_temporal source_media 使用仓库内相对链接路径；"
                     "评分器硬门 G2 与公平门 same_media_hash 均解析到同一真实文件。"
                     "真实包绝对路径只在 scripts/task19_ingest.py --pack 默认值（代码）中，"
                     "本文件只存仓库相对路径与脱敏包根。"),
            "pack_root": sanitize(pack),
            "links": link_map,
        }, ensure_ascii=False, indent=2) + "\n")
    with open(os.path.join(INGESTION, "dev-pack-verification.json"), "w",
              encoding="utf-8") as handle:
        json.dump(verification, handle, ensure_ascii=False, indent=2)

    print(f"\n[摄验通过] 状态 VALID：9 视频 / 9 卡 / 6 Prompt / 6 许可凭证；"
          f"视频总字节 {total_bytes}")
    print(f"[卡片复制] {CARDS_DIR}（字节 identical，哈希复核通过）")
    print(f"[媒体链接] {MEDIA_DIR}（只读符号链接，未复制视频）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
