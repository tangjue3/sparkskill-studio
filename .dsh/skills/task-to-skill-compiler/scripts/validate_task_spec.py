#!/usr/bin/env python3
"""VisualTaskSpec 校验器（SparkSkill Studio · task-to-skill-compiler）

用纯标准库校验一个 VisualTaskSpec 实例是否符合 schemas/visual-task-spec.schema.json，
并执行安全内容检查（拒绝任意代码、shell 命令、凭据样式内容）。

用法:
    python3 validate_task_spec.py --schema <schema.json> --input <spec.json>
退出码: 0 = 通过; 1 = 校验失败; 2 = 用法/IO 错误
"""
import argparse
import json
import os
import re
import sys

SECURITY_PATTERNS = [
    (re.compile(r"```"), "code fence (```) 不允许出现在任务规格中"),
    (re.compile(r"(?i)\bexec\(|eval\(|subprocess|os\.system|os\.popen"), "疑似代码执行调用"),
    (re.compile(r"(?i)(sudo|rm\s+-rf|curl\s+http|wget\s+http|chmod\s+\+x)\b"), "疑似 shell 命令"),
    (re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd|bearer\s+[A-Za-z0-9._-]{8,})"), "疑似凭据内容"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "疑似私钥"),
]

# 媒体路径安全校验（任务 06 多来源）：未授权路径一律拒绝
SENSITIVE_PATH_PREFIXES = (
    "/etc", "/root", "/proc", "/sys", "/dev", "/boot",
    "/var/log", "/var/run", "/run",
)
SENSITIVE_PATH_MARKERS = (
    ".ssh", "id_rsa", "id_ed", ".credentials", "credentials",
    "secret", ".env", "password", "passwd", "token", "private_key",
    "BEGIN PRIVATE KEY", ".git/config",
)

STRING_FIELDS = ("description", "source_media", "task_id", "skill_name")


def project_root():
    """项目根 = 最近的 .git 祖先目录（与 DSH Skill 发现规则一致）。"""
    current = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def authorized_media_roots():
    """授权的媒体根目录：项目根 + 环境变量受控扩展。

    公开版不再内置任何开发机特定目录（内部留档版曾包含开发机上真实测试
    媒体的目录）。复现者如需分析项目外媒体，用
    SPARKSKILL_AUTHORIZED_MEDIA_ROOTS（os.pathsep 分隔）显式扩展；
    仓库内 artifacts/task-16、artifacts/task-17、artifacts/task-18 下
    fixtures/videos/ 的合成 fixture 位于项目根内，默认即可通过校验。
    """
    roots = []
    root = project_root()
    if root:
        roots.append(root)
    extra = os.environ.get("SPARKSKILL_AUTHORIZED_MEDIA_ROOTS", "")
    roots.extend(part for part in extra.split(os.pathsep) if part.strip())
    return [os.path.abspath(path) for path in roots]


def check_media_path(raw_path, path_label):
    """单条媒体路径安全校验；返回问题列表（空 = 通过）。"""
    problems = []
    if not isinstance(raw_path, str) or not raw_path.strip():
        return [f"{path_label}: 路径必须为非空字符串"]
    text = raw_path.strip()
    if any(char in text for char in ("\n", "\r", "\x00", ";", "|", "&", "$", "`")):
        problems.append(f"{path_label}: 路径包含非法字符（shell 元字符/控制字符），疑似命令注入")
        return problems
    lowered = text.lower()
    for marker in SENSITIVE_PATH_MARKERS:
        if marker in lowered:
            problems.append(f"{path_label}: 路径命中敏感标记 {marker!r}，属未授权路径")
            return problems
    roots = authorized_media_roots()
    if os.path.isabs(text):
        resolved = os.path.abspath(text)
    else:
        base = project_root() or os.getcwd()
        resolved = os.path.abspath(os.path.join(base, text))
        if resolved != base and not resolved.startswith(base + os.sep):
            problems.append(f"{path_label}: 相对路径越出项目根（路径穿越），属未授权路径")
            return problems
    for prefix in SENSITIVE_PATH_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            problems.append(f"{path_label}: 路径位于系统敏感目录 {prefix!r}，属未授权路径")
            return problems
    if not any(resolved == root or resolved.startswith(root + os.sep) for root in roots):
        problems.append(
            f"{path_label}: 路径不在授权媒体根目录内（授权根：{roots}），属未授权路径")
    return problems


