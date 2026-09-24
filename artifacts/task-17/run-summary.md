# Task 17 运行摘要 — Evidence Pack 数据契约与时间 Ground Truth 评分器

- 日期：2026-09-22（UTC）
- 任务：建立独立、确定性、CPU-only 的 Evidence Pack 数据契约与时间 Ground Truth 评分器，把"流水线完成 / 证据语义正确 / 采样效率"分开评价；用冻结的任务 16 产物重新评分
- 初始状态：分支 `master`，HEAD `8c962fccc3491bebbb265fd3c7df982a55f84ee1`，工作区干净，恢复 tag `pre-task13-deploy-4c4c3ca` 保留，无 remote，无 Git 锁/进行中 Git 进程
- 真实性等级：**规则测试 38/38 + 六项既有回归全通过 + 任务 16 冻结产物重评分（10 臂，零模型调用）**；全部数字来自真实运行/确定性复算；技术 fixture 结果不外推为真实仓储准确率。

## 1. 实现内容

| 组件 | 变更 |
| --- | --- |
| `schemas/evidence-pack-manifest.schema.json`（新） | Evidence Pack manifest 契约（schema 1.0.0）：pack_id/profile/created_at/frozen_at/samples[]；sample 含 sample_id（唯一）、split(dev/holdout)、source_type(generated/licensed_public/technical_fixture)、媒体相对路径 + SHA-256 + 时长、data_card、target_query、task_type、公开演示/公开 Git 许可、source_provenance（按来源类型条件必填）；**不得内嵌时间真值**；profile=sparkskill-competition-2026 时校验 12 编号与 9/3 split（底层契约不硬编码编号） |
| `schemas/temporal-ground-truth.schema.json`（新） | 时间 Ground Truth 契约（schema 1.0.0）：segments[]（confirmed/not_found/uncertain）、media_sha256、时长、target_query、annotation_version、annotated_at、annotator_id（非敏感）、boundary_tolerance_ms、label_frozen、revision_history（含 after_model_run）、notes；时间线合法性规则（排序/完整覆盖/不重叠/不留隙/正长度/相邻合并/左闭右开+末段含终点）；**不得包含模型字段** |
| `scripts/validate_evidence_pack.py`（新） | 契约校验器：复用 `validate_task_spec.py` 的 JSON Schema 严格子集（不引入 jsonschema）；语义规则（sample_id 唯一、媒体路径安全、条件 provenance、competition profile、GT 时间线、跨文件一致）；结构化问题（code+location+message）；退出码 0/1/2 |
| `scripts/score_temporal_ground_truth.py`（新） | 评分器：显式参数 `--manifest/--predictions/--ground-truth/--out/[--comparison]`；8 项硬门（样本一致/媒体哈希冻结/查询一致/时长一致/GT 时间线合法/时间戳范围/provenance 自洽/预测形态）；七类采样点计数（每项分母=对应类别分母，0 分母写 `not_applicable`）；事件覆盖；transition 一对一最大匹配（Kuhn，方向兼容规则：decisive→decisive 不得匹配涉及 uncertain 的边界）；效率指标；双臂公平比较（10 条件 fairness gate + attestation）与四类 verdict；holdout GT 只进摘要不进输出；输出确定性（无时间戳/绝对路径，落盘前凭据自检） |
| `scripts/test_temporal_ground_truth_scoring.py`（新） | 测试套件：34 个确定性 fixture 用例 + 4 项一致性测试（分类规则与 adaptive_sampler 一致/确定性/输入只读/输出卫生），断言具体字段与具体计数 |
| `artifacts/task-17/fixtures/`（新） | `build_fixtures.py` 确定性生成 34 个用例（manifest/GT/构造 temporal-evidence/占位媒体/expected.json）；占位二进制仅用于 SHA-256 契约测试，明确不是真实视频 |
| `artifacts/task-17/contracts/`（新） | 任务 16 fixture 的 manifest 与 5 份派生 GT（`build-task16-ground-truth.py`：present→confirmed、absent→not_found、present_low_contrast→uncertain；容差 250ms）、数据卡、competition profile 示例（占位值） |
| `artifacts/task-17/rescored-task16/`（新） | prediction-set、comparison-spec、10 臂 score.json/score.md/input-hashes.json、comparison.json/md |
| `docs/plans/2026-09-22-evidence-pack-ground-truth-scoring-design.md`（新） | 设计文档（15 类必需要素） |

## 2. 测试结果

- **任务 17 新测试**（`scripts/test_temporal_ground_truth_scoring.py`）：**38/38 通过**（34 fixture 用例 + X1 分类规则一致性【核对 100 个冻结任务 16 时间线条目，0 不一致】+ X2 确定性【两次运行逐字节一致】+ X3 输入只读 + X4 输出卫生）。完整结果：`artifacts/task-17/test-results.json`。
- **回归（本任务重跑，全部通过）**：任务 16 时序证据 **27/27**；任务 04 视频规则 **16/16**；任务 06 多视频规则 **32/32**；M1–M8 媒体来源契约 **10/10**；v2 评分器回归 **17/17**；工作台静态测试 **26/26**（未修改 `app/`）。
- **交付验证**：`artifacts/task-17/verify_task17.py` **24/24**（`verification.json`）。

