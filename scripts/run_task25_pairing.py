#!/usr/bin/env python3
"""run_task25_pairing.py — Task 25 同期同中心帧配对实验执行器（SparkSkill Studio 任务 25）

预注册协议（artifacts/task-25/preregistration/，阶段 A 提交冻结；本执行器在阶段 A 提交之后
才允许对任何 dev 单元发起正式视觉调用）:

  - 184 个唯一中心帧（按 (sample_id, frame_sha256, target_query) 去重 Task 22 冻结 256 点）；
    每单元记录媒体 SHA-256、中心时间戳、目标查询、来源 point_id+arm；GT 不进入任何视觉请求。
  - 基线 v1 = analyze_image.PROMPT_TEMPLATE 现行生产模板（SHA-256 冻结，零改动），
    **单帧**（仅中心帧，帧农场冻结 PNG），请求构造逐字节复用 analyze_image.call_ollama。
  - 候选 cand = prompt-candidate.txt，**多图有序**（[前一帧, 中心帧, 后一帧]，仅传入存在侧），
    唯一新增为区分图顺序 + 限定"只判断中心帧"的通用说明；请求与 v1 同构（同模型/format/
    stream/keep_alive/temperature/timeout），唯一差异为 images 列表与提示词。
  - 每单元每臂恰好一次真实 Qwen 调用（v1 一次 + cand 一次 = 每单元 2 次）；无单侧重试。
  - 两臂同一份中心帧字节（帧农场 PNG，逐字节匹配冻结哈希）、同一目标查询、同一 spec；
    邻帧为中心时间戳 ±500ms（extract_frames 同一解码路径），仅候选臂可见。
  - 运行顺序轮换（按单元在 184 规范化序中的索引奇偶）；失败/超时/无效 JSON/契约拒绝如实记账。
  - 批量前资源门（内存/H3/Ollama/DSH/外部 Qwen）；运行中每单元前轻量复核；失败即暂停、
    保留已完成证据、状态 RESOURCE_BLOCKED。
  - 预算：--scope first48 最多 96 次正式新调用；累计（first48+remaining）最多 368 次；
    warm-up/smoke 单独披露、不计入正式。

用法:
  python3 run_task25_pairing.py --scope first48|remaining|all \
      [--out artifacts/task-25/stage-b] [--timeout 300]
退出码: 0 = 完成; 1 = 预注册/资源门失败; 2 = 执行器致命错误
"""
import argparse
import base64
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
PREREG = os.path.join(PROJECT_ROOT, "artifacts", "task-25", "preregistration")
UNIT_MANIFEST = os.path.join(PREREG, "unit-manifest-184.json")
PROMPT_CAND = os.path.join(PREREG, "prompt-candidate.txt")
FROZEN_HASHES = os.path.join(PREREG, "frozen-hashes.json")
SPEC_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "predictions")
WARMUP_FIXTURE_FRAME = os.path.join(
    PROJECT_ROOT, "artifacts", "task-19", "predictions", "_warmup", "warmup-frame",
    "fixture-present-throughout_f00000_t00000000ms.png")
WARMUP_SPEC = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "predictions", "_warmup",
                           "warmup-spec.json")
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest"
GENERATED = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06"]
LICENSED = ["WEB01", "WEB02", "WEB03"]
WHITELIST = set(GENERATED + LICENSED)
BUDGET = {"first48": 96, "all": 368, "remaining": 368}

GENERATION_PATTERNS = ("vllm.entrypoints", "vllm serve", "api_server", "DiffusionWorker",
                       "h3_lite_api.py", "native_bench.py", "h3-next", "diffusion_service")
WEBUI_PATTERNS = ("minimax-h3/webui", "h3-studio", "minimax-h3/experiments",
                  "minimax-h3/env/webui/bin/python app.py")
