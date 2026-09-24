#!/usr/bin/env python3
"""run_task19_baseline.py — Task 19B dev Evidence Pack 三臂真实基线评测执行器（SparkSkill Studio）

预注册协议（artifacts/task-19/preregistration/，阶段 A 提交 e3ef01e 冻结）：
  三臂 uniform / adaptive_coarse_to_fine / coverage_aware_adaptive；同样本三臂相同视频/
  查询/Ground Truth/模型/后端/硬预算/超时/分类规则；样本按 ID 字典序；样本内臂顺序按
  索引循环左移轮换（热状态控制）；批量前一次统一 warm-up（任务 16 冻结 fixture 一帧，
  不计入任何 arm、不使用 dev 标签）；无单侧重试、不删失败样本、不看结果改标签。

流程：
  0) 预注册哈希复核（frozen-hashes.json 全量重算 + 阶段 A 提交 blob 比对）；
  1) 资源门槛（任务书第十节 7 项；任一失败即拒绝执行并保存 blocker）；
  2) 统一 warm-up（一次真实 Qwen 调用，任务 18 fixture，不计入任何 arm）；
  3) 九样本 × 三臂：写 execution manifest（不含标签）+ VisualTaskSpec（校验后执行）
     → trace_temporal.py 真实 Qwen 运行（原始返回存档）→ generate_report.py temporal
     报告 → 指标提取 → 关键帧缩略图（长边 ≤640 JPEG）；
  4) prediction-set.json + run 元数据。

Ground Truth 只在评分阶段（scripts/run_task19_scoring.py）被读取；本执行器不读取
artifacts/task-19/ground-truth/。

用法:
    python3 scripts/run_task19_baseline.py [--out artifacts/task-19] [--timeout 300]
退出码: 0 = 评测执行完成; 1 = 预注册/资源门槛失败或执行器致命错误
"""
import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKILL_SCRIPTS = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                             "scripts")
REPORTER_SCRIPTS = os.path.join(PROJECT_ROOT, ".dsh", "skills", "evidence-report-generator",
                                "scripts")
COMPILER_SCRIPTS = os.path.join(PROJECT_ROOT, ".dsh", "skills", "task-to-skill-compiler",
                                "scripts")
TRACE_TEMPORAL = os.path.join(SKILL_SCRIPTS, "trace_temporal.py")
GENERATE_REPORT = os.path.join(REPORTER_SCRIPTS, "generate_report.py")
ANALYZE_IMAGE = os.path.join(SKILL_SCRIPTS, "analyze_image.py")
EXTRACT_FRAMES = os.path.join(SKILL_SCRIPTS, "extract_frames.py")
VALIDATE_SPEC = os.path.join(COMPILER_SCRIPTS, "validate_task_spec.py")
SPEC_SCHEMA = os.path.join(PROJECT_ROOT, "schemas", "visual-task-spec.schema.json")
TASK19 = os.path.join(PROJECT_ROOT, "artifacts", "task-19")
PREREGISTRATION = os.path.join(TASK19, "preregistration")
INGESTION = os.path.join(TASK19, "ingestion")
PREDICTIONS = os.path.join(TASK19, "predictions")
EXECUTION_MANIFESTS = os.path.join(TASK19, "execution-manifests")
WARMUP_DIR = os.path.join(PREDICTIONS, "_warmup")
# warm-up 使用任务 16 冻结 technical fixture（present-throughout；与 dev 样本和 dev 标签无关）
WARMUP_FIXTURE_VIDEO = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures",
                                    "videos", "fixture-present-throughout.mp4")

PHASE_A_COMMIT = "e3ef01e"
DEFAULT_MODEL = "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest"
ARM_IDS = ["uniform", "adaptive", "coverage"]

# 资源门槛：生成类进程精确模式（与任务 18 runner 同口径）
GENERATION_PATTERNS = (
    "vllm.entrypoints", "vllm serve", "api_server", "DiffusionWorker",
    "h3_lite_api.py", "native_bench.py", "h3-next", "diffusion_service",
)
WEBUI_PATTERNS = (
    "minimax-h3/webui", "h3-studio", "minimax-h3/experiments",
    "minimax-h3/env/webui/bin/python app.py",
)


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def sha256_of(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mem_available_gib():
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 1024.0 / 1024.0, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def port_listening(port):
    result = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True)
    return f":{port} " in result.stdout


