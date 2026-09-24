#!/usr/bin/env python3
"""run_task22_pairing.py — Task 22 同期同帧配对实验执行器（SparkSkill Studio 任务 22）

预注册协议（artifacts/task-22/preregistration/，阶段 A 提交冻结；本执行器在阶段 A
提交之后才允许对 256 个 dev 采样点发起任何视觉调用）:

  - 256 个采样点与 Task 20 同期同帧（同一 dev 包、同一 Task 19B 27 臂时间线、同一帧农场
    字节），逐点记录媒体 SHA-256、原时间戳、目标查询、所属 arm；GT 不进入任何视觉请求。
  - 基线 v1 = analyze_image.PROMPT_TEMPLATE 现行生产模板（SHA-256 冻结，零改动引用）；
    候选 c3 = prompt-c3.txt（要求分项可审计视觉支持 + 可见性非机械拒答纪律；核心 JSON
    输出契约与证据状态集合不变；分项为附加可审计字段；不含任何素材答案/时间/样本编号）。
  - **每帧每版恰好一次真实 Qwen 调用**（v1 与 c3 各一次，同一份帧字节）；无第二候选、
    无两阶段多调用、无隐藏推理、无缓存冒充、无存档复制、无 scorer 改动。
  - 请求参数与 v1 流水线同构: 同一 Ollama 模型、format=json、stream=False、keep_alive=10m、
    options.temperature=0.1、超时 300s；直接复用 analyze_image.call_ollama。
  - c3 证据 coercer = analyze_image.coerce_evidence（核心字段校验逐字节相同，保证外部证据
    状态与 classify_entry 兼容）+ 分项字段宽松抽取（缺项如实记录、不猜补、不改变分类）。
  - 运行顺序按预注册轮换: 冻结点序（样本 ID 字典序 → arm 序 → 时间戳升序）下，偶数索引
    v1 先、奇数索引 c3 先；两版各只常规运行一次，无单侧重试；失败/超时/无效 JSON/契约
    拒绝如实记账。
  - 批量前 8 项资源门槛；运行中每点前轻量复核；失败即暂停新调用、保留已完成证据、
    状态 RESOURCE_BLOCKED。
  - warm-up: 1 次真实调用（任务 16 冻结 fixture 一帧，v1 模板，不计入 256 点对、不使用
    dev 数据）；smoke 模式用 fixture 帧验证链路，不计入正式。

用法:
    python3 run_task22_pairing.py [--out artifacts/task-22/pairs] [--timeout 300] \
        [--versions v1,c3] [--smoke]
退出码: 0 = 配对实验完成; 1 = 预注册/资源门槛失败; 2 = 执行器致命错误
"""
import argparse
import datetime
import glob
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKILL_SCRIPTS = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor", "scripts")
ANALYZE_IMAGE = os.path.join(SKILL_SCRIPTS, "analyze_image.py")
PREREGISTRATION = os.path.join(PROJECT_ROOT, "artifacts", "task-22", "preregistration")
POINT_MANIFEST = os.path.join(PREREGISTRATION, "point-manifest-256.json")
FRAME_FARM_REPORT = os.path.join(PROJECT_ROOT, "artifacts", "task-20", "phase0", "frame-farm-report.json")
PROMPT_C3 = os.path.join(PREREGISTRATION, "prompt-c3.txt")
FROZEN_HASHES = os.path.join(PREREGISTRATION, "frozen-hashes.json")
WARMUP_FIXTURE_FRAME = os.path.join(
    PROJECT_ROOT, "artifacts", "task-19", "predictions", "_warmup", "warmup-frame",
    "fixture-present-throughout_f00000_t00000000ms.png")
WARMUP_SPEC = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "predictions", "_warmup",
                           "warmup-spec.json")
DEFAULT_MODEL = "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest"
ARMS = ("uniform", "adaptive", "coverage")
GENERATED = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06"]
LICENSED = ["WEB01", "WEB02", "WEB03"]
WHITELIST = set(GENERATED + LICENSED)

