#!/usr/bin/env python3
"""visual-evidence-extractor · 最小图片版本（SparkSkill Studio）

接收合法 VisualTaskSpec + 一个本地图片路径，调用 DGX Spark 本地 Ollama Qwen Vision
模型获取结构化视觉证据，校验后输出证据 JSON。

设计红线:
  - 不推断人物身份、年龄、国籍、关系或意图（任务规格中的 forbidden_inferences 会注入提示）；
  - 无法确认时 object_found=false 且必须给出 abstention_reason；
  - 不伪造 bounding_box（模型返回 null 就保持 null）；
  - 像素坐标受控归一化（任务 06）：仅当四元数值、全部 >1、x1<x2/y1<y2、
    不越界、可读真实帧宽高时才归一化，否则置 null 并记录 warning，不重跑模型凑结果；
  - 只使用 Python 标准库，不安装任何依赖。

用法:
    python3 analyze_image.py --task-spec <spec.json> --image <path.png> \
        [--output <evidence.json>] [--model <ollama-model>] [--timeout 300]
"""
import argparse
import base64
import datetime
import json
import sys
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest"
EVIDENCE_SCHEMA_VERSION = "1.0.0"

PROMPT_TEMPLATE = """你是一个视觉证据抽取器。请仔细观察这张图片，完成一项对象存在性判断。

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
- 只描述你在图片中实际看到的内容；
- 禁止猜测，禁止把不确定的内容写成事实。"""


def build_prompt(spec):
    target = spec.get("target", {})
    attributes = target.get("attributes") or []
    forbidden = spec.get("constraints", {}).get("forbidden_inferences") or []
    return PROMPT_TEMPLATE.format(
        target_description=target.get("description", ""),
        attributes="、".join(attributes) if attributes else "（无）",
        forbidden="、".join(forbidden) if forbidden else "（无）",
    )


def call_ollama(model, prompt, image_path, timeout):
    with open(image_path, "rb") as handle:
        image_b64 = base64.b64encode(handle.read()).decode("ascii")
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [image_b64],
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
        body = json.loads(response.read().decode("utf-8"))
    return body


