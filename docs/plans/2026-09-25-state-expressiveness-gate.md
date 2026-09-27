# State Expressiveness Gate — 证据状态表达能力预注册（Task 28）

- 状态：**PREREGISTERED**（本文先于任何 Oracle 实现与任何 dev 数据读取）
- 日期：2026-09-25（UTC）
- 性质：**零模型调用**的历史 replay 实验。不改任何 Skill、schema、scorer、冻结 artifacts。
- 动机锚点：Task 19B 三臂真实域全部 NO_IMPROVEMENT，8 个真实 GT 边界 `matched=0/8`
  （全部涉及 uncertain 过渡），`overclaim_on_uncertain` 11/7/9（uniform/adaptive/coverage）。
  冻结 `direction_compatible` 只匹配 `state_transitions`，而非确定预测类别不得
  承接涉及 uncertain 的 GT 边界 → 当前契约下 0/8 是**结构必然**，不是坏运气。

## 1. 假设（两个，必须分开检验）

- **H-expression（状态模型缺陷）**：模型已产出足够信息，但现有三态契约
  （`confirmed`/`not_found`/`abstained`/`low_confidence`，其中 confirmed 与
  low_confidence 只由 `confidence >= threshold` 决定）把"看着但没把握"和
  "确信"压成了同类，导致 uncertain 过渡无法承接。
- **H-perception（感知缺陷）**：原始输出里的信息不足以表达"看不清"，
  扩展状态模型不会提升任何指标。

Task 22/25 已证明提示词与上下文校准**不解决**该问题；Task 19B 已证明采样优化**不解决**。
本实验检验唯一尚未被检验的变量：**状态模型表达力**。

## 2. 设计：三态 + 正交不确定原因（不是第四平级状态）

```text
ObservationState        decided（confirmed / not_found / uncertain）
UncertaintyReason       transition / occlusion / low_light / ambiguity /
                        insufficient_visual_evidence
```

**明确否决**把 `uncertain_transition` 做成与 `confirmed` 平级的第四类：
它是 `uncertain` 的一个**原因**，不是一种状态。状态回答"看见没有"，
原因回答"为什么没有把握"。混为一类会让 `confirmed` 的比较基数失真，
且破坏了"三态可判定类别"与"非可判定类别"的二分结构。

## 3. 三个 Oracle（必须按此定义实现，不得混用）

输入只允许：模型历史输出字段（`object_found` / `confidence` /
`abstention_reason` / `evidence_text` / `bounding_box` / `frame_status`）。

| Oracle | 允许的信息 | 禁止 |
| --- | --- | --- |
| **O0 恒等基线** | 只用现有字段复现既有 `classify_entry` 分类 | 任何新规则 |
| **O1 信息保持型（主判据）** | 以上 + confidence/abstention_reason/evidence_text 单帧启发式 | **读 GT**、跨帧邻域、读媒体 |
| **O2 GT 注入型（仅内部诊断，不进交付叙事）** | 以上 + GT 状态反推每帧最优类别 | 无（本就不可交付） |

O2 量化的是"如果模型输出里含有正确状态信息、只是被契约压掉"的上界。
**O2 的分数不得写进任何结论或 README/BENCHMARK**；它是内部诊断，
用于解释 O1 与 O2 之间的差距来源。

### 3.1 O2 的对称护栏（否则数字不可解释）

允许 O2 用 GT 反推，会系统性高估。因此必须**同时报告**四个数：

1. `o2_matched` — O2 的 matched_boundary
2. `o2_boundaries_gt_driven` — 其中仅由"读 GT"才能得到的边界数
3. `o2_boundaries_heuristic_reachable` — 仅凭单帧启发式（不读 GT）即可得到的边界数
4. `o1_matched` — 主判据

若 `o2_boundaries_heuristic_reachable == o1_matched`，则扩展状态模型确实拿走了
全部可拿收益；只报 `o2_matched` 而不报拆分会构成**回测幻觉**，
违反本项目 "不得用带答案数据讲质量故事" 的既有红线（Task 26B 口径）。

## 4. Provenance：为什么必须新建评分器而不是复用冻结 scorer 的入口

冻结 scorer 的 G7 要求
`actual_model_calls == len(fresh_call decisions) == len(timeline)`。
诚实标注 256 个历史点为 `archived_call` 会同时违反两个等式
（Task 21 `REPLAY_UNSCORABLE`，54/54 候选文档被拒）；唯一"通过"方式是
把已归档调用冒充 `fresh_call`，属禁止的伪造 provenance。

因此：**新评分器 `scripts/score_state_replay.py` 显式声明
`provenance_nature=archived_replay`，并把 G7 替换为 `G7r-replay-provenance`**
（要求 `archived_call` 数 == 时间线条目数 == 评分行数，且**禁止**出现
`fresh_call` 标注）。这与 Task 20 配对评分器"新建而非改冻结评分器"的先例一致。

冻结 `scripts/score_temporal_ground_truth.py` 零改动；等价性由测试逐行断言背书。

## 5. 数据与输入隔离

