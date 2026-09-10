# 轻量级 Workflow Resume + Tracing 方案调研（个人/零依赖，2026-08-24）

> researcher 调研存档。背景：AMTA 零依赖铁律（ADR-009/018），已有 `00_run_all.py`（文件存在=跳过）+ `pipeline_log.py`（span）+ `03 --trace`（LLM 日志）+ `tickets.py`（工单）。OpenClaw 结论：Metaflow/Prefect/OTel/Pydantic/GE 太重。本文评估更轻替代 + 渐进式路径。

## TL;DR（主 agent 该行动什么）

1. **AMTA 已有方案已经是"轻量方案"的天花板**——与零依赖的 owf（纯 stdlib + SQLite resume）思想同级，对脚本流水线甚至更贴合；**不需要引入任何 workflow 框架**。
2. **真正缺的是 3 个 stdlib 级小改进，不是新依赖**：① `.ok` marker（内容级断点，防"坏产物被跳过"）；② `os.mkdir` 原子锁（防双跑竞争写 pipeline_log）；③ `--force-step/--force-page`（替代手工删文件重跑）。各 ~10 行，全部 `pathlib`/`os`/`json`。
3. **若未来出现具体痛点再按序升级**：多 worker 并发 → GigQ（SQLite job queue）；agent 调用编排 → 借鉴 owf 的 resume/缓存语义；自造重试膨胀 → tenacity（零运行时依赖）。**现在不做**。

## Findings（每条带 URL）

### 1. 候选方案清单与真实体积评估

