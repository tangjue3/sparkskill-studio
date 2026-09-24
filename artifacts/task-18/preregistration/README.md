# 任务 18 预注册（preregistration）— Coverage-Aware Adaptive Sampling v2 三臂评测

本目录在**实现开始之前**冻结任务 18 的三臂评测协议，随阶段 A 提交
（`docs: preregister coverage-aware sampling evaluation`）进入 Git 历史，
形成"评测规则先于实现"的时间顺序证据。实现开始后本目录内容不得修改。

## 文件

| 文件 | 内容 |
| --- | --- |
| `evaluation-plan.json` | 评测总计划：三臂、11 个场景、统一预算、执行顺序、replay/真实 Qwen 划分、资源门槛、评分指标、公平门、工程与算法分离 |
| `arm-configs.json` | 三个臂的完整配置（uniform / adaptive_coarse_to_fine / coverage_aware_adaptive）与预算覆盖规则 |
| `verdict-policy.json` | pairwise（复述任务 17 冻结规则）与 pack 级三臂 verdict 规则、reason codes、报告口径 |
| `fixture-manifest.json` | 11 个场景的媒体（6 段任务 18 新增 + 4 段复用任务 16 + 1 个 tight-budget 变体）、SHA-256、目标查询、Ground Truth 引用、预算与类别（由 `build_preregistration.py` 从冻结输入生成） |
| `ground-truth-manifest.json` | 11 份 Ground Truth 文件的 SHA-256 与区间摘要（任务 17 temporal-ground-truth 契约） |
| `frozen-hashes.json` | 全部预注册文件、fixture、Ground Truth、契约与设计文档的 SHA-256 冻结清单（实现前后一致性核验的依据） |

## 协议要点

- **三臂**：`uniform`（正式 baseline）vs `adaptive_coarse_to_fine`（任务 16 策略）vs
  `coverage_aware_adaptive`（任务 18 新策略）；同场景三臂统一预算（主对照 12，
  tight-budget 场景 6）；相同媒体/查询/Ground Truth/模型/超时/分类规则；
  无单侧重试、不删失败场景、不看结果改标签。
- **场景覆盖任务书十类要求**：全程存在、中途出现、中途消失、出现-消失-再次出现、
  coarse 网格间短 confirmed 事件、coarse 网格间短 uncertain 区域、两个间隔较短的事件、
  无目标/无转换、预算不足（覆盖与细化竞争）、两个相位不同但语义相同的对抗样本。
- **执行顺序**：场景按 `fixture-manifest.json` 的 `scenario_order`；场景内臂顺序固定
  uniform → adaptive → coverage；不轮换（顺序效应记为已知限制）。
- **先 replay 后真实**：deterministic replay（构造证据，零模型调用，逐字节可复算）
  先于任何真实 Qwen 运行；不得根据 replay 结果修改正式 Qwen 场景、Ground Truth 或规则。
- **评分**：任务 17 冻结评分器（`scripts/score_temporal_ground_truth.py`，零改动）
  经兼容适配层 `scripts/task18_scorer_adapter.py` 使用（仅在内存扩展策略白名单）。
- **verdict**：允许 `IMPROVEMENT` / `TRADEOFF` / `NO_IMPROVEMENT` / `INVALID_COMPARISON`；
  由冻结规则从指标计算；工程实现验收与算法 verdict 分开。
- **红线**：不声称任意短事件必检；不声称真实仓储准确率；synthetic technical fixture
  不得外推；用户 8 AI + 4 licensed public Evidence Pack 未接入前不得声称真实域效果。

## 重新生成数据文件

`fixture-manifest.json` / `ground-truth-manifest.json` / `frozen-hashes.json` 由

```bash
python3 artifacts/task-18/preregistration/build_preregistration.py
```

从冻结输入（`artifacts/task-18/fixtures/`、`artifacts/task-18/contracts/`、
`artifacts/task-16/fixtures/`）确定性重新生成；`frozen-hashes.json` 同时覆盖本目录的
人工声明文件，任何改动都会使哈希核验失败。
