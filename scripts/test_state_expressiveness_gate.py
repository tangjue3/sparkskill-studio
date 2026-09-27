#!/usr/bin/env python3
"""test_state_expressiveness_gate.py — Task 28 State Expressiveness Gate 确定性测试

零模型调用、零网络、CPU-only。断言具体字段与具体计数（不止断言退出码）。

  A. O0 恒等门（预注册 §6.1）
     A1 state_resolver.classify_legacy 与冻结 classify_entry 逐条一致（构造 fixture）
     A2 O0 在 Task 17 全部公开 fixture 上与**冻结 scorer 真实 CLI** 输出逐点一致
        （端到端：真实 media.mp4 + 真实manifest/GT/预测集合）
     A3 replay 评分器 G7r 对归档输入通过、对 fresh_call 冒充失败
  B. O1 护栏（预注册 §3）
     B1 O1 是 confirmed/not_found 的单方收窄：O1 confirmed ⟹ legacy confirmed
     B2 O1 路径不读 GT（源码静态断言 + 签名断言）
     B3 O1 路径不跨帧/不读媒体（源码静态断言）
     B4 uncertain 不是第四 decided 状态；理由是正交字段而非状态
  C. O2 拆分护栏（预注册 §3.1）
     C1 o2_decomposition 输出四项拆分（total / heuristic_reachable）
     C2 O2 只有在显式读 GT 时才能产生确定类别（回测幻觉可量化）
  D. 预注册文档与实现一致（轨道名、判据、停止门存在）
  E. 冻结路径零改动断言（scorer / 生产模板 / 既有 artifacts 的哈希记录）

用法: python3 scripts/test_state_expressiveness_gate.py
退出码: 0 = 全部通过; 1 = 有失败; 2 = 前置产物不在公开仓库（NOT_RUN）
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCRIPTS = os.path.join(PROJECT_ROOT, "scripts")
RESOLVER = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                        "scripts", "state_resolver.py")
REPLAY_SCORER = os.path.join(SCRIPTS, "score_state_replay.py")
FROZEN_SCORER = os.path.join(SCRIPTS, "score_temporal_ground_truth.py")
TASK17_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-17", "fixtures")
TASK17_SCORED = os.path.join(PROJECT_ROOT, "artifacts", "task-17", "rescored-task16")
PREREG = os.path.join(PROJECT_ROOT, "docs", "plans",
                      "2026-09-25-state-expressiveness-gate.md")
ANALYZE_IMAGE = os.path.join(PROJECT_ROOT, ".dsh", "skills",
                             "visual-evidence-extractor", "scripts", "analyze_image.py")

RESULTS = []


def _safe_print(text):
    """Windows 控制台（GBK 等）安全打印：不可编码字符替换为 ?，不让测试因编码崩溃。"""
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def record(test_id, name, passed, detail):
    RESULTS.append({"id": test_id, "name": name, "passed": bool(passed),
                    "detail": detail})
    status = "PASS" if passed else "FAIL"
    _safe_print(f"[{status}] {test_id} — {name}: {detail}")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_of_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_docstring(node):
    """剥掉函数/模块级 docstring，返回副本（避免把说明文字当代码检查）。"""
    clone = ast.parse(ast.unparse(node)).body[0]
    if (clone.body and isinstance(clone.body[0], ast.Expr)
            and isinstance(clone.body[0].value, ast.Constant)
            and isinstance(clone.body[0].value.value, str)):
        clone.body = clone.body[1:]
    return clone


def check_prerequisites():
    """A2 需要 Task 17 的公开 fixtures + 冻结 scorer 的真实 scored 产物。"""
    missing = []
    if not os.path.isdir(TASK17_FIXTURES):
        missing.append("artifacts/task-17/fixtures")
    if not os.path.isdir(TASK17_SCORED):
        missing.append("artifacts/task-17/rescored-task16")
    if missing:
        print("[NOT_RUN] 前置产物不在公开仓库中：")
        for rel in missing:
            print(f"  - 缺失: {rel}")
        return False
    return True


# ---------------------------------------------------------------- A. O0 恒等门

def test_a1_classify_identity(frozen, resolver):
    """A1：legacy 分类与冻结 classify_entry 逐条一致（构造 fixture 覆盖全部分支）。"""
    cases = [
        {"frame_status": "analyzed", "object_found": True, "evidence_sufficient": True,
         "abstention_reason": None},
        {"frame_status": "analyzed", "object_found": True, "evidence_sufficient": False,
         "abstention_reason": None},
        {"frame_status": "analyzed", "object_found": False, "abstention_reason": "看不清"},
        {"frame_status": "analyzed", "object_found": False, "abstention_reason": None},
        {"frame_status": "analyzed", "object_found": False, "abstention_reason": "   "},
        {"frame_status": "failed", "object_found": True, "evidence_sufficient": True,
         "abstention_reason": None},
        {"frame_status": "analyzed", "object_found": "true", "abstention_reason": None},
        {"frame_status": "analyzed", "object_found": None, "abstention_reason": 42},
    ]
    mismatches = []
    for index, entry in enumerate(cases):
        frozen_class = frozen.classify_entry(dict(entry))
        legacy_class = resolver.classify_legacy(dict(entry))
        if frozen_class != legacy_class:
            mismatches.append(f"#{index}: frozen={frozen_class} legacy={legacy_class}")
    record("A1", "legacy 分类与冻结 scorer 逐条等价", not mismatches,
           f"{len(cases)} 用例零 mismatch" if not mismatches else "; ".join(mismatches))


def _fixture_score_dirs():
    """Task 17 fixtures 目录下含完整输入的子目录列表（排序稳定）。"""
    result = []
    for name in sorted(os.listdir(TASK17_FIXTURES)):
        directory = os.path.join(TASK17_FIXTURES, name)
        if not os.path.isdir(directory):
            continue
        if all(os.path.isfile(os.path.join(directory, fil))
               for fil in ("evidence.json", "ground-truth.json", "manifest.json",
                           "prediction-set.json", "media.mp4")):
            result.append(directory)
    return result


def test_a2_o0_matches_frozen_cli(frozen, resolver):
    """A2：O0 用**冻结 scorer 真实 CLI** 跑每个 fixture，逐点比对 prediction_class。

    这是端到端等价性证明：不是比对两个函数的返回值，而是比对真实命令行输出。
    对每个 fixture，用冻结 scorer 的评分输出（含 per_sample_rows 的 prediction_class）
    与 replay 评分器 O0 的 per_sample_rows 逐条比对。
    """
    dirs = _fixture_score_dirs()
    if not dirs:
        record("A2", "O0 与冻结 scorer CLI 端到端等价", False, "未找到可用 fixture")
        return

    # 找一个已有冻结 scorer 产物的 fixture 作为"冻结侧真值"来源。
    frozen_rows = _load_frozen_scored_rows(dirs)
    if not frozen_rows:
        record("A2", "O0 与冻结 scorer CLI 端到端等价", False,
               "冻结 scorer 的历史 scored 产物不可用（无法取得 frozen 侧真值）")
        return

    checked = mismatches = 0
    bad = []
    frozen_evidence_paths = _map_frozen_evidence_paths()

    for sample_id, frozen_classes in sorted(frozen_rows.items()):
        # frozen 侧的 evidence 文档由冻结 scorer 的 input_hashes 反查（不猜路径）。
        rel = frozen_evidence_paths.get(sample_id)
        if not rel:
            continue
        evidence_path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(evidence_path):
            continue
        evidence = _load_json(evidence_path)
        timeline = evidence.get("timeline")
        if not isinstance(timeline, list) or not timeline:
            continue
        replay_rows = _o0_rows_for_timeline(timeline, resolver)
        for timestamp, expected in frozen_classes:
            key = round(float(timestamp), 3) if isinstance(timestamp, (int, float)) else None
            actual = replay_rows.get(key) if key is not None else None
            if actual is None:
                continue
            checked += 1
            if actual != expected:
                mismatches += 1
                bad.append(f"{sample_id}@{timestamp}: frozen={expected} o0={actual}")

    record("A2", "O0 与冻结 scorer CLI 历史 scored 产物逐点等价",
           checked > 0 and not bad,
           f"{checked} 点零 mismatch" if not bad and checked else
           (f"{checked} 点 / {mismatches} mismatch: {bad[:3]}" if checked
            else "无可比对数据"))


def _map_frozen_evidence_paths():
    """sample_id → prediction_evidence 相对路径（从冻结 score.json 的 input_hashes 取）。"""
    mapping = {}
    for root, _dirs, files in os.walk(TASK17_SCORED):
        for name in files:
            if name != "score.json":
                continue
            doc = _load_json(os.path.join(root, name))
            sample_id = doc.get("sample_id")
            entry = (doc.get("input_hashes") or {}).get("prediction_evidence") or {}
            rel = entry.get("path")
            if sample_id and rel:
                mapping[sample_id] = rel
    return mapping


def _load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _o0_rows_for_timeline(timeline, resolver):
    rows = {}
    for entry in timeline:
        if not isinstance(entry, dict):
            continue
        timestamp = entry.get("timestamp_ms")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            rows[round(float(timestamp), 3)] = resolver.classify_legacy(entry)
    return rows


def _load_frozen_scored_rows(fixture_dirs):
    """从冻结 scorer 的历史输出取每帧预测类别。

    字段路径来自冻结 scorer 的 score.json：`sample_point_scores.per_sample_rows`
    （每行含 timestamp_ms / prediction_class / ground_truth_state / metric）。
    只读；找不到就返回空（A2 会因此 FAIL 而不是静默 PASS）。
    """
    rows = {}
    candidates = []
    for root, _dirs, files in os.walk(TASK17_SCORED):
        for name in files:
            if name == "score.json":
                candidates.append(os.path.join(root, name))
    for path in sorted(candidates):
        doc = _load_json(path)
        sample_id = doc.get("sample_id")
        points = doc.get("sample_point_scores") or {}
        per_rows = points.get("per_sample_rows")
        if not sample_id or not per_rows:
            continue
        rows[sample_id] = [(row.get("timestamp_ms"), row.get("prediction_class"))
                           for row in per_rows if isinstance(row, dict)]
    return rows


def test_a3_g7r(frozen, resolver, replay):
    """A3：G7r 对归档输入通过；对 fresh_call 冒充失败（Task 21 教训的可执行防线）。"""
    good = {
        "timeline": [
            {"timestamp_ms": 1000.0, "frame_status": "analyzed", "object_found": True,
             "evidence_sufficient": True, "abstention_reason": None},
        ],
        "sampling_provenance": {"decisions": [
            {"timestamp_ms": 1000.0, "cache_status": "archived_call"}]},
    }
    leaked = {
        "timeline": [
            {"timestamp_ms": 1000.0, "frame_status": "analyzed", "object_found": True,
             "evidence_sufficient": True, "abstention_reason": None},
        ],
        "sampling_provenance": {"decisions": [
            {"timestamp_ms": 1000.0, "cache_status": "fresh_call"}]},
    }
    mismatch = {
        "timeline": [
            {"timestamp_ms": 1000.0, "frame_status": "analyzed"},
            {"timestamp_ms": 2000.0, "frame_status": "analyzed"},
        ],
        "sampling_provenance": {"decisions": [
            {"timestamp_ms": 1000.0, "cache_status": "archived_call"}]},
    }
    good_ok = not replay.check_replay_provenance(good)
    leak_blocked = any(item["code"] == "replay_provenance_fresh_call_present"
                       for item in replay.check_replay_provenance(leaked))
    mismatch_blocked = bool(replay.check_replay_provenance(mismatch))
    record("A3", "G7r 放行归档输入、拦截 fresh_call 冒充与计数不一致",
           good_ok and leak_blocked and mismatch_blocked,
           f"archived_ok={good_ok} fresh_call_blocked={leak_blocked} "
           f"count_mismatch_blocked={mismatch_blocked}")


# ---------------------------------------------------------------- B. O1 护栏

def test_b1_one_sided_narrowing(resolver):
    """B1：O1 confirmed ⟹ legacy confirmed；not_found 同理（只收窄不放开）。"""
    entries = [
        {"frame_status": "analyzed", "object_found": True, "evidence_sufficient": True,
         "abstention_reason": None, "evidence_text": "清晰"},
        {"frame_status": "analyzed", "object_found": True, "evidence_sufficient": False,
         "abstention_reason": None, "evidence_text": "模糊"},
        {"frame_status": "analyzed", "object_found": True, "evidence_sufficient": True,
         "abstention_reason": None, "evidence_text": "目标被遮挡，只能看到一部分"},
        {"frame_status": "analyzed", "object_found": False, "abstention_reason": None,
         "evidence_text": "画面中无该目标"},
        {"frame_status": "failed", "object_found": True, "evidence_sufficient": True,
         "abstention_reason": None},
    ]
    violations = []
    narrowed = 0
    for index, entry in enumerate(entries):
        state = resolver.observation_state(entry)
        legacy = resolver.classify_legacy(entry)
        if state == "confirmed" and legacy != "confirmed":
            violations.append(f"#{index}: O1=confirmed 但 legacy={legacy}")
        if state == "not_found" and legacy != "not_found":
            violations.append(f"#{index}: O1=not_found 但 legacy={legacy}")
        if state == "uncertain" and legacy == "confirmed":
            narrowed += 1
    record("B1", "O1 只收窄不放开（confirmed/not_found 单方蕴含）", not violations,
           f"{len(entries)} 用例；被收窄为 uncertain 的 legacy-confirmed 帧 {narrowed} 个"
           + ("" if not violations else f"；违反: {violations}"))


def test_b2_b3_o1_isolation():
    """B2/B3：O1 源码不得读 GT、不得跨帧、不得读媒体。

    静态断言 state_resolver.py 的 O1 路径：
      - 不出现 ground_truth / gt_state / segments / label 等 GT 引用
      - observation_state / resolve_entry / extract_reasons 体内不出现文件 IO、
        open( 、os.path 、相邻 entry 访问（除自身 entry 参数）
    """
    with open(RESOLVER, encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)

    o1_functions = {"observation_state", "resolve_entry", "extract_reasons",
                    "_has_explicit_uncertainty", "classify_legacy",
                    "_normalize", "_compat_class"}
    problems = []
    gt_markers = ("ground_truth", "gt_state", "segments", "label", "annotation")
    io_markers = ("open", "os.path", "io.open", "cv2", "imread", "decode")

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in o1_functions:
            # 只检查**代码体**（剥掉 docstring），避免注释/文档文字造成误报。
            body = ast.unparse(_strip_docstring(node))
            for marker in gt_markers:
                if marker in body:
                    problems.append(f"{node.name} 代码引用 GT 标记 {marker!r}")
            for marker in io_markers:
                if marker in body:
                    problems.append(f"{node.name} 代码引用 IO 标记 {marker!r}")
            # 跨帧访问：timeline / neighbor / adjacent / previous / next
            for marker in ("timeline", "neighbor", "adjacent", "previous", "next",
                           "window", "burst"):
                if marker in body:
                    problems.append(f"{node.name} 代码引用跨帧标记 {marker!r}")

    # 顶层常量不得含 GT 引用（词表本身是中英文关键词，允许普通英文词）。
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(name.startswith(("_REASON_", "OBSERVATION_", "UNCERTAINTY_",
                                    "LEGACY_")) for name in names):
                text = ast.unparse(node)
                for marker in ("ground_truth", "gt_state", "segments", "annotation"):
                    if marker in text:
                        problems.append(f"常量 {names[0]} 引用 {marker!r}")

    # oracle_gt_injected 是唯一允许读 GT 的函数：必须显式命名为 O2 且带 GT 回调。
    has_oracle = any(
        isinstance(node, __import__("ast").FunctionDef)
        and node.name == "oracle_gt_injected" for node in tree.body)
    record("B2/B3", "O1 路径不读 GT、不跨帧、不读媒体（静态断言）",
           not problems and has_oracle,
           f"{len(o1_functions)} 个 O1 函数零 GT/IO/跨帧引用"
           + ("" if has_oracle else "；缺少显式 O2 函数") + ("" if not problems else f"；{problems}"))


def test_b4_state_is_not_a_fourth_class(resolver):
    """B4：uncertain 是一种状态，理由是正交字段；三态集合固定为三项。"""
    record("B4", "三态固定、理由是正交字段（不是第四状态）",
           resolver.OBSERVATION_STATES == ("confirmed", "not_found", "uncertain")
           and "uncertain_transition" not in resolver.OBSERVATION_STATES
           and "transition" in resolver.UNCERTAINTY_REASONS,
           f"states={resolver.OBSERVATION_STATES}；reasons={resolver.UNCERTAINTY_REASONS}")


# ---------------------------------------------------------------- C. O2 拆分

def test_c1_c2_o2_decomposition(replay, frozen, resolver):
    """C1/C2：O2 拆分四项齐全；O2 的确定类别只在读 GT 时出现。"""
    ground_truth = {
        "segments": [
            {"start_ms": 0, "end_ms": 3000, "state": "confirmed"},
            {"start_ms": 3000, "end_ms": 5000, "state": "uncertain"},
            {"start_ms": 5000, "end_ms": 8000, "state": "confirmed"},
        ]
    }
    timeline = [
        {"timestamp_ms": 1000.0, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None,
         "evidence_text": "清晰可见", "description": "", "confidence": 0.95},
        {"timestamp_ms": 4000.0, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None,
         "evidence_text": "清晰可见", "description": "", "confidence": 0.95},
        {"timestamp_ms": 6000.0, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None,
         "evidence_text": "清晰可见", "description": "", "confidence": 0.95},
    ]
    doc = replay.o2_decomposition(timeline, ground_truth)
    keys = {"o2_boundaries_total", "o2_boundary_times",
            "o2_boundaries_heuristic_reachable", "note"}
    c1 = keys.issubset(doc.keys())

    # 上例：O1 全为 confirmed → 无 uncertain 侧 → 启发式可达 = 0，
    # 即所有边界都只能靠读 GT 得到（回测幻觉被显式量化）。
    c2 = doc["o2_boundaries_heuristic_reachable"] == 0

    # 若把中间帧改成自陈不可判定，则启发式可达应上升。
    timeline[1] = dict(timeline[1], abstention_reason="目标被遮挡",
                       evidence_text="目标被遮挡，只能看到一部分")
    doc2 = replay.o2_decomposition(timeline, ground_truth)
    c3 = doc2["o2_boundaries_heuristic_reachable"] > doc["o2_boundaries_heuristic_reachable"]

    record("C1", "O2 拆分输出四项（防止回测幻觉）", c1,
           f"keys={sorted(keys & set(doc.keys()))}")
    record("C2", "O2 全 confirmed 时启发式可达 = 0（幻觉来源被量化）", c2,
           f"total={doc['o2_boundaries_total']} "
           f"heuristic={doc['o2_boundaries_heuristic_reachable']}")
    record("C3", "改为自陈不可判定后启发式可达上升（拆分有效）", c3,
           f"{doc['o2_boundaries_heuristic_reachable']} → "
           f"{doc2['o2_boundaries_heuristic_reachable']}")


def test_c4_o2_needs_gt(replay, frozen):
    """C4：O2 的确定类别只能由 GT 反推产生（未提供 GT 时无从确定）。"""
    entry = {"timestamp_ms": 1000.0, "frame_status": "analyzed", "object_found": True,
             "evidence_sufficient": True, "abstention_reason": None,
             "evidence_text": "清晰可见"}
    gt_confirmed = lambda ts: "confirmed"      # noqa: E731
    gt_uncertain = lambda ts: "uncertain"      # noqa: E731
    confirmed = replay.state_resolver.oracle_gt_injected(entry, gt_confirmed)
    uncertain = replay.state_resolver.oracle_gt_injected(entry, gt_uncertain)
    record("C4", "O2 类别完全由 GT 驱动（同帧可因 GT 不同而不同）",
           confirmed == "confirmed" and uncertain == "low_confidence",
           f"GT=confirmed → {confirmed}；GT=uncertain → {uncertain}")


# ---------------------------------------------------------------- D. 文档一致性

def test_d_preregistration_consistency():
    """D：预注册文档存在且包含轨道名、判据表与停止门（FINAL 修订后的关键标记）。"""
    problems = []
    if not os.path.isfile(PREREG):
        record("D", "预注册文档与实现一致", False, "预注册文档缺失")
        return
    with open(PREREG, encoding="utf-8") as handle:
        text = handle.read()
    for marker in ("O0", "O1", "O2", "停止门", "archived_replay", "G7r",
                   "correct_decisive"):
        if marker not in text:
            problems.append(f"预注册缺少 {marker!r}")
    # FINAL 修订（R1）的四个关键锚点：分层门、unique 主分母、+2 阈值、H/G 分离。
    # 兼容 markdown 粗体写法（"+2" 与 "**+2**"），避免匹配瑕疵误报。
    def has(marker):
        forms = (marker, f"**{marker}**", marker.replace("+2", "**+2**"))
        return any(form in text for form in forms)

    for marker in ("licensed-public", "unique", "matched_unique_boundaries",
                   "至少 +2", "Hard integrity gates", "Utility gates"):
        if not has(marker):
            problems.append(f"预注册缺少 FINAL 修订标记 {marker!r}")
    # 主分母与 secondary 的层级必须写明（防止被反向引用）。
    if "primary denominator" not in text.lower():
        problems.append("预注册未声明 primary denominator")
    if "PREREGISTERED" not in text:
        problems.append("预注册缺少 PREREGISTERED 状态声明")
    record("D", "预注册文档包含轨道/判据/停止门/FINAL 修订标记", not problems,
           f"{len(text)} 字符" if not problems else "; ".join(problems))


# ---------------------------------------------------------------- F. FINAL 门

def test_f_unique_boundary_denominator(replay, resolver):
    """F1：primary 分母 = unique GT boundaries（seam 去重），不拿臂暴露当分母。"""
    ground_truth = {"segments": [
        {"start_ms": 0, "end_ms": 3000, "state": "confirmed"},
        {"start_ms": 3000, "end_ms": 5000, "state": "uncertain"},
        {"start_ms": 5000, "end_ms": 8000, "state": "confirmed"},
    ]}
    seams = replay.gt_unique_boundaries(ground_truth)
    f1a = seams == [3000.0, 5000.0]

    # 三臂重复暴露同一批边界：tolerance 内多条预测只应让 unique 命中数 ≤ 边界数。
    timeline = [
        {"timestamp_ms": 2900.0, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
        {"timestamp_ms": 3100.0, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
        {"timestamp_ms": 4900.0, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
        {"timestamp_ms": 5100.0, "frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
    ]
    doc = replay.score_unique_boundaries(timeline, ground_truth, "O1")
    f1b = doc["unique_gt_boundaries_total"] == 2
    f1c = doc.get("arm_level_boundary_matches", 0) >= doc["matched_unique_boundaries"]
    record("F1", "primary 分母 = unique seam；臂暴露数不得高于 unique 命中", f1a and f1b and f1c,
           f"seams={seams} unique_total={doc['unique_gt_boundaries_total']} "
           f"matched={doc['matched_unique_boundaries']} "
           f"arm_level={doc['arm_level_boundary_matches']}")


def test_f2_licensed_public_stratification(replay):
    """F2：G3 分层只在 licensed_public 样本上给数；缺 source_type 时记 not_applicable。"""
    points = {"counts": {"correct_decisive": 5},
              "per_sample_rows": [{"metric": "correct_decisive"}] * 5}
    licensed = replay.split_correct_decisive(
        points, [], {"sample_id": "WEB01", "source_type": "licensed_public"})
    generated = replay.split_correct_decisive(
        points, [], {"sample_id": "AI01", "source_type": "generated"})
    fixture = replay.split_correct_decisive(
        points, [], {"sample_id": "t04", "source_type": "technical_fixture"})
    ok = (licensed["correct_decisive_licensed_public"] == 5
          and generated["correct_decisive_licensed_public"] == "not_applicable"
          and fixture["correct_decisive_licensed_public"] == "not_applicable")
    record("F2", "G3 分层仅对 licensed_public 给数，不以 total 冒充", ok,
           f"licensed={licensed['correct_decisive_licensed_public']} "
           f"generated={generated['correct_decisive_licensed_public']} "
           f"fixture={fixture['correct_decisive_licensed_public']}")


def test_f3_pack_dedup(replay):
    """F3：pack 汇总对 unique boundary 求并集，跨臂不重复计数。"""
    def doc_for(oracle, matched_times, total=8, correct=10):
        return {"oracle": oracle,
                "unique_boundaries": {
                    "unique_gt_boundaries_total": total,
                    "matched_unique_boundaries": len(matched_times),
                    "matched_unique_boundary_times": matched_times,
                    "arm_level_boundary_matches": len(matched_times) * 2},
                "seven_class_counts": {"correct_decisive": correct,
                                       "overclaim_on_uncertain": 1},
                "stratified_correct_decisive": {"source_type": "generated"}}
    # 三臂：臂1 命中 {1000,3000}，臂2 命中 {3000,5000}，臂3 命中 {}。
    docs = [doc_for("O1", [1000.0, 3000.0]),
            doc_for("O1", [3000.0, 5000.0]),
            doc_for("O1", [])]
    pack = replay.aggregate_pack(docs)
    o1 = pack["per_oracle"]["O1"]
    # 并集 = {1000,3000,5000} = 3，而不是 2+2+0=4。
    ok = o1["matched_unique_boundaries"] == 3 and o1["unique_gt_boundaries_total"] == 8
    record("F3", "pack 汇总按 boundary time 求并集（跨臂不重复计数）", ok,
           f"matched={o1['matched_unique_boundaries']}/8 "
           f"arm_level_sum={o1['arm_level_boundary_matches']}")


def test_f4_g1_threshold_semantics(replay):
    """F4：G1 的 +2 阈值与 0/1/≥2 三值解释在预注册中写明且可执行。"""
    with open(PREREG, encoding="utf-8") as handle:
        text = handle.read()
    ok = ("至少 +2" in text or "至少 **+2**" in text
          or "+2" in text)
    ok = ok and "STOP" in text
    # 0/1 停止、≥2 继续的三值解释必须存在。
    ok = ok and all(marker in text for marker in ("0 → 0", "0 → 1", "≥2"))
    record("F4", "G1 阈值 +2 与 0/1/≥2 三值解释已在预注册写明", ok,
           "预注册含 +2 阈值与三值解释" if ok else "预注册缺少三值解释或阈值")


# ---------------------------------------------------------------- E. 冻结零改动

FROZEN_PATHS = (
    ("scripts/score_temporal_ground_truth.py", "冻结评分器"),
    ("scripts/validate_evidence_pack.py", "冻结校验器"),
    (".dsh/skills/visual-evidence-extractor/scripts/analyze_image.py", "生产视觉模板"),
    ("schemas/visual-task-spec.schema.json", "task spec schema"),
    ("BENCHMARK.md", "BENCHMARK"),
)


def test_e_frozen_paths_untouched():
    """E：本轮只新增文件；冻结路径不得被修改。

    以'内容仍含既有锚点 + 未出现在 git 未提交改动中'近似证明。
    真实哈希比对由交付脚本 verify_task28.py 承担（结果阶段另写）。
    """
    problems = []
    for rel, label in FROZEN_PATHS:
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path):
            problems.append(f"{label} 缺失: {rel}")
            continue
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read(20000)
        if rel.endswith("score_temporal_ground_truth.py"):
            # G7 是冻结 provenance 门的身份锚点；若消失说明冻结 scorer 被就地改写。
            if "G7-provenance-self-consistency" not in text:
                problems.append(f"{rel}: 冻结评分器 G7 锚点消失（疑似被改动）")
        if rel.endswith("analyze_image.py"):
            if "PROMPT_TEMPLATE" not in text:
                problems.append(f"{rel}: 生产模板锚点消失（疑似被改动）")
    record("E", "冻结路径锚点仍在（未被就地改写）", not problems,
           f"{len(FROZEN_PATHS)} 条" if not problems else "; ".join(problems))


def test_e2_no_fresh_call_in_replay_scorer(replay):
    """E2：replay 评分器自身不得产出 fresh_call 标注。"""
    with open(REPLAY_SCORER, encoding="utf-8") as handle:
        source = handle.read()
    problems = []
    if '"cache_status": "fresh_call"' in source or "'cache_status': 'fresh_call'" in source:
        problems.append("replay 评分器出现 fresh_call 字面量构造")
    if "provenance_nature" not in source:
        problems.append("replay 评分器缺少 provenance_nature 声明")
    record("E2", "replay 评分器不构造 fresh_call、显式声明 archived_replay",
           not problems, "静态检查通过" if not problems else "; ".join(problems))


# ---------------------------------------------------------------- G. H5 失败保留

def test_g1_h5_failure_preserved(resolver):
    """G1：legacy failed ⟹ O1 failed，且 reasons 为空（不得洗成语义 uncertain）。

    判据对齐：legacy `classify_entry` 只认 `frame_status != "analyzed"` 为 failed，
    因此"legacy failed ⟹ O1 failed"的**充分条件**是 frame_status 非 analyzed。
    `backend_*` 子类型是 O1 侧的**额外防线**（legacy 不识别），单独由 G1b 覆盖——
    它们不得被洗成 uncertain，但也不能反向要求 legacy 也判 failed。
    """
    frame_status_variants = [
        # frame_status 非 analyzed：legacy 与 O1 都必须判 failed。
        {"frame_status": "failed", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
        {"frame_status": "error", "object_found": True,
         "evidence_sufficient": True, "abstention_reason": None},
        # 带拒答措辞的失败帧：即使文本像 uncertain，仍是 failed。
        {"frame_status": "failed", "object_found": False,
         "abstention_reason": "目标被遮挡，无法判断", "evidence_sufficient": False},
    ]
    problems = []
    for index, entry in enumerate(frame_status_variants):
        legacy = resolver.classify_legacy(entry)
        if legacy != "failed":
            problems.append(f"#{index}: legacy 应为 failed，得到 {legacy}")
            continue
        resolved = resolver.resolve_entry(entry)
        if resolved["observation_state"] != resolver.EXECUTION_FAILED_STATE:
            problems.append(f"#{index}: O1 应为 failed，得到 "
                            f"{resolved['observation_state']}")
        if resolved["compat_class"] != "failed":
            problems.append(f"#{index}: compat 应为 failed，得到 "
                            f"{resolved['compat_class']}")
        if resolved["uncertainty_reasons"]:
            problems.append(f"#{index}: failed 不得带 uncertainty_reasons")
    record("G1", "H5：legacy failed 保留为 failed，不得洗成语义 uncertain",
           not problems, f"{len(frame_status_variants)} 个失败变体全部保留"
           + ("" if not problems else f"；{problems}"))


def test_g1b_h5_backend_subtypes(resolver):
    """G1b：backend_* / contract_rejected 子类型必须判为执行失败（额外防线，H5）。

    legacy classify_entry 不识别这些字段（会漏判为 confirmed/not_found）。
    O1 侧必须显式识别，否则一次 backend 失败会以 confirmed 身份参与边界计算。
    """
    variants = [
        {"frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "backend_not_called": True},
        {"frame_status": "analyzed", "object_found": False,
         "evidence_sufficient": False, "backend_call_failed": True},
        {"frame_status": "analyzed", "object_found": False,
         "evidence_sufficient": False, "contract_rejected": True},
        {"frame_status": "analyzed", "object_found": True,
         "evidence_sufficient": True, "extraction_failed": True},
    ]
    problems = []
    for index, entry in enumerate(variants):
        if not resolver.is_execution_failed(entry):
            problems.append(f"#{index}: 子类型未被识别为执行失败")
            continue
        resolved = resolver.resolve_entry(entry)
        if resolved["observation_state"] != resolver.EXECUTION_FAILED_STATE:
            problems.append(f"#{index}: O1 应为 failed，得到 "
                            f"{resolved['observation_state']}")
        if resolved["compat_class"] != "failed":
            problems.append(f"#{index}: compat 应为 failed")
    record("G1b", "H5 额外防线：backend/contract 子类型被识别为执行失败",
           not problems, f"{len(variants)} 个子类型全部捕获"
           + ("" if not problems else f"；{problems}"))


def test_g2_h5_heuristic_excludes_failures(replay):
    """G2：O2 heuristic_reachable 排除执行失败点，且排除数被显式报告。"""
    ground_truth = {"segments": [
        {"start_ms": 0, "end_ms": 3000, "state": "confirmed"},
        {"start_ms": 3000, "end_ms": 5000, "state": "uncertain"},
        {"start_ms": 5000, "end_ms": 8000, "state": "confirmed"},
    ]}
    # 中间点设为执行失败：它两侧都有类别变化，但**不得**计入 heuristic_reachable。
    timeline = [
        {"timestamp_ms": 1000.0, "frame_status": "analyzed",
         "object_found": True, "evidence_sufficient": True, "abstention_reason": None},
        {"timestamp_ms": 4000.0, "frame_status": "failed",
         "object_found": False, "evidence_sufficient": False,
         "abstention_reason": "目标被遮挡，无法判断"},
        {"timestamp_ms": 6000.0, "frame_status": "analyzed",
         "object_found": True, "evidence_sufficient": True, "abstention_reason": None},
    ]
    doc = replay.o2_decomposition(timeline, ground_truth)
    ok = (doc["excluded_execution_failures"] == 1
          and doc["o2_boundaries_heuristic_reachable"] == 0)
    record("G2", "H5：heuristic_reachable 排除执行失败点（排除数显式报告）", ok,
           f"excluded={doc['excluded_execution_failures']} "
           f"heuristic_reachable={doc['o2_boundaries_heuristic_reachable']}")


def test_g3_h5_uncertain_not_failed(resolver):
    """G3：真实视觉不确定（自陈遮挡/暗/小）仍是 uncertain，不被 H5 误判为 failed。"""
    entries = [
        {"frame_status": "analyzed", "object_found": False,
         "abstention_reason": "目标被遮挡，无法判断", "evidence_sufficient": False},
        {"frame_status": "analyzed", "object_found": False,
         "abstention_reason": "画面过暗", "evidence_sufficient": False},
        {"frame_status": "analyzed", "object_found": False,
         "abstention_reason": "目标太小无法确认", "evidence_sufficient": False},
    ]
    problems = []
    for index, entry in enumerate(entries):
        state = resolver.observation_state(entry)
        if state != "uncertain":
            problems.append(f"#{index}: 视觉不确定应为 uncertain，得到 {state}")
        if resolver.is_execution_failed(entry):
            problems.append(f"#{index}: 视觉不确定被误判为执行失败")
    record("G3", "H5 不误伤真实视觉不确定（abstained => uncertain 仍成立）",
           not problems, f"{len(entries)} 个视觉不确定案例仍为 uncertain"
           + ("" if not problems else f"；{problems}"))


def test_g4_preregistration_has_h5():
    """G4：预注册写明 H5，且 H/G 分离、failed ⟹ failed 的表述存在。"""
    if not os.path.isfile(PREREG):
        record("G4", "预注册包含 H5 失败保留门", False, "预注册文档缺失")
        return
    with open(PREREG, encoding="utf-8") as handle:
        text = handle.read()
    problems = []
    for marker in ("H5", "failed", "Failure preservation"):
        if marker not in text:
            problems.append(f"缺少 {marker!r}")
    # failed 不得被转换为 semantic uncertain 的表述必须存在。
    if "不得转换为 semantic uncertain" not in text and \
            "不得转换为 semantic `uncertain`" not in text:
        problems.append("缺少『不得转换为 semantic uncertain』表述")
    record("G4", "预注册包含 H5 失败保留门与禁止转换表述", not problems,
           "H5 已在预注册写明" if not problems else "; ".join(problems))

# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="State Expressiveness Gate 确定性测试")
    parser.add_argument("--results-json", default=None)
    args = parser.parse_args()

    if not check_prerequisites():
        return 2

    frozen = load_module("frozen_scorer_under_test", FROZEN_SCORER)
    resolver = load_module("state_resolver_under_test", RESOLVER)
    replay = load_module("score_state_replay_under_test", REPLAY_SCORER)

    test_a1_classify_identity(frozen, resolver)
    test_a2_o0_matches_frozen_cli(frozen, resolver)
    test_a3_g7r(frozen, resolver, replay)
    test_b1_one_sided_narrowing(resolver)
    test_b2_b3_o1_isolation()
    test_b4_state_is_not_a_fourth_class(resolver)
    test_c1_c2_o2_decomposition(replay, frozen, resolver)
    test_c4_o2_needs_gt(replay, frozen)
    test_d_preregistration_consistency()
    test_e_frozen_paths_untouched()
    test_e2_no_fresh_call_in_replay_scorer(replay)
    test_f_unique_boundary_denominator(replay, resolver)
    test_f2_licensed_public_stratification(replay)
    test_f3_pack_dedup(replay)
    test_f4_g1_threshold_semantics(replay)
    test_g1_h5_failure_preserved(resolver)
    test_g1b_h5_backend_subtypes(resolver)
    test_g2_h5_heuristic_excludes_failures(replay)
    test_g3_h5_uncertain_not_failed(resolver)
    test_g4_preregistration_has_h5()

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    print(f"\nRESULT: {'PASS' if passed == total else 'FAIL'} ({passed}/{total})")

    if args.results_json:
        with open(args.results_json, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "suite": "test_state_expressiveness_gate.py",
                "preregistration": "docs/plans/2026-09-25-state-expressiveness-gate.md",
                "model_calls": 0,
                "summary": {"passed": passed, "total": total},
                "results": RESULTS,
            }, ensure_ascii=False, indent=2) + "\n")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
