# BENCHMARK — task-to-skill-compiler

> 所有数字来自 2026-09-21 真实运行（DSH 0.1.5-rc.2 headless + StepFun step-5-preview + 本地校验器）。
> 任务 05 增补一段：由 **DSH headless 自主 Agent**（非外部脚本串联）在会话内生成并校验的两次 VisualTaskSpec。
> 样本量小，只记录测试次数与通过次数，不写百分比。

## 运行环境

- Harness：DSH 0.1.5-rc.2（headless profile，单任务模式）
- 模型：stepfun / step-5-preview（文本链路）
- 校验器：`scripts/validate_task_spec.py`（纯标准库）

## 测试结果（2026-09-21）

| # | 测试 | 结果 | 说明 |
| --- | --- | --- | --- |
| 1 | 正向编译：红色背包追踪任务 → VisualTaskSpec | **通过** | 产出 `artifacts/task-03/task-spec.json`，RESULT: VALID；task_type=object_trace，requires_visual_input=true，默认拒答与禁推断均生效 |
| 2 | 正向编译：主要目标存在性任务 → VisualTaskSpec | **通过** | 产出 `artifacts/task-03/positive-task-spec.json`，RESULT: VALID；task_type=object_presence |
| 3 | 非视觉负向：写诗任务 | **通过（正确拒绝）** | 返回 `{"accepted":false,"reason":"..."}`，未产出 VisualTaskSpec |
| 4 | 安全负向：含 shell 命令与凭据样式的规格 | **通过（正确拒绝）** | 校验器报"疑似 shell 命令 / 疑似凭据内容"，exit=1 |
| 5 | Schema 边界：requires_visual_input=false | **通过（正确拒绝）** | exit=1 |
| 6 | Schema 边界：task_type=face_recognition | **通过（正确拒绝）** | exit=1 |
| 7 | Schema 边界：缺少 confidence_threshold | **通过（正确拒绝）** | exit=1 |
| 8 | Schema 边界：额外字段 code | **通过（正确拒绝）** | exit=1 |

小计：8 项测试，8 项通过，0 项失败。

## 任务 05：DSH 自主 Agent 运行（2026-09-21，headless 会话内自主完成）

两次全新 `dsh --profile headless` 会话，由会话内 Agent 自主发现/加载 Skill、生成并校验 VisualTaskSpec（证据见 `artifacts/task-05/agent-session-summary.md` 与两会话 stderr reasoning 流）。

| # | 测试 | 结果 | 说明 |
| --- | --- | --- | --- |
| T5-1 | 正向：自主生成 VisualTaskSpec（目标由开放式 Qwen 探针从真实帧判定为"日落山湖景观中的太阳"） | **通过** | `artifacts/task-05/task-spec.json`，`h3-sunset-sun-trace-001`，RESULT: VALID |
| T5-2 | 负向：自主生成 VisualTaskSpec（紫色大象） | **通过** | `artifacts/task-05/negative-task-spec.json`，`h3-purple-elephant-trace-001`，RESULT: VALID |
| T5-3 | Skill 发现与选择（Agent 自行从 catalog 发现三 Skill 并加载相关者，未调用无关 Skill） | **通过** | reasoning 流记录 "load all three skills via the `skill` tool" |
| T5-4 | 会话内本地 Schema 校验 + 安全扫描 | **通过** | 两次均 RESULT: VALID，无安全问题 |

小计：任务 05 自主运行 4 项，4 项通过，0 项失败（累计 12 项测试 / 12 项通过）。

## 耗时（真实测量）

| 阶段 | 耗时 |
| --- | --- |
| DSH headless 启动 + StepFun 生成规格（首次，E2E step1） | 64.8 s |
| DSH headless 启动 + StepFun 生成规格（会话内复跑） | 约 60–70 s（headless 每次冷启动） |
| 本地 Schema 校验 + 安全扫描 | 0.019 s |
| 任务 05 正向整会话（发现/加载 Skill + 探针 + 规格 + 校验 + 抽帧 + trace + 报告） | 607 s（06:37:32→06:47:39，含 StepFun 多轮 reasoning 与 6 帧 Qwen 调用） |
| 任务 05 负向整会话（发现/加载 Skill + 规格 + 校验 + trace + 报告） | 320 s（06:50:00→06:55:20） |

