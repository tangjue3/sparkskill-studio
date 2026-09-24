#!/usr/bin/env python3
"""run_task16_dsh_session.py — 任务 16 DSH headless 自主会话驱动器（SparkSkill Studio）

执行 Agent 只负责：资源门槛复核 → 写好任务提示词 → 用 `dsh --profile headless`
启动一个全新会话 → 记录起止时间与 stdout/stderr → 事后校验产物。
会话内的 Skill 发现/加载、VisualTaskSpec 生成与校验、adaptive 证据链运行与报告
生成全部由会话内 Agent 自主完成（非外部脚本串联）。

用法:
    python3 scripts/run_task16_dsh_session.py
退出码: 0 = 会话完成且产物校验通过; 1 = 资源门槛不满足或产物校验失败
"""
import datetime
import json
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SESSION_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "dsh-session")
PROMPT_PATH = os.path.join(SESSION_DIR, "task-prompt.txt")


def mem_available_gib():
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 1024.0 / 1024.0, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def resource_gate():
    samples = [mem_available_gib()]
    for _ in range(2):
        time.sleep(1)
        samples.append(mem_available_gib())
    gate = {
        "mem_available_gib_samples": samples,
        "mem_gate_passed": all(s is not None and s >= 45 for s in samples),
        "ollama_reachable": None,
        "port_8000_listening": None,
    }
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5):
            gate["ollama_reachable"] = True
    except Exception:
        gate["ollama_reachable"] = False
    try:
        with open("/proc/net/tcp", encoding="utf-8") as handle:
            listening = any(
                line.split()[3] == "0A" and int(line.split()[1].split(":")[1], 16) == 8000
                for line in handle.readlines()[1:] if len(line.split()) >= 4)
        gate["port_8000_listening"] = listening
    except OSError:
        gate["port_8000_listening"] = None
    gate["all_passed"] = (gate["mem_gate_passed"] and gate["ollama_reachable"] is True
                          and gate["port_8000_listening"] is False)
    return gate


def main():
    os.makedirs(SESSION_DIR, exist_ok=True)
    gate = resource_gate()
    with open(os.path.join(SESSION_DIR, "resource-gate.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(gate, ensure_ascii=False, indent=2) + "\n")
    print(f"[资源门槛] {json.dumps(gate, ensure_ascii=False)}")
    if not gate["all_passed"]:
        blocked = {
            "task": "task-16-dsh-autonomous-session",
            "status": "resource_blocked",
            "resource_gate": gate,
            "note": ("资源门槛不满足（MemAvailable 连续三次 ≥45 GiB、Ollama 可达、"
                     ":8000 无监听）；未启动 DSH 会话、未调用任何模型；"
                     "规则测试结果不受影响。"),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with open(os.path.join(SESSION_DIR, "resource-blocker-report.json"), "w",
                  encoding="utf-8") as handle:
            handle.write(json.dumps(blocked, ensure_ascii=False, indent=2) + "\n")
        return 1

    with open(PROMPT_PATH, encoding="utf-8") as handle:
        prompt = handle.read().strip()

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
    with open(os.path.join(SESSION_DIR, "session-stdout.txt"), "w", encoding="utf-8") as handle:
        handle.write(proc.stdout)
    with open(os.path.join(SESSION_DIR, "session-stderr.txt"), "w", encoding="utf-8") as handle:
        handle.write(proc.stderr)
    print(f"[会话结束] exit={proc.returncode} 耗时={elapsed}s "
          f"({start.isoformat()} → {end.isoformat()})")

    # 事后校验产物（不修改会话产物；兼容 Agent 自选文件名）
    checks = {}
    temporal_path = os.path.join(SESSION_DIR, "temporal-evidence.json")
    report_path = os.path.join(SESSION_DIR, "final-report.json")
    if not os.path.isfile(report_path):
        report_path = os.path.join(SESSION_DIR, "temporal-report.json")
    spec_candidates = [os.path.join(SESSION_DIR, name) for name in
                       ("visual-task-spec.json", "task-spec.json")]
    spec_path = next((p for p in spec_candidates if os.path.isfile(p)), spec_candidates[0])
    for path in (spec_path, temporal_path, report_path):
        checks[os.path.basename(path)] = os.path.isfile(path)
    summary = {
        "task": "task-16-dsh-autonomous-session",
        "status": "completed" if proc.returncode == 0 else "session_nonzero_exit",
        "session_exit_code": proc.returncode,
        "started_at": start.isoformat(),
        "ended_at": end.isoformat(),
        "elapsed_s": elapsed,
        "prompt_file": "artifacts/task-16/dsh-session/task-prompt.txt",
        "autonomous": True,
        "artifacts_present": checks,
        "resource_gate": gate,
    }
    if os.path.isfile(temporal_path):
        with open(temporal_path, encoding="utf-8") as handle:
            doc = json.load(handle)
        provenance = doc.get("sampling_provenance") or {}
        summary["strategy"] = doc.get("sampling_strategy")
        summary["actual_model_calls"] = provenance.get("actual_model_calls")
        summary["configured_budget"] = provenance.get("configured_budget")
        summary["budget_exhausted"] = provenance.get("budget_exhausted")
        summary["refinement_rounds"] = provenance.get("refinement_rounds")
        summary["first_confirmed_observed_ms"] = (
            doc.get("temporal_evidence") or {}).get("first_confirmed_observed_ms")
        summary["last_confirmed_observed_ms"] = (
            doc.get("temporal_evidence") or {}).get("last_confirmed_observed_ms")
        summary["state_transition_count"] = (
            doc.get("temporal_evidence") or {}).get("state_transition_count")
        summary["evidence_nature"] = doc.get("evidence_nature")
    with open(os.path.join(SESSION_DIR, "session-summary.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    ok = (proc.returncode == 0 and all(checks.values())
          and summary.get("actual_model_calls") is not None)
    print(f"[产物校验] {checks} actual_calls={summary.get('actual_model_calls')} "
          f"budget={summary.get('configured_budget')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
