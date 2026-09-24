# SparkSkill Studio 设计文档

- 日期：2026-09-21
- 状态：设计定稿；阶段 1（图片最小闭环）、阶段 2（短视频最小闭环）、阶段 2.5（DSH Agent 自主视频演示）、阶段 3 第一部分（多段视频统一证据时间线）、第二阶段（Tier-3 对照评测与 E9 修复）与第三部分（评测器 v2 与全量重评分，Verdict PASS）已实施，实施偏差见 §17
- 关联文档：`PROJECT_CONTEXT.md`、`README.md`、`docs/DEVELOPMENT_STATUS.md`、`BENCHMARK.md`

---

## 1. 项目摘要

SparkSkill Studio 是"StepFun 多模态模型 × NVIDIA Agent Skills"的本地视觉 Skill 编译与验证工作台。用户输入一句自然语言视觉任务，DSH Agent Harness 理解任务并生成/配置一个受控 Agent Skill；该 Skill 在 DGX Spark 本地环境中执行视觉分析，视觉理解由 StepFun 多模态模型完成；最终输出带时间、关键帧、目标框和置信度的证据结果，并支持用户在新视频上复用该 Skill。

首个演示场景：仓储/园区多段短视频中的对象追踪与事件证据链生成（示例："创建一个 Skill，追踪红色背包在多段视频中的移动路径，记录它出现过的时间、区域和关键画面；如果证据不足，不要猜测。"）。

本项目的创新点在 Agent Harness 对 Skill 全生命周期（生成、发现、加载、执行、复用）的治理，以及带契约、带证据、带拒答机制的视觉 Skill 工程化，而不在视频处理算法本身。

## 2. 赛事评分映射

| 评分项 | 本设计的对应落点 |
| --- | --- |
| Agent Harness | DSH 0.1.5-rc.2 作为 Agent 运行时，负责任务理解与 Skill 编排；Harness 行为被显式设计而非黑箱 |
| StepFun 多模态模型 | 所有视觉理解（对象/事件识别、目标框、置信度）均由 StepFun 多模态模型完成，端点为 `https://api.stepfun.com/step_plan/v1` |
| Skill 生成/发现/加载/执行/复用 | 三个自研 Skill 覆盖编译→抽取→报告的流水线；Skill Card 声明触发条件；同一 Skill 可加载到新视频上复用 |
| 输入输出契约 | 每个 Skill 有显式 input/output 契约与证据 schema（见 §9） |
| 正向/负向触发 | 每个 Skill Card 定义 should-trigger 与 should-not-trigger 示例（见 §7） |
| Skill Card | 标准 SKILL.md 元数据 + 契约 + 边界（见 §8） |
| evals | baseline（无 Skill 直接提问模型）vs with-skill 的对比评测集与判定标准（见 §11） |
| Benchmark | 本地环境下的延迟/吞吐与证据质量基线；不写未经验证的数字（见 §13） |
| 安全边界 | 拒答机制、无人脸/身份推断、无任意代码执行、不冒充官方签名（见 §10） |
| DGX Spark 本地算力 | 统一内存架构、GB10、CUDA 13.0.2、ARM64；本地承担 Harness 运行时与视频预处理 |
| 带证据的视觉结果 | 证据必须含时间戳、关键帧、目标框、置信度四要素（见 §9） |
| OpenCV 的正确定位 | 仅用于抽帧、读元数据、存关键帧；不构成核心创新或卖点 |

## 3. 用户故事

1. 作为园区安防复盘人员，我希望用一句话创建一个追踪 Skill，让它追踪红色背包在多段视频中的移动路径，记录出现的时间、区域和关键画面。
2. 作为使用者，我希望每个结论都有证据（时间、关键帧、目标框、置信度），没有证据的地方明确说"证据不足"，而不是猜。
3. 作为使用者，我希望把创建好的 Skill 直接复用到新拍的视频上，不需要重新描述任务。
4. 作为评审，我希望看到 baseline（不用 Skill）和 with-skill 的对比，知道 Skill 真的带来了可度量的改进。
5. 作为评审，我希望看到 Skill 有明确的触发边界：该用时用，不该用时明确拒绝。

## 4. 最小可行范围（MVP）

