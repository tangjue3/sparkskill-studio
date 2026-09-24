# REPRODUCTION — SparkSkill Studio 复现与部署说明

> 本文面向**第一次看到项目的评委或开发者**：如何在一台准备好的 NVIDIA DGX Spark 上验证本项目。
> 所有命令均从仓库根目录执行。文中 `<...>` 为需按你的环境替换的占位符；本文不含任何密钥、token 或凭据。
>
> 相关文档：`README.md`（项目总览）、`docs/OPTIMIZATION_NOTES.md`（已做/未做的优化）、
> `docs/COMPETITION_READINESS_AUDIT.md`（赛事交付差距审计）、`BENCHMARK.md`（Tier-3 完整历史）。

---

## 1. 项目在做什么（一句话）

用户输入一句自然语言视觉任务，DSH Agent Harness 理解任务并生成/配置一个受控 Agent Skill，
Skill 在 DGX Spark 本地执行视觉分析，输出带时间、关键帧、目标框和置信度的证据结果，并可在新媒体上复用。

**真实技术分工（全仓统一表述，不得混淆）**：

| 组件 | 职责 | 明确不负责 |
| --- | --- | --- |
| StepFun `step-5-preview`（经 DSH 文本链路） | 理解用户文本任务、规划、生成结构化 VisualTaskSpec | **不读取图片、不识别视频帧、不做视觉推理**（当前 DSH 配置下该 provider 未声明图片输入能力，图片调用在链路层被拒） |
| DSH `0.1.5-rc.2` | Agent Harness：发现、加载和编排项目 Skill，管理会话与工具调用 | 不承担视觉推理本身 |
| `task-to-skill-compiler` | 把文本视觉任务编译为受约束的 VisualTaskSpec；媒体来源 provenance 硬门 | 不做视觉推理、不生成可执行代码 |
| OpenCV（5.0.0） | 底层视频解码、读取元数据、抽帧、保存关键帧 | **不是核心创新、不是卖点** |
| 本地 Ollama Qwen3.8-27B Vision | 读取图片和视频帧，做对象存在性判断，生成结构化视觉证据 | 不做 Skill 编排、不做任务编译 |
| `visual-evidence-extractor` | 约束视觉调用、证据格式、坐标规范与拒答边界 | 不生成最终报告 |
| `evidence-report-generator` | 依据证据生成报告并执行反幻觉交叉校验 | 不做视觉推理 |
| Evidence Workbench（`app/`） | **只读展示已经保存的真实 artifacts** | **不在浏览器内实时调用 StepFun / Qwen / DSH / 三个 Skill** |

**平台价值**：NVIDIA DGX Spark（GX10 / GB10）本地算力 + 统一内存环境下的本地视觉模型运行；
数据不离开本地视觉推理环境；Agent、视觉模型与生成服务之间的资源治理。
**未接入** NVIDIA 官方 Skills、TAO、VSS、DeepStream、NIM（当前环境未发现，不得声称已安装或已接入）。

---

## 2. 硬件与软件前提

### 2.1 硬件

- NVIDIA DGX Spark / GX10，GPU 为 NVIDIA GB10，统一内存架构（约 119 GiB），ARM64（aarch64）；
- CUDA 13.x（本仓库开发时实测 `/usr/local/cuda-13.0`，驱动随机器镜像提供）。

### 2.2 软件（本项目开发时实测版本）

| 组件 | 实测版本 | 用途 |
| --- | --- | --- |
| Python | 3.12.3 | 全部业务脚本（**纯标准库，无第三方依赖**） |
| Node.js | 22.20.0 | 仅用于 `node --check` 语法校验与浏览器 QA 脚本；**前端零依赖、无构建、无 npm install** |
| DSH | `0.1.5-rc.2` | Agent Harness（headless 与 web profile） |
| Ollama | 0.33.2 | 本地视觉后端服务（`:11434`） |
| 视觉模型 | `modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`（27.3B，Q4_K_M，vision） | 本地图片/帧理解 |
| OpenCV | 5.0.0 | 抽帧（**复用机器上已有的安装，不新增依赖**；系统 python3 无 cv2 时由 `skill_env.py` 自动切换到含 cv2 的解释器） |

> 版本会随环境变化；上表为"已验证环境"快照，不是最低要求。任何组件缺失时按第 8 节降级处理，**不要为了跑通而安装依赖或下载模型**。

