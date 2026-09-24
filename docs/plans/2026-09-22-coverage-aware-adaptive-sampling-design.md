# 设计文档 — Coverage-Aware Adaptive Sampling v2 与预注册三臂评测（任务 18）

- 日期：2026-09-22
- 状态：预注册冻结（阶段 A）；实现与评测见阶段 B 及 `artifacts/task-18/`
- 基线：分支 `master`，HEAD `929314365c3087f0756b1f0cd285669ede0feaa7`（任务 17 提交），工作区干净，恢复 tag `pre-task13-deploy-4c4c3ca` 保留，无 remote
- 关联：`docs/plans/2026-09-22-temporal-evidence-adaptive-sampling-design.md`（任务 16）、`docs/plans/2026-09-22-evidence-pack-ground-truth-scoring-design.md`（任务 17）、`schemas/visual-task-spec.schema.json`、三个 Skill 的 `SKILL.md`、`artifacts/task-16/`、`artifacts/task-17/`

---

## 0. 本任务的定位

任务 16 建立 `uniform` / `adaptive_coarse_to_fine` 两种采样策略与硬调用预算；任务 17 用独立 Ground Truth 评分器对任务 16 冻结数据重评分，得到严格结论 `TRADEOFF`，并量化了 adaptive 的**覆盖盲区**。本任务（任务 18）新增第三种独立版本化的采样策略 `coverage_aware_adaptive`，用**预注册冻结的三臂评测**（uniform / adaptive_coarse_to_fine / coverage_aware_adaptive）在相同媒体、查询、Ground Truth、模型与预算下度量它，并用任务 17 冻结评分器（经兼容适配层）确定性评分。

**工程实现成功与算法 benchmark verdict 必须分开报告**：前者指契约、预算、provenance、测试与回归全部达标；后者只由预注册 verdict 规则从冻结指标计算，不预设、不调参、不删场景。

## 1. 任务 17 暴露了什么覆盖盲区

任务 17 对任务 16 冻结产物重评分（`artifacts/task-17/comparison.json`，fairness gate 10/10，pack 级 verdict=TRADEOFF）暴露三个事实：

1. **adaptive 的初始覆盖可能完全错过窄事件/窄不确定区**：`abstain-zone` 场景中 adaptive 的 4 个初始覆盖点（0 / 2666.667 / 5333.333 / 8000 ms）全部落在 GT uncertain 区间 [3000, 5000] ms 之外，没有任何触发信号，细化轮数=0，`unreached_uncertain_segments`=1（uniform 为 0）。**覆盖盲区被量化为：采样网格的相邻间隔大于目标时间尺度时，整个区间对策略不可见。**
2. **触达 uncertain 不等于适当拒答（模型语义校准问题是独立的）**：uniform 臂触达了 uncertain 区间，但真实 Qwen 对 3 个低对比度帧给出确定性负面，形成 3/3 `overclaim_on_uncertain`。这是模型校准失败，不是采样覆盖失败。
3. **效率收益真实存在但不覆盖语义缺口**：adaptive 34 vs uniform 60 次调用、平均边界误差 138.333 vs 150.0 ms（严格更好项），但漏检/未触达类指标出现回归（`more_unreached_uncertain_segments`），故严格口径为 TRADEOFF 而非 IMPROVEMENT。

此外任务 17 重评分显示 `reappear` 场景 adaptive 仅 2/3 边界在容差内（uniform 3/3）——预算在覆盖与细化之间的分配也影响边界质量。

## 2. 为什么触发式边界细化无法发现完全未采样的窄事件

`adaptive_coarse_to_fine` 的细化候选只来自**已观测证据**：相邻采样对类别不同（state_change），或某一侧采样是 abstained / low_confidence / failed。若一个窄事件（或窄 uncertain 区）完全落在两个粗采样点之间：

- 事件前后的两个采样点类别相同（例如都是 `not_found`）→ 不产生 state_change 候选；
- 没有任何采样点落在事件内 → 不可能出现 abstained/low_confidence/failed 样本；
- 因此**候选区间集合为空**，策略没有任何可细化的对象，事件对策略完全不可见。

结论：**触发式细化是"证据驱动"的，它只能放大已经看到信号的位置；对没有任何信号的未观测区间，它在结构上不可能发现窄事件。** 这不是实现缺陷，是范式边界——需要一种"覆盖驱动"的职责来压缩未观测时间间隔。本任务量化并缓解该盲区，但不声称消除它（见 §7）。

