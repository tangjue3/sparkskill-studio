# SparkSkill Studio · 视觉证据工作台 — 界面设计系统

> **当前权威版本：任务 12 / 12.1 / 13 已部署的 Apple 风格亮色界面。**
> 所有 CSS 颜色、字体、圆角、间距必须来自本文件的 token，token 唯一定义于 `app/styles.css` 的 `:root`。
> 修改界面样式前必须先更新本文件；两者不一致时以 `app/styles.css` 的 `:root` 为唯一权威来源。
>
> **历史说明（任务 15 补充）**：任务 10 的第一版工作台是石墨黑/炭灰暗色系统（`--bg #0d1013` 等令牌）。
> 任务 11 视觉验收 FAIL 后，任务 12 重设计为当前的亮色系统，`a2fe686` 起旧暗色令牌已全部从 `app/styles.css` 移除。
> 本节末尾保留暗色系统的历史记录，仅作沿革说明，**不得作为当前规范使用**。

## 1. 用户

- 黑客松评委（90 秒内看懂证据链；投影或共享屏幕观看）；
- NVIDIA 与 StepFun 技术评审（核查真实性与组件分工）；
- 现场观看演示的开发者（沿证据链逐步审计）。

## 2. 主要任务

> 从用户任务开始，沿证据链检查每一步，确认最终结论是否有真实视觉证据支撑。

界面感受：**明亮、克制、可投影的专业证据工作台**（Apple 产品发布页 × 证据审查工具）。
不是：营销落地页 / 普通管理后台 / 通用聊天机器人 / 彩色 KPI 卡片集合 / 等权卡片网格 / 终端风暗色页面。

## 3. 标志性结构：Evidence Ribbon（证据链路）

界面核心不是 KPI 卡，而是按真实执行顺序的横向九阶段证据链路：

```
用户任务 → StepFun 任务规划 → DSH 技能匹配 → 视觉任务规范 → 视频抽帧
→ Qwen 视觉证据 → 全局证据时间线 → 最终结论 → Tier-3 验证
```

（节点 ID 与顺序固定为 `user-task, stepfun-plan, dsh-skill-match, visual-task-spec, video-frames,
qwen-evidence, global-timeline, final-decision, tier3-verification`；任务 12.1 起主要标题与说明为中文，
执行器/模型/脚本名保留为最低层 metadata。）

每个阶段显示：状态、真实性等级、执行主体、输入/输出摘要、artifact 路径、风险/限制。
点击阶段 → 阶段证据画布切换到该阶段最相关内容；选中帧或时间线行 → 打开右侧 Provenance 抽屉。
Evidence Ribbon 承担：执行状态、证据来源、失败位置、数据血缘、Skill 路由、真实性检查。
它**不是**普通步骤条。

## 4. 色彩 token（颜色必须表达状态）

| Token | 值 | 用途 |
| --- | --- | --- |
| `--gallery-canvas` | `#f5f5f7` | 苹果白画布：页面背景 |
| `--gallery-white` | `#ffffff` | 主表面（卡片/面板） |
| `--gallery-inset` | `#f0f1f3` | 内嵌表面（帧网格底、代码块） |
| `--gallery-hover` | `#f8f8fa` | hover 表面 |
| `--gallery-selected` | `#f1f7fd` | 选中表面（蓝调） |
| `--graphite` | `#1d1d1f` | 主要文字 |
| `--graphite-soft` | `#424245` | 次级文字 |
| `--graphite-muted` | `#6e6e73` | 说明文字 |
| `--graphite-faint` | `#86868b` | 弱化文字/标签 |
| `--line` | `#d9d9de` | 一级边界 |
| `--line-soft` | `#e8e8ed` | 弱边界/分隔 |
| `--line-strong` | `#b8b8bd` | 强边界（控件） |
| `--apple-blue` | `#0071e3` | **交互强调色（唯一）**：链接、选中、聚焦、主动作 |
| `--apple-blue-dark` | `#0066cc` | 交互 hover/active |
| `--apple-blue-soft` | `#e8f2fc` | 选中底色 |
| `--verified` / `--verified-soft` | `#188038` / `#eaf6ed` | Verified / PASS / confirmed |
| `--recorded` / `--recorded-soft` | `#8a5a00` / `#fff5d9` | Recorded / 历史运行 |
| `--structural` / `--structural-soft` | `#4a6480` / `#eef3f8` | Structural / artifact 链接 |
| `--blocked` / `--blocked-soft` | `#b54708` / `#fff0e6` | Blocked / abstained / 证据不足 |
| `--danger` / `--danger-soft` | `#d92d20` / `#fff0ef` | Failed / 安全禁止 / 缺陷 |
| `--fixture` / `--fixture-soft` | `#7253a3` / `#f2edfa` | Synthetic Fixture |
| `--shadow-ambient` | `rgba(0,0,0,0.05)` | 环境阴影 |
| `--shadow-focus` | `rgba(0,113,227,0.22)` | 键盘聚焦环 |
| `--shadow-overlay` | `rgba(0,0,0,0.26)` | 弹窗背板 |
| `--shadow-media` | `rgba(0,0,0,0.18)` | 关键帧媒体阴影 |
| `--media-black` | `#0b0b0d` | 帧图片占位底 |
| `--white-text` | `#ffffff` | 深底上的文字 |

