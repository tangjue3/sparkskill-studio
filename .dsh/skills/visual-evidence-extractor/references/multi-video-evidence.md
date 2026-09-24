# 多段视频统一证据时间线参考（visual-evidence-extractor · 任务 06）

由 `scripts/trace_multi_video.py` 产出，报告由 evidence-report-generator 的
`scripts/generate_report.py --mode multi-video`（或 auto 判别）生成。
本参考定义多媒体 VisualTaskSpec 的 `source_media` 契约、每来源时间线、全局时间线、
跨视频语义边界与像素坐标受控归一化规则。

## 1. 多媒体 VisualTaskSpec（source_media 两种合法形态）

`source_media` 保持向后兼容：

- **字符串**（旧版单媒体任务，任务 03/04/05 规格继续有效）：单个本地路径；
  多视频执行器将其包装为单一来源（`source_id="media-0"`，`time_offset_ms=0`）。
- **来源对象数组**（多段视频，任务 06）：

```json
"source_media": [
  {"source_id": "video-a", "path": "/abs/path/a.mp4", "location": "scene-a", "time_offset_ms": 0},
  {"source_id": "video-b", "path": "/abs/path/b.mp4", "location": "scene-b", "time_offset_ms": 5000}
]
```

| 字段 | 规则 |
| --- | --- |
| `source_id` | 任务内唯一；kebab/snake 安全字符；重复即拒绝 |
| `path` | 本地媒体路径；经安全校验（拒绝 shell 元字符/控制字符、凭据样式标记、系统敏感目录、路径穿越、未授权根目录） |
| `location` | 可选场景标注（如 `scene-a`）；不得包含身份等敏感推断 |
| `time_offset_ms` | 可选，非负数，默认 0；用于全局排序时间计算 |

授权媒体根目录：项目根（最近的 `.git` 祖先）、`<内部测试媒体目录>/outputs`
（本机既有真实测试媒体目录），可用环境变量 `SPARKSKILL_AUTHORIZED_MEDIA_ROOTS`
以 `os.pathsep` 分隔扩展（受控扩展，默认不放宽）。

## 2. 每来源时间线（per-source/<source_id>-timeline.json）

每个来源独立调用 `trace_video.trace()`（任务 04 单段视频能力**原样复用**，
未重写视觉提示词或视频处理逻辑），字段与 `video-evidence.md` 第 2 节完全一致：
`source_video`、`duration_ms`、`sampled_frames`、`target_query`、`timeline[]`、
`state_changes[]`、`summary{}`（首末确认、确认帧数、四态计数、overall_status）。
**原视频时间戳保持不变**（`timestamp_ms` 仍为该视频内的时间）。

## 3. 全局时间线（global-timeline.json）

顶层：`schema_version`（1.2.0）、`task_id`、`target_query`、`sources[]`、
`global_timeline[]`、`global_summary{}`、`semantic_limitations{}`、`backend`、`warnings`。

`sources[]` 每项：`source_id`、`path`、`location`、`time_offset_ms`、`duration_ms`、
`sampled_frames`、`timeline_path`、`keyframes_dir`、`summary{}`、`warnings`、
`resource_blocked`。

`global_timeline[]` 每项（每个条目必须可回溯到来源视频与关键帧）：

| 字段 | 规则 |
| --- | --- |
| `global_timestamp_ms` | 全局排序时间 = 原视频 `timestamp_ms` + 来源 `time_offset_ms` |
| `source_id` / `source_path` / `source_location` / `source_time_offset_ms` | 来源溯源信息 |
| `timestamp_ms` | **原视频时间戳**（未经偏移修改） |
| `frame_path` | 关键帧路径，结论可回溯到该文件 |
| 其余字段 | 与单视频时间线条目一致（`object_found`/`description`/`bounding_box`/`confidence`/`evidence_text`/`abstention_reason`/`frame_status`/`evidence_sufficient`/`gaps`/`warnings`/归一化字段） |