## 3. 覆盖探索与边界细化的职责分离

| 职责 | 驱动信号 | 目标 | 决策对象 | 失败模式 |
| --- | --- | --- | --- | --- |
| **时间覆盖探索**（coverage exploration） | 采样几何：相邻采样间隔宽度（与证据语义无关） | 压缩最大相邻采样间隔到覆盖目标以内 | 最大的未观测间隔（largest-gap-first 二分） | 间隔已低于目标仍漏掉更短事件（覆盖分辨率极限） |
| **事件边界细化**（boundary refinement） | 证据语义：状态变化 / 拒答 / 低置信 / 失败 | 缩小状态转换括号宽度到目标边界精度 | 触发器命名的相邻区间（二分中点） | 预算不足时括号保持宽度（如实报告残存不确定性） |

分离原则：

- 覆盖探索**不看证据类别**（避免"没有信号就不探索"的结构性盲区）；边界细化**不看间隔几何**（保持任务 16 行为逐字节不变）；
- 两者的调用在 provenance 中用不同 `phase`（`coverage_exploration` vs `refinement`）与 `purpose`（`temporal_coverage` vs `boundary_refinement`）显式区分，可分别复算；
- 覆盖探索发现状态变化后，**剩余预算**才进入边界细化（§4）。

## 4. 硬调用预算如何在两类职责之间分配

单一硬预算 `max_model_calls`（全任务上限，多来源共享），分三个阶段确定性管理：

1. **初始覆盖**（`initial_coverage_samples` 个点，与 adaptive 同公式）；
2. **覆盖探索**：最多 `coverage_call_reserve` 次新鲜调用（超出初始覆盖的部分），每次压缩当前最大的未观测间隔，直到：所有相邻间隔 ≤ `coverage_gap_target_ms`（目标达成）、储备用尽、预算耗尽、或无合法候选（间隔已窄于帧分辨率，记 `coverage_no_refinable_gap`）；
3. **边界细化**：与 adaptive 完全相同的触发器二分逻辑，使用**剩余预算**（`max_model_calls − 已用`）与 `max_refinement_rounds`。

硬性不变式（实现与测试双重断言）：

- `initial_coverage_samples + coverage_call_reserve ≤ max_model_calls`（编译期/执行期同口径拒绝，覆盖配置不得超出总预算）；
- 任意路径 `actual_model_calls ≤ max_model_calls`（CallBudget 账本）；
- `coverage_calls_used ≤ coverage_call_reserve`；
- 重复时间戳不重复调用、可复用证据不重复调用（不计入新鲜调用）；
- 预算耗尽即停，`budget_exhausted` 如实报告，**不算"分析成功"**。

## 5. “最大相邻采样间隔”的定义

**定义（可复算）**：设已分析时间戳集合为 `T`（升序去重），媒体时长 `D`，观测点集 `O = {0, D} ∪ T`。相邻采样间隔为 `O` 中相邻点对的差值；**最大相邻采样间隔** = 这些间隔的最大值（ms）。初始值与最终值分别记录（初始值 = 初始覆盖完成后的最大间隔；最终值 = 运行结束时的值）。

选择把媒体边界 0 与 D 纳入观测点集的理由：初始覆盖被预算截断时，`[0, 首个采样]` 与 `[末个采样, D]` 同样是未观测区间；纳入后该指标是"最大未观测时间窗口"的保守度量，可由 `(analyzed_timestamps, duration_ms)` 精确复算（专项测试断言）。

## 6. 覆盖分辨率能说明什么、不能说明什么

**能说明**：在已完成的采样下，不存在宽度超过 `最大相邻采样间隔` 的完全未观测时间窗口；事件/不确定区若宽度 ≥ 最大间隔且位置合适，至少有一个采样点落入其中（**必要非充分条件**——是否被正确判定仍取决于模型语义）。

**不能说明**：

- 不能说明所有长于最大间隔的事件都被发现（模型可能漏检或误判）；
- 不能说明两个采样点之间目标连续存在（采样点之间只有"未采样/未知"）；
- 不能说明覆盖"百分比"——采样点覆盖不是连续时间全覆盖，禁止使用 "coverage=100%" 类表述；本策略只报告确定的间隔几何事实；
- 不能把覆盖改善当作语义正确（覆盖与模型校准是两个问题，§13）。

