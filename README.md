# SparkSkill Studio

StepFun 多模态模型 × NVIDIA Agent Skills 的本地视觉 Skill 编译与验证工作台。

## 一句话定位

用户输入一句自然语言视觉任务，DSH Agent Harness 生成/配置一个受控 Agent Skill，Skill 在 DGX Spark 上执行视觉分析，输出带证据的结果，并可在新视频上复用。

## 首个应用场景

仓储/园区多段短视频中的**对象存在性与时序证据、事件证据链生成**。

示例任务：

> "判断红色背包在输入媒体中出现/未出现的时间区间，输出视觉证据；如果不存在或无法确认，不要猜测。"

**场景边界**：这是存在性 / 时序证据场景，**不是目标跟踪器**——不输出物体运动路径、不做跨摄像头身份或实例关联、不做实时跟踪。同一目标查询在多段视频中分别得到视觉匹配时，只表述为"在来源 A 中确认 / 在来源 B 中确认"。

## 技术主线

> **真实分工（唯一口径，全仓一致）**：StepFun `step-5-preview` 理解用户文本任务、规划并生成结构化任务规格；
> DSH `0.1.5-rc.2` 发现、加载和编排 Skill；`task-to-skill-compiler` 把文本视觉任务编译为受约束的
> VisualTaskSpec；OpenCV 只做底层解码与抽帧；**本地 Ollama Qwen3.8-27B Vision 读取图片和视频帧并生成结构化视觉证据**；
> `visual-evidence-extractor` 约束视觉调用、证据格式、坐标规范与拒答边界；`evidence-report-generator`
> 依据证据生成报告并执行反幻觉交叉校验；Evidence Workbench 只读展示已保存的真实 artifacts。

- **Agent Harness**：DSH 0.1.5-rc.2 负责任务理解与 Skill 的发现、加载、执行、复用；
- **StepFun 多模态模型**：当前负责**文本任务解析与 Agent 规划**（step-5-preview，经 DSH 文本链路）；**当前 DSH 配置下 StepFun 图片输入不可用**（provider 未声明图片能力，图片调用在链路层被拒）——**StepFun 不读取图片、不识别视频帧**；
- **本地 Qwen Vision**：当前**视觉后端**为 DGX Spark 本地 Ollama 上的 `modelscope.cn/unsloth/Qwen3.8-27B-GGUF`（27B，Q4_K_M，vision），负责图片与视频帧理解、结构化视觉证据输出与拒答；
- **Agent Skill**：`.dsh/skills/` 下的受控能力单元，带输入输出契约、正/负向触发、Skill Card 与安全边界；
- **evals / Benchmark**：每个 Skill 带 `evals/evals.json` 与真实运行数据 `BENCHMARK.md`；项目级 Tier-3 baseline vs with-skill 对照评测见根目录 `BENCHMARK.md`；
- **OpenCV**：仅作视频解码、抽帧、读取视频信息和保存关键帧的底层工具（5.0.0，复用本机 vLLM 环境已有安装，未新增依赖），**不是项目核心**。

## 当前实现状态（2026-09-23，任务 20 配对实验后）

- **图片最小闭环已跑通**（任务 03）：自然语言 → DSH+StepFun 生成 VisualTaskSpec → Schema 校验 → 本地 Qwen Vision 抽取证据 → 报告生成器输出结论；端到端实测 72.5s（任务 03 原始运行产物为内部留档；其真实图片证据样例与旧版规格——`artifacts/task-03/task-spec.json`、`positive-evidence.json`、`negative-evidence.json`——随公开仓库分发，供契约测试回放使用）。
- **短视频最小闭环已跑通**（任务 04）：自然语言 → DSH+StepFun 生成 VisualTaskSpec → `extract_frames.py` 按采样策略抽帧 → `trace_video.py` 逐帧复用任务 03 图片分析能力 → 聚合视觉证据时间线 → 报告生成器视频模式输出报告（任务 04 原始运行产物为内部留档；其规则测试`.dsh/skills/visual-evidence-extractor/scripts/test_video_pipeline.py` 随公开仓库分发，公开版实测 16/16 通过）。
  - 已完成：视频读取、元数据、可配置抽帧（间隔/最大帧数/起止时间）、时间戳单调递增、帧路径可追溯、聚合规则（去重/状态变化/首末确认/confirmed·not_found·abstained·failed 四态区分）、视频报告状态一致性与交叉校验、资源守卫；16/16 测试通过。
