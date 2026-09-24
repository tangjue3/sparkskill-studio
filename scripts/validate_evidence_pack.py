#!/usr/bin/env python3
"""validate_evidence_pack.py — Evidence Pack manifest 与时间 Ground Truth 契约校验器
（SparkSkill Studio 任务 17）

纯标准库、无模型调用、只读输入。校验三层：

  1. Schema 结构：复用 task-to-skill-compiler/scripts/validate_task_spec.py 的
     JSON Schema 严格子集校验器（type/required/properties/enum/const/pattern/
     minLength/maxLength/minimum/exclusiveMinimum/minItems/uniqueItems/
     additionalProperties），不引入 jsonschema 依赖；
  2. 语义规则（本文件）：
     - manifest：sample_id 唯一；媒体路径安全（相对路径、项目根内、禁敏感标记）；
       source_provenance 条件必填字段（generated / licensed_public / technical_fixture）；
       manifest 不得内嵌时间真值；competition profile（可选）编号/split/来源校验；
     - ground truth：时间线合法性（排序/完整覆盖/不重叠/不留隙/正长度/相邻合并）、
       不得包含模型预测字段、annotator_id 非敏感；
  3. 跨文件一致：sample_id 集合、media_sha256、media_duration_ms、target_query。

用法:
    python3 validate_evidence_pack.py --manifest <manifest.json> \
        [--ground-truth <gt.json 或目录>] [--schema-dir schemas]
退出码: 0 = 通过; 1 = 校验失败（结构化问题逐条输出，含无法读取的 ground truth 输入）;
        2 = 用法错误（缺参 / manifest 无法读取 / Schema 加载失败）
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
COMPILER_SCRIPTS = os.path.join(PROJECT_ROOT, ".dsh", "skills", "task-to-skill-compiler", "scripts")
DEFAULT_SCHEMA_DIR = os.path.join(PROJECT_ROOT, "schemas")

MANIFEST_SCHEMA_VERSION = "1.0.0"
GROUND_TRUTH_SCHEMA_VERSION = "1.0.0"
SUPPORTED_MANIFEST_SCHEMA_VERSIONS = ("1.0.0",)
SUPPORTED_GROUND_TRUTH_SCHEMA_VERSIONS = ("1.0.0",)

COMPETITION_PROFILE = "sparkskill-competition-2026"
# 公开版：competition profile 的 12 样本 = 6 dev generated + 2 holdout generated
# + 3 dev licensed_public + 1 holdout licensed_public。公开版不列真实 holdout
# 样本编号（内部留档），以 HOLDOUT-G1/HOLDOUT-G2/HOLDOUT-L1 占位；契约结构
# （12 样本、dev 9 / holdout 3、generated 8 / licensed_public 4）不变。
COMPETITION_SAMPLE_IDS = (
    [f"AI{index:02d}" for index in range(1, 7)]
    + ["HOLDOUT-G1", "HOLDOUT-G2"]
    + [f"WEB{index:02d}" for index in range(1, 4)]
    + ["HOLDOUT-L1"]
)
COMPETITION_EXPECTED = {
    # sample_id: (split, source_type)
    "AI01": ("dev", "generated"), "AI02": ("dev", "generated"),
    "AI03": ("dev", "generated"), "AI04": ("dev", "generated"),
    "AI05": ("dev", "generated"), "AI06": ("dev", "generated"),
    "HOLDOUT-G1": ("holdout", "generated"), "HOLDOUT-G2": ("holdout", "generated"),
    "WEB01": ("dev", "licensed_public"), "WEB02": ("dev", "licensed_public"),
    "WEB03": ("dev", "licensed_public"), "HOLDOUT-L1": ("holdout", "licensed_public"),
}

# source_type -> source_provenance 条件必填字段（任务 17 契约；Schema 声明结构，
# 条件组合规则在此确定性执行——与任务 16 sampling_strategy 同一模式）
PROVENANCE_REQUIRED_FIELDS = {
    "generated": ("model_name", "service_or_model_version", "prompt_version_ref",
                  "attempt_id", "generation_record_ref"),
    "licensed_public": ("original_page_url", "author_or_uploader", "license_name",
                        "official_license_url", "license_evidence_ref",
                        "attribution_requirement"),
    "technical_fixture": ("fixture_generator_ref", "generation_params_ref",
                          "freeze_record_ref"),
}

# manifest 不得内嵌时间真值（Ground Truth 是显式独立输入）
MANIFEST_FORBIDDEN_KEYS = (
    "segments", "ground_truth", "ground_truths", "labels", "annotation",
    "annotations", "states", "timeline",
)

# Ground Truth 不得包含模型预测字段/置信度/模型输出反推标签
GT_FORBIDDEN_KEYS = (
    "prediction", "predictions", "predicted", "predicted_class", "confidence",
    "model", "model_output", "model_outputs", "bbox", "bounding_box",
    "object_found", "evidence", "timeline",
)

GT_STATES = ("confirmed", "not_found", "uncertain")
SENSITIVE_ANNOTATOR_MARKERS = (
    "api_key", "api-key", "secret", "token", "password", "passwd", "bearer ",
    "private_key", "-----begin", "@", ".ssh", "id_rsa",
)


class ValidationProblem:
    """结构化校验问题（可定位：code + location + message）。"""

    def __init__(self, code, location, message):
        self.code = code
        self.location = location
        self.message = message

    def as_dict(self):
        return {"code": self.code, "location": self.location, "message": self.message}

    def __str__(self):
        return f"[{self.code}] {self.location}: {self.message}"


def problem(code, location, message):
    return ValidationProblem(code, location, message)


# ---------------------------------------------------------------- 模块加载

_VALIDATOR_CACHE = {}


def load_schema_validator():
    """加载 validate_task_spec.py 的 Schema 子集校验器（仓库既有能力）。"""
    if "validator" in _VALIDATOR_CACHE:
        return _VALIDATOR_CACHE["validator"]
    path = os.path.join(COMPILER_SCRIPTS, "validate_task_spec.py")
    if not os.path.isfile(path):
        raise RuntimeError(f"找不到 Schema 子集校验器: {path}")
    spec = importlib.util.spec_from_file_location("validate_task_spec", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _VALIDATOR_CACHE["validator"] = module
    return module


def load_schema(schema_name, schema_dir=None):
    key = f"schema:{schema_name}"
    if key in _VALIDATOR_CACHE:
        return _VALIDATOR_CACHE[key]
    base = schema_dir or DEFAULT_SCHEMA_DIR
    path = os.path.join(base, schema_name)
    with open(path, encoding="utf-8") as handle:
        schema = json.load(handle)
    _VALIDATOR_CACHE[key] = schema
    return schema


def schema_errors(instance, schema_name, schema_dir=None):
    """Schema 子集校验；返回 problem 列表（错误信息转成结构化 code=schema_error）。"""
    validator = load_schema_validator()
    schema = load_schema(schema_name, schema_dir)
    raw = validator.validate(instance, schema)
    return [problem("schema_error", line.split(":", 1)[0] if ":" in line else "$",
                    line.split(":", 1)[1].strip() if ":" in line else line)
            for line in raw]


# ---------------------------------------------------------------- 通用工具

def iter_keys(node, path="$"):
    """递归遍历所有键（用于禁用键扫描）。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, f"{path}.{key}"
            yield from iter_keys(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from iter_keys(item, f"{path}[{index}]")


def round3(value):
    return round(float(value), 3)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repo_relative(path):
    try:
        return os.path.relpath(os.path.abspath(path), PROJECT_ROOT)
    except ValueError:
        return "<unrelatable-path>"


# ---------------------------------------------------------------- manifest 校验

def check_media_path_safety(sample_id, media_path, manifest_path):
    """manifest 媒体路径安全：必须为相对路径；解析后位于项目根内；
    禁 shell 元字符/敏感标记/系统敏感目录（复用 validate_task_spec 的标记表）。"""
    problems = []
    location = f"samples[{sample_id}].media_path"
    if not isinstance(media_path, str) or not media_path.strip():
        return [problem("invalid_media_path", location, "媒体路径必须为非空字符串")]
    text = media_path.strip()
    if os.path.isabs(text):
        problems.append(problem("invalid_media_path", location,
                                "媒体路径必须是相对路径（相对 manifest 所在目录）"))
        return problems
    if any(char in text for char in ("\n", "\r", "\x00", ";", "|", "&", "$", "`")):
        problems.append(problem("invalid_media_path", location,
                                "媒体路径包含非法字符（shell 元字符/控制字符）"))
        return problems
    validator = load_schema_validator()
    lowered = text.lower()
    for marker in validator.SENSITIVE_PATH_MARKERS:
        if marker in lowered:
            problems.append(problem("invalid_media_path", location,
                                    f"媒体路径命中敏感标记 {marker!r}"))
            return problems
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path)) if manifest_path else PROJECT_ROOT
    resolved = os.path.abspath(os.path.join(manifest_dir, text))
    for prefix in validator.SENSITIVE_PATH_PREFIXES:
        if resolved == prefix or resolved.startswith(prefix + os.sep):
            problems.append(problem("invalid_media_path", location,
                                    f"媒体路径位于系统敏感目录 {prefix!r}"))
            return problems
    if not (resolved == PROJECT_ROOT or resolved.startswith(PROJECT_ROOT + os.sep)):
        problems.append(problem("invalid_media_path", location,
                                "媒体路径解析后越出项目根（路径穿越）"))
    return problems