## 7. 为什么不能保证发现任意短事件

有限预算 `N` 次采样在时长 `D` 内，最大相邻间隔的理论下界约为 `D/(N−1)`（端点含内）。任何宽度小于最大相邻采样间隔的事件都可能完整落在两个相邻采样点之间（`twin-short-events` 场景专门证明这一点：600ms 事件落在 1333ms 间隔内可被漏检）。即便间隔小于事件宽度，发现仍依赖模型在该点的正确判定。因此产物必须显式携带：

```text
arbitrary_short_event_detection_guaranteed: false
events_shorter_than_max_sampling_gap_may_be_missed: true
```

且 `underobserved_intervals`（结束时仍宽于覆盖目标的间隔清单）逐条列出剩余盲区。

## 8. 新策略如何保持旧策略行为不变

- **代码路径分离**：`uniform` 继续走 `extract_frames.plan_sample_times` 规划（零改动）；`adaptive_coarse_to_fine` 继续走"初始覆盖 + 触发器细化"同一循环（零改动）；`coverage_aware_adaptive` 是 `run_source_temporal` 中新增的独立分支（初始覆盖之后、细化之前插入覆盖探索阶段），旧分支的控制流不被修改；
- **Schema 向后兼容**：`sampling_strategy` 仍可选；缺失 = 旧版 uniform 行为；新字段只在新策略下合法（uniform 与 adaptive 都拒绝 coverage 专属字段，属"不支持组合"）；
- **输出兼容**：旧策略产物结构不变（仅在 `decisions[]` 增加 `purpose` / `candidate_interval` 两个附加字段，`temporal_evidence` 增加可选 `coverage` 块；任务 17 评分器 G7 只校验既有字段，附加字段不影响旧臂评分）；
- **回归证明**：任务 16 的 27/27 测试、任务 04 16/16、任务 06 32/32、M1–M8 10/10、v2 评分器 17/17、工作台 26/26 全部重跑；另加专项测试断言 uniform/adaptive 在相同输入下的调用数、阶段、停止原因与任务 16 冻结行为逐项一致。

## 9. 新配置如何保持旧 VisualTaskSpec 向后兼容

- 不新增顶层必填字段；`additionalProperties: false` 纪律保持（新字段是 `sampling_strategy` 对象内的显式可选属性）；
- 旧规格（无 `sampling_strategy`）→ 旧版 uniform 行为，任务 03 真实规格继续 VALID；
- 未知字段继续被严格 Schema 拒绝；
- 媒体来源硬门、路径安全、敏感推断限制零变化；
- `strategy` 枚举从 `["uniform", "adaptive_coarse_to_fine"]` 扩展为三值；旧规格的枚举子集仍然合法。

## 10. 三臂比较的公平条件

三个臂在同一预注册协议下执行，公平条件（任一不满足 → 该对比较 `INVALID_COMPARISON`，不算分）：

1. 相同样本（场景）集合与相同执行顺序（场景按预注册顺序；场景内臂顺序固定 uniform → adaptive → coverage）；
2. 相同媒体与 SHA-256（冻结 fixture；评分器硬门 G2 实际计算三方一致）；
3. 相同 target query（"红色正方形"）；
4. 相同 Ground Truth 版本（同一批 GT 文件，`annotation_version` 一致，无运行后修订）；
5. 相同模型与后端（本地 Ollama Qwen3.8-27B-GGUF；deterministic replay 时为同一构造证据生成器）；
6. 相同总模型调用预算（每场景统一预算；预算不足场景三臂同预算）；
7. 相同输出与超时规则（同一 `trace_temporal.py` 代码路径、同一 `frame_class` 分类规则、同一超时）；
8. 无单侧重试、无额外上下文、无人工修正、不删除失败样本（调用方显式声明 `fairness_attestation`）；
9. 相同 `evidence_nature`（replay 三臂全为 `constructed_fixture_evidence`；真实运行三臂全为 `real_model_output`——禁止一臂真实一臂构造的伪比较）；
10. GT 不进入采样决策（§24 专项测试）。

## 11. 预注册的 fixture、Ground Truth、查询、预算、顺序与 verdict 规则