### 2.3 需要提前存在的配置（否则部分步骤无法执行）

| 步骤 | 前置条件 |
| --- | --- |
| DSH headless 会话（真实 Agent 流水线） | DSH 已安装；DSH 中已配置 StepFun provider（openai-completions 兼容端点 + `step-5-preview` 模型 id）；`agent-default-model` 指向该 provider |
| 视觉证据抽取 | Ollama 已运行且已拉取 Qwen3.8-27B-GGUF（vision）模型；`MemAvailable ≥ 40 GiB` |
| 媒体路径校验 | 媒体文件位于授权根目录内（默认：项目根本身 + 机器上既有的测试媒体目录；可用 `SPARKSKILL_AUTHORIZED_MEDIA_ROOTS` 以 `os.pathsep` 分隔受控扩展） |
| 静态工作台 | 仅需 Python 3（标准库） |

> StepFun 与 Ollama 的**凭据由用户在自己的环境中配置**；本仓库不包含、也不读取任何密钥。

---

## 3. Skill 发现目录与契约结构

DSH 通过 `@deepseek-ai/dsh-skill-filesystem` 插件扫描 Skill 目录，本项目的 Skill 位于：

```
<projectRoot>/.dsh/skills/
├── task-to-skill-compiler/     # 第一环：自然语言 → VisualTaskSpec + 媒体来源硬门
├── visual-evidence-extractor/  # 第二环：本地 Qwen Vision → 结构化视觉证据
└── evidence-report-generator/  # 第三环：证据 → 反幻觉报告
```

每个 Skill 的标准结构（DSH `parseSkillFile` 硬性要求 + 本项目约定）：

```
<skill>/
├── SKILL.md            # 必须以 YAML frontmatter 开头：name（kebab-case）+ description（非空）
├── skill-card.md       # Skill Card：职责/输入输出/触发/拒答/安全边界/评测
├── BENCHMARK.md        # 真实运行记录（通过数/总数，不写无分母百分比）
├── evals/evals.json    # 评测用例（正向/负向/契约/向后兼容）
├── references/         # 渐进式披露：契约与规则的详细文档
└── scripts/            # 纯标准库脚本（校验/执行/测试）
```

**关键约定**：`SKILL.md` 缺少 frontmatter 或 `name` 不是 kebab-case 时，DSH 会**静默跳过**该 Skill（只记警告，模型侧无诊断）。任务 02 曾因此三个 Skill 全部不可见，补齐 frontmatter 后恢复（见 `docs/SMOKE_TEST_REPORT.md` §2）。

---

## 4. 静态工作台：启动与验证入口（不需要模型）

Evidence Workbench 是**只读的 recorded-artifact viewer**：展示已存档的真实运行产物，
不在浏览器内实时调用任何模型。

### 4.1 启动

```bash
python3 scripts/serve_demo.py                # 默认 http://127.0.0.1:8787/
python3 scripts/serve_demo.py --port 9000    # 自定义端口
```

浏览器打开 `http://127.0.0.1:8787/`。服务特性：

- 只监听 `127.0.0.1`（不对外）；仅 GET/HEAD（POST 返回 501）；
- 不服务 `.git`、凭据、配置文件、模型权重；不允许目录遍历（`../`、URL 编码穿越均 403）；
- 媒体仅限显式 allowlist（`scripts/serve_demo.py` 的 `MEDIA_ALLOWLIST`；公开版 allowlist 指向仓库内 `artifacts/task-16|task-18/fixtures/videos/` 的自产合成 fixture——内部留档版曾指向开发机测试媒体），URL 只暴露 id 不暴露绝对路径；支持 Range/206。

### 4.2 Manifest 重新生成（可选）

```bash
python3 scripts/build_demo_manifest.py                 # 写入 app/data/demo-manifest.json
python3 scripts/build_demo_manifest.py --out <path>    # 输出到指定路径
```

构建器从真实 artifacts 读取数据，构建期做凭据自检（命中即中止），缺失字段安全降级；
**不要把 Manifest 当数据源手写**，它是 artifacts 的投影。

### 4.3 自动化验证入口

```bash
python3 scripts/test_demo_app.py                        # 静态测试（26 项）
python3 scripts/test_demo_app.py --results-json <path>  # 结果落盘
node --check app/app.js                                 # 前端语法校验
```

