# 数据卡 — disappear-midway

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：中途消失；中途消失（目标在 4800 ms 离开画面）
- 媒体：`fixture-disappear-midway.mp4`（SHA-256 `59a203c0ebff95d96f9d73e3429b60fa9de32ecdef019dfc86f7afdc5e945728`，复用任务 16 冻结 fixture）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/disappear-midway.temporal-ground-truth.json`）：
  - [0, 4800) ms → confirmed
  - [4800, 8000) ms → not_found
