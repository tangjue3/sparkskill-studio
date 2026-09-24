# 设计文档 — dev Evidence Pack 三策略真实基线评测（任务 19B）

- 日期：2026-09-22
- 状态：阶段 A（预注册冻结）；实现与真实评测见阶段 B 及 `artifacts/task-19/`
- 基线：分支 `master`，HEAD `ef9f3296c6b8c9f7aa62125df87f8aba86abae96`（任务 18 提交），工作区干净，无 remote
- 关联：`docs/plans/2026-09-22-temporal-evidence-adaptive-sampling-design.md`（任务 16）、`docs/plans/2026-09-22-evidence-pack-ground-truth-scoring-design.md`（任务 17）、`docs/plans/2026-09-22-coverage-aware-adaptive-sampling-design.md`（任务 18）、`schemas/evidence-pack-manifest.schema.json`、`schemas/temporal-ground-truth.schema.json`、`scripts/score_temporal_ground_truth.py`、`scripts/task18_scorer_adapter.py`、三个 Skill 的 `SKILL.md`、`artifacts/task-18/`

---

## 0. 本任务的定位

任务 16/17/18 在**合成技术 fixture** 上建立了三策略（uniform / adaptive_coarse_to_fine / coverage_aware_adaptive）的契约、预算、provenance、时序证据、Ground Truth 评分器与 verdict 纪律，并明确记录"用户 Evidence Pack 未接入前不得声称真实域效果"。本任务（任务 19B）是第一次把该冻结系统应用到**用户真实交付的 dev Evidence Pack**（6 段 MiniMax-H3 生成受控测试视频 + 3 段 Pexels licensed-public 真实行业视频）上，做**当前冻结系统的真实基线评测**。

**本任务必须先测量，不能校准。** 不得修改视觉 Prompt、采样算法、证据分类、报告规则或评分器来改善结果；失败与过度断言是本轮需要保存的基线证据。工程状态（baseline completion）与模型效果 verdict 严格分离（§13）。

## 1. 为什么先做未校准基线

1. **系统已冻结，且冻结状态就是被评测对象**：视觉 Prompt、三种采样算法、VisualTaskSpec schema、temporal evidence 分类、report generator、任务 17 scorer、任务 18 adapter 均处于冻结状态；本轮唯一正当操作是"用冻结系统测量真实 dev 数据"。
2. **校准需要基线作为对照锚点**：任务 16/17/18 已在合成 fixture 上多次观察到"Qwen 触达 uncertain 区域后过度断言而非拒答"（overclaim_on_uncertain）与"确定性负面 vs 人工 uncertain 标签"的冲突。在真实 dev 数据上量化同一模式（AI04 遮挡区间、AI06 低照度小目标）是任何后续校准（任务 20 候选）的前提——没有基线就没有"校准是否有效"的判据。
3. **先测量防止对指标过拟合**：若边测边调（改 Prompt/阈值/预算/标签），得到的数字既不是系统真实能力，也不构成可复算的基线；预注册 + 冻结 + 单次运行的纪律保证基线证据可被第三方复算与质疑。
4. **失败与过度断言是有效证据**：本轮明确把 AI05/WEB03 的负向误报、AI06 的拒答失败、AI04 的遮挡区过度断言、WEB02 的无边界鲁棒性作为必须逐项披露的观测，不得只展示表现好的样本。

## 2. transfer-safe card 与冻结源卡的 lineage

- 唯一标签来源：dev 包内九张 **transfer-safe card**（`data-cards/transfer-safe/<ID>.json`，由任务 19A 从本地冻结源 YAML 卡 `data-cards/dev/<ID>.yaml` 确定性派生）。源 YAML 卡不随包传输、留在用户本地，本任务不接触。
- 每张 transfer-safe 卡携带 `lineage`：`source_card_path`（`data-cards/dev/<ID>.yaml`）、`source_card_sha256`、`derived_at`、`removed_or_normalized_fields`（唯一内容级处理：删除 WEB01 notes 中两处超出 dev 白名单的编号范围引用 + YAML 行内注释不进入 JSON）、`core_fields_unchanged: true` 声明。
- 摄验（`scripts/task19_ingest.py`）逐卡核验：派生卡哈希 == `dev-freeze.sha256` == `transfer-manifest.json.derived_card_hashes`；`lineage.source_card_sha256` == `manifest.source_card_hashes`；`core_fields_unchanged == true`；卡片 `media.sha256` == 实际视频 SHA-256。
- 卡片以字节 identical 方式复制到 `artifacts/task-19/ingestion/（内部留档）data-cards/`（哈希复核）；**原卡与 dev 包只读，不被修改**。

