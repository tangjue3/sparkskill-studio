# 数据卡 — appear-midway

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：中途出现（目标在 3200 ms 进入画面）
- 媒体：`fixture-appear-midway.mp4`（SHA-256 `37147666284b3481c9a4ea7b0236014e880fc96f74eadd168d1910ee9e94721f`，冻结于任务 16）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/appear-midway.temporal-ground-truth.json`）：
  - [0, 3200) ms → not_found
  - [3200, 8000) ms → confirmed
- 已知事实：该 fixture 的真实 Qwen 行为已由任务 16 如实记录（abstain-zone 的低对比度区间
  得到确定性负面而非拒答）；任务 17 评分器在新口径下逐采样点复算，不修改任何标签。
