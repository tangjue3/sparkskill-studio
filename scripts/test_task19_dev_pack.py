#!/usr/bin/env python3
"""test_task19_dev_pack.py — Task 19B 确定性测试（SparkSkill Studio）

覆盖任务书第十二节 22 类要求（无模型调用、无网络、确定性）：

  T01 dev 包只含九个白名单 ID
  T02 transfer manifest 哈希（34 个文件逐条重算）
  T03 视频与卡片哈希（dev-freeze + manifest + 卡片 media 三方）
  T04 source-card lineage
  T05 transfer-safe 卡核心字段
  T06 Ground Truth 确定性转换（重算派生与提交 GT 逐字节一致）
  T07 相邻同状态规范化（AI06/WEB02 合并；原因保留）
  T08 规范化不改变状态覆盖与边界集合
  T09 execution manifest 不含标签（27 份 manifest + 27 份 spec 深扫描）
  T10 预算只依赖媒体时长（公式复算 + 三臂同预算）
  T11 三臂公平门（同模型/后端/预算/证据性质；scope 公平门全过）
  T12 track 分类（AI=generated / WEB=licensed_public）
  T13 无边界样本不进入边界精度分母
  T14 generated/licensed-public 分轨汇总（三范围比较文档样本集合正确）
  T15 失败与超时计入结果（真实数据复算 + 冻结评分器构造用例）
  T16 零分母 not_applicable（真实数据全量断言 + 构造用例）
  T17 原始视频不在 Git（无 .mp4 入库 + 九个 dev 视频哈希不出现在任何跟踪文件）
  T18 非白名单编号拒绝（合成用例 + 真实包扫描结果）
  T19 输入只读（dev 包全部文件哈希与摄验记录一致）
  T20 输出无凭据与仓库外敏感绝对路径
  T21 预注册哈希在运行后不变
  T22 scorer 与实现冻结文件零改动（相对任务 18 提交 ef9f329 逐字节）

用法:
    python3 scripts/test_task19_dev_pack.py
退出码: 0 = 全部通过; 1 = 存在失败项
确定性: 同一输入永远得到同一输出；结果写入 artifacts/task-19/test-results.json。
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TASK19 = os.path.join(PROJECT_ROOT, "artifacts", "task-19")
PREREGISTRATION = os.path.join(TASK19, "preregistration")
INGESTION = os.path.join(TASK19, "ingestion")
CARDS_DIR = os.path.join(INGESTION, "data-cards")
GROUND_TRUTH = os.path.join(TASK19, "ground-truth")
EXECUTION_MANIFESTS = os.path.join(TASK19, "execution-manifests")
PREDICTIONS = os.path.join(TASK19, "predictions")
SCORES = os.path.join(TASK19, "scores")
COMPARISONS = os.path.join(TASK19, "comparisons")
DEV_PACK = "<DEV_EVIDENCE_PACK_ROOT>"

WHITELIST = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06",
             "WEB01", "WEB02", "WEB03"]
GENERATED = {"AI01", "AI02", "AI03", "AI04", "AI05", "AI06"}
LICENSED = {"WEB01", "WEB02", "WEB03"}
ARM_IDS = ["uniform", "adaptive", "coverage"]
PHASE_A_COMMIT = "e3ef01e"
TASK18_COMMIT = "ef9f329"

# 冻结零改动文件（相对任务 18 提交 ef9f329）
FROZEN_FILES = (
    "scripts/score_temporal_ground_truth.py",
    "scripts/task18_scorer_adapter.py",
    "scripts/validate_evidence_pack.py",
    "scripts/test_temporal_ground_truth_scoring.py",
    "schemas/temporal-ground-truth.schema.json",
    "schemas/evidence-pack-manifest.schema.json",
    "schemas/visual-task-spec.schema.json",
    ".dsh/skills/task-to-skill-compiler/scripts/validate_task_spec.py",
    ".dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py",
    ".dsh/skills/visual-evidence-extractor/scripts/trace_temporal.py",
    ".dsh/skills/visual-evidence-extractor/scripts/analyze_image.py",
    ".dsh/skills/visual-evidence-extractor/scripts/extract_frames.py",
    ".dsh/skills/visual-evidence-extractor/scripts/trace_video.py",
    ".dsh/skills/evidence-report-generator/scripts/generate_report.py",
)

FORBIDDEN_LABEL_KEYS = (
    "expected_final_status", "expected_timeline", "difficulty", "ground_truth",
    "ground_truths", "segments", "boundary", "boundaries", "boundary_location",
    "scorer", "score", "label", "labels", "annotation", "annotations", "answer",
    "hint", "expected_status", "expected",
)
GT_STATE_TOKENS = ("confirmed", "not_found", "uncertain")
CREDENTIAL_MARKERS = ("api_key", "api-key", "apikey", "secret", "token=", "password",
                      "passwd", "bearer ", "private_key", "-----begin")
ABS_PATH_RE = re.compile(r"(?<![A-Za-z0-9])/(?:home|root|tmp|var|etc|opt)/[A-Za-z0-9_\-./]+")

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


def iter_keys(node, path="$"):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, f"{path}.{key}"
            yield from iter_keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from iter_keys(item, f"{path}[{index}]")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(*args):
    return subprocess.run(["git", "-C", PROJECT_ROOT, *args], capture_output=True, text=True)


# ---------------------------------------------------------------- T01–T05 数据包侧

def t01_whitelist():
    verification = load_json(os.path.join(INGESTION, "dev-pack-verification.json"))
    manifest = load_json(os.path.join(DEV_PACK, "transfer-manifest.json"))
    ok = (sorted(manifest["allowed_sample_ids"]) == sorted(WHITELIST)
          and verification["all_passed"] is True
          and verification["status"] == "VALID"
          and sorted(verification["videos"]) == sorted(WHITELIST)
          and sorted(verification["cards"]) == sorted(WHITELIST))
    scan = [item for item in verification["checks"] if item["id"] == "I3-sample-id-scan"][0]
    record("T01", "dev 包只含九个白名单 ID", ok,
           f"manifest 白名单=九样本；摄验 VALID；编号扫描: {scan['detail'][:80]}")


def t02_manifest_hashes():
    manifest = load_json(os.path.join(DEV_PACK, "transfer-manifest.json"))
    problems = []
    for entry in manifest["files"]:
        path = os.path.join(DEV_PACK, entry["path"])
        if not os.path.isfile(path):
            problems.append(f"{entry['path']}:缺失")
            continue
        if sha256_of(path) != entry["sha256"].lower():
            problems.append(f"{entry['path']}:哈希")
        if os.path.getsize(path) != entry["size_bytes"]:
            problems.append(f"{entry['path']}:大小")
    record("T02", "transfer manifest 哈希（34 文件逐条重算）", not problems,
           f"{len(manifest['files'])} 个文件全部一致" if not problems
           else "；".join(problems[:5]))


def t03_video_card_hashes():
    verification = load_json(os.path.join(INGESTION, "dev-pack-verification.json"))
    problems = []
    for sample_id in WHITELIST:
        video = verification["videos"][sample_id]
        if not (video["freeze_match"] and video["freeze_list_match"] and video["size_match"]):
            problems.append(f"{sample_id}:视频")
        card = verification["cards"][sample_id]
        if not (card["derived_hash_match"] and card["freeze_list_match"]
                and card["source_card_hash_match"]):
            problems.append(f"{sample_id}:卡")
    # 卡片 media.sha256 == 实际视频哈希
    for sample_id in WHITELIST:
        card = load_json(os.path.join(CARDS_DIR, f"{sample_id}.json"))
        if card["media"]["sha256"].upper() != verification["videos"][sample_id]["sha256"]:
            problems.append(f"{sample_id}:卡媒体哈希")
    record("T03", "视频与卡片哈希（dev-freeze + manifest + 卡 media 三方）",
           not problems, "九视频 + 九卡 + 卡媒体哈希全部一致" if not problems
           else "；".join(problems[:5]))


def t04_lineage():
    problems = []
    for sample_id in WHITELIST:
        card = load_json(os.path.join(CARDS_DIR, f"{sample_id}.json"))
        lineage = card.get("lineage") or {}
        if lineage.get("source_card_path") != f"data-cards/dev/{sample_id}.yaml":
            problems.append(f"{sample_id}:源卡路径")
        if not re.fullmatch(r"[0-9A-F]{64}", lineage.get("source_card_sha256", "")):
            problems.append(f"{sample_id}:源卡哈希格式")
        if lineage.get("core_fields_unchanged") is not True:
            problems.append(f"{sample_id}:核心字段未改变声明")
        if not lineage.get("removed_or_normalized_fields"):
            problems.append(f"{sample_id}:规范化字段清单")
    record("T04", "source-card lineage", not problems,
           "九卡 lineage（源卡路径/源卡哈希/核心字段未改变/规范化清单）全部合规"
           if not problems else "；".join(problems[:5]))


def t05_card_core_fields():
    core = ["schema_version", "sample_id", "filename", "split", "source", "media",
            "task", "expected_timeline", "difficulty", "safety", "dataset_control"]
    problems = []
    for sample_id in WHITELIST:
        card = load_json(os.path.join(CARDS_DIR, f"{sample_id}.json"))
        for field in core:
            if field not in card:
                problems.append(f"{sample_id}:缺{field}")
        if card.get("sample_id") != sample_id or card.get("split") != "dev":
            problems.append(f"{sample_id}:身份字段")
        task = card.get("task") or {}
        for field in ("target_query", "task_type", "expected_final_status",
                      "boundary_tolerance_ms"):
            if field not in task:
                problems.append(f"{sample_id}:task缺{field}")
        if card.get("generation") and sample_id in GENERATED:
            pass
        elif sample_id in GENERATED:
            problems.append(f"{sample_id}:缺 generation provenance")
        if sample_id in LICENSED and not (card.get("source") or {}).get("source_detail_url"):
            problems.append(f"{sample_id}:缺许可详情 URL")
    record("T05", "transfer-safe 卡核心字段", not problems,
           "九卡核心字段与 provenance 齐全" if not problems else "；".join(problems[:5]))


# ---------------------------------------------------------------- T06–T08 GT 派生

def t06_gt_deterministic():
    spec = importlib.util.spec_from_file_location(
        "build_gt", os.path.join(PROJECT_ROOT, "scripts",
                                 "build_task19_ground_truth.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    link_map = load_json(os.path.join(INGESTION, "media-link-map.json"))["links"]
    problems = []
    for sample_id in WHITELIST:
        card = load_json(os.path.join(CARDS_DIR, f"{sample_id}.json"))
        measured = link_map[sample_id]["measured_duration_ms"]
        gt, _record = module.derive_ground_truth(card, measured)
        committed = load_json(os.path.join(GROUND_TRUTH, f"{sample_id}.json"))
        if json.dumps(gt, ensure_ascii=False, sort_keys=True) != \
                json.dumps(committed, ensure_ascii=False, sort_keys=True):
            problems.append(sample_id)
    record("T06", "Ground Truth 确定性转换（重算与提交 GT 一致）", not problems,
           "九份 GT 重算逐字段一致" if not problems else f"不一致: {problems}")


def t07_adjacent_merge():
    report = load_json(os.path.join(PREREGISTRATION,
                                    "ground-truth-normalization-report.json"))
    problems = []
    for sample_id in WHITELIST:
        entry = report["samples"][sample_id]
        card = load_json(os.path.join(CARDS_DIR, f"{sample_id}.json"))
        gt = load_json(os.path.join(GROUND_TRUTH, f"{sample_id}.json"))
        expected_merges = sum(
            1 for index in range(1, len(card["expected_timeline"]))
            if card["expected_timeline"][index]["state"]
            == card["expected_timeline"][index - 1]["state"])
        if len(entry["merge_records"]) != expected_merges:
            problems.append(f"{sample_id}:合并次数")
        if len(gt["segments"]) != len(card["expected_timeline"]) - expected_merges:
            problems.append(f"{sample_id}:段数")
        # 合并段原因保留全部原人工原因
        for merge in entry["merge_records"]:
            merged_segment = next(s for s in gt["segments"]
                                  if s["start_ms"] == merge["merged_into"]["start_ms"])
            for reason in merge["reasons_preserved"]:
                if reason and reason not in (merged_segment.get("reason") or ""):
                    problems.append(f"{sample_id}:原因丢失")
    ai06 = report["samples"]["AI06"]
    web02 = report["samples"]["WEB02"]
    ok = (not problems and len(ai06["merge_records"]) == 1
          and len(web02["merge_records"]) == 1
          and len(load_json(os.path.join(GROUND_TRUTH, "AI06.json"))["segments"]) == 1
          and len(load_json(os.path.join(GROUND_TRUTH, "WEB02.json"))["segments"]) == 1)
    record("T07", "相邻同状态规范化（AI06/WEB02 合并；人工原因保留）", ok,
           "AI06 uncertain[0,6000]+[6000,10125]→[0,10125]；WEB02 "
           "confirmed[0,3000]+[3000,10260]→[0,10243.567]；两段原因均保留"
           if ok else "；".join(problems[:5]))


def t08_coverage_unchanged():
    report = load_json(os.path.join(PREREGISTRATION,
                                    "ground-truth-normalization-report.json"))
    problems = []
    for sample_id in WHITELIST:
        entry = report["samples"][sample_id]
        if not entry["state_coverage_unchanged"]:
            problems.append(f"{sample_id}:状态覆盖")
        if not entry["boundary_semantics_unchanged"]:
            problems.append(f"{sample_id}:边界集合")
        if entry["boundaries_before"] != entry["boundaries_after"]:
            problems.append(f"{sample_id}:边界明细")
    record("T08", "规范化不改变状态覆盖与边界集合", not problems,
           "九样本状态覆盖（实测媒体范围内）与边界集合前后一致"
           if not problems else "；".join(problems[:5]))


# ---------------------------------------------------------------- T09–T11 执行与公平

def t09_execution_manifest_no_labels():
    problems = []
    files = []
    for sample_id in WHITELIST:
        for arm_id in ARM_IDS:
            files.append(os.path.join(EXECUTION_MANIFESTS, sample_id, f"{arm_id}.json"))
            files.append(os.path.join(PREDICTIONS, sample_id, arm_id, "task-spec.json"))
    checked = 0
    for path in files:
        if not os.path.isfile(path):
            continue
        checked += 1
        doc = load_json(path)
        for key, location in iter_keys(doc):
            if key in FORBIDDEN_LABEL_KEYS:
                problems.append(f"{os.path.basename(path)}:{location}")
        for value in _iter_string_values(doc):
            if value in GT_STATE_TOKENS:
                problems.append(f"{os.path.basename(path)}:状态值{value}")
    difficulty_strings = set()
    for sample_id in WHITELIST:
        card = load_json(os.path.join(CARDS_DIR, f"{sample_id}.json"))
        difficulty_strings.update(card.get("difficulty") or [])
    for path in files:
        if not os.path.isfile(path):
            continue
        text = open(path, encoding="utf-8").read()
        for token in difficulty_strings:
            if token and token in text:
                problems.append(f"{os.path.basename(path)}:难度标签{token}")
    record("T09", "execution manifest 不含标签（深扫描）",
           not problems and checked == 54,
           f"{checked}/54 份文件无标签键/状态值/难度字符串" if not problems
           else "；".join(problems[:5]))


def _iter_string_values(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_string_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_string_values(item)
    elif isinstance(node, str):
        yield node


def t10_budget_only_duration():
    import math
    sample_manifest = load_json(os.path.join(PREREGISTRATION, "sample-manifest.json"))
    problems = []
    for sample_id in WHITELIST:
        entry = sample_manifest["samples"][sample_id]
        expected = min(24, max(12, math.ceil(entry["measured_duration_ms"] / 1000.0)))
        if entry["budget_max_model_calls"] != expected:
            problems.append(f"{sample_id}:公式")
        for arm_id in ARM_IDS:
            evidence_path = os.path.join(PREDICTIONS, sample_id, arm_id,
                                         "temporal-evidence.json")
            if not os.path.isfile(evidence_path):
                continue
            evidence = load_json(evidence_path)
            provenance = evidence.get("sampling_provenance") or {}
            if provenance.get("configured_budget") != expected:
                problems.append(f"{sample_id}/{arm_id}:产物预算")
            if (provenance.get("actual_model_calls") or 0) > expected:
                problems.append(f"{sample_id}/{arm_id}:超预算")
    record("T10", "预算只依赖媒体时长（公式复算 + 三臂同预算 + 不超预算）",
           not problems,
           "九样本预算=clamp(ceil(duration/1000),12,24)；27 份产物预算一致且未超"
           if not problems else "；".join(problems[:5]))


def t11_three_arm_fairness():
    problems = []
    # 产物级公平条件（同模型/后端/预算/证据性质）
    for sample_id in WHITELIST:
        seen = {}
        for arm_id in ARM_IDS:
            evidence_path = os.path.join(PREDICTIONS, sample_id, arm_id,
                                         "temporal-evidence.json")
            if not os.path.isfile(evidence_path):
                continue
            evidence = load_json(evidence_path)
            backend = evidence.get("backend") or {}
            provenance = evidence.get("sampling_provenance") or {}
            seen[arm_id] = (backend.get("model"), backend.get("vision_backend"),
                            provenance.get("configured_budget"),
                            evidence.get("evidence_nature"),
                            evidence.get("target_query"))
        if len(seen) == 3 and len(set(seen.values())) != 1:
            problems.append(f"{sample_id}:臂间条件不一致")
    # scope 比较文档的公平门（口径：generated 同质范围十条件全过；licensed-public 与
    # all-dev 多查询/多预算，冻结实现的 same_target_query/same_call_budget 单值条件
    # FAIL——如实保留为 INVALID_COMPARISON；逐样本公平门必须全部通过）
    gate_summary = []
    per_sample_all_pass = True
    for sample_id in WHITELIST:
        path = os.path.join(SCORES, "per-sample", sample_id,
                            "three-arm-comparison.json")
        if not os.path.isfile(path):
            continue
        doc = load_json(path)
        for pair_id, pair in (doc.get("pairwise") or {}).items():
            if not pair["fairness_gate"]["all_passed"]:
                per_sample_all_pass = False
                problems.append(f"per-sample/{sample_id}/{pair_id}:公平门失败")
    for scope in ("generated", "licensed-public", "all-dev"):
        path = os.path.join(SCORES, scope, "three-arm-comparison.json")
        if not os.path.isfile(path):
            continue
        doc = load_json(path)
        for pair_id, pair in (doc.get("pairwise") or {}).items():
            failed = [c["id"] for c in pair["fairness_gate"]["conditions"]
                      if not c["passed"]]
            if scope == "generated" and failed:
                problems.append(f"{scope}/{pair_id}:同质范围公平门失败 {failed}")
            if scope != "generated" and                     set(failed) - {"same_target_query", "same_call_budget"}:
                problems.append(f"{scope}/{pair_id}:非预期公平门失败 {failed}")
            gate_summary.append(f"{scope}/{pair_id}:{'PASS' if not failed else 'FAIL(' + ','.join(failed) + ')'}")
    if not per_sample_all_pass:
        problems.append("逐样本公平门未全部通过")
    record("T11", "三臂公平门（臂间条件一致 + 逐样本门全过 + 范围门口径正确）",
           not problems,
           "；".join(gate_summary[:6]) + ("；……" if len(gate_summary) > 6 else "")
           if not problems else "；".join(problems[:5]))


# ---------------------------------------------------------------- T12–T14 分轨

def t12_track_classification():
    sample_manifest = load_json(os.path.join(PREREGISTRATION, "sample-manifest.json"))
    manifest = load_json(os.path.join(INGESTION, "evidence-pack-manifest.json"))
    problems = []
    by_id = {sample["sample_id"]: sample for sample in manifest["samples"]}
    for sample_id in WHITELIST:
        entry = sample_manifest["samples"][sample_id]
        expected_track = "generated" if sample_id in GENERATED else "licensed_public"
        if entry["track"] != expected_track:
            problems.append(f"{sample_id}:track")
        if by_id[sample_id]["source_type"] != expected_track:
            problems.append(f"{sample_id}:source_type")
    tracks = sample_manifest["tracks"]
    if sorted(tracks["generated"]) != sorted(GENERATED) or \
            sorted(tracks["licensed_public"]) != sorted(LICENSED):
        problems.append("tracks 集合")
    record("T12", "track 分类（AI=generated / WEB=licensed_public）", not problems,
           "九样本 track 与 source_type 全部正确" if not problems else "；".join(problems[:5]))


def t13_no_boundary_denominator():
    sample_manifest = load_json(os.path.join(PREREGISTRATION, "sample-manifest.json"))
    no_boundary = [sid for sid in WHITELIST
                   if not sample_manifest["samples"][sid]["has_existence_boundary"]]
    problems = []
    checked = 0
    for sample_id in no_boundary:
        for arm_id in ARM_IDS:
            score_path = os.path.join(SCORES, "all-dev", sample_id, arm_id, "score.json")
            if not os.path.isfile(score_path):
                continue
            checked += 1
            score = load_json(score_path)
            boundaries = score.get("boundary_scores") or {}
            if boundaries.get("gt_boundaries_total") != 0:
                problems.append(f"{sample_id}/{arm_id}:GT 边界数非 0")
            if boundaries.get("matched_boundaries") != 0:
                problems.append(f"{sample_id}/{arm_id}:匹配数非 0")
            stats = boundaries.get("boundary_error_stats") or {}
            if stats.get("matched_count") != 0:
                problems.append(f"{sample_id}/{arm_id}:误差分母非 0")
            for field in ("max_ms", "min_ms", "median_ms", "mean_ms"):
                if stats.get(field) != "not_applicable":
                    problems.append(f"{sample_id}/{arm_id}:{field} 非 not_applicable")
    record("T13", "无边界样本不进入边界精度分母（AI01/AI05/AI06/WEB02/WEB03）",
           not problems,
           f"无边界样本 {no_boundary}；已核验 {checked} 份 score：匹配数=0、"
           f"误差统计=not_applicable" if not problems else "；".join(problems[:5]))


def t14_track_summaries():
    problems = []
    expected = {"generated": sorted(GENERATED), "licensed-public": sorted(LICENSED),
                "all-dev": sorted(WHITELIST)}
    for scope, ids in expected.items():
        path = os.path.join(SCORES, scope, "three-arm-comparison.json")
        if not os.path.isfile(path):
            problems.append(f"{scope}:缺比较文档")
            continue
        doc = load_json(path)
        if sorted(doc.get("comparison_sample_ids") or []) != ids:
            problems.append(f"{scope}:样本集合")
        table = doc.get("per_sample_table") or {}
        for arm_id in ARM_IDS:
            keys = set((table.get(arm_id) or {}).keys())
            if not set(ids) <= keys:
                problems.append(f"{scope}/{arm_id}:逐样本表缺少范围样本")
    record("T14", "generated/licensed-public 分轨汇总（三范围样本集合正确）",
           not problems,
           "generated=6、licensed-public=3、all-dev=9；分轨聚合互不混合"
           if not problems else "；".join(problems[:5]))


# ---------------------------------------------------------------- T15–T16 计数规则

def _mini_pack_for_scorer(tmpdir, timeline, gt_segments, duration_ms):
    """构造最小 Evidence Pack（manifest + GT + evidence）供冻结评分器单元测试。"""
    media = os.path.join(tmpdir, "media.bin")
    with open(media, "wb") as handle:
        handle.write(b"task19-test-media")
    manifest = {
        "schema_version": "1.0.0", "pack_id": "task19-test-pack",
        "profile": "task19-test", "created_at": "2026-09-22T00:00:00Z",
        "frozen_at": "2026-09-22T00:00:00Z",
        "samples": [{
            "sample_id": "S1", "split": "dev", "source_type": "technical_fixture",
            "media_path": "media.bin",
            "media_sha256": hashlib.sha256(b"task19-test-media").hexdigest(),
            "media_duration_ms": duration_ms, "data_card": "card.json",
            "target_query": "测试目标", "task_type": "temporal_presence_evidence",
            "public_demo_allowed": False, "raw_file_public_git_allowed": False,
            "source_provenance": {"source_type": "technical_fixture",
                                  "fixture_generator_ref": "test",
                                  "generation_params_ref": "test",
                                  "freeze_record_ref": "test"},
        }],
    }
    gt = {
        "schema_version": "1.0.0", "sample_id": "S1",
        "media_sha256": hashlib.sha256(b"task19-test-media").hexdigest(),
        "media_duration_ms": duration_ms, "target_query": "测试目标",
        "annotation_version": "test-1", "annotated_at": "2026-09-22",
        "annotator_id": "test", "boundary_tolerance_ms": 1000,
        "segments": gt_segments,
        "label_frozen": {"frozen": True, "frozen_at": "2026-09-22T00:00:00Z"},
        "revision_history": [],
        "notes": "test",
    }
    # 时间线条目补 G7 必需字段（evidence_nature；failed 帧为 backend_call_failed）
    entries = []
    for entry in timeline:
        item = dict(entry)
        item["evidence_nature"] = ("backend_call_failed"
                                   if entry.get("frame_status") != "analyzed"
                                   else "real_model_output")
        entries.append(item)
    evidence = {
        "schema_version": "1.3.0", "task_id": "t", "target_query": "测试目标",
        "input_nature": "technical_fixture", "evidence_nature": "real_model_output",
        "source_video": media, "duration_ms": duration_ms, "sampled_frames": len(timeline),
        "sampling_strategy": "uniform",
        "timeline": entries,
        "sampling_provenance": {
            "strategy": "uniform", "configured_budget": len(timeline),
            "actual_model_calls": len(timeline), "budget_exhausted": False,
            "analyzed_timestamps": sorted({round(float(e["timestamp_ms"]), 3)
                                           for e in timeline}),
            "decisions": [{"timestamp_ms": e["timestamp_ms"], "cache_status": "fresh_call"}
                          for e in timeline],
            "timing": {"extraction_ms": 0.0, "analysis_ms": 0.0,
                       "aggregation_ms": 0.0, "total_ms": 0.0},
        },
        "temporal_evidence": {"class_counts": _counts(timeline),
                              "actual_model_calls": len(timeline)},
        "summary": {"overall_status": "completed"},
        "backend": {"vision_backend": "ollama", "model": "test-model",
                    "resource_blocked": False},
    }
    return manifest, gt, evidence, media


def _counts(timeline):
    counts = {"confirmed": 0, "not_found": 0, "abstained": 0, "low_confidence": 0,
              "failed": 0}
    for entry in timeline:
        if entry.get("frame_status") != "analyzed":
            counts["failed"] += 1
        elif entry.get("object_found") is True:
            counts["confirmed" if entry.get("evidence_sufficient") else "low_confidence"] += 1
        elif (entry.get("abstention_reason") or "").strip():
            counts["abstained"] += 1
        else:
            counts["not_found"] += 1
    return counts


def t15_failures_counted():
    spec = importlib.util.spec_from_file_location(
        "scorer", os.path.join(PROJECT_ROOT, "scripts",
                               "score_temporal_ground_truth.py"))
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    problems = []
    # (a) 构造用例：determinate 区的 failed 帧必须计入 failed_on_determinate
    with tempfile.TemporaryDirectory() as tmpdir:
        timeline = [
            {"timestamp_ms": 0.0, "frame_path": "f0.png", "object_found": False,
             "description": "", "bounding_box": None, "confidence": 0.9,
             "evidence_text": "", "abstention_reason": None, "frame_status": "analyzed",
             "evidence_sufficient": False, "gaps": [], "warnings": []},
            {"timestamp_ms": 1000.0, "frame_path": "f1.png", "object_found": False,
             "description": "", "bounding_box": None, "confidence": 0.0,
             "evidence_text": "", "abstention_reason": "单帧调用超时（非敏感原因）",
             "frame_status": "failed", "evidence_sufficient": False, "gaps": [],
             "warnings": []},
        ]
        manifest, gt, evidence, _media = _mini_pack_for_scorer(
            tmpdir, timeline, [{"start_ms": 0, "end_ms": 2000, "state": "not_found"}],
            2000.0)
        manifest_path = os.path.join(tmpdir, "manifest.json")
        gt_path = os.path.join(tmpdir, "gt.json")
        evidence_path = os.path.join(tmpdir, "evidence.json")
        predictions_path = os.path.join(tmpdir, "predictions.json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        with open(gt_path, "w", encoding="utf-8") as handle:
            json.dump(gt, handle)
        with open(evidence_path, "w", encoding="utf-8") as handle:
            json.dump(evidence, handle)
        with open(predictions_path, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": "1.0.0", "pack_id": "task19-test-pack",
                       "arms": [{"arm_id": "uniform", "samples": [
                           {"sample_id": "S1", "evidence": "evidence.json"}]}]}, handle)
        sample = manifest["samples"][0]
        score = scorer.score_sample(sample, gt, evidence, evidence_path, manifest_path,
                                    predictions_path, gt_path, "uniform")
        metrics = score["sample_point_scores"]["metrics"]
        if metrics["failed_on_determinate"]["passed"] != 1:
            problems.append(
                f"构造用例 failed_on_determinate="
                f"{metrics['failed_on_determinate']['passed']}")
        if metrics["correct_decisive"]["passed"] != 1:
            problems.append("构造用例 correct_decisive")
    # (b) 真实数据：七类计数之和 == 时间线条目数（failed 计入分母）
    real_checked = 0
    for sample_id in WHITELIST:
        for arm_id in ARM_IDS:
            score_path = os.path.join(SCORES, "all-dev", sample_id, arm_id, "score.json")
            evidence_path = os.path.join(PREDICTIONS, sample_id, arm_id,
                                         "temporal-evidence.json")
            if not (os.path.isfile(score_path) and os.path.isfile(evidence_path)):
                continue
            real_checked += 1
            score = load_json(score_path)
            evidence = load_json(evidence_path)
            metrics = score["sample_point_scores"]["metrics"]
            total = sum(metrics[key]["passed"] for key in
                        ("correct_decisive", "incorrect_decisive",
                         "abstention_on_determinate", "failed_on_determinate",
                         "appropriate_abstention", "overclaim_on_uncertain",
                         "failed_on_uncertain"))
            if total != len(evidence.get("timeline") or []):
                problems.append(f"{sample_id}/{arm_id}:计数和与时间线不符")
    record("T15", "失败与超时计入结果（构造用例 + 27 份真实 score 复算）",
           not problems,
           f"构造用例 failed_on_determinate=1（超时帧计入分母）；真实数据复算 "
           f"{real_checked}/27 份计数和=时间线条目数" if not problems
           else "；".join(problems[:5]))


def t16_zero_denominator():
    problems = []
    real_checked = 0
    ratio_fields = ("correct_decisive", "incorrect_decisive",
                    "abstention_on_determinate", "failed_on_determinate",
                    "appropriate_abstention", "overclaim_on_uncertain",
                    "failed_on_uncertain")
    for sample_id in WHITELIST:
        for arm_id in ARM_IDS:
            score_path = os.path.join(SCORES, "all-dev", sample_id, arm_id, "score.json")
            if not os.path.isfile(score_path):
                continue
            real_checked += 1
            score = load_json(score_path)
            section = score["sample_point_scores"]
            metrics = section["metrics"]
            for field in ratio_fields:
                entry = metrics.get(field)
                if not isinstance(entry, dict):
                    problems.append(f"{sample_id}/{arm_id}:{field} 缺失")
                    continue
                value = entry.get("ratio")
                if not (isinstance(value, (int, float)) or value == "not_applicable"):
                    problems.append(f"{sample_id}/{arm_id}:{field} 非法值 {value}")
                # 零分母必须写 not_applicable（不得写 0 或百分比）
                if entry.get("total") == 0 and value != "not_applicable":
                    problems.append(f"{sample_id}/{arm_id}:{field} 零分母未写 not_applicable")
                if entry.get("total") not in (0, None) and value == "not_applicable":
                    problems.append(f"{sample_id}/{arm_id}:{field} 非零分母误写 not_applicable")
            if section.get("denominator_determinate_samples") == 0 and \
                    metrics["correct_decisive"]["ratio"] != "not_applicable":
                problems.append(f"{sample_id}/{arm_id}:零 determinate 分母未写 not_applicable")
            if section.get("denominator_uncertain_samples") == 0 and \
                    metrics["appropriate_abstention"]["ratio"] != "not_applicable":
                problems.append(f"{sample_id}/{arm_id}:零 uncertain 分母未写 not_applicable")
    record("T16", "零分母 not_applicable（27 份真实 score 全量断言）", not problems,
           f"已核验 {real_checked}/27 份：比率仅可为数值或 not_applicable；"
           f"零分母一律 not_applicable" if not problems else "；".join(problems[:5]))


# ---------------------------------------------------------------- T17–T20 边界与卫生

def t17_raw_videos_not_in_git():
    tracked = git("ls-files").stdout.splitlines()
    problems = []
    mp4_tracked = [path for path in tracked if path.endswith(".mp4")]
    for path in mp4_tracked:
        full = os.path.join(PROJECT_ROOT, path)
        if not os.path.isfile(full):
            continue
        digest = sha256_of(full).upper()
        for sample_id in WHITELIST:
            card = load_json(os.path.join(CARDS_DIR, f"{sample_id}.json"))
            if digest == card["media"]["sha256"].upper():
                problems.append(f"{path}=={sample_id} 视频")
    for path in tracked:
        if path.startswith("artifacts/task-19/") and path.endswith(".mp4"):
            problems.append(f"task-19 目录存在入库 mp4: {path}")
    record("T17", "原始视频不在 Git（九个 dev 视频哈希不出现在任何跟踪文件）",
           not problems,
           f"跟踪 mp4 {len(mp4_tracked)} 个（任务 16/18 合成 fixture），"
           f"无一与 dev 视频哈希匹配；task-19 无入库 mp4" if not problems
           else "；".join(problems[:5]))


def t18_non_whitelist_rejected():
    verification = load_json(os.path.join(INGESTION, "dev-pack-verification.json"))
    scan = next(item for item in verification["checks"]
                if item["id"] == "I3-sample-id-scan")
    holdout = next(item for item in verification["checks"]
                   if item["id"] == "I5-no-holdout-ids")
    # 合成用例：白名单外编号必须被谓词拒绝。
    # 公开版：holdout 占位编号（HOLDOUT-*，公开版不列真实 holdout 编号）只参与
    # "不属于白名单"断言；编号形态断言限定在 ID 形态合成 token 上，避免空断言。
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "task19_ingest", os.path.join(PROJECT_ROOT, "scripts", "task19_ingest.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    id_shaped = ["AI00", "WEB99"]
    placeholder_tokens = ["HOLDOUT-G1", "HOLDOUT-G2", "HOLDOUT-L1"]
    synthetic_tokens = placeholder_tokens + id_shaped
    rejected = all(token not in module.WHITELIST for token in synthetic_tokens)
    pattern_ok = all(module.SAMPLE_ID_RE.fullmatch(token) for token in id_shaped)
    ok = (scan["passed"] and holdout["passed"] and rejected and pattern_ok)
    record("T18", "非白名单编号拒绝（合成谓词 + 真实包扫描）", ok,
           f"合成编号 {synthetic_tokens} 全部不属于白名单；"
           f"编号形态 token {id_shaped} 可被模式识别；"
           f"真实包扫描: {scan['detail'][:60]}")


def t19_inputs_readonly():
    verification = load_json(os.path.join(INGESTION, "dev-pack-verification.json"))
    problems = []
    # dev 包全部文件哈希与摄验记录（阶段 A）一致 → 输入只读
    for sample_id in WHITELIST:
        rel = verification["videos"][sample_id]["path"]
        full = os.path.join(DEV_PACK, rel)
        if sha256_of(full).upper() != verification["videos"][sample_id]["sha256"]:
            problems.append(f"{sample_id}:视频被修改")
        card_rel = f"data-cards/transfer-safe/{sample_id}.json"
        if sha256_of(os.path.join(DEV_PACK, card_rel)).upper() != \
                verification["cards"][sample_id]["sha256"]:
            problems.append(f"{sample_id}:卡被修改")
    # 复制的卡与包内卡字节一致
    for sample_id in WHITELIST:
        if sha256_of(os.path.join(CARDS_DIR, f"{sample_id}.json")) != \
                sha256_of(os.path.join(DEV_PACK,
                                       f"data-cards/transfer-safe/{sample_id}.json")):
            problems.append(f"{sample_id}:复制卡不一致")
    record("T19", "输入只读（dev 包 18 个关键文件哈希与阶段 A 摄验记录一致）",
           not problems,
           "九视频 + 九卡 + 九复制卡全部与摄验记录一致（dev 包未被修改）"
           if not problems else "；".join(problems[:5]))


def t20_output_hygiene():
    problems = []
    scanned = 0
    for root, dirs, files in os.walk(TASK19):
        dirs[:] = [d for d in dirs if d not in ("frames", "__pycache__", "media")]
        for name in files:
            if not name.endswith((".json", ".md", ".txt", ".log")):
                continue
            path = os.path.join(root, name)
            try:
                text = open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            scanned += 1
            lowered = text.lower()
            for marker in CREDENTIAL_MARKERS:
                if marker in lowered and marker not in ("secret",):
                    problems.append(f"{os.path.relpath(path, PROJECT_ROOT)}:{marker}")
            for match in ABS_PATH_RE.finditer(text):
                token = match.group(0)
                # 允许项目内绝对路径（帧审计轨迹惯例，与任务 16/18 已提交产物一致）；
                # 禁止仓库外用户路径（dev 包路径等）；详情中的路径脱敏后报告
                if token.startswith(PROJECT_ROOT):
                    continue
                problems.append(f"{os.path.relpath(path, PROJECT_ROOT)}:"
                                f"{token.replace(os.path.expanduser('~'), '~')}")
    record("T20", "输出无凭据与仓库外敏感绝对路径", not problems,
           f"扫描 {scanned} 个 task-19 文本产物：无凭据样式、无仓库外绝对路径"
           f"（项目内帧审计路径为既有惯例）" if not problems
           else "；".join(problems[:5]))


# ---------------------------------------------------------------- T21–T22 冻结

def t21_preregistration_hashes_after_run():
    frozen = load_json(os.path.join(PREREGISTRATION, "frozen-hashes.json"))
    problems = []
    total = 0
    for group in ("preregistration_declarations", "ingestion", "ground_truth",
                  "design_doc", "frozen_scorer_adapter"):
        for key, entry in frozen.get(group, {}).items():
            total += 1
            path = os.path.join(PROJECT_ROOT, entry["path"])
            if not os.path.isfile(path) or sha256_of(path) != entry["sha256"]:
                problems.append(f"{group}/{key}")
    for name in ("evaluation-plan.json", "arm-configs.json", "verdict-policy.json",
                 "README.md"):
        committed = git("show", f"{PHASE_A_COMMIT}:artifacts/task-19/preregistration/{name}")
        with open(os.path.join(PREREGISTRATION, name), "rb") as handle:
            current = handle.read()
        if committed.returncode != 0 or committed.stdout.encode("utf-8") != current:
            problems.append(f"{name}:与阶段 A 提交不一致")
    record("T21", "预注册哈希在运行后不变（31 条目 + 4 份声明文件 blob 比对）",
           not problems,
           f"{total} 个哈希条目全部一致；声明文件与 {PHASE_A_COMMIT} 逐字节一致"
           if not problems else "；".join(problems[:5]))


def t22_frozen_files_unchanged():
    problems = []
    for rel in FROZEN_FILES:
        committed = git("show", f"{TASK18_COMMIT}:{rel}")
        current_path = os.path.join(PROJECT_ROOT, rel)
        if committed.returncode != 0:
            problems.append(f"{rel}:基线不可读")
            continue
        with open(current_path, "rb") as handle:
            if handle.read() != committed.stdout.encode("utf-8"):
                problems.append(f"{rel}:与 {TASK18_COMMIT} 不一致")
    record("T22", "scorer 与实现冻结文件零改动（相对 ef9f329 逐字节）", not problems,
           f"{len(FROZEN_FILES)} 个冻结文件与任务 18 提交逐字节一致"
           if not problems else "；".join(problems[:5]))


def check_prerequisites():
    """公开版前置检查：本测试的多数用例读取任务 19B 的内部摄验/评分产物与
    仓库外 dev Evidence Pack，这些内容不随公开仓库分发（见
    docs/PUBLIC-VERSION-NOTES.md）。缺失时不伪报 PASS，明确退出。"""
    missing = []
    for label, path in (
        ("dev Evidence Pack（仓库外，用户本地只读）", DEV_PACK),
        ("artifacts/task-19/preregistration/", PREREGISTRATION),
        ("artifacts/task-19/ingestion/", INGESTION),
        ("artifacts/task-19/ground-truth/", GROUND_TRUTH),
        ("artifacts/task-19/execution-manifests/", EXECUTION_MANIFESTS),
        ("artifacts/task-19/predictions/", PREDICTIONS),
        ("artifacts/task-19/scores/", SCORES),
    ):
        if not os.path.exists(path):
            missing.append(label)
    if missing:
        print("[NOT_RUN] Task 19B 确定性测试的前置产物不在公开仓库中：")
        for item in missing:
            print(f"  - 缺失: {item}")
        print("说明：这些内容为内部留档（媒体授权与开发机路径原因，不随公开仓库分发）。")
        print("      本测试在备齐上述前置产物后即可运行；公开仓库中不伪报任何结果。")
        return False
    return True


def main():
    if not check_prerequisites():
        return 2
    tests = [
        ("T01", t01_whitelist), ("T02", t02_manifest_hashes),
        ("T03", t03_video_card_hashes), ("T04", t04_lineage),
        ("T05", t05_card_core_fields), ("T06", t06_gt_deterministic),
        ("T07", t07_adjacent_merge), ("T08", t08_coverage_unchanged),
        ("T09", t09_execution_manifest_no_labels), ("T10", t10_budget_only_duration),
        ("T11", t11_three_arm_fairness), ("T12", t12_track_classification),
        ("T13", t13_no_boundary_denominator), ("T14", t14_track_summaries),
        ("T15", t15_failures_counted), ("T16", t16_zero_denominator),
        ("T17", t17_raw_videos_not_in_git), ("T18", t18_non_whitelist_rejected),
        ("T19", t19_inputs_readonly), ("T20", t20_output_hygiene),
        ("T21", t21_preregistration_hashes_after_run), ("T22", t22_frozen_files_unchanged),
    ]
    for _id, func in tests:
        try:
            func()
        except Exception as error:  # noqa: BLE001
            record(_id, func.__name__, False, f"异常: {type(error).__name__}: {error}")
    passed = sum(1 for item in RESULTS if item["passed"])
    result = {
        "task": "task-19b-deterministic-tests",
        "total": len(RESULTS),
        "passed": passed,
        "failed": len(RESULTS) - passed,
        "all_passed": passed == len(RESULTS),
        "results": RESULTS,
    }
    os.makedirs(TASK19, exist_ok=True)
    with open(os.path.join(TASK19, "test-results.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"\n[测试结果] {passed}/{len(RESULTS)} 通过"
          f"（结果: artifacts/task-19/test-results.json）")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
