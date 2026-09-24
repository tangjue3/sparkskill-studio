#!/usr/bin/env python3
"""check_source_media.py — 视觉任务媒体来源前置校验（SparkSkill Studio 任务 08）

根因背景（任务 07 Tier-3 E9 失败）：Agent 在用户未提供媒体路径时，从项目文档、
历史 run-summary 与目录扫描中推断出视频路径并完成分析。规格本身"合法"，
唯一能拦住它的是**来源 provenance 规则**：视觉任务的媒体只能来自当前用户请求。

本脚本是该规则的确定性执行器：只读取"当前用户请求文本"（与可选的候选规格），
**不访问项目文件系统、不读取 README/历史产物、不做目录扫描**——它是请求文本的纯函数。

契约输出（stdout，JSON）:
  accepted    status=accepted,  source_media_provenance=user_provided,
              source_media_candidates=[...]                       （可继续编译规格）
  needs_input status=needs_input, error_code=missing_source_media,
              tool_calls_allowed=false                            （缺参：必须问用户）
  rejected    status=rejected,   error_code=invalid_source_media 或
              inferred_source_media, tool_calls_allowed=false      （非法/推断来源）
  not_applicable                                                    （非视觉任务）

用法:
    python3 check_source_media.py --request <user-request.txt> [--spec <spec.json>]
退出码: 0 = accepted/not_applicable; 2 = 用法/IO 错误; 3 = needs_input; 4 = rejected
"""
import argparse
import importlib.util
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

MEDIA_EXTENSIONS = ("mp4", "mov", "avi", "mkv", "webm", "flv", "ts",
                    "png", "jpg", "jpeg", "gif", "bmp", "webp")

# 视觉任务判定（用于决定本前置校验是否适用）
VISUAL_TASK_PATTERN = re.compile(
    r"视频|影片|录像|片段|图片|图像|照片|画面|关键帧|这一帧|这帧|媒体|"
    r"\b(video|image|frame|media)\b", re.IGNORECASE)

# 显式媒体路径提取（含媒体扩展名；允许绝对/相对/./.. 前缀；
# 前后边界排除词内连字符/句点/斜杠造成的截断匹配）
PATH_PATTERN = re.compile(
    r"(?<![\w./-])((?:/|\.{1,2}/)?(?:[\w.\-]+/)*[\w.\-]+\.(?:"
    + "|".join(MEDIA_EXTENSIONS) + r"))(?![\w./-])", re.IGNORECASE)
# 显式非媒体路径引用（绝对或 ./ ../ 前缀；任意扩展名或绝对无扩展名文件）：
# 用户给了路径但不可用作媒体来源时，必须判 invalid 而非 missing
ANY_PATH_PATTERN = re.compile(
    r"(?<![\w./-])((?:/|\.{1,2}/)(?:[\w.\-]+/)*[\w.\-]+(?:\.[A-Za-z0-9]{1,6})?)(?![\w./-])",
    re.IGNORECASE)
QUOTED_PATTERN = re.compile(r"[\"']([^\"'\n]{1,300}?\.[a-z0-9]{2,5})[\"']", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)

NEEDS_INPUT_CONTRACT = {
    "accepted": False,
    "status": "needs_input",
    "error_code": "missing_source_media",
    "missing_fields": ["source_media"],
    "message": ("请明确提供要分析的图片或视频路径。媒体来源只能是当前请求中显式给出的"
                "本地路径，或由 Harness 明确传入的附件；我不会从项目文档、历史运行记录"
                "或目录扫描中推断媒体。"),
    "tool_calls_allowed": False,
}


