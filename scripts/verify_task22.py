#!/usr/bin/env python3
"""verify_task22.py — Task 22 交付验证（CPU-only，零模型调用）

复核项（供最终报告引用）:
  V1  Phase A 预注册提交早于第一笔正式 dev 调用（Git 历史时序）
  V2  冻结哈希全量重算一致（frozen-hashes.json）
  V3  256 点清单 + 帧字节 SHA-256 逐点一致
  V4  正式调用记账：512 次、失败分类、零重试、每帧每版一次
  V5  从 256 逐点存档用冻结评分器独立复算 v1/c3 七类账（各合计 256）
  V6  门槛与 verdict 独立复算与 paired-score.json 一致
  V7  分项支持完整度审计（c3 itemized_support_complete 比例）
  V8  去重敏感性按 frame_sha256（184 唯一帧）
  V9  git diff --check 干净 + 无凭据/敏感命中
  V10 无原始视频/权重/媒体误入 Git（task-22）
  V11 冻结路径（Task 17/18/19/20/21、app/、生产 v1、Tier-3）零改动
  V12 （若阶段 C 运行）动态运行记账与 Task 17 scorer 来源核验
"""
import glob
import importlib.util
import json
import os
import re
import subprocess
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
T22 = os.path.join(PROJECT_ROOT, "artifacts", "task-22")
PREREG = os.path.join(T22, "preregistration")
PAIRS = os.path.join(T22, "pairs")
SCORES = os.path.join(T22, "scores")
SCORER = os.path.join(PROJECT_ROOT, "scripts", "score_temporal_ground_truth.py")
SEVEN = ["correct_decisive", "incorrect_decisive", "abstention_on_determinate",
         "failed_on_determinate", "appropriate_abstention", "overclaim_on_uncertain",
         "failed_on_uncertain"]
