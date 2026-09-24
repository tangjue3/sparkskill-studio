#!/usr/bin/env python3
"""run_task18_comparison.py — 任务 18 三臂评测执行器（SparkSkill Studio）

预注册协议（artifacts/task-18/preregistration/，阶段 A 冻结）：
  三臂 uniform / adaptive_coarse_to_fine / coverage_aware_adaptive，相同媒体/查询/
  Ground Truth/模型/预算/超时/分类规则；场景按预注册顺序；场景内臂顺序固定
  uniform → adaptive → coverage；无单侧重试、不删失败场景、不看结果改标签。

两种模式：
  --mode replay   deterministic replay：全部场景 × 3 臂，构造证据
                  （evidence_nature=constructed_fixture_evidence，按冻结 Ground Truth
                  确定性生成帧级证据；零模型调用；逐字节可复算）；
  --mode real     真实本地 Qwen 小样本评测：先执行 8 项资源门槛，通过后才对全部
                  场景 × 3 臂各运行一次（subprocess trace_temporal.py，真实模型调用，
                  保存原始返回）；门槛不满足则拒绝执行并保留结构化 blocker。

两种模式都经 task18_scorer_adapter.py（任务 17 冻结评分器兼容适配层）评分：
七类采样点计数、事件覆盖、边界匹配、效率指标、maximum sampling gap、两两 fairness
gate + verdict、pack 级三臂 verdict（全部由预注册 verdict-policy.json 规则计算）。

用法:
    python3 scripts/run_task18_comparison.py --mode replay [--out artifacts/task-18]
    python3 scripts/run_task18_comparison.py --mode real [--budget 12] [--timeout 300]
退出码: 0 = 评测完成; 1 = 前置校验/资源门槛/执行失败
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
TRACE_TEMPORAL = os.path.join(SKILL_SCRIPTS, "trace_temporal.py")
GENERATE_REPORT = os.path.join(REPORTER_SCRIPTS, "generate_report.py")
ADAPTER = os.path.join(PROJECT_ROOT, "scripts", "task18_scorer_adapter.py")
FIXTURE_GENERATOR = os.path.join(PROJECT_ROOT, "scripts", "generate_task18_fixtures.py")
PREREGISTRATION = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "preregistration")
TASK18_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "fixtures")
TASK16_FIXTURES = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures")
CONTRACTS = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "contracts")

TARGET_QUERY = "红色正方形"
TARGET_ATTRIBUTES = ["红色", "正方形"]
DEFAULT_MODEL = "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest"


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- 资源门槛（任务书第十二节）

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


# 生成类进程精确模式（排除 tmux 会话名/ shell 包装等误报）
GENERATION_PATTERNS = (
    "vllm.entrypoints", "vllm serve", "api_server", "DiffusionWorker",
    "h3_lite_api.py", "native_bench.py", "h3-next", "diffusion_service",
)
# 用户 MiniMax-H3/WebUI 相关进程模式
WEBUI_PATTERNS = (
    "minimax-h3/webui", "h3-studio", "minimax-h3/experiments",
    "minimax-h3/env/webui/bin/python app.py",
)


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
    """预注册哈希一致性（frozen-hashes.json 全量重算 + 阶段 A 提交 blob 比对 +
    fixture 冻结复核）。与 test_task18_coverage_sampling.py C35 同口径。"""
    import hashlib
    problems = []
    frozen_path = os.path.join(PREREGISTRATION, "frozen-hashes.json")
    if not os.path.isfile(frozen_path):
        return ["缺少 frozen-hashes.json"]
    frozen = load_json(frozen_path)
    for group in ("preregistration_declarations", "preregistration_data", "fixtures",
                  "ground_truth", "contracts", "design_doc"):
        for key, entry in frozen.get(group, {}).items():
            path = os.path.join(PROJECT_ROOT, entry["path"])
            if not os.path.isfile(path):
                problems.append(f"{group}/{key}: 文件缺失")
                continue
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != entry["sha256"]:
                problems.append(f"{group}/{key}: SHA-256 不一致")
    for name in ("evaluation-plan.json", "arm-configs.json", "verdict-policy.json",
                 "README.md"):
        committed = subprocess.run(
            ["git", "-C", PROJECT_ROOT, "show",
             f"dcaf324:artifacts/task-18/preregistration/{name}"],
            capture_output=True)
        current = open(os.path.join(PREREGISTRATION, name), "rb").read()
        if committed.returncode != 0 or committed.stdout != current:
            problems.append(f"{name}: 与阶段 A 提交 dcaf324 内容不一致")
    verify = subprocess.run([sys.executable, FIXTURE_GENERATOR, "--verify"],
                            capture_output=True, text=True)
    if verify.returncode != 0:
        problems.append("fixture 冻结复核失败")
    return problems


def resource_gate(min_gib=45.0, samples=3):
    """任务书第十二节 8 项资源门槛；返回 (gate_doc, all_passed)。"""
    checks = {}

    h3_generation = process_matching(GENERATION_PATTERNS)
    port_8000 = port_listening(8000)
    port_8010 = port_listening(8010)
    checks["minimax_h3_no_generation_task"] = {
        "passed": not h3_generation and not port_8000,
        "evidence": (f":8000 {'有' if port_8000 else '无'}监听；"
                     f":8010（h3-lite 实验 API）{'有' if port_8010 else '无'}监听；"
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
        "samples_gib": readings,
        "threshold_gib": min_gib,
    }
    reachable = ollama_reachable()
    checks["ollama_reachable"] = {
        "passed": reachable,
        "evidence": "GET /api/tags 200" if reachable else "Ollama 不可达",
    }
    loaded = ollama_loaded_models()
    checks["no_external_qwen_consumer"] = {
        "passed": loaded is not None and len(loaded) == 0,
        "evidence": (f"ollama /api/ps 已加载模型: {loaded}"
                     if loaded else "ollama /api/ps 无已加载模型（或不可读）"),
    }
    version = subprocess.run(["dsh", "--version"], capture_output=True, text=True)
    checks["dsh_normal"] = {
        "passed": version.returncode == 0 and "0.1.5" in (version.stdout + version.stderr),
        "evidence": (version.stdout + version.stderr).strip().splitlines()[-1]
        if (version.stdout + version.stderr).strip() else "dsh --version 无输出",
    }
    status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                            cwd=PROJECT_ROOT)
    locks = [name for name in (".git/index.lock", ".git/HEAD.lock")
             if os.path.exists(os.path.join(PROJECT_ROOT, name))]
    unexpected = [line for line in status.stdout.splitlines()
                  if line.strip() and not line.startswith("??")
                  and "artifacts/task-18/" not in line
                  and "docs/plans/2026-09-22-coverage-aware" not in line
                  and "scripts/generate_task18_fixtures.py" not in line
                  and "scripts/task18_scorer_adapter.py" not in line
                  and "scripts/run_task18_comparison.py" not in line
                  and "schemas/visual-task-spec.schema.json" not in line
                  and "validate_task_spec.py" not in line
                  and "adaptive_sampler.py" not in line
                  and "trace_temporal.py" not in line
                  and "generate_report.py" not in line
                  and "README.md" not in line and "PROJECT_CONTEXT.md" not in line
                  and "BENCHMARK.md" not in line and "docs/" not in line
                  and ".dsh/skills/" not in line]
    checks["git_workspace_expected"] = {
        "passed": not locks and not unexpected,
        "evidence": (f"Git 锁: {locks or '无'}；非预期改动: {unexpected or '无'}"
                     f"（{len([l for l in status.stdout.splitlines() if l.strip()])} 个变更项）"),
    }
    hash_problems = verify_preregistration_hashes()
    checks["preregistration_hashes_consistent"] = {
        "passed": not hash_problems,
        "evidence": ("frozen-hashes.json 全部条目重算一致；4 份声明文件与阶段 A 提交 "
                     "dcaf324 逐字节一致；fixture 冻结复核 FROZEN_OK"
                     if not hash_problems else "；".join(hash_problems[:5])),
    }
    all_passed = all(item["passed"] for item in checks.values())

    def sanitize(text):
        # 证据文本中的用户 home 绝对路径替换为 ~（保留可识别性，避免提交绝对用户路径）
        return text.replace(os.path.expanduser("~"), "~")

    for item in checks.values():
        if isinstance(item.get("evidence"), str):
            item["evidence"] = sanitize(item["evidence"])
    return {
        "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "scope": "real_qwen_run",
        "checks": checks,
        "all_passed": all_passed,
    }, all_passed


# ---------------------------------------------------------------- 构造证据分析器（replay 专用）

def state_at(segments, timestamp_ms):
    for segment in segments:
        if segment["start_ms"] <= timestamp_ms < segment["end_ms"]:
            return segment["state"]
    return segments[-1]["state"] if segments else "absent"


def make_scripted_analyzer(segments_by_video):
    """按冻结 Ground Truth 时间轴确定性生成帧级构造证据（规则回放专用）。

    这是构造结构化证据，不是模型输出：trace_temporal 将其标记为
    evidence_nature=constructed_fixture_evidence，不计为 Qwen 调用。
    Ground Truth 只用于“模拟一个忠实模型的输出”，不参与采样点选择。
    """
    def analyze(spec, frame):
        video_stem = None
        for stem in segments_by_video:
            if stem in os.path.basename(frame["frame_path"]):
                video_stem = stem
                break
        segments = segments_by_video.get(video_stem, [])
        timestamp_ms = frame["timestamp_ms"]
        state = state_at(segments, timestamp_ms)
        if state == "absent":
            return {
                "timestamp_ms": timestamp_ms, "frame_path": frame["frame_path"],
                "object_found": False, "description": "构造证据：画面中无红色正方形",
                "bounding_box": None, "bounding_box_raw": None,
                "bounding_box_source_format": None,
                "bounding_box_normalization_applied": False,
                "frame_width": None, "frame_height": None, "confidence": 0.9,
                "evidence_text": "构造证据（规则测试回放，非模型输出）",
                "abstention_reason": None, "frame_status": "analyzed",
                "evidence_sufficient": False, "gaps": ["目标未被确认存在"],
                "warnings": [],
            }
        if state == "present_low_contrast":
            return {
                "timestamp_ms": timestamp_ms, "frame_path": frame["frame_path"],
                "object_found": False,
                "description": "构造证据：低对比度区间，无法可靠确认",
                "bounding_box": None, "bounding_box_raw": None,
                "bounding_box_source_format": None,
                "bounding_box_normalization_applied": False,
                "frame_width": None, "frame_height": None, "confidence": 0.3,
                "evidence_text": "构造证据（规则测试回放，非模型输出）",
                "abstention_reason": "目标对比度过低，无法可靠确认（构造拒答）",
                "frame_status": "analyzed", "evidence_sufficient": False,
                "gaps": ["证据不足，无法可靠确认"], "warnings": [],
            }
        return {
            "timestamp_ms": timestamp_ms, "frame_path": frame["frame_path"],
            "object_found": True, "description": "构造证据：红色正方形出现",
            "bounding_box": [0.44, 0.39, 0.56, 0.61], "bounding_box_raw": None,
            "bounding_box_source_format": "normalized",
            "bounding_box_normalization_applied": False,
            "frame_width": None, "frame_height": None, "confidence": 0.95,
            "evidence_text": "构造证据（规则测试回放，非模型输出）",
            "abstention_reason": None, "frame_status": "analyzed",
            "evidence_sufficient": True, "gaps": [], "warnings": [],
        }
    return analyze


# ---------------------------------------------------------------- 规格与场景

def base_spec(task_id, video, sampling_strategy):
    return {
        "task_id": task_id,
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_trace",
        "target": {"description": TARGET_QUERY, "attributes": TARGET_ATTRIBUTES},
        "source_media": video,
        "required_outputs": ["object_found", "description", "bounding_box",
                             "confidence", "evidence_text"],
        "constraints": {
            "abstain_if_insufficient_evidence": True,
            "forbidden_inferences": ["identity", "age", "nationality",
                                     "relationship", "intent"],
        },
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
        "sampling_strategy": sampling_strategy,
    }


def load_scenarios():
    """从预注册 fixture-manifest 读取场景（唯一事实来源）。"""
    manifest = load_json(os.path.join(PREREGISTRATION, "fixture-manifest.json"))
    arm_configs = load_json(os.path.join(PREREGISTRATION, "arm-configs.json"))
    arms = {arm["arm_id"]: arm for arm in arm_configs["arms"]}
    scenarios = []
    for sample_id in manifest["scenario_order"]:
        entry = manifest["scenarios"][sample_id]
        scenarios.append({
            "sample_id": sample_id,
            "video": os.path.join(PROJECT_ROOT, entry["media_path"]),
            # spec 中的 source_media 使用仓库相对路径（媒体安全校验以项目根解析；
            # 执行期 FrameSampler 仍会 abspath，产物 source_video/frame_path 的绝对
            # 路径属帧可追溯审计轨迹，与任务 16 已提交产物惯例一致）
            "spec_media": entry["media_path"],
            "budget": entry["max_model_calls_all_arms"],
            "category": entry["category"],
        })
    return scenarios, arms


def arm_strategy_block(arm, budget):
    """按场景预算派生臂配置。

    主对照预算（12）下直接使用预注册冻结参数。预算不足场景（预注册
    tight_budget_override：三臂统一预算 6，注记“adaptive/coverage 初始覆盖 4
    + 仅 2 次后续调用”）下，把初始覆盖与覆盖储备压到预算内：
      initial_eff = min(冻结 initial, budget)
      reserve_eff = min(冻结 reserve, budget − initial_eff)
    该派生是执行层实现，不修改任何预注册文件；主对照（同预算）参数逐字冻结。
    """
    block = dict(arm["sampling_strategy_block"])
    block["max_model_calls"] = budget
    if "initial_coverage_samples" in block:
        initial_eff = min(block["initial_coverage_samples"], budget)
        block["initial_coverage_samples"] = initial_eff
    if "coverage_call_reserve" in block:
        block["coverage_call_reserve"] = min(
            block["coverage_call_reserve"], budget - block["initial_coverage_samples"])
    return block


# sampling_strategy 块键 → trace_temporal.py CLI 参数（确定性派生，避免手抄）
BLOCK_TO_CLI = {
    "strategy": "--strategy",
    "max_model_calls": "--max-model-calls",
    "initial_coverage_samples": "--initial-coverage-samples",
    "target_boundary_precision_ms": "--target-boundary-precision-ms",
    "max_refinement_rounds": "--max-refinement-rounds",
    "coverage_gap_target_ms": "--coverage-gap-target-ms",
    "coverage_call_reserve": "--coverage-call-reserve",
}


def strategy_cli_args(block):
    """从（预注册冻结的）sampling_strategy 块派生 CLI 参数。"""
    args = []
    for key, value in block.items():
        if key == "refinement_triggers":
            args += ["--refinement-triggers", ",".join(value)]
        elif key in BLOCK_TO_CLI:
            args += [BLOCK_TO_CLI[key], str(value)]
    if block.get("strategy") == "uniform":
        arm_configs = load_json(os.path.join(PREREGISTRATION, "arm-configs.json"))
        shared = arm_configs["shared"]
        args += ["--interval-ms", str(shared["uniform_interval_ms"]),
                 "--max-frames", str(shared["uniform_max_frames"])]
    return args


def segments_for_video(video_path):
    """视频文件名 → 冻结 GT segments（任务 18 新 fixture 或任务 16 复用 fixture）。"""
    name = os.path.basename(video_path)
    t18_gt = load_json(os.path.join(TASK18_FIXTURES, "ground-truth.json"))
    for fixture in t18_gt["fixtures"].values():
        if fixture["file"] == name:
            return fixture["segments"]
    t16_gt = load_json(os.path.join(TASK16_FIXTURES, "ground-truth.json"))
    for fixture in t16_gt["fixtures"].values():
        if fixture["file"] == name:
            return fixture["segments"]
    raise SystemExit(f"[错误] 找不到 fixture 的冻结 ground truth: {name}")


# ---------------------------------------------------------------- 指标提取

def metrics_from(doc, report, elapsed_s):
    provenance = doc.get("sampling_provenance") or {}
    temporal = doc.get("temporal_evidence") or {}
    summary = doc.get("summary") or {}
    timing = provenance.get("timing") or {}
    actual_calls = provenance.get("actual_model_calls", 0)
    return {
        "strategy": doc.get("sampling_strategy"),
        "final_status": summary.get("overall_status"),
        "actual_model_calls": actual_calls,
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
        "report_has_temporal_disclaimer": "不是连续跟踪真值" in (report.get("conclusion") or ""),
        "report_has_coverage_statement": "不保证发现任意短事件" in (report.get("conclusion") or ""),
        "resource_blocked": doc.get("backend", {}).get("resource_blocked"),
        "wall_time_s": elapsed_s,
        "pipeline_total_ms": timing.get("total_ms"),
    }


def run_report(spec_path, evidence_path, report_path):
    proc = subprocess.run(
        [sys.executable, GENERATE_REPORT,
         "--task-spec", spec_path, "--evidence", evidence_path,
         "--output", report_path, "--mode", "temporal"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"[错误] 报告生成失败:\n{proc.stderr[-2000:]}")
    return load_json(report_path)


# ---------------------------------------------------------------- 主流程

def main():
    parser = argparse.ArgumentParser(description="任务 18 三臂评测执行器")
    parser.add_argument("--mode", choices=["replay", "real"], required=True,
                        help="replay=确定性构造证据回放（零模型调用）；real=真实 Qwen（需资源门槛）")
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "artifacts", "task-18"),
                        help="artifacts/task-18 目录")
    parser.add_argument("--budget", type=int, default=None,
                        help="覆盖预注册主对照预算（默认按预注册：12/6）")
    parser.add_argument("--timeout", type=int, default=300, help="单帧调用超时秒数")
    parser.add_argument("--min-available-gib", type=float, default=45.0,
                        help="资源门槛：MemAvailable 阈值（GiB，任务书要求 45）")
    args = parser.parse_args()

    # 0) fixture 冻结复核（评测前必须通过）
    verify = subprocess.run([sys.executable, FIXTURE_GENERATOR, "--verify"],
                            capture_output=True, text=True)
    if verify.returncode != 0:
        print(verify.stderr, file=sys.stderr)
        return 1
    print(f"[fixture 冻结复核] {verify.stdout.strip()}")

    scenarios, arms = load_scenarios()
    if args.budget is not None:
        for scenario in scenarios:
            scenario["budget"] = args.budget

    out_root = args.out
    if args.mode == "replay":
        run_dir = os.path.join(out_root, "deterministic")
        evidence_nature = "constructed_fixture_evidence"
        gate_doc = {
            "recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "scope": "deterministic_replay",
            "note": ("deterministic replay 不调用任何视觉模型（构造证据回放），"
                     "不适用真实 Qwen 资源门槛；模型调用数=0"),
            "model_calls": 0,
            "checks": {},
            "all_passed": True,
        }
    else:
        run_dir = os.path.join(out_root, "real-qwen")
        evidence_nature = "real_model_output"
        print("[资源门槛] 正在核验任务书第十二节 8 项条件……")
        gate_doc, gate_passed = resource_gate(min_gib=args.min_available_gib)
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(out_root, "resource-gate.json"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(gate_doc, ensure_ascii=False, indent=2) + "\n")
        print(f"[资源门槛] all_passed={gate_passed} "
              f"(mem={gate_doc['checks']['mem_available_3x_ge_45gib']['samples_gib']})")
        if not gate_passed:
            blocked = {
                "task": "task-18-three-arm-comparison",
                "status": "resource_blocked",
                "final_status": "PARTIAL_RESOURCE_BLOCKED",
                "resource_gate": gate_doc,
                "note": ("资源门槛不满足：未执行任何真实 Qwen 调用，未执行 DSH 自主演示；"
                         "deterministic replay 与规则测试结果不受影响；不虚构模型结果"),
                "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            with open(os.path.join(run_dir, "comparison.json"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps(blocked, ensure_ascii=False, indent=2) + "\n")
            print("[资源阻塞] 真实 Qwen 评测未执行（详见 artifacts/task-18/resource-gate.json）")
            return 1

    os.makedirs(run_dir, exist_ok=True)
    if args.mode == "replay":
        with open(os.path.join(out_root, "resource-gate.json"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(gate_doc, ensure_ascii=False, indent=2) + "\n")

    sys.path.insert(0, SKILL_SCRIPTS)
    import skill_env  # noqa: E402
    skill_env.ensure_cv2_interpreter()
    trace_temporal = load_module("trace_temporal", TRACE_TEMPORAL)

    comparison = {
        "task": "task-18-three-arm-comparison",
        "mode": args.mode,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "input_nature": ("constructed_fixture_replay" if args.mode == "replay"
                         else "real_qwen_model_output_on_synthetic_technical_fixture"),
        "evidence_nature": evidence_nature,
        "fairness": {
            "same_video": True,
            "same_target_query": TARGET_QUERY,
            "same_model": DEFAULT_MODEL + "（本地 Ollama）" if args.mode == "real"
            else "构造证据生成器（replay，非模型）",
            "same_status_rules": "同一 trace_temporal.py 代码路径与 frame_class 分类规则",
            "same_ground_truth": "artifacts/task-18/contracts/ground-truth/（冻结）",
            "same_scorer": "scripts/score_temporal_ground_truth.py（任务 17 冻结）"
                           "+ scripts/task18_scorer_adapter.py（内存扩展策略白名单）",
            "same_timeout_s": args.timeout,
            "execution_order": "场景按预注册 scenario_order；场景内臂顺序 uniform→adaptive→coverage",
            "no_single_side_retry": True,
            "no_sample_removal": True,
            "ground_truth_not_modified_after_results": True,
            "tier3_untouched": True,
        },
        "scenarios": {},
    }

    prediction_arms = {arm_id: [] for arm_id in ("uniform", "adaptive", "coverage")}
    for scenario in scenarios:
        sample_id = scenario["sample_id"]
        video = scenario["video"]
        budget = scenario["budget"]
        segments = segments_for_video(video)
        analyzer = make_scripted_analyzer({os.path.splitext(os.path.basename(video))[0]:
                                           segments})
        print(f"[场景] {sample_id}（预算 {budget}）")
        scenario_doc = {"fixture": os.path.basename(video), "budget": budget,
                        "category": scenario["category"], "arms": {}}
        for arm_id in ("uniform", "adaptive", "coverage"):
            arm = arms[arm_id]
            block = arm_strategy_block(arm, budget)
            spec = base_spec(f"task18-cmp-{sample_id}-{arm_id}",
                             scenario["spec_media"], block)
            out_dir = os.path.join(run_dir, sample_id, arm_id)
            os.makedirs(out_dir, exist_ok=True)
            spec_path = os.path.join(out_dir, "task-spec.json")
            with open(spec_path, "w", encoding="utf-8") as handle:
                json.dump(spec, handle, ensure_ascii=False)
            evidence_path = os.path.join(out_dir, "temporal-evidence.json")
            report_path = os.path.join(out_dir, "temporal-report.json")
            started = time.monotonic()
            uniform_planning = {}
            if block.get("strategy") == "uniform":
                shared = load_json(os.path.join(PREREGISTRATION, "arm-configs.json"))["shared"]
                uniform_planning = {"interval_ms": shared["uniform_interval_ms"],
                                    "max_frames": shared["uniform_max_frames"]}
            if args.mode == "replay":
                doc = trace_temporal.trace_temporal(
                    spec, evidence_path, allow_low_memory=True, analyze_fn=analyzer,
                    input_nature="technical_fixture",
                    frames_dir=os.path.join(out_dir, "frames"), **uniform_planning)
            else:
                cmd = [sys.executable, TRACE_TEMPORAL,
                       "--task-spec", spec_path, "--output", evidence_path,
                       "--timeout", str(args.timeout),
                       "--input-nature", "technical_fixture",
                       "--save-raw-dir", os.path.join(out_dir, "raw")]
                cmd += strategy_cli_args(block)
                proc = subprocess.run(cmd, capture_output=True, text=True)
                if proc.returncode != 0:
                    raise SystemExit(
                        f"[错误] {sample_id}/{arm_id} 执行失败（exit={proc.returncode}）:\n"
                        f"{proc.stderr[-2000:]}")
                doc = load_json(evidence_path)
            elapsed = round(time.monotonic() - started, 3)
            report = run_report(spec_path, evidence_path, report_path)
            metrics = metrics_from(doc, report, elapsed)
            scenario_doc["arms"][arm_id] = {
                "artifacts_dir": os.path.relpath(out_dir, PROJECT_ROOT),
                "metrics": metrics,
            }
            prediction_arms[arm_id].append({
                "sample_id": sample_id,
                "evidence": os.path.relpath(evidence_path, run_dir),
            })
            print(f"  [{arm_id}] 状态={metrics['final_status']} "
                  f"调用={metrics['actual_model_calls']}/{budget} "
                  f"覆盖探索={metrics['coverage_exploration_calls']} "
                  f"细化={metrics['boundary_refinement_calls']} "
                  f"最大间隔={metrics['max_adjacent_sampling_gap_ms_final']}ms "
                  f"转换={metrics['state_transition_count']} "
                  f"停止={metrics['stop_reasons']}")
        comparison["scenarios"][sample_id] = scenario_doc

    # ---- prediction-set + 适配层评分
    prediction_set = {
        "schema_version": "1.0.0",
        "pack_id": "task18-technical-fixtures",
        "arms": [{"arm_id": arm_id, "samples": prediction_arms[arm_id]}
                 for arm_id in ("uniform", "adaptive", "coverage")],
    }
    prediction_path = os.path.join(run_dir, "prediction-set.json")
    with open(prediction_path, "w", encoding="utf-8") as handle:
        json.dump(prediction_set, handle, ensure_ascii=False, indent=2)

    # 比较样本范围 = 预注册 fixture-manifest 中 in_same_budget_main_comparison=true
    # 的场景（预算不足场景只评分不比较；verdict-policy.json 预注册规则）
    pre_manifest = load_json(os.path.join(PREREGISTRATION, "fixture-manifest.json"))
    same_budget_ids = [sample_id for sample_id in pre_manifest["scenario_order"]
                       if pre_manifest["scenarios"][sample_id][
                           "in_same_budget_main_comparison"]]
    adapter_proc = subprocess.run(
        [sys.executable, ADAPTER,
         "--manifest", os.path.join(CONTRACTS, "task18-fixture-evidence-pack-manifest.json"),
         "--predictions", prediction_path,
         "--ground-truth", os.path.join(CONTRACTS, "ground-truth"),
         "--out", os.path.join(run_dir, "scores"),
         "--comparison-id", f"task18-three-arm-{args.mode}",
         "--sample-scope", ",".join(same_budget_ids)],
        capture_output=True, text=True)
    print(adapter_proc.stdout.strip()[-3000:])
    if adapter_proc.returncode != 0:
        print(adapter_proc.stderr[-3000:], file=sys.stderr)
        return 1
    adapter_doc = load_json(os.path.join(run_dir, "scores", "three-arm-comparison.json"))

    comparison["pairwise"] = adapter_doc.get("pairwise", {})
    comparison["pack_verdict"] = adapter_doc.get("pack_verdict")
    comparison["max_sampling_gap_ms"] = adapter_doc.get("max_sampling_gap_ms")
    comparison["aggregate_metrics"] = adapter_doc.get("metrics")
    with open(os.path.join(run_dir, "comparison.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n")
    write_comparison_md(os.path.join(run_dir, "comparison.md"), comparison)
    print(f"[Verdict] pack={comparison['pack_verdict']['verdict']} — "
          f"{comparison['pack_verdict']['reason']}")
    return 0


def write_comparison_md(path, comparison):
    lines = [
        f"# 任务 18 三臂评测（{comparison['mode']}；{comparison['input_nature']}）",
        "",
        f"- 生成时间：{comparison['generated_at']}",
        f"- 证据性质：{comparison['evidence_nature']}",
        "- **本评测使用合成技术 fixture，不是真实行业视频；结果不得外推为真实仓储准确率。**",
        "",
        "## 公平性",
        "",
    ]
    for key, value in comparison["fairness"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## 逐场景结果", ""]
    for sample_id, scenario in comparison["scenarios"].items():
        lines.append(f"### {sample_id}（{scenario['category']}；预算 {scenario['budget']}）")
        lines.append("")
        lines.append("| 指标 | uniform | adaptive | coverage |")
        lines.append("| --- | --- | --- | --- |")
        arms = scenario["arms"]
        rows = [
            ("最终状态", "final_status"),
            ("实际调用", "actual_model_calls"),
            ("初始覆盖调用", "initial_coverage_calls"),
            ("覆盖探索调用", "coverage_exploration_calls"),
            ("边界细化调用", "boundary_refinement_calls"),
            ("最大相邻间隔初始(ms)", "max_adjacent_sampling_gap_ms_initial"),
            ("最大相邻间隔最终(ms)", "max_adjacent_sampling_gap_ms_final"),
            ("状态转换数", "state_transition_count"),
            ("最大边界宽度(ms)", "max_uncertainty_width_ms"),
            ("达到目标边界精度", "target_precision_reached"),
            ("耗尽预算", "budget_exhausted"),
            ("停止原因", "stop_reasons"),
            ("证据性质", "evidence_nature"),
        ]
        for label, field in rows:
            values = [arms.get(arm, {}).get("metrics", {}).get(field) for arm in
                      ("uniform", "adaptive", "coverage")]
            lines.append(f"| {label} | {values[0]} | {values[1]} | {values[2]} |")
        for arm in ("uniform", "adaptive", "coverage"):
            counts = arms.get(arm, {}).get("metrics", {}).get("class_counts") or {}
            lines.append(f"- {arm} 五类计数：{counts}")
        lines.append("")
    lines += ["## 两两 Verdict", ""]
    for pair_id, pair in (comparison.get("pairwise") or {}).items():
        verdict = pair["verdict"]
        lines.append(f"### {pair_id}（baseline={pair['baseline']}, candidate={pair['candidate']}）")
        lines.append("")
        lines.append(f"- fairness gate: {'全部通过' if pair['fairness_gate']['all_passed'] else '未通过'}")
        lines.append(f"- **verdict: {verdict['verdict']}** — {verdict['reason']}")
        lines.append(f"- reason_codes: {verdict['reason_codes']}")
        lines.append("")
    pack = comparison.get("pack_verdict") or {}
    lines += [
        "## Pack 级三臂 Verdict",
        "",
        f"**{pack.get('verdict')}** — {pack.get('reason')}",
        "",
        f"- reason_codes: {pack.get('reason_codes')}",
        f"- 最大相邻采样间隔（跨场景最大值）: {comparison.get('max_sampling_gap_ms')}",
        "",
        "## 不得外推的声明",
        "",
        "- 技术 fixture 小样本 + 单次运行：不构成统计显著性，不得外推为真实仓储/园区准确率；",
        "- replay 为构造证据回放（零模型调用）；真实 Qwen 运行受模型非确定性影响；两者指标不混合平均；",
        "- `completed`（execution_status）不等于语义正确；覆盖探索不保证发现任意短事件。",
        "",
    ]
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
