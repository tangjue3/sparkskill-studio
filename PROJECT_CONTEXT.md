# PROJECT_CONTEXT — SparkSkill Studio 长期项目上下文

> 本文件是 SparkSkill Studio 项目的长期上下文（living context）。任何 Agent 在本项目中工作前必须先阅读本文件；本文件与正式设计文档（`docs/plans/2026-09-21-sparkskill-studio-design.md`）冲突时，以设计文档为准，并回改本文件。

## 1. 项目目标

SparkSkill Studio 是一个本地视觉 Skill 编译与验证工作台：用户输入一句自然语言视觉任务，DSH Agent Harness 理解任务并生成/配置一个受控的 Agent Skill，该 Skill 在 DGX Spark 上执行视觉分析，输出带时间、关键帧、目标框和置信度的证据结果，用户可在新视频上复用这个 Skill。

## 2. 赛事评分重点

评分关注以下方向，项目所有取舍都必须服务于此：

- Agent Harness（DSH）作为智能体底座的使用深度；
- StepFun 多模态模型在**文本任务理解、规划与任务规格生成**上的接入与应用（当前 DSH 配置下其图片输入不可用，视觉理解由本地 Qwen 承担）；
- Skill 的生成、发现、加载、执行和复用全生命周期；
- Skill 的输入输出契约的明确与可验证；
- 正向触发与负向触发（何时用、何时不用）；
- Skill Card 的标准与可读性；
- evals（基线 vs with-skill 的可度量对比）；
- Benchmark（本地算力下的性能与质量基线）；
- 安全边界（不越权、不猜测、不冒充）；
- DGX Spark 本地算力的真实利用；
- 带证据的视觉结果（时间、关键帧、目标框、置信度）。

## 3. 产品定位

StepFun 多模态模型 × NVIDIA Agent Skills 的本地视觉 Skill 编译与验证工作台。

核心用户流程：

```
自然语言视觉任务
  → DSH Agent Harness 理解任务
  → 生成/配置受控 Agent Skill
  → Skill 在 DGX Spark 上执行视觉分析
  → 输出带时间、关键帧、目标框、置信度的证据结果
  → 用户在新视频上复用该 Skill
```

## 4. 首个演示场景

仓储/园区多段短视频中的**对象存在性与时序证据、事件证据链生成**。

示例任务：

> "创建一个 Skill，判断红色背包在多段视频中**出现/未出现的时间区间**，记录关键画面与置信度；如果证据不足，不要猜测。"

**场景边界（不得超出）**：这是**存在性 / 时序证据**场景，**不是目标跟踪器**——不输出物体运动路径、不做跨摄像头身份或实例关联、不断言同一个物理实例跨视频移动、不做实时跟踪（与 §9 红线一致）。同一目标查询在多段视频中分别得到视觉匹配时，只能表述为"在来源 A 中确认 / 在来源 B 中确认"，`semantic_limitations` 随产物与报告输出。

## 5. 各组件职责划分

| 组件 | 职责 | 明确不属于它的职责 |
| --- | --- | --- |
| DSH Agent Harness（DSH 0.1.5-rc.2） | Agent 运行时：理解自然语言任务、编排 Skill 的生成/发现/加载/执行、管理会话与工具调用 | 不承担视觉推理本身；不替代 Skill 契约 |
| StepFun 多模态模型（step-5-preview，api.stepfun.com/step_plan/v1） | **当前**：文本任务解析与 Agent 规划（经 DSH 文本链路生成 VisualTaskSpec）；当前 DSH 配置下其图片输入**不可用** | 不做 Skill 编排；当前不做视觉理解 |
| 本地 Qwen Vision（Ollama，modelscope.cn/unsloth/Qwen3.8-27B-GGUF） | **当前视觉后端**：DGX Spark 本地图片理解、目标存在性判断、描述与视觉证据输出、无法确认时拒答 | 不做 Skill 编排；不做任务编译 |
| Agent Skill（.dsh/skills/ 下自研 Skill） | 受控能力单元：带 SKILL.md、输入输出契约、正/负向触发、安全边界，可被 Harness 发现与复用 | 不是任意领域生成器；不含自由生成代码 |
| DGX Spark 本地算力（GB10、统一内存、CUDA 13.0.2、ARM64） | 提供本地执行环境：DSH 运行时、Ollama 视觉后端、Benchmark 运行环境 | 视觉大模型推理走本地 Ollama（Qwen），不新增其他大模型 |
| OpenCV | 仅作视频抽帧、读取视频元数据、保存关键帧的底层工具（5.0.0，复用本机 vLLM 环境已有安装，未新增依赖；系统 python3 无 cv2 时由 skill_env.py 自动切换解释器） | 绝不是项目核心创新、核心架构或主要卖点 |

