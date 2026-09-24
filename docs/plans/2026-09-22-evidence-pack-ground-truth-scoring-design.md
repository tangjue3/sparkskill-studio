# 设计文档 — Evidence Pack 数据契约与时间 Ground Truth 评分器（任务 17）

- 日期：2026-09-22
- 状态：已实现并验证（新测试见 `artifacts/task-17/test-results.json`；Task 16 冻结产物重评分见 `artifacts/task-17/rescored-task16/`）
- 基线：分支 `master`，HEAD `8c962fccc3491bebbb265fd3c7df982a55f84ee1`，工作区干净，恢复 tag `pre-task13-deploy-4c4c3ca` 保留，无 remote
- 关联：`docs/plans/2026-09-22-temporal-evidence-adaptive-sampling-design.md`（任务 16）、`schemas/visual-task-spec.schema.json`、三个 Skill 的 `SKILL.md`、`artifacts/task-16/`

---

## 1. 问题

任务 16 已实现 uniform / adaptive_coarse_to_fine 采样、硬预算、采样 provenance 与时序证据，但留下五个必须正视的问题：

1. **`execution status=completed` 只表示流水线完成**，不代表语义结论正确（`summary.overall_status` 是聚合状态，不是逐样本真值判定）；
2. **abstain-zone 的真实 Qwen 输出是确定性负面**（低对比度区间 3 帧 `not_found`），与 fixture ground truth（该区间为不确定区）冲突——旧对照只记录了"最终状态正确"，没有逐采样点评分暴露这个冲突；
3. **adaptive 初始覆盖可能漏掉初始采样点之间的窄事件/窄不确定区**（abstain-zone adaptive 臂 4 个初始点全部落在不确定区之外，0 次细化）；
4. 任务 16 的 `IMPROVEMENT` 更接近"效率与已检测边界改进"（调用更少、边界更窄），**尚不能证明真实视频准确率全面提升**；
5. **用户的 8 段 AI 生成 + 4 段公开许可真实视频 Evidence Pack 尚未上传**——不能虚构路径、许可、标签或结果，但必须提供零改代码的接入方式。

本任务建立**独立、确定性、CPU-only** 的数据契约与 Ground Truth 评分器，把三个被混在一起的问题分开评价：

| 被混淆的问题 | 本任务的分离方式 |
| --- | --- |
| 流水线是否跑完 | `execution_status`（来自预测产物自报的聚合状态） |
| 证据语义是否正确 | `semantic_score_status` + 逐采样点/事件/边界的确定性计数 |
| 采样是否高效 | 效率指标（调用数、复用、耗时；**不能抵消语义错误**） |

## 2. 目标与非目标

**目标**（对应任务书第三节）：

1. Evidence Pack manifest 契约（版本化 JSON Schema，不含任何时间真值）；
2. 时间 Ground Truth 契约（版本化 JSON Schema，显式独立输入）；
3. Ground Truth 与媒体哈希冻结验证（硬门，评分前执行）；
4. Task 16 预测产物的确定性评分（消费 `temporal-evidence.json`，不调用任何模型）；
5. uniform 与 adaptive 的公平比较（fairness gate + 四类 verdict）；
6. dev 与 holdout 真值隔离协议；
7. 用冻结的 Task 16 产物重新评分（5 个场景 × 2 臂）；
8. 为未来 8 AI + 4 真实视频提供零改代码接入方式（competition profile）。

**非目标**（本任务明确不做）：

- 不调用任何模型（StepFun、Qwen、Ollama、MiniMax-H3、DSH headless 一律不调用）；
- 不抽帧、不生成视频、不下载素材、不修改工作台（`app/` 零变化）；
- 不创建第四个 Skill（评分器是项目级工具，与 `scripts/score_tier3_eval_v2.py` 同层）；
- 不接入或运行用户 holdout；不虚构媒体、许可、Prompt、标签或评分结果；
- 不做真实素材推理、自适应算法修复、演示录屏；
- 多来源（`global_timeline`）时序证据的逐样本评分（v1 不支持，结构化报错，见 §21）。

## 3. 总体架构

