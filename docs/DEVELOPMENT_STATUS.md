# DEVELOPMENT STATUS — SparkSkill Studio

- 更新日期：2026-09-24（任务 27 后）
- 当前阶段：阶段 4 已完成四部分——**本地视觉证据工作台（任务 10）**、**Apple 风格重设计（任务 12）**、**中文证据表达优化（任务 12.1）**、**云端提交级部署（任务 13）**；**Competition Readiness Audit（任务 14）** 与 **文档一致性/复现说明/过度声明修复（任务 15）** 已完成；**目标时序证据与粗到细自适应采样（任务 16）**、**Evidence Pack 数据契约与时间 Ground Truth 评分器（任务 17）**、**Coverage-Aware Adaptive Sampling v2 与预注册三臂评测（任务 18）**、**dev Evidence Pack 三策略真实基线评测（任务 19B）**、**视觉证据判断校准配对实验（任务 20）**、**Task 20 勘误与固定采样时序重放（任务 21）**、**单调用分项视觉证据核验配对实验（任务 22）** 均已完成；**StepFun 视觉小样本质量闸门（任务 23）**、**真人复核面板（任务 24 / 24A / 24B）**、**中心帧+邻帧上下文视觉质量闸门（任务 25）**、**盲化标签复核（任务 26A / 26B）**、**视频上下文补充复核（任务 26C，用户中止）** 均已收尾；**赛事交付候选包与诚实演示方案（任务 27）** 已完成，产出集中于 `docs/submission/（整目录为赛事交付候选包，内部留档）`。
- 当前 HEAD：任务 27 提交后以此文件顶部为准（任务 26C 收尾提交为 `4430263`）。
- **公开发布状态：`RELEASE_BLOCKED`**（公开仓库 URL / B 站 URL / 十日谈 URL / 团队合影 / 组委会表单确认全部缺失，且存在未决的再分发许可与本机绝对路径暴露问题）。技术候选包状态：`PACKAGE_READY_FOR_USER_REVIEW`。详见 `docs/submission/README.md（内部留档）` 与 `docs/submission/RELEASE-RISK-AUDIT.md（内部留档）`。**任何情况下不得写 `SUBMISSION_COMPLETE`。**
- 关联：`PROJECT_CONTEXT.md`、`README.md`、`docs/plans/2026-09-21-sparkskill-studio-design.md`、`docs/plans/2026-09-22-apple-evidence-workbench-redesign.md`、`docs/plans/2026-09-22-temporal-evidence-adaptive-sampling-design.md`、`docs/plans/2026-09-22-evidence-pack-ground-truth-scoring-design.md`、`BENCHMARK.md`、`docs/COMPETITION_READINESS_AUDIT.md`（内部留档，不随公开仓库分发）、`docs/REPRODUCTION.md`、`docs/OPTIMIZATION_NOTES.md`、`artifacts/task-06/（内部留档）`、`artifacts/task-07/`、`artifacts/task-08/`、`artifacts/task-09/`、`artifacts/task-10/（内部留档）`、`artifacts/task-12/`、`artifacts/task-12-1/`、`artifacts/task-16/`、`artifacts/task-17/`、`app/`、`.interface-design/system.md`

## 1. 已完成

- 阶段 0：仓库初始化、三个 Skill 骨架（frontmatter 对齐 DSH 发现要求）、上下文/设计/README/状态文档、初始提交。
- 阶段 0.5（任务 02）：DSH Harness、Skill 发现机制、StepFun 文本链路冒烟验证（报告见 `docs/SMOKE_TEST_REPORT.md`）。
- 阶段 1（任务 03）：
  - `schemas/visual-task-spec.schema.json` + 校验器（纯标准库，含安全扫描）；
  - 三个 Skill 的 SKILL.md / references / skill-card.md / evals.json / BENCHMARK.md 全部落地；
  - `scripts/validate_task_spec.py`、`scripts/analyze_image.py`、`scripts/generate_report.py` 三个纯标准库脚本；
  - **第一条端到端链路真实跑通**：自然语言 → DSH+StepFun → VisualTaskSpec → 本地 Qwen Vision → 证据 → 报告，端到端 72.5s；
  - 产物存于 `artifacts/task-03/（任务 03 原始运行产物为内部留档）`（含模型原始输出，审计用）。
- 阶段 2（任务 04）：
  - `scripts/extract_frames.py`：视频元数据读取 + 可配置采样抽帧（间隔/最大帧数/起止时间）+ 稳定命名 + 帧索引 JSON；顺序解码保证时间戳严格单调递增；
  - `scripts/trace_video.py`：读取 VisualTaskSpec → 抽帧 → **逐帧复用 analyze_image.py 既有逻辑（未重写提示词体系）** → 聚合（排序/去重/状态变化/首末确认/四态区分）→ timeline.json；
  - `scripts/skill_env.py`：cv2 解释器自动切换（复用本机 vLLM 环境已有 OpenCV 5.0.0，未安装依赖）；
  - evidence-report-generator 新增视频模式：video-report（source_video/duration_ms/sampled_frames/target_query/timeline/summary/status/conclusion），状态独立复算 + 与 timeline.summary 交叉校验；
  - `references/video-evidence.md`：帧索引/时间线/聚合规则/资源守卫/报告契约；
  - `scripts/test_video_pipeline.py`：16 项测试全部通过（真实抽取 5 + 聚合规则 7 + 错误处理 4）；
  - 资源守卫：MemAvailable < 40 GiB 时不加载 Qwen，如实降级 failed；
  - 产物存于 `artifacts/task-04/（内部留档）`。
- 阶段 2.5（任务 05 重跑，2026-09-21）——**DSH Agent 自主视频演示真实跑通**：
  - 用户于 ≈06:18 手动关停 MiniMax-H3；核验 MemAvailable = 115.55 GiB（≥ 40 GiB）；Qwen 预热加载后 79.80 GiB；
  - 两次全新 `dsh --profile headless` 会话（正向 + 负向），由**会话内 Agent 自主**发现/加载 Skill、生成并校验 VisualTaskSpec、调用抽帧/视觉证据/报告工具、得出结论；
  - **真实 Qwen 视频逐帧调用首次验证**：正向（目标=太阳）confirmed=5/failed=1/overall=completed；负向（目标=紫色大象）not_found=6/confirmed=0/overall=completed（负面结论）；
  - 1 帧 Qwen 返回像素坐标框被契约校验拒绝并如实标 failed（未伪造/未修补）；负向所有 bounding_box=null（无伪造）；
  - 产物存于 `artifacts/task-05/（内部留档）`（含两会话 stderr reasoning 流、raw-frames 原始返回、verification.json）；
  - 三个 Skill 的 BENCHMARK.md 增补真实 Agent 运行结果；项目文档如实更新。
- 阶段 3 第一部分（任务 06，2026-09-21）——**多段视频统一证据时间线（DSH Agent 自主驱动）**：
  - **多媒体 VisualTaskSpec**：`schemas/visual-task-spec.schema.json` 的 `source_media` 扩展为 `oneOf[字符串（旧版兼容）, 来源对象数组]`（source_id 唯一、path 安全校验、time_offset_ms 非负）；`required_outputs` 枚举扩充 per_source_timeline/global_timeline/keyframes/evidence_report；
  - **校验器扩展**（`validate_task_spec.py`）：Schema 子集新增 oneOf；新增 source_id 唯一性、time_offset_ms 非负、媒体路径安全校验（拒绝 shell 元字符/凭据样式/系统敏感目录/路径穿越/未授权根目录；授权根 = 项目根 + 本机既有测试媒体目录，可用 `SPARKSKILL_AUTHORIZED_MEDIA_ROOTS` 受控扩展）；
  - **多视频执行器**（`scripts/trace_multi_video.py`）：依次复用 `trace_video.py` 单段能力（未重写视觉提示词/视频处理逻辑）→ 每来源独立时间线（保留 source_id 与原视频时间戳）→ global = 原时间 + time_offset_ms → 统一全局时间线（按 (global_timestamp_ms, source_id) 排序，允许跨来源并列）→ 每来源与全局首末确认/确认帧数；failed/abstained/not_found 全部保留；`semantic_limitations` 随产物输出；
  - **像素坐标受控归一化**（`analyze_image.py`）：纯标准库读取 PNG/JPEG 真实帧尺寸；仅当四元数值、全部 >1（混合拒绝）、x1<x2/y1<y2、不越界、尺寸可读时才归一化，并记录 raw/format/applied/帧尺寸；否则置 null + warning，不重跑模型；
  - **多视频报告**（`generate_report.py --mode multi-video`）：每来源独立状态 + 全局摘要 + 跨视频语义限制声明；状态独立复算并与 global_summary 交叉校验；结论只用允许措辞；
  - **测试视频选择**：开放式视觉探针（真实 Qwen 调用）确认两段真实视频（h3-smoke.mp4 / h3-t2va-8s.mp4）均含共同非敏感目标"太阳"，**使用两段真实视频**，无需 technical fixture；
  - **DSH 自主演示（两次全新 headless 会话）**：正向（太阳）8/8 confirmed（每来源 4/4，置信度 0.95–0.98，3 帧真实触发像素归一化）；负向（紫色大象）8/8 not_found（确定性负面，bbox 全 null）；会话内 Agent 还自行发现并修复 2 个 Skill 代码真实缺陷（校验器路径 off-by-one、多视频交叉校验误报）；
  - **测试**：多视频规则测试 32/32 通过；任务 04 回归 16/16 通过；任务书 17 项验证（实现为 18 项检查）18/18 通过；
  - 产物存于 `artifacts/task-06/（内部留档）`（含两会话 reasoning 流、raw-frames 原始返回、verification.json、run-summary.md、agent-session-summary.md）。
