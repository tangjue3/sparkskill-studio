# Task 25 运行摘要——中心帧 + 邻帧上下文视觉质量闸门（停在 STAGE1_HARM_STOP）

- 日期：2026-09-23（UTC）
- 工程状态：**PAIRING_COMPLETE（阶段 B）**——阶段 A 预注册先于任何正式 dev 调用；48 对同期配对完整记账；verdict 由冻结规则自动计算。
- 模型质量 verdict：**STAGE1_HARM_STOP**（阶段 B 门 B4 failed_not_increased 失败——候选多图引入了 2 次输出契约失败）。
- 阶段 A 提交：`2961139`（16:16:09Z）+ 执行器预执行修复 `0d3b9d4`（16:18:21Z），**均早于第一笔正式 dev 调用**（Stage B warm-up 16:16:37Z 为 fixture 非 dev；首笔正式 dev 调用在 warm-up 之后）。
- 阶段 C：**未运行**（阶段 B 停止门；不追加第 49 单元、不换候选、不重抽面板）；候选 cand **未采纳**，生产 v1 不变；holdout 仍封存。

## 1. 实验问题与设计

唯一新假设：让同一个本地 Qwen 在一次调用中看到指定**中心帧**以及前后各 500 ms 的**邻帧**（有序、明确标注），是否比同期单帧生产 v1 更能判断中心帧目标状态。候选只回答中心帧，邻帧只提供上下文。设计为**同期同中心帧配对**：184 个唯一中心帧（按 `(sample_id, frame_sha256, target_query)` 去重 Task 22 冻结 256 点），每单元生产 v1（单帧）/ 候选 cand（多图有序+只判中心帧）各一次真实 Qwen 调用，同一份中心帧字节、同一模型、同一请求参数、同一查询；唯一变量为候选多图上下文与必要的"只判中心帧"任务说明。**诚实披露**：两臂同时改变了图片上下文与任务说明，结果不能冒充纯输入信息的因果拆分。

## 2. 阶段 0（只读，先于任何 dev 调用）

- **多图接口技术 smoke（项目外合成图，7 次 ≤12）**：本地 Ollama Qwen 端点支持**单次请求有序输入多张图**；模型能稳定仅依据中心帧判断——仅中心/三帧都有目标 → object_found=true；仅前一帧/仅后一帧有目标 → object_found=false（关键负例各重复 2 次稳定，模型描述中心为"纯灰色背景"正确忽略邻帧目标）。verdict=**FEASIBLE**。见 `artifacts/task-25/smoke/smoke-report.json`。
- dev 包：manifest SHA-256 `794fbbe4…` 与给定值一致；九视频+九卡 **18/18 OK**；白名单九段；**holdout（公开版占位编号 HOLDOUT-G1/HOLDOUT-G2/HOLDOUT-L1）零接触**（包内无其文件）。
- 资源：MemAvailable 连续三次 ≥45 GiB（实测 ~120 GiB）、H3 停止、Ollama 正常、DSH 0.1.5-rc.2、无外部 Qwen 消费者、Git 无锁。

## 3. 184 单元、邻帧与候选定义

- **256→184 去重**：按 `(sample_id, frame_sha256, target_query)`；generated 110 / licensed-public 74；逐样本 AI01=15/AI02=20/AI03=20/AI04=18/AI05=14/AI06=23/WEB01=26/WEB02=18/WEB03=30；GT confirmed=86/not_found=64/uncertain=34。跨臂 GT 一致；中心帧逐字节匹配冻结帧农场（184/184）。见 `preregistration/unit-manifest-184.json`。
- **邻帧**：中心时间戳 ±500ms，`extract_frames.py` 同一 cv2 顺序解码+imwrite；越界侧缺席（absent_prev=10 / absent_next=10，不复制中心帧）；three=164 / two=20。**解码路径探针**：AI01/WEB01/WEB03 三分辨率中段帧重解码与冻结中心帧逐字节 all_match=true（证明同一 decode+encode）。
- **v1** = `analyze_image.PROMPT_TEMPLATE`（现行生产，零改动，SHA-256 `fc290780…`），单帧，请求逐字节复用 `analyze_image.call_ollama`。
- **cand** = `preregistration/prompt-candidate.txt`（SHA-256 `9f31a17c…`）= v1 主体 + 前置说明（图序 + 只判中心帧 + 不投射邻帧目标）+ 两处"这张图片/你在图片中"→"中心帧"指代替换；新增占位符仅 `{image_count}`/`{image_roles}`；多图有序 images=[prev,center,next]（存在侧）。coercer = `analyze_image.coerce_evidence`（核心字段逐字节相同；bbox 归一化用中心帧宽高，画框只对应中心帧）。

