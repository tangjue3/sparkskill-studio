# Task 20 勘误表（Task 21 阶段 B，2026-09-23）

- 性质：**追加勘误，不覆盖历史**。本文档逐项指向 Task 20 原始文件与正确口径；Task 19B/Task 20 的
  原始 `artifacts`、score、run-summary、paired-report、verification 与原始模型输出**字节不变**
  （哈希见 `artifacts/task-21/plan/input-hashes.json` 与 Task 20 `preregistration/frozen-hashes.json`）。
- 依据：对 256 个逐点存档（`artifacts/task-20/pairs/points/T20-P*.json`）与 `scores/paired-rows.json`
  的只读独立复算（CPU-only，零模型调用）；复算规则与 Task 17 冻结评分器同义
  （classify_entry / gt_state_at / metric_for）。
- 影响范围：只修正**人类可读口径**。Task 20 的预注册门槛、配对 verdict（`TRADEOFF`）、v1 生产模板
  身份与 holdout 封存状态**均不改变**（见 E7）。
- 与总控/前轮 Agent 文字不一致时，以可复核的逐点证据为准；本表记录所有已核实的偏差。

## E1. 七类账各合计 256；v2 五类主表缺 6+1 是口径子集，不是数据丢失

**原始文件**：`artifacts/task-20/scores/paired-score.json`（totals）、`scores/paired-rows.json`、
`run-summary.md` 第 5 节、`scores/paired-report.md` 第 1 节。

**正确口径**（从 256 个逐点存档独立复算，v1/v2 各 256）：

| 类别 | 同期 v1 | 同期 v2 |
| --- | ---: | ---: |
| correct_decisive | 186 | 181 |
| incorrect_decisive | 24 | 23 |
| abstention_on_determinate | 0 | **6** |
| failed_on_determinate | 0 | 0 |
| appropriate_abstention | 6 | 11 |
| overclaim_on_uncertain | 40 | 34 |
| failed_on_uncertain | 0 | **1** |
| **合计** | **256** | **256** |

- v2 的五类主表（181+23+11+34+0）只合计 **249**：它是有意的"五类主指标"口径子集
  （预注册 `design.md` 第 6 节把 abstention_on_determinate / failed_on_uncertain 列为补充类），
  **不是数据丢失，也不是新的评分成绩**。两类补充项已在 `paired-rows.json` 逐点记录
  （v2_metric 计数：abstention_on_determinate 6、failed_on_uncertain 1）。
- 人读材料在展示五类主表时应同时明示补充两类，或给出七类合计 256，避免读者误以为 7 个点消失。

## E2. 六次 determinate 拒答 = 5 次正确判断损伤 + 1 次误报修复

**原始文件**：`run-summary.md` 第 5/6/10 节、README.md、PROJECT_CONTEXT.md、BENCHMARK.md、
`docs/DEVELOPMENT_STATUS.md`。

**正确口径**（逐点证据）：

| 点 | 样本/臂 | 时间戳 | v1 指标 | v2 指标 | 性质 |
| --- | --- | --- | --- | --- | --- |
| T20-P0002 | AI01/uniform | 666.667 | correct_decisive | abstention_on_determinate | 正确判断损伤 |
| T20-P0015 | AI01/adaptive | 666.667 | correct_decisive | abstention_on_determinate | 正确判断损伤 |
| T20-P0022 | AI01/coverage | 666.667 | correct_decisive | abstention_on_determinate | 正确判断损伤 |
| T20-P0238 | WEB03/uniform | 17480.0 | **incorrect_decisive** | abstention_on_determinate | **误报修复**（非损伤） |
| T20-P0242 | WEB03/adaptive | 17480.0 | correct_decisive | abstention_on_determinate | 正确判断损伤 |
| T20-P0256 | WEB03/coverage | 17480.0 | correct_decisive | abstention_on_determinate | 正确判断损伤 |

- 不能把 6 次全部称为"六次正确判断损伤"或"6 损伤（correct→误拒）"：其中 5 次是 correct→拒答，
  1 次（WEB03/uniform t=17480）是把 v1 的误报（incorrect_decisive）改为拒答，**缓解误报**。
- run-summary 第 5 节逐点清单已正确披露 uniform 臂的误报修复属性；但其第 6/10 节汇总表述
  （"误拒 6 个可判定帧"）与四个人类可读入口的同类表述过度概括，以本表为准。
- 该区分不改变任何门槛计算：G3 用的是 correct_decisive 降幅（−5，仍超容忍 4），verdict 仍为 TRADEOFF。

## E3. AI04：遮挡区 9 个采样点、样本总数 24；v2 仅 1 点转拒答

**原始文件**：`run-summary.md` 第 7 节（"同期 v1 遮挡区 [4000,9000] overclaim 9/24 点"）。

**正确口径**：AI04 样本总数 **24** 点（uniform 12 / adaptive 4 / coverage 8）；遮挡区
[4000,9000) 内有 **9** 个采样点。同期 v1 这 9 点全部 overclaim_on_uncertain；同期 v2 其中
**1 点**（uniform t=7375）转为 appropriate_abstention，其余 8 点仍过度断言。
"9/24" 的写法把"遮挡区内 9 点"与"样本总数 24"并置，易误读为"遮挡区 24 点中的 9 点"，
应写"遮挡区 9 个采样点全部过度断言（样本总数 24）"。

## E4. WEB03：样本总数 36（不是 48）；v2 的 3 次 determinate 拒答来源

**原始文件**：`run-summary.md` 第 7 节（"v1 incorrect 10/48、correct 26/48"）。

