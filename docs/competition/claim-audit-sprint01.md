# Claim Audit — Sprint 01（对外陈述核验报告）

- 核验时间：2026-09-26（UTC+8）· 核验环境：Windows 11 + Python 3.13.12（托管 venv，纯标准库）
- 核验对象：`README.md`、`PROJECT_CONTEXT.md`、`BENCHMARK.md`、`docs/PUBLIC-VERSION-NOTES.md`、
  `artifacts/{task-19,task-25,stepfun-vision-gate,detect-gdino-crosscheck,task-26c}/` 摘要中的对外数字
- 核验方式：**在公开仓库工作副本上实际运行可复现套件 + 哈希复算 + 与文档逐条对读**。
  不引入新模型调用；holdout 零接触。

## 1. 本次实际跑过的确定性回归（结果如实记录）

| 套件 | 文档声明 | 本次实测（Windows，无 cv2） | 结论 |
| --- | --- | --- | --- |
| `scripts/test_score_tier3_eval_v2.py` | 17/17 | **17/17 通过**（exit 0） | ✅ 一致 |
| `.dsh/skills/task-to-skill-compiler/scripts/test_missing_media_contract.py` | 10/10 | **10/10 通过**（exit 0） | ✅ 一致 |
| `scripts/test_demo_app.py` | 26/26 | **26/26 通过**（exit 0；运行后 `git status` 干净，`demo-manifest.json` 未被改动） | ✅ 一致 |
| `scripts/test_temporal_ground_truth_scoring.py` | 34/34（公开版子集） | **34/34 通过**（exit 0） | ✅ 一致 |
| `.dsh/skills/visual-evidence-extractor/scripts/test_video_pipeline.py` | 16/16（开发机实测） | **ENV_BLOCKED**（exit 1：本机无任何含 OpenCV 的解释器，项目不装依赖） | ⚠️ 本机不可跑 |
| `.../test_multi_video_pipeline.py` | 32/32（开发机实测） | **ENV_BLOCKED**（同上） | ⚠️ 本机不可跑 |
| `.../test_temporal_evidence.py` | 27/27（开发机实测） | **ENV_BLOCKED**（同上） | ⚠️ 本机不可跑 |
| `.../test_task18_coverage_sampling.py` | 36/36（开发机实测） | **ENV_BLOCKED**（同上） | ⚠️ 本机不可跑 |
| `scripts/test_task25_gate.py` 等 5 套 | 明确的 NOT_RUN（内部前置缺失） | **exit 2 = NOT_RUN**（5/5 如实报告，不伪报） | ✅ 一致 |

**外陈述口径**：四个抽帧相关套件在本核验机上是 `ENV_BLOCKED`，与"开发机实测 16/16、32/32、27/27、
36/36"不矛盾——两件事都要说：开发机上实测通过；无 OpenCV 的复现机上如实标记不可跑。
**不得**把 ENV_BLOCKED 写成"全部 regression 通过"（与 Task 28 阻塞记录同一口径）。

## 2. 哈希声明复算（LF 归一化，原因见 §5）

| 对象 | 文档声明 | 复算结果 | 结论 |
| --- | --- | --- | --- |
| `scripts/score_tier3_eval.py` | `c35b4506…`（v1 冻结） | `c35b4506…` | ✅ 一致 |
| `scripts/score_tier3_eval_v2.py` | `949772c9…`（v2 冻结） | `949772c9…` | ✅ 一致 |
| `artifacts/task-18/preregistration/frozen-hashes.json` 全部条目 | 冻结一致 | **41/41 一致**（0 漂移 0 缺失） | ✅ 一致 |
| `evals/tier3/evals.json` | PUBLIC-VERSION-NOTES §7：公开版 `2205b1a6…` | 实际 `2205d0c7…` | ❌ **不一致，已修正（见 §3）** |
| 内部留档版 evals 哈希 | `64da5041…` | 内部文件不在本仓库，无法复算 | ➖ 如实标注为内部声明 |

## 3. 发现的问题与修正（不越过红线）

**问题 P1（过期声明，已修正）**：`docs/PUBLIC-VERSION-NOTES.md` §7 第 6 条写
`evals/tier3/evals.json` 公开版 SHA-256 为 `2205b1a6…`；该文件自初始公开提交（`89f1c5e`）后
逐字节未变，实际 LF 归一化 SHA-256 为 `2205d0c73f74c576a507c8f6c5f65e0563f3dd5341880162b1033dd75079a56f`。