`test_demo_app.py` 会临时启动一个本地只读服务（测试端口）并临时执行 Manifest 构建器验证可生成性，
退出时恢复已提交快照；**它不调用任何模型**。任务 12.1 的静态测试产物为内部留档；公开版本次实测 26/26 通过。

浏览器 QA（需要本机 Chrome/Chromium，按需执行，非必需）：任务 12.1 的浏览器 QA 脚本与产物为内部留档；
公开版交付前已用 Playwright + Chrome 完成真实浏览器 QA（首页/六条运行记录/证据视图/Provenance 抽屉/
Tier-3 历史链/控制台无错误，结果见交付报告的 QA 记录）。

### 4.4 工作台能看什么

- 6 条运行记录：任务 16 / 任务 18 单视频时序证据回放（真实 Qwen 调用、输入为仓库内自产合成 fixture）+
  Tier-3 历史链四条（初次 PARTIAL、E9 修复、评测器 v1 误报发现、Tier-3 最终 PASS v2）；
  内部留档版另有任务 05/06 的记录（媒体为内部测试视频，不随公开仓库分发）；
- 九阶段证据链路（用户任务 → StepFun 任务规划 → DSH 技能匹配 → 视觉任务规范 → 视频抽帧 →
  Qwen 视觉证据 → 全局证据时间线 → 最终结论 → Tier-3 验证）；
- 五级 Truth Status：Verified / Recorded / Structural / Blocked / Synthetic Fixture；
- Tier-3 完整历史链：Initial PARTIAL → E9 Remediation → Evaluator v1 Finding → Evaluator v2 PASS
  （**不得只展示最终 PASS**）。

---

## 5. 真实流水线入口（需要模型与资源窗口）

> **资源前提**：调用视觉模型前会检查 `/proc/meminfo` 的 `MemAvailable`，低于阈值（默认 40 GiB；
> Qwen3.8-27B 加载约需 34.6 GB）时**不加载模型**，全部帧标记 failed 并如实报告"真实视觉调用被资源条件阻塞"。
> 不得用 `--allow-low-memory` 强行加载，不得停止机器上其他服务来腾内存。

### 5.1 单图片闭环

```bash
# 1) 生成 VisualTaskSpec（由 DSH + StepFun 文本链路完成；以下为本地校验示例）
python3 .dsh/skills/task-to-skill-compiler/scripts/validate_task_spec.py \
    --schema schemas/visual-task-spec.schema.json --input <spec.json>

# 2) 视觉证据抽取（本地 Qwen Vision）
python3 .dsh/skills/visual-evidence-extractor/scripts/analyze_image.py \
    --task-spec <spec.json> --image <image.png> \
    --output <evidence.json> --save-raw <raw-model-output.json>

# 3) 报告生成（反幻觉规则引擎，无模型调用）
python3 .dsh/skills/evidence-report-generator/scripts/generate_report.py \
    --task-spec <spec.json> --evidence <evidence.json> --output <report.json> --mode image
```

### 5.2 单段短视频闭环

```bash
# 抽帧（OpenCV，只读原视频）
python3 .dsh/skills/visual-evidence-extractor/scripts/extract_frames.py \
    --video <video.mp4> --output-dir <frames-dir> --interval-ms 1000 --max-frames 8

# 逐帧分析 + 聚合为时间线（复用 analyze_image.py，未重写视觉提示词）
python3 .dsh/skills/visual-evidence-extractor/scripts/trace_video.py \
    --task-spec <spec.json> --video <video.mp4> --output <timeline.json> \
    --interval-ms 1000 --max-frames 8 --save-raw-dir <raw-dir>

# 视频报告
python3 .dsh/skills/evidence-report-generator/scripts/generate_report.py \
    --task-spec <spec.json> --evidence <timeline.json> --output <report.json> --mode video
```

### 5.3 多段视频统一证据时间线

`source_media` 为来源对象数组：

```json
"source_media": [
  {"source_id": "video-a", "path": "<abs>/a.mp4", "location": "scene-a", "time_offset_ms": 0},
  {"source_id": "video-b", "path": "<abs>/b.mp4", "location": "scene-b", "time_offset_ms": 5000}
]
```

