#!/usr/bin/env python3
"""test_missing_media_contract.py — 缺参/非法媒体契约测试（SparkSkill Studio 任务 08）

对 task-to-skill-compiler 的"媒体来源可信"契约做确定性测试（不调用任何模型）：

  M1 视觉任务无媒体路径            → needs_input / missing_source_media
  M2 "这个视频"式指代无附件/路径   → needs_input / missing_source_media
  M3 项目文档有历史路径但用户未提供 → 不读取历史路径、不选默认视频、missing_source_media
  M4 README/run-summary 含示例路径  → 示例路径不能作为用户输入、missing_source_media
  M5 用户显式提供合法视频路径       → 可继续编译（accepted，候选来源被提取）
  M6 用户显式提供多个合法视频路径   → 可继续多视频任务（accepted，两个候选）
  M7 非法路径                      → invalid_source_media（不得退化成 missing）
  M8 非视觉任务                    → 不触发视觉媒体检查（not_applicable）

另含校验器契约测试：
  V1 规格缺少 source_media         → missing_source_media / needs_input
  V2 规格含未授权路径              → invalid_source_media / rejected

用法:
    python3 test_missing_media_contract.py [--results-json <path>]
退出码: 0 = 全部通过; 1 = 存在失败项
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "..", "..", "..", ".."))
COMPILER_DIR = os.path.join(PROJECT_ROOT, ".dsh", "skills", "task-to-skill-compiler")
CHECKER = os.path.join(COMPILER_DIR, "scripts", "check_source_media.py")
VALIDATOR = os.path.join(COMPILER_DIR, "scripts", "validate_task_spec.py")
SCHEMA = os.path.join(PROJECT_ROOT, "schemas", "visual-task-spec.schema.json")

RESULTS = []


def record(test_id, name, passed, detail, expectation):
    RESULTS.append({
        "id": test_id, "name": name, "passed": bool(passed),
        "detail": detail, "expectation": expectation,
    })
    print(f"[{'PASS' if passed else 'FAIL'}] {test_id} — {name}: {detail}")


def run_checker(request_text, spec=None, cwd="/tmp"):
    """运行来源前置校验器；返回 (exit_code, contract_dict_or_None, raw_stdout)。"""
    if not os.path.isfile(CHECKER):
        return None, None, f"校验器不存在: {CHECKER}"
    with tempfile.TemporaryDirectory(prefix="t08-mtest-") as tmp:
        request_path = os.path.join(tmp, "request.txt")
        with open(request_path, "w", encoding="utf-8") as handle:
            handle.write(request_text)
        command = [sys.executable, CHECKER, "--request", request_path]
        if spec is not None:
            spec_path = os.path.join(tmp, "spec.json")
            with open(spec_path, "w", encoding="utf-8") as handle:
                json.dump(spec, handle, ensure_ascii=False)
            command += ["--spec", spec_path]
        proc = subprocess.run(command, capture_output=True, text=True, cwd=cwd, timeout=120)
        contract = None
        try:
            contract = json.loads(proc.stdout.strip())
        except (json.JSONDecodeError, ValueError):
            pass
        return proc.returncode, contract, proc.stdout.strip()


def run_validator(spec):
    with tempfile.TemporaryDirectory(prefix="t08-vtest-") as tmp:
        spec_path = os.path.join(tmp, "spec.json")
        with open(spec_path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle, ensure_ascii=False)
        proc = subprocess.run([sys.executable, VALIDATOR, "--schema", SCHEMA,
                               "--input", spec_path],
                              capture_output=True, text=True, timeout=120)
        return proc.returncode, proc.stdout + proc.stderr


def base_spec(source_media=None):
    spec = {
        "task_id": "t08-missing-media-test",
        "skill_name": "visual-evidence-extractor",
        "task_type": "object_trace",
        "target": {"description": "太阳", "attributes": []},
        "required_outputs": ["object_found", "description", "bounding_box", "confidence"],
        "constraints": {"abstain_if_insufficient_evidence": True,
                        "forbidden_inferences": ["identity", "age", "nationality",
                                                 "relationship", "intent"]},
        "confidence_threshold": 0.5,
        "requires_visual_input": True,
    }
    if source_media is not None:
        spec["source_media"] = source_media
    return spec


def main():
    # ---------------- M1：视觉任务无媒体路径
    exit_code, contract, raw = run_checker("请分析视频并寻找目标：太阳。给出存在性结论与证据。")
    ok = (contract or {}).get("status") == "needs_input" \
        and (contract or {}).get("error_code") == "missing_source_media" \
        and (contract or {}).get("tool_calls_allowed") is False
    record("M1-visual-task-no-media", "视觉任务无媒体路径 → needs_input/missing_source_media",
           ok, f"exit={exit_code} contract={json.dumps(contract, ensure_ascii=False)[:160] if contract else raw[:160]}",
           "needs_input + missing_source_media + tool_calls_allowed=false")

    # ---------------- M2："这个视频"式指代
    exit_code, contract, raw = run_checker("请分析这个视频并总结它的内容。")
    ok = (contract or {}).get("status") == "needs_input" \
        and (contract or {}).get("error_code") == "missing_source_media"
    record("M2-deictic-reference-no-media", "“这个视频”指代但无附件/路径 → missing_source_media",
           ok, f"exit={exit_code} contract={json.dumps(contract, ensure_ascii=False)[:160] if contract else raw[:160]}",
           "needs_input + missing_source_media")

    # ---------------- M3：项目文档有历史路径但用户未提供
    # 校验器必须是请求文本的纯函数：在 /tmp 下运行（远离项目），
    # 且请求文本不含任何路径——即使项目 artifacts 中存在大量历史视频路径，
    # 也不得影响判定（不读取、不选择默认视频）。
    request_m3 = "请分析视频并寻找目标：太阳。抽帧不超过 2 帧。"
    exit_code, contract, raw = run_checker(request_m3, cwd="/tmp")
    ok = (contract or {}).get("error_code") == "missing_source_media" \
        and (contract or {}).get("tool_calls_allowed") is False
    has_project_paths = os.path.isdir(os.path.join(PROJECT_ROOT, "artifacts", "task-07"))
    record("M3-historical-paths-not-consulted",
           "项目文档含历史路径但用户未提供 → 不读取/不选默认，missing_source_media",
           ok and has_project_paths,
           f"（项目历史路径存在={has_project_paths}，校验器在 /tmp 下运行）"
           f"exit={exit_code} contract={json.dumps(contract, ensure_ascii=False)[:160] if contract else raw[:160]}",
           "missing_source_media；判定与项目文件系统无关")

    # ---------------- M4：README/run-summary 含示例路径
    request_m4 = "请按项目文档里的示例视频，分析其中的太阳。"
    exit_code, contract, raw = run_checker(request_m4, cwd="/tmp")
    ok = (contract or {}).get("error_code") == "missing_source_media"
    record("M4-example-paths-not-user-input", "README/run-summary 示例路径不能作为用户输入",
           ok, f"exit={exit_code} contract={json.dumps(contract, ensure_ascii=False)[:160] if contract else raw[:160]}",
           "missing_source_media（示例路径不得被当作用户提供的媒体）")

    # ---------------- M5：显式提供单个合法路径
    # 公开版：使用仓库内任务 16 合成 fixture 的相对路径（授权根=项目根，
    # 任何机器上都被接受；不依赖任何开发机私有媒体）。
    video = "artifacts/task-16/fixtures/videos/fixture-reappear.mp4"
    request_m5 = f"请分析视频 {video}，寻找目标：红色正方形。"
    exit_code, contract, raw = run_checker(request_m5, cwd="/tmp")
    candidates = (contract or {}).get("source_media_candidates") or []
    ok = (contract or {}).get("status") == "accepted" \
        and (contract or {}).get("source_media_provenance") == "user_provided" \
        and any(video in str(item) for item in candidates)
    record("M5-explicit-single-path", "用户显式提供合法视频路径 → 可继续编译",
           ok, f"exit={exit_code} contract={json.dumps(contract, ensure_ascii=False)[:200] if contract else raw[:200]}",
           "accepted + user_provided + 候选来源被提取（仓库内合成 fixture 相对路径）")

    # ---------------- M6：显式提供多个合法路径
    video_b = "artifacts/task-18/fixtures/videos/fixture-short-event-between-grid.mp4"
    request_m6 = (f"请分析以下两个视频：{video} 与 {video_b}，"
                  f"寻找目标：红色正方形，分别给出证据并合并全局时间线。")
    exit_code, contract, raw = run_checker(request_m6, cwd="/tmp")
    candidates = (contract or {}).get("source_media_candidates") or []
    joined = json.dumps(candidates, ensure_ascii=False)
    ok = (contract or {}).get("status") == "accepted" \
        and video in joined and video_b in joined
    record("M6-explicit-multiple-paths", "用户显式提供多个合法视频路径 → 可继续多视频任务",
           ok, f"exit={exit_code} 候选数={len(candidates)}",
           "accepted + 两个候选来源均被提取")

    # ---------------- M7：非法路径（必须 invalid 而非 missing）
    request_m7 = "请分析这个媒体文件并总结内容：/etc/shadow"
    exit_code, contract, raw = run_checker(request_m7, cwd="/tmp")
    ok = (contract or {}).get("status") == "rejected" \
        and (contract or {}).get("error_code") == "invalid_source_media"
    record("M7-illegal-path", "非法路径 → invalid_source_media（不得退化成 missing）",
           ok, f"exit={exit_code} contract={json.dumps(contract, ensure_ascii=False)[:200] if contract else raw[:200]}",
           "rejected + invalid_source_media；不读取文件")

    # ---------------- M8：非视觉任务不触发媒体检查
    request_m8 = "请写一首关于仓库的诗。"
    exit_code, contract, raw = run_checker(request_m8, cwd="/tmp")
    ok = (contract or {}).get("status") == "not_applicable"
    record("M8-non-visual-task", "非视觉任务 → 不触发视觉媒体检查",
           ok, f"exit={exit_code} contract={json.dumps(contract, ensure_ascii=False)[:160] if contract else raw[:160]}",
           "not_applicable（不调用视觉 Skill）")

    # ---------------- V1：规格缺少 source_media → missing_source_media
    code, output = run_validator(base_spec(source_media=None))
    ok = "missing_source_media" in output and "needs_input" in output
    record("V1-spec-missing-source-media", "规格缺少 source_media → missing_source_media/needs_input",
           ok, f"exit={code}；输出含 missing_source_media={'missing_source_media' in output}，"
               f"needs_input={'needs_input' in output}",
           "missing_source_media + needs_input（与非法路径区分）")

    # ---------------- V2：规格含未授权路径 → invalid_source_media
    spec = base_spec(source_media="/etc/shadow")
    code, output = run_validator(spec)
    ok = "invalid_source_media" in output and "rejected" in output
    record("V2-spec-invalid-path", "规格含未授权路径 → invalid_source_media/rejected",
           ok, f"exit={code}；输出含 invalid_source_media={'invalid_source_media' in output}",
           "invalid_source_media + rejected")

    passed = sum(1 for item in RESULTS if item["passed"])
    total = len(RESULTS)
    print(f"\n小计：{passed}/{total} 通过")
    return 0 if passed == total else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="缺参/非法媒体契约测试")
    parser.add_argument("--results-json", help="测试结果 JSON 输出路径")
    args = parser.parse_args()
    code = main()
    if args.results_json:
        summary = {
            "suite": "task-08-missing-media-contract",
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "passed": sum(1 for item in RESULTS if item["passed"]),
            "total": len(RESULTS),
            "results": RESULTS,
        }
        with open(args.results_json, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    sys.exit(code)
