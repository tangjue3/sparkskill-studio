# 目标时序证据与粗到细自适应采样参考（visual-evidence-extractor · 任务 16）

由 `scripts/trace_temporal.py`（执行器）与 `scripts/adaptive_sampler.py`（纯逻辑）产出，
报告由 evidence-report-generator 的 `scripts/generate_report.py --mode temporal`
（或 `--mode temporal-multi`，或 auto 判别）生成。
本参考定义 `sampling_strategy` 契约、采样 provenance、时序证据结构与语义红线。

## 1. 策略契约（VisualTaskSpec.sampling_strategy，可选，向后兼容）

Schema：项目根 `schemas/visual-task-spec.schema.json`；校验器：
`task-to-skill-compiler/scripts/validate_task_spec.py`（Schema 子集 + 语义组合规则）。

| 策略 | 必填字段 | 语义 |
| --- | --- | --- |
| （缺失） | — | 旧版 uniform 行为（`trace_video.py` 路径不变） |
| `uniform` | 仅可选 `max_model_calls` | 正式 baseline：固定间隔/均匀采样；带预算时截断并如实记录 |
| `adaptive_coarse_to_fine` | `max_model_calls`、`initial_coverage_samples`、`target_boundary_precision_ms`、`max_refinement_rounds` | 初始覆盖 + 二分细化；可选 `refinement_triggers`（缺省 state_change/abstained/low_confidence/failed 全开） |
| `coverage_aware_adaptive`（任务 18） | `max_model_calls`、`initial_coverage_samples`、`coverage_gap_target_ms`、`coverage_call_reserve`、`target_boundary_precision_ms`、`max_refinement_rounds` | 初始覆盖 + **时间覆盖探索**（largest-gap-first 压缩未观测间隔）+ 边界细化；同一硬预算内双职责；可选 `refinement_triggers` |

硬性规则（违反即拒绝，执行期与校验期同口径）：

- `max_model_calls` ∈ [1, 512] 整数；`target_boundary_precision_ms` > 0；
- adaptive 必填四字段齐全；`initial_coverage_samples <= max_model_calls`；
- coverage_aware_adaptive 必填六字段齐全；`initial_coverage_samples + coverage_call_reserve <= max_model_calls`（覆盖配置之和不得超出硬预算，边界细化至少保留调用空间）；
- `coverage_gap_target_ms` > 0（覆盖目标）；`coverage_call_reserve` 为正整数（覆盖调用储备；0/负数/非整数拒绝）；
- uniform 不接受任何细化参数与 coverage 专属字段；adaptive_coarse_to_fine 不接受 coverage 专属字段（不支持组合）；
- `require_sampling_provenance` / `require_temporal_evidence` 缺省 true。

## 2. 采样算法（adaptive_coarse_to_fine）

1. **初始覆盖**：在 `[start_ms, end_ms]`（默认整个视频）内均匀取 `initial_coverage_samples`
   个采样点（含端点；公式与 `extract_frames.plan_sample_times` 的 uniform 分支一致）。
2. **细化候选**：对相邻已分析采样对 `(left, right)`，当区间宽度 >
   `target_boundary_precision_ms` 且命中启用的触发器时成为候选：
   - `state_change`：两侧类别不同（定位状态边界）；
   - `abstained` / `low_confidence` / `failed`：任一侧是该类别（证据缺口邻域）。
   没有状态变化、没有拒答/低置信/失败样本时**不产生候选**（不做无意义细化）。
3. **细化执行**：每轮对所有候选区间取中点采样（二分查找边界），受预算与
   `max_refinement_rounds` 约束；中点命中已有帧（区间窄于单帧间隔）时记
   `skipped_duplicate`，不重复调用模型。
4. **停止原因**（`provenance.stop_reasons`，可多个）：`budget_exhausted`、
   `max_refinement_rounds_reached`、`target_precision_reached`、`no_refinable_interval`、
   `refinement_converged_no_new_sample`、`resource_blocked`。

uniform 策略：使用 `extract_frames.plan_sample_times` 的同一规划（interval 网格或
区间均匀），不做细化；带 `max_model_calls` 时采样计划截断到预算内并记录
`uniform_sampling_truncated_to_budget=true`。

### 2.1 覆盖探索算法（coverage_aware_adaptive，任务 18）

1. **观测点集**：已分析时间戳 + 媒体边界 `{0, duration_ms}`（升序去重）——初始覆盖被
   预算截断时，媒体边界与首/末采样之间的间隔同样是未观测区间；
2. **候选间隔**：宽度 > `coverage_gap_target_ms` 且未被排除的相邻间隔；
3. **确定性选择**：宽度最大；并列取 `left_ms` 最小；再并列取 `right_ms` 最小
   （纯函数 `next_coverage_candidate(gaps, target_ms, excluded)`，只依赖采样几何，
   **不读取 Ground Truth、fixture 文件名、预期结果或历史模型返回**）；
4. **执行**：对候选间隔取中点采样；中点命中已有帧（间隔已窄于帧分辨率）时记
   `skipped_duplicate` 并排除该间隔（不重复调用模型、不计入覆盖调用）；