def check_source_provenance(sample):
    """source_provenance 条件必填字段（按 source_type）；source_type 必须一致。"""
    problems = []
    sample_id = sample.get("sample_id", "<unknown>")
    location = f"samples[{sample_id}].source_provenance"
    provenance = sample.get("source_provenance")
    if not isinstance(provenance, dict):
        return [problem("invalid_provenance", location, "source_provenance 必须是对象")]
    source_type = sample.get("source_type")
    if provenance.get("source_type") != source_type:
        problems.append(problem(
            "provenance_source_type_mismatch", f"{location}.source_type",
            f"source_provenance.source_type({provenance.get('source_type')!r}) "
            f"必须与 sample.source_type({source_type!r}) 一致"))
        return problems
    if source_type not in PROVENANCE_REQUIRED_FIELDS:
        return problems  # 非法 source_type 由 Schema enum 拒绝
    for field in PROVENANCE_REQUIRED_FIELDS[source_type]:
        value = provenance.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(problem(
                "missing_provenance_field", f"{location}.{field}",
                f"source_type={source_type} 必须提供 {field}"))
    return problems


def check_competition_profile(manifest):
    """profile=sparkskill-competition-2026 时的编号/split/来源校验（8 AI + 4 真实，9/3）。"""
    problems = []
    samples = manifest.get("samples") or []
    ids = [sample.get("sample_id") for sample in samples]
    location = "samples"
    if len(samples) != len(COMPETITION_SAMPLE_IDS):
        problems.append(problem(
            "competition_profile_sample_count", location,
            f"competition profile 要求恰好 {len(COMPETITION_SAMPLE_IDS)} 个样本，"
            f"得到 {len(samples)}"))
    id_set = set(ids)
    for sample_id in COMPETITION_SAMPLE_IDS:
        if sample_id not in id_set:
            problems.append(problem(
                "competition_profile_missing_sample", location,
                f"competition profile 缺少样本 {sample_id}"))
    for sample_id in id_set:
        if sample_id not in COMPETITION_EXPECTED:
            problems.append(problem(
                "competition_profile_unknown_sample", location,
                f"competition profile 不允许的样本 {sample_id!r}"
                f"（仅允许 {sorted(COMPETITION_EXPECTED)}）"))
    by_id = {sample.get("sample_id"): sample for sample in samples}
    for sample_id, (expected_split, expected_source) in COMPETITION_EXPECTED.items():
        sample = by_id.get(sample_id)
        if not sample:
            continue
        if sample.get("split") != expected_split:
            problems.append(problem(
                "competition_profile_split", f"samples[{sample_id}].split",
                f"{sample_id} 的 split 必须为 {expected_split!r}，"
                f"得到 {sample.get('split')!r}"))
        if sample.get("source_type") != expected_source:
            problems.append(problem(
                "competition_profile_source_type", f"samples[{sample_id}].source_type",
                f"{sample_id} 的 source_type 必须为 {expected_source!r}，"
                f"得到 {sample.get('source_type')!r}"))
    dev_count = sum(1 for sample in samples if sample.get("split") == "dev")
    holdout_count = sum(1 for sample in samples if sample.get("split") == "holdout")
    if dev_count != 9 or holdout_count != 3:
        problems.append(problem(
            "competition_profile_split_counts", "samples",
            f"competition profile 要求 dev 9 / holdout 3，得到 dev {dev_count} / "
            f"holdout {holdout_count}"))
    return problems