- 阶段 3 第二部分（任务 07，2026-09-21）——**Tier-3 baseline vs with-skill 对照评测（Verdict: PARTIAL）**：
  - 评测集 `evals/tier3/evals.json` v1.0.0：9 个任务（E1 单视频正向 / E2 单视频负向 / E3 多视频正向 / E4 多视频负向 / E5 证据不足 / E6 非视觉 / E7 敏感属性 / E8 非法媒体路径 / E9 缺失媒体），视觉任务统一 max_frames=2；负向/边界用例（7 个）全部保留；
  - 运行器 `scripts/run_tier3_eval.py`：baseline 在项目外隔离目录（无 .git 祖先、不加载项目 Skill）运行；两侧任务文本逐字节相同、相同 max_frames/超时/模型/媒体；按任务交替执行；统一预热一次；日志落盘前脱敏 + 泄露检测；
  - 评分器 `scripts/score_tier3_eval.py`：确定性规则评分（读取结构化产物与会话转录；不用第二个大模型当裁判；不让被测 Agent 自评）；四维（security/correctness/discoverability/effectiveness）通过数/总数 + Efficiency 数量指标；
  - **结果**：Security 8/9→8/9；Correctness 8/9→8/9；**Discoverability 4/9→8/9**；**Effectiveness 6/9→9/9**；总耗时 3211.9s→1970.4s（−38.7%）；工具调用 177→220；Qwen 调用 4（可观测下限）→30；重试 0/0；失败 0/0；
  - 关键发现：baseline 在 5 个视觉任务中均未发现本地 Qwen Vision（0/5，E1 因此给出错误负面结论）；with-skill 5/5 发现并正确使用；E7 baseline 自建脚本向模型询问 apparent gender/age（身份推断调用，安全失败）；E8 双侧零凭据泄露；
  - **失败未隐藏**：with-skill 在 E9（缺失媒体）未返回缺参错误，而从项目文档推断视频路径并完成真实分析——安全/正确性/可发现性各失 1 项，故 Verdict 为 PARTIAL 而非 PASS；改进项已记入 BENCHMARK.md 已知限制；
  - 产物：`artifacts/task-07/`（18 个任务目录 + comparison.json/md + eval-manifest.json + verification.json + run-summary.md）与根目录 `BENCHMARK.md`；回归测试 12/12 通过（任务 03/04/06 套件 + Spec + 归一化 + 路径安全 + 报告复算 + git diff --check + 敏感扫描 + 评测完整性）。

## 2. 当前架构事实（必须如实维护）

- StepFun（step-5-preview）：负责**文本任务解析与 Agent 规划**；当前 DSH 配置下其**图片输入不可用**（不直接读取图片/视频）。
- 视觉后端：**DGX Spark 本地 Ollama Qwen3.8-27B（vision）**，经 `scripts/analyze_image.py` 调用；按需加载/卸载（任务 03 实测 34.6 GB；任务 05 预热实测 ~35.75 GB）。
- 当前实现范围：**图片最小闭环 + 单段短视频最小闭环 + 多段视频统一证据时间线（任务 06）**。
- **真实 Qwen 视频逐帧分析：已完成（任务 05）**。在用户关停 MiniMax-H3 后的资源窗口（MemAvailable 115.55 GiB）内，由 DSH 自主 Agent 会话真实跑通：正向 confirmed=5/failed=1、负向 not_found=6。产物 `artifacts/task-05/（内部留档）`。
- **DSH 会话内 Agent 自主加载 Skill 并驱动完整流水线：已完成（任务 05，多视频扩展验证于任务 06）**。任务 06 两次 headless 会话中，Agent 自行发现/加载三 Skill、生成并校验多媒体 VisualTaskSpec（source_media 来源数组）、调用 `trace_multi_video.py` 与多视频报告生成器并得出结论；会话内还自行修复 2 个 Skill 代码缺陷。证据见 `artifacts/task-06/（内部留档）agent-session-summary.md` 与两会话 stderr reasoning 流。
- **多段视频统一时间线：已实现（任务 06）**。每来源独立时间线 + 按 time_offset_ms 计算全局排序时间的统一全局时间线；**全局时间线是证据聚合，不是跨摄像头身份追踪**：同一目标查询在多段视频中分别得到视觉匹配（matched target query / visually consistent with target description / confirmed in source A / confirmed in source B），不得断言同一个物理实例或跨视频移动；`semantic_limitations` 随产物与报告输出。
- **像素坐标受控归一化：已实现（任务 06）**。真实运行中 3/8 帧 Qwen 返回像素坐标被确定性归一化（记录原始值与帧尺寸）；混合/越界/顺序错误/尺寸未知不归一化（bbox 置 null + warning，不重跑模型）。
- 跨摄像头身份或实例关联：**未实现且明确不做**（需要可靠关联证据）。
- 不做人脸识别、身份/年龄/关系/意图推断。
- OpenCV（5.0.0，本机 vLLM 环境）：仅作底层抽帧工具，不是核心。
- NVIDIA 官方 Skills、TAO、VSS、DeepStream、NIM：**仍未接入**（未发现）。
- MiniMax-H3（:8000）：**当前由用户授权停止，尚未恢复**。任务 06 期间用户曾于 07:49:39 自行重启加载（≈07:57 中止，H3 恢复停止），执行 Agent未停止/未干预该用户服务；h3-studio WebUI（:7860）按需模式运行，任务期间未自动拉起 H3。本项目不得停止/重启它。

## 3. 已验证能力

- DSH Skill 发现/加载/热重载；headless 单任务执行。
- StepFun 文本链路生成受控 VisualTaskSpec（正向 2/2，非视觉拒绝 1/1）。
- VisualTaskSpec Schema 校验与安全扫描（8/8）。
- 本地 Qwen Vision 图片证据抽取（正向/负向各 1/1，真实模型输出）。
- 报告生成器反幻觉规则（图片 7/7）。
- 视频读取、元数据、抽帧、时间戳单调递增、帧路径可追溯（真实视频，5/5）。
- 视频聚合规则：目标存在/不存在/证据不足/bbox 不伪造/去重与状态变化/报告状态一致性/资源守卫/错误处理（16/16，其中聚合样例使用任务 03 真实证据回放）。
- 视频报告状态一致性与交叉校验（一致运行匹配；注入不一致被复算纠正）。
- **真实 Qwen 视频逐帧视觉调用（任务 05）**：正向 confirmed=5/failed=1、负向 not_found=6，真实模型输出存档于 `raw-frames/` 与 `negative-raw-frames/`。
- **DSH 会话内 Agent 自主发现/加载 Skill 并驱动完整流水线（任务 05）**：两次 headless 会话，Skill 发现/选择/加载、VisualTaskSpec 生成与校验、抽帧/视觉证据/报告工具调用均由会话内 Agent 自主完成（证据见 `artifacts/task-05/（内部留档）agent-session-summary.md`）。
- **多媒体 VisualTaskSpec（任务 06）**：source_media 来源数组生成/校验/拒绝规则 7/7；旧版单媒体规格向后兼容（任务 03 真实规格仍 VALID）。
- **多视频聚合与全局时间线（任务 06）**：global=local+time_offset_ms、排序正确、每来源时间戳递增、failed/not_found 保留、全局摘要正确（规则测试 32/32）。
- **像素坐标受控归一化（任务 06）**：合法像素坐标归一化 1/1；混合/越界/顺序错误/尺寸未知/负坐标/非法框置 null 共 6/6；真实运行 3 帧触发且数学校验全部正确。
- **多视频报告与跨视频语义边界（任务 06）**：正向 completed + 允许措辞齐全 + 禁用措辞 0 命中；负向 completed 负面结论；abstained/failed 规则正确；状态独立复算与交叉校验一致。
- **多视频 DSH 自主运行（任务 06）**：两次全新 headless 会话，正向 8/8 confirmed（每来源 4/4）、负向 8/8 not_found；真实 Qwen 调用 18 次（10 正向含 2 探针 + 8 负向），原始返回全部存档。
- **Tier-3 对照评测（任务 07）**：18 个真实会话（9 任务 × 2 侧）；确定性评分器对结构化产物与会话转录判定；baseline 隔离有效性经污染检测确认；评测完整性（prompt 双侧一致、负向用例保留、评分确定性复跑一致）经 R10 校验。

## 4. 未验证/未实现

- 跨摄像头身份或实例关联（明确不做；需要可靠关联证据）。
- evals 的规模化样本（当前为小样本真实运行，未写百分比）。
- baseline（无 Skill）对比评测——**已完成两轮（任务 07 初始、任务 08 修复后重跑）并经任务 09 用 v2 评分器全量重评分（Verdict PASS，9 任务小样本，见 BENCHMARK.md）**；规模化样本与统计显著性未做。
- StepFun 侧是否存在支持图片的模型——未验证（需用户更新 provider 配置后才能验证）。
- with-skill 对"用户未提供媒体"的缺参拒绝（E9 失败暴露的缺口）——**已于任务 08 修复**（`check_source_media.py` 四态契约 + compiler SKILL.md 第 0 步硬门 + 停止清单；M1–M8 契约测试 10/10、E9 稳定性 3/3）。当前未验证项仅为：StepFun 侧是否存在支持图片的模型、评测集规模化与统计显著性、跨摄像头身份/实例关联（明确不做）。

## 5. 当前阻塞项

- **统一内存资源（任务 05 首次尝试，2026-09-21 05:39–05:42 UTC，历史记录）**：任务 05 首次因 MemAvailable = 2.48 GiB 阻塞，生成资源阻塞报告（`artifacts/task-05/（内部留档）resource-blocker-report.md`）并以 `docs: record autonomous video demo blocker` 提交。**该阻塞已由用户关停 MiniMax-H3 解除，任务 05 已于 06:37–06:55 重跑成功**（见 §1 阶段 2.5）。
- **MiniMax-H3 重启与环境波动（任务 06 期间，2026-09-21 07:49–07:57 UTC，如实记录）**：任务 06 执行期间用户自行重启 MiniMax-H3 加载（≈07:49:39 开始，≈07:57 中止，H3 恢复停止），期间 MemAvailable 一度降至 ≈7 GiB、swap 占满；执行 Agent 未停止/未干预该用户服务，待其中止后资源窗口恢复（≈76 GiB）继续任务，两次 DSH 自主会话均未被资源守卫阻塞。**教训：真实演示对"H3 保持停止"这一外部前提敏感，未来长任务应在会话前复核并在 run-summary 中记录环境变化。**
- **多模态路由选择**：当前视觉 100% 走后端本地 Qwen；若未来 StepFun 侧启用图片输入能力（需用户先在 provider 配置中声明 `input: [ text, image ]` 并确认可用图片模型 id），才可能把图片/帧理解切换回 StepFun——**当前配置下不得做此声称**。
- **赛事四份资料不在项目目录**：设计文档按任务书路线编写，资料到位后需回读核对。
- **GitHub 推送阻塞（遗留）**：本机到 github.com 网络不可达；无 Git 全局身份、无 credential helper、无 SSH 公钥。

## 6. 下一阶段任务

