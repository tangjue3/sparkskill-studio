# OPTIMIZATION NOTES — Agent 系统、契约、安全、编排与资源治理优化说明

> 赛事"智能体与模型优化技术深度"维度的证据文件。
> **口径声明（必须与本文一起阅读）**：本项目的"优化"指 **Agent 系统层、契约层、安全层、编排层与资源治理层**的工程优化，
> **不是模型权重级优化**。本文不声称任何量化、投机解码、vLLM serving 调优或训练/微调是本项目实现的模型优化。

---

## 1. 已完成的优化（每项都有代码与真实运行证据）

### 1.1 VisualTaskSpec 契约化

- 自然语言视觉任务被编译为符合 `schemas/visual-task-spec.schema.json` 的结构化规格：
  `task_id` / `skill_name` / `task_type` / `target` / `source_media` / `required_outputs` /
  `constraints` / `confidence_threshold` / `requires_visual_input`；
- `additionalProperties: false` + 枚举收敛：非法 task_type、缺字段、额外字段一律拒绝（exit 1）；
- 效果：视觉任务从"自由问答"变为"可校验、可复现、可评分"的结构化契约。
- 证据：`schemas/visual-task-spec.schema.json`、`.dsh/skills/task-to-skill-compiler/scripts/validate_task_spec.py`、
  `artifacts/task-03/task-spec.json`（RESULT: VALID）。

### 1.2 Skill 触发边界与负向触发

- 每个 Skill 有显式正向触发与负向触发：非视觉任务、身份/年龄/国籍/关系/意图推断、生成代码或 shell、
  凭据相关请求一律拒绝，不产出 VisualTaskSpec；
- 效果：误触发 0 次（任务 03 起累计记录）；Tier-3 E6（写诗）with-skill 侧未加载任何 Skill 直接完成。
- 证据：三个 `SKILL.md` 的"正向触发/负向触发"节、`.dsh/skills/task-to-skill-compiler/BENCHMARK.md`。

### 1.3 媒体来源 provenance 与缺参硬门（任务 08 根因修复）

- 视觉任务的 `source_media` **只能来自当前用户请求**：`check_source_media.py` 是请求文本纯函数，
  输出四态契约 `accepted` / `needs_input(missing_source_media)` / `rejected(invalid_source_media|inferred_source_media)` /
  `not_applicable`；
- 缺参时唯一允许动作是把契约返回用户：禁止搜索项目文件、读取历史 artifacts、目录扫描、
  加载视觉 Skill 或调用视觉模型（停止清单逐条列明，任务 08 稳定性复测曾发现违规搜索并已强化）；
- 缺失路径（问用户）与非法路径（拒绝）**不得互相退化**；
- 效果：契约测试 M1–M8 从修复前 0/10 到修复后 10/10；E9 稳定性 3/3（0 Qwen 调用、0 视觉命令、0 搜索）。
- 证据：`.dsh/skills/task-to-skill-compiler/SKILL.md` 第 0 步、`scripts/test_missing_media_contract.py`、
  `artifacts/task-08/pre-fix-regression/`（修复前失败证据，保留）。

### 1.4 视觉证据结构

- 证据 JSON 固定字段：`object_found` / `description` / `bounding_box` / `confidence` /
  `evidence_text` / `abstention_reason`；`object_found=false` 必须填 `abstention_reason`；
  confidence 低于任务阈值标记 `evidence_sufficient=false` 并记入 `gaps`；
- 视频证据时间线每项必须对应**真实抽取的帧文件**（`frame_path` 可回溯），严格区分
  confirmed / not_found / abstained / failed 四态；
- 效果：结论可逐帧审计；负向结论不被表述为存在性断言。
- 证据：`references/evidence-schema.md`、`references/video-evidence.md`、`artifacts/task-05/（内部留档）raw-frames/（内部留档）`、
  `artifacts/task-06/raw-frames/`（模型原始返回存档）。

### 1.5 像素坐标确定性归一化

- 模型返回像素坐标时，仅当四元数值、全部 >1（混合拒绝）、`x1<x2`/`y1<y2`、不越界、可读真实帧宽高，
  才确定性归一化到 0–1，并记录 `bounding_box_source_format="pixel"`、
  `bounding_box_normalization_applied=true`、`frame_width/frame_height` 与原始值 `bounding_box_raw`；
