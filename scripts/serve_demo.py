#!/usr/bin/env python3
"""serve_demo.py — 视觉证据工作台只读本地服务（SparkSkill Studio 任务 10）

安全属性：
  - 只监听 127.0.0.1:8787（不对外）；
  - 只读：仅 GET/HEAD，无任何写 API，不执行 shell，不调用模型；
  - 不允许目录遍历；/media/ 只服务显式 allowlist 内的仓库内合成 fixture 视频；
  - 凭据/敏感文件（.credentials.yaml、settings.yaml、.git/、.env、私钥等）一律 403；
  - 媒体 URL 使用 allowlist id，不暴露绝对路径；
  - 关闭后无残留进程（SIGTERM/SIGINT 即退）。

用法:
    python3 scripts/serve_demo.py [--port 8787]
"""
import argparse
import os
import posixpath
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
APP_DIR = os.path.join(PROJECT_ROOT, "app")

# 媒体 allowlist（公开版：仓库内自产合成技术 fixture 视频；URL 只暴露 id。
# 内部留档版的 allowlist 曾指向开发机 MiniMax-H3 产出目录，公开版改为仓库内
# 可再分发的合成 fixture——详见 docs/PUBLIC-VERSION-NOTES.md）
MEDIA_ALLOWLIST = {
    "video-a": os.path.join(PROJECT_ROOT, "artifacts", "task-16", "fixtures",
                           "videos", "fixture-reappear.mp4"),
    "video-b": os.path.join(PROJECT_ROOT, "artifacts", "task-18", "fixtures",
                           "videos", "fixture-short-event-between-grid.mp4"),
}

# 拒绝服务的路径模式（凭据/配置/版本控制/私钥）
DENIED_PATTERNS = [
    re.compile(r"(^|/)\.git(/|$)"),
    re.compile(r"\.credentials\.ya?ml$", re.IGNORECASE),
    re.compile(r"(^|/)settings\.ya?ml$", re.IGNORECASE),
    re.compile(r"(^|/)\.env$", re.IGNORECASE),
    re.compile(r"\.(pem|key|ppk)$", re.IGNORECASE),
    re.compile(r"(^|/)id_rsa$"),
    re.compile(r"(^|/)\.ssh(/|$)"),
    re.compile(r"\.gguf$", re.IGNORECASE),   # 模型权重不服务
]

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".md": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".mp4": "video/mp4",
}


def denied(rel_path):
    for pattern in DENIED_PATTERNS:
        if pattern.search(rel_path):
            return True
    return False


def safe_join(base, rel_path):
    """把 URL 相对路径解析到 base 内；越界返回 None。"""
    rel_path = posixpath.normpath(urllib.parse.unquote(rel_path)).lstrip("/")
    if rel_path.startswith("..") or "/../" in rel_path:
        return None
    full = os.path.abspath(os.path.join(base, rel_path))
    base_abs = os.path.abspath(base)
    if full != base_abs and not full.startswith(base_abs + os.sep):
        return None
    return full


class DemoHandler(BaseHTTPRequestHandler):
    server_version = "SparkSkillDemo/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静默默认日志（避免控制台噪音）
        sys.stderr.write("[serve_demo] %s\n" % (fmt % args))

    # ---------------------------------------------------------- 基础响应

    def _send(self, status, body=b"", content_type="text/plain; charset=utf-8",
              headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self._send(404, "not found")
            return
        range_header = self.headers.get("Range")
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header.strip())
            if match:
                start = int(match.group(1)) if match.group(1) else 0
                end = int(match.group(2)) if match.group(2) else len(body) - 1
                end = min(end, len(body) - 1)
                if start > end:
                    self._send(416, "range not satisfiable")
                    return
                chunk = body[start:end + 1]
                self.send_response(206)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(chunk)))
                self.send_header("Content-Range",
                                 f"bytes {start}-{end}/{len(body)}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(chunk)
                return
        self._send(200, body, content_type, {"Accept-Ranges": "bytes"})

    # ---------------------------------------------------------- 路由

    def do_GET(self):
        self._route()

    def do_HEAD(self):
        self._route()

    def _route(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_file(os.path.join(APP_DIR, "index.html"), CONTENT_TYPES[".html"])
            return
        if path == "/manifest" or path == "/data/demo-manifest.json":
            manifest = os.path.join(APP_DIR, "data", "demo-manifest.json")
            if not os.path.isfile(manifest):
                self._send(404, "manifest not found; run scripts/build_demo_manifest.py")
                return
            self._send_file(manifest, CONTENT_TYPES[".json"])
            return
        if path.startswith("/artifact/"):
            rel = path[len("/artifact/"):]
            if denied(rel):
                self._send(403, "forbidden")
                return
            full = safe_join(PROJECT_ROOT, rel)
            if full is None or not os.path.isfile(full):
                self._send(404, "not found")
                return
            ext = os.path.splitext(full)[1].lower()
            if ext not in CONTENT_TYPES:
                self._send(403, "unsupported file type")
                return
            self._send_file(full, CONTENT_TYPES[ext])
            return
        if path.startswith("/media/"):
            media_id = urllib.parse.unquote(path[len("/media/"):]).strip("/")
            if media_id not in MEDIA_ALLOWLIST:
                self._send(403, "media not in allowlist")
                return
            full = MEDIA_ALLOWLIST[media_id]
            if not os.path.isfile(full):
                self._send(404, "media unavailable (degrade to keyframes)")
                return
            self._send_file(full, CONTENT_TYPES[".mp4"])
            return
        # 应用静态资源
        rel = path.lstrip("/")
        full = safe_join(APP_DIR, rel)
        if full is None or not os.path.isfile(full):
            self._send(404, "not found")
            return
        ext = os.path.splitext(full)[1].lower()
        if ext not in CONTENT_TYPES:
            self._send(403, "unsupported file type")
            return
        self._send_file(full, CONTENT_TYPES[ext])


def main():
    parser = argparse.ArgumentParser(description="视觉证据工作台只读本地服务")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    print(f"[serve_demo] 只读服务已启动: http://127.0.0.1:{args.port}/ （Ctrl-C 停止）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[serve_demo] 已停止，无残留进程")
    return 0


if __name__ == "__main__":
    sys.exit(main())
