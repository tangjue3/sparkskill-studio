# 数据卡 — short-uncertain-phase-b

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：相位移动的短 uncertain 区域；相位移动的短 uncertain 区域（6200–6800 ms 低对比度；与 short-uncertain-between-grid 语义相同、时间相位不同）
- 媒体：`fixture-short-uncertain-phase-b.mp4`（SHA-256 `ba3b9e928d4c839dcf6471f3993348906cf2df55fa7856b0bfb9f1cb84e710cb`，任务 18 新增冻结 fixture）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/short-uncertain-phase-b.temporal-ground-truth.json`）：
  - [0, 6200) ms → confirmed
  - [6200, 6800) ms → uncertain
  - [6800, 8000) ms → confirmed