def check_source_media(instance):
    """source_media 语义校验：数组时 source_id 唯一、路径安全、time_offset_ms 非负。"""
    problems = []
    source_media = instance.get("source_media")
    if isinstance(source_media, str):
        problems.extend(check_media_path(source_media, "$.source_media"))
        return problems
    if isinstance(source_media, list):
        seen = set()
        for index, source in enumerate(source_media):
            label = f"$.source_media[{index}]"
            if not isinstance(source, dict):
                problems.append(f"{label}: 必须是对象")
                continue
            source_id = source.get("source_id")
            if not isinstance(source_id, str) or not source_id.strip():
                problems.append(f"{label}: source_id 必须为非空字符串")
            elif source_id in seen:
                problems.append(f"{label}: source_id {source_id!r} 在同一任务内重复（必须唯一）")
            else:
                seen.add(source_id)
            problems.extend(check_media_path(source.get("path"), f"{label}.path"))
            offset = source.get("time_offset_ms")
            if offset is not None and (not isinstance(offset, (int, float))
                                       or isinstance(offset, bool) or offset < 0):
                problems.append(f"{label}: time_offset_ms 必须为非负数，得到 {offset!r}")
    return problems


# ---------------------------------------------------------------- 采样策略（任务 16）

ADAPTIVE_REQUIRED_FIELDS = (
    "max_model_calls", "initial_coverage_samples",
    "target_boundary_precision_ms", "max_refinement_rounds",
)
UNIFORM_FORBIDDEN_FIELDS = (
    "initial_coverage_samples", "target_boundary_precision_ms",
    "max_refinement_rounds", "refinement_triggers",
)
# 任务 18：coverage_aware_adaptive 专属字段（覆盖目标 + 覆盖调用储备）。
# 这两个字段对 uniform 与 adaptive_coarse_to_fine 都是“不支持组合”。
COVERAGE_ONLY_FIELDS = ("coverage_gap_target_ms", "coverage_call_reserve")
COVERAGE_REQUIRED_FIELDS = ADAPTIVE_REQUIRED_FIELDS + COVERAGE_ONLY_FIELDS