- 否则 bbox 置 null + warning，**不重跑模型凑结果**；
- 效果：任务 05 中一帧越界像素坐标 `[431,222,545,356]` 被如实拒绝（未修补/未伪造）；任务 06 中 3/8 帧
  按契约归一化且数学校验全部正确（如 raw=[432,222,545,356] @ 960×576 → [0.45, 0.385417, 0.567708, 0.618056]）。
- 证据：`scripts/analyze_image.py` 的 `normalize_bounding_box()`、`artifacts/task-06/test-results.json`（B 组 10 项）。

### 1.6 报告状态独立复算与交叉校验

- 报告引擎按帧/全局条目**独立复算**状态，并与 `timeline.summary.overall_status` /
  `global_summary.overall_status` 交叉校验；不一致以复算结果为准并记入 `warnings`；
- 效果：两套实现互检，防单点规则错误；注入的不一致被复算纠正（任务 04/06 均验证）。
- 证据：`.dsh/skills/evidence-report-generator/scripts/generate_report.py`、
  `artifacts/task-06/test-results.json`（D 组）、`artifacts/task-04/（内部留档）test-results.json（内部留档）`（B6）。

### 1.7 反幻觉规则

- 无视觉证据 → `status=failed`，`conclusion=null`，不作存在性断言；
- `object_found=false` → 只给负面结论；`abstention_reason` 非空 → `status=abstained`；
- `conclusion` 只能由输入证据字段组成，不得添加输入中不存在的事实；
- 视频/多视频结论必须可回溯到具体帧；
- 效果：图片规则 7/7、视频模式 5/5、任务 05 真实时间线报告 4/4、任务 06 多视频报告 5/5，无幻觉、无越证。
- 证据：`.dsh/skills/evidence-report-generator/BENCHMARK.md`。

### 1.8 多来源时间轴聚合

- 每来源独立调用单段视频能力（**未重写视觉提示词或视频处理逻辑**），保留 `source_id` 与原视频时间戳；
- `global = 原时间戳 + time_offset_ms`，按 `(global_timestamp_ms, source_id)` 排序合并；
  failed / abstained / not_found 全部保留；每来源与全局的首末确认与确认帧数分别统计；
- 跨视频语义边界：只允许 matched target query / visually consistent with target description /
  confirmed in source A / confirmed in source B；禁止 same physical instance / moved from A to B /
  identity matched；`semantic_limitations` 随产物与报告输出；
- 效果：任务 06 正向 8/8 confirmed（全局 0.0 → 12958.333 ms）、负向 8/8 not_found（bbox 全 null）；
  规则测试 32/32。
- 证据：`scripts/trace_multi_video.py`、`references/multi-video-evidence.md`、
  `artifacts/task-06/global-timeline.json`、`artifacts/task-06/test-results.json`。

### 1.9 资源门槛与统一内存治理

- 调用视觉模型前检查 `/proc/meminfo` 的 `MemAvailable`，低于阈值（默认 40 GiB；Qwen 加载约需 34.6 GB）
  时不加载模型，全部帧标记 failed 并如实报告"真实视觉调用被资源条件阻塞"；
- 视觉模型按需加载 / 用后卸载；不停止机器上既有服务、不强载导致 OOM、不安装依赖、不下载模型；
- OpenCV 复用机器上已有的安装（`skill_env.py` 自动切换解释器），零新增依赖；
- 效果：任务 04 资源窗口关闭时如实降级 failed（未伪造输出）；任务 05/06 窗口打开时真实跑通。
- 证据：`PROJECT_CONTEXT.md` §8、`scripts/analyze_image.py` 资源守卫、
  `artifacts/task-05/（内部留档）run-summary.md`（内存表）、`artifacts/task-05/（内部留档）resource-blocker-report.md（内部留档）`（历史保留）。

### 1.10 baseline vs with-skill：Skill 价值的可度量证明

- 方法：同一个 DSH Agent、同一任务文本、同一模型/媒体/帧上限/超时，唯一变量为是否加载项目 Skill；
  baseline 在项目外隔离目录（无 `.git` 祖先、项目 Skill 不被发现、目录每次重建）执行，带污染检测；
  按任务交替、每任务独立会话、运行前统一预热；确定性规则评分（不用第二个大模型当裁判、不让被测 Agent 自评）。
