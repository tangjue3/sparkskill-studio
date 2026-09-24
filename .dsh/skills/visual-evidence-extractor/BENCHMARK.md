# BENCHMARK — visual-evidence-extractor

> 图片部分数字来自 2026-09-21 真实运行（DGX Spark 本地 Ollama + Qwen3.8-27B-GGUF，vision）。
> 视频抽帧/聚合规则数字来自 2026-09-21 任务 04 真实运行与规则测试（任务 03 真实证据回放）。
> **真实 Qwen 视频逐帧调用**：任务 04 因 MiniMax-H3 占用统一内存被资源守卫阻塞；**任务 05 在用户关停 MiniMax-H3 后的资源窗口内，由 DSH 自主 Agent 会话真实跑通**（见下节）。
> 样本量小，只记录测试次数与通过次数，不写百分比。

## 运行环境

- 后端：Ollama（127.0.0.1:11434）
- 模型：`modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`（qwen35，27.3B，Q4_K_M，capabilities 含 vision）
- 图片测试占用：加载后 34.6 GB（任务 03 实测）
- 测试图片：`<内部测试媒体目录>/test_first.png`（PNG 1024×576）
- 视频抽帧：OpenCV 5.0.0（复用本机 vLLM 环境 `<含cv2的解释器环境路径>` 中已有的 cv2，**未安装任何依赖**；系统 python3 无 cv2 时由 `scripts/skill_env.py` 自动切换解释器）
- 测试视频（均为用户 MiniMax-H3 服务的真实产出，未修改原文件）：
  - `h3-smoke.mp4`：H.264/avc1，24 fps，107 帧，960×576，4458.333 ms
  - `h3-t2va-8s.mp4`：H.264/avc1，24 fps，192 帧，960×576，8000.0 ms

## 图片测试结果（2026-09-21，任务 03）

| # | 测试 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 图片正向：主要目标存在性 | **通过** | object_found=true，confidence=1.0，证据充分 |
| 2 | 图片负向：红色背包（图中实际不存在） | **通过（正确负面结论）** | object_found=false，bounding_box=null（未伪造），confidence=1.0 |
| 3 | 契约守卫：requires_visual_input=false | **通过（正确拒绝）** | exit=1，不调用模型 |
| 4 | 错误处理：图片路径不存在 | **通过** | exit=3，明确非敏感错误 |

小计：4 项测试，4 项通过。

## 视频测试结果（2026-09-21，任务 04）

测试套件：`scripts/test_video_pipeline.py`；完整结果：`artifacts/task-04/test-results.json`。
小计：**16 项测试，16 项通过**（逐项输入性质见 results JSON，关键标注如下）。

### A. 真实视频抽取（真实运行）

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| A1 | 视频元数据读取 | 真实视频 h3-smoke.mp4 | **通过**：fps=24.0、107 帧、960×576、4458.333 ms |
| A2 | 帧抽取 | 真实视频 | **通过**：计划 6 帧全部抽出，文件存在，稳定命名 |
| A3 | 时间戳单调递增 | 真实视频 | **通过**：[0.0, 791.667, 1583.333, 2416.667, 3208.333, 4000.0] |
| A4 | 帧路径可追溯 | 真实视频 | **通过**：每个帧索引指向真实 PNG 文件 |
| A5 | 帧索引 JSON 可解析 | 真实视频 | **通过** |

