# Skill Card — evidence-report-generator

| 项 | 内容 |
| --- | --- |
| name | evidence-report-generator |
| status | minimal（单图片证据 + 单视频时间线报告 + 多来源视频统一时间线报告 + 目标时序证据报告（含 coverage_aware_adaptive 覆盖摘要与限制声明）；跨摄像头身份追踪报告不做） |
| 一句话职责 | 视觉证据 JSON / 视频证据时间线 / 多视频全局时间线 / 时序证据文档 → 反幻觉最终报告（completed / abstained / failed），结论只由输入证据字段组成 |
| 输入 | VisualTaskSpec JSON + 证据 JSON（对象或数组）、视频时间线 JSON（timeline.json）、多视频全局时间线 JSON（global-timeline.json）或时序证据文档（temporal-evidence.json） |
| 输出 | 报告 JSON。图片：`references/report-schema.md`；单视频：source_video/duration_ms/sampled_frames/target_query/timeline/summary/status/conclusion/abstention_reason/warnings；多视频：sources[]（每来源独立状态与统计）+ global_summary + timeline + semantic_limitations + status + conclusion；时序（任务 16）：sampling_strategy/vision_call_budget/actual_model_calls/budget_exhausted/target_boundary_precision_ms/target_precision_reached/residual_uncertainty_ms + 独立复算 summary + semantic_limitation_note |
| 正向触发 | 收到 visual-evidence-extractor 产出的合法证据（图片证据对象/数组、视频时间线、多视频全局时间线或时序证据文档） |
| 负向触发 | 证据缺失 object_found 字段；输入不是证据对象/数组；视频时间线缺少非空 timeline 数组；多视频全局时间线缺少 global_timeline/sources；时序证据文档缺少 timeline+sampling_provenance+temporal_evidence（或 global_timeline+sources+global_temporal_evidence） |
| 拒答条件 | 无视觉证据 → status=failed，conclusion=null，不作存在性断言；object_found=false → 不得声称目标存在，只给负面结论；abstention_reason 非空 → status=abstained；object_found=true 但 confidence 低于阈值 → status=abstained；视频/时序无 analyzed 帧 → failed |
| 反幻觉规则 | 结论只能由输入证据字段组成，不得添加输入中不存在的事实；视频/多视频/时序结论必须可回溯到具体帧（frame_path）；failed 帧不进 confirmed、不出现在结论的“确认”里；负面结论不得表述为存在性断言 |
| 状态复算与交叉校验 | 报告状态按帧/全局条目/时间线条目独立复算，并与 timeline.summary.overall_status / global_summary.overall_status / temporal_evidence 交叉校验；不一致以复算结果为准并记入 warnings（两套实现互检，防单点规则错误）；时序模式还校验实际调用数与预算（越界告警），并透传采样策略与覆盖摘要（coverage_aware_adaptive：覆盖探索/边界细化/初始覆盖调用、最大相邻采样间隔、剩余盲区与“不保证发现任意短事件”声明） |
| 时序证据报告（任务 16） | 独立复算首末 confirmed 观察时间、状态转换、五类计数、边界不确定性；必须显示采样策略/预算与实际调用/是否耗尽/是否达到目标精度/“这是采样证据支持的时序结论，不是连续跟踪真值”；首末 confirmed 是采样观察时间（≠真实进入/离开）；采样点之间不断言连续存在；abstained/low_confidence/failed 不退化为 not_found |
| 多视频语义边界 | 结论只允许 matched target query / visually consistent with target description / confirmed in source A / confirmed in source B；**必须显示跨视频语义限制**：不断言同一个物理实例（same physical instance）、不宣称从来源 A 移动到来源 B（moved from A to B）、不做身份匹配（identity matched）；全局时间线是证据聚合，不是跨摄像头身份追踪 |
| 安全边界 | 禁身份/年龄/国籍/关系/意图推断；不做视觉推理（属 visual-evidence-extractor）；不执行任意模型生成代码；不冒充 NVIDIA 官方 Skill |
| 评测 | `evals/evals.json`；实测记录 `BENCHMARK.md`；项目级 Tier-3 对照评测中 with-skill 侧视觉任务报告均由本 Skill 生成（任务 07/08），v2 评分未改动报告相关规则 |
| 已验证测试数字 | 图片规则 7/7；视频模式 5/5（V1–V5）；任务 05 真实 Qwen 时间线报告 4/4（W1–W4）；任务 06 多视频报告 5/5（MV1–MV5）；任务 16 时序报告规则测试（T18–T21，含于 27/27） |
| 脚本 | `scripts/generate_report.py`（纯标准库规则引擎，无模型调用；`--mode auto\|image\|video\|multi-video\|temporal\|temporal-multi`） |
| 后续阶段（未实现） | 可复现报告版本记录；跨来源证据链的进一步结构化（不做跨摄像头身份断言） |
| 非目标 | 不做视觉推理；不做任务编译；不做跨摄像头身份追踪报告；不冒充 NVIDIA 官方 Skill |
