# 数据卡 — reappear

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：出现、消失、再次出现（两次进入 + 两次离开）
- 媒体：`fixture-reappear.mp4`（SHA-256 `a298c6e36b61f4299cd09ee46bbf0b2999c6049bb71cb8a73856a7b1e9f7d0ca`，冻结于任务 16）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/reappear.temporal-ground-truth.json`）：
  - [0, 2000) ms → confirmed
  - [2000, 4000) ms → not_found
  - [4000, 6000) ms → confirmed
  - [6000, 8000) ms → not_found
- 已知事实：该 fixture 的真实 Qwen 行为已由任务 16 如实记录（abstain-zone 的低对比度区间
  得到确定性负面而非拒答）；任务 17 评分器在新口径下逐采样点复算，不修改任何标签。
