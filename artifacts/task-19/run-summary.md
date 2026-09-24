# Task 19B 运行摘要 — dev Evidence Pack 三策略真实基线评测

- 日期：2026-09-22/23（UTC）
- 工程状态：**BASELINE_COMPLETE**（九样本三臂真实运行 + 评分 + DSH 自主会话完整；与算法 verdict 独立）
- 阶段 A 提交：`e3ef01e`（docs: preregister dev evidence pack evaluation，预注册先于任何 dev 模型调用）
- 基线：分支 `master`，HEAD `ef9f329`（任务 18 提交）→ 阶段 A `e3ef01e`
- 评分：任务 17 冻结 scorer（`scripts/score_temporal_ground_truth.py`，零改动）+ 任务 18 已提交适配层（`scripts/task18_scorer_adapter.py`，零改动）

## 1. 环境与资源门槛

- H3 保持停止（:8000/:8010 无监听、无生成类进程、无 WebUI 任务）；Ollama 0.33.2 正常；DSH 0.1.5-rc.2 正常；`MemAvailable` 连续三次 115.8+ GiB（≥45 GiB）；`/api/ps` 无外部 Qwen 消费者（模型按需加载、自然过期，未强制卸载）。
- 批量运行前 8 项资源门槛全部通过并记录（`artifacts/task-19/resource-gate.json`）；DSH 会话前门槛独立复核通过（`dsh-session/resource-gate.json`）。
- 运行期间用户未启动 H3、未出现外部消费者；无任何服务被停止/重启/改配置；未联网、未安装依赖、未读取凭据。

## 2. dev 包摄验（`ingestion/dev-pack-verification.json`，14 项全过）

- 包路径 `<DEV_EVIDENCE_PACK_ROOT>`（真实绝对路径只在 scripts/task19_ingest.py --pack 默认值中；Git 仓库之外，包内无 .git）；35 个文件（9 视频 + 9 卡 + 6 Prompt + 6 许可凭证 + manifest + freeze 清单 + README + 交接清单 + 生成记录）。
- 白名单恰好 AI01–AI06 + WEB01–WEB03；文件名与 19 个文本内容中全部 `AI\d+/WEB\d+` 编号属于白名单；无 holdout 编号（公开版占位编号 HOLDOUT-G1/HOLDOUT-G2/HOLDOUT-L1 0 命中）；无非白名单路径引用（源 YAML 卡按名引用 9 处，设计上不随包传输）。
- 无凭据/私钥样式、无 IPv4、无 user@host（否定/声明语境不计，与包自带 text_scan 同口径）。
- 九段视频冻结 SHA-256 双源匹配（dev-freeze.sha256 + manifest.video_freeze_hashes）；九张卡哈希匹配且 `lineage.source_card_sha256` 与 manifest 一致；卡片 media SHA-256 与实际视频一致；视频总字节 137,919,113 与交付清单一致。
- 实测元数据（cv2，与流水线同一公式）：AI01/AI05 8000.0ms、AI02/AI03/AI04/AI06 10125.0ms、WEB01 18551.867ms（卡片标称 18560）、WEB02 10243.567ms（卡片标称 10260）、WEB03 17520.0ms。

## 3. Ground Truth 派生（`ground-truth/` + `preregistration/ground-truth-normalization-report.json`）

- 唯一标签来源：九张 transfer-safe card（字节 identical 复制到 `ingestion/data-cards/`；源卡与 dev 包只读未修改）。
- 结构规范化（任务 17 契约）：
  - **AI06**：uncertain [0,6000] + [6000,10125] → **[0,10125]**（相邻同状态合并；两段人工原因以"；"连接保留）；
  - **WEB02**：confirmed [0,3000] + [3000,10260] → **[0,10243.567]**（合并 + 末段终点对齐实测时长；原因保留）；
  - **WEB01**：末段终点 18560 → 18551.867（对齐实测时长；状态与边界不变）；
  - 其余六张卡无相邻同状态，GT 与卡片逐段一致。
- 不变式逐样本校验：状态覆盖（实测媒体范围内）未改变、边界集合未改变、原人工原因全部保留；九份 GT 通过任务 17 冻结契约校验。
- GT 与模型执行隔离：execution manifest（27 份）与 VisualTaskSpec（27 份）深扫描无标签键/状态值/难度字符串（测试 T09）。

## 4. 三臂执行（`predictions/`）