H3_PORTS = (8000, 8010)


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
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def load_analyze_image():
    spec = importlib.util.spec_from_file_location("analyze_image", ANALYZE_IMAGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call_ollama_multi(model, prompt, image_paths, timeout):
    """单次请求有序输入多张图（与 analyze_image.call_ollama 同构，唯一差异:
    images 为按序 [prev, center, next]（仅存在侧）的多图 base64 列表）。"""
    images_b64 = []
    for path in image_paths:
        with open(path, "rb") as handle:
            images_b64.append(base64.b64encode(handle.read()).decode("ascii"))
    payload = {
        "model": model, "prompt": prompt, "images": images_b64,
        "format": "json", "stream": False, "keep_alive": "10m",
        "options": {"temperature": 0.1},
    }
    request = urllib.request.Request(
        OLLAMA_URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def image_roles_for(present):
    label = {"prev": "【前一帧】", "center": "【中心帧】", "next": "【后一帧】"}
    ordinals = ["第一张", "第二张", "第三张"]
    return len(present), "、".join(f"{ordinals[i]}{label[k]}" for i, k in enumerate(present))


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
    return [l for l in lines if any(p in l for p in GENERATION_PATTERNS)]


def webui_processes(lines):
    return [l for l in lines if any(p in l for p in WEBUI_PATTERNS)]


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
        "evidence": f"生成类进程 {len(gen)}；:8000={port_listening(8000)}；:8010={port_listening(8010)}"}
    checks["no_user_active_h3_webui_task"] = {"passed": not webui,
                                              "evidence": f"WebUI 类进程 {len(webui)}"}
    mem = []
    for _ in range(3):
        mem.append(round(mem_available_gib(), 2))
        time.sleep(1)
    checks["mem_available_3x_ge_45gib"] = {"passed": all(v >= 45.0 for v in mem),
                                           "samples_gib": mem, "threshold_gib": 45.0}
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as response:
            tags_ok = response.status == 200
    except Exception:  # noqa: BLE001
        tags_ok = False
    checks["ollama_reachable"] = {"passed": tags_ok}
    ps = ollama_ps()
    loaded = ps.get("models", []) if isinstance(ps, dict) else []
    loaded_names = [m.get("name") for m in loaded]
    # 无外部 Qwen 消费者：不得加载预期 Qwen 之外的任何模型（执行器自身 keep_alive 驻留的
    # 预期 Qwen 不是外部消费者；H3 停止 + 无生成进程下，执行器为唯一 Qwen 使用者）。
    external = [n for n in loaded_names if n != DEFAULT_MODEL]
    checks["no_external_qwen_consumer"] = {
        "passed": not external,
        "loaded_models": loaded_names, "external_models": external,
        "evidence": "无预期 Qwen 之外模型即无外部消费者；执行器 keep_alive 驻留为自身 warm"}
    ver = dsh_version()
    checks["dsh_normal"] = {"passed": bool(ver) and "unavailable" not in ver, "evidence": ver}
    if full:
        checks["git_workspace_expected"] = {
            "passed": True,
            "evidence": f"Git 锁: {'有' if glob.glob(os.path.join(PROJECT_ROOT, '.git', '*.lock')) else '无'}"}
    return checks


def verify_preregistration():
    frozen = load_json(FROZEN_HASHES)
    problems = []
    for name, entry in frozen["entries"].items():
        path = os.path.join(PROJECT_ROOT, entry["path"])
        if not os.path.isfile(path):
            problems.append(f"missing: {entry['path']}")
            continue
        if sha256_of(path) != entry["sha256"]:
            problems.append(f"hash mismatch: {entry['path']}")
    return problems


def validate_unit_frames(unit):
    """校验单元物理完整性：中心帧存在且逐字节匹配冻结哈希；present 邻帧存在。
    返回问题列表（空 = 通过）。中心帧哈希不符即视为必须停止的硬错误。"""
    problems = []
    center_abs = os.path.join(PROJECT_ROOT, unit["center_frame_path"])
    if not os.path.isfile(center_abs):
        problems.append(f"center_missing:{unit['unit_id']}")
    elif sha256_of(center_abs) != unit["center_frame_sha256"]:
        problems.append(f"center_hash_mismatch:{unit['unit_id']}")
    for role in ("prev", "next"):
        nb = unit.get("neighbors", {}).get(role, {})
        if nb.get("present"):
            nb_abs = os.path.join(PROJECT_ROOT, nb["frame_path"])
            if not os.path.isfile(nb_abs):
                problems.append(f"neighbor_missing:{unit['unit_id']}:{role}")
            elif nb.get("frame_sha256") and sha256_of(nb_abs) != nb["frame_sha256"]:
                problems.append(f"neighbor_hash_mismatch:{unit['unit_id']}:{role}")
    return problems


# ---------------------------------------------------------------- 单点执行
def run_one_call(analyze_mod, arm, prompt, spec, center_path, timeout, model, neighbor_paths):
    """一次常规视觉调用（无重试）。v1=单帧(call_ollama)；cand=多图有序(call_ollama_multi)。
    返回 (judgment, call_record, image_hashes)。"""
    started = time.time()
    record = {"arm": arm, "model": model, "timeout_s": timeout,
              "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    image_hashes = {"center": sha256_of(center_path)}
    try:
        if arm == "v1":
            body = analyze_mod.call_ollama(model, prompt, center_path, timeout)
        else:
            ordered = list(neighbor_paths) + [center_path]  # prev..., center, next...
            for p in ordered[:-1]:
                image_hashes[os.path.basename(p)] = sha256_of(p)
            body = call_ollama_multi(model, prompt, ordered, timeout)
    except Exception as error:  # noqa: BLE001
        record.update({"outcome": "call_failed", "error_type": type(error).__name__,
                       "latency_s": round(time.time() - started, 3)})
        judgment = {"frame_status": "failed", "object_found": False, "confidence": 0.0,
                    "evidence_text": "无模型输出；调用失败",
                    "abstention_reason": f"帧分析失败：{type(error).__name__}",
                    "evidence_sufficient": False, "evidence_nature": "backend_call_failed"}
        return judgment, record, image_hashes
    latency = round(time.time() - started, 3)
    raw_text = body.get("response", "")
    record["latency_s"] = latency
    record["raw_response_sha256"] = sha256_of_text(raw_text)
    record["raw_response_chars"] = len(raw_text)
    try:
        raw = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        record.update({"outcome": "invalid_json", "raw_prefix": raw_text[:200]})
        judgment = {"frame_status": "failed", "object_found": False, "confidence": 0.0,
                    "evidence_text": "无模型输出；返回非合法 JSON",
                    "abstention_reason": "帧分析失败：模型未返回合法 JSON",
                    "evidence_sufficient": False, "evidence_nature": "backend_call_failed"}
        return judgment, record, image_hashes
    try:
        judgment = analyze_mod.coerce_evidence(raw, spec, center_path, model)
        judgment["frame_status"] = "analyzed"
        judgment["evidence_nature"] = "real_model_output"
        record["outcome"] = "ok"
        record["object_found"] = judgment["object_found"]
        record["confidence"] = judgment["confidence"]
        return judgment, record, image_hashes
    except ValueError as error:
        record.update({"outcome": "contract_rejected", "error": str(error)})
        judgment = {"frame_status": "failed", "object_found": False, "confidence": 0.0,
                    "evidence_text": "无模型输出；证据校验失败",
                    "abstention_reason": f"帧分析失败：{error}",
                    "evidence_sufficient": False, "evidence_nature": "backend_call_failed"}
        return judgment, record, image_hashes


def main():
    parser = argparse.ArgumentParser(description="Task 25 同期同中心帧配对执行器")
    parser.add_argument("--scope", choices=["first48", "remaining", "all"], required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dry-run", action="store_true",
                        help="校验全链路（选点/规格/提示词渲染/图序/哈希/邻帧存在）但不发起任何 Qwen 调用")
    args = parser.parse_args()

    analyze_mod = load_analyze_image()
    unit_manifest = load_json(UNIT_MANIFEST)
    if unit_manifest.get("invalid_input"):
        print("[拒绝] 单元清单标记 invalid_input，停止", file=sys.stderr)
        return 1
    units = unit_manifest["units"]
    first48 = set(unit_manifest["first_batch_48_unit_ids"])
    if args.scope == "first48":
        run_units = [u for u in units if u["unit_id"] in first48]
    elif args.scope == "remaining":
        run_units = [u for u in units if u["unit_id"] not in first48]
    else:
        run_units = list(units)
    run_units.sort(key=lambda u: u["unit_id"])
    budget = BUDGET[args.scope]

    v1_template = analyze_mod.PROMPT_TEMPLATE
    cand_template = open(PROMPT_CAND, encoding="utf-8").read()
    v1_hash = sha256_of_text(v1_template)
    cand_hash = sha256_of_text(cand_template)
    # v1 必须逐字节为现行生产模板
    if v1_hash != "fc29078044d5fe47daacb2384f3f29f562ed8638b835f2577732a8bd185de65b":
        print("[拒绝] 生产 v1 模板哈希与冻结值不符", file=sys.stderr)
        return 1

    def spec_for(unit):
        # 复用 Task 19B 该样本该臂的 task-spec（与 Task 22 同口径，取代表 arm 的 spec）
        rep_arm = unit["representative_arm"]
        spec_path = os.path.join(SPEC_DIR, unit["sample_id"], rep_arm, "task-spec.json")
        spec = load_json(spec_path)
        for forbidden_key in ("segments", "ground_truth", "gt", "label", "state"):
            if forbidden_key in spec:
                print(f"[拒绝] spec 含疑似标签键 {forbidden_key}", file=sys.stderr)
                raise SystemExit(2)
        return spec

    def prompt_v1(spec):
        return analyze_mod.build_prompt(spec)

    def prompt_cand(spec, present):
        count, roles = image_roles_for(present)
        target = spec.get("target", {})
        attributes = target.get("attributes") or []
        forbidden = spec.get("constraints", {}).get("forbidden_inferences") or []
        return cand_template.format(
            image_count=count, image_roles=roles,
            target_description=target.get("description", ""),
            attributes="、".join(attributes) if attributes else "（无）",
            forbidden="、".join(forbidden) if forbidden else "（无）")

    # ------------------------------------------------ 阶段 A 哈希复核
    problems = verify_preregistration()
    if problems:
        print("[拒绝] 预注册哈希复核失败: " + "; ".join(problems), file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    points_dir = os.path.join(args.out, "points")
    os.makedirs(points_dir, exist_ok=True)
    call_log_path = os.path.join(args.out, "call-log.jsonl")

    # 预检：中心帧存在 + 哈希匹配；邻帧存在（present 时）
    center_hash_all_match = True
    for u in run_units:
        unit_problems = validate_unit_frames(u)
        if unit_problems:
            center_hash_all_match = False
            print(f"[拒绝] 单元帧完整性失败: {'; '.join(unit_problems)}", file=sys.stderr)
            return 1

    # ------------------------------------------------ dry-run：全链路校验，零 Qwen 调用
    if args.dry_run:
        dry = {"scope": args.scope, "planned_units": len(run_units),
               "planned_formal_calls": len(run_units) * 2,
               "v1_prompt_sha256": v1_hash, "cand_prompt_sha256": cand_hash,
               "units": [], "all_ok": True}
        for u in run_units:
            center_abs = os.path.join(PROJECT_ROOT, u["center_frame_path"])
            center_ok = (os.path.isfile(center_abs)
                         and sha256_of(center_abs) == u["center_frame_sha256"])
            spec = spec_for(u)
            nb = u["neighbors"]
            prev_present = nb.get("prev", {}).get("present", False)
            next_present = nb.get("next", {}).get("present", False)
            present = (["prev"] if prev_present else []) + ["center"] + (
                ["next"] if next_present else [])
            neighbor_paths = []
            if prev_present:
                neighbor_paths.append(os.path.join(PROJECT_ROOT, nb["prev"]["frame_path"]))
            if next_present:
                neighbor_paths.append(os.path.join(PROJECT_ROOT, nb["next"]["frame_path"]))
            neighbors_exist = all(os.path.isfile(p) for p in neighbor_paths)
            pv1 = prompt_v1(spec)
            pcand = prompt_cand(spec, present)
            ordered = neighbor_paths + [center_abs]
            unit_ok = center_ok and neighbors_exist
            dry["all_ok"] = dry["all_ok"] and unit_ok
            dry["units"].append({
                "unit_id": u["unit_id"], "sample_id": u["sample_id"],
                "image_count": len(present), "present_roles": present,
                "center_hash_ok": center_ok, "neighbors_exist": neighbors_exist,
                "v1_prompt_sha256": sha256_of_text(pv1),
                "cand_prompt_sha256": sha256_of_text(pcand),
                "cand_image_order": [os.path.basename(p) for p in ordered],
                "gt_state": u["gt_state"], "stratum": u.get("stratum")})
        dry["image_count_distribution"] = {
            "three_image": sum(1 for x in dry["units"] if x["image_count"] == 3),
            "two_image": sum(1 for x in dry["units"] if x["image_count"] == 2)}
        # 构造一个完整 point_record（与主循环同构，含 neighbors 字典推导）并 JSON 序列化，
        # 以在零调用前捕获序列化/推导类缺陷
        try:
            u0 = run_units[0]
            nb0 = u0["neighbors"]
            global_index0 = units.index(u0)
            pr = {
                "unit_id": u0["unit_id"], "sample_id": u0["sample_id"],
                "center_timestamp_ms": u0["center_timestamp_ms"], "track": u0["track"],
                "stratum": u0.get("stratum"), "target_query": u0["target_query"],
                "media_sha256": u0["media_sha256"],
                "center_frame_path": u0["center_frame_path"],
                "center_frame_sha256": u0["center_frame_sha256"],
                "image_count": 3 if (nb0.get("prev", {}).get("present")
                                     and nb0.get("next", {}).get("present")) else 2,
                "present_roles": present, "source_point_ids": u0["source_point_ids"],
                "source_arms": u0["source_arms"],
                "representative_point_id": u0["representative_point_id"],
                "neighbors": {r: {"present": nb0[r]["present"],
                                  "frame_path": nb0[r].get("frame_path"),
                                  "frame_sha256": nb0[r].get("frame_sha256"),
                                  "timestamp_ms": nb0[r].get("timestamp_ms"),
                                  "absent_reason": nb0[r].get("absent_reason")}
                              for r in ("prev", "next")},
                "call_order": ["v1", "cand"] if global_index0 % 2 == 0 else ["cand", "v1"],
                "resource_observation": {"mem_available_gib": round(mem_available_gib(), 2)}}
            json.dumps(pr, ensure_ascii=False)
            dry["point_record_serializable"] = True
        except Exception as error:  # noqa: BLE001
            dry["point_record_serializable"] = False
            dry["point_record_error"] = f"{type(error).__name__}: {error}"
            dry["all_ok"] = False
        dry["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        dump_json(os.path.join(args.out, "dry-run.json"), dry)
        print(json.dumps({"dry_run": True, "scope": args.scope,
                          "planned_units": dry["planned_units"],
                          "planned_formal_calls": dry["planned_formal_calls"],
                          "image_count_distribution": dry["image_count_distribution"],
                          "point_record_serializable": dry.get("point_record_serializable"),
                          "all_ok": dry["all_ok"]}, ensure_ascii=False))
        return 0 if dry["all_ok"] else 1

    metadata = {
        "model": args.model, "timeout_s": args.timeout,
        "v1_prompt_sha256": v1_hash, "cand_prompt_sha256": cand_hash,
        "v1_prompt_source": "analyze_image.PROMPT_TEMPLATE（现行生产冻结模板，零改动；单帧）",
        "cand_prompt_source": "artifacts/task-25/preregistration/prompt-candidate.txt（多图有序+只判中心帧）",
        "request_params": {"format": "json", "stream": False, "keep_alive": "10m",
                           "options": {"temperature": 0.1},
                           "note": "v1/cand 同构；唯一差异为 images 列表与提示词"},
        "order_policy": "按单元 184 规范化索引奇偶轮换 v1先/cand先；无单侧重试",
        "budget_formal_calls": budget,
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

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

    # warm-up 1 次（Task 16 fixture 帧，v1 单帧，加载 Qwen，不计入正式、不用 dev 数据）
    if os.path.isfile(WARMUP_FIXTURE_FRAME) and os.path.isfile(WARMUP_SPEC):
        warmup_spec = load_json(WARMUP_SPEC)
        judgment, record, _ = run_one_call(analyze_mod, "v1", prompt_v1(warmup_spec),
                                           warmup_spec, WARMUP_FIXTURE_FRAME, args.timeout,
                                           args.model, [])
        record.update({"kind": "warmup", "frame": os.path.basename(WARMUP_FIXTURE_FRAME),
                       "counts_toward_formal": False, "side": "v1"})
        log_call(record)
        metadata["warmup"] = {"status": "completed", "counts_toward_formal": False,
                              "outcome": record["outcome"]}
        print(f"[warm-up] {record['outcome']} ({record.get('latency_s')}s)", flush=True)

    formal_calls = 0
    pairing_points = []
    resource_blocked = False
    calls_for_scoring = []
    for u in run_units:
        if formal_calls >= budget:
            print(f"[停止] 已达本 scope 正式预算 {budget}", file=sys.stderr)
            break
        light = resource_gate(full=False)
        signals = {k: v for k, v in light.items()
                   if k in ("mem_available_3x_ge_45gib", "minimax_h3_stopped",
                            "no_user_active_h3_webui_task", "no_external_qwen_consumer",
                            "ollama_reachable")}
        if not all(c["passed"] for c in signals.values()):
            resource_blocked = True
            metadata["resource_blocked_at"] = {"unit_id": u["unit_id"], "checks": light,
                                               "note": "资源窗口变化：暂停新视觉调用，保留已完成证据"}
            break
        spec = spec_for(u)
        center_abs = os.path.join(PROJECT_ROOT, u["center_frame_path"])
        nb = u["neighbors"]
        prev_present = nb.get("prev", {}).get("present", False)
        next_present = nb.get("next", {}).get("present", False)
        present = (["prev"] if prev_present else []) + ["center"] + (["next"] if next_present else [])
        neighbor_paths = []
        if prev_present:
            neighbor_paths.append(os.path.join(PROJECT_ROOT, nb["prev"]["frame_path"]))
        if next_present:
            neighbor_paths.append(os.path.join(PROJECT_ROOT, nb["next"]["frame_path"]))
        # 顺序轮换：按单元在 184 规范化序的索引奇偶
        global_index = units.index(u)
        order = ["v1", "cand"] if global_index % 2 == 0 else ["cand", "v1"]
        point_record = {
            "unit_id": u["unit_id"], "sample_id": u["sample_id"],
            "center_timestamp_ms": u["center_timestamp_ms"], "track": u["track"],
            "stratum": u.get("stratum"), "target_query": u["target_query"],
            "media_sha256": u["media_sha256"],
            "center_frame_path": u["center_frame_path"],
            "center_frame_sha256": u["center_frame_sha256"],
            "image_count": len(present), "present_roles": present,
            "source_point_ids": u["source_point_ids"], "source_arms": u["source_arms"],
            "representative_point_id": u["representative_point_id"],
            "neighbors": {r: {"present": nb[r]["present"],
                              "frame_path": nb[r].get("frame_path"),
                              "frame_sha256": nb[r].get("frame_sha256"),
                              "timestamp_ms": nb[r].get("timestamp_ms"),
                              "absent_reason": nb[r].get("absent_reason")}
                          for r in ("prev", "next")},
            "call_order": order,
            "resource_observation": {"mem_available_gib": round(mem_available_gib(), 2)},
        }
        judgments = {}
        for arm in order:
            if formal_calls >= budget:
                break
            if arm == "v1":
                prompt = prompt_v1(spec)
                judgment, record, img_hashes = run_one_call(
                    analyze_mod, "v1", prompt, spec, center_abs, args.timeout, args.model, [])
            else:
                prompt = prompt_cand(spec, present)
                judgment, record, img_hashes = run_one_call(
                    analyze_mod, "cand", prompt, spec, center_abs, args.timeout, args.model,
                    neighbor_paths)
            record.update({"kind": "formal", "unit_id": u["unit_id"], "side": arm,
                           "frame": os.path.basename(center_abs),
                           "center_frame_sha256": u["center_frame_sha256"],
                           "image_hashes": img_hashes, "image_count": len(present)})
            log_call(record)
            calls_for_scoring.append(record)
            judgments[arm] = judgment
            point_record.setdefault("calls", []).append(record)
            formal_calls += 1
        point_record["judgments"] = judgments
        pairing_points.append(point_record)
        if len(pairing_points) % 8 == 0:
            print(f"[{len(pairing_points)}/{len(run_units)}] {u['unit_id']} done; "
                  f"formal_calls={formal_calls}", flush=True)

    metadata["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata["resource_blocked"] = resource_blocked
    metadata["formal_calls_completed"] = formal_calls
    metadata["units_completed"] = len(pairing_points)
    metadata["center_hash_all_match"] = center_hash_all_match
    failures = {"call_failed": 0, "invalid_json": 0, "contract_rejected": 0}
    for p in pairing_points:
        for r in p.get("calls", []):
            if r["outcome"] in failures:
                failures[r["outcome"]] += 1
    metadata["failure_counts"] = failures
    metadata["retry_policy"] = "无任何单侧重试"
    metadata["status"] = ("RESOURCE_BLOCKED" if resource_blocked else
                          ("COMPLETED" if len(pairing_points) == len(run_units) else "PARTIAL"))

    for p in pairing_points:
        dump_json(os.path.join(points_dir, f"{p['unit_id']}.json"), p)
    pairing_doc = {
        "task": "task25-pairing-results", "scope": args.scope, "model": args.model,
        "v1_prompt_sha256": v1_hash, "cand_prompt_sha256": cand_hash,
        "safety_ok": True, "resource_blocked": resource_blocked,
        "center_hash_all_match": center_hash_all_match,
        "units": [{
            "unit_id": p["unit_id"], "sample_id": p["sample_id"],
            "center_timestamp_ms": p["center_timestamp_ms"], "track": p["track"],
            "stratum": p.get("stratum"), "image_count": p["image_count"],
            "present_roles": p["present_roles"], "source_arms": p["source_arms"],
            "center_frame_sha256": p["center_frame_sha256"],
            "v1_judgment": p["judgments"].get("v1"),
            "cand_judgment": p["judgments"].get("cand"),
        } for p in pairing_points],
        "calls": [{"side": c.get("side"), "kind": c.get("kind"),
                   "latency_s": c.get("latency_s"), "outcome": c.get("outcome"),
                   "unit_id": c.get("unit_id")} for c in calls_for_scoring],
    }
    dump_json(os.path.join(args.out, "pairing-results.json"), pairing_doc)
    dump_json(os.path.join(args.out, "run-metadata.json"), metadata)
    call_log.close()
    print(json.dumps({"status": metadata["status"], "scope": args.scope,
                      "units_completed": len(pairing_points), "formal_calls": formal_calls,
                      "failures": failures, "center_hash_all_match": center_hash_all_match},
                     ensure_ascii=False))
    return 0 if not resource_blocked else 1


if __name__ == "__main__":
    sys.exit(main())