### B. 聚合规则（任务 03 真实证据回放 + 构造输入）

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| B1 | 目标存在样例 | **任务 03 真实 Qwen 证据**（positive-evidence.json）回放到真实帧时间戳 | **通过**：confirmed=3，first=0.0 ms，last=1583.333 ms，status=completed |
| B2 | 目标不存在样例 | **任务 03 真实 Qwen 负向证据**（红色背包确定性负面）回放 | **通过**：not_found=2、confirmed=0，结论为负面表述，无虚假路径/时间线 |
| B3 | 证据不足样例 | 构造输入（明确标注非模型输出） | **通过**：abstained=2，status=abstained，拒答原因保留 |
| B4 | bounding_box 不伪造 | 任务 03 真实证据（positive 整幅框 / negative null） | **通过**：null 保持 null；整幅框被标记"定位不可靠" |
| B5 | 去重与状态变化 | 任务 03 真实证据回放 | **通过**：3 帧相同证据 → state_changes=1；found→not_found→found → state_changes=3 |
| B6 | 视频报告状态一致性 | 任务 03 真实证据回放 + 注入不一致 | **通过**：report.status 与 timeline.summary 一致；注入冲突后复算正确且 warnings 记录冲突 |
| B7 | 资源守卫 | 本机 /proc/meminfo 真实读数 | **通过**：MemAvailable=22.3 GiB 时 blocked=True（未调用任何模型） |

### C. 失败输入错误处理

| # | 测试 | 结果 |
| --- | --- | --- |
| C1 | 视频不存在 | **通过**：exit=3 |
| C2 | 损坏的视频文件 | **通过**：exit=3 |
| C3 | 非法规格（requires_visual_input=false） | **通过**：exit=2 |
| C4 | 损坏的证据 JSON | **通过**：exit=2 |

## 真实 Qwen 视频逐帧调用：被资源条件阻塞（任务 04，如实记录）

- 运行期间观察：MiniMax-H3（:8000）由用户重启后正在执行视频生成任务（vllm-h3-next.log 显示 t2va 49 步推理进行中）；
- `/proc/meminfo` MemAvailable 在测试期间从 38 GiB 一路降至 22.3 GiB、3.31 GiB；
- Qwen3.8-27B 加载约需 34.6 GB → 强行加载有 OOM 风险并会破坏用户服务；
- 处置：未停止 MiniMax-H3、未强行加载 Qwen；`trace_video.py` 资源守卫（默认阈值 40 GiB）阻止模型加载，全部帧标记 failed 并记录真实原因，整体状态 failed；
- 产物：`artifacts/task-04/timeline.json`、`video-report.json`、`extraction-only-report.json`；
- **未使用任何伪造模型输出**；聚合规则正确性由任务 03 真实证据回放验证。

## 真实 Qwen 视频逐帧调用：任务 05 资源窗口内由 DSH 自主 Agent 真实跑通（2026-09-21）

前置：用户于 ≈06:18 手动关停 MiniMax-H3（:8000 无监听、无 vllm/DiffusionWorker 进程）；核验 MemAvailable = 115.55 GiB（≥ 40 GiB 门槛）；Qwen 预热加载后 MemAvailable = 79.80 GiB。以下由两次全新 `dsh --profile headless` 会话内的 Agent 自主执行（证据见 `artifacts/task-05/agent-session-summary.md`）。

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| D1 | 目标判定（开放式探针） | **真实 Qwen 调用**，对真实帧 f00058 开放式提问 | **通过**：Qwen 如实描述"日落时分的山湖景观"，据此选定可可靠确认目标"太阳"（未预设红色背包） |
| D2 | 视频抽帧 | 真实视频 h3-smoke.mp4，interval 800ms/max 6 | **通过**：6 帧，时间戳 [0, 791.667, 1583.333, 2416.667, 3208.333, 4000.0] ms 严格递增；抽帧窗口 ≈0.13 s |
| D3 | 逐帧视觉证据（正向·太阳） | **真实 Qwen 视频逐帧调用**（`raw-frames/` 6 份原始返回存档） | **通过**：confirmed=5、failed=1、overall=completed；首次确认 0.0 ms、最后确认 4000.0 ms；5 帧归一化局部框 x≈0.43–0.57,y≈0.22–0.40 |
| D4 | 逐帧视觉证据（负向·紫色大象） | **真实 Qwen 视频逐帧调用**（`negative-raw-frames/` 6 份原始返回存档） | **通过（正确负面）**：not_found=6、confirmed=0、overall=completed（负面结论）；所有 bounding_box=null，无伪造 |
| D5 | bounding_box 不伪造（真实模型抖动） | 真实 Qwen 返回 | **通过**：1 帧 Qwen 返回像素坐标 `[431,222,545,356]`（越界），被 `coerce_evidence` 拒绝并标 failed，**未修补/未伪造/未重跑凑数** |
| D6 | 资源守卫 | 本机 `/proc/meminfo` 真实读数 | **通过**：正向 trace 时 79.95 GiB、负向 78.06 GiB，均 ≥ 40 GiB，blocked=false；未用 `--allow-low-memory` |
| D7 | 时间线可回溯 | 真实帧文件 | **通过**：timeline 每条 frame_path 均指向真实 PNG；timeline 帧集 == keyframes 目录（交叉核验一致） |

