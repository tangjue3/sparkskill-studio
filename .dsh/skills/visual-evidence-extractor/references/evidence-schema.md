# 视觉证据 Schema 参考（visual-evidence-extractor 产出物）

由 `.dsh/skills/visual-evidence-extractor/scripts/analyze_image.py` 产出。
字段分两类：模型返回字段（脚本原样透传，不修补）与脚本计算字段。

## 模型返回字段（禁止伪造）

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `object_found` | boolean | 目标是否被确认存在；无法确认必须为 false |
| `description` | string | 画面主要内容的客观描述 |
| `bounding_box` | [number×4] \| null | 归一化 0–1 的 [x1,y1,x2,y2]；无法可靠定位必须 null，**禁止编造** |
| `confidence` | number | 0–1 |
| `evidence_text` | string | 客观视觉依据 |
| `abstention_reason` | string \| null | object_found=false 时必填 |

## 脚本计算字段

| 字段 | 说明 |
| --- | --- |
| `schema_version` | 证据 schema 版本（当前 1.0.0） |
| `task_id` / `task_type` | 来自输入 VisualTaskSpec |
| `backend` / `model` | 推理后端与模型名（当前 ollama / Qwen3.8-27B-GGUF） |
| `source_media` | 输入图片路径 |
| `target_query` | 目标描述（来自任务规格） |
| `evidence_sufficient` | object_found=true 且 confidence ≥ confidence_threshold |
| `gaps` | 证据缺口列表（目标未确认 / 置信度不足 / 无定位框） |
| `generated_at` | UTC 时间戳 |

## 拒答规则

- object_found=false 且 abstention_reason 非空 → 拒答（无法确认）；
- object_found=false 且 abstention_reason=null → 确定性负面结论（目标确实不存在）；
- object_found=false 时 abstention_reason 不允许为空字符串；
- confidence < 阈值 → evidence_sufficient=false，gaps 记录原因；
- bounding_box=null 不视为失败，记入 gaps，不伪造。

## 安全边界

- 提示词注入 forbidden_inferences；不推断身份、年龄、国籍、关系、意图；
- 不输出证据字段之外的信息；不输出凭据。