- **DSH Agent 自主视频演示已跑通（任务 05 重跑）**：在用户关停 MiniMax-H3 后的资源窗口内，两次全新 `dsh --profile headless` 会话由**会话内 Agent 自主**发现/加载 Skill、生成并校验 VisualTaskSpec、调用抽帧/视觉证据/报告工具并得出结论（非外部脚本串联）。**真实 Qwen 视频逐帧分析首次验证**：正向（目标=太阳，由开放式 Qwen 探针从真实帧判定）confirmed=5/failed=1、负向（紫色大象）not_found=6；1 帧 Qwen 返回像素坐标框被契约校验如实拒绝（未伪造）。（任务 05 原始会话产物为内部留档，不随公开仓库分发；其多视频规则测试`test_multi_video_pipeline.py` 随公开仓库分发，公开版实测 32/32 通过。）
- **多段视频统一证据时间线已跑通（任务 06）**：两次全新 DSH headless 自主会话驱动**多媒体 VisualTaskSpec**（`source_media` 来源对象数组，向后兼容旧版单路径字符串）→ 每段视频独立证据时间线（复用 `trace_video.py` 单段能力，未重写视觉提示词）→ 按 `time_offset_ms` 计算全局排序时间 → 统一全局时间线 → 跨视频证据摘要报告。测试视频为两段内部测试媒体（不随公开仓库分发；开放式探针确认共同非敏感目标"太阳"）。任务 06 原始会话产物为内部留档。
  - 正向：8/8 帧确认（每来源 4/4，置信度 0.95–0.98），全局时间线 0.0 → 12958.333 ms；
  - 负向（紫色大象）：8/8 帧 not_found（确定性负面），bbox 全 null，无虚假跨视频关系；
  - **像素坐标受控归一化**：3/8 帧 Qwen 返回像素坐标被确定性归一化（记录原始值/格式/帧尺寸）；混合/越界/顺序错误/尺寸未知不归一化（置 null + warning，不重跑模型）；
  - **跨视频语义边界（核心安全要求）**：同一目标查询在多段视频中分别得到视觉匹配（matched target query / visually consistent with target description / confirmed in source A / confirmed in source B）；**不断言同一个物理实例、不宣称跨视频移动、不做身份匹配**；`semantic_limitations` 随全局时间线与最终报告输出；
  - 会话内 Agent 还自行发现并修复 2 个 Skill 代码缺陷（详见任务 06 会话摘要，内部留档）；
  - 测试：多视频规则测试 32/32（公开版实测）、任务 04 回归 16/16（公开版实测）；任务 06 原始产物为内部留档。