- 一个自然语言任务入口：红色背包追踪（对象追踪 + 时间线 + 关键帧 + 证据链）。
- 三个自研 Skill 的骨架与契约先行，业务代码分阶段实现（见 §15）。
- StepFun 多模态模型作为唯一视觉推理来源。
- OpenCV 仅用于抽帧、读取视频元数据、保存关键帧。
- 一组最小 evals：baseline vs with-skill，指标见 §11。
- 90 秒演示脚本（见 §12）。

MVP 明确不做：多对象多类别泛化、实时流处理、本地部署视觉大模型、报告 UI（先用文件输出）。

## 5. 系统架构

```
┌────────────────────────────────────────────────────────────┐
│ 用户（自然语言视觉任务）                                      │
│   "追踪红色背包…时间/区域/关键画面；证据不足不要猜"            │
└───────────────┬────────────────────────────────────────────┘
                ▼
┌────────────────────────────────────────────────────────────┐
│ DSH Agent Harness（本地，DGX Spark）                         │
│  · 任务理解与 Skill 编排                                    │
│  · Skill 发现（.dsh/skills/）与加载                          │
│  · 契约校验、拒答路由、会话与审计                             │
└───┬──────────────────┬──────────────────┬─────────────────┘
    ▼                  ▼                  ▼
┌─────────┐   ┌──────────────────┐   ┌──────────────┐
│Skill A  │   │Skill B           │   │Skill C       │
│task-to- │ → │visual-evidence-  │ → │evidence-     │
│skill-   │   │extractor         │   │report-       │
│compiler │   │                  │   │generator     │
└─────────┘   └────────┬─────────┘   └──────────────┘
                       │ 抽帧 / 元数据 / 存关键帧
                       ▼
              ┌─────────────────┐
              │ OpenCV（底层工具）│  ← 仅此三件事，非核心卖点
              └─────────────────┘
                       │ 帧图像
                       ▼
              ┌─────────────────────────┐
              │ StepFun 多模态模型        │  ← 视觉理解：对象/事件、
              │ api.stepfun.com/        │    目标框、置信度
              │ step_plan/v1            │
              └─────────────────────────┘
                       │ 结构化证据（JSON）
                       ▼
              带时间/关键帧/目标框/置信度的证据结果 + 证据链报告
```

模块职责：

- **DSH Harness**：唯一的编排者；不直接做视觉推理；负责把 A→B→C 串成流水线并做契约与拒答治理。
- **Skill A/B/C**：受控能力单元，详见 §7。
- **OpenCV**：被 Skill B 调用的底层工具，职责被严格限制。
- **StepFun**：视觉理解引擎，只接收帧图像 + 结构化查询，只返回结构化结果。
- **DGX Spark**：上述 Harness 与预处理流水线的本地运行环境。

## 6. DSH Harness / StepFun / Skill / DGX Spark 的职责

| 组件 | 职责 | 不负责 |
| --- | --- | --- |
| DSH Agent Harness | 任务理解；Skill 生成/发现/加载/执行/复用；契约校验；拒答路由；会话与审计日志 | 视觉推理本身；视频解码细节 |
| StepFun 多模态模型 | 帧级对象/事件识别；目标框与置信度；自然语言判定 | Skill 编排；本地资源管理 |
| Agent Skill | 声明式能力单元（SKILL.md + 契约 + 触发边界）；可复用、可评测 | 自由代码执行；跨领域泛化 |
| DGX Spark 本地算力 | 运行 Harness；视频抽帧与元数据处理；Benchmark 运行环境 | （当前）本地视觉大模型推理 |
| OpenCV | 抽帧、读视频元数据、保存关键帧 | 任何"核心能力"定位 |

## 7. 三个 Skill 的设计

### 7.1 task-to-skill-compiler（Skill A）

- 职责：把一句自然语言视觉任务编译为受控 Skill 配置草稿（Skill Card）。
- 输入：自然语言任务描述 + 约束（对象描述、时间/区域约束、证据要求、拒答条件）。
- 输出：Skill Card 草稿（name、description、输入输出契约、正/负向触发、安全边界、参数：抽帧间隔、置信度阈值、最小证据条数）。
- 正向触发示例：用户说"创建一个 Skill 追踪红色背包…"。
- 负向触发示例：用户要求识别人脸/身份；用户要求生成任意可执行代码；任务超出"视觉证据"范围（如纯文本问答）。
- 红线：不生成、不执行任何自由形式的模型代码或脚本；产出物只有声明式配置。