def process_matching(patterns):
    result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
    return [line for line in result.stdout.splitlines()
            if any(pattern in line for pattern in patterns) and "grep" not in line]


def ollama_reachable(timeout=5):
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout):
            return True
    except Exception:
        return False


def ollama_loaded_models(timeout=5):
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=timeout) as resp:
            return [item.get("name") for item in json.load(resp).get("models", [])]
    except Exception:
        return None


def verify_preregistration_hashes():
    """预注册哈希一致性（frozen-hashes.json 全量重算 + 阶段 A 提交 blob 比对）。"""
    problems = []
    frozen = load_json(os.path.join(PREREGISTRATION, "frozen-hashes.json"))
    for group in ("preregistration_declarations", "ingestion", "ground_truth",
                  "design_doc", "frozen_scorer_adapter"):
        for key, entry in frozen.get(group, {}).items():
            path = os.path.join(PROJECT_ROOT, entry["path"])
            if not os.path.isfile(path):
                problems.append(f"{group}/{key}: 文件缺失")
            elif sha256_of(path) != entry["sha256"]:
                problems.append(f"{group}/{key}: SHA-256 不一致")
    for name in ("evaluation-plan.json", "arm-configs.json", "verdict-policy.json",
                 "README.md"):
        committed = subprocess.run(
            ["git", "-C", PROJECT_ROOT, "show",
             f"{PHASE_A_COMMIT}:artifacts/task-19/preregistration/{name}"],
            capture_output=True)
        current = open(os.path.join(PREREGISTRATION, name), "rb").read()
        if committed.returncode != 0 or committed.stdout != current:
            problems.append(f"{name}: 与阶段 A 提交 {PHASE_A_COMMIT} 内容不一致")
    return problems


def resource_gate(min_gib=45.0, samples=3):
    """任务书第十节资源门槛；返回 (gate_doc, all_passed)。"""
    checks = {}
    h3_generation = process_matching(GENERATION_PATTERNS)
    port_8000 = port_listening(8000)
    port_8010 = port_listening(8010)
    checks["minimax_h3_stopped"] = {
        "passed": not h3_generation and not port_8000 and not port_8010,
        "evidence": (f":8000 {'有' if port_8000 else '无'}监听；"
                     f":8010 {'有' if port_8010 else '无'}监听；"
                     f"生成类进程 {len(h3_generation)} 个"
                     + (f"（如: {h3_generation[0][:140]}）" if h3_generation else "")),
    }
    webui = process_matching(WEBUI_PATTERNS)
    checks["no_user_active_h3_webui_task"] = {
        "passed": not webui,
        "evidence": (f"用户 MiniMax-H3/WebUI 相关进程 {len(webui)} 个"
                     + (f"（如: {webui[0][:120]}）" if webui else "")),
    }
    readings = []
    for _ in range(samples):
        readings.append(mem_available_gib())
        time.sleep(1)
    checks["mem_available_3x_ge_45gib"] = {
        "passed": all(r is not None and r >= min_gib for r in readings),
        "samples_gib": readings, "threshold_gib": min_gib,
    }
    reachable = ollama_reachable()
    checks["ollama_reachable"] = {
        "passed": reachable,
        "evidence": "GET /api/tags 200" if reachable else "Ollama 不可达",
    }
    loaded = ollama_loaded_models()
    checks["no_external_qwen_consumer"] = {
        "passed": loaded is not None and len(loaded) == 0,
        "evidence": (f"ollama /api/ps 已加载模型: {loaded}" if loaded
                     else "ollama /api/ps 无已加载模型（或不可读）"),
    }
    version = subprocess.run(["dsh", "--version"], capture_output=True, text=True)
    checks["dsh_normal"] = {
        "passed": version.returncode == 0 and "0.1.5" in (version.stdout + version.stderr),
        "evidence": ((version.stdout + version.stderr).strip().splitlines() or ["无输出"])[-1],
    }
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True,
                            text=True, cwd=PROJECT_ROOT)
    locks = [name for name in (".git/index.lock", ".git/HEAD.lock")
             if os.path.exists(os.path.join(PROJECT_ROOT, name))]
    allowed_prefixes = ("artifacts/task-19/", "docs/plans/2026-09-22-dev-evidence-pack",
                        "scripts/task19_ingest.py", "scripts/build_task19_ground_truth.py",
                        "scripts/run_task19_baseline.py", "scripts/run_task19_scoring.py",
                        "scripts/test_task19_dev_pack.py", ".gitignore",
                        "artifacts/task-19/verify_task19.py")
    unexpected = [line for line in status.stdout.splitlines()
                  if line.strip() and not line.startswith("??")
                  and not any(line.strip().lstrip("AMDR").startswith(prefix)
                              or prefix in line for prefix in allowed_prefixes)]
    checks["git_workspace_expected"] = {
        "passed": not locks and not unexpected,
        "evidence": (f"Git 锁: {locks or '无'}；非预期改动: {unexpected or '无'}"
                     f"（{len([l for l in status.stdout.splitlines() if l.strip()])} 个变更项）"),
    }
    hash_problems = verify_preregistration_hashes()
    checks["preregistration_hashes_consistent"] = {
        "passed": not hash_problems,
        "evidence": ("frozen-hashes.json 全部条目重算一致；4 份声明文件与阶段 A 提交 "
                     f"{PHASE_A_COMMIT} 逐字节一致" if not hash_problems
                     else "；".join(hash_problems[:5])),
    }
    all_passed = all(item["passed"] for item in checks.values())

    def sanitize(text):
        return text.replace(os.path.expanduser("~"), "~")

    for item in checks.values():
        if isinstance(item.get("evidence"), str):
            item["evidence"] = sanitize(item["evidence"])
    return {
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "task19_dev_baseline_real_run",
        "checks": checks,
        "all_passed": all_passed,
    }, all_passed