小计：任务 05 真实视频视觉 7 项，7 项通过，0 项失败。**"真实 Qwen 视频逐帧调用"自任务 04 阻塞后首次验证通过。**

### 逐帧 Qwen 耗时（真实测量，取自 `raw-frames/` 文件 mtime 差）

| 会话 | 每帧耗时 | 6 帧合计 |
| --- | --- | --- |
| 正向（详细描述 + 定位框） | 11.1–12.6 s | ≈72.3 s |
| 负向（简短 not_found） | 8.3–9.1 s | ≈42.9 s |

Qwen 预热（含首次加载 ~35.75 GiB）：11.9 s；内存 115.55 → 79.80 GiB。

## 已知失败并修复（保留证据，任务 03）

- 首轮负向图片测试失败：模型 object_found=false 但 abstention_reason=null 被拒；根因是提示词未区分"确定性负面"与"拒答"；已修复并复跑通过。

## 耗时（真实测量）

| 调用 | 耗时 |
| --- | --- |
| 图片正向测试（含首次模型加载） | 23.6 s |
| 图片正向测试（模型热） | 9.2 s |
| 图片负向测试（模型热） | 7.7 s |
| h3-smoke.mp4 抽帧（顺序解码 107 帧，interval 1000ms/max 8） | 0.25 s |
| h3-t2va-8s.mp4 抽帧（顺序解码 192 帧，interval 1000ms/max 8） | 0.37 s |
| trace_video.py 全流程（含抽帧，资源守卫降级，无模型调用） | 0.27 s |
| test_video_pipeline.py 全套 16 项（无模型调用） | 0.77 s |
| generate_report.py 视频模式（evidence-report-generator） | 0.01 s |

## 结论

- 视频读取、抽帧、时间戳、可追溯性：真实视频上全部通过（A1–A5）。
- 聚合与报告规则：16/16 通过；"未发现"与"无法确认"严格区分；无伪造 bounding_box；无虚假时间线。
- **真实视频视觉结论：已在任务 05 资源窗口内由 DSH 自主 Agent 真实验证**（正向 confirmed=5/failed=1、负向 not_found=6；见上节 D1–D7，7/7 通过）。任务 04 的 failed 降级为历史资源阻塞记录，不再是当前状态。

## 多段视频统一证据时间线：任务 06（2026-09-21，DSH 自主 Agent 真实运行）

前置：用户关停 MiniMax-H3 后的资源窗口（任务开始时 MemAvailable 71 GiB；会话期 ≈72–76 GiB，均 ≥ 40 GiB 阈值）。以下由两次全新 `dsh --profile headless` 会话内的 Agent 自主执行（证据见 `artifacts/task-06/agent-session-summary.md`）。测试视频为两段真实视频（`h3-smoke.mp4` 与 `h3-t2va-8s.mp4`，均含日落山湖景观；开放式探针据实选定共同非敏感目标"太阳"）。

### 规则测试（`scripts/test_multi_video_pipeline.py`，无模型调用）

