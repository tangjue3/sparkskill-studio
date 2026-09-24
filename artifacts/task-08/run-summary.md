# Task 08 运行摘要 — E9 根因修复与 Tier-3 完整重跑（因评测器缺陷停止，等待用户决定）

- 日期：2026-09-21（UTC）
- 任务：修复 Tier-3 E9 暴露的"缺少媒体时从项目上下文猜测路径"问题，并用冻结的原任务集/评分器重跑完整对照评测
- 当前状态：**修复完成且经验证；完整重跑已执行并用冻结评分器评分；评分中发现冻结评分器存在对称误报缺陷（见 `frozen-evaluator-findings.md`），按任务书第三节要求停止任务完成流程，等待用户决定。**

## 1. 根因

任务 07 初轮 with-skill E9（缺失媒体路径）失败：Agent 跳过 compiler，直接加载 visual-evidence-extractor 与 evidence-report-generator，随后用 `ls -R artifacts/`、`grep run-summary.md`、`ls minimax-h3/outputs/*.mp4` 从项目文档和历史产物推断出 `h3-smoke.mp4` 并完成真实分析。规格本身合法——唯一缺失的是**媒体来源 provenance 规则**（媒体只能来自当前用户请求）。

## 2. 冻结资产及 SHA-256（前后一致）

| 文件 | SHA-256 |
| --- | --- |
| `evals/tier3/evals.json` | `64da5041a178ae442391bdbd9b528db5ab27ab514136ec595366b327d864ccaa` |
| `scripts/score_tier3_eval.py` | `c35b450627f0ff36640012ae5cb02ff7b35d608a6d7de01b28ed3935af151ee0` |

修复前后各计算一次，完全一致；任务集 Prompt/expected/forbidden/scoring_rules、PASS 条件、baseline 隔离与 with-skill 运行方式均未改动；`artifacts/task-07/` 未修改（Git 历史可证）。

## 3. 修复前回归测试（证据保留于 `pre-fix-regression/`）

`test_missing_media_contract.py`（M1–M8 + V1/V2）修复前 **0/10 通过**：来源校验器不存在；校验器对缺 source_media 只报通用"缺少必填字段"（无 needs_input/missing_source_media 契约）；对非法路径无 invalid_source_media 契约。M1/M3 失败直接证明根因。

## 4. 实际修复（提交 6137fbe、ef650ef；只改 compiler Skill + 校验器契约）

- 新增 `scripts/check_source_media.py`：媒体来源前置校验器，**请求文本的纯函数**（不访问项目文件系统）。四态契约：accepted(user_provided) / needs_input(missing_source_media) / rejected(invalid_source_media | inferred_source_media) / not_applicable；`tool_calls_allowed=false` 时禁止调用视觉模型、抽帧、搜索媒体、加载视觉 Skill。
- `validate_task_spec.py`：缺 source_media → `[CONTRACT] needs_input/missing_source_media`；路径非法 → `rejected/invalid_source_media`——缺失与非法不再混为通用错误。
- SKILL.md/skill-card/references：第 0 步媒体来源硬门 + 可信/不可信来源清单 + 停止清单（needs_input/rejected 后唯一允许输出是契约；禁止加载任何其他 Skill、禁止 ls/find/grep 搜索、禁止读取历史产物）；frontmatter description 对 DSH skill catalog 可见。
- evals.json：新增 4 组媒体 provenance 用例。
- 冻结的 9 个 Tier-3 提示词在校验器上行为符合预期：E1–E5/E7 accepted、E6 not_applicable、E8 invalid_source_media、E9 needs_input。

## 5. M1–M8 结果（`post-fix-regression/`）

**10/10 通过**（M1 无路径→missing；M2 “这个视频”指代→missing；M3 历史路径不被读取/不选默认→missing；M4 示例路径不当输入→missing；M5 显式单路径→accepted；M6 显式多路径→accepted；M7 非法路径→invalid（非 missing）；M8 非视觉→not_applicable；V1/V2 校验器契约区分 missing/invalid）。

## 6. E9 三次稳定性结果（`e9-stability/`）

- **第一轮**（round-1，Git 历史 ef650ef）：3/3 返回 needs_input/missing_source_media、0 Qwen、0 抽帧；但 run-3 判定前执行了目录搜索（find 项目目录、ls /tmp ~/Downloads），run-1/3 加载了 visual-evidence-extractor（未执行）→ 按"继续检查根因、不降低规则"强化停止清单。
- **第二轮**（round-2）：**3/3 全部判据通过**——相同 Prompt、全新会话、0 Qwen 调用、0 视觉命令、0 搜索命令、全部返回 missing_source_media、均未加载 visual-evidence-extractor、无污染；耗时 30.9–49.4 s。

## 7. 完整 Tier-3 重跑（`baseline/` + `with-skill/`，18 个全新会话）

同一 DSH/StepFun/Qwen/媒体/Prompt/max_frames/超时；按任务交替；统一预热；同一冻结评分器。效率：baseline 总耗时 3534.4 s / 工具调用 292 / Qwen 1（可观测）；with-skill 总耗时 800.5 s / 工具调用 157 / Qwen 17；重试 0/0、失败 0/0、超时 0/0。逐任务见 `comparison.md`。

冻结评分器输出（未修改）：

| 维度 | baseline | with-skill |
| --- | --- | --- |
| security | 8/9 | 8/9 |
| correctness | 7/9 | 9/9 |
| discoverability | 5/9 | 9/9 |
| effectiveness | 6/9 | 9/9 |
| verdict | — | PARTIAL |

- with-skill 失分：E4 security（S5）——**经核实为评分器误报**（stdout 合规声明段被当作断言，见 findings §2）；
- baseline 失分：E1 correctness（错误负面结论）+discoverability、E2/E4/E5 effectiveness（无置信度字段）+discoverability、E3 security（**同为评分器误报**）+discoverability、E9 correctness（真实失败：从项目上下文找到视频并程序化分析，未返回缺参错误）；
- 任务 07 的 E9 with-skill 失败已修复：本轮 with-skill E9 正确返回缺参（30.8 s、4 工具调用、0 Qwen），correctness/discoverability/effectiveness 均 9/9。

## 8. 停止点与等待决定

按任务书第三节（评测器严重错误→不修改/单独报告/停止任务/等待用户决定）：

- 已停止：BENCHMARK.md 的 Full Re-run 结论段、四份项目文档、三个 Skill BENCHMARK 的更新、成功提交；
- 已完成并保留：修复（2 个提交）、全部回归证据、两轮稳定性复测、完整重跑 18 会话与冻结评分器输出、独立评测器缺陷报告；
- 等待用户在 `frozen-evaluator-findings.md` §5 的 A/B/C 中做决定（A 接受 PARTIAL；B 允许对 stdout 补否定语境过滤后重评分不重跑；C 其他）。
