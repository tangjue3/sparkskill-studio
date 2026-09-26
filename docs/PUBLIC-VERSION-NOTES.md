# docs/PUBLIC-VERSION-NOTES.md — Task 29 公开候选：公开版与内部留档版的关系

> **本文件为公开候选的关键说明文档**，描述：哪些内容随公开仓库发布、哪些仅为内部留档、可在公开版中复现的数字与仅基于内部冻结数据的可用数字的边界，以及脱敏重写记录与公开版的停止门。
> 配套文档：`docs/REPRODUCTION.md`（复现说明）、`BENCHMARK.md`（Tier-3 历史）、`README.md`（主说明）、`PROJECT_CONTEXT.md`（长期上下文）。
>
> **2026-09-24 勘误重建**：Task 29 补充审计（`任务29补充-公开候选勘误与历史审计报告.md`）发现初版候选存在"敏感字面值出现在本文件与构建器禁入模式中、与 0 命中声明矛盾"等问题。本版本已清除全部敏感字面值（改以占位符/正则等价形式描述），并**重建为全新的独立 Git 根**（旧候选提交存档于 `任务29-inspect/task29-candidate-staging-archive.bundle`，仅本地内部留档，不作为发布源）。本文件的当前版本即发布口径。

---

## 1. 收录范围（公开版含）

公开候选 tree `sparkskill-studio-public-candidate/`（独立 Git 根，与内部留档版无历史继承）包含以下类别的内容：