小计：**32 项测试，32 项通过**（完整结果 `artifacts/task-06/test-results.json`；输入性质逐条标注：真实抽取帧 + 任务 03 真实证据回放 + 构造输入）。

| 分组 | 项数 | 覆盖 |
| --- | --- | --- |
| A 规格/校验器 | 7 | 旧单媒体规格向后兼容 VALID；多视频规格 VALID；重复 source_id / 负 time_offset_ms / 未授权路径 / shell 元字符路径 / 旧版路径穿越均被拒绝 |
| B 像素坐标归一化 | 10 | 合法像素坐标归一化（含真实 PNG 帧尺寸读取）；混合/越界/顺序错误/尺寸未知/负坐标不归一化；已归一化坐标原样通过；coerce_evidence 端到端归一化与置 null+warning |
| C 多视频聚合 | 9 | global=local+time_offset_ms 且排序正确；每来源时间戳递增；failed/not_found 帧全部保留；global_summary 首末确认；重复 source_id / 负偏移 / 旧版字符串包装 / 执行期路径守卫（拒绝未授权 + 放行授权根） |
| D 多视频报告 | 6 | 正向 completed + 允许措辞 + 无禁止措辞；负向 completed 负面结论；abstained；failed 无存在性断言；交叉校验复算；全局条目可回溯 |

任务 04 回归（`scripts/test_video_pipeline.py`）：**16/16 通过**（无破坏）。

### 真实多视频运行（DSH 自主会话，真实 Qwen 调用）

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| M1 | 目标选择（开放式探针） | **真实 Qwen 调用**，两视频各 1 帧 | **通过**：两帧"太阳"显著度均为高，据此选定共同非敏感目标（未伪造共同目标） |
| M2 | 多媒体 VisualTaskSpec 生成 + 校验 | 会话内 Agent 自主生成 | **通过**：`multi-video-task-spec.json` RESULT: VALID（source_media 两来源，video-b 偏移 5000 ms） |
| M3 | 多视频逐帧视觉证据（正向·太阳） | **真实 Qwen 视频逐帧调用**（`raw-frames/` 8 份原始返回存档） | **通过**：2 来源 × 4 帧 = 8/8 confirmed，置信度 0.95–0.98；每来源 first/last 确认帧数与全局首末确认均正确 |
| M4 | 像素坐标受控归一化（真实模型抖动） | 真实 Qwen 返回 | **通过**：3/8 帧返回像素坐标，全部按契约归一化并记录 raw/format/applied/帧尺寸（如 raw=[432,222,545,356] @ 960×576 → [0.45, 0.385417, 0.567708, 0.618056]）；无修补、无重跑凑数 |
| M5 | 多视频视觉证据（负向·紫色大象） | **真实 Qwen 视频逐帧调用**（`negative-raw-frames/` 8 份存档） | **通过（正确负面）**：8/8 not_found，bounding_box 全 null，无虚假目标/路径/跨视频关系 |
| M6 | 全局时间线聚合 | 真实帧 + 规则计算 | **通过**：8 条目按 global_timestamp_ms 排序（0.0 → 12958.333 ms），global=local+offset 数学正确，每条可回溯到来源与关键帧 |
| M7 | 跨视频语义边界 | 真实报告产物 | **通过**：结论仅用 matched target query / visually consistent with target description / confirmed in source A/B；禁用措辞 0 命中；semantic_limitations 随报告输出 |
| M8 | 资源守卫 | 本机 `/proc/meminfo` 真实读数 | **通过**：会话期 MemAvailable ≈72–76 GiB ≥ 40 GiB，blocked=false；未用 `--allow-low-memory` |
| M9 | 每来源时间线时间戳递增 | 真实帧 | **通过**：video-a [0.0, 1500.0, 2958.333, 4416.667]；video-b [0.0, 2666.667, 5333.333, 7958.333] |

小计：任务 06 真实多视频运行 9 项，9 项通过，0 项失败。

### 真实运行中的两个代码缺陷及会话内 Agent 自主修复（如实记录）