- 输入：Task 19B / Task 22 已冻结的模型原始输出（`internal-artifact`，
  公开仓库中不存在时测试走 `NOT_RUN`，不伪报 PASS）。
- e2e 等价性数据源：`artifacts/task-17/fixtures/`（公开，含真实 `media.mp4`），
  直接用冻结 scorer 的真实 CLI 运行并与 O0 对齐。
- GT 只允许进入 O2 的**显式标注路径**；O1 代码路径不得引用 GT 对象。
  由测试静态断言 + fixture 隔离保证，不依赖自觉。

## 6. 判据（预注册，先于看到任何结果）

### 6.1 O0 前置门（不通过则整轮 `INVALID`）

- O0 在旧规则下必须与历史七类账**逐点一致**（`overclaim_on_uncertain` 41、
  边界 matched 口径不变）。
- O0 与冻结 scorer 在 `artifacts/task-17/fixtures` 上逐点 `prediction_class` 零 mismatch。

### 6.2 主分母（FINAL 修订，R1）

**Primary denominator = 8 个 unique GT boundary times**，不是 24 个手臂暴露。

理由：三臂是同一批 GT 边界的**重复暴露**，不是 24 个独立边界。拿 24 当分母会把
"同一个边界被三臂各采到一次"计成三次成功，从而虚高恢复率。

因此结果必须同时写两行，且顺序固定：

```text
Unique-boundary recovery: x / 8        ← 主判据（G1 只看这个）
Arm-level boundary matches: y / 24      ← secondary diagnostic（不得单独引用）
```

### 6.3 主判据 O1（信息保持型）

对旧规则报告 Δ：

- `matched_unique_boundaries`（主）
- `arm_level_boundary_matches`（secondary）
- `overclaim_on_uncertain`
- `appropriate_abstention`
- `covered_confirmed_events` / `missed_confirmed_events`
- `correct_decisive`，分 **total** 与 **licensed-public** 两层

### 6.4 判据表（FINAL）

Hard integrity gates（任一失败 → 整轮 `INVALID`，不得解读为负面结论）：

| 门 | 要求 |
| --- | --- |
| H1 | O0 与冻结历史端到端等价 PASS（§6.1） |
| H2 | `archived_replay` 中 `fresh_call` = 0 |
| H3 | provenance / count / hash / mapping 自洽 |
| H4 | O1 `confirmed ⟹ legacy confirmed`（单方收窄硬保证） |
| **H5** | **Failure preservation**：legacy `failed` ⟹ O1 `failed`；`backend_not_called` / `backend_call_failed` / `contract_rejected` / `extraction_failed` **不得转换为 semantic `uncertain`** |

### H5 的理由（为什么 failed 不是 uncertain）

```text
abstained → uncertain(reason=occlusion/…)      允许（状态表达收窄）
confirmed / not_found → uncertain               允许（状态表达收窄）
legacy failed → failed                          必须（执行不完整，不是视觉不确定）
```

`failed` 表示**执行不完整**（backend 未调用 / 调用失败 / 契约拒绝），
不是"画面看不清"。若把它重解释为 `uncertain`，一次 backend 失败就能
在时间线上制造一个假的 state transition，从而虚高边界恢复率——
这与 GroundingDINO 那类"错误质疑"是同一条作弊路径。

因此 **O2 的 `heuristic_reachable` 也必须排除执行失败点**，
并把排除数量显式报告为 `excluded_execution_failures`。

注意判据分层：legacy `classify_entry` 只认 `frame_status != "analyzed"`，
`backend_*` 子类型是 O1 侧的**额外防线**（legacy 不识别）；
后者不得反向要求 legacy 也判 failed。

Utility gates：

| 门 | 要求 | 失败含义 |
| --- | --- | --- |
| **G1** | `matched_unique_boundaries` 至少 **+2**（旧值 0/8） | `STOP_STATE_MODEL` |
| **G2** | `correct_decisive` **total** 降幅 ≤ 4 | STOP（对齐 Task 20 G3 总量容忍） |
| **G3** | `correct_decisive` **licensed-public 分层**降幅 ≤ **1** | STOP（Task 20 原始 G3 就是这条；只留总量门等于比历史 G3 放宽） |
| **G4** | 不得通过放宽 confirmed 门获得收益 | 由 H4 硬保证 |
| **G5** | O2 必须单独报告 `total_oracle_gain` / `heuristic_reachable_gain` / `boundary_times` | 不得把 total Oracle 当可实现收益 |

G1 的三值解释（primary = unique boundaries）：

```text
0 → 0  : STOP
0 → 1  : STOP（单个边界很可能只是启发式碰巧命中，不构成系统级证据）
0 → ≥2 : 值得继续状态模型路线
```

### 6.5 硬停止门（任一命中即停止，不得"再调一版"）

- 为拿到更好 O1 数字而引入**读 GT** 的规则 → `INVALID`，本轮作废
- G1 / G2 / G3 任一失败 → 停止状态模型路线；**不得发明 O1.1、O1.2 去追 dev**
- 第二轮尝试仍未过判据表 → 停止，**不迭代第三个候选**（Task 20/22/25 一律纪律）

