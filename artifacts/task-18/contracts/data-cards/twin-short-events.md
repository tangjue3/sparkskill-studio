# 数据卡 — twin-short-events

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：两个间隔较短的事件；两个间隔较短的事件（1600–2200 ms 与 3000–3600 ms，各 600ms，均落在 coarse 网格间隔内）
- 媒体：`fixture-twin-short-events.mp4`（SHA-256 `27a44ff7ac55f5d304eeaf0dc4ee6f9c51b541b55d1ae13303e807047ea68b7b`，任务 18 新增冻结 fixture）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/twin-short-events.temporal-ground-truth.json`）：
  - [0, 1600) ms → not_found
  - [1600, 2200) ms → confirmed
  - [2200, 3000) ms → not_found
  - [3000, 3600) ms → confirmed
  - [3600, 8000) ms → not_found