## 3. Ground Truth 如何从卡片确定性派生

`scripts/build_task19_ground_truth.py` 对每张卡执行纯函数派生（无模型、无网络、确定性输出）：

1. **时间线来源**：卡片 `expected_timeline`（总控 2026-09-22 人工观察；`reason` 为原人工原因，逐段保留）。
2. **媒体身份**：`media_sha256` 取卡片值（小写）；`media_duration_ms` 取 **cv2 实测时长**（与流水线 `extract_frames.read_metadata` 同一公式 `round(frame_count/fps*1000, 3)`）——WEB01 实测 18551.867ms（卡片标称 18560）、WEB02 实测 10243.567ms（卡片标称 10260），其余七段与标称一致。
3. **边界容差**：卡片 `task.boundary_tolerance_ms`（1000ms）。
4. **标注元数据**：`annotation_version=task19-dev-gt-1.0.0`（九份一致，公平门可观测）、`annotated_at=2026-09-22`、`annotator_id=总控（人工观察）`（非敏感）、`label_frozen{frozen:true, frozen_at:2026-09-22T13:12:24Z（dev 包素材冻结时刻 UTC）, derived_from:卡路径+源卡哈希}`、`revision_history:[]`（无修订；派生不是标签修订）。
5. **契约校验**：每份 GT 必须通过任务 17 冻结校验器 `validate_ground_truth`（Schema 严格子集 + 时间线七条 + 语义规则），否则派生失败（退出码 1）。
6. 输出九份 GT（`artifacts/task-19/ground-truth/（内部留档）<ID>.json`）与 `normalization-report.json`（逐样本：来源卡哈希、原始区间、合并后区间、状态覆盖未改变证明、边界语义未新增证明、人工原因保留清单、派生 GT 哈希）。

## 4. 相邻同状态片段如何规范化合并

任务 17 GT 契约第 5 条要求"相邻相同状态必须合并"。dev 包九张卡中两张存在相邻同状态区间：

| 样本 | 卡片原始区间 | 派生 GT 区间 | 处理 |
| --- | --- | --- | --- |
| AI06 | uncertain [0,6000] + uncertain [6000,10125] | uncertain [0,10125] | 合并；两段原人工原因以"；"连接完整保留 |
| WEB02 | confirmed [0,3000] + confirmed [3000,10260] | confirmed [0,10243.567] | 合并 + 末段终点对齐实测时长；两段原人工原因完整保留 |

其余七张卡（AI01/AI02/AI03/AI04/AI05/WEB01/WEB03）无相邻同状态区间，GT 区间与卡片逐段一致（WEB01 仅末段终点由 18560 对齐为实测 18551.867）。

**结构规范化的不变式（每样本在派生时确定性校验，任一违反即失败）**：

- **状态覆盖未改变**：在实测媒体范围 [0, measured_duration_ms] 内，按状态累计时长前后一致（卡片标称时长超出实测时长的部分在媒体中不存在，不属于任何状态覆盖——WEB01/WEB02 已按此口径比较并记录）；
- **边界语义未新增**：状态变化点集合（右段 start_ms）前后完全一致——合并只消除"同状态相邻"的伪边界可能，不新增、不删除任何状态转换语义；
- **原人工原因保留**：合并段的原因为原各段原因的"；"连接；未合并段原因原样保留；
- **时间线合法性**：从 0 开始、覆盖到实测终点、不重叠、不留隙、每段长度为正。

这属于**结构规范化**，在阶段 A（任何模型运行之前）完成并冻结；不得写成模型运行后改标签——GT 的 `revision_history` 为空且 `label_frozen.frozen=true`，公平门 `ground_truth_not_revised_after_run` 全程可验证。

## 5. Ground Truth 与模型执行如何隔离