- 预算政策（阶段 A 冻结）：`max_model_calls = clamp(ceil(media_duration_ms/1000), 12, 24)` → AI01–AI06 与 WEB02 = 12，WEB01 = 19，WEB03 = 18；同样本三臂同预算。
- 臂参数（通用政策常数）：uniform（interval=duration/budget、max_frames=budget）；adaptive（initial=4、precision=500、rounds=6、四触发器）；coverage（initial=4、gap_target=1500、reserve=4、precision=500、rounds=6）。
- 执行顺序：样本按 ID 字典序；样本内臂顺序按索引循环左移轮换（热状态控制）；批量前一次统一 warm-up（任务 16 冻结 fixture 一帧，1 次真实调用，不计入任何 arm，不使用 dev 标签）。
- **27/27 (样本,臂) 运行成功，0 失败**；真实 Qwen Vision 调用合计 **256 次**（uniform 121 + adaptive 51 + coverage 84；不含 warm-up 1 次）；每 (样本,臂) 保存 execution manifest、VisualTaskSpec、抽帧时间戳、模型原始 JSON（raw/）、采样 provenance、temporal evidence、temporal 报告、关键帧缩略图、指标。
- 单帧超时 300s；无单侧重试、无额外上下文、无人工纠正、不删除失败样本。WEB03/uniform 有 1 帧 failed（计入 failed_on_determinate=1）。
- 全分辨率抽帧不入库（`.gitignore`）；提交 JPEG 缩略图（长边 ≤640）+ 全部 JSON 证据。

## 5. 逐样本逐臂语义结果（任务 17 冻结 scorer；`scores/all-dev/<样本>/<臂>/score.json`）

七类计数（correct/incorrect/abstention_on_determinate/failed_on_determinate/appropriate_abstention/overclaim_on_uncertain/failed_on_uncertain）：

| 样本/臂 | correct | incorrect | app_abst | overclaim | failed_det | 事件覆盖 | uncertain 未触达 | GT 边界 matched/missed | 调用 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AI01/uniform | 11 | 1 | 0 | 0 | 0 | 1/1 | 0 | 0/0 | 12 |
| AI01/adaptive | 5 | 2 | 0 | 0 | 0 | 1/1 | 0 | 0/0 | 7 |
| AI01/coverage | 7 | 2 | 0 | 0 | 0 | 1/1 | 0 | 0/0 | 9 |
| AI02/uniform | 12 | 0 | 0 | 0 | 0 | 1/1 | **1** | 0/2 | 12 |
| AI02/adaptive | 6 | 0 | 1 | 1 | 0 | 1/1 | 0 | 0/2 | 7 |
| AI02/coverage | 9 | 0 | 1 | 1 | 0 | 1/1 | 0 | 0/2 | 10 |
| AI03/uniform | 11 | 0 | 0 | 1 | 0 | 1/1 | 0 | 0/2 | 12 |
| AI03/adaptive | 6 | 0 | 0 | 1 | 0 | 1/1 | 0 | 0/2 | 7 |
| AI03/coverage | 9 | 0 | 0 | 1 | 0 | 1/1 | 0 | 0/2 | 10 |
| AI04/uniform | 7 | 0 | 0 | **5** | 0 | 2/2 | 0 | 0/2 | 12 |
| AI04/adaptive | 3 | 0 | 0 | 1 | 0 | 2/2 | 0 | 0/2 | 4 |
| AI04/coverage | 5 | 0 | 0 | 3 | 0 | 2/2 | 0 | 0/2 | 8 |
| AI05/uniform | 12 | 0 | 0 | 0 | 0 | 0/0 | 0 | 0/0 | 12 |
| AI05/adaptive | 4 | 0 | 0 | 0 | 0 | 0/0 | 0 | 0/0 | 4 |
| AI05/coverage | 7 | 0 | 0 | 0 | 0 | 0/0 | 0 | 0/0 | 7 |
| AI06/uniform | 0 | 0 | 1 | **11** | 0 | 0/0 | 0 | 0/0 | 12 |
| AI06/adaptive | 0 | 0 | 3 | 7 | 0 | 0/0 | 0 | 0/0 | 10 |
| AI06/coverage | 0 | 0 | 1 | 9 | 0 | 0/0 | 0 | 0/0 | 10 |
| WEB01/uniform | 14 | **5** | 0 | 0 | 0 | 1/1 | 1 | 0/2 | 19 |
| WEB01/adaptive | 3 | 1 | 0 | 0 | 0 | 1/1 | 1 | 0/2 | 4 |
| WEB01/coverage | 6 | 2 | 0 | 0 | 0 | 1/1 | 1 | 0/2 | 8 |
| WEB02/uniform | 12 | 0 | 0 | 0 | 0 | 1/1 | 0 | 0/0 | 12 |
| WEB02/adaptive | 4 | 0 | 0 | 0 | 0 | 1/1 | 0 | 0/0 | 4 |
| WEB02/coverage | 8 | 0 | 0 | 0 | 0 | 1/1 | 0 | 0/0 | 8 |
| WEB03/uniform | 13 | **4** | 0 | 0 | **1** | 0/0 | 0 | 0/0 | 18 |
| WEB03/adaptive | 4 | 0 | 0 | 0 | 0 | 0/0 | 0 | 0/0 | 4 |
| WEB03/coverage | 9 | **5** | 0 | 0 | 0 | 0/0 | 0 | 0/0 | 14 |