### 7.2 visual-evidence-extractor（Skill B）

- 职责：按 Skill Card 配置执行视觉证据抽取。
- 输入：Skill Card（或编译产物）+ 图片或短视频 + 目标描述。
- 处理（图片）：调用本地 Ollama Qwen Vision 做对象存在性判断，校验结构化输出（见任务 03 实施）。
- 处理（视频，任务 04 实施）：`extract_frames.py` 按可配置采样策略（最大帧数、时间间隔、起止时间）抽帧并保存关键帧 → `trace_video.py` 对帧逐帧**复用图片分析逻辑** → 聚合为视频级证据时间线（timeline.json：source_video/duration_ms/sampled_frames/target_query/timeline[]/summary{}）。
- 输出：证据列表，每条含 `timestamp`、`keyframe_ref`、`bbox`、`confidence`、`reason`；整体含 `evidence_sufficient` 布尔与 `gaps` 列表。
- 拒答规则：`evidence_sufficient = false` 或 `confidence < threshold` 或证据条数 < 最小值时，输出"证据不足"并列出缺口，禁止猜测。
- 视频附加规则：不得凭空生成时间线；不得把连续帧自动解释成同一个对象；bounding_box 不可靠时必须为 null；严格区分 confirmed / not_found / abstained / failed；所有结论可回溯到具体帧。
- 红线：不做人脸识别与身份推断；不做跨镜头身份追踪；OpenCV 仅限抽帧/元数据/存关键帧。

### 7.3 evidence-report-generator（Skill C）

- 职责：把证据列表汇总为事件证据链报告。
- 输入：Skill B 的证据 JSON + Skill Card 引用。
- 输出：按时间线组织的报告（关键帧索引、目标框、置信度汇总、移动路径描述、证据缺口、所用 Skill 版本）。
- 降级呈现：证据不足时报告显著位置标注"证据不足：缺口列表"，不给确定性结论。
- 红线：不做视觉推理；不执行任意模型生成代码。

## 8. Skill 目录结构

```
.dsh/skills/
├── task-to-skill-compiler/
│   └── SKILL.md          # skeleton：name/description/职责/状态
├── visual-evidence-extractor/
│   └── SKILL.md          # skeleton
└── evidence-report-generator/
    └── SKILL.md          # skeleton
```

后续阶段每个 Skill 目录可扩展（如 `contracts/`、`evals/`、`references/`），但当前阶段只允许 SKILL.md 骨架，不得加入业务代码。

Skill Card 必填字段：`name`、`description`、`status`、`输入契约`、`输出契约`、`正向触发`、`负向触发`、`安全边界`、`拒答条件`。

## 9. 输入输出契约

统一原则：契约用 JSON Schema 描述；任何一步输入不满足契约时，Harness 必须拒收并说明原因，而不是猜测性放行。

**Skill A 契约**

```json
{
  "input": {
    "type": "object",
    "properties": {
      "task": { "type": "string" },
      "constraints": { "type": "object" }
    },
    "required": ["task"]
  },
  "output": {
    "type": "object",
    "properties": {
      "skill_card": { "type": "object" },
      "accepted": { "type": "boolean" },
      "reject_reason": { "type": "string" }
    },
    "required": ["accepted"]
  }
}
```

**Skill B 契约（证据 schema 四要素）**

```json
{
  "evidence": [
    {
      "timestamp": "HH:MM:SS.mmm",
      "keyframe_ref": "path/to/keyframe.jpg",
      "bbox": [x, y, w, h],
      "confidence": 0.0,
      "reason": "string"
    }
  ],
  "evidence_sufficient": true,
  "gaps": ["string"]
}
```

**Skill C 契约**

```json
{
  "report": {
    "timeline": ["..."],
    "keyframes": ["..."],
    "confidence_summary": { "min": 0.0, "max": 0.0, "mean": 0.0 },
    "path_description": "string",
    "gaps": ["string"],
    "skill_version": "string"
  },
  "insufficient_evidence": true
}
```