```
schemas/evidence-pack-manifest.schema.json   Evidence Pack 输入清单契约（无真值）
schemas/temporal-ground-truth.schema.json    时间 Ground Truth 契约（显式独立输入）
scripts/validate_evidence_pack.py            契约校验器（Schema 子集 + 语义规则 + profile）
scripts/score_temporal_ground_truth.py       评分器（硬门 + 采样点/事件/边界评分 + 公平比较）
scripts/test_temporal_ground_truth_scoring.py 测试（30+ 确定性用例）
artifacts/task-17/fixtures/                  确定性 JSON fixtures（由 build_fixtures.py 生成）
artifacts/task-17/contracts/                 Task 16 fixture 的 manifest/GT 派生与 competition profile 示例
artifacts/task-17/rescored-task16/           Task 16 冻结产物重评分输出
```

三个组件的依赖方向：`score_temporal_ground_truth.py` → 导入 `validate_evidence_pack.py` 的硬门函数（单一事实来源）→ 复用 `task-to-skill-compiler/scripts/validate_task_spec.py` 的 JSON Schema 子集校验器（仓库既有能力，不引入 `jsonschema` 依赖）。

**为什么不是第四个 Skill**：契约校验与真值评分是项目级评测基础设施（与 Tier-3 v2 评分器同层），不属于"编译 / 抽取 / 报告"任何一环的运行时职责；放入 Skill 会让 DSH catalog 出现语义模糊的能力单元，并违背任务 16 已确立的"三 Skill 边界"。

## 4. Manifest 与 Ground Truth 为什么分离

- **Manifest 是"有什么"**：样本清单、媒体身份（路径 + SHA-256 + 时长）、目标查询、来源 provenance、dev/holdout 划分、公开演示/公开 Git 许可。它**可以**随仓库公开，供第三方复算与审计。
- **Ground Truth 是"答案"**：逐样本的时间真值（区间 + 状态 + 容差 + 标注版本 + 修订历史）。它**可能敏感**（尤其 holdout），必须作为显式独立输入按 split 隔离分发。
- 分离的硬性规则：
  1. Manifest **不得内嵌**任何时间真值字段（Schema 层 `additionalProperties: false` + 校验器扫描 `segments`/`state`/`ground_truth` 等疑似真值键）；
  2. 评分器的 `--ground-truth` 是**必显参数**——缺省即结构化错误退出，禁止从 README、历史 artifacts、项目目录或文件名猜测真值，禁止自动寻找默认测试视频；
  3. holdout 的 Ground Truth 内容**不进入任何输出文件**（只进 SHA-256 摘要与段数，见 §7）；
  4. 比较输出（`comparison.json`/`comparison.md`）只含指标计数，不含任何 GT 区间内容。

## 5. Evidence Pack Manifest 契约

Schema：`schemas/evidence-pack-manifest.schema.json`（`$id: https://sparkskill.studio/schemas/evidence-pack-manifest.schema.json`，版本化，`additionalProperties: false` 严格字段纪律）。

顶层必填：`schema_version`、`pack_id`、`profile`、`created_at`、`frozen_at`、`samples[]`。

每个 sample 必填：

| 字段 | 规则 |
| --- | --- |
| `sample_id` | 全局唯一（校验器查重）；`^[a-z0-9][a-z0-9_-]{0,63}$` |
| `split` | `dev` \| `holdout` |
| `source_type` | `generated` \| `licensed_public` \| `technical_fixture` |
| `media_path` | 相对路径（相对 manifest 所在目录）；解析后必须在项目根内；禁 shell 元字符/敏感标记/系统敏感目录 |
| `media_sha256` | 64 位小写十六进制 |
| `media_duration_ms` | 正数 |
| `data_card` | 相对路径（数据卡，描述样本用途与性质） |
| `target_query` | 非空字符串（≤200） |
| `task_type` | `temporal_presence_evidence`（const） |
| `public_demo_allowed` | boolean（是否允许公开演示） |
| `raw_file_public_git_allowed` | boolean（是否允许原始文件进入公开 Git） |
| `source_provenance` | 对象；`source_type` 必须与 sample 一致；按来源类型的条件必填字段见下 |