# ---------------------------------------------------------------- execution manifest（不含标签）

FORBIDDEN_LABEL_KEYS = (
    "expected_final_status", "expected_timeline", "difficulty", "ground_truth",
    "segments", "boundary", "boundaries", "scorer", "score", "label", "labels",
    "annotation", "answer", "hint",
)


def build_execution_manifest(sample, arm_id, arm_cfg, budget, link):
    """标签隔离的执行清单：只含样本身份、媒体身份、查询、任务类型、策略与预算、
    安全限制与输出要求。不含任何标签/真值/边界/难度/评分信息。"""
    block = dict(arm_cfg["sampling_strategy_block"])
    block["max_model_calls"] = budget
    return {
        "schema_version": "1.0.0",
        "sample_id": sample["sample_id"],
        "arm_id": arm_id,
        "media": {
            "path": link["repo_relative_link"],
            "sha256": link["media_sha256"],
            "duration_ms": link["measured_duration_ms"],
        },
        "target_query": sample["target_query"],
        "task_type": "temporal_presence_evidence",
        "sampling_strategy": block,
        "safety": {
            "abstain_if_insufficient_evidence": True,
            "forbidden_inferences": ["identity", "age", "nationality", "relationship",
                                     "intent"],
        },
        "output_requirements": ["object_found", "description", "bounding_box",
                                "confidence", "evidence_text", "abstention_reason",
                                "sampling_provenance", "temporal_evidence"],
        "runtime": {
            "vision_backend": "ollama",
            "model": DEFAULT_MODEL,
            "timeout_s": None,  # 由 runner 填充
        },
    }


def build_task_spec(sample, arm_id, block, budget, link):
    """VisualTaskSpec（与 execution manifest 同源，同样不含标签）。"""
    return {
        "task_id": f"task19-dev-{sample['sample_id'].lower()}-{arm_id}",
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_trace",
        "target": {"description": sample["target_query"]},
        "source_media": link["repo_relative_link"],
        "required_outputs": ["object_found", "description", "bounding_box",
                             "confidence", "evidence_text"],
        "constraints": {
            "abstain_if_insufficient_evidence": True,
            "forbidden_inferences": ["identity", "age", "nationality", "relationship",
                                     "intent"],
        },
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
        "sampling_strategy": block,
    }


BLOCK_TO_CLI = {
    "strategy": "--strategy",
    "max_model_calls": "--max-model-calls",
    "initial_coverage_samples": "--initial-coverage-samples",
    "target_boundary_precision_ms": "--target-boundary-precision-ms",
    "max_refinement_rounds": "--max-refinement-rounds",
    "coverage_gap_target_ms": "--coverage-gap-target-ms",
    "coverage_call_reserve": "--coverage-call-reserve",
}


