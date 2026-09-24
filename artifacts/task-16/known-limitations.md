# 任务 16 已知限制（必须与结果一起阅读）

1. **技术 fixture 不是真实行业素材**：5 段合成视频（640×360@24fps、8s、灰底红色正方形）只验证方法论的规则正确性与策略行为；**结果不得外推为真实仓储/园区准确率**。若 Qwen 不能可靠理解某个 fixture，已在 `comparison.json` 逐场景如实记录（未修改标签迁就模型输出）。
2. **小样本 + 单次运行**：每个 fixture 每臂一次运行；Qwen 推理与 Agent 行为非确定性，换一次运行数值可能不同；不构成统计显著性。
3. **adaptive 的初始覆盖盲区**：`initial_coverage_samples` 决定初始网格密度；窄于初始网格的“不确定区间”（如低对比度带）可能完全不触发细化——这是策略的真实边界，对照数据中如实呈现（不调参到只剩漂亮样本）。
4. **边界精度受帧率限制**：细化中点映射到真实帧序号；区间窄于单帧间隔（1/fps）时无法再产出新采样点（`refinement_converged_no_new_sample`），剩余不确定性如实报告。
5. **首末 confirmed 不是真实进入/离开时间**：时序结论是“采样证据支持的时序结论”（temporal presence evidence / evidence-supported state transition / boundary uncertainty），不是连续跟踪真值；两个 confirmed 采样点之间不断言连续存在。
6. **预算耗尽不是成功**：`budget_exhausted=true` 只表示预算用尽；报告必须与未耗尽场景区分。
7. **多来源共享预算**：`max_model_calls` 是整个任务的硬上限；单个来源可能耗尽预算导致后续来源无采样（如实记录，不用其他来源冒充）。
8. **未做事项**：跨摄像头身份/实例关联、ReID、目标跟踪、实时跟踪（明确非目标）；真实 ground-truth 逐样本时间准确率评分（需要用户 holdout 标注，未实现）；Evidence Workbench 接入（留给后续独立任务，本任务未修改工作台）。
9. **Qwen 对合成 fixture 的理解边界**：任务 16 前探针（真实 Qwen 调用）确认红色正方形在清晰帧可被可靠确认（object_found=true/confidence=1.0）、缺失帧为确定性负面（object_found=false/confidence=1.0）；低对比度区间的模型行为以真实运行记录为准。
10. **环境依赖**：真实对照与 DSH 会话依赖资源窗口（MemAvailable ≥ 45 GiB、MiniMax-H3 无生成任务、无外部 Qwen 消费者）；资源门槛不满足时按任务书生成资源阻塞报告，不用伪造输出冒充。