```bash
python3 .dsh/skills/visual-evidence-extractor/scripts/trace_multi_video.py \
    --task-spec <multi-spec.json> --output <global-timeline.json> \
    --interval-ms 1000 --max-frames 4 --per-source-dir <dir> --save-raw-dir <raw-dir>

python3 .dsh/skills/evidence-report-generator/scripts/generate_report.py \
    --task-spec <multi-spec.json> --evidence <global-timeline.json> \
    --output <report.json> --mode multi-video
```

语义边界（硬约束）：每来源独立时间线，保留原视频时间戳；`global = 原时间戳 + time_offset_ms`；
**全局时间线是证据聚合，不是跨摄像头身份追踪**——不断言同一物理实例、不宣称跨视频移动、不做身份匹配；
`semantic_limitations` 随产物与报告输出。

### 5.4 目标时序证据与粗到细自适应采样（任务 16）

`sampling_strategy` 为 VisualTaskSpec 的可选顶层字段（缺失 = 旧版 uniform 行为）：

```json
"sampling_strategy": {
  "strategy": "adaptive_coarse_to_fine",
  "max_model_calls": 12,
  "initial_coverage_samples": 4,
  "target_boundary_precision_ms": 500,
  "max_refinement_rounds": 6,
  "refinement_triggers": ["state_change", "abstained", "low_confidence", "failed"]
}
```

```bash
# 时序证据（uniform 正式 baseline 或 adaptive 粗到细；复用 analyze_image.py 视觉能力）
python3 .dsh/skills/visual-evidence-extractor/scripts/trace_temporal.py \
    --task-spec <spec.json> --video <video.mp4> --output <temporal-evidence.json> \
    --strategy adaptive_coarse_to_fine --max-model-calls 12 \
    --initial-coverage-samples 4 --target-boundary-precision-ms 500 \
    --max-refinement-rounds 6 --input-nature user_media

# 时序证据报告（独立复算 + 交叉校验 + 语义红线展示）
python3 .dsh/skills/evidence-report-generator/scripts/generate_report.py \
    --task-spec <spec.json> --evidence <temporal-evidence.json> \
    --output <temporal-report.json> --mode temporal
```

语义边界（硬约束）：首/末 confirmed 是**采样观察时间**，不等于目标真实进入/离开时间；
两个 confirmed 采样点之间不断言连续存在；状态变化只定位到左右采样点形成的范围
（`uncertainty_width_ms`）；abstained/low_confidence/failed 不退化为 not_found；
不做跨帧身份一致性、不做跨摄像头实例关联、不输出物体运动路径；
**不是 ReID、不是目标跟踪器、不是实时跟踪**。`max_model_calls` 是硬预算：
重复时间戳不重复调用、预算耗尽即停（不算"分析成功"）、资源守卫阻塞时未执行调用不计为真实视觉调用。

### 5.4.1 覆盖感知自适应采样（任务 18：coverage_aware_adaptive）

```json
"sampling_strategy": {
  "strategy": "coverage_aware_adaptive",
  "max_model_calls": 12,
  "initial_coverage_samples": 4,
  "coverage_gap_target_ms": 1500,
  "coverage_call_reserve": 4,
  "target_boundary_precision_ms": 500,
  "max_refinement_rounds": 6
}
```

```bash
python3 .dsh/skills/visual-evidence-extractor/scripts/trace_temporal.py     --task-spec <spec.json> --video <video.mp4> --output <temporal-evidence.json>     --strategy coverage_aware_adaptive --max-model-calls 12     --initial-coverage-samples 4 --coverage-gap-target-ms 1500     --coverage-call-reserve 4 --target-boundary-precision-ms 500     --max-refinement-rounds 6 --input-nature user_media
```

语义边界（附加）：初始覆盖后用 ≤ `coverage_call_reserve` 次调用做**时间覆盖探索**
（largest-gap-first 二分压缩尚未充分观测的间隔，与证据语义无关），剩余预算做**边界细化**；
`initial_coverage_samples + coverage_call_reserve ≤ max_model_calls`；provenance 区分
`initial_coverage_calls`/`coverage_exploration_calls`/`boundary_refinement_calls` 并复算
`max_adjacent_sampling_gap_ms_initial/final` 与 `underobserved_intervals`；
**不保证发现任意短事件**（宽度小于最大相邻采样间隔的事件可能漏检）。

technical fixture（合成技术测试输入，不得外推为真实行业素材结论）：