## 10. 安全与治理

- **拒答优先**：任何阶段证据不足（低置信度、低证据条数、目标描述不可判定）必须显式拒答并列出缺口；禁止猜测、禁止补全。
- **隐私红线**：不做人脸识别、身份推断、个人信息识别；目标描述限定为可见物体/事件。
- **无任意代码执行**：Skill 产物是声明式配置与数据；不执行模型自由生成的代码；业务代码只来自仓库中受版本控制的实现。
- **不冒充**：自研 Skill 不得冒充 NVIDIA 官方签名；NVIDIA 官方 Skills 当前不可用，文档/演示必须如实标注"未接入"。
- **密钥纪律**：禁止输出任何 API key、token、密码或 GUI token；StepFun 端点地址可以写，密钥绝不入库。
- **资源治理**：不得启动新大模型、不得停止/重启 MiniMax-H3 / Ollama / DSH；内存操作先评估后执行。
- **可审计**：每次 Skill 执行应记录输入契约哈希、模型端点、证据条数与拒答原因，供 evals 复核。

## 11. baseline / with-skill 评测

- **baseline**：不使用本项目 Skill。运行器把同一任务文本交给**同一个 DSH Agent**，但在项目外的隔离目录中执行（该目录无 `.git` 祖先，因此 `<projectRoot>/.dsh/skills/` 不会被 DSH 发现，项目 Skill 不进入会话 catalog；隔离目录每次运行前重建，避免遗留文件影响）。baseline 可自由使用自身能力（自建脚本、程序化分析、直接调用本地 Ollama 等），不获得项目 Skill 的契约、脚本与安全边界。
- **with-skill**：在项目根运行，DSH 发现并加载三个自研 Skill，走 compiler → extractor → report generator 流水线，输出受契约约束的结构化证据。
- **两侧唯一变量**：是否加载项目 Skill。任务文本逐字节相同，`max_frames`、超时、模型、媒体相同；按任务交替执行（E1 baseline → E1 with-skill → E2 baseline → …）；每任务独立全新 headless 会话；运行前统一预热一次。
- **观测限制（必须随结果声明）**：baseline 若自建脚本内部调用视觉模型，其调用次数无法存档，因此 baseline 的 Qwen 调用计数只是**可观测下限**。
- **评测集（任务 15 修正，与 `evals/tier3/evals.json` 一致）**：9 个任务（E1 单视频正向 / E2 单视频负向 / E3 多视频正向 / E4 多视频负向 / E5 证据不足 / E6 非视觉 / E7 敏感属性 / E8 非法媒体路径 / E9 缺失媒体），媒体为本机两段真实短视频（`h3-smoke.mp4` 与 `h3-t2va-8s.mp4`），视觉任务统一 `max_frames=2`；负向/边界用例（E2/E4/E5/E6/E7/E8/E9，共 7 个）全部保留。**尚未使用仓储/园区实拍素材，也没有逐样本 ground-truth 出现时段标注**——判定口径为"允许措辞/禁止措辞 + 结构化产物完整性的确定性规则评分"，不是位置/时间准确率（需要 ground-truth，见 §17 偏差记录）。
- **指标**（设计期指标；实际 Tier-3 落地口径见 §17 偏差记录——以通过数/总数 + 数量指标表达，不写无分母百分比）：
  - 证据完整率：四要素（时间/关键帧/目标框/置信度）齐全的证据占比；
  - 拒答正确率：证据不足时拒答、证据充分时作答的正确比例（惩罚猜测）；
  - 位置/时间准确率：目标框与出现时段和标注的一致程度（**未实现：无 ground-truth 标注**）；
  - 可复用性：同一 Skill 在新视频上零改动加载成功率（已在任务 03/05/06 的图片/单视频/多视频上验证）；
  - 时延与资源：单视频端到端时延、抽帧与推理占比。
- **判定原则**：宁可漏报不可错报（错报权重高于漏报）；所有指标必须从实际运行记录统计，不写未经验证的数字。

## 12. 90 秒演示流程