5. **停止原因**（追加到 `provenance.stop_reasons`）：`coverage_gap_target_reached`、
   `coverage_reserve_exhausted`、`coverage_no_refinable_gap`、`budget_exhausted`、
   `resource_blocked`；
6. **职责分离**：覆盖探索不看证据类别（避免"没有信号就不探索"的结构性盲区）；
   边界细化不看间隔几何（任务 16 行为逐字节不变）；两者用不同 `phase`
   （`coverage_exploration` vs `refinement`）与 `purpose`
   （`temporal_coverage` vs `boundary_refinement`）在 provenance 中区分；
7. **多来源**：`coverage_call_reserve` 按来源分别生效（与 `initial_coverage_samples`
   一致），全局硬预算 `max_model_calls` 是最终上限。

## 3. 采样 provenance（sampling_provenance{}）

顶层字段：`strategy`、`configured_budget`、`actual_model_calls`、
`reused_evidence_count`、`budget_exhausted`、`initial_samples`、`refinement_samples`、
`refinement_rounds`、`uniform_sampling_truncated_to_budget`、`decisions[]`、
`analyzed_timestamps`、`skipped_duplicate_timestamps`、`stop_reasons`、
`resource_guard`、`resource_blocked`、`timing{extraction_ms, analysis_ms,
aggregation_ms, total_ms}`。

覆盖字段（任务 18；旧策略下覆盖调用为 0、目标为 None，结构保持一致）：

`initial_coverage_calls` / `coverage_exploration_calls` / `boundary_refinement_calls`
（三类新鲜调用数，之和 = `actual_model_calls`）、`coverage_call_reserve`、
`coverage_gap_target_ms`、`max_adjacent_sampling_gap_ms_initial` /
`max_adjacent_sampling_gap_ms_final`（最大相邻采样间隔的初始值与最终值；由
`(analyzed_timestamps, duration_ms)` 复算：观测点集 = 已分析时间戳 + 媒体边界）、
`underobserved_intervals`（结束时仍宽于覆盖目标的间隔清单 = 剩余盲区）、
`arbitrary_short_event_detection_guaranteed: false`、
`events_shorter_than_max_sampling_gap_may_be_missed: true`。

`decisions[]` 每项（每次采样决策可追溯）：

| 字段 | 说明 |
| --- | --- |
| `sample_index` / `timestamp_ms` | 决策序号与实际采样时间戳（真实帧序号推导） |
| `phase` | `initial_coverage`（初始覆盖）/ `coverage_exploration`（覆盖探索，任务 18）/ `refinement`（后续细化） |
| `purpose` | `initial_coverage` / `temporal_coverage`（覆盖探索）/ `boundary_refinement`（边界细化）——两类职责的显式区分 |
| `candidate_interval` | 覆盖探索时为被压缩的候选间隔 `{left_ms, right_ms}`（细化决策为 null；触发区间见 `trigger_interval`） |
| `refinement_round` | 第几轮细化（初始覆盖为 null） |
| `reason` | 为什么选择这个时间戳 |
| `trigger_interval` / `trigger_reason` | 由哪个候选时间区间触发（初始覆盖为 null） |
| `observed_states_at_decision` | 决策时已观察到的状态（类别对 / 已分析数） |
| `model_call_seq` | 第几次模型调用（未调用为 null） |
| `cache_status` | `fresh_call` / `skipped_duplicate` / `budget_blocked` / `resource_blocked` |
| `budget_state` | 决策时点的预算快照（上限/已用/剩余/是否耗尽） |

provenance 安全：产物落盘前做凭据自检（命中即拒绝输出）；不得记录或暴露凭据。

## 4. 时序证据（temporal_evidence{}）

| 字段 | 语义 |
| --- | --- |
| `first_confirmed_observed_ms` / `last_confirmed_observed_ms` | 首个/最后被观察为 confirmed 的**采样**时间（**不是**目标真实进入/离开时间） |
| `confirmed_sample_count` / `class_counts` | confirmed 采样数；confirmed/not_found/abstained/low_confidence/failed 五类计数（**不互相折算**） |
| `analyzed_sample_count` / `analyzed_ratio` | 有效分析采样数与比例 |
| `state_transitions[]` | 相邻采样类别变化：`{left_ms, right_ms, from_class, to_class, uncertainty_width_ms}` |
| `boundary_uncertainty{}` | `{target_ms, max_ms, min_ms, target_precision_reached, residual_uncertainty_ms}` |
| `evidence_supported_segments[]` | 相邻同类采样的最大连续段（只覆盖采样点自身，不断言段内连续事实） |
| `unconfirmed_intervals[]` | 任一侧不是确定性类别的相邻区间（无法确认的时间片段） |
| `stopped_by_budget` / `stop_reasons` | 是否因调用预算停止；停止原因列表 |
| `actual_model_calls` | 真实视觉调用次数（与 provenance 一致） |
| `semantics{}` | 语义红线结构化声明（随产物输出） |
| `coverage{}`（任务 18） | `max_adjacent_sampling_gap_ms_initial/final`、`coverage_gap_target_ms`、`coverage_calls`、`coverage_call_reserve`、`underobserved_intervals`、`arbitrary_short_event_detection_guaranteed: false`、`events_shorter_than_max_sampling_gap_may_be_missed: true`、`coverage_statement`（覆盖分辨率能/不能说明什么） |