```bash
python3 scripts/generate_task16_fixtures.py          # 生成并冻结（manifest + ground truth + SHA-256）
python3 scripts/generate_task16_fixtures.py --verify # 评测前冻结复核
python3 scripts/run_task16_comparison.py             # uniform vs adaptive 同预算真实对照（需资源窗口）
```

### 5.4.2 dev Evidence Pack 三策略真实基线（任务 19B；仓库外只读数据包）

dev 数据包（用户交付，位于 Git 仓库之外，只读）：

```text
<DEV_EVIDENCE_PACK_ROOT>   # 仓库外、用户本地只读；不随公开仓库分发（scripts/task19_ingest.py --pack 显式指定）
```

完整基线评测复现（顺序执行；阶段 A 不调用任何模型，阶段 B 需资源门槛通过）：

```bash
# 阶段 A：摄验（隔离/哈希/lineage）→ GT 确定性派生 → 预注册生成 → 自检
python3 scripts/task19_ingest.py                                  # dev 包 14 项摄验 + 卡片复制 + 媒体链接农场
python3 scripts/build_task19_ground_truth.py                      # 九份 GT + 规范化报告（任务 17 契约校验）

# 公开版注：上述 preregistration/build_preregistration.py 与 self_check.py 以及任务 19B 的
# 预注册/摄验/GT/执行/评分详细产物为内部留档；复现者需自备同等结构的 dev 包。
# 阶段 B：三臂真实基线（27 运行 + 256 次真实 Qwen 调用；资源门槛 8 项）
python3 scripts/run_task19_baseline.py --dry-run                  # 预检（不调用模型）
python3 scripts/run_task19_baseline.py                            # 真实运行（warm-up + 9 样本 × 3 臂轮换）
python3 scripts/run_task19_scoring.py                             # 三范围评分 + 逐样本门 + pooled verdict

# DSH 自主真实域验证会话（WEB01，阶段 A 冻结）
python3 scripts/run_task19_dsh_session.py

# 测试与验证
python3 scripts/test_task19_dev_pack.py                           # 22 项确定性测试（前置缺失时 NOT_RUN）
```

关键口径：预算政策 `clamp(ceil(media_duration_ms/1000),12,24)`（只依赖媒体时长）；
transfer-safe 卡是唯一标签来源（原卡与数据包只读）；媒体链接农场为指向仓库外视频的只读符号链接
（不复制视频、不入 Git）；原始视频不得进入公开 Git。

### 5.5 由 DSH Agent 自主驱动（项目主张的用法）

上述脚本也可以由 DSH headless 会话内的 Agent 自主发现/加载 Skill 并调用（任务 05/06 的真实用法）：

```bash
dsh --profile headless "<自然语言视觉任务文本（必须显式提供媒体路径）>"
```

真实运行时长参考（单次完整会话）：任务 05 正向 ≈607 s、负向 ≈320 s；任务 06 正向 ≈2202 s、负向 ≈302 s。
**3 分钟内不可能完成一次完整自主会话**；现场演示请用第 4 节的工作台回放 + 已存档的 reasoning 流。

---

## 6. 规则测试入口（不需要模型、不启动服务）

以下测试均为纯 CPU、纯标准库、只写临时目录，可安全重复执行：