> **架构前提（任务 15 修正，与 §17 偏差记录一致）**：当前 DSH 配置下 StepFun `step-5-preview` **不声明图片输入能力**，不读取图片、不识别视频帧。演示中**视觉识别一律由 DGX Spark 本地 Ollama Qwen3.8-27B Vision 完成**；StepFun 只负责理解用户文本任务、规划并生成结构化 VisualTaskSpec。OpenCV 只做底层解码与抽帧。
>
> 下方流程为设计期叙事，实际定稿的 3 分钟分镜脚本见 `docs/COMPETITION_READINESS_AUDIT.md` §9.2（按秒拆分，含降级方案）。

| 时间 | 动作 | 要点 |
| --- | --- | --- |
| 0–10s | 口播定位 + 输入任务 | "追踪红色背包在多段视频中的出现情况；证据不足不要猜"（不断言跨摄像头移动） |
| 10–25s | Harness 调用 Skill A（task-to-skill-compiler） | 屏幕上出现生成的 Skill Card：契约、触发边界、阈值；StepFun 文本链路生成 VisualTaskSpec |
| 25–55s | Harness 调用 Skill B（visual-evidence-extractor） | OpenCV 抽帧 → **本地 Qwen Vision 逐帧识别** → 证据流出现（时间戳/关键帧/目标框/置信度） |
| 55–70s | Harness 调用 Skill C（evidence-report-generator） | 证据链报告生成；切换一段新视频复用同一 Skill |
| 70–85s | 负向演示 | 输入一个证据不足/超出范围的任务，展示拒答与缺口说明 |
| 85–90s | 收尾 | 强调：DSH Harness 治理 + StepFun 文本规划 + 本地 Qwen 视觉 + 契约化 Skill + 本地 DGX Spark |

## 13. 资源和内存约束

- 环境：DGX Spark / GX10，NVIDIA GB10，统一内存架构，CUDA 13.0.2，ARM64。
- 现状：MiniMax-H3（:8000，FL2VA）占用大量统一内存；Ollama（:11434）运行 Qwen3.8-27B-GGUF；DSH 0.1.5-rc.2 运行中。
- 约束：
  - 本项目不启动新的大模型、不下载模型；视觉推理走 StepFun API。
  - 抽帧间隔、并发帧数、关键帧保存策略必须可配置，避免本地内存/磁盘峰值。
  - Benchmark 只测量端到端时延与证据质量，不与 MiniMax-H3 抢内存。
  - 任何内存敏感操作先评估、后执行，未经确认不动现有服务。
- 红线：未经验证的性能数字不得写入任何文档。

## 14. 失败降级策略

| 失败点 | 降级行为 |
| --- | --- |
| 自然语言任务无法解析为合法 Skill 配置 | Skill A 拒收并给出原因，不生成半成品 Skill |
| StepFun 调用失败/超时 | 该批次标记为"未检验"，不计入证据；整体证据不足时拒答 |
| 目标框缺失或低置信度 | 丢弃该条证据并记入 gaps；条数不足即拒答 |
| 抽帧失败/视频元数据不可读 | 该视频标记为不可用并说明；不影响其他视频继续 |
| 报告生成时证据缺口过多 | 输出"证据不足"报告，仅列缺口与已有证据 |
| 任一阶段契约不满足 | Harness 中断流水线并输出结构化错误，禁止猜测性放行 |

## 15. 实现阶段（实际进度）

