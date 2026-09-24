---
name: evidence-report-generator
description: 将结构化视觉证据汇总为可复核的事件证据链报告：按规则生成 completed/abstained/failed 状态的结论；支持图片证据、短视频证据时间线（video-report）、多段视频统一时间线报告（multi-video-report，含跨视频语义限制声明，不做跨视频身份断言）与目标时序证据报告（temporal / temporal-multi：独立复算状态转换与边界不确定性，显示调用预算、覆盖探索与边界细化调用区分、最大相邻采样间隔与“采样证据支持的时序结论，不是连续跟踪真值”）；证据不足时必须允许拒答，不得给出确定性结论，不得添加输入中不存在的事实。
---

# Skill: evidence-report-generator

- **name**: evidence-report-generator
- **status**: minimal（单条/多条证据汇总 + 视频时间线报告 + 多段视频统一时间线报告 + 目标时序证据报告；跨摄像头身份追踪报告不做）
- **owner**: SparkSkill Studio（自研，非 NVIDIA 官方签名）

## description

SparkSkill Studio 流水线的第三环：接收 `visual-evidence-extractor` 产出的证据 JSON（图片证据对象/数组，或短视频证据时间线 timeline.json），按硬规则生成最终报告 JSON，保证结论不幻觉、不越证。

## 当前职责

- 汇总证据（单条对象或数组），输出 `{task_id, status, conclusion, evidence, confidence, abstention_reason, warnings}`。
- 规则：
  - 没有视觉证据 → status=failed，不生成任何结论；
  - object_found=false → 不得声称目标存在，只给出负面结论；
  - abstention_reason 非空 → status 必须为 abstained；
  - object_found=true 但 confidence 低于阈值 → status=abstained；
  - conclusion 只能由输入证据字段组成，不得添加输入中不存在的事实。
- **视频模式（任务 04 新增）**：输入为 `trace_video.py` 产出的视频证据时间线时（自动判别或 `--mode video`），输出视频级报告：`source_video`、`duration_ms`、`sampled_frames`、`target_query`、`timeline[]`、`summary{first_confirmed_timestamp_ms, last_confirmed_timestamp_ms, confirmed_frame_count, overall_status}`、`status`、`conclusion`、`abstention_reason`、`warnings`。
- 视频状态规则（与 visual-evidence-extractor 的聚合规则一致，由本引擎独立复算）：
  - 无任何 analyzed 帧 → failed（不对目标作任何存在性断言）；
  - 存在 confirmed 帧 → completed（结论引用首次/最后确认时间与确认帧数，可回溯到具体帧）；
  - 无 confirmed 但有 abstained/low_confidence 帧 → abstained（保留拒答原因）；
  - 全部为 not_found（确定性负面）→ completed，但结论必须是负面表述。
- **交叉校验**：视频模式下本引擎按帧条目独立复算状态，并与 `timeline.summary.overall_status` 比对；不一致时以复算结果为准并记入 warnings（两套实现互检，防单点规则错误）。
- **多视频模式（任务 06 新增）**：输入为 `trace_multi_video.py` 产出的全局时间线（global-timeline.json，含 `global_timeline[]` 与 `sources[]`，自动判别或 `--mode multi-video`），输出多视频报告：`sources[]`（每来源独立状态与统计）、`global_summary{}`、`timeline[]`、`semantic_limitations{}`、`status`、`conclusion`。状态按全局条目独立复算并与 `global_summary.overall_status` 交叉校验。结论只允许使用 matched target query / visually consistent with target description / confirmed in source A / confirmed in source B 等表述；**必须显示跨视频语义限制**：不断言同一个物理实例、不宣称跨视频移动、不做身份匹配。
- **时序证据模式（任务 16/18 新增）**：输入为 `trace_temporal.py` 产出的时序证据文档（temporal-evidence.json：单来源含 `timeline[]`/`sampling_provenance{}`/`temporal_evidence{}`；多来源含 `global_timeline[]`/`sources[]`/`global_temporal_evidence{}`；自动判别或 `--mode temporal` / `--mode temporal-multi`），输出时序报告：按时间线条目**独立复算**首末 confirmed 观察时间、状态转换、五类计数、边界不确定性（自有实现，与 adaptive_sampler 两套互检）；与上游 `temporal_evidence` / `sampling_provenance` 交叉校验，不一致以复算为准并记 warnings（不静默接受上游摘要、不重新调用模型掩盖矛盾）；实际调用超过配置预算也记 warning。报告必须显示：采样策略、视觉调用预算与实际调用数、是否耗尽预算、是否达到目标时间精度、**“这是采样证据支持的时序结论，不是连续跟踪真值”**；多来源时序报告继续显示跨视频语义限制。**任务 18 附加**：coverage_aware_adaptive 产物的报告追加 `coverage_summary`（覆盖探索/边界细化/初始覆盖调用、覆盖目标、最大相邻采样间隔初始/最终值、剩余盲区清单）与覆盖限制句（不保证发现任意短事件，宽度小于最大相邻采样间隔的事件可能被漏检）。结论遵守时序语义红线（首末 confirmed 是采样观察时间；采样点之间不断言连续存在；abstained/low_confidence/failed 不退化为 not_found）。
- 严格区分 confirmed / not_found / abstained / failed；不做身份跟踪、不做跨镜头关联、不做没有证据的路径推断。

