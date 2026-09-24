# 任务 18 三臂评测（replay；constructed_fixture_replay）

- 生成时间：2026-09-22T12:02:21.581311+00:00
- 证据性质：constructed_fixture_evidence
- **本评测使用合成技术 fixture，不是真实行业视频；结果不得外推为真实仓储准确率。**

## 公平性

- same_video: True
- same_target_query: 红色正方形
- same_model: 构造证据生成器（replay，非模型）
- same_status_rules: 同一 trace_temporal.py 代码路径与 frame_class 分类规则
- same_ground_truth: artifacts/task-18/contracts/ground-truth/（冻结）
- same_scorer: scripts/score_temporal_ground_truth.py（任务 17 冻结）+ scripts/task18_scorer_adapter.py（内存扩展策略白名单）
- same_timeout_s: 300
- execution_order: 场景按预注册 scenario_order；场景内臂顺序 uniform→adaptive→coverage
- no_single_side_retry: True
- no_sample_removal: True
- ground_truth_not_modified_after_results: True
- tier3_untouched: True

## 逐场景结果

### present-throughout（目标全程存在/无状态转换；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 4 | 7 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 0 | 0 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 0 | 0 | 0 |
| 最大边界宽度(ms) | None | None | None |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 12, 'not_found': 0, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 4, 'not_found': 0, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 7, 'not_found': 0, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

### appear-midway（中途出现；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 7 | 9 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 3 | 2 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 1 | 1 | 1 |
| 最大边界宽度(ms) | 708.333 | 333.333 | 333.333 |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 7, 'not_found': 5, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 4, 'not_found': 3, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 5, 'not_found': 4, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

### disappear-midway（中途消失；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 7 | 9 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 3 | 2 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 1 | 1 | 1 |
| 最大边界宽度(ms) | 708.334 | 333.333 | 333.333 |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 7, 'not_found': 5, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 4, 'not_found': 3, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 5, 'not_found': 4, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

### reappear（出现—消失—再次出现；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 12 | 12 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 8 | 5 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 1333.333 | 1333.333 |
| 状态转换数 | 3 | 3 | 3 |
| 最大边界宽度(ms) | 708.334 | 666.667 | 666.667 |
| 达到目标边界精度 | None | False | False |
| 耗尽预算 | True | True | True |
| 停止原因 | [] | ['budget_exhausted'] | ['coverage_gap_target_reached', 'budget_exhausted'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 6, 'not_found': 6, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 6, 'not_found': 6, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 6, 'not_found': 6, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

### short-event-between-grid（coarse 初始网格之间的短 confirmed 事件；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 4 | 11 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 0 | 4 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 2 | 0 | 2 |
| 最大边界宽度(ms) | 708.333 | None | 333.334 |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 1, 'not_found': 11, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 0, 'not_found': 4, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 2, 'not_found': 9, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

### short-uncertain-between-grid（coarse 初始网格之间的短 uncertain 区域；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 4 | 11 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 0 | 4 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 2 | 0 | 2 |
| 最大边界宽度(ms) | 708.333 | None | 333.334 |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 11, 'not_found': 0, 'abstained': 1, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 4, 'not_found': 0, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 9, 'not_found': 0, 'abstained': 2, 'low_confidence': 0, 'failed': 0}

### twin-short-events（两个间隔较短的事件；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 4 | 7 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 0 | 0 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 4 | 0 | 0 |
| 最大边界宽度(ms) | 708.334 | None | None |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 2, 'not_found': 10, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 0, 'not_found': 4, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 0, 'not_found': 7, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

### absent-throughout（无目标/无状态转换；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 4 | 7 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 0 | 0 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 0 | 0 | 0 |
| 最大边界宽度(ms) | None | None | None |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 0, 'not_found': 12, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 0, 'not_found': 4, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 0, 'not_found': 7, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

### short-event-phase-b（相位移动的短 confirmed 事件（对抗样本）；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 4 | 11 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 0 | 4 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 2 | 0 | 2 |
| 最大边界宽度(ms) | 708.334 | None | 333.334 |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 1, 'not_found': 11, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 0, 'not_found': 4, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 2, 'not_found': 9, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

### short-uncertain-phase-b（相位移动的短 uncertain 区域（对抗样本）；预算 12）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 12 | 4 | 11 |
| 初始覆盖调用 | 12 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 3 |
| 边界细化调用 | 0 | 0 | 4 |
| 最大相邻间隔初始(ms) | 708.334 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 708.334 | 2666.667 | 1333.334 |
| 状态转换数 | 2 | 0 | 2 |
| 最大边界宽度(ms) | 708.334 | None | 333.334 |
| 达到目标边界精度 | None | True | True |
| 耗尽预算 | True | False | False |
| 停止原因 | [] | ['no_refinable_interval'] | ['coverage_gap_target_reached', 'no_refinable_interval'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 11, 'not_found': 0, 'abstained': 1, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 4, 'not_found': 0, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 9, 'not_found': 0, 'abstained': 2, 'low_confidence': 0, 'failed': 0}