1. `trace_multi_video.py` 校验器路径 off-by-one（阻断性）：`COMPILER_SCRIPTS` 多上一级导致执行期路径守卫加载失败、多视频抽取执行前即被拒绝。由会话内 Agent 自行诊断修复（`EXTRACTOR_DIR/..` → `.dsh/skills/task-to-skill-compiler/scripts`）。
2. `generate_report.py` 多视频交叉校验误报（非阻断）：`overall_status` 与不含该键的 stats 比较导致状态一致也误报。由会话内 Agent 修复为与复算 status 比较。

修复后规则测试通过；执行 Agent 在交付前复核并补充回归用例（C8 断言拒绝原因来自路径规则本身、C9 断言授权路径放行）。

### 耗时（真实测量）

| 调用 | 耗时 |
| --- | --- |
| 多视频规则测试全套 32 项（无模型调用） | ≈1.5 s |
| 正向 DSH 自主会话（发现/加载 Skill + 双探针 + 规格 + 校验 + 8 帧 Qwen + 报告 + 2 次 bug 修复与重跑） | ≈2202 s（08:09:54→08:46:35） |
| 负向 DSH 自主会话（发现/加载 Skill + 规格 + 校验 + 8 帧 Qwen + 报告） | ≈302 s（08:50:07→08:55:09） |
| Qwen 逐帧（会话内观测，取自 raw-frames mtime 差） | ≈11–13 s/帧 |

## Tier-3 对照评测中的视觉抽取表现（任务 07，2026-09-21）

with-skill 侧在 5 个视觉任务（E1/E2/E3/E4/E5）中全部正确使用本 Skill：发现并加载 Skill 5/5、
真实 Qwen 调用（E1=2、E2=2、E3=4、E4=4、E5=2 帧）、结论全部正确（E1/E3 正向 confirmed、
E2/E4 负面、E5 拒答）；baseline 侧 5/5 未发现本地视觉后端（改用程序化分析，E1 得出错误负面结论）。
完整对照见根目录 `BENCHMARK.md` 与 `artifacts/task-07/comparison.md`。

已知缺口（任务 07 E9，未隐藏）：用户未提供媒体路径时，Agent 可能从项目上下文推断路径并执行抽取，
而非返回缺参错误——后续在 task-to-skill-compiler 负向触发中显式覆盖。

## Tier-3 评测器版本化影响（任务 09）

v2 评分器仅修复断言语境误报，未改动任何视觉抽取规则；with-skill 侧 E1–E5 视觉任务判定不变（均通过）。完整历史见根目录 `BENCHMARK.md`。

## 目标时序证据与粗到细自适应采样：任务 16（2026-09-22）

新增能力（不新增第四个 Skill；uniform baseline 行为零变化）：

- `scripts/adaptive_sampler.py`：纯逻辑（无 cv2/无网络/无模型调用）——策略配置解析（与校验器同口径）、初始覆盖规划、细化候选区间（二分）、硬预算账本（按来源命名空间隔离的时间戳缓存）、时序证据推导、provenance 结构；
- `scripts/trace_temporal.py`：执行器——uniform（复用 `extract_frames.plan_sample_times` + `trace_video.analyze_frame` + `trace_video.aggregate`，分类规则逐字节一致）/ adaptive_coarse_to_fine（初始覆盖 + 触发器细化），输出 `temporal-evidence.json`（timeline + summary + sampling_provenance + temporal_evidence）；多来源时每来源独立执行并复用 `trace_multi_video` 合并规则（共享同一预算账本）；
- `references/temporal-evidence.md`：策略契约 / provenance / 时序证据 / 语义红线；
- technical fixture：`scripts/generate_task16_fixtures.py` 生成 5 段合成视频（present-throughout / appear-midway / disappear-midway / reappear / abstain-zone，640×360@24fps、8s、红色正方形；确定性渲染），第一次评测前冻结 manifest + ground truth + SHA-256（`artifacts/task-16/fixtures/`），评测前 `--verify` 复核。

