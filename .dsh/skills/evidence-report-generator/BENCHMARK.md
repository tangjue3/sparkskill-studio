# BENCHMARK — evidence-report-generator

> 图片部分数字来自 2026-09-21 真实运行。规则单测使用构造输入（明确标注，非模型输出）；
> 端到端数字来自真实模型链路产物。
> 视频部分（任务 04）数字来自 2026-09-21 真实运行：输入为 trace_video.py 产出的真实时间线
> （资源守卫降级）与任务 03 真实证据回放。
> 任务 05 增补：由 **DSH 自主 Agent** 在会话内对**真实 Qwen 视频时间线**生成的两份视频报告（正向 completed / 负向负面结论）。

## 图片测试结果（2026-09-21）

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| 1 | 正向证据 → 报告 | 规则单测（构造） | **通过**：status=completed，conclusion 由证据字段组成 |
| 2 | 负面证据（object_found=false + abstention_reason）→ 报告 | 规则单测（构造） | **通过**：status=abstained，不声称存在 |
| 3 | 低置信证据（confidence=0.2 < 0.5）→ 报告 | 规则单测（构造） | **通过**：status=abstained |
| 4 | 空证据数组 → 报告 | 规则单测（构造） | **通过**：status=failed，conclusion=null |
| 5 | 真实正向链路报告 | **真实模型输出** | **通过**：`artifacts/task-03/positive-report.json`，status=completed |
| 6 | 真实负向链路报告 | **真实模型输出** | **通过**：`artifacts/task-03/negative-report.json`，负面结论无幻觉 |
| 7 | E2E 报告 | **真实模型输出** | **通过**：`artifacts/task-03/e2e/report.json`，warnings 透明暴露缺口 |

小计：7 项测试，7 项通过，0 项失败。

## 视频模式测试结果（2026-09-21，任务 04）

测试套件：`.dsh/skills/visual-evidence-extractor/scripts/test_video_pipeline.py`（B1/B2/B3/B6 覆盖本 Skill 视频规则）；
完整结果：`artifacts/task-04/test-results.json`。

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| V1 | 视频报告：目标存在样例 | 任务 03 真实正向证据回放为时间线 | **通过**：status=completed，结论引用首/末确认时间与确认帧数，无越证 |
| V2 | 视频报告：目标不存在样例 | 任务 03 真实负向证据回放为时间线 | **通过**：status=completed 负面结论，未声称存在，无虚假路径 |
| V3 | 视频报告：证据不足样例 | 构造输入（明确标注） | **通过**：status=abstained，abstention_reason 非空 |
| V4 | 视频报告：状态一致性 + 交叉校验 | 任务 03 真实证据回放 + 注入不一致 | **通过**：一致运行 status 匹配；注入冲突后独立复算正确且 warnings 记录冲突 |
| V5 | 视频报告：failed 不作存在性断言 | **真实运行产物** `artifacts/task-04/timeline.json`（资源守卫降级，6 帧 failed） | **通过**：status=failed，conclusion 明确"不对目标作任何存在性断言"，abstention_reason 记录资源阻塞原因 |

小计：视频模式 5 项测试，5 项通过，0 项失败。

## 任务 05：DSH 自主 Agent 运行（2026-09-21，真实 Qwen 视频时间线输入）

