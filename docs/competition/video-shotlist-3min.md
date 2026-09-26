# 3 分钟产品介绍视频 · 镜头脚本（Sprint 01 定稿）

> 总时长 3:00（±10s 可剪区间）。**原则：本地浏览器 UI 为主，服务器运行日志为辅；
> 服务器负责计算，本地只操作与录屏。** 脚本中所有数字出处见文末对照表；
> 任何镜头不得出现未脱敏路径、凭据、内部编号。
> 配套：[demo-runbook.md](demo-runbook.md)（操作流程）、
> [evidence-workbench-record-checklist.md](evidence-workbench-record-checklist.md)（工作台逐项清单）。

## 分镜总览

| 段 | 时间 | 内容 | 画面来源 |
| --- | --- | --- | --- |
| A 钩子 | 0:00–0:20 | 问题与定位 | 本地浏览器（开头字幕） |
| B 架构 | 0:20–0:40 | 一张图讲清分工 | 架构图/字幕 |
| C 主 Demo | 0:40–1:55 | 一条完整链路跑通 | 本地浏览器（DSH 工作台） |
| D 证据 | 1:55–2:25 | 工作台 + Tier-3 对比 | 本地工作台 + 对比图 |
| E 诚实边界 + 收尾 | 2:25–3:00 | 停止门与不宣称 | 字幕 + 结束页 |

---

## A. 钩子（0:00–0:20）

| 镜号 | 时间 | 画面 | 口播要点 | 注意事项 |
|---|---|---|---|---|
| A1 | 0:00–0:06 | 黑场淡入，仓库名 + 一句话："让视觉 Agent 的每个结论都有出处" | 不念稿，一句话立住 | 字幕用仓库 README 首句，不自行加形容词 |
| A2 | 0:06–0:14 | 截图：一段仓储视频 + 任务文本"红色背包何时被观察到？看不清时不要猜" | 用户场景：园区/仓储短视频的对象存在性与时序证据 | 用仓库内合成 fixture 或已授权素材，不用内部留档媒体 |
| A3 | 0:14–0:20 | 快切三个词：**不猜 / 可回溯 / 可核验** | "它不是目标跟踪器，也不把'模型说有'当事实" | 直接引 README 原话 |

## B. 架构（0:20–0:40）

| 镜号 | 时间 | 画面 | 口播要点 | 注意事项 |
|---|---|---|---|---|
| B1 | 0:20–0:33 | 架构图（[architecture-and-skills.md](architecture-and-skills.md) 的分层图做成静帧） | 自然语言 → VisualTaskSpec → 抽帧 → 本地 Qwen Vision → 证据聚合 → 可追溯报告；DSH 编排，StepFun 只做文本规划 | 图必须与文档一致：StepFun 不读图片；OpenCV 只是底层抽帧 |
| B2 | 0:33–0:40 | 三个 Skill 卡片并排 | task-to-skill-compiler / visual-evidence-extractor / evidence-report-generator 各一句职责 | 说"自研 Skill"，**不说** NVIDIA 官方 |

## C. 主 Demo（0:40–1:55）

> 拍摄对象 = 本地浏览器里的 DSH 工作台（经 SSH 隧道访问 DGX Spark 上的服务）；
> 计算在服务器完成。录制前按 Runbook 完整跑过一遍，确定表现最佳的案例再录。

| 镜号 | 时间 | 画面 | 口播要点 | 注意事项 |
|---|---|---|---|---|
| C1 | 0:40–0:50 | 本地终端：SSH 隧道命令 + "隧道已建立" | "本地只负责操作和录屏，推理在 DGX Spark" | 终端窗口不占全屏；确认无敏感信息（密码用环境变量/_spark.env，勿入画） |
| C2 | 0:50–1:00 | 浏览器打开工作台（带 token 的 URL 一镜带过） | "浏览器通过隧道直达平台" | URL 中的 token 出现在地址栏可接受，但**不要**暂停放大 |
| C3 | 1:00–1:15 | 上传测试视频（仓库内合成 fixture） | Step 1：用户只给自然语言 + 媒体 | 上传动效等真实进度，不剪掉等待（时间预算内） |
| C4 | 1:15–1:30 | 输入 Prompt → Compile / Generate Skill | Step 2：编译成受约束任务规格 | 强调编译器硬门：缺媒体来源会拒绝，不猜路径 |
| C5 | 1:30–1:42 | Run Skill；切服务器终端 3–5 秒 B-roll：GPU 占用 / 模型加载 / Skill 执行日志 | Step 3：服务器本地执行视觉推理 | B-roll 只插在推理等待处；用 `nvidia-smi` 与 Skill 日志即可 |
| C6 | 1:42–1:55 | 回到浏览器：检测结果页——时间戳、关键帧、证据链、最终报告 | Step 4：结果带出处；拒答就是拒答 | 展示一条真实记录；若结果含 NO_IMPROVEMENT/TRADEOFF 语义，按原样讲 |

