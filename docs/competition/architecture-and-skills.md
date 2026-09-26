# 核心架构与 3 个 Skill — 简化展示（Sprint 01）

> 用途：视频 B 段静帧、答辩一页纸、对外介绍的统一口径。
> 口径来源：`README.md` 核心设计 + `PROJECT_CONTEXT.md` §12.1（唯一架构口径，任何文档/演示不得偏离）。

## 1. 一张图（简化分层）

```text
用户（一句自然语言）
   │
   ▼
DSH Agent Harness 0.1.5-rc.2 ── 发现 / 加载 / 编排 Skill；不承担视觉推理
   │        ▲
   │        └── StepFun step-5-preview：只做文本任务理解与规划
   │            （当前 DSH 配置下不读取图片，不做视觉判断）
   ▼
┌────────────────────────────────────────────────────────────┐
│ Skill 1  task-to-skill-compiler                            │
│   自然语言 → 受约束 VisualTaskSpec（目标/媒体来源/预算/边界） │
│   媒体来源硬门：缺来源 = needs_input 并停止，禁止猜路径       │
├────────────────────────────────────────────────────────────┤
│ Skill 2  visual-evidence-extractor                         │
│   OpenCV 抽帧（底层工具）→ 本地 Ollama Qwen3.8-27B Vision   │
│   uniform / adaptive / coverage_aware_adaptive 采样 + 预算   │
│   输出：帧、时间戳、原始返回、结构化判断、拒答及原因          │
├────────────────────────────────────────────────────────────┤
│ Skill 3  evidence-report-generator                         │
│   证据 → 图片/单视频/多视频/时序报告                        │
│   独立复算状态转换 + 反幻觉交叉校验；缺口不得写成肯定         │
└────────────────────────────────────────────────────────────┘
   │
   ▼
Evidence Workbench（app/）：只读归档展示，不在浏览器调用任何模型
```

硬件与数据边界：全部视觉推理在 **NVIDIA DGX Spark（GX10 / GB10，统一内存 119GiB，ARM64）** 本地完成，
数据不离开本地视觉推理环境；模型权重与受限媒体不随仓库分发。

## 2. 三个 Skill 一览（对外只讲这七行）

| Skill | 干什么 | 明确不干什么 |
| --- | --- | --- |
| `task-to-skill-compiler` | 把任务编译成带输入输出契约的任务规格；媒体来源 provenance 硬门；采样策略契约（uniform / adaptive / coverage_aware_adaptive + 硬预算） | 不动态生成 Skill 文件或可执行代码；不猜媒体路径 |
| `visual-evidence-extractor` | 受控调用本地 Qwen Vision，保留帧/时间戳/原始返回/结构化判断；证据不足必须拒答 | 不生成最终报告 |
| `evidence-report-generator` | 生成证据链报告并交叉校验；显式声明跨视频语义限制 | 不做视觉推理；不做跨视频身份断言 |

三 Skill 全部**自研**；未接入、未冒充 NVIDIA 官方 Skills / TAO / VSS / DeepStream / NIM。
OpenCV 只是底层抽帧工具，不是核心创新或卖点。

## 3. 产品契约五句话（演示/答辩可直接念）

1. 来源可核：每个结论回到帧、时间戳、原始模型返回与调用记录。
2. 拒答即结论：`not_found` / `abstained` / `failed` 不可互相替代，禁止把缺口写成肯定。
3. 跨视频只聚合不关联：同一查询在多段视频分别确认 ≠ 同一个物理实例移动。
4. 采样留痕：预算、覆盖探索、边界细化调用分别记账；采样结论不等于连续跟踪真值。
5. 失败留档：停止门（NO_GO / STAGE1_HARM_STOP / GATE_NOT_MET / NO_IMPROVEMENT）随成功记录一起公开。

## 4. 模型分工表（被追问时逐格回答）

| 组件 | 职责 | 不负责 |
| --- | --- | --- |
| DSH 0.1.5-rc.2 | Agent 运行时：任务理解入口、Skill 发现/加载/编排 | 视觉推理本身 |
| StepFun step-5-preview | 文本任务解析、规划、生成 VisualTaskSpec | 不读图片、不做视觉 |
| 本地 Ollama Qwen3.8-27B Vision | 图片/帧的存在性判断、结构化证据、拒答 | Skill 编排、任务编译 |
| OpenCV 5.0.0 | 解码、抽帧、关键帧存储 | 核心创新/卖点（不是） |
| Evidence Workbench | 只读展示已存档 artifacts | 浏览器内实时调用模型 |

## 5. 一致性自检（演示前 30 秒过一遍）

- 每一句"谁负责什么"与 §4 表逐格一致；
- 三个 Skill 名称与 `.dsh/skills/` 目录名一致；
- 每个能力主张能在 `README.md` / `PROJECT_CONTEXT.md` / `BENCHMARK.md` 找到出处；
- 数字只引 [claim-audit-sprint01.md](claim-audit-sprint01.md) §4 白名单内的值。