- **修复 E9 暴露的缺口**：**已于任务 08 完成**（`task-to-skill-compiler` 负向触发显式覆盖"用户未提供媒体路径 → 必须返回结构化缺参错误"，禁止从项目上下文推断默认文件；`check_source_media.py` 四态契约 + SKILL.md 第 0 步硬门 + 停止清单；M1–M8 契约测试 10/10、E9 稳定性 3/3）。留痕保留。
- **补齐赛事提交材料（最高优先，需用户人工，不可由 Agent 替代）**：公开仓库 URL、B 站演示视频、黑客松十日谈文章、团队合影、组委会表单提交与回执。当前状态矩阵与占位符见 `docs/submission/SUBMISSION-MATRIX.md（内部留档）`；发布阻塞与排除清单见 `docs/submission/WINDOWS-RELEASE-HANDOFF.md（内部留档）`。
- **演示包定稿**：分镜与素材许可门见 `docs/submission/DEMO-RUNBOOK.md（内部留档）`（本任务只交付 runbook，未录屏）。
- Tier-3 评测集扩充与多轮重复（当前 9 任务单次运行，小样本；明确不做统计显著性声明）。
- 跨摄像头身份或实例关联：**明确非目标**（除非未来存在可靠关联证据，且需单独安全评审）。
- （已完成，留痕）多段视频统一证据时间线：任务 06；
- （已完成，留痕）Tier-3 baseline vs with-skill 对照评测：任务 07（Verdict PARTIAL，失败项未隐藏）。

## 7. 不能擅自做的环境操作

以下操作未经用户明确指示一律禁止：

- 安装依赖、下载模型；
- 修改 DSH 全局配置（`~/.dsh/settings.yaml`、`~/.dsh/.credentials.yaml`）、修改环境变量；
- 启动新模型或新服务；停止/重启 MiniMax-H3、Ollama、DSH；
- 读取或输出任何密钥、token、密码；
- 把未发现的 NVIDIA 组件写成已接入；
- 修改 GitHub remote 或执行 push（当前网络不可达）。

## 8. 阶段 3 第三部分（任务 09，2026-09-21）——评测器 v2 与全量重评分（Verdict: PASS）

- **背景**：任务 08 完整重跑后，冻结的 v1 评分器（SHA-256 c35b4506…）被发现存在确定性 stdout 断言语境误报（baseline E3 合规否定、with-skill E4 政策声明被判 Security 失败）；按用户决策（方案 B）采取版本化修复。
- **v2 评分器**（`scripts/score_tier3_eval_v2.py`，SHA-256 949772c9…）：导入继承 v1 全部 22 条规则，仅覆盖 S1/S5 断言扫描；唯一逻辑变化为"stdout 与 JSON 结论纳入与文件一致的从句级否定/声明语境判定"+"补全否定标记清单（'没有'等）"。任务集、PASS 条件未动。
- **回归测试**（`scripts/test_score_tier3_eval_v2.py`）：17/17（N1–N5 合规不判违规、P1–P5 真实断言含混合语境判违规、C1–C2、语境判定精度、继承性）。
- **Known Findings**：baseline E3 与 with-skill E4 误报均修复（v1 FAIL→v2 PASS），触发文本/语境分类/差异原因/人工核验留档。
- **全量重评分**：v2 对任务 08 冻结数据 18/18 重评分（未重跑任何模型会话）；差异仅 2 项且均为允许的已知误报修复，0 意外变化。
- **最终五维（v2）**：Security 9/9→9/9、Correctness 7/9→9/9、Discoverability 5/9→9/9、Effectiveness 6/9→9/9；Efficiency：3534.4s→800.5s、工具 292→157、Qwen 1→17（baseline 为可观测下限）；**Verdict: PASS**（六项 PASS 条件逐条满足，由 v2 实测计算）。
- **验证**：`verify_task09.py` 15/15（冻结哈希×2、任务 07/08 零改动、N/P/C、known-findings、18/18、无意外变化、verdict 复算、BENCHMARK 历史链、git diff --check、敏感扫描、无临时进程）。
- **历史保留**：任务 07 初始 PARTIAL、任务 08 修复与 v1 冻结结果、v1 误报发现与停止过程，全部保留于 `BENCHMARK.md` 历史链与 `artifacts/task-07|08|09/`。


## 9. 阶段 4 第一部分（任务 10，2026-09-21）——本地视觉证据工作台

- **定位**：完全离线、CPU-only、由真实项目 artifacts 驱动的本地"视觉证据工作台"（`app/`），让评委 90 秒内沿证据链审计每一步；**不重新运行模型**。
- **结构**：三栏工作区（任务与 Skill 契约 / Evidence Rail + 证据 / Provenance Inspector）+ 底部（Skill Governance / Tier-3 Benchmark 历史 tab）。Evidence Rail 九节点按真实执行顺序：User Task → StepFun Plan → DSH Skill Match → VisualTaskSpec → Video Frames → Qwen Evidence → Global Timeline → Final Decision → Tier-3 Verification。
- **运行记录（7 个可切换）**：任务 05 单视频自主 Agent（正/负向）、任务 06 多视频正向、任务 06 多视频负向、Tier-3 初次 PARTIAL、E9 修复、评测器 v1 误报发现、Tier-3 最终 PASS（v2）。
- **Truth Status 五级**：Verified / Recorded / Structural / Blocked / Synthetic Fixture；来自 Manifest，不写死成功状态。
- **数据**：`scripts/build_demo_manifest.py` 从真实 artifacts 生成 `app/data/demo-manifest.json`（171KB；构建期凭据自检；缺失字段安全降级；相对 artifact 路径）。
- **只读服务**：`scripts/serve_demo.py`（127.0.0.1:8787；GET/HEAD only；无目录遍历；媒体 allowlist + Range 支持；凭据/配置/.git/模型权重 403）。
- **测试**：`scripts/test_demo_app.py` **21/21 通过**（Manifest 生成/合法/无凭据/无敏感绝对路径、HTML 结构、CSS 无外部资源、CSS 颜色全 token、JS 语法、无 CDN、服务启动、三类 HTTP 200、遍历拒绝、媒体 allowlist、PARTIAL/PASS 历史、E9 缺陷与修复、真实性标签一致、预览进程关闭）。
- **设计系统**：`.interface-design/system.md`（任务 10 时为石墨黑/炭灰暗色 + 信号绿唯一强调色；**任务 12 已重设计为 Apple 风格亮色界面**，当前令牌以 `app/styles.css` 的 `:root` 为唯一权威，system.md 已于任务 15 同步更新）。
- **限制**：任务 10 时点未执行浏览器截图检查（不安装浏览器/Playwright）；**任务 12/12.1 已用真实 Chrome headless 完成四档视口截图与 40/40、43/43 浏览器 QA**（截图见 `artifacts/task-12/screenshots/`、`artifacts/task-12-1/screenshots/`）；界面为静态展示，不是实时模型调用。

## 10. 阶段 4 第零部分（任务 11，2026-09-22）——原界面视觉验收 FAIL（历史，保留）

- **结论：FAIL。** 任务 10 的三栏等权工作台在投影场景下不成立，未通过视觉验收。
- **P0-1（阻断）**：`[hidden]` 浮层被组件 display 规则覆盖，loading / JSON modal / Provenance 抽屉永久遮挡首屏，页面不可点击。
- **P1-1**：三栏等权长页，1920×1080 下首屏看不到主线（三列各约 2585px 的"假工作台"），评委 90 秒内无法建立叙事。
- **P1-2**：长路径与调试字段常驻首屏且被裁切。
- **处置**：任务 12 重设计（下述）；FAIL 记录与问题清单保留，未删除。
- **证据**：任务 11 无独立 artifact 目录；问题清单与回归结论记录于 `artifacts/task-12/VISUAL_QA_REPORT.md` 的"任务 11 问题回归"节。

## 11. 阶段 4 第二部分（任务 12，2026-09-22）——Apple 风格 Evidence Workbench 重设计

- **定位**：亮色、克制、可投影的专业证据工作台；苹果白画布 `#F5F5F7`、纯白表面、石墨文字 `#1D1D1F`、Apple Blue 交互色 `#0071E3`；绿色仅用于已验证状态；状态语义不靠颜色单独表达。
- **信息架构**：最小顶栏 → Hero 结果摘要（真实关键帧为画面主体 + 主体/结果行/摘要 + `READ-ONLY · RECORDED ARTIFACTS` 标注）→ 横向九阶段证据链路（User Task → StepFun Plan → DSH Skill Match → VisualTaskSpec → Video Frames → Qwen Evidence → Global Timeline → Final Decision → Tier-3 Verification）→ 阶段证据画布 → 验证终章（四维 9/9 + 3534.4s→800.5s + 四段历史链）。
- **交互**：运行选择器、正/负向模式、帧与时间线点击联动 Provenance 右侧抽屉、原始 JSON 按需弹窗、Esc 关闭并焦点回归、Ribbon 键盘可达（Tab/Enter/Space）。
- **数据纪律**：仍只读 `app/data/demo-manifest.json` 与真实 artifact 图片；未手写任何 Manifest 字段；7 条运行记录、五级 Truth Status、跨视频语义限制声明、Benchmark 失败历史全部保留。
- **测试**：静态 **22/22**（`artifacts/task-12/static-test-results.json`）、真实 Chrome headless 浏览器 QA **40/40**（`artifacts/task-12/browser-qa.json`，console 错误 0、网络错误 0）、四档视口（1920×1080 / 1440×900 / 1280×800 / 1024×768）截图 10 张；`node --check app/app.js` 通过。
- **提交**：`1d30221`（设计计划）、`a2fe686`（实现）。
- **P0/P1 回归**：任务 11 的 P0-1 与 P1-1/P1-2 均已消除并有浏览器实测证据。

## 12. 阶段 4 第三部分（任务 12.1，2026-09-22）——中文证据表达优化

- **目标**：导航与说明文案中文化，产品与模型专有名词（StepFun、DSH、Qwen、Tier-3、VisualTaskSpec、SparkSkill Studio）保留英文。
- **Hero 派生规则**（不写死成功状态）：主体取自 `target.description` 括号外部分；状态由帧级结构化字段派生——有 `object_found=true` 有效帧 → `已被确认出现`；已分析但全部 `not_found` → `在已抽样证据中未被确认`；存在拒答 → `证据不足，保持拒答`；仅失败 → `分析未能完成`；资源阻塞 → `受资源条件阻塞`。时间/帧数/来源数取自 `summary` / `global_summary` 与帧状态复算。
- **调试字段隔离**：Hero 正文不再直接显示绝对路径、`frame_path`、英文 timeline 字段、Schema 字段名与原始 artifact ID；这些信息仍可经 Provenance 与 JSON 按需查看。
- **Benchmark 记录中文化**：PASS → `确定性验证通过`；PARTIAL → `阶段性验证尚未全部通过`；FAIL → `确定性验证未通过`（不把 PARTIAL 改写为成功）。
- **测试**：静态 **26/26**（`artifacts/task-12-1/static-test-results.json`）、浏览器 QA **43/43**（`artifacts/task-12-1/browser-qa.json`）、4 张视口/负向/中文 Ribbon 截图。
- **提交**：`433d169`（文案计划）、`2a950d9`（实现）。

## 13. 阶段 4 第四部分（任务 13，2026-09-22）——云端提交级部署

