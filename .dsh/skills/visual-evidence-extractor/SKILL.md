---
name: visual-evidence-extractor
description: 在 DGX Spark 本地算力上执行受控的视觉证据抽取：对输入图片或本地短视频调用本地 Ollama Qwen Vision 模型进行对象存在性判断，输出带目标框、置信度和时间戳的结构化证据；视频使用抽帧策略逐帧分析并聚合为时间线；支持多段视频统一证据时间线（每段独立时间线 + 按 time_offset_ms 合并全局时间线，不做跨视频身份断言）；支持目标时序证据与粗到细自适应采样（uniform baseline / adaptive_coarse_to_fine / coverage_aware_adaptive 覆盖感知自适应，硬性调用预算 + 采样 provenance + 状态边界不确定性 + 覆盖探索与剩余盲区声明）；证据不足时必须拒答，禁止猜测。
---

# Skill: visual-evidence-extractor

- **name**: visual-evidence-extractor
- **status**: minimal（图片 + 单段短视频 + 多段视频统一证据时间线 + 目标时序证据与粗到细自适应采样闭环；跨摄像头身份关联不做）
- **owner**: SparkSkill Studio（自研，非 NVIDIA 官方签名）

## description

SparkSkill Studio 流水线的第二环：接收合法 VisualTaskSpec 与一个本地图片路径、一个本地短视频路径，或**多个视频来源**（`source_media` 来源数组），调用 DGX Spark 本地 Ollama 上的 Qwen3.8-27B（vision）模型完成对象存在性判断，输出结构化视觉证据 JSON。视频输入使用抽帧策略：先按可配置采样策略抽取关键帧，再逐帧复用任务 03 的图片分析能力，聚合为视频级证据时间线。多段视频时每段独立时间线，按 `time_offset_ms` 计算全局排序时间并合并为统一全局时间线（证据聚合，非跨摄像头身份追踪）。当前 DSH 配置下 StepFun 不具备图片输入能力，因此视觉后端使用本地 Qwen Vision；StepFun 负责文本任务解析与 Agent 规划。

## 当前职责

