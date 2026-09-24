#!/usr/bin/env python3
"""build_demo_manifest.py — 生成视觉证据工作台数据 Manifest（SparkSkill Studio 公开版）

从项目真实 artifacts 读取数据，生成 app/data/demo-manifest.json。CPU-only：
不调用任何模型、不访问网络、不修改 artifacts。

公开版与内部留档版的差异（详见 docs/PUBLIC-VERSION-NOTES.md）：
  - 演示运行记录取自任务 16 / 任务 18 的 DSH headless 自主会话：真实 Qwen 调用，
    输入为**项目自产合成技术 fixture 视频**（Apache-2.0 覆盖，可再分发），
    不涉及任何受限媒体；
  - 不读取任务 05/06 的会话产物（其媒体为内部测试视频，不随公开仓库分发）；
  - Tier-3 benchmark 历史链仍来自任务 07/08/09 的冻结对比 JSON（衍生摘要）；
    原始会话产物为内部留档，不在公开仓库；
  - 构建期自检：凭据样式 + 私有路径/主机名/holdout 编号扫描，命中即中止。

设计原则：
  - 不编造字段：所有数值来自真实文件；缺失即安全降级（null + 说明）；
  - 每条数据标注真实性等级（verified/recorded/structural/blocked/synthetic_fixture）；
  - 使用相对 artifact 路径；
  - 不含凭据、不含绝对敏感路径、不含完整服务日志/推理日志；
  - 保留 PARTIAL 历史，不用 PASS 覆盖。

用法:
    python3 scripts/build_demo_manifest.py [--out app/data/demo-manifest.json]
"""
import argparse
import datetime
import json
import os
import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# 媒体 allowlist（公开版：仓库内自产合成技术 fixture 视频；URL 中不暴露绝对路径）
MEDIA_ALLOWLIST = [
    {"id": "video-a", "title": "fixture-reappear.mp4（任务 16 合成 fixture）",
     "source": "project-synthetic-fixture",
     "note": "项目脚本确定性渲染的合成测试视频（640×360@24fps，8s），Apache-2.0 覆盖；不是真实行业素材"},
    {"id": "video-b", "title": "fixture-short-event-between-grid.mp4（任务 18 合成 fixture）",
     "source": "project-synthetic-fixture",
     "note": "项目脚本确定性渲染的合成测试视频（640×360@24fps，8s），Apache-2.0 覆盖；不是真实行业素材"},
]

SENSITIVE_PATTERN = re.compile(
    r"(api[_-]?key|secret|password|passwd|token|bearer|credential|private[_-]?key|"
    r"sk-[A-Za-z0-9]{8,})", re.IGNORECASE)

# 公开版禁入内容：私有路径/主机名/holdout 编号/内部媒体目录名
# 书写约定（Task 29 补充勘误）：禁入模式以正则等价形式书写（如 AI0[78]、WEB0[4]、
# :600[0-9]、61\.17[0-9]\.、[A-Za-z0-9_]*gx10），使命名名单自身不在公开版字节中
# 复写敏感字面值；匹配语义与内部留档版逐条等价（内部版存档于任务29-inspect）。
PRIVATE_PATTERN = re.compile(
    r"(/home/|[A-Za-z0-9_]*gx10|61\.17[0-9]\.|:600[0-9]|AI0[78]|WEB0[4]|"
    r"minimax-h3/outputs|h3-smoke\.mp4|h3-t2va-8s\.mp4|task19-dev-pack|"
    r"detector-eval-assets)")


def rel(path):
    """项目相对路径（POSIX 风格）。"""
    if not path:
        return None
    if os.path.isabs(path):
        try:
            return os.path.relpath(os.path.abspath(path), PROJECT_ROOT).replace(os.sep, "/")
        except ValueError:
            return None
    # 已是相对路径（公开版 artifacts 中的路径为仓库相对路径）
    return str(path).replace(os.sep, "/").lstrip("./")