def strategy_cli_args(block, duration_ms, budget):
    """从（预注册冻结的）sampling_strategy 块派生 CLI 参数（确定性派生，避免手抄）。"""
    args = []
    for key, value in block.items():
        if key == "refinement_triggers":
            args += ["--refinement-triggers", ",".join(value)]
        elif key in BLOCK_TO_CLI:
            args += [BLOCK_TO_CLI[key], str(value)]
    if block.get("strategy") == "uniform":
        # 预注册 uniform 政策：interval = duration/budget（网格点超预算 → 区间内均匀
        # 取样，恰好 budget 个点含两端点）
        args += ["--interval-ms", str(round(duration_ms / budget, 6)),
                 "--max-frames", str(budget)]
    return args


def metrics_from(doc, report, elapsed_s):
    provenance = doc.get("sampling_provenance") or {}
    temporal = doc.get("temporal_evidence") or {}
    summary = doc.get("summary") or {}
    timing = provenance.get("timing") or {}
    timeline = doc.get("timeline") or []
    failed_entries = [entry for entry in timeline
                      if entry.get("frame_status") != "analyzed"]
    timeout_like = [entry for entry in failed_entries
                    if "超时" in str(entry.get("abstention_reason") or "")
                    or "timeout" in str(entry.get("abstention_reason") or "").lower()]
    return {
        "strategy": doc.get("sampling_strategy"),
        "final_status": summary.get("overall_status"),
        "actual_model_calls": provenance.get("actual_model_calls"),
        "configured_budget": provenance.get("configured_budget"),
        "budget_exhausted": provenance.get("budget_exhausted"),
        "initial_coverage_calls": provenance.get("initial_coverage_calls"),
        "coverage_exploration_calls": provenance.get("coverage_exploration_calls"),
        "boundary_refinement_calls": provenance.get("boundary_refinement_calls"),
        "max_adjacent_sampling_gap_ms_initial": provenance.get(
            "max_adjacent_sampling_gap_ms_initial"),
        "max_adjacent_sampling_gap_ms_final": provenance.get(
            "max_adjacent_sampling_gap_ms_final"),
        "underobserved_intervals": provenance.get("underobserved_intervals"),
        "stop_reasons": provenance.get("stop_reasons"),
        "class_counts": temporal.get("class_counts"),
        "state_transition_count": temporal.get("state_transition_count"),
        "state_transitions": temporal.get("state_transitions"),
        "max_uncertainty_width_ms": (temporal.get("boundary_uncertainty") or {}).get("max_ms"),
        "target_precision_reached": (temporal.get("boundary_uncertainty") or {}).get(
            "target_precision_reached"),
        "evidence_nature": doc.get("evidence_nature"),
        "resource_blocked": (doc.get("backend") or {}).get("resource_blocked"),
        "sampled_frames": len(timeline),
        "failed_frames": len(failed_entries),
        "timeout_like_failures": len(timeout_like),
        "report_has_temporal_disclaimer": "不是连续跟踪真值" in (report.get("conclusion") or ""),
        "report_has_coverage_statement": "不保证发现任意短事件" in (report.get("conclusion") or ""),
        "wall_time_s": elapsed_s,
        "pipeline_total_ms": timing.get("total_ms"),
    }


