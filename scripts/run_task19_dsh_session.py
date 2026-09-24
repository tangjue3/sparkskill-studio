#!/usr/bin/env python3
"""run_task19_dsh_session.py — Task 19B DSH headless 自主真实域验证会话驱动器（SparkSkill Studio）

预注册协议（artifacts/task-19/preregistration/evaluation-plan.json，阶段 A 提交冻结）：
  自主验证样本 = WEB01（licensed-public dev 样本；阶段 A 冻结，先于任何预测结果）。
  会话只获得：media path（仓库内链接路径）、target query、用户任务、采样预算（19，
  按预算政策）与安全要求。会话不得获得 Ground Truth、expected status、expected
  timeline 或评分结果。

执行 Agent 只负责：资源门槛复核 → 写好任务提示词 → 用 `dsh --profile headless`
启动一个全新会话 → 记录起止时间与 stdout/stderr → 事后校验产物。
会话内的 Skill 发现/加载、VisualTaskSpec 生成与校验、时序证据链运行与报告生成
全部由会话内 Agent 自主完成（非外部脚本串联）。

用法:
    python3 scripts/run_task19_dsh_session.py
退出码: 0 = 会话完成且产物校验通过; 1 = 资源门槛不满足或产物校验失败
"""
import datetime
import json
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
TASK19 = os.path.join(PROJECT_ROOT, "artifacts", "task-19")
SESSION_DIR = os.path.join(TASK19, "dsh-session")
PROMPT_PATH = os.path.join(SESSION_DIR, "task-prompt.txt")
INGESTION = os.path.join(TASK19, "ingestion")
LINK_MAP = os.path.join(INGESTION, "media-link-map.json")
SAMPLE = "WEB01"
STRATEGY_BLOCK = {
    "strategy": "coverage_aware_adaptive",
    "max_model_calls": 19,
    "initial_coverage_samples": 4,
    "coverage_gap_target_ms": 1500,
    "coverage_call_reserve": 4,
    "target_boundary_precision_ms": 500,
    "max_refinement_rounds": 6,
}


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


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


GENERATION_PATTERNS = (
    "vllm.entrypoints", "vllm serve", "api_server", "DiffusionWorker",
    "h3_lite_api.py", "native_bench.py", "h3-next", "diffusion_service",
)
WEBUI_PATTERNS = (
    "minimax-h3/webui", "h3-studio", "minimax-h3/experiments",
    "minimax-h3/env/webui/bin/python app.py",
)


def resource_gate():
    samples = [mem_available_gib()]
    for _ in range(2):
        time.sleep(1)
        samples.append(mem_available_gib())
    import urllib.request
    ollama_ok = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5):
            ollama_ok = True
    except Exception:
        ollama_ok = False
    h3_generation = process_matching(GENERATION_PATTERNS)
    webui = process_matching(WEBUI_PATTERNS)
    gate = {
        "mem_available_gib_samples": samples,
        "mem_gate_passed": all(s is not None and s >= 45 for s in samples),
        "ollama_reachable": ollama_ok,
        "port_8000_listening": port_listening(8000),
        "port_8010_listening": port_listening(8010),
        "h3_generation_processes": len(h3_generation),
        "h3_webui_processes": len(webui),
    }
    gate["all_passed"] = (
        gate["mem_gate_passed"] and ollama_ok
        and not gate["port_8000_listening"] and not gate["port_8010_listening"]
        and gate["h3_generation_processes"] == 0 and gate["h3_webui_processes"] == 0)
    return gate