- **目录隔离**：GT 只在 `artifacts/task-19/ground-truth/（内部留档）`；模型执行只消费 `artifacts/task-19/execution-manifests/（内部留档）` 与 `artifacts/task-19/predictions/（内部留档）`。runner 与 trace_temporal 的代码路径不读取 GT 目录。
- **execution manifest 标签隔离**：每样本每臂在执行前生成 execution manifest，只允许包含：sample ID、media path/hash/duration、target query、task type、sampling strategy 与预算、安全限制和输出要求。**不得包含** expected final status、expected timeline、difficulty、Ground Truth segment、boundary location、scorer 结果或任何提示模型答案的字段。专项测试（T09）对 27 份 execution manifest 与 27 份 VisualTaskSpec 做禁用键扫描。
- **采样决策隔离**：三种采样策略的决策输入只有已观测帧证据与策略几何（任务 16/18 既有性质）；任务 18 专项测试 C 类已断言 GT 不进入采样决策，本任务回归复用。
- **评分隔离**：任务 17 冻结 scorer 的 `--ground-truth` 是必显参数；评分只在全部预测落盘后执行；scorer 输出（score.json / comparison）经 `assert_output_safe` 净化。
- **DSH 自主会话隔离**：会话提示词只含媒体路径、目标查询、任务、预算与安全要求；明确禁止读取任何 Ground Truth 文件（§12）。

## 6. 三个 arm 的公平条件

同一样本三臂必须满足（任一不满足 → 该对比较 `INVALID_COMPARISON`，由任务 17 冻结 fairness gate 十条件机检）：

1. 相同样本集合与相同视频（九样本全量；同一 manifest 样本，硬门 G2 实际计算媒体 SHA-256 三方一致）；
2. 相同 target query（卡片 `task.target_query` 逐字传入 spec，硬门 G3 三方一致）；
3. 相同 Ground Truth 版本（同一批 GT 文件、`annotation_version` 一致、无运行后修订）；
4. 相同 Qwen 模型与 Ollama 后端（`modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`，本地 Ollama；同一 `trace_temporal.py` 代码路径与 `frame_class` 分类规则）；
5. 相同硬调用预算（每样本三臂同一 `max_model_calls`，由 §7 政策从媒体时长确定性派生）；
6. 相同输出格式、超时（单帧 300s）与错误处理；
7. 无单侧重试、无额外 Prompt、无人工纠正、不删除失败样本（调用方 `fairness_attestation` 显式声明；runner 实现保证：每臂每样本一次 subprocess 运行，失败原样保存）；
8. 相同 `evidence_nature`（三臂全部 `real_model_output`——真实 Qwen 调用，禁止与构造证据混合）。

## 7. 每样本预算政策（只依赖媒体时长与通用政策）

**冻结公式**（阶段 A 预注册，先于任何模型调用；不得依据事件数量、边界位置、expected status、difficulty 或先跑结果调整）：

```text
max_model_calls(sample) = clamp(ceil(media_duration_ms / 1000), 12, 24)
```

| 样本 | 实测时长 (ms) | 预算 |
| --- | ---: | ---: |
| AI01 | 8000.000 | 12 |
| AI02 | 10125.000 | 12 |
| AI03 | 10125.000 | 12 |
| AI04 | 10125.000 | 12 |
| AI05 | 8000.000 | 12 |
| AI06 | 10125.000 | 12 |
| WEB01 | 18551.867 | 19 |
| WEB02 | 10243.567 | 12 |
| WEB03 | 17520.000 | 18 |

政策理由：约"每秒 1 次调用"的通用密度，下限 12 保证 adaptive/coverage 的初始覆盖（4）+ 覆盖储备（4）之后仍有不少于 4 次边界细化预算，上限 24 控制 4K 长视频（WEB01）的总调用成本。时长取自摄验阶段 cv2 实测值（与流水线同一公式），在预注册 `sample-manifest.json` 中逐样本冻结。

**arm 参数（通用政策常数，不随样本内容变化）**：

