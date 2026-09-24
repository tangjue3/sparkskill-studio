# 运行摘要 — 任务 18：Coverage-Aware Adaptive Sampling v2 与预注册三臂评测

- 日期：2026-09-22（首轮 + 补跑轮）
- 基线：分支 `master`，HEAD `929314365c3087f0756b1f0cd285669ede0feaa7`（任务 17 提交），工作区干净，无 remote，恢复 tag `pre-task13-deploy-4c4c3ca` 保留
- 阶段 A 提交：`dcaf324c19f018af93f8213f3ae4948531d4b699`（`docs: preregister coverage-aware sampling evaluation`）
- 实现提交：`b10b80da81657c0f26daa871f5d62a0858f2babb`（`feat: add coverage-aware temporal sampling`）
- 最终状态：**COMPLETED**（补跑轮经用户授权优雅停止 MiniMax-H3 服务族后，真实 Qwen 三臂评测 287 次调用与一次全新 DSH headless 自主会话均已完成；工程实现 PASS；replay 与 real Qwen 分别评分、分别给 verdict，均为 pack-level TRADEOFF）
- 关联：`docs/plans/2026-09-22-coverage-aware-adaptive-sampling-design.md`、`artifacts/task-18/preregistration/`、`artifacts/task-16/`、`artifacts/task-17/`

## 1. 任务与初始状态核验

任务书要求执行前只读核验 8 项。核验结果：HEAD `9293143`、分支 `master`、remote 无、tag `pre-task13-deploy-4c4c3ca` 存在、无 Git 锁/进行中 Git 进程、任务 16/17 文档/artifacts/schema/评分器/提交均存在。**唯一异常**：`artifacts/task-17/verification.json` 有未提交修改（任务 17 会话提交后重跑校验脚本遗留，`detail` 字段 "17"→"0"）。按任务书"已跟踪文件有修改立即停止并报告"的规定停止并请示用户；用户授权后执行 `git restore artifacts/task-17/verification.json` 恢复为冻结版本，工作区干净后开始任务。

## 2. 阶段 A：设计、预注册与第一次提交（先于实现）

- 设计文档 `docs/plans/2026-09-22-coverage-aware-adaptive-sampling-design.md`：回答任务书 18 个必答问题（覆盖盲区、触发式细化的结构缺陷、职责分离、预算分配、最大相邻间隔定义、覆盖分辨率边界、任意短事件不保证、旧策略零变化、向后兼容、公平条件、预注册内容、非确定性记录、覆盖与校准分离、过度断言评分、组件职责、资源守卫、回归/冻结范围、非目标红线）。
- 新增 6 段确定性 technical fixture（`scripts/generate_task18_fixtures.py`；与任务 16 同一组冻结生成参数 640×360@24fps/8s/192 帧/mp4v/红色正方形 80×80；低对比度区间 BGR (214,214,214)）：short-event-between-grid（事件 [3500,4100]）、short-uncertain-between-grid（uncertain [3500,4100]）、twin-short-events（[1600,2200]+[3000,3600]）、absent-throughout、short-event-phase-b（[6200,6800]）、short-uncertain-phase-b（[6200,6800]）。第一次评测前冻结 manifest + ground truth + SHA-256（`--verify` 复核通过；4 段复用任务 16 冻结 fixture 以相对路径引用并核验哈希一致）。
- 任务 18 契约（`artifacts/task-18/contracts/`）：11 样本 Evidence Pack manifest + 11 份任务 17 契约格式 Ground Truth（present→confirmed、absent→not_found、present_low_contrast→uncertain；容差 250ms）+ 11 张数据卡；`validate_evidence_pack.py` 校验 RESULT: VALID。
- 预注册 7 份文件（`artifacts/task-18/preregistration/`）：evaluation-plan / arm-configs / verdict-policy / fixture-manifest / ground-truth-manifest / frozen-hashes / README + 构建与自检脚本。自检 8/8（设计文档 18 问、文件齐全、JSON 结构、frozen-hashes 41 条目一致、fixture 冻结、契约校验、安全扫描、实现尚未开始）。
- **阶段 A 提交 `dcaf324`**（一次性身份 `tangjue3 <tangjue3@users.noreply.github.com>`，未改全局配置，未 push）——评测规则先于实现冻结，形成时间顺序证据。