def read_image_size(path):
    """用纯标准库读取 PNG/JPEG 图片宽高（不依赖 cv2/PIL，不安装任何东西）。

    返回 (width, height)；无法识别格式或读取失败返回 None。
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(32)
            if len(head) < 24:
                return None
            if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                width = int.from_bytes(head[16:20], "big")
                height = int.from_bytes(head[20:24], "big")
                return (width, height) if width > 0 and height > 0 else None
            if head[:2] == b"\xff\xd8":  # JPEG：顺序扫描标记段找 SOF
                handle.seek(2)
                while True:
                    marker = handle.read(2)
                    if len(marker) < 2 or marker[0] != 0xFF:
                        return None
                    code = marker[1]
                    if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
                        continue
                    length_bytes = handle.read(2)
                    if len(length_bytes) < 2:
                        return None
                    seg_len = int.from_bytes(length_bytes, "big")
                    if code in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                                0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        seg = handle.read(5)
                        if len(seg) < 5:
                            return None
                        height = int.from_bytes(seg[1:3], "big")
                        width = int.from_bytes(seg[3:5], "big")
                        return (width, height) if width > 0 and height > 0 else None
                    handle.seek(seg_len - 2, 1)
    except OSError:
        return None
    return None


def normalize_bounding_box(box, width, height):
    """像素坐标受控归一化（任务 06）。

    仅当同时满足以下全部条件时才执行归一化：
      1. 四个坐标都是数值；
      2. 坐标全部大于 1（明确识别为像素坐标，而非 0-1 归一化；混合坐标拒绝）；
      3. x1 < x2 且 y1 < y2；
      4. 坐标全部位于实际图片宽高范围内；
      5. 能读取该关键帧的真实宽高。
    否则不归一化：bounding_box 置 null、记录 warning、保留原始值摘要，不重跑模型。

    返回 dict：bounding_box / bounding_box_source_format（normalized|pixel|null）/
    bounding_box_normalization_applied / frame_width / frame_height / warning。
    """
    result = {
        "bounding_box": None,
        "bounding_box_source_format": None,
        "bounding_box_normalization_applied": False,
        "frame_width": width,
        "frame_height": height,
        "warning": None,
    }
    if box is None:
        return result
    if (not isinstance(box, list) or len(box) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in box)):
        result["warning"] = (
            f"模型返回的 bounding_box 不是 [x1,y1,x2,y2] 四元数值：{box!r}，已置 null（不归一化）")
        return result
    x1, y1, x2, y2 = (float(v) for v in box)
    raw_summary = f"[{x1:g}, {y1:g}, {x2:g}, {y2:g}]"
    if all(0.0 <= v <= 1.0 for v in (x1, y1, x2, y2)):
        result["bounding_box"] = [x1, y1, x2, y2]
        result["bounding_box_source_format"] = "normalized"
        return result
    if any(v < 0 for v in (x1, y1, x2, y2)):
        result["warning"] = (
            f"模型返回的 bounding_box 含负坐标 {raw_summary}，非法，已置 null（不归一化）")
        return result
    in_unit = sum(1 for v in (x1, y1, x2, y2) if v <= 1.0)
    if in_unit:
        result["warning"] = (
            f"模型返回的 bounding_box 为混合坐标（部分 ≤1、部分 >1）{raw_summary}，"
            "无法可靠判定格式，已置 null（不归一化）")
        return result
    if not width or not height:
        result["warning"] = (
            f"模型返回的 bounding_box 疑似像素坐标 {raw_summary}，但无法读取关键帧真实宽高，"
            "已置 null（不归一化）")
        return result
    if not (x1 < x2 and y1 < y2):
        result["warning"] = (
            f"模型返回的 bounding_box 坐标顺序错误（x1<x2、y1<y2 不满足）{raw_summary}，"
            "已置 null（不归一化）")
        return result
    if x2 > width or y2 > height:
        result["warning"] = (
            f"模型返回的 bounding_box 像素坐标超出图片尺寸 {width}x{height}：{raw_summary}，"
            "已置 null（不归一化）")
        return result
    result["bounding_box"] = [
        round(x1 / width, 6), round(y1 / height, 6),
        round(x2 / width, 6), round(y2 / height, 6),
    ]
    result["bounding_box_source_format"] = "pixel"
    result["bounding_box_normalization_applied"] = True
    return result


def coerce_evidence(raw, spec, image_path, model):
    """把模型返回解析为证据结构；字段缺失或类型错误视为失败，不做修补。"""
    if not isinstance(raw, dict):
        raise ValueError("模型返回不是 JSON 对象")
    object_found = raw.get("object_found")
    if not isinstance(object_found, bool):
        raise ValueError("模型返回缺少合法的 object_found(boolean)")
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("模型返回缺少合法的 description(string)")
    bounding_box = raw.get("bounding_box")
    warnings = []
    if bounding_box is not None and (not isinstance(bounding_box, list) or len(bounding_box) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bounding_box)):
        raise ValueError("模型返回的 bounding_box 不是 [x1,y1,x2,y2] 或 null")
    bounding_box_raw = list(bounding_box) if isinstance(bounding_box, list) else None
    frame_size = read_image_size(image_path) if bounding_box is not None else None
    frame_width, frame_height = frame_size if frame_size else (None, None)
    bbox_format = None
    bbox_normalization_applied = False
    if bounding_box is not None:
        # 任务 06 像素坐标受控归一化：仅在全部条件满足时归一化，否则置 null 并记录 warning
        normalized = normalize_bounding_box(bounding_box, frame_width, frame_height)
        bounding_box = normalized["bounding_box"]
        bbox_format = normalized["bounding_box_source_format"]
        bbox_normalization_applied = normalized["bounding_box_normalization_applied"]
        if normalized["warning"]:
            warnings.append(normalized["warning"])
    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("模型返回缺少合法的 confidence(number)")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("模型返回的 confidence 超出 0-1 范围")
    evidence_text = raw.get("evidence_text")
    if not isinstance(evidence_text, str):
        raise ValueError("模型返回缺少合法的 evidence_text(string)")
    abstention_reason = raw.get("abstention_reason")
    if abstention_reason is not None and not isinstance(abstention_reason, str):
        raise ValueError("模型返回的 abstention_reason 必须是 string 或 null")
    if isinstance(abstention_reason, str) and not abstention_reason.strip():
        raise ValueError("abstention_reason 不允许为空字符串（无法确认时填写原因，确定性负面结论用 null）")

    threshold = spec.get("confidence_threshold", 0.5)
    evidence_sufficient = bool(object_found) and confidence >= threshold
    gaps = []
    if not object_found:
        gaps.append("目标未被确认存在")
    if object_found and confidence < threshold:
        gaps.append(f"置信度 {confidence} 低于阈值 {threshold}")
    if object_found and bounding_box is None:
        if bounding_box_raw is not None:
            gaps.append("模型返回的定位框未通过契约校验（格式/越界/顺序非法），已置 null，不伪造")
        else:
            gaps.append("模型未提供定位框（不伪造，允许缺失）")

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "task_id": spec.get("task_id"),
        "task_type": spec.get("task_type"),
        "backend": "ollama",
        "model": model,
        "source_media": image_path,
        "target_query": spec.get("target", {}).get("description", ""),
        "object_found": object_found,
        "description": description,
        "bounding_box": bounding_box,
        "bounding_box_raw": bounding_box_raw,
        "bounding_box_source_format": bbox_format,
        "bounding_box_normalization_applied": bbox_normalization_applied,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "confidence": round(float(confidence), 4),
        "evidence_text": evidence_text,
        "abstention_reason": abstention_reason,
        "evidence_sufficient": evidence_sufficient,
        "gaps": gaps,
        "warnings": warnings,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="本地 Qwen Vision 图片证据抽取")
    parser.add_argument("--task-spec", required=True, help="VisualTaskSpec JSON 路径")
    parser.add_argument("--image", required=True, help="本地图片路径")
    parser.add_argument("--output", help="证据 JSON 输出路径（默认打印到 stdout）")
    parser.add_argument("--save-raw", help="保存模型原始返回 JSON 的路径（审计用）")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Ollama 模型名")
    parser.add_argument("--timeout", type=int, default=300, help="单次调用超时秒数")
    args = parser.parse_args()

    try:
        with open(args.task_spec, encoding="utf-8") as handle:
            spec = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[错误] 无法读取任务规格: {error}", file=sys.stderr)
        return 2

    # 最小契约检查：完整校验由 task-to-skill-compiler 的 validate_task_spec.py 负责
    if spec.get("requires_visual_input") is not True:
        print("[拒绝] 任务规格 requires_visual_input 必须为 true", file=sys.stderr)
        return 1
    if spec.get("task_type") not in ("object_trace", "object_presence"):
        print(f"[拒绝] 不支持的 task_type: {spec.get('task_type')!r}", file=sys.stderr)
        return 1
    if not spec.get("target", {}).get("description"):
        print("[拒绝] 任务规格缺少 target.description", file=sys.stderr)
        return 1

    prompt = build_prompt(spec)
    try:
        body = call_ollama(args.model, prompt, args.image, args.timeout)
    except Exception as error:  # 网络/HTTP/超时等，统一转为非敏感错误
        print(f"[错误] Ollama 调用失败: {type(error).__name__}: {error}", file=sys.stderr)
        return 3

    raw_text = body.get("response", "")
    if args.save_raw:
        with open(args.save_raw, "w", encoding="utf-8") as handle:
            handle.write(raw_text)
    try:
        raw = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        print(f"[错误] 模型未返回合法 JSON（前 200 字符）: {str(raw_text)[:200]!r}", file=sys.stderr)
        return 3

    try:
        evidence = coerce_evidence(raw, spec, args.image, args.model)
    except ValueError as error:
        print(f"[错误] 证据校验失败: {error}", file=sys.stderr)
        return 3

    text = json.dumps(evidence, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"[完成] 证据已写入 {args.output}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