- 结果（v2 对任务 08 冻结数据全量重评分）：

| 维度 | baseline | with-skill |
| --- | --- | --- |
| Security | 9/9 | 9/9 |
| Correctness | 7/9 | 9/9 |
| Discoverability | 5/9 | 9/9 |
| Effectiveness | 6/9 | 9/9 |

- 数量指标：总耗时 3534.4s → 800.5s、工具调用 292 → 157、Qwen 调用 1 → 17
  （**baseline 为可观测下限**：其自建脚本的内部调用无法存档）；重试 0/0、失败 0/0、超时 0/0；
- 可发现性差距的具体表现：baseline 在 5 个视觉任务中**均未发现本地 Qwen Vision**（0/5，E1 因此给出错误负面结论），
  with-skill 5/5 发现并正确使用；
- 证据：`BENCHMARK.md`、`artifacts/task-07/comparison.json`、`artifacts/task-09/comparison-v2.json`、
  `artifacts/task-09/verdict-v2.json`。

### 1.11 评分器版本化与冻结数据重评分纪律

- v1 评分器冻结（SHA-256 `c35b4506…`，未修改）；发现其 stdout 断言语境误报（把合规否定/政策声明当作违规）后，
  按"不修改 / 单独报告 / 停止 / 等待用户决定"流程处理，用户选方案 B；
- v2（SHA-256 `949772c9…`）以导入方式继承 v1 全部 22 条规则，仅覆盖 S1/S5 两条断言扫描规则，
  唯一逻辑变化为"stdout 与文件一致的从句级否定/声明语境判定"+"补全否定标记清单"；
  任务集、PASS 条件、baseline/with-skill 定义与 v1 逐字节一致；
- v2 对任务 08 **冻结原始输出**全量重评分（未重跑任何模型会话），差异精确检查：仅 2 项规则级变化、
  全部为允许的已知误报修复（FAIL→PASS）、0 项意外变化；
- 回归 17/17（N1–N5 合规不判违规、P1–P5 真实断言含混合语境判违规、C1–C2、语境判定精度、继承性）；
- 证据：`scripts/score_tier3_eval_v2.py`、`scripts/test_score_tier3_eval_v2.py`、
  `artifacts/task-09/evaluator-regression.json`、`artifacts/task-09/evaluator-diff.json`、
  `artifacts/task-08/frozen-evaluator-findings.md`。

---

## 1.12 目标时序证据与粗到细自适应采样（任务 16）

- **问题**：固定抽帧 + 逐帧存在性判断无法回答"目标大约何时出现/消失，答案的不确定度是多少"；定长网格不区分稳定区间与变化区间，视觉调用预算被浪费在低信息量帧上。
- **契约化采样策略**：`sampling_strategy`（可选，向后兼容）把"怎么抽帧"从脚本参数提升为受 Schema 约束的任务契约——uniform（正式 baseline）/ adaptive_coarse_to_fine（初始覆盖 + 按 state_change/abstained/low_confidence/failed 触发器二分细化）、`max_model_calls` 硬预算、`target_boundary_precision_ms` 目标边界精度、`max_refinement_rounds`；非法组合在编译期（校验器）与执行期（`adaptive_sampler.parse_strategy_config`）双重拒绝。
- **硬性调用预算治理**：同一时间戳至多一次真实 Qwen 调用（时间戳缓存 + skipped_duplicate 记录）；已有可复用证据不重复调用；预算耗尽即停并如实报告（`budget_exhausted`，不算"分析成功"）；无法达到目标精度时输出剩余不确定性（`residual_uncertainty_ms` + `target_precision_reached=false`）；资源守卫阻塞时未执行的调用不计为真实视觉调用（`evidence_nature=backend_not_called` vs `real_model_output` vs `backend_call_failed` vs `constructed_fixture_evidence`）。
- **可追溯采样决策**：`sampling_provenance` 记录每次决策（时间戳/阶段/理由/触发区间/决策时观察状态/第几次调用/缓存状态/预算快照）、集中式 `decisions[]`、`analyzed_timestamps`、`stop_reasons`、逐阶段耗时；落盘前凭据自检。
- **可复算时序证据**：首末 confirmed 采样观察时间、状态转换左右边界与不确定宽度、五类计数、证据支持状态片段、无法确认片段；报告引擎用**第二套独立实现**复算并交叉校验（不一致以复算为准 + warning），不静默接受上游摘要。
- **公平对照**：uniform 与 adaptive 同预算/同视频/同查询/同模型/同状态规则（同一 `frame_class` 实现）对照，不删失败样本、不单侧重试、不看结果改 ground truth；Verdict 不预设（`artifacts/task-16/comparison.json`）。
- **证据**：`schemas/visual-task-spec.schema.json`、`.dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py`、`trace_temporal.py`、`references/temporal-evidence.md`、`artifacts/task-16/`。
- **口径**：这是 Agent 系统层/契约层/资源治理层优化，**不是模型权重级优化**；technical fixture 小样本结果不得外推为真实仓储准确率。

