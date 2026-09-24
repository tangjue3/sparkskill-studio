# 设计文档 — 目标时序证据与粗到细自适应采样（任务 16）

- 日期：2026-09-22
- 状态：已实现并验证（规则测试 27/27；uniform vs adaptive 同预算真实对照 Verdict: IMPROVEMENT，小样本不外推；一次全新 DSH headless 自主会话成功；产物见 `artifacts/task-16/`）
- 基线：分支 `master`，HEAD `04e262f7f711a4f2b1d6d3419ed1d154df03e497`，工作区干净
- 关联：`docs/plans/2026-09-21-sparkskill-studio-design.md`、`PROJECT_CONTEXT.md`、三个 Skill 的 `SKILL.md`

---

## 1. 问题

任务 04/06 落地后，视频能力有两个明确的、由真实运行暴露的弱点：

1. **`object_trace` 名不副实**：当前实现是"固定抽帧后的逐帧存在性判断"，时间线上有 first/last confirmed 与 state_changes，但**没有输出有明确语义的时序事件**——状态变化只能定位到"前后两帧之间"，且没有把这种定位精度显式建模出来。用户无法回答"目标大约什么时候出现/消失，这个答案的不确定度是多少"。
2. **抽帧策略是定长网格**：`uniform`（间隔网格或区间内均匀）不区分"状态稳定的区间"和"正在变化的区间"——边界附近每帧都可能落空，而稳定区间被反复确认，视觉调用预算被浪费在低信息量帧上。没有机制依据状态变化、低置信度或拒答区间细化证据，也没有硬性调用预算。

本任务直接服务赛事三个评分维度：

- **智能体与模型优化技术深度**：把"采样策略"变成受契约约束、可评测、带 provenance 的 Agent 决策（不是模型权重级优化，本项目明确不做后者）；
- **行业价值**：证据链审计场景真正需要的是"带不确定度的时间边界"，而不是更密集的均匀帧；
- **DGX Spark 平台适配**：统一内存下每次视觉调用都有真实成本，硬预算 + 缓存复用 + 资源守卫是平台级治理。

## 2. 架构选择：不新增第四个 Skill

**批准后的架构选择：不增加第四个 Skill。** 在现有三个 Skill 内向后兼容地增强：

| Skill | 本任务的职责变化 | 明确不做 |
| --- | --- | --- |
| `task-to-skill-compiler` | 编译视觉任务；**新增**：生成/校验可选 `sampling_strategy` 策略块（uniform / adaptive_coarse_to_fine、最大视觉模型调用次数、初始覆盖采样数、目标时间边界精度、最大细化轮数、细化触发器、provenance/temporal evidence 输出开关）；媒体来源硬门不变 | 不生成可执行代码；不改来源 provenance 规则 |
| `visual-evidence-extractor` | **保留 uniform 为正式 baseline**（`trace_video.py` 行为零变化）；**新增** adaptive coarse-to-fine 策略（`trace_temporal.py` + `adaptive_sampler.py`）；输出完整采样 provenance 与可复算的时序证据结构（`temporal-evidence.json`）；硬性调用预算 | 不重写视觉提示词体系（逐帧仍复用 `analyze_image.py`）；不做 ReID/跟踪/实时 |
| `evidence-report-generator` | **新增** temporal 报告模式：依据采样证据独立复算时序结论（首末确认、状态转换、各类计数、边界不确定性、预算与资源状态），与上游摘要交叉校验，不一致以复算为准并记 warning；报告必须显示"这是采样证据支持的时序结论，不是连续跟踪真值" | 不做视觉推理；不重新调用模型掩盖矛盾；不写采样点之间的未知时间为连续事实 |

**为什么不新增**：三个 Skill 的职责边界（编译 / 抽取 / 报告）与本任务的三个新能力（策略契约 / 采样与证据 / 时序报告）一一对应；新增第四个 Skill 只会造成职责重叠，并让 DSH 会话 catalog 出现语义模糊的能力单元。

## 3. 向后兼容