语义色（verified/recorded/structural/blocked/danger/fixture）**只承担状态语义**；交互强调色只有 Apple Blue 一种。
禁止：装饰性渐变、高饱和霓虹、玻璃拟态、厚重阴影、发光边框、把语义色当装饰色使用。

## 5. 字体与文本层级

| 层级 | 规格 |
| --- | --- |
| 字体栈 | `--font-display` / `--font-text`：`-apple-system, BlinkMacSystemFont, "SF Pro Display"/"SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif`（本地系统字体，**不加载网络字体**） |
| 等宽 | `--font-mono`：`"SFMono-Regular", "SF Mono", Menlo, Consolas, "Liberation Mono", monospace`；数据、时间戳、路径、JSON 一律等宽 |
| Hero 主标题 | `clamp(38px, 3.3vw, 62px)` / 700 / `--font-display` / letter-spacing -0.045em |
| 阶段标题 h2 | `clamp(24px, 2vw, 34px)` / 680 |
| 结论行 | `clamp(15px, 1.1vw, 18px)` / 590 / `--graphite-soft` |
| 正文 | 13–15px / `--graphite-soft`–`--graphite` |
| 标签/元信息 | 10–12px / `--graphite-faint`；英文 overline 允许 10px |

投影可读性：主要内容不使用 10–11px；10px 仅限英文 overline、序号与技术元数据。

## 6. 边框与深度

- 一级边界：1px `--line`（面板之间、表格行）；弱边界 `--line-soft`；控件边界 `--line-strong`；
- 深度：白表面 + 安静的分层阴影（`--shadow-ambient` / `--shadow-media` / `--shadow-overlay`）；
- 禁止：玻璃拟态、大阴影、发光边框、高饱和霓虹、>1px 厚重边框。

## 7. 控件 token

- 主动作/链接：`--apple-blue` 底或文字色，hover `--apple-blue-dark`；
- 聚焦：3px `--shadow-focus` outline（键盘 focus 可见，所有交互元素可用 Tab/Enter/Space/Esc 操作）；
- 运行选择器 / tab：白底 + 1px `--line`，选中 `--gallery-selected` + 蓝调文字；
- 证据链路节点：白底 + `--line`，选中加 `--gallery-selected` 与蓝调边界；
- Provenance 抽屉 / JSON 弹窗：右侧或居中浮层，`--shadow-overlay` 背板，Esc 关闭后焦点回归触发元素；
- 时间线行/帧卡片：hover `--gallery-hover`，选中 `--gallery-selected`。

## 8. 间距与圆角

- 间距基线 4px：`--sp-1`(4) `--sp-2`(8) `--sp-3`(12) `--sp-4`(16) `--sp-5`(20) `--sp-6`(24) `--sp-8`(32) `--sp-10`(40) `--sp-12`(48) `--sp-16`(64)；
- 圆角（Apple 风格大圆角，取代任务 10 的 4/6px）：`--radius-xs`(8) `--radius-sm`(12) `--radius-md`(18) `--radius-lg`(26) `--radius-xl`(34)；
- 内容最大宽度 `--shell: 1600px`；
- 动画：短促、平静的过渡；`prefers-reduced-motion` 时禁用；禁止弹跳、 glow、装饰性动画（loading spinner 为例外）。

## 9. 状态颜色（Truth Status 与证据状态）

| 状态 | 色 | 出现位置 |
| --- | --- | --- |
| Verified | `--verified` 绿 | 有真实 Harness/模型/程序化校验产物 |
| Recorded | `--recorded` 琥珀 | 历史真实运行，当前页面不重新执行 |
| Structural | `--structural` 冷灰蓝 | 仅 Schema/抽帧/状态机结构验证 |
| Blocked | `--blocked` 橙棕 | 资源/环境未完成 |
| Synthetic Fixture | `--fixture` 紫 | 自动测试数据 |
| Failed / 安全禁止 | `--danger` 红 | failed 帧、缺陷、凭据拒绝 |
| confirmed / not_found / abstained | 绿 / 琥珀 / 橙棕 | 帧状态 |
| PASS / PARTIAL / FAIL | 绿 / 琥珀 / 红 | Verdict 徽章 |

