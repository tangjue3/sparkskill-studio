# 成品演示视频 · 链接与提交口径

> 交付用途：NVIDIA DGX Spark 黑客松提交材料之一。**提交表单请使用规范视频页链接，不要使用动态链接**（动态仅为转发载体，可能被删除，站外渲染不稳定）。
> 关联文档：[demo-runbook.md](demo-runbook.md)（录制操作流程）、[video-shotlist-3min.md](video-shotlist-3min.md)（3 分钟镜头脚本）、[claim-audit-sprint01.md](claim-audit-sprint01.md)（数字白名单）。

## 链接

| 用途 | 链接 |
|---|---|
| **提交用（规范视频页）** | https://www.bilibili.com/video/BV1jLa36yEmw/ |
| 投稿动态（来源留档） | https://t.bilibili.com/1253064289281900545 |

## 视频信息

- 标题：SparkSkill Studio｜让视觉 Agent 的每一步都可验证｜NVIDIA DGX Spark 黑客松
- BV 号：BV1jLa36yEmw
- 时长：1:31（单 P）
- 发布：2026-09-28，UP主：我不懂vanish，公开可见
- 素材口径：画面仅使用仓库内合成 fixture 与已授权素材（规则见 [video-shotlist-3min.md](video-shotlist-3min.md) 拍摄前检查）

## 评审维度覆盖对照

> 下表为**投稿简介所声明的覆盖范围**；画面内实际镜头以成片为准，提交前请对照下方"待核对项"过一遍。

| 评审维度 | 简介中的对应声明 |
|---|---|
| DSH Agent Harness 编排 | 核心流程 User Task → DSH Agent Harness → Skills Orchestration → Evidence → Verifiable Report |
| 自研 Skill 全生命周期 | task-to-skill-compiler / visual-evidence-extractor / evidence-report-generator 三个 Skill 逐一说明 |
| StepFun 接入与模型分工 | StepFun step-5-preview 负责文本任务理解与规划；视觉证据处理与 Skill 执行在本地完成 |
| DGX Spark 本地算力 | 面向 NVIDIA DGX Spark 运行环境适配，视觉推理本地执行 |
| evals 可度量对比 | 冻结测试集 + Evaluator，Security / Correctness / Discoverability / Effectiveness 四维前后对照 |
| 诚实边界 | 结尾命题：Agent 调用 Skill 时能否知道它做了什么、为什么、结论来自哪里 |

## 提交前待核对项（成片画面）

1. **DGX Spark 本地推理证据**：`nvidia-smi` / Ollama 日志 / GPU 占位画面至少出现一次（评分重点"本地算力真实利用"）；
2. **Tier-3 对比**：9/9 vs baseline、效率 3534.4s→800.5s，画面或字幕至少一处，且带"每侧 9 任务小样本、单次运行"限定语；
3. **片尾仓库落版**：`github.com/tangjue3/sparkskill-studio` 静帧，保证视频与仓库互相引得上。

## 与 3 分钟脚本的关系

本条为 1:31 压缩版；3:00 分镜总览（16 镜头，含 Tier-3 对比图与停止门段落）见 [video-shotlist-3min.md](video-shotlist-3min.md)，作为后续补录或加长版的剪辑依据。所有数字与表述口径以 [claim-audit-sprint01.md](claim-audit-sprint01.md) §4 白名单为准，字幕不得引用白名单之外的数字。