## 6. 开发环境历史快照（以 2026-09-21 任务 06 后快照为准；公开版注：本节为开发机运行时快照，不是公开仓库的运行要求——复现前提以 `docs/REPRODUCTION.md` 为准）

- 机型已确认：NVIDIA DGX Spark / GX10；GPU 为 NVIDIA GB10；统一内存架构；CUDA 13.0.2；ARM64。
- DSH 0.1.5-rc.2 已安装并运行；DSH_HOME 指向开发机用户主目录下的 `.dsh`（复现者按 `docs/REPRODUCTION.md` §2.3 自行配置）。
- StepFun Provider 已配置，端点 `https://api.stepfun.com/step_plan/v1`，默认模型 `step-5-preview`（文本链路可用；图片输入在当前配置下不可用）。
- Ollama 运行于 `:11434`；`modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`（vision）为当前视觉后端，**按需加载**（任务 03 实测加载后约 34.6 GB；任务 05 预热实测 ~35.75 GB；任务结束后卸载，需要时由 `analyze_image.py` 重新加载）。
- MiniMax-H3（:8000）：用户的另一路视频生成服务，由用户自行启停（任务 18 期间曾按用户授权优雅停止、恢复方式已记录于内部留档；停止/重启细节不随公开仓库分发）。**本项目任何任务不得停止/重启 MiniMax-H3。**
- OpenCV 5.0.0 位于开发机某含 cv2 的 Python 环境（复现者自备含 OpenCV 的解释器，或设置 `SPARKSKILL_CV2_PYTHON`；本项目不安装任何依赖）。
- 以上事实发生变化时，必须更新本节并在 Git 历史中留痕，不得引用过期事实。

## 7. 当前不可用/未发现的 NVIDIA 组件

- 未发现 NVIDIA 官方 Skills、TAO、VSS、DeepStream、NIM。
- 红线：不得把尚未发现或尚未验证的 NVIDIA 组件写成"已接入"；文档与演示中如需提及，必须如实标注"当前不可用/未接入"。
- 自研 Skill 不得冒充 NVIDIA 官方签名。

## 8. 统一内存资源红线

- DGX Spark 为统一内存架构（119 GiB），大模型占用是核心矛盾。
- 当前常驻：MiniMax-H3（用户服务，运行中）、Ollama 本身、DSH；Qwen3.8-27B 按需加载（约 34.6 GB）。
- 加载 Qwen 前必须检查 `/proc/meminfo` MemAvailable（本项目脚本内置资源守卫，默认阈值 40 GiB）；不足时不强行加载，如实降级并报告，不得停止 MiniMax-H3。
- 任何任务不得为了本项目启动新的大模型、下载模型。
- 停止/重启 MiniMax-H3、Ollama、DSH 对本项目一律禁止（任务 03 的授权停止为例外历史，不得援引）。
- 视觉推理当前走本地 Ollama Qwen；StepFun 文本链路不占本地内存。
- 涉及内存的操作必须先评估对现有服务的影响，未经确认不得执行。

## 9. 项目范围红线