## 3. 阶段 B：实现（最小兼容改动）

| 文件 | 改动 |
| --- | --- |
| `schemas/visual-task-spec.schema.json` | strategy 枚举 +`coverage_aware_adaptive`；新增 `coverage_gap_target_ms`（>0）与 `coverage_call_reserve`（正整数）两个 coverage 专属字段；描述同步 |
| `.dsh/skills/task-to-skill-compiler/scripts/validate_task_spec.py` | `check_sampling_strategy` 新分支：coverage 六必填字段、`initial+reserve ≤ max_model_calls`、uniform/adaptive 拒绝 coverage 专属字段 |
| `.dsh/skills/visual-evidence-extractor/scripts/adaptive_sampler.py` | STRATEGIES 扩展；配置解析新分支（含覆盖配置越界拒绝）；新增纯逻辑：`observed_points`/`adjacent_gaps`/`max_adjacent_gap_ms`/`coverage_candidates`/`next_coverage_candidate`（largest-gap-first，并列取最早）/`underobserved_intervals`；`build_temporal_evidence` 增加 coverage 块与限制声明 |
| `.dsh/skills/visual-evidence-extractor/scripts/trace_temporal.py` | 新增阶段 2 覆盖探索（确定性 largest-gap-first 二分；重复时间戳排除；停止原因 coverage_gap_target_reached/coverage_reserve_exhausted/coverage_no_refinable_gap/budget_exhausted/resource_blocked）；细化阶段扩展到新策略；provenance 增加 initial/coverage/refinement 调用区分、最大相邻间隔初始/最终值、underobserved_intervals、两个限制字段；decisions 增加 purpose/candidate_interval；CLI 增加两个参数 |
| `.dsh/skills/evidence-report-generator/scripts/generate_report.py` | temporal 报告增加 coverage_summary 与覆盖限制句（附加显示，旧字段不变） |

旧策略行为经回归证明零变化（任务 16 测试 27/27 + C02 专项：uniform 预算截断、adaptive 无变化场景 4 调用/停止原因、adaptive 出现场景括号含 3200ms 且精度达成——与任务 16 冻结行为逐项一致）。

## 4. 测试与 deterministic replay

- **任务 18 新测试 36/36**（`test_task18_coverage_sampling.py`，C01–C35 + C34b；构造证据回放，除 C30 复用 replay 产物外零模型调用）：覆盖任务书第十节全部 35 项要求（契约/兼容/预算/覆盖/细化/场景/五类分支/uncertain 评分/GT 不进入采样/只读/卫生/provenance 自洽/多来源/资源守卫/四类 verdict/预注册哈希）。
- **三臂 deterministic replay**（`run_task18_comparison.py --mode replay`，11 场景 × 3 臂，构造证据 `constructed_fixture_evidence`）：逐场景指标见 `deterministic/comparison.json|md`。关键实证：
  - short-event-between-grid：coverage 发现事件（漏检 0/匹配 2/2/容差内 2），adaptive 漏检（1）——任务 17 盲区被修复；
  - short-uncertain-between-grid：coverage 触达 uncertain（2 次恰当拒答、未触达 0），adaptive 未触达（1）——abstain-zone 盲区被修复；
  - twin-short-events：coverage 与 adaptive 均漏检 2/2（600ms 事件 < 1333.334ms 最终间隔），uniform 12 点网格 0 漏检——**任意短事件不保证发现的诚实实证**；
  - reappear-tight-budget（三臂预算 6）：coverage 初始 4+覆盖 2+细化 0，adaptive 初始 4+细化 2，uniform 截断 6 点——预算竞争确定性分配；
  - 语义内容逐字节可复算（两次运行仅 `generated_at`/`timing.*_ms` 墙钟字段不同）。
