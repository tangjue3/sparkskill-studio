# Task 19B 三范围 verdict 汇总

- 生成时间：2026-09-23T01:03:28.400073+00:00
- 评分器：scripts/score_temporal_ground_truth.py（任务 17 冻结，零改动）
- 适配层：scripts/task18_scorer_adapter.py（任务 18 已提交适配层，零改动）
- **licensed-public 轨道只有三段：小样本真实域观察，不得外推为真实仓储准确率、统计显著性 or 生产可用性。**

## 公平门口径（多查询/多预算包）

冻结双臂公平门的 same_target_query / same_call_budget 条件在实现上要求比较范围内取值唯一。本包按预注册预算政策跨样本预算不同（12×7、WEB01=19、WEB03=18）且 licensed-public 轨道有三个 target query：generated 范围（查询与预算同质）十条件全部通过；licensed-public 与 all-dev 范围该两条件在冻结实现下 FAIL（判 INVALID_COMPARISON，如实保留）。逐样本公平门（同查询/同预算在样本内成立）见 scores/per-sample/；pooled pairwise verdict 用冻结 compute_verdict 对汇总指标计算（纪律不变），与逐样本门证据并列披露。

逐样本公平门（九样本 × 三对）全部通过：是

## 范围 generated（6 样本）

### 冻结适配层 pairwise（公平门十条件）

- coverage-vs-uniform: fairness_gate=PASS verdict=**TRADEOFF** reason_codes=['fewer_model_calls', 'more_incorrect_decisive']
- coverage-vs-adaptive: fairness_gate=PASS verdict=**NO_IMPROVEMENT** reason_codes=['more_overclaim_on_uncertain']
- adaptive-vs-uniform: fairness_gate=PASS verdict=**TRADEOFF** reason_codes=['fewer_model_calls', 'more_incorrect_decisive']

### pooled pairwise verdict（冻结 compute_verdict 对汇总指标）

- coverage-vs-uniform: **TRADEOFF** — 有严格改进（['fewer_model_calls']）但非回归条件被违反（['more_incorrect_decisive']）：省调用/缩边界的同时增加了漏检、过度断言或未触达 uncertain
- coverage-vs-adaptive: **NO_IMPROVEMENT** — 没有严格改进，且非回归条件被违反（['more_overclaim_on_uncertain']）；NO_IMPROVEMENT 不表示两臂等价，违反项已在差异字段完整披露
- adaptive-vs-uniform: **TRADEOFF** — 有严格改进（['fewer_model_calls']）但非回归条件被违反（['more_incorrect_decisive']）：省调用/缩边界的同时增加了漏检、过度断言或未触达 uncertain

### pack 级 verdict

- **NO_IMPROVEMENT** reason_codes=['more_incorrect_decisive_vs_uniform', 'larger_max_sampling_gap_vs_uniform', 'more_overclaim_on_uncertain_vs_adaptive']
- 最大相邻采样间隔（跨样本最大值，按臂）: {'adaptive': 3375.0, 'coverage': 1708.333, 'uniform': 958.334}

## 范围 licensed-public（3 样本）

### 冻结适配层 pairwise（公平门十条件）

- coverage-vs-uniform: fairness_gate=FAIL(same_target_query,same_call_budget) verdict=**INVALID_COMPARISON** reason_codes=['fairness_gate_failed']
- coverage-vs-adaptive: fairness_gate=FAIL(same_target_query,same_call_budget) verdict=**INVALID_COMPARISON** reason_codes=['fairness_gate_failed']
- adaptive-vs-uniform: fairness_gate=FAIL(same_target_query,same_call_budget) verdict=**INVALID_COMPARISON** reason_codes=['fairness_gate_failed']

### pooled pairwise verdict（冻结 compute_verdict 对汇总指标）

- coverage-vs-uniform: **IMPROVEMENT** — 非回归条件全部满足，且至少一项严格更好（['fewer_model_calls']）
- coverage-vs-adaptive: **NO_IMPROVEMENT** — 没有严格改进，且非回归条件被违反（['more_incorrect_decisive']）；NO_IMPROVEMENT 不表示两臂等价，违反项已在差异字段完整披露
- adaptive-vs-uniform: **IMPROVEMENT** — 非回归条件全部满足，且至少一项严格更好（['fewer_model_calls']）

