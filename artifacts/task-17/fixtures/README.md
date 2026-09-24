# 任务 17 确定性测试 fixtures

由 `build_fixtures.py` 生成（纯标准库、无模型调用、确定性：同一参数永远
得到同一文件内容）。每个目录一个用例，`expected.json` 记录测试断言
（具体字段与具体计数）。

媒体文件是**占位二进制**（`<case_id>` 的确定性内容）：评分器只计算
SHA-256、不解码视频；它们不是真实视频，不得外推为真实素材结论。
预测证据文档全部标注 `constructed_fixture_evidence`（构造证据，
非模型输出）。

| 用例 | 覆盖 |
| --- | --- |
| t01-all-correct | 完全正确的采样点 |
| t02-incorrect-decisive | confirmed↔not_found 错误断言 |
| t03-appropriate-abstention | uncertain 上的适当拒答 |
| t04-overclaim-confirmed | uncertain 上的 confirmed 过度断言 |
| t05-overclaim-not-found | uncertain 上的 not_found 过度断言 |
| t06-abstention-on-determinate | determinate 上的拒答 |
| t07-failed-states | failed 状态（determinate/uncertain） |
| t08-confirmed-event-covered | confirmed event 被覆盖 |
| t09-narrow-event-missed | 窄 confirmed event 完全漏检 |
| t10-narrow-uncertain-unreached | 窄 uncertain segment 完全未触达 |
| t11-boundary-within-tolerance | 边界在容差内 |
| t12-boundary-out-of-tolerance | 边界超出容差 |
| t13-direction-incompatible | transition 方向不兼容 |
| t14-extra-predicted-transition | 多余预测 transition |
| t15-gt-overlap | Ground Truth 时间线重叠 |
| t16-gt-gap | Ground Truth 时间线有空隙 |
| t17-gt-unmerged | 相邻相同状态未合并 |
| t18-duration-mismatch | duration 不一致 |
| t19-media-hash-mismatch | media hash 不一致 |
| t20-sample-id-mismatch | sample ID 不一致 |
| t21-missing-ground-truth-arg | 缺少显式 Ground Truth 参数 |
| t22-improvement-fewer-calls | 相同质量、更少调用 → IMPROVEMENT |
| t23-improvement-boundary | 边界更准、调用相同 → IMPROVEMENT |
| t24-tradeoff-missed-event | 调用更少但漏掉事件 → TRADEOFF |
| t25-tradeoff-unreached-uncertain | 调用更少但漏掉 uncertain → TRADEOFF |
| t26-no-improvement | 无任何实质改进 → NO_IMPROVEMENT |
| t27-invalid-comparison-budget | 预算不一致 → INVALID_COMPARISON |
| t28-empty-denominators | 空分母输出 not_applicable |
| t28b-empty-timeline | 空时间线 → not_applicable |
| t29-holdout-gt-not-in-output | holdout Ground Truth 不进入公开输出 |
| t30-competition-profile-valid | 8 AI + 4 真实 profile 合规 |
| t31-competition-profile-bad-split | profile split 不合规（负向） |
| t32-competition-profile-missing-license | 许可字段缺失（负向） |
| t33-competition-profile-duplicate-id | 重复 sample_id（负向） |