说明：
- **AI06 全部采样点落在人工 uncertain 区**：confirmed+not_found 均为 overclaim_on_uncertain（模型双向过度断言：既强行确认也强行否认），appropriate_abstention 仅 1–3/10–12；GT 无边界（单 uncertain 段），边界指标 0/0。
- **AI04 遮挡区 [4000,9000]**：三臂全部在遮挡区判 confirmed（overclaim 5/1/3），0 状态转换 → 2 个 GT 边界全部漏配；adaptive 仅 4 次调用（初始覆盖后无触发）。
- **AI02/AI03/WEB01 的 uncertain 过渡区**：模型要么不触达（uniform/AI02 与 WEB01 全部三臂未触达 [4000,4500]），要么触达后给出确定性结论（AI03 overclaim 1；AI02 adaptive/coverage 各 1 次适当拒答）。全部 8 个 GT 边界均漏配（0/8/臂）：方向兼容规则要求涉及 uncertain 的 GT 边界由非确定类别 transition 承接，而模型从不产出 abstained→confirmed 形式的 transition。
- **AI05/WEB03 明确负向**：AI05 三臂 12/4/7 全部正确 not_found（红色干扰物未致误报）；WEB03 uniform 4 + coverage 5 个 incorrect_decisive（真实域误报，疑与橙红结构件/相似容器有关），adaptive 4 点稀疏采样恰好避开误报帧；WEB03/uniform 另有 1 帧 failed。
- **WEB02 无存在性边界**：GT 单 confirmed 段，边界精度分母为 0（matched_count=0，误差统计 not_applicable），不进入边界精度计算；三臂 12/4/8 全部正确。
- AI01：uniform 1 个 incorrect_decisive（清晰目标上的伪 not_found），adaptive/coverage 各 2 个。

## 6. 分轨汇总（`comparisons/task19-three-scope-verdicts.json`；计数为原始分子，分母见各 score.json 的对应类别分母）

**generated track（AI01–AI06，6 样本；查询同质"红色背包"、预算同质 12；已分析采样点分母 72/39/54）**

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 调用总数 | 72 | 39 | 54 |
| correct_decisive | 53 | 24 | 37 |
| incorrect_decisive | 1 | 2 | 2 |
| appropriate_abstention | 1 | 3 | 1 |
| overclaim_on_uncertain | 17 | 10 | 14 |
| covered/missed confirmed events | 5/0 | 5/0 | 5/0 |
| unreached uncertain segments | 1 | 0 | 0 |
| GT 边界 matched/missed | 0/6 | 0/6 | 0/6 |
| 多余 predicted transition | 7 | 7 | 5 |
| 最大相邻采样间隔（跨样本最大） | 958.334ms | 3375.0ms | 1708.333ms |

**licensed-public track（WEB01–WEB03，3 样本；三个 target query、预算 19/12/18；已分析采样点分母 49/12/30）**

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 调用总数 | 49 | 12 | 30 |
| correct_decisive | 39 | 11 | 23 |
| incorrect_decisive | 9 | 1 | 7 |
| failed_on_determinate | 1 | 0 | 0 |
| appropriate_abstention / overclaim | 0/0（uncertain 分母 0，not_applicable） | 0/0 | 0/0 |
| covered/missed confirmed events | 2/0 | 2/0 | 2/0 |
| unreached uncertain segments | 1 | 1 | 1 |
| GT 边界 matched/missed | 0/2 | 0/2 | 0/2 |
| 多余 predicted transition | 4 | 0 | 2 |
| 最大相邻采样间隔 | 1040.0ms | 6206.2ms | 3103.1ms |

**all-dev（9 样本，仅作为补充；已分析采样点分母 121/51/84）**