条件必填（Schema 声明全部字段，条件要求在校验器中以确定性规则执行——与任务 16 `sampling_strategy` 的"Schema 管结构、校验器管组合语义"同一模式，错误信息可定位）：

- `generated`：`model_name`、`service_or_model_version`、`prompt_version_ref`、`attempt_id`、`generation_record_ref`；
- `licensed_public`：`original_page_url`、`author_or_uploader`、`license_name`、`official_license_url`、`license_evidence_ref`、`attribution_requirement`；
- `technical_fixture`：`fixture_generator_ref`、`generation_params_ref`、`freeze_record_ref`。

**不硬编码 12 个编号**：Schema 与校验器对任意 `sample_id` 可复用；`profile` 为自由字符串时只执行通用规则。当 `profile == "sparkskill-competition-2026"` 时额外执行 competition profile 校验：恰好 12 个样本、ID 集合 = 8 个 generated 样本 + 4 个 licensed_public 样本、dev 9 个（AI01–AI06 + WEB01–WEB03）/ holdout 3 个（HOLDOUT-G1–HOLDOUT-G2 + HOLDOUT-L1）、AI 8 个 generated / WEB 4 个 licensed_public、条件字段完整。示例见 `artifacts/task-17/contracts/competition-profile-example.json（内部留档的占位值契约示例；公开版以 `schemas/evidence-pack-manifest.schema.json` 的 profile 规则替代）`（占位媒体路径与占位哈希，明确标注"用户上传真实素材后必须替换"；**不虚构真实视频路径、许可、Prompt、标签或模型结果**）。

## 6. 时间 Ground Truth 契约

Schema：`schemas/temporal-ground-truth.schema.json`（版本化，每份 GT 一个文件，`sample_id` 单样本）。

必填：`schema_version`、`sample_id`、`media_sha256`、`media_duration_ms`、`target_query`、`annotation_version`、`annotated_at`、`annotator_id`（非敏感标识）、`boundary_tolerance_ms`（>0）、`segments[]`、`label_frozen{}`、`revision_history[]`、`notes`。

segment 必填：`start_ms`、`end_ms`、`state`（`confirmed` \| `not_found` \| `uncertain`）、可选 `reason`。

**时间线合法性规则**（校验器 `check_ground_truth_timeline` 确定性执行，任一违反即硬门失败）：

1. 按 `start_ms` 严格排序；
2. 完整覆盖 `[0, media_duration_ms]`（首段 `start_ms == 0`，末段 `end_ms == media_duration_ms`）；
3. 不重叠、不留空隙（相邻段 `left.end_ms == right.start_ms`）；
4. 每段长度为正（`end_ms > start_ms`）；
5. 相邻相同状态必须合并（相邻段状态不得相同）；
6. **区间判定规则**：普通段左闭右开 `[start_ms, end_ms)`，最后一段包含媒体终点（`end_ms == media_duration_ms` 处的采样归入最后一段）——与任务 16 fixture 的 `state_at` 规则一致；
7. GT 中**不得出现**模型预测字段、模型置信度或根据模型输出反推的标签（校验器扫描 `prediction`/`confidence`/`model` 等键并拒绝）。

**标签冻结与修订历史**：

- `label_frozen{frozen: bool, frozen_at, freeze_note}`：冻结后不得修改；
- `revision_history[]`：每项 `{from_version, to_version, revised_at, reason, after_model_run}`——`after_model_run=true` 表示修订发生在模型运行之后。评分器对这类样本记 warning；**公平比较中任一修订 `after_model_run=true` 即使 fairness gate 失败（`INVALID_COMPARISON`）**——"看到结果后修改 ground truth"破坏对照公平（任务 16 公平性纪律同款）。

## 7. dev/holdout 隔离协议

1. **分发隔离**：dev GT 可随公开产物引用；holdout GT 只由持票方显式传入 `--ground-truth`，不进入公开 manifest、不进公开 Git、不进任何输出文件；
2. **输出隔离**（评分器强制执行）：
   - `split=holdout` 的样本，score.json 中 `ground_truth` 节只写 `gt_sha256`、`gt_segment_count`、`gt_states_digest`（段状态序列的哈希）与 `holdout_gt_excluded: true`，**不写段边界、不写状态序列明文**；
   - `split=dev` 的样本写 GT 摘要（段数、状态序列、边界数），便于审计；
   - comparison.json/md 任何情况下都不含 GT 段内容；
