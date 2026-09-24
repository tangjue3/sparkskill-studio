# 语义评分 — abstain-zone / adaptive

- pack sample: `abstain-zone`（split=dev, source_type=technical_fixture）
- **execution_status**: `completed`（流水线是否完成）
- **semantic_score_status**: `scored`（语义评分是否可算；completed ≠ 语义正确）
- 预测策略: `adaptive_coarse_to_fine`；evidence_nature: `real_model_output`；采样点: 4

## 输入验证（硬门）

| 门 | 通过 | 说明 |
| --- | --- | --- |
| G1-sample-identity | 是 | evidence.target_query 存在且非空 |
| G2-media-hash-freeze | 是 | 媒体 SHA-256 三方一致（manifest/GT/实际文件）: 277de0bbbb2bb327… |
| G3-target-query | 是 | target_query 三方一致（manifest/GT/evidence） |
| G4-media-duration | 是 | 媒体时长一致（manifest/GT/evidence）: 8000.0 ms |
| G5-ground-truth-timeline | 是 | GT 时间线合法（排序/覆盖/不重叠/不留隙/正长度/相邻合并） |
| G6-prediction-timestamps-in-range | 是 | 全部 4 个采样时间戳位于 [0, 8000.0] ms |
| G7-provenance-self-consistency | 是 | provenance 自洽（调用数=新鲜调用=时间线条目；预算未超；时间戳集合一致；五类计数复算一致） |
| G8-prediction-shape | 是 | 单来源时序证据文档（顶层 timeline） |

## 采样点语义评分

- 分母（已分析采样点）: 4（determinate 4 / uncertain 0）

| 指标 | 通过 | 总数 | 比率 |
| --- | --- | --- | --- |
| correct_decisive | 4 | 4 | 1.0 |
| incorrect_decisive | 0 | 4 | 0.0 |
| abstention_on_determinate | 0 | 4 | 0.0 |
| failed_on_determinate | 0 | 4 | 0.0 |
| appropriate_abstention | 0 | 0 | not_applicable |
| overclaim_on_uncertain | 0 | 0 | not_applicable |
| failed_on_uncertain | 0 | 0 | not_applicable |

## 事件覆盖

- GT confirmed segments: 2；覆盖: 2；漏掉: 0
- GT not_found segments: 0；覆盖: 0；漏掉: 0
- GT uncertain segments: 1；未触达: 1
  - [3000.0, 5000.0] ms：reached=False，appropriate_abstention=False，段内采样点=0

## 状态转换与边界

- GT 边界总数: 2；匹配: 0；漏掉: 2；多余预测 transition: 0
- 容差（250.0 ms）内边界: 0
- 边界误差（分母=匹配数 0）：max=not_applicable min=not_applicable median=not_applicable mean=not_applicable

## 效率（不抵消语义错误）

- configured_budget=12；actual_model_calls=4；unique_analyzed_timestamps=4；reused_evidence=0；duplicate_skips=0；budget_exhausted=False
- 耗时: total=79839.969 ms（extraction=1.049，analysis=79721.682，aggregation=0.07）
- 每正确 decisive 采样调用: 1.0；每覆盖 confirmed event 调用: 2.0；每匹配边界调用: not_applicable

## Ground Truth（dev，可审计）

- annotation_version=1.0.0；段数=3；边界数=2；容差=250.0 ms
- 状态序列: confirmed → uncertain → confirmed

## 输入文件哈希

- manifest: `artifacts/task-17/contracts/task16-fixture-evidence-pack-manifest.json` → `f66ab0fd8b5120c2…`
- prediction_set: `artifacts/task-17/rescored-task16/prediction-set.json` → `7b28847e71f1eba0…`
- ground_truth: `artifacts/task-17/contracts/ground-truth/abstain-zone.temporal-ground-truth.json` → `bf5b63eeb674ad48…`
- prediction_evidence: `artifacts/task-16/comparison/abstain-zone/adaptive/temporal-evidence.json` → `ac7faf5480d0b0c6…`
- media: `../../task-16/fixtures/videos/fixture-abstain-zone.mp4` → `277de0bbbb2bb327…`

## 已知限制

- completed（execution_status）不等于语义正确；语义正确只由七类计数定义
- 时序结论是采样证据支持的结论，不是连续跟踪真值；采样点之间不断言连续存在
- 单次运行 + 小样本：不构成统计显著性，不得外推
- technical_fixture 为合成技术测试输入；不得外推为真实仓储/园区准确率
