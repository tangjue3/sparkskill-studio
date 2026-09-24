# Task 16 运行摘要 — 目标时序证据与粗到细自适应采样

- 日期：2026-09-22（UTC）
- 任务：在三个现有 Skill 内向后兼容地增加"目标时序证据"与"粗到细自适应采样"（不新增第四个 Skill）
- 初始状态：分支 `master`，HEAD `04e262f7f711a4f2b1d6d3419ed1d154df03e497`，工作区干净，恢复 tag `pre-task13-deploy-4c4c3ca` 保留，无 remote
- 真实性等级：**规则测试 27/27 + 真实 Qwen 对照（100 次调用）+ 一次全新 DSH headless 自主会话（12 次调用）**；全部数字来自真实运行；技术 fixture 结果不外推为真实仓储准确率。

## 1. 资源与服务状态（任务前核验，真实记录）

| 项 | 记录 |
| --- | --- |
| Git 工作区 | 干净（HEAD 04e262f，master）；无 Git 锁、无进行中的 Git 进程；tag 保留 |
| MiniMax-H3（:8000） | 无监听、无活动推理；无 vllm/DiffusionWorker 生成进程；用户 h3-lite 实验 API（:8010）无活动连接且进程已退出。**本任务未停止、未重启、未干预任何服务** |
| Ollama（:11434） | 运行中（0.33.2）；任务开始时 `/api/ps` 无已加载模型（无外部 Qwen 消费者） |
| MemAvailable | 任务前三次采样 96.40 / 96.41 / 96.40 GiB（≥45 GiB 门槛）；真实对照期间 ≈60 GiB；DSH 会话期间 59.11–59.13 GiB（均 ≥40 GiB 资源守卫阈值） |
| DSH | 0.1.5-rc.2 正常；Skill 目录热加载验证通过（本任务修改 SKILL.md 后 catalog 描述同步更新） |
| 既有 artifacts | 任务 04/05/06/08/09/12/12.1 关键 artifacts 均在；任务 03 旧规格存在（向后兼容测试用） |

资源门槛完整记录：`artifacts/task-16/resource-gate.json`（7 项检查全部通过）与 `dsh-session/resource-gate.json`。

## 2. 实现内容（向后兼容，不新增第四个 Skill）

| 组件 | 变更 |
| --- | --- |
| `schemas/visual-task-spec.schema.json` | 新增可选顶层 `sampling_strategy`（缺失=旧版 uniform 行为）：`strategy` ∈ {uniform, adaptive_coarse_to_fine}；`max_model_calls`（1–512 硬预算）；adaptive 必填 `initial_coverage_samples`/`target_boundary_precision_ms`(>0)/`max_refinement_rounds`；可选 `refinement_triggers`（unique）、`require_sampling_provenance`/`require_temporal_evidence` |
| `task-to-skill-compiler/scripts/validate_task_spec.py` | 新增 `exclusiveMinimum`/`uniqueItems` Schema 子集支持；新增 `check_sampling_strategy` 语义规则（uniform 带细化参数、adaptive 缺必填、initial>budget 均拒绝；归入 errors 不混淆媒体契约） |
| `visual-evidence-extractor/scripts/adaptive_sampler.py`（新） | 纯逻辑：策略配置解析（与校验器同口径）、初始覆盖规划（与 extract_frames 公式一致）、细化候选区间（二分）、预算账本（按来源命名空间隔离的时间戳缓存）、时序证据推导、provenance 凭据自检 |
| `visual-evidence-extractor/scripts/trace_temporal.py`（新） | 执行器：uniform（复用 `extract_frames.plan_sample_times` + `trace_video.analyze_frame` + `trace_video.aggregate`，分类规则逐字节一致）/ adaptive（初始覆盖 + 触发器细化）；输出 temporal-evidence.json；多来源共享预算并复用 `trace_multi_video` 合并规则；`evidence_nature` 区分真实模型输出/调用失败/未调用/构造证据 |
| `evidence-report-generator/scripts/generate_report.py` | 新增 `--mode temporal` / `--mode temporal-multi`（auto 判别）：独立复算（第二套实现）首末 confirmed、五类计数、状态转换与边界不确定性；与上游 temporal_evidence/provenance 交叉校验（不一致以复算为准 + warning；预算越界告警）；必显采样策略/预算/实际调用/耗尽/精度/"不是连续跟踪真值" |
| `scripts/generate_task16_fixtures.py`（新） | technical fixture 生成与冻结（见 §3） |
| `scripts/run_task16_comparison.py`（新） | uniform vs adaptive 同预算对照（公平性字段、逐场景指标、GT 检查、Verdict 计算；`--from-artifacts` 无模型重建） |
| `scripts/run_task16_dsh_session.py`（新） | DSH headless 会话驱动器（资源门槛 + 会话记录 + 产物校验） |
| `docs/plans/2026-09-22-temporal-evidence-adaptive-sampling-design.md`（新） | 设计文档（问题/不新增第四 Skill/三 Skill 职责变化/向后兼容/预算/provenance/时序语义/边界不确定性/uniform baseline/fixture/公平性/不做事项/dev-holdout 接入路径） |
| 文档 | README、PROJECT_CONTEXT、DEVELOPMENT_STATUS、OPTIMIZATION_NOTES、REPRODUCTION 与三个 Skill 的 SKILL.md/skill-card/references/evals/BENCHMARK 全部更新 |