3. **读取隔离**：评分器不读取 `--ground-truth` 之外的任何真值来源；不扫描目录找真值；
4. **manifest 隔离**：manifest 只有 split 标记，没有任何真值（§4）。

## 8. execution_status 与 semantic_score_status

| 字段 | 来源 | 取值 | 语义 |
| --- | --- | --- | --- |
| `execution_status` | 预测产物 `summary.overall_status` | `completed` \| `abstained` \| `failed` | **流水线是否跑完**。`completed` 不代表语义正确 |
| `semantic_score_status` | 评分器 | `scored` \| `not_applicable` \| `invalid_input` | **语义评分是否可算**：硬门全过且有已分析采样点 = `scored`；硬门失败 = `invalid_input`（附结构化错误，不算分）；时间线为空 = `not_applicable`（全部计数 0，全部比率 `not_applicable`） |

两者必须同时输出。任务 16 重评分将真实展示：10 个臂全部 `execution_status=completed`，而 abstain-zone 两臂的语义计数暴露冲突（§14）。

## 9. 输入安全硬门（评分前，任一失败即停止计分）

| 门 | 检查 |
| --- | --- |
| G1 样本一致 | sample_id 存在于 manifest 与 GT；prediction-set 引用的 evidence 存在且可解析 |
| G2 媒体冻结 | 媒体文件存在可读；计算 SHA-256 == manifest.media_sha256 == gt.media_sha256 |
| G3 查询一致 | manifest.target_query == gt.target_query == evidence.target_query |
| G4 时长一致 | manifest.media_duration_ms == gt.media_duration_ms == evidence.duration_ms（各四舍五入到 3 位小数后相等） |
| G5 GT 时间线合法 | §6 的 7 条规则 |
| G6 采样点在媒体范围内 | 所有 timeline 时间戳 ∈ [0, duration_ms] |
| G7 provenance 自洽 | actual_model_calls == fresh_call 决策数；非资源阻塞时 == 时间线条目数；资源阻塞时 == 0 且全部条目 `backend_not_called`；actual ≤ configured_budget；analyzed_timestamps == 排序去重后的时间线时间戳；评分器按任务 16 `classify_entry` 同规则复算的五类计数 == 产物自报 `temporal_evidence.class_counts`；strategy ∈ {uniform, adaptive_coarse_to_fine} |
| G8 预测形态受支持 | evidence 为单来源文档（含顶层 `timeline`）；多来源 `global_timeline` 文档返回 `unsupported_prediction_shape` 结构化错误（v1 已知限制） |

硬门失败时：该样本 `semantic_score_status=invalid_input`，输出结构化错误（错误码 + 定位 + 期望/实际），**不计算任何分数**；整次运行以退出码 1 结束（用法/IO 错误为退出码 2，与仓库既有脚本一致）。

## 10. 时间状态区间语义与采样点评分规则

GT 状态：`confirmed`（确定存在）/ `not_found`（确定不存在）/ `uncertain`（无法可靠判定）。预测类别（任务 16 五态，由时间线条目按 `classify_entry` 同规则复算）：`confirmed` / `not_found` / `abstained` / `low_confidence` / `failed`。判定类别归属的规则与 `adaptive_sampler.classify_entry` 逐条一致（`frame_status != analyzed → failed`；`object_found=true → confirmed/low_confidence(按 evidence_sufficient)`；有 `abstention_reason → abstained`；否则 `not_found`），评分器内置同规则实现，与 Skill 代码的规则一致性由测试断言（不让评分器在运行期依赖 Skill 代码，保证评分确定性不受 Skill 演进影响）。

**对每个已分析时间戳**（分母 = 时间线条目数，含 failed——failed 是采样点上的真实结果，不是缺失数据），按 GT 段落定计数：