- **内容**：将任务 12/12.1 的界面部署到 DGX Spark 云服务器，作为提交级状态。
- **回归记录**：部署 Agent 回报云端静态测试 26/26、云端浏览器回归 **47/47**。
- **证据边界（必须随数字声明）**：**仓库内可独立复算的记录是任务 12.1 的静态 26/26 与浏览器 43/43**（`artifacts/task-12-1/`）；任务 13 的 47/47 来自部署 Agent 的回报，**当前仓库没有对应的完整截图或 verification artifact，`artifacts/task-13/（内部留档；Task 13 云端回归 47/47 为部署 Agent 回报）` 不存在**。对外引用 47/47 时必须注明"任务 13 部署回报记录"，不得伪装成仓库内已有可独立复算的 artifact。
- **恢复点**：tag `pre-task13-deploy-4c4c3ca`（指向 `4c4c3ca`）为部署前恢复点，保留未动。

## 14. 阶段 5 第一部分（任务 14，2026-09-22）——Competition Readiness Audit

- **性质**：只读事实核验 + 评分证据整理 + 冲刺优先级判断；未开发功能、未修改现有代码、未调用模型、未联网。
- **产出**：`docs/COMPETITION_READINESS_AUDIT.md`（内部留档，不随公开仓库分发）（16 节：Executive Summary、审计依据与资料限制、成熟度、六维评分表、Agent Skills 合规表、技术栈真实性表、完整性表、提交物清单、演示风险、过度声明检查、Top 3 冲刺任务、明确不做、下一项唯一推荐、证据索引、环境快照、已知限制）。
- **关键结论**：保守 **63/100**、乐观 **81/100**；技术上具备前十竞争力，但提交材料（仓库 URL、B 站视频、十日谈文章、合影、报名信息）全部缺失可能构成资格硬门槛；定位到 6 处仓库内文档不一致 + 1 处报告口径差异。
- **原始四份赛事资料**：云服务器不存在，审计基于任务书已确认要求 + 仓库证据，未联网检索。
- **提交**：`5d7dda8`。

## 15. 阶段 5 第二部分（任务 15，2026-09-22）——文档一致性、复现说明与过度声明修复

- **修复的七类已知问题**（任务 14 定位）：
  1. **StepFun 视觉职责错误**：设计文档 §12"抽帧→StepFun 识别""StepFun 视觉"已改为"OpenCV 抽帧 → 本地 Qwen Vision 逐帧识别"；§11 baseline 定义修正为与 Tier-3 实现一致；两项均在 §17 增补偏差记录。
  2. **设计系统过时**：`.interface-design/system.md` 从任务 10 暗色令牌更新为任务 12 亮色令牌，并标注历史设计已被替代。
  3. **Skill 测试数字矛盾**：`visual-evidence-extractor/SKILL.md` 的"31/31"统一为已提交产物记录的 **32/32**（`artifacts/task-06/（内部留档）test-results.json`）；未改任何测试产物。
  4. **Skill Card 能力滞后**：两个 skill-card 补齐任务 06 已验证的多视频能力（单图片/单视频/多来源聚合/来源独立时间戳与全局偏移/正负拒答失败四态/不做跨摄像头身份匹配）。
  5. **baseline 定义不一致**：以冻结评测数据为准重写（隔离方式、同文本/模型/媒体/帧上限/超时、每任务独立会话、双侧交替、Qwen 计数观测限制、v2 对冻结数据重评分而非重跑会话）。
  6. **DEVELOPMENT_STATUS 历史缺失**：补齐任务 11（FAIL 与 P0/P1）、12、12.1、13（47/47 注明为部署回报）、14；更新日期与 HEAD。
  7. **陌生环境复现与开源完整性**：新增 `docs/REPRODUCTION.md`（复现/部署/排查）与 `docs/OPTIMIZATION_NOTES.md`（已做与未做的优化），README 增加导航与许可声明；新增 Apache-2.0 `LICENSE`。
- **未做（红线）**：未修改业务脚本/Schema/前端代码/evals/评分器/冻结 artifacts；未重跑 Tier-3；未调用模型；未启动 DSH headless；未启停任何服务；未安装依赖；未改全局配置；未读取凭据；未添加任何虚构 URL；未删除或淡化 PARTIAL/E9/v1 误报历史；未推送 GitHub；未改分支与 tag。
- **统一后的真实架构分工**（全仓一致表述）：StepFun `step-5-preview` = 理解用户文本任务、规划、生成结构化任务规格；DSH `0.1.5-rc.2` = 发现、加载和编排项目 Skill；`task-to-skill-compiler` = 把文本视觉任务编译为受约束的 VisualTaskSpec；OpenCV = 底层视频解码与抽帧工具（非核心创新）；本地 Ollama Qwen3.8-27B Vision = 读取图片和视频帧、生成结构化视觉证据；`visual-evidence-extractor` = 约束视觉调用、证据格式、坐标规范与拒答边界；`evidence-report-generator` = 依据证据生成报告并执行反幻觉交叉校验；Evidence Workbench = 只读展示已保存的真实 artifacts，不在浏览器内实时调用模型。

## 16. 下一步方向（任务 15 后）

- **最高优先（需用户人工）**：补齐赛事提交材料——公开仓库 URL、B 站演示视频、黑客松十日谈文章、团队合影、报名/提交信息（本机网络不可达，推送与上传须由用户执行）。
- **次高优先**：按 `docs/COMPETITION_READINESS_AUDIT.md`（内部留档，不随公开仓库分发）§9.2 定稿 3 分钟演示分镜并录屏，准备无资源窗口时的降级方案。
- **明确不做**：跨摄像头身份/实例关联；接入 NVIDIA 官方 Skills/TAO/VSS/DeepStream/NIM；StepFun 图片链路改造；浏览器实时模型调用界面；模型权重级优化（量化/vLLM/投机解码）冒充为本项目优化；评测集规模化与统计显著性声明。
- **环境备注**：MiniMax-H3（:8000）当前由用户授权停止、尚未恢复；本地 Qwen 按需加载；两者不宜同时高负载常驻。

## 17. 阶段 5 第三部分（任务 16，2026-09-22）——目标时序证据与粗到细自适应采样

- **背景**：任务 04/06 后视频能力有两个真实弱点——`object_trace` 实际是固定抽帧后的逐帧存在性判断（没有明确语义的时序事件）；抽帧策略是定长网格（不按状态变化/低置信度/拒答区间细化，无硬性调用预算）。
- **架构选择**：不增加第四个 Skill。三个现有 Skill 向后兼容增强：compiler 增加 `sampling_strategy` 编译与校验；extractor 增加 adaptive coarse-to-fine + provenance + 时序证据（uniform baseline 行为零变化）；report-generator 增加 temporal 报告模式（独立复算 + 交叉校验）。
- **契约**：`schemas/visual-task-spec.schema.json` 新增可选顶层 `sampling_strategy`（`strategy` ∈ {uniform, adaptive_coarse_to_fine}；adaptive 必填 `max_model_calls`/`initial_coverage_samples`/`target_boundary_precision_ms`/`max_refinement_rounds`；可选 `refinement_triggers`/`require_sampling_provenance`/`require_temporal_evidence`）。非法预算、负/零精度、未知策略、uniform 带细化参数、adaptive 缺必填、initial>budget 均明确拒绝；旧规格（无该字段）继续 uniform 行为。
- **实现**：`.dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py`（纯逻辑：规划/预算账本/provenance/时序证据）、`trace_temporal.py`（执行器：uniform 复用 extract_frames.plan_sample_times + trace_video.analyze_frame/aggregate；adaptive 初始覆盖+触发器二分细化；多来源共享预算并复用 trace_multi_video 合并规则）、`references/temporal-evidence.md`；report-generator `--mode temporal|temporal-multi`（独立复算 + 上游交叉校验 + 必显语义红线）。
- **调用预算**：`max_model_calls` 硬限；同时间戳至多一次真实调用；重复时间戳记 skipped_duplicate；预算耗尽即停（不算"分析成功"）；资源守卫阻塞时未执行调用不计为真实视觉调用；构造 fixture 证据不计为 Qwen 调用（evidence_nature 区分）。
- **technical fixture**：`scripts/generate_task16_fixtures.py` 生成 5 段合成视频（present-throughout/appear-midway/disappear-midway/reappear/abstain-zone；640×360@24fps、8s、红色正方形；确定性渲染），第一次评测前冻结 manifest+ground truth+SHA-256（`artifacts/task-16/fixtures/`），评测前 `--verify` 复核；单帧 failed 与预算耗尽另有规则级 fixture（构造结构化证据）。
- **测试**：`scripts/test_temporal_evidence.py` **27/27 通过**（T1–T6 契约、T7–T16 采样与预算、T17 规则一致、T18–T19 报告复算、T20–T21 多来源、T22 资源守卫零调用、T23 provenance 无凭据、T24 fixture 区分；完整结果 `artifacts/task-16/test-results.json`）。回归：任务 04 16/16、任务 06 32/32、M1–M8 10/10、v2 评分器 17/17 全部通过；任务 07–09 冻结数据零变化。
- **uniform vs adaptive 对照**：`scripts/run_task16_comparison.py`，同预算（12）/同视频/同查询/同模型/同资源窗口/同状态规则；结果与 Verdict 见 `artifacts/task-16/comparison.json` 与 `comparison.md`（**不预设 adaptive 必须 PASS；技术 fixture 结果不外推为真实仓储准确率**）。
- **DSH 自主会话**：一次全新 `dsh --profile headless` 会话由会话内 Agent 自主发现/加载 Skill、生成带 adaptive 策略的合法规格、运行时序证据链路并生成报告；会话证据见 `artifacts/task-16/dsh-session/`。
- **文档**：新增 `docs/plans/2026-09-22-temporal-evidence-adaptive-sampling-design.md`；更新 README/PROJECT_CONTEXT/DEVELOPMENT_STATUS/OPTIMIZATION_NOTES 与三个 Skill 的 SKILL.md/skill-card/references/evals/BENCHMARK。
- **未做（红线）**：不修改 Evidence Workbench；不触碰用户 holdout；不做跨摄像头身份/实例关联、ReID、目标跟踪、实时跟踪声称；不停止/重启任何服务；不安装依赖；不联网；未修改 Tier-3 冻结任务集/评分器/PASS 条件。

## 18. 阶段 5 第四部分（任务 17，2026-09-22）——Evidence Pack 数据契约与时间 Ground Truth 评分器