| arm | strategy | 参数 |
| --- | --- | --- |
| uniform | `uniform` | `max_model_calls`=预算；`interval_ms = duration_ms / budget`、`max_frames = budget`（网格点数超预算时 `plan_sample_times` 退化为区间内均匀取样，恰好预算个点、含两端点） |
| adaptive | `adaptive_coarse_to_fine` | `max_model_calls`=预算；`initial_coverage_samples`=4；`target_boundary_precision_ms`=500；`max_refinement_rounds`=6；触发器 state_change/abstained/low_confidence/failed |
| coverage | `coverage_aware_adaptive` | `max_model_calls`=预算；`initial_coverage_samples`=4；`coverage_gap_target_ms`=1500；`coverage_call_reserve`=4；`target_boundary_precision_ms`=500；`max_refinement_rounds`=6；触发器同上 |

uniform 的 interval 派生是执行层实现（由预注册政策公式确定性计算），不修改任何预注册文件；三臂预算恒等（公平门 `same_call_budget` 的可观测基础）。

## 8. arm 执行顺序和热状态控制

- **样本顺序**：按 sample_id 字典序 AI01→AI06→WEB01→WEB03 固定执行（预注册冻结；不按难度或预期表现排序）。
- **臂顺序轮换**：样本索引 i（从 0 开始）的臂执行顺序为 `[uniform, adaptive, coverage]` 循环左移 i 位：
  - AI01（i=0）：uniform → adaptive → coverage
  - AI02（i=1）：adaptive → coverage → uniform
  - AI03（i=2）：coverage → uniform → adaptive
  - AI04（i=3）：uniform → adaptive → coverage
  - ……如此循环
- **热状态控制**：轮换使模型加载/推理热态、Ollama 驻留状态与系统缓存的"先发劣势"在三个臂间均匀分布；任一臂在九样本中各处于三种顺序位置各 3 次（确定性均衡）。
- **统一 warm-up**：批量开始前执行一次 warm-up（对任务 18 冻结 technical fixture 的一帧做一次真实 Qwen 调用，使模型驻留），**不计入任何 arm**，且**不使用任何 dev 标签**（warm-up 目标是合成 fixture，与 dev 样本和 GT 无关）。warm-up 记录于 resource-gate 与 run-summary。
- 顺序效应作为已知限制记录（单轮运行，不构成统计结论）。

## 9. 失败、超时、重试和无效 JSON 规则

- **无单侧重试**：每样本每臂一次 `trace_temporal.py` subprocess 运行；任何失败（subprocess 非零退出、抽帧失败、规格错误）原样记录为该 (sample, arm) 的执行事实，不重跑、不换参数、不删除。
- **超时**：单帧 Qwen 调用超时 300s（与任务 18 真实评测一致）；超时帧由既有链路记为 `frame_status=failed` 并保留 `abstention_reason`（非敏感原因），不中断其他帧。
- **无效 JSON / 契约拒绝**：模型返回无法解析或不符合证据 schema 时，按既有规则该帧 failed 并如实记录；**不得伪造或修补模型输出**（任务 05/06 既有纪律）。
- **资源守卫阻塞**：MemAvailable 低于执行器阈值（40 GiB）或 Ollama 不可达时，未执行的调用不计为真实视觉调用，全部帧 failed 并记录真实原因；该 (sample, arm) 的 `evidence_nature=resource_blocked`，评分时硬门 G7 按资源阻塞口径校验。若批量执行中发生资源阻塞，保存已完成数据、停止发起新调用、报告中断点（不停止用户服务）。
- **失败计入结果**：failed 采样点进入七类计数（`failed_on_determinate` / `failed_on_uncertain`）与分母，不删除、不折算。

## 10. generated 与 licensed-public 为什么分轨报告

- **来源性质不同**：AI01–AI06 是 MiniMax-H3 生成的受控测试视频（干净场景、受控光照、目标明确）；WEB01–WEB03 是 Pexels licensed-public 真实行业视频（复杂背景、运动模糊、真实光照、相似干扰）。两者难度分布与失败模式不可比，混合平均会同时高估和低估。
- **样本量不同**：generated 6 段、licensed-public 3 段；真实轨道只有三段，只能写"小样本真实域观察"，不能写真实仓储准确率、统计显著性 or 生产可用性。
- **许可边界不同**：AI 段标注为 MiniMax-H3 生成受控测试视频；WEB 段标注为 Pexels licensed-public（原始文件不得进入公开 Git，对外仅详情页链接/SHA-256/派生关键帧）。分轨使许可声明可以精确附加。
- **汇总规则**：分别输出 generated track（AI01–AI06）、licensed-public track（WEB01–WEB03）与全体九样本汇总（仅作为补充）；任何比例同时给原始分子/分母，零分母写 `not_applicable`；pairwise 与 pack-level verdict 分别按 all-dev、generated、licensed-public 三个范围计算并分别报告。