- 接收合法 VisualTaskSpec（requires_visual_input=true，task_type ∈ {object_trace, object_presence}）。
- 调用本地 Ollama Qwen Vision（`modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`），要求模型只返回结构化 JSON。
- 校验模型输出：object_found(boolean)、description(string)、bounding_box([x1,y1,x2,y2] 归一化或 null)、confidence(0-1)、evidence_text(string)、abstention_reason(string|null)。
- object_found=false 时必须提供 abstention_reason；confidence 低于任务阈值时标记 evidence_sufficient=false 并记入 gaps。
- 不伪造 bounding_box（模型返回 null 即保持 null；覆盖接近整幅画面的框标记定位不可靠，不作为精确定位证据）。
- **视频输入（任务 04 新增）**：`scripts/extract_frames.py` 读取视频元数据并按采样策略（最大帧数、时间间隔、起始/结束时间）抽取关键帧，输出带稳定命名与时间戳的帧索引 JSON；`scripts/trace_video.py` 对抽取帧逐帧调用 `scripts/analyze_image.py` 的既有逻辑（**不重复实现视觉提示词体系**），聚合为视频级证据时间线（timeline.json）。
- **视频级输出**：source_video、duration_ms、sampled_frames、target_query、timeline[{timestamp_ms, frame_path, object_found, description, bounding_box, confidence, evidence_text, abstention_reason, ...}]、summary{first/last_confirmed_timestamp_ms, confirmed_frame_count, overall_status: completed|abstained|failed}。字段与聚合规则见 `references/video-evidence.md`。
- **像素坐标受控归一化（任务 06）**：模型返回像素坐标（四元数值、全部 >1、x1<x2/y1<y2、不越界、可读真实帧宽高）时确定性归一化为 0-1，并记录 `bounding_box_source_format="pixel"`、`bounding_box_normalization_applied=true`、`frame_width/frame_height` 与原始值 `bounding_box_raw`；混合/越界/顺序错误/尺寸未知时不归一化，bbox 置 null 并记 warning，不重跑模型凑结果。
- **多段视频输入（任务 06 新增）**：`scripts/trace_multi_video.py` 读取 `source_media` 为来源对象数组的多媒体 VisualTaskSpec，**依次对每个视频复用 `trace_video.py` 单段能力**（不重写视觉提示词或视频处理逻辑），为每段生成独立时间线（保留 source_id 与原视频时间戳），按 `time_offset_ms` 计算全局排序时间，合并为统一全局时间线（global-timeline.json），输出每来源与全局的首次/最后确认与确认帧数；failed/abstained/not_found 全部保留。契约见 `references/multi-video-evidence.md`。
- **目标时序证据与粗到细自适应采样（任务 16 新增）**：`scripts/trace_temporal.py` 读取规格中可选 `sampling_strategy`（缺失 = 旧版 uniform 行为），支持三种策略：
  - `uniform`（正式 baseline，行为与 `trace_video.py` 的规划/分类/报告规则一致，另加调用计数与逐阶段耗时）；
  - `adaptive_coarse_to_fine`：先按 `initial_coverage_samples` 均匀覆盖，再对命中 `refinement_triggers`（state_change / abstained / low_confidence / failed）且宽度超过 `target_boundary_precision_ms` 的相邻区间做二分中点细化，直到达到目标精度 / 达到最大轮数 / **预算耗尽** / 无可细化区间；
  - `coverage_aware_adaptive`（任务 18 新增）：同一硬预算内双职责——初始覆盖后先用 ≤ `coverage_call_reserve` 次调用做**时间覆盖探索**（largest-gap-first 二分压缩尚未充分观测的间隔，与证据语义无关；目标：最大相邻采样间隔 ≤ `coverage_gap_target_ms`），再把剩余预算用于**边界细化**（与 adaptive 同款触发器逻辑）；必填 `coverage_gap_target_ms` 与 `coverage_call_reserve`，且 `initial_coverage_samples + coverage_call_reserve ≤ max_model_calls`；显式声明 `arbitrary_short_event_detection_guaranteed: false` 与 `events_shorter_than_max_sampling_gap_may_be_missed: true`（不保证发现任意短事件）；
  - `max_model_calls` 是硬性预算：同一时间戳至多一次真实调用、已有可复用证据不重复调用、预算耗尽即停且不算"分析成功"；资源守卫阻塞时未执行的调用不计为真实视觉调用；
  - 输出完整**采样 provenance**（每次决策的时间戳/阶段/理由/触发区间/观察状态/第几次调用/缓存状态/预算状态/停止原因/耗时）与可复算的**时序证据**（首末 confirmed 观察时间、状态转换左右边界与不确定宽度、五类计数、有效分析比例、证据支持状态片段、无法确认片段、是否达到目标精度、是否因预算停止）。契约见 `references/temporal-evidence.md`。

## 输入输出契约

- 输入（图片）：VisualTaskSpec JSON + 本地图片路径。
- 输出（图片）：证据 JSON（字段见 `references/evidence-schema.md`）。
- 执行（图片）：`python3 scripts/analyze_image.py --task-spec <spec.json> --image <path.png> --output <evidence.json>`。
- 输入（视频）：VisualTaskSpec JSON + 本地短视频路径（第一版只面向短视频，不追求实时）。
- 输出（视频）：timeline.json（字段见 `references/video-evidence.md`）。
- 执行（抽帧）：`python3 scripts/extract_frames.py --video <path.mp4> --output-dir <dir> [--metadata-json <path>] [--interval-ms 1000] [--max-frames 8] [--start-ms 0] [--end-ms N]`。
- 执行（视频时间线）：`python3 scripts/trace_video.py --task-spec <spec.json> --video <path.mp4> --output <timeline.json> [--interval-ms 1000] [--max-frames 8]`。
- 输入（多段视频，任务 06）：VisualTaskSpec JSON，`source_media` 为来源对象数组：
  `[{"source_id": "video-a", "path": "...", "location": "scene-a", "time_offset_ms": 0}, ...]`
  （source_id 任务内唯一；path 必须经过安全校验；time_offset_ms 非负；旧版单路径字符串仍受支持并包装为单一来源 media-0）。
