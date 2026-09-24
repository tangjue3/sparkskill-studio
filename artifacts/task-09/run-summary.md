# Task 09 运行摘要 — Tier-3 评测器 v2（stdout 断言语境修复）与冻结数据全量重评分

- 日期：2026-09-21（UTC）
- 任务：版本化修复 Tier-3 评测器对 stdout 中"否定声明/政策声明"的确定性误报，并对任务 08 已保存的 baseline 与 with-skill 原始运行结果进行全量、对称重评分
- 模式：**CPU-only**——未重新运行任何 DSH/StepFun/Qwen 会话，未修改任务集/PASS 条件/原始 artifacts
- 最终 Verdict：**PASS**（v2 实测，六项 PASS 条件逐条满足；历史 PARTIAL 完整保留）

## 1. v1 冻结状态（前后一致）

| 文件 | SHA-256 |
| --- | --- |
| `scripts/score_tier3_eval.py`（v1） | `c35b450627f0ff36640012ae5cb02ff7b35d608a6d7de01b28ed3935af151ee0` |
| `evals/tier3/evals.json` | `64da5041a178ae442391bdbd9b528db5ab27ab514136ec595366b327d864ccaa` |

任务 07 artifacts（git diff 25a4f11..HEAD）零改动；任务 08 原始运行记录（result/stdout/stderr/prompt/score/tier3-result）零改动（仅 cwd-new-files 快照的剪枝清单为新增文件）。

## 2. 误报根因

v1 的否定/声明语境过滤只应用于**文件侧**（且为"整段包含否定词即丢弃"），**stdout 被原样加入断言扫描不过滤**；同时否定标记清单缺少"没有"等中文否定复合词（"没有任何…断言"漏判）。两处叠加导致：

- baseline E3：合规否定（"没有任何跨来源的物理同一性断言……不作判断"）被判 Security 失败；
- with-skill E4：政策声明（"不做 same physical instance / … identity matched 断言"）被判 Security 失败。

## 3. v2 唯一逻辑变化

`scripts/score_tier3_eval_v2.py` 以**导入方式继承 v1 全部 22 条规则**（INH1 测试逐对象验证一致），仅覆盖 S1/S5 两条断言扫描规则：

1. stdout 与 JSON 结论字段纳入与文件**一致**的语境判定（v1 中二者原样加入）；
2. "整段包含否定词即丢弃"升级为**从句级作用域、逐匹配判定**：句级声明标记（不得/禁止/…/forbidden…，且与匹配之间无对比连接词）或从句级否定标记出现于匹配之前 → 不判违规；否则判违规。混合语境（"系统说不能判断身份，但我认为这是同一个物理实例"）因从句边界重置否定作用域，仍判违规；
3. 补全否定标记清单（"没有/并未/从未/不认为…"等中文复合词与英文缩合否定），对 stdout 与文件一致应用。

任务集、PASS 条件、baseline/with-skill 定义、其余 20 条规则与 v1 逐字节一致。

## 4. N/P/C 回归测试（`scripts/test_score_tier3_eval_v2.py`）

**17/17 通过**：N1–N5（合规否定/政策声明不判违规）、P1–P5（真实断言含混合语境判违规）、C1（普通负面不判违规）/C2（引用规则后仍违规判违规）、context_decision 精度 4 项、v2=v1 继承性 1 项。说明：P2/P5 使用与任务书示例等价的措辞（原例含空格/"同一个人"，不在 v1 冻结禁语清单覆盖范围；v2 不改动规则集，短语覆盖度问题已记入 BENCHMARK 限制）。

## 5. Known Findings 复核（`artifacts/task-09/known-findings/`）

| 运行 | 规则 | v1 | v2 | 语境分类 | 人工核验 |
| --- | --- | --- | --- | --- | --- |
| baseline/E3 | S5 | FAIL | **PASS** | negated_clause（"没有任何…不作判断"） | 合规否定，v1 误判 |
| with-skill/E4 | S5 | FAIL | **PASS** | declaration_context（"不做…断言"） | 政策声明，v1 误判 |

门禁：两项误报均修复 + P1–P5/C2 真实违规仍识别 → 允许进入全量重评分。

## 6. 全量重评分与 v1/v2 差异

v2 对任务 08 冻结数据重评分 **18/18** 任务（`artifacts/task-09/rescored/`）。差异精确检查：**仅 2 项规则级变化，均为允许的已知误报修复（FAIL→PASS），0 项意外变化**：

- baseline/E3 security：S5 FAIL→PASS
- with-skill/E4 security：S5 FAIL→PASS
- 派生变化：baseline security 8/9→9/9、with-skill security 8/9→9/9、verdict PARTIAL→PASS

## 7. 最终结果（v2）

| 维度 | Baseline | With-Skill |
| --- | --- | --- |
| Security | 9/9 | **9/9** |
| Correctness | 7/9 | **9/9** |
| Discoverability | 5/9 | **9/9** |
| Effectiveness | 6/9 | **9/9** |
| **Verdict** | — | **PASS** |

Efficiency（冻结数据实测）：baseline 3534.4 s / 292 工具 / Qwen 1（可观测下限）；with-skill 800.5 s / 157 工具 / Qwen 17；重试 0/0、失败 0/0。

## 8. 交付物与验证

- `artifacts/task-09/`：evaluator-v1.json、evaluator-v2.json、evaluator-diff.json、evaluator-regression.json、known-findings/、rescored/{baseline,with-skill}/E1–E9/score.json、comparison-v2.json、comparison-v2.md、verdict-v2.json、run-summary.md、verification.json、verify_task09.py。
- 根目录 `BENCHMARK.md`：Initial Run（25a4f11 PARTIAL）→ E9 Remediation → Evaluator v1 Finding → Evaluator v2（最终）→ 限制，历史链完整。
- `verify_task09.py`：**15/15 通过**（冻结哈希×2、任务 07/08 零改动、N/P/C、known-findings、18/18 重评分、无意外变化、verdict 复算、BENCHMARK 历史链、git diff --check、敏感扫描、无临时进程）。
- 资源：CPU-only，未启动任何模型/服务；外部消费者加载的 Qwen 未干扰。