排序规则：按 `(global_timestamp_ms, source_id)` 升序；**允许不同来源的全局时间相同**
（只要求每来源内部时间戳严格单调递增，由 trace_video 聚合保证；全局只要求非降序）。
**不丢弃任何帧**：failed / abstained / not_found / low_confidence 全部保留。

`global_summary{}`：`first_confirmed_global_timestamp_ms`、
`last_confirmed_global_timestamp_ms`、`first_confirmed_source_id`、
`last_confirmed_source_id`、`confirmed_entry_count`、`sources_with_confirmation`、
`class_counts`（confirmed/not_found/abstained/low_confidence/failed）、
`analyzed_entry_count`、`per_source{}`（每来源首末确认/计数/overall_status）、
`overall_status`。

整体状态规则（与单视频一致）：无任何 analyzed → `failed`；有 confirmed → `completed`；
无 confirmed 但有 abstained/low_confidence → `abstained`；全部 not_found →
`completed`（负面结论也是完成态）。

## 4. 跨视频语义边界（核心安全要求）

当同一目标查询在两段视频中被确认时，**只能**得出：

- matched target query（同一目标查询）；
- visually consistent with target description（分别与目标描述视觉一致）；
- confirmed in source A / confirmed in source B（在来源 A / 来源 B 中分别确认）。

**不得**自动得出（除非未来存在可靠的跨摄像头身份或实例关联证据）：

- same physical instance（同一个物理实例）；
- moved from A to B（从 A 移动到 B）；
- carried by the same person（被同一人携带）；
- entered another camera（进入另一个摄像头）；
- identity matched（身份匹配）。

`semantic_limitations` 字段随 global-timeline.json 与 multi-video 报告一并输出，
最终报告必须在显著位置显示该限制。全局时间线是**证据聚合**，不是跨摄像头身份追踪。

## 5. 像素坐标受控归一化（任务 06）

任务 05 中曾出现一帧模型返回像素坐标 `[431,222,545,356]`（合法像素坐标但不符合 0–1
归一化契约）被整体拒绝。任务 06 起实现**确定性受控归一化**，仅当同时满足：

1. 四个坐标都是数值；
2. 坐标全部大于 1（明确识别为像素坐标；**混合坐标**——部分 ≤1 部分 >1——拒绝）；
3. `x1 < x2` 且 `y1 < y2`；
4. 坐标全部位于实际图片宽高范围内；
5. 能读取该关键帧的真实宽高（纯标准库解析 PNG/JPEG 头，不依赖 cv2/PIL）。

才执行 `x1/width, y1/height, x2/width, y2/height`，并记录：

```json
{
  "bounding_box": [0.449, 0.386, 0.568, 0.618],
  "bounding_box_raw": [431, 222, 545, 356],
  "bounding_box_source_format": "pixel",
  "bounding_box_normalization_applied": true,
  "frame_width": 960,
  "frame_height": 576
}
```

坐标混合、越界、顺序错误或尺寸未知时：**不归一化**；`bounding_box` 返回 null；
记录 warning（含原始值脱敏摘要）；**不重跑模型凑结果**；该帧其余证据字段保持不变。
帧尺寸不可知（非 PNG/JPEG 或文件损坏）同样拒绝归一化。

## 6. 资源守卫与失败降级

- 与单视频链路一致：调用视觉模型前检查 `/proc/meminfo` MemAvailable，低于阈值
  （默认 40 GiB）时不加载模型，该来源全部帧标 failed，全局状态如实降级；
- 单个来源抽帧/规格失败 → 明确错误退出（不静默跳过、不用其他来源冒充）；
- 单帧后端失败 → 该帧 failed，不中断其他帧与其他来源。

## 7. 安全边界

- 不推断人物身份、年龄、国籍、关系或意图；不做人脸识别；
- 不做跨镜头身份追踪、不实现实时多摄像头；全局时间线不是跨摄像头追踪；
- OpenCV 仅作底层抽帧工具（读元数据/抽帧/存图），绝不是项目核心创新或卖点；
- 多视频报告必须显示跨视频语义限制声明。
