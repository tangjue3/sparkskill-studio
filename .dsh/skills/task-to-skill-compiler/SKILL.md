---
name: task-to-skill-compiler
description: 将用户的一句自然语言视觉任务编译为一个受控的、带输入输出契约的 Agent Skill 配置（Skill Card 草稿）；支持单媒体与多段视频（source_media 来源数组）任务规格。任何视觉任务的第一环与硬门：用户未在当前请求中显式提供媒体路径/附件时，必须返回 needs_input/missing_source_media 缺参契约并停止——禁止搜索项目文件、README、历史 artifacts、run-summary 或目录来推断媒体，禁止加载视觉 Skill 或调用视觉模型；只做声明式配置，不生成、不执行任何自由形式的模型代码或脚本。
---

# Skill: task-to-skill-compiler

- **name**: task-to-skill-compiler
- **status**: minimal（图片最小闭环已实现；多段视频规格已支持，任务 06；媒体来源前置硬门已建立，任务 08；采样策略契约已支持，任务 16）
- **owner**: SparkSkill Studio（自研，非 NVIDIA 官方签名）

## description

SparkSkill Studio 流水线的第一环：把用户的一句自然语言视觉任务，通过 DSH Harness + StepFun（step-5-preview，文本链路）编译成符合 `schemas/visual-task-spec.schema.json` 的结构化 VisualTaskSpec JSON，供 `visual-evidence-extractor` 消费。只做声明式配置，不生成、不执行任何自由形式的模型代码或脚本。

## 第 0 步：媒体来源前置校验（硬门，任务 08 建立；先于任何其他动作）

**任何视觉任务**（要求分析图片/视频/帧/画面的任务）在生成 VisualTaskSpec 之前，必须先判定媒体来源是否可信：

1. 运行 `python3 scripts/check_source_media.py --request <当前用户请求文本>`（可加 `--spec <候选规格>` 做反推断校验）。该脚本是请求文本的纯函数，不访问项目文件系统。
2. 按契约输出行动：
   - `status=accepted`（source_media_provenance=user_provided）→ 才允许继续生成规格、加载 `visual-evidence-extractor`、调用视觉模型；
   - `status=needs_input`（error_code=missing_source_media）→ **立即停止**：向用户返回缺参契约，不得执行任何后续动作；
   - `status=rejected`（error_code=invalid_source_media 或 inferred_source_media）→ **立即停止**：向用户返回拒绝契约，不得执行任何后续动作。
3. `tool_calls_allowed=false` 时禁止：调用 Qwen/任何视觉模型、抽帧、读取历史媒体路径、搜索项目文件、加载 `visual-evidence-extractor`、生成 VisualTaskSpec、生成任何证据。缺参时唯一允许的动作是把契约返回给用户。

### 停止清单（needs_input / rejected 时必须逐条遵守；任务 08 稳定性复测曾发现违规搜索）

判定为 needs_input 或 rejected 后，**唯一允许的输出是契约本身**。以下动作一律禁止（无一例外）：

- 不得加载任何其他 Skill——**包括 `visual-evidence-extractor`**（即使用户任务文本看起来直接匹配它的 description；本 Skill 的第 0 步先于一切）；
- 不得运行 `ls` / `find` / `grep` / `cat` / `tree` 或任何目录列举/搜索——包括项目目录、`artifacts/`、`/tmp`、`~/Downloads`、`minimax-h3/outputs` 等任何位置；
- 不得读取 README / PROJECT_CONTEXT / 设计文档 / run-summary / 历史 artifacts / 上一次会话产物；
- 不得以"帮用户找媒体"为由做任何探索性工具调用；缺参时问用户是唯一正确行为。

### 媒体来源可信条件（首版）

**只接受**：

1. 当前用户消息中显式提供的本地媒体路径（绝对或相对路径，含媒体扩展名）；
2. 当前用户正式上传/附加、并由 Harness 明确传入的媒体（Harness 传入时请求中会出现该路径或附件标识）；
3. 当前用户消息中显式列出的多个媒体来源（多段视频任务）。

**不得接受**（出现即视为不可信来源，禁止用作 source_media）：

- README / PROJECT_CONTEXT / 设计文档中的路径；
- run-summary / 历史 artifacts / 上一次会话产物中的路径；
- 先前会话中的默认视频；
- 目录扫描找到的第一个视频（如 `ls outputs/*.mp4`）；
- 测试目录中的示例视频；
- 模型自行推断的媒体；
- Agent 根据"看起来合适"选择的视频。

### 缺参返回契约（needs_input）

```json
{
  "accepted": false,
  "status": "needs_input",
  "error_code": "missing_source_media",
  "missing_fields": ["source_media"],
  "message": "请明确提供要分析的图片或视频路径。",
  "tool_calls_allowed": false
}
```

### 非法/推断来源返回契约（rejected）

```json
{
  "accepted": false,
  "status": "rejected",
  "error_code": "invalid_source_media",
  "tool_calls_allowed": false
}
```

（规格中的媒体未出现在当前用户请求中时为 `inferred_source_media`，同样 rejected。）

**缺失路径与非法路径必须区分**：没给路径是 `missing_source_media`（问用户），给了但不可用是 `invalid_source_media`（拒绝），不得互相退化。

## 当前职责