| 指标 | uniform | adaptive | coverage |
| --- | --- | --- | --- |
| 调用总数 | 121 | 51 | 84 |
| correct_decisive | 92 | 35 | 60 |
| incorrect_decisive | 10 | 3 | 9 |
| failed_on_determinate | 1 | 0 | 0 |
| appropriate_abstention | 1 | 3 | 1 |
| overclaim_on_uncertain | 17 | 10 | 14 |
| covered/missed confirmed events | 7/0 | 7/0 | 7/0 |
| unreached uncertain segments | 2 | 1 | 1 |
| GT 边界 matched/missed | 0/8 | 0/8 | 0/8 |
| 最大相邻采样间隔 | 1040.0ms | 6206.2ms | 3103.1ms |

零分母项（licensed-public 的 appropriate_abstention / overclaim_on_uncertain / failed_on_uncertain；无边界样本的边界误差统计）一律写 `not_applicable`，未造数。

## 7. Verdict（冻结规则计算；`scores/*/three-arm-comparison.json`）

**公平门口径（重要披露）**：冻结双臂公平门的 `same_target_query` / `same_call_budget` 条件在实现上要求比较范围内取值唯一。generated 范围（查询/预算同质）十条件全部通过；licensed-public 与 all-dev 范围因多查询（3 个 target query）与多预算（12/18/19，任务书预算政策的必然结果）在该两个条件上 FAIL → 冻结实现判 `INVALID_COMPARISON`（如实保留）。逐样本公平门（同查询/同预算在样本内成立）**九样本 × 三对全部通过**（`scores/per-sample/`）。

**generated track（冻结门 PASS）**：
- coverage vs uniform：**TRADEOFF**（fewer_model_calls + more_incorrect_decisive）
- coverage vs adaptive：**NO_IMPROVEMENT**（无严格更好项）
- adaptive vs uniform：**TRADEOFF**（fewer_model_calls + more_overclaim_on_uncertain）
- pack 级（candidate=coverage）：**NO_IMPROVEMENT**（违反：more_incorrect_decisive_vs_uniform、larger_max_sampling_gap_vs_uniform、more_overclaim_on_uncertain_vs_adaptive）

**licensed-public track / all-dev（pack 级）**：均为 **NO_IMPROVEMENT**（larger_max_sampling_gap_vs_uniform、more_incorrect_decisive_vs_adaptive；all-dev 另加 more_overclaim_on_uncertain_vs_adaptive）。

**pooled pairwise verdict**（冻结 compute_verdict 对轨道汇总指标；与逐样本门证据并列披露）：
- generated：coverage-vs-uniform TRADEOFF / coverage-vs-adaptive NO_IMPROVEMENT / adaptive-vs-uniform TRADEOFF；
- licensed-public：coverage-vs-uniform **IMPROVEMENT**（fewer_model_calls，汇总 incorrect 9→7）/ coverage-vs-adaptive NO_IMPROVEMENT / adaptive-vs-uniform IMPROVEMENT；
- all-dev：coverage-vs-uniform IMPROVEMENT / coverage-vs-adaptive NO_IMPROVEMENT / adaptive-vs-uniform IMPROVEMENT。
- 逐样本 verdict：coverage-vs-uniform 在 6/9 样本 IMPROVEMENT（fewer_model_calls），AI01/AI02/WEB03 为 TRADEOFF；coverage-vs-adaptive 九样本全部 NO_IMPROVEMENT（AI04/AI06/WEB01/WEB03 有 more_overclaim 或 more_incorrect）；adaptive-vs-uniform 8/9 IMPROVEMENT。

**边界误差统计**：全部 27 个 (样本,臂) matched_boundaries=0 → 误差统计 `not_applicable`（零分母不造数）；边界类严格更好条件（要求两臂 matched≥1）从未触发。

## 8. 必须逐项披露的样本行为

- **AI01（生成轨道持续正向）**：三臂均确认目标存在，但 uniform 1 个、adaptive/coverage 各 2 个 incorrect_decisive（清晰可见目标上的伪 not_found）——稳定正向但不完美。
- **AI02/AI03（进入/离开边界）**：determinate 区全部正确；[4000,4500] 窄 uncertain 区 uniform 未触达（AI02 unreached=1）、adaptive/coverage 触达后各 1 次适当拒答（AI02）或 1 次 overclaim（AI03）；进入/离开边界 2/2 全部漏配（方向兼容规则）。
- **AI04（遮挡区间过度断言）**：**是，被过度断言**。三臂在遮挡区 [4000,9000] 全部判 confirmed（overclaim 5/1/3），0 状态转换，2 个边界全漏；模型不报告"被遮挡/无法确认"。
- **AI05（红色干扰物误报）**：**未发生误报**。三臂 12/4/7 全部正确 not_found，无伪造目标框。
- **AI06（低照度小目标）**：**未按人工标签拒答，继续过度断言**。三臂 overclaim 11/7/9（confirmed 与 not_found 双向），appropriate_abstention 仅 1/3/1；4/4/2 个多余 transition。
- **WEB01（真实行业正向与状态变化）**：事件覆盖 1/1（确认段被覆盖），但早期"货叉空载"帧被误报为 confirmed（incorrect 5/1/2），[4000,4500] uncertain 区三臂均未触达，2 个边界全漏。
- **WEB02（全程存在、复杂背景与运动）**：三臂 12/4/8 全部正确、0 多余 transition；**无存在性边界，未计入边界精度分母**（matched_count=0，误差统计 not_applicable）。
- **WEB03（真实行业明确负向与相似容器干扰）**：uniform 4 + coverage 5 个 incorrect_decisive（真实域误报）+ uniform 1 帧 failed；adaptive 4 点稀疏采样 0 误报（采样偶然避开，非策略保证）。