两次 headless 会话内 Agent 自主调用 `generate_report.py --mode video`，输入为 `trace_video.py 产出的**真实** Qwen 视频时间线（非构造、非回放）。

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| W1 | 正向视频报告（目标=太阳） | **真实 Qwen 时间线**（5 confirmed + 1 failed），`artifacts/task-05/timeline.json` | **通过**：`video-report.json` status=completed，conclusion 引用首次 0.0ms/最后 4000.0ms/5 帧确认，可回溯 frame_path |
| W2 | 负向视频报告（目标=紫色大象） | **真实 Qwen 时间线**（6 not_found），`artifacts/task-05/negative-timeline.json` | **通过（正确负面）**：`negative-report.json` status=completed，conclusion="未确认目标存在（负面结论，非肯定性断言）"，confidence=0.0，未声称存在 |
| W3 | 状态独立复算 + 交叉校验 | 真实时间线 | **通过**：两份报告复算 status 与 timeline.summary.overall_status 一致；正向 failed 帧被如实计入 warnings，不作存在性断言 |
| W4 | 反幻觉（failed 帧 / 负面结论） | 真实时间线 | **通过**：正向 1 failed 帧不进 confirmed、不出现在结论的"确认"里；负向 6 not_found → 负面表述，无虚假目标/框/路径/置信度 |

小计：任务 05 自主运行 4 项，4 项通过，0 项失败（视频模式累计 9 项 / 9 项通过）。

## 反幻觉规则核验（真实运行）

- 无证据 → failed，conclusion=null：核验通过（图片测试 4）。
- object_found=false → 不声称存在：核验通过（图片测试 2/6/7；视频测试 V2/V5）。
- abstention_reason 非空 → status=abstained：核验通过（图片测试 2；视频测试 V3）。
- conclusion 不添加输入外事实：核验通过（conclusion 仅引用 description/evidence_text/source_media/confidence/时间线条目）。
- 视频结论可回溯到具体帧：核验通过（V1 结论引用 timeline 帧时间戳；timeline 每项含 frame_path）。
- 视频状态两套实现交叉校验：核验通过（V4，注入不一致被复算纠正并记录 warnings）。

## 耗时（真实测量）

| 阶段 | 耗时 |
| --- | --- |
| 图片报告生成（本地，无模型调用） | 0.031 s |
| 视频报告生成（本地，无模型调用） | 0.01 s |

## 模型/工具错误

- 无。本 Skill 为纯本地规则引擎，不调用模型。

## 结论

- 图片证据一致性规则 7/7 通过；视频报告规则 5/5 通过；均未出现幻觉或越证。
- 视频模式下报告状态与时间线状态交叉校验机制有效（V4）。
- 报告生成不是链路时延瓶颈（0.01–0.03 s）。
- 输入为资源阻塞的真实时间线时，报告如实输出 failed 且不作存在性断言（V5）。
- **任务 05**：对两份**真实 Qwen 视频时间线**（正向 completed / 负向负面结论）自主生成报告，4/4 通过；状态复算与交叉校验一致，无幻觉、无越证、无虚构存在性断言。

## 任务 06：多视频统一时间线报告（2026-09-21，DSH 自主 Agent 真实运行）

输入为 `trace_multi_video.py` 产出的真实全局时间线（正向 8/8 confirmed；负向 8/8 not_found），由会话内 Agent 自主调用 `generate_report.py --mode multi-video` 生成。

| # | 测试 | 结果 | 说明 |
| --- | --- | --- | --- |
| MV1 | 正向多视频报告 | **通过** | `artifacts/task-06/multi-video-report.json`：status=completed，每来源独立状态与统计，confirmed_entry_count=8，sources_with_confirmation=[video-a, video-b] |
| MV2 | 负向多视频报告 | **通过（正确负面）** | `artifacts/task-06/negative-report.json`：status=completed，结论为负面表述，confidence=0.0，无存在性断言 |
| MV3 | 跨视频语义限制 | **通过** | 结论仅用 matched target query / visually consistent with target description / confirmed in source A/B；semantic_limitation_note 与 semantic_limitations 随报告输出；禁用措辞 0 命中 |
| MV4 | 状态独立复算 + 交叉校验 | **通过** | 报告 status 与 derive_multi_video_status 复算及 global_summary.overall_status 三方一致（正/负均 completed）；注入不一致被复算纠正（规则测试 D5） |
| MV5 | 规则测试（D1–D6） | **通过** | 正向措辞/负向结论/abstained/failed/交叉校验/可回溯 6 项全过（`artifacts/task-06/test-results.json`） |

小计：任务 06 多视频报告 5 项，5 项通过，0 项失败（多视频模式累计 5 项 / 5 项通过）。

### 耗时（真实测量）

| 阶段 | 耗时 |
| --- | --- |
| 多视频报告生成（本地规则引擎，无模型调用） | ≈0.01 s |

## Tier-3 对照评测中的报告生成表现（任务 07，2026-09-21）

with-skill 侧视觉任务的报告均由本 Skill 生成（E1/E3 多视频报告含分来源状态 + 全局摘要 +
跨视频语义限制声明；E2/E4 负面结论；E5 拒答）；状态独立复算与 global_summary 交叉校验一致
（回归 R7 复算 completed=completed）。baseline 侧无报告契约（E2/E4/E5 未提供置信度字段）。
完整对照见根目录 `BENCHMARK.md`。

## Tier-3 评测器版本化影响（任务 09）

v2 评分器未改动报告相关规则（S2/C 系列不变）；with-skill 侧报告任务判定不变。完整历史见根目录 `BENCHMARK.md`。

## 时序证据报告模式（任务 16，2026-09-22；规则测试，无模型调用）

新增 `--mode temporal` / `--mode temporal-multi`（auto 判别）：输入 `trace_temporal.py` 产出的 temporal-evidence.json。本引擎按时间线条目**独立复算**（`derive_temporal_evidence`，自有实现，与 adaptive_sampler 两套互检）首末 confirmed 观察时间、五类计数、状态转换与不确定宽度；与上游 `temporal_evidence` / `sampling_provenance` 交叉校验，不一致以复算为准并记 warnings；实际调用超过配置预算记 warning。报告必显：采样策略、预算与实际调用、是否耗尽、是否达到目标精度、“采样证据支持的时序结论，不是连续跟踪真值”。规则测试 T18–T21（含于 `test_temporal_evidence.py` 27/27，完整结果 `artifacts/task-16/test-results.json`）：

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| T18 | 独立复算（confirmed 数/首末确认时间/计数/status） | 构造证据回放（fixture + 脚本化证据，非模型输出） | **通过**：报告复算与手工复算一致 |
| T19 | 注入上游错误摘要（first_confirmed=-999、转换数=42） | 构造输入 | **通过**：warnings 记“交叉校验不一致”，复算值未被污染 |
| T19b | 注入超预算计数（999 > 16） | 构造输入 | **通过**：warnings 记“调用预算异常” |
| T20–T21 | 多来源时序报告 | 构造证据回放（两 fixture + offset 5000） | **通过**：per-source 独立复算；允许措辞齐全；禁用措辞 0 命中；跨视频语义限制显示 |

## Coverage-Aware 时序证据报告（任务 18，2026-09-22；规则测试，无模型调用）

temporal 报告模式对第三种策略 `coverage_aware_adaptive` 的透传与附加显示（策略值透传，无分支逻辑改动；附加字段为增量）：

| 检查 | 输入 | 结果 |
| --- | --- | --- |
| 覆盖摘要透传 | coverage_aware_adaptive 运行产物 | **通过**：报告含 `coverage_summary`（覆盖探索/边界细化/初始覆盖调用、覆盖目标、最大相邻间隔初始/最终值、剩余盲区、两个限制声明） |
| 覆盖限制句 | 同上 | **通过**：结论追加"不保证发现任意短事件，宽度小于最大相邻采样间隔的事件可能被漏检"（不断言连续存在句保留） |
| 旧策略报告不变 | uniform / adaptive 产物 | **通过**：既有字段与结论结构不变（任务 16 T18/T19/T19b 回归 27/27） |
| 多来源覆盖报告 | 两 fixture + coverage 策略 + offset 5000 | **通过**：per-source 独立复算；允许措辞齐全；禁用措辞 0 命中；共享预算语义正确 |

小计：任务 18 时序报告 4 项检查，4 项通过，0 项失败（完整结果 `artifacts/task-18/test-results.json`，C07/C26/C28 等）。

## dev Evidence Pack 时序报告：任务 19B（2026-09-22/23；真实运行）

- temporal 报告模式在 27 次真实三臂运行 + 1 次 DSH 自主会话（WEB01）中全部正常产出：独立复算与上游 temporal_evidence 交叉校验无不一致 warning；语义红线句（"采样证据支持的时序结论，不是连续跟踪真值"）与 coverage 限制句（"不保证发现任意短事件"）逐产物命中（测试断言）；
- 报告结论与本轮基线发现一致：uncertain 区拒答缺失（AI06）、遮挡区过度确认（AI04）、真实域早期误报（WEB01/WEB03）均如实进入报告结论，未粉饰；
- 完整证据：`artifacts/task-19/predictions/<样本>/<臂>/temporal-report.json`、`artifacts/task-19/dsh-session/final-report.json`。