- **目标时序证据与粗到细自适应采样已跑通（任务 16）**：在三个现有 Skill 内向后兼容地新增（**不增加第四个 Skill**）——VisualTaskSpec 新增可选 `sampling_strategy` 契约（`uniform` 正式 baseline 行为零变化 / `adaptive_coarse_to_fine` 初始覆盖+触发器细化、`max_model_calls` 硬预算、目标时间边界精度、最大细化轮数）；`trace_temporal.py` + `adaptive_sampler.py` 输出完整**采样 provenance**（每次决策的时间戳/阶段/理由/触发区间/观察状态/第几次调用/缓存状态/预算状态/停止原因）与可复算**时序证据**（首末 confirmed 采样观察时间、状态转换左右边界与不确定宽度、五类计数、证据支持状态片段、无法确认片段、是否达到目标精度、是否因预算停止）；报告引擎 temporal 模式独立复算并交叉校验。语义红线：首末 confirmed 是采样观察时间（≠真实进入/离开）、采样点之间不断言连续存在、abstained/low_confidence/failed 不退化为 not_found、不是 ReID/目标跟踪器/实时跟踪。规则测试 **27/27**（`.dsh/skills/visual-evidence-extractor/scripts/test_temporal_evidence.py`，构造证据回放+真实 fixture 抽取，无真实模型调用）；technical fixture（5 段合成视频，640×360@24fps，红色正方形出现/消失/再现/低对比度区间）评测前冻结 manifest+ground truth+SHA-256；uniform vs adaptive 同预算真实对照见 `artifacts/task-16/comparison.json`（**技术 fixture 小样本，不外推为真实仓储准确率；不预设 adaptive 必须 PASS**）。
- **NVIDIA 官方 Skills 当前未接入**：未发现官方 Skills、TAO、VSS、DeepStream、NIM；本项目 Skill 均为自研，不冒充 NVIDIA 官方签名。
- **Evidence Pack 数据契约与时间 Ground Truth 评分器已建立（任务 17）**：`schemas/evidence-pack-manifest.schema.json`（输入清单契约，不含时间真值）+ `schemas/temporal-ground-truth.schema.json`（显式独立真值输入）+ `scripts/validate_evidence_pack.py`（契约校验）+ `scripts/score_temporal_ground_truth.py`（确定性 CPU-only 评分器，零模型调用）。它把三个曾被混淆的问题分开：`execution_status`（流水线是否完成）、语义评分（七类采样点计数 + 事件覆盖 + 边界匹配，**`completed` 不等于语义正确**）、效率指标（调用/复用/耗时，不抵消语义错误）。用冻结的任务 16 产物重评分（5 场景 × 2 臂，fairness gate 10/10）：**pack 级 verdict=TRADEOFF**——adaptive 省调用（34 vs 60）且平均边界误差更小，但未触达 abstain-zone 的 uncertain 区间（`unreached_uncertain_segments` 1 > 0），且 uniform 臂在 uncertain 区间 3/3 过度断言（真实 Qwen 确定性负面 vs GT 不确定）。**任务 16 旧 `IMPROVEMENT` 是旧口径历史结论（未篡改）**；严格 scorer 的复算 verdict 以 `artifacts/task-17/comparison.json` 为准。规则测试 38/38（`artifacts/task-17/test-results.json`，内部留档版结果；公开版排除 4 个 holdout 同名 fixture 后为 34/34，本次实测通过）。**合成 fixture 不是真实仓储准确率；用户 8 AI + 4 真实视频 Evidence Pack 上传前，不得声称真实域评分已完成**（competition profile 的契约结构见 `schemas/evidence-pack-manifest.schema.json` 的 profile 规则；内部留档版另有一份占位值明确标注的契约示例，不随公开仓库分发）。
- **Coverage-Aware 自适应采样与预注册三臂评测已落地（任务 18）**：在三个现有 Skill 内向后兼容新增第三种采样策略 `coverage_aware_adaptive`（**不增加第四个 Skill**；uniform 与 adaptive_coarse_to_fine 行为零变化，回归证明）——同一硬模型调用预算内管理**时间覆盖探索**（largest-gap-first 压缩尚未充分观测的时间间隔）与**事件边界细化**两种职责，provenance 区分覆盖探索/边界细化/初始覆盖调用并复算**最大相邻采样间隔**与剩余盲区（`underobserved_intervals`），产物显式声明 `arbitrary_short_event_detection_guaranteed: false` 与 `events_shorter_than_max_sampling_gap_may_be_missed: true`（**不保证发现任意短事件**）。预注册冻结（阶段 A 提交先于实现）：11 场景 × 3 臂（uniform / adaptive_coarse_to_fine / coverage_aware_adaptive，同预算；6 段新增确定性 technical fixture + 4 段复用任务 16 冻结 fixture；覆盖任务书十类场景含两个相位对抗样本）。评测用任务 17 冻结评分器（零改动，经内存扩展策略白名单的兼容适配层）：公平门 10/10 × 3 对；**pairwise verdict：coverage vs adaptive = IMPROVEMENT**（平均边界误差更小、容差内边界更多——任务 17 量化的初始覆盖盲区被修复：网格间短事件/短 uncertain 区被发现/触达，adaptive 漏检/未触达），coverage vs uniform = TRADEOFF、adaptive vs uniform = TRADEOFF；**pack 级 verdict = TRADEOFF**（twin-short-events：两个 600ms 事件小于 1333ms 覆盖间隔，coverage 与 adaptive 均漏检、仅 uniform 密集网格捕获——覆盖不保证任意短事件发现的诚实实证）。规则测试 **36/36**（`artifacts/task-18/test-results.json`）。**真实 Qwen 三臂评测与 DSH 自主会话已完成**（2026-09-22 补跑轮；此前两轮因用户 MiniMax-H3 服务活跃资源门槛失败、状态 PARTIAL_RESOURCE_BLOCKED，阻塞记录保留于 `resource-gate-rerun.json`；补跑轮经用户授权优雅停止 H3 服务族——纯 SIGTERM、零强杀、恢复方式已记录、任务结束后保持停止，见 `h3-shutdown-record.json`）：`run_task18_comparison.py --mode real` 按同一预注册协议执行 **287 次真实 Qwen Vision 调用**（零失败/零超时/零无效输出；原始返回为内部留档，公开版保留其评分与 verdict 结论于 `artifacts/task-18/three-arm-comparison.json`、`verdict.json` 与 `run-summary.md`），**replay 与 real 分别评分、分别给 verdict、不混合平均**。真实模式 pairwise：coverage vs adaptive = **TRADEOFF**（replay 中为 IMPROVEMENT——真实 Qwen 触达 uncertain 区域后**过度断言**而非拒答：overclaim coverage 4 / uniform 2 / adaptive 0，重现任务 16 确定性负面 overclaim 模式，差异源于视觉模型语义而非采样策略），coverage vs uniform = TRADEOFF、adaptive vs uniform = TRADEOFF；**real pack 级 verdict = TRADEOFF**（严格改进：平均边界误差 93.519ms 小于两个基线；违反：overclaim、漏检 2 个 confirmed 事件、最大间隔 1333.334ms > uniform 708.334ms）。真实运行同时证实：coverage 采到短事件后 Qwen 能正确识别（两个短事件场景 confirmed=2 vs adaptive=0），600ms twin 事件仍漏检（**不保证发现任意短事件**）。DSH headless 自主会话成功（三 Skill 自主发现/加载、coverage_aware_adaptive 规格校验 VALID、11/12 次真实调用、发现短事件且边界 mean 33.333ms、冻结评分器离线评分 11/11）。**工程实现 PASS 不等于算法全面优于基线**；synthetic technical fixture 不是真实仓储准确率；**不得声称任意短事件必检、真实域效果或统计显著性**；用户 dev/holdout Evidence Pack 尚未接入。
- **dev Evidence Pack 三策略真实基线评测已完成（任务 19B，2026-09-22/23）**：第一次把冻结三策略（uniform / adaptive_coarse_to_fine / coverage_aware_adaptive）应用到用户真实交付的 dev Evidence Pack（AI01–AI06 MiniMax-H3 生成受控测试视频 + WEB01–WEB03 Pexels licensed-public 真实行业视频；仓库外只读包，白名单九样本，摄验 14 项全过）。**先测量、不校准**：预注册（阶段 A 提交 `e3ef01e`）先于任何 dev 模型调用；GT 由 transfer-safe 卡确定性结构派生（AI06/WEB02 相邻同状态合并、WEB01/WEB02 末段对齐实测时长，状态覆盖与边界集合不变）；预算政策 `clamp(ceil(duration/1000),12,24)` 只依赖媒体时长；样本内臂顺序轮换 + 统一 warm-up（不计入任何 arm）。**27/27 真实运行、0 失败、256 次真实 Qwen 调用**（+1 warm-up）；任务 17 冻结 scorer + 任务 18 适配层评分，27 份硬门全过、逐样本公平门 27/27 通过。**算法结论：三范围 pack verdict 全部 NO_IMPROVEMENT**——核心缺陷是模型语义校准失败而非采样几何：AI06 uncertain 区双向过度断言（overclaim 11/7/9、abstention 仅 1/3/1）、AI04 遮挡区三臂全部误判 confirmed、WEB01 真实域早期误报、WEB03 真实负向误报（uniform 4 / coverage 5）；AI05 三臂全部正确；全部 8 个 GT 边界 matched=0（方向兼容规则下带不确定度的边界不可用）。DSH headless 自主会话（WEB01，阶段 A 冻结）成功：三 Skill 自主发现/加载、规格校验 VALID、8 次真实调用、离线评分 correct 6/8。工程状态 **BASELINE_COMPLETE** 与算法 verdict 分开；新测试 22/22、回归全过、交付验证 21/21（任务 19B 原始执行/评分产物为内部留档；公开版收录 `artifacts/task-19/run-summary.md`、`known-limitations.md`、`comparisons/task19-three-scope-verdicts.md` 与 `verification.json`）。**不得声称真实仓储准确率/统计显著性/生产可用性；licensed-public 仅三段，只写小样本真实域观察。**
- **视觉证据判断校准：同期同帧配对实验已完成（任务 20，2026-09-23）**：在 Task 19B 冻结 dev 基线上做**单变量校准检验**——通用视觉判断语义的版本化变化（v1 现行模板 → v2 候选；唯一差异为判断纪律段：确认存在/确定性负面/拒答的三类准入 + 拒答触发条件 + 置信度纪律；JSON 输出契约与证据状态集合不变，不含任何素材答案/时间/样本编号）。设计为同期同帧配对：256 个 Task 19B 采样点，每点 v1/v2 各一次真实 Qwen 调用，**同一份帧字节、同一模型、同一请求参数、同一查询**（不调采样参数、不换模型、不改标签、不改冻结评分规则）。预注册提交 `31cf893`（preregister）**早于第一笔 dev 采样点调用**（02:04:49Z < 02:38:47Z）；一个 v2 候选、一次预注册、一次正式实验；运行顺序按索引轮换（v1 先/v2 先各 128）；GT 不进入视觉请求；新配对评分器与 Task 17 冻结评分器 256 个历史点逐行等价。**512/512 正式调用完成**（+warm-up 1 + smoke 4 均 fixture 帧不计入；511 ok + 1 契约拒绝、0 超时、0 无效 JSON、0 重试；平均 14.1s/调用）。**配对 verdict = TRADEOFF**：v2 让不可判定画面更愿意拒答（overclaim_on_uncertain 40→34，降幅 6 ≥ 5；appropriate_abstention 6→11；incorrect_decisive 24→23；failed_on_determinate 0→0），但**拒答精确度不足**——6 个可判定帧被推入拒答：其中 **5 个是正确判断损伤**（AI01 t=666 运动模糊边际帧 ×3 臂、WEB03 t=17480 末帧 adaptive/coverage 两臂）、**1 个是误报修复**（WEB03 t=17480 uniform 臂，v1 误报→拒答；七类账与逐点证据见 Task 21 勘误 E1/E2），correct_decisive 186→181（−5，超容忍 4）、licensed-public −2（超容忍 1）→ 预注册门槛 G3 FAIL。按停止门**不运行阶段 C 动态三臂、不做 DSH 自主会话、不迭代第二个候选**；v2 未被采纳进 Skill（analyze_image.py 零改动，v1 仍是生产模板）。AI04 遮挡区 9 个采样点 overclaim 9→8（样本总数 24，勘误 E3）、AI06 overclaim 26→21/拒答 6→10（均未解决）、WEB01 无变化、WEB03 误报 10→9 且 3 次 determinate 拒答（1 次误报修复 + 2 次误拒，样本总数 36，勘误 E4）；**Task 19B 历史 v1 动态三臂 8 个 GT 边界 0/8；Task 20 v2 动态边界 not_measured（阶段 C 未运行）**；Task 21 固定采样重放（规则级反事实诊断，非动态实测）对同期 v1/v2 存档输出各 0/24 次边界暴露匹配（勘误 E6）。工程状态 **PAIRING_COMPLETE** 与模型质量状态（TRADEOFF）分开；去重敏感性（184 唯一帧；v2 五类表须补示 abstention_on_determinate 2 + failed_on_uncertain 1，且"首现行"去重有跨臂选择依赖、不得声称统计显著性，勘误 E5）方向一致；同期 v1 vs Task 19B 历史 249/256 一致（漂移已披露）。新测试 19/19、旧回归全过、交付验证 20/20（任务 20 原始配对产物为内部留档）。**Task 20 人类可读口径勘误：`artifacts/task-21/errata/task20-errata.md`（该文件随公开仓库分发）。****dev 小样本 + 单次运行 + 温度 0.1 随机性：不得给出统计显著性、不得外推真实仓储准确率。**
- **中心帧 + 邻帧上下文视觉质量闸门（任务 25，2026-09-23）**：检验"让同一个本地 Qwen 在一次调用中看到指定中心帧以及前后各 500ms 的邻帧（有序、明确标注）是否比同期单帧生产 v1 更能判断中心帧目标状态"。阶段 0 技术 smoke（项目外合成图 7 次）证实本地 Ollama Qwen 端点支持**单次请求有序多图**、模型能稳定只判中心帧、目标只在邻帧时中心 object_found=false（FEASIBLE）。阶段 A 预注册（提交 `2961139`+`0d3b9d4`）先于任何正式 dev 调用：184 唯一中心帧（去重 Task 22 冻结 256 点，generated 110/licensed-public 74）、邻帧 ±500ms（extract_frames 同一解码路径，越界缺席，探针证明 decode+encode 逐字节一致）、候选 cand=生产 v1+图序/只判中心帧前置说明+两处中心帧指代替换（多图有序）。阶段 B 48 对同期配对（96/96 真实调用，0 超时/0 无效 JSON/2 契约拒绝）verdict=**STAGE1_HARM_STOP**——候选多图**略微**降错误断言（20→19）、升正确判断（26→27）、降误报（incorrect 10→8），但**引入 2 次输出契约失败**（failed_on_determinate/failed_on_uncertain 各 0→1，触发 B4 门）、overclaim 反升（10→11）、新增 2 个邻帧目标误投射中心。按停止门不运行阶段 C、候选未采纳（生产 v1 零改动）、holdout 仍封存。结论：**加入邻帧时序上下文不是修复路径**（失败层仍在视觉模型语义 + 多图下输出契约稳定性）。新测试 28/28、Task 22 回归 30/30、Task 17 38/38、交付验证 13/13（任务 25 运行摘要随公开仓库分发：`artifacts/task-25/run-summary.md`；原始配对产物为内部留档）。dev 小样本+单次运行+温度 0.1：不给统计显著性、不外溢真实仓储准确率。
- **Tier-3 对照评测已完成（任务 07）**：参照 NVIDIA SkillEvaluator Tier-3 思路，同一个 DSH Agent、同一 StepFun 模型、同一本地 Qwen Vision、同一媒体、同一任务文本，唯一变量为是否加载项目 Skill。9 个任务（含 7 个负向/边界用例）× 两侧 = 18 个全新 headless 会话真实运行，确定性规则评分（不用大模型当裁判、不让被测 Agent 自评）。初始结果：**Security 8/9→8/9、Correctness 8/9→8/9、Discoverability 4/9→8/9、Effectiveness 6/9→9/9；总耗时 −38.7%；Verdict: PARTIAL**（with-skill 在 E9 缺失媒体任务上未返回缺参错误——失败未隐藏）。完整结果见根目录 `BENCHMARK.md`；运行摘要与比较结论见 `artifacts/task-07/run-summary.md` 与 `artifacts/task-07/comparison.json`（原始会话产物为内部留档）。
- **E9 根因修复与评测器 v2（任务 08/09）**：E9 是真实产品缺陷（缺媒体时从项目上下文推断路径），已通过媒体来源 provenance 硬门修复（M1–M8 契约测试 10/10、E9 稳定性 3/3）；完整重跑后发现**冻结的 v1 评分器存在 stdout 断言语境误报**（把合规否定/政策声明当作违规），按用户决策（方案 B）新增版本化评分器 `scripts/score_tier3_eval_v2.py`（唯一变化：stdout 与文件一致的从句级否定/声明语境判定；回归 17/17），对任务 08 冻结数据全量对称重评分（未重跑任何模型会话）：**Security 9/9→9/9、Correctness 7/9→9/9、Discoverability 5/9→9/9、Effectiveness 6/9→9/9；Verdict: PASS**。历史 PARTIAL 与 v1 冻结状态完整保留（`BENCHMARK.md` 历史链、`artifacts/task-09/`）。
- **本地视觉证据工作台（任务 10，任务 12/12.1/13 重设计为 Apple 风格亮色界面）**：完全离线、CPU-only、由真实 artifacts 驱动的本地界面（`app/`）：Hero 结果摘要（真实关键帧为主体）+ 横向九阶段证据链路（用户任务 → StepFun 任务规划 → DSH 技能匹配 → 视觉任务规范 → 视频抽帧 → Qwen 视觉证据 → 全局证据时间线 → 最终结论 → Tier-3 验证）+ Provenance 抽屉 + 验证终章；6 个可切换运行记录（任务 16 / 任务 18 单视频时序证据回放——真实 Qwen 调用、输入为仓库内自产合成 fixture，加 Tier-3 历史链四条：初次 PARTIAL、E9 修复、评测器 v1 误报发现、Tier-3 最终 PASS；内部留档版另有任务 05/06 的记录，其媒体为内部测试视频，不随公开仓库分发）；Truth Status 五级（Verified/Recorded/Structural/Blocked/Synthetic Fixture）；只读 localhost 服务（127.0.0.1:8787，媒体 allowlist、禁目录遍历、不服务凭据/模型权重）。**界面只读展示已保存的真实 artifacts，不在浏览器内实时调用 StepFun / Qwen / DSH / 三个 Skill。** 启动：`python3 scripts/serve_demo.py`；重新生成 Manifest：`python3 scripts/build_demo_manifest.py`。设计系统记录：`.interface-design/system.md`。
- 本文档不写任何未经验证性能数字；Benchmark 数字均来自真实运行。