## 9. DSH 自主真实域验证会话（`dsh-session/`）

- 全新 `dsh --profile headless`（exit 0，393.827s）；样本 WEB01（阶段 A 冻结）；会话只获媒体路径/目标查询/任务/预算 19/安全要求，未获 GT 与任何评分信息。
- Agent 自主：发现并加载三 Skill → 来源硬门 accepted/user_provided → StepFun 生成 coverage_aware_adaptive 规格（冻结参数，校验 RESULT: VALID）→ trace_temporal 真实 Qwen 调用 **8 次**（初始 4 + 覆盖探索 4 + 细化 0；0 失败/0 拒答/0 重试）→ 报告器独立复算生成 final-report.json。
- 时序证据：8/8 confirmed（0.85–0.95），0 状态转换，最大相邻间隔 6206.2→3103.1ms（目标 1500 因储备耗尽未达成），7 个未充分观测区间；1 条 bbox 混合坐标按契约置 null 的 warning。
- 离线评分（冻结 scorer）：correct 6/8、incorrect 2/8、事件覆盖 1/1、unreached uncertain 1、边界 0/2、调用 8/19。与批量 coverage 臂行为一致：**真实域早期误报是该样本的稳定失败模式（模型语义，非采样策略）**。

## 10. 效率与稳定性

- 调用/耗时：uniform 121 次（analysis 1679.8s）、adaptive 51 次（618.5s）、coverage 84 次（1008.4s）；WEB01 4K 帧单帧约 22s，AI 段约 12s/帧；27 运行 0 失败、0 超时、0 无效 JSON（仅 WEB03/uniform 1 帧 backend failed，如实计入）。
- 最大相邻采样间隔（跨样本最大）：uniform 1040.0ms < coverage 3103.1ms < adaptive 6206.2ms；coverage 在多数样本达到/逼近 1500ms 目标（AI 段 1333–1708ms），长视频 WEB01/WEB03 因储备 4 次用尽未达标（3103.1/2920.0ms）。
- budget_exhausted：uniform 臂在规划点数=预算时为 True（规划截断，非失败）；adaptive/coverage 均未耗尽。

## 11. 测试与回归（`test-results.json` / `verification.json`）

- 任务 19 新测试 **22/22**（22 类要求全覆盖）；
- 回归：任务 18 36/36、任务 17 38/38、任务 16 27/27、任务 04 16/16、任务 06 32/32、M1–M8 10/10、Tier-3 v2 17/17、工作台静态 26/26；
- `git diff --check` 干净；敏感信息扫描 0 命中；冻结数据（任务 07/08/09/16/17/18、Tier-3、app/、scorer/schema/adapter/采样算法/视觉 Prompt）相对 ef9f329 零改动；预注册 31 条目哈希运行后不变；
- 交付验证 **21/21**（`artifacts/task-19/verify_task19.py`）。

## 12. 工程状态与结论

- **工程状态：BASELINE_COMPLETE**（九样本三臂 + 评分 + DSH 会话完整；预注册先于运行；公平门与 verdict 由冻结规则计算）。
- **算法结论（模型效果）**：三范围 pack 级 verdict 全部 **NO_IMPROVEMENT**——当前冻结系统在真实 dev 数据上的核心缺陷是**模型语义校准失败**（uncertain 区过度断言双向、遮挡区不报告无法确认、真实域早期误报）而非采样几何：coverage 修覆盖（触达更多 uncertain/短事件）但模型在被触达处仍过度断言；adaptive 省调用但漏触达；uniform 密采样有最多 incorrect/overclaim 暴露。边界匹配在方向兼容规则下全臂 0/8——**带不确定度的边界产出在该模型下不可用**。
- 失败与过度断言已完整保存为本轮基线证据；**不建议**在修复校准前任何"策略更优"的对外声明。
