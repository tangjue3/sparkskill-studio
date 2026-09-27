# Task 28 — 存量环境阻塞记录（`PRE_EXISTING_ENVIRONMENT_BLOCKER`）

- 记录时间：2026-09-25（UTC）
- 性质：**诊断记录，不是失败结论**。记录一次在 Gate 工作中观察到的存量环境问题，
  及其与本轮 Gate 的正交性。
- 本文件只读描述，不修复、不启用、不改任何代码。

## 1. 现象

以下两个测试在**前半段规则用例通过后**崩溃：

```text
.dsh/skills/visual-evidence-extractor/scripts/test_temporal_evidence.py
.dsh/skills/visual-evidence-extractor/scripts/test_task18_coverage_sampling.py
```

崩溃点为依赖 `extract_frames.py` 抽帧的步骤：

```text
extract_frames.ExtractionError: 帧目录不存在:
  .../Temp/.../sparkskill-t16-run-*/frames/fixture-reappear_f00000_t00000000ms.png
```

`extract_frames.py` 顶部有 `skill_env.ensure_cv2_interpreter()`：当当前解释器无 cv2 时
会用 `execv` 切换到"本机已有 cv2 的解释器"。该切换在临时目录语义下不能稳定复现，
是崩溃的直接来源。

## 2. 阻塞分类

```text
PRE_EXISTING_ENVIRONMENT_BLOCKER

affected:
  - test_temporal_evidence.py            extraction-dependent cases
  - test_task18_coverage_sampling.py     extraction-dependent cases

introduced_by_gate:      false
source_modified_by_gate: false
blocks_state_replay:     false
```

三项判据各有实证：

| 判据 | 证据 |
| --- | --- |
| `introduced_by_gate: false` | 本轮只新增 `state_resolver.py`、`score_state_replay.py`、`test_state_expressiveness_gate.py`、`freeze_task28_hashes.py` 与预注册/记录文档；未修改这两个测试的任何输入 |
| `source_modified_by_gate: false` | 相关源文件 mtime 均为 `2026-09-24 04:36:22`（本轮开始之前），逐字未变 |
| `blocks_state_replay: false` | Gate 是 `CPU-only / archived_replay / 0 model calls / 0 frame extraction`，不经过 `extract_frames`；17/17 Gate 测试与三轨 e2e 冒烟均不依赖抽帧 |

## 3. 回归口径（必须按此表述，不得简写）

**不得**写成"全部 regression 通过"。正确口径：

> Gate-specific tests **PASS**（17/17）；冻结 scorer regression **PASS**（34/34）；
> 两套既有 extraction-dependent 回归因**存量环境问题** `NOT_RUN` / `ENV_BLOCKED`。

已实际运行并通过的回归：

| 套件 | 结果 |
| --- | --- |
| `scripts/test_state_expressiveness_gate.py` | PASS 17/17 |
| `.dsh/skills/visual-evidence-extractor/scripts/state_resolver.py --audit` | PASS 25/25 |
| `scripts/test_temporal_ground_truth_scoring.py`（冻结 scorer） | PASS 34/34 |
| `scripts/test_demo_app.py` | PASS 26/26 |
| `.dsh/skills/task-to-skill-compiler/scripts/test_missing_media_contract.py` | PASS 10/10 |

受阻（存量，非本轮引入）：

| 套件 | 状态 |
| --- | --- |
| `test_temporal_evidence.py` | `ENV_BLOCKED`（前半段规则用例 PASS 后于抽帧步骤崩溃） |
| `test_task18_coverage_sampling.py` | `ENV_BLOCKED`（同上） |

## 4. 处理决定

**本轮不修。** 理由：

1. Gate 的生命周期（预注册 → 冻结 → replay → 判据）与抽帧路径正交；
2. 顺手修改 `extract_frames.py` / `skill_env.py` 会污染"Gate 前只新增文件"的干净状态；
3. 修复本身需要独立的复现与回归，属另一项工作。

修复合入条件（建议作为独立任务，另行预注册）：

- 能在一个干净临时目录稳定复现崩溃；
- 明确 `ensure_cv2_interpreter()` 的 `execv` 切换目标解析规则；
- 修复后两套 extraction-dependent 回归必须**完整通过**，而非只跑到规则用例；
- 修复不得改动 `analyze_image.py` 生产模板与冻结 scorer。

## 5. 相关副作用（已知，非代码问题）

`scripts/test_demo_app.py` 会重写 `app/data/demo-manifest.json`（内含 `generated_at`）。
该文件不被父仓库 git 跟踪，因此无法用 `git checkout` 还原；已保留运行后状态，
未做手工编辑。后续如需确定性 manifest，应由 `build_demo_manifest.py` 显式重生成。