## 输入输出契约

- 输入：VisualTaskSpec JSON + 证据 JSON（对象或数组）、视频时间线 JSON（timeline.json）、多视频全局时间线 JSON（global-timeline.json）或时序证据文档（temporal-evidence.json）。
- 输出：报告 JSON（图片模式字段见 `references/report-schema.md`；视频模式字段见 visual-evidence-extractor 的 `references/video-evidence.md` 第 5 节；多视频模式字段见 `references/multi-video-evidence.md` 第 3/4 节；时序模式字段见 `references/temporal-evidence.md` 第 4/6 节）。
- 执行：`python3 scripts/generate_report.py --task-spec <spec.json> --evidence <evidence.json> --output <report.json> [--mode auto|image|video|multi-video|temporal|temporal-multi]`。

## 安全边界

- 不推断人物身份、年龄、国籍、关系或意图。
- 不做视觉推理（视觉推理属于 visual-evidence-extractor）。
- 不执行任意模型生成代码。
- 视频报告不得声称跨帧同一性；没有确认帧时不得声称目标存在；failed 时不给存在性断言。
- 多视频报告必须显示跨视频语义限制：不断言同一个物理实例（same physical instance）、不宣称从来源 A 移动到来源 B（moved from A to B）、不做身份匹配（identity matched）；全局时间线是证据聚合，不是跨摄像头身份追踪。
- 时序报告必须显示“采样证据支持的时序结论，不是连续跟踪真值”：首/末 confirmed 是采样观察时间（不等于真实进入/离开），采样点之间不断言连续存在，状态边界只给出左右采样点范围与不确定宽度；本报告不是 ReID、不是目标跟踪器、不是实时跟踪。
- 不冒充 NVIDIA 官方签名 Skill。

## 当前状态

- minimal：规则引擎与反幻觉约束已实现并经真实运行验证（见 artifacts/task-03/ 与 BENCHMARK.md）。
- minimal：视频时间线报告已实现；状态一致性与交叉校验经规则测试验证（见 artifacts/task-04/ 与 BENCHMARK.md）；真实视频视觉证据输入与 DSH 自主编排已于任务 05 验证（见 artifacts/task-05/）。
- minimal：多视频统一时间线报告已实现（任务 06）：每来源独立状态 + 全局摘要 + 跨视频语义限制声明；规则测试见 `scripts/test_multi_video_pipeline.py`（D1–D6），真实运行证据见 `artifacts/task-06/`。
- minimal：目标时序证据报告已实现（任务 16）：temporal / temporal-multi 模式独立复算 + 交叉校验 + 语义红线展示；规则测试 T18–T21 见 `visual-evidence-extractor/scripts/test_temporal_evidence.py`（27/27）。
- minimal：coverage_aware_adaptive 时序报告附加展示已实现（任务 18）：coverage_summary 与覆盖限制句（策略透传，无分支逻辑改动）；任务 18 规则测试 36/36 见 `visual-evidence-extractor/scripts/test_task18_coverage_sampling.py`。
