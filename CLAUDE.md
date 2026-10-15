# CLAUDE.md

AMTA — 会话驱动的漫画翻译自动化。DSH 会话=导演（决策/翻译判断/修复决策/验收），amta Python=确定性工具层。

> **设计原则**：本文档是"宪法"，只写不变的原则和指针。易变的事实（路径、配置、模型位置）不写在这里——它们由代码自动检查（环境自检门卫）或运行时参数指定。如果发现本文档有具体路径/配置，那就是腐化了，应该移走。

## 核心原则
- **执行边界**：默认 detect/ocr/inpaint/typeset 在本地执行，translate 调用 LLM API；显式选择 VLM OCR 的页面会向视觉 API 发送整页与裁图。PSD 导出依赖本机 Photoshop。
- **环境自检门卫（Embedded）**：`run_pipeline.py` 启动时自动检查环境（代理、模型、.env、ROOT 路径），不可达的代理自动关闭，有问题直接报错。**不需要 AI 手动检查环境**
- **找产物用 artifact，跑管线用 run_pipeline，看管线现状用 `peek`**——这三个是唯一入口，禁止自己拼 01/02/03 脚本。找代码/找符号用原生 grep + `docs/module-map.md`

## 关键入口（指针）
| 用途 | 命令 | 说明 |
|---|---|---|
| 跑管线 | `uv run python scripts/run_pipeline.py --work-id <id> --src-dir <dir> --start-page N --end-page M --stages <阶段>` | 启动时自动环境自检；阶段：detect,ocr,translate,inpaint,typeset,segment（`segment` 是占位阶段，已注册未接，调用会报错）；上游产物已存在时**可只跑下游**（如 `--stages typeset`，上游自动从磁盘读，不用全列）；但 detect/ocr 是非确定性的——一旦缓存失效被迫重跑会改 canon，重排 typeset 前先确认 OCR 产物是你要冻结的那版；artifact_cache 自动跳过未变更阶段 |
| 搞懂代码现状 | `uv run python scripts/peek.py` | 打印当前 stage/engine/上下游/占位与孤儿阶段（读当前源码，非文档）。**它只干这件事**：找模块/函数/类用 grep，模块总览读 `docs/module-map.md` |
| 批量改导入路径 | `uv run python scripts/refactor_module.py --old <旧点路径> --new <新点路径> [--dry-run] [--test]` | 重命名模块时用，禁止手改 imports（深接口工具，`--dry-run` 先预览） |
| 找产物 | `uv run python scripts/artifact.py {query\|find\|invalidate} ...` | **一个 `query` 原语覆盖所有查询场景**：`--work-id <id>` 或 `--all`，可选 `--stage`/`--page`/`--format {json,table}`。`find` 是兼容层（要 `--stage`+`--page`+`--artifacts-dir`）。`invalidate` 失效单页缓存（要 `--work-id`+`--page`）。**拿不准先 `--help`，别照抄本行** |
| 生成报告 | `uv run python scripts/gen_report.py --work-id <id> --src-dir <dir> --pages N-M` | 验收唯一视觉载体（前三个参数**必填**）；深接口：再叠加 `--granularity page\|region` + `--stages raw,detect,ocr,translate,inpaint,typeset` 自由组合 |
| 分享文件 | `uv run python scripts/share_file.py --file <路径>` | 一键上传到飞书云空间并生成公网链接（互联网任何人可阅读）；手机端查看产物时必用，禁止给本地路径 |
| 质检 | `uv run python scripts/fastcheck.py` | 收尾必跑 |
| 记忆检索 | `uv run python scripts/memory.py {read|grep|index|recent|status|lint|gc|inject}` | 先查记忆再动手，别重踩坑。`grep` 全库检索 / `read` 按 ID 深读（L<n> / ADR-n）/ `inject` 刷新 DSH 注入包 |

## 必执行 Checklist（chained，AI 自主触发）
- **对话结束**：走 **cycle-close** 协议收尾。落盘唯一入口 `state.py finish "summary"`——**它内置全量质检，红了拒绝提交**（急用 `--skip-check`），不需要手动 git add/commit。npm 别名见 `package.json`，不在此处复述
- **改到一半**：`fastcheck.py --quick` 秒级只读快检，不用等收尾（pre-commit 跑的就是它，两条路同一扇门）
- 搞懂代码现状：**先 `peek` 看管线全貌，再用 grep / `docs/module-map.md` 定位模块**，然后才读目标文件；不要先翻 workspace/ 旧产物。读一个阶段按这个顺序：`src/amta/orchestrator/registry.py` 的 StageSpec（契约）→ `src/amta/orchestrator/adapters/<阶段>.py`（薄入口）→ 对应 station → 深模块；想知道"为什么这么设计"用 `memory.py grep --scope decisions <阶段名>`
- 找产物/查缓存/列某阶段文件：**用 `artifact.py`**，禁止翻目录
- 遇到报错/异常/测试失败：**先按 diagnosing-bugs skill 流程定位根因**，禁止直接猜答案
- 做架构/选型决策前：先核对现有代码、产物和相关 ADR；只有关键取舍需要用户判断时才提问
- 需要外部信息/调研：先查可用的直接来源；只有独立调研能增加证据时才委派
- 跑管线：**用 `run_pipeline.py`**，启动时自动环境自检，不需要手动检查代理/.env/模型
- 验收画面质量或修改 OCR、翻译、修复、排版时：用 `gen_report.py` 对相关页和区域做视觉核对；纯 CLI/文档任务不必生成报告