- **评分**：任务 17 冻结评分器经适配层 `task18_scorer_adapter.py`（内存扩展策略白名单，文件零改动）评分。公平门 10/10 × 3 对全部通过。**Pairwise verdict**：coverage-vs-adaptive = **IMPROVEMENT**（平均边界误差更小、容差内边界更多，无非回归违反）；coverage-vs-uniform = **TRADEOFF**（省调用+边界更准但 twin-short-events 漏检更多）；adaptive-vs-uniform = **TRADEOFF**（与任务 17 结论一致的模式）。**Pack 级 verdict = TRADEOFF**（对两个基线：平均边界误差严格更好，但对 uniform 漏检更多、最大间隔更大）——按预注册规则计算，未预设、未调参。
- 适配层端到端验证：混合预算进入比较范围时三对比较全部 `INVALID_COMPARISON`（same_call_budget 失败，C30）；四类 verdict 规则单元验证（C31–C34b）。

## 5. 资源门槛、授权停服与真实评测（补跑轮完成）

### 5.1 两轮阻塞历史（原样保留）

首轮 12:08 与补跑轮初测 12:42 均因用户 MiniMax-H3 服务族活跃失败：h3-lite API
（:8010，resident，今日 11:10 启动）、h3-studio WebUI（今日 11:24 启动，
WEBUI_IDLE_STOP_MINUTES=600）、7861–7863 遗留 tab_test 服务、2 个 coexistence-keeper
守护进程；用户当天 11:28:57 仍有 t2va 生成记录（job 4dba2a28c2f8，240.4s）。两轮
结构化 blocker 保留于 `resource-gate-rerun.json` 历史块，当时均**未获得**停服授权，
未执行 Qwen、未虚构结果。

### 5.2 用户授权后的安全门与优雅停服

补跑轮用户明确授权停服。停服前重新建立事实（不照抄旧 PID）：完整进程清单（PID/PPID/
启动时间/命令行/端口）、生成队列连续三次为空（generation_lock=false, queue_depth=0,
running=false）、:8010 无任何 ESTAB 连接、:7860 仅一条无主 idle keep-alive、输出目录
10 分钟无新文件、最近完成任务为 11:28:57。确认官方 stop 脚本均不可原样使用
（stop-h3-lite.sh 会升级 kill -9；stop-studio.sh 依赖不存在的 tmux 会话且会
pkill -9）后，手工执行纯 SIGTERM 优雅停止：WebUI 树（930055→930056/930053/930052
管道自然结束）→ API（899899，pidfile+cmdline 校验）→ tab_test2/3/4 → 2 个
coexistence-keeper（命中冻结门槛 WEBUI_PATTERNS 的 `minimax-h3/experiments` 模式，
不停止则 real 门禁必然失败；归属经路径核验，恢复命令已记录）。全部 1-5 秒自行退出，
零残留、零强杀。DSH/Ollama/SSH/系统服务未触碰；用户 51 个输出视频与 163G 模型未动；
PID 文件未删（stale pidfile 由官方脚本逻辑处理）。逐项证据：
`h3-shutdown-record.json`。**任务结束后 H3 保持停止，未执行恢复。**

### 5.3 真实 Qwen 三臂评测（`--mode real`）

- 命令：`python3 scripts/run_task18_comparison.py --mode real`（未覆盖 --budget/
  --timeout，按预注册默认 12/6 与 300s）；运行前 runner 内置 8 项门槛 all_passed=True
  （mem 115.84 GiB×3），fixture 冻结复核 FROZEN_OK。