def check_sampling_strategy(instance):
    """sampling_strategy 语义校验（任务 16 + 任务 18）：未知策略/非法预算/负时间精度由 Schema 拒绝；
    此处拒绝"不支持组合"与必填缺失（这些问题归入 errors，不混淆 media 契约）：

    - strategy=uniform：只允许 max_model_calls；任何细化参数与 coverage 专属字段都是不支持组合；
    - strategy=adaptive_coarse_to_fine：max_model_calls / initial_coverage_samples /
      target_boundary_precision_ms / max_refinement_rounds 必填；
      且 initial_coverage_samples <= max_model_calls（初始覆盖不得超出硬预算）；
      不接受 coverage 专属字段（不支持组合）；
    - strategy=coverage_aware_adaptive（任务 18）：adaptive 四字段 + coverage_gap_target_ms /
      coverage_call_reserve 必填；initial_coverage_samples + coverage_call_reserve <=
      max_model_calls（覆盖配置之和不得超出硬预算，边界细化至少保留 1 次调用空间）。
    """
    problems = []
    block = instance.get("sampling_strategy")
    if not isinstance(block, dict):
        return problems  # 类型问题由 Schema validate() 负责
    strategy = block.get("strategy")
    if strategy == "uniform":
        for field in UNIFORM_FORBIDDEN_FIELDS + COVERAGE_ONLY_FIELDS:
            if field in block:
                problems.append(
                    f"$.sampling_strategy: uniform 策略不接受细化/覆盖参数 '{field}'"
                    "（不支持组合：uniform 是正式 baseline，不做粗到细细化与覆盖探索）")
    elif strategy == "adaptive_coarse_to_fine":
        for field in ADAPTIVE_REQUIRED_FIELDS:
            if field not in block:
                problems.append(
                    f"$.sampling_strategy: adaptive_coarse_to_fine 策略缺少必填字段 "
                    f"'{field}'（硬预算/初始覆盖/边界精度/细化轮数必须显式声明）")
        for field in COVERAGE_ONLY_FIELDS:
            if field in block:
                problems.append(
                    f"$.sampling_strategy: adaptive_coarse_to_fine 策略不接受 coverage "
                    f"专属字段 '{field}'（不支持组合：覆盖探索属于 coverage_aware_adaptive）")
        budget = block.get("max_model_calls")
        initial = block.get("initial_coverage_samples")
        if (isinstance(budget, int) and not isinstance(budget, bool)
                and isinstance(initial, int) and not isinstance(initial, bool)
                and initial > budget):
            problems.append(
                f"$.sampling_strategy: initial_coverage_samples({initial}) 超过 "
                f"max_model_calls({budget})：初始覆盖采样不得超出硬性调用预算")
    elif strategy == "coverage_aware_adaptive":
        for field in COVERAGE_REQUIRED_FIELDS:
            if field not in block:
                problems.append(
                    f"$.sampling_strategy: coverage_aware_adaptive 策略缺少必填字段 "
                    f"'{field}'（硬预算/初始覆盖/覆盖目标/覆盖储备/边界精度/细化轮数必须显式声明）")
        budget = block.get("max_model_calls")
        initial = block.get("initial_coverage_samples")
        reserve = block.get("coverage_call_reserve")
        if (isinstance(budget, int) and not isinstance(budget, bool)
                and isinstance(initial, int) and not isinstance(initial, bool)
                and isinstance(reserve, int) and not isinstance(reserve, bool)
                and initial + reserve > budget):
            problems.append(
                f"$.sampling_strategy: initial_coverage_samples({initial}) + "
                f"coverage_call_reserve({reserve}) 超过 max_model_calls({budget})："
                "覆盖配置之和不得超出硬性调用预算")
    return problems


MISSING_SOURCE_MEDIA_CONTRACT = {
    "accepted": False,
    "status": "needs_input",
    "error_code": "missing_source_media",
    "missing_fields": ["source_media"],
    "message": ("请明确提供要分析的图片或视频路径。媒体来源只能是当前用户请求中显式给出"
                "的本地路径或 Harness 明确传入的附件；禁止从项目文档、历史运行记录、"
                "README 或目录扫描中推断。"),
    "tool_calls_allowed": False,
}


def source_media_contract(instance, problems):
    """缺失与非法必须区分（任务 08）：返回结构化契约或 None。"""
    if "source_media" not in instance:
        return dict(MISSING_SOURCE_MEDIA_CONTRACT)
    if problems:
        return {
            "accepted": False,
            "status": "rejected",
            "error_code": "invalid_source_media",
            "message": "source_media 未通过安全/语义校验（路径未授权、shell 元字符、"
                       "source_id 重复或 time_offset_ms 为负等）",
            "problems": problems,
            "tool_calls_allowed": False,
        }
    return None