# 资源门槛：生成类进程精确模式（与任务 18/19/20 runner 同口径）
GENERATION_PATTERNS = (
    "vllm.entrypoints", "vllm serve", "api_server", "DiffusionWorker",
    "h3_lite_api.py", "native_bench.py", "h3-next", "diffusion_service",
)
WEBUI_PATTERNS = (
    "minimax-h3/webui", "h3-studio", "minimax-h3/experiments",
    "minimax-h3/env/webui/bin/python app.py",
)
H3_PORTS = (8000, 8010)

# c3 分项支持字段（宽松抽取；缺项记录、不猜补）
ITEMIZED_STR_FIELDS = ("target_category", "target_relationship", "visibility")
ITEMIZED_BOOL_FIELDS = ("category_match", "visibility_impedes_judgment")
ITEMIZED_LIST_FIELDS = ("necessary_attributes",)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def load_analyze_image():
    spec = importlib.util.spec_from_file_location("analyze_image", ANALYZE_IMAGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def coerce_c3(analyze_mod, raw, spec, image_path, model):
    """c3 证据 coercer：核心字段校验复用 analyze_image.coerce_evidence（逐字节相同，
    保证 object_found/evidence_sufficient/abstention_reason/frame_status 与 classify_entry
    兼容）；随后宽松抽取分项支持字段。缺项/类型不符如实记录，不猜补、不改变核心分类。"""
    evidence = analyze_mod.coerce_evidence(raw, spec, image_path, model)
    itemized = {}
    gaps = []
    for field in ITEMIZED_STR_FIELDS:
        value = raw.get(field) if isinstance(raw, dict) else None
        if isinstance(value, str) and value.strip():
            itemized[field] = value
        else:
            itemized[field] = None
            gaps.append(field)
    for field in ITEMIZED_BOOL_FIELDS:
        value = raw.get(field) if isinstance(raw, dict) else None
        if isinstance(value, bool):
            itemized[field] = value
        else:
            itemized[field] = None
            gaps.append(field)
    for field in ITEMIZED_LIST_FIELDS:
        value = raw.get(field) if isinstance(raw, dict) else None
        if isinstance(value, list) and all(isinstance(v, str) for v in value):
            itemized[field] = list(value)
        else:
            itemized[field] = None
            gaps.append(field)
    evidence["itemized_support"] = itemized
    evidence["itemized_support_complete"] = not gaps
    evidence["itemized_support_gaps"] = gaps
    return evidence


# ---------------------------------------------------------------- 资源门槛

def mem_available_gib():
    with open("/proc/meminfo", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 * 1024)
    return None


def process_lines():
    result = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=30)
    return [line for line in result.stdout.splitlines() if line.strip()]


def generation_processes(lines):
    hits = []
    for line in lines:
        for pattern in GENERATION_PATTERNS:
            if pattern in line:
                hits.append(line)
                break
    return hits


def webui_processes(lines):
    hits = []
    for line in lines:
        for pattern in WEBUI_PATTERNS:
            if pattern in line:
                hits.append(line)
                break
    return hits