## 5. 多来源时序证据

`source_media` 为来源对象数组时：每来源独立执行本链路（保留 `source_id` 与原视频
时间戳），复用 `trace_multi_video` 的合并规则生成 `global_timeline[]`
（`global_timestamp_ms = 原时间戳 + time_offset_ms`），并输出
`global_summary{}`、`global_temporal_evidence{}`、`shared_budget{}`
（**整个任务共享同一个 `max_model_calls` 硬预算**）与 `semantic_limitations{}`
（跨视频语义边界不变：全局时间线是证据聚合，不是跨摄像头身份追踪）。

## 6. evidence_nature（真实模型输出 vs 构造证据 vs 未调用）

timeline 每项与文档顶层都有 `evidence_nature`：

| 值 | 含义 |
| --- | --- |
| `real_model_output` | 真实 Qwen 视觉调用产生的证据 |
| `backend_call_failed` | 真实调用已发生但返回不合法/超时（计为一次真实调用，帧 failed） |
| `backend_not_called` | 未执行调用（资源守卫阻塞 / 构造分析器异常）——**不计为 Qwen 调用** |
| `constructed_fixture_evidence` | 规则级测试注入的构造证据（明确标注，非模型输出） |

文档顶层 `evidence_nature` 为汇总值；`input_nature` 标记输入是 `user_media` 还是
`technical_fixture`（合成技术 fixture 不得外推为真实行业素材结论）。

## 7. 资源守卫与失败降级

- 与任务 04/06 一致：调用视觉模型前检查 `/proc/meminfo` MemAvailable（默认阈值
  40 GiB），不足时不加载模型；**未执行的调用不计入真实视觉调用**，
  初始覆盖帧全部标记 failed 并记录真实原因，细化阶段整体跳过
  （`stop_reasons` 含 `resource_blocked`）；
- 单帧分析失败 → 该帧 failed（`backend_call_failed`），不中断其他帧；
- 预算耗尽 → 停止细化并如实报告，不用“分析成功”措辞。

## 8. 安全边界

- 语义红线见 `SKILL.md` “目标时序证据语义红线”节；
- provenance 不含凭据（落盘前自检）；
- technical fixture 与真实模型输出以 `evidence_nature` / `input_nature` 显式区分；
- OpenCV 仅作底层抽帧工具；不新增依赖。

## 9. Ground Truth 评分契约（任务 17，项目级工具，只读消费本产物）

`temporal-evidence.json`（本参考定义的结构）是项目级确定性评分器
`scripts/score_temporal_ground_truth.py` 的标准输入；评分器**只读**本产物、
**不修改**本产物、**不重新调用任何视觉模型**。契约与口径：

- 输入三分離：Evidence Pack manifest（`schemas/evidence-pack-manifest.schema.json`，
  媒体身份 + split + 来源 provenance，**不含时间真值**）、时间 Ground Truth
  （`schemas/temporal-ground-truth.schema.json`，显式独立输入）、prediction-set
  （引用本产物）；
- 硬门：sample ID / 媒体 SHA-256（实际计算）/ target query / 时长 / GT 时间线合法性 /
  时间戳范围 / provenance 自洽（`actual_model_calls` == fresh_call 决策数 == 时间线条目数、
  预算未超、`analyzed_timestamps` 与时间线一致、五类计数复算一致）/ 单来源形态；
- 语义评分：七类采样点计数（uncertain 上的拒答与过度断言分开；0 分母写 `not_applicable`）、
  confirmed event 覆盖、transition 一对一匹配（方向兼容：decisive→decisive 不得匹配涉及
  uncertain 的 GT 边界）、边界误差（容差来自 GT `boundary_tolerance_ms`）；
- 公平比较：uniform 与 adaptive 两臂的 `temporal-evidence.json` 经 fairness gate
  （相同样本/媒体/查询/GT 版本/模型后端/预算、无单侧重试、输入完整、同 evidence_nature、
  GT 无运行后修订）后计算 verdict（IMPROVEMENT / TRADEOFF / NO_IMPROVEMENT /
  INVALID_COMPARISON），不预设结果；
- 口径红线（评分器输出随附）：`execution_status=completed` 不等于语义正确；
  时序结论是采样证据支持的结论，不是连续跟踪真值；合成 fixture 不外推为真实准确率；
  用户 8 AI + 4 真实视频 Evidence Pack 上传前不得声称真实域评分已完成；
- 任务 16 冻结产物的重评分结论：`artifacts/task-17/comparison.json`
  （verdict=TRADEOFF，旧 `IMPROVEMENT` 为旧口径历史，未篡改）。
