# 视频证据参考（visual-evidence-extractor 视频链路产出物）

由 `scripts/extract_frames.py`（抽帧）与 `scripts/trace_video.py`（逐帧分析 + 聚合）产出，
报告由 evidence-report-generator 的 `scripts/generate_report.py --mode video` 生成。
字段分两类：**真实运行字段**（必须来自真实抽取的帧或真实模型输出）与**规则计算字段**（聚合/统计）。

## 1. 帧索引（extract_frames.py 产出）

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `source_video` | string | 输入视频绝对路径（只读，不修改原视频） |
| `metadata` | object | `fps`/`frame_count`/`width`/`height`/`duration_ms`；任一不可信（≤0）即拒绝抽帧 |
| `sampling` | object | `interval_ms`/`max_frames`/`start_ms`/`end_ms`/`strategy`/`planned_sample_times_ms` |
| `frames[]` | array | `{index, frame_number, timestamp_ms, frame_path}`；时间戳由真实帧序号推导，**严格单调递增**；帧文件稳定命名 `<前缀>_f<序号>_t<毫秒>ms.png` |

采样策略：优先按时间间隔网格；网格点数超过 `max_frames` 时在 `[start_ms, end_ms]` 内均匀取样。
顺序解码（不随机 seek），保证 H.264 下时间戳准确。

## 2. 视频证据时间线（trace_video.py 产出，timeline.json）

顶层：`source_video`、`duration_ms`、`sampled_frames`、`target_query`、`timeline[]`、
`state_changes[]`、`summary{}`、`video_metadata`、`sampling`、`backend`、`warnings`。

`timeline[]` 每项（对应一个真实抽取的帧，禁止凭空生成）：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `timestamp_ms` | number | 帧时间戳（来自帧索引） |
| `frame_path` | string | 帧图片路径，结论必须可回溯到该文件 |
| `object_found` | boolean | 模型判断；无法确认必须 false |
| `description` | string | 画面客观描述（模型返回，透传不修补） |
| `bounding_box` | [number×4] \| null | 归一化 0–1；不可靠必须 null；**禁止编造、禁止把整幅图片框成目标框**（覆盖 ≥95% 画面时记入 gaps 标记定位不可靠） |
| `confidence` | number | 0–1 |
| `evidence_text` | string | 客观视觉依据 |
| `abstention_reason` | string \| null | object_found=false 时必填原因或确定性负面用 null；**不允许空字符串** |
| `frame_status` | enum | `analyzed`（真实模型输出）/ `failed`（后端未调用或调用失败，原因写入 abstention_reason） |
| `evidence_sufficient` | boolean | object_found=true 且 confidence ≥ 阈值 |
| `gaps` | array | 证据缺口（透传自 analyze_image.py + 定位不可靠标记） |

`summary{}`：`first_confirmed_timestamp_ms`、`last_confirmed_timestamp_ms`、
`confirmed_frame_count`、`not_found_frame_count`、`abstained_frame_count`、
`low_confidence_frame_count`、`failed_frame_count`、`analyzed_frame_count`、
`overall_status`（`completed` \| `abstained` \| `failed`）。

## 3. 聚合规则（第一版，可解释）

1. **按时间戳排序**；时间戳未严格单调递增 → 聚合失败（拒绝输出）。
2. **删除完全重复的结果**：连续帧的 `object_found/description/bounding_box/confidence/
   evidence_text/abstention_reason/frame_status` 完全相同时，只保留该状态段首帧，
   记入 `state_changes`（`A→B→A` 属于关键状态变化，保留）。
3. **保留每个关键状态变化**：`state_changes` 是逐帧独立状态的序列，
   **不声明跨帧同一性**，不做身份跟踪、不做跨镜头关联、不做没有证据的路径推断。
4. **首次/最后确认与确认帧数量**：confirmed = analyzed 且 object_found=true 且
   evidence_sufficient=true。
5. **严格区分**：
   - `not_found`：object_found=false 且 abstention_reason=null（确定性负面）；
   - `abstained`：object_found=false 且 abstention_reason 非空（无法确认/拒答）；
   - `failed`：帧未获得任何视觉证据（后端未调用或调用失败）；
   - `low_confidence`：object_found=true 但置信度不足。
6. **整体状态**：无任何 analyzed 帧 → `failed`；有 confirmed → `completed`；
   无 confirmed 但有 abstained/low_confidence → `abstained`；全部 not_found →
   `completed`（负面结论也是完成态，但结论必须是负面表述）。

## 4. 资源守卫（统一内存红线）

- 调用视觉模型前读取 `/proc/meminfo` 的 `MemAvailable`；低于阈值（默认 40 GiB，
  Qwen3.8-27B 加载约需 34.6 GB）时**不加载模型**，全部帧标记 `failed` 并记录真实原因，
  整体状态 `failed`；
- 不停止 MiniMax-H3、不强行加载导致 OOM；不用伪造输出冒充真实视觉结果；
- `--allow-low-memory` 可覆盖守卫（仅在确认资源窗口时使用）；
- Ollama 探测只用 `GET /api/tags`（不触发模型加载）。

## 5. 视频报告（generate_report.py --mode video 产出）

必填：`source_video`、`duration_ms`、`sampled_frames`、`target_query`、
`timeline[]`、`summary{}`、`status`、`conclusion`、`abstention_reason`、`warnings`。

- `status` 由报告引擎按帧条目**独立复算**，并与 `timeline.summary.overall_status`
  交叉校验；不一致时以复算为准并记入 warnings（两套实现互检）；
- `conclusion` 只能由 timeline 字段组成，不得添加输入中不存在的事实；
- 没有确认帧时不得声称目标存在；`failed` 时不作任何存在性断言。

## 6. 安全边界

- 不推断人物身份、年龄、国籍、关系或意图（提示词注入 forbidden_inferences）；
- 不做人脸识别；不做跨镜头身份追踪；
- 不实现实时多摄像头；
- OpenCV 仅作底层抽帧工具（读元数据/抽帧/存图），绝不是项目核心创新或卖点；
- 视频分析失败时：该帧/该视频标记 failed 并说明原因，不影响其他输入，不猜测性放行。
