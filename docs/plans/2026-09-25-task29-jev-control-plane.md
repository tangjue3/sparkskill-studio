# Task 29 — Jev Control-Plane Gate 预注册（Optional Semantic Control Plane）

- 状态：**PREREGISTERED_BLOCKED_ON_TASK28**（本文先于任何 Jev 调用；开工条件见 §0）
- 日期：2026-09-25（UTC）
- 性质：**shadow-mode 同期同状态配对实验**。Jev 只观测不控制，不拥有最终事实判定权。

## 0. 开工条件（硬门，任一不满足不得写实现/调用）

```text
C1  Task 28（State Expressiveness Gate）已出判决，且 State schema 已定版
C2  internal-only 输入已通过 scripts/verify_internal_inputs.py 校验
C3  Jev API key 已由用户配置（不在本仓库、不入 Git）
C4  本文档 hash 已冻结，且冻结早于第一次 Jev 调用
```

**当前状态：C1 未满足**（Task 28 = `STATE_EXPRESSIVENESS_GATE_FROZEN_INPUT_BLOCKED`，
零 Oracle 数字）。因此本任务**不得开工**，本文档只锁定设计与判据。

原因：Task 29 的 A 组 baseline 就是"现有 deterministic policy"的逐帧状态，
而那些状态正是 Task 28 正在检验的对象。若 Task 28 未出判决，A 组就是**未验证的
baseline**——用它做对照会把两个未决变量混在一个实验里。

## 1. Jev 的定位（不是第四个视觉模型）

```text
StepFun  = Planner（慢思考、文本任务理解与规划）
Jev     = Fast typed decision / control plane（路由、风险、升级判断）
DGX + Qwen = Local perception（视觉判断，媒体不离开设备）
Skills  = Execution capabilities
确定性规则 = Final safety / integrity boundary（最终事实判定权）
```

Jev **不得**拥有最终事实判定权。它的输入是**脱敏结构化状态**，不是媒体。

## 2. 权限最小化契约（硬约束）

允许传给 Jev 的字段（聚合、不可反推媒体）：

```json
{
  "task_type": "temporal_presence",
  "target_complexity": "attribute_relation | category_only | relation_only",
  "sampled_frames": 8,
  "class_counts": {"confirmed": 4, "not_found": 1, "abstained": 3, "failed": 0},
  "mean_confidence": 0.71,
  "resource_budget": "small | medium | large"
}
```

**明确禁止**传出（任一出现即违反契约，判 `INVALID`）：

| 禁止字段 | 原因 |
| --- | --- |
| `timestamp_ms` / 任何时间戳 | 可近似还原媒体时间结构 |
| `max_sampling_gap_ms` / `sampling_strategy` 参数 | 暴露项目方法论资产 |
| `frame_path` / `frame_sha256` / `media_sha256` | 直接指向媒体 |
| `target_query` 原文 / 目标描述词 | 媒体内容 |
| `bounding_box` | 媒体空间信息 |
| `frame_index` / `sample_index` | 采样位置 |

合同判据由测试静态断言：构造含禁止字段的 payload 必须被拒绝。

## 3. 决策集（类型化，与 Jev 的 yes/no / Choice / Score 对齐）

```text
Q1 Choice:   route = 8B | 27B | human_review
Q2 Bool:     sufficient_for_auto_conclusion
Q3 Score:    risk = low | medium | high
Q4 Bool:     worth_extra_expensive_call
```

Jev 一次并行返回上述决策与概率。**阈值留给代码，不交给 Jev**：

```text
P(human_review) >= 0.8        → ESCALATE_HUMAN
0.4 <= P(human_review) < 0.8  → ABSTAIN
P(human_review) < 0.4         → 进入确定性 evidence gate
```

## 4. Shadow-mode 设计（同期同状态配对）

复刻 Task 20/22/25 的同期同帧配对范式，唯一变量为"决策来源"：

```text
冻结状态帧（来自 Task 28 定版 State schema）
   ├── A: 现有 deterministic policy  ─┐
   └── B: Jev typed decision        ─┴→ 同期配对评分
```

