#!/usr/bin/env python3
"""run_task20_dynamic.py — Task 20 阶段 C 动态三臂验证执行器（SparkSkill Studio 任务 20）

仅在阶段 B 配对 verdict = IMPROVEMENT（预注册全门通过）时才允许运行（预注册
evaluation-plan.json 的 phase_c_entry 条件）。执行 v2 提示词语义下的九样本三臂
动态运行，与 Task 19B 运行规则同构：

  - 同一 dev 媒体（仓库外只读包，经任务 19B ingestion 链接农场）、同一 target query、
    同一三臂与同预算政策（clamp(ceil(duration/1000),12,24)，取自任务 19B 冻结
    sample-manifest.json）、同一臂参数（任务 19B 冻结 arm-configs.json）；
  - 样本按 ID 字典序；样本内臂顺序按索引循环左移轮换（任务 19B 同规则）；
  - 批量前一次统一 warm-up（任务 16 冻结 fixture 一帧，不计入任何 arm）；
  - --prompt-version v1|v2 可选择：v1 = 现行 analyze_image 模板（默认，行为与
    任务 19B 逐字节一致）；v2 = 阶段 A 冻结的 prompt-v2.txt，经对
    trace_temporal.trace_video.analyze_image.build_prompt 的同对象补丁注入
    （真实模型调用路径不变：call_ollama / coerce_evidence / 原始返回存档 /
    provenance / 预算记账全部沿用；补丁机制与版本哈希逐运行记录）。
  - 无单侧重试、不删失败样本；GT 不在执行器读取范围（评分阶段才读）。

与 Task 19B 旧动态基线的比较是运行层观察，不是同期同帧单变量因果证据
（动态样本点可能因 v2 状态反馈改变）；分别报告 generated / licensed-public，
不把 pooled 数字包装为严格配对 PASS。

用法:
    python3 scripts/run_task20_dynamic.py --prompt-version v2 \
        [--out artifacts/task-20/dynamic] [--timeout 300] [--dry-run]
退出码: 0 = 动态运行完成; 1 = 预注册/资源门槛/进入条件失败; 2 = 执行器致命错误
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
VALIDATE_SPEC = os.path.join(COMPILER_SCRIPTS, "validate_task_spec.py")
SPEC_SCHEMA = os.path.join(PROJECT_ROOT, "schemas", "visual-task-spec.schema.json")
TASK19 = os.path.join(PROJECT_ROOT, "artifacts", "task-19")
TASK19_PREREG = os.path.join(TASK19, "preregistration")
TASK19_INGESTION = os.path.join(TASK19, "ingestion")
TASK20_PREREG = os.path.join(PROJECT_ROOT, "artifacts", "task-20", "preregistration")
PROMPT_V2 = os.path.join(TASK20_PREREG, "prompt-v2.txt")
WARMUP_FIXTURE_VIDEO = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures",
                                    "videos", "fixture-present-throughout.mp4")
DEFAULT_MODEL = "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest"

GENERATION_PATTERNS = (
    "vllm.entrypoints", "vllm serve", "api_server", "DiffusionWorker",
    "h3_lite_api.py", "native_bench.py", "h3-next", "diffusion_service",
)
WEBUI_PATTERNS = (
    "minimax-h3/webui", "h3-studio", "minimax-h3/experiments",
    "minimax-h3/env/webui/bin/python app.py",
)

BLOCK_TO_KWARG = {
    "strategy": "strategy",
    "max_model_calls": "max_model_calls",
    "initial_coverage_samples": "initial_coverage_samples",
    "target_boundary_precision_ms": "target_boundary_precision_ms",
    "max_refinement_rounds": "max_refinement_rounds",
    "coverage_gap_target_ms": "coverage_gap_target_ms",
    "coverage_call_reserve": "coverage_call_reserve",
}


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
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_text(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def resource_gate(min_gib=45.0, samples=3):
    """任务书第十节资源门槛（与任务 19B 同口径）。"""
    import urllib.request
    checks = {}
    h3_generation = process_matching(GENERATION_PATTERNS)
    port_8000 = port_listening(8000)
    port_8010 = port_listening(8010)
    checks["minimax_h3_stopped"] = {
        "passed": not h3_generation and not port_8000 and not port_8010,
        "evidence": (f":8000 {'有' if port_8000 else '无'}监听；"
                     f":8010 {'有' if port_8010 else '无'}监听；"
                     f"生成类进程 {len(h3_generation)} 个"),
    }
    webui = process_matching(WEBUI_PATTERNS)
    checks["no_user_active_h3_webui_task"] = {
        "passed": not webui,
        "evidence": f"用户 MiniMax-H3/WebUI 相关进程 {len(webui)} 个",
    }
    readings = []
    for _ in range(samples):
        readings.append(mem_available_gib())
        time.sleep(1)
    checks["mem_available_3x_ge_45gib"] = {
        "passed": all(r is not None and r >= min_gib for r in readings),
        "samples_gib": readings, "threshold_gib": min_gib,
    }
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10):
            reachable = True
    except Exception:  # noqa: BLE001
        reachable = False
    checks["ollama_reachable"] = {"passed": reachable,
                                  "evidence": "GET /api/tags 200" if reachable else "不可达"}
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=10) as resp:
            loaded = [item.get("name") for item in json.load(resp).get("models", [])]
    except Exception:  # noqa: BLE001
        loaded = None
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
    locks = [name for name in (".git/index.lock", ".git/HEAD.lock")
             if os.path.exists(os.path.join(PROJECT_ROOT, ".git", name))]
    checks["git_workspace_expected"] = {
        "passed": not locks,
        "evidence": f"Git 锁: {locks or '无'}",
    }
    all_passed = all(item["passed"] for item in checks.values())

    def sanitize(text):
        return text.replace(os.path.expanduser("~"), "~")

    for item in checks.values():
        if isinstance(item.get("evidence"), str):
            item["evidence"] = sanitize(item["evidence"])
    return {"recorded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "scope": "task20_dynamic_real_run",
            "checks": checks, "all_passed": all_passed}, all_passed


def verify_preregistration():
    """阶段 A 冻结哈希复核 + 阶段 B 配对结果存在且 verdict=IMPROVEMENT（进入条件）。"""
    problems = []
    frozen_path = os.path.join(TASK20_PREREG, "frozen-hashes.json")
    if not os.path.isfile(frozen_path):
        return ["frozen-hashes.json 缺失"]
    frozen = load_json(frozen_path)
    for rel, entry in frozen["entries"].items():
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path):
            problems.append(f"missing: {rel}")
        elif sha256_of(path) != entry["sha256"]:
            problems.append(f"hash mismatch: {rel}")
    return problems


def verify_phase_b_gate():
    """阶段 C 进入条件：阶段 B 配对 verdict 必须为 IMPROVEMENT。"""
    score_path = os.path.join(PROJECT_ROOT, "artifacts", "task-20", "scores",
                              "paired-score.json")
    if not os.path.isfile(score_path):
        return False, "阶段 B 配对评分不存在（paired-score.json 缺失）"
    score = load_json(score_path)
    verdict = score.get("verdict")
    return verdict == "IMPROVEMENT", f"阶段 B verdict={verdict}"


def render_prompt_v2(template, spec):
    """v2 提示词渲染（与 run_task20_pairing.py 的 prompt_for(v2) 同逻辑）。"""
    target = spec.get("target", {})
    attributes = target.get("attributes") or []
    forbidden = spec.get("constraints", {}).get("forbidden_inferences") or []
    return template.format(
        target_description=target.get("description", ""),
        attributes="、".join(attributes) if attributes else "（无）",
        forbidden="、".join(forbidden) if forbidden else "（无）",
    )


def build_execution_manifest(sample, arm_id, arm_cfg, budget, link, prompt_version,
                             prompt_sha256):
    block = dict(arm_cfg["sampling_strategy_block"])
    block["max_model_calls"] = budget
    return {
        "schema_version": "1.0.0",
        "sample_id": sample["sample_id"],
        "arm_id": arm_id,
        "media": {"path": link["repo_relative_link"], "sha256": link["media_sha256"],
                  "duration_ms": link["measured_duration_ms"]},
        "target_query": sample["target_query"],
        "task_type": "temporal_presence_evidence",
        "sampling_strategy": block,
        "safety": {"abstain_if_insufficient_evidence": True,
                   "forbidden_inferences": ["identity", "age", "nationality",
                                            "relationship", "intent"]},
        "output_requirements": ["object_found", "description", "bounding_box",
                                "confidence", "evidence_text", "abstention_reason",
                                "sampling_provenance", "temporal_evidence"],
        "runtime": {"vision_backend": "ollama", "model": DEFAULT_MODEL,
                    "timeout_s": None},
        "prompt_versioning": {
            "version": prompt_version,
            "prompt_sha256": prompt_sha256,
            "mechanism": ("v2 经 trace_temporal.trace_video.analyze_image.build_prompt "
                          "同对象补丁注入；真实模型调用路径（call_ollama/coerce_evidence/"
                          "原始返回存档/provenance/预算记账）不变"),
            "v1_reference": "analyze_image.PROMPT_TEMPLATE（未修改）",
        },
    }


def build_task_spec(sample, arm_id, block, budget, link):
    return {
        "task_id": f"task20-dyn-{sample['sample_id'].lower()}-{arm_id}-{block['strategy']}",
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_trace",
        "target": {"description": sample["target_query"]},
        "source_media": link["repo_relative_link"],
        "required_outputs": ["object_found", "description", "bounding_box",
                             "confidence", "evidence_text"],
        "constraints": {"abstain_if_insufficient_evidence": True,
                        "forbidden_inferences": ["identity", "age", "nationality",
                                                 "relationship", "intent"]},
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
        "sampling_strategy": block,
    }


def strategy_kwargs(block, duration_ms, budget):
    kwargs = {}
    for key, value in block.items():
        if key == "refinement_triggers":
            kwargs["refinement_triggers"] = list(value)
        elif key in BLOCK_TO_KWARG:
            kwargs[BLOCK_TO_KWARG[key]] = value
    if block.get("strategy") == "uniform":
        kwargs["interval_ms"] = round(duration_ms / budget, 6)
        kwargs["max_frames"] = budget
    return kwargs


def main():
    parser = argparse.ArgumentParser(description="Task 20 阶段 C 动态三臂验证执行器")
    parser.add_argument("--prompt-version", choices=["v1", "v2"], default="v1")
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "artifacts", "task-20",
                                                      "dynamic"))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--min-available-gib", type=float, default=45.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="只生成 manifest/规格并校验，不调用模型")
    args = parser.parse_args()

    # cv2 解释器保障
    sys.path.insert(0, SKILL_SCRIPTS)
    import skill_env  # noqa: E402
    skill_env.ensure_cv2_interpreter()

    # 0) 预注册哈希 + 阶段 B 进入条件
    problems = verify_preregistration()
    if problems:
        print("[预注册复核失败] " + "；".join(problems), file=sys.stderr)
        return 1
    gate_ok, gate_detail = verify_phase_b_gate()
    if not gate_ok and not args.dry_run:
        print(f"[进入条件失败] {gate_detail}；阶段 C 禁止运行", file=sys.stderr)
        return 1
    print(f"[进入条件] {gate_detail}")

    # 1) 载入任务 19B 冻结协议（样本/预算/臂参数/链接农场）
    sample_manifest = load_json(os.path.join(TASK19_PREREG, "sample-manifest.json"))
    arm_configs = load_json(os.path.join(TASK19_PREREG, "arm-configs.json"))
    link_map = load_json(os.path.join(TASK19_INGESTION, "media-link-map.json"))["links"]
    arms = {arm["arm_id"]: arm for arm in arm_configs["arms"]}

    # 2) v2 补丁（同对象补丁；v1 不打补丁）
    prompt_sha256 = None
    patch_record = {"version": args.prompt_version}
    tt_spec = importlib.util.spec_from_file_location("trace_temporal", TRACE_TEMPORAL)
    tt = importlib.util.module_from_spec(tt_spec)
    tt_spec.loader.exec_module(tt)
    if args.prompt_version == "v2":
        template = open(PROMPT_V2, encoding="utf-8").read()
        prompt_sha256 = sha256_of_text(template)
        original_build_prompt = tt.trace_video.analyze_image.build_prompt
        v1_template = tt.trace_video.analyze_image.PROMPT_TEMPLATE

        def build_prompt_v2(spec, _template=template):
            return render_prompt_v2(_template, spec)

        tt.trace_video.analyze_image.build_prompt = build_prompt_v2
        patch_record.update({
            "prompt_sha256": prompt_sha256,
            "v1_prompt_sha256": sha256_of_text(v1_template),
            "patched_object": "trace_temporal.trace_video.analyze_image.build_prompt",
            "restored_after_run": False,
        })
    else:
        patch_record["prompt_sha256"] = sha256_of_text(
            tt.trace_video.analyze_image.PROMPT_TEMPLATE)
        patch_record["patched_object"] = None

    os.makedirs(args.out, exist_ok=True)
    predictions_dir = os.path.join(args.out, "predictions")
    manifests_dir = os.path.join(args.out, "execution-manifests")
    os.makedirs(predictions_dir, exist_ok=True)
    os.makedirs(manifests_dir, exist_ok=True)

    metadata = {
        "task": "task20-dynamic-three-arm",
        "mode": "dry-run" if args.dry_run else "real",
        "prompt_version": args.prompt_version,
        "prompt_sha256": prompt_sha256 or patch_record["prompt_sha256"],
        "patch": patch_record,
        "model": DEFAULT_MODEL,
        "timeout_s": args.timeout,
        "protocol_source": "任务 19B 冻结 sample-manifest/arm-configs/media-link-map（同预算/同臂参数/同轮换）",
        "comparison_caveat": ("与 Task 19B 旧动态基线的比较是运行层观察，不是同期同帧单变量因果证据；"
                              "动态样本点可能因 v2 状态反馈改变"),
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    if args.dry_run:
        for sample_id in sample_manifest["sample_order"]:
            entry = sample_manifest["samples"][sample_id]
            link = link_map[sample_id]
            budget = entry["budget_max_model_calls"]
            duration = entry["measured_duration_ms"]
            for arm_id in entry["arm_execution_order"]:
                arm_cfg = arms[arm_id]
                block = dict(arm_cfg["sampling_strategy_block"])
                block["max_model_calls"] = budget
                spec = build_task_spec(entry, arm_id, block, budget, link)
                spec_path = os.path.join(predictions_dir, sample_id, arm_id, "task-spec.json")
                os.makedirs(os.path.dirname(spec_path), exist_ok=True)
                dump_json(spec_path, spec)
                validate = subprocess.run(
                    [sys.executable, VALIDATE_SPEC, "--schema", SPEC_SCHEMA,
                     "--input", spec_path], capture_output=True, text=True)
                print(f"  {sample_id}/{arm_id}: spec={'VALID' if validate.returncode == 0 else 'INVALID'}"
                      f" budget={budget}")
                if validate.returncode != 0:
                    print(validate.stderr[-800:], file=sys.stderr)
                    return 1
        print("[dry-run] 全部 27 个 (样本,臂) 规格校验通过（未调用模型）")
        return 0

    # 3) 资源门槛
    gate_doc, gate_passed = resource_gate(min_gib=args.min_available_gib)
    dump_json(os.path.join(args.out, "resource-gate.json"), gate_doc)
    metadata["resource_gate_all_passed"] = gate_passed
    if not gate_passed:
        dump_json(os.path.join(args.out, "run-metadata.json"), metadata)
        print("[拒绝] 资源门槛未通过，未发起任何动态调用", file=sys.stderr)
        return 1

    # 4) 统一 warm-up（任务 16 fixture，不计入任何 arm）
    warmup_dir = os.path.join(predictions_dir, "_warmup")
    os.makedirs(os.path.join(warmup_dir, "warmup-frame"), exist_ok=True)
    warmup_record = {"kind": "warmup", "counts_toward_no_arm": True,
                     "fixture": os.path.relpath(WARMUP_FIXTURE_VIDEO, PROJECT_ROOT),
                     "prompt_version": args.prompt_version}
    try:
        warmup_spec = {
            "task_id": "task20-dyn-warmup", "skill_name": "visual-evidence-extractor",
            "task_type": "object_trace",
            "target": {"description": "红色背包"},
            "source_media": WARMUP_FIXTURE_VIDEO,
            "required_outputs": ["object_found", "description", "bounding_box",
                                 "confidence", "evidence_text"],
            "constraints": {"abstain_if_insufficient_evidence": True,
                            "forbidden_inferences": ["identity", "age", "nationality",
                                                     "relationship", "intent"]},
            "confidence_threshold": 0.5, "requires_visual_input": True,
            "sampling_strategy": {"strategy": "uniform", "max_model_calls": 1},
        }
        warmup_doc = tt.trace_temporal(
            warmup_spec, os.path.join(warmup_dir, "warmup-evidence.json"),
            strategy="uniform", max_model_calls=1, interval_ms=0, max_frames=1,
            frames_dir=os.path.join(warmup_dir, "warmup-frame"),
            model=DEFAULT_MODEL, timeout=args.timeout,
            save_raw_dir=os.path.join(warmup_dir, "raw"))
        warmup_record["status"] = "completed"
        warmup_record["actual_model_calls"] = (warmup_doc.get("sampling_provenance") or {}
                                               ).get("actual_model_calls")
    except Exception as error:  # noqa: BLE001
        warmup_record["status"] = f"failed: {type(error).__name__}"
    dump_json(os.path.join(warmup_dir, "warmup-record.json"), warmup_record)
    metadata["warmup"] = warmup_record
    print(f"[warm-up] {warmup_record['status']}", flush=True)

    # 5) 九样本 × 三臂
    runs = []
    total_calls = 0
    for sample_id in sample_manifest["sample_order"]:
        entry = sample_manifest["samples"][sample_id]
        link = link_map[sample_id]
        budget = entry["budget_max_model_calls"]
        duration = entry["measured_duration_ms"]
        for arm_id in entry["arm_execution_order"]:
            arm_cfg = arms[arm_id]
            block = dict(arm_cfg["sampling_strategy_block"])
            block["max_model_calls"] = budget
            out_dir = os.path.join(predictions_dir, sample_id, arm_id)
            os.makedirs(out_dir, exist_ok=True)
            os.makedirs(os.path.join(manifests_dir, sample_id), exist_ok=True)
            manifest = build_execution_manifest(entry, arm_id, arm_cfg, budget, link,
                                                args.prompt_version,
                                                patch_record["prompt_sha256"])
            manifest["runtime"]["timeout_s"] = args.timeout
            dump_json(os.path.join(manifests_dir, sample_id, f"{arm_id}.json"), manifest)
            spec = build_task_spec(entry, arm_id, block, budget, link)
            spec_path = os.path.join(out_dir, "task-spec.json")
            dump_json(spec_path, spec)
            started = time.time()
            status = "completed"
            error = None
            try:
                doc = tt.trace_temporal(
                    spec, os.path.join(out_dir, "temporal-evidence.json"),
                    frames_dir=os.path.join(out_dir, "frames", "media-0"),
                    save_raw_dir=os.path.join(out_dir, "raw"),
                    model=DEFAULT_MODEL, timeout=args.timeout,
                    **strategy_kwargs(block, duration, budget))
                calls = (doc.get("sampling_provenance") or {}).get("actual_model_calls", 0)
            except Exception as exc:  # noqa: BLE001
                status = f"failed: {type(exc).__name__}"
                error = str(exc)[:300]
                doc = None
                calls = 0
            elapsed = round(time.time() - started, 3)
            report_path = os.path.join(out_dir, "temporal-report.json")
            if doc is not None:
                report = subprocess.run(
                    [sys.executable, GENERATE_REPORT,
                     "--task-spec", spec_path,
                     "--evidence", os.path.join(out_dir, "temporal-evidence.json"),
                     "--output", report_path, "--mode", "temporal"],
                    capture_output=True, text=True)
                if report.returncode != 0:
                    status = f"report_failed: {report.stderr[-200:]}"
            runs.append({"sample_id": sample_id, "arm_id": arm_id, "status": status,
                         "error": error, "actual_model_calls": calls,
                         "wall_time_s": elapsed})
            total_calls += calls
            print(f"[{sample_id}/{arm_id}] {status} calls={calls} ({elapsed}s)", flush=True)

    metadata["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata["runs"] = runs
    metadata["total_actual_model_calls"] = total_calls
    metadata["status"] = ("COMPLETED" if all(r["status"] == "completed" for r in runs)
                          else "PARTIAL")
    dump_json(os.path.join(args.out, "run-metadata.json"), metadata)
    print(json.dumps({"status": metadata["status"], "runs": len(runs),
                      "total_actual_model_calls": total_calls}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