| GT 状态 | prediction | 计数 |
| --- | --- | --- |
| confirmed / not_found（determinate） | 相同确定状态 | `correct_decisive` |
| determinate | 相反确定状态 | `incorrect_decisive` |
| determinate | abstained / low_confidence | `abstention_on_determinate` |
| determinate | failed | `failed_on_determinate` |
| uncertain | abstained / low_confidence | `appropriate_abstention` |
| uncertain | confirmed / not_found | `overclaim_on_uncertain` |
| uncertain | failed | `failed_on_uncertain` |

输出每项原始计数 + 该项的分母与全局分母：**每项比率的分母取对应类别分母**（四个 determinate 指标用 determinate 采样点数，三个 uncertain 指标用 uncertain 采样点数），同时输出全局分母（已分析采样点数）与两个类别分母字段。**分母为 0 时该比率写字符串 `not_applicable`，不得写 100%**。比率四舍五入到 6 位小数；毫秒值 3 位小数。

**不得**把 `completed`、报告已生成或执行无异常计为语义正确——语义正确只由上表七类计数定义。

## 11. uncertain 区域的评价

- uncertain 段内的 `abstained`/`low_confidence` 是**正确行为**（`appropriate_abstention`）；
- uncertain 段内的 `confirmed`/`not_found` 是**过度断言**（`overclaim_on_uncertain`）——任务 16 abstain-zone 的真实 Qwen 确定性负面正落在此类；
- uncertain 段内 `failed` 单列 `failed_on_uncertain`（既不算拒答正确，也不算过度断言）；
- **未被任何采样点触达的 uncertain 段**单列 `unreached_uncertain_segments`（覆盖缺口，不计入过度断言，但进入公平比较的非回归条件）——adaptive 初始覆盖盲区由此量化；
- 每个 uncertain 段输出 `appropriate_abstention_achieved`（是否至少一次适当拒答）与 `reached`（是否有采样点）。

## 12. confirmed event 覆盖与 transition/boundary 评分

**事件覆盖**：

1. GT confirmed segment 总数；
2. 被 ≥1 个正确 confirmed 采样点覆盖的 confirmed segment 数（`covered_confirmed_events`）；
3. 漏掉的 confirmed segment 数（`missed_confirmed_events`，含窄事件完全漏检）；
4. GT not_found segment 覆盖（同规则，`covered_not_found_segments` / `missed_not_found_segments`）；
5. 每个 uncertain 段：`reached`、`appropriate_abstention_achieved`；
6. `unreached_uncertain_segments`。

**边界匹配**（GT 边界 = 相邻段的状态变化点，取右段 `start_ms`；含涉及 uncertain 的边界）：

- 候选预测 transition 来自产物 `temporal_evidence.state_transitions[]`（`{left_ms, right_ms, from_class, to_class, uncertainty_width_ms}`）；
- **方向兼容规则**（确定性）：GT 侧状态为 confirmed/not_found 时，预测侧类别必须映射到同一确定状态；GT 侧状态为 uncertain 时，预测侧类别必须是非确定类（abstained/low_confidence/failed）。**decisive→decisive 的预测 transition 不得匹配任何涉及 uncertain 的 GT 边界**——不能把整个 uncertain 区域伪装成精确进入/离开时刻；matched 的 uncertain 过渡必须由预测侧的非确定类别承接；
- **括号包含规则**：预测 transition 的 `[left_ms, right_ms]` 必须包含 GT 边界时刻（`left_ms <= b <= right_ms`）；
- **一对一匹配**：Kuhn 增广路最大二分匹配（GT 边界按时间排序、候选按 `(uncertainty_width_ms, left_ms, 原文索引)` 排序后确定性执行，结果可复算）；
- 输出：GT 边界总数、匹配数（`matched_boundaries`）、漏掉的 GT 边界数（`missed_gt_boundaries`）、未匹配的额外预测 transition 数（`unmatched_predicted_transitions`）、每个匹配边界的 bracket width 与 midpoint 绝对误差（`|midpoint - b|`）、容差内边界数（误差 ≤ `boundary_tolerance_ms`）、最大/最小/中位/平均边界误差（**保留原始分母**：匹配数；中位数对偶数个取中间两值平均）；
- 匹配数为 0 时，误差统计写 `not_applicable`（分母为 0 不得造数）。