## 渐进式加载（遇到 X → 先做 Y）
| 症状 / 场景 | 先做 |
|---|---|
| 任何报错 / 测试失败 / 行为异常 | `memory.py grep --query "<关键词>"`（先搜 lessons，别重踩） |
| 接手任务 / 不知道停在哪 | `memory.py recent` |
| 架构 / 选型决策前 | `memory.py grep --scope decisions --query "<主题>"` |
| docs 导航 | `docs/lessons.md`（坑）｜`docs/decisions/`（ADR）｜`docs/module-map.md`（代码地图） |
| 想新增守卫 / hook / 工具 | `docs/friction.md`（不顺账；没有对应账目的机制不建） |

## 工作协议
- **收尾规程单一真相源**：收尾怎么做，只有一处定义——`cycle-close` skill（正文）；收尾的**执行入口**只有 `state.py finish`。任何人（含 AI）不得在别处写第二套等价步骤——`tests/test_harness_covenant.py` 的 H7 会拦。
- **知识晋升五路分流**：全局规则(CLAUDE.md)·流程(.dsh/skills/)·架构(docs/decisions/ADR-N)·机械(test/lint/hook)；test/lint/hook 是唯一真强制层
- **机械护栏分层**：pre-commit `fastcheck --quick`（秒级，**不含 pytest**，只读不写文件）→ `state.py finish` 强制跑完整（含 pytest/depguard/memory/**module-map 刷新**）→ pre-push 无强制检查。安装：`scripts/install_hooks.ps1`。
  ⚠️ **--quick 不是门槛，是门槛的一半**：2026-09-10 事故——脚本清理后 12 条测试永久变红、无人察觉约两天，因为唯一的 commit 拦截层只跑 --quick。**"通过了"必须说明跑的是哪一层。**
- **指针必须指向活着的东西**：本项目跑在 DSH 上。CC 方言的 hook 层已于 2026-09-12 **整体移除**（`.claude/settings.json`、`.claude/settings.local.json`、`scripts/hook_pretooluse.py`、`scripts/hook_sessionstart.py`）——它们声明的机制在 DSH 下**从未触发过**，是"看起来已生效"的死配置。最后一份 CC 方言文件 `.mcp.json` 与它的接线脚本 `scripts/install_dsh_mcp.ps1` 已于 2026-09-16 一并删除：`.mcp.json` 一直是空的 `{}`，而脚本**从不读它**（"输入源"的说法是错的）；脚本写进 DSH 的注册块指向现已归档到 `scripts/archive/mcp_memory.py` 的那份字典 server → 连接必然失败、死了两天无人察觉、存活期调用为 0（新增前置：**MCP 服务器不得只靠散文声明**，若再引入必须配连接性探针）。历史与理由见 lessons `L11`/`L34` 与 ADR-027 后记。
- **新机制准入（不顺账）**：新增守卫/hook/工具前，先在 `docs/friction.md` 记一条账——必须是白天真实卡过的一次，且**能被一条命令判定真假**、**拦下过一次真实事故**；**预防性机制一律不建**（一个坏了 N 天没人发现的机制，等于没人用，该删）。
- **Harness 契约**：任何"某机制已生效"的声明都必须配一条能跑的探针——契约条款与探针焊在 `tests/test_harness_covenant.py`（H1 单一 Python 入口 / H2 声明的 hook 必须真被加载 / H3 排除名单不得有死路径 / H4 git hook 引用必须存在 / H5 契约自身无孤儿条款 / H6 改动不得夹带行尾噪声 / H7 收尾规程单一真相源）。**新增声明 = 新增条款 + 新增探针，不接受只有散文的声明。**
- **知识落地**：可复用经验落 `docs/lessons.md`（坑）或 `docs/decisions/ADR-N`（决策）；检索一律 `memory.py grep/read`
- **HTML 报告铁律**：必须用 `src/amta/report/` 深接口，禁止 scripts/ 下新建独立 HTML 生成脚本
- **CLI 工具原语化铁律**：工具必须提供可组合的原语（数据加载+处理原语+布局），禁止枚举使用场景（`--type a/b/c/d`）。新增需求 = 原语的新组合，不是新的 `--type`。反例：旧 gen_report 有 5 种写死类型，加"原图+干净图对比"得写第 6 种；正例：新 gen_report 只有 `--granularity page|region` + `--stages`，任意组合。
- **模型推理设备铁律**：所有模型推理阶段必须自动检测设备（`cuda if available else cpu`），禁止硬编码 `device="cpu"`。换 GPU 环境后应自动提速，不需要改代码。

## Python 运行规范（强制）
所有 Python 命令用 `uv run python`，禁止裸 `python`（系统 Python 无依赖，`.venv` 是 3.12）。项目包在 `src/` 下，脚本内部已自动处理 PYTHONPATH。

## 编码风格（强制）
- Python 3.12，四空格缩进，type hints，小公共接口。Ruff + Pyright 强制风格与类型。
- `snake_case` 模块/函数，`PascalCase` 类，`test_<行为>` 测试。
- 每个 bug fix 加回归测试（artifact 契约、stage 依赖、渲染行为）。fixture 保持小，**永远不提交整页漫画图**。
- 提交信息用 Conventional Commit：`feat(scope):` / `fix(scope):` / `refactor(scope):` / `docs(scope):` / `chore(scope):`。每个 commit 聚焦一件事。