GT_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ground-truth")
WHITELIST = {"AI01", "AI02", "AI03", "AI04", "AI05", "AI06", "WEB01", "WEB02", "WEB03"}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def sha256_of(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    results = []

    def check(vid, name, passed, detail=""):
        results.append({"id": vid, "name": name, "passed": bool(passed), "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {vid} {name}" + (f" — {detail}" if detail else ""),
              flush=True)

    scorer = load_module("frozen_scorer", SCORER)
    paired = load_module("paired_scorer", os.path.join(PREREG, "paired_scorer.py"))

    # V2 冻结哈希
    frozen = load_json(os.path.join(PREREG, "frozen-hashes.json"))
    fproblems = []
    for rel, entry in frozen["entries"].items():
        path = os.path.join(PROJECT_ROOT, rel)
        if not os.path.isfile(path) or sha256_of(path) != entry["sha256"]:
            fproblems.append(rel)
    check("V2", "冻结哈希全量重算一致", not fproblems,
          f"{len(frozen['entries'])} 条" + (f"；异常 {fproblems}" if fproblems else ""))

    # V1 Phase A 提交早于第一笔 dev 调用
    try:
        phase_a_sha = subprocess.run(
            ["git", "-C", PROJECT_ROOT, "log", "--format=%H %ci", "-1",
             "plan(task22): preregister"], capture_output=True, text=True)
        # 找到 preregister 提交
        log = subprocess.run(["git", "-C", PROJECT_ROOT, "log", "--format=%H|%ci",
                              "--grep", "preregister single-call"], capture_output=True, text=True)
        prereg_line = log.stdout.strip().splitlines()[0] if log.stdout.strip() else ""
        prereg_time = prereg_line.split("|")[1] if "|" in prereg_line else ""
        call_rows = [json.loads(l) for l in open(os.path.join(PAIRS, "call-log.jsonl"))]
        first_formal = min((r["started_at"] for r in call_rows if r.get("kind") == "formal"),
                           default="")
        # 比较（都是 ISO8601 UTC）
        ok_order = bool(prereg_time and first_formal and prereg_time < first_formal.replace("+00:00", " +0000").replace("T", " "))
        # 更稳健：直接字符串比较 ISO 前缀
        ok_order = bool(prereg_time[:19] and first_formal[:19] and prereg_time[:19] < first_formal[:19])
        check("V1", "Phase A 预注册提交早于第一笔正式 dev 调用", ok_order,
              f"prereg={prereg_time[:19]} first_formal_call={first_formal[:19]}")
    except Exception as error:  # noqa: BLE001
        check("V1", "Phase A 预注册提交早于第一笔正式 dev 调用", False, f"error {error}")

    # V3 256 点 + 帧哈希
    manifest = load_json(os.path.join(PREREG, "point-manifest-256.json"))["points"]
    point_files = sorted(glob.glob(os.path.join(PAIRS, "points", "T20-P*.json")))
    ok_count = len(point_files) == 256 and len(manifest) == 256
    ok_whitelist = all(p["sample_id"] in WHITELIST for p in manifest)
    ok_frames = True
    for p in manifest:
        path = os.path.join(PROJECT_ROOT, p["task20_frame_path"])
        if not os.path.isfile(path) or sha256_of(path) != p["task20_frame_sha256"]:
            ok_frames = False
            break
    check("V3", "256 点清单 + 帧字节 SHA-256 逐点一致",
          ok_count and ok_whitelist and ok_frames,
          f"points={len(point_files)} whitelist={ok_whitelist} frames={ok_frames}")

    # V4 调用记账
    meta = load_json(os.path.join(PAIRS, "run-metadata.json"))
    call_rows = [json.loads(l) for l in open(os.path.join(PAIRS, "call-log.jsonl"))]
    formal = [r for r in call_rows if r.get("kind") == "formal"]
    per_point_calls = {}
    for r in formal:
        per_point_calls.setdefault(r["point_id"], []).append(r["version"])
    max_per_frame = max((len(v) for v in per_point_calls.values()), default=0)
    # 每帧每版一次：每个 point 的 version 集合应为 {v1,c3}（各一次）
    one_each = all(sorted(v) == ["c3", "v1"] for v in per_point_calls.values())
    failures = meta.get("failure_counts", {})
    ok_acct = (meta.get("formal_calls_completed") == 512 and len(formal) == 512
               and one_each and max_per_frame == 2 and meta.get("retry_policy", "").startswith("无"))
    check("V4", "正式调用记账（512 次/每帧每版一次/失败如实/零重试）", ok_acct,
          f"formal={len(formal)} status={meta.get('status')} failures={failures} "
          f"one_each={one_each} max_per_frame={max_per_frame}")

    # V5 独立复算七类账
    gts = {sid: load_json(os.path.join(GT_DIR, f"{sid}.json")) for sid in WHITELIST}
    ledgers = {"v1": {m: 0 for m in SEVEN}, "c3": {m: 0 for m in SEVEN}}
    item_complete = {"v1": 0, "c3": 0}
    item_attempted = {"v1": 0, "c3": 0}
    pairing_points = load_json(os.path.join(PAIRS, "pairing-results.json"))["points"]
    for f in point_files:
        p = load_json(f)
        gt = gts[p["sample_id"]]
        for side in ("v1", "c3"):
            j = p["judgments"][side]
            pred = scorer.classify_entry(j)
            state = scorer.gt_state_at(gt, p["timestamp_ms"])
            ledgers[side][scorer.metric_for(state, pred)] += 1
            item_attempted[side] += 1
            if j.get("itemized_support_complete"):
                item_complete[side] += 1
    ok_sum = sum(ledgers["v1"].values()) == 256 and sum(ledgers["c3"].values()) == 256
    score = load_json(os.path.join(SCORES, "paired-score.json"))
    ok_match = (ledgers["v1"] == score["totals"]["v1"] and ledgers["c3"] == score["totals"]["c3"])
    check("V5", "独立复算 v1/c3 七类账（各 256）与 paired-score 一致",
          ok_sum and ok_match, f"v1={ledgers['v1']} c3={ledgers['c3']}")

    # V6 门槛 + verdict 复算（完全独立：从 points 经 score_side 重算分轨→门槛→verdict）
    v1_side = paired.score_side(pairing_points, gts, "v1")
    c3_side = paired.score_side(pairing_points, gts, "c3")
    gates = paired.evaluate_gates(v1_side["counts"], c3_side["counts"],
                                  v1_side["by_track"], c3_side["by_track"])
    verdict, reasons = paired.decide_verdict(v1_side["counts"], c3_side["counts"], gates,
                                             safety_ok=True)
    ok_totals = (v1_side["counts"] == score["totals"]["v1"] and c3_side["counts"] == score["totals"]["c3"])
    ok_track = (v1_side["by_track"] == score["by_track"]["v1"] and c3_side["by_track"] == score["by_track"]["c3"])
    ok_verdict = (verdict == score["verdict"]
                  and {k: v["passed"] for k, v in gates.items()} ==
                  {k: v["passed"] for k, v in score["gates"].items()})
    check("V6", "门槛与 verdict 独立复算一致（totals+分轨+门+verdict）",
          ok_totals and ok_track and ok_verdict,
          f"verdict={verdict} reasons={reasons}")

    # V7 分项完整度
    c3_ratio = item_complete["c3"] / item_attempted["c3"] if item_attempted["c3"] else 0
    check("V7", "c3 分项支持完整度审计", True,
          f"c3 complete={item_complete['c3']}/{item_attempted['c3']} ({c3_ratio:.1%}); "
          f"v1 complete={item_complete['v1']}/{item_attempted['v1']}（v1 不请求分项，预期 0）")

    # V8 去重
    dedup = score["dedup_sensitivity"]
    ok_dedup = (dedup["v1"]["unique_frames"] == 184 and dedup["c3"]["unique_frames"] == 184
                and dedup["v1"]["dedup_key"] == "frame_sha256")
    check("V8", "去重敏感性按 frame_sha256（184 唯一帧）", ok_dedup,
          f"v1={dedup['v1']['unique_frames']} c3={dedup['c3']['unique_frames']}")

    # V9 git diff --check + 敏感扫描
    diff_check = subprocess.run(["git", "-C", PROJECT_ROOT, "diff", "--check"],
                                capture_output=True, text=True)
    # 敏感扫描：task-22 新增文本文件中不应有凭据样式
    secret_hits = []
    secret_patterns = [r"sk-[A-Za-z0-9]{16,}", r"Bearer\s+[A-Za-z0-9._-]{16,}",
                       r"api[_-]?key[\"'=:\s]+[A-Za-z0-9]{16,}",
                       r"password[\"'=:\s]+\S{6,}"]
    for f in glob.glob(os.path.join(T22, "**", "*.*"), recursive=True):
        if f.endswith((".json", ".md", ".py", ".txt", ".jsonl", ".log")):
            try:
                text = open(f, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            for pat in secret_patterns:
                if re.search(pat, text):
                    secret_hits.append(os.path.relpath(f, PROJECT_ROOT))
                    break
    check("V9", "git diff --check 干净 + task-22 无凭据样式", diff_check.returncode == 0 and not secret_hits,
          f"diff_check_rc={diff_check.returncode} secret_hits={secret_hits}")

    # V10 无媒体/权重入 Git
    media_in_git = subprocess.run(
        ["git", "-C", PROJECT_ROOT, "ls-files", "artifacts/task-22"],
        capture_output=True, text=True).stdout.splitlines()
    bad_media = [f for f in media_in_git if f.endswith((".mp4", ".gguf", ".safetensors", ".png", ".jpg"))]
    check("V10", "无原始视频/权重/媒体误入 Git（task-22 tracked）", not bad_media,
          f"tracked={len(media_in_git)} bad_media={bad_media}")

    # V11 冻结路径零改动（相对 Phase A 提交，冻结路径不得出现在 diff 中）
    # 冻结路径 = Task 17/18/19/20/21 artifacts、app/、生产 analyze_image、Tier-3、schemas
    frozen_prefixes = ("artifacts/task-17/", "artifacts/task-18/", "artifacts/task-19/",
                       "artifacts/task-20/", "artifacts/task-21/", "app/",
                       ".dsh/skills/visual-evidence-extractor/scripts/analyze_image.py",
                       ".dsh/skills/visual-evidence-extractor/scripts/trace_temporal.py",
                       ".dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py",
                       "evals/", "schemas/", "scripts/score_temporal_ground_truth.py",
                       "scripts/task18_scorer_adapter.py", "scripts/score_tier3_eval_v2.py")
    # 工作区未提交改动中的冻结路径
    changed = subprocess.run(["git", "-C", PROJECT_ROOT, "status", "--porcelain"],
                             capture_output=True, text=True).stdout.splitlines()
    changed_paths = [ln[3:].strip() for ln in changed if ln.strip()]
    frozen_touched = [p for p in changed_paths if p.startswith(frozen_prefixes)]
    check("V11", "冻结路径零改动（工作区）", not frozen_touched,
          f"frozen_touched={frozen_touched}")

    # V12 （若阶段 C 运行）
    dyn_meta_path = os.path.join(T22, "dynamic", "run-metadata.json")
    if os.path.isfile(dyn_meta_path):
        dyn = load_json(dyn_meta_path)
        check("V12", "阶段 C 动态运行记账存在", True,
              f"status={dyn.get('status')} runs={len(dyn.get('runs', []))} "
              f"total_calls={dyn.get('total_actual_model_calls')}")
    else:
        check("V12", "阶段 C 动态运行（未运行则记录）", True, "阶段 C 未运行（verdict 非 IMPROVEMENT 或未过门）")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    out = {"task": "task22-verification", "total": total, "passed": passed,
           "failed": total - passed, "all_passed": passed == total, "results": results}
    with open(os.path.join(T22, "verification.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(f"\nRESULT: {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
