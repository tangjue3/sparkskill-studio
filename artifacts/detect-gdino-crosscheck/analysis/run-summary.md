# 视觉交叉核验 B — Grounding DINO Tiny 隔离实测：运行摘要与最终报告

- 任务性质：**新检测调用对历史 Qwen v1 存档**的诊断。不是同期双模型质量对照，不产生可部署 verdict。
  **不是 Task 23；不设计/接入正式双模型 Skill。** 完成后停止，交总控。
- 冻结提交：`8ff77e187a8da58b7c9de4c19d033538652e1caa` @ 2026-09-23T11:33:22Z（协议/阈值/查询映射/口径，早于任何 dev 调用）。
- 检测运行：起始 2026-09-23T11:34:10Z → 结束 11:36:09Z（冻结提交之后，顺序可验证）。

## 最终结论（VERDICT）

**`PARTIAL_TARGET_COVERAGE` + `NO_GO`（就"用本资产挑战/增强 Qwen 的双模型 Skill"而言）。**

- 覆盖仅**类别**：背包/周转箱/纸箱托盘/托盘周转箱的类别框可靠；**颜色"红色"基本不被判别**；
  **装载/相邻关系多数不可靠**（WEB01 货叉关系使检出从 23→4 崩塌；WEB02 平台关系可用）。
  → 只有类别框 ⇒ 标 `PARTIAL_TARGET_COVERAGE`。
- 信号会**大量误拦正确判断**：在 185 个历史 `correct_decisive` 中，检测器会**误质疑 66（35.7%）**，
  集中在颜色关键的 WEB03(25)/AI05(23)（类别假阳，不验证颜色）与关系场景 WEB01(18)（漏检）。
  → 满足"模型信号会大量误拦正确判断" ⇒ 就挑战式双模型用法如实写 `NO_GO`。
- 唯一窄正面：在 25 个 `incorrect_decisive`（Qwen 漏掉真实存在目标）中，检测器标记出 13 个冲突，
  但其中仅 3 个框得分 ≥0.5（强），10 个在 0.40–0.50（弱，勉强过阈）。该弱信号被 66 个误拦压倒。
- 该结论不否定检测器作为"类别存在性第二意见"的窄用途，但**不足以**据此设计生产双模型 Skill；
  是否值得总控另行设计正式实验见末节。

---

## 起末 HEAD / 提交
- 起始（只读核验）：`master`，HEAD `7bf60257c53c7a5595acdf0174dfe296402b8dab`，工作区干净，无 remote。
- 冻结提交：`8ff77e1`（9 文件：协议/证据/脚本），一次性身份 `detect-crosscheck-b <detect-crosscheck-b@local>`，未改全局 git 配置。
- 结果提交：本文件随结果一并提交（SHA 见运行日志，不在文内自引用）。
- 结束：`master` 上仅**新增** `artifacts/detect-gdino-crosscheck/` 下文件；冻结路径 0 字节改动；仍无 remote、未 push。

## 模型资产与许可证复核（Hard Gate 1，PASS）
- 精确路径 `<私有模型资产目录>/grounding-dino-tiny-a2bb814`（权限 700）。
- 来源 `IDEA-Research/grounding-dino-tiny` @ 不可变 `a2bb814dd30d776dcf7e30523b00659f4f141c71`。
- 9 资产逐文件 SHA-256/字节全部匹配 manifest（总 690,308,125 B <1GiB）；manifest 自哈希 `021f1d0b…` 一致。
- 无 `.bin`/pickle/权重副本/凭据/缓存/隐藏文件；`pytorch_model.bin`、`.gitattributes` 明确未下载。
- 许可证据（仅记录）：模型卡 `license: apache-2.0`；官方代码仓库 Apache-2.0；加载依赖 transformers(Apache-2.0)+PyTorch(BSD-3-Clause)，
  **无 trust_remote_code**。再分发决策留总控；非法律定论。
- 加载完整性：safetensors 990 张量/172,277,902 参数；可训练参数 172,250,626（差为 int64 缓冲）。

## 实际环境/依赖变化（Hard Gate 4）
- 项目外隔离 venv `<项目外隔离目录>/venv`（Python 3.12.3, aarch64, cuda=NVIDIA GB10）。
- **新增**（清华 PyPI 镜像，新下载 ≈22 MiB ≪500 MiB 上限）：`transformers==5.15.1`、`tokenizers==0.22.2`、
  `safetensors==0.8.0`、`huggingface_hub==1.32.0`、regex/PyYAML/requests/tqdm 及传递依赖。