- **背景**：任务 16 留下五个必须正视的问题——`execution status=completed` 只表示流水线完成；abstain-zone 真实 Qwen 输出是确定性负面、与 fixture ground truth（不确定区）冲突；adaptive 初始覆盖可能漏掉窄事件/窄不确定区；旧 `IMPROVEMENT` 更接近效率与已检测边界改进；用户 8 AI + 4 真实视频 Evidence Pack 尚未上传。
- **实现**（项目级工具，不新增第四个 Skill，与 Tier-3 v2 评分器同层）：
  - `schemas/evidence-pack-manifest.schema.json`：Evidence Pack 输入清单契约（sample_id 唯一、split dev/holdout、source_type 三类、媒体相对路径 + SHA-256 + 时长、data_card、target_query、公开演示/公开 Git 许可、按来源类型条件必填的 source_provenance；**manifest 不得内嵌时间真值**；profile=sparkskill-competition-2026 时校验 12 编号与 9/3 split，底层契约不硬编码编号）；
  - `schemas/temporal-ground-truth.schema.json`：时间 Ground Truth 契约（segments confirmed/not_found/uncertain、时间线合法性七条、标签冻结与修订历史【含 after_model_run】、**不得包含模型字段**）；
  - `scripts/validate_evidence_pack.py`：契约校验器（Schema 严格子集复用 + 语义规则 + competition profile + 跨文件一致；结构化错误 code+location）；
  - `scripts/score_temporal_ground_truth.py`：确定性评分器（8 项硬门；七类采样点计数，每项分母=对应类别分母、0 分母写 `not_applicable`；事件覆盖；transition 一对一最大匹配 + 方向兼容【decisive→decisive 不得匹配涉及 uncertain 的边界】；效率指标；双臂公平比较 10 条件 gate + 四类 verdict；holdout GT 只进摘要不进输出；输出无时间戳/绝对路径、落盘前凭据自检）；
  - `scripts/test_temporal_ground_truth_scoring.py`：**38/38 通过**（34 个确定性 fixture 用例覆盖任务书 30 类要求 + 分类规则一致性/确定性/输入只读/输出卫生 4 项）；
  - `artifacts/task-17/`：contracts（任务 16 manifest 与 5 份派生 GT、数据卡、competition profile 占位示例）、fixtures、rescored-task16、test-results.json、comparison.json/md、run-summary.md、verification.json（24/24）、verify_task17.py。
- **Task 16 冻结产物重评分结论**（同预算 12，零新模型调用）：fairness gate 10/10；**pack 级 verdict=TRADEOFF**（评分器计算，未预设）——adaptive 省调用（34 vs 60）且平均边界误差更小（138.333 vs 150.0 ms），但 `unreached_uncertain_segments` 1 > 0（abstain-zone 初始覆盖盲区）；uniform 臂在 uncertain 区间 3/3 `overclaim_on_uncertain`（真实 Qwen 确定性负面 vs GT 不确定）；两臂 decisive→decisive transition 均不能匹配涉及 uncertain 的 GT 边界（各漏 2 个）；10 臂全部 `execution_status=completed` 而语义计数暴露冲突——**completed ≠ 语义正确**。
- **历史口径处理**：任务 16 旧 `IMPROVEMENT` 是旧口径历史结论（`artifacts/task-16/comparison.json` 未篡改）；任务 17 只在新文档与 artifacts 中追加事实，不回写历史。合成 fixture 小样本不外推为真实仓储准确率；8 AI + 4 真实视频上传前不得声称真实域评分已完成。
- **回归（全部通过）**：任务 16 时序 27/27、任务 04 16/16、任务 06 32/32、M1–M8 10/10、v2 评分器 17/17、工作台静态 26/26；`git diff --check` clean；敏感信息扫描 0 命中；任务 07/08/09/16、Tier-3、app/、Task 16 sampler/executor 零改动。
- **未做（红线）**：未调用任何模型；未抽帧/生成视频/下载素材/联网/安装依赖；未启停任何服务；未修改工作台；未触碰用户 holdout；未创建第四个 Skill；未修复 adaptive 初始覆盖盲区（算法问题留给后续独立任务，本任务只量化它）。


## 19. 阶段 5 第五部分（任务 18，2026-09-22）——Coverage-Aware Adaptive Sampling v2 与预注册三臂评测

- **背景**：任务 17 复评量化了 adaptive_coarse_to_fine 的覆盖盲区（abstain-zone `unreached_uncertain_segments=1`：4 个初始采样点全部落在 uncertain 区外，触发器无信号，细化轮数=0）。触发式细化是证据驱动的，对完全未采样的窄事件/窄不确定区在结构上不可见。
- **阶段 A（预注册先于实现，提交 `dcaf324`）**：设计文档（18 个必答问题）；6 段新 deterministic technical fixture（`scripts/generate_task18_fixtures.py`，与任务 16 同一组冻结生成参数；short-event/short-uncertain/twin-short-events/absent/phase-b × 2）；任务 18 契约（11 样本 manifest + 11 份任务 17 格式 GT + 数据卡）；预注册 7 文件（evaluation-plan/arm-configs/verdict-policy/fixture-manifest/ground-truth-manifest/frozen-hashes/README）；自检 8/8。
- **阶段 B（实现）**：`schemas/visual-task-spec.schema.json`（strategy 枚举第三值 + `coverage_gap_target_ms`/`coverage_call_reserve`）；`validate_task_spec.py`（coverage 六必填 + initial+reserve≤budget + 旧策略拒绝 coverage 字段）；`adaptive_sampler.py`（策略解析新分支 + 覆盖几何纯函数：`adjacent_gaps`/`max_adjacent_gap_ms`/`next_coverage_candidate`（largest-gap-first，并列取最早）/`underobserved_intervals` + `build_temporal_evidence` coverage 块）；`trace_temporal.py`（阶段 2 覆盖探索 + provenance 覆盖字段 + decisions purpose/candidate_interval + CLI）；`generate_report.py`（coverage_summary 与覆盖限制句，附加显示）。
- **测试与评测**：新测试 **36/36**（`test_task18_coverage_sampling.py`，C01–C35 + C34b）；三臂 deterministic replay（`run_task18_comparison.py --mode replay`，11 场景 × 3 臂，构造证据，语义内容逐字节可复算）；评分适配层 `task18_scorer_adapter.py`（任务 17 冻结评分器零改动，内存扩展策略白名单；公平门 10/10 × 3 对）；**pack 级 verdict=TRADEOFF**（coverage vs adaptive = IMPROVEMENT；coverage/uniform 与 adaptive/uniform = TRADEOFF）。
- **资源门槛与真实评测（补跑轮已完成）**：首轮与补跑轮初测两轮 8 项核验均因用户 MiniMax-H3 服务族活跃失败 2 项（h3-lite API :8010 resident 监听 + WebUI/tab_test/keeper 进程活跃；用户当天 11:28:57 仍有生成）→ 状态 **PARTIAL_RESOURCE_BLOCKED**，两轮结构化 blocker 保留于 `resource-gate-rerun.json`（未倒写授权历史）。补跑轮经用户明确授权：停服前安全门 8 项通过（队列 3 次为空、无活动连接、输出无增长）后以纯 SIGTERM 优雅停止 7 个经事实核验归属 `~/minimax-h3` 的进程（API、WebUI 树、3 个 tab_test、2 个 coexistence-keeper），无 kill -9、无误停 DSH/Ollama/SSH、未删用户文件，恢复方式已记录，任务结束后 H3 保持停止（`h3-shutdown-record.json`）；停服后十项门槛全部通过。
- **真实 Qwen 三臂评测（已完成）**：`run_task18_comparison.py --mode real`（预注册默认预算/超时，未覆盖）；287 次真实调用（uniform 120 + adaptive 54 + coverage 95，与 replay 计划逐臂一致），零失败/零超时/零无效输出，原始返回全存档（`real-qwen/`）。real pairwise：coverage vs adaptive = **TRADEOFF**（replay 为 IMPROVEMENT——真实 Qwen 触达 uncertain 后过度断言：overclaim coverage 4/uniform 2/adaptive 0，appropriate_abstention 三臂 0，重现任务 16 模式；差异源于视觉模型语义而非采样策略）、coverage vs uniform = TRADEOFF、adaptive vs uniform = TRADEOFF；**real pack = TRADEOFF**（严格改进：平均边界误差 93.519ms 小于两个基线；违反：overclaim、漏检 2 个 confirmed 事件、最大间隔 1333.334ms > uniform 708.334ms）。真实运行证实 coverage 采到短事件后 Qwen 能正确识别（confirmed=2 vs adaptive 0）；600ms twin 事件仍漏检（不保证发现任意短事件）。replay 与 real 分别评分、分别给 verdict、不混合平均。
- **DSH headless 自主会话（成功）**：`dsh --profile headless` 全新会话（13:55:46→14:00:22，exit 0）；Agent 自主发现并加载三个 Skill、source media 硬门 accepted（user_provided）、StepFun 生成 coverage_aware_adaptive 规格校验 VALID、未读 Ground Truth、本地 Qwen Vision 真实调用 11/12、报告器独立复算；发现短事件（GT [3500,4100] 被正确括号，边界 mean 33.333ms）；会话后冻结评分器离线评分 correct_decisive 11/11、事件覆盖 1/1、边界 2/2 容差内、overclaim 0（`dsh-session/`）。
- **回归（全部通过，补跑轮重跑）**：任务 18 新测试 36/36、任务 17 GT 38/38、任务 16 时序 27/27、任务 04 16/16、任务 06 32/32、M1–M8 10/10、v2 评分器 17/17、工作台静态 26/26；verdict 冻结规则复算一致（replay 与 real 各自）；`git diff --check` clean；冻结数据（预注册 41 项哈希、7 份 blob 逐字节、任务 07/08/09/16/17、Tier-3、任务 17 评分器/schema、app/、实现文件）零改动；交付验证 24/24（`artifacts/task-18/verification.json`）。
- **未做（红线）**：未新增第四个 Skill；未修改任务 16/17 冻结 artifacts 与 Tier-3；未接入用户 dev/holdout；未安装依赖；未联网；未改全局配置；未推送。停服仅限用户授权范围内事实核验归属 H3 的进程；真实模型调用总数 **298**（三臂评测 287 + DSH 会话 11），全部本地 Qwen Vision 真实调用；replay 为构造证据，两者不混合。


## 20. 阶段 5 第六部分（任务 19B，2026-09-22/23）——dev Evidence Pack 三策略真实基线评测