## 13. 效率指标（不抵消语义错误）

来自产物 `sampling_provenance` 与评分结果：`configured_budget`、`actual_model_calls`、`unique_analyzed_timestamps`、`reused_evidence_count`、`duplicate_skips`、`budget_exhausted`、`timing{extraction_ms, analysis_ms, aggregation_ms, total_ms}`，以及三个派生指标（分母为 0 时 `not_applicable`）：

- `calls_per_correct_decisive_sample = actual_model_calls / correct_decisive`；
- `calls_per_covered_confirmed_event = actual_model_calls / covered_confirmed_events`；
- `calls_per_matched_boundary = actual_model_calls / matched_boundaries`。

同时输出 `evidence_nature`（`real_model_output` / `constructed_fixture_evidence` / `resource_blocked`），**调用少不等于效果好**：效率只在 verdict 的"至少一项严格更好"中作为候选条件，且必须通过 §12 的非回归条件。

## 14. uniform 与 adaptive 公平比较

**Fairness gate**（比较前逐项检查，任一失败 → `INVALID_COMPARISON`，不算分）：

| 条件 | 可观测性 |
| --- | --- |
| 相同 sample ID 集合 |  Observable（prediction-set 两臂覆盖一致） |
| 相同媒体哈希 | Observable（同一 manifest 样本；evidence.source_video 解析后的真实路径与 manifest 媒体路径一致） |
| 相同 target query | Observable（evidence.target_query） |
| 相同 Ground Truth 版本 | Observable（同一 GT 文件哈希 + `annotation_version`） |
| 相同模型与后端 | Observable（`backend.model` + `backend.vision_backend`） |
| 相同调用预算 | Observable（`provenance.configured_budget`） |
| 没有单侧重试或额外上下文 | **不可从产物观测**：由比较输入文件中的 `fairness_attestation` 显式声明（含声明依据文本），评分器记录声明值并纳入 gate；虚假声明的后果由调用方承担 |
| prediction 输入完整 | Observable（每样本两臂 evidence 均存在且硬门全过） |
| 相同 evidence_nature | Observable（两臂同为真实模型输出或同为构造证据，防止"一臂真调用一臂构造"的伪比较） |
| GT 未在模型运行后修订 | Observable（`revision_history[].after_model_run` 全为 false） |

**Verdict 判定**（只有四种，确定性计算，不预设任务 16 的结果）：

- `INVALID_COMPARISON`：fairness gate 任一条件失败；
- 非回归条件（全部满足才可能 IMPROVEMENT）：
  1. adaptive `incorrect_decisive` ≤ uniform；
  2. adaptive `overclaim_on_uncertain` ≤ uniform；
  3. adaptive `missed_confirmed_events` ≤ uniform；
  4. adaptive `missed_gt_boundaries` ≤ uniform；
  5. adaptive `unreached_uncertain_segments` ≤ uniform；
- 严格更好条件（至少一项）：
  1. adaptive 总调用数 < uniform；
  2. 两臂匹配边界数均 ≥1 且 adaptive 最大边界误差 < uniform；
  3. 两臂匹配边界数均 ≥1 且 adaptive 平均边界误差 < uniform；
  4. adaptive 容差内边界数 > uniform；
- 判定矩阵：

| 非回归条件 | 严格更好 | Verdict |
| --- | --- | --- |
| 全部满足 | 至少一项 | `IMPROVEMENT` |
| 全部满足 | 无 | `NO_IMPROVEMENT` |
| 有违反 | 至少一项 | `TRADEOFF`（省调用/缩边界但增加漏检、过度断言或未触达 uncertain） |
| 有违反 | 无 | `NO_IMPROVEMENT`（**不表示两臂等价**——违反项全部进入 reason codes 与差异字段完整披露） |

verdict 附 `reason_codes`（如 `fewer_model_calls`、`worse_missed_boundaries`、`unreached_uncertain_regression` 等），以及"不得外推"声明（技术 fixture 小样本、单次运行、非确定性）。