1. **阶段 0（已完成）**：仓库初始化、三个 Skill 骨架、上下文/设计/README/状态文档。无业务代码。
2. **阶段 1（已完成，任务 03）**：Skill A 契约与最小解析逻辑；Skill Card 模板落地；DSH 加载机制验证（发现/加载/复用）；本地 Qwen Vision 图片证据闭环；报告生成器反幻觉规则；端到端 72.5s 实测。
3. **阶段 2（已完成，任务 04）**：短视频最小闭环——OpenCV 抽帧（仅底层工具）+ 逐帧复用图片分析能力 + 证据时间线聚合 + 视频报告模式 + 16 项测试；**真实 Qwen 视频逐帧调用因 MiniMax-H3 占用统一内存被资源守卫阻塞，待资源窗口验证**（见 `artifacts/task-04/（内部留档）run-summary.md（内部留档）`）。
4. **阶段 2.5（已完成，任务 05 重跑）**：**DSH Agent 自主视频演示**——用户关停 MiniMax-H3 后资源窗口打开（MemAvailable 115.55 GiB），两次全新 `dsh --profile headless` 会话由会话内 Agent 自主发现/加载 Skill、生成并校验 VisualTaskSpec、调用抽帧/视觉证据/报告工具并得出结论；**真实 Qwen 视频逐帧调用首次验证**（正向 confirmed=5/failed=1、负向 not_found=6）；**"DSH 会话内模型自主加载 Skill 并驱动流水线"首次验证**。证据见 `artifacts/task-05/（内部留档）run-summary.md（内部留档）`、`agent-session-summary.md`。注：此为单段短视频的 Agent 自主编排，非跨摄像头/多段追踪。
5. **阶段 3 第一部分（已完成，任务 06）**：**多段视频统一证据时间线（DSH Agent 自主驱动）**——多媒体 VisualTaskSpec（`source_media` 来源对象数组，向后兼容旧版字符串）、`trace_multi_video.py`（每来源复用 `trace_video.py` 单段能力，未重写视觉提示词）、按 `time_offset_ms` 计算全局排序时间的统一全局时间线、每来源与全局首末确认/确认帧数、failed/abstained/not_found 全保留、像素坐标受控归一化（任务 05 出现过的像素坐标格式本次被正确处理并记录审计字段）、跨视频语义边界（matched target query / confirmed in source A / confirmed in source B；禁止 same physical instance / moved from A to B / identity matched 等断言；`semantic_limitations` 随产物与报告输出）。两次全新 headless 自主会话真实跑通：正向（太阳，两段真实视频）8/8 confirmed、负向（紫色大象）8/8 not_found；规则测试 32/32、回归 16/16、任务书验证 18/18。证据见 `artifacts/task-06/（内部留档）`。注：全局时间线是**证据聚合，不是跨摄像头身份追踪**；测试视频为两段真实视频（开放式探针确认共同非敏感目标），未使用 technical fixture。
6. **阶段 3 第二部分（已完成，任务 07）**：**Tier-3 baseline vs with-skill 对照评测**——评测集 `evals/tier3/evals.json`（9 任务：单/多视频正负向、证据不足、非视觉、敏感属性、非法路径、缺失媒体；视觉任务 max_frames=2）；运行器 `scripts/run_tier3_eval.py`（baseline 项目外隔离、双侧同文本/同参数/交替执行/统一预热/日志脱敏）；评分器 `scripts/score_tier3_eval.py`（确定性规则，不用大模型当裁判）。结果：Discoverability 4/9→8/9、Effectiveness 6/9→9/9、Security 8/9→8/9、Correctness 8/9→8/9、总耗时 −38.7%；**Verdict: PARTIAL**（with-skill E9 缺失媒体处理失败，未隐藏）。证据见 `BENCHMARK.md` 与 `artifacts/task-07/`。
7. **阶段 3 剩余（仍未完成，如实记录）**：评测集扩充与多轮重复；baseline vs with-skill 的规模化统计（当前为 9 任务小样本，不声称统计显著性）。E9 缺口已修复（任务 08）。
8. **阶段 3 第三部分（已完成，任务 09）**：**评测器 v2 与冻结数据全量重评分**——v1 冻结评分器存在 stdout 断言语境误报（合规否定/政策声明被误判），按用户决策（方案 B）新增版本化评分器 v2（导入继承 v1 全部规则，唯一变化为 stdout/文件一致的从句级语境判定，回归 17/17），对任务 08 冻结数据 18/18 对称重评分（未重跑模型会话），差异仅 2 项已知误报修复；最终 Security 9/9→9/9、Correctness 7/9→9/9、Discoverability 5/9→9/9、Effectiveness 6/9→9/9，**Verdict: PASS**（历史 PARTIAL 保留）。
9. **阶段 4 第一部分（已完成，任务 10）**：**本地视觉证据工作台**——`app/` 零依赖前端 + `scripts/build_demo_manifest.py`（真实 artifacts → Manifest）+ `scripts/serve_demo.py`（只读 localhost:8787，媒体 allowlist）+ `.interface-design/system.md` 设计系统；7 个运行记录切换（含 Tier-3 完整历史链，PARTIAL 保留）；21/21 测试通过；CPU-only，不重新运行模型。
10. **阶段 4 第二部分（已完成，任务 12/12.1/13）**：**Evidence Workbench 重设计为 Apple 风格亮色界面**——首屏 Hero（真实关键帧 + 主体 + 结果行）、横向九阶段证据链路（中文）、Provenance 右侧抽屉、验证终章；任务 12 静态 22/22 + 浏览器 40/40，任务 12.1 静态 26/26 + 浏览器 43/43（产物见 `artifacts/task-12/`、`artifacts/task-12-1/`）；任务 13 为云端提交级部署，部署 Agent 回报云端浏览器回归 47/47（**该回归产物未入库，仓库内可独立复算的记录为任务 12.1 的 26/26 + 43/43**）。设计系统记录见 `.interface-design/system.md`（任务 15 已更新为当前亮色令牌）。
11. **阶段 4 剩余（未完成）**：Skill 复用心流的新视频零改动复用演示、评测集规模化、统计显著性（均明确不做或资源不足，见 `docs/COMPETITION_READINESS_AUDIT.md` §12）。