- **复用**（0 新字节，来自上一轮项目外 venv，经 `.pth` 只读加入，未改其文件）：`torch==2.13.0+cu130`、
  `torchvision==0.28.0+cu130`、`numpy==2.3.5`、`opencv-python-headless==5.0.0.93`、`pillow==12.3.0` 及 CUDA13 库。
- 未改全局/系统/Docker/GPU runtime/用户服务/任何现有 venv。离线运行（HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1）。
- 兼容性：transformers 5.x 将后处理参数 `box_threshold` 重命名为 `threshold`；官方推荐**数值** box=0.4/text=0.3 保留。

## 实际检测调用数
- dev 帧 GroundingDINO 推理：**368 次** = 184 唯一 `(frame_sha256, target_query)` × {完整短语(主) + 仅类别探针}。
- 另 3 次合成技术图冒烟（非 dev），用于加载/输出契约。
- **本轮新 Qwen 调用 = 0**（Qwen v1 全为 Task 22 历史归档，从未当本轮 fresh_call；未调用冻结 Task 17 scorer 评本模型）。

## 全部查询覆盖矩阵（每目标，唯一帧；full=完整短语检出数, cat=仅类别检出数）
| target_query | 唯一帧 | full_det | cat_det | both | only_full | only_cat | neither | 颜色/关系判别 |
|---|---|---|---|---|---|---|---|---|
| 红色背包 (AI01–06) | 110 | 93 | 89 | 88 | 5 | 1 | 16 | 颜色弱（93≈89） |
| 红色周转箱 (WEB03) | 30 | 28 | 30 | 28 | 0 | 2 | 0 | **颜色未判别**（28≈30） |
| 叉车货叉上的托盘周转箱 (WEB01) | 26 | 4 | 23 | 3 | 1 | 20 | 2 | **关系崩塌**（23→4） |
| 拣选车平台上的纸箱托盘 (WEB02) | 18 | 18 | 12 | 12 | 6 | 0 | 0 | 关系可用（full≥cat） |
| **合计** | **184** | **143** | **154** | 131 | 12 | 23 | 18 | — |

覆盖判定：**类别支持**（四类均可检出类别框）；**颜色不支持**（红色周转箱/红色背包的完整≈仅类别，颜色词被忽略）；
**关系不一致**（WEB01 货叉关系严重抑制检出；WEB02 平台关系反而更稳）。开放词汇接口不保证组合判别——实测确实不能判颜色。

## 错误发现与正确误拦的具体分母（detector 完整短语 vs Qwen v1，同帧）
**256 行视图：**
- `incorrect_decisive`(25)：`conflicts_with_v1`=13（3 强≥0.5 / 10 弱<0.5）、`no_conclusion`=12、`supports_v1_error`=0。
- `overclaim_on_uncertain`(41)：`conflicts_with_v1`=3、`supports_v1_error`=38、`no_conclusion`=0。
- `correct_decisive`(185)：`detector_agrees`=119、**`wrongly_challenged`=66**（35.7%）。
  - 误拦子型：`false_positive`=48（WEB03 25 + AI05 23，颜色失效→在无目标处框出类别）、
    `missed_detection`=18（WEB01，关系短语过难→漏掉真实在场目标）。