- 规模：11 场景 × 3 臂按预注册顺序（场景按 scenario_order，臂 uniform→adaptive→
  coverage）；同一 Qwen 模型（本地 Ollama `modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`，
  vision 能力）、同一后端/超时/输出格式；**实际模型调用 287 次**
  （uniform 120 + adaptive 54 + coverage 95），与 replay 计划逐臂一致；**零失败、
  零超时、零无效输出**；每次原始返回存档于 `real-qwen/<场景>/<臂>/raw/`。
- 真实逐场景关键结果（confirmed 帧数 / 调用数 / 最大间隔最终值）：
  - short-event-between-grid：uniform 1/12/708ms、adaptive **0/4**/2667ms（漏检）、
    coverage **2/11**/1333ms（**发现事件**）；
  - short-uncertain-between-grid：coverage 9/11 触达 uncertain 但给出确定性结论
    （过度断言），adaptive 4/4 未触达；
  - twin-short-events：uniform 2/12（发现两个 600ms 事件）、adaptive 0/4、coverage 0/7
    （均漏检——任意短事件不保证发现的诚实实证）；
  - absent-throughout：三臂均 0 confirmed（正确确定性负面）；
  - reappear-tight-budget（预算 6）：uniform 截断 6 点、adaptive/coverage 各 6 次
    （coverage 初始 4 中仅 2 次覆盖调用后细化 0，预算竞争如实记录）。
- **评分**（任务 17 冻结评分器 + 任务 18 冻结适配层，real 与 replay 分开）：
  - 聚合（real）：correct_decisive uniform 118 / adaptive 54 / coverage 91；
    incorrect_decisive 三臂 0；overclaim_on_uncertain **uniform 2 / adaptive 0 /
    coverage 4**；appropriate_abstention 三臂 0；covered_confirmed_events
    uniform 13/13、coverage 11/13、adaptive 9/13；matched_boundaries
    uniform 13 / coverage 9 / adaptive 5；边界误差均值 uniform 196.474ms /
    adaptive 138.333ms / **coverage 93.519ms**；最大相邻采样间隔 uniform 708.334ms /
    coverage 1333.334ms / adaptive 2666.667ms。
  - **Pairwise（real）**：coverage-vs-uniform = **TRADEOFF**（省调用+边界更准，但
    overclaim 4v2、漏检 2v0）；coverage-vs-adaptive = **TRADEOFF**（边界误差更小+
    容差内更多，但 overclaim 4v0——**replay 的 IMPROVEMENT 在真实模型下不成立**）；
    adaptive-vs-uniform = TRADEOFF（与任务 17 一致的模式）。
  - **Pack（real）= TRADEOFF**：严格改进 `smaller_mean_boundary_error_than_both`；
    违反 `more_overclaim_on_uncertain_vs_uniform`、
    `more_missed_confirmed_events_vs_uniform`、`more_missed_gt_boundaries_vs_uniform`、
    `larger_max_sampling_gap_vs_uniform`、`more_overclaim_on_uncertain_vs_adaptive`。
  - replay 与 real 的差异全部来自**视觉模型语义**（Qwen 对 uncertain 过度断言、
    对短事件能正确识别），采样计划两种模式完全一致；两者指标不混合平均。
- 产物：`artifacts/task-18/real-qwen/`（777 文件：逐臂 spec/evidence/report/frames/
  raw 287 份 + scores/ + comparison.json|md + prediction-set.json）；
  `deterministic/` 零改动。

### 5.4 DSH headless 自主会话（成功）

- 命令：`dsh --profile headless "<task-prompt>"`（提示词预注册于
  `dsh-session/task-prompt.txt`，提供合法 fixture 路径与冻结参数）；会话
  13:55:46→14:00:22（4.6 分钟），exit=0。
- 会话内 Agent 自主完成：发现并加载三个 Skill（task-to-skill-compiler →
  visual-evidence-extractor → evidence-report-generator）；source media 硬门
  accepted（user_provided，未从 README/历史/文件名推断）；StepFun 生成
  coverage_aware_adaptive VisualTaskSpec（冻结参数）并通过仓库校验器 RESULT: VALID；
  未读 Ground Truth；本地 Qwen Vision 真实调用 **11/12**（4 初始+3 覆盖+4 细化），
  原始返回全存档；报告器独立复算状态。证据：发现短事件（confirmed 3666.667/4000.0ms，
  GT [3500,4100] 被正确括号，边界不确定宽度 333.334ms < 目标 500ms），最大间隔
  2666.667→1333.334ms，underobserved 为空，限制声明齐全。