## 3. Task 16 冻结产物重评分（同预算 12，真实 Qwen 输出，零新模型调用）

公平性：fairness gate **10/10 条件通过**（相同样本/媒体哈希/查询/GT 版本/模型后端/预算、无单侧重试或额外上下文【依据任务 16 fairness 块声明】、输入完整、同 evidence_nature、GT 无运行后修订）。

| 场景 | 指标 | uniform | adaptive |
| --- | --- | --- | --- |
| present-throughout | correct_decisive / 调用 | 12/12 / 12 | 4/4 / **4** |
| appear-midway | correct_decisive / 匹配边界 / 最大误差 / 调用 | 12/12 / 1 / 54.167ms / 12 | 7/7 / 1 / **33.333ms** / **7** |
| disappear-midway | correct_decisive / 匹配边界 / 最大误差 / 调用 | 12/12 / 1 / 237.5ms / 12 | 7/7 / 1 / **33.334ms** / **7** |
| reappear | correct_decisive / 匹配边界 / 容差内 / 最大误差 / 调用 | 12/12 / 3 / **3** / 250.0ms / 12 | 12/12 / 3 / 2 / 291.666ms / 12 |
| abstain-zone | correct_decisive / overclaim_on_uncertain / 匹配边界 / 漏边界 / 未触达 uncertain / 调用 | 9/9 / **3** / 0 / 2 / 0 / 12 | 4/4 / 0 / 0 / 2 / **1** / **4** |

**逐场景语义事实**：

1. **abstain-zone（核心冲突暴露）**：uniform 臂在 GT uncertain 区间（3000–5000ms）的 3 个采样点全部得到真实 Qwen 确定性负面（not_found）→ `overclaim_on_uncertain = 3/3`；两臂的 decisive→decisive 预测 transition 均**不能**匹配 confirmed→uncertain / uncertain→confirmed 的 GT 边界（方向不兼容）→ 各漏 2 个 GT 边界；adaptive 臂 4 个初始采样点全部落在不确定区之外 → `unreached_uncertain_segments = 1`（初始覆盖盲区被量化）。
2. **completed ≠ 语义正确**：10 个臂全部 `execution_status=completed`，而语义计数暴露上述冲突（`semantic_score_status=scored` 与 execution_status 并排输出）。
3. **adaptive 初始覆盖盲区**：abstain-zone adaptive 0 次细化、未发现不确定区间——策略真实边界，如实记录（不调参到只剩漂亮样本）。

**Pack 级 verdict：TRADEOFF**（由评分器从冻结产物计算，未预设）：

- 严格更好项：`fewer_model_calls`（34 vs 60）、`smaller_mean_boundary_error`（138.333 vs 150.0 ms）；
- 回归项：`more_unreached_uncertain_segments`（1 vs 0）；
- 非回归条件：incorrect_decisive 0=0、overclaim 0≤3、missed events 0=0、missed boundaries 2≤2 均满足，唯 unreached uncertain 被违反；
- **任务 16 旧 `IMPROVEMENT` 是旧口径历史**（`artifacts/task-16/comparison.json` 未篡改）：旧口径看"最终状态正确 + 边界不劣 + 调用更少"，新严格口径把 uncertain 区域的拒答/触达纳入非回归条件后 verdict 变为 **TRADEOFF**——adaptive 在合成 fixture 上确实省调用且平均边界误差更小，但以未触达 uncertain 区间为代价；且 uniform 臂的 3 次过度断言说明"最终状态正确"曾掩盖语义冲突。

## 4. 边界遵守

- **未调用任何模型**（StepFun/Qwen/Ollama/MiniMax-H3/DSH headless 均未调用）；未抽帧、未生成视频、未下载素材；未联网；未安装依赖；
- 未停止/重启/干预任何服务（工作台静态测试由仓库既有测试脚本自行管理临时只读服务，非本项目服务）；
- 未修改 `artifacts/task-16/`（只读引用其冻结预测与 GT；派生 GT 由独立脚本生成，源文件零改动——V17 验证通过）；
- 未修改任务 07/08/09、Tier-3 任务集与 v1/v2 评分器（SHA-256 与文档声明一致）、`app/` 与工作台脚本、Task 16 sampler/executor/comparison；
- 未创建第四个 Skill；未接入或运行用户 holdout；未虚构媒体、许可、Prompt、标签或评分结果；
- 8 AI + 4 真实视频 Evidence Pack **尚未上传**：competition profile 示例只验证契约与编号/split/来源合规（占位值明确标注），**不得声称真实域评分已完成**。

## 5. 产物索引（artifacts/task-17/）

`contracts/`（manifest、GT 派生脚本与 5 份 GT、数据卡、competition profile 示例、README）、`fixtures/`（34 用例 + build_fixtures.py + README）、`rescored-task16/`（prediction-set、comparison-spec、10 臂 score.json/score.md/input-hashes.json、comparison.json/md）、`test-results.json`（38/38）、`comparison.json`、`comparison.md`（rescored-task16 副本，SHA-256 相同）、`run-summary.md`（本文件）、`verification.json`（24/24）、`verify_task17.py`。
