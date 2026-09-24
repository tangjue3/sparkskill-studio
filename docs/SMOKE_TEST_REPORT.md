# SMOKE TEST REPORT — SparkSkill Studio 任务 02

- 日期：2026-09-21
- 任务：验证 DSH Harness、项目 Skill 发现机制和 StepFun Provider 的最小可行链路
- 方法：全部结论来自实际执行（DSH headless 模式真实调用 + 当前会话实时观察），非文档推测

## 1. 测试环境

- 硬件平台：NVIDIA DGX Spark / GX10（GB10，统一内存架构，CUDA 13.0.2，ARM64）
- DSH 版本：0.1.5-rc.2（`<npm缓存>/_npx/1e7f6d9597241db0/node_modules/.bin/dsh`）
- 验证方式：`dsh --profile headless "<task>"`（headless profile，单任务执行后退出）；另通过当前 Web 会话的实时 skill catalog 交叉验证
- 项目 Skill 路径：`.dsh/skills/`（项目根由最近的 `.git` 祖先判定，本仓库已初始化 Git，判定正确）
- StepFun Provider：`stepfun`（`api: openai-completions`，`baseURL: https://api.stepfun.com/step_plan/v1`），默认模型 `step-5-preview`（由 `agent-default-model` 配置决定）
- 本报告不含任何凭据（未读取、未输出任何 API key / token / 密码）

## 2. Skill 发现结果

### 发现机制（已从 DSH 源码确认并经运行验证）

- 实现插件：`@deepseek-ai/dsh-skill-filesystem`（由 `@deepseek-ai/dsh-base` bundle 挂载，headless 与 web profile 均包含）
- 扫描根（按 rank）：`<projectRoot>/.dsh/skills`（rank 100）→ `<projectRoot>/.agents/skills`（200）→ 自定义目录（300）→ `<dshHome>/skills`（400）→ `<agentsHome>/skills`（500）
- 发现形式：目录 bundle `<name>/SKILL.md` 或平铺 `<name>.md`，仅一层，不递归
- frontmatter 硬性要求（源码 `parseSkillFile`）：文件首行必须是 `---`；必填 `name`（kebab-case，正则 `^[a-z0-9]+(?:-[a-z0-9]+)*$`）与 `description`（非空字符串）；可选 `whenToUse`、`metadata`、`disable-model-invocation`、`user-invocable`；旧键 `disableModelInvocation`/`modelInvocable`/`userInvocable` 会被拒绝
- 渲染链路：`dsh-skill`（registry）→ `dsh-tool-skill`（会话 catalog + `skill` 加载工具）；catalog 变更会热重载推送，无需重启

### 修正前（实证）

- 执行：headless 会话中询问 skill catalog → 返回 `CATALOG_EMPTY`
- 原因：三个 SKILL.md 当时为纯 Markdown，无 YAML frontmatter，被 `parseSkillFile` 以 "missing YAML frontmatter" 跳过（该跳过只记警告，模型侧无诊断）
- 结论：**修正前三个 Skill 均不可被发现**

### 修正后（实证）

- 修正：给三个 SKILL.md 补齐最小 frontmatter（`name` + `description`），正文保持不变
- 执行 1：新 headless 会话询问 catalog → 返回全部三个名称：
  ```
  evidence-report-generator
  task-to-skill-compiler
  visual-evidence-extractor
  ```
- 执行 2：当前 Web 会话在文件落盘后即时收到 catalog 推送（`<available_skills>` 出现三条），证明 watcher 热重载生效
- 结论：**修正后三个 Skill 均被正常发现，frontmatter 检查通过**

## 3. StepFun 文本调用结果

- 执行：headless 任务要求返回固定 JSON
- 结果：**成功**
- Provider：`stepfun`（DSH 默认模型配置 `agent-default-model: provider=stepfun`）
- 模型：`step-5-preview`（模型自报与配置一致）
- 实际返回（逐字）：
  ```json
  {"task":"sparkskill_smoke_test","status":"ok","model":"step-5-preview","harness":"dsh"}
  ```