```bash
# 多视频规则测试（规格/校验器/坐标归一化/聚合/报告）
python3 .dsh/skills/visual-evidence-extractor/scripts/test_multi_video_pipeline.py
# 任务 06 原始测试产物为内部留档；公开版本次实测 32/32 通过

# 任务 04 视频规则回归
python3 .dsh/skills/visual-evidence-extractor/scripts/test_video_pipeline.py
# 任务 04 原始测试产物为内部留档；公开版本次实测 16/16 通过（输入为仓库内任务 16 合成 fixture）

# 媒体来源 provenance 契约测试（M1–M8 + V1/V2）
python3 .dsh/skills/task-to-skill-compiler/scripts/test_missing_media_contract.py
# 修复后 10/10（修复前 0/10 的回归产物为内部留档）；公开版本次实测 10/10 通过

# 评分器 v2 回归测试（N/P/C/语境精度/继承性）
python3 scripts/test_score_tier3_eval_v2.py
# 最近一次结果：artifacts/task-09/evaluator-regression.json（17/17）

# 任务 16 时序证据与自适应采样规则测试（T1–T24，无模型调用）
python3 .dsh/skills/visual-evidence-extractor/scripts/test_temporal_evidence.py
# 最近一次结果：artifacts/task-16/test-results.json（27/27）

# 任务 17 Evidence Pack 契约校验（manifest + ground truth）
python3 scripts/validate_evidence_pack.py \
    --manifest <manifest.json> [--ground-truth <gt.json 或目录>]

# 任务 17 时间 Ground Truth 评分器（确定性、CPU-only、零模型调用）
python3 scripts/score_temporal_ground_truth.py \
    --manifest <manifest.json> --predictions <prediction-set.json> \
    --ground-truth <gt.json 或目录> --out <输出目录> [--comparison <比较规格.json>]
# Task 16 冻结产物重评分复现：
python3 scripts/score_temporal_ground_truth.py \
    --manifest artifacts/task-17/contracts/task16-fixture-evidence-pack-manifest.json \
    --predictions artifacts/task-17/rescored-task16/prediction-set.json \
    --ground-truth artifacts/task-17/contracts/ground-truth \
    --comparison artifacts/task-17/rescored-task16/comparison-spec.json \
    --out artifacts/task-17/rescored-task16

# 任务 17 评分器测试（34 fixture 用例 + 4 项一致性测试，无模型调用）
python3 scripts/test_temporal_ground_truth_scoring.py
# 最近一次结果：artifacts/task-17/test-results.json（38/38）

# 任务 17 交付前验证脚本依赖 holdout 同名 fixture（按纪律排除），为内部留档；
# 公开版以 scripts/test_temporal_ground_truth_scoring.py（本次实测 34/34）覆盖其评分器回归。

# 任务 19B dev 包确定性测试（22 项，无模型调用；覆盖任务书第十二节 22 类）
python3 scripts/test_task19_dev_pack.py
# 任务 18 coverage_aware_adaptive 规则测试（36 项，无模型调用）
python3 .dsh/skills/visual-evidence-extractor/scripts/test_task18_coverage_sampling.py
# 最近一次结果：artifacts/task-18/test-results.json（36/36）

# 任务 18 technical fixture 生成与冻结复核
python3 scripts/generate_task18_fixtures.py          # 生成并冻结（6 段新 fixture）
python3 scripts/generate_task18_fixtures.py --verify # 冻结复核（SHA-256/元数据/复用一致性）

# 任务 18 三臂评测（replay=构造证据零模型调用；real=真实 Qwen，需资源门槛通过）
python3 scripts/run_task18_comparison.py --mode replay
python3 scripts/run_task18_comparison.py --mode real   # 资源门槛 8 项通过后才会执行

# 任务 18 顶层产物组装 + 交付前验证（20 项）
python3 scripts/assemble_task18_final.py
python3 artifacts/task-18/verify_task18.py
```

> `scripts/test_demo_app.py` 会临时启动本地只读服务并临时重建 Manifest（退出时恢复），
> 已在第 4.3 节说明；如需严格"零副作用"，可跳过它并直接以本次"公开版实测 26/26 通过"为准（任务 12.1 的静态测试产物为内部留档）。

---

## 6.1 Evidence Pack 与时间 Ground Truth 评分（任务 17，不需要模型）

独立、确定性、CPU-only 的评测基础设施（项目级工具，与 Tier-3 v2 评分器同层；**不新增第四个 Skill**）：

