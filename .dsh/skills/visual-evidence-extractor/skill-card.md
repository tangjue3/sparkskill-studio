# Skill Card — visual-evidence-extractor

| 项 | 内容 |
| --- | --- |
| name | visual-evidence-extractor |
| status | minimal（单图片 + 单段短视频 + 多来源视频证据聚合 + 目标时序证据与粗到细自适应采样闭环；跨摄像头身份关联不做） |
| 一句话职责 | 合法 VisualTaskSpec + 本地图片 / 单段短视频 / 多来源视频 → 本地 Qwen Vision 结构化证据（视频为抽帧逐帧时间线，多来源合并为统一全局时间线；支持 uniform baseline / adaptive_coarse_to_fine / coverage_aware_adaptive 自适应采样 + 采样 provenance + 时序证据 + 覆盖探索与剩余盲区声明） |
| 输入 | VisualTaskSpec JSON + 本地媒体：① 单个图片路径；② 单个短视频路径；③ `source_media` 来源对象数组（多段视频，`[{source_id, path, location, time_offset_ms}, ...]`；旧版单路径字符串仍受支持并包装为单一来源 media-0）。可选 `sampling_strategy`（任务 16/18）：`{strategy: uniform\|adaptive_coarse_to_fine\|coverage_aware_adaptive, max_model_calls, initial_coverage_samples, target_boundary_precision_ms, max_refinement_rounds, coverage_gap_target_ms, coverage_call_reserve, refinement_triggers, require_sampling_provenance, require_temporal_evidence}`；缺失 = 旧版 uniform 行为；coverage 策略必填 coverage_gap_target_ms/coverage_call_reserve 且 initial+reserve ≤ max_model_calls |
| 输出 | 图片：证据 JSON（`references/evidence-schema.md`）；单视频：timeline.json（`references/video-evidence.md`）；多视频：global-timeline.json + per-source/`<source_id>`-timeline.json（`references/multi-video-evidence.md`）；时序证据：temporal-evidence.json（`references/temporal-evidence.md`） |
| 视觉后端 | DGX Spark 本地 Ollama：`modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`（vision）。当前 DSH 配置下 StepFun 不声明图片输入，因此视觉推理不走 StepFun |
| 正向触发 | 持有合法 VisualTaskSpec（requires_visual_input=true，task_type ∈ {object_trace, object_presence}）且提供可读的本地媒体 |
| 负向触发 | 规格不合法（缺 target.description / requires_visual_input≠true / task_type 不支持）；媒体不存在或不可读；来源数组 source_id 重复 / time_offset_ms 为负 / path 未通过安全校验；采样策略非法（未知策略 / 非法预算 / ≤0 精度 / uniform 带细化或覆盖参数 / adaptive 带 coverage 专属字段或缺必填 / coverage 缺必填 / initial(+reserve)>budget） |
| 拒答条件 | object_found=false 必须填 abstention_reason；confidence<阈值标记 evidence_sufficient=false 并记入 gaps；单帧后端失败记 failed 不中断其他帧；统一内存不足时资源守卫阻止加载并整体降级 failed；预算耗尽停止细化并如实报告（不算“分析成功”） |
| 媒体策略 | 单图片：analyze_image.py 直接分析。视频：extract_frames.py 抽帧（间隔/最大帧数/起止时间可配）→ trace_video.py 复用 analyze_image.py 逐帧分析（未重写视觉提示词）→ 聚合时间线。多视频：trace_multi_video.py 依次复用 trace_video.py 单段能力（未重写视频处理逻辑）。时序证据：trace_temporal.py + adaptive_sampler.py（规划/预算/provenance/时序证据纯逻辑） |
| 时间线语义 | 每来源独立时间线，保留 source_id 与原视频时间戳；global = 原时间戳 + time_offset_ms，按 (global_timestamp_ms, source_id) 排序合并为统一全局时间线。**全局时间线是证据聚合，不是跨摄像头身份追踪** |
| 时序证据语义（任务 16） | 首/末 confirmed 是采样观察时间（≠真实进入/离开）；采样点之间不断言连续存在；状态变化只定位到左右采样点范围 `[left_ms,right_ms]`，`uncertainty_width_ms=right_ms-left_ms`；abstained/low_confidence/failed 不退化为 not_found；不做跨帧身份一致性、不输出运动路径；不是 ReID/目标跟踪器/实时跟踪 |
| 调用预算（任务 16/18） | `max_model_calls` 是硬上限：同时间戳至多一次真实调用、可复用证据不重复调用、重复时间戳记 skipped_duplicate、预算耗尽即停；资源守卫阻塞时未执行调用不计为真实视觉调用；uniform / adaptive / coverage 都如实记录实际调用数与逐阶段耗时。coverage_aware_adaptive 在初始覆盖后用 ≤ coverage_call_reserve 次调用做时间覆盖探索（largest-gap-first 压缩未观测间隔），剩余预算做边界细化；provenance 区分 initial_coverage_calls / coverage_exploration_calls / boundary_refinement_calls 并记录最大相邻采样间隔与 underobserved_intervals；显式声明不保证发现任意短事件 |
| 跨视频语义边界 | 同一目标查询在多来源中被确认时，只允许 matched target query / visually consistent with target description / confirmed in source A / confirmed in source B；禁止 same physical instance / moved from A to B / carried by the same person / entered another camera / identity matched；`semantic_limitations` 随产物输出 |
| 坐标规范 | 模型返回像素坐标且四元数值、全部 >1、x1<x2/y1<y2、不越界、帧尺寸可读时确定性归一化并记录 raw/format/applied/帧尺寸；否则 bbox 置 null + warning，不重跑模型 |
| 状态四态 | confirmed / not_found（确定性负面）/ abstained（证据不足拒答）/ failed（帧失败或资源阻塞）/ low_confidence（object_found=true 但置信度不足）；negative 结论不得表述为存在性断言 |
| 安全边界 | 禁身份/年龄/国籍/关系/意图推断；禁人脸识别；禁跨镜头身份追踪；禁伪造 bounding_box；禁把连续帧解释为同一对象；OpenCV 仅作底层抽帧工具；provenance 落盘前凭据自检；不输出凭据；不冒充 NVIDIA 官方 Skill |
| 资源守卫 | 调用视觉模型前检查 /proc/meminfo MemAvailable，低于阈值（默认 40 GiB；Qwen 加载约需 34.6 GB）时不加载并如实降级 failed（不停止 MiniMax-H3、不 OOM、不装依赖） |
| 评测 | `evals/evals.json`；实测记录 `BENCHMARK.md`；项目级 Tier-3 对照评测（baseline vs with-skill）中本 Skill 5/5 视觉任务正确被发现并调用（任务 07），最终 v2 评分 Verdict PASS（历史 PARTIAL 保留） |
| 已验证测试数字 | 多视频规则测试 32/32（`artifacts/task-06/test-results.json`）；任务 04 视频规则回归 16/16；任务 05 真实 Qwen 逐帧 7/7（D1–D7）；任务 06 真实多视频运行 9/9（M1–M9）；任务 16 时序证据与自适应采样规则测试 27/27（`artifacts/task-16/test-results.json`，无真实模型调用）；任务 18 coverage_aware_adaptive 规则测试 36/36（`artifacts/task-18/test-results.json`，除 C30 复用 replay 产物外无模型调用） |
| 脚本 | `scripts/analyze_image.py`（图片）、`scripts/extract_frames.py`（抽帧）、`scripts/trace_video.py`（单视频时间线）、`scripts/trace_multi_video.py`（多视频全局时间线）、`scripts/adaptive_sampler.py`（任务 16/18 纯逻辑）、`scripts/trace_temporal.py`（任务 16/18 执行器）、`scripts/skill_env.py`（cv2 解释器切换）、`scripts/test_video_pipeline.py`、`scripts/test_multi_video_pipeline.py`、`scripts/test_temporal_evidence.py`、`scripts/test_task18_coverage_sampling.py`（测试，纯标准库） |
| 后续阶段（未实现） | evals 规模化样本与多轮重复；baseline 对比的统计显著性；StepFun 侧图片能力可用后的路由切换（需用户更新 provider 配置）；逐样本 ground-truth 评分器已建立（任务 17，项目级 `scripts/score_temporal_ground_truth.py`；技术 fixture 重评分 verdict=TRADEOFF）；待用户 8 AI + 4 真实视频 Evidence Pack 上传后接入真实域评分 |
| 非目标 | 不做任务编译；不生成报告；不做跨摄像头身份/实例关联；不做实时多摄像头；不做 ReID/目标跟踪；不冒充 NVIDIA 官方 Skill |