### pack 级 verdict

- **NO_IMPROVEMENT** reason_codes=['larger_max_sampling_gap_vs_uniform', 'more_incorrect_decisive_vs_adaptive']
- 最大相邻采样间隔（跨样本最大值，按臂）: {'adaptive': 6206.2, 'coverage': 3103.1, 'uniform': 1040.0}

## 范围 all-dev（9 样本）

### 冻结适配层 pairwise（公平门十条件）

- coverage-vs-uniform: fairness_gate=FAIL(same_target_query,same_call_budget) verdict=**INVALID_COMPARISON** reason_codes=['fairness_gate_failed']
- coverage-vs-adaptive: fairness_gate=FAIL(same_target_query,same_call_budget) verdict=**INVALID_COMPARISON** reason_codes=['fairness_gate_failed']
- adaptive-vs-uniform: fairness_gate=FAIL(same_target_query,same_call_budget) verdict=**INVALID_COMPARISON** reason_codes=['fairness_gate_failed']

### pooled pairwise verdict（冻结 compute_verdict 对汇总指标）

- coverage-vs-uniform: **IMPROVEMENT** — 非回归条件全部满足，且至少一项严格更好（['fewer_model_calls']）
- coverage-vs-adaptive: **NO_IMPROVEMENT** — 没有严格改进，且非回归条件被违反（['more_incorrect_decisive', 'more_overclaim_on_uncertain']）；NO_IMPROVEMENT 不表示两臂等价，违反项已在差异字段完整披露
- adaptive-vs-uniform: **IMPROVEMENT** — 非回归条件全部满足，且至少一项严格更好（['fewer_model_calls']）

### pack 级 verdict

- **NO_IMPROVEMENT** reason_codes=['larger_max_sampling_gap_vs_uniform', 'more_incorrect_decisive_vs_adaptive', 'more_overclaim_on_uncertain_vs_adaptive']
- 最大相邻采样间隔（跨样本最大值，按臂）: {'adaptive': 6206.2, 'coverage': 3103.1, 'uniform': 1040.0}

## 逐样本公平门与 pairwise verdict

| 样本 | coverage-vs-uniform | coverage-vs-adaptive | adaptive-vs-uniform |
| --- | --- | --- | --- |
| AI01 | PASS / TRADEOFF | PASS / NO_IMPROVEMENT | PASS / TRADEOFF |
| AI02 | PASS / TRADEOFF | PASS / NO_IMPROVEMENT | PASS / TRADEOFF |
| AI03 | PASS / IMPROVEMENT | PASS / NO_IMPROVEMENT | PASS / IMPROVEMENT |
| AI04 | PASS / IMPROVEMENT | PASS / NO_IMPROVEMENT | PASS / IMPROVEMENT |
| AI05 | PASS / IMPROVEMENT | PASS / NO_IMPROVEMENT | PASS / IMPROVEMENT |
| AI06 | PASS / IMPROVEMENT | PASS / NO_IMPROVEMENT | PASS / IMPROVEMENT |
| WEB01 | PASS / IMPROVEMENT | PASS / NO_IMPROVEMENT | PASS / IMPROVEMENT |
| WEB02 | PASS / IMPROVEMENT | PASS / NO_IMPROVEMENT | PASS / IMPROVEMENT |
| WEB03 | PASS / TRADEOFF | PASS / NO_IMPROVEMENT | PASS / IMPROVEMENT |

## 不得外推的声明

- 小样本 + 单次运行：不构成统计显著性；generated 轨道为 MiniMax-H3 生成受控测试视频，licensed-public 轨道为 Pexels 真实素材小样本观察；
- 真实 Qwen 运行受模型非确定性影响；效率指标（调用/耗时/间隔）不能抵消语义错误；
- `completed`（execution_status）不等于语义正确；覆盖探索不保证发现任意短事件。