完整机器可读版本：`artifacts/task-18/preregistration/`（`evaluation-plan.json` 等 7 份，阶段 A 提交冻结）。要点：

**场景（11 个，覆盖任务书十类要求）**：

| # | 场景 ID | 类别 | 媒体 | Ground Truth 要点 |
| --- | --- | --- | --- | --- |
| 1 | present-throughout | 目标全程存在/无转换 | 复用任务 16 冻结 fixture | confirmed [0,8000] |
| 2 | appear-midway | 中途出现 | 复用 | not_found [0,3200) → confirmed [3200,8000] |
| 3 | disappear-midway | 中途消失 | 复用 | confirmed [0,4800) → not_found [4800,8000] |
| 4 | reappear | 出现—消失—再次出现 | 复用 | 3 个 confirmed 段 + 边界 @2000/4000/6000 |
| 5 | short-event-between-grid | coarse 初始网格之间的短 confirmed 事件 | **新增 fixture** | confirmed [3500,4100]（网格点 2666.667/5333.333 之间） |
| 6 | short-uncertain-between-grid | coarse 初始网格之间的短 uncertain 区域 | **新增 fixture** | uncertain [3500,4100]（低对比度） |
| 7 | twin-short-events | 两个间隔较短的事件 | **新增 fixture** | confirmed [1600,2200] + confirmed [3000,3600] |
| 8 | absent-throughout | 无目标/无状态转换 | **新增 fixture** | not_found [0,8000] |
| 9 | reappear-tight-budget | 预算不足以同时完成覆盖与全部边界细化 | 复用 reappear 视频 | 同 #4 GT，三臂统一预算 6 |
| 10 | short-event-phase-b | 相位移动的短事件（语义同 #5） | **新增 fixture** | confirmed [6200,6800] |
| 11 | short-uncertain-phase-b | 相位移动的短 uncertain（语义同 #6） | **新增 fixture** | uncertain [6200,6800] |

新增 fixture 与任务 16 使用**同一组冻结生成参数**（640×360、24 fps、8000 ms/192 帧、mp4v、80×80 红色正方形、背景 BGR (200,200,200)、低对比度 BGR (214,214,214)、确定性渲染），由 `scripts/generate_task18_fixtures.py` 生成，第一次评测前冻结 manifest + SHA-256 + ground truth，之后不得重新生成或修改标签。

**统一预算**：主对照场景三臂 `max_model_calls=12`（与任务 16 一致，保证跨任务可比）；预算不足场景三臂 `max_model_calls=6`（显式标注，不参与同预算主对照的效率结论）。

**臂配置**（`arm-configs.json` 冻结）：

| 臂 | strategy | 关键参数 |
| --- | --- | --- |
| uniform | `uniform` | max_model_calls=12；interval 700ms × max 12（与任务 16 uniform 臂相同规划） |
| adaptive | `adaptive_coarse_to_fine` | max_model_calls=12；initial_coverage_samples=4；target_boundary_precision_ms=500；max_refinement_rounds=6 |
| coverage | `coverage_aware_adaptive` | max_model_calls=12；initial_coverage_samples=4；coverage_gap_target_ms=1500；coverage_call_reserve=4；target_boundary_precision_ms=500；max_refinement_rounds=6 |

**执行顺序**：场景按上表顺序；场景内臂顺序固定 uniform → adaptive → coverage（与任务 16 方法论一致；顺序效应作为已知限制记录，不轮换——轮换规则留给未来多轮重复实验）。

**replay 与真实 Qwen 的划分**：先执行 deterministic replay（全部 11 场景 × 3 臂，构造证据 `evidence_nature=constructed_fixture_evidence`，逐字节可复算，无任何模型调用）；资源门槛满足时执行预注册的真实 Qwen 小样本评测（同样 11 场景 × 3 臂，每臂每场景一次运行，不单侧重试）。**不得根据 replay 结果修改正式 Qwen 场景、Ground Truth 或规则。**