### reappear-tight-budget（预算不足以同时完成覆盖与全部边界细化；预算 6）

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 最终状态 | completed | completed | completed |
| 实际调用 | 6 | 6 | 6 |
| 初始覆盖调用 | 6 | 4 | 4 |
| 覆盖探索调用 | 0 | 0 | 2 |
| 边界细化调用 | 0 | 2 | 0 |
| 最大相邻间隔初始(ms) | 4500.0 | 2666.667 | 2666.667 |
| 最大相邻间隔最终(ms) | 4500.0 | 2625.0 | 2625.0 |
| 状态转换数 | 1 | 3 | 3 |
| 最大边界宽度(ms) | 666.666 | 2625.0 | 2625.0 |
| 达到目标边界精度 | None | False | False |
| 耗尽预算 | True | True | True |
| 停止原因 | [] | ['budget_exhausted'] | ['budget_exhausted'] |
| 证据性质 | constructed_fixture_evidence | constructed_fixture_evidence | constructed_fixture_evidence |
- uniform 五类计数：{'confirmed': 3, 'not_found': 3, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- adaptive 五类计数：{'confirmed': 4, 'not_found': 2, 'abstained': 0, 'low_confidence': 0, 'failed': 0}
- coverage 五类计数：{'confirmed': 4, 'not_found': 2, 'abstained': 0, 'low_confidence': 0, 'failed': 0}

## 两两 Verdict

### coverage-vs-uniform（baseline=uniform, candidate=coverage）

- fairness gate: 全部通过
- **verdict: TRADEOFF** — 有严格改进（['fewer_model_calls', 'smaller_max_boundary_error', 'smaller_mean_boundary_error']）但非回归条件被违反（['more_missed_confirmed_events', 'more_missed_gt_boundaries']）：省调用/缩边界的同时增加了漏检、过度断言或未触达 uncertain
- reason_codes: ['fewer_model_calls', 'smaller_max_boundary_error', 'smaller_mean_boundary_error', 'more_missed_confirmed_events', 'more_missed_gt_boundaries']

### coverage-vs-adaptive（baseline=adaptive, candidate=coverage）

- fairness gate: 全部通过
- **verdict: IMPROVEMENT** — 非回归条件全部满足，且至少一项严格更好（['smaller_mean_boundary_error', 'more_boundaries_within_tolerance']）
- reason_codes: ['smaller_mean_boundary_error', 'more_boundaries_within_tolerance']

### adaptive-vs-uniform（baseline=uniform, candidate=adaptive）

- fairness gate: 全部通过
- **verdict: TRADEOFF** — 有严格改进（['fewer_model_calls', 'smaller_max_boundary_error', 'smaller_mean_boundary_error']）但非回归条件被违反（['more_missed_confirmed_events', 'more_missed_gt_boundaries', 'more_unreached_uncertain_segments']）：省调用/缩边界的同时增加了漏检、过度断言或未触达 uncertain
- reason_codes: ['fewer_model_calls', 'smaller_max_boundary_error', 'smaller_mean_boundary_error', 'more_missed_confirmed_events', 'more_missed_gt_boundaries', 'more_unreached_uncertain_segments']

## Pack 级三臂 Verdict

**TRADEOFF** — 有严格改进（['smaller_mean_boundary_error_than_both']）但非回归条件被违反（['more_missed_confirmed_events_vs_uniform', 'more_missed_gt_boundaries_vs_uniform', 'larger_max_sampling_gap_vs_uniform']）：省调用/缩边界/缩间隔的同时增加了漏检、过度断言或未触达 uncertain

- reason_codes: ['smaller_mean_boundary_error_than_both', 'more_missed_confirmed_events_vs_uniform', 'more_missed_gt_boundaries_vs_uniform', 'larger_max_sampling_gap_vs_uniform']
- 最大相邻采样间隔（跨场景最大值）: {'adaptive': 2666.667, 'coverage': 1333.334, 'uniform': 708.334}

## 不得外推的声明

- 技术 fixture 小样本 + 单次运行：不构成统计显著性，不得外推为真实仓储/园区准确率；
- replay 为构造证据回放（零模型调用）；真实 Qwen 运行受模型非确定性影响；两者指标不混合平均；
- `completed`（execution_status）不等于语义正确；覆盖探索不保证发现任意短事件。
