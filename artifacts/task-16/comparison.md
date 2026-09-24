# 任务 16 uniform vs adaptive 对照（technical fixture，真实 Qwen 调用）

- 生成时间：2026-09-22T08:53:56.456426+00:00
- 输入性质：real_qwen_model_output_on_synthetic_technical_fixture
- **本对照使用合成技术 fixture，不是真实行业视频；结果不得外推为真实仓储准确率。**

## 公平性

- same_video: True
- same_target_query: 红色正方形
- same_model: modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest（本地 Ollama）
- same_resource_window: 真实运行见 artifacts/task-16/resource-gate.json
- same_status_rules: 同一 trace_temporal.py 代码路径与 frame_class 分类规则
- same_max_model_calls: 12
- exception: BUDGET_SCENARIOS 中的 reappear-adaptive-budget-6 为显式的“更少调用”预算耗尽场景，不参与同预算主对照
- same_timeout_s: 300
- no_single_side_retry: True
- no_sample_removal: True
- ground_truth_not_modified_after_results: True
- tier3_untouched: True

## 逐场景结果

### same-budget-present-throughout

- fixture: present-throughout；预算: 12
- 目的: 持续正向 + 无状态变化（目标全程清晰存在；adaptive 应 0 次细化）

| 指标 | uniform | adaptive |
| --- | --- | --- |
| 最终状态 | completed | completed |
| 首次 confirmed 采样(ms) | 0.0 | 0.0 |
| 最后 confirmed 采样(ms) | 7708.333 | 7958.333 |
| confirmed 采样数 | 12 | 4 |
| 状态转换数 | 0 | 0 |
| 最大边界不确定宽度(ms) | None | None |
| 达到目标边界精度 | None | True |
| 实际 Qwen 调用数 | 12 | 4 |
| 配置预算 | 12 | 12 |
| 耗尽预算 | True | False |
| 总耗时(s) | 255.312 | 80.664 |
| 单次调用耗时(ms) | 21264.7 | 20138.8 |
| abstained 数 | 0 | 0 |
| failed 数 | 0 | 0 |
| 证据性质 | real_model_output | real_model_output |
- uniform ground truth 检查：存在性正确=True，GT 转换覆盖 0/0
- adaptive ground truth 检查：存在性正确=True，GT 转换覆盖 0/0

### same-budget-appear-midway

- fixture: appear-midway；预算: 12
- 目的: 中途出现（目标在 3200 ms 进入画面）

| 指标 | uniform | adaptive |
| --- | --- | --- |
| 最终状态 | completed | completed |
| 首次 confirmed 采样(ms) | 3500.0 | 3333.333 |
| 最后 confirmed 采样(ms) | 7708.333 | 7958.333 |
| confirmed 采样数 | 7 | 4 |
| 状态转换数 | 1 | 1 |
| 最大边界不确定宽度(ms) | 708.333 | 333.333 |
| 达到目标边界精度 | None | True |
| 实际 Qwen 调用数 | 12 | 7 |
| 配置预算 | 12 | 12 |
| 耗尽预算 | True | False |
| 总耗时(s) | 222.914 | 129.669 |
| 单次调用耗时(ms) | 18563.2 | 18499.4 |
| abstained 数 | 0 | 0 |
| failed 数 | 0 | 0 |
| 证据性质 | real_model_output | real_model_output |
- uniform ground truth 检查：存在性正确=True，GT 转换覆盖 1/1
- adaptive ground truth 检查：存在性正确=True，GT 转换覆盖 1/1

### same-budget-disappear-midway

- fixture: disappear-midway；预算: 12
- 目的: 中途消失（目标在 4800 ms 离开画面）

| 指标 | uniform | adaptive |
| --- | --- | --- |
| 最终状态 | completed | completed |
| 首次 confirmed 采样(ms) | 0.0 | 0.0 |
| 最后 confirmed 采样(ms) | 4208.333 | 4666.667 |
| confirmed 采样数 | 7 | 4 |
| 状态转换数 | 1 | 1 |
| 最大边界不确定宽度(ms) | 708.334 | 333.333 |
| 达到目标边界精度 | None | True |
| 实际 Qwen 调用数 | 12 | 7 |
| 配置预算 | 12 | 12 |
| 耗尽预算 | True | False |
| 总耗时(s) | 225.458 | 130.776 |
| 单次调用耗时(ms) | 18777.1 | 18656.2 |
| abstained 数 | 0 | 0 |
| failed 数 | 0 | 0 |
| 证据性质 | real_model_output | real_model_output |
- uniform ground truth 检查：存在性正确=True，GT 转换覆盖 1/1
- adaptive ground truth 检查：存在性正确=True，GT 转换覆盖 1/1

### same-budget-reappear