## 快速验证（评委入口）

**只想 90 秒看懂项目**（不需要任何模型）：

```bash
python3 scripts/serve_demo.py     # → http://127.0.0.1:8787/
```

**想独立复现或部署**：见 `docs/REPRODUCTION.md`（硬件/软件前提、Skill 发现目录与契约结构、静态工作台启动与验证、真实图片/单视频/多视频流水线入口、资源门槛、网络不可用限制、常见失败排查）。

**想核对优化深度**：见 `docs/OPTIMIZATION_NOTES.md`（契约化、触发边界、provenance 硬门、证据结构、坐标归一化、反幻觉、多来源聚合、资源治理、baseline vs with-skill 数据，以及**明确没有做**的模型权重级优化）。

**想核对公开版与内部留档版的关系**（哪些数字可在公开版复算、哪些仅基于内部冻结数据、脱敏改写记录）：见 `docs/PUBLIC-VERSION-NOTES.md`。赛事交付候选包（发布风险审计、主张—证据—限制矩阵、演示 runbook、提交矩阵）为内部留档，不随公开仓库分发。

## 已知环境

- NVIDIA DGX Spark / GX10，NVIDIA GB10，统一内存架构，CUDA 13.0.2，ARM64；
- DSH 0.1.5-rc.2 已安装并运行，DSH_HOME 指向用户主目录下的 `.dsh`（复现者按 `docs/REPRODUCTION.md` §2.3 自行配置）；
- StepFun Provider 已配置（`https://api.stepfun.com/step_plan/v1`，默认模型 step-5-preview）；
- Ollama 运行于 `:11434`（Qwen3.8-27B-GGUF，vision）；
- MiniMax-H3（:8000）为用户的另一路视频生成服务，由用户自行启停（内部留档版记录了任务 18 期间经用户授权优雅停止与恢复的全过程）；本项目不得停止它；
- OpenCV 5.0.0 位于开发机某含 cv2 的 Python 环境（复现者自备；系统 python3 无 cv2 时由 `.dsh/skills/visual-evidence-extractor/scripts/skill_env.py` 按 `SPARKSKILL_CV2_PYTHON` 或常见环境模式自动切换，不安装依赖）。