---

## 1.13 Evidence Pack 数据契约与时间 Ground Truth 评分（任务 17）

- **问题**：任务 16 的对照把"流水线完成 / 证据语义正确 / 采样效率"混在一起——`execution status=completed` 只表示流水线跑完；abstain-zone 的真实 Qwen 输出是确定性负面、与 fixture 不确定区真值冲突，却被"最终状态正确"掩盖；adaptive 初始覆盖盲区（窄不确定区完全未触达）没有指标量化；旧 `IMPROVEMENT` 更接近效率与已检测边界改进。
- **契约化分离**：`schemas/evidence-pack-manifest.schema.json`（输入清单：媒体身份 + split + 来源 provenance，**不得内嵌时间真值**）与 `schemas/temporal-ground-truth.schema.json`（显式独立真值：区间语义 + 容差 + 标注版本 + 冻结与修订历史，**不得包含模型字段**）分离；dev/holdout 隔离（holdout GT 内容不进任何输出，只进摘要）。
- **确定性评分**：`scripts/score_temporal_ground_truth.py` 零模型调用、纯标准库；8 项输入硬门（样本一致/媒体哈希冻结/查询一致/时长一致/GT 时间线合法/时间戳范围/provenance 自洽/预测形态）；七类采样点计数把"uncertain 上的拒答"与"uncertain 上的过度断言"分开；transition 一对一最大匹配 + 方向兼容（decisive→decisive 不得匹配涉及 uncertain 的 GT 边界，不把整个 uncertain 区域伪装成精确进入/离开时刻）；效率指标与语义分开且不抵消语义错误。
- **可复算比较**：10 条件 fairness gate + 四类 verdict（IMPROVEMENT/TRADEOFF/NO_IMPROVEMENT/INVALID_COMPARISON）全部由指标计算，不预设结果；不可观测条件（无单侧重试/额外上下文）由调用方显式声明并记录依据。
- **对任务 16 的诚实复算**：旧 `IMPROVEMENT` 保留为历史口径；严格 scorer 对同一冻结产物复算得 **TRADEOFF**（adaptive 34 vs uniform 60 调用、平均边界误差 138.333 vs 150.0 ms，但 unreached uncertain 1 > 0；uniform 在 uncertain 区间 3/3 过度断言）——效率收益真实存在，语义覆盖缺口同时被量化，不再被"最终状态正确"掩盖。
- **测试与回归**：新测试 38/38（34 个确定性 fixture 用例 + 分类规则一致性/确定性/输入只读/输出卫生）；回归任务 16 27/27、任务 04 16/16、任务 06 32/32、M1–M8 10/10、v2 评分器 17/17、工作台静态 26/26；`git diff --check` clean；敏感扫描 0 命中；任务 07/08/09/16、Tier-3、app/ 零改动。
- **证据**：`schemas/evidence-pack-manifest.schema.json`、`schemas/temporal-ground-truth.schema.json`、`scripts/validate_evidence_pack.py`、`scripts/score_temporal_ground_truth.py`、`scripts/test_temporal_ground_truth_scoring.py`、`artifacts/task-17/`。
- **口径**：Agent 系统层/契约层评测基础设施优化，**不是模型权重级优化**；合成 fixture 小样本不外推；8 AI + 4 真实视频上传前不得声称真实域评分已完成。

---

