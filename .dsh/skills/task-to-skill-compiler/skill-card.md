# Skill Card — task-to-skill-compiler

| 项 | 内容 |
| --- | --- |
| name | task-to-skill-compiler |
| status | minimal |
| 一句话职责 | 自然语言视觉任务 → 受控 VisualTaskSpec（DSH + StepFun 文本链路）；视觉任务第一环与媒体来源硬门；采样策略契约（uniform / adaptive_coarse_to_fine / coverage_aware_adaptive + 硬预算 + 边界精度 + 覆盖目标与覆盖储备） |
| 输入 | 自然语言任务字符串 |
| 输出 | VisualTaskSpec JSON（`schemas/visual-task-spec.schema.json`）；或缺参/拒绝契约（needs_input/missing_source_media、rejected/invalid_source_media） |
| 正向触发 | 要求对图像/视频对象做存在性判断/追踪并要求证据与拒答的任务（含用户未提供媒体路径的视觉任务——此时返回缺参契约） |
| 负向触发 | 非视觉任务；人脸/身份/年龄/关系/意图推断；生成代码或 shell；凭据相关 |
| 拒答条件 | 任务无法解析为合法 VisualTaskSpec；缺失关键参数（缺媒体 → needs_input/missing_source_media，禁止从项目文档/历史产物/目录扫描推断）；安全扫描不过（→ rejected/invalid_source_media）；非法采样策略组合（uniform 带细化/覆盖参数 / adaptive 带 coverage 专属字段或缺必填 / coverage 缺必填 / initial(+reserve)>budget / 未知策略 / 非法预算 / ≤0 边界精度或覆盖目标） |
| 安全边界 | 不生成/不执行任意代码；默认禁敏感推断；默认证据不足拒答；媒体来源必须来自当前用户请求显式提供或 Harness 明确传入 |
| 评测 | `evals/evals.json`；实测记录 `BENCHMARK.md`；项目级 Tier-3 对照评测（baseline vs with-skill）评分器：v1 冻结 + v2（`scripts/score_tier3_eval_v2.py`，stdout 断言语境修复），最终 Verdict PASS（历史 PARTIAL 保留） |
| 脚本 | `scripts/validate_task_spec.py`、`scripts/check_source_media.py`（来源前置校验）、`scripts/test_missing_media_contract.py`（M1–M8 契约测试）（纯标准库） |
| 依赖 | 无第三方依赖；模型走 DSH + StepFun step-5-preview |
| 非目标 | 不做视觉推理；不做视频处理；不冒充 NVIDIA 官方 Skill |