## 15. 媒体哈希、标签冻结与修订历史

- **媒体哈希冻结**：manifest 声明 `media_sha256`；评分器硬门 G2 计算实际文件哈希并三方一致（manifest / GT / 实际文件）。哈希不一致 → `invalid_input`，继续算分没有意义；
- **标签冻结**：GT `label_frozen.frozen=true` 后不可修改；任务 17 从任务 16 冻结 GT 派生的新契约 GT 记录派生来源（`derived_from` + 源冻结时间），派生脚本 `artifacts/task-17/contracts/build-task16-ground-truth.py` 只读源文件、确定性输出；
- **修订历史**：`revision_history[]` 保留原版本、原因、时间、`after_model_run`；运行后修订 → 单样本 warning + 比较 `INVALID_COMPARISON`（§6）。

## 16. 输入错误、缺失数据与空分母

- **输入错误**：结构化错误 `{error_code, location, expected, actual, message}`；错误码示例：`missing_required_argument`、`unreadable_input`、`invalid_json`、`sample_id_mismatch`、`media_hash_mismatch`、`duration_mismatch`、`target_query_mismatch`、`gt_timeline_overlap`、`gt_timeline_gap`、`gt_timeline_unmerged`、`gt_timeline_incomplete_coverage`、`prediction_timestamp_out_of_range`、`provenance_inconsistent`、`unsupported_prediction_shape`、`missing_ground_truth_for_sample`；
- **缺失数据**：缺 `--ground-truth` → 退出码 2 + `missing_required_argument`（**禁止**自动寻找默认测试视频或从目录/README 猜测）；manifest 中样本缺 GT → 该样本 `invalid_input`（比较中该样本两臂均无法评 → fairness gate 的"输入完整"失败）；
- **空分母**：任何比率/派生指标分母为 0 → 值写字符串 `not_applicable`，同时保留原始计数与分母字段；空时间线 → `semantic_score_status=not_applicable`。

## 17. 不读取或泄露 holdout 真值的约束

- 不读取 `--ground-truth` 之外的任何真值；不从文件名/目录/历史产物推断 holdout 内容；
- holdout GT 内容不进任何输出（§7）；输出中不出现用户绝对路径、凭据、无关系统信息（所有路径以仓库相对路径表达，内容只有哈希与指标）；
- 比较输出不含 GT 段内容；
- 评分器产物落盘前做凭据样式自检（命中即拒绝输出，与任务 16 provenance 自检同款）。

## 18. 与 Task 16 输出的兼容方式

- 评分器**只读** `temporal-evidence.json`（schema 1.3.0 单来源文档）：`timeline[]`、`sampling_provenance{}`、`temporal_evidence{}`、`summary{}`、`backend{}`、`target_query`、`duration_ms`、`sampling_strategy`；
- 不修改 `artifacts/task-16/` 任何文件；重评分通过 `artifacts/task-17/rescored-task16/prediction-set.json` 以**相对路径引用**冻结产物（`../../task-16/comparison/<场景>/<臂>/temporal-evidence.json`）；
- Task 16 的 fixture GT（`present`/`absent`/`present_low_contrast`）由派生脚本映射为新契约状态（`confirmed`/`not_found`/`uncertain`），映射关系记录在 GT 的 `label_frozen.derivation` 中；**不修改源 GT**；
- 任务 16 的 `state_transitions`、`class_counts`、provenance 计数被评分器复算校验（G7），不是被盲目信任；
- 多来源文档（`global_timeline`）v1 不支持（结构化错误 + 已知限制），任务 16 的 multi-source-pair 场景不在重评分范围（任务书要求 5 个单视频场景）。

## 19. 测试与回归范围

