# Task 23 运行摘要——Step 3.7 Flash 视觉后端小样本闸门（阶段 A+B）

- 日期：2026-09-23（UTC）
- 起点 HEAD `90c76b6`（master，工作区干净，无 remote）
- 阶段 A 冻结提交：`67559008`（2026-09-23T12:24:11Z），**早于第一次 dev 模型调用**（12:24:16Z，早 5 秒，V1 时序证明）
- 本提交为阶段 B 事实结果提交
- **最终 verdict：`GATE_NOT_MET`**（G1 有害降幅、G2 overclaim 降幅、G5 失败不增 三项失败）；按预注册纪律保留失败产物、停止 step-3.7-flash 路线、不擅自再调第二个候选

## 1. 实验问题与设计

唯一新假设：StepFun `step-3.7-flash` 云端后端（官方开放平台 `https://api.stepfun.com/v1/chat/completions`）相对生产 Qwen v1 本地后端（`analyze_image.py` 零改动），在同一 dev 帧字节、同一 target_query、同一语义边界、同一结构化证据契约下，是否有足够同帧语义增益。48 帧诊断面板（覆盖层 27 + 困难层 21）× 2 侧 = **96 次正式视觉调用**，同期同帧配对；唯一变量为后端。提示词双方逐字节一致（9/9 样本 identical，哈希冻结）；候选提示词在技术冒烟后、正式 dev 调用前固定一次。

## 2. 阶段 0（可用性与技术冒烟，先于任何 dev 调用）

- 官方文档核对：`step-3.7-flash` 为原生多模态推理模型（198B/11B MoE，256K 上下文）；开放平台 Chat Completions 支持 base64 `image_url` multipart 与 `json_object`/`json_schema`；**Step Plan 通道（`/step_plan/v1`）不支持图像输入**（`unsupported_content_type`），故候选走官方开放平台端点（模型 ID 不变）。
- 凭据机制：DSH 凭据 seam 检查显示 `STEPFUN_API_KEY` 初始未配置；用户在本轮对话中提供密钥后，经 `credentials.set` 只写存入托管存储（`source: file`），**密钥值未进入任何输出/日志/artifacts/Git**；未改 `~/.dsh/settings.yaml`、全局环境、profile、Ollama 配置或 Git 全局身份。
- API 通道验证：`GET /v1/models` 200，36 个模型含 `step-3.7-flash`。
- 技术冒烟（合成非 dev 测试图，最多 3 次）：smoke-1 存在目标 `object_found=true`（描述与边框正确对应图像内容，证明图像抵达模型）；smoke-2 不存在目标 `object_found=false, abstention_reason=null`（确定性负面纪律）；smoke-3 用阶段 A 冻结提示词模板复验拒答纪律。3 次均 200、JSON 可解析、usage 元数据完整（如 smoke-1: prompt 508/completion 561 tokens）。冒烟期草稿变体（禁止推断以 `,` 连接）与冻结文本（`、` 连接）的差异已在 `phase0/smoke-prompt-consistency.json` 如实记录。
- 资源窗口：H3 未运行（无用户任务）、Ollama 空闲、MemAvailable ~115.8 GiB、无 Git 锁。

## 3. 阶段 A 冻结内容（提交 `67559008`）

候选模型/端点/参数（temperature=0.1、reasoning_effort=medium、detail=high、response_format=json_object、max_tokens=2048、timeout=180s）；生产 v1 文件哈希 `e3441778…`；双方提示词全文与逐样本哈希；视觉输出契约（与生产 `coerce_evidence` 同义）；48 帧 sample ID/原视频时间/帧 SHA-256/原媒体 SHA-256/target_query/调用顺序（固定种子 20260923 洗牌，先手方奇偶交替各 24）；无重试纪律；GT 封存后读取；七类互斥映射；扩实验闸门；敏感信息检查口径。48/48 帧哈希在盘验证，30 帧与 Task 20 冻结帧农场逐字节一致；dev 包 manifest SHA-256 复算匹配。帧存于仓库外 700 目录，不入 Git。