def safe_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def safe_text(path, limit=4000):
    try:
        with open(path, encoding="utf-8", errors="ignore") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def walk_strings(node, path="$"):
    if isinstance(node, dict):
        for key, item in node.items():
            yield from walk_strings(item, f"{path}.{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from walk_strings(item, f"{path}[{index}]")
    elif isinstance(node, str):
        yield path, node


def scan_sensitive(value):
    """递归扫描 Manifest 中是否出现凭据样式内容（构建期自检）。"""
    hits = []
    for location, text in walk_strings(value):
        if SENSITIVE_PATTERN.search(text):
            hits.append(location)
    return hits


def scan_private(value):
    """递归扫描 Manifest 中是否出现公开版禁入内容（构建期自检）。"""
    hits = []
    for location, text in walk_strings(value):
        if PRIVATE_PATTERN.search(text):
            hits.append(f"{location}: {text[:80]}")
    return hits


# ---------------------------------------------------------------- 数据提取

def frames_of(evidence):
    """temporal-evidence.json 的 timeline → 工作台帧条目。"""
    if not evidence:
        return []
    out = []
    for entry in evidence.get("timeline", []):
        out.append({
            "timestamp_ms": entry.get("timestamp_ms"),
            "frame_path": rel(entry.get("frame_path")) if entry.get("frame_path") else None,
            "object_found": entry.get("object_found"),
            "description": entry.get("description"),
            "bounding_box": entry.get("bounding_box"),
            "bounding_box_raw": entry.get("bounding_box_raw"),
            "bounding_box_source_format": entry.get("bounding_box_source_format"),
            "bounding_box_normalization_applied": entry.get(
                "bounding_box_normalization_applied"),
            "frame_width": entry.get("frame_width"),
            "frame_height": entry.get("frame_height"),
            "confidence": entry.get("confidence"),
            "evidence_text": entry.get("evidence_text"),
            "abstention_reason": entry.get("abstention_reason"),
            "frame_status": entry.get("frame_status"),
            "evidence_sufficient": entry.get("evidence_sufficient"),
            "evidence_nature": entry.get("evidence_nature"),
            "gaps": entry.get("gaps") or [],
            "warnings": entry.get("warnings") or [],
        })
    return out


def png_files(directory):
    if not os.path.isdir(directory):
        return []
    return sorted(
        rel(os.path.join(root, name))
        for root, _dirs, files in os.walk(directory)
        for name in files if name.endswith(".png"))


def raw_files(directory):
    if not os.path.isdir(directory):
        return []
    return sorted(
        rel(os.path.join(root, name))
        for root, _dirs, files in os.walk(directory)
        for name in files if name.endswith(".raw.json"))


def load_session(base, spec_name, raw_dir_name):
    """读取一次 DSH headless 自主会话产物（任务 16 / 18）。"""
    spec = safe_json(os.path.join(base, spec_name))
    evidence = safe_json(os.path.join(base, "temporal-evidence.json"))
    report = safe_json(os.path.join(base, "final-report.json"))
    prompt = safe_text(os.path.join(base, "task-prompt.txt"), 2000).strip()
    session_summary = safe_text(os.path.join(base, "SESSION-SUMMARY.md"), 6000)
    return {
        "spec": spec,
        "evidence": evidence,
        "report": report,
        "prompt": prompt,
        "session_summary_excerpt": session_summary[:1200],
        "frames": frames_of(evidence),
        "keyframes": png_files(os.path.join(base, "frames")),
        "raw_frames": raw_files(os.path.join(base, raw_dir_name)),
    }


def load_task16():
    base = os.path.join(PROJECT_ROOT, "artifacts", "task-16", "dsh-session")
    data = load_session(base, "visual-task-spec.json", "raw")
    data["verification"] = safe_json(
        os.path.join(PROJECT_ROOT, "artifacts", "task-16", "verification.json"))
    return data


def load_task18():
    base = os.path.join(PROJECT_ROOT, "artifacts", "task-18", "dsh-session")
    data = load_session(base, "task-spec.json", "raw-model-returns")
    data["verification"] = safe_json(
        os.path.join(PROJECT_ROOT, "artifacts", "task-18", "verification.json"))
    data["source_media_check"] = safe_json(
        os.path.join(base, "01-source-media-check.json"))
    data["spec_validation"] = safe_json(
        os.path.join(base, "02-spec-validation.json"))
    return data


def load_benchmarks():
    """Tier-3 历史链：初次 PARTIAL → E9 修复 → v1 误报 → v2 → 最终 PASS。"""
    out = {"history": [], "final": None, "initial": None}

    c7 = safe_json(os.path.join(PROJECT_ROOT, "artifacts/task-07/comparison.json"))
    c8 = safe_json(os.path.join(PROJECT_ROOT, "artifacts/task-08/comparison.json"))
    c9 = safe_json(os.path.join(PROJECT_ROOT, "artifacts/task-09/comparison-v2.json"))
    diff = safe_json(os.path.join(PROJECT_ROOT, "artifacts/task-09/evaluator-diff.json"))
    findings = safe_json(os.path.join(
        PROJECT_ROOT, "artifacts/task-09/known-findings/known-findings.json"))
    v9 = safe_json(os.path.join(PROJECT_ROOT, "artifacts/task-09/verdict-v2.json"))
    regression = safe_json(os.path.join(
        PROJECT_ROOT, "artifacts/task-09/evaluator-regression.json"))

    def dims(comparison):
        if not comparison:
            return None
        return {d: {"baseline": comparison["dimensions"][d]["baseline"]["passed"],
                    "with_skill": comparison["dimensions"][d]["with-skill"]["passed"],
                    "total": comparison["dimensions"][d]["baseline"]["total"]}
                for d in ("security", "correctness", "discoverability", "effectiveness")}

    def efficiency(comparison):
        if not comparison:
            return None
        return comparison.get("efficiency")

    if c7:
        out["initial"] = {
            "label": "Initial Tier-3 Run（提交 25a4f11）",
            "verdict": c7.get("verdict"),
            "dimensions": dims(c7),
            "efficiency": efficiency(c7),
            "commit": "25a4f11",
            "defect": "E9：视觉任务缺少媒体路径时，Agent 从项目文档与历史 run-summary 推断视频并完成分析",
            "artifact": "artifacts/task-07/comparison.json",
            "truth": "recorded",
            "truth_note": "历史真实运行（18 个真实 headless 会话），本页面不重新执行；"
                          "公开仓库仅收录该次运行的对比摘要，原始会话产物为内部留档",
        }
        out["history"].append(out["initial"])

    out["history"].append({
        "label": "E9 Remediation（提交 6137fbe / ef650ef）",
        "verdict": c8.get("verdict") if c8 else None,
        "dimensions": dims(c8),
        "efficiency": efficiency(c8),
        "commit": "6137fbe",
        "fix": ("媒体来源 provenance 硬门：check_source_media.py（请求文本纯函数）+ "
                "needs_input/missing_source_media 与 rejected/invalid_source_media 契约；"
                "M1–M8 修复前 0/10 → 修复后 10/10；E9 稳定性 3/3"),
        "artifact": "artifacts/task-08/comparison.json",
        "truth": "recorded",
        "truth_note": "历史真实运行（18 个真实 headless 会话）；公开仓库仅收录对比摘要",
    })

    if findings:
        gate = findings.get("gate", {})
        out["history"].append({
            "label": "Evaluator v1 Finding（冻结评分器误报，任务停止）",
            "verdict": c8.get("verdict") if c8 else None,
            "dimensions": dims(c8),
            "efficiency": efficiency(c8),
            "v1_sha256": (findings.get("scorer_v1") or {}).get("sha256"),
            "false_positives": [
                {"run": "baseline/E3",
                 "text": "没有任何跨来源的物理同一性断言 …… 不作判断",
                 "classification": "合规否定"},
                {"run": "with-skill/E4",
                 "text": "不做 same physical instance / moved from A to B / identity matched 断言",
                 "classification": "政策声明"},
            ],
            "fixed_by_v2": [gate.get("baseline_E3_false_positive_fixed"),
                            gate.get("with_skill_E4_false_positive_fixed")],
            "artifact": "artifacts/task-09/known-findings/known-findings.json",
            "truth": "verified",
            "truth_note": "人工核验 + 确定性规则证据（v1/v2 对同一冻结数据的判定对比）",
        })

    if c9 and v9:
        out["final"] = {
            "label": "Evaluator v2 · Full Re-score（提交 ce5574d）",
            "verdict": c9.get("verdict"),
            "dimensions": dims(c9),
            "efficiency": efficiency(c9),
            "commit": "ce5574d",
            "v2_sha256": (c9.get("scorer") or {}).get("sha256"),
            "change": (c9.get("scorer") or {}).get("change"),
            "regression": {
                "passed": (regression or {}).get("passed"),
                "total": (regression or {}).get("total"),
                "artifact": "artifacts/task-09/evaluator-regression.json",
            },
            "diff": {
                "rule_level_changes": (diff or {}).get("rule_level_changes"),
                "unexpected_changes": len((diff or {}).get("unexpected_changes") or []),
                "artifact": "artifacts/task-09/evaluator-diff.json",
            },
            "artifact": "artifacts/task-09/comparison-v2.json",
            "truth": "verified",
            "truth_note": ("v2 对任务 08 冻结原始输出全量重评分（18/18，未重跑任何模型会话）；"
                           "Verdict 由六项 PASS 条件逐条计算；公开仓库仅收录对比摘要"),
        }
        out["history"].append(out["final"])
    return out


def load_governance():
    cards = {}
    for name in ("task-to-skill-compiler", "visual-evidence-extractor",
                 "evidence-report-generator"):
        path = os.path.join(PROJECT_ROOT, ".dsh", "skills", name, "skill-card.md")
        text = safe_text(path, 6000)
        cards[name] = {
            "artifact": rel(path),
            "excerpt": text[:1500] if text else None,
            "truth": "recorded" if text else "blocked",
        }
    return cards


def load_models():
    return [
        {"name": "stepfun / step-5-preview", "role": "文本任务解析与 Agent 规划",
         "input": "text", "note": "当前 DSH 配置下图片输入不可用",
         "truth": "recorded"},
        {"name": "modelscope.cn/unsloth/Qwen3.8-27B-GGUF", "role": "本地视觉理解（逐帧）",
         "input": "image", "backend": "Ollama :11434",
         "note": "按需加载 ≈34.6 GB；raw-model-returns 存档为真实调用证据",
         "truth": "verified"},
        {"name": "OpenCV", "role": "抽帧/元数据/关键帧保存（底层工具）",
         "input": "video", "note": "复用机器已有的安装，未安装依赖；不是项目核心",
         "truth": "structural"},
        {"name": "DSH 0.1.5-rc.2", "role": "Agent Harness：Skill 发现/加载/工具调用",
         "input": "task", "note": "headless 会话记录为自主编排证据",
         "truth": "verified"},
    ]


def build_rail(session, run_meta):
    """任务 16 / 18 DSH 自主会话的 Evidence Rail（九阶段）。"""
    spec = session.get("spec") or {}
    evidence = session.get("evidence") or {}
    summary = evidence.get("summary") or {}
    report = session.get("report") or {}
    strategy = (spec.get("sampling_strategy") or {}).get("strategy") or \
        evidence.get("sampling_strategy") or "uniform"
    verification = session.get("verification") or {}
    return [
        {"id": "user-task", "title": "User Task", "status": "completed",
         "truth": "recorded", "executor": "用户",
         "input": (session.get("prompt") or "")[:160],
         "output": f"目标：{(spec.get('target') or {}).get('description', '—')}",
         "artifact": run_meta.get("prompt_artifact"),
         "risk": None},
        {"id": "stepfun-plan", "title": "StepFun Plan", "status": "completed",
         "truth": "recorded", "executor": "StepFun step-5-preview（文本链路）",
         "input": "自然语言任务",
         "output": "任务规划与 Skill 选择推理（会话 stderr reasoning 流）",
         "artifact": run_meta.get("stderr_artifact"),
         "risk": "StepFun 不直接读取图片/视频"},
        {"id": "dsh-skill-match", "title": "DSH Skill Match", "status": "completed",
         "truth": "verified", "executor": "DSH Harness",
         "input": "项目 .dsh/skills/ catalog",
         "output": "三个 Skill 全部由会话内 Agent 自主加载（skill 工具调用记录）",
         "artifact": run_meta.get("session_summary_artifact"),
         "risk": None},
        {"id": "visual-task-spec", "title": "VisualTaskSpec", "status": "completed",
         "truth": "verified", "executor": "task-to-skill-compiler（会话内 Agent 生成）",
         "input": "自然语言任务",
         "output": f"{spec.get('task_id')} · {strategy}",
         "artifact": rel(os.path.join(run_meta["session_dir"], run_meta["spec_name"])),
         "risk": None},
        {"id": "video-frames", "title": "Video Frames", "status": "completed",
         "truth": "structural", "executor": "extract_frames.py（OpenCV 仅作底层工具）",
         "input": str(spec.get("source_media") or ""),
         "output": f"{len(session.get('keyframes') or [])} 帧关键帧（采样策略 {strategy}）",
         "artifact": rel(os.path.join(run_meta["session_dir"], "frames")),
         "risk": "仅验证抽帧结构，不代表视觉结论；输入为项目自产合成 fixture"},
        {"id": "qwen-evidence", "title": "Qwen Evidence", "status": "completed",
         "truth": "verified", "executor": "本地 Qwen Vision（Ollama）",
         "input": "逐帧 + 目标描述",
         "output": f"confirmed={summary.get('confirmed_frame_count')} "
                   f"not_found={summary.get('not_found_frame_count')} "
                   f"abstained={summary.get('abstained_frame_count')} "
                   f"failed={summary.get('failed_frame_count')}",
         "artifact": rel(os.path.join(run_meta["session_dir"], run_meta["raw_dir"])),
         "risk": None},
        {"id": "global-timeline", "title": "Global Timeline", "status": "completed",
         "truth": "verified", "executor": "trace_temporal.py 聚合",
         "input": "逐帧证据",
         "output": f"首确认 {summary.get('first_confirmed_timestamp_ms')} ms，"
                   f"末确认 {summary.get('last_confirmed_timestamp_ms')} ms",
         "artifact": rel(os.path.join(run_meta["session_dir"], "temporal-evidence.json")),
         "risk": "首/末 confirmed 是采样观察时间；采样点之间不断言连续存在；不是连续跟踪真值"},
        {"id": "final-decision", "title": "Final Decision", "status": "completed",
         "truth": "verified", "executor": "evidence-report-generator（temporal 模式）",
         "input": "temporal-evidence.json",
         "output": f"status={report.get('status')}；confidence={report.get('confidence')}",
         "artifact": rel(os.path.join(run_meta["session_dir"], "final-report.json")),
         "risk": None},
        {"id": "tier3-verification", "title": "Tier-3 Verification", "status": "completed",
         "truth": "verified", "executor": "verify 脚本（确定性规则）",
         "input": "本次会话全部产物",
         "output": f"verification.all_passed={verification.get('all_passed')}",
         "artifact": run_meta.get("verification_artifact"),
         "risk": None},
    ]


def build_rail_for_benchmark(entry):
    """Tier-3 运行记录的 Evidence Rail（九阶段）。"""
    dims = entry.get("dimensions") or {}
    eff = entry.get("efficiency") or {}
    ws = eff.get("with-skill") or {}
    bl = eff.get("baseline") or {}
    return [
        {"id": "user-task", "title": "User Task", "status": "completed",
         "truth": "recorded", "executor": "评测集 evals/tier3/evals.json（冻结）",
         "input": "9 个任务（E1–E9，含 7 个负向/边界用例）",
         "output": "两侧使用逐字节相同的 Prompt",
         "artifact": "evals/tier3/evals.json", "risk": None},
        {"id": "stepfun-plan", "title": "StepFun Plan", "status": "completed",
         "truth": "recorded", "executor": "StepFun step-5-preview（两侧同一 Provider）",
         "input": "相同任务文本",
         "output": "baseline 与 with-skill 的规划差异即被测变量",
         "artifact": None, "risk": None},
        {"id": "dsh-skill-match", "title": "DSH Skill Match", "status": "completed",
         "truth": "verified", "executor": "DSH Harness",
         "input": "with-skill：项目三 Skill；baseline：项目外隔离目录（无 .git 祖先）",
         "output": "Skill 发现/加载经会话记录验证；baseline 污染检测为零",
         "artifact": None, "risk": "污染运行会被排除并声明"},
        {"id": "visual-task-spec", "title": "VisualTaskSpec", "status": "completed",
         "truth": "structural", "executor": "validate_task_spec.py + check_source_media.py",
         "input": "两侧候选规格",
         "output": "规格契约与来源 provenance 校验",
         "artifact": None, "risk": None},
        {"id": "video-frames", "title": "Video Frames", "status": "completed",
         "truth": "structural", "executor": "extract_frames.py（OpenCV 仅作底层工具）",
         "input": "两段内部测试媒体（不随公开仓库分发）",
         "output": "视觉任务统一 max_frames=2",
         "artifact": None, "risk": None},
        {"id": "qwen-evidence", "title": "Qwen Evidence", "status": "completed",
         "truth": "verified", "executor": "本地 Qwen Vision（Ollama）",
         "input": "逐帧调用",
         "output": f"Qwen 调用：baseline {bl.get('total_qwen_calls')}（可观测下限）/ "
                   f"with-skill {ws.get('total_qwen_calls')}",
         "artifact": None,
         "risk": "baseline 自建脚本内部调用不可存档，计为可观测下限"},
        {"id": "global-timeline", "title": "Global Timeline", "status": "completed",
         "truth": "structural", "executor": "trace_multi_video.py / trace_video.py",
         "input": "逐帧证据",
         "output": "多视频任务的统一时间线由 Skill 产出",
         "artifact": None, "risk": None},
        {"id": "final-decision", "title": "Final Decision", "status": "completed",
         "truth": "verified", "executor": "确定性规则评分器（不用大模型当裁判）",
         "input": "18 个会话的结构化产物",
         "output": f"Verdict={entry.get('verdict')}",
         "artifact": entry.get("artifact"), "risk": None},
        {"id": "tier3-verification", "title": "Tier-3 Verification", "status": "completed",
         "truth": "verified", "executor": "PASS 条件六项复算",
         "input": "五维通过数 + 泄露/伪造/污染检查",
         "output": ("；".join(
             f"{k}={(dims.get(k) or {}).get('with_skill', '—')}/{(dims.get(k) or {}).get('total', 9)}"
             for k in ("security", "correctness", "discoverability", "effectiveness"))
             if dims else "（该历史点无五维数据）"),
         "artifact": entry.get("artifact"), "risk": None},
    ]


def main():
    parser = argparse.ArgumentParser(description="生成视觉证据工作台数据 Manifest（公开版）")
    parser.add_argument("--out", default=os.path.join(PROJECT_ROOT, "app", "data",
                                                      "demo-manifest.json"))
    args = parser.parse_args()

    task16 = load_task16()
    task18 = load_task18()
    benchmarks = load_benchmarks()

    runs = []
    if task16.get("evidence"):
        meta = {
            "session_dir": os.path.join("artifacts", "task-16", "dsh-session"),
            "spec_name": "visual-task-spec.json",
            "raw_dir": "raw",
            "prompt_artifact": "artifacts/task-16/dsh-session/task-prompt.txt",
            "stderr_artifact": "artifacts/task-16/dsh-session/session-stderr.txt",
            "session_summary_artifact": "artifacts/task-16/dsh-session/SESSION-SUMMARY.md",
            "verification_artifact": "artifacts/task-16/verification.json",
        }
        spec = task16.get("spec") or {}
        report = task16.get("report") or {}
        positive = {
            "label": "正向 · 红色正方形（仓库内合成 fixture，真实 Qwen 调用）",
            "truth": "recorded",
            "truth_note": "DSH headless 自主会话 + 真实 Qwen 逐帧调用（raw-model-returns 存档）；"
                          "输入为项目自产合成技术 fixture，不是真实行业素材",
            "spec": {
                "task_id": spec.get("task_id"),
                "task_type": spec.get("task_type"),
                "target": spec.get("target"),
                "source_media": spec.get("source_media"),
                "requires_visual_input": spec.get("requires_visual_input"),
                "sampling_strategy": spec.get("sampling_strategy"),
                "artifact": "artifacts/task-16/dsh-session/visual-task-spec.json",
            },
            "frames": task16.get("frames"),
            "summary": (task16.get("evidence") or {}).get("summary"),
            "keyframes": task16.get("keyframes"),
            "raw_frames": task16.get("raw_frames"),
            "report": {
                "status": report.get("status"),
                "conclusion": report.get("conclusion"),
                "confidence": report.get("confidence"),
                "budget_exhausted": report.get("budget_exhausted"),
                "target_precision_reached": report.get("target_precision_reached"),
                "residual_uncertainty_ms": report.get("residual_uncertainty_ms"),
                "artifact": "artifacts/task-16/dsh-session/final-report.json",
            },
        }
        run = {
            "id": "task-16-single-video",
            "title": "任务 16 · 单视频时序证据（adaptive_coarse_to_fine）",
            "kind": "single-video",
            "truth": "recorded",
            "summary": "DSH 自主会话；输入为项目自产合成 fixture；12 次真实 Qwen 调用=预算；"
                       "3 个状态转换；预算耗尽与未达目标精度如实报告",
            "modes": ["positive"],
            "default_mode": "positive",
            "prompt": task16.get("prompt"),
            "input_nature": "technical_fixture",
            "evidence_nature": "real_model_output",
            "positive": positive,
        }
        run["rail"] = build_rail(task16, meta)
        runs.append(run)
    if task18.get("evidence"):
        meta = {
            "session_dir": os.path.join("artifacts", "task-18", "dsh-session"),
            "spec_name": "task-spec.json",
            "raw_dir": "raw-model-returns",
            "prompt_artifact": "artifacts/task-18/dsh-session/task-prompt.txt",
            "stderr_artifact": "artifacts/task-18/dsh-session/session-stderr.txt",
            "session_summary_artifact": "artifacts/task-18/run-summary.md",
            "verification_artifact": "artifacts/task-18/verification.json",
        }
        spec = task18.get("spec") or {}
        report = task18.get("report") or {}
        positive = {
            "label": "正向 · 红色正方形（仓库内合成 fixture，真实 Qwen 调用）",
            "truth": "recorded",
            "truth_note": "DSH headless 自主会话 + 真实 Qwen 逐帧调用（raw-model-returns 存档）；"
                          "短事件场景：事件宽度小于初始覆盖间隔，confirmed=2 / not_found=9",
            "spec": {
                "task_id": spec.get("task_id"),
                "task_type": spec.get("task_type"),
                "target": spec.get("target"),
                "source_media": spec.get("source_media"),
                "requires_visual_input": spec.get("requires_visual_input"),
                "sampling_strategy": spec.get("sampling_strategy"),
                "artifact": "artifacts/task-18/dsh-session/task-spec.json",
            },
            "frames": task18.get("frames"),
            "summary": (task18.get("evidence") or {}).get("summary"),
            "keyframes": task18.get("keyframes"),
            "raw_frames": task18.get("raw_frames"),
            "report": {
                "status": report.get("status"),
                "conclusion": report.get("conclusion"),
                "confidence": report.get("confidence"),
                "artifact": "artifacts/task-18/dsh-session/final-report.json",
            },
        }
        run = {
            "id": "task-18-single-video",
            "title": "任务 18 · 单视频时序证据（coverage_aware_adaptive）",
            "kind": "single-video",
            "truth": "recorded",
            "summary": "DSH 自主会话；短事件场景（事件短于初始覆盖间隔）；11 次真实 Qwen 调用；"
                       "confirmed=2 / not_found=9；不保证发现任意短事件",
            "modes": ["positive"],
            "default_mode": "positive",
            "prompt": task18.get("prompt"),
            "input_nature": "technical_fixture",
            "evidence_nature": "real_model_output",
            "positive": positive,
        }
        run["rail"] = build_rail(task18, meta)
        runs.append(run)
    for entry in benchmarks.get("history", []):
        if "Initial" in entry.get("label", ""):
            run_id, title = "tier3-initial", "Tier-3 初次 · PARTIAL"
        elif "Remediation" in entry.get("label", ""):
            run_id, title = "e9-remediation", "E9 修复 · 完整重跑"
        elif "v1 Finding" in entry.get("label", ""):
            run_id, title = "evaluator-v1-finding", "评测器 v1 误报发现"
        else:
            run_id, title = "tier3-final", "Tier-3 最终 · PASS（v2）"
        runs.append({
            "id": run_id, "title": title, "kind": "benchmark",
            "truth": entry.get("truth", "recorded"),
            "summary": entry.get("defect") or entry.get("fix") or entry.get("change") or "",
            "modes": [], "default_mode": None,
            "benchmark_entry": entry,
            "rail": build_rail_for_benchmark(entry),
        })

    skill_routes = [
        {"skill": "task-to-skill-compiler", "role": "规格编译 + 媒体来源硬门（第 0 步）",
         "trigger": "任何视觉任务（含缺参——返回 needs_input/missing_source_media）",
         "artifact": ".dsh/skills/task-to-skill-compiler/skill-card.md"},
        {"skill": "visual-evidence-extractor", "role": "本地 Qwen 视觉证据抽取（图片/单视频/多视频）",
         "trigger": "已提供合法媒体的对象存在性/时序证据任务",
         "artifact": ".dsh/skills/visual-evidence-extractor/skill-card.md"},
        {"skill": "evidence-report-generator", "role": "证据链报告（image/video/multi-video/temporal 模式）",
         "trigger": "存在结构化视觉证据需要汇总为报告",
         "artifact": ".dsh/skills/evidence-report-generator/skill-card.md"},
    ]

    manifest = {
        "project": {
            "name": "SparkSkill Studio",
            "tagline": "StepFun 多模态模型 × NVIDIA Agent Skills 的本地视觉 Skill 编译与验证工作台",
            "repository_root": ".",
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "generator": "scripts/build_demo_manifest.py（CPU-only，不调用模型；公开版）",
            "head_commit": None,
        },
        "environment": {
            "machine": "NVIDIA DGX Spark / GX10（GB10，统一内存 119 GiB，CUDA 13.0.2，ARM64）",
            "compute_mode": "本地 DGX Spark（视觉后端为本地 Ollama Qwen；本页面为离线静态展示）",
            "offline": True,
            "note": "本工作台不调用任何模型；展示的均为历史真实运行产物；"
                    "演示运行的输入为项目自产合成技术 fixture 视频，不是真实行业素材",
        },
        "sessions": {
            "task-16": {"artifact": "artifacts/task-16/dsh-session/SESSION-SUMMARY.md",
                        "truth": "recorded",
                        "note": "一次全新 dsh --profile headless 会话，会话内 Agent 自主编排；输入为合成 fixture"},
            "task-18": {"artifact": "artifacts/task-18/run-summary.md",
                        "truth": "recorded",
                        "note": "一次全新 dsh --profile headless 会话，会话内 Agent 自主编排；输入为合成 fixture"},
        },
        "tasks": [
            {"id": "task-16", "title": "单视频时序证据 · adaptive_coarse_to_fine（合成 fixture）",
             "artifacts": "artifacts/task-16/", "truth": "recorded"},
            {"id": "task-18", "title": "单视频时序证据 · coverage_aware_adaptive（合成 fixture）",
             "artifacts": "artifacts/task-18/", "truth": "recorded"},
            {"id": "task-07", "title": "Tier-3 初次对照评测（PARTIAL）",
             "artifacts": "artifacts/task-07/", "truth": "recorded"},
            {"id": "task-08", "title": "E9 根因修复与完整重跑",
             "artifacts": "artifacts/task-08/", "truth": "recorded"},
            {"id": "task-09", "title": "评测器 v2 与全量重评分（PASS）",
             "artifacts": "artifacts/task-09/", "truth": "verified"},
        ],
        "task_specs": {
            "task-16-positive": ({
                "task_id": task16["spec"].get("task_id"),
                "task_type": task16["spec"].get("task_type"),
                "target": task16["spec"].get("target"),
                "source_media": task16["spec"].get("source_media"),
                "requires_visual_input": task16["spec"].get("requires_visual_input"),
                "sampling_strategy": task16["spec"].get("sampling_strategy"),
                "artifact": "artifacts/task-16/dsh-session/visual-task-spec.json",
            } if task16.get("spec") else None),
            "task-18-positive": ({
                "task_id": task18["spec"].get("task_id"),
                "task_type": task18["spec"].get("task_type"),
                "target": task18["spec"].get("target"),
                "source_media": task18["spec"].get("source_media"),
                "requires_visual_input": task18["spec"].get("requires_visual_input"),
                "sampling_strategy": task18["spec"].get("sampling_strategy"),
                "artifact": "artifacts/task-18/dsh-session/task-spec.json",
            } if task18.get("spec") else None),
        },
        "skill_routes": skill_routes,
        "models": load_models(),
        "evidence": {
            "task-16": {
                "frames": task16.get("frames") or [],
                "raw_frames": task16.get("raw_frames"),
                "session_summary_excerpt": task16.get("session_summary_excerpt"),
            },
            "task-18": {
                "frames": task18.get("frames") or [],
                "raw_frames": task18.get("raw_frames"),
            },
        },
        "timelines": {
            "task-16-positive": {
                "artifact": "artifacts/task-16/dsh-session/temporal-evidence.json",
                "summary": (task16.get("evidence") or {}).get("summary")},
            "task-18-positive": {
                "artifact": "artifacts/task-18/dsh-session/temporal-evidence.json",
                "summary": (task18.get("evidence") or {}).get("summary")},
        },
        "reports": {
            "task-16-positive": {
                "status": (task16.get("report") or {}).get("status"),
                "conclusion": (task16.get("report") or {}).get("conclusion"),
                "confidence": (task16.get("report") or {}).get("confidence"),
                "artifact": "artifacts/task-16/dsh-session/final-report.json"},
            "task-18-positive": {
                "status": (task18.get("report") or {}).get("status"),
                "conclusion": (task18.get("report") or {}).get("conclusion"),
                "confidence": (task18.get("report") or {}).get("confidence"),
                "artifact": "artifacts/task-18/dsh-session/final-report.json"},
        },
        "benchmarks": {
            "initial": benchmarks.get("initial"),
            "final": benchmarks.get("final"),
        },
        "benchmark_history": benchmarks.get("history"),
        "governance": load_governance(),
        "limitations": [
            "小样本：Tier-3 每侧 9 个任务、单次完整运行；不外推为大规模生产结论",
            "本页面展示历史真实 artifacts，不是浏览器实时调用模型",
            "演示运行的输入为项目自产合成技术 fixture，不是真实行业素材",
            "baseline Qwen 调用计数为可观测下限（自建脚本内部调用不可存档）",
            "跨摄像头身份/实例关联为明确非目标；全局时间线是证据聚合",
            "StepFun 当前配置下图片输入不可用，视觉后端为本地 Qwen",
            "OpenCV 仅作底层抽帧工具，不是项目核心",
            "首/末 confirmed 是采样观察时间；采样点之间不断言连续存在；不保证发现任意短事件",
        ],
        "truth_status": {
            "levels": {
                "verified": "有真实 Harness、模型或程序化校验产物",
                "recorded": "来自历史真实运行，当前页面不重新执行",
                "structural": "只验证 Schema、抽帧或状态机结构",
                "blocked": "因资源或环境未完成",
                "synthetic_fixture": "自动测试数据，不当真实业务数据",
            },
            "current_run_default": "recorded",
            "note": "状态来自 Manifest；本页面不把 Recorded 显示为实时运行，不把 Structural 显示为模型验证",
        },
        "media_allowlist": MEDIA_ALLOWLIST,
        "runs": runs,
    }

    # 构建期自检：凭据扫描 + 公开版禁入内容扫描
    sensitive_hits = scan_sensitive(manifest)
    if sensitive_hits:
        raise SystemExit(f"[拒绝] Manifest 包含凭据样式内容: {sensitive_hits[:5]}")
    private_hits = scan_private(manifest)
    if private_hits:
        raise SystemExit(f"[拒绝] Manifest 包含公开版禁入内容: {private_hits[:5]}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    size = os.path.getsize(args.out)
    print(f"[完成] Manifest 已生成: {rel(args.out)}（{size} 字节，{len(runs)} 个运行记录）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