## 11. 真实素材许可与 Git 边界

- dev 包位于 Git 仓库之外（`<DEV_EVIDENCE_PACK_ROOT>`），本任务只读使用；**原始视频不得复制进项目仓库或提交 Git**。
- 九段视频 `public_repo_allowed=false`（AI 段按卡片设定；WEB 段受 Pexels License 限制）；`public_demo_allowed` 仅 WEB01–WEB03 为 true（且须标注 Pexels licensed-public 与作者）。
- 仓库内只保存：小型派生关键帧缩略图（JPEG，长边 ≤640，每 (sample, arm) 一张，由 cv2 从真实抽取帧确定性生成）、证据 JSON、模型原始返回、评分与比较产物、哈希清单。
- 执行期用**仓库内只读符号链接农场**（`artifacts/task-19/ingestion/（内部留档）media/<sample_id>.mp4` → 仓库外真实视频）满足 manifest 媒体路径契约（相对路径、项目根内）与 trace_temporal 路径安全（授权根=项目根）；链接不复制视频内容、不提交 Git（`.gitignore` 排除），评分器硬门 G2 与公平门 `same_media_hash` 均解析到同一真实文件。
- 对外声明红线：不得把 AI 段写成真实监控/客户数据；不得公开服务器地址、用户名或凭据；不得声称接入 NVIDIA 官方 Skills。

## 12. DSH 自主会话范围

三臂批量评测完整结束且资源门槛仍满足后，启动**一个全新 DSH headless 会话**（`dsh --profile headless`）：

- **自主验证样本在阶段 A 冻结**（看到任何预测结果之前）：**WEB01**（licensed-public dev 样本）。选择依据（设计期理由，非结果驱动）：WEB01 的人工时间线包含真实域状态转换（not_found→uncertain→confirmed，约第 4 秒叉车取出托盘），是 licensed-public 轨道中唯一同时覆盖"事件覆盖 + 边界 + 真实复杂背景"的样本；WEB02（无存在性边界）与 WEB03（明确负向）的行为已由三臂批量覆盖。
- **会话只获得**：明确的 media path（仓库内链接路径）、target query（叉车货叉上的托盘周转箱）、用户任务（受控视觉证据抽取自主任务）、采样预算（19 次，按 §7 政策）与安全要求（证据不足必须拒答、禁止编造、禁止读取 GT）。
- **会话不得获得**：Ground Truth、expected status、expected timeline、评分结果。
- **要求 Agent 自主**：发现并加载三个 Skill → StepFun（文本链路）生成合法 VisualTaskSpec（strategy=coverage_aware_adaptive，预注册冻结参数）→ 本地 Qwen Vision 分析真实视频 → 生成 provenance / temporal evidence / 报告 → 结束后由离线 scorer 评分。
- **禁止用外部脚本串联冒充 Agent 自主执行**；保存会话 reasoning 摘要、Skill 发现、工具调用、规格、原始返回、关键帧、报告与离线评分。
- 会话产物落盘 `artifacts/task-19/dsh-session/（内部留档）`；会话评分单独报告，不与三臂结果混合平均。

## 13. baseline completion 与模型效果 verdict 的区别

| 维度 | 含义 | 取值 |
| --- | --- | --- |
| **工程状态**（baseline completion） | 九样本三臂真实运行、评分与 DSH 会话是否完整执行 | `BASELINE_COMPLETE` / `PARTIAL`（真实运行不完整）/ `INVALID_EVALUATION`（隔离、哈希、公平或冻结硬门失败） |
| **模型效果 verdict** | 由冻结规则从指标计算的算法结论 | `IMPROVEMENT` / `TRADEOFF` / `NO_IMPROVEMENT` / `INVALID_COMPARISON`（按 all-dev / generated / licensed-public 三个范围分别计算） |

工程状态独立于算法结果：即使三臂评测完整执行（`BASELINE_COMPLETE`），模型效果 verdict 完全可能为 `NO_IMPROVEMENT` 或 `TRADEOFF`（漏检、过度断言、未触达 uncertain 都是合法基线证据）。verdict 纪律沿用任务 17/18 冻结规则：效率不能抵消语义错误；增加 uncertain overclaim、漏检事件、漏边界或未触达 uncertain 时不能判全面 `IMPROVEMENT`。

