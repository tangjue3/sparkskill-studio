# 公平比较 — task16-uniform-vs-adaptive-rescored

- 基线臂（arm_a）: `uniform`；候选臂（arm_b）: `adaptive`
- 样本: present-throughout, appear-midway, disappear-midway, reappear, abstain-zone

## Fairness gate

| 条件 | 通过 | 说明 |
| --- | --- | --- |
| same_sample_ids | 是 | 两臂样本集合与比较规格一致（5 个） |
| same_media_hash | 是 | 两臂媒体文件与 manifest 一致 |
| same_target_query | 是 | 两臂 target_query 一致: ['红色正方形'] |
| same_ground_truth_version | 是 | Ground Truth annotation_version 一致: ['1.0.0'] |
| same_model_and_backend | 是 | 模型/后端一致: ['modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest'] / ['ollama'] |
| same_call_budget | 是 | 两臂 configured_budget 一致: [12] |
| no_single_side_retry_or_extra_context | 是 | 调用方声明（不可从产物观测）: no_single_side_retry=True, no_extra_context=True; 依据: artifacts/task-16/comparison.json fairness 块：same_video/same_target_query/same_model/same_max_model_calls=12/no_single_side_retry=true/no_sample_removal=true/ground_truth_not_modified_after_results=true；两臂均为真实 Qwen 模型输出（evidence_nature=real_model_output），同一资源窗口 |
| prediction_input_complete | 是 | 两臂全部样本的预测输入完整且硬门通过 |
| same_evidence_nature | 是 | 两臂 evidence_nature 一致: ['real_model_output'] |
| ground_truth_not_revised_after_run | 是 | 全部样本 GT 无模型运行后修订 |

fairness gate 全部通过: True

## 指标对比（aggregate）

| 指标 | uniform（arm_a） | adaptive（arm_b） | Δ(adaptive−uniform) |
| --- | --- | --- | --- |
| correct_decisive | 57 | 34 | -23 |
| incorrect_decisive | 0 | 0 | 0 |
| abstention_on_determinate | 0 | 0 | 0 |
| failed_on_determinate | 0 | 0 | 0 |
| appropriate_abstention | 0 | 0 | 0 |
| overclaim_on_uncertain | 3 | 0 | -3 |
| failed_on_uncertain | 0 | 0 | 0 |
| denominator_analyzed_samples | 60 | 34 | -26 |
| gt_confirmed_segments | 7 | 7 | 0 |
| covered_confirmed_events | 7 | 7 | 0 |
| missed_confirmed_events | 0 | 0 | 0 |
| gt_boundaries_total | 7 | 7 | 0 |
| matched_boundaries | 5 | 5 | 0 |
| missed_gt_boundaries | 2 | 2 | 0 |
| unmatched_predicted_transitions | 2 | 0 | -2 |
| within_tolerance_boundaries | 5 | 4 | -1 |
| unreached_uncertain_segments | 0 | 1 | 1 |
| actual_model_calls | 60 | 34 | -26 |
| boundary_error_max_ms | 250.0 | 291.666 | 41.666 |
| boundary_error_min_ms | 54.167 | 33.333 | -20.834 |
| boundary_error_median_ms | 145.834 | 166.667 | 20.833 |
| boundary_error_mean_ms | 150.0 | 138.333 | -11.667 |
| boundary_error_matched_count | 5 | 5 | 0.0 |

## Verdict

**TRADEOFF** — 有严格改进（['fewer_model_calls', 'smaller_mean_boundary_error']）但非回归条件被违反（['more_unreached_uncertain_segments']）：省调用/缩边界的同时增加了漏检、过度断言或未触达 uncertain

- 严格更好项: ['fewer_model_calls', 'smaller_mean_boundary_error']
- 回归项: ['more_unreached_uncertain_segments']
- 非回归条件: {"incorrect_decisive_not_worse": true, "overclaim_on_uncertain_not_worse": true, "missed_confirmed_events_not_worse": true, "missed_gt_boundaries_not_worse": true, "unreached_uncertain_not_worse": false}

## 不得外推的声明

- 技术 fixture 小样本 + 单次运行：不构成统计显著性，不得外推为真实仓储/园区准确率；verdict 只反映本次冻结产物在严格 ground truth 口径下的对照结果

## 逐样本指标

| 样本 | uniform 正确 decisive | adaptive 正确 decisive | uniform overclaim | adaptive overclaim | uniform 调用 | adaptive 调用 | uniform 漏边界 | adaptive 漏边界 | uniform 未触达 uncertain | adaptive 未触达 uncertain |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| present-throughout | 12 | 4 | 0 | 0 | 12 | 4 | 0 | 0 | 0 | 0 |
| appear-midway | 12 | 7 | 0 | 0 | 12 | 7 | 0 | 0 | 0 | 0 |
| disappear-midway | 12 | 7 | 0 | 0 | 12 | 7 | 0 | 0 | 0 | 0 |
| reappear | 12 | 12 | 0 | 0 | 12 | 12 | 0 | 0 | 0 | 0 |
| abstain-zone | 9 | 4 | 3 | 0 | 12 | 4 | 2 | 2 | 0 | 1 |