## 16. 明确非目标

- **不是**普通 OpenCV 视频处理工具：OpenCV 只做抽帧、读元数据、存关键帧，绝不是核心创新、核心架构或主要卖点。
- **不是**任意领域 Skill 生成器：只做"受控视觉证据类 Skill"的编译与验证。
- 不做人脸识别、身份推断；不做跨镜头身份追踪。
- 不执行任意模型生成代码。
- 不接入未发现的 NVIDIA 官方组件（官方 Skills、TAO、VSS、DeepStream、NIM 当前均未发现、未接入）。
- 不做实时视频流处理（MVP 只做离线短视频）。
- 不写未经验证的数字；不输出任何密钥。

## 17. 实施偏差记录（设计 vs 实际，必须如实维护）

| 设计原文 | 实际实施 | 原因与记录 |
| --- | --- | --- |
| "StepFun 多模态模型作为唯一视觉推理来源" | 视觉后端为 **DGX Spark 本地 Ollama Qwen3.8-27B（vision）**；StepFun 仅负责文本任务解析与 Agent 规划 | 当前 DSH 配置下 StepFun provider 未声明图片输入能力，图片调用不可用（任务 02 实证）。切回条件：用户更新 provider 配置并确认可用图片模型 id |
| 阶段 2 "OpenCV 抽帧 + StepFun 调用" | OpenCV 5.0.0 抽帧（复用本机 vLLM 环境，未装依赖）+ **逐帧复用本地 Qwen 图片能力** | 同上；抽帧链路本身按设计实现（仅底层工具） |
| MVP "本地部署视觉大模型"为非目标 | 本地 Qwen 为当前视觉后端（按需加载，任务 03 实测 34.6 GB） | 上述路由偏差的后果；加载受统一内存资源守卫约束（默认阈值 40 GiB） |
| 视频链路（阶段 2/3） | 阶段 2 已完成单段短视频闭环；多段/跨镜头未实现 | 任务 04；**真实 Qwen 视频逐帧调用与 DSH Agent 自主编排已于任务 05 在资源窗口内验证**（MiniMax-H3 被用户关停后 MemAvailable 115.55 GiB） |
| "StepFun 作为唯一视觉推理来源" | 视觉后端为本地 Qwen；StepFun 仅文本规划；**但 Agent 编排（发现/加载 Skill、驱动流水线）由 DSH Harness 完成** | 任务 02（StepFun 图片输入不可用）+ 任务 05（DSH 自主编排真实验证） |
| "多段视频中的对象追踪"（首个演示场景） | 阶段 3 第一部分（任务 06）实现为**多段视频统一证据时间线**：每来源独立时间线 + 全局证据聚合；**不做跨摄像头身份/实例关联**（same physical instance / moved from A to B / identity matched 等断言被显式禁止，`semantic_limitations` 随产物输出）；演示中的"红色背包跨段移动路径"叙事相应收窄为"同一目标查询在多来源中分别确认" | 任务 06；跨摄像头身份关联需要可靠的关联证据，超出当前可验证范围，列为明确非目标 |
| bounding_box 契约（0–1 归一化） | 任务 06 增加**像素坐标受控归一化**：模型返回像素坐标且全部条件满足（四元数值、全部 >1、x1<x2/y1<y2、不越界、可读真实帧尺寸）时确定性归一化并记录审计字段（raw/format/applied/帧尺寸）；混合/越界/顺序错误/尺寸未知不归一化（置 null + warning，不重跑模型） | 任务 05 真实运行中出现一帧 Qwen 返回像素坐标 `[431,222,545,356]` 被整体拒绝；任务 06 改为受控归一化，任务 06 真实运行中 3/8 帧触发且数学校验全部正确 |