- 输出（多段视频）：global-timeline.json + per-source/<source_id>-timeline.json（字段见 `references/multi-video-evidence.md`）。
- 执行（多段视频时间线）：`python3 scripts/trace_multi_video.py --task-spec <spec.json> --output <global-timeline.json> [--interval-ms 1000] [--max-frames 6] [--per-source-dir <dir>] [--save-raw-dir <dir>]`。
- 输出（时序证据，任务 16）：temporal-evidence.json（单视频：timeline + summary + sampling_provenance + temporal_evidence；多来源：sources + global_timeline + global_summary + global_temporal_evidence + shared_budget；字段见 `references/temporal-evidence.md`）。
- 执行（时序证据，任务 16/18）：`python3 scripts/trace_temporal.py --task-spec <spec.json> --video <path.mp4> --output <temporal-evidence.json> [--strategy uniform|adaptive_coarse_to_fine|coverage_aware_adaptive] [--max-model-calls 12] [--initial-coverage-samples 4] [--target-boundary-precision-ms 500] [--coverage-gap-target-ms 1500] [--coverage-call-reserve 4] [--max-refinement-rounds 6] [--refinement-triggers state_change,abstained,low_confidence,failed] [--input-nature user_media|technical_fixture]`（source_media 为来源数组时自动进入多来源模式，共享同一预算账本；coverage_call_reserve 按来源分别生效，全局硬预算为最终上限）。

## 视频证据规则（硬约束）

- 不得凭空生成时间线：timeline 每一项必须对应一个真实抽取的帧文件。
- 不得把连续帧自动解释成同一个对象：时间线只记录逐帧独立结论；不做身份跟踪、不做跨镜头关联、不做没有证据的路径推断。
- bounding_box 不可靠时必须为 null；不得把整幅图片框成目标框来伪造定位。
- 证据不足时必须保留 abstention_reason；严格区分 confirmed / not_found / abstained / failed。
- 所有结论都必须能回溯到具体帧（frame_path）。
- **视频分析失败时如何报告**：单帧后端调用失败 → 该帧 frame_status=failed、abstention_reason 记录非敏感原因，不中断其他帧；统一内存不足时资源守卫阻止加载 Qwen（见下），全部帧标记 failed，整体状态 failed，如实报告"真实视觉调用被资源条件阻塞"，**不得用伪造模型输出冒充真实视频结果**。

## 跨视频语义边界（任务 06 核心安全要求）

当同一目标查询在多段视频中被确认时，只能得出：**matched target query**（同一目标查询）、
**visually consistent with target description**（分别与目标描述视觉一致）、
**confirmed in source A / confirmed in source B**（在来源 A / 来源 B 中分别确认）。

不得得出（除非未来存在可靠的跨摄像头身份或实例关联证据）：
same physical instance（同一个物理实例）、moved from A to B（从 A 移动到 B）、
carried by the same person（被同一人携带）、entered another camera（进入另一个摄像头）、
identity matched（身份匹配）。全局时间线是**证据聚合，不是跨摄像头身份追踪**；
`semantic_limitations` 随 global-timeline.json 与最终报告一并输出，报告必须显示该限制。

## 目标时序证据语义红线（任务 16 核心安全要求）

- “首个 confirmed 采样时间”不等于目标真实首次进入时间；“最后 confirmed 采样时间”不等于目标真实离开时间；
- 两个 confirmed 采样点之间**不得**自动断言目标连续存在（采样点之间只有“未采样/未知”）；
- 状态变化只能定位到左右相邻采样点形成的时间范围 `[left_ms, right_ms]`，`uncertainty_width_ms = right_ms - left_ms`，不得伪造精确瞬间；
- `abstained` / `low_confidence` / `failed` 独立计数，**不得折算成 not_found**；
- 不做跨帧身份一致性、不做跨摄像头实例关联、不输出物体运动路径；
- 本功能命名与对外表述只用：目标时序证据 / temporal presence evidence / evidence-supported state transition / boundary uncertainty；**不得**命名或宣传为 ReID、目标跟踪器或实时跟踪；
- `max_model_calls` 是硬预算：预算耗尽不是“分析成功”的证据，必须如实报告 `budget_exhausted` 与剩余不确定性。

## 资源守卫（统一内存红线）