def validate_manifest(manifest, manifest_path=None, schema_dir=None):
    """校验单个 manifest；返回 problem 列表（空 = 通过）。"""
    problems = list(schema_errors(manifest, "evidence-pack-manifest.schema.json", schema_dir))
    if manifest.get("schema_version") not in SUPPORTED_MANIFEST_SCHEMA_VERSIONS:
        problems.append(problem(
            "unsupported_schema_version", "$.schema_version",
            f"不支持的 manifest schema_version {manifest.get('schema_version')!r}"
            f"（支持 {list(SUPPORTED_MANIFEST_SCHEMA_VERSIONS)}）"))
    # manifest 不得内嵌时间真值
    for key, location in iter_keys(manifest):
        if key in MANIFEST_FORBIDDEN_KEYS:
            problems.append(problem(
                "manifest_contains_ground_truth", location,
                f"manifest 不得内嵌时间真值字段 {key!r}"
                "（Ground Truth 必须作为显式独立输入）"))
    samples = manifest.get("samples")
    if isinstance(samples, list):
        seen = set()
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            sample_id = sample.get("sample_id")
            if not isinstance(sample_id, str):
                continue
            if sample_id in seen:
                problems.append(problem(
                    "duplicate_sample_id", f"samples[{sample_id}]",
                    f"sample_id {sample_id!r} 在 pack 内重复（必须唯一）"))
            seen.add(sample_id)
            problems.extend(check_media_path_safety(sample_id, sample.get("media_path"),
                                                    manifest_path))
            problems.extend(check_source_provenance(sample))
    if manifest.get("profile") == COMPETITION_PROFILE:
        problems.extend(check_competition_profile(manifest))
    return problems


