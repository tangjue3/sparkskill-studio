# 数据卡 — short-event-between-grid

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：coarse 初始网格之间的短 confirmed 事件；coarse 初始网格之间的短 confirmed 事件（3500–4100 ms，落在 2666.667/5333.333 两个初始采样点之间；adaptive 无触发信号必然漏检）
- 媒体：`fixture-short-event-between-grid.mp4`（SHA-256 `d9f194ff7ef2b5d3f52f9e98c90d77b9de2cc907639bd7adcdbb09ffb4a4d172`，任务 18 新增冻结 fixture）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/short-event-between-grid.temporal-ground-truth.json`）：
  - [0, 3500) ms → not_found
  - [3500, 4100) ms → confirmed
  - [4100, 8000) ms → not_found