- 本项目不是普通 OpenCV 视频处理工具；OpenCV 只是底层抽帧工具（读元数据/抽帧/存关键帧），绝不是核心。
- 本项目不是任意领域 Skill 生成器；只面向"受控的视觉证据类 Skill"这一狭窄范围。
- 不做人脸识别、身份推断；不做跨镜头身份追踪；不做实时多摄像头。
- 不执行任意模型生成代码（Skill 产出的是配置与契约，不是自由脚本）。
- 证据不足时必须拒答，禁止猜测；负面结论不得表述为存在性断言。
- 禁止输出任何 API key、token、密码或 GUI token。
- 当前实现：**图片最小闭环 + 单段短视频最小闭环 + 多段视频统一证据时间线（任务 06）+ 目标时序证据与粗到细自适应采样（任务 16）**。多段视频时每段独立时间线，按 `time_offset_ms` 合并为统一全局时间线；**全局时间线是证据聚合，不是跨摄像头身份追踪**：同一目标查询在多段视频中分别得到视觉匹配（matched target query / visually consistent with target description / confirmed in source A / confirmed in source B），不得断言同一个物理实例或跨视频移动；`semantic_limitations` 随产物与报告输出。
- **目标时序证据与粗到细自适应采样（任务 16）**：`sampling_strategy` 契约（可选；缺失=旧版 uniform）支持 `uniform`（正式 baseline，行为零变化）与 `adaptive_coarse_to_fine`（初始覆盖 + 按 state_change/abstained/low_confidence/failed 触发器二分细化）；`max_model_calls` 是硬性视觉调用预算（同时间戳至多一次真实调用、可复用证据不重复调用、预算耗尽即停且不算"分析成功"）；产物含采样 provenance 与时序证据（首末 confirmed **采样观察时间**、状态转换左右边界与不确定宽度、五类计数、证据支持状态片段、无法确认片段）。语义红线：首末 confirmed 不等于目标真实进入/离开时间；两个 confirmed 采样点之间不得断言连续存在；状态变化只定位到左右采样点范围；abstained/low_confidence/failed 不得折算为 not_found；不做跨帧身份一致性、不做跨摄像头实例关联、不输出物体运动路径；**不是 ReID、不是目标跟踪器、不是实时跟踪**。technical fixture（合成视频）不得外推为真实仓储准确率。规则测试 27/27（`artifacts/task-16/test-results.json`）。
- **Coverage-Aware 自适应采样与预注册三臂评测（任务 18）**：`sampling_strategy` 契约扩展第三种策略 `coverage_aware_adaptive`（向后兼容；uniform/adaptive_coarse_to_fine 行为零变化）：初始覆盖 + 时间覆盖探索（largest-gap-first 二分压缩未观测间隔；必填 `coverage_gap_target_ms`/`coverage_call_reserve`；`initial_coverage_samples + coverage_call_reserve ≤ max_model_calls`）+ 边界细化（任务 16 同款触发器逻辑，剩余预算）；provenance 区分 `initial_coverage_calls`/`coverage_exploration_calls`/`boundary_refinement_calls`，复算 `max_adjacent_sampling_gap_ms_initial/final`（观测点集 = 已分析时间戳 + 媒体边界）与 `underobserved_intervals`；显式声明不保证发现任意短事件。预注册三臂评测（阶段 A 提交 `dcaf324` 先于实现；11 场景 × 3 臂同预算；任务 17 冻结评分器经兼容适配层评分）：公平门 10/10 × 3 对；pack 级 verdict=TRADEOFF（coverage 对 adaptive 有严格改进——修复任务 17 量化的初始覆盖盲区；但对 uniform 在 twin-short-events 漏检更多——600ms 事件 < 1333ms 覆盖间隔）。规则测试 36/36（`artifacts/task-18/test-results.json`）。**真实 Qwen 三臂评测（287 次真实调用，零失败）与 DSH headless 自主会话（11/12 次调用，离线评分 11/11）均已完成**（补跑轮；此前两轮资源阻塞历史保留于 `resource-gate-rerun.json`；用户授权优雅停止 MiniMax-H3 服务族见 `h3-shutdown-record.json`，任务结束后 H3 保持停止）。**replay 与 real 分别评分、分别给 verdict、不混合平均**：replay  pairwise coverage-vs-adaptive = IMPROVEMENT、pack = TRADEOFF；**real pairwise 三对全 TRADEOFF、pack = TRADEOFF**——真实 Qwen 触达 uncertain 区域后过度断言而非拒答（overclaim：coverage 4 / uniform 2 / adaptive 0；重现任务 16 确定性负面 overclaim 模式），coverage-vs-adaptive 的 IMPROVEMENT 在真实模型下不成立，差异源于视觉模型语义而非采样策略；真实运行同时证实 coverage 采到短事件后 Qwen 能正确识别、600ms twin 事件仍漏检。**不得声称任意短事件必检、真实域效果或统计显著性；工程 PASS 不等于算法全面优于基线；用户 dev/holdout 尚未接入。**
- **dev Evidence Pack 三策略真实基线评测（任务 19B）**：用户 dev 包（`<DEV_EVIDENCE_PACK_ROOT>`，仓库外只读；AI01–AI06 MiniMax-H3 生成受控测试视频 + WEB01–WEB03 Pexels licensed-public）第一次接入冻结三策略评测。硬纪律：**先测量、不校准**（视觉 Prompt/采样算法/证据分类/报告规则/scorer/adapter 零改动）；预注册（阶段 A 提交 `e3ef01e`）先于任何 dev 模型调用；GT 唯一来源为 transfer-safe 卡，确定性结构规范化（相邻同状态合并 + 末段终点对齐实测时长；状态覆盖与边界集合不变）；execution manifest 标签隔离；预算 `clamp(ceil(duration/1000),12,24)` 只依赖媒体时长与通用政策；臂顺序样本间轮换；无单侧重试；generated 与 licensed-public 分轨报告（真实轨道仅三段=小样本真实域观察）；工程状态（BASELINE_COMPLETE/PARTIAL/INVALID_EVALUATION）与算法 verdict 分开。结果：27/27 运行、256 次真实调用、三范围 pack verdict 全 NO_IMPROVEMENT；核心缺陷为**模型语义校准失败**（AI06 uncertain 双向过度断言、AI04 遮挡区过度确认、WEB01/WEB03 真实域误报、全部 8 个 GT 边界 matched=0）。原始视频不入 Git（媒体链接农场为只读符号链接，`.gitignore` 排除）；未修复 dev 失败、未开始校准、未触碰 holdout。
- **视觉证据判断校准：同期同帧配对实验（任务 20，2026-09-23）**：在 Task 19B 冻结 dev 基线上检验**唯一变量为通用视觉判断语义版本**（v1 现行模板 → v2 候选，仅改判断纪律段：三类判断准入 + 拒答触发条件 + 置信度纪律；JSON 契约与证据状态集合不变、不含素材特定提示）的同期同帧配对：256 个 Task 19B 采样点 × 2 版 = **512 次真实 Qwen 调用**（+warm-up 1 + smoke 4，均 fixture 帧、不计入正式；511 ok + 1 契约拒绝、0 超时、0 重试）。硬纪律：预注册提交（`31cf893`，preregister）**早于第一笔 dev 采样点调用**（02:04:49Z < 02:38:47Z，V1 时序证明）；一个 v2 候选、一次预注册、一次正式实验；看见结果后不得改参数；帧同一性 = 每点 v1/v2 同一份帧字节（帧农场 184 唯一帧，与 Task 19B 盘上帧逐字节一致——盘上实证；正式口径为同媒体同时间戳，因 Task 19B 未冻结帧哈希）；运行顺序按索引轮换（v1 先/v2 先各 128）；GT 不进入视觉请求；新配对评分器（`paired_scorer.py`）与 Task 17 冻结评分器同义重实现，256 个历史点逐行等价证明（零 mismatch）。**结果：verdict = TRADEOFF**——v2 让不可判定画面更愿意拒答（overclaim 40→34，降幅 6 ≥ 5；appropriate_abstention 6→11；incorrect 24→23；failed 持平），但**拒答精确度不足**：6 个可判定帧被推入拒答，其中 **5 个是正确判断损伤**（AI01 t=666 运动模糊边际帧 ×3 臂、WEB03 t=17480 末帧 adaptive/coverage 两臂）、**1 个是误报修复**（WEB03 t=17480 uniform 臂，v1 误报→拒答；七类账 v1/v2 各 256，v2 五类主表 249 = 五类口径子集 + 补充两类 6+1，见勘误 E1/E2），correct_decisive 186→181（−5 超容忍 4）、licensed-public −2 超容忍 1 → G3 FAIL。按预注册停止门：**不运行阶段 C 动态三臂、不做 DSH 自主会话、不迭代第二个候选**；v2 候选未被采纳进 Skill（analyze_image.py 零改动，v1 仍是生产模板）。AI04 遮挡区 9 个采样点 overclaim 9→8（1 点转拒答；样本总数 24，勘误 E3）、AI06 overclaim 26→21 / 拒答 6→10（未解决，双向过度断言仍存）、WEB01 无变化（incorrect 9、[4000,4500] 仍未触达）、WEB03 误报 10→9 且 3 次 determinate 拒答（1 次误报修复 + 2 次误拒；样本总数 36 非 48，勘误 E4）；**Task 19B 历史 v1 动态三臂 8 个 GT 边界 0/8；Task 20 v2 动态边界 not_measured（阶段 C 未运行）**；Task 21 固定采样重放（规则级反事实，非动态实测）对同期 v1/v2 存档输出各 0/24 次边界暴露匹配（勘误 E6）。工程状态 PAIRING_COMPLETE 与模型质量状态（TRADEOFF）分开；dev 小样本 + 单次运行 + 温度 0.1 随机性（同期 v1 vs 历史 249/256 一致；去重 184 唯一帧，v2 五类去重表须补示 abstention_on_determinate 2 + failed_on_uncertain 1，"首现行"去重有跨臂选择依赖，勘误 E5），不得给出统计显著性、不得外推真实仓储准确率。任务 20 原始产物（run-summary、preregistration、pairs、scores、verification）与任务 21 固定采样重放为内部留档；**人类可读口径勘误：`artifacts/task-21/errata/task20-errata.md`（随公开仓库分发）**。
- **Evidence Pack 数据契约与时间 Ground Truth 评分（任务 17）**：`schemas/evidence-pack-manifest.schema.json`（输入清单，**不得内嵌时间真值**）与 `schemas/temporal-ground-truth.schema.json`（显式独立真值输入）分离；dev/holdout 隔离（holdout GT 只由持票方显式传入，内容不进任何输出，只进 SHA-256 摘要）；`scripts/validate_evidence_pack.py` + `scripts/score_temporal_ground_truth.py`（项目级工具，**不新增第四个 Skill**）做确定性 CPU-only 评分（零模型调用）：8 项输入硬门（样本一致/媒体哈希冻结/查询一致/时长一致/GT 时间线合法/时间戳范围/provenance 自洽/预测形态）；七类采样点计数（correct_decisive/incorrect_decisive/abstention_on_determinate/failed_on_determinate/appropriate_abstention/overclaim_on_uncertain/failed_on_uncertain，每项分母=对应类别分母，0 分母写 `not_applicable`）；事件覆盖与 transition 一对一匹配（方向兼容：decisive→decisive 不得匹配涉及 uncertain 的 GT 边界）；效率指标不抵消语义错误。**口径红线**：`execution_status=completed` 只表示流水线完成，**不等于语义正确**；任务 16 旧 `IMPROVEMENT` 是旧口径历史结论（`artifacts/task-16/comparison.json` 未篡改），任务 17 严格 scorer 对同一冻结产物复算的 verdict 为 **TRADEOFF**（`artifacts/task-17/comparison.json`），历史结论只通过新报告补充、不回写篡改；合成 fixture 不是真实仓储准确率；用户 8 AI + 4 真实视频 Evidence Pack 上传前不得声称真实域评分已完成。规则测试 38/38（`artifacts/task-17/test-results.json`，内部留档版结果；公开版排除 4 个 holdout 同名 fixture 后为 34/34，本次实测通过）。
- **真实 Qwen 视频逐帧分析已于任务 05 在资源窗口内由 DSH 自主 Agent 验证**（正向 confirmed=5/failed=1、负向 not_found=6；任务 05 原始会话产物为内部留档）；**DSH 会话内 Agent 自主加载 Skill 并驱动完整流水线亦已于任务 05 验证**（同上）；**多段视频统一证据时间线（多媒体规格 + 全局时间线 + 跨视频语义边界 + 像素坐标受控归一化）已于任务 06 由 DSH 自主 Agent 验证**（正向 8/8 confirmed、负向 8/8 not_found；任务 06 原始产物为内部留档；其规则测试 `test_multi_video_pipeline.py` 随公开仓库分发，公开版实测 32/32）。
- **Tier-3 对照评测（任务 07）**：baseline（不加载 Skill，项目外隔离目录）vs with-skill（加载三 Skill）严格对照，9 任务 × 两侧 = 18 个真实 headless 会话，确定性规则评分。初始结果（提交 25a4f11）：Discoverability 4/9→8/9、Effectiveness 6/9→9/9、Security 8/9→8/9、Correctness 8/9→8/9、总耗时 −38.7%、Verdict PARTIAL（E9 缺失媒体处理失败，未隐藏）。详见根目录 `BENCHMARK.md`；**小样本，不得外推为大规模生产结论**。
- **E9 修复与评测器 v2（任务 08/09）**：E9 为真实产品缺陷，已由媒体来源 provenance 硬门修复（`check_source_media.py` + needs_input/missing_source_media 契约；M1–M8 10/10、E9 稳定性 3/3）；v1 冻结评分器（SHA-256 c35b4506…，未修改）存在 stdout 断言语境误报，已按用户决策新增版本化评分器 v2（`score_tier3_eval_v2.py`，唯一变化为 stdout/文件一致的从句级语境判定，回归 17/17），对任务 08 冻结数据全量对称重评分后：**Security 9/9→9/9、Correctness 7/9→9/9、Discoverability 5/9→9/9、Effectiveness 6/9→9/9、Verdict PASS**。PARTIAL 历史与冻结资产完整保留（BENCHMARK.md 历史链）。