## 4. 执行与调用账（阶段 B）

- 运行窗口 12:24:16Z → 12:47:45Z（约 23.5 分钟）。
- **正式调用 96/96 完成**（48 对 × 2 侧）：两侧各 48 次；**0 传输失败、0 超时、0 重试**；warm-up 1 次（Task 16 fixture 帧，Qwen 侧，不计正式）。
- Qwen v1 侧 48/48 analyzed；候选侧 46 analyzed + **2 contract_rejected**（GATE-P0027/P0029，WEB01 困难层：`finish_reason=length`，推理占满 2048 max_tokens 致 content 为空——按冻结纪律不重试、不改参数，如实记账）。
- 延迟：v1 均值 15.32s/中位 13.57s/max 33.16s；候选均值 13.64s/中位 10.88s/max 32.13s。
- 候选 token 用量：prompt 64,726 + completion 32,545 = 97,271（按官方定价约 ¥0.35）。
- 每点前资源门持续通过（0 事件）；`resource_blocked=false`。
- 历史漂移交叉检查：与 Task 22 同期 v1 在 30 个同 (sample,ts) 点上**类别零差异**（v1 侧完全复现）。

## 5. 七类互斥账（48 帧，主比较以同期 v1 为准）

| 类别 | 同期 v1 | 候选 | Δ |
| --- | ---: | ---: | ---: |
| 正确确定 correct_decisive | 22 | 22 | 0 |
| 错误确定 incorrect_decisive | 18 | 13 | −5 |
| 可判定误拒 abstention_on_determinate | 0 | 3 | +3 |
| 可判定失败 failed_on_determinate | 0 | 2 | +2 |
| uncertain恰当拒答 appropriate_abstention | 1 | 1 | 0 |
| uncertain过度断言 overclaim_on_uncertain | 7 | 7 | 0 |
| uncertain失败 failed_on_uncertain | 0 | 0 | 0 |
| **有害合计** | **25** | **25** | **0** |

- 双轨：generated（24 帧）v1 有害 8 → 候选 10（correct −2、incorrect +1、误拒 +1）；licensed-public（24 帧）v1 有害 17 → 候选 15（incorrect 17→11 被误拒 +2、失败 +2 部分抵消）。
- 两层：覆盖层 27 v1 有害 6 → 候选 8；困难层 21 v1 有害 19 → 候选 17。
- 九样本：AI01 v1 4 正确/1 错误 → 候选 2/2（+1 误拒）；AI02/AI03/AI05 全正确持平；AI04 overclaim 3→3 持平；AI06 overclaim 4→4 持平；WEB01 v1 1 正确/9 错误 → 候选 3/5（+2 失败）；WEB02 4→4 持平；WEB03 v1 2/8 → 候选 2/6（+2 误拒）。
- 故障类别：F1 假阳性 v1 13 错误 → 候选 7 错误 + 2 误拒 + 2 失败 + 2 正确；F2 假阴性 2→2；F3 uncertain 过度断言 4→3（+1 恰当拒答）；F4 边际帧 1 正确 → 1 错误；F5 困难控制 1→1。
- 逐帧转移 12 帧：候选修复 5 个真实域假阳性（WEB01×3、WEB03 内 2 个转正确/拒答混合）、AI06 t=0 过度断言转恰当拒答；但引入 AI01 边际帧误拒（t=666.667 转错误、t=791.667 转误拒）、WEB01 t=9275.933 正确转错误、AI06 t=5083.333 恰当拒答转过度断言、WEB03 2 个假阳性转误拒、WEB01 2 个假阳性转失败。

## 6. 扩实验闸门逐项判定（协议第七节，看到 dev 返回后未修改）