- **性质**：对当前冻结系统在用户真实 dev 数据上的**未校准基线**测量。禁止修改视觉 Prompt/采样算法/证据分类/报告规则/scorer/adapter；失败与过度断言是本轮要保存的基线证据。
- **数据**：dev 包位于 Git 仓库之外（`<DEV_EVIDENCE_PACK_ROOT>`，只读）；白名单九样本（AI01–AI06 MiniMax-H3 生成受控测试视频 + WEB01–WEB03 Pexels licensed-public）；摄验 14 项全过（白名单/隔离/双源冻结哈希/lineage/卡媒体哈希/总字节 137,919,113/无凭据无地址）；九张 transfer-safe 卡字节 identical 复制入库，源卡未修改。
- **Ground Truth**：`scripts/build_task19_ground_truth.py` 确定性派生（AI06/WEB02 相邻同状态合并；WEB01/WEB02 末段终点对齐 cv2 实测时长 18551.867/10243.567；状态覆盖与边界集合不变式逐样本校验；原人工原因保留）；九份 GT 过任务 17 冻结契约；规范化报告随预注册提交。
- **预注册（阶段 A 提交 `e3ef01e`，先于任何 dev 模型调用）**：设计文档（16 必答点）+ 预注册 7 文件 + 自检 8/8；预算政策 `clamp(ceil(duration/1000),12,24)`；臂顺序样本间轮换；warm-up 用任务 16 fixture（不计入任何 arm）；DSH 自主验证样本 WEB01 冻结；verdict-policy 三范围（generated/licensed-public/all-dev）。
- **真实评测**：27/27（9 样本 × 3 臂）成功、0 失败、**256 次真实 Qwen 调用**（uniform 121 + adaptive 51 + coverage 84；+warm-up 1）；资源门槛 8 项运行前全过（MemAvailable 115.8+ GiB，H3 停止，无外部 Qwen 消费者）；每臂保存 execution manifest（无标签）、spec、原始返回、provenance、时序证据、报告、缩略图。
- **评分**：任务 17 冻结 scorer + 任务 18 适配层（零改动）；27 份硬门全过；逐样本公平门 27/27；**公平门口径披露**：冻结门 same_target_query/same_call_budget 单值条件使 licensed-public 与 all-dev 范围判 INVALID_COMPARISON（多查询/多预算包），generated 同质范围十条件全过；pooled pairwise verdict 用冻结 compute_verdict 对汇总指标补充计算。
- **算法结论**：三范围 pack verdict 全部 **NO_IMPROVEMENT**。核心发现（模型语义，非采样策略）：AI06 uncertain 区双向过度断言（overclaim 11/7/9，appropriate_abstention 仅 1/3/1）；AI04 遮挡区 [4000,9000] 三臂全部误判 confirmed（0 转换，边界 2/2 漏）；WEB01 真实域早期误报（incorrect 5/1/2）；WEB03 真实负向误报（uniform 4、coverage 5、adaptive 0）；AI05 三臂全部正确（红色干扰物未致误报）；WEB02 无边界样本不计入边界精度分母且三臂全部正确；全部 8 个 GT 边界 matched=0（方向兼容规则下 abstained→confirmed transition 不存在）。
- **DSH 自主会话**：WEB01（阶段 A 冻结）全新 headless 会话成功（exit 0，393.8s）：三 Skill 自主发现/加载、来源硬门 accepted、规格校验 VALID、8 次真实调用、报告器独立复算；离线评分 correct 6/8、incorrect 2/8、边界 0/2（与批量 coverage 臂行为一致）。
- **测试与验证**：新测试 22/22（`scripts/test_task19_dev_pack.py`）；回归 Task 18 36/36、Task 17 38/38、Task 16 27/27、Task 04 16/16、Task 06 32/32、M1–M8 10/10、Tier-3 v2 17/17、工作台 26/26；`git diff --check` 干净；冻结数据零改动；交付验证 21/21（`artifacts/task-19/verification.json`）。
- **未做（红线）**：未修复 dev 失败；未开始校准；未触碰 holdout；未更新工作台；未录屏/文章/推送；未安装依赖/联网/改配置/启停服务；原始视频未入 Git。
- **建议（供总控决策）**：Task 20 校准候选——uncertain 拒答校准（提示词/阈值层，禁用改标签迁就模型）、遮挡/不可见显式类别、边界 transition 的方向兼容产出；详见 `artifacts/task-19/known-limitations.md`。


## 21. 阶段 5 第七部分（任务 20，2026-09-23）——视觉证据判断校准：同期同帧配对实验

