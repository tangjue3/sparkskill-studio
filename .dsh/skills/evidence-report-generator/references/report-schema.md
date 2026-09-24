# 报告 Schema 参考（evidence-report-generator 产出物）

由 `.dsh/skills/evidence-report-generator/scripts/generate_report.py` 产出。
支持六种模式：图片证据模式（默认）、视频时间线模式（`--mode video` 或自动判别）、
多视频模式（`--mode multi-video`）、时序证据模式（`--mode temporal` / `--mode temporal-multi`，任务 16）。

## 图片模式输出结构

```json
{
  "schema_version": "1.1.0",
  "task_id": "string",
  "status": "completed | abstained | failed",
  "conclusion": "string | null",
  "evidence": [],
  "confidence": 0.0,
  "abstention_reason": "string | null",
  "warnings": [],
  "generated_at": "UTC ISO-8601"
}
```

## 图片模式状态机规则（硬约束）

| 条件 | status | conclusion |
| --- | --- | --- |
| 无任何证据 | `failed` | null（不得生成任何结论） |
| 任一证据 abstention_reason 非空 | `abstained` | 证据不足，拒答 |
| object_found=true 且 confidence ≥ 阈值 | `completed` | 基于证据字段的肯定结论 |
| object_found=true 但 confidence < 阈值 | `abstained` | 线索待确认 |
| object_found=false 且无 abstention_reason | `completed` | 负面结论（未确认存在），**不得声称存在** |

## 视频模式输出结构（任务 04 新增）

输入为 visual-evidence-extractor `trace_video.py` 产出的 timeline.json。

```json
{
  "schema_version": "1.1.0",
  "report_type": "video_timeline",
  "task_id": "string",
  "source_video": "string",
  "duration_ms": 0.0,
  "sampled_frames": 0,
  "target_query": "string",
  "status": "completed | abstained | failed",
  "conclusion": "string",
  "confidence": 0.0,
  "abstention_reason": "string | null",
  "summary": {
    "first_confirmed_timestamp_ms": 0.0,
    "last_confirmed_timestamp_ms": 0.0,
    "confirmed_frame_count": 0,
    "not_found_frame_count": 0,
    "abstained_frame_count": 0,
    "low_confidence_frame_count": 0,
    "failed_frame_count": 0,
    "analyzed_frame_count": 0,
    "overall_status": "completed | abstained | failed"
  },
  "evidence": [],
  "warnings": [],
  "generated_at": "UTC ISO-8601"
}
```

### 视频模式状态规则（按优先级）

| 条件 | status | conclusion |
| --- | --- | --- |
| 无任何 analyzed 帧（全部 failed） | `failed` | 不作任何存在性断言；abstention_reason 记录失败原因 |
| 存在 confirmed 帧（object_found=true 且证据充分） | `completed` | 引用首次/最后确认时间与确认帧数，可回溯到具体帧 |
| 无 confirmed，但有 abstained / low_confidence 帧 | `abstained` | 证据不足，拒答；保留拒答原因 |
| 全部为 not_found（确定性负面） | `completed` | 负面结论（未确认存在），**不得声称存在** |

### 视频模式交叉校验

- `status` 与 `summary` 由本引擎按帧条目**独立复算**；
- 与输入 `timeline.summary.overall_status` 比对，不一致时以复算结果为准并记入 warnings；
- `evidence` 为完整 timeline（每项含 frame_path，结论可回溯）。

## 反幻觉规则

- conclusion 只能由输入证据中的字段（description / evidence_text / source_media / confidence / 时间线条目）组成；
- 不得添加输入证据中不存在的事实；
- 不得推断人物身份、年龄、国籍、关系或意图；
- 视频模式不得声称跨帧同一性，不做身份跟踪与跨镜头关联；
- warnings 汇总所有 gaps 与交叉校验冲突，向调用方透明暴露证据缺口。

## 时序证据模式（任务 16）

输入为 `visual-evidence-extractor` `trace_temporal.py` 产出的 temporal-evidence.json
（单来源：`timeline[]` + `sampling_provenance{}` + `temporal_evidence{}`；
多来源：`global_timeline[]` + `sources[]` + `global_temporal_evidence{}` + `shared_budget{}`）。

```json
{
  "schema_version": "1.3.0",
  "report_type": "temporal_evidence | temporal_multi_video",
  "task_id": "string",
  "target_query": "string",
  "source_video": "string（单来源）",
  "input_nature": "user_media | technical_fixture",
  "evidence_nature": "real_model_output | constructed_fixture_evidence | resource_blocked",
  "sampling_strategy": "uniform | adaptive_coarse_to_fine | coverage_aware_adaptive",
  "vision_call_budget": 0,
  "actual_model_calls": 0,
  "budget_exhausted": false,
  "target_boundary_precision_ms": 0,
  "target_precision_reached": true,
  "residual_uncertainty_ms": 0,
  "resource_blocked": false,
  "status": "completed | abstained | failed",
  "conclusion": "string",
  "confidence": 0.0,
  "abstention_reason": "string | null",
  "summary": {},
  "sampling_provenance": {},
  "temporal_evidence": {},
  "semantic_limitation_note": "string（时序语义限制，必显）",
  "evidence": [],
  "warnings": [],
  "generated_at": "UTC ISO-8601"
}
```

### 时序模式独立复算与交叉校验（两套实现互检）

- 本引擎按时间线条目**独立复算**（`derive_temporal_evidence`，不导入 extractor 模块）：
  首末 confirmed 观察时间、五类计数、状态转换与不确定宽度、整体状态；
- 与上游 `temporal_evidence` 逐字段比对，不一致 → warnings 记录，**以复算结果为准**；
- `provenance.actual_model_calls` 与配置预算比对（越界 → warning）；与 timeline 中
  真实模型证据条目数比对（不一致 → warning；构造 fixture 证据不参与该校验）；
- 不静默接受上游摘要；不重新调用模型掩盖矛盾。

### 时序模式必显语义（硬约束）

- 采样策略、视觉调用预算与实际调用数、是否耗尽预算、是否达到目标时间精度；
- “这是采样证据支持的时序结论，不是连续跟踪真值”声明（`semantic_limitation_note`）；
- 首/末 confirmed 是采样观察时间，不等于目标真实进入/离开时间；
- 两个 confirmed 采样点之间不断言连续存在；状态边界只给左右采样点范围；
- abstained / low_confidence / failed 不退化为 not_found；
- 多来源时序报告继续显示跨视频语义限制（`semantic_limitations`）。

### 时序模式状态规则（按优先级）

| 条件 | status | conclusion |
| --- | --- | --- |
| 无任何 analyzed 采样点（全部 failed） | `failed` | 不作任何存在性断言；abstention_reason 记录失败原因 |
| 存在 confirmed 采样点 | `completed` | 引用首/末 confirmed 采样时间、确认数、状态转换数与最大边界宽度，可回溯到帧 |
| 无 confirmed，但有 abstained / low_confidence | `abstained` | 证据不足，拒答；保留拒答原因 |
| 全部为 not_found（确定性负面） | `completed` | 负面结论，**不得声称存在** |