| 闸门 | 规则 | 实测 | 结果 |
| --- | --- | --- | --- |
| G0 辨别力 | v1 有害 ≥5 | 25 | PASS |
| G1 有害降幅 | 少 ≥3 且 ≥20% | 25→25（0，0%） | **FAIL** |
| G2 overclaim 降幅 | 少 ≥1 | 7→7 | **FAIL** |
| G3 正确容忍 | 最多少 2 | 22→22（0） | PASS |
| G4 licensed 有害不增 | ≤ | 17→15 | PASS |
| G5 失败不增 | 各自不增 | failed_det 0→2、契约拒绝 0→2 | **FAIL** |
| G6 完整性 | 48/48 + 账完整 | 48/48、96/96、0 重试、无资源中断 | PASS |

**verdict = GATE_NOT_MET**（reasons: G1_harmful_reduction, G2_overclaim_reduction, G5_failures_not_increased）。

## 7. 解读与边界

- 候选在真实域假阳性上有同帧语义增益（WEB01 空载误报 9→5、WEB03 误报 8→6，licensed 有害 17→15），但增益被三类新问题抵消：可判定误拒 +3（AI01 边际帧、WEB03 负向帧）、可判定失败 +2（WEB01 推理占满 max_tokens 截断）、覆盖层 AI06 uncertain 帧新增过度断言。uncertain 区核心缺口（AI04/AI06 过度断言）**未改善**（7→7）。
- 48 帧为诊断面板，不是随机行业样本；dev 小样本 + 温度 0.1 随机性 + 单次运行：不给统计显著性、不外推真实仓储准确率、不宣称时间边界改善。AI 段为 MiniMax-H3 生成受控测试视频。
- fresh-call/provenance 形式不满足 Task 17 正式 scorer 处为规则级诊断（复用冻结纯函数 + 本任务闸门），不伪装 Task 17 正式分数。
- **PROMISING_FOR_FULL_DEV 未达到**：不向总控申请完整九段 dev 扩展；按预注册停止门，不运行动态三臂、不接入 Skill、不改生产 v1、不触碰 holdout、不调第二个候选。

## 8. 纪律与回归

- 冻结路径（Task 17/18/19/20/21/22、app/、生产 v1、三 Skill、Tier-3、schemas）零改动（git diff 90c76b6→HEAD 仅 `artifacts/stepfun-vision-gate/`，30 文件）。
- 生产 `analyze_image.py` 哈希复验 `e3441778…` 未变；dev 包 manifest 复验未变；帧目录仓库外 700。
- 敏感扫描 0 命中（无密钥/token）；holdout（公开版占位编号 HOLDOUT-G1/HOLDOUT-G2/HOLDOUT-L1）零搜索/零读取/零复制/零推断；原视频/WEB 帧/完整 data card/GT/历史 Qwen 输出未入 Git，也未提交给 StepFun（仅提交经许可检查的 dev 帧字节）。
- 服务原状：Ollama 0.33.2 正常运行、DSH Web 未重启、H3 未启动/停止/卸载、未用 `keep_alive=0`；未建 remote、未 push、未改全局配置。
- 每次提交用一次性 Git 身份（`task23-stepfun-gate@localhost.invalid`）。

## 9. 产物索引

- `preregistration/`：protocol.json、protocol.md、prompt-candidate.txt、frame-selection.json（含完整候选池与筛选理由）、frame-manifest-48.json、frozen-hashes.json、specs/（9 样本）
- `phase0/`：smoke-prompt-consistency.json；`smoke/`：3 次冒烟记录 + 合成测试图
- `runs/`：run-metadata.json、call-log.jsonl（97 条：1 warm-up + 96 正式）、pairing-results.json、points/（48 逐点 + 96 侧调用原始返回）、run.stdout.log
- `scores/`：paired-score.json、paired-rows.json（48 逐帧转移）、paired-report.md、historical-drift-crosscheck.json
- `scripts/`：select_frames.py、extract_gate_frames.py、freeze_protocol.py、stepfun_call.mjs、stepfun_credentials_check.mjs、run_gate.py、score_gate.py