**指标**（任务 17 冻结评分器口径，经兼容适配层扩展第三臂）：七类采样点计数（correct_decisive / incorrect_decisive / abstention_on_determinate / failed_on_determinate / appropriate_abstention / overclaim_on_uncertain / failed_on_uncertain，分母为对应类别分母，0 分母写 `not_applicable`）、事件覆盖（covered/missed confirmed events、unreached uncertain segments）、边界匹配（Kuhn 一对一匹配 + 方向兼容 + 容差内计数 + 误差统计）、效率（调用数、复用、耗时、三个派生指标）、**maximum sampling gap**（来自 coverage provenance，跨场景取最大值）。

**verdict 规则**（`verdict-policy.json` 冻结）：

- **Pairwise**（coverage vs uniform、coverage vs adaptive、adaptive vs uniform）：直接使用任务 17 冻结评分器的 fairness gate（10 条件）与四类 verdict 规则（非回归 5 条件 + 严格更好项集合；规则逐条复述于 verdict-policy.json，不修改冻结评分器文件）；
- **Pack-level 三臂 verdict**（候选臂 = coverage，基线臂 = uniform 与 adaptive）：
  - 任一两臂公平门失败 → `INVALID_COMPARISON`；
  - 非回归条件：coverage 对 uniform **且** 对 adaptive 的 5 项非回归条件（incorrect_decisive ≤、overclaim_on_uncertain ≤、missed_confirmed_events ≤、missed_gt_boundaries ≤、unreached_uncertain_segments ≤）全部满足；
  - 严格更好项（至少一项，均相对两个基线同时成立）：(a) 总调用数少于两臂；(b) 两臂匹配边界数均 ≥1 且平均边界误差小于两臂；(c) 容差内边界数多于两臂；(d) 最大相邻采样间隔小于两臂（覆盖效率）；(e) 未触达 uncertain 段数少于两翼（语义覆盖，仅在两基线均 >0 时计入）；
  - 判定矩阵：非回归全过 + 有严格更好 → `IMPROVEMENT`；非回归全过 + 无严格更好 → `NO_IMPROVEMENT`；非回归违反 + 有严格更好 → `TRADEOFF`；非回归违反 + 无严格更好 → `NO_IMPROVEMENT`（完整披露违反项，不表示等价）；
  - 所有 verdict 附 reason codes；算法 verdict 与工程实现验收（PASS/FAIL）分开输出。

## 12. 真实模型非确定性如何记录

- deterministic replay：构造证据由冻结 GT 确定性生成，同输入两次运行输出逐字节一致（专项测试）；产物标注 `evidence_nature=constructed_fixture_evidence`、`input_nature=technical_fixture`；
- 真实 Qwen 运行：每臂每场景**单次运行**、不重试；保存模型原始返回（`raw/`）、资源门槛快照、起止时间；产物标注 `evidence_nature=real_model_output`；所有结论附"单次运行 + Agent/模型行为非确定性 + 技术 fixture 小样本不得外推"声明；
- 两次运行（replay 与 real）的指标分开汇总，不混合平均。

## 13. coverage 与模型语义校准为何必须分开

覆盖（sampling）回答"我们看了哪些时间点"；校准（calibration）回答"模型在被看到的点上是否给出正确/恰当拒答的结论"。任务 17 的 abstain-zone 证明两者独立：uniform 覆盖触达 uncertain 区但模型 3/3 过度断言（校准失败）；adaptive 覆盖未触达（覆盖失败）。coverage_aware_adaptive 只修复"没看"的问题；对"看了但模型误判"无能为力。因此评测必须分别报告 `unreached_uncertain_segments`（覆盖指标）与 `overclaim_on_uncertain`（校准指标），且覆盖改善不得抵消校准退化（verdict 非回归条件同时约束两者）。

## 14. uncertain 被触达但模型过度断言时如何评分

沿用任务 17 冻结口径：uncertain 段内的采样点按预测类别计入 `appropriate_abstention`（abstained/low_confidence）、`overclaim_on_uncertain`（confirmed/not_found）或 `failed_on_uncertain`（failed）；**被触达但过度断言不计入覆盖成功**——`reached=true` 只记录采样几何事实，语义计分照常。verdict 规则中 `overclaim_on_uncertain` 上升是明确的回归项（`more_overclaim_on_uncertain`）。真实 Qwen 在新 uncertain fixture 上的行为未知，预注册不假设模型会拒答（任务 16 的 abstain-zone 已证明它可能给出确定性负面）。

## 15. DSH/StepFun/Qwen 的真实职责

