# 任务 16 会话摘要：红色正方形 · 自适应粗到细采样时序证据

> **本会话分析的输入是合成技术 fixture（synthetic technical fixture），不是真实行业视频。**
> 所有结论仅对该 fixture 的采样证据成立，不得外推为真实行业素材结论。

## 任务与配置

- **目标**：红色正方形（object_trace）
- **输入媒体**：`artifacts/task-16/fixtures/videos/fixture-reappear.mp4`
  （用户在当前请求中显式提供；`check_source_media.py` 校验 `source_media_provenance=user_provided`）
- **视频元数据**：640×360，24 fps，192 帧，时长 8000 ms
- **采样策略**：`adaptive_coarse_to_fine`
  - 硬性视觉调用预算 `max_model_calls=12`
  - 初始覆盖 `initial_coverage_samples=4`
  - 目标时间边界精度 `target_boundary_precision_ms=500`
  - 最大细化轮数 `max_refinement_rounds=6`
  - 细化触发器：state_change / abstained / low_confidence / failed（全开）
- **视觉后端**：本地 Ollama Qwen Vision（`modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest`），逐帧真实调用
- **资源守卫**：MemAvailable 59.01 GiB ≥ 40 GiB 阈值，未阻塞

## 流水线执行记录

1. **媒体来源前置硬门**（task-to-skill-compiler 第 0 步）：`check_source_media.py` → `status=accepted`，`tool_calls_allowed=true`。
2. **VisualTaskSpec 生成**：`visual-task-spec.json`（含 `sampling_strategy` 字段）。
3. **Schema 校验**：`validate_task_spec.py` → `RESULT: VALID`；来源反推断校验 `spec_source_media_check=user_provided`。
4. **自适应证据链**（visual-evidence-extractor）：`trace_temporal.py` 真实运行，4 次初始覆盖 + 8 次细化（3 轮），共 **12 次真实 Qwen Vision 调用**，总耗时约 218.5 s。
5. **最终报告**（evidence-report-generator）：`generate_report.py --mode temporal` → `final-report.json`，独立复算与上游一致。

## 采样 provenance 要点

- 实际模型调用 **12/12**，预算耗尽（`budget_exhausted=true`），停止原因 `budget_exhausted`；
- 无重复调用、无资源阻塞；每次决策的时间戳/阶段/触发区间/预算快照见 `temporal-evidence.json` 的 `sampling_provenance.decisions`（12 条，`cache_status` 全部为 `fresh_call`）。

## 时序证据结论（temporal evidence）

- 五类计数：**confirmed 6 / not_found 6 / abstained 0 / low_confidence 0 / failed 0**（互不折算）。
- 首个 confirmed **采样观察**时间 0.0 ms；最后 confirmed 采样观察时间 5958.333 ms（不等于真实进入/离开时间）。
- 3 个证据支持的状态转换（边界为左右相邻采样点范围）：
  1. confirmed → not_found：[1666.667, 2000.0] ms，不确定宽度 333.333 ms；
  2. not_found → confirmed：[3666.667, 4000.0] ms，不确定宽度 333.333 ms；
  3. confirmed → not_found：[5958.333, 6625.0] ms，不确定宽度 **666.667 ms**。
- 目标边界精度 500 ms：**未达到**（第 3 个边界因预算耗尽未能继续细化），残存不确定性 666.667 ms。
- 证据支持片段仅覆盖已采样点（0–1666.667 confirmed；2000–3666.667 not_found；4000–5958.333 confirmed；6625–7958.333 not_found），不断言片段内未采样时间的连续事实。

## 语义红线遵守声明

- 这是**采样证据支持的时序结论，不是连续跟踪真值**；两个 confirmed 采样点之间未断言目标连续存在。
- abstained / low_confidence / failed 独立计数，未折算为 not_found（本例均为 0）。
- 不做跨帧身份一致性、不做跨摄像头实例关联、不输出物体运动路径；不是 ReID、不是目标跟踪器、不是实时跟踪。
- 全部 12 条时间线证据 `evidence_nature=real_model_output`；`input_nature=technical_fixture`。

## 产物清单（本目录）

| 文件 | 说明 |
| --- | --- |
| `visual-task-spec.json` | 合法 VisualTaskSpec（含 sampling_strategy，已过 Schema 校验） |
| `temporal-evidence.json` | 时序证据文档：timeline + summary + sampling_provenance + temporal_evidence |
| `final-report.json` | 最终报告（--mode temporal，含语义红线声明） |
| `frames/` | 12 个真实抽取的关键帧（每次调用对应一帧） |
| `raw/` | 12 份模型原始返回存档（审计用） |
| `request.txt` | 本次用户请求文本（来源校验输入） |
