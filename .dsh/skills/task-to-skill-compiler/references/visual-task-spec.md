# VisualTaskSpec 契约参考（task-to-skill-compiler 产出物）

Schema 文件：`schemas/visual-task-spec.schema.json`（项目根）。
校验器：`.dsh/skills/task-to-skill-compiler/scripts/validate_task_spec.py`。

## 字段说明

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `task_id` | string | `^[a-z0-9][a-z0-9_-]{2,63}$` | 任务唯一标识 |
| `skill_name` | string | kebab-case | 目标 Skill 名称 |
| `task_type` | enum | `object_trace` \| `object_presence` | 首版仅两种 |
| `target.description` | string | 1–200 字符 | 目标对象描述 |
| `target.attributes` | array\<string\> | ≤20 项 | 目标属性（颜色、类别等） |
| `source_media` | string \| array | 1–500 字符（字符串）或 1–16 项来源对象数组 | 输入媒体：单路径字符串（旧版单媒体任务，保持兼容）或来源对象数组（多段视频统一证据时间线，任务 06） |
| `required_outputs` | array\<enum\> | 1–7 项 | 见下方枚举 |
| `constraints.abstain_if_insufficient_evidence` | boolean | 默认 true | 证据不足必须拒答 |
| `constraints.forbidden_inferences` | array\<enum\> | 默认身份/年龄/国籍/关系/意图 | 禁止推断维度 |
| `confidence_threshold` | number | 0–1，默认 0.5 | 证据充分性阈值 |
| `requires_visual_input` | boolean | **必须为 true** | 本契约仅用于视觉任务 |
| `sampling_strategy` | object | 可选（任务 16） | 视频采样策略块；**缺失时保持旧版 uniform 行为（向后兼容）**，见下表 |

## 采样策略（sampling_strategy，任务 16；可选，向后兼容）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `strategy` | enum | `uniform` \| `adaptive_coarse_to_fine` \| `coverage_aware_adaptive`（任务 18） | uniform=旧版固定间隔/均匀采样（正式 baseline）；adaptive=初始覆盖 + 按触发器二分细化；coverage_aware_adaptive=初始覆盖 + 时间覆盖探索（largest-gap-first 压缩未观测间隔）+ 边界细化（同一硬预算双职责） |
| `max_model_calls` | integer | 1–512 | **硬性视觉模型调用预算**：整个任务真实 Qwen 视觉调用不得超过；0/负数/非整数/超上限拒绝 |
| `initial_coverage_samples` | integer | 1–64 | adaptive 初始覆盖采样数（区间内均匀含端点）；不得超过 max_model_calls |
| `target_boundary_precision_ms` | number | >0，≤600000 | adaptive 目标时间边界精度（毫秒）；无法达到时如实报告剩余不确定性 |
| `max_refinement_rounds` | integer | 1–16 | adaptive / coverage 最大细化轮数 |
| `coverage_gap_target_ms` | number | >0，≤600000 | coverage_aware_adaptive 覆盖目标：最大相邻采样间隔目标值（毫秒）；覆盖探索到达该目标、储备用尽、预算耗尽或无合法候选时确定性停止 |
| `coverage_call_reserve` | integer | 1–512 | coverage_aware_adaptive 覆盖调用储备：初始覆盖之外的最大覆盖探索调用次数（正整数）；`initial_coverage_samples + coverage_call_reserve ≤ max_model_calls` |
| `refinement_triggers` | array\<enum\> | 1–4 项，unique | `state_change`/`abstained`/`low_confidence`/`failed`（缺省全开） |
| `require_sampling_provenance` | boolean | 默认 true | 是否要求输出采样 provenance |
| `require_temporal_evidence` | boolean | 默认 true | 是否要求输出 temporal evidence |

**不支持组合（校验器明确拒绝）**：uniform 策略带任何细化参数或 coverage 专属字段
（`initial_coverage_samples` / `target_boundary_precision_ms` / `max_refinement_rounds` /
`refinement_triggers` / `coverage_gap_target_ms` / `coverage_call_reserve`）；
adaptive_coarse_to_fine 策略缺少四个必填字段之一或带 coverage 专属字段；
coverage_aware_adaptive 策略缺少六个必填字段之一（adaptive 四字段 + coverage 两字段）；
`initial_coverage_samples > max_model_calls`；
`initial_coverage_samples + coverage_call_reserve > max_model_calls`（覆盖配置之和不得
超出硬预算）；未知策略；非法预算；≤0 的边界精度或覆盖目标；非正整数覆盖储备。

**语义红线**（随产物与报告输出，写入 `temporal_evidence.semantics`）：
首个/最后 confirmed 只是**采样观察时间**，不等于目标真实进入/离开时间；
两个 confirmed 采样点之间不得断言连续存在；状态变化只定位到左右采样点形成的
时间范围（boundary uncertainty）；abstained/low_confidence/failed 不得折算为
not_found；不做跨帧身份一致性、不做跨摄像头实例关联、不输出物体运动路径；
本功能不是 ReID、不是目标跟踪器、不是实时跟踪。

adaptive 策略示例：

```json
"sampling_strategy": {
  "strategy": "adaptive_coarse_to_fine",
  "max_model_calls": 12,
  "initial_coverage_samples": 4,
  "target_boundary_precision_ms": 500,
  "max_refinement_rounds": 6,
  "refinement_triggers": ["state_change", "abstained", "low_confidence", "failed"],
  "require_sampling_provenance": true,
  "require_temporal_evidence": true
}
```

coverage_aware_adaptive 策略示例（任务 18；预注册三臂评测的 coverage 臂配置）：