def save_thumbnail(evidence_doc, out_dir):
    """关键帧缩略图：首选最早 object_found=true 的分析帧，否则最早分析帧；
    cv2 缩放到长边 ≤640 的 JPEG（小型派生关键帧；全分辨率帧不入库）。"""
    try:
        import cv2
    except ImportError:
        return None
    timeline = evidence_doc.get("timeline") or []
    chosen = None
    for entry in timeline:
        if entry.get("frame_status") == "analyzed" and entry.get("object_found") is True:
            chosen = entry
            break
    if chosen is None:
        for entry in timeline:
            if entry.get("frame_status") == "analyzed":
                chosen = entry
                break
    if chosen is None:
        return None
    frame_path = chosen.get("frame_path")
    if not frame_path or not os.path.isfile(frame_path):
        return None
    image = cv2.imread(frame_path)
    if image is None:
        return None
    height, width = image.shape[:2]
    longest = max(width, height)
    if longest > 640:
        scale = 640.0 / longest
        image = cv2.resize(image, (max(1, int(round(width * scale))),
                                   max(1, int(round(height * scale)))),
                           interpolation=cv2.INTER_AREA)
    out_path = os.path.join(out_dir, "keyframe-thumb.jpg")
    cv2.imwrite(out_path, image, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    return {
        "path": os.path.relpath(out_path, PROJECT_ROOT),
        "source_frame_path": frame_path,
        "source_timestamp_ms": chosen.get("timestamp_ms"),
        "object_found": chosen.get("object_found"),
        "selection_rule": ("earliest_analyzed_confirmed_frame"
                           if chosen.get("object_found") is True
                           else "earliest_analyzed_frame"),
    }


def run_warmup(timeout_s):
    """统一 warm-up：任务 16 冻结 technical fixture 一帧的一次真实 Qwen 调用。
    不计入任何 arm，不使用任何 dev 标签。"""
    os.makedirs(WARMUP_DIR, exist_ok=True)
    frames_dir = os.path.join(WARMUP_DIR, "warmup-frame")
    os.makedirs(frames_dir, exist_ok=True)
    started = time.monotonic()
    extract = subprocess.run(
        [sys.executable, EXTRACT_FRAMES, "--video", WARMUP_FIXTURE_VIDEO,
         "--output-dir", frames_dir, "--interval-ms", "0", "--max-frames", "1",
         "--start-ms", "0", "--end-ms", "1"],
        capture_output=True, text=True)
    frames = sorted(name for name in os.listdir(frames_dir) if name.endswith(".png"))
    if extract.returncode != 0 or not frames:
        record = {"status": "failed", "exit_code": extract.returncode,
                  "wall_time_s": round(time.monotonic() - started, 3),
                  "fixture": os.path.relpath(WARMUP_FIXTURE_VIDEO, PROJECT_ROOT),
                  "error": (extract.stderr or "无帧输出")[-500:],
                  "note": ("统一 warm-up：任务 16 冻结 technical fixture 一帧的一次真实 Qwen 调用；不计入任何 arm 的调用预算，不使用任何 dev 样本或 dev 标签"),
                  "counts_toward_no_arm": True}
        dump_json(os.path.join(WARMUP_DIR, "warmup-record.json"), record)
        return record
    frame_path = os.path.join(frames_dir, frames[0])
    spec = {
        "task_id": "task19-warmup",
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_presence",
        "target": {"description": "红色正方形"},
        "source_media": frame_path,
        "required_outputs": ["object_found", "description", "bounding_box",
                             "confidence", "evidence_text"],
        "constraints": {"abstain_if_insufficient_evidence": True,
                        "forbidden_inferences": ["identity", "age", "nationality",
                                                 "relationship", "intent"]},
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
    }
    spec_path = os.path.join(WARMUP_DIR, "warmup-spec.json")
    dump_json(spec_path, spec)
    evidence_path = os.path.join(WARMUP_DIR, "warmup-evidence.json")
    raw_path = os.path.join(WARMUP_DIR, "warmup-raw.json")
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, ANALYZE_IMAGE, "--task-spec", spec_path, "--image", frame_path,
         "--output", evidence_path, "--save-raw", raw_path, "--timeout", str(timeout_s)],
        capture_output=True, text=True)
    elapsed = round(time.monotonic() - started, 3)
    record = {
        "status": "completed" if proc.returncode == 0 else "failed",
        "exit_code": proc.returncode,
        "wall_time_s": elapsed,
        "fixture": os.path.relpath(WARMUP_FIXTURE_VIDEO, PROJECT_ROOT),
        "note": ("统一 warm-up：任务 16 冻结 technical fixture 一帧的一次真实 Qwen 调用；"
                 "不计入任何 arm 的调用预算，不使用任何 dev 样本或 dev 标签"),
        "counts_toward_no_arm": True,
    }
    if proc.returncode == 0 and os.path.isfile(evidence_path):
        evidence = load_json(evidence_path)
        record["object_found"] = evidence.get("object_found")
        record["confidence"] = evidence.get("confidence")
    else:
        record["stderr_tail"] = (proc.stderr or "")[-500:]
    dump_json(os.path.join(WARMUP_DIR, "warmup-record.json"), record)
    return record