- 结构化 JSON：成功，无 markdown 包裹、无多余文本
- 超时：无；认证错误：无；模型路由错误：无；格式错误：无
- 退出码：0

## 4. StepFun 多模态调用结果

- 执行：headless 任务要求读取 `<内部测试媒体目录>/test_first.png`（PNG，1024×576）并返回结构化 JSON
- 结果：**失败（DSH 链路层拦截）**
- Agent 实际返回（逐字）：
  ```json
  {"image_read_attempted":true,"error":"model does not support image input","evidence_insufficient":true}
  ```
- 失败原因：当前 DSH 的 stepfun provider 模型目录未声明图片输入能力（settings.yaml 中仅 ollama 的 Qwen3.8-27B 声明了 `input: [ text, image ]`；stepfun 下所有模型均未声明）。图片读取在到达模型前被链路拒绝。本会话自验同样报错：`model "step-5-preview" does not declare image input`
- 未使用另两张测试图片（`test_first_small.png`、`test_last.png`）：失败原因与具体图片无关，重复无意义
- 说明：StepFun API 侧是否存在支持图片的模型（如换用其他模型 id 并声明 `input: [text, image]`）**未经本次验证**；修改 settings.yaml 属本任务禁止事项，未尝试

## 5. 当前可行性判断

| 能力 | 判断 | 依据 |
|---|---|---|
| DSH Harness | **可用** | headless 模式两轮正常启动、执行、退出（exit 0）；模型调用、工具调用、reasoning 流均正常 |
| StepFun 文本调用 | **可用** | `step-5-preview` 返回符合要求的结构化 JSON，无超时/认证/路由/格式错误 |
| StepFun 图片调用 | **不可用（当前链路）** | stepfun provider 未声明图片输入，读取在链路层被拒；API 侧能力待确认 |
| 项目 Skill 发现 | **可用** | frontmatter 修正后三个 Skill 在新会话均被发现，且支持热重载 |

## 6. 对后续开发的影响

- Skill 骨架的 frontmatter 契约已对齐 DSH 实际要求（`name` kebab-case + `description` 必填），后续新增 Skill 必须沿用该格式，否则会静默不可见。
- Skill 的发现/加载/复用链路（项目根判定、watcher 热重载、catalog 渲染）已实证可用，阶段 1 的"DSH 加载机制验证"目标已提前达成。
- StepFun 文本链路可用：Skill A/B/C 中所有"文本结构化输出"环节（Skill Card 生成、证据 JSON、报告）具备模型条件。
- **视觉证据抽取（Skill B 的核心）当前被阻塞**：多模态输入不可用。在用户确认并启用图片输入能力之前，不得承诺任何视觉功能；设计中"视觉推理走 StepFun API"的假设需要补充验证或调整（例如确认 StepFun 支持图片的模型 id，或由用户更新 provider 声明）。
- 本报告所有结论仅基于上述四次真实执行记录。

## 7. 禁止事项检查

- 是否安装依赖：**否**（未安装任何包）
- 是否修改系统配置：**否**
- 是否修改 DSH 全局配置：**否**（未改 `~/.dsh/settings.yaml`、`~/.dsh/.credentials.yaml`；headless 启动时 DSH 自行重写了 profile 引导产物 `~/.dsh/profiles/headless/cordis.yml`，内容与既有文件一致，非配置变更）
- 是否启动或停止服务：**否**（MiniMax-H3 :8000、Ollama :11434、DSH Web :7000 均未触碰；headless 为一次性执行后退出的独立进程）
- 是否读取凭据：**否**（查看 settings.yaml 时仅提取 provider 名称/端点/模型 id，密钥字段已脱敏，未读取、未输出任何 key/token/密码）
- 是否修改 GitHub remote：**否**（未添加、未修改、未推送）
- 其他：未编写业务脚本、未下载模型、未做人脸/身份相关处理、未把 OpenCV 写为核心技术、未伪造 NVIDIA 官方 Skill 接入