- **A 组不变**：deterministic policy 逐字节复用，不得因 Jev 结果调整；
- **B 组只观测**：Jev 决策不真正控制系统，不触发任何视觉调用；
- 顺序轮换（A 先/B 先各半），无单侧重试，失败保留；
- 零新增视觉调用（这是控制面比较，不是感知比较）。

## 5. 指标（预注册，先于看到任何结果）

| 指标 | 定义 | 角色 |
| --- | --- | --- |
| `route_accuracy` | Jev 路由与冻结最优路由一致的比例 | 效用 |
| **`false_auto_accept`** | A 拒答/uncertain 而 Jev 自动接受的比例 | **G1 主门** |
| `false_human_escalation` | A 可直接判而 Jev 升级人工的比例 | G2 |
| `27B_escalation_accuracy` | 升级 27B 的判断是否必要 | G3 |
| `latency_p50/p95` | Jev 单次决策耗时 | G4 |
| `cost_per_decision` | 估算成本 | 参考 |
| `decision_stability` | 同状态重复查询的决策一致率 | G5 |

## 6. 判据表

Hard integrity（任一失败 → 整轮 `INVALID`）：

| 门 | 要求 |
| --- | --- |
| H1 | payload 不含 §2 禁止字段（静态 + 运行时双重断言） |
| H2 | Jev 未参与任何最终事实判定（确定性规则在冲突时胜） |
| H3 | **G0 fallback 一致性**：JEV_ENABLED=false 与 Jev 失败降级的**决策输出**（`decision` + `action`）一致；两者的 `reason` 诊断字符串允许不同（可观测性 ≠ 行为一致性） |
| H4 | 零新增视觉调用（shadow mode 未触发模型） |

Utility：

| 门 | 要求 | 失败含义 |
| --- | --- | --- |
| **G1** | `false_auto_accept` **不增加**（相对 A 组） | 停止 Jev 控制路线 |
| **G2** | `route_accuracy` ≥ A 组 + 至少一项严格更好 | NO_IMPROVEMENT |
| **G3** | `false_human_escalation` 不增加 | 停止 |
| **G4** | `latency_p95` 达标（预注册具体阈值，见数前冻结） | 停止 |
| **G5** | `decision_stability` ≥ 阈值 | 停止 |

## 7. 降级与可用性（Jev 是在线服务）

```text
JEV_ENABLED=false            → 必须仍能跑通完整 demo（不得 requiring key）
Jev HTTP 失败 / 超时          → 单次降级 deterministic，不重试、不阻塞 pipeline
Jev 返回非法 schema           → 丢弃该次决策，fallback
Jev 宕机                     → deterministic policy 接管，pipeline 不中断
```

架构命名必须是 **Optional Semantic Control Plane**，不是核心依赖。
媒体数据永不离开设备；只有脱敏聚合状态出网。

## 8. 明确不做

- 不让 Jev 读图片/视频/帧；
- 不让 Jev 生成代码或 Skill；
- 不用 Jev 替代确定性 evidence gate；
- 不在 Task 28 判决前开工；
- 不把 Jev 输出写入任何冻结 artifacts；
- 不触碰 holdout。

## 9. 与其他任务的关系

- **Task 28 先前**：Task 29 的 A 组 baseline 依赖 Task 28 定版的 State schema；
  Task 28 未出判决则 Task 29 不得开工（§0）。
- **8B/27B/Jev Router 三臂**：可作为 Task 29 之后的 Task 30，但**必须**额外报告
  `overclaim_on_uncertain_frames` 与 `missed_uncertain_frames`——否则"少调 40% 27B"
  可能只是少看到了本该拒答的帧（Task 19B 已证 27B 的错误集中在 uncertain 帧）。
- GroundingDINO 复活条件仍适用：能验证颜色/关系的检测器须另起 preregistered experiment。

## 10. 交付物（开工后才写）

- `docs/plans/2026-09-25-task29-jev-control-plane.md`（本文）
- Jev 客户端（官方默认端点、key 不入 Git、offline 契约测试）
- payload 权限最小化过滤器 + 禁止字段测试
- `--oracle` 风格的 A/B 配对评分器（shadow mode）
- `artifacts/task-29/run-summary.md`（结果阶段）