## 3. technical fixture（第一次评测前冻结）

`scripts/generate_task16_fixtures.py` 生成 5 段**合成技术 fixture**（640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中；确定性渲染）：

| fixture | 场景 | ground truth 转换 |
| --- | --- | --- |
| present-throughout | 持续正向 + 无状态变化 | 无 |
| appear-midway | 中途出现 | absent→present @3200ms |
| disappear-midway | 中途消失 | present→absent @4800ms |
| reappear | 出现/消失/再现/消失 | 3 个转换 @2000/4000/6000ms |
| abstain-zone | abstained/low-confidence 区间（3000–5000ms 低对比度） | 无（GT 全程存在） |

规则级 fixture（构造结构化证据）：单帧 failed、预算耗尽。多来源 fixture：appear-midway + disappear-midway（offset 5000ms）。
冻结产物：`fixtures/fixture-manifest.json`、`fixtures/ground-truth.json`、`fixtures/fixtures.sha256.json`；SHA-256（评测前 `--verify` 复核通过）：

| 文件 | SHA-256 |
| --- | --- |
| fixture-abstain-zone.mp4 | `277de0bbbb2bb327d38a5d5a30e8f0e414a15dc919daa802b81fb998adb441b2` |
| fixture-appear-midway.mp4 | `37147666284b3481c9a4ea7b0236014e880fc96f74eadd168d1910ee9e94721f` |
| fixture-disappear-midway.mp4 | `59a203c0ebff95d96f9d73e3429b60fa9de32ecdef019dfc86f7afdc5e945728` |
| fixture-present-throughout.mp4 | `f0f37098e966b337c3fb877e87d59bb4fae67d424a59b890f872dffa7a804b3a` |
| fixture-reappear.mp4 | `a298c6e36b61f4299cd09ee46bbf0b2999c6049bb71cb8a73856a7b1e9f7d0ca` |

前置探针（真实 Qwen，2 次调用）：清晰帧 confirmed（confidence=1.0，"灰色背景中央有一个红色正方形"）；缺失帧确定性负面（confidence=1.0）。**低对比度区间的真实模型行为与设计意图不符，已如实记录**（见 §6）。

## 4. 测试结果

- **任务 16 新测试**（`scripts/test_temporal_evidence.py`）：**27/27 通过**（T1–T6 契约、T7–T16 采样与预算、T17 规则一致、T18–T19 报告复算、T20–T21 多来源、T22 资源守卫零调用、T23 provenance 无凭据、T24 fixture 区分；构造证据回放 + 真实 fixture 抽取，**无真实模型调用**）。完整结果：`artifacts/task-16/test-results.json`。
- **回归（全部通过）**：任务 04 视频规则 16/16；任务 06 多视频规则 32/32；M1–M8 媒体来源契约 10/10；v2 评分器回归 17/17；工作台静态测试 26/26（未修改 app/）；任务 03 旧规格 VALID。
- **交付验证**：`artifacts/task-16/verify_task16.py`（24 项检查）。

## 5. uniform vs adaptive 真实对照（同预算 12，真实 Qwen 调用）

公平性：相同 fixture/目标查询/模型/资源窗口/状态规则/最大调用预算/超时；不单侧重试、不删除失败样本、看到结果后不改 ground truth、不修改 Tier-3。完整数据：`comparison.json` / `comparison.md`。

| 场景 | 指标 | uniform | adaptive |
| --- | --- | --- | --- |
| present-throughout | 最终状态 / 调用 | completed / 12 | completed / **4** |
| appear-midway | 最终状态 / 调用 / 转换数 / 最大边界宽度 | completed / 12 / 1 / 708.333ms | completed / **7** / 1 / **333.333ms**（≤500 目标） |
| disappear-midway | 最终状态 / 调用 / 转换数 / 最大边界宽度 | completed / 12 / 1 / 708.334ms | completed / **7** / 1 / **333.333ms** |
| reappear | 最终状态 / 调用 / 转换数 / 最大边界宽度 | completed / 12 / 3 / 708.334ms | completed / 12 / 3 / **666.667ms**（预算耗尽，第 3 边界未达 500ms 目标，如实报告） |
| abstain-zone | 最终状态 / 调用 / 转换数 | completed / 12 / 2 | completed / **4** / 0（初始覆盖未采到低对比度区间，见已知限制） |