## 10. 本地视觉证据工作台（任务 10）

- `app/` 为完全离线、CPU-only 的本地界面：展示历史真实 artifacts，**不是浏览器实时调用模型**；
- Truth Status 五级必须如实标注：Verified（有真实 Harness/模型/程序化校验产物）、Recorded（历史真实运行，当前不重新执行）、Structural（仅 Schema/抽帧/状态机）、Blocked（资源/环境未完成）、Synthetic Fixture（自动测试数据）；
- 禁止把 Recorded 显示成实时运行、Structural 显示成模型验证、Blocked 显示成 Success、命令行串联显示成 DSH 自主编排；
- 服务只监听 127.0.0.1:8787，只读，媒体仅限显式 allowlist（video-a/video-b；公开版 allowlist 指向仓库内 `artifacts/task-16|task-18/fixtures/videos/` 的自产合成 fixture，内部留档版曾指向开发机测试媒体），不服务凭据/配置/模型权重，不允许目录遍历；
- Tier-3 Benchmark 历史必须完整展示（Initial PARTIAL → E9 Remediation → Evaluator v1 Finding → Evaluator v2 PASS），不得只展示最终 PASS。

## 11. 后续 Agent 协作规则

- 每个 Agent 开始工作前必须阅读：本文件 → `README.md` → `docs/DEVELOPMENT_STATUS.md` → 当前设计文档。
- 改动必须符合既定路线（赛事四份资料 + 任务书），不得私自扩大或改写项目范围。
- 不得安装依赖、下载模型、修改 DSH 全局配置、修改环境变量、启动/停止/重启任何服务，除非获得用户明确指示。
- 提交信息使用约定式提交（conventional commits）；初始化提交为 `chore: initialize SparkSkill Studio project`。
- 文档中不得写入未经验证的性能数字；不得写入任何密钥。
- 发现环境事实与本文件不符时，先更新文档再继续工作，并在汇报中说明。