| 方案 | 类型 | 真实体积/依赖 | 上手成本 | 与 AMTA 现状对比 |
|---|---|---|---|---|
| **现状自造**（00_run_all + pipeline_log + tickets + --trace） | 零依赖 stdlib | 0 依赖 | 已落地 | — |
| **owf**（[akakabrian/agent-workflows](https://github.com/akakabrian/agent-workflows)） | 零依赖 Python workflow runtime | **纯 stdlib，零运行时依赖**（README 原文 "zero-dependency, stdlib-only"）；Python 3.11+ | 中（agent 语义） | 有 SQLite run journal + `owf resume`（replay 跳过缓存只读调用）+ budget/cache 语义——与 AMTA 思想同级，但面向 LLM agent 调用，非确定性脚本流水线 |
| **GigQ**（[kpouianou/GigQ](https://github.com/kpouianou/GigQ)） | SQLite job queue | SQLite 后端（Python 内置 sqlite3）；retries+backoff / crash recovery / Workflow 依赖声明（parent_results 注入） | 低-中 | 定位"outgrown for loop，不想上 Redis"——AMTA 已自造等价物；真多 worker 时才需要 |
| **tenacity**（[PyPI 9.1.4](https://pypi.org/project/tenacity/)） | Python retry 库 | **零运行时依赖**（PyPI requires_dist 仅 doc/test extras）；requires_python>=3.10；Apache-2.0；~100KB | 极低 | AMTA 已有自造重试（机械重译 1 次 + repair ≤3 轮）——除非自造代码膨胀才引 |
| **filelock**（[PyPI](https://pypi.org/project/filelock/)） | 文件锁 | 零运行时依赖，MIT | 极低 | workers=1 串行时不需要；`os.mkdir` 原子锁可替代 |
| **just**（[casey/just](https://github.com/casey/just)，winget 包 `Casey.Just`） | 任务运行器（单二进制） | **单二进制 ~3MB**（Windows x86_64），winget/scoop 可装 | 低 | **只做命令入口**（recipe 依赖顺序），**不追踪产物、不提供断点**——解决不了 resume，仅是 `python scripts/00_run_all.py` 的入口美化 |
| **make** | 构建工具 | Windows 无内置 GNU make，需额外安装 | 中 | timestamp 依赖图 ≠ 内容断点；AMTA 产物是 JSON 非编译产物，make 语义不贴合；Windows 成本高 |
| **SQLite 断点表** | 状态持久化 | **Python 内置 sqlite3，零新依赖** | 低 | JSON 文件够用时不必；多进程/高并发/防损坏时升级 |
| **结构化 bash + 产物即断点 / `set -x`** | 思想 | 0 依赖 | — | 思想与 AMTA 现状同源（shell 版 00_run_all）；`set -x` 等效 --trace |
| **git 工作流恢复**（worktree/commit checkpoint） | 思想 | git 已有 | — | AMTA 产物即状态（文件落盘），git 只做代码版本（pipeline_log 已记 git_head），不需要 git 做产物 checkpoint |

### 2. AMTA 已有方案评估：缺什么

对照成熟方案能力面逐项核对（[ADR-018](amta/docs/decisions/018-pipeline-orchestrator.md) + [00_run_all.py](amta/scripts/00_run_all.py) + [pipeline_log.py](amta/src/amta/pipeline_log.py) 源码）：

| 能力 | 成熟方案（Prefect/Metaflow） | AMTA 现状 | 缺口 |
|---|---|---|---|
| 断点续跑 | resume | 文件存在=跳过 | **内容级校验缺失**：只查"文件存在"，坏/半截产物（如 region_id 不全的 translation.json）会被跳过——补 `.ok` marker 或产物首行 done 标记 |
| step tracing | span/OTel | pipeline_log.json span（run_id/git_head/step/page/status/input/output/duration） | ✅ 够用；缺 runs 裁剪（无限 append）与 status 摘要视图 |
| 失败定位 | task state | failed_step 锚点（step/page/reason）+ tickets 工单 | ✅ 够用 |
| 重试 | retry policy | 机械重译 1 次 + repair_failed ≤3 轮 + 工单 | ✅ 够用 |
| LLM 观测 | LangSmith/LiteLLM | 03 --trace（roles/tool_calls/content 前 200 字） | ✅ 够用 |
| 并发安全 | worker pool | workers=1（CLAUDE.md 铁律） | **无锁**：双跑同一 work 会竞争写 pipeline_log——补 mkdir 原子锁 |
| 强制重跑 | `--force`/`-B` | 手工删文件 | **缺 `--force-step/--force-page`** |
| 失败视图 | UI/dashboard | pipeline_log.json 裸 JSON | 缺 `06_status.py` 摘要命令（最后 N 次/失败锚点/耗时） |

**结论：缺的是 4 个 stdlib 级小件（.ok marker / 原子锁 / --force / status 视图 + 裁剪），不是框架。**

### 3. 渐进式路径（0 依赖 → 何时引第一个依赖）

**阶段 0（现在，零依赖，各 ~10 行）**：
1. `.ok` marker：产物旁写 `{name}.ok`（或产物 JSON 首字段 `"_done": true`），00_run_all 以 `.ok` 存在为断点条件——防坏产物被跳过（对齐 ADR-014 机械护栏"结构校验"）。
2. mkdir 原子锁：00_run_all 开头 `os.mkdir(state/.lock)` 捕获 `FileExistsError`，`finally: os.rmdir`——防双跑。
3. `--force-step/--force-page`：删对应产物（替代手工删）。
4. `06_status.py`：读 pipeline_log.json 打印 runs 摘要（最后 5 次、失败锚点、每步耗时），即"诊断 workflow 失败原因"的手动入口。
5. pipeline_log 裁剪：runs >50 时裁旧 run（防 JSON 无限膨胀）。

**阶段 1（仅当具体痛点出现才引第一个依赖）**：
- 自造重试逻辑膨胀（>100 行）→ **tenacity**（零运行时依赖，Apache-2.0，~100KB）——纯增量，不违反铁律精神。
- 需要跨进程锁（多脚本并行调用 00_run_all）→ **filelock**（零运行时依赖，MIT）或继续用 mkdir 原子锁。
- 断点需要更强持久化（多进程/防损坏）→ **SQLite 断点表**（内置 sqlite3，零新依赖）。

**阶段 2（规模信号出现才考虑）**：
- 真多 worker 并发（打破 workers=1 铁律）→ **GigQ**（SQLite job queue：retries/backoff/crash recovery/依赖声明）。
- 引入 LLM agent 调用编排（非确定性脚本）→ 借鉴 **owf** 的 SQLite run journal + resume 缓存语义（不引库，照抄思想——它就是零依赖的）。
- 需要跨机/可视化 DAG/团队协作 → 那时 Prefect/Dagster 才进入候选（个人项目大概率永远不到）。

### 4. 最省 1-2 个依赖（如果一定要）

- **第一候选：tenacity**（零运行时依赖，唯一有"自造会膨胀"可能的重试面）——但 AMTA 已有自造重试，大概率不需要。
- **第二候选：filelock**（零运行时依赖，唯一可能的多进程锁需求）——mkdir 原子锁可替代，大概率不需要。
- **just 不是编排器**：仅命令入口美化（`just run-all`），winget 单二进制 ~3MB；不解决 resume/tracing，**不建议为它引依赖**。
- **make 不建议**：Windows 无内置、timestamp 语义不贴合 JSON 产物。

## Verdicts

- **维持零依赖（强推）**：AMTA 现状已覆盖 resume + tracing + 失败定位 + 重试 + LLM 观测的全部核心能力，与 owf/GigQ 思想同级；补 4 个 stdlib 小件即达"个人项目够用"的完整形态。
- **不引任何 workflow 框架**：Metaflow/Prefect/Dagster/LangSmith 结论维持（ADR-018），owf/GigQ 作为"未来规模信号的参照物"记录在案。
- **第一个依赖的触发条件**：自造重试 >100 行 → tenacity；出现多进程锁需求 → filelock。两者都是零运行时依赖，符合铁律精神，且都是"替换自造代码"而非"新增框架"。

## Open questions / risks

- `.ok` marker 会改变所有工位的写文件契约（01/02/03/04/05 都要写 marker）——改造面约 5 个脚本，需回归 fastcheck。
- pipeline_log.json 在 Windows 下多进程同时写可能损坏（无 WAL 的 JSON）——mkdir 锁只防"同 work 双跑"，不防"不同 work 共享 state 目录"；实际按 work 隔离（ADR-013 per-work workspace），风险低。
- tenacity/filelock 虽是零运行时依赖，仍违反"零依赖字面铁律"——若队长坚持字面零依赖，stdlib 替代（手写 retry / mkdir 锁）完全够用，无需引。
- GigQ/owf 的具体 API 细节未实测（仅 README 级评估）——真需要时再深读。

## 一手材料

- [owf README](https://github.com/akakabrian/agent-workflows)（零依赖声明、resume/journal/budget 语义）
- [GigQ README](https://github.com/kpouianou/GigQ)（SQLite job queue、Workflow parent_results、requeue）
- [tenacity PyPI 元数据](https://pypi.org/project/tenacity/)（9.1.4，requires_dist 仅 doc/test extras → 零运行时依赖）
- [filelock PyPI](https://pypi.org/project/filelock/)（MIT）
- [casey/just](https://github.com/casey/just)（单二进制任务运行器，winget `Casey.Just`）
- 本地：amta/scripts/00_run_all.py、amta/src/amta/pipeline_log.py、amta/docs/decisions/018-pipeline-orchestrator.md
