# 数据卡 — abstain-zone

- 性质：synthetic technical fixture（合成技术测试输入；**非真实行业素材；不得外推为真实仓储/园区准确率**）
- 用途：abstained / low-confidence 区间（3000–5000 ms 目标低对比度，难以可靠确认）
- 媒体：`fixture-abstain-zone.mp4`（SHA-256 `277de0bbbb2bb327d38a5d5a30e8f0e414a15dc919daa802b81fb998adb441b2`，冻结于任务 16）
- 生成参数：640×360@24fps、8s/192 帧、mp4v、灰底红色正方形 80×80 居中、确定性渲染
- 目标查询：红色正方形
- 时间真值（任务 17 契约，详见 `ground-truth/abstain-zone.temporal-ground-truth.json`）：
  - [0, 3000) ms → confirmed
  - [3000, 5000) ms → uncertain
  - [5000, 8000) ms → confirmed
- 已知事实：该 fixture 的真实 Qwen 行为已由任务 16 如实记录（abstain-zone 的低对比度区间
  得到确定性负面而非拒答）；任务 17 评分器在新口径下逐采样点复算，不修改任何标签。