## 4. 执行与资源

- Stage B 运行窗口 2026-09-23T16:18–~16:52（UTC）；批量前 8 项资源门槛全过；运行中每单元前轻量门限通过；`resource_blocked=false`。
- warm-up 1 次（Task 16 fixture 帧，v1，不计正式）；阶段 0 smoke 7 次单列。
- **正式调用 96/96 完成**（48 单元 × 2 臂）：ok 94；**contract_rejected 2**（均在 cand 臂）、0 call_failed、0 invalid_json、0 重试；每点每臂至多一次；中心帧哈希 48/48 匹配。
- 2 次契约拒绝均为 cand 臂、错误"模型返回缺少合法的 object_found(boolean)"——多图输入下模型偶发返回不合规 JSON，被 coercer 如实记为 failed（不删点、不重试）。

## 5. 阶段 B 同期配对主结果（48 对，主比较以同期 v1 为准）

| 类别 | 同期 v1 | 同期 cand | Δ(cand−v1) |
| --- | --- | --- | --- |
| correct_decisive | 26 | 27 | +1 |
| incorrect_decisive | 10 | 8 | −2 |
| abstention_on_determinate | 0 | 0 | 0 |
| failed_on_determinate | 0 | **1** | **+1** |
| appropriate_abstention | 2 | 0 | −2 |
| overclaim_on_uncertain | 10 | 11 | +1 |
| failed_on_uncertain | 0 | **1** | **+1** |
| **错误断言**(incorrect+overclaim) | **20** | **19** | −1 |
| **合计** | **48** | **48** | |

分层：邻帧目标误投射中心实例 14 个（cand 判中心 confirmed 而 GT 判中心无目标），其中 **2 个为 v1 未犯的新增误投射**，12 个 v1 同样误判（预先存在的硬帧错误）。逐点变化 6 个。

## 6. 阶段 B 门槛逐项判定与 verdict

| 门槛 | 规则 | 实测 | 结果 |
| --- | --- | --- | --- |
| B1 错误断言不多于 v1 | cand ≤ v1 | 19 ≤ 20 | PASS |
| B2 correct 最多减 1 | v1−cand ≤ 1 | 26−27 = −1 | PASS |
| B3 新增误拒 ≤ 1 | cand−v1 ≤ 1 | 0−0 = 0 | PASS |
| B4 failed 不增加 | 各自 cand ≤ v1 | failed_det 0→1、failed_unc 0→1 | **FAIL** |
| B5 smoke 邻帧负例 | 阶段 0 负例无中心肯定 | 通过（阶段 0） | PASS |
| B6 完整性 | 媒体/调用/资源/安全/冻结 | 全过 | PASS |

**配对 verdict = STAGE1_HARM_STOP**（reason: B4_failed_not_increased；由 score_task25_pairs.py 冻结规则自动计算，独立复算一致）。

解读：候选多图在 48 单元上**略微**降低了错误断言（20→19）并小幅提升正确判断（26→27）、降低误报（incorrect 10→8），但**引入了 2 次输出契约失败**（多图输入下模型偶发返回缺 object_found 的 JSON）——failed_on_determinate 0→1、failed_on_uncertain 0→1，触发预注册 B4 门。候选还新增 2 个邻帧目标误投射中心的错误，overclaim 10→11 未降。**核心问题：多图时序上下文没有带来可靠的判断增益，反而增加了输出契约不稳定性**（失败面）与邻帧误投射风险。