## 模型/工具错误

- 测试 1–3、E2E：无错误（exit 0）。
- 已知失败并修复：无（本 Skill 自身未发生失败；视觉侧的提示词缺陷见 visual-evidence-extractor 的 BENCHMARK）。

## 结论

- Skill 触发判定：正向视觉任务正确编译，非视觉任务正确拒绝，误触发 0 次。
- VisualTaskSpec 校验：8/8 通过。
- headless 每次冷启动约 60–70 s，是链路主要时延来源（Harness 启动 + 模型首包），非 Skill 逻辑问题。

## 任务 06：DSH 自主 Agent 多视频规格生成（2026-09-21）

两次全新 `dsh --profile headless` 会话，由会话内 Agent 自主发现/加载 Skill、生成并校验**多媒体 VisualTaskSpec**（`source_media` 来源对象数组；证据见 `artifacts/task-06/agent-session-summary.md`）。

| # | 测试 | 结果 | 说明 |
| --- | --- | --- | --- |
| T6-1 | 正向：自主生成多媒体 VisualTaskSpec（目标由开放式 Qwen 探针从两段真实帧判定为"日落山湖景观中的太阳"） | **通过** | `artifacts/task-06/multi-video-task-spec.json`（`h3-multivideo-sun-presence-06`），RESULT: VALID；source_media=[video-a(scene-a, offset 0), video-b(scene-b, offset 5000)]；required_outputs 含 per_source_timeline/global_timeline/keyframes/evidence_report |
| T6-2 | 负向：自主生成多媒体 VisualTaskSpec（紫色大象） | **通过** | `artifacts/task-06/negative-task-spec.json`（`h3-multivideo-purple-elephant-neg-06`），RESULT: VALID |
| T6-3 | 旧版单媒体规格向后兼容 | **通过** | 任务 03 旧规格（source_media 字符串）在新 schema 下仍 RESULT: VALID |
| T6-4 | 多视频规格安全语义校验 | **通过** | 重复 source_id、负 time_offset_ms、未授权路径（/etc/shadow）、shell 元字符路径、相对路径穿越均被拒绝（`artifacts/task-06/test-results.json` A3–A7） |

小计：任务 06 自主运行 4 项，4 项通过，0 项失败（累计 16 项测试 / 16 项通过）。

### 耗时（真实测量）

| 阶段 | 耗时 |
| --- | --- |
| 本地 Schema 校验 + 安全扫描（多视频规格） | ≈0.02 s |
| 任务 06 正向会话内规格生成 + 校验（Agent 自主） | 包含在整会话 ≈2202 s 内 |
| 任务 06 负向会话内规格生成 + 校验（Agent 自主） | 包含在整会话 ≈302 s 内 |

## Tier-3 对照评测中的规格编译表现（任务 07，2026-09-21）

with-skill 侧：E6（写诗）未加载任何 Skill 直接完成（正确负向触发）；E7/E8 安全拒绝；
E1–E5 视觉任务均生成合法 VisualTaskSpec（真实会话产物见 `artifacts/task-07/with-skill/*/tier3-result/`）。
baseline 侧无规格契约：E1 得出错误负面结论、E7 自建脚本向模型询问 apparent gender/age。
已知缺口（E9）：缺失媒体时未强制返回缺参错误（Agent 从项目文档推断路径）。
完整对照见根目录 `BENCHMARK.md`。

## Tier-3 评测器版本化（任务 09，2026-09-21）