## 1.14 Coverage-Aware 自适应采样与预注册三臂评测（任务 18）

- **问题**：任务 17 复评量化了 adaptive_coarse_to_fine 的覆盖盲区——触发式细化只放大已观测信号（状态变化/拒答/低置信/失败），完全落在初始采样点之间的窄事件/窄 uncertain 区不产生任何信号，策略在结构上无法发现它们（abstain-zone `unreached_uncertain_segments=1`）。
- **双职责策略**：`coverage_aware_adaptive` 在同一硬预算内把"时间覆盖探索"（largest-gap-first 二分压缩未观测间隔，纯几何、不看证据类别）与"事件边界细化"（任务 16 触发器逻辑，剩余预算）分离；provenance 用 `phase`/`purpose` 区分两类调用，并可复算最大相邻采样间隔（观测点集 = 已分析时间戳 + 媒体边界）与剩余盲区（`underobserved_intervals`）。
- **预算治理**：`initial_coverage_samples + coverage_call_reserve ≤ max_model_calls` 编译期/执行期双拒绝；三类调用之和 = 实际调用 ≤ 硬预算；覆盖储备用尽/目标达成/预算耗尽/帧分辨率收敛均为确定性停止并记录原因。
- **诚实边界**：产物显式声明 `arbitrary_short_event_detection_guaranteed: false` 与 `events_shorter_than_max_sampling_gap_may_be_missed: true`；twin-short-events 场景实证两个 600ms 事件落在 1333ms 覆盖间隔内时 coverage 与 adaptive 均漏检——覆盖是发现的必要非充分条件，且覆盖与模型语义校准（uncertain 区域的 overclaim）是两个独立问题。
- **预注册评测纪律**：评测协议（三臂配置、11 场景、预算、顺序、指标、pairwise 与 pack 级 verdict 规则、公平门）在实现前以独立提交冻结（`dcaf324`）；任务 17 冻结评分器零改动，经内存扩展策略白名单的适配层复用于第三臂；verdict 全部由冻结规则从指标计算（pack 级 TRADEOFF：coverage 对 adaptive 严格改进——盲区修复；对 uniform 在对抗场景漏检更多）。
- **测试与回归**：新测试 36/36（契约/兼容/预算/覆盖/细化/场景/五类分支/uncertain 评分/GT 不进入采样/只读/卫生/provenance 自洽/多来源/资源守卫/四类 verdict/预注册哈希）；回归任务 17 38/38、任务 16 27/27、任务 04 16/16、任务 06 32/32、M1–M8 10/10、v2 17/17、工作台 26/26；交付验证 24/24。
- **真实模型验证（补跑轮，2026-09-22）**：用户授权优雅停止 MiniMax-H3 服务族（纯 SIGTERM，`h3-shutdown-record.json`）后，`--mode real` 三臂评测 287 次真实 Qwen Vision 调用（零失败）与 DSH headless 自主会话（11/12 次调用，离线评分 11/11）均完成。真实模式 verdict（冻结规则计算）：pairwise 三对全 TRADEOFF、pack TRADEOFF；**coverage vs adaptive 由 replay 的 IMPROVEMENT 变为 TRADEOFF**——真实 Qwen 触达 uncertain 后过度断言（overclaim coverage 4/adaptive 0），差异源于视觉模型语义而非采样策略（两种模式调用计划完全一致）。replay 与 real 分别评分、不混合平均。
- **证据**：`docs/plans/2026-09-22-coverage-aware-adaptive-sampling-design.md`、`artifacts/task-18/preregistration/`、`artifacts/task-18/deterministic/`、`artifacts/task-18/real-qwen/`、`artifacts/task-18/dsh-session/`、`artifacts/task-18/three-arm-comparison.json`、`schemas/visual-task-spec.schema.json`、`.dsh/skills/visual-evidence-extractor/scripts/{adaptive_sampler,trace_temporal,test_task18_coverage_sampling}.py`、`scripts/{run_task18_comparison,task18_scorer_adapter,generate_task18_fixtures,assemble_task18_final}.py`。
- **口径**：Agent 系统层/契约层/资源治理层优化，**不是模型权重级优化**；replay 度量采样几何、real 度量真实模型语义，两者结论分别报告；合成 fixture 小样本不外推；不得声称任意短事件必检；工程 PASS 不等于算法全面优于基线。