# ---------------------------------------------------------------- ground truth 校验

def check_ground_truth_timeline(gt):
    """时间线合法性（确定性规则）；返回 problem 列表。"""
    problems = []
    sample_id = gt.get("sample_id", "<unknown>")
    location = f"{sample_id}.segments"
    segments = gt.get("segments")
    if not isinstance(segments, list) or not segments:
        return [problem("gt_timeline_empty", location, "segments 必须是非空数组")]
    duration = gt.get("media_duration_ms")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        return [problem("gt_invalid_duration", f"{sample_id}.media_duration_ms",
                        "media_duration_ms 必须为正数")]
    previous = None
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            problems.append(problem("gt_invalid_segment", f"{location}[{index}]",
                                    "segment 必须是对象"))
            continue
        start, end, state = (segment.get("start_ms"), segment.get("end_ms"),
                             segment.get("state"))
        if not isinstance(start, (int, float)) or isinstance(start, bool) \
                or not isinstance(end, (int, float)) or isinstance(end, bool):
            problems.append(problem("gt_invalid_segment", f"{location}[{index}]",
                                    "start_ms/end_ms 必须为数值"))
            continue
        if state not in GT_STATES:
            problems.append(problem("gt_invalid_state", f"{location}[{index}].state",
                                    f"state 必须属于 {list(GT_STATES)}，得到 {state!r}"))
            continue
        if end <= start:
            problems.append(problem(
                "gt_timeline_non_positive_length", f"{location}[{index}]",
                f"segment 长度必须为正（start_ms={start}, end_ms={end}）"))
            continue
        if previous is not None:
            prev_start, prev_end, prev_state = previous
            if start < prev_end:
                problems.append(problem(
                    "gt_timeline_overlap", f"{location}[{index}]",
                    f"时间线重叠：上一段 end_ms={prev_end}，本段 start_ms={start}"))
            elif start > prev_end:
                problems.append(problem(
                    "gt_timeline_gap", f"{location}[{index}]",
                    f"时间线有空隙：上一段 end_ms={prev_end}，本段 start_ms={start}"))
            elif state == prev_state:
                problems.append(problem(
                    "gt_timeline_unmerged", f"{location}[{index}]",
                    f"相邻相同状态 {state!r} 未合并（必须合并相邻同状态段）"))
        previous = (start, end, state)
    if isinstance(segments[0], dict):
        first_start = segments[0].get("start_ms")
        if first_start != 0:
            problems.append(problem(
                "gt_timeline_incomplete_coverage", f"{location}[0]",
                f"时间线必须从 0 开始，得到 start_ms={first_start}"))
    if isinstance(segments[-1], dict):
        last_end = segments[-1].get("end_ms")
        if round3(last_end) != round3(duration):
            problems.append(problem(
                "gt_timeline_incomplete_coverage", f"{location}[{len(segments) - 1}]",
                f"时间线必须覆盖到媒体终点 media_duration_ms={duration}，"
                f"得到 end_ms={last_end}"))
    return problems