```json
"sampling_strategy": {
  "strategy": "coverage_aware_adaptive",
  "max_model_calls": 12,
  "initial_coverage_samples": 4,
  "coverage_gap_target_ms": 1500,
  "coverage_call_reserve": 4,
  "target_boundary_precision_ms": 500,
  "max_refinement_rounds": 6,
  "refinement_triggers": ["state_change", "abstained", "low_confidence", "failed"],
  "require_sampling_provenance": true,
  "require_temporal_evidence": true
}
```

coverage 语义红线（附加）：覆盖探索只压缩未观测时间间隔，**不保证发现任意短事件**
（产物携带 `arbitrary_short_event_detection_guaranteed: false` 与
`events_shorter_than_max_sampling_gap_may_be_missed: true`）；覆盖改善不等于语义正确
（模型在 uncertain 区域的校准是独立问题，任务 17 已实证）。

`required_outputs` 允许值：`object_found`、`description`、`bounding_box`、`confidence`、`evidence_text`、`timestamp`、`keyframe_ref`（单媒体任务）与 `per_source_timeline`、`global_timeline`、`keyframes`、`evidence_report`（多段视频任务，任务 06 扩充；旧版规格不受影响）。
`forbidden_inferences` 允许值：`identity`、`age`、`nationality`、`relationship`、`intent`、`health`、`emotion`。

`source_media` 为来源对象数组时，每项字段规则见 `visual-evidence-extractor/references/multi-video-evidence.md` 第 1 节：`source_id` 任务内唯一、`path` 必须经过安全校验、`location` 可选且不得包含身份等敏感推断、`time_offset_ms` 可选非负（默认 0）。

## 安全约束（校验器强制）

- 不允许任意代码（代码围栏、exec/eval/subprocess 等字样）；
- 不允许 shell 命令（sudo、rm -rf、curl/wget http、chmod +x 等）；
- 不允许凭据内容（api_key/secret/token/password/bearer 令牌、私钥头）；
- 不允许 `additionalProperties`（schema 中 `additionalProperties: false`）。

## 示例

```json
{
  "task_id": "red-backpack-trace-001",
  "skill_name": "visual-evidence-extractor",
  "task_type": "object_trace",
  "target": {
    "description": "红色背包",
    "attributes": ["红色", "背包"]
  },
  "source_media": "/path/to/media",
  "required_outputs": ["object_found", "description", "bounding_box", "confidence", "evidence_text"],
  "constraints": {
    "abstain_if_insufficient_evidence": true,
    "forbidden_inferences": ["identity", "age", "nationality", "relationship", "intent"]
  },
  "confidence_threshold": 0.5,
  "requires_visual_input": true
}
```

多段视频任务的 `source_media` 形态（任务 06；字段规则见上）：

```json
"source_media": [
  {"source_id": "video-a", "path": "/abs/path/a.mp4", "location": "scene-a", "time_offset_ms": 0},
  {"source_id": "video-b", "path": "/abs/path/b.mp4", "location": "scene-b", "time_offset_ms": 5000}
]
```

## 媒体来源可信契约（任务 08 建立）

视觉任务的 `source_media` 只能来自**当前用户请求**。这是根因修复：任务 07 Tier-3 E9 中，
Agent 在用户未提供媒体路径时从项目文档与历史 run-summary 推断出 `h3-smoke.mp4` 并完成分析——
结果真实但违反"关键参数不全时必须先问用户"的产品安全契约。

### 可信来源（只接受）

1. 当前用户消息中显式提供的本地媒体路径（绝对/相对路径，含媒体扩展名）；
2. 当前用户正式上传/附加、并由 Harness 明确传入的媒体；
3. 当前用户消息中显式列出的多个媒体来源。

### 不可信来源（禁止用作 source_media）

README / PROJECT_CONTEXT / 设计文档中的路径；run-summary / 历史 artifacts / 上一次会话
产物中的路径；先前会话中的默认视频；目录扫描找到的第一个视频；测试目录中的示例视频；
模型自行推断的媒体；Agent 根据"看起来合适"选择的视频。

### 前置校验

`scripts/check_source_media.py --request <用户请求文本> [--spec <规格>]`：请求文本的纯函数
（不访问项目文件系统）。输出契约：

| status | error_code | 含义 | 允许的后续动作 |
| --- | --- | --- | --- |
| `accepted` | — | 来源为 user_provided | 生成规格 → 校验 → 抽取 |
| `needs_input` | `missing_source_media` | 用户未提供媒体 | **无**（只许把契约返回用户） |
| `rejected` | `invalid_source_media` | 显式提供的路径未通过安全校验 | **无** |
| `rejected` | `inferred_source_media` | 规格中的路径未出现在当前请求中（推断） | **无** |
| `not_applicable` | — | 非视觉任务 | 走非视觉负向触发 |

### 校验器的 missing/invalid 区分

`validate_task_spec.py` 对规格缺少 `source_media` 输出 `[CONTRACT] {"status":"needs_input",
"error_code":"missing_source_media",...}`；对路径非法输出 `{"status":"rejected",
"error_code":"invalid_source_media",...}`。两者不得互相退化。

### 契约测试

`scripts/test_missing_media_contract.py`（M1–M8 + V1/V2，全部确定性、不调用模型）：
M1 无媒体路径 / M2 “这个视频”指代 / M3 历史路径不被读取 / M4 示例路径不当输入 /
M5 显式单路径放行 / M6 显式多路径放行 / M7 非法路径 invalid（非 missing）/ M8 非视觉不触发。
