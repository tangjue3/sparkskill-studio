# 数据卡 — short-uncertain-between-grid

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：coarse 初始网格之间的短 uncertain 区域；coarse 初始网格之间的短 uncertain 区域（3500–4100 ms 低对比度，落在两个初始采样点之间；对应任务 17 量化的 adaptive 覆盖盲区）
- 媒体：`fixture-short-uncertain-between-grid.mp4`（SHA-256 `05b3fb405150b6fcd0c7c8191b3d09f46c524b0250d18e3e87ef57711f6f8aa3`，任务 18 新增冻结 fixture）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/short-uncertain-between-grid.temporal-ground-truth.json`）：
  - [0, 3500) ms → confirmed
  - [3500, 4100) ms → uncertain
  - [4100, 8000) ms → confirmed