- fixture: reappear；预算: 12
- 目的: 出现、消失、再次出现（两次进入 + 两次离开）

| 指标 | uniform | adaptive |
| --- | --- | --- |
| 最终状态 | completed | completed |
| 首次 confirmed 采样(ms) | 0.0 | 0.0 |
| 最后 confirmed 采样(ms) | 5583.333 | 5958.333 |
| confirmed 采样数 | 6 | 6 |
| 状态转换数 | 3 | 3 |
| 最大边界不确定宽度(ms) | 708.334 | 666.667 |
| 达到目标边界精度 | None | False |
| 实际 Qwen 调用数 | 12 | 12 |
| 配置预算 | 12 | 12 |
| 耗尽预算 | True | True |
| 总耗时(s) | 217.134 | 222.918 |
| 单次调用耗时(ms) | 18084.5 | 18554.4 |
| abstained 数 | 0 | 0 |
| failed 数 | 0 | 0 |
| 证据性质 | real_model_output | real_model_output |
- uniform ground truth 检查：存在性正确=True，GT 转换覆盖 3/3
- adaptive ground truth 检查：存在性正确=True，GT 转换覆盖 3/3

### same-budget-abstain-zone

- fixture: abstain-zone；预算: 12
- 目的: abstained / low-confidence 区间（3000–5000 ms 目标低对比度，难以可靠确认）

| 指标 | uniform | adaptive |
| --- | --- | --- |
| 最终状态 | completed | completed |
| 首次 confirmed 采样(ms) | 0.0 | 0.0 |
| 最后 confirmed 采样(ms) | 7708.333 | 7958.333 |
| confirmed 采样数 | 9 | 4 |
| 状态转换数 | 2 | 0 |
| 最大边界不确定宽度(ms) | 708.333 | None |
| 达到目标边界精度 | None | True |
| 实际 Qwen 调用数 | 12 | 4 |
| 配置预算 | 12 | 12 |
| 耗尽预算 | True | False |
| 总耗时(s) | 234.048 | 79.84 |
| 单次调用耗时(ms) | 19492.5 | 19930.4 |
| abstained 数 | 0 | 0 |
| failed 数 | 0 | 0 |
| 证据性质 | real_model_output | real_model_output |
- uniform ground truth 检查：存在性正确=True，GT 转换覆盖 0/0
- adaptive ground truth 检查：存在性正确=True，GT 转换覆盖 0/0

### reappear-adaptive-budget-6

- fixture: reappear；预算: 6
- 目的: 预算耗尽场景（显式少于主对照预算，验证停止细化与如实报告）

| 指标 | uniform | adaptive |
| --- | --- | --- |
| 最终状态 | None | completed |
| 首次 confirmed 采样(ms) | None | 0.0 |
| 最后 confirmed 采样(ms) | None | 5333.333 |
| confirmed 采样数 | None | 4 |
| 状态转换数 | None | 3 |
| 最大边界不确定宽度(ms) | None | 2625.0 |
| 达到目标边界精度 | None | False |
| 实际 Qwen 调用数 | None | 6 |
| 配置预算 | None | 6 |
| 耗尽预算 | None | True |
| 总耗时(s) | None | 111.994 |
| 单次调用耗时(ms) | None | 18635.1 |
| abstained 数 | None | 0 |
| failed 数 | None | 0 |
| 证据性质 | None | real_model_output |
- adaptive ground truth 检查：存在性正确=True，GT 转换覆盖 3/3

### multi-source-pair

- fixture: ['appear-midway', 'disappear-midway']；预算: 24
- 目的: 多来源输入（共享预算；验证 source_id/原时间戳保留与全局时序证据）

| 指标 | uniform | adaptive |
| --- | --- | --- |
| 最终状态 | None | completed |
| 首次 confirmed 采样(ms) | None | 0.0 |
| 最后 confirmed 采样(ms) | None | 7958.333 |
| confirmed 采样数 | None | 8 |
| 状态转换数 | None | 10 |
| 最大边界不确定宽度(ms) | None | 2666.667 |
| 达到目标边界精度 | None | False |
| 实际 Qwen 调用数 | None | 14 |
| 配置预算 | None | 24 |
| 耗尽预算 | None | False |
| 总耗时(s) | None | None |
| 单次调用耗时(ms) | None | None |
| abstained 数 | None | 0 |
| failed 数 | None | 0 |
| 证据性质 | None | real_model_output |

## Verdict

**IMPROVEMENT** — 同预算主对照 5 个场景：两臂最终状态均正确；adaptive 边界定位不劣于 uniform（最大边界宽度均不高于 uniform），且调用数不高于 uniform 或达到目标边界精度；详细逐项数据见 scenarios

- 小样本声明：技术 fixture 小样本；结果不得外推为真实仓储准确率；单次运行，Agent/模型行为非确定性
