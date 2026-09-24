# 数据卡 — reappear-tight-budget

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：预算不足以同时完成覆盖与全部边界细化（三臂统一预算 6）；出现、消失、再次出现（两次进入 + 两次离开）
- 媒体：`fixture-reappear.mp4`（SHA-256 `a298c6e36b61f4299cd09ee46bbf0b2999c6049bb71cb8a73856a7b1e9f7d0ca`，复用任务 16 冻结 fixture）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/reappear-tight-budget.temporal-ground-truth.json`）：
  - [0, 2000) ms → confirmed
  - [2000, 4000) ms → not_found
  - [4000, 6000) ms → confirmed
  - [6000, 8000) ms → not_found
