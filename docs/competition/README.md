# Competition Delivery Sprint 01 — 比赛交付整理（公开仓库版）

> 生成时间：2026-09-26（UTC+8）· 工作副本：`tangjue3/sparkskill-studio`（独立 Git 根，origin 已核实）
> 本轮定位：把散在 `README.md` / `BENCHMARK.md` / `artifacts/*/run-summary.md` 里的证据，
> 整理成可直接支撑"录 Demo + 对外陈述"的交付材料。**全部数字来自仓库真实证据与本次实测，
> 不引入任何新模型调用、不触碰 holdout、不改写历史实验结果、不删除失败记录。**

## 边界声明（先读）

- **不修改 Task 28 已冻结文件**：Task 28 预冻结清单（`docs/plans/2026-09-25-state-expressiveness-gate.md`、
  `state_resolver.py`、`score_state_replay.py`、`test_state_expressiveness_gate.py`、
  `verify_internal_inputs.py` 及 2 个 guarded anchors）为**内部留档**，不存在于本公开仓库，天然未触碰。
- **Task 29 冻结边界**：本仓库即 Task 29 公开候选；本轮仅**新增** `docs/competition/` 目录与一处
  经授权的文档勘误（见 claim-audit）。`artifacts/task-18/preregistration/frozen-hashes.json`
  41/41 条复算一致（含 30 条因 Windows autocrlf 需 LF 归一化后一致，零漂移）。
- **本轮未运行任何模型**：所有"实测"均为确定性脚本/静态检查（Python 3.13，纯规则套件）。

## 交付物清单与阅读顺序

| # | 文件 | 用途 | 先说结论 |
|---|------|------|----------|
| 1 | [claim-audit-sprint01.md](claim-audit-sprint01.md) | **对外 claim audit**：每条对外数字/能力/限制的出处与本次核验结果 | 核心 claim 与证据一致；发现并修正 1 处过期哈希声明 |
| 2 | [video-shotlist-3min.md](video-shotlist-3min.md) | 3 分钟产品介绍视频镜头脚本 | 本地浏览器 UI 为主 + 服务器运行日志为辅 |
| 3 | [demo-runbook.md](demo-runbook.md) | Demo Runbook：从服务检查到录屏的逐步操作 | 含 401/403/端口占用/后端切换的处置 |
| 4 | [evidence-workbench-record-checklist.md](evidence-workbench-record-checklist.md) | Evidence Workbench 需要录制的页面/交互清单 | 按 6 条运行记录 × 9 阶段链路逐项列 |
| 5 | [tier3-comparison.svg](tier3-comparison.svg) | Tier-3 核心对比图 | v2 最终：四维 9/9 + 效率 −77% |
| 6 | [groundingdino-no-go.md](groundingdino-no-go.md) | GroundingDINO `NO_GO` 结论与外陈述口径 | 35.7% 误拦正确判断，不做挑战式双模型 |
| 7 | [task25-stage1-harm-stop.md](task25-stage1-harm-stop.md) | Task 25 `STAGE1_HARM_STOP` 结论与外陈述口径 | 多图邻帧上下文不是修复路径 |
| 8 | [architecture-and-skills.md](architecture-and-skills.md) | 核心架构 + 3 个 Skill 的简化展示 | StepFun 只做文本、Qwen 只做视觉、工作台只读 |

## 录制纪律（与镜头脚本、Runbook 共同遵守）

1. 服务器负责真正计算；本地电脑只负责操作与录屏。
2. 正式录之前先完整跑一遍，确定最佳案例；不边跑边录。
3. 不录服务器远程桌面；需要"证明在服务器执行"的镜头，录服务器终端（GPU/模型加载/Skill 日志）。
4. 录制内容不得出现任何未脱敏路径、凭据、内部留档编号。
5. 视频中出现的每个数字必须能在本目录文件或 `BENCHMARK.md` 中找到出处。
