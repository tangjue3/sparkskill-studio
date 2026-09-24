#!/usr/bin/env python3
"""run_task25_smoke.py — Task 25 阶段 0 技术可行性 smoke（SparkSkill Studio 任务 25）

目的（只读 dev 之前的技术核验，不触碰任何 dev 图/dev 点）:
  确认本地 Ollama Qwen 端点是否支持**单次请求有序输入多张图**，能否把三图明确
  标作「前一帧 / 中心帧 / 后一帧」，并仅依据中心帧判断目标存在性。

硬边界:
  - 只用**项目外合成图**（/tmp/task25_smoke，红圆 = 目标「红色圆形」），
    最多 12 次技术 smoke；不用九段 dev 图试错。
  - 合成场景覆盖: 仅中心有目标 / 仅邻帧有目标 / 三帧都有目标 / 三帧都无目标。
  - 关键负例: 目标只在邻帧时，模型不得对中心帧给出肯定存在断言。
  - 若不能稳定区分中心图，或端点不支持有序多图 → FEASIBILITY_BLOCKED，停下。
  - 不改拼图、不改视频端点、不改模型、不做多次调用拼凑。

记录每次: 图字节 SHA-256、请求/响应、提示词版本与 SHA-256、调用时间、失败原因。

退出码: 0 = 可行性通过; 1 = FEASIBILITY_BLOCKED; 2 = 执行器致命错误
"""
import argparse
import base64
import datetime
import hashlib
import importlib.util
import json
import os
import sys
import time
import urllib.request

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
ANALYZE_IMAGE = os.path.join(PROJECT_ROOT, ".dsh", "skills", "visual-evidence-extractor",
                             "scripts", "analyze_image.py")
SMOKE_IMG_DIR = "/tmp/task25_smoke/img"
SMOKE_OUT = os.path.join(PROJECT_ROOT, "artifacts", "task-25", "smoke")
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest"