def main():
    os.makedirs(SESSION_DIR, exist_ok=True)
    gate = resource_gate()
    with open(os.path.join(SESSION_DIR, "resource-gate.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(gate, ensure_ascii=False, indent=2) + "\n")
    print(f"[资源门槛] {json.dumps(gate, ensure_ascii=False)}")
    if not gate["all_passed"]:
        blocked = {
            "task": "task-19b-dsh-autonomous-session",
            "status": "resource_blocked",
            "resource_gate": gate,
            "note": ("资源门槛不满足（MemAvailable 连续三次 ≥45 GiB、Ollama 可达、"
                     "H3 停止）；未启动 DSH 会话、未调用任何模型；不虚构会话产物"),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with open(os.path.join(SESSION_DIR, "resource-blocker-report.json"), "w",
                  encoding="utf-8") as handle:
            handle.write(json.dumps(blocked, ensure_ascii=False, indent=2) + "\n")
        return 1

    link = load_json(LINK_MAP)["links"][SAMPLE]
    media_repo_relative = link["repo_relative_link"]
    sample_manifest = load_json(os.path.join(
        PROJECT_ROOT, "artifacts", "task-19", "preregistration", "sample-manifest.json"))
    target_query = sample_manifest["samples"][SAMPLE]["target_query"]
    prompt = f"""请对以下预注册 dev 样本执行一次完整的受控视觉证据抽取自主任务（真实域验证）：

媒体路径（合法路径，直接使用，禁止猜测或替换）：
{media_repo_relative}

目标：{target_query}；任务类型：object_trace；视觉后端：本地 Ollama；模型：modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest；单帧超时 300 秒。

硬性要求：

1. 你必须先自主发现并加载三个相关 Skill（任务编译/受控视觉证据抽取/证据报告生成），按 Skill 的契约执行；禁止用外部自由脚本替代 Skill 编排。
2. 文本理解、规划与 VisualTaskSpec 生成由你（StepFun，文本模型）完成——你不读取、不看图片，只做规格与规划；所有图像/视频帧分析必须由本地 Qwen Vision 模型真实执行。
3. 生成的 VisualTaskSpec 必须使用 coverage_aware_adaptive 采样策略，参数为冻结预注册值：max_model_calls=19、initial_coverage_samples=4、coverage_gap_target_ms=1500、coverage_call_reserve=4、target_boundary_precision_ms=500、max_refinement_rounds=6；必须通过仓库现有 VisualTaskSpec 校验器（schema + 业务校验全部通过），校验不通过不得继续。
4. 不得从 README、历史 artifacts 或文件名推断媒体内容；媒体以上方给定路径为准。
5. 不得读取任何 Ground Truth 文件来选择或调整采样点；采样只能依据已观测到的视觉证据与策略规则。
6. 运行受控证据链：真实调用本地 Qwen Vision 逐帧分析，遵守硬性调用预算；每次模型原始返回必须存档。
7. 输出必须包含：coverage/refinement 采样 provenance（初始覆盖/覆盖探索/边界细化调用区分、最大相邻采样间隔初始值与最终值、未充分观测区间）、temporal evidence（状态转换与边界不确定性）、以及限制声明（不保证发现任意短事件；采样证据支持的时序结论不是连续跟踪真值）。
8. 最终报告必须由报告器独立复算状态生成；证据不足必须拒答，禁止编造，禁止把 uncertain 写成确定性结论。
9. 全部产物写入：{SESSION_DIR}/（含 task-spec、校验结果、temporal-evidence、final-report、原始模型返回与 provenance）。
10. 如实报告实际模型调用次数、失败与拒答；不得为了让结果好看而重试或挑选样本。
"""
    with open(PROMPT_PATH, "w", encoding="utf-8") as handle:
        handle.write(prompt)

    start = datetime.datetime.now(datetime.timezone.utc)
    started = time.monotonic()
    with open(os.path.join(SESSION_DIR, "session-start.ts"), "w", encoding="utf-8") as handle:
        handle.write(start.isoformat() + "\n")
    proc = subprocess.run(["dsh", "--profile", "headless", prompt],
                          cwd=PROJECT_ROOT, capture_output=True, text=True)
    end = datetime.datetime.now(datetime.timezone.utc)
    elapsed = round(time.monotonic() - started, 3)
    with open(os.path.join(SESSION_DIR, "session-end.ts"), "w", encoding="utf-8") as handle:
        handle.write(end.isoformat() + "\n")
    # 日志落盘前脱敏（用户 home 绝对路径 → ~；与 run_tier3_eval.py 日志脱敏惯例一致；
    # 只替换路径前缀，不改变 reasoning 内容）
    def sanitize(text):
        # 用户 home 路径脱敏 + 行尾空白清理（日志卫生；reasoning 内容不变）
        return "\n".join(line.rstrip() for line in
                          text.replace(os.path.expanduser("~"), "~").splitlines())

    with open(os.path.join(SESSION_DIR, "session-stdout.txt"), "w", encoding="utf-8") as handle:
        handle.write(sanitize(proc.stdout))
    with open(os.path.join(SESSION_DIR, "session-stderr.txt"), "w", encoding="utf-8") as handle:
        handle.write(sanitize(proc.stderr))
    with open(os.path.join(SESSION_DIR, "session-exit-code.txt"), "w",
              encoding="utf-8") as handle:
        handle.write(str(proc.returncode) + "\n")
    print(f"[会话结束] exit={proc.returncode} 耗时={elapsed}s "
          f"({start.isoformat()} → {end.isoformat()})")

    checks = {}
    temporal_path = os.path.join(SESSION_DIR, "temporal-evidence.json")
    report_path = os.path.join(SESSION_DIR, "final-report.json")
    if not os.path.isfile(report_path):
        report_path = os.path.join(SESSION_DIR, "temporal-report.json")
    spec_candidates = [os.path.join(SESSION_DIR, name) for name in
                       ("visual-task-spec.json", "task-spec.json")]
    spec_path = next((p for p in spec_candidates if os.path.isfile(p)),
                     spec_candidates[0])
    for path in (spec_path, temporal_path, report_path):
        checks[os.path.basename(path)] = os.path.isfile(path)
    summary = {
        "task": "task-19b-dsh-autonomous-session",
        "sample": SAMPLE,
        "status": "completed" if proc.returncode == 0 else "session_nonzero_exit",
        "session_exit_code": proc.returncode,
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "elapsed_s": elapsed,
        "prompt_file": "artifacts/task-19/dsh-session/task-prompt.txt",
        "autonomous": True,
        "artifacts_present": checks,
        "resource_gate": gate,
        "sampling_strategy_required": STRATEGY_BLOCK,
    }
    if os.path.isfile(temporal_path):
        with open(temporal_path, encoding="utf-8") as handle:
            doc = json.load(handle)
        provenance = doc.get("sampling_provenance") or {}
        summary["strategy"] = doc.get("sampling_strategy")
        summary["actual_model_calls"] = provenance.get("actual_model_calls")
        summary["configured_budget"] = provenance.get("configured_budget")
        summary["budget_exhausted"] = provenance.get("budget_exhausted")
        summary["evidence_nature"] = doc.get("evidence_nature")
        summary["first_confirmed_observed_ms"] = (
            doc.get("temporal_evidence") or {}).get("first_confirmed_observed_ms")
        summary["last_confirmed_observed_ms"] = (
            doc.get("temporal_evidence") or {}).get("last_confirmed_observed_ms")
        summary["state_transition_count"] = (
            doc.get("temporal_evidence") or {}).get("state_transition_count")
    with open(os.path.join(SESSION_DIR, "session-summary.json"), "w",
              encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    ok = (proc.returncode == 0 and all(checks.values())
          and summary.get("actual_model_calls") is not None)
    print(f"[产物校验] {checks} actual_calls={summary.get('actual_model_calls')} "
          f"budget={summary.get('configured_budget')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
