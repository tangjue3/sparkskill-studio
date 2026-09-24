# 语义评分 — short-uncertain-phase-b / coverage

- pack sample: `short-uncertain-phase-b`（split=dev, source_type=technical_fixture）
- **execution_status**: `completed`（流水线是否完成）
- **semantic_score_status**: `scored`（语义评分是否可算；completed ≠ 语义正确）
- 预测策略: `coverage_aware_adaptive`；evidence_nature: `constructed_fixture_evidence`；采样点: 11

## 输入验证（硬门）

| 门 | 通过 | 说明 |
| --- | --- | --- |
| G1-sample-identity | 是 | evidence.target_query 存在且非空 |
| G2-media-hash-freeze | 是 | 媒体 SHA-256 三方一致（manifest/GT/实际文件）: ba3b9e928d4c839d… |
| G3-target-query | 是 | target_query 三方一致（manifest/GT/evidence） |
| G4-media-duration | 是 | 媒体时长一致（manifest/GT/evidence）: 8000.0 ms |
| G5-ground-truth-timeline | 是 | GT 时间线合法（排序/覆盖/不重叠/不留隙/正长度/相邻合并） |
| G6-prediction-timestamps-in-range | 是 | 全部 11 个采样时间戳位于 [0, 8000.0] ms |
| G7-provenance-self-consistency | 是 | provenance 自洽（调用数=新鲜调用=时间线条目；预算未超；时间戳集合一致；五类计数复算一致） |
| G8-prediction-shape | 是 | 单来源时序证据文档（顶层 timeline） |

## 采样点语义评分

- 分母（已分析采样点）: 11（determinate 9 / uncertain 2）

| 指标 | 通过 | 总数 | 比率 |
| --- | --- | --- | --- |
| correct_decisive | 9 | 9 | 1.0 |
| incorrect_decisive | 0 | 9 | 0.0 |
| abstention_on_determinate | 0 | 9 | 0.0 |
| failed_on_determinate | 0 | 9 | 0.0 |
| appropriate_abstention | 2 | 2 | 1.0 |
| overclaim_on_uncertain | 0 | 2 | 0.0 |
| failed_on_uncertain | 0 | 2 | 0.0 |

## 事件覆盖

- GT confirmed segments: 2；覆盖: 2；漏掉: 0
- GT not_found segments: 0；覆盖: 0；漏掉: 0
- GT uncertain segments: 1；未触达: 0
  - [6200.0, 6800.0] ms：reached=True，appropriate_abstention=True，段内采样点=2

## 状态转换与边界

- GT 边界总数: 2；匹配: 2；漏掉: 0；多余预测 transition: 0
- 容差（250.0 ms）内边界: 2
- 边界误差（分母=匹配数 2）：max=75.0 min=8.334 median=41.667 mean=41.667

| GT 边界 (ms) | 方向 | bracket [left, right] | width | midpoint | 误差 | 容差内 |
| --- | --- | --- | --- | --- | --- | --- |
| 6200.0 | confirmed→uncertain | [5958.333, 6291.667] | 333.334 | 6125.0 | 75.0 | True |
| 6800.0 | uncertain→confirmed | [6625.0, 6958.333] | 333.333 | 6791.666 | 8.334 | True |

## 效率（不抵消语义错误）

- configured_budget=12；actual_model_calls=11；unique_analyzed_timestamps=11；reused_evidence=0；duplicate_skips=0；budget_exhausted=False
- 耗时: total=122.44 ms（extraction=0.636，analysis=0.0，aggregation=0.114）
- 每正确 decisive 采样调用: 1.222222；每覆盖 confirmed event 调用: 5.5；每匹配边界调用: 5.5

## Ground Truth（dev，可审计）

- annotation_version=1.0.0；段数=3；边界数=2；容差=250.0 ms
- 状态序列: confirmed → uncertain → confirmed

## 输入文件哈希

- manifest: `artifacts/task-18/contracts/task18-fixture-evidence-pack-manifest.json` → `5b0c024189a8ea0c…`
- prediction_set: `artifacts/task-18/deterministic/prediction-set.json` → `9facf2ad8bf045a4…`
- ground_truth: `artifacts/task-18/contracts/ground-truth/short-uncertain-phase-b.temporal-ground-truth.json` → `9f5de571278dd181…`
- prediction_evidence: `artifacts/task-18/deterministic/short-uncertain-phase-b/coverage/temporal-evidence.json` → `0e19592b27109146…`
- media: `../fixtures/videos/fixture-short-uncertain-phase-b.mp4` → `ba3b9e928d4c839d…`

## 已知限制

- completed（execution_status）不等于语义正确；语义正确只由七类计数定义
- 时序结论是采样证据支持的结论，不是连续跟踪真值；采样点之间不断言连续存在
- 单次运行 + 小样本：不构成统计显著性，不得外推
- technical_fixture 为合成技术测试输入；不得外推为真实仓储/园区准确率
- 构造证据（非模型输出）：调用数为分析调用计数，不是真实视觉调用