| "evals：baseline vs with-skill 对比评测集"（§11） | 阶段 3 第二部分（任务 07）落地为 **Tier-3 对照评测**：9 任务小样本、确定性规则评分、严格隔离与同文本对照；**Verdict PARTIAL**（with-skill E9 失败未隐藏） | 任务 07；指标口径按"通过数/总数"，小样本不写无分母百分比；大规模统计与多轮重复未做 |
| 设计预期 Skill 带来可度量改进（§11 指标） | 首轮实测：Discoverability 4/9→8/9、Effectiveness 6/9→9/9、总耗时 −38.7%；Security/Correctness 持平（8/9=8/9，失分点不同） | 任务 07；改进显著但样本小，不外推 |

| 评测器缺陷处理 | v1 冻结评分器的 stdout 语境误报按"不修改/单独报告/停止/用户决策"流程处理；用户选方案 B 后以版本化 v2 修复（唯一逻辑变化），对冻结数据全量重评分 | 任务 08/09；v1 PARTIAL 与误报发现过程完整保留，Verdict 由 v2 实测决定（PASS），未预设 |
| "evals：baseline vs with-skill 对比评测集"（§11） | 两轮完整运行 + v2 重评分；**当前 Verdict: PASS**（with-skill 四维 9/9） | 任务 07/08/09；小样本不外推；baseline Qwen 计数为可观测下限 |
| §11 评测集"仓储/园区多段短视频、红色背包追踪、每条样本标注 ground-truth 出现时段与区域" | 任务 15 修正为与实现一致：9 任务（E1–E9，含 7 个负向/边界用例）、媒体为本机两段真实短视频、视觉任务 `max_frames=2`；**无仓储实拍素材、无逐样本 ground-truth 标注**，因此位置/时间准确率指标未实现，实际判定口径为确定性规则评分（允许措辞/禁止措辞 + 结构化产物完整性 + 安全边界） | 任务 07/08/09 实现（`evals/tier3/evals.json` v1.0.0 冻结）；原描述既不符合实现，也会让评委误以为有标注数据集支撑的位置准确率结论 |
| §11 baseline 定义"直接把同一任务与抽帧图像交给 StepFun 模型，让其自由回答" | 任务 15 修正为与 Tier-3 实现一致：**baseline = 同一个 DSH Agent 在项目外隔离目录（无 `.git` 祖先、项目 Skill 不被发现、目录每次重建）自主执行同一任务文本**，可自建脚本 / 直接调用本地 Ollama；with-skill = 项目根加载三 Skill。两侧同文本、同 `max_frames`/超时/模型/媒体、按任务交替、每任务独立会话、运行前统一预热 | 任务 07 实现（`scripts/run_tier3_eval.py`：隔离目录 + 污染检测 + 交替执行）；原定义既不符合实现，也不符合"StepFun 不读图"的当前架构。**修正只涉及文档表述，未改动冻结评测集、评分器、PASS 条件或任务 07/08 原始 artifacts** |
| §12 演示流程"抽帧 → StepFun 识别""StepFun 视觉" | 任务 15 修正为"OpenCV 抽帧 → **本地 Qwen Vision 逐帧识别**"，收尾改为"DSH Harness 治理 + StepFun 文本规划 + 本地 Qwen 视觉 + 契约化 Skill + 本地 DGX Spark"；并注明 StepFun 当前配置不声明图片输入能力 | 任务 02 实证 + §17 既有偏差记录；原表述与真实架构矛盾，会被评委判定为过度声明 |