## D. 证据（1:55–2:25）

| 镜号 | 时间 | 画面 | 口播要点 | 注意事项 |
|---|---|---|---|---|
| D1 | 1:55–2:08 | 本地 Evidence Workbench：运行记录 + 证据时间线 + Provenance 抽屉 | 公开版工作台是只读归档查看器，每个结论可回到原始证据 | 逐项按 [record-checklist](evidence-workbench-record-checklist.md) 拍 |
| D2 | 2:08–2:17 | [tier3-comparison.svg](tier3-comparison.svg) 全屏 | Tier-3：同任务集，是否加载 Skill 的对照；四维 9/9，效率 3534.4s→800.5s | 必须同时说"每侧 9 任务小样本、单次运行" |
| D3 | 2:17–2:25 | BENCHMARK 历史链一屏带过（PARTIAL→修复→评分器误报→PASS） | "失败没有被覆盖：初轮 PARTIAL、评分器误报，都留着" | 只展示公开版收录的四段，不展开内部留档 |

## E. 诚实边界 + 收尾（2:25–3:00）

| 镜号 | 时间 | 画面 | 口播要点 | 注意事项 |
|---|---|---|---|---|
| E1 | 2:25–2:40 | 字幕逐行：GroundingDINO NO_GO / Task 25 STAGE1_HARM_STOP / StepFun GATE_NOT_MET / dev 域 NO_IMPROVEMENT | 主动讲停止门："我们停了四条不该往下走的路线" | 每个名词指回本目录对应说明文档，不口头展开细节 |
| E2 | 2:40–2:50 | 字幕：不做什么——不跟踪、不跨摄像头身份、不猜；不宣称生产可用/真实准确率 | 能力边界即产品契约 | 原文表述优先 |
| E3 | 2:50–3:00 | 结束页：仓库地址 `github.com/tangjue3/sparkskill-studio` + Apache-2.0 + 团队名 | "代码、契约、测试、失败记录全部在仓库里" | 落版 3 秒静帧即可 |

---

## 镜头与数字出处对照（字幕只能引这些）

| 镜头说法 | 出处 |
| --- | --- |
| 每个结论有出处 / 不猜 / 可回溯 | `README.md` 首段 |
| StepFun 只做文本、Qwen 做视觉、OpenCV 只抽帧 | `README.md` 核心设计 + `PROJECT_CONTEXT.md` §12.1 |
| Tier-3：四维 9/9、baseline 7/5/6、效率 3534.4s→800.5s、292→157 | `BENCHMARK.md` §4 |
| 历史链四段 | `BENCHMARK.md` §1–§4 |
| 只读工作台、五级 Truth Status | `README.md`、`PROJECT_CONTEXT.md` §10 |
| 停止门四例 | 本目录 `groundingdino-no-go.md`、`task25-stage1-harm-stop.md`、`artifacts/stepfun-vision-gate/run-summary.md`、`BENCHMARK.md` §8 |
| 自研、未接 NVIDIA 官方组件 | `PROJECT_CONTEXT.md` §7/§12 |

## 拍摄前检查（每次录制前跑一遍）

1. 隧道在、服务在：见 [demo-runbook.md](demo-runbook.md) §2 的 5 条预检。
2. 完整跑通一次目标案例；记录结果页与服务器日志时间戳，供剪辑对轴。
3. 屏录分辨率 ≥1080p，浏览器缩放 100%，隐藏书签栏与无关标签。
4. 地址栏 token、终端密码、任何绝对路径不得成为画面焦点。
5. 本脚本提到的每个数字在讲前再核对一遍本文件出处列。