- **输入三分離**：manifest（输入清单：媒体路径 + SHA-256 + 时长 + split + 来源 provenance，**不含时间真值**）、Ground Truth（显式独立输入，逐样本文件）、predictions（Task 16 的 `temporal-evidence.json` 冻结产物，经 prediction-set 引用）。评分器**禁止**从 README/历史 artifacts/目录猜测真值，`--ground-truth` 是必显参数；
- **dev/holdout 隔离**：holdout GT 只由持票方显式传入；其内容不进入任何输出（score.json 只记 `gt_sha256`/`gt_segment_count`/`gt_states_digest`）；
- **硬门**：sample ID / 媒体 SHA-256（实际计算）/ target query / 时长 / GT 时间线合法性 / 时间戳范围 / provenance 自洽（调用数=新鲜调用=时间线条目、预算未超、五类计数复算一致）任一失败即停止计分并输出结构化错误；
- **语义评分**：七类采样点计数（uncertain 上的过度断言 `overclaim_on_uncertain` 与适当拒答 `appropriate_abstention` 分开；0 分母写 `not_applicable`）、confirmed event 覆盖、transition 一对一匹配（方向兼容：decisive→decisive 不得匹配涉及 uncertain 的 GT 边界）、边界误差（容差来自 GT `boundary_tolerance_ms`）；
- **效率不抵消语义错误**：调用数/复用/耗时与三个派生指标分开报告；
- **公平比较**：10 条件 fairness gate（相同样本/媒体/查询/GT 版本/模型后端/预算、无单侧重试或额外上下文【调用方声明】、输入完整、同 evidence_nature、GT 无运行后修订）；verdict ∈ {IMPROVEMENT, TRADEOFF, NO_IMPROVEMENT, INVALID_COMPARISON}，由指标计算不预设；
- **Task 16 复算结论**：旧 `IMPROVEMENT` 是旧口径历史；严格 scorer 对同一冻结产物复算 **TRADEOFF**（细节见 `artifacts/task-17/comparison.md` 与 `docs/plans/2026-09-22-evidence-pack-ground-truth-scoring-design.md`）；
- **8 AI + 4 真实视频接入**：用户上传素材后，按 `schemas/evidence-pack-manifest.schema.json` 的 competition profile 规则构造 manifest（真实路径/哈希/许可/provenance）并提供逐样本 GT，即可零改代码运行同一评分器（内部留档版另有一份占位值明确标注的契约示例，不随公开仓库分发）；上传前**不得声称真实域评分已完成**。

---

## 7. Tier-3 对照评测复现（重资源，按需执行）

**警告：完整运行需要 18 个全新 DSH headless 会话（9 任务 × 2 侧），单侧 30–60 分钟量级，且需要资源窗口。**
本任务的文档修复**没有**重跑评测；历史结果来自真实运行并已冻结。

```bash
# 公开版注：任务 08 冻结原始输出为内部留档，v1/v2 对 task-08 的重评分无法在公开仓库原样重跑；
# 其结论已收录于 artifacts/task-09/（comparison-v2.json / evaluator-diff.json / verdict-v2.json）。
# 测试媒体需复现者自备，默认指向 <内部测试媒体目录> 占位（公开版 allowlist 改为仓库内合成 fixture）。
# 历史运行（产物已提交，勿覆盖）
python3 scripts/run_tier3_eval.py --out artifacts/task-07     # 初始运行（Verdict PARTIAL）
python3 scripts/run_tier3_eval.py --out artifacts/task-08     # E9 修复后完整重跑

# 交付前验证（15 项）
python3 artifacts/task-09/verify_task09.py
```

**baseline 定义（与实现一致）**：baseline 不使用项目 Skill，把**同一任务文本**交给**同一个 DSH Agent**，
在项目外隔离目录中执行（该目录无 `.git` 祖先，因此 `<projectRoot>/.dsh/skills/` 不会被 DSH 发现；
目录每次运行前重建）。baseline 可自建脚本、程序化分析或直接调用本地 Ollama。
两侧唯一变量是是否加载项目 Skill：任务文本逐字节相同，`max_frames`/超时/模型/媒体相同，按任务交替执行，
每任务独立全新会话，运行前统一预热一次。

**评测集构成**（`evals/tier3/evals.json` v1.0.0，冻结）：E1 单视频正向 / E2 单视频负向 / E3 多视频正向 /
E4 多视频负向 / E5 证据不足 / E6 非视觉 / E7 敏感属性 / E8 非法媒体路径 / E9 缺失媒体；媒体为本机两段真实
短视频，视觉任务统一 `max_frames=2`；负向/边界用例（E2/E4/E5/E6/E7/E8/E9 共 7 个）**不得为了提高分数而删除**。
评测集**不使用仓储实拍素材，也没有逐样本 ground-truth 标注**——判定口径为确定性规则评分
（允许措辞/禁止措辞 + 结构化产物完整性 + 安全边界），位置/时间准确率指标未实现。

**最终结果（v2 对任务 08 冻结数据重评分）**：Security 9/9→9/9、Correctness 7/9→9/9、
Discoverability 5/9→9/9、Effectiveness 6/9→9/9；总耗时 3534.4s→800.5s、工具调用 292→157、
Qwen 调用 1→17（**baseline 计数是可观测下限**，其自建脚本的内部调用无法存档）；Verdict: PASS。
样本为每侧 9 个任务、单次运行，**不构成统计显著性，不得外推**。

---

## 8. 资源与统一内存注意事项