**新测试**（`scripts/test_temporal_ground_truth_scoring.py`，确定性 JSON fixtures 由 `artifacts/task-17/fixtures/build_fixtures.py（fixtures 生成器，内部留档；公开版只收录生成的 t01-t29+t28b fixture）` 生成并提交，测试断言具体字段与具体计数——不止断言退出码）：任务书第十五节 30 类用例（完全正确/错误断言/uncertain 拒答/两类过度断言/determinate 拒答/failed/事件覆盖/窄事件漏检/窄 uncertain 未触达/容差内边界/容差外边界/方向不兼容/多余 transition/GT 重叠/GT 空隙/相邻未合并/duration 不一致/哈希不一致/sample ID 不一致/缺 GT 参数/四类 verdict/空分母 not_applicable/holdout GT 不进公开输出/competition profile 合规与负向），另加：评分器分类规则与 `adaptive_sampler.classify_entry` 在全部冻结 Task 16 时间线上一致、评分器确定性（同输入两次运行输出逐字节相同）。

**回归**（任务书第十八节）：Task 16 时序证据测试、Task 04 视频规则测试、Task 06 多视频规则测试、M1–M8 媒体来源契约、v2 评分器回归、工作台静态测试、`git diff --check`、敏感信息扫描。冻结零改动确认：`artifacts/task-07|08|09|16/`、`evals/tier3/evals.json`、Tier-3 v1/v2 评分器与 PASS 条件、`app/` 与工作台脚本、Task 16 sampler/executor/原始 comparison 数据。

## 20. 产物与复现入口

```bash
# 契约校验（manifest + ground truth）
python3 scripts/validate_evidence_pack.py --manifest <m.json> --ground-truth <gt.json 或目录>

# 评分 + 公平比较（全部显式参数；--comparison 可选）
python3 scripts/score_temporal_ground_truth.py \
    --manifest artifacts/task-17/contracts/task16-fixture-evidence-pack-manifest.json \
    --predictions artifacts/task-17/rescored-task16/prediction-set.json \
    --ground-truth artifacts/task-17/contracts/ground-truth \
    --comparison artifacts/task-17/rescored-task16/comparison-spec.json \
    --out artifacts/task-17/rescored-task16

# 测试（30+ 用例，无模型调用）
python3 scripts/test_temporal_ground_truth_scoring.py

# 交付前验证
python3 artifacts/task-17/verify_task17.py（依赖 holdout 同名 fixture，内部留档；公开版以 test_temporal_ground_truth_scoring.py 覆盖）
```

Task 17 artifacts：`contracts/`（manifest、GT 派生脚本与 5 份 GT、数据卡、competition profile 示例）、`fixtures/`（确定性测试 fixtures + 生成器 + README）、`rescored-task16/`（prediction-set、comparison-spec、10 个臂的 score.json/score.md/input-hashes.json、comparison.json/comparison.md）、`test-results.json`、`comparison.json`、`comparison.md`（rescored-task16 的副本，SHA-256 相同）、`run-summary.md`、`verification.json`、`verify_task17.py`。

**确定性约定**：输出不含墙钟时间戳/主机名/绝对路径；同一输入永远得到逐字节相同的输出；排序稳定（时间戳 → sample_id → arm_id）；浮点舍入：毫秒 3 位、比率 6 位、均值 3 位；中位数偶数取中间两值平均。

## 21. 非目标与已知限制

1. **多来源时序证据评分未实现**（v1 结构化报错 `unsupported_prediction_shape`）——`global_timeline` 的偏移时间轴与逐样本 GT 的对齐语义需要单独设计，不在本任务范围；
2. **技术 fixture 不是真实素材**：Task 16 的 5 段合成视频重评分只验证评分器与方法论，**不得外推为真实仓储/园区准确率**；
3. **小样本 + 单次运行**：每场景每臂一次运行；不构成统计显著性；
4. 公平比较中"没有单侧重试或额外上下文"依赖调用方声明（fairness_attestation），不可从产物观测；
5. `abstain-zone` 的低对比度设计**未触发**真实 Qwen 拒答（确定性负面）——这是任务 16 已如实记录的反常，本任务在新口径下把它计为 `overclaim_on_uncertain`，**不修改任何标签迁就模型输出**；
6. 用户的 8 AI + 4 真实视频 Evidence Pack **尚未上传**：competition profile 示例只验证契约与编号/split/来源合规，**不得声称真实域评分已完成**；
7. 评分器不修复 adaptive 初始覆盖盲区（那是算法问题，留给后续独立任务）；本任务只量化它（`unreached_uncertain_segments`）。