- 旧规格（无 `sampling_strategy`）→ 继续走现有 uniform 行为；`trace_video.py` / `trace_multi_video.py` / `analyze_image.py` / `generate_report.py` 既有模式**零行为变化**；
- 旧 CLI 全部保留；新能力只通过新增可选字段与新增脚本/模式提供；
- `additionalProperties: false` 契约纪律保持：新字段是显式顶层可选属性 `sampling_strategy`；
- 媒体来源与路径安全规则不变（授权根 / shell 元字符 / 凭据样式 / 路径穿越 / 系统敏感目录）；
- 非法配置明确拒绝：未知策略、非正整数/超上限/为零的调用预算、≤0 的目标边界精度、uniform 带细化参数、adaptive 缺必填项、`initial_coverage_samples > max_model_calls`。

## 4. 调用预算（硬限制）

`sampling_strategy.max_model_calls` 是**全任务硬上限**：

- 每个**不同时间戳**至多触发一次真实 Qwen 视觉调用；重复时间戳跳过并记入 `provenance.skipped_duplicate_timestamps`；
- 已有可复用证据（同轮内同时间戳缓存）不得重复调用，记 `cache_status=reused_evidence`；
- 预算耗尽 → 立即停止细化，`temporal_evidence.stopped_by_budget=true`，`budget_exhausted=true`；**预算耗尽不是"分析成功"的证据**，报告必须如实显示；
- 无法把边界区间细化到 `target_boundary_precision_ms` 以内时，输出 `residual_boundary_uncertainty_ms` 与 `target_precision_reached=false`，不伪造精确瞬间；
- 资源守卫阻塞（MemAvailable 低于阈值或 Ollama 不可达）时未执行的调用**不计为真实视觉调用**：`backend.actual_model_calls=0`，全部帧 `frame_status=failed` 并记录真实原因；
- 规则级测试注入的构造证据**不计为 Qwen 调用**，产物以 `evidence_nature` 字段与真实模型输出显式区分。
- uniform 与 adaptive 使用**相同**的最大调用预算进行公平对照（除显式比较"更少调用达到相同结果"的测试外）。

## 5. 采样 provenance

每次采样决策记录：选择的时间戳、阶段（`initial_coverage` / `refinement`）、理由（`reason`）、触发候选区间（`trigger_interval {left_ms, right_ms}` + `trigger_class_pair`）、决策时已观察状态、第几次模型调用、缓存状态（`fresh_call` / `reused_evidence` / `skipped_duplicate`）、预算状态（已用/上限/剩余）。细化停止原因单独记录（`budget_exhausted` / `max_refinement_rounds_reached` / `target_precision_reached` / `no_refinable_interval`）。

最终产物包含：策略名、配置预算、实际调用数、初始采样数、细化采样数、细化轮数、是否耗尽预算、采样决策列表、已分析时间戳、被跳过的重复时间戳、资源守卫状态、总耗时与逐阶段耗时（extraction / analysis / aggregation）。provenance 不含任何凭据（有专项测试扫描）。

## 6. 时序证据语义

`temporal_evidence{}` 至少表达：首个/最后被观察为 confirmed 的**采样**时间；相邻采样证据之间的状态变化；每个状态变化的左右时间边界；边界不确定宽度；五类计数（confirmed / not_found / abstained / low_confidence / failed）；有效分析比例；证据支持的状态片段；无法确认的时间片段；是否达到目标时间精度；是否因预算停止。

**语义红线（写入代码注释、参考文档与报告展示）**：

- "首个 confirmed 采样时间" ≠ 目标真实首次进入时间；"最后 confirmed 采样时间" ≠ 目标真实离开时间；
- 两个 confirmed 采样点之间**不得**自动断言目标连续存在；
- 状态变化只能定位到左右采样点形成的时间范围，不得伪造精确瞬间；
- failed / abstained **不得**折算成 not_found；
- 不做跨帧身份一致性、不做跨摄像头实例关联、不输出物体运动路径；
- 本功能命名与对外表述只用：目标时序证据 / temporal presence evidence / evidence-supported state transition / boundary uncertainty；**不得**命名或宣传为 ReID、目标跟踪器或实时跟踪。

## 7. uniform baseline