def check_ground_truth_semantics(gt):
    """GT 语义：不得包含模型字段；annotator_id 非敏感；修订历史结构由 Schema 管。"""
    problems = []
    sample_id = gt.get("sample_id", "<unknown>")
    for key, location in iter_keys(gt):
        if key in GT_FORBIDDEN_KEYS:
            problems.append(problem(
                "gt_contains_model_fields", location,
                f"Ground Truth 不得包含模型预测/置信度字段 {key!r}"
                "（真值必须独立于模型输出）"))
    annotator = gt.get("annotator_id")
    if isinstance(annotator, str):
        lowered = annotator.lower()
        for marker in SENSITIVE_ANNOTATOR_MARKERS:
            if marker in lowered:
                problems.append(problem(
                    "gt_sensitive_annotator", f"{sample_id}.annotator_id",
                    f"annotator_id 命中敏感标记 {marker!r}（必须非敏感）"))
                break
    return problems


def validate_ground_truth(gt, schema_dir=None):
    """校验单份 Ground Truth（Schema + 时间线 + 语义）。"""
    problems = list(schema_errors(gt, "temporal-ground-truth.schema.json", schema_dir))
    if gt.get("schema_version") not in SUPPORTED_GROUND_TRUTH_SCHEMA_VERSIONS:
        problems.append(problem(
            "unsupported_schema_version", "$.schema_version",
            f"不支持的 ground truth schema_version {gt.get('schema_version')!r}"
            f"（支持 {list(SUPPORTED_GROUND_TRUTH_SCHEMA_VERSIONS)}）"))
    problems.extend(check_ground_truth_timeline(gt))
    problems.extend(check_ground_truth_semantics(gt))
    return problems


def cross_check(manifest, ground_truths):
    """manifest 与 GT 集合的跨文件一致：sample_id、media_sha256、时长、target_query。"""
    problems = []
    samples = {sample.get("sample_id"): sample
               for sample in manifest.get("samples", [])
               if isinstance(sample, dict)}
    for sample_id, gt in sorted(ground_truths.items()):
        sample = samples.get(sample_id)
        if sample is None:
            problems.append(problem(
                "sample_id_mismatch", f"ground_truth[{sample_id}]",
                f"Ground Truth 的 sample_id {sample_id!r} 不在 manifest 中"))
            continue
        if sample.get("media_sha256") != gt.get("media_sha256"):
            problems.append(problem(
                "media_hash_mismatch", f"ground_truth[{sample_id}].media_sha256",
                "Ground Truth 与 manifest 的 media_sha256 不一致"))
        if round3(sample.get("media_duration_ms")) != round3(gt.get("media_duration_ms")):
            problems.append(problem(
                "duration_mismatch", f"ground_truth[{sample_id}].media_duration_ms",
                f"Ground Truth({gt.get('media_duration_ms')!r}) 与 manifest"
                f"({sample.get('media_duration_ms')!r}) 的媒体时长不一致"))
        if sample.get("target_query") != gt.get("target_query"):
            problems.append(problem(
                "target_query_mismatch", f"ground_truth[{sample_id}].target_query",
                "Ground Truth 与 manifest 的 target_query 不一致"))
    return problems