### 规则测试（`scripts/test_temporal_evidence.py`，无真实模型调用）

小计：**27 项测试，27 项通过**（完整结果 `artifacts/task-16/test-results.json`；输入性质逐条标注：构造证据回放 / 规则测试 / 真实 fixture 视频抽取）。

| 组 | 项 | 覆盖 |
| --- | --- | --- |
| T1–T6 | Schema/校验器 | 旧规格兼容；uniform/adaptive 合法；未知策略、非法预算（0/-3/12.5/"12"）、负/零精度、uniform+细化参数、adaptive 缺必填均拒绝 |
| T7–T16 | 采样与预算 | 实际调用 ≤ 预算（adaptive 8/8、uniform 5/5）；重复时间戳不重复调用（收敛到帧间隔→skipped_duplicate）；时间戳严格递增；初始/细化可区分；状态变化左右边界（GT 3200ms 落在区间内）；边界宽度=right-left 且 ≤ 目标；预算耗尽停止（reappear 预算 5）；abstained 不退化为 not_found；单帧 failed 不退化为 not_found；无状态变化零细化（4 调用=初始覆盖） |
| T17 | 规则一致 | extractor/sampler/reporter 三处 frame_class 对 5 类矩阵完全一致；uniform 规划公式与 extract_frames 一致 |
| T18–T19 | 报告 | 独立复算（与手工复算一致）；注入上游错误→warning+复算赢；超预算计数→warning |
| T20–T21 | 多来源 | source_id/原时间戳/global=local+offset/排序保持；无跨视频身份断言（禁用措辞 0 命中，允许措辞齐全） |
| T22 | 资源守卫 | 阈值 1e9 GiB → blocked，实际调用=0，全部帧 failed，不计入预算 |
| T23 | 安全 | provenance 与整文档凭据扫描 0 命中 |
| T24 | fixture 区分 | 构造证据 evidence_nature=constructed_fixture_evidence，报告透传 input_nature=technical_fixture |

### uniform vs adaptive 真实对照（technical fixture + 真实 Qwen 调用）

公平性：相同 fixture/目标查询/模型/资源窗口/状态规则/最大调用预算（12）/超时；不单侧重试、不删样本、不看结果改 ground truth。逐场景真实结果与 Verdict 见 `artifacts/task-16/comparison.json` 与 `comparison.md`（本 BENCHMARK 只记录结论口径：**技术 fixture 小样本结果不得外推为真实仓储准确率；不预设 adaptive 必须 PASS**）。

### 任务 17 复评口径（2026-09-22，零模型调用）

`temporal-evidence.json` 是项目级 Ground Truth 评分器（`scripts/score_temporal_ground_truth.py`）的标准输入；评分器只读本产物、不修改、不调用任何模型。对任务 16 冻结产物（5 场景 × 2 臂，fairness gate 10/10）的复评结论：**pack 级 verdict=TRADEOFF**（`artifacts/task-17/comparison.json`）——adaptive 34 vs uniform 60 次调用、平均边界误差 138.333 vs 150.0 ms（严格更好），但 `unreached_uncertain_segments` 1 > 0（abstain-zone 初始覆盖盲区）且 uniform 臂在 uncertain 区间 3/3 `overclaim_on_uncertain`（真实 Qwen 确定性负面 vs GT 不确定）。任务 16 旧 `IMPROVEMENT` 为旧口径历史（未篡改）。评分器规则测试 38/38（`artifacts/task-17/test-results.json`）。**`completed` 不等于语义正确；合成 fixture 不外推；8 AI + 4 真实视频上传前不得声称真实域评分已完成。**

## Coverage-Aware 自适应采样：任务 18（2026-09-22；replay + 真实 Qwen 双模式完成）