- **StepFun（step-5-preview，经 DSH 文本链路）**：只理解文本任务、规划并生成合法 VisualTaskSpec（含 `sampling_strategy` 声明）；当前 DSH 配置下**不读取图片、不识别视频帧**；
- **DSH（0.1.5-rc.2）**：Skill 发现、加载与 Agent 编排；资源门槛满足时执行一次全新 `--profile headless` 自主会话（会话内 Agent 自主发现/加载三个 Skill、生成规格、驱动执行器与报告器）；
- **本地 Qwen Vision（Ollama，Qwen3.8-27B-GGUF）**：唯一视觉后端，负责帧理解与结构化证据；
- **OpenCV（5.0.0）**：仅底层视频解码/抽帧；
- **coverage-aware sampling**：本项目自研采样策略（纯 Python 标准库逻辑），**不是 NVIDIA 官方组件**，与 TAO/VSS/DeepStream/NIM 无关。

## 16. 资源守卫与阻塞行为

真实视觉调用前执行 8 项资源门槛（任务书第十二节）：MiniMax-H3 无生成任务/监听、无用户活跃 WebUI 任务、MemAvailable 连续三次 ≥ 45 GiB、Ollama 可达、无外部 Qwen 消费者、DSH 正常、Git 工作区符合预期、预注册哈希一致。门槛不满足时：完成设计/实现/纯逻辑测试/回归 → 生成结构化 resource blocker（`artifacts/task-18/resource-gate.json`）→ 不执行真实 Qwen 与 DSH 自主演示 → 最终状态 `PARTIAL_RESOURCE_BLOCKED` → 不虚构模型结果。执行器层资源守卫（MemAvailable < 阈值不加载模型、未执行调用不计真实调用、全部帧 failed 并记录真实原因）与任务 16 相同。用户自行启动服务导致窗口关闭时：停止新的模型调用、保留已完成数据、如实报告，不干预用户服务。

## 17. 回归范围、冻结范围与允许修改范围

**冻结零改动**：`artifacts/task-07|08|09|16|17/`、`evals/tier3/evals.json`、Tier-3 v1/v2 评分器与 PASS 条件、任务 17 GT schema/评分器/verdict policy、任务 16 旧 fixture/GT/comparison、`app/` 与工作台脚本、用户未交付的 Evidence Pack 与 holdout。

**允许修改**：任务 18 设计文档与预注册文件；新 fixture 生成器/测试/benchmark runner/适配层；`schemas/visual-task-spec.schema.json`、`validate_task_spec.py`、`adaptive_sampler.py`、`trace_temporal.py`、`generate_report.py` 的**最小兼容性改动**（新策略分支 + 附加字段，旧行为零变化，回归证明）；三个 Skill 与项目文档的同步更新；`artifacts/task-18/`。

**回归**：任务 18 新测试（35 项）；任务 17 GT 测试 38/38；任务 16 temporal 27/27；任务 04 16/16；任务 06 32/32；M1–M8 10/10；v2 Tier-3 17/17；工作台静态 26/26；旧 VisualTaskSpec 正向/负向测试；`git diff --check`；敏感信息扫描；冻结文件完整性；预注册哈希完整性。

## 18. 非目标与对外声明红线

- 不新增第四个 Skill（第三策略在现有三 Skill 内向后兼容落地；评分适配层是项目级工具，与任务 17 评分器同层）；
- 不声称任意短事件必检、不声称实时视频监控、不声称跨摄像头身份追踪、不声称 StepFun 视觉识别、不给统计显著性结论；
- 不把 coverage-aware sampling 表述为 NVIDIA 官方视觉 Skill/TAO/VSS/DeepStream/NIM；
- 不声称真实仓储准确率；technical fixture 与真实仓储视频分开；
- 用户 8 AI + 4 licensed public Evidence Pack 未接入前，不得声称真实域效果；真实 dev 评测与 holdout 盲测仍是后续独立任务；
- 不修改任务 16/17 冻结 artifacts，不回写历史结论；任务 16 旧 `IMPROVEMENT` 与任务 17 `TRADEOFF` 作为历史完整保留，任务 18 的 verdict 只在新产物中追加；
- 不安装依赖、不联网搜索或下载、不改 DSH/StepFun/Ollama/系统全局配置、不读取或输出凭据、不添加 remote、不 push、不擅自启停任何服务。