### 6.6 修订记录（保留，不得删除）

- **R1（2026-09-25，冻结前最后一次修订）**：
  1. G3 补 **licensed-public 分层降幅 ≤1**。原稿只写 total ≤4，比 Task 20
     原始 G3 的两层门更宽松（Task 20 当时 total −5 且 licensed-public −2 双重失败）。
  2. primary denominator 由"边界 matched"改为 **8 unique GT boundary times**；
     `arm-level boundary matches (y/24)` 降为 secondary diagnostic。
  3. G1 门由模糊的"≥6/8 或 ≤旧+1"改为唯一可执行的 **+2** 阈值，并给出
     0/1/≥2 三值解释。
  4. 硬完整性门（H1–H4）与效用门（G1–G5）分离：H 失败是口径失效，
     G 失败才是负面结论——两者不得混读。
- **R2（2026-09-25，见数前最后一次修订）**：补 **H5 Failure preservation**。
  legacy `failed` ⟹ O1 `failed`；`backend_not_called` / `backend_call_failed` /
  `contract_rejected` / `extraction_failed` 不得转换为 semantic `uncertain`。
  动机：failed 是**执行不完整**而非视觉不确定；把它洗成 uncertain 会让一次
  backend 失败在时间线上制造假 transition，从而虚高边界恢复率——
  与 GroundingDINO"错误质疑"属同一条作弊路径。O2 的 heuristic_reachable
  同步排除执行失败点，并报告 `excluded_execution_failures`。
  实现侧同时发现：legacy `classify_entry` 不识别 `backend_*` 子类型，
  故子类型作为 O1 侧额外防线（不得反向要求 legacy 判 failed）。

### 6.7 判决规则（FINAL，见数后不得修改）

结果出来只读四个数字 + 一个 secondary：

```text
O1 unique_boundary_recovery:      x / 8        ← 主判据（G1 阈值 +2）
O1 correct_decisive total:        Δ?
O1 correct_decisive licensed:     Δ?           ← G3 分层 ≤1
O2 heuristic_reachable:           y / 8
arm_level_boundary_matches:       z / 24       ← secondary diagnostic
```

| 情形 | 结论 |
| --- | --- |
| `O1 ≥ 2/8` 且 `correct_decisive` 损失在 G2/G3 内 | 状态模型路线**值得进入下一阶段** |
| `O1 ≤ 1/8`（即使 `O2 heuristic` 很高） | **`STOP_STATE_MODEL`**。理论空间大不等于当前 resolver 达标；**不得**据此继续优化 resolver |
| `O1 = O2 heuristic` | 最干净的结果：deterministic resolver 已吃满 archived evidence 的表达空间 |
| 任一 H 门失败 | 整轮 `INVALID`（口径失效），**不得**解读为负面结论 |

**看到数字以后不再改 resolver**（不发明 O1.1 / O1.2 追 dev）。这条与 Task 20/22/25
"未过门不迭代第二个候选"的停止纪律一致。

### 6.8 输入不可用时的状态（不是失败）

当 internal frozen artifacts 不可读时，唯一合法状态是：

```text
INPUT_NOT_AVAILABLE
```

**禁止**的补救方式（全部违反媒体 provenance 原则）：

- 从 README / run-summary 摘要反推 predictions；
- 重建"近似 predictions"或合成替代数据；
- 重新调用模型补数据；
- `find` / 全盘 `glob` 寻找 dev 产物；
- 从旧 summary 猜路径。

对应 Gate 的最终状态词：

```text
STATE_EXPRESSIVENESS_GATE_FROZEN_INPUT_BLOCKED
```

含义：Gate 已冻结、实现已验证、正式 dev replay 因 internal frozen artifacts
不在当前工作区而尚未执行。这既不是失败，也不是"待调参"。

## 7. 与其他工作的关系（不串行、不阻塞）

- O1 是纯离线 CPU 实验，与 8B/27B deployment frontier（GPU/Ollama）**资源不冲突**，
  两者可并行；但 §6 预注册必须先冻结，保证不被 8B 结果污染。
- GroundingDINO-tiny + 当前复合查询 + challenge fusion 已知 `NO_GO`
  （35.7% 误拦，颜色与组合关系不判别）。它**不得**进入 capability catalog；
  换个能处理属性/关系组合的 grounding 模型须另起**新的 preregistered experiment**。
- holdout 最后开启：schema、模型选择、recipe 全部冻结后才可一次性开启。

## 8. 交付物

- `scripts/state_resolver.py` — 三态 + UncertaintyReason 解析器（`--audit` 自检）
- `scripts/score_state_replay.py` — replay 评分器（`provenance_nature=archived_replay`）
- `scripts/test_state_expressiveness_gate.py` — O0 等价性、O1 护栏、O2 拆分的测试
- `artifacts/task-28/run-summary.md` — 结果（结果阶段另写，不预填）

## 9. 本阶段明确不做

不实现 O1 背后的模型改动；不改 `analyze_image.py` 生产模板；不改三态 evidence schema；
不触碰 holdout；不做任何模型调用；不据此修改 README/BENCHMARK 的任何既有数字。