---

- **没有训练或微调任何模型**：未做 SFT、LoRA、RLHF 或任何参数更新；
- **没有修改 Qwen 权重**：视觉后端是现成的 `modelscope.cn/unsloth/Qwen3.8-27B-GGUF`（Q4_K_M），
  本项目只调用与约束它；
- **没有把量化、投机解码或 vLLM 实现为本项目的模型优化**：Q4_K_M 量化来自模型发布方；
  vLLM 环境仅被复用为 OpenCV 的运行环境（本机既有安装），本项目未修改、未调优它；
- **没有接入 NVIDIA 官方 Skills、TAO、VSS、DeepStream 或 NIM**：当前环境未发现这些组件，
  不得声称已安装、已接入或已使用；
- **没有统计显著性结论**：每侧 9 个任务、单次运行，通过数/总数不构成统计显著性，不外推为大规模生产性能；
- **没有做跨摄像头身份或实例关联**：明确非目标（需要可靠关联证据）；
- **没有实现浏览器实时模型调用**：工作台是只读 recorded-artifact viewer。
- **真实域 Ground Truth 评分已完成第一轮（dev 九样本，任务 19B）**：用户 dev Evidence Pack（6 生成 + 3 真实）已接入并完成未校准基线评分（27/27 运行、256 次真实调用、三范围 pack verdict 全 NO_IMPROVEMENT）；但 **holdout 三样本仍未接入**，licensed-public 轨道仅三段（小样本真实域观察），不得声称真实仓储准确率、统计显著性 or 生产可用性；competition profile 的 12 样本口径（8 AI + 4 真实）尚未凑齐。

---

## 1.15 dev Evidence Pack 三策略真实基线与"先测量后校准"纪律（任务 19B）

- **真实域基线已建立（未校准）**：用户 dev 包（6 段 MiniMax-H3 生成受控测试视频 + 3 段 Pexels licensed-public）第一次接入冻结三策略评测：27/27 真实运行、256 次真实 Qwen 调用、零失败；任务 17 冻结 scorer + 任务 18 适配层评分（27 份硬门全过、逐样本公平门 27/27）；三范围 pack verdict 全部 NO_IMPROVEMENT（`artifacts/task-19/`）。
- **本轮量化的核心缺口是模型语义校准，不是采样几何**：uncertain 区双向过度断言（AI06 overclaim 11/7/9、abstention 仅 1/3/1）、遮挡区过度确认（AI04 三臂全部 confirmed）、真实域误报（WEB01 早期 5/1/2、WEB03 uniform 4 / coverage 5）、带不确定度的边界不可用（8/8 GT 边界 matched=0，方向兼容规则下模型不产出非确定 transition）。coverage 修覆盖（触达更多 uncertain）但模型在被触达处仍过度断言——**覆盖与校准是两个问题，本基线把两者分开量化**。
- **方法学优化**：预算只依赖媒体时长的通用政策（`clamp(ceil(duration/1000),12,24)`）；臂顺序样本间轮换 + 统一 warm-up（不计入任何 arm）；execution manifest 标签隔离（54 份深扫描）；多查询/多预算包的公平门口径披露（逐样本门 27/27 + pooled verdict 与冻结门结果并列）；dev/holdout 隔离与 Git 边界（媒体链接农场只读符号链接，原始视频不入 Git）。
- **为校准提供锚点**：上述全部失败模式已逐样本存档（score.json / 原始返回 / 报告），Task 20 校准候选（uncertain 拒答校准、遮挡/不可见显式类别、边界 transition 方向兼容产出）以此为对照基线；**不得在修复校准前做任何"策略更优"的对外声明**。

## 3. 优化效果的边界

- 上表所有数字来自真实运行，未写未经验证的数据；
- 效率提升（3534.4s→800.5s、工具 292→157）来自 **Skill 化编排减少了探索性工具调用与重复推理**，
  不是来自更快的模型或更强的硬件；
- 换一次运行数值可能不同（Agent 行为非确定性）；v2 重评分只对已保存的冻结输出，不重新运行 Agent；
- 小样本 + 单次运行的结论强度有限，演示与征文中必须同时给出分母与限制。