def iter_strings(node, path="$"):
    """遍历实例中所有字符串值，用于安全扫描。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from iter_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_strings(value, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def validate(instance, schema, path="$", errors=None):
    """实现 JSON Schema 的一个严格子集：type/required/properties/enum/const/
    pattern/minLength/maxLength/minItems/maxItems/items/minimum/maximum/
    exclusiveMinimum/uniqueItems/additionalProperties/oneOf。"""
    if errors is None:
        errors = []
    expected = schema.get("type")
    type_map = {
        "object": dict, "array": list, "string": str,
        "number": (int, float), "integer": int, "boolean": bool,
    }
    if expected:
        py_type = type_map.get(expected)
        if expected in ("number", "integer") and isinstance(instance, bool):
            errors.append(f"{path}: 期望 {expected}，得到 boolean")
            return errors
        if py_type and not isinstance(instance, py_type):
            errors.append(f"{path}: 期望 {expected}，得到 {type(instance).__name__}")
            return errors
        if expected == "string" and isinstance(instance, str) and not instance.strip():
            errors.append(f"{path}: 不允许空字符串")
            return errors
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: 必须等于常量 {schema['const']!r}，得到 {instance!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: 取值 {instance!r} 不在允许集合 {schema['enum']} 中")
    if "oneOf" in schema:
        candidates = schema["oneOf"]
        sub_results = []
        for index, subschema in enumerate(candidates):
            sub_errors = validate(instance, subschema, f"{path}(候选{index})", [])
            sub_results.append((index, sub_errors))
        matched = [index for index, sub_errors in sub_results if not sub_errors]
        if len(matched) == 0:
            for index, sub_errors in sub_results:
                for line in sub_errors[:2]:
                    errors.append(f"{path}: 不满足 source_media 的任一允许结构（{line}）")
            return errors
        if len(matched) > 1:
            errors.append(f"{path}: 同时满足多个互斥结构 {matched}，规格存在歧义")
            return errors
    if isinstance(instance, str):
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: 不匹配 pattern {schema['pattern']}")
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: 长度 {len(instance)} 小于 minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: 长度 {len(instance)} 超过 maxLength {schema['maxLength']}")
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} 小于 minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} 超过 maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: {instance} 不大于 exclusiveMinimum "
                          f"{schema['exclusiveMinimum']}（必须严格大于）")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: 缺少必填字段 '{key}'")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in instance:
                if key not in properties:
                    errors.append(f"{path}: 不允许的字段 '{key}'")
        for key, subschema in properties.items():
            if key in instance:
                validate(instance[key], subschema, f"{path}.{key}", errors)
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: 元素数 {len(instance)} 少于 minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: 元素数 {len(instance)} 超过 maxItems {schema['maxItems']}")
        if schema.get("uniqueItems") is True:
            seen = []
            for item in instance:
                if item in seen:
                    errors.append(f"{path}: 数组元素 {item!r} 重复（uniqueItems=true）")
                else:
                    seen.append(item)
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(instance):
                validate(item, item_schema, f"{path}[{index}]", errors)
    return errors


def security_scan(instance):
    problems = []
    for path, text in iter_strings(instance):
        for pattern, message in SECURITY_PATTERNS:
            if pattern.search(text):
                problems.append(f"{path}: {message}")
    return problems


def main():
    parser = argparse.ArgumentParser(description="校验 VisualTaskSpec 实例")
    parser.add_argument("--schema", required=True, help="JSON Schema 文件路径")
    parser.add_argument("--input", required=True, help="待校验的 VisualTaskSpec JSON 文件路径")
    args = parser.parse_args()

    try:
        with open(args.schema, encoding="utf-8") as handle:
            schema = json.load(handle)
        with open(args.input, encoding="utf-8") as handle:
            instance = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[IO/JSON 错误] {error}", file=sys.stderr)
        return 2

    errors = validate(instance, schema)
    problems = security_scan(instance)
    problems.extend(check_source_media(instance))
    # 采样策略语义问题（任务 16）归入 errors：它们是规格配置错误，
    # 不得与媒体来源问题混在一起触发 invalid_source_media 契约。
    errors.extend(check_sampling_strategy(instance))
    contract = source_media_contract(instance, problems)
    if errors or problems:
        for line in errors + problems:
            print(f"[校验失败] {line}", file=sys.stderr)
        if contract:
            print(f"[CONTRACT] {json.dumps(contract, ensure_ascii=False)}", file=sys.stderr)
        print(f"RESULT: INVALID ({len(errors) + len(problems)} 个问题)", file=sys.stderr)
        return 1
    print("RESULT: VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