- 修正方式：仅更新该哈希值为实测值。**保留**原文全部诚实性要求（不得把脱敏字节标榜为内部冻结哈希、
  `verify_task09.py` V2 检查如实报告失配）不变。
- 不涉及：历史实验结论、失败记录、评分规则、任何冻结清单。
- 依据：任务书授权"文档里有过期、矛盾或过度声明可以修正"；本修正是把过期值改为实测值，
  使公开版停止门 §7 继续可自证。

## 4. 关键对外 claim 逐条核对（演讲/视频/README 可用）

| 对外说法 | 出处 | 状态 |
| --- | --- | --- |
| Tier-3 最终 v2：Security 9/9 vs 9/9；Correctness 9/9 vs 7/9；Discoverability 9/9 vs 5/9；Effectiveness 9/9 vs 6/9；Verdict PASS | BENCHMARK.md §4 + `artifacts/task-09/comparison-v2.json` | ✅ 可用（必须带"9 任务/侧小样本、单次运行"限定） |
| Tier-3 效率：3534.4s→800.5s、工具调用 292→157 | BENCHMARK.md §4 | ✅ 可用 |
| Tier-3 历史链：PARTIAL → E9 修复 → 评分器误报发现 → v2 PASS | BENCHMARK.md §1–4 | ✅ 可讲，**四段都讲，不得只讲 PASS** |
| dev 域 9 视频 27 运行 256 调用，三范围 pack verdict 全 NO_IMPROVEMENT，8 边界 matched=0 | BENCHMARK.md §8 + task-19 摘要 | ✅ 可用（必须与 NO_IMPROVEMENT 同时出现） |
| 任务 18 三臂 287 次真实调用、replay/real 均 TRADEOFF | BENCHMARK.md §7 | ✅ 可用 |
| 任务 20 配对 512 次调用、verdict TRADEOFF、v2 未采纳 | BENCHMARK.md §9 | ✅ 可用 |
| Task 25 `STAGE1_HARM_STOP`（B4：2 次契约失败） | task-25 摘要 + 本轮任务书 | ✅ 见 [task25-stage1-harm-stop.md](task25-stage1-harm-stop.md) |
| GroundingDINO `NO_GO`（误拦 66/185=35.7%） | gdino-crosscheck 摘要 | ✅ 见 [groundingdino-no-go.md](groundingdino-no-go.md) |
| StepFun step-3.7-flash `GATE_NOT_MET`（G1/G2/G5 失败） | stepfun-vision-gate 摘要 | ✅ 可用（与 NO_GO/STOP 类声明并列，讲"诚实停止门"） |
| Task 26C `STOPPED_BY_USER_NOT_SCORED`（有效真人决定 2/14） | task-26c STOP-REPORT | ✅ 可用 |
| 三个 Skill 全部自研、未接入/未冒充 NVIDIA 官方 Skills/TAO/VSS/DeepStream/NIM | PROJECT_CONTEXT §7/§12 | ✅ 必须原文携带，不得省略 |
| StepFun（step-5-preview）只做文本理解与规划，不做视觉；视觉 = 本地 Ollama Qwen3.8-27B | README + PROJECT_CONTEXT §5/§12 | ✅ 必须原文携带 |
| 公开工作台（`app/`）是只读归档查看器，不实时调用模型 | README + serve_demo.py | ✅ 必须原文携带 |
| "生产可用 / 真实仓储准确率 / 统计显著提升" | 各文档红线 | ❌ **任何场合都不得声称** |
| 跨摄像头同一性、目标跟踪、运动路径重建 | 场景边界 | ❌ 不得声称 |

## 5. 环境因素记录（影响哈希判读，必须随报告保留）

本核验机 `core.autocrlf=true` 且仓库无 `.gitattributes`，checkout 为 CRLF；
文档哈希均在 Linux LF 下实测。复算时对 CRLF→LF 归一化后比对：评分器两条、task-18 冻结
41 条、evals 一条均按此口径。该差异是**行尾差异，不是内容漂移**；不得据此声称"冻结哈希失配"。

**死链扫描**（对 16 份文档的 35 个仓库相对链接做存在性检查）：**0 死链**，
满足公开版停止门"无指向不存在路径的引用"一条。

## 6. 结论

- 公开版对外数字与仓库证据**总体一致**；抽帧套件在本机 ENV_BLOCKED 已如实记录。
- 修正 1 处过期哈希声明（P1），未发现其他过期/矛盾/过度声明。
- 冻结边界零漂移：Task 28 清单（内部）未触碰；Task 29 发布根仅新增 `docs/competition/` 与 P1 修正。