## 12. 架构口径、复现入口与许可（任务 15 确立）

### 12.1 唯一架构口径（全仓一致，任何文档/演示/征文不得偏离）

| 组件 | 职责 | 明确不负责 |
| --- | --- | --- |
| StepFun `step-5-preview`（经 DSH 文本链路） | 理解用户文本任务、规划、生成结构化 VisualTaskSpec | **不读取图片、不识别视频帧、不做视觉推理**（当前 DSH 配置下 provider 未声明图片输入能力） |
| DSH `0.1.5-rc.2` | Agent Harness：发现、加载和编排项目 Skill | 不承担视觉推理本身 |
| `task-to-skill-compiler` | 把文本视觉任务编译为受约束的 VisualTaskSpec；媒体来源 provenance 硬门；采样策略契约（uniform/adaptive_coarse_to_fine/coverage_aware_adaptive + 硬预算 + 边界精度 + 覆盖目标与覆盖储备，任务 16/18） | 不做视觉推理、不生成可执行代码 |
| OpenCV（5.0.0） | 底层视频解码、读取元数据、抽帧、保存关键帧 | **不是核心创新、不是卖点** |
| 本地 Ollama Qwen3.8-27B Vision | 读取图片和视频帧、生成结构化视觉证据、证据不足时拒答 | 不做 Skill 编排、不做任务编译 |
| `visual-evidence-extractor` | 约束视觉调用、证据格式、坐标规范与拒答边界；uniform/adaptive/coverage_aware_adaptive 采样、采样 provenance、时序证据与覆盖探索声明（任务 16/18） | 不生成最终报告 |
| `evidence-report-generator` | 依据证据生成报告并执行反幻觉交叉校验；时序证据报告（独立复算状态转换与边界不确定性，显示调用预算、覆盖探索与边界细化调用区分、最大相邻采样间隔与"采样证据支持的时序结论，不是连续跟踪真值"，任务 16/18） | 不做视觉推理 |
| Evidence Workbench（`app/`） | **只读展示已经保存的真实 artifacts** | **不在浏览器内实时调用 StepFun / Qwen / DSH / 三个 Skill** |