**正确口径**：WEB03 样本总数 **36**（uniform 18 / adaptive 4 / coverage 14；36 = 26+10）。
- 同期 v1：correct_decisive 26、incorrect_decisive 10（合计 36）。
- 同期 v2：correct_decisive 24、incorrect_decisive 9、abstention_on_determinate **3**（合计 36）。
- 3 次 determinate 拒答全部在 t=17480 末帧（三臂同一帧）：**1 次源自 v1 误报**
  （uniform，incorrect→拒答，误报修复）、**2 次源自 v1 正确判断**（adaptive/coverage，
  correct→拒答，误拒）。
- "/48" 与任何实际计数不符（v1 两类合计 36、v2 三类合计 36），应为分母错误，以逐点证据为准。

## E5. 去重口径：各 184 唯一帧；v2 五类去重表须补示两类补充项；"首现行"有选择依赖

**原始文件**：`scores/paired-score.json`（dedup_sensitivity）、`run-summary.md` 第 8 节、
BENCHMARK.md 去重段。

**正确口径**（按 (sample_id, timestamp_ms) 去重，首现行顺序）：

| 类别 | v1 去重(184) | v2 去重(184) |
| --- | ---: | ---: |
| correct_decisive | 131 | 130 |
| incorrect_decisive | 19 | 18 |
| abstention_on_determinate | 0 | **2** |
| failed_on_determinate | 0 | 0 |
| appropriate_abstention | 4 | 8 |
| overclaim_on_uncertain | 30 | 25 |
| failed_on_uncertain | 0 | **1** |
| **合计** | **184** | **184** |

- v2 五类去重表（130+18+8+25+0=181）不足 184，缺的两类补充项（abstention_on_determinate **2**、
  failed_on_uncertain **1**）必须明示；v1 五类去重表恰好 184（两类补充项为 0）。
- **"首现行"去重有选择依赖**：跨臂输出不一致的帧保留哪一臂取决于点序遍历顺序。已实证：
  v1 首现行 {correct 131, incorrect 19} vs 末现行 {correct 132, incorrect 18}（AI06 t=10083.333 等
  5 个帧跨臂不一致：v1 4 帧、v2 2 帧）。因此去重敏感性**只能报告方向一致，不能声称统计显著性**，
  也不能把去重值当作该帧的唯一真相（各臂实际输出见 Task 21 重放产物的逐臂状态序列）。

## E6. 历史动态 0/8 与 v2 动态边界 not_measured 不可混淆

**原始文件**：README.md、PROJECT_CONTEXT.md、BENCHMARK.md、`docs/DEVELOPMENT_STATUS.md` 的
Task 20 段落（"8 个 GT 边界仍 0/8"）；`artifacts/task-19/run-summary.md` 第 5/6 节。

**正确口径**：
- `0/8`（每臂 matched 0 / 8 个 GT 边界，三臂合计 24 次暴露全 missed）属于 **Task 19B 历史 v1
  动态三臂**（`artifacts/task-19/scores/all-dev/three-arm-comparison.json`：matched_boundaries=0、
  missed_gt_boundaries=8/臂）。
- **Task 20 v2 没有跑动态时间线**（阶段 C 因 verdict≠IMPROVEMENT 未运行，V11 已验证
  `dynamic/` 无 run-metadata.json）：v2 的**动态边界成绩只能写 `not_measured`**。
- 任何 v2 段落都不得含糊写"边界仍 0/8"——那会把历史动态结果安到未测量的 v2 动态上。
- Task 21 固定采样重放（`artifacts/task-21/replay/`）提供了第三种证据：在 Task 19B 已选时间点上，
  同期 v1 与同期 v2 的存档输出在 Task 17 方向兼容规则下均 **0/24 次边界暴露匹配**；
  这是规则级反事实诊断，**不是** v2 动态测量，也不改变 Task 20 verdict。

## E7. PAIRING_COMPLETE 是工程状态；模型质量仍是 TRADEOFF；生产模板仍是 v1；holdout 未开启

**原始文件**：README.md、PROJECT_CONTEXT.md、BENCHMARK.md、`docs/DEVELOPMENT_STATUS.md`。

**正确口径**：
- `PAIRING_COMPLETE` 只表示工程实验完整（一次预注册、一个候选、512/512 调用完整记账）；
  v2 的模型质量状态是 **TRADEOFF**（G1/G2/G4 PASS、G3 FAIL），两者正交，不得互相代替。
- v2 **未被采纳进 Skill**：`analyze_image.py` 零改动，**v1 仍是生产模板**（哈希
  `fc290780…`，frozen-hashes 复算一致）。
- holdout **尚未获准开启**；本任务及 Task 20 均未触碰 holdout。
- dev 小样本 + 单次运行 + 温度 0.1 随机性：不得给出统计显著性、不得外推真实仓储准确率。

## 附：本勘误的复算方法与可复核性

- 复算输入：256 个逐点存档 + `paired-rows.json` + 9 份 GT；规则：Task 17 冻结
  classify_entry / gt_state_at / metric_for（与 `paired_scorer.py` 同义）。
- 复算产物：`artifacts/task-21/replay/replay-results.json`（含每版七类汇总、逐臂、逐边界矩阵），
  测试 `scripts/test_task21_replay.py`（12/12，CPU-only，零模型调用）。
- 本文档修正的人类可读入口：README.md、PROJECT_CONTEXT.md、BENCHMARK.md、
  docs/DEVELOPMENT_STATUS.md（均保留 PARTIAL/TRADEOFF 等版本历史并链接本表）。