- 调用视觉模型前检查 `/proc/meminfo` MemAvailable；低于阈值（默认 40 GiB；Qwen 加载约需 34.6 GB）时不加载模型并如实降级为 failed。
- 不停止 MiniMax-H3、不强行加载导致 OOM、不安装依赖、不下载模型。
- OpenCV 仅作为底层工具（读视频元数据、抽帧、保存关键帧），**绝不是项目核心创新或卖点**；本机未安装 cv2 的解释器会经 `scripts/skill_env.py` 自动切换到本机已有 OpenCV 的解释器（复用 vLLM 环境，不安装任何东西）。

## 安全边界

- 不推断人物身份、年龄、国籍、关系或意图（forbidden_inferences 注入提示词）。
- 不做人脸识别；不做跨镜头身份追踪；不实现实时多摄像头。
- 无法确认时 object_found=false 并给出 abstention_reason，禁止把不确定内容写成事实。
- 不泄露证据字段之外的信息；不输出任何凭据。
- 不冒充 NVIDIA 官方签名 Skill。

## 后续阶段（未实现）

- 跨摄像头身份或实例关联（需要可靠的关联证据，当前明确不做）。
- StepFun 侧图片能力可用后的路由切换（需用户更新 provider 配置）。
- evals 规模化样本与 baseline 对比。

## 当前状态

- minimal：图片闭环已实现并经真实运行验证（见 artifacts/task-03/ 与 BENCHMARK.md）。
- minimal：短视频抽帧 + 逐帧分析 + 聚合链路已实现；真实 Qwen 视频逐帧调用与 DSH Agent 自主编排已于任务 05 验证（见 artifacts/task-05/ 与 BENCHMARK.md）。
- minimal：多段视频统一证据时间线已实现（任务 06）：多媒体 VisualTaskSpec（source_media 数组）、`trace_multi_video.py`、像素坐标受控归一化、跨视频语义边界；规则测试 **32/32 通过**（`scripts/test_multi_video_pipeline.py`，完整结果 `artifacts/task-06/test-results.json`；任务 06 会话内修复 2 个缺陷后当时版本为 31/31，交付前补充 C8/C9 回归用例后为 32/32），真实运行证据见 `artifacts/task-06/`。
- minimal：目标时序证据与粗到细自适应采样已实现（任务 16）：`sampling_strategy` 契约（uniform baseline 零行为变化 + adaptive_coarse_to_fine）、`trace_temporal.py`、`adaptive_sampler.py`（纯逻辑：规划/预算/provenance/时序证据）、硬调用预算、采样 provenance、边界不确定性；规则测试 **27/27 通过**（`scripts/test_temporal_evidence.py`，完整结果 `artifacts/task-16/test-results.json`；构造证据回放 + 真实 fixture 抽取，无真实模型调用）；uniform vs adaptive 真实对照见 `artifacts/task-16/comparison.json`。
- minimal：coverage_aware_adaptive 覆盖感知自适应采样已实现（任务 18）：第三种策略（时间覆盖探索 + 边界细化双职责，同一硬预算；coverage provenance 区分两类调用；最大相邻采样间隔与剩余盲区可复算；任意短事件不保证发现）；规则测试 **36/36 通过**（`scripts/test_task18_coverage_sampling.py`，完整结果 `artifacts/task-18/test-results.json`）；预注册三臂评测（uniform / adaptive_coarse_to_fine / coverage_aware_adaptive，11 场景）见 `artifacts/task-18/`——真实 Qwen 评测因资源门槛未执行（PARTIAL_RESOURCE_BLOCKED），算法结论来自 deterministic replay；**不得声称任意短事件必检或真实域效果**。
- minimal（任务 17，项目级工具，只读消费本 Skill 产物）：`temporal-evidence.json` 是 Ground Truth 评分器（`scripts/score_temporal_ground_truth.py`，确定性、CPU-only、零模型调用）的标准输入；契约见 `references/temporal-evidence.md` 第 9 节。任务 16 冻结产物复评 verdict=TRADEOFF（`artifacts/task-17/comparison.json`；旧 `IMPROVEMENT` 为旧口径历史）。**`completed` 不等于语义正确；8 AI + 4 真实视频上传前不得声称真实域评分已完成。**