# 阶段 0 草拟候选提示词（多图有序 + 只判中心帧）；最终版在阶段 A 冻结，
# 此处仅用于技术可行性核验，记录其版本与 SHA-256。
CANDIDATE_TEMPLATE_V0 = """你是一个视觉证据抽取器。本次输入按顺序包含 {image_count} 张图片：{image_roles}。它们来自同一镜头的前后瞬间，其中【中心帧】是你唯一需要判断目标存在性的帧；【前一帧】和【后一帧】（如提供）仅用于提供时间上下文。你只能依据【中心帧】的画面作答，不得把【前一帧】或【后一帧】中出现的目标当作【中心帧】中存在目标的证据。

任务目标: {target_description}
目标属性: {attributes}
禁止推断: {forbidden}（即使画面中有人物，也不得推断其身份、年龄、国籍、关系或意图）

请只返回一个 JSON 对象（不要输出任何其他文字、不要使用 markdown 代码块），格式:
{{
  "object_found": true 或 false,
  "description": "对画面主要内容的简短客观描述",
  "bounding_box": [x1, y1, x2, y2] 或 null（归一化到 0-1；若无法可靠定位必须返回 null，禁止编造）,
  "confidence": 0.0 到 1.0 之间的数字,
  "evidence_text": "支持上述判断的客观视觉依据",
  "abstention_reason": "string 或 null"
}}

关于 object_found=false 的两种情况（必须区分）:
- 如果你清晰看到整个画面、确认该目标确实不存在: object_found=false, abstention_reason=null（这是确定性负面结论）;
- 如果你无法判断（画面模糊、目标被遮挡、超出识别能力等）: object_found=false, 并在 abstention_reason 中说明原因（这是拒答）。

规则:
- 只描述你在【中心帧】中实际看到的内容；
- 禁止猜测，禁止把不确定的内容写成事实。"""


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_of_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_analyze_image():
    spec = importlib.util.spec_from_file_location("analyze_image", ANALYZE_IMAGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_synthetic_images():
    """用 cv2 生成确定性合成图：灰底 + 可选红色圆形（目标=红色圆形）。返回 {name: path}。"""
    import cv2  # noqa: F401  (由调用方保证在含 cv2 的解释器下运行)
    import numpy as np
    os.makedirs(SMOKE_IMG_DIR, exist_ok=True)
    w, h = 640, 360

    def bg():
        img = np.full((h, w, 3), 128, dtype=np.uint8)  # 灰底
        return img

    def with_red_circle():
        img = bg()
        cv2.circle(img, (w // 2, h // 2), 55, (0, 0, 255), -1)  # 红色实心圆
        return img

    out = {}
    for name, maker in (("bg", bg), ("target", with_red_circle)):
        path = os.path.join(SMOKE_IMG_DIR, f"{name}.png")
        cv2.imwrite(path, maker())
        out[name] = path
    return out


def call_ollama_multi(model, prompt, image_paths, timeout):
    """单次请求有序输入多张图（与 analyze_image.call_ollama 同构，唯一差异:
    images 为按序排列的多图 base64 列表）。返回原始响应 body(dict)。"""
    images_b64 = []
    for path in image_paths:
        with open(path, "rb") as handle:
            images_b64.append(base64.b64encode(handle.read()).decode("ascii"))
    payload = {
        "model": model,
        "prompt": prompt,
        "images": images_b64,
        "format": "json",
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.1},
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def image_roles_for(present):
    """present: ['prev','center','next'] 中实际出现的（center 必有）。
    返回 (image_count, image_roles_zh, ordered_paths_key)。"""
    label = {"prev": "【前一帧】", "center": "【中心帧】", "next": "【后一帧】"}
    ordinals = ["第一张", "第二张", "第三张"]
    roles = []
    for i, key in enumerate(present):
        roles.append(f"{ordinals[i]}{label[key]}")
    return len(present), "、".join(roles)


def main():
    parser = argparse.ArgumentParser(description="Task 25 阶段 0 多图接口技术 smoke")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    os.makedirs(SMOKE_OUT, exist_ok=True)
    analyze = load_analyze_image()

    images = make_synthetic_images()
    img_hashes = {name: sha256_of(path) for name, path in images.items()}
    spec = {"task_id": "task25-smoke", "task_type": "object_trace",
            "target": {"description": "红色圆形"},
            "constraints": {"forbidden_inferences": ["identity", "age", "nationality"]},
            "confidence_threshold": 0.5, "requires_visual_input": True}

    def render_prompt(present):
        count, roles = image_roles_for(present)
        return CANDIDATE_TEMPLATE_V0.format(
            image_count=count, image_roles=roles,
            target_description=spec["target"]["description"],
            attributes="（无）", forbidden="identity、age、nationality")

    prompt_hash = sha256_of_text(CANDIDATE_TEMPLATE_V0)

    # 场景定义: (scenario_id, present_keys, [prev,center,next] 用的图名, 期望 center object_found)
    BG, TGT = "bg", "target"
    scenarios = [
        ("A_only_center", ["prev", "center", "next"], [BG, TGT, BG], True,
         "仅中心帧有目标 → 期望中心 object_found=true"),
        ("B_only_prev_neighbor", ["prev", "center", "next"], [TGT, BG, BG], False,
         "仅前一帧有目标 → 期望中心 object_found=false（关键负例：不得把邻帧目标投射到中心）"),
        ("C_only_next_neighbor", ["prev", "center", "next"], [BG, BG, TGT], False,
         "仅后一帧有目标 → 期望中心 object_found=false（关键负例）"),
        ("D_all_three", ["prev", "center", "next"], [TGT, TGT, TGT], True,
         "三帧都有目标 → 期望中心 object_found=true"),
        ("E_none", ["prev", "center", "next"], [BG, BG, BG], False,
         "三帧都无目标 → 期望中心 object_found=false"),
    ]
    # 调用计划（≤12）: A×1, B×2, C×2, D×1, E×1 = 7；关键负例重复以检验稳定性
    plan = [("A_only_center", 1), ("B_only_prev_neighbor", 2),
            ("C_only_next_neighbor", 2), ("D_all_three", 1), ("E_none", 1)]
    scenario_by_id = {s[0]: s for s in scenarios}

    call_log = []
    feasibility = {"endpoint_accepts_multi_image": None, "model_distinguishes_center": None,
                   "negative_neighbor_only_no_center_assertion": None, "notes": []}
    seq = 0
    for scenario_id, repeat in plan:
        _, present, frame_names, expect_found, desc = scenario_by_id[scenario_id]
        for r in range(repeat):
            seq += 1
            ordered_paths = [images[name] for name in frame_names]
            center_path = ordered_paths[present.index("center")]
            prompt = render_prompt(present)
            record = {
                "seq": seq, "scenario": scenario_id, "repeat": r + 1,
                "kind": "technical_smoke", "counts_toward_formal": False,
                "model": args.model, "prompt_version": "candidate-v0-draft",
                "prompt_sha256": prompt_hash,
                "image_order": present,
                "image_hashes": {present[i]: sha256_of(ordered_paths[i]) for i in range(len(present))},
                "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "expect_center_object_found": expect_found, "scenario_desc": desc,
            }
            started = time.time()
            try:
                body = call_ollama_multi(args.model, prompt, ordered_paths, args.timeout)
            except Exception as error:  # noqa: BLE001
                record.update({"outcome": "call_failed", "error_type": type(error).__name__,
                               "latency_s": round(time.time() - started, 3)})
                call_log.append(record)
                feasibility["endpoint_accepts_multi_image"] = False
                feasibility["notes"].append(f"{scenario_id}: call_failed {type(error).__name__}")
                continue
            latency = round(time.time() - started, 3)
            raw_text = body.get("response", "")
            record["latency_s"] = latency
            record["raw_response_sha256"] = sha256_of_text(raw_text)
            try:
                raw = json.loads(raw_text)
            except (json.JSONDecodeError, TypeError):
                record.update({"outcome": "invalid_json", "raw_prefix": raw_text[:200]})
                call_log.append(record)
                continue
            try:
                evidence = analyze.coerce_evidence(raw, spec, center_path, args.model)
                record.update({
                    "outcome": "ok",
                    "object_found": evidence["object_found"],
                    "confidence": evidence["confidence"],
                    "abstention_reason": evidence["abstention_reason"],
                    "description": evidence["description"][:160],
                    "center_object_found_matches_expectation":
                        evidence["object_found"] == expect_found,
                })
            except ValueError as error:
                record.update({"outcome": "contract_rejected", "error": str(error)})
            call_log.append(record)
            print(f"[smoke {seq}] {scenario_id} r{r+1}: {record['outcome']} "
                  f"object_found={record.get('object_found')} (expect {expect_found}) "
                  f"latency={latency}s", flush=True)

    # ------------------------------------------------ 可行性判定
    ok_calls = [c for c in call_log if c["outcome"] == "ok"]
    endpoint_ok = any(c["outcome"] in ("ok", "invalid_json", "contract_rejected") for c in call_log) \
        and not any(c["outcome"] == "call_failed" for c in call_log)
    feasibility["endpoint_accepts_multi_image"] = endpoint_ok

    def found(scn):
        return [c.get("object_found") for c in ok_calls if c["scenario"] == scn]

    # 模型能区分中心: A/D 判 true、E 判 false、B/C 判 false（关键）
    a = found("A_only_center"); b = found("B_only_prev_neighbor")
    c = found("C_only_next_neighbor"); d = found("D_all_three"); e = found("E_none")
    center_positive_ok = a and all(v is True for v in a) and d and all(v is True for v in d)
    center_negative_ok = e and all(v is False for v in e)
    neighbor_negative_ok = (b and all(v is False for v in b)
                            and c and all(v is False for v in c))
    feasibility["model_distinguishes_center"] = bool(center_positive_ok and center_negative_ok)
    feasibility["negative_neighbor_only_no_center_assertion"] = bool(neighbor_negative_ok)
    feasibility["scenario_object_found"] = {"A_only_center": a, "B_only_prev_neighbor": b,
                                            "C_only_next_neighbor": c, "D_all_three": d,
                                            "E_none": e}

    feasible = bool(endpoint_ok and feasibility["model_distinguishes_center"]
                    and feasibility["negative_neighbor_only_no_center_assertion"])
    feasibility["verdict"] = "FEASIBLE" if feasible else "FEASIBILITY_BLOCKED"

    report = {
        "task": "task25-phase0-technical-smoke",
        "model": args.model,
        "purpose": "确认单次请求有序多图 + 模型仅依据中心帧判断（不把邻帧目标投射到中心）",
        "synthetic_images_dir": SMOKE_IMG_DIR,
        "synthetic_images_note": "项目外合成图（红圆=目标『红色圆形』），非 dev 媒体；脚本确定性可再生",
        "synthetic_image_hashes": img_hashes,
        "target_query": spec["target"]["description"],
        "candidate_template_sha256": prompt_hash,
        "candidate_template_version": "candidate-v0-draft（阶段 0 草拟；阶段 A 冻结最终版）",
        "total_smoke_calls": len(call_log),
        "smoke_call_budget": 12,
        "feasibility": feasibility,
        "smoke_calls": call_log,
        "known_limitations": [
            "技术 smoke 用项目外合成图，只验证端点与中心帧区分机制，不代表 dev 质量",
            "合成目标（红圆）比真实 dev 目标简单；dev 表现需在阶段 B/C 测量",
        ],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    with open(os.path.join(SMOKE_OUT, "smoke-report.json"), "w", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with open(os.path.join(SMOKE_OUT, "call-log.jsonl"), "w", encoding="utf-8") as handle:
        for record in call_log:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(json.dumps({"feasibility_verdict": feasibility["verdict"],
                      "endpoint_accepts_multi_image": endpoint_ok,
                      "model_distinguishes_center": feasibility["model_distinguishes_center"],
                      "neighbor_only_no_center_assertion":
                          feasibility["negative_neighbor_only_no_center_assertion"],
                      "scenario_object_found": feasibility["scenario_object_found"],
                      "total_smoke_calls": len(call_log)}, ensure_ascii=False, indent=2))
    return 0 if feasible else 1


if __name__ == "__main__":
    sys.exit(main())
