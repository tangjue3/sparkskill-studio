#!/usr/bin/env python3
"""test_demo_app.py — 视觉证据工作台交付前测试（SparkSkill Studio 任务 10）

对应任务书第十七节 20 项验证：Manifest 生成/合法/无凭据/无敏感绝对路径、
HTML 结构、CSS 无外部资源、CSS 颜色全部来自 token、JS 语法、无 CDN、
localhost 服务启动、首页/Manifest/静态资源 HTTP 200、路径遍历拒绝、
非 allowlist 媒体拒绝、PARTIAL/PASS 历史、E9 缺陷与修复、真实性标签一致、
临时预览进程正确关闭。

CPU-only：不调用模型、不访问网络（仅 localhost）。

用法:
    python3 scripts/test_demo_app.py [--results-json <path>]
退出码: 0 = 全部通过; 1 = 存在失败项
"""
import argparse
import atexit
import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")
MANIFEST = os.path.join(APP_DIR, "data", "demo-manifest.json")
TEST_PORT = 8788  # 预览端口 8787 之外的测试端口，避免冲突

RESULTS = []


def record(test_id, name, passed, detail):
    RESULTS.append({"id": test_id, "name": name, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {test_id} — {name}: {detail}")


def http_get(url, method="GET", timeout=10):
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()
    except Exception as error:
        return None, {}, str(error).encode()


def wait_port(port, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
                return True
        except urllib.error.HTTPError:
            return True  # 有响应即算就绪（401/404 也算服务在听）
        except Exception:
            time.sleep(0.3)
    return False


def main():
    # Manifest 是真实 artifacts 的已提交快照。测试会调用构建器验证可生成性，
    # 但必须在退出时恢复快照，避免 generated_at 与跨平台路径重写污染工作区。
    manifest_before = None
    if os.path.isfile(MANIFEST):
        with open(MANIFEST, "rb") as handle:
            manifest_before = handle.read()

    def restore_manifest_snapshot():
        if manifest_before is not None:
            with open(MANIFEST, "wb") as handle:
                handle.write(manifest_before)

    atexit.register(restore_manifest_snapshot)

    # 1) Manifest 可以从真实 artifacts 生成
    proc = subprocess.run([sys.executable, os.path.join(PROJECT_ROOT, "scripts",
                                                        "build_demo_manifest.py")],
                          capture_output=True, text=True, timeout=300)
    record("T1-manifest-generates", "Manifest 可以从真实 artifacts 生成",
           proc.returncode == 0 and os.path.isfile(MANIFEST),
           f"build_demo_manifest.py exit={proc.returncode}；产物存在={os.path.isfile(MANIFEST)}")

    # 2) Manifest JSON 合法
    try:
        with open(MANIFEST, encoding="utf-8") as handle:
            manifest = json.load(handle)
        valid = isinstance(manifest, dict) and "runs" in manifest
    except (OSError, json.JSONDecodeError) as error:
        manifest, valid = None, False
        print(f"  manifest error: {error}")
    record("T2-manifest-json-valid", "Manifest JSON 合法", valid,
           f"顶层键数={len(manifest) if manifest else 0}；runs={len(manifest.get('runs', [])) if manifest else 0}")

    # 3) Manifest 不含凭据
    sensitive = re.compile(
        r"(api[_-]?key|secret|password|passwd|token|bearer|credential|"
        r"sk-[A-Za-z0-9]{8,}|BEGIN [A-Z ]*PRIVATE KEY)", re.IGNORECASE)
    text = open(MANIFEST, encoding="utf-8").read() if manifest else ""
    hits = sensitive.findall(text)
    record("T3-manifest-no-credentials", "Manifest 不含凭据", not hits,
           f"凭据样式命中={hits[:3] or '无'}")

    # 4) Manifest 不含绝对敏感路径（允许 allowlist 的视频文件名，不允许敏感目录/文件）
    bad_paths = []
    if manifest:
        def walk(node):
            if isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, str):
                for pattern in ("/.dsh/.credentials", "/.ssh/", "/etc/", "settings.yaml",
                                "id_rsa", ".env"):
                    if pattern in node:
                        bad_paths.append(node[:60])
        walk(manifest)
    record("T4-manifest-no-sensitive-abs-paths", "Manifest 不含绝对敏感路径", not bad_paths,
           f"敏感绝对路径命中={bad_paths[:2] or '无'}")

    # 5) HTML 结构存在
    html = open(os.path.join(APP_DIR, "index.html"), encoding="utf-8").read()
    required_ids = ["topbar", "run-select", "rail", "evidence-body", "inspector-body",
                    "pane-governance", "pane-benchmark", "truth-badge"]
    missing_ids = [node_id for node_id in required_ids if f'id="{node_id}"' not in html]
    record("T5-html-structure", "HTML 结构存在（Hero + Ribbon + Stage + Inspector + Verification）",
           not missing_ids, f"必需容器缺失={missing_ids or '无'}")

    js_path = os.path.join(APP_DIR, "app.js")
    js = open(js_path, encoding="utf-8").read()

    # 5b) Hero 只展示派生中文摘要，不直接回显原始报告/路径/Schema 字段。
    hero_ids = ["hero-title", "hero-status", "hero-target-detail", "hero-result"]
    hero_block = js[js.find("function renderHero()"):
                    js.find("function benchmarkNarrative")]
    hero_ids_present = all(f'id="{node_id}"' in html for node_id in hero_ids)
    unsafe_hero_bindings = [term for term in
                            ["/home/", "frame_path", "timeline", "task_type", ".conclusion"]
                            if term in hero_block]
    record("T5b-hero-copy-safe", "Hero 使用派生中文摘要且不暴露调试字段",
           hero_ids_present and
           "visualHeroPresentation" in hero_block and not unsafe_hero_bindings,
           f"Hero 容器完整={hero_ids_present}；"
           f"直接绑定敏感/调试字段={unsafe_hero_bindings or '无'}")

    # 5c) 九阶段主要可见标题全部中文化，专名保留。
    chinese_stage_titles = [
        "用户任务", "StepFun 任务规划", "DSH 技能匹配", "视觉任务规范", "视频抽帧",
        "Qwen 视觉证据", "全局证据时间线", "最终结论", "Tier-3 验证"]
    missing_stage_titles = [title for title in chinese_stage_titles if title not in js]
    record("T5c-ribbon-chinese", "九阶段 Evidence Ribbon 标题中文化",
           not missing_stage_titles and "执行证据链" in html and "证据链路" in html,
           f"缺失中文阶段={missing_stage_titles or '无'}")

    # 5d) 正向、负向、拒答与失败状态拥有互斥派生分支。
    status_copy = ["已被确认出现", "在已抽样证据中未被确认", "证据不足，保持拒答", "分析未能完成"]
    status_logic_ok = all(copy in js for copy in status_copy) and \
        "counts.confirmed > 0" in js and "counts.abstained > 0" in js
    record("T5d-hero-status-branches", "Hero 正向/负向/拒答/失败文案不混淆",
           status_logic_ok, f"状态文案完整={all(copy in js for copy in status_copy)}")

    # 5e) 公开版运行记录集合完整：两条会话回放（task-16/18 合成 fixture）+
    #     Tier-3 历史链四条（initial PARTIAL / E9 修复 / v1 误报发现 / v2 PASS），
    #     均可由同一选择器路径渲染，标题不为空。
    PUBLIC_RUN_IDS = [
        "task-16-single-video", "task-18-single-video",
        "tier3-initial", "e9-remediation", "evaluator-v1-finding", "tier3-final",
    ]
    runs = (manifest or {}).get("runs", [])
    run_ids = [str(run.get("id") or "") for run in runs]
    run_titles = [str(run.get("title") or "") for run in runs]
    runs_ok = (run_ids == PUBLIC_RUN_IDS
               and all(title and "undefined" not in title for title in run_titles))
    record("T5e-public-runs-renderable", "公开版六条运行记录标题完整且共用切换逻辑",
           runs_ok and "function selectRun" in js,
           f"运行数={len(run_titles)}；id 集合匹配={run_ids == PUBLIC_RUN_IDS}；"
           f"空标题={sum(not title for title in run_titles)}")

    # 6) CSS 不引用外部资源
    css = open(os.path.join(APP_DIR, "styles.css"), encoding="utf-8").read()
    external = re.findall(r"(?:url\(|@import|src\s*=\s*['\"]https?://)[^)]*", css)
    external += re.findall(r"https?://(?!127\.0\.0\.1)[^\s)'\"]+", css)
    record("T6-css-no-external", "CSS 不引用外部资源", not external,
           f"外部引用={external[:3] or '无'}")

    # 任务 11 P0 回归：组件 display 规则不得覆盖 hidden 原生语义。
    hidden_guard = re.search(
        r"\[hidden\]\s*\{[^}]*display\s*:\s*none\s*!important\s*;?[^}]*\}",
        css, re.DOTALL | re.IGNORECASE)
    record("T6b-hidden-overlay-guard", "hidden 浮层有强制隐藏守卫", bool(hidden_guard),
           "[hidden] 必须始终计算为 display:none")

    # 7) CSS 颜色全部来自 token
    root_block = re.search(r":root\s*\{(.*?)\}", css, re.DOTALL)
    tokens = set(re.findall(r"(--[\w-]+)\s*:", root_block.group(1))) if root_block else set()
    css_body = css[:root_block.start()] + css[root_block.end():] if root_block else css
    css_body = re.sub(r"/\*.*?\*/", "", css_body, flags=re.DOTALL)
    hardcoded = []
    for match in re.finditer(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]+\)", css_body):
        literal = match.group(0)
        start = max(0, match.start() - 60)
        context = css_body[start:match.start()]
        if "var(" in context.split(";")[-1]:
            continue  # var(--x, #fallback) 形式
        hardcoded.append(literal)
    token_values = set(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", root_block.group(1))) \
        if root_block else set()
    untokened = [literal for literal in hardcoded
                 if not any(literal in value for _name, value in token_values)]
    record("T7-css-colors-from-tokens", "CSS 颜色全部来自 token", not untokened,
           f"非 token 颜色={untokened[:5] or '无'}（token 数={len(tokens)}）")

    # 8) JavaScript 语法通过（node --check）
    proc = subprocess.run(["node", "--check", js_path], capture_output=True, text=True)
    record("T8-js-syntax", "JavaScript 语法通过（node --check）", proc.returncode == 0,
           f"node --check exit={proc.returncode} {proc.stderr.strip()[:120]}")

    # 9) 页面无 CDN（HTML/JS/CSS 合并检查）
    cdn = re.findall(r"https?://(?!127\.0\.0\.1)[^\s)'\"]+",
                     html + css + open(js_path, encoding="utf-8").read())
    record("T9-no-cdn", "页面无 CDN", not cdn, f"CDN/外链={cdn[:3] or '无'}")

    # 10) localhost 服务启动 + 11/12/13 HTTP 200 + 14/15 安全拒绝
    server = subprocess.Popen(
        [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "serve_demo.py"),
         "--port", str(TEST_PORT)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True)
    try:
        ready = wait_port(TEST_PORT)
        record("T10-server-starts", "localhost 服务启动", ready, f"serve_demo.py 在 127.0.0.1:{TEST_PORT} 就绪={ready}")

        status, _headers, _body = http_get(f"http://127.0.0.1:{TEST_PORT}/")
        record("T11-index-200", "首页 HTTP 200", status == 200, f"GET / -> {status}")

        status, _headers, _body = http_get(f"http://127.0.0.1:{TEST_PORT}/data/demo-manifest.json")
        record("T12-manifest-200", "Manifest HTTP 200", status == 200, f"GET /data/demo-manifest.json -> {status}")

        ok_assets = []
        for asset in ("styles.css", "app.js"):
            status, _headers, _body = http_get(f"http://127.0.0.1:{TEST_PORT}/{asset}")
            ok_assets.append((asset, status))
        record("T13-static-assets-200", "静态资源 HTTP 200", all(code == 200 for _n, code in ok_assets),
               f"styles.css/app.js -> {ok_assets}")

        status, _headers, _body = http_get(
            f"http://127.0.0.1:{TEST_PORT}/artifact/../../.dsh/.credentials.yaml")
        traversal_url = f"http://127.0.0.1:{TEST_PORT}/artifact/..%2f..%2f.dsh%2f.credentials.yaml"
        status2, _h, _b = http_get(traversal_url)
        status3, _h, _b = http_get(
            f"http://127.0.0.1:{TEST_PORT}/artifact/.dsh/.credentials.yaml")
        record("T14-traversal-rejected", "路径遍历被拒绝",
               status in (403, 404) and status2 in (403, 404) and status3 in (403, 404),
               f"../穿越={status}；编码穿越={status2}；直接凭据路径={status3}（均期望 403/404）")

        status, _headers, _body = http_get(f"http://127.0.0.1:{TEST_PORT}/media/video-c")
        status_abs, _headers, _body = http_get(
            f"http://127.0.0.1:{TEST_PORT}/media//any/absolute/path.mp4")
        record("T15-media-allowlist-enforced", "非 allowlist 媒体被拒绝",
               status == 403 and status_abs == 403,
               f"未知媒体 id={status}；URL 内绝对路径={status_abs}（均期望 403）")

        # allowlist 媒体可用性（存在则 200/206，不存在则 404 降级）
        status_a, _headers, _body = http_get(
            f"http://127.0.0.1:{TEST_PORT}/media/video-a", method="HEAD")
        record("T15b-allowlist-media-handled", "allowlist 媒体被正确处理", status_a in (200, 206, 404),
               f"/media/video-a HEAD -> {status_a}（200/206=可播放；404=降级关键帧）")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
    # 20) 预览进程正确关闭
    time.sleep(0.5)
    alive = server.poll() is None
    record("T20-preview-process-closes", "临时预览进程正确关闭", not alive,
           f"terminate 后 poll={server.poll()}（None=仍存活）")

    # 16) PARTIAL 历史存在
    history = (manifest or {}).get("benchmark_history") or []
    partial_entries = [h for h in history if h.get("verdict") == "PARTIAL"]
    pass_entries = [h for h in history if h.get("verdict") == "PASS"]
    record("T16-partial-history-present", "PARTIAL 历史存在", bool(partial_entries),
           f"历史条目={len(history)}；PARTIAL 条目={len(partial_entries)}（不得只展示 PASS）")

    # 17) PASS 历史存在
    record("T17-pass-history-present", "PASS 历史存在", bool(pass_entries),
           f"PASS 条目={len(pass_entries)}")

    # 18) E9 缺陷与修复存在
    e9_defect = any("E9" in str(h.get("defect") or "") for h in history)
    e9_fix = any("provenance" in str(h.get("fix") or "") or "missing_source_media" in str(h.get("fix") or "")
                 for h in history)
    record("T18-e9-defect-and-fix", "E9 缺陷与修复存在", e9_defect and e9_fix,
           f"E9 缺陷记录={e9_defect}；修复记录={e9_fix}")

    # 19) 真实性标签与 artifacts 一致
    truth_ok = True
    details = []
    for run in (manifest or {}).get("runs", []):
        if run["id"] == "task-16-single-video":
            ok = (run.get("positive") or {}).get("raw_frames")
            truth_ok = truth_ok and bool(ok)
            details.append(f"task-16 raw_frames={bool(ok)}")
        if run["id"] == "task-18-single-video":
            ok = (run.get("positive") or {}).get("raw_frames")
            truth_ok = truth_ok and bool(ok)
            details.append(f"task-18 raw_frames={bool(ok)}")
        if run["id"] == "tier3-final":
            ok = (run.get("benchmark_entry") or {}).get("verdict") == "PASS"
            truth_ok = truth_ok and ok
            details.append(f"tier3-final verdict=PASS:{ok}")
        if run["id"] == "tier3-initial":
            ok = (run.get("benchmark_entry") or {}).get("verdict") == "PARTIAL"
            truth_ok = truth_ok and ok
            details.append(f"tier3-initial verdict=PARTIAL:{ok}")
    record("T19-truth-labels-consistent", "真实性标签与 artifacts 一致", truth_ok, "；".join(details))

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    print(f"\n小计：{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="视觉证据工作台测试")
    parser.add_argument("--results-json", help="测试结果 JSON 输出路径")
    args = parser.parse_args()
    code = main()
    if args.results_json:
        summary = {
            "suite": "task-10-demo-app",
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "passed": sum(1 for item in RESULTS if item["passed"]),
            "total": len(RESULTS),
            "results": RESULTS,
        }
        with open(args.results_json, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    sys.exit(code)