状态必须**颜色 + 文字/符号双重表达**，不得仅靠颜色区分。
禁止：把 Recorded 显示成实时运行；把 Structural 显示成模型验证；把 Blocked 显示成 Success；
把 Synthetic Fixture 显示成真实业务数据；把命令行串联显示成 DSH 自主编排。

## 10. 组件模式

- **顶栏**：品牌 + 一句话定位 + 运行记录选择器 + Truth Status；环境与模型细节作为次级披露，不排成一串徽章；
- **Hero 结果摘要**：真实关键帧为画面主体 + `READ-ONLY · RECORDED ARTIFACTS` 标注 + 主体/结果行/支撑描述/结果摘要 + 关键事实（首次确认、最后确认、有效帧数、来源数）；
- **证据链路（Ribbon）**：横向九阶段，常见桌面宽度下完整可见或明显可横向导航；
- **阶段证据画布**：规格/帧/时间线/结论/Benchmark 各自的信息结构，不套用等权日志卡片；长路径与技术字符串换行或截断，按需揭示；
- **Provenance 抽屉**：右侧上下文面板，回答"结论从哪来"，不长期占据三分之一屏幕；
- **验证终章**：Security/Correctness/Discoverability/Effectiveness 9/9 + 3534.4s→800.5s 形成视觉高潮；完整历史 Initial PARTIAL → E9 Remediation → Evaluator v1 Finding → Evaluator v2 PASS 同屏可得；
- **帧卡片**：bbox 为 null 时显示"未提供可靠定位框"，**禁止画假框**；
- **JSON 弹窗**：等宽 pre + Esc/背板关闭，默认隐藏，按需打开。

## 11. 禁止的默认模板

- 禁止"左侧导航 + 四个统计卡 + 表格"的管理后台模板；
- 禁止等权卡片网格作为主体；
- 禁止营销式 hero/渐变横幅；
- 禁止紫色渐变、终端暗色风、 oversized pill；
- 禁止把证据链路退化成无状态信息的普通步骤条；
- 禁止常驻原始 JSON 与调试路径；
- 禁止装饰性动画。

## 12. 布局与响应式

```
┌─────────────────────────────────────────────────────────────┐
│ 顶栏：品牌 / 定位 / 运行记录切换 / Truth Status（sticky）     │
├─────────────────────────────────────────────────────────────┤
│ Hero：真实关键帧 + 主体 + 结果行 + 结果摘要 + READ-ONLY 标注  │
├─────────────────────────────────────────────────────────────┤
│ 证据链路：横向九阶段（选中阶段更新下方画布）                   │
├─────────────────────────────────────────────────────────────┤
│ 阶段证据画布（规格 / 帧 / 时间线 / 结论 / Benchmark）          │
├─────────────────────────────────────────────────────────────┤
│ 验证终章：四维 9/9 + 3534.4s→800.5s + 四段历史链             │
├─────────────────────────────────────────────────────────────┤
│ 页脚 / Provenance 抽屉（右侧浮层）/ JSON 弹窗（居中浮层）      │
└─────────────────────────────────────────────────────────────┘
```

- 断点：`1320px` / `1080px` / `860px`；
- 桌面目标 1920×1080、1440×900、1280×800：首屏同屏呈现 Hero 结果、真实关键帧与完整九阶段链路（实测 Ribbon 底部 y≈1068px @1920）；
- 1024×768：有意的双栏 Hero + 完整横向 Ribbon，不退化为单列长文本；
- 所有视口无页面级横向溢出；中文标题不裁切；
- 语义地标（`header` / `main` / `section[aria-labelledby]` / `footer`）与可见焦点态为硬性要求。

## 13. 历史设计记录（任务 10 暗色系统，已被任务 12 取代，仅作沿革）

任务 10（提交 `a1e5646`）的工作台为暗色系统：`--bg #0d1013`（石墨黑背景）、`--surface #14181c` / `--surface-2 #191e23` / `--surface-3 #1f252b`、`--border #262d33` / `--border-strong #36414a`、`--text #e6ebef` / `--text-dim #98a3ac` / `--text-faint #66727b`、`--green #3fb950`（信号绿唯一强调色）、`--amber #d29922`、`--red #e5534b`、`--blue-grey #6e8aa8`、`--frame-placeholder #000`、`--modal-backdrop rgba(0,0,0,0.6)`；圆角 4/6px；布局为左（任务与 Skill 契约）/ 中（Evidence Rail + 证据）/ 右（Provenance Inspector）三栏 + 底部 tab，<1180px 堆叠为单栏。

该版本在任务 11 视觉验收中 FAIL（P0：`[hidden]` 浮层被组件 display 规则覆盖导致首屏被永久遮挡；P1：三栏等权长页、首屏看不到主线；P1：长路径常驻首屏），已由任务 12 重设计取代。**上述暗色令牌不再是当前规范；当前实现不得重新引入。**