- 会话后由冻结评分器**离线评分**（`dsh-session/scores/`）：correct_decisive 11/11、
  事件覆盖 1/1、边界 2/2 容差内（mean 33.333ms / max 66.666ms）、overclaim 0、
  漏检 0；硬门 G1/G2（含媒体哈希三方一致）通过。
- 会话期间资源读数：MemAvailable 77.46 GiB（≥40 守卫），Ollama 可达，H3 保持停止。

## 6. 回归（全部通过，补跑轮重跑）

| 套件 | 结果 |
| --- | --- |
| 任务 18 新测试 | **36/36** |
| 任务 17 Ground Truth 测试 | **38/38** |
| 任务 16 temporal evidence 测试 | **27/27** |
| 任务 04 视频规则测试 | **16/16** |
| 任务 06 多视频规则测试 | **32/32** |
| M1–M8 媒体来源契约 | **10/10** |
| v2 Tier-3 评分器回归 | **17/17** |
| 工作台静态测试 | **26/26** |
| verdict 冻结规则复算 | replay 与 real 各自 pack+pairwise 全部一致 |
| `git diff --check` | clean |
| 冻结文件完整性 | 预注册 41 项哈希、7 份 blob 逐字节、fixture 冻结、17 个冻结路径、实现文件（相对 b10b80d）全部零改动 |
| 敏感信息扫描 | 凭据 0 命中；本人为记录绝对路径已 sanitize |

## 7. 边界遵守

未新增第四个 Skill；未修改任务 16/17 冻结 artifacts、Tier-3 冻结任务/评分器/PASS
条件、工作台；未接入用户 dev/holdout；未安装依赖；未联网；未改全局配置；未读取或输出
凭据；未添加 remote、未 push。停服经用户明确授权且限于事实核验归属 `~/minimax-h3`
的进程：纯 SIGTERM、无 kill -9、无批量 pkill、未停 DSH/Ollama/SSH/系统服务、未删除
用户文件、未改开机启动/watchdog/环境变量。真实模型调用总数：**287**（三臂评测）+
**11**（DSH 会话）= 298，全部为本地 Qwen Vision 真实调用；replay 为构造证据，
两者不混合。两轮资源阻塞记录按任务书要求保留，未倒写授权历史。

## 8. 产物索引

`artifacts/task-18/`：`preregistration/`（7 份预注册 + 构建/自检脚本）、`fixtures/`、
`contracts/`、`deterministic/`（replay 逐场景逐臂产物 + scores + comparison）、
`real-qwen/`（真实三臂评测全部产物 + scores + comparison + 287 份原始返回）、
`dsh-session/`（会话提示词、spec、校验、证据、报告、11 份原始返回、离线评分）、
`three-arm-comparison.json/md`（replay 顶层）、`verdict.json`（replay/real 双块 +
DSH 会话）、`resource-gate.json`（runner 按已提交行为重生成为停服后通过态）、
`resource-gate-rerun.json`（两轮阻塞历史 + 停服后通过门槛）、
`h3-shutdown-record.json`（授权停服全程证据与恢复方式）、`test-results.json`、
`known-limitations.md`、`run-summary.md`（本文件）、`verification.json`（24 项）、
`verify_task18.py`。新脚本（首轮已提交）：`scripts/generate_task18_fixtures.py`、
`scripts/run_task18_comparison.py`、`scripts/task18_scorer_adapter.py`、
`scripts/assemble_task18_final.py`、
`.dsh/skills/visual-evidence-extractor/scripts/test_task18_coverage_sampling.py`。
