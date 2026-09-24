#!/usr/bin/env python3
"""skill_env.py — SparkSkill Studio Skill 脚本的本地运行环境助手（纯标准库）。

背景：抽帧需要 OpenCV（cv2）。本项目红线是不安装依赖、不下载模型。
因此本模块在当前解释器缺少 cv2 时，自动改用**本机已有**含 cv2 的解释器
重新执行当前脚本：不安装、不下载任何东西，只是复用机器上已存在的工具。

切换顺序（可通过环境变量覆盖）:
   1. $SPARKSKILL_CV2_PYTHON（复现者显式指定，推荐）
   2. 常见既有环境的探测模式（conda/venv，见 CANDIDATE_GLOBS）

内部留档版曾写死开发机上的解释器路径；公开版不假设任何机器特定路径，
复现者按 docs/REPRODUCTION.md §2.2 自行准备含 OpenCV 的解释器。
"""
import glob
import os
import subprocess
import sys

BOOTSTRAP_FLAG = "SPARKSKILL_CV2_BOOTSTRAPPED"

# 常见既有 Python 环境的探测模式（仅探测，不安装、不下载）
CANDIDATE_GLOBS = (
    os.path.expanduser("~/miniconda*/envs/*/bin/python"),
    os.path.expanduser("~/anaconda*/envs/*/bin/python"),
    os.path.expanduser("~/miniforge*/envs/*/bin/python"),
    "/opt/conda/envs/*/bin/python",
    "/usr/local/envs/*/bin/python",
    os.path.expanduser("~/.virtualenvs/*/bin/python"),
    os.path.expanduser("~/venvs/*/bin/python"),
)


def _probe(interpreter):
    """探测解释器是否能 import cv2（不加载模型、不写文件）。"""
    try:
        result = subprocess.run(
            [interpreter, "-c", "import cv2"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def candidate_interpreters():
    candidates = []
    env_python = os.environ.get("SPARKSKILL_CV2_PYTHON")
    if env_python:
        candidates.append(env_python)
    for pattern in CANDIDATE_GLOBS:
        candidates.extend(sorted(glob.glob(pattern)))
    seen = set()
    unique = []
    for item in candidates:
        if item and item not in seen and os.path.isfile(item) and os.access(item, os.X_OK):
            seen.add(item)
            unique.append(item)
    return unique


def find_cv2_python():
    for interpreter in candidate_interpreters():
        if _probe(interpreter):
            return interpreter
    return None


def ensure_cv2_interpreter():
    """当前解释器无 cv2 时，用本机已有 cv2 的解释器重新执行当前脚本（execv 替换进程）。"""
    try:
        import cv2  # noqa: F401
        return None
    except ImportError:
        pass
    if os.environ.get(BOOTSTRAP_FLAG) == "1":
        raise RuntimeError(
            "当前解释器缺少 cv2，且已尝试过切换解释器；本项目不安装依赖，"
            "请设置 SPARKSKILL_CV2_PYTHON 指向本机已有 OpenCV 的解释器"
        )
    interpreter = find_cv2_python()
    if interpreter is None:
        raise RuntimeError("未在本机找到任何已安装 OpenCV 的 Python 解释器（本项目不安装依赖）")
    env = dict(os.environ)
    env[BOOTSTRAP_FLAG] = "1"
    script = os.path.abspath(sys.argv[0])
    os.execve(interpreter, [interpreter, script] + sys.argv[1:], env)
