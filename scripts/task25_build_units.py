#!/usr/bin/env python3
"""task25_build_units.py — Task 25 阶段 A：184 唯一中心帧单元清单 + 邻帧抽取（确定性，零模型调用）

输入（全部冻结/只读）:
  - artifacts/task-22/preregistration/point-manifest-256.json  （Task 22 已存档 256 点）
  - artifacts/task-22/pairs/points/T20-PXXXX.json              （Task 22 归档 v1/c3 判断，仅取 v1 作历史参考）
  - artifacts/task-19/ground-truth/<sample>.json               （Task 17/19B 冻结 GT）
  - artifacts/task-20/frames/<sample>/*.png                    （冻结中心帧农场）
  - 仓库外 dev 包视频（经 ingestion/media 符号链接，只读）

步骤:
  1. 按 (sample_id, frame_sha256, target_query) 去重 256 -> 184 唯一中心帧。
  2. 核验: 256->184; 每单元中心帧哈希 == 冻结农场哈希; 跨臂 GT 一致（同帧同时戳 GT 相同）。
  3. 每单元记录: 样本/中心时间戳/目标查询/轨道/媒体 SHA-256/来源 point_id+arm/GT 状态/
     代表性历史类别（point_id 最小的 v1 结论，披露其他 arm 结论）。
  4. 邻帧: 中心时间戳 ±500ms，按 extract_frames.py 同一解码路径顺序解码；
     越界侧标缺席（不复制中心帧）；记录邻帧路径/哈希/缺席原因。
  5. 校验解码路径可复现冻结中心帧（抽样比对，证明同一 decode+encode）。
  6. 确定性抽取首批 48 单元（固定种子 + 分层覆盖 9 样本/2 轨/correct-error-uncertain）。

退出码: 0 = 成功; 1 = INVALID_INPUT（去重/哈希/GT 不一致）; 2 = 致命错误
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import random
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
T22_PREREG = os.path.join(PROJECT_ROOT, "artifacts", "task-22", "preregistration")
T22_POINTS = os.path.join(PROJECT_ROOT, "artifacts", "task-22", "pairs", "points")
GT_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ground-truth")
MEDIA_LINK_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-19", "ingestion", "media")
NEIGHBOR_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-25", "frames")
OUT_DIR = os.path.join(PROJECT_ROOT, "artifacts", "task-25", "preregistration")

GENERATED = ["AI01", "AI02", "AI03", "AI04", "AI05", "AI06"]
LICENSED = ["WEB01", "WEB02", "WEB03"]
WHITELIST = set(GENERATED + LICENSED)
NEIGHBOR_OFFSET_MS = 500.0
FIXED_SEED = 20250923  # 冻结抽样种子

# 视频元数据（阶段 0 只读实测，fps/frame_count/duration_ms）
VIDEO_META = {
    "AI01": {"fps": 24.0, "frame_count": 192, "duration_ms": 8000.0},
    "AI02": {"fps": 24.0, "frame_count": 243, "duration_ms": 10125.0},
    "AI03": {"fps": 24.0, "frame_count": 243, "duration_ms": 10125.0},
    "AI04": {"fps": 24.0, "frame_count": 243, "duration_ms": 10125.0},
    "AI05": {"fps": 24.0, "frame_count": 192, "duration_ms": 8000.0},
    "AI06": {"fps": 24.0, "frame_count": 243, "duration_ms": 10125.0},
    "WEB01": {"fps": 29.97, "frame_count": 556, "duration_ms": 18551.9},
    "WEB02": {"fps": 29.97, "frame_count": 307, "duration_ms": 10243.6},
    "WEB03": {"fps": 25.0, "frame_count": 438, "duration_ms": 17520.0},
}


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def dump_json(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


# ---------------------------------------------------------------- 七类（与冻结评分器同义）
GT_DETERMINATE = ("confirmed", "not_found")


def classify_entry(entry):
    if entry.get("frame_status") != "analyzed":
        return "failed"
    if entry.get("object_found") is True:
        return "confirmed" if entry.get("evidence_sufficient") else "low_confidence"
    reason = entry.get("abstention_reason")
    if isinstance(reason, str) and reason.strip():
        return "abstained"
    return "not_found"


def gt_state_at(gt, timestamp_ms):
    for segment in gt["segments"]:
        if segment["start_ms"] <= timestamp_ms < segment["end_ms"]:
            return segment["state"]
        if (timestamp_ms == segment["end_ms"]
                and segment["end_ms"] == gt["media_duration_ms"]):
            return segment["state"]
    return None


def metric_for(gt_state, pred_class):
    decisive = ("confirmed", "not_found")
    non_decisive = ("abstained", "low_confidence")
    if gt_state in GT_DETERMINATE:
        if pred_class in decisive:
            return "correct_decisive" if pred_class == gt_state else "incorrect_decisive"
        if pred_class in non_decisive:
            return "abstention_on_determinate"
        return "failed_on_determinate"
    if pred_class in non_decisive:
        return "appropriate_abstention"
    if pred_class in decisive:
        return "overclaim_on_uncertain"
    return "failed_on_uncertain"


# ---------------------------------------------------------------- 邻帧解码（extract_frames 同路径）
def frame_number_for(ts_ms, fps, frame_count):
    return min(frame_count - 1, max(0, int(round(ts_ms / 1000.0 * fps))))


def decode_specific_frames(video_path, sample_id, wanted):
    """wanted: dict {role: (frame_number, ts_ms)}。按 extract_frames.py 同一顺序解码+imwrite。
    返回 {role: {"frame_path","frame_number","timestamp_ms","frame_sha256"}}。"""
    import cv2
    import numpy as np  # noqa: F401
    out_dir = os.path.join(NEIGHBOR_DIR, sample_id)
    os.makedirs(out_dir, exist_ok=True)
    targets = {role: fn for role, (fn, _ts) in wanted.items()}
    order = sorted(targets, key=lambda r: targets[r])
    target_fn_sorted = sorted(set(targets.values()))
    result = {}
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"无法打开视频: {video_path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        pos = 0
        next_i = 0
        while next_i < len(target_fn_sorted):
            ok, frame = cap.read()
            if not ok:
                break
            if pos == target_fn_sorted[next_i]:
                ts_ms = round(pos / fps * 1000.0, 3)
                roles_here = [r for r in order if targets[r] == pos]
                for role in roles_here:
                    prefix = f"{sample_id}_{role}"
                    fname = f"{prefix}_f{pos:05d}_t{int(round(ts_ms)):08d}ms.png"
                    fpath = os.path.join(out_dir, fname)
                    if not cv2.imwrite(fpath, frame):
                        raise RuntimeError(f"邻帧保存失败: {fpath}")
                    result[role] = {
                        "role": role, "frame_number": pos, "timestamp_ms": ts_ms,
                        "frame_path": os.path.relpath(fpath, PROJECT_ROOT),
                        "frame_sha256": sha256_of(fpath),
                    }
                next_i += 1
            pos += 1
    finally:
        cap.release()
    return result


def main():
    parser = argparse.ArgumentParser(description="Task 25 阶段 A 单元清单与邻帧抽取")
    parser.add_argument("--skip-neighbors", action="store_true",
                        help="只做去重/GT/历史分类/ breakdown，不解码邻帧（调试用）")
    args = parser.parse_args()

    manifest = load_json(os.path.join(T22_PREREG, "point-manifest-256.json"))
    points256 = manifest["points"]
    problems = []

    # ---- 1. 去重 256 -> 184 by (sample_id, frame_sha256, target_query)
    groups = {}
    for p in points256:
        if p["sample_id"] not in WHITELIST:
            problems.append(f"point {p['point_id']} 非白名单样本 {p['sample_id']}")
        key = (p["sample_id"], p["task20_frame_sha256"], p["target_query"])
        groups.setdefault(key, []).append(p)

    # ---- 载入 GT
    gts = {sid: load_json(os.path.join(GT_DIR, f"{sid}.json")) for sid in WHITELIST}

    # ---- 载入 Task 22 归档 v1 判断（历史参考）
    archived_v1 = {}
    for p in points256:
        pp = os.path.join(T22_POINTS, f"{p['point_id']}.json")
        if os.path.isfile(pp):
            doc = load_json(pp)
            j = doc.get("judgments", {}).get("v1")
            if j is not None:
                archived_v1[p["point_id"]] = j

    # ---- 2+3. 每单元信息 + 核验
    units = []
    for key, members in groups.items():
        sample_id, frame_sha256, target_query = key
        members_sorted = sorted(members, key=lambda m: m["point_id"])
        rep = members_sorted[0]  # point_id 最小 = 代表
        # 中心帧哈希核验
        center_abs = os.path.join(PROJECT_ROOT, rep["task20_frame_path"])
        if not os.path.isfile(center_abs):
            problems.append(f"单元 {sample_id} 中心帧缺失: {rep['task20_frame_path']}")
            center_hash_ok = False
        else:
            center_hash_ok = sha256_of(center_abs) == frame_sha256
            if not center_hash_ok:
                problems.append(f"单元 {sample_id} 中心帧哈希不匹配: {rep['task20_frame_path']}")
        # 跨臂 GT 一致性（同帧应同时戳 -> 同 GT）
        gt_states = {gt_state_at(gts[sample_id], m["timestamp_ms"]) for m in members_sorted}
        if len(gt_states) != 1:
            problems.append(f"单元 {sample_id} 跨点 GT 不一致: {gt_states} "
                            f"(points {[m['point_id'] for m in members_sorted]})")
        gt_state = gt_state_at(gts[sample_id], rep["timestamp_ms"])
        # 代表性历史类别（point_id 最小 v1 结论）+ 披露其他 arm
        rep_hist_class = None
        rep_metric = None
        if rep["point_id"] in archived_v1:
            rep_hist_class = classify_entry(archived_v1[rep["point_id"]])
            rep_metric = metric_for(gt_state, rep_hist_class)
        # stratum: uncertain / error / correct / other
        if gt_state == "uncertain":
            stratum = "uncertain"
        elif rep_metric == "correct_decisive":
            stratum = "correct"
        elif rep_metric == "incorrect_decisive":
            stratum = "error"
        else:
            stratum = "other"
        other_arm_classes = []
        for m in members_sorted[1:]:
            if m["point_id"] in archived_v1:
                other_arm_classes.append({
                    "point_id": m["point_id"], "arm": m["arm"],
                    "v1_class": classify_entry(archived_v1[m["point_id"]]),
                    "metric": metric_for(gt_state, classify_entry(archived_v1[m["point_id"]])),
                })
        units.append({
            "sample_id": sample_id,
            "center_timestamp_ms": rep["timestamp_ms"],
            "target_query": target_query,
            "track": rep["track"],
            "media_sha256": rep["media_sha256"],
            "center_frame_path": rep["task20_frame_path"],
            "center_frame_sha256": frame_sha256,
            "center_hash_ok": center_hash_ok,
            "gt_state": gt_state,
            "source_point_ids": [m["point_id"] for m in members_sorted],
            "source_arms": sorted({m["arm"] for m in members_sorted}),
            "representative_point_id": rep["point_id"],
            "representative_arm": rep["arm"],
            "historical_v1_class": rep_hist_class,
            "historical_v1_metric": rep_metric,
            "stratum": stratum,
            "other_arm_historical_classes": other_arm_classes,
        })

    # 规范化单元 ID（样本字典序 -> 中心时间戳升序）
    units.sort(key=lambda u: (u["sample_id"], u["center_timestamp_ms"]))
    for i, u in enumerate(units, 1):
        u["unit_id"] = f"T25-U{i:04d}"

    # ---- breakdown
    def breakdown():
        by_sample = {}
        by_track = {"generated": 0, "licensed-public": 0}
        by_stratum = {"correct": 0, "error": 0, "uncertain": 0, "other": 0}
        by_gt = {"confirmed": 0, "not_found": 0, "uncertain": 0, None: 0}
        for u in units:
            by_sample[u["sample_id"]] = by_sample.get(u["sample_id"], 0) + 1
            by_track[u["track"]] += 1
            by_stratum[u["stratum"]] += 1
            by_gt[u["gt_state"]] = by_gt.get(u["gt_state"], 0) + 1
        return {"total_units": len(units), "by_sample": by_sample,
                "by_track": by_track, "by_stratum": by_stratum,
                "by_gt_state": {str(k): v for k, v in by_gt.items()}}
    bd = breakdown()

    # ---- 4. 邻帧抽取
    neighbor_summary = {"offset_ms": NEIGHBOR_OFFSET_MS, "three_image_units": 0,
                        "two_image_units": 0, "absent_prev": 0, "absent_next": 0,
                        "decode_path_reproduces_center_probe": None}
    if not args.skip_neighbors:
        # 按样本收集所需邻帧帧号
        per_sample_wanted = {}
        for u in units:
            sid = u["sample_id"]
            meta = VIDEO_META[sid]
            fps, fc, dur = meta["fps"], meta["frame_count"], meta["duration_ms"]
            cts = u["center_timestamp_ms"]
            wanted = {}
            prev_ts = cts - NEIGHBOR_OFFSET_MS
            next_ts = cts + NEIGHBOR_OFFSET_MS
            u["neighbors"] = {}
            if prev_ts < 0:
                u["neighbors"]["prev"] = {"present": False,
                                          "absent_reason": "timestamp_before_start",
                                          "requested_timestamp_ms": round(prev_ts, 3)}
                neighbor_summary["absent_prev"] += 1
            else:
                wanted["prev"] = (frame_number_for(prev_ts, fps, fc), prev_ts)
            if next_ts > dur:
                u["neighbors"]["next"] = {"present": False,
                                          "absent_reason": "timestamp_after_end",
                                          "requested_timestamp_ms": round(next_ts, 3)}
                neighbor_summary["absent_next"] += 1
            else:
                wanted["next"] = (frame_number_for(next_ts, fps, fc), next_ts)
            if wanted:
                per_sample_wanted.setdefault(sid, []).append((u, wanted))

        # 每样本一次顺序解码（合并所有需要的帧号）
        for sid, items in per_sample_wanted.items():
            video_path = os.path.join(MEDIA_LINK_DIR, f"{sid}.mp4")
            all_wanted = {}
            for u, wanted in items:
                for role, (fn, ts) in wanted.items():
                    all_wanted[role if False else f"{u['unit_id']}:{role}"] = (fn, ts, u, role)
            # 合并为帧号->roles 映射，单次解码
            fn_to_roles = {}
            for token, (fn, ts, u, role) in all_wanted.items():
                fn_to_roles.setdefault(fn, []).append((u, role, ts))
            wanted_by_fn = {fn: (fn, roles[0][2]) for fn, roles in fn_to_roles.items()}
            # 用 decode_specific_frames 需要 {role:(fn,ts)}；这里改为自定义合并解码
            decoded = decode_merged(video_path, sid, fn_to_roles)
            for fn, roles in fn_to_roles.items():
                info = decoded.get(fn)
                for (u, role, ts) in roles:
                    if info is None:
                        u["neighbors"][role] = {"present": False,
                                                "absent_reason": "decode_failed",
                                                "requested_timestamp_ms": round(ts, 3)}
                        if role == "prev":
                            neighbor_summary["absent_prev"] += 1
                        else:
                            neighbor_summary["absent_next"] += 1
                    else:
                        u["neighbors"][role] = {
                            "present": True, "frame_number": info["frame_number"],
                            "timestamp_ms": info["timestamp_ms"],
                            "frame_path": info["frame_path"],
                            "frame_sha256": info["frame_sha256"],
                            "requested_timestamp_ms": round(ts, 3),
                            "role": role,
                        }
        for u in units:
            nb = u.get("neighbors", {})
            if nb.get("prev", {}).get("present") and nb.get("next", {}).get("present"):
                neighbor_summary["three_image_units"] += 1
            else:
                neighbor_summary["two_image_units"] += 1

        # 解码路径可复现性探针：抽 3 个中心帧重解码比对
        probe = verify_decode_reproduces_center(units)
        neighbor_summary["decode_path_reproduces_center_probe"] = probe
        # 探针不一致不构成 INVALID_INPUT（中心帧直接用冻结 PNG，非重解码）；
        # 但如实披露：说明邻帧解码路径与冻结中心帧的 decode+encode 是否逐字节一致。
        if not probe["all_match"]:
            neighbor_summary["decode_path_caveat"] = (
                "重解码中心帧与冻结 PNG 不完全逐字节一致：邻帧为同一 cv2 顺序解码+imwrite 产物，"
                "但未与冻结中心字节完全对齐；中心帧仍逐字节使用冻结 PNG（center_hash_ok），"
                "邻帧无需匹配任何冻结哈希，仅记录其自身 SHA-256。")

    # ---- 6. 48 确定性抽样
    sample48 = stratified_sample_48(units)

    manifest_out = {
        "schema_version": "1.0.0",
        "task": "task25-unit-manifest-184",
        "note": "Task 25 阶段 A：184 唯一中心帧（按 (sample_id, frame_sha256, target_query) 去重 "
                "Task 22 冻结 256 点）。邻帧 = 中心时间戳 ±500ms，extract_frames 同一解码路径。",
        "source_256_manifest": "artifacts/task-22/preregistration/point-manifest-256.json",
        "dedup_key": "(sample_id, frame_sha256, target_query)",
        "total_source_points": len(points256),
        "total_units": len(units),
        "dedup_256_to_184_ok": len(units) == 184 and len(points256) == 256,
        "whitelist": sorted(WHITELIST),
        "breakdown": bd,
        "neighbor_summary": neighbor_summary,
        "sampling": {
            "seed": FIXED_SEED,
            "algorithm": "分层确定性抽样：按样本比例（largest-remainder，每样本下限 3）分配 48 名额；"
                         "样本内按层 round-robin（uncertain→error→correct→other 保覆盖），"
                         "每层内以固定种子洗牌；不足按预算从剩余单元 canonical 序补位",
            "first_batch_count": len(sample48),
        },
        "invalid_input": bool(problems),
        "problems": problems,
        "units": units,
        "first_batch_48_unit_ids": [u["unit_id"] for u in sample48],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    dump_json(os.path.join(OUT_DIR, "unit-manifest-184.json"), manifest_out)

    # 单独存 48 抽样（含分层信息）
    sample48_doc = {
        "schema_version": "1.0.0",
        "task": "task25-first-batch-48",
        "seed": FIXED_SEED,
        "count": len(sample48),
        "coverage": {
            "samples": sorted({u["sample_id"] for u in sample48}),
            "tracks": sorted({u["track"] for u in sample48}),
            "strata": sorted({u["stratum"] for u in sample48}),
        },
        "units": [{
            "unit_id": u["unit_id"], "sample_id": u["sample_id"],
            "center_timestamp_ms": u["center_timestamp_ms"], "track": u["track"],
            "gt_state": u["gt_state"], "stratum": u["stratum"],
            "historical_v1_class": u["historical_v1_class"],
            "representative_point_id": u["representative_point_id"],
            "source_point_ids": u["source_point_ids"],
            "three_image": bool(u.get("neighbors", {}).get("prev", {}).get("present")
                                and u.get("neighbors", {}).get("next", {}).get("present")),
        } for u in sample48],
    }
    dump_json(os.path.join(OUT_DIR, "first-batch-48.json"), sample48_doc)

    print(json.dumps({
        "total_source_points": len(points256),
        "total_units": len(units),
        "dedup_ok": manifest_out["dedup_256_to_184_ok"],
        "breakdown": bd,
        "neighbor_summary": neighbor_summary,
        "first_batch_48_count": len(sample48),
        "first_batch_coverage": sample48_doc["coverage"],
        "invalid_input": bool(problems),
        "problems": problems[:10],
    }, ensure_ascii=False, indent=2))
    return 1 if problems else 0


def decode_merged(video_path, sample_id, fn_to_roles):
    """一次顺序解码，抓取 fn_to_roles 中所有目标帧号，返回 {frame_number: info}。"""
    import cv2
    out_dir = os.path.join(NEIGHBOR_DIR, sample_id)
    os.makedirs(out_dir, exist_ok=True)
    target_fns = sorted(fn_to_roles.keys())
    result = {}
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(f"无法打开视频: {video_path}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        pos = 0
        ni = 0
        while ni < len(target_fns):
            ok, frame = cap.read()
            if not ok:
                break
            if pos == target_fns[ni]:
                ts_ms = round(pos / fps * 1000.0, 3)
                roles = fn_to_roles[pos]
                # 同一帧号可能被多个单元/角色共用；用第一个角色命名，其余记录同哈希
                first_role = roles[0][1]
                prefix = f"{sample_id}_{first_role}"
                fname = f"{prefix}_f{pos:05d}_t{int(round(ts_ms)):08d}ms.png"
                fpath = os.path.join(out_dir, fname)
                if not cv2.imwrite(fpath, frame):
                    raise RuntimeError(f"邻帧保存失败: {fpath}")
                result[pos] = {
                    "frame_number": pos, "timestamp_ms": ts_ms,
                    "frame_path": os.path.relpath(fpath, PROJECT_ROOT),
                    "frame_sha256": sha256_of(fpath),
                }
                ni += 1
            pos += 1
    finally:
        cap.release()
    return result


def verify_decode_reproduces_center(units, probe_n=3):
    """抽 probe_n 个中心帧：用中心帧帧号重新解码，与冻结中心 PNG 逐字节比对，
    证明邻帧解码路径与冻结中心帧同一 decode+encode。"""
    import cv2
    probes = []
    # 覆盖不同分辨率与轨道的三个样本：AI01(1728x960,generated)、WEB01(3840x2160,licensed)、WEB03(1920x1080,licensed)
    probe_samples = ["AI01", "WEB01", "WEB03"]
    by_sample_units = {}
    for u in units:
        by_sample_units.setdefault(u["sample_id"], []).append(u)
    chosen = []
    for sid in probe_samples:
        cell = sorted(by_sample_units.get(sid, []), key=lambda x: x["center_timestamp_ms"])
        if cell:
            # 取一个非零时间戳的中段帧（若该样本有），证明非平凡帧也可复现
            mid = next((u for u in cell if u["center_timestamp_ms"] > 1000), cell[0])
            chosen.append(mid)
    for u in chosen:
        sid = u["sample_id"]
        meta = VIDEO_META[sid]
        center_fn = frame_number_for(u["center_timestamp_ms"], meta["fps"], meta["frame_count"])
        video_path = os.path.join(MEDIA_LINK_DIR, f"{sid}.mp4")
        cap = cv2.VideoCapture(video_path)
        redecoded_hash = None
        if cap.isOpened():
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            pos = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if pos == center_fn:
                    tmp = os.path.join("/tmp", f"task25_probe_{sid}.png")
                    cv2.imwrite(tmp, frame)
                    redecoded_hash = sha256_of(tmp)
                    os.remove(tmp)
                    break
                pos += 1
        cap.release()
        frozen_hash = u["center_frame_sha256"]
        probes.append({"sample_id": sid, "center_frame": u["center_frame_path"],
                       "center_frame_number": center_fn,
                       "frozen_sha256": frozen_hash, "redecoded_sha256": redecoded_hash,
                       "match": redecoded_hash == frozen_hash})
    return {"probe_count": len(probes),
            "all_match": all(p["match"] for p in probes), "probes": probes}


def stratified_sample_48(units):
    rng = random.Random(FIXED_SEED)
    by_sample = {}
    for u in units:
        by_sample.setdefault(u["sample_id"], []).append(u)
    samples = sorted(by_sample)
    total = len(units)
    target = 48
    floor = 3
    # 比例分配（largest remainder），每样本下限 floor
    exact = {s: len(by_sample[s]) / total * target for s in samples}
    alloc = {s: max(floor, int(exact[s])) for s in samples}
    # 修正总和到 target
    def alloc_sum():
        return sum(alloc.values())
    # 若超目标，从超出 floor 最多的样本减
    while alloc_sum() > target:
        # 选 alloc>floor 且 (alloc-exact) 最大者减 1
        candidates = [s for s in samples if alloc[s] > floor]
        if not candidates:
            break
        s = max(candidates, key=lambda x: (alloc[x] - exact[x], x))
        alloc[s] -= 1
    # 若不足目标，按 remainder 从大到小补
    while alloc_sum() < target:
        remainders = sorted(samples, key=lambda s: (-(exact[s] - int(exact[s])), s))
        progressed = False
        for s in remainders:
            if alloc[s] < len(by_sample[s]):
                alloc[s] += 1
                progressed = True
                if alloc_sum() >= target:
                    break
        if not progressed:
            break
    strata_order = ["uncertain", "error", "correct", "other"]
    picked = []
    picked_ids = set()
    for s in samples:
        cell = list(by_sample[s])
        by_strat = {st: [u for u in cell if u["stratum"] == st] for st in strata_order}
        for st in by_strat:
            rng.shuffle(by_strat[st])
        chosen = []
        # 第一遍：每层取 1（保覆盖）
        for st in strata_order:
            if by_strat[st] and len(chosen) < alloc[s]:
                chosen.append(by_strat[st].pop(0))
        # 填满配额：按层优先级循环
        idx = 0
        guard = 0
        while len(chosen) < alloc[s] and guard < 10000:
            guard += 1
            st = strata_order[idx % len(strata_order)]
            if by_strat[st]:
                chosen.append(by_strat[st].pop(0))
            idx += 1
            if all(not by_strat[x] for x in strata_order):
                break
        for u in chosen:
            picked.append(u)
            picked_ids.add(u["unit_id"])
    # 补位规则（预先声明）：若不足 48，从剩余单元 canonical 序补
    if len(picked) < target:
        remaining = [u for u in units if u["unit_id"] not in picked_ids]
        remaining.sort(key=lambda u: u["unit_id"])
        for u in remaining:
            if len(picked) >= target:
                break
            picked.append(u)
            picked_ids.add(u["unit_id"])
    picked.sort(key=lambda u: (u["sample_id"], u["center_timestamp_ms"]))
    return picked[:target]


if __name__ == "__main__":
    sys.exit(main())