平台价值表述：NVIDIA DGX Spark GX10/GB10 本地算力、统一内存环境下的本地视觉模型运行、数据不离开本地视觉推理环境、
Agent/视觉模型/生成服务之间的资源治理。**不得把普通 OpenCV 处理包装成 NVIDIA 技术创新。**

### 12.2 文档与复现入口

- `docs/REPRODUCTION.md`：陌生环境复现与部署说明（唯一入口，README 必须可导航到）；
- `docs/OPTIMIZATION_NOTES.md`：优化说明（已做的系统层优化 + 明确没有做的模型权重级优化）；
- `docs/PUBLIC-VERSION-NOTES.md`：公开版与内部留档版的关系（收录范围、脱敏记录、可复算边界、停止门）；
- `.interface-design/system.md`：界面设计系统（任务 15 起与 `app/styles.css` 的 `:root` 保持一致；
  任务 10 暗色令牌为历史记录，不再是当前规范）。

### 12.3 许可

- 本仓库代码与三个自研 Skill 按 **Apache License 2.0** 开源（`LICENSE`，`Copyright 2026 tangjue3`）；
- 第三方模型、模型权重与素材遵守各自许可证；**仓库不包含任何第三方模型权重**；
- 自研 Skill 不冒充 NVIDIA 官方签名 Skill；当前未接入 NVIDIA 官方 Skills、TAO、VSS、DeepStream、NIM。