## 14. 资源守卫

正式运行前与每个阶段之间核验（任务书第十节；结构化记录于 `artifacts/task-19/resource-gate.json`）：

1. H3 保持停止（:8000/:8010 无监听、无生成类进程、无用户活跃 WebUI 任务）；
2. `MemAvailable` 连续三次 ≥ 45 GiB；
3. Ollama 可达（`/api/tags` 200）；
4. 无外部 Qwen 消费者（`/api/ps` 无已加载模型）；
5. DSH 正常（`dsh --version` 含 0.1.5）；
6. Git 工作区符合预期（无锁、无非预期改动）；
7. 预注册哈希一致（frozen-hashes.json 全量重算 + 阶段 A 提交 blob 比对）。

用户启动 H3 或出现外部消费者时：不再发起新模型调用、让当前调用安全结束、保存已完成数据、不停止用户服务、报告中断点。本任务不授权停止或重启 H3，不授权修改任何服务配置；Qwen 按需加载，任务结束后允许自然过期，不强制卸载。

## 15. 测试、回归、冻结范围

**新增确定性测试**（`scripts/test_task19_dev_pack.py`，覆盖任务书第十二节 22 类）：dev 包只含九个白名单 ID；transfer manifest 哈希；视频与卡片哈希；source-card lineage；transfer-safe 卡核心字段；GT 确定性转换；相邻同状态规范化；规范化不改变状态覆盖；execution manifest 不含标签；预算只依赖媒体时长；三臂公平门；track 分类；无边界样本不进入边界精度分母；generated/licensed-public 分轨汇总；失败与超时计入结果；零分母 `not_applicable`；原始视频不在 Git；非白名单编号拒绝；输入只读；输出无凭据与敏感绝对路径（仓库外路径）；预注册哈希在运行后不变；scorer 与实现冻结文件零改动。

**回归（全部重跑并记录）**：Task 18 36/36、Task 17 38/38、Task 16 27/27、Task 04 16/16、Task 06 32/32、M1–M8 10/10、Tier-3 v2 17/17、工作台静态 26/26；`git diff --check`；敏感信息扫描；冻结文件完整性。

**冻结零改动**：`artifacts/task-07|08|09|16|17|18/`、`evals/tier3/evals.json`、Tier-3 v1/v2 评分器与 PASS 条件、任务 17 scorer/schema/validator/测试、任务 18 adapter/runner/预注册、三个 Skill 的视觉 Prompt/采样算法/证据分类/报告规则、`app/` 与工作台脚本、Tier-3 冻结数据、dev 数据包（仓库外，只读）。

**允许修改**：任务 19 设计文档与预注册；dev card/manifest/GT 的确定性转换与验证脚本；任务 19 runner、测试与 scorer 调用适配；`artifacts/task-19/`；与实际结果直接相关的 README、PROJECT_CONTEXT、BENCHMARK、DEVELOPMENT_STATUS、REPRODUCTION、OPTIMIZATION_NOTES 与 Skill BENCHMARK 文档。

## 16. 非目标与对外声明红线

- 不修改视觉 Prompt、置信度/拒答规则、三种采样算法、VisualTaskSpec schema、temporal evidence 分类、report generator、任务 17 scorer、任务 18 adapter、DSH/StepFun/Ollama 配置；运行暴露实现缺陷时保存证据并停止受影响部分，**不在本轮修复后重跑**。
- 不修复 dev 失败、不开始校准（任务 20 候选）、不做未见集（holdout）测试、不更新工作台、不录屏、不写文章、不推送 GitHub。
- 不声称真实仓储准确率、统计显著性 or 生产可用性；licensed-public 轨道只有三段，只写"小样本真实域观察"。
- 不声称任意短事件必检、不声称实时视频监控/跨摄像头身份追踪/StepFun 视觉识别。
- 不安装依赖、不联网下载、不修改配置或凭据、不添加 remote、不 push、不擅自启停任何服务。
- 不搜索、要求或推测未交付（盲测）数据；不遍历用户主目录寻找其他视频。
