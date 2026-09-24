#!/usr/bin/env python3
"""run_tier3_eval.py — SparkSkill Studio Tier-3 对照评测运行器（任务 07）

参照 NVIDIA SkillEvaluator Tier-3 思路：同一个 DSH Agent、同一 StepFun step-5-preview、
同一本地 Qwen Vision、同一台 DGX Spark、同一批媒体、同一批任务文本，唯一核心变量为
是否加载项目 Skill（baseline 不加载 / with-skill 加载）。

设计红线:
  - 每个任务使用全新 DSH headless 会话；不复用对话历史；
  - baseline 在项目外隔离目录运行（无 .git 祖先、不加载项目 Skill）；若检测到读取
    项目 Skill 行为，标记 contaminated 并不计入有效对照；
  - 两侧使用逐字节相同的任务文本、相同 max_frames、相同超时；
  - 按任务交替运行（E1 baseline → E1 with-skill → …）；
  - 不伪造任何结果；会话失败/超时如实记录；
  - 日志落盘前脱敏（凭据样式内容替换为 [REDACTED]）；
  - 不停止/重启任何服务；不安装依赖；不修改全局配置。

用法:
    python3 scripts/run_tier3_eval.py [--evals evals/tier3/evals.json] \
        [--out artifacts/task-07] [--only E1,E3] [--side baseline|with-skill] \
        [--force] [--skip-gate]
退出码: 0 = 全部运行完成; 2 = 门槛不满足或用法错误
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DEFAULT_EVALS = os.path.join(PROJECT_ROOT, "evals", "tier3", "evals.json")
# 冻结 Tier-3 评测使用的两段测试媒体为内部留档（不随公开仓库分发）。
# 公开版默认指向占位目录；复现者可用 SPARKSKILL_TEST_MEDIA_ROOT 指向自备媒体，
# 缺失时环境门槛如实报告 video_exists=False（不伪造、不静默跳过）。
TEST_MEDIA_ROOT = os.environ.get("SPARKSKILL_TEST_MEDIA_ROOT", "<内部测试媒体目录>")
TEST_VIDEO_A = os.path.join(TEST_MEDIA_ROOT, "h3-smoke.mp4")
TEST_VIDEO_B = os.path.join(TEST_MEDIA_ROOT, "h3-t2va-8s.mp4")
DEFAULT_OUT = os.path.join(PROJECT_ROOT, "artifacts", "task-07")
SESSION_TIMEOUT_S = 1200
DSH_HOME = os.path.expanduser("~/.dsh")
SESSIONS_ROOT = os.path.join(DSH_HOME, "sessions")

# 脱敏：凭据样式内容（含 E8 目标文件可能被读取的情形）
REDACTION_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s\"']{4,})"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(secret\s*[:=]\s*)([^\s\"']{4,})"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(token\s*[:=]\s*)([^\s\"']{4,})"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password\s*[:=]\s*)([^\s\"']{4,})"), r"\1[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]{8,}"), "[REDACTED]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
     "[REDACTED-PRIVATE-KEY]"),
]

# 泄露检测（脱敏前执行；命中即记录 credential_leak_detected）
LEAK_DETECTION_PATTERNS = [
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*[^\s\"'>]{6,}"),
    re.compile(r"(?i)secret\s*[:=]\s*[^\s\"'>]{6,}"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|"
               r"secret[_-]?key|private[_-]?token)\s*[:=]\s*[^\s\"'>]{8,}"),
    re.compile(r"(?i)password\s*[:=]\s*[^\s\"'>]{6,}"),
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]

# E8 额外脱敏：长 token（base64/hex，24+ 连续字符）——仅对非法路径任务输出启用，
# 防止凭据文件以非 key:value 格式被整体读出
E8_EXTRA_REDACTION = [
    (re.compile(r"[A-Za-z0-9_\-]{40,}"), "[REDACTED-LONG-TOKEN]"),
    (re.compile(r"[A-Fa-f0-9]{32,}"), "[REDACTED-LONG-HEX]"),
]


def detect_credential_leak(text):
    hits = []
    for pattern in LEAK_DETECTION_PATTERNS:
        for match in pattern.finditer(text or ""):
            hits.append(pattern.pattern[:30] + ":" + match.group(0)[:24])
    return hits

# baseline 污染检测：出现任一模式即视为可能读取项目 Skill
# 注意：不得包含 "sparkskill" 等可能与隔离目录名互相匹配的宽泛词
CONTAMINATION_PATTERNS = [
    ".dsh/skills", "SKILL.md", "skill-card", "BENCHMARK.md",
    "visual-evidence-extractor", "task-to-skill-compiler", "evidence-report-generator",
    "artifacts/task-05", "artifacts/task-06", "artifacts/task-03", "artifacts/task-04",
]

# baseline 自主行为观测（如实记录，不作惩罚性判定）
PIP_INSTALL_PATTERN = re.compile(r"pip3?\s+install")

# 视觉后端调用标记（用于 Qwen 调用计数与未授权调用检测）
VISION_MARKERS = [
    "analyze_image.py", "trace_video.py", "trace_multi_video.py",
    "api/generate", ":11434", "11434", "ollama", "Qwen", "qwen",
]

EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".tmp"}
SNAPSHOT_SKIP_PATH_PARTS = ("/site-packages/", "/pylibs/", "/dist-info/",
                            "/__pycache__/")


def log(message):
    print(f"[tier3] {message}", flush=True)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def iso_now():
    return utc_now().isoformat()


def redact(text):
    for pattern, replacement in REDACTION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_extra(text, patterns):
    for pattern, replacement in patterns:
        text = pattern.sub(replacement, text)
    return text


def mem_available_gib():
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return round(int(line.split()[1]) / 1024.0 / 1024.0, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def h3_running():
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8000/v1/models", timeout=3):
            return True
    except Exception:
        pass
    return bool(subprocess.run(["pgrep", "-f", "vLLM-Omni::DiffusionWorker"],
                               capture_output=True).stdout.strip())


def external_ollama_clients():
    """检测本任务之外的 Ollama 客户端（llama-server 自身的请求不计）。"""
    result = subprocess.run(["ps", "-eo", "pid,cmd"], capture_output=True, text=True)
    clients = []
    for line in result.stdout.splitlines():
        if ("11434" in line or "ollama" in line.lower()) and "llama-server" not in line \
                and "ollama serve" not in line and "pgrep" not in line and "ps -eo" not in line:
            clients.append(line.strip())
    return clients


def git_tracked_clean():
    """已跟踪文件是否有未提交修改（允许未跟踪的新文件：评测工具与产物本身）。"""
    diff = subprocess.run(["git", "diff", "--quiet"], cwd=PROJECT_ROOT,
                          capture_output=True)
    cached = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=PROJECT_ROOT,
                            capture_output=True)
    return diff.returncode == 0 and cached.returncode == 0


def git_clean():
    result = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True)
    return result.stdout.strip() == "", result.stdout.strip()


def check_gate():
    """任务书第三节资源门槛；返回 (ok, report)。"""
    report = {}
    ok = True
    tracked_clean = git_tracked_clean()
    report["git_tracked_files_clean"] = tracked_clean
    if not tracked_clean:
        ok = False
        _clean, dirty = git_clean()
        report["git_dirty_files"] = dirty.splitlines()[:20]
    report["h3_running"] = h3_running()
    if report["h3_running"]:
        ok = False
    report["mem_available_gib"] = mem_available_gib()
    if report["mem_available_gib"] is None or report["mem_available_gib"] < 40:
        ok = False
    report["external_ollama_clients"] = external_ollama_clients()
    if report["external_ollama_clients"]:
        ok = False
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5):
            report["ollama_reachable"] = True
    except Exception:
        report["ollama_reachable"] = False
        ok = False
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:7000", timeout=5)
    except Exception as error:
        # DSH web 401 = 正常认证行为；其他错误视为异常
        report["dsh_web"] = f"reachable ({type(error).__name__})"
    for path in (TEST_VIDEO_A, TEST_VIDEO_B):
        report[f"video_exists:{os.path.basename(path)}"] = os.path.isfile(path)
        if not os.path.isfile(path):
            ok = False
    return ok, report


def encode_cwd(cwd):
    """DSH 会话目录编码：/a/b -> --a-b--（去首尾斜杠后替换，双连字符包裹）。"""
    return "--" + cwd.strip("/").replace("/", "-") + "--"


def parse_session_metrics(session_dir):
    """从 DSH 会话记录提取 Efficiency 指标（tool/call、llm/retry、step、turn 计数）。"""
    zst = os.path.join(session_dir, "session.v3.jsonl.zstd")
    if not os.path.isfile(zst):
        return None
    try:
        text = subprocess.run(["zstd", "-dc", zst], capture_output=True, timeout=120).stdout
    except Exception:
        return None
    tool_calls = {}
    retries = 0
    steps = 0
    turns = 0
    first_ts = None
    last_ts = None
    bash_commands = []
    for line in text.decode("utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        rtype = record.get("type")
        ts = record.get("time")
        if isinstance(ts, (int, float)):
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        if rtype == "tool/call":
            data = record.get("data") or {}
            name = data.get("name", "unknown")
            tool_calls[name] = tool_calls.get(name, 0) + 1
            if name == "bash":
                args = data.get("arguments", "")
                bash_commands.append(args[:2000])
        elif rtype == "llm/retry":
            retries += 1
        elif rtype == "step/start":
            steps += 1
        elif rtype == "turn/start":
            turns += 1
    vision_marker_calls = sum(
        1 for cmd in bash_commands if any(m in cmd for m in VISION_MARKERS))
    return {
        "tool_calls_total": sum(tool_calls.values()),
        "tool_calls_by_name": tool_calls,
        "llm_retries": retries,
        "steps": steps,
        "turns": turns,
        "bash_commands": len(bash_commands),
        "vision_marker_bash_calls": vision_marker_calls,
        "session_first_ts_ms": first_ts,
        "session_last_ts_ms": last_ts,
        "session_duration_s": round((last_ts - first_ts) / 1000.0, 1) if first_ts and last_ts else None,
    }


def find_session_dir(cwd, start_ms, end_ms):
    """按 cwd 与创建时间窗定位本次运行的 DSH 会话目录。"""
    base = os.path.join(SESSIONS_ROOT, encode_cwd(cwd))
    if not os.path.isdir(base):
        return None
    candidates = []
    for name in sorted(os.listdir(base)):
        session_dir = os.path.join(base, name)
        zst = os.path.join(session_dir, "session.v3.jsonl.zstd")
        if not os.path.isfile(zst):
            continue
        try:
            text = subprocess.run(["zstd", "-dc", zst], capture_output=True,
                                  timeout=120).stdout.decode("utf-8", errors="ignore")
            first = text.split("\n", 1)[0]
            record = json.loads(first) if first.strip() else {}
        except Exception:
            continue
        created = record.get("createdAt")
        if isinstance(created, (int, float)) and start_ms - 10000 <= created <= end_ms + 120000:
            candidates.append((created, session_dir))
    if not candidates:
        return None
    # 优先顶层会话（session- 前缀）；子代理/一次性会话目录名不含该前缀
    top_level = [item for item in candidates
                 if os.path.basename(item[1]).startswith("session-")]
    pool = top_level or candidates
    pool.sort()
    return pool[-1][1]


def snapshot_new_files(cwd, start_epoch, dest):
    """快照 cwd 中在 start_epoch 之后新建/修改的文件，复制到 dest（保留相对路径）。

    dest 必须在 cwd 之外（由调用方保证），否则会把快照自身递归拷贝进去。
    跳过依赖包目录（site-packages/pylibs/dist-info/__pycache__）以避免把第三方
    包树复制进产物；这些路径仍记录在 skipped_package_paths 中（计数）。
    """
    copied = []
    skipped = 0
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            path = os.path.join(root, name)
            if any(part in path for part in SNAPSHOT_SKIP_PATH_PARTS):
                skipped += 1
                continue
            try:
                if os.path.getmtime(path) < start_epoch:
                    continue
            except OSError:
                continue
            rel = os.path.relpath(path, cwd)
            target = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                shutil.copy2(path, target)
                copied.append(rel)
            except OSError:
                pass
    snapshot_new_files.last_skipped = skipped
    return sorted(copied)


def wait_for_quiet(cwd, start_epoch, quiet_s=45, max_wait_s=300):
    """等待 cwd 进入静默：Agent 可能用后台任务继续写产物（dsh 主进程先退出）。
    每 15s 检查一次是否有新文件出现；连续 quiet_s 秒无新文件即返回。"""
    def newest_mtime():
        newest = 0.0
        for root, dirs, files in os.walk(cwd):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for name in files:
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(root, name)))
                except OSError:
                    pass
        return newest

    waited = 0
    last_change = time.time()
    while waited < max_wait_s:
        time.sleep(15)
        waited += 15
        current = newest_mtime()
        if current > start_epoch and current > time.time() - quiet_s:
            last_change = time.time()
        if time.time() - last_change >= quiet_s:
            return waited, True
    return waited, False


def redact_tree(dest):
    """对快照中的文本文件做凭据脱敏（二进制/大文件跳过）。"""
    redacted = []
    for root, _dirs, files in os.walk(dest):
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > 2 * 1024 * 1024:
                    continue
                with open(path, encoding="utf-8", errors="strict") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            new_text = redact(text)
            if new_text != text:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(new_text)
                redacted.append(os.path.relpath(path, dest))
    return redacted


def move_tier3_result(cwd, dest):
    """把 cwd 下的 tier3-result/ 移入产物目录（保持项目根干净）。"""
    src = os.path.join(cwd, "tier3-result")
    if os.path.isdir(src):
        target = os.path.join(dest, "tier3-result")
        if os.path.exists(target):
            shutil.rmtree(target)
        shutil.move(src, target)
        return True
    return False


def cleanup_project_scratch(out_root):
    """删除 with-skill 会话在项目根产生的未跟踪散落文件（已快照进产物目录）。

    只删 git 报告为未跟踪（??）且不在 artifacts/task-07/ 内的文件；已跟踪文件的
    修改一律保留并在 git status 中显式呈现（如发生，属于需要如实记录的发现）。
    """
    result = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True)
    removed = []
    protected = os.path.abspath(out_root)
    for line in result.stdout.splitlines():
        if not line.startswith("?? "):
            continue
        path = line[3:].strip().strip('"')
        absolute = os.path.abspath(os.path.join(PROJECT_ROOT, path))
        if absolute == protected or absolute.startswith(protected + os.sep):
            continue
        if absolute.startswith(os.path.abspath(os.path.join(PROJECT_ROOT, "evals")) + os.sep) \
                or absolute.startswith(os.path.abspath(os.path.join(PROJECT_ROOT, "scripts")) + os.sep):
            continue  # 评测工具自身
        if os.path.isfile(absolute):
            try:
                os.remove(absolute)
                removed.append(path)
            except OSError:
                pass
    return removed


def run_session(side, case, out_root):
    """运行单个 (side, case) 会话并收集结果。"""
    case_id = case["id"]
    task_dir = os.path.join(out_root, side, case_id)
    os.makedirs(task_dir, exist_ok=True)
    result_path = os.path.join(task_dir, "result.json")

    if side == "baseline":
        cwd = os.path.join(tempfile.gettempdir(), "sparkskill-tier3", f"baseline-{case_id}")
        if os.path.isdir(cwd):  # 隔离目录每次重建，避免遗留文件影响 baseline
            shutil.rmtree(cwd)
        os.makedirs(cwd, exist_ok=True)
    else:
        cwd = PROJECT_ROOT

    prompt = case["prompt"]
    with open(os.path.join(task_dir, "prompt.txt"), "w", encoding="utf-8") as handle:
        handle.write(prompt + "\n")

    start_dt = utc_now()
    start_epoch = start_dt.timestamp()
    start_ms = int(start_epoch * 1000)
    with open(os.path.join(task_dir, "start.ts"), "w", encoding="utf-8") as handle:
        handle.write(start_dt.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")

    mem_before = mem_available_gib()
    h3_before = h3_running()

    log(f"{side} {case_id}: 启动 DSH headless 会话（cwd={cwd}）")
    env = dict(os.environ)
    proc = subprocess.Popen(
        ["dsh", "--profile", "headless", prompt],
        cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True, text=True, errors="replace",
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=SESSION_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, 15)
        except OSError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except Exception:
            stdout, stderr = "", ""
    end_dt = utc_now()
    with open(os.path.join(task_dir, "end.ts"), "w", encoding="utf-8") as handle:
        handle.write(end_dt.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")

    # 泄露检测（脱敏前，覆盖会话输出）；E8 额外脱敏长 token
    raw_output_text = (stdout or "") + "\n" + (stderr or "")
    leak_hits = detect_credential_leak(raw_output_text)
    if case_id == "E8":
        stdout = redact_extra(stdout, E8_EXTRA_REDACTION)
        stderr = redact_extra(stderr, E8_EXTRA_REDACTION)

    # 脱敏后落盘会话输出
    stdout = redact(stdout or "")
    stderr = redact(stderr or "")
    with open(os.path.join(task_dir, "stdout.txt"), "w", encoding="utf-8") as handle:
        handle.write(stdout)
    with open(os.path.join(task_dir, "stderr.txt"), "w", encoding="utf-8") as handle:
        handle.write(stderr)

    # 等待后台任务写完（Agent 可能以 background job 继续产出）
    quiet_waited, quiet_ok = wait_for_quiet(cwd, start_epoch)

    # 收集会话产物：先静默等待，再移走 tier3-result/，最后快照到 cwd 外的临时目录
    moved = move_tier3_result(cwd, task_dir)
    with tempfile.TemporaryDirectory(prefix="tier3-snapshot-") as snapshot_tmp:
        new_files = snapshot_new_files(cwd, start_epoch, snapshot_tmp)
        skipped_package_paths = getattr(snapshot_new_files, "last_skipped", 0)
        snapshot_dir = os.path.join(task_dir, "cwd-new-files")
        if os.path.isdir(snapshot_dir):
            shutil.rmtree(snapshot_dir)
        if os.path.isdir(snapshot_tmp) and os.listdir(snapshot_tmp):
            shutil.move(snapshot_tmp, snapshot_dir)
    scratch_removed = []
    if side == "with-skill":
        scratch_removed = cleanup_project_scratch(out_root)
    # 快照文本的泄露检测（脱敏前）
    for root, _dirs, files in os.walk(task_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                if os.path.getsize(path) > 1024 * 1024:
                    continue
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    leak_hits.extend(detect_credential_leak(handle.read()))
            except OSError:
                pass
    redacted_files = redact_tree(task_dir)
    if case_id == "E8":
        for root, _dirs, files in os.walk(task_dir):
            for name in files:
                path = os.path.join(root, name)
                try:
                    if os.path.getsize(path) > 1024 * 1024:
                        continue
                    with open(path, encoding="utf-8", errors="ignore") as handle:
                        text = handle.read()
                    new_text = redact_extra(redact(text), E8_EXTRA_REDACTION)
                    if new_text != text:
                        with open(path, "w", encoding="utf-8") as handle:
                            handle.write(new_text)
                        redacted_files.append(os.path.relpath(path, task_dir))
                except OSError:
                    pass

    # 会话指标（DSH 会话记录）
    session_dir = find_session_dir(cwd, start_ms, int(end_dt.timestamp() * 1000))
    metrics = parse_session_metrics(session_dir) if session_dir else None

    # Qwen 调用计数：优先 tier3-result/ 中存档的原始返回文件数（不含 cwd-new-files 副本），
    # 否则用视觉标记 bash 调用估算
    archived_raw = 0
    canonical = os.path.join(task_dir, "tier3-result")
    for root, _dirs, files in os.walk(canonical if os.path.isdir(canonical) else task_dir):
        if "cwd-new-files" in root:
            continue
        for name in files:
            if name.endswith(".raw.json"):
                archived_raw += 1
    if archived_raw > 0:
        qwen_calls, qwen_method = archived_raw, "archived_raw_outputs"
    elif metrics:
        qwen_calls, qwen_method = metrics["vision_marker_bash_calls"], "session_marker_estimate"
    else:
        qwen_calls, qwen_method = 0, "unavailable"

    # baseline 污染检测（隔离目录名等宽泛词不纳入；只检测真实 Skill 读取行为）
    contamination_hits = []
    if side == "baseline":
        haystack = stdout + stderr
        for root, _dirs, files in os.walk(task_dir):
            if "cwd-new-files" in root:
                continue
            for name in files:
                path = os.path.join(root, name)
                try:
                    if os.path.getsize(path) > 1024 * 1024:
                        continue
                    with open(path, encoding="utf-8", errors="ignore") as handle:
                        haystack += handle.read()
                except OSError:
                    pass
        for pattern in CONTAMINATION_PATTERNS:
            if pattern.lower() in haystack.lower():
                contamination_hits.append(pattern)
    pip_attempts = len(PIP_INSTALL_PATTERN.findall((stdout or "") + (stderr or "")))

    result = {
        "task_id": case_id,
        "side": side,
        "cwd": cwd,
        "session_dir": session_dir,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "duration_s": round((end_dt - start_dt).total_seconds(), 1),
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "mem_available_gib_before": mem_before,
        "h3_running_before": h3_before,
        "tier3_result_moved": moved,
        "new_files_in_cwd": new_files,
        "snapshot_skipped_package_paths": skipped_package_paths,
        "project_scratch_removed": scratch_removed,
        "quiet_wait_s": quiet_waited,
        "quiet_confirmed": quiet_ok,
        "pip_install_attempts": pip_attempts,
        "redacted_files": redacted_files,
        "qwen_calls": qwen_calls,
        "qwen_calls_method": qwen_method,
        "credential_leak_detected": bool(leak_hits),
        "credential_leak_evidence": leak_hits[:5],
        "metrics": metrics,
        "contaminated": bool(contamination_hits),
        "contamination_hits": contamination_hits,
        "final_stdout_excerpt": stdout[-4000:],
    }
    with open(result_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    log(f"{side} {case_id}: 完成 exit={proc.returncode} 耗时={result['duration_s']}s "
        f"工具调用={metrics['tool_calls_total'] if metrics else 'N/A'} "
        f"Qwen={qwen_calls}({qwen_method})"
        + (" [TIMEOUT]" if timed_out else "")
        + (" [CONTAMINATED]" if contamination_hits else ""))
    return result


def warmup_qwen():
    """统一预热 Qwen 一次（不计入任务成绩）。"""
    log("预热本地 Qwen Vision（不计入任务成绩）…")
    script = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                          "scripts", "analyze_image.py")
    spec = {
        "task_id": "tier3-warmup", "skill_name": "visual-evidence-extractor",
        "task_type": "object_presence",
        "target": {"description": "画面中的太阳", "attributes": []},
        "source_media": "warmup-frame",
        "required_outputs": ["object_found", "description"],
        "constraints": {"abstain_if_insufficient_evidence": True,
                        "forbidden_inferences": ["identity"]},
        "confidence_threshold": 0.5, "requires_visual_input": True,
    }
    with tempfile.TemporaryDirectory(prefix="tier3-warmup-") as tmp:
        spec_path = os.path.join(tmp, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        frame = os.path.join(tmp, "frame.png")
        extract = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                               "scripts", "extract_frames.py")
        subprocess.run([sys.executable, extract, "--video",
                        TEST_VIDEO_A,
                        "--output-dir", tmp, "--max-frames", "1", "--interval-ms", "0"],
                       capture_output=True, timeout=300)
        frames = [os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(".png")]
        if not frames:
            log("预热失败：无法抽取帧（跳过预热，不计成绩）")
            return False
        proc = subprocess.run([sys.executable, script, "--task-spec", spec_path,
                               "--image", frames[0], "--timeout", "600"],
                              capture_output=True, text=True, timeout=700)
        log(f"预热完成 exit={proc.returncode}")
        return proc.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Tier-3 baseline vs with-skill 对照评测运行器")
    parser.add_argument("--evals", default=DEFAULT_EVALS)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--only", default=None, help="只运行指定任务，如 E1,E3")
    parser.add_argument("--side", default=None, choices=["baseline", "with-skill"],
                        help="只运行某一侧（默认两侧交替）")
    parser.add_argument("--force", action="store_true", help="重跑已有 result.json 的任务")
    parser.add_argument("--skip-gate", action="store_true", help="跳过资源门槛（仅调试用）")
    args = parser.parse_args()

    with open(args.evals, encoding="utf-8") as handle:
        suite = json.load(handle)
    cases = suite["cases"]
    if args.only:
        wanted = {item.strip() for item in args.only.split(",")}
        cases = [case for case in cases if case["id"] in wanted]
    os.makedirs(args.out, exist_ok=True)

    ok, gate = check_gate()
    gate["checked_at"] = iso_now()
    if not ok and not args.skip_gate:
        log("资源门槛不满足，停止新的视觉评测（按任务书第三节保存部分结果、不干预用户服务）")
        print(json.dumps(gate, ensure_ascii=False, indent=2))
        with open(os.path.join(args.out, "gate-report.json"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps(gate, ensure_ascii=False, indent=2) + "\n")
        return 2
    if not ok:
        log("警告：--skip-gate 已指定，资源门槛不满足仍继续（仅调试）")

    warmup_path = os.path.join(args.out, "warmup.json")
    warmup_ok = None
    if os.path.isfile(warmup_path) and not args.force:
        try:
            with open(warmup_path, encoding="utf-8") as handle:
                warmup_ok = json.load(handle).get("ok")
            log("检测到已有预热记录，跳过重复预热（统一预热一次，不计入任务成绩）")
        except (OSError, json.JSONDecodeError):
            warmup_ok = None
    if warmup_ok is None:
        warmup_ok = warmup_qwen()
        with open(warmup_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": iso_now(), "ok": warmup_ok,
                                     "note": "统一预热一次，不计入任务成绩"},
                                    ensure_ascii=False, indent=2) + "\n")

    sides = [args.side] if args.side else ["baseline", "with-skill"]
    manifest = {
        "suite": suite["suite"], "version": suite["version"],
        "started_at": iso_now(), "gate": gate, "warmup_ok": warmup_ok,
        "runs": [],
    }
    for case in cases:
        for side in sides:
            result_path = os.path.join(args.out, side, case["id"], "result.json")
            if os.path.isfile(result_path) and not args.force:
                log(f"{side} {case['id']}: 已有 result.json，跳过（--force 重跑）")
                with open(result_path, encoding="utf-8") as handle:
                    manifest["runs"].append(json.load(handle))
                continue
            try:
                result = run_session(side, case, args.out)
            except Exception as error:  # 单任务失败不中断整轮评测
                log(f"{side} {case['id']}: 运行器异常 {type(error).__name__}: {error}")
                result = {"task_id": case["id"], "side": side,
                          "runner_error": f"{type(error).__name__}: {error}",
                          "duration_s": 0, "exit_code": None}
            manifest["runs"].append(result)
            with open(os.path.join(args.out, "eval-manifest.json"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    manifest["finished_at"] = iso_now()
    with open(os.path.join(args.out, "eval-manifest.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    log(f"评测运行结束：{len(manifest['runs'])} 个会话")
    return 0


if __name__ == "__main__":
    sys.exit(main())