**184 唯一帧视图：** incorrect(19): 10 冲突/9 无结论；overclaim(31): 2 冲突/29 支持；correct(131): 81 同意/**50 误拦**。

## 九样本与双轨明细（256 行）
| 样本 | 轨 | incorrect(冲突/无结论) | overclaim(冲突/支持) | correct(同意/误拦) |
|---|---|---|---|---|
| AI01 模糊可辨 | gen | 5 (3/2) | 0 | 23 (23/0) |
| AI02 进入 | gen | 0 | 2 (2/0) | 27 (27/0) |
| AI03 离开 | gen | 0 | 3 (1/2) | 26 (26/0) |
| AI04 遮挡 | gen | 0 | 9 (0/9) | 15 (15/0) |
| AI05 相似红色干扰 | gen | 0 | 0 | **23 (0/23)** |
| AI06 暗光小目标 | gen | 0 | 27 (0/27) | 0 |
| WEB01 空载关系 | lic | 9 (1/8) | 0 | 22 (4/**18**) |
| WEB02 平台关系 | lic | 0 | 0 | 24 (24/0) |
| WEB03 相似容器 | lic | 11 (9/2) | 0 | **25 (0/25)** |
| **generated 小计** | | 5 (3/2) | 41 (3/38) | 114 (91/23) |
| **licensed 小计** | | 20 (10/10) | 0 | 71 (28/**43**) |

- 逐帧失败/成功例（示例框图见 `screenshots/`，供人眼复核）：
  - **WEB03 颜色假阳**：GT 全程无红周转箱（黑/蓝箱），检测器 28/30 帧仍框出 "red turnover box" → 颜色不验证。
  - **AI05 干扰物假阳**：GT 无背包（红工具箱/红纸箱），检测器框出 "red backpack" → 类别假阳。
  - **WEB01 关系漏检**：货叉空载段仅类别命中、完整(货叉上)不命中；载箱段完整短语也仅 4/26 命中 → 关系短语过难。
  - **AI01 真阳性冲突**：检测器检出 Qwen v1 漏掉的背包（弱，得分<0.5）。
  - **AI06 暗光**：GT=uncertain，检测器仍稳定框出 → 与 Qwen "发现"一致（38 个 overclaim 中检测器多支持而非揭示过度断言）。
- 强证据冲突 vs 单纯没检到：incorrect_decisive 的 13 个冲突仅 3 个得分≥0.5（强），其余 10 个弱；`no_conclusion`(12) 为单纯没检到，**不证明不存在**。

## 延迟 / 内存 / 共存
- 首次加载 5.177s；单帧完整短语推理 mean 0.266s（min 0.26 / p50 0.263 / max 0.792）；full+category 对 mean 0.528s。
- 峰值统一内存：CUDA allocated 1.931 GiB / reserved 2.35 GiB；系统 MemAvailable 运行中 115.3→111.7 GiB，结束回 115.74 GiB。
- **与 Qwen 实际共存：未实测共驻**。运行期 Ollama Qwen 0 驻留（自行加载 Qwen 会违 0 新 Qwen 调用禁令，故未做）。
  共存仅为内存余量推断（115.74 GiB 可用 vs 检测器 ~2 GiB），非经验共载结论。
- 失败/超时/无效输出：0 inference_error、0 超时、0 resource_blocked；184/184 帧哈希推理时复验匹配。

## 历史存档 vs 新鲜调用的区分
- Qwen v1 = Task 22 归档调用（`artifacts/task-22/pairs/points/*` 的 `judgments.v1`），本轮 0 新 Qwen 调用，从未冒充 fresh_call。
- 检测器输出 = 本轮新鲜调用（`raw/detector_raw.jsonl`，含权重哈希/帧哈希/框/得分/阈值/时间）。
- 未调用冻结 Task 17 scorer 给本轮模型正式评分；七类账由 Task 17 冻结规则独立复现（v1=185/25/0/0/5/41/0，与冻结 paired-score 一致）。

## 未测项（明确列出）
- 未测：mAP/框准确率（无人工 bbox GT）；动态视频边界改善（未跑连续跟踪）；OWLv2/YOLOE（冻结禁换）；
  跨摄像头物理身份追踪（不做）；holdout（公开版占位编号 HOLDOUT-G1/HOLDOUT-G2/HOLDOUT-L1）未接触；颜色/关系的子跨度 grounding（短语级 label 限制）；
  与 Qwen 经验共载；正式双模型 Skill 集成；生产 PASS/行业泛化/获奖（均不作声明）。

## 冻结数据 / 服务 / holdout / 凭据状态
- 冻结路径（Task 17 scorer/GT、Task 19B–22、Task 16–18、Tier-3、三 Skill、`app/`、生产 v1 `analyze_image.py`、dev 包）：
  **0 字节改动**；31 项 frozen-hashes 运行后复检全 intact。
- 服务：Ollama(0.33.2, 0 加载)、DSH web(:7000)、MiniMax-H3(vllm-serve 仅空闲 bash) 均原状；无停/重启、无 keep_alive=0、无卸载外部模型。
- Holdout：未读/未列/未用（公开版以占位编号 HOLDOUT-G1/HOLDOUT-G2/HOLDOUT-L1 指代，真实编号见内部留档）。盲测未启动。
- 凭据：`.credentials.yaml` 未读、未输出；无 secret/key 打印；未建 remote、未 push；全局 git 配置未改。

## 下一轮是否值得设计正式实验
**条件性不值得（就当前资产与协议）。** GroundingDINO-tiny 只给类别、不验颜色、关系不稳；其信号会在颜色/关系关键场景
（WEB03/AI05/WEB01，即 20/25 决定性错误与干扰物拒答所在）以 35.7% 比率误拦 Qwen 的正确判断。用它做"挑战式"双模型
预期为负收益。若总控仍要推进，前提是：(a) 选用能验证颜色/关系或带组合 grounding 的检测器并通过许可审查；
(b) 设计"仅类别存在性第二意见、显式声明不判颜色/关系"的受限 Skill；(c) 预先设定误拦率上限并用 dev 集校准阈值。
在此之前，不建议启动正式双模型 Skill / Task 23 / holdout。