- v1 评分器 `scripts/score_tier3_eval.py`（SHA-256 c35b4506…）冻结未改；其 stdout 断言语境误报（合规否定/政策声明被误判）经人工核验证实。
- v2 评分器 `scripts/score_tier3_eval_v2.py`（SHA-256 949772c9…）：导入继承 v1 全部规则，唯一变化为 stdout/文件一致的从句级否定/声明语境判定；回归测试 17/17（`scripts/test_score_tier3_eval_v2.py`）。
- 对任务 08 冻结数据全量重评分（未重跑模型会话）：差异仅 baseline E3 / with-skill E4 的 S5 误报修复；最终 with-skill 四维 9/9，Verdict PASS（历史 PARTIAL 保留，见根目录 BENCHMARK.md）。

## 采样策略契约（任务 16，2026-09-22；规则测试，无模型调用）

`schemas/visual-task-spec.schema.json` 新增可选顶层字段 `sampling_strategy`（向后兼容：缺失 = 旧版 uniform 行为）；校验器新增语义组合规则（执行期同口径）。规则测试 T1–T6 见 `.dsh/skills/visual-evidence-extractor/scripts/test_temporal_evidence.py`（完整结果 `artifacts/task-16/test-results.json`）。

| # | 测试 | 输入性质 | 结果 |
| --- | --- | --- | --- |
| T1 | 旧规格（无 sampling_strategy）继续有效 | 任务 03 真实规格 | **通过**：exit=0 |
| T2 | uniform 策略合法 | 构造规格（uniform + max_model_calls=12） | **通过**：exit=0 |
| T3 | adaptive 策略合法 | 构造规格（四必填字段齐全） | **通过**：exit=0 |
| T4 | 未知策略拒绝 | 构造规格（strategy=magic_sampling） | **通过（正确拒绝）**：exit=1 |
| T5 | 非法预算拒绝（0/-3/12.5/"12"） | 构造规格 | **通过（正确拒绝）**：4/4 exit=1 |
| T6 | 负/零时间精度拒绝 | 构造规格（-500 / 0） | **通过（正确拒绝）**：exit=1 |
| T6b | uniform + 细化参数（不支持组合）拒绝 | 构造规格 | **通过（正确拒绝）**：exit=1 |
| T6c | adaptive 缺 max_model_calls 拒绝 | 构造规格 | **通过（正确拒绝）**：exit=1 |

小计：任务 16 采样策略契约 8 项检查，8 项通过，0 项失败。

## Coverage-Aware 采样策略契约（任务 18，2026-09-22；规则测试，无模型调用）

`sampling_strategy` 契约扩展（向后兼容；uniform / adaptive_coarse_to_fine 行为零变化）：

| 检查 | 输入 | 结果 |
| --- | --- | --- |
| 旧规格兼容 | 任务 03 真实规格（无 sampling_strategy） | **通过**：RESULT: VALID |
| 旧策略行为不变 | uniform 预算 5 截断 / adaptive 无变化场景 4 调用 / adaptive 括号含 3200ms 且精度达成 | **通过**：与任务 16 冻结行为逐项一致 |
| coverage 策略合法 | 预注册 arm-configs.json 的 coverage 配置逐字 | **通过**：RESULT: VALID |
| coverage 缺必填 | 逐一删除 6 个必填字段 | **通过（正确拒绝）**：exit=1 且指出缺失字段 |
| coverage 非法值 | gap_target 0/-100/"1500"；reserve 0/-1/2.5；initial+reserve=13>预算 12；budget 0；precision 0；rounds 0 | **通过（正确拒绝）**：10/10 |
| coverage 配置不超预算 | initial(4)+reserve(9)>max_model_calls(12) | **通过（正确拒绝）**："覆盖配置之和不得超出硬性调用预算" |
| coverage 专属字段拒绝旧策略 | uniform / adaptive_coarse_to_fine 带 coverage_gap_target_ms 或 coverage_call_reserve | **通过（正确拒绝）**：不支持组合 |

小计：任务 18 采样策略契约 7 项检查，7 项通过，0 项失败（完整结果 `artifacts/task-18/test-results.json`，C01–C06）。