- **性质**：dev 校准实验。唯一变量 = 通用视觉判断语义版本（v1 现行模板 → v2 候选，仅改判断纪律段；JSON 契约与证据状态集合不变）。不调采样参数、不换模型、不改标签、不改冻结评分规则。不是 holdout 盲测，不是真实仓储准确率证明。
- **阶段 0（只读归因）**：Task 19B 五类计数独立复算一致（187/22/5/41/1=256；调用 121/51/84；边界 0/8；与冻结 score.json 逐点零 mismatch）；run-summary.md 两处小表格/表述与冻结 score.json 不符（AI02 adaptive/coverage 实为 overclaim 1 而非适当拒答）已披露、未改旧文件；错误归因：① 模型判断 63 点（主因）、② 映射 0、③ 采样未触达 4 段、④ 边界方向兼容 24 missed、⑤ 后端失败 1；关键量化：overclaim 点 confidence 均值 0.922（模型"自信地错"），256 点中仅 5 点使用拒答通道 → 唯一杠杆是拒答通道语义强化。256 点全部一一映射（媒体哈希/来源/时间戳/查询/原始返回）；Task 19B 未冻结帧哈希 → 正式口径"同媒体同时间戳"，盘上实证 184/184 帧逐字节一致。
- **预注册（阶段 A 提交 `31cf893`，02:04:49Z，早于第一笔 dev 调用 02:38:47Z）**：design.md + evaluation-plan.json + prompt-v2.txt（sha256 3d6c616f…）+ paired_scorer.py + point-manifest-256.json + frozen-hashes.json（33 条）+ runner + 测试；预注册门槛 G1–G5 与 verdict 规则冻结；披露式修订 `358766f`（smoke 发现的每点资源门限 /api/ps 自击败问题 → 运行中改为观测、门限用内存+H3；实验参数零变化，仍早于任何 dev 点调用）；执行器 `c0befb2`（阶段 C runner，门控）。
- **正式配对**：256 点 × 2 版 = **512/512 真实 Qwen 调用**（+warm-up 1 + smoke 4 均 fixture 帧；511 ok + 1 契约拒绝（AI06/adaptive t=5500 缺 description → failed_on_uncertain）；0 超时/0 无效 JSON/0 重试；平均 14.1s；2 小时 13 分）；顺序轮换 v1 先/v2 先各 128；批量前 8 项资源门槛全过、运行中无阻塞。
- **配对结果（verdict=TRADEOFF）**：overclaim 40→34（−6，G1 PASS）；incorrect 24→23（G2 PASS，三口径均不增）；correct 186→181（−5 超容忍 4；licensed-public −2 超容忍 1 → **G3 FAIL**）；failed 0→0（G4 PASS）；appropriate_abstention 6→11。七类账各 256：v1 186/24/0/0/6/40/0，v2 181/23/**6**/0/11/34/**1**（v2 五类主表 249 = 口径子集，非数据丢失）。逐点 14 点变化：6 改进（overclaim→拒答：AI04×1、AI06×5）、**5 损伤 + 1 误报修复**（correct→误拒：AI01 t=666 ×3 臂、WEB03 t=17480 adaptive/coverage 两臂；WEB03 t=17480 uniform 臂为 v1 误报→拒答）、1 契约拒绝、1 反向退化（AI06/coverage t=10083）。去重（184 帧）方向一致；**v2 去重五类表须补示 abstention_on_determinate 2 + failed_on_uncertain 1**；同期 v1 vs 历史 249/256 一致（漂移 7 点全在最歧义帧）。人类可读口径勘误：`artifacts/task-21/errata/task20-errata.md`（E1–E7）。
- **阶段 C/DSH 会话**：**未运行**（verdict 非 IMPROVEMENT，预注册停止门）；不迭代第二个候选；v2 未被采纳进 Skill（analyze_image.py 零改动）。
- **测试与验证**：新测试 19/19（`scripts/test_task20_pairing.py`，含与冻结评分器 256 点逐行等价证明）；回归 Task 19 22/22、Task 17 38/38、Task 18 36/36、Task 16 27/27、Task 04 16/16、Task 06 32/32、M1–M8 10/10、Tier-3 v2 17/17、工作台 26/26；`git diff --check` 干净；敏感扫描 0 命中；冻结路径 15 项相对 8a06052 零改动；交付验证 20/20（`artifacts/task-20/（内部留档）verification.json`）。
- **未做（红线）**：未运行阶段 C 动态三臂与 DSH 自主会话（未过门）；未采纳 v2 进 Skill；未开始 holdout；未替换模型；未接入工作台；未录屏/文章/推送；未安装依赖/联网/改配置/启停服务；原始视频与派生帧未入 Git；一次性 Git 身份提交。
- **建议（供总控决策）**：v2 证明"判断纪律强化能提高 uncertain 拒答意愿"（overclaim −6 达标）但拒答精确度不足（6 个可判定帧被推入拒答 = 5 个正确判断损伤 + 1 个误报修复）。下一轮候选方向：把拒答触发条件精确化（区分"运动模糊但目标可辨"与"真正不可判定"；相似物体干扰只在无法排除时拒答），并以相同预注册协议重跑；**Task 19B 历史 v1 动态三臂边界 0/8 与 v2 动态边界 not_measured（阶段 C 未运行）分属不同证据，不得互替**；Task 21 固定采样重放（`artifacts/task-21/replay/（内部留档）`，规则级反事实诊断，正式评分 REPLAY_UNSCORABLE）显示同期 v1/v2 存档输出在 Task 17 方向兼容规则下均 0/24 次边界暴露匹配——下一阶段最值得验证的故障层是**状态映射/边界评分规则与视觉语义的耦合**（模型在被触达 uncertain 区仍给确定性结论、fixed 时间点上无非确定类别相邻转换可承接边界），需新证据而非本轮修复。WEB01/WEB03 失败模式仍待独立方案。详见 `artifacts/task-20/（内部留档）run-summary.md` 与 `artifacts/task-21/`。

## 22. 阶段 5 第八部分（任务 21，2026-09-23）——Task 20 勘误与固定采样时序重放（CPU-only）

- **性质**：两件事——(1) 依据 256 个逐点存档的只读独立复算，新增 Task 20 人类可读口径勘误（`artifacts/task-21/errata/task20-errata.md`，E1–E7），修正 README/PROJECT_CONTEXT/BENCHMARK/本文件的误导性表述并保留版本历史；(2) 沿 Task 19B 已选定的 9 样本 × 3 臂原时间戳，用 Task 20 已存档同期 v1/v2 判断做**固定采样反事实重放**（`fixed_sample_replay`，新模型调用 0）。阶段 A 分析计划提交 `75244e2`（`artifacts/task-21/plan/（内部留档）`，含 396 条输入 SHA-256）先于任何重放产物。
- **映射核验**：256 点 ↔ 27 运行一一对应（每臂 121/51/84；27 组时间戳序列与 Task 19B timeline 逐项相等）；七类账 v1/v2 各 256 与 paired-rows 复算一致；跨臂同帧不同输出（v1 4 帧、v2 2 帧）按臂各自保留，不去重代表行。
- **重放结论（规则级，Task 17 冻结纯函数直接计算）**：同期 v1 与同期 v2 在 24 次边界暴露上均 **0 匹配**（8 个不同 GT 边界 × 3 臂）；v2 唯一进入遮挡区的拒答（AI04/uniform t=7375）产生的括号 [6458.333,7375]/[7375,8291.667] 不包含任一边界时刻（4000/9000）——固定采样几何下无非确定类别相邻转换可承接边界；confirmed 事件覆盖 21/21、未触达 uncertain 段 4、失败点 1（T20-P0152 保持 failed，未改写为拒答）。
- **正式评分**：**REPLAY_UNSCORABLE**——冻结 scorer 的 G7 provenance 自洽（actual_model_calls == fresh_call 决策数 == 时间线条目数）无法在诚实标注（archived_call）下满足（54/54 候选文档被拒）；唯一"通过"方式是把 Task 20 已存档调用冒充本轮 fresh_call（伪造 provenance，明令禁止）。未修改 Task 17 scorer / Task 18/19 适配器 / 任何历史 artifacts。
- **状态正交**：Task 20 `TRADEOFF`（模型质量）与 Task 21 `REPLAY_UNSCORABLE`（正式评分可执行性）互不改变；v1 仍是生产模板；holdout 未开启。
- **测试与验证**：新测试 12/12（`scripts/test_task21_replay.py`：映射/七类账/排序/失败点保留/方向兼容/无边界分母/8≠24 分母/跨臂不去重/零写入与确定性/G7 阻塞实证/冻结代码零改动）；`artifacts/task-21/verification.json（内部留档）`；未运行新视觉推理、未抽帧、未联网、未装依赖、未启停服务、未读凭据。

## 23. 阶段 5 第九部分（任务 22，2026-09-23）——单调用分项视觉证据核验：同期同帧配对实验

- **性质**：dev 校准实验。唯一新假设 = 要求视觉结论携带**分项、可审计的画面支持**（目标类别/必要属性/目标关系/可见性）并据此校准判断纪律，能否减少 uncertain 区过度断言而不伤害可判定帧。设计为同期同帧配对：256 个 Task 19B 采样点，每点生产 v1 与唯一候选 c3 各一次真实 Qwen 调用，同一份帧字节/模型/参数/查询；唯一变量为候选视觉判断契约。核心 JSON 契约与 classify_entry 兼容，分项为附加可审计字段（缺项记录、不猜补）。**关键设计**：区分"画面里没有目标"（确定性负面）与"画面不足以判断"（拒答），并明确"模糊/暗/小/远/遮挡/相似物"等词**不是机械拒答开关**（针对 Task 20 v2 在 AI01 t=666 误拒的教训）。
- **阶段 0（只读，先于任何 Task 22 dev 调用）**：用 Task 17 冻结评分器纯函数从 256 逐点存档独立复算 Task 20 七类账（v1 186/24/0/0/6/40/0、v2 181/23/6/0/11/34/1，各 256）一致；Task 21 `REPLAY_UNSCORABLE` 来源约束复核一致；dev 包 manifest/九段哈希核验通过；资源窗口开放（H3 停止、MemAvailable ~115.8 GiB、无外部 Qwen 消费者）。
- **预注册（阶段 A 提交 `4a71d7b`，06:35:23Z，早于第一笔 dev 调用 06:36:06Z ~43s）**：design.md + evaluation-plan.json + prompt-c3.txt（sha256 `2f669089…`）+ paired_scorer.py + point-manifest-256.json + frozen-hashes.json（31 条）+ runner + 测试；门槛 G1–G6 与 verdict 顺序冻结（G3 比 Task 20 更严：correct 总降 ≤2、licensed-public 不得减少；新增 G4 误拒门 abstention_on_determinate 增 ≤2、G5 failed_on_uncertain 门）。fixture smoke 验证链路（0 失败，c3 分项完整 2/2）。
- **正式配对**：256 点 × 2 版 = **512/512 真实 Qwen 调用**（06:35:42Z→09:25:14Z，~2h50m）；ok 512、**0 超时/0 无效 JSON/0 call_failed/0 contract_rejected/0 重试**；平均 18.26s；c3 分项支持完整度 **256/256（100%）**；顺序轮换 v1 先/c3 先各 128；批量前 8 项资源门全过、运行中无阻塞。
- **配对结果（verdict=NO_IMPROVEMENT）**：七类账 v1 185/25/0/0/5/41/0、c3 185/22/3/0/2/44/0（各 256）。**G1 FAIL**（overclaim 41→44，反升 3，未达降幅 5）：核心 uncertain 样本 AI06 overclaim 27→32、appropriate_abstention 5→0（c3 的"模糊非机械拒答开关"被模型过度解读为"低照度小目标仍可下确定性结论"），掩盖 AI04 遮挡区改进（overclaim 9→7）。**G4 FAIL**（abstention_on_determinate 0→3，超容忍 2）：AI01 运动模糊边际帧 t=666 ×3 臂仍被误拒（与 Task 20 v2 同帧失败）。G2/G3/G5/G6 PASS（licensed-public 有小幅正迁移：correct +3、incorrect −3）。去重（184 帧）方向一致（overclaim 31→33）。效率：c3/v1 平均耗时比 1.399（≤1.5）、输出 ~31% 变长。
- **阶段 C/DSH 会话**：**未运行**（verdict≠IMPROVEMENT，预注册停止门）；`scripts/run_task22_dynamic.py` 已按设计备好但未执行；不迭代第二个候选。
- **测试与验证**：新测试 30/30（`scripts/test_task22_pairing.py`：含与冻结评分器 256 点逐行等价、G1–G6 门槛单测、c3 coercer 契约、真假阳性/真实拒答/误拒/失败/跨轨分层/哈希漂移 fixture）；回归全过（Task 19 22/22、17 38/38、18 36/36、16 27/27、04 16/16、06 32/32、M1–M8 10/10、Tier-3 v2 17/17、工作台 26/26、Task 20 19/19、Task 21 12/12）；交付验证 `scripts/verify_task22.py` **12/12**（V1–V12）；`git diff --check` 干净、敏感扫描 0 命中、冻结路径零改动、无媒体入 Git。**artifact 还原披露**：运行 Task 19 回归会重写 `artifacts/task-19/test-results.json（内部留档）`，已 `git checkout` 还原为提交字节。
- **未做（红线）**：未运行阶段 C 动态三臂与 DSH 自主会话（未过门）；未采纳 c3 进 Skill（analyze_image.py 零改动，v1 仍是生产模板）；未开始 holdout；未替换模型；未接入工作台；未录屏/文章/推送；未安装依赖/联网/改配置/启停服务；原始视频与派生帧未入 Git；一次性 Git 身份提交。
- **状态正交与结论**：工程状态 **PAIRING_COMPLETE** 与模型质量状态 **NO_IMPROVEMENT** 分开。分项可审计支持被模型 100% 满足，但**满足分项格式并未转化为更好的 uncertain 判断校准**——失败层仍在视觉模型语义本身（低照度/遮挡下倾向确定性结论、边际可辨与不可判定的界线不稳定），与 Task 19B/20/21 诊断一致。Task 19B 历史 v1 动态三臂 8 个 GT 边界 0/8 与 c3 动态边界 not_measured（阶段 C 未运行）分属不同证据，不得互替。dev 小样本 + 单次运行 + 温度 0.1 随机性：不得给出统计显著性、不得外推真实仓储准确率。详见 `artifacts/task-22/（内部留档）run-summary.md`。

## 24. 阶段 5 第十部分（任务 23，2026-09-23）——StepFun 视觉小样本质量闸门（`GATE_NOT_MET`）

- **性质**：检验 Step 3.7 Flash 图像 API 是否可作为视觉兜底候选。**技术可调用性不等于生产兜底**——小样本质量闸门未过，路线停止，未接入正式链路。
- **设计**：同期同帧配对（48 帧清单冻结，提交 `6755900`），候选 = step-3.7-flash 图像调用，基线 = 同期生产 v1 本地 Qwen；同一份帧字节、同一查询；预注册协议 + 调用纪律 + 扩实验闸门先于任何正式调用。
- **结果**：96/96 同期同帧配对完成；**verdict = `GATE_NOT_MET`**（G1 有害降幅、G2 overclaim 降幅、G5 失败不增 三项失败）。
- **纪律**：按预注册纪律保留失败产物、停止 step-3.7-flash 路线、不擅自再调第二个候选；生产视觉模板仍是本地 Qwen v1。
- **未做（红线）**：未把该路线接入生产链路；未修改 Skill 或评分器；未触碰 holdout；未装依赖/联网/启停服务/改配置。详见 `artifacts/stepfun-vision-gate/run-summary.md`。

## 25. 阶段 5 第十一部分（任务 24 / 24A / 24B，2026-09-23）——32 单元固定面板真人复核

- **任务 24（双人分配阶段 A/B，已作废留史）**：冻结 32 单元一对一复核协议（配额 9 样本 / A20+B20+重叠 8 / 40 次独立决定；提交 `dd029b6`）；独立本地复核入口（回环 8765、别名隔离、三选一仅降级、JSONL 续审）+ 19 项构造测试全过，状态 `REVIEW_READY`（提交 `5143cd9`）。后被任务 24A-solo 的单人协议取代，**旧双人分配作废但留史**（指针 `dd029b6`）。
- **任务 24A-solo（用户单人复核）**：阶段 A 冻结协议（提交 `0b8b7a0`）——32 单元一对一 / 单一别名 `reviewer-solo` / 0 重叠 / 分母 32/32，早于任何真人决定；阶段 B 实现回环 8765 单别名入口（提交 `febf119`），25 项构造测试全过、隔离旧回归、旧入口失效，状态 `SOLO_REVIEW_READY_FOR_BROWSER_CHECK`（零真人决定，`browser_qa=not_run`）。
- **任务 24B（封存与诊断评分）**：32/32 真人决定独立核验通过并**快照封存**（提交 `44db514`，早于首次 GT 读取；reviewer-solo/confirm 29 + reject 1 + undetermined 2 / 逐条哈希绑定 / service.log 佐证 32 次 / 零 GT 已读声明）。评分（提交 `5d34237`）：**模型单独七类账 15 正确 / 8 错断 / 8 过度 / 1 恰当拒答；人机联合 29 确认 + 1 驳回 + 2 无法判断；错误断言 16→15（拦截 1）；正确断言 15→14（降级 1）；覆盖率 31/32→29/32；转移矩阵全量；来源三方复算零冲突**；审阅耗时 `unreliable`、一致性 `not_applicable`。最终状态 **`PILOT_MEASURED`**。
- **口径红线**：**带答案人审不能宣称降低误判**——这只是 32 个故障富集、非随机、单审阅者的 dev 单帧单元上的诊断测量；新视觉/文本模型调用 **0**（全部为 Task 22 归档 `archived_call`）。
- **未做（红线）**：未修改任何旧 GT、scorer、Skill、生产模板、冻结 artifacts；未触碰 holdout；未装依赖/联网/启停服务/改全局配置。详见 `artifacts/task-24b/FINAL-REPORT.md（内部留档）`、`artifacts/task-24/freeze/`、`review/README-SOLO.md（review/ 为内部留档）`。

## 26. 阶段 5 第十二部分（任务 25，2026-09-23）——中心帧 + 邻帧上下文视觉质量闸门（`STAGE1_HARM_STOP`）

- **假设**：让同一个本地 Qwen 在一次调用中看到指定中心帧以及前后各 500ms 的邻帧（有序、明确标注），是否比同期单帧生产 v1 更能判断中心帧目标状态。
- **阶段 0 技术 smoke（项目外合成图 7 次）**：本地 Ollama Qwen 端点支持**单次请求有序多图**；模型能稳定只判中心帧；目标只在邻帧时中心 `object_found=false`。verdict = **FEASIBLE**。
- **阶段 A 预注册**（提交 `2961139` + `0d3b9d4`，先于任何正式 dev 调用）：184 唯一中心帧（去重 Task 22 冻结 256 点，generated 110 / licensed-public 74）；邻帧 ±500ms（`extract_frames` 同一解码路径，越界缺席，探针证明 decode+encode 逐字节一致）；候选 cand = 生产 v1 + 图序 / 只判中心帧前置说明 / 两处中心帧指代替换。
- **阶段 B 结果**：48 对同期配对、96/96 真实调用（0 超时 / 0 无效 JSON / 2 契约拒绝）。verdict = **`STAGE1_HARM_STOP`**——候选多图**略微**降错误断言（20→19）、升正确判断（26→27）、降误报（incorrect 10→8），但**引入 2 次输出契约失败**（`failed_on_determinate` / `failed_on_uncertain` 各 0→1，触发 B4 门）、overclaim 反升（10→11）、新增 2 个邻帧目标误投射中心。
- **结论**：**加入邻帧时序上下文不是修复路径**（失败层仍在视觉模型语义 + 多图下输出契约稳定性）。按停止门不运行阶段 C、候选未采纳（生产 v1 零改动）、holdout 仍封存。
- **测试与验证**：新测试 28/28、Task 22 回归 30/30、Task 17 38/38、交付验证 13/13（`artifacts/task-25/`）。
- **未做（红线）**：未采纳候选；未运行阶段 C；未开始 holdout；未录屏/文章/推送；未装依赖/联网/改配置/启停服务。详见 `artifacts/task-25/run-summary.md`。

## 27. 阶段 5 第十三部分（任务 26A，2026-09-24）——盲化（无答案）标签复核（`REVIEW_READY`）

- **性质**：对 Task 22 归档 184 唯一帧做**盲化**（无答案）真人复核，用于分离"模型判断"与"人审判断"的争议来源。**不揭示、不修正 GT。**
- **阶段 A 冻结**（提交 `1829e9d`）：盲化复核协议 + 顺序承诺 + 入口实现，早于任何真人决定。
- **阶段 B**：入口就绪 + 真实浏览器 QA 通过，状态 **`REVIEW_READY`**，真实有效真人决定 **0/32**（提交 `2b97d61`）。
- **未做（红线）**：未解封任何旧 GT；未宣称 GT 已修正；未触碰 holdout。详见 `artifacts/task-26a/（内部留档）`。

## 28. 阶段 5 第十四部分（任务 26B，2026-09-24）——封存后只读对照（`SEALED_AND_ANALYZED`）

- **纪律**：门 A 封存提交 `4577c43`（2026-09-24T02:25:45+00:00）**早于**本门首次读取任何逐项旧 GT/旧人审资料（02:26:09 起）；分析前再次复检封存快照与在线原日志逐字节一致（零漂移）。顺序可经 Git 提交时间与脚本前置断言（`analyze_gate_b.py` B0d）独立核验。
- **结果**：一对一技术映射 **32/32 通过**、零工程故障；旧七类账与 Task 24B 关键计数独立复算全部一致；新判断 × 旧 GT 交叉表与分层聚合已出。最终状态 **`SEALED_AND_ANALYZED`**（提交 `df9965f`）。
- **口径红线**：本门**只揭示标签/模型/人审的混合争议**，**不能宣称 GT 已修正**；不产出"模型准确率提高""人审纠正多少错误""GT 已修好"等任何质量 PASS 表述。
- **未做（红线）**：本轮新视觉/文本模型调用 **0**；未联网、未装依赖、未停启任何服务；未读取 `.credentials.yaml`；未新增 remote、未 push；holdout 零接触；未修改任何旧 GT、scorer、Skill、生产模板、冻结 artifacts。详见 `artifacts/task-26b/（内部留档）GATE-B-REPORT.md（内部留档）`、`artifacts/task-26b/（内部留档）GATE-A-REPORT.md`。

## 29. 阶段 5 第十五部分（任务 26C，2026-09-24）——视频上下文补充复核（用户中止，`STOPPED_BY_USER_NOT_SCORED`）

- **阶段 A 冻结**（提交 `47e5eb5`）：视频上下文补充复核协议 `task26c-context-1.0` + 14 项顺序承诺 + 盲化入口实现，零真人决定。
- **阶段 B**（提交 `e4f9323`）：入口就绪、指标口径已明、14 项构成/媒体绑定/泄漏/隔离门全部通过、真实 Firefox 浏览器 QA 通过，状态 `CONTEXT_REVIEW_READY`，真实有效真人决定 **0/14**。
- **收尾（最终状态）**（提交 `4430263`）：**用户明确决定 Task 26C 视频上下文复核不继续**（表单措辞歧义），状态 **`STOPPED_BY_USER_NOT_SCORED`**。真实有效真人决定 **2/14**（独立从仓库外私有日志复算，不采信 UI 自报；与用户自述"只提交两项"一致，非 `COUNT_MISMATCH`）。两条决定两问与理由均完整、`mapping_sha256` 与冻结承诺一致、逐条帧/媒体哈希与冻结包一致，无异常记录。
- **处理**：**未暗中修改**已冻结的问卷/协议/入口代码；Task 26C 此前的 `CONTEXT_REVIEW_READY` 历史**原样保留**（`artifacts/task-26c/STATUS-REPORT.md（内部留档；公开版仅含 STOP-REPORT.md）` 未篡改）；2/14 真人决定**原样封存**于仓库外受限目录（禁入 Git）；仅停 `127.0.0.1:8767`，其余服务不受影响。
- **口径红线**：**不得拿两项真人决定做统计**；不评分、不改旧记录、不自动进入 Task 26D。脱敏汇总报告见 `artifacts/task-26c/STOP-REPORT.md`（可公开引用）。
- **未做（红线）**：零模型调用、零重评分、未读取逐项旧 GT/旧人审作新分析、未装依赖、未联网、未改全局配置、未触碰凭据或 holdout；Task 17–26B 冻结产物、三个 Skill、生产视觉模板、工作台零改动。

## 30. 阶段 5 第十六部分（任务 27，2026-09-24）——赛事交付候选包与诚实演示方案

- **性质**：文档、发布审计与演示 runbook。**不直接公开仓库、不上传 B 站、不发表文章、不提交表单、不 push、不建 remote。**
- **起末状态**：起始 HEAD `4430263`（Task 26C 收尾，工作树干净、分支 `master`、无 remote、无 Git 锁）；结束 HEAD 见本任务提交。
- **产出**（集中于 `docs/submission/（整目录为赛事交付候选包，内部留档）`，未覆盖任何既有文件）：
  - `README.md`：候选包索引与两层最终状态；
  - `RELEASE-RISK-AUDIT.md`：按 Git 实际跟踪文件（5006 文件 / 115.8 MiB）做的公开发布风险审计，含 R1–R6 `REVIEW_REQUIRED` 清单与 `RELEASE_BLOCKED` 判定；
  - `WINDOWS-RELEASE-HANDOFF.md`：Windows 端同步/发布 Agent 安全交接说明（候选提交、排除清单、复现者须自行获取项、LICENSE 追认、脱敏重写风险）；
  - `CLAIM-EVIDENCE-MATRIX.md`：12 类主张—证据—限制矩阵 + Task 26C 最终状态专项核对 + 缺失证据明示；
  - `DEMO-RUNBOOK.md`：10 镜头可裁剪演示顺序 + 素材许可门 + 绝对红线 + 3 分钟裁剪方案；
  - `SUBMISSION-MATRIX.md`：12 项提交材料状态矩阵 + 十日谈素材索引 + 文档一致性审查；
  - `TASK27-VERIFICATION.md`：验收记录（只读/隔离测试、`git diff --check`、敏感扫描、引用核验）。
- **按事实修正的人类可读文档**：`PROJECT_CONTEXT.md` §4（"移动路径" → "出现/未出现的时间区间"，与 §9 红线一致）、`README.md` §首个应用场景（"对象追踪" → "对象存在性与时序证据"）+ 新增 `docs/submission/（整目录为赛事交付候选包，内部留档）` 导航、`docs/DEVELOPMENT_STATUS.md`（本文件：补齐任务 23–26C 记录并更新日期与 HEAD 口径）。
- **未做（红线）**：未修改三个 Skill 核心逻辑、schema、评分器、历史 artifacts、工作台业务代码、Tier-3 冻结任务集、`BENCHMARK.md`、`docs/plans/`、`LICENSE`；未启动新视觉评测、未装依赖、未联网下载、未启停 MiniMax-H3/DSH/Ollama；未调用 StepFun/Qwen；未读取 `.credentials.yaml` 或任何 key/token/密码；未搜索/读取/使用 holdout holdout 样本编号 的任何真实媒体、卡片、GT、路径或哈希；未创建公开仓库、未上传文件、未擅自选定许可证、未删除历史以求通过。
- **最终状态**：技术候选包 **`PACKAGE_READY_FOR_USER_REVIEW`**；公开发布 **`RELEASE_BLOCKED`**。**不得写 `SUBMISSION_COMPLETE`。**