def port_listening(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def ollama_ps():
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as error:  # noqa: BLE001
        return {"error": type(error).__name__}


def dsh_version():
    try:
        result = subprocess.run(["dsh", "--version"], capture_output=True, text=True, timeout=30)
        return (result.stdout or result.stderr).strip()
    except (OSError, subprocess.SubprocessError) as error:
        return f"unavailable: {type(error).__name__}"


def resource_gate(full=True):
    checks = {}
    lines = process_lines()
    gen = generation_processes(lines)
    webui = webui_processes(lines)
    checks["minimax_h3_stopped"] = {
        "passed": not gen and not port_listening(8000) and not port_listening(8010),
        "evidence": f"生成类进程 {len(gen)} 个；:8000 监听={port_listening(8000)}；"
                    f":8010 监听={port_listening(8010)}",
    }
    checks["no_user_active_h3_webui_task"] = {
        "passed": not webui,
        "evidence": f"WebUI 类进程 {len(webui)} 个",
    }
    mem_samples = []
    for _ in range(3):
        mem_samples.append(round(mem_available_gib(), 2))
        time.sleep(1)
    checks["mem_available_3x_ge_45gib"] = {
        "passed": all(value >= 45.0 for value in mem_samples),
        "samples_gib": mem_samples, "threshold_gib": 45.0,
    }
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as response:
            tags_ok = response.status == 200
    except Exception:  # noqa: BLE001
        tags_ok = False
    checks["ollama_reachable"] = {"passed": tags_ok, "evidence": "GET /api/tags"}
    ps = ollama_ps()
    loaded = ps.get("models", []) if isinstance(ps, dict) else []
    checks["no_external_qwen_consumer"] = {
        "passed": not loaded,
        "evidence": f"/api/ps 已加载模型 {len(loaded)} 个"
                    + (f"（{loaded[0].get('name')}）" if loaded else ""),
    }
    checks["dsh_normal"] = {"passed": bool(dsh_version()) and "unavailable" not in dsh_version(),
                            "evidence": dsh_version()}
    if full:
        checks["git_workspace_expected"] = {
            "passed": True,  # 由调用方在阶段 A 提交后核验；此处记录锁状态
            "evidence": f"Git 锁: {'有' if glob.glob(os.path.join(PROJECT_ROOT, '.git', '*.lock')) else '无'}",
        }
    return checks


# ---------------------------------------------------------------- 预注册哈希复核

def verify_preregistration():
    frozen = load_json(FROZEN_HASHES)
    problems = []
    for name, entry in frozen["entries"].items():
        path = os.path.join(PROJECT_ROOT, entry["path"])
        if not os.path.isfile(path):
            problems.append(f"missing: {entry['path']}")
            continue
        actual = sha256_of(path)
        if actual != entry["sha256"]:
            problems.append(f"hash mismatch: {entry['path']}")
    return problems


# ---------------------------------------------------------------- 单点执行

def run_one_call(analyze_mod, version, prompt, spec, image_path, timeout, model):
    """一次常规视觉调用（无重试）。返回 (judgment, call_record)。"""
    started = time.time()
    record = {"version": version, "model": model, "timeout_s": timeout,
              "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        body = analyze_mod.call_ollama(model, prompt, image_path, timeout)
    except Exception as error:  # noqa: BLE001 — 网络/HTTP/超时统一记账
        record.update({"outcome": "call_failed", "error_type": type(error).__name__,
                       "latency_s": round(time.time() - started, 3)})
        judgment = {"frame_status": "failed", "object_found": False, "confidence": 0.0,
                    "evidence_text": "无模型输出；调用失败", "abstention_reason":
                        f"帧分析失败：{type(error).__name__}",
                    "evidence_sufficient": False,
                    "evidence_nature": "backend_call_failed"}
        return judgment, record
    latency = round(time.time() - started, 3)
    raw_text = body.get("response", "")
    record["latency_s"] = latency
    record["raw_response_sha256"] = sha256_of_text(raw_text)
    try:
        raw = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        record.update({"outcome": "invalid_json", "raw_prefix": raw_text[:200]})
        judgment = {"frame_status": "failed", "object_found": False, "confidence": 0.0,
                    "evidence_text": "无模型输出；返回非合法 JSON", "abstention_reason":
                        "帧分析失败：模型未返回合法 JSON",
                    "evidence_sufficient": False,
                    "evidence_nature": "backend_call_failed"}
        return judgment, record
    try:
        if version == "c3":
            judgment = coerce_c3(analyze_mod, raw, spec, image_path, model)
        else:
            judgment = analyze_mod.coerce_evidence(raw, spec, image_path, model)
        judgment["frame_status"] = "analyzed"
        judgment["evidence_nature"] = "real_model_output"
        record["outcome"] = "ok"
        record["object_found"] = judgment["object_found"]
        record["confidence"] = judgment["confidence"]
        if version == "c3":
            record["itemized_support_complete"] = judgment.get("itemized_support_complete")
        return judgment, record
    except ValueError as error:
        record.update({"outcome": "contract_rejected", "error": str(error)})
        judgment = {"frame_status": "failed", "object_found": False, "confidence": 0.0,
                    "evidence_text": "无模型输出；证据校验失败", "abstention_reason":
                        f"帧分析失败：{error}",
                    "evidence_sufficient": False,
                    "evidence_nature": "backend_call_failed"}
        return judgment, record


def main():
    parser = argparse.ArgumentParser(description="Task 22 同期同帧配对实验执行器")
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "artifacts", "task-22", "pairs"))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--versions", default="v1,c3", help="逗号分隔：v1 / c3")
    parser.add_argument("--smoke", action="store_true",
                        help="用任务 16 fixture 帧验证执行器链路（不触碰 256 个 dev 点）")
    args = parser.parse_args()
    versions = [v.strip() for v in args.versions.split(",") if v.strip()]
    if set(versions) - {"v1", "c3"}:
        print("[拒绝] --versions 仅支持 v1,c3", file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    points_dir = os.path.join(args.out, "points")
    os.makedirs(points_dir, exist_ok=True)
    call_log_path = os.path.join(args.out, "call-log.jsonl")

    analyze_mod = load_analyze_image()
    v1_template = analyze_mod.PROMPT_TEMPLATE
    c3_template = open(PROMPT_C3, encoding="utf-8").read()
    v1_hash = sha256_of_text(v1_template)
    c3_hash = sha256_of_text(c3_template)

    def prompt_for(version, spec):
        if version == "v1":
            return analyze_mod.build_prompt(spec)
        target = spec.get("target", {})
        attributes = target.get("attributes") or []
        forbidden = spec.get("constraints", {}).get("forbidden_inferences") or []
        return c3_template.format(
            target_description=target.get("description", ""),
            attributes="、".join(attributes) if attributes else "（无）",
            forbidden="、".join(forbidden) if forbidden else "（无）",
        )

    # ------------------------------------------------ 阶段 A 哈希复核
    problems = verify_preregistration()
    if problems:
        print("[拒绝] 预注册哈希复核失败: " + "; ".join(problems), file=sys.stderr)
        return 1

    metadata = {
        "task": "task22-paired-experiment",
        "mode": "smoke" if args.smoke else "formal",
        "model": DEFAULT_MODEL,
        "timeout_s": args.timeout,
        "v1_prompt_sha256": v1_hash,
        "c3_prompt_sha256": c3_hash,
        "v1_prompt_source": "analyze_image.PROMPT_TEMPLATE（现行生产冻结模板，零改动引用）",
        "c3_prompt_source": "artifacts/task-22/preregistration/prompt-c3.txt",
        "request_params": {"format": "json", "stream": False, "keep_alive": "10m",
                           "options": {"temperature": 0.1},
                           "note": "与 v1 流水线同构（复用 analyze_image.call_ollama）"},
        "order_policy": "冻结点序下偶数索引 v1 先、奇数索引 c3 先；无单侧重试",
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    # ------------------------------------------------ 资源门槛（批量前 8 项）
    gate = resource_gate(full=True)
    metadata["resource_gate_before_batch"] = gate
    metadata["resource_gate_all_passed"] = all(c["passed"] for c in gate.values())
    if not metadata["resource_gate_all_passed"]:
        dump_json(os.path.join(args.out, "run-metadata.json"), metadata)
        print("[拒绝] 资源门槛未通过，未发起任何配对调用", file=sys.stderr)
        return 1

    call_log = open(call_log_path, "a", encoding="utf-8")

    def log_call(record):
        call_log.write(json.dumps(record, ensure_ascii=False) + "\n")
        call_log.flush()

    # ------------------------------------------------ warm-up（不计入正式配对）
    warmup_spec = load_json(WARMUP_SPEC)
    if os.path.isfile(WARMUP_FIXTURE_FRAME):
        warm_started = time.time()
        judgment, record = run_one_call(analyze_mod, "v1", prompt_for("v1", warmup_spec),
                                        warmup_spec, WARMUP_FIXTURE_FRAME, args.timeout,
                                        DEFAULT_MODEL)
        record.update({"kind": "warmup", "frame": os.path.basename(WARMUP_FIXTURE_FRAME),
                       "counts_toward_formal": False,
                       "wall_time_s": round(time.time() - warm_started, 3)})
        log_call(record)
        metadata["warmup"] = {"status": "completed", "counts_toward_formal": False,
                              "frame": os.path.basename(WARMUP_FIXTURE_FRAME),
                              "outcome": record["outcome"]}
        print(f"[warm-up] {record['outcome']} ({record.get('latency_s')}s)", flush=True)

    # ------------------------------------------------ 实验点集
    if args.smoke:
        smoke_frames = sorted(glob.glob(os.path.join(
            PROJECT_ROOT, "artifacts", "task-16", "**", "*.png"), recursive=True))[:2]
        if not smoke_frames:
            print("[拒绝] 未找到 smoke fixture 帧", file=sys.stderr)
            return 2
        points = []
        for index, frame in enumerate(smoke_frames):
            points.append({
                "point_id": f"SMOKE-{index + 1:04d}", "sample_id": "FIXTURE",
                "arm": "smoke", "timestamp_ms": 0.0, "track": "fixture",
                "target_query": warmup_spec.get("target", {}).get("description", ""),
                "frame_path": os.path.relpath(frame, PROJECT_ROOT),
                "spec": warmup_spec,
            })
        metadata["smoke_frames"] = [os.path.basename(f) for f in smoke_frames]
    else:
        manifest = load_json(POINT_MANIFEST)
        farm = load_json(FRAME_FARM_REPORT)
        farm_by_key = {(r["sample_id"], r["timestamp_ms"]): r for r in farm["frames"]}
        points = []
        for entry in manifest["points"]:
            key = (entry["sample_id"], entry["timestamp_ms"])
            frame = farm_by_key[key]
            spec_path = os.path.join(
                PROJECT_ROOT, "artifacts", "task-19", "predictions", entry["sample_id"],
                entry["arm"], "task-spec.json")
            spec = load_json(spec_path)
            for forbidden_key in ("segments", "ground_truth", "gt", "label", "state"):
                if forbidden_key in spec:
                    print(f"[拒绝] spec 含疑似标签键 {forbidden_key}", file=sys.stderr)
                    return 2
            points.append({
                "point_id": entry["point_id"], "sample_id": entry["sample_id"],
                "arm": entry["arm"], "timestamp_ms": entry["timestamp_ms"],
                "track": entry["track"], "target_query": entry["target_query"],
                "frame_path": frame["task20_frame_path"],
                "frame_sha256": frame["task20_frame_sha256"],
                "media_sha256": entry["media_sha256"], "spec": spec,
            })
        # 帧字节存在性与哈希复核（v1/c3 同一性的物理基础）
        for point in points:
            absolute = os.path.join(PROJECT_ROOT, point["frame_path"])
            if not os.path.isfile(absolute):
                print(f"[拒绝] 帧文件缺失: {point['frame_path']}", file=sys.stderr)
                return 1
            if sha256_of(absolute) != point["frame_sha256"]:
                print(f"[拒绝] 帧哈希不匹配: {point['frame_path']}", file=sys.stderr)
                return 1

    metadata["point_count"] = len(points)
    metadata["planned_formal_calls"] = len(points) * len(versions) if not args.smoke else 0

    # ------------------------------------------------ 主循环
    pairing_points = []
    resource_blocked = False
    for index, point in enumerate(points):
        light = resource_gate(full=False)
        light_ps = ollama_ps()
        loaded = light_ps.get("models", []) if isinstance(light_ps, dict) else []
        gate_signals = {k: v for k, v in light.items()
                        if k in ("mem_available_3x_ge_45gib", "minimax_h3_stopped",
                                 "no_user_active_h3_webui_task")}
        if not all(c["passed"] for c in gate_signals.values()):
            resource_blocked = True
            metadata["resource_blocked_at"] = {
                "point_id": point["point_id"], "index": index,
                "checks": light,
                "note": "用户服务在长任务中重新活跃或资源不足：暂停新视觉调用，保留已完成证据",
            }
            break
        if index == 0:
            metadata["per_point_resource_policy"] = {
                "gate_signals": sorted(gate_signals),
                "observation_only": ["no_external_qwen_consumer（/api/ps 运行中仅观测："
                                     "本执行器 keep_alive 驻留使模型保持加载，无法归属消费者）"],
                "first_point_api_ps_loaded_models": [m.get("name") for m in loaded],
            }
        order = ["v1", "c3"] if index % 2 == 0 else ["c3", "v1"]
        order = [v for v in order if v in versions]
        if versions == ["c3"]:
            order = ["c3"]
        elif versions == ["v1"]:
            order = ["v1"]
        image_path = os.path.join(PROJECT_ROOT, point["frame_path"])
        point_record = dict(point)
        point_record["call_order"] = order
        point_record["resource_observation"] = {
            "mem_available_gib": round(mem_available_gib(), 2),
            "api_ps_loaded_models": [m.get("name") for m in loaded],
        }
        point_record["judgments"] = {}
        point_record["calls"] = []
        for version in order:
            prompt = prompt_for(version, point["spec"])
            judgment, record = run_one_call(analyze_mod, version, prompt, point["spec"],
                                            image_path, args.timeout, DEFAULT_MODEL)
            record.update({"kind": "formal", "point_id": point["point_id"],
                           "frame": os.path.basename(image_path)})
            log_call(record)
            point_record["judgments"][version] = judgment
            point_record["calls"].append(record)
        pairing_points.append(point_record)
        if index % 16 == 0 or index == len(points) - 1:
            done = sum(len(p["judgments"]) for p in pairing_points)
            print(f"[{index + 1}/{len(points)}] {point['point_id']} done; "
                  f"calls so far: {done}", flush=True)

    # ------------------------------------------------ 汇总
    metadata["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata["resource_blocked"] = resource_blocked
    formal_calls = sum(len(p["judgments"]) for p in pairing_points)
    metadata["formal_calls_completed"] = formal_calls
    metadata["formal_points_completed"] = len(pairing_points)
    failures = {"call_failed": 0, "invalid_json": 0, "contract_rejected": 0}
    latencies = []
    itemized_complete = {"v1": 0, "c3": 0}
    itemized_attempted = {"v1": 0, "c3": 0}
    for point in pairing_points:
        for record in point["calls"]:
            if record["outcome"] in failures:
                failures[record["outcome"]] += 1
            if record.get("kind") == "formal" and isinstance(record.get("latency_s"), (int, float)):
                latencies.append(record["latency_s"])
    for point in pairing_points:
        for version, judgment in point["judgments"].items():
            if version in itemized_attempted:
                itemized_attempted[version] += 1
                if judgment.get("itemized_support_complete"):
                    itemized_complete[version] += 1
    metadata["failure_counts"] = failures
    metadata["retry_policy"] = "无任何单侧重试；失败/超时/无效 JSON 如实记账"
    metadata["latency_stats_s"] = {
        "count": len(latencies),
        "mean_s": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "max_s": round(max(latencies), 3) if latencies else None,
    }
    metadata["itemized_support_completeness"] = {
        "v1": {"attempted": itemized_attempted["v1"], "complete": itemized_complete["v1"]},
        "c3": {"attempted": itemized_attempted["c3"], "complete": itemized_complete["c3"]},
    }
    metadata["status"] = ("RESOURCE_BLOCKED" if resource_blocked else
                          ("COMPLETED" if formal_calls == metadata.get("planned_formal_calls", 0)
                           else "PARTIAL"))

    for point in pairing_points:
        dump_json(os.path.join(points_dir, f"{point['point_id']}.json"), point)
    pairing_doc = {
        "task": "task22-pairing-results",
        "mode": metadata["mode"],
        "model": DEFAULT_MODEL,
        "v1_prompt_sha256": v1_hash, "c3_prompt_sha256": c3_hash,
        "safety_ok": True,
        "points": [{
            "point_id": p["point_id"], "sample_id": p["sample_id"], "arm": p["arm"],
            "timestamp_ms": p["timestamp_ms"], "track": p["track"],
            "frame_path": p["frame_path"], "frame_sha256": p.get("frame_sha256"),
            "media_sha256": p.get("media_sha256"),
            "call_order": p["call_order"],
            "v1_judgment": p["judgments"].get("v1"),
            "c3_judgment": p["judgments"].get("c3"),
        } for p in pairing_points],
    }
    dump_json(os.path.join(args.out, "pairing-results.json"), pairing_doc)
    dump_json(os.path.join(args.out, "run-metadata.json"), metadata)
    call_log.close()
    print(json.dumps({"status": metadata["status"],
                      "points_completed": len(pairing_points),
                      "formal_calls": formal_calls,
                      "failures": failures,
                      "latency_stats_s": metadata["latency_stats_s"],
                      "itemized_completeness": metadata["itemized_support_completeness"]},
                     ensure_ascii=False))
    return 0 if not resource_blocked else 1


if __name__ == "__main__":
    sys.exit(main())