新增第三种采样策略 `coverage_aware_adaptive`（不新增第四个 Skill；uniform 与 adaptive_coarse_to_fine 行为零变化，回归证明）：

- **契约**（`schemas/visual-task-spec.schema.json` + `validate_task_spec.py`，编译期/执行期同口径）：strategy 枚举第三值；必填 `max_model_calls`/`initial_coverage_samples`/`coverage_gap_target_ms`（>0）/`coverage_call_reserve`（正整数）/`target_boundary_precision_ms`/`max_refinement_rounds`；`initial_coverage_samples + coverage_call_reserve ≤ max_model_calls`（覆盖配置不得超出硬预算）；coverage 专属字段对 uniform/adaptive 均拒绝；
- **行为**（`adaptive_sampler.py` 纯逻辑 + `trace_temporal.py` 阶段 2）：初始覆盖 → 覆盖探索（largest-gap-first 二分压缩未观测间隔，与证据语义无关；并列取最早；重复时间戳排除）→ 边界细化（任务 16 同款触发器逻辑，用剩余预算）；停止原因 `coverage_gap_target_reached`/`coverage_reserve_exhausted`/`coverage_no_refinable_gap`/`budget_exhausted`；
- **provenance**：区分 `initial_coverage_calls`/`coverage_exploration_calls`/`boundary_refinement_calls`；`max_adjacent_sampling_gap_ms_initial/final`（可由 (analyzed_timestamps, duration_ms) 复算）；`underobserved_intervals` 剩余盲区；`arbitrary_short_event_detection_guaranteed: false` 与 `events_shorter_than_max_sampling_gap_may_be_missed: true` 显式限制声明；
- **technical fixture**：`scripts/generate_task18_fixtures.py` 新增 6 段（short-event-between-grid / short-uncertain-between-grid / twin-short-events / absent-throughout / short-event-phase-b / short-uncertain-phase-b；与任务 16 同一组冻结生成参数），第一次评测前冻结 manifest + ground truth + SHA-256；4 段复用任务 16 冻结 fixture（相对路径 + 哈希核验）；
- **规则测试**：`scripts/test_task18_coverage_sampling.py`（C01–C35 + C34b）**36/36 通过**（`artifacts/task-18/test-results.json`；构造证据回放，除 C30 复用 replay 产物外零模型调用）；
- **三臂评测 — deterministic replay**（`scripts/run_task18_comparison.py --mode replay` + `scripts/task18_scorer_adapter.py`，任务 17 冻结评分器经内存扩展白名单的适配层）：11 场景 × 3 臂（uniform / adaptive / coverage，同预算 12；tight-budget 场景三臂 6）；公平门 10/10 × 3 对；**pairwise verdict：coverage-vs-adaptive = IMPROVEMENT**（平均边界误差更小、容差内边界更多）；coverage-vs-uniform = TRADEOFF；adaptive-vs-uniform = TRADEOFF；**pack 级 = TRADEOFF**（`artifacts/task-18/deterministic/`，顶层 `three-arm-comparison.json` 为 replay 口径）。关键实证：coverage 发现 coarse 网格间的短事件/短 uncertain 区（adaptive 漏检/未触达——任务 17 盲区修复），但 twin-short-events（两个 600ms 事件 < 1333.334ms 最终间隔）coverage 与 adaptive 均漏检 2/2——**任意短事件不保证发现的诚实实证**；
- **三臂评测 — 真实 Qwen**（`--mode real`；用户授权优雅停止 MiniMax-H3 服务族后十项资源门槛通过，`artifacts/task-18/h3-shutdown-record.json`；两轮阻塞历史保留于 `resource-gate-rerun.json`）：**287 次真实调用**（uniform 120 + adaptive 54 + coverage 95，与 replay 计划逐臂一致），零失败/零超时/零无效输出，每次原始返回存档（`real-qwen/<场景>/<臂>/raw/`）；公平门 10/10 × 3 对；**pairwise 三对全 TRADEOFF、pack = TRADEOFF**（`real-qwen/`）。与 replay 的关键差异：**coverage-vs-adaptive 的 IMPROVEMENT 在真实模型下变为 TRADEOFF**——真实 Qwen 触达 uncertain 区域后过度断言而非拒答（`overclaim_on_uncertain`：coverage 4 / uniform 2 / adaptive 0；`appropriate_abstention` 三臂均 0；重现任务 16 确定性负面 overclaim 模式）；真实运行同时证实 coverage 采到短事件后 Qwen 能正确识别（两个短事件场景 confirmed=2 vs adaptive=0）。**差异源于视觉模型语义而非采样策略（两种模式调用计划完全一致）；replay 与 real 分别评分、不混合平均**；
- **DSH headless 自主会话（成功）**：`dsh --profile headless` 全新会话自主发现并加载三个 Skill、生成并通过 coverage_aware_adaptive 规格校验、本地 Qwen Vision 真实调用 11/12、发现短事件（边界 mean 33.333ms）；会话后冻结评分器离线评分 11/11（`artifacts/task-18/dsh-session/`）。