- 两臂全部场景最终状态正确（GT 存在性 5/5；转换覆盖：appear 1/1、disappear 1/1、reappear 3/3，两臂一致）；
- adaptive 在 3/5 场景用更少调用（4 vs 12、7 vs 12、7 vs 12、4 vs 12；reappear 相同 12），边界宽度全面不劣于 uniform（333.333 vs 708.333 等）；
- 单次调用耗时两臂基本一致（≈18–21 s/帧）；总耗时 adaptive 在 4 个场景显著更低；
- 预算耗尽场景（reappear-adaptive-budget-6）：6/6 调用耗尽，3 个转换仍全部覆盖 GT（宽度 1333.334/1333.333/2625.0），`target_precision_reached=false` 如实报告；
- 多来源场景（共享预算 24）：14 次调用，全局时序证据生成，source_id/原时间戳/global=local+offset 保持，跨视频语义限制显示；
- **Verdict: IMPROVEMENT**（由真实指标计算，未预设）：两臂正确性一致；adaptive 边界定位全面不劣于 uniform 且调用数不高于 uniform 或达到目标精度。
- **小样本 + 单次运行 + 合成 fixture：不构成统计显著性，不得外推为真实仓储准确率。**

## 6. 如实记录的反常与限制

1. **abstain-zone fixture 未触发模型拒答**：真实 Qwen 对低对比度区间给出确定性负面（not_found，uniform 臂 3 帧），与 ground truth（存在）不一致——低对比度设计未达到触发 abstained/low_confidence 的程度，且模型倾向负面断言而非拒答。**未修改标签迁就模型输出**；该 fixture 的 abstained 语义由规则测试（构造证据）覆盖。
2. **adaptive 初始覆盖盲区**：abstain-zone 的 adaptive 臂 4 个初始采样点全部落在低对比度区间之外 → 0 转换、未发现该区间。这是策略的真实边界（初始网格密度决定盲区），已在 `known-limitations.md` 记录。
3. **reappear 预算耗尽**：3 个转换 × 3 轮细化超出 12 次预算，第 3 个边界停在 666.667ms（>500ms 目标）——预算耗尽被如实报告为"未达到目标精度"，不是"分析成功"。
4. uniform 臂 12/12 调用时 `budget_exhausted=true`（预算恰好用尽）但 `stop_reasons=[]`（uniform 无细化可停）——两个字段分别如实反映"预算耗尽"与"细化停止原因"。

## 7. DSH headless 自主会话（全新会话，真实自主编排）

- 会话：`dsh --profile headless "<任务文本>"`，08:54:05 → 09:00:44 UTC（399.2 s），exit 0；产物与 reasoning 流在 `artifacts/task-16/dsh-session/`。
- 会话内 Agent **自主**完成：加载全部三个 Skill（reasoning："load all three skills first since they're all relevant"）→ 媒体来源硬门 `check_source_media.py` → accepted/user_provided → 生成含 `sampling_strategy` 的 VisualTaskSpec（独立校验 RESULT: VALID）→ 运行 `trace_temporal.py`（4 初始覆盖 + 8 细化、3 轮、**12 次真实 Qwen 调用=预算，budget_exhausted=true**）→ `generate_report.py --mode temporal` 生成最终报告 → 自主撰写 SESSION-SUMMARY.md（含语义红线遵守声明）。
- 时序结论：confirmed 6 / not_found 6 / abstained 0 / low_confidence 0 / failed 0；3 个转换 [1666.667,2000] w333.333、[3666.667,4000] w333.333、[5958.333,6625] w666.667；目标精度 500ms **未达到**（第 3 边界预算耗尽，残存 666.667ms，如实报告）；首/末 confirmed 采样观察 0.0 / 5958.333 ms。
- 独立复算校验：报告引擎第二套实现复算与上游一致，无交叉校验 warning；调用计数与时间线条目一致（12=12，全部 real_model_output）。
- StepFun 实际职责：文本任务理解、规划、生成结构化 VisualTaskSpec（不读图；视觉 100% 本地 Qwen）。

## 8. 边界遵守

- 未新增第四个 Skill；未修改 Evidence Workbench（`app/` 与工作台脚本零变化，工作台测试 26/26 通过）；
- 未触碰用户 holdout；未使用真实行业视频做对照（fixture 明确标注 synthetic）；
- 未停止/重启 MiniMax-H3、Ollama、DSH；未安装依赖；未下载模型；**未联网**；未读取或输出任何凭据；
- 未修改 Tier-3 冻结任务集、v1/v2 评分器（SHA-256 核验一致）与 PASS 条件；任务 07/08/09 冻结 artifacts 零变化；
- 未把 OpenCV 写成核心创新；未把采样时间线写成实例追踪；未声称 ReID/目标跟踪/实时跟踪；
- 未伪造任何模型输出、ground truth、时间边界或性能数据；未删除失败样本。

## 9. 产物索引（artifacts/task-16/）

`test-results.json`（27/27）、`fixtures/`（manifest/ground-truth/SHA-256/videos）、`comparison.json`、`comparison.md`、`comparison/<场景>/<臂>/`（temporal-evidence.json + temporal-report.json + frames/ + raw/）、`dsh-session/`（task-prompt、visual-task-spec、temporal-evidence、final-report、frames/、raw/、两会话流、session-summary、资源门槛、Agent 自撰 SESSION-SUMMARY.md）、`resource-gate.json`、`known-limitations.md`、`verification.json`、`verify_task16.py`、`run-summary.md`（本文件）。
