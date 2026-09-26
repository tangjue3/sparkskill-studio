# Evidence Workbench 录制清单 — 页面与交互逐项（Sprint 01）

> 录制对象：本地 Evidence Workbench（`python3 scripts/serve_demo.py` → `http://127.0.0.1:8787/`，
> 只读、不调用模型）。每一项都标注了**必须同时讲出的诚实限定**。
> 页面结构依据 `app/index.html` / `app/app.js` 实测整理。

## 0. 录制总原则

1. 这是**归档查看器**：开场必须说"页面不会实时调用模型，展示的是已存档的真实运行产物"。
2. 五级 Truth Status 如实念：Verified / Recorded / Structural / Blocked / Synthetic Fixture；
   看到哪级念哪级，不美化。
3. Tier-3 历史链**四段都过**：Initial PARTIAL → E9 Remediation → Evaluator v1 Finding → Evaluator v2 PASS。
4. 鼠标跟随：每个面板停留 ≥2 秒再切换；不开 2 倍速。

## 1. 逐项清单（按录制顺序）

### R1 运行选择器（`#run-select` / `#run-picker`）

| 录什么 | 讲什么 | 诚实限定 |
|---|---|---|
| 下拉打开，露出 6 条记录 | 公开版收录 6 条：任务 16 / 任务 18 单视频时序证据回放 + Tier-3 历史链四条 | 输入为仓库内自产合成 fixture；任务 05/06（内部媒体）不在公开版 |
| 逐条切换的标题与徽标 | 每条记录的 verdict 原样念 | PARTIAL/PASS/TRADEOFF 都是真实历史判定 |

### R2 主结论区（`#hero-*`：result / status / facts / json / provenance / target-detail）

| 录什么 | 讲什么 | 诚实限定 |
|---|---|---|
| 目标结论 + 状态徽标 | 结论 + 它属于哪个来源 | confirmed 只代表"该采样帧获得支持" |
| Hero JSON 弹层（`#json-modal`） | "每个结论背后是结构化字段，可逐项核对" | 字段含义按 app 实际展示念 |
| Provenance 摘要（`#hero-provenance`） | 来源链路：哪次运行、什么媒体、什么采样 | 不宣称跨视频同一性 |

### R3 证据时间线（`#evidence-body` / `#evidence-controls` + `#ribbon-title` / `#ribbon-legend`）

| 录什么 | 讲什么 | 诚实限定 |
|---|---|---|
| 逐帧/逐采样点时间线 | 时间戳 + 关键帧 + 每点的判断（含拒答） | 两个 confirmed 采样点之间**不得**断言连续存在 |
| 选中某一行的高亮变化 | 时间线与帧图联动 | 边界只定位到左右采样点范围 |
| 图例（`#ribbon-legend`） | 五类/七类计数怎么读 | abstained / low_confidence / failed 不折算为 not_found |

### R4 Provenance Inspector 抽屉（`#inspector-*` / `#drawer-*`）

| 录什么 | 讲什么 | 诚实限定 |
|---|---|---|
| 点开抽屉的完整交互 | 原始返回、时间戳、媒体哈希、调用记录 | "这是把'模型说有'和'事实'分开的地方" |
| 抽屉内字段滚动 | 采样策略、预算消耗、覆盖探索 | 公开版条目按实际渲染讲；没有的字段不提 |

### R5 阶段链路（`#stage-deck` / `#stage-index`）

| 录什么 | 讲什么 |
|---|---|
| 九阶段逐段点亮 | 用户任务 → StepFun 任务规划 → DSH Skill 匹配 → VisualTaskSpec → 抽帧 → Qwen 视觉证据 → 全局时间线 → 最终结论 → Tier-3 验证 |
| 阶段与运行记录对应 | "图上每一步都能在记录里找到对应产物" |

### R6 Benchmark 页签（`#pane-benchmark` / `#tab-benchmark`）

| 录什么 | 讲什么 | 诚实限定 |
|---|---|---|
| 历史链四段切换 | 每段的 verdict 与原因 | v1 评分器误报是**评测器缺陷被抓住**，不是瞒住 |
| [tier3-comparison.svg](../competition/tier3-comparison.svg) 数据来源 | 四维对比 + 效率 | "每侧 9 任务、单次运行；不外推" |

### R7 Governance 页签（`#pane-governance` / `#tab-governance`）

| 录什么 | 讲什么 | 诚实限定 |
|---|---|---|
| Truth Status / 治理规则展示 | 项目怎么防止"把缺口写成肯定" | 客户端零依赖、只读、无模型调用 |
| 失败与停止记录所在 | 停止门在哪几个文档里 | 见 `docs/competition/` 四例说明 |

## 2. 交互禁忌（出现即废镜头）

1. 不得打开任何指向不存在路径的链接（公开版已保证无死链，但换环境录要复查）。
2. 不得现场修改任何数据——本工作台只读，没有写入口。
3. 不得把 Recorded 说成"实时运行"、把 Structural 说成"模型验证"、把 Blocked 说成"成功"。
4. 控制台报错、断网图、白屏一律重录。
5. 不录与演示无关的桌面内容（私人消息、文件管理器、其他项目）。

## 3. 一镜到底的推荐顺序（约 70–90 秒）

R1 打开选择器（念 6 条）→ R2 主结论 + JSON 弹层 → R3 时间线选点 → R4 Provenance 抽屉 →
R5 阶段链路 → R6 Benchmark 四段 → R7 Governance 收尾。主 Demo（Runbook §4）之后接这一段，
再接 Tier-3 对比图与停止门字幕（见 [video-shotlist-3min.md](video-shotlist-3min.md) D/E 段）。
