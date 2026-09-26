# Demo Runbook — SparkSkill Studio 演示操作手册（Sprint 01）

> 目标：把"服务器真正计算、本地操作录屏"的 Demo 流程固化为任何人都能照做的步骤。
> 环境基线：服务器 = NVIDIA DGX Spark（GX10/GB10，~119GiB 统一内存，ARM64）；
> 本地 = 任意能开浏览器的机器。**本手册不含任何密钥；凭据由持有人在本地注入。**

## 0. 角色分工（不可颠倒）

| 角色 | 负责 | 不负责 |
| --- | --- | --- |
| 服务器（DGX Spark） | 平台前端/后端、模型推理、Skill 执行 | 录屏画面 |
| 本地电脑 | 浏览器操作、屏录、后期 | 视觉推理全部发生在远端 |

## 1. 开录前 T-1 天：完整试跑

1. 按 §2 预检 → §3 连接 → §4 完整跑一遍 Demo 主链路。
2. 对比 2–3 个候选案例，固定**表现最佳的一个**作为正式录制案例。
3. 记录：结果页截图、服务器日志时间戳、总耗时，供剪辑对轴。
4. **不要边跑边录正式素材**；试跑与正式录屏分离。

## 2. 服务器预检（按序执行，任何一条不过先修再录）

```bash
# 1) GPU 在位（DGX Spark 为 GB10，unified memory）
nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu --format=csv

# 2) 平台 web 服务（DSH）在跑，且只监听回环
ss -tlnp | grep 7000        # 期望：127.0.0.1:7000

# 3) 视觉后端二选一，确认哪一个是当前激活后端
ollama list                 # ollama 路线：期望含 modelscope.cn/unsloth/Qwen3.8-27B-GGUF:latest
curl -s http://127.0.0.1:11434/api/version
# 或
~/start-vllm-nemotron.sh status   # vLLM 路线：Nemotron-30B + DSpark；注意与 Ollama 不能同时常驻

# 4) 内存余量（加载 Qwen 前 MemAvailable 建议 ≥ 45GiB）
free -h

# 5) token 有效（DSH 重启后 token 会变，失效见 §5）
```

> 两个后端切换会改变 DSH 的模型配置；**录制当天不要切换后端**。当前激活哪个以
> `~/.dsh/settings.yaml` 为准，拿不准就问平台负责人。

## 3. 本地连接（三种情形）

| 情形 | 操作 |
|---|---|
| 首次使用 | 按队友包说明准备 `_spark.env`（仅本地保存）→ `python teammate_tunnel.py` |
| 端口 8899 被占用 | `python teammate_tunnel.py 9000`，浏览器相应改为 `http://localhost:9000/?token=...` |
| 多人同时用 | 各自用不同本地端口，互不影响 |

隧道成功的标志（终端保持不关）：

```text
隧道已建立，浏览器打开： http://localhost:8899
转发： 127.0.0.1:8899 -> <服务器> -> 127.0.0.1:7000
```

浏览器第一次访问必须带 token：`http://localhost:8899/?token=<队长提供>`；
成功后服务端下发长期 cookie，同一浏览器后续直接开 `/` 即可。

## 4. Demo 主链路（录屏顺序）

1. **上传测试视频**：使用仓库内合成 fixture 或已授权素材，不用内部媒体。
2. **输入 Prompt**：一句自然语言视觉任务（例：判断红色背包出现/未出现的时间区间；证据不足不要猜）。
3. **Compile / Generate Skill**：展示任务规格生成；如故意演示负例——不提供媒体来源时，编译器必须
   返回 needs_input 并停止，而不是去猜路径。
4. **Run Skill**：此处切服务器终端 3–5 秒 B-roll（`nvidia-smi`、模型加载、Skill 执行日志），
   证明推理发生在服务器本地。
5. **结果页**：时间戳、关键帧、证据链、最终报告；强调 not_found / abstained / failed 不可互相替代。
6. **收尾**：回本地 Evidence Workbench 展示归档（只读查看器），接 Tier-3 对比。

## 5. 故障处置（出现即停录，修好再继续）

| 现象 | 含义 | 处置 |
|---|---|---|
| 401 Unauthorized | token 失效（DSH 重启过） | 找平台负责人要新 token |
| 403 | 用了局域网 IP 访问 | 必须用 localhost / 127.0.0.1 |
| 本地端口被占用 | 8899 被本机其他程序占用 | 换端口（§3） |
| "缺少密码且当前不是交互终端" | 找不到 `_spark.env` | 确认它与隧道脚本同目录 |
| 连接超时 | 服务器节点异常或 ssh 端口不通 | 找平台负责人；不要反复重试 |
| 模型长时间无输出 | 资源不足（统一内存被占） | 停录，查 `free -h`；不得自行停他人服务 |

## 6. 录屏规范

- 只录本地浏览器界面；**不录服务器远程桌面**。
- 服务器素材只录终端窗口（tile 布局，主录屏画面旁或推理等待处插入）。
- 1080p 起步；浏览器 100% 缩放；隐藏无关书签/标签；关掉与演示无关的通知。
- 地址栏 token、终端密码、绝对路径不得成为画面焦点。
- 正式素材与试跑分开存放；每录完一段立即回看确认。

## 7. 与公开仓库的对应（演示中说到的每个能力都要落在仓库里）

| 演示提到 | 仓库证据 |
| --- | --- |
| 任务规格 + 媒体硬门 | `.dsh/skills/task-to-skill-compiler/` + M1–M8 契约测试 10/10 |
| 受控视觉证据 | `.dsh/skills/visual-evidence-extractor/` + 规则测试（开发机 27/27、36/36；无 cv2 机器如实 ENV_BLOCKED） |
| 证据链报告 + 反幻觉校验 | `.dsh/skills/evidence-report-generator/` |
| 对照评测 | `BENCHMARK.md`（Tier-3 历史链） |
| 只读工作台 | `app/` + `scripts/serve_demo.py`（127.0.0.1:8787） |
| 诚实停止门 | `docs/competition/` 四例说明 |