小计：任务 18 规则测试 36 项，36 项通过，0 项失败；真实 Qwen 三臂评测 287 次调用零失败（verdict：pairwise 三对 TRADEOFF、pack TRADEOFF）；DSH 自主会话 11/12 次调用、离线评分 11/11。技术 fixture 小样本 + 单次运行，不得外推；`completed` 不等于语义正确；8 AI + 4 真实视频上传前不得声称真实域评分已完成。

## dev Evidence Pack 三策略真实基线：任务 19B（2026-09-22/23；真实 Qwen，未校准基线）

第一次把冻结三策略应用到用户真实交付的 dev Evidence Pack（6 段 MiniMax-H3 生成受控测试视频 + 3 段 Pexels licensed-public 真实行业视频；仓库外只读数据包，白名单九样本）。**先测量、不校准**：视觉 Prompt/采样算法/证据分类/报告规则/scorer/adapter 零改动。

- **协议**（阶段 A 提交 `e3ef01e` 先于任何 dev 模型调用）：预算政策 `clamp(ceil(duration/1000),12,24)`（只依赖媒体时长）；样本内臂顺序循环左移轮换（热状态控制）；统一 warm-up（任务 16 fixture 一帧，不计入任何 arm）；无单侧重试；execution manifest 标签隔离（54 份深扫描通过）。
- **Ground Truth**：transfer-safe 卡为唯一标签来源；确定性结构规范化（AI06/WEB02 相邻同状态合并、WEB01/WEB02 末段对齐实测时长），状态覆盖与边界集合不变式逐样本校验；九份 GT 过任务 17 冻结契约。
- **真实运行**：27/27（9 样本 × 3 臂）成功、0 失败；**256 次真实 Qwen 调用**（uniform 121 + adaptive 51 + coverage 84）+ warm-up 1 次；每次原始返回存档。
- **评分**（任务 17 冻结 scorer + 任务 18 适配层，零改动）：27 份硬门全过；逐样本公平门 27/27 通过；三范围 pack verdict 全部 **NO_IMPROVEMENT**。
- **核心发现（模型语义，非采样几何）**：AI06 uncertain 区双向过度断言（overclaim 11/7/9，abstention 仅 1/3/1）；AI04 遮挡区三臂全部误判 confirmed（0 状态转换）；WEB01 真实域早期误报（incorrect 5/1/2）；WEB03 真实负向误报（uniform 4 / coverage 5）；AI05 三臂全部正确；全部 8 个 GT 边界 matched=0（方向兼容规则下带不确定度的边界不可用）。
- 结论口径：小样本单次运行；licensed-public 仅三段（小样本真实域观察）；**工程 BASELINE_COMPLETE 不等于模型效果达标**；完整证据 `artifacts/task-19/`（run-summary.md / known-limitations.md / verification.json 21/21 / 新测试 22/22）。
