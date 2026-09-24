# SparkSkill Studio

### 让视觉 Agent 的每个结论都有出处

SparkSkill Studio 是运行在 **NVIDIA DGX Spark** 上的视觉任务工作流：用户用自然语言提出问题，Agent 将其转成受约束的任务规格，读取图片或视频帧，最后交付可回溯的证据与报告。项目目前聚焦仓储、园区短视频中的**对象存在性和时序证据**，例如：“红色背包在这些视频中何时被观察到？看不清时不要猜。”

它不是目标跟踪器，也不把“模型说有”直接等同于事实。来源、采样时间、原始视觉返回、拒答原因和报告结论需要能相互核对。

**先看效果：**[90 秒本地体验](#90-秒本地体验) · **再看证据：**[已验证的结果](#已验证的结果) · **深入复现：**[部署与文档](#部署与文档)

## 90 秒本地体验

公开版附带一个只读 Evidence Workbench。它展示仓库内的合成测试视频、关键帧、证据时间线、来源信息和评测历史；**打开页面不会实时调用模型**。

```bash
git clone https://github.com/tangjue3/sparkskill-studio.git
cd sparkskill-studio
python3 scripts/serve_demo.py
```

浏览器打开 **http://127.0.0.1:8787/**。Windows 可将 `python3` 换成 `py -3`。此入口只需要 Python 3 标准库；服务仅监听本机回环地址。想运行真正的 Agent + 视觉推理，请按[复现指南](docs/REPRODUCTION.md)另行配置 DSH、StepFun、本地 Qwen 与视频处理环境。

在工作台中，可以依次查看目标结论、逐帧证据、时间线、Provenance Inspector，以及 Tier-3 评测从 **PARTIAL → 修复缺参问题 → 修正评分器 → PASS** 的完整历史。历史失败没有被成功结果覆盖。

## 核心设计

```text
自然语言任务
   ↓  DSH 编排 + StepFun 文本规划
VisualTaskSpec（目标、媒体来源、采样预算、安全边界）
   ↓  OpenCV 解码与抽帧
本地 Qwen Vision → 逐帧结构化证据
   ↓  时间线聚合 + 独立交叉校验
可追溯报告 → 只读 Evidence Workbench
```

三项 `.dsh/skills/` 下的 **自研 Agent Skill** 将这条链路拆成可复用、可评测的能力单元：

| Skill | 职责 |
| --- | --- |
| [`task-to-skill-compiler`](.dsh/skills/task-to-skill-compiler/SKILL.md) | 把文字视觉任务转成受约束的 VisualTaskSpec；缺失媒体来源时拒绝自行猜路径。它不动态生成新的 Skill 文件或可执行代码。 |
| [`visual-evidence-extractor`](.dsh/skills/visual-evidence-extractor/SKILL.md) | 调用本地 Qwen Vision，保留帧、时间戳、原始返回与结构化判断；区分未发现、证据不足及调用失败。 |
| [`evidence-report-generator`](.dsh/skills/evidence-report-generator/SKILL.md) | 根据证据生成图片、单视频或多视频报告，并交叉校验状态与结论，避免把缺口写成肯定判断。 |

**模型分工必须明确：**DSH `0.1.5-rc.2` 负责发现、加载和编排 Skill；StepFun `step-5-preview` 负责**文本**任务理解与规划，当前项目配置下**不读取图片**；视觉判断由 DGX Spark 本地 Ollama 上的 Qwen3.8-27B Vision 完成。OpenCV 只承担视频解码、抽帧等底层工作。项目没有接入或冒充 NVIDIA 官方 Skills、TAO、VSS、DeepStream 或 NIM。

技术重点不在“又加一个识别模型”，而在**任务契约、媒体来源硬门、采样决策留痕、拒答纪律和反幻觉交叉校验**。多段视频可以汇总同一目标查询的证据，但不能据此断言是同一个物理实例跨摄像头移动。

## 已验证的结果

| 验证 | 结果 | 如何理解 |
| --- | --- | --- |
| Agent 自主编排 | DSH headless 会话曾自主加载三项 Skill、生成规格、调用本地视觉链路并产出报告。见[任务 18 运行摘要](artifacts/task-18/run-summary.md)。 | 证明工作流可执行；公开工作台是归档展示，不是该会话的实时控制台。 |
| Tier-3 baseline 对照 | 冻结的 9 个任务中，with-skill 正确性 **9/9**（baseline **7/9**），视觉能力发现 **9/9**（baseline **5/9**）。见 [BENCHMARK](BENCHMARK.md)。 | 小样本、单次运行，说明 Skill 对本组任务有帮助；不代表统计显著性或行业准确率。 |
| dev 视频评测 | 9 段视频（6 段生成、3 段授权公开素材）、27 次三策略运行、256 次本地 Qwen 调用；按生成、授权素材、全部 dev 三个范围汇总，候选 coverage 的 pack verdict 均为 **NO_IMPROVEMENT**，每臂 8 个真实时间边界匹配均为 **0/8**。见[任务 19 摘要](artifacts/task-19/run-summary.md)。 | 如实暴露遮挡、低照度与相似物体的视觉误判；不能把技术 fixture 成绩当作真实场景成绩。 |

这些实验区分**工程闭环是否跑通**与**视觉判断是否正确**。采样算法可以减少调用、记录不确定时间区间，却无法自动修复视觉模型在难帧上“自信地判断错误”的问题。[优化说明](docs/OPTIMIZATION_NOTES.md)记录了已做的系统优化与没有做的模型权重优化。

## 适用边界

- 不做实时目标跟踪、运动路径重建、跨摄像头身份或实例关联；采样点之间不宣称目标连续存在。
- `confirmed` 只表示在特定采样帧获得支持；`not_found`、`abstained`、`failed` 不能互相替代。
- 公开仓库不分发受限原始视频、dev/holdout 数据、私有人工复核记录或全部真实模型原始返回。因此部分真实域结果只能核对公开摘要，无法仅凭此仓库完整重跑；详见[公开版范围说明](docs/PUBLIC-VERSION-NOTES.md)。
- 当前实验规模不足以支持“生产可用”“真实仓储准确率”或“统计显著提升”的声明。

## 部署与文档

| 想了解什么 | 从这里开始 |
| --- | --- |
| 从零启动工作台、配置完整推理链路、排查环境问题 | [复现指南](docs/REPRODUCTION.md) |
| Skill 的评测方法、失败和修复历史 | [Tier-3 Benchmark](BENCHMARK.md) |
| 契约、采样、证据与资源治理的设计取舍 | [优化说明](docs/OPTIMIZATION_NOTES.md) |
| 公开版与内部留档版有何不同 | [公开版范围说明](docs/PUBLIC-VERSION-NOTES.md) |
| 完整开发记录与状态 | [开发状态](docs/DEVELOPMENT_STATUS.md) |

本仓库自研代码和 Skill 按 [Apache License 2.0](LICENSE) 开源，版权署名为 **tangjue3**。第三方模型、服务与媒体遵守各自的许可；模型权重和受限视频不随仓库分发。