## 7. 纪律与回归

- 阶段 A 提交（`2961139`）与执行器预执行修复（`0d3b9d4`）均早于首笔正式 dev 调用；**首笔 Stage B 尝试因 point_record 邻居字典推导语法错误在任何正式 dev 调用前崩溃（仅 1 次 fixture warm-up、0 正式 dev 调用），属阶段 A 预执行缺陷，已透明修复并复跑，无任何正式 dev 返回被改动**。
- **评分器接口缺陷披露**：Stage B 运行后发现 run_task25_pairing.py 输出键为 `units` 而 score_task25_pairs.py 读取键为 `points`（键名不一致）。此为纯数据读取缺陷，**未改任何 classify_entry/metric_for/门槛/verdict 逻辑、未改 48/184 名单/候选提示词/帧偏移/模型参数/GT/运行顺序、未重跑任何 Qwen 调用**；修复后 `--verify-historical` 仍 256/256 等价、门单测不变，对不可变的 96 条 Stage B 结果重新评分得同一 verdict。已向总控披露备审。
- 新测试 `scripts/test_task25_gate.py` **28/28**；旧回归：Task 22 配对 **30/30**、Task 17 评分器 **38/38**、`--verify-historical` 256/256；交付验证 `scripts/verify_task25.py` **13/13**（V2–V11）。
- `git diff --check` 干净；敏感扫描 0 命中；冻结路径（生产 v1/Task17/GT/schema/app/task-25 预注册）零改动；无原始视频/权重/媒体/凭据/私有真人决定入 Git。

## 8. 结论与状态

- **工程状态：阶段 B PAIRING_COMPLETE**——一次预注册、一个候选、一次正式 48 对配对、96/96 调用完整记账、verdict 由冻结规则计算、独立复算一致。
- **模型质量状态：STAGE1_HARM_STOP**。候选多图时序上下文在 48 单元早停门上因引入 2 次输出契约失败（failed 两类各 +1）触发 B4 停止门；错误断言仅降 1（远低于阶段 C 要求的 ≥8）、overclaim 反升 1、新增 2 个邻帧误投射。**多图上下文未转化为可靠的中心帧判断增益，且增加输出契约不稳定性与邻帧误投射风险**。
- **按预注册停止门：不运行阶段 C、不做 DSH 自主会话、不迭代第二候选、不改生产 v1**。候选 cand **未采纳**（analyze_image.py 零改动，v1 仍是生产模板）。
- **仍未解决**（与 Task 19B/20/22 一致）：uncertain 区过度断言、真实域误报、GT 边界匹配、模型语义校准——本轮进一步证据表明**加入邻帧时序上下文不是修复路径**（失败层仍在视觉模型语义 + 多图下输出契约稳定性）。
- dev 小样本 + 单次运行 + 温度 0.1 随机性：不给统计显著性、不外溢真实仓储准确率。holdout 仍封存；未触碰任何 holdout。

## 9. 产物索引

- `preregistration/`：design.md、evaluation-plan.json、prompt-candidate.txt、unit-manifest-184.json、first-batch-48.json、frozen-hashes.json（37 条）
- `smoke/`：阶段 0 多图技术 smoke 报告 + 调用日志（7 次）
- `stage-b/`：run-metadata.json、call-log.jsonl（1 warm-up + 96 正式）、pairing-results.json、points/（48 单元逐点）、paired-score-B.json、paired-rows-B.json、analysis.json
- `verification.json`（13/13）、`test-results.json`（28/28）
- `scripts/`：task25_build_units.py、run_task25_smoke.py、run_task25_pairing.py、score_task25_pairs.py、task25_analyze.py、test_task25_gate.py、verify_task25.py、build_frozen_hashes_task25.py