- DGX Spark 为统一内存架构，大模型占用是核心矛盾。视觉模型按需加载、用后卸载；
- 加载 Qwen 前必须确认 `MemAvailable ≥ 40 GiB`（脚本内置守卫），不足时如实降级 failed，**不得强行加载**；
- **用户的 MiniMax-H3 视频生成服务与本地 Qwen 不宜同时高负载常驻**：任务 04 曾因 H3 占用导致
  MemAvailable 降至 22.3 GiB / 3.31 GiB，真实视觉调用被资源守卫阻塞（历史记录为内部留档；资源守卫逻辑可由本仓库脚本复现：`trace_video.py` 的 `resource_guard()`）；
- 任何任务不得为了本项目启动新的大模型、下载模型、停止或重启机器上既有服务；
- 涉及内存的操作先评估对现有服务的影响，未经确认不得执行。

---

## 9. 网络不可用时的限制

- 本机到 github.com / NGC 等外部网络可能不可达：**无法推送 GitHub、无法拉取官方镜像或模型、无法下载依赖**；
  仓库当前未配置 remote，推送与发布由用户在网络可达的环境执行；
- StepFun 是云端 API：网络不可用时文本规划链路不可用，但**本地 Qwen 视觉链路与静态工作台不受影响**
  （工作台完全离线、CPU-only）；
- 未安装任何第三方依赖；如环境缺少 cv2，由 `skill_env.py` 切换到机器上已有的含 cv2 的解释器，
  **不要为此安装新包**。

---

## 10. 常见失败与排查入口

| 现象 | 可能原因 | 排查入口 |
| --- | --- | --- |
| DSH 会话中 Skill 不可见（catalog 为空） | `SKILL.md` 缺 YAML frontmatter 或 `name` 非 kebab-case；DSH 只记警告不报错 | `docs/SMOKE_TEST_REPORT.md` §2 |
| 视觉任务返回 `needs_input`/`missing_source_media` | 用户未在当前请求中显式提供媒体路径（**设计行为，非缺陷**） | `.dsh/skills/task-to-skill-compiler/SKILL.md` 第 0 步硬门 |
| 视觉任务返回 `rejected`/`invalid_source_media` | 显式提供的路径未通过安全校验（shell 元字符、凭据样式、未授权根、路径穿越） | `scripts/validate_task_spec.py` 的 `check_media_path()` |
| 全部帧 failed 且提示资源阻塞 | `MemAvailable < 40 GiB` | `/proc/meminfo`；资源守卫逻辑见 `trace_video.py` `resource_guard()` |
| 时间线出现 `abstained` | 模型无法确认（`object_found=false` + `abstention_reason`）或 confidence 低于阈值 | `references/video-evidence.md` 聚合规则 |
| bbox 为 null | 模型未返回可靠框，或像素坐标未通过归一化条件（混合/越界/顺序错误/尺寸未知）——**不伪造框** | `references/multi-video-evidence.md` 坐标规范 |
| 工作台页面空白 / Manifest 加载失败 | 未启动服务或 Manifest 未生成 | 重新执行 `python3 scripts/build_demo_manifest.py` 与 `python3 scripts/serve_demo.py` |
| 工作台 403 / 404 | 目录穿越被拒或媒体不在 allowlist | `scripts/serve_demo.py` 的 `DENIED_PATTERNS` / `MEDIA_ALLOWLIST` |
| 演示时想"现场跑一次完整会话" | 单次自主会话 5–37 分钟，3 分钟内不可行 | 用工作台回放 + 已存档 reasoning 流；`docs/COMPETITION_READINESS_AUDIT.md` §9 |

---

## 11. 已知限制（复现前必读）

- 样本量小：Tier-3 每侧 9 个任务、单次运行，无统计显著性；
- 真实运行使用的媒体是本机既有的两段真实短视频；**首个演示场景（仓储/园区）是场景设定，
  尚未用仓储实拍素材验证**；
- 跨摄像头身份/实例关联**明确不做**（需要可靠关联证据）；
- 当前 DSH 配置下 StepFun 不读图，视觉 100% 走本地 Qwen；
- 工作台是 recorded-artifact viewer，不是实时模型调用界面；
- 授权媒体根目录默认包含机器特定路径，换环境时用 `SPARKSKILL_AUTHORIZED_MEDIA_ROOTS` 显式扩展。