`trace_video.py`（任务 04）不做任何行为变化，继续作为正式 baseline：旧时间戳、帧命名、状态分类、报告规则不变。任务 16 对照中的 uniform 臂由 `trace_temporal.py --strategy uniform` 执行（复用同一批纯函数：`extract_frames.plan_sample_times`、`analyze_frame`、`trace_video.frame_class/aggregate`），因此两臂分类规则逐字节一致；uniform 臂同样记录调用数与逐阶段耗时，保证可比性。不允许为了让 adaptive 好看而削弱 uniform。

## 8. technical fixture 纪律

- 8–12 段行业视频由用户并行准备，**不是本任务前置条件**；本任务使用本机 OpenCV 生成的**合成技术 fixture**（明确标注 synthetic technical fixture）；
- fixture 覆盖：持续正向、中途出现、中途消失、出现-消失-再次出现、abstained/low-confidence 区间、单帧 failed（规则级）、预算耗尽（规则级+真实）、无状态变化、多来源输入；
- fixture 在第一次评测前**冻结生成参数与 ground truth**，记录 SHA-256（manifest + ground-truth JSON + hash 文件），之后不得重新生成或修改标签迁就模型输出；
- fixture 不作为视觉准确率或行业落地结论；若 Qwen 不能可靠理解某个 fixture，**如实记录，不得改标签**；
- fixture 不进入用户保留的 holdout 集。

## 9. uniform vs adaptive 对照

独立于 Tier-3 冻结评测的 `artifacts/task-16/comparison.json|md`：

- **公平性**：相同视频、相同目标查询、相同 Qwen Vision 模型、相同资源窗口、相同状态分类规则（同一 `frame_class` 实现）、相同最大调用预算（除显式的"更少调用达到相同结果"场景）、相同超时、不单侧重试、不删除失败样本、不在看到结果后修改 ground truth、不修改 Tier-3 任务集与 PASS 条件；
- **记录项**：最终状态是否正确（对照 ground truth）、首次/最后 confirmed 观察点、状态变化数量、状态边界范围、边界不确定宽度、实际 Qwen 调用数、总耗时、单次调用耗时、abstained/failed 数、是否耗尽预算、是否出现虚假连续性结论；
- **不预设 adaptive 必须 PASS**：若无改善，Verdict 写 `PARTIAL` 或 `NO_IMPROVEMENT` 并保留真实结果；
- 技术 fixture 结果不得外推为真实仓储准确率。

## 10. 真实 Qwen 与 DSH 自主演示

资源门槛满足时执行一次全新 `dsh --profile headless` 会话：会话内 Agent 自主发现/加载 Skill → StepFun 文本链路生成带 adaptive 策略的合法 VisualTaskSpec → Schema 校验 → 运行 adaptive 视频证据链 → 本地 Qwen Vision → 生成 provenance / 时序证据 / 报告。保存 reasoning、工具调用、原始模型返回与最终产物。只允许使用本任务 fixture 或用户已明确上传 dev 的素材；禁止 holdout。门槛不满足则保留规则测试结果并生成资源阻塞报告，不得伪造。

## 11. 不做事项

- 不做实时视频、目标 ReID、实例跟踪、跨摄像头关联、运动路径输出；
- 不新增第四个 Skill；不改 Evidence Workbench（新 artifact 接入界面留给后续任务）；
- 不修改 Tier-3 冻结任务集、评分器（v1/v2）与 PASS 条件，不改任务 07/08/09 冻结产物；
- 不停止/重启任何服务，不安装依赖，不下载模型，不联网，不改全局配置，不读取凭据；
- 不做模型权重级优化声称（量化/vLLM/投机解码与本任务无关）。

## 12. 后续接入用户的 dev/holdout Evidence Pack

- dev 素材：用户明确上传到 dev 的素材 → 作为 `source_media`（媒体来源硬门仍然适用：必须是当前请求显式提供）；用同一 `sampling_strategy` 契约声明策略即可零改动复用；
- holdout：本任务不得触碰；接入 holdout 前需要用户提供 holdout 的 ground-truth（出现时段标注）与使用授权，评测口径需要单独的 ground-truth 评分器（时间/位置准确率），本任务只实现了规则级 + fixture 级 ground truth 对照，**尚未实现**逐样本真实 ground-truth 准确率评分；
- 工作台接入：本任务明确不修改 Evidence Workbench；`artifacts/task-16/` 的产物按后续独立任务决定是否进 manifest。