## 文档索引

- `PROJECT_CONTEXT.md`：项目长期上下文与红线；
- `docs/REPRODUCTION.md`：**复现与部署说明**（评委/新人入口：前提、Skill 结构、工作台启动与验证、三条真实流水线入口、资源门槛、排查）；
- `docs/OPTIMIZATION_NOTES.md`：**优化说明**（已做的 Agent 系统/契约/安全/编排/资源治理优化，与明确没有做的模型权重级优化）；
- `docs/PUBLIC-VERSION-NOTES.md`：**公开版与内部留档版的关系**（收录范围、脱敏改写记录、可复算与不可复现数字的边界、停止门）；
- `docs/plans/2026-09-21-sparkskill-studio-design.md`：正式设计文档（含 §17 实施偏差记录）；
- `docs/plans/2026-09-22-apple-evidence-workbench-redesign.md`：Evidence Workbench 重设计计划；
- `docs/DEVELOPMENT_STATUS.md`：开发状态、阻塞项与下一阶段（含任务 11–15 记录）；
- `docs/SMOKE_TEST_REPORT.md`：任务 02 冒烟验证报告；
- `artifacts/task-03/{task-spec,positive-evidence,negative-evidence}.json`：任务 03 真实规格与图片证据样例（供契约测试回放；任务 03 其余原始产物为内部留档）；
- 任务 04/05/06 的原始运行产物为内部留档（其规则测试随公开仓库分发：`test_video_pipeline.py` 16/16、`test_multi_video_pipeline.py` 32/32、`test_missing_media_contract.py` 10/10，本次实测通过）；
- `docs/plans/2026-09-22-temporal-evidence-adaptive-sampling-design.md`：目标时序证据与粗到细自适应采样设计文档（任务 16）；
- `docs/plans/2026-09-22-evidence-pack-ground-truth-scoring-design.md`：Evidence Pack 数据契约与时间 Ground Truth 评分器设计文档（任务 17）；
- `docs/plans/2026-09-22-coverage-aware-adaptive-sampling-design.md`：Coverage-Aware Adaptive Sampling v2 与预注册三臂评测设计文档（任务 18）；
- `artifacts/task-16/`：任务 16 产物（fixture manifest/ground truth/SHA-256、规则测试 27/27、uniform vs adaptive 对照、DSH 自主会话记录、验证）；
- `artifacts/task-17/`：任务 17 产物（Evidence Pack/GT 契约实例、确定性 fixtures t01–t29+t28b、Task 16 冻结产物重评分、verdict=TRADEOFF 的比较报告、测试结果与验证；公开版实测规则测试 34/34——内部留档版另含 4 个 holdout 同名 fixture 为 38/38）；
- `artifacts/task-19/{run-summary.md,known-limitations.md,verification.json,comparisons/}`：任务 19B 真实域基线的运行摘要、已知限制、三范围 verdict 与交付验证（dev 包摄验/GT/执行/评分原始产物为内部留档）
- `artifacts/task-21/errata/task20-errata.md`：任务 20 配对实验的人类可读口径勘误（任务 20 原始配对产物为内部留档）
- `artifacts/task-18/`：任务 18 产物（预注册 7 份文件 + 冻结哈希、6 段新 technical fixture、契约、deterministic replay 三臂评测、dsh-session 自主会话产物与离线评分、规则测试 36/36、resource-gate、两轮阻塞历史 resource-gate-rerun、授权停服记录 h3-shutdown-record、verdict=TRADEOFF（replay 与 real 双块）、内部 24 项验证记录；real-qwen 的 287 份原始模型返回为内部留档，其评分与 verdict 结论已收录）；
- `BENCHMARK.md`：**Tier-3 baseline vs with-skill 对照评测**（任务 07；五维结果、逐任务结果、Efficiency、已知限制、Verdict）；
- `artifacts/task-07/{run-summary.md,comparison.json}`：Tier-3 评测运行摘要与比较结论（原始会话产物为内部留档）；
- `.dsh/skills/*/SKILL.md`、`skill-card.md`、`BENCHMARK.md`：三个 Skill 的定义与实测；
- `.interface-design/system.md`：视觉证据工作台设计系统；`app/`：本地工作台（零依赖前端）；`scripts/build_demo_manifest.py` / `scripts/serve_demo.py` / `scripts/test_demo_app.py`：Manifest 生成 / 只读服务 / 测试。

## 开源许可（License）

- **本仓库的代码与三个自研 Skill 按 Apache License 2.0 开源**，完整正文见 [`LICENSE`](LICENSE)（`Copyright 2026 tangjue3`）；
- **第三方模型、模型权重与素材继续遵守各自许可证**：本地视觉后端 `modelscope.cn/unsloth/Qwen3.8-27B-GGUF` 的权重与模型卡遵循其发布方许可；文本规划使用 StepFun API 的服务条款；冻结 Tier-3 评测使用的两段测试视频为用户 MiniMax-H3 服务的真实产出，仅作只读测试用途，未修改原文件、**不随公开仓库分发**（公开版演示输入为仓库内自产合成 fixture）；
- **本仓库不包含任何第三方模型权重**（无 `.gguf` / `.safetensors` / 检查点入库；`.gitignore` 与工作台服务都拒绝服务模型权重文件）；
- Apache-2.0 仅覆盖本仓库自有代码与文档，**不授予、也不限制**上述第三方模型与素材的权利；不得把第三方授权错误纳入本项目代码许可证；
- 自研 Skill **不冒充 NVIDIA 官方签名 Skill**；当前未接入 NVIDIA 官方 Skills、TAO、VSS、DeepStream、NIM。