def main():
    parser = argparse.ArgumentParser(description="Task 19B dev 三臂真实基线评测执行器")
    parser.add_argument("--out", default=TASK19, help="artifacts/task-19 目录")
    parser.add_argument("--timeout", type=int, default=300, help="单帧调用超时秒数")
    parser.add_argument("--min-available-gib", type=float, default=45.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="预检：生成 execution manifest 与规格、校验规格、派生 CLI，"
                             "不调用任何模型（用于正式运行前检查）")
    args = parser.parse_args()

    # cv2 解释器保障（无 cv2 时按 skill_env 规则切换到本机已有 OpenCV 的解释器）
    sys.path.insert(0, SKILL_SCRIPTS)
    import skill_env  # noqa: E402
    skill_env.ensure_cv2_interpreter()

    sample_manifest = load_json(os.path.join(PREREGISTRATION, "sample-manifest.json"))
    arm_configs = load_json(os.path.join(PREREGISTRATION, "arm-configs.json"))
    link_map = load_json(os.path.join(INGESTION, "media-link-map.json"))["links"]
    arms = {arm["arm_id"]: arm for arm in arm_configs["arms"]}

    # 0) 预注册哈希复核
    hash_problems = verify_preregistration_hashes()
    if hash_problems:
        print("[预注册复核失败] " + "；".join(hash_problems), file=sys.stderr)
        return 1
    print("[预注册复核] frozen-hashes.json 全量一致；声明文件与阶段 A 提交逐字节一致")

    if args.dry_run:
        print("[dry-run] 生成 execution manifest + 规格并校验（不调用模型）")
        for sample_id in sample_manifest["sample_order"]:
            entry = sample_manifest["samples"][sample_id]
            link = link_map[sample_id]
            budget = entry["budget_max_model_calls"]
            duration = entry["measured_duration_ms"]
            for arm_id in entry["arm_execution_order"]:
                arm_cfg = arms[arm_id]
                block = dict(arm_cfg["sampling_strategy_block"])
                block["max_model_calls"] = budget
                out_dir = os.path.join(PREDICTIONS, sample_id, arm_id)
                os.makedirs(out_dir, exist_ok=True)
                exec_manifest = build_execution_manifest(entry, arm_id, arm_cfg,
                                                         budget, link)
                exec_manifest["runtime"]["timeout_s"] = args.timeout
                exec_dir = os.path.join(EXECUTION_MANIFESTS, sample_id)
                os.makedirs(exec_dir, exist_ok=True)
                dump_json(os.path.join(exec_dir, f"{arm_id}.json"), exec_manifest)
                spec = build_task_spec(entry, arm_id, block, budget, link)
                spec_path = os.path.join(out_dir, "task-spec.json")
                dump_json(spec_path, spec)
                validate = subprocess.run(
                    [sys.executable, VALIDATE_SPEC, "--schema", SPEC_SCHEMA,
                     "--input", spec_path],
                    capture_output=True, text=True)
                cli = " ".join(strategy_cli_args(block, duration, budget))
                ok = validate.returncode == 0
                print(f"  {sample_id}/{arm_id}: spec={'VALID' if ok else 'INVALID'} "
                      f"budget={budget} cli={cli}")
                if not ok:
                    print(validate.stderr[-800:], file=sys.stderr)
                    return 1
        print("[dry-run] 全部 27 个 (样本,臂) 规格校验通过")
        return 0

    # 1) 资源门槛
    print("[资源门槛] 正在核验任务书第十节 7 项条件……")
    gate_doc, gate_passed = resource_gate(min_gib=args.min_available_gib)
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "resource-gate.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(gate_doc, ensure_ascii=False, indent=2) + "\n")
    print(f"[资源门槛] all_passed={gate_passed} "
          f"(mem={gate_doc['checks']['mem_available_3x_ge_45gib']['samples_gib']})")
    if not gate_passed:
        blocked = {
            "task": "task-19b-dev-baseline",
            "status": "resource_blocked",
            "engineering_status": "PARTIAL",
            "resource_gate": gate_doc,
            "note": ("资源门槛不满足：未执行任何真实 Qwen 调用，未执行 DSH 自主会话；"
                     "不虚构模型结果"),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        dump_json(os.path.join(args.out, "run-blocker.json"), blocked)
        print("[资源阻塞] 真实评测未执行（详见 artifacts/task-19/resource-gate.json）")
        return 1

    # 2) 统一 warm-up
    print("[warm-up] 任务 16 冻结 fixture 一帧（不计入任何 arm，不使用 dev 标签）……")
    warmup = run_warmup(args.timeout)
    print(f"[warm-up] status={warmup['status']} 耗时={warmup['wall_time_s']}s")

    # 3) 九样本 × 三臂（样本内臂顺序按预注册轮换）
    run_doc = {
        "task": "task-19b-dev-baseline",
        "mode": "real",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": DEFAULT_MODEL + "（本地 Ollama）",
        "timeout_s": args.timeout,
        "warmup": warmup,
        "fairness": {
            "same_video": True,
            "same_target_query": "逐样本取自卡片（execution manifest 与 spec 同源）",
            "same_ground_truth": "artifacts/task-19/ground-truth/（评分阶段才读取）",
            "same_model": DEFAULT_MODEL + "（本地 Ollama）",
            "same_status_rules": "同一 trace_temporal.py 代码路径与 frame_class 分类规则",
            "same_scorer": ("scripts/score_temporal_ground_truth.py（任务 17 冻结）"
                            "+ scripts/task18_scorer_adapter.py（任务 18 适配层）"),
            "same_timeout_s": args.timeout,
            "execution_order": ("样本按 ID 字典序；样本内臂顺序按索引循环左移轮换"
                                "（预注册 arm_order_rotation）"),
            "no_single_side_retry": True,
            "no_sample_removal": True,
            "ground_truth_not_modified_after_results": True,
        },
        "samples": {},
    }
    prediction_arms = {arm_id: [] for arm_id in ARM_IDS}
    total_calls = 0
    total_failures = 0
    for sample_id in sample_manifest["sample_order"]:
        entry = sample_manifest["samples"][sample_id]
        link = link_map[sample_id]
        budget = entry["budget_max_model_calls"]
        duration = entry["measured_duration_ms"]
        print(f"[样本] {sample_id}（{entry['track']}；时长 {duration}ms；预算 {budget}；"
              f"臂顺序 {'→'.join(entry['arm_execution_order'])}）")
        sample_doc = {"track": entry["track"], "budget": budget,
                      "duration_ms": duration, "arm_execution_order":
                      entry["arm_execution_order"], "arms": {}}
        for arm_id in entry["arm_execution_order"]:
            arm_cfg = arms[arm_id]
            block = dict(arm_cfg["sampling_strategy_block"])
            block["max_model_calls"] = budget
            out_dir = os.path.join(PREDICTIONS, sample_id, arm_id)
            os.makedirs(out_dir, exist_ok=True)
            exec_manifest = build_execution_manifest(entry, arm_id, arm_cfg, budget, link)
            exec_manifest["runtime"]["timeout_s"] = args.timeout
            exec_dir = os.path.join(EXECUTION_MANIFESTS, sample_id)
            os.makedirs(exec_dir, exist_ok=True)
            exec_path = os.path.join(exec_dir, f"{arm_id}.json")
            dump_json(exec_path, exec_manifest)
            spec = build_task_spec(entry, arm_id, block, budget, link)
            spec_path = os.path.join(out_dir, "task-spec.json")
            dump_json(spec_path, spec)

            # 规格校验（预检；失败即该臂执行失败，不重试）
            validate = subprocess.run(
                [sys.executable, VALIDATE_SPEC, "--schema", SPEC_SCHEMA,
                 "--input", spec_path],
                capture_output=True, text=True)
            if validate.returncode != 0:
                sample_doc["arms"][arm_id] = {
                    "execution_status": "failed",
                    "failure": "spec_validation_failed",
                    "stderr_tail": (validate.stderr or "")[-800:],
                    "artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                }
                total_failures += 1
                print(f"  [{arm_id}] 规格校验失败（未执行模型调用）")
                continue

            evidence_path = os.path.join(out_dir, "temporal-evidence.json")
            report_path = os.path.join(out_dir, "temporal-report.json")
            cmd = [sys.executable, TRACE_TEMPORAL,
                   "--task-spec", spec_path, "--output", evidence_path,
                   "--timeout", str(args.timeout),
                   "--input-nature", "user_media",
                   "--save-raw-dir", os.path.join(out_dir, "raw")]
            cmd += strategy_cli_args(block, duration, budget)
            started = time.monotonic()
            subprocess_timeout = budget * args.timeout + 600
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=subprocess_timeout)
                returncode = proc.returncode
                stderr_tail = (proc.stderr or "")[-1500:]
            except subprocess.TimeoutExpired as error:
                returncode = -9
                raw_stderr = error.stderr
                if isinstance(raw_stderr, bytes):
                    stderr_tail = raw_stderr.decode("utf-8", "replace")[-1500:]
                else:
                    stderr_tail = str(raw_stderr or "")[-1500:]
            elapsed = round(time.monotonic() - started, 3)

            if returncode != 0 or not os.path.isfile(evidence_path):
                sample_doc["arms"][arm_id] = {
                    "execution_status": "failed",
                    "failure": "trace_temporal_failed",
                    "exit_code": returncode,
                    "stderr_tail": stderr_tail,
                    "wall_time_s": elapsed,
                    "artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                }
                total_failures += 1
                print(f"  [{arm_id}] 执行失败（exit={returncode}；不重试，原样保存）")
                continue

            doc = load_json(evidence_path)
            report_proc = subprocess.run(
                [sys.executable, GENERATE_REPORT, "--task-spec", spec_path,
                 "--evidence", evidence_path, "--output", report_path,
                 "--mode", "temporal"],
                capture_output=True, text=True)
            if report_proc.returncode != 0:
                sample_doc["arms"][arm_id] = {
                    "execution_status": "failed",
                    "failure": "report_generation_failed",
                    "stderr_tail": (report_proc.stderr or "")[-800:],
                    "wall_time_s": elapsed,
                    "artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                }
                total_failures += 1
                print(f"  [{arm_id}] 报告生成失败（不重试，原样保存）")
                continue
            report = load_json(report_path)
            metrics = metrics_from(doc, report, elapsed)
            thumbnail = save_thumbnail(doc, out_dir)
            if thumbnail:
                metrics["keyframe_thumb"] = thumbnail
            sample_doc["arms"][arm_id] = {
                "execution_status": "completed",
                "metrics": metrics,
                "artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
            }
            prediction_arms[arm_id].append({
                "sample_id": sample_id,
                "evidence": os.path.relpath(evidence_path, PREDICTIONS),
            })
            calls = metrics.get("actual_model_calls") or 0
            total_calls += calls
            print(f"  [{arm_id}] 状态={metrics['final_status']} 调用={calls}/{budget} "
                  f"覆盖={metrics['coverage_exploration_calls']} "
                  f"细化={metrics['boundary_refinement_calls']} "
                  f"最大间隔={metrics['max_adjacent_sampling_gap_ms_final']}ms "
                  f"转换={metrics['state_transition_count']} "
                  f"失败帧={metrics['failed_frames']} 停止={metrics['stop_reasons']}")
        run_doc["samples"][sample_id] = sample_doc

    prediction_set = {
        "schema_version": "1.0.0",
        "pack_id": "task19-dev-pack-v1",
        "arms": [{"arm_id": arm_id, "samples": prediction_arms[arm_id]}
                 for arm_id in ARM_IDS],
    }
    dump_json(os.path.join(PREDICTIONS, "prediction-set.json"), prediction_set)

    run_doc["totals"] = {
        "sample_arm_runs": sum(len(sample["arms"]) for sample in run_doc["samples"].values()),
        "failed_sample_arm_runs": total_failures,
        "total_real_model_calls": total_calls,
        "warmup_calls": 1 if warmup.get("status") == "completed" else 0,
    }
    dump_json(os.path.join(PREDICTIONS, "run-metadata.json"), run_doc)
    print(f"\n[执行完成] {run_doc['totals']['sample_arm_runs']} 个 (样本,臂) 运行，"
          f"失败 {total_failures} 个；真实模型调用合计 {total_calls} 次"
          f"（不含 warm-up {run_doc['totals']['warmup_calls']} 次）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
