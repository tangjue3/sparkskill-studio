# 数据卡 — short-event-phase-b

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：相位移动的短 confirmed 事件；相位移动的短 confirmed 事件（6200–6800 ms；与 short-event-between-grid 语义相同、时间相位不同，防止只对单一时间位置调参）
- 媒体：`fixture-short-event-phase-b.mp4`（SHA-256 `d2bd059a75c0aa2f6bec0373c5d50fb591d2c20d56c09bbc752eb985c16aee5d`，任务 18 新增冻结 fixture）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/short-event-phase-b.temporal-ground-truth.json`）：
  - [0, 6200) ms → not_found
  - [6200, 6800) ms → confirmed
  - [6800, 8000) ms → not_found