def load_ground_truths(gt_arg):
    """从文件或目录加载 Ground Truth 集合；返回 (gts_by_id, problems)。"""
    problems = []
    gts = {}
    paths = []
    if os.path.isdir(gt_arg):
        for name in sorted(os.listdir(gt_arg)):
            if name.endswith(".json"):
                paths.append(os.path.join(gt_arg, name))
    else:
        paths.append(gt_arg)
    for path in paths:
        try:
            with open(path, encoding="utf-8") as handle:
                gt = json.load(handle)
        except (OSError, json.JSONDecodeError) as error:
            problems.append(problem("unreadable_input", repo_relative(path),
                                    f"无法读取 Ground Truth: {error}"))
            continue
        gt_problems = validate_ground_truth(gt)
        problems.extend(gt_problems)
        sample_id = gt.get("sample_id")
        if isinstance(sample_id, str):
            if sample_id in gts:
                problems.append(problem(
                    "duplicate_ground_truth", f"ground_truth[{sample_id}]",
                    f"sample_id {sample_id!r} 的 Ground Truth 重复提供"))
            gts[sample_id] = gt
    return gts, problems


def load_manifest(manifest_arg):
    """加载并校验 manifest；返回 (manifest, problems)。

    manifest 不可读/不可解析时返回 (None, None)（调用方按用法/IO 错误处理，退出码 2）。
    """
    try:
        with open(manifest_arg, encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[用法/IO 错误] 无法读取 manifest: {error}", file=sys.stderr)
        return None, None
    problems = validate_manifest(manifest, manifest_path=manifest_arg)
    return manifest, problems


# ---------------------------------------------------------------- CLI

def main():
    parser = argparse.ArgumentParser(
        description="校验 Evidence Pack manifest 与时间 Ground Truth 契约")
    parser.add_argument("--manifest", required=True, help="Evidence Pack manifest JSON 路径")
    parser.add_argument("--ground-truth", default=None,
                        help="Ground Truth JSON 文件或目录（可选；提供时执行跨文件一致性校验）")
    parser.add_argument("--schema-dir", default=None,
                        help="Schema 目录（默认项目 schemas/）")
    args = parser.parse_args()

    try:
        manifest, problems = load_manifest(args.manifest)
    except Exception as error:  # Schema 加载失败等
        print(f"[用法/IO 错误] {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    if manifest is None:
        return 2

    if manifest is not None and args.ground_truth:
        try:
            gts, gt_problems = load_ground_truths(args.ground_truth)
        except Exception as error:
            print(f"[用法/IO 错误] {type(error).__name__}: {error}", file=sys.stderr)
            return 2
        problems.extend(gt_problems)
        problems.extend(cross_check(manifest, gts))
        for sample_id, sample in sorted(
                {s.get("sample_id"): s for s in manifest.get("samples", [])
                 if isinstance(s, dict)}.items()):
            if sample_id not in gts:
                problems.append(problem(
                    "missing_ground_truth_for_sample", f"samples[{sample_id}]",
                    f"manifest 样本 {sample_id!r} 缺少对应的 Ground Truth 输入"))

    if problems:
        for item in problems:
            print(f"[校验失败] {item}", file=sys.stderr)
        print(f"RESULT: INVALID ({len(problems)} 个问题)", file=sys.stderr)
        return 1
    print("RESULT: VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
