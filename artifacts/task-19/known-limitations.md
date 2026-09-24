# 任务 19B 已知限制（known limitations）

本文件随任务 19B 产物提交，与 `run-summary.md`、`comparisons/task19-three-scope-verdicts.json`、
`verification.json` 一起阅读。所有限制均为如实记录，不得在对外表述中淡化。

## 1. 模型语义校准失败（本轮最核心的基线发现）

- **uncertain 区双向过度断言**：AI06（人工标签全程 uncertain）三臂 overclaim 11/7/9——
  Qwen 对低照度远处小目标同时给出 confirmed 与 not_found 两种确定性结论，appropriate_abstention
  仅 1/3/1。任务 16/18 在合成 fixture 上记录的"确定性负面 overclaim"模式在真实 dev 数据上重现
  且更严重（双向）。
- **遮挡区不报告无法确认**：AI04 遮挡区间 [4000,9000] 三臂全部判 confirmed（overclaim 5/1/3），
  0 状态转换；模型没有"被遮挡/不可见"的概念出口。
- **真实域早期误报**：WEB01"货叉空载"前 4 秒被误判为 confirmed（incorrect 5/1/2）；WEB03 真实负向
  样本 uniform 4 + coverage 5 个 incorrect_decisive（相似容器/橙红结构件干扰）。
- **边界产出在方向兼容规则下不可用**：全部 8 个 GT 边界（均涉及 uncertain 过渡）在三臂上
  matched=0——模型从不产出 abstained/low_confidence→confirmed 形式的 transition，decisive→decisive
  按冻结规则不得匹配涉及 uncertain 的边界。边界误差统计全部 not_applicable。
- 以上均为**视觉模型语义问题，与采样策略无关**（三臂同模式）；本任务禁止校准，仅量化保存。

## 2. 采样策略的固有限制（真实数据复证）

- **coverage 修覆盖但不修校准**：coverage 臂触达了 adaptive 未触达的 uncertain 区（AI02/AI03），
  但模型在被触达处仍过度断言 → coverage-vs-adaptive 九样本全部 NO_IMPROVEMENT。
- **覆盖目标在长视频上未达成**：WEB01/WEB03 的 coverage 储备（4 次）用尽后最大相邻间隔仍为
  3103.1/2920.0ms（目标 1500ms）；`coverage_call_reserve=4` 未在 17–19s 视频上验证过。
- **不保证发现任意短事件**：AI02/WEB01 的 [4000,4500]（500ms）uncertain 区在 uniform 臂也未被
  触达（AI02/WEB01 的网格点恰好跳过该窗口）。
- **adaptive 的省调用以漏触达为代价**：AI04 adaptive 仅 4 次调用（初始覆盖后无触发信号），
  遮挡区完全未观测；uniform 密采样暴露最多失败（incorrect/overclaim 计数最高）。

## 3. 评测方法学限制

- **小样本 + 单次运行**：9 样本 × 3 臂各一次真实运行；licensed-public 轨道只有 3 段，只能写
  "小样本真实域观察"——不得写真实仓储准确率、统计显著性 or 生产可用性；generated 轨道为
  MiniMax-H3 生成受控测试视频，不外推为真实域结论。
- **公平门口径（多查询/多预算包）**：冻结双臂公平门的 same_target_query / same_call_budget 条件
  在实现上要求比较范围内取值唯一。generated 范围（查询/预算同质）十条件全部通过；
  licensed-public 与 all-dev 范围因 3 个 target query 与 3 档预算（12/18/19，任务书预算政策的
  必然结果）在该两个条件上 FAIL，冻结实现判 INVALID_COMPARISON——已如实保留，并以逐样本公平门
  （九样本 × 三对全部通过）与 pooled pairwise verdict（冻结 compute_verdict 对汇总指标）补充披露。
  **这不是评分规则修改，是比较单位选择的口径披露。**
- ** pooled pairwise 的汇总掩盖逐样本回归**：licensed-public coverage-vs-uniform 的 pooled
  IMPROVEMENT（fewer calls + 汇总 incorrect 9→7）背后，AI01 与 WEB03 两个样本 coverage 的
  incorrect 实际高于 uniform（2>1、5>4）——逐样本表已完整披露，不得只引汇总结论。
- **uniform 臂的 interval 规划**：interval=duration/budget 使网格点超预算、退化为区间内均匀取样
  （恰好预算个点、含两端点）；该规划为任务 19 预注册政策，与任务 16/18 的 700ms 定长网格不同
  （跨任务 uniform 配置不完全相同，跨任务比较需注意）。
- **墙钟字段非确定**：产物 `generated_at` 与 `timing.*_ms` 为真实测量值；评分输出已净化。
- **全分辨率帧不入库**：4K/1080p 抽帧体量过大，`.gitignore` 排除；提交 JPEG 缩略图（长边 ≤640）
  与全部 JSON 证据；帧可追溯性以时间戳 + provenance 记录为准。

## 4. DSH 自主会话限制

- 单样本单次会话（WEB01，8/19 次调用）：验证自主编排链路完整；单样本不构成统计结论。
- 会话内 Agent 的覆盖储备用尽后最大间隔 3103.1ms > 目标 1500ms（与批量 coverage 臂一致）；
  早期误报模式与批量一致（correct 6/8、incorrect 2/8）。
- 会话日志已按仓库既有惯例脱敏（用户 home 路径前缀 → ~），reasoning 内容未改动。

## 5. 评分与适配层限制

- 冻结评分器 v1 只支持单来源 temporal-evidence（G8）；本评测全部为单来源。
- 适配层（任务 18）pairwise 固定三对、pack 级候选臂固定 coverage；本评测沿用，未修改。
- 评分器 G7 的 actual_model_calls == 时间线条目数恒成立（本流水线每采样点一次真实调用），
  reused/duplicate 计数为 0——缓存复用路径在本轮未被触发。

## 6. 环境与边界

- 真实包路径只存在于 runner 代码 `--pack` 默认值；artifact 内只存脱敏/仓库相对路径。
- 媒体链接农场（`ingestion/media/`）为指向仓库外 dev 包的只读符号链接：不复制视频、不入 Git
  （`.gitignore`）；评分硬门 G2 与公平门 same_media_hash 均解析到同一真实文件。
- 原始视频（Pexels licensed-public 与 MiniMax-H3 生成素材）均未进入 Git；对外仅可提供详情页
  链接、SHA-256 或派生关键帧，且 AI 段必须标注"MiniMax-H3 生成的受控测试视频"。

## 7. 明确不做（非目标）

- 不修复 dev 失败、不开始校准（任务 20 候选）、不做未见集（holdout）测试、不更新工作台、
  不录屏、不写文章、不推送 GitHub；
- 不声称任意短事件必检、实时监控、跨摄像头身份追踪、StepFun 视觉识别；
- 不给统计显著性结论；不把生成轨道结果外推为真实域效果；
- **工程状态 BASELINE_COMPLETE 不等于模型效果达标**：三范围 pack 级 verdict 均为
  NO_IMPROVEMENT；当前系统在"带不确定度的边界"与"uncertain 拒答"两项上不具备可用性。
