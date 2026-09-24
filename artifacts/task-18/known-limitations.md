# 任务 18 已知限制（known limitations）

本文件随任务 18 产物提交，与 `three-arm-comparison.json`、`verdict.json`、
`run-summary.md` 一起阅读。所有限制均为如实记录，不得在对外表述中淡化。

## 1. 运行状态（已完成真实验证；两轮阻塞历史保留）

- **真实 Qwen 三臂评测与 DSH 自主会话均已完成**（2026-09-22 补跑轮）。此前两轮
  （12:08、12:42）因用户 MiniMax-H3 服务族活跃（h3-lite API :8010 监听、h3-studio
  WebUI 服务中、用户当天 11:28:57 仍有生成）资源门槛失败，状态为
  PARTIAL_RESOURCE_BLOCKED，两轮结构化 blocker 原样保留于
  `resource-gate-rerun.json` 历史块（未删除、未改写）。
- 补跑轮经用户明确授权：停服前安全门 8 项全部通过（生成队列连续三次为空、最近完成
  任务为当天 11:28:57、无活动生成连接、输出文件无增长），随后以纯 SIGTERM 优雅停止
  7 个经事实核验归属 `~/minimax-h3` 的进程（API、WebUI 树、3 个遗留 tab_test、
  2 个 coexistence-keeper 守护进程），全程无 kill -9、无误停 DSH/Ollama/SSH、未删除
  任何用户文件；停服后十项资源门槛全部通过。逐项证据见 `h3-shutdown-record.json`；
  恢复方式已记录，**任务结束后 H3 保持停止**。
- **H3 是用户生成素材服务，不是本项目视觉证据后端**；本项目的真实视觉分析全部由
  本地 Ollama Qwen Vision（`modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`）完成。

## 2. 真实 Qwen 运行揭示的限制（replay 无法证明的部分）

- **Qwen 触达 uncertain 区域后不拒答，而是过度断言**：真实运行中 coverage 臂触达了
  全部 2 个 uncertain 场景（adaptive 均未触达），但 Qwen 对低对比度 uncertain 帧给出
  确定性结论——overclaim_on_uncertain：coverage 4 次、uniform 2 次、adaptive 0 次
  （adaptive 的 0 是因为从未触达，而非模型拒答）。**任务 16 的确定性负面 overclaim
  模式在真实模型下重现**；appropriate_abstention 三臂均为 0（模型从未拒答）。
- **coverage-vs-adaptive 的 replay `IMPROVEMENT` 在真实模型下不成立，变为
  `TRADEOFF`**：唯一违反的非回归条件是 `more_overclaim_on_uncertain`。采样计划在两种
  模式下逐臂逐场景完全一致（均为 287 次调用），差异完全来自**视觉模型语义**
  （对 uncertain 的过度断言），而非采样策略。
- **coverage 采到短事件后 Qwen 能正确识别**：short-event-between-grid 与
  short-event-phase-b 两场景，coverage confirmed=2（发现事件），adaptive=0（漏检），
  uniform=1——任务 17 暴露的覆盖盲区在真实模型下被真实修复。
- **任意短事件仍不保证发现**：twin-short-events（两个 600ms 事件 < 1333.334ms 最终
  间隔）真实运行中 coverage 与 adaptive 均漏检 2/2，uniform 12 点网格 0 漏检——
  与 replay 结论一致的诚实实证。
- **真实运行零失败**：287 次调用无失败、无超时、无无效 JSON 输出；每次原始返回已存档
  （`real-qwen/*/raw/`）。

## 3. 覆盖策略的固有限制

- **不保证发现任意短事件**：产物显式携带
  `arbitrary_short_event_detection_guaranteed: false` 与
  `events_shorter_than_max_sampling_gap_may_be_missed: true`。覆盖间隔小于事件宽度
  是发现的必要非充分条件。
- **覆盖目标与预算的权衡**：`coverage_gap_target_ms=1500` + `coverage_call_reserve=4`
  是在 8s/12 次调用预算下的预注册选择；reappear-tight-budget（预算 6）真实运行中
  coverage 的 2 次覆盖调用后细化调用为 0。该参数组合未在其它时长/预算下验证。
- **稳定内容上覆盖探索"浪费"调用**：present-throughout 真实运行 coverage 用 7 次
  （adaptive 仅 4 次）压缩一个本无状态变化的视频的间隔——覆盖职责的固有成本。
- **多来源语义**：`coverage_call_reserve` 按来源分别生效，全局硬预算
  `max_model_calls` 是最终上限；每来源 provenance 的 `actual_model_calls` 是共享
  账本累计值（任务 16 既有行为）。

## 4. 评测方法学限制

- **小样本 + 单次运行**：11 个场景 × 3 臂各一次真实运行，不构成统计显著性，不得外推为
  真实仓储/园区准确率；**synthetic technical fixture 不是真实行业素材**。
- **uniform 臂的网格巧合**：short-event-between-grid 的事件起点 3500ms 恰好落在
  uniform 的 700ms 网格点（700×5）上，uniform 因此"发现"该事件——这是冻结 fixture
  的既成事实（预注册后不得改标签），不是对任何臂的偏袒。
- **墙钟字段非确定**：真实与 replay 产物中 `generated_at` 与 `timing.*_ms` 为真实
  测量值，逐字节复算范围排除这些字段。
- **绝对路径惯例**：temporal-evidence.json 的 `source_video`/`frame_path` 与报告
  conclusion 中的视频引用为绝对路径（帧可追溯审计轨迹，与任务 16 已提交产物一致）；
  评分器输出全部经净化，不含绝对用户路径；本人为记录的停服/门槛证据已 sanitize。

## 5. DSH 自主会话限制

- 单样本单次会话（fixture-short-event-between-grid，11/12 次调用）：验证了自主编排
  链路（Skill 发现→规格→校验→真实视觉→独立复算报告→离线评分），离线评分
  correct_decisive 11/11、边界 mean 33.333ms；但单样本不构成对该策略的统计结论。
- 会话产物中的媒体路径为绝对路径（合法路径契约），评分器硬门 G2 已三方核验媒体哈希。

## 6. 适配层限制

- 任务 17 冻结评分器的策略白名单在**内存**中扩展（+coverage_aware_adaptive），
  冻结文件零改动（SHA-256 不变，核验见 verification.json）；该扩展只影响 G7 硬门
  的策略枚举检查，不影响任何评分逻辑。
- 冻结评分器的 `difference_table`/`per_sample_row`/`render_comparison_md` 为双臂
  列名硬编码；三臂对比由适配层自行构建（pairwise 逐对计算 + pack 级聚合）。
- 评分器 v1 只支持单来源 temporal-evidence（G8）；本评测全部场景为单来源。

## 7. 明确不做（非目标）

- 不声称任意短事件必检、不声称实时视频监控、不声称跨摄像头身份追踪；
- 不声称 StepFun 视觉识别（StepFun 只做文本理解/规划/规格生成）；
- 不给统计显著性结论；不把 synthetic fixture 结果外推为真实域效果；
- **工程实现 PASS 不等于算法全面优于基线**：real pack-level verdict 为 TRADEOFF
  （严格改进：平均边界误差小于两个基线；违反：overclaim/漏检/最大间隔）；
- 用户 8 AI + 4 licensed public Evidence Pack（dev/holdout）**尚未接入**；真实 dev
  评测与 holdout 盲测仍是后续独立任务。