- 解析自然语言任务意图：判定是否为视觉对象任务（object_trace / object_presence），提取目标描述与属性、输入媒体、必需输出、拒答条件。
- 产出 VisualTaskSpec（task_id、skill_name、task_type、target、source_media、required_outputs、constraints、confidence_threshold、requires_visual_input=true）。
- **多段视频任务（任务 06）**：`source_media` 产出为来源对象数组 `[{"source_id","path","location","time_offset_ms"}, ...]`：source_id 任务内唯一、path 必须位于授权媒体根目录（项目根 / `<内部测试媒体目录>/outputs` / `<内部测试媒体目录>/webui/uploads`，可用 `SPARKSKILL_AUTHORIZED_MEDIA_ROOTS` 受控扩展）、time_offset_ms 非负；旧版单路径字符串规格继续有效（向后兼容）。
- **采样策略（任务 16/18）**：视频任务可声明可选顶层字段 `sampling_strategy`（向后兼容；缺失 = 旧版 uniform 行为）：
  - `strategy`：`uniform`（正式 baseline，固定间隔/均匀采样）/ `adaptive_coarse_to_fine`（初始覆盖 + 按触发器二分细化）/ `coverage_aware_adaptive`（任务 18：时间覆盖探索 + 边界细化双职责）；
  - `max_model_calls`：硬性视觉模型调用预算（正整数，≤512；实际 Qwen 调用不得超过）；
  - `initial_coverage_samples` / `target_boundary_precision_ms` / `max_refinement_rounds`：adaptive 与 coverage 必填（初始覆盖数 ≤ 预算；边界精度 > 0 ms）；
  - `coverage_gap_target_ms` / `coverage_call_reserve`：coverage_aware_adaptive 必填（覆盖目标 > 0 ms；覆盖调用储备正整数；且 `initial_coverage_samples + coverage_call_reserve ≤ max_model_calls`——覆盖配置不得超出硬预算）；
  - `refinement_triggers`：`state_change` / `abstained` / `low_confidence` / `failed`（缺省全开）；
  - `require_sampling_provenance` / `require_temporal_evidence`：缺省 true；
  - 不支持组合明确拒绝：uniform 带细化/覆盖参数、adaptive 带 coverage 专属字段、任一策略缺必填字段、initial(+reserve) > budget、未知策略、非法预算、≤0 精度（校验器执行期与编译期同口径）。
  - 编译自然语言中的"自适应采样/调用预算/边界精度/覆盖"意图时必须显式生成该字段，不得默认猜测。
- 用 `scripts/validate_task_spec.py` 对产出做本地 Schema 校验 + 安全扫描（拒绝代码、shell 命令、凭据样式内容、未授权路径、重复 source_id、负 time_offset_ms、非法采样策略组合）；规格缺少 source_media 时输出 `missing_source_media`/`needs_input` 契约，路径非法时输出 `invalid_source_media`/`rejected` 契约。
- 缺失参数或非视觉任务时返回明确错误，不猜测性放行。

## 正向触发（should-trigger）

- "追踪红色背包在输入媒体中的出现情况；输出视觉证据；如果不存在或无法确认，不要猜测。"
- "判断这张图片里有没有 X，并给出证据。"
- 任何要求对图像/视频中的对象做存在性判断或追踪、并要求证据与拒答的自然语言任务。
- 任何视觉任务——**即使用户没有提供媒体路径**（此时本 Skill 的职责是返回 `needs_input`/`missing_source_media` 缺参契约，而不是帮用户找媒体）。

## 负向触发（should-not-trigger）

- 非视觉任务（纯文本问答、写诗、翻译、代码咨询等）——不得产出 VisualTaskSpec，不触发媒体前置校验。
- 要求识别人脸、推断身份/年龄/国籍/关系/意图的任务——拒绝并说明原因。
- 要求生成可执行代码、shell 命令或涉及凭据的任务——拒绝。
- 与视觉证据无关的系统操作请求——拒绝。

## 输入输出契约

- 输入：自然语言任务字符串（经 DSH Harness 传入）。
- 输出：VisualTaskSpec JSON（契约见 `references/visual-task-spec.md`，Schema 见项目根 `schemas/visual-task-spec.schema.json`）；或缺参/拒绝契约（见第 0 步）。
- 校验：`python3 scripts/validate_task_spec.py --schema ../../schemas/visual-task-spec.schema.json --input <spec.json>`。
- 来源前置校验：`python3 scripts/check_source_media.py --request <用户请求文本> [--spec <规格>]`。

## 安全边界

- 不生成、不执行任意模型代码；产出物只有声明式 JSON 配置。
- 默认 `constraints.forbidden_inferences = [identity, age, nationality, relationship, intent]`，默认 `abstain_if_insufficient_evidence = true`。
- **媒体来源可信**：source_media 只能来自当前用户请求显式提供或 Harness 明确传入；禁止从项目文档、历史产物、目录扫描或模型推断获得（见第 0 步）。
- 不冒充 NVIDIA 官方签名 Skill。
- 视觉推理不属于本 Skill（属于 visual-evidence-extractor）。

## 当前状态

- minimal：契约、校验脚本、触发边界、Skill Card、evals、BENCHMARK 已落地；编译动作由 DSH + StepFun 文本链路完成，无本地业务脚本编排。
- minimal：媒体来源前置硬门（`check_source_media.py` + missing/invalid 契约区分）已建立，M1–M8 契约测试见 `scripts/test_missing_media_contract.py`（任务 08）。
- minimal：采样策略契约（`sampling_strategy`：uniform / adaptive_coarse_to_fine + 硬预算 + 边界精度 + 细化触发器）已建立（任务 16）；规则测试 T1–T6 见 `visual-evidence-extractor/scripts/test_temporal_evidence.py`。
- minimal：coverage_aware_adaptive 策略契约已建立（任务 18：六必填字段 + 覆盖配置不超预算 + coverage 专属字段对旧策略拒绝）；规则测试 C01–C06 见 `visual-evidence-extractor/scripts/test_task18_coverage_sampling.py`（36/36）。