def load_validator_module():
    """复用 task-to-skill-compiler 校验器的路径安全规则（不重复实现）。"""
    path = os.path.join(SCRIPT_DIR, "validate_task_spec.py")
    spec = importlib.util.spec_from_file_location("validate_task_spec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_visual_task(request_text):
    return bool(VISUAL_TASK_PATTERN.search(request_text or ""))


def extract_media_candidates(request_text):
    """从请求文本提取显式本地媒体路径候选（保持出现顺序，去重）。

    第一优先：含媒体扩展名的路径（可继续编译的候选来源）。
    另记录显式非媒体路径引用（绝对或 ./ ../ 前缀）——用户给了路径但不可用作
    媒体来源时，调用方据此判 invalid 而非 missing。
    """
    candidates = []
    other_paths = []
    seen = set()
    seen_other = set()

    def add(collection, keyset, path):
        cleaned = path.strip().strip("\"'").rstrip(".,;:)]")
        key = cleaned.lower()
        if key and key not in keyset:
            keyset.add(key)
            collection.append(cleaned)

    for match in QUOTED_PATTERN.finditer(request_text):
        value = match.group(1)
        if value.lower().endswith(tuple(f".{ext}" for ext in MEDIA_EXTENSIONS)):
            add(candidates, seen, value)
    for match in PATH_PATTERN.finditer(request_text):
        add(candidates, seen, match.group(1))
    for match in ANY_PATH_PATTERN.finditer(request_text):
        value = match.group(1)
        if value.lower() not in seen:
            add(other_paths, seen_other, value)
    extract_media_candidates.last_other_paths = other_paths
    return candidates


def check(request_text, spec=None):
    """核心判定：只依赖请求文本（与可选规格），不访问项目文件系统。"""
    if not is_visual_task(request_text):
        return {
            "status": "not_applicable",
            "tool_calls_allowed": None,
            "note": "非视觉任务，媒体来源前置校验不适用",
        }, 0

    candidates = extract_media_candidates(request_text)
    other_paths = getattr(extract_media_candidates, "last_other_paths", [])
    if not candidates and other_paths:
        # 用户显式提供了路径，但不可用作媒体来源：判 invalid 而非 missing
        return {
            "accepted": False,
            "status": "rejected",
            "error_code": "invalid_source_media",
            "message": ("请求中显式提供的路径不是可用的媒体文件（扩展名不受支持或非媒体）；"
                        "请提供受支持的图片/视频路径"),
            "explicit_paths": other_paths,
            "tool_calls_allowed": False,
        }, 4
    if not candidates:
        contract = dict(NEEDS_INPUT_CONTRACT)
        contract["detail"] = ("当前请求中未找到显式提供的本地媒体路径；"
                              "不得搜索项目文件、README、历史 artifacts 或目录来推断")
        return contract, 3

    validator = load_validator_module()
    problems = []
    for candidate in candidates:
        problems.extend(validator.check_media_path(candidate, "source_media"))
    if problems:
        return {
            "accepted": False,
            "status": "rejected",
            "error_code": "invalid_source_media",
            "message": "请求中显式提供的媒体路径未通过安全校验",
            "problems": problems,
            "tool_calls_allowed": False,
        }, 4

    result = {
        "accepted": True,
        "status": "accepted",
        "source_media_provenance": "user_provided",
        "source_media_candidates": candidates,
        "tool_calls_allowed": True,
    }

    # 若提供了候选规格：规格中的来源必须全部来自当前请求（反推断核心）
    if isinstance(spec, dict):
        spec_paths = []
        source_media = spec.get("source_media")
        if isinstance(source_media, str):
            spec_paths = [source_media]
        elif isinstance(source_media, list):
            spec_paths = [item.get("path") for item in source_media
                          if isinstance(item, dict) and item.get("path")]
        request_lower = request_text.lower()
        inferred = [path for path in spec_paths
                    if path and path.strip().lower() not in request_lower
                    and os.path.basename(path).lower() not in request_lower]
        if inferred:
            return {
                "accepted": False,
                "status": "rejected",
                "error_code": "inferred_source_media",
                "message": ("规格中的媒体来源未出现在当前用户请求中（推断来源，违反媒体"
                            "来源可信契约）；必须回到用户请求获取显式路径或返回 "
                            "needs_input/missing_source_media"),
                "inferred_paths": inferred,
                "tool_calls_allowed": False,
            }, 4
        result["spec_source_media_check"] = "user_provided"
    return result, 0


def main():
    parser = argparse.ArgumentParser(
        description="视觉任务媒体来源前置校验（请求文本纯函数，不访问项目文件）")
    parser.add_argument("--request", required=True, help="当前用户请求文本文件路径")
    parser.add_argument("--spec", default=None, help="可选：待校验的 VisualTaskSpec JSON")
    args = parser.parse_args()

    try:
        with open(args.request, encoding="utf-8") as handle:
            request_text = handle.read()
    except OSError as error:
        print(f"[错误] 无法读取请求文本: {error}", file=sys.stderr)
        return 2

    spec = None
    if args.spec:
        try:
            with open(args.spec, encoding="utf-8") as handle:
                spec = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            print(f"[错误] 无法读取规格: {error}", file=sys.stderr)
            return 2

    contract, exit_code = check(request_text, spec)
    print(json.dumps(contract, ensure_ascii=False, indent=2))
    if contract.get("status") == "needs_input":
        print("[CONTRACT] needs_input / missing_source_media："
              "关键参数不全，必须先问用户；禁止调用视觉模型、抽帧或搜索媒体",
              file=sys.stderr)
    elif contract.get("status") == "rejected":
        print(f"[CONTRACT] rejected / {contract.get('error_code')}："
              "媒体来源不满足可信条件，禁止继续", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