| 类别 | 内容 | 备注 |
| --- | --- | --- |
| **代码：3 个自研 Skill** | `.dsh/skills/{task-to-skill-compiler, visual-evidence-extractor, evidence-report-generator}/` | SKILL.md / skill-card.md / evals/evals.json / references/ / scripts/ / BENCHMARK.md |
| **Schema 契约** | `schemas/{visual-task-spec, evidence-pack-manifest, temporal-ground-truth}.schema.json` | 任务 17 Evidence Pack 契约 |
| **脚本与测试** | `scripts/*.py`（49 个；含构建器/服务/测试/校验/评分/适配层） | 纯标准库（除 OpenCV 与 Ollama 调用）；测试套件按本次实测结果标注 |
| **工作台前端** | `app/`（HTML/CSS/JS，零依赖） | demo-manifest.json 由公开版构建器重新生成 |
| **任务 16 完整产物** | `artifacts/task-16/`（fixtures、dsh-session、comparison、test-results、verification、run-summary） | 规则测试 27/27；uniform vs adaptive 对照；DSH 自主会话 |
| **任务 17 部分产物** | `artifacts/task-17/` 的 comparison / run-summary / test-results（34/34）/ verification / contracts 子集 / fixtures t01–t29+t28b / rescored-task16 | 排除 holdout 同名 fixture（t30-t33）、build_fixtures.py、verify_task17.py、competition-profile-example.json |
| **任务 18 完整产物（除 real-qwen）** | `artifacts/task-18/` 的 fixtures / preregistration / deterministic / dsh-session / run-summary / known-limitations / verdict / verification / test-results / three-arm-comparison / resource-gate / resource-gate-rerun / h3-shutdown-record / contracts | 排除 `real-qwen/`（287 份原始模型返回为内部留档）；verdict 与评分结论已收录 |
| **任务 07/08/09 比较摘要** | `artifacts/task-07/{comparison.json, run-summary.md}`、`artifacts/task-08/{comparison.json, run-summary.md}`、`artifacts/task-09/`（29 文件） | 完整评分器回归测试 17/17 通过；v1/v2 评分器 SHA-256 与内部留档版一致 |
| **任务 19 摘要** | `artifacts/task-19/{run-summary.md, known-limitations.md, verification.json, comparisons/}` | 原始摄验/GT/执行/评分产物为内部留档 |
| **任务 21 勘误** | `artifacts/task-21/errata/task20-errata.md` | 任务 20 原始产物为内部留档 |
| **任务 25 摘要** | `artifacts/task-25/run-summary.md` | 原始产物为内部留档 |
| **任务 26C 摘要** | `artifacts/task-26c/STOP-REPORT.md` | 任务 26C 唯一公开的"脱敏版"摘要 |
| **StepFun/GDINO 摘要** | `artifacts/stepfun-vision-gate/run-summary.md`、`artifacts/detect-gdino-crosscheck/analysis/run-summary.md` | 详细产物为内部留档 |
| **根级文档** | `README.md`、`PROJECT_CONTEXT.md`、`BENCHMARK.md`、`LICENSE`、`NOTICE`、`.gitignore`、`.interface-design/system.md` | Apache-2.0 LICENSE；公开版权归 `tangjue3`（Task 30 经用户授权完成权属署名变更；Apache-2.0 标准正文未动，仅附录版权占位行填写） |
| **docs/** | `docs/REPRODUCTION.md`、`docs/OPTIMIZATION_NOTES.md`、`docs/SMOKE_TEST_REPORT.md`、`docs/DEVELOPMENT_STATUS.md`、`docs/plans/*.md` | 历史开发日志中的内部留档引用均加注「（内部留档）」 |
| **NOTICE** | `NOTICE` | 第三方依赖声明（复现者自备） |

---

## 2. 排除内容（仅内部留档，不随公开仓库分发）

按 §3 默认排除与「RELEASE-RISK-AUDIT.md R1–R6」清单，下列内容**不进入**公开版，原因与替代说明一并列出：

### 2.1 受限媒体与素材

| 不分发内容 | 性质 | 替代说明 |
| --- | --- | --- |
| 用户的 MiniMax-H3 生成视频（h3-smoke.mp4、h3-t2va-8s.mp4） | 受版权约束的内部测试视频（无 LICENSE） | 公开版工作台 `MEDIA_ALLOWLIST` 改为指向仓库内 `artifacts/task-16|18/fixtures/videos/` 的**项目自产合成技术 fixture**（项目脚本 `generate_task16_fixtures.py` / `generate_task18_fixtures.py` 确定性渲染，640×360@24fps，Apache-2.0 覆盖） |
| dev Evidence Pack AI01–AI06（MiniMax-H3 生成受控测试视频） + WEB01–WEB03（Pexels licensed-public） | 仓库外用户本地只读，dev 训练集（含 transfer-safe 卡） | 公开版不试图重发；公开版运行的 `test_task19_dev_pack.py` 在缺失前置产物时明确 `NOT_RUN`（exit 2），不伪报 |
| 任务 19B 的 9 份 GT 与确定性派生报告 | dev 集的训练/评测真值；与 dev 视频同源 | 同上 |
| 任务 18 的 287 份真实 Qwen 原始返回（`artifacts/task-18/real-qwen/`） | 原始模型输出（按数据卡 raw_redistribution_allowed=false） | 其评分摘要与 verdict 结论收录于 `artifacts/task-18/three-arm-comparison.json`、`verdict.json`、`run-summary.md` |
| Tier-3 冻结评测的两段测试视频（任务 07/08） | 同上 | 同上；测试运行脚本与 `SPARKSKILL_TEST_MEDIA_ROOT` 环境变量默认指向占位目录，复现者需自备 |
| Task 12/12.1 工作台 QA 截图与产物 | 内部 QA 产物 | 公开版以本次浏览器 QA 记录替代 |
| Task 04/05/06/10/13/20/22/24/24b/26a/26b 原始运行产物 | 内部运行产物（依赖内部媒体或外部网络） | 任务 06 多视频规则测试 32/32、任务 04 视频规则测试 16/16、任务 20 配对测试 19/19 等公开版可运行的规则测试已随仓库分发 |
| Task 23 未启动（按记录）；holdout 三样本 | 公开版以占位编号 HOLDOUT-G1/G2/L1 指代；真实 holdout 编号不出现于公开版任何文件（本文件亦不复写其字面值，见 §4） | 任务 17 的合同规则保留（12 样本结构 / dev 9 / holdout 3 / generated 8 / licensed_public 4） |
| 私有评审工具 `review/` | 任务 24/24B/26A/26B 的内部人类评审工具 | 不在公开评测范围 |
| 赛事交付候选包 `docs/submission/` | 赛事内部审核材料 | 公开版以 `docs/PUBLIC-VERSION-NOTES.md`（本文件）替代 |

### 2.2 不在公开版的 artifacts（按类）

| 类别 | 不分发内容 |
| --- | --- |
| 任务 03/04/05/06/10/12/12-1/13 | 原始运行产物（仅任务 03 的规格 + 2 个真实 Qwen 图片证据样例随公开仓库分发供契约测试回放） |
| 任务 19 | 除 run-summary / known-limitations / verification / comparisons/ 外的产物（ingestion/摄验、ground-truth/、preregistration/、predictions/、scores/、dsh-session/、test-results.json） |
| 任务 20/21/22 | 全部原始产物（除任务 21 的 errata 勘误文件） |
| 任务 17 | t30-t33 的 holdout 同名 fixture、build_fixtures.py、verify_task17.py、competition-profile-example.json |
| 任务 18 | real-qwen/（287 份原始模型返回） |

---

## 3. 可复现数字 vs 仅基于内部冻结数据的数字

公开版运行可复现、且数字与公开仓库状态一致的：

| 数字 | 公开版来源 | 本次实测 |
| --- | --- | --- |
| **任务 04 视频规则 16/16** | `test_video_pipeline.py` | 16/16 |
| **任务 06 多视频规则 32/32** | `test_multi_video_pipeline.py` | 32/32 |
| **任务 16 时序证据规则测试 27/27** | `test_temporal_evidence.py` | 27/27 |
| **任务 17 GT 评分 34/34**（公开版） | `test_temporal_ground_truth_scoring.py`（t30-t33 排除后） | 34/34 |
| **任务 18 coverage 采样规则测试 36/36** | `test_task18_coverage_sampling.py` | 36/36 |
| **M1–M8 媒体来源契约 10/10** | `test_missing_media_contract.py` | 10/10 |
| **Tier-3 v2 评分器回归 17/17** | `test_score_tier3_eval_v2.py` | 17/17 |
| **工作台静态测试 26/26** | `test_demo_app.py` | 26/26 |
| **浏览器 QA 15/15** | 本次 Playwright + Chrome 实测 | 15/15（控制台无错误、6 条运行记录渲染、关键帧图 200、负向状态未被改成肯定、Provenance 抽屉工作、归档标签真实、无私有路径泄露） |

公开版运行可复现、但与内部留档版口径不同的（公开版因排除 holdout 同名 fixture 而改变子集）：

| 数字 | 公开版结果 | 内部留档版结果 | 差异原因 |
| --- | --- | --- | --- |
| 任务 17 GT 评分测试 | **34/34** | 38/38 | 公开版排除 t30-t33（holdout 同名 fixture，其真实编号在公开版以 HOLDOUT-G1/G2/L1 占位），内部留档版含全部 34 个 fixture 目录 |
| 任务 04/06/08 原始会话产物 | 仅 run-summary + comparison 摘要 | 完整 18 个 DSH headless 会话产物 | 受限媒体保留或缺 |
| 任务 19 dev 域 27/27 真实运行 | `test_task19_dev_pack.py` 明确 `NOT_RUN`（前置缺失） | 27/27（dev 集已备齐） | dev 集不随公开仓库分发 |
| 任务 20 512 次配对运行 | `test_task20_pairing.py` 在缺失前置时 `NOT_RUN` | 512/512 | 原始配对产物为内部留档 |

仅基于内部冻结数据、不在公开版复现：

| 数字 | 来源（内部留档） |
| --- | --- |
| Tier-3 五维最终数字（Security 9/9、Correctness 9/9、Discoverability 9/9、Effectiveness 9/9；Verdict PASS；总耗时 3534.4s→800.5s） | `artifacts/task-08/comparison.json` + `artifacts/task-09/comparison-v2.json`（脱敏后字节未变，路径保留；公开版含这些比较 JSON 但不可重跑） |
| Task 16/18 自适应采样对照（uniform vs adaptive vs coverage）三场景 PASS/IMPROVEMENT/TRADEOFF 数字 | `artifacts/task-16/comparison.json`、`artifacts/task-18/three-arm-comparison.json`（公开版含 JSON，比特完整） |
| Tier-3 v1/v2 评分器 SHA-256（c35b4506…、949772c9…） | `scripts/score_tier3_eval.py` 与 `scripts/score_tier3_eval_v2.py` 实际字节哈希（已实测与文档声明一致） |
| Task 25 STAGE1_HARM_STOP、Task 22 NO_IMPROVEMENT、Task 19B 三范围 NO_IMPROVEMENT、Grounding DINO NO_GO、StepFun GATE_NOT_MET、Task 26C STOPPED_BY_USER_NOT_SCORED | 内部 run-summary（已在公开版收录的对应摘要中如实记录） |
| evals/tier3/evals.json 的 SHA-256 哈希声明（64da5041a178ae442391bdbd9b528db5ab27ab514136ec595366b327d864ccaa） | 该哈希针对**内部留档版**未脱敏 evals；公开版 evals 是已脱敏路径的版本，**SHA-256 必然不同**，并已记录于 `artifacts/task-09/verify_task09.py` V2 检查的失配项（公开版运行该检查时报 V2-evals-frozen 哈希不一致——此为公开版与内部留档版口径差的诚实表现，详见下文 §7） |

---

## 4. 脱敏改写记录

公开版对下列内容进行了脱敏重写（所有改动记录在 `redact-log.json`，每个文件含 before/after SHA-256）：

| 类别 | 改写规则 | 说明 |
| --- | --- | --- |
| 开发机绝对路径 | 开发机用户主目录下的工作区绝对路径（`<开发机用户主目录>/workspace/<项目目录>/`）→ 删除前缀（变仓库内相对路径） | artifacts 中 1200+ 处工作区路径转换为 `artifacts/...` 相对路径；字面值仅存于内部留档脱敏日志 |
| 开发机其他私有路径 | minimax-h3 目录、datasets/SparkSkill_Studio、.credentials.yaml、.dsh、envs/vllm 等 | 全部替换为中文尖括号占位符（`<内部测试媒体目录>`、`<DEV_EVIDENCE_PACK_ROOT>` 等） |
| 主机名与 SSH 信息 | 开发机主机名、SSH 端口、IP 地址、私钥文件名（字面值仅存于内部留档脱敏日志） | 全部替换为 `<开发机主机名>` 等占位符 |
| Holdout 样本编号 | holdout 三个真实样本编号（字面值仅存于内部留档脱敏日志） | 公开版以 `HOLDOUT-G1` / `HOLDOUT-G2` / `HOLDOUT-L1` 占位编号替代；契约结构（12 样本、dev 9 / holdout 3、generated 8 / licensed_public 4）保留 |
| 凭据 | 无任何凭据存在于公开版（验证脚本 + build_demo_manifest 扫描） | — |

公开版构建器对前述规则做内置自检（构建期即中止），并对每个改写文件记录 SHA-256 before/after。所有改写文件不得再标榜为"原始冻结字节"。

---

## 5. 真实产物与脱敏版的关系

| 内部留档产物（不随公开仓库） | 公开版对应产物 | 关系 |
| --- | --- | --- |
| 任务 16 DSH 自主会话的 12 份原始模型返回 + 会话流 | `artifacts/task-16/dsh-session/raw/*.raw.json`、`session-stdout.txt`（同字节，路径脱敏后） | 路径脱敏；未改写帧图像或模型返回内容 |
| 任务 18 DSH 自主会话的 11 份原始模型返回 + 会话流 | `artifacts/task-18/dsh-session/raw-model-returns/*.raw.json`、`session-stderr.txt` | 同上 |
| 任务 16/18 deterministic/replay 的 100+ 时间线 + 帧报告 | `artifacts/task-{16,18}/{deterministic,comparison}/` | 同上 |
| Tier-3 冻结评分器 v1 (`c35b4506…`)、v2 (`949772c9…`) | `scripts/score_tier3_eval.py`、`scripts/score_tier3_eval_v2.py` | **未改写**；SHA-256 实测一致 |
| 任务 17 GT 评分器（任务 17 提交 9293143 冻结） | `scripts/score_temporal_ground_truth.py`、`scripts/task18_scorer_adapter.py` | **未改写** |

公开版不声称**外部能够逐字节重放**以下过程（依赖媒体或运行时状态）：

- 任务 05/06 DSH headless 真实自主会话（依赖内部测试视频）
- 任务 07/08 Tier-3 18 个真实会话（依赖冻结 Tier-3 媒体）
- 任务 18 real-qwen 287 次真实 Qwen 调用（依赖本地 Qwen 与授权状态）
- 任务 19 27 个真实 dev 域运行（依赖 dev Evidence Pack）

公开版提供的脚本可让复现者以**自备媒体与 dev 包**完整复现以上实验，但**复现结果不会与公开版的摘要数字一致**（除非复现者以同等输入重新运行真实 Qwen）。

---

## 6. 公开版与赛事交付候选包（内部留档 `docs/submission/`）的关系

赛事交付候选包为内部留档（按 §2.1）。公开版不收录其内容（RELEASE-RISK-AUDIT / WINDOWS-RELEASE-HANDOFF / CLAIM-EVIDENCE-MATRIX / DEMO-RUNBOOK / SUBMISSION-MATRIX / TASK27-VERIFICATION），但以本文件 + `docs/REPRODUCTION.md` 覆盖其关键信息：

- 发布风险审计的关键结论（按 R1–R6）：本文件 §2、§4、§5、§7 全部覆盖
- Windows 端交接说明：见 `docs/REPRODUCTION.md` §7（复现方式已显式标注哪些可在公开版复现、哪些需内部前置产物）
- 主张—证据—限制矩阵：见 `BENCHMARK.md`（Tier-3 历史链 + §1 限制）、`README.md`（§当前实现状态）、`docs/REPRODUCTION.md` §11（已知限制）
- 演示 runbook：见 `docs/REPRODUCTION.md` §4（工作台启动）、§5（流水线入口）；B 站/十日谈/团队合影/组委会表单按外部流程取得，不由本仓库决定

---

## 7. 公开版的停止门（不写入）

公开版严格遵守：

1. **不写入 `SUBMISSION_COMPLETE`**——赛事资格材料需按外部流程取得。
2. **不修改任务 03/04/05/06 的内部原始产物**——任务 03 仅随公开仓库分发 `task-spec.json` 与两个真实图片证据样例（用于契约测试回放），其原始运行产物为内部留档。
3. **不冒充 NVIDIA 官方签名**——三 Skill 全部自研，当前未接入 NVIDIA 官方 Skills、TAO、VSS、DeepStream、NIM。
4. **不声称统计显著性**——所有运行均为 dev 小样本 + 单次运行 + 温度 0.1。
5. **不删除 holdout 占位编号之外的契约结构**——competition profile 的 12 样本 / dev 9 / holdout 3 划分保留。
6. **不把脱敏改写后的字节标榜为内部冻结哈希**——`evals/tier3/evals.json` 公开版 SHA-256（`2205d0c73f74c576a507c8f6c5f65e0563f3dd5341880162b1033dd75079a56f`，脱敏改写后；2026-09-26 Sprint 01 claim audit 复算更正，此前文本误写为 `2205b1a6…`，文件自初始公开提交 `89f1c5e` 起未改动）与内部留档版（`64da5041…`）不同，`verify_task09.py` V2 检查会如实报告哈希失配（已在交付报告 QA 部分记录）。

---

## 8. 公开版与历史快照（`artifacts/task-18/verification.json`）的关系

`artifacts/task-18/verification.json` 公开版收录内部留档版历史快照（24/24 通过，生成于 2026-09-22T14:05）。该快照反映了当时脚本版本与任务 18 数据形态的对应关系。**公开版任务 18 verify_task18.py 经过 §7 适配（V1/V2 git-blob NOT_RUN、V13 资源阻塞数据布局对齐、V15 /proc/ 移除等）后输出与内部留档版口径一致但范围更窄（不依赖内部 Git 历史）。** 公开版运行 verify_task18.py 写入的 `verification.json` 由交付前再次运行产生，与本历史快照共存；历史快照作为"内部留档版交付时的可核验状态"完整保留。

---

## 9. 公开版的诚实性边界（必须随结果一起阅读）

- Tier-3 PASS 是冻结九任务 + 单次小样本的工作流对照（**不是视觉真值准确率**，不外推）。
- Task 19B 三范围 pack verdict 全部 NO_IMPROVEMENT——核心缺陷是模型语义校准失败而非采样几何。
- Task 20 TRADEOFF——v2 让不可判定画面更愿意拒答，但拒答精确度不足（6 帧被推入拒答：5 正确判断损伤 + 1 误报修复）。
- Task 22 NO_IMPROVEMENT——coverage 修复覆盖盲区但仍漏检 600ms twin 短事件。
- Task 25 STAGE1_HARM_STOP——加入邻帧时序上下文不是修复路径（v2 multi-image 引入 2 次输出契约失败）。
- Task 26C STOPPED_BY_USER_NOT_SCORED——表单措辞歧义中止，真实有效真人决定 2/14 不用于评分。
- Grounding DINO NO_GO——双模型方案未过基础正确性门。
- StepFun 3.7 Flash GATE_NOT_MET——技术可调用不等于生产兜底。
- holdout 三样本（公开版以 HOLDOUT-G1/G2/L1 占位）从未接入，盲测未启动。
- 工程 PASS 不等于算法全面优于基线；小样本 + 单次运行 + 温度 0.1 随机性——**不外推为真实仓储准确率**。

---

## 10. 复现本公开版的停止门

满足以下全部条件，方可视为复现成功（用于 Stage 30 同文后续发布任务的对接）：

1. 公开版 Git 根为独立仓库（无内部留档版的提交祖先），提交历史可独立审计。
2. 公开版 README/PROJECT_CONTEXT/BENCHMARK/REPRODUCTION 中**无指向不存在路径的引用**（所有内部留档引用均加注「（内部留档）」或替换为公开版对应产物）。
3. 公开版构建器 `scripts/build_demo_manifest.py` 在独立根仓库上生成无错误，`scripts/serve_demo.py` 启动并服务首页与 6 条运行记录。
4. 本文件 §3 列出的可复现数字全部通过；§3 列出的仅内部冻结数据已在其出处明确标注"内部留档"。
5. 浏览器 QA 15/15 通过，控制台无阻断错误，旧绝对路径不显示，归档标签真实。
6. LICENSE（Apache-2.0）+ NOTICE（第三方依赖声明）齐全；Apache-2.0 标准正文与官方原文逐行一致（唯一差异是附录版权占位行 `Copyright [yyyy] [name of copyright owner]` 被填写为 `Copyright 2026 tangjue3`，README/PROJECT_CONTEXT/LICENSE 三处权属表述一致）。

未满足任一项 → 不得视为复现成功，需回到 §3 检查并补充缺失条目。

---

**交付报告**：本公开版的逐项质量记录见同级目录 `任务29-同仓公开候选交付报告.md`（QA 报告 + 浏览器实测截图 + 权利与脱敏审计 + 公开版 manifest）。