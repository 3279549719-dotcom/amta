# CLAUDE.md

AMTA — 会话驱动的漫画翻译自动化。DSH 会话=导演（决策/翻译判断/修复决策/验收），amta Python=确定性工具层。

> **设计原则**：本文档是"宪法"，只写不变的原则和指针。易变的事实（路径、配置、模型位置）不写在这里——它们由代码自动检查（环境自检门卫）或运行时参数指定。如果发现本文档有具体路径/配置，那就是腐化了，应该移走。

## 核心原则
- **全管线纯本地执行**：只有 translate 阶段需要 LLM API，其他阶段（detect/ocr/inpaint/typeset）全本地，不需要任何外部服务（ADR-029）
- **环境自检门卫（Embedded）**：`run_pipeline.py` 启动时自动检查环境（代理、模型、.env、ROOT 路径），不可达的代理自动关闭，有问题直接报错。**不需要 AI 手动检查环境**
- **找代码用 find_code，找产物用 artifact，跑管线用 run_pipeline**——这三个是唯一入口，禁止用 Glob/grep 瞎找，禁止自己拼 01/02/03 脚本

## 关键入口（指针）
| 用途 | 命令 | 说明 |
|---|---|---|
| 跑管线 | `uv run python scripts/run_pipeline.py --work-id <id> --src-dir <dir> --start-page N --end-page M --stages <阶段>` | 启动时自动环境自检；阶段：detect,ocr,translate,inpaint,typeset；**必须包含所有上游依赖阶段**（跑 typeset 必须含 detect,ocr,translate,inpaint）；artifact_cache 自动跳过未变更阶段 |
| 找代码 | `uv run python scripts/find_code.py <关键词>` | 搜索模块/函数/类，禁止瞎猜路径或硬 grep |
| 找产物 | `uv run python scripts/artifact.py {find\|list\|status\|invalidate} ...` | 参数按子命令不同：`find` 要 `--stage`+`--page`；`list` 要 `--stage`；`status`/`invalidate` **不接受 `--stage`**（`invalidate` 要 `--page`）。公共参数 `--work-id <id>`。拿不准先 `--help`，别照抄本行 |
| 对话状态 | `uv run python scripts/state.py {bootstrap\|finish}` | 对话开始 `bootstrap` 读 git+env+diff 状态（统一格式）；对话结束 `finish "summary"` 落盘——**它会先跑完整质检，红了就拒绝提交**（急用时 `--skip-check`）；替代 progress.md，不需要手动跑 git log |
| 生成报告 | `uv run python scripts/gen_report.py` | 验收唯一视觉载体 |
| 质检 | `uv run python scripts/fastcheck.py` | 收尾必跑 |
| 记忆检索 | `uv run python scripts/memory.py {grep|recent|status}` | 先查记忆再动手，别重踩坑 |

## 必执行 Checklist（chained，AI 自主触发）
- **对话开始**：先跑 `state.py bootstrap` 读取当前状态（git log + diff + status + env），不需要手动跑 git log，不需要读 progress.md
- **对话结束**：用 `state.py finish "summary"` 落盘——**它内置完整质检，红了拒绝提交**，所以"全量门槛没跑"在机制上不可能再发生；不需要手动 git add/commit
- 找代码/模块/函数位置：**先用 `find_code.py <关键词>`**，再读目标文件
- 找产物/查缓存/列某阶段文件：**用 `artifact.py`**，禁止翻目录
- 遇到报错/异常/测试失败：**先按 diagnosing-bugs skill 流程定位根因**，禁止直接猜答案
- 做架构/选型决策前：**先调用 grilling skill 至少 3 轮苏格拉底追问**
- 需要外部信息/调研：**委派 research skill 后台 subagent**
- 跑管线：**用 `run_pipeline.py`**，启动时自动环境自检，不需要手动检查代理/.env/模型
- 管线完成后：**自动调用 `gen_report.py` 生成报告**
- 会话结束/收尾：**先 cycle-close，委派 finisher subagent 做知识归类**

## 渐进式加载（遇到 X → 先做 Y）
| 症状 / 场景 | 先做 |
|---|---|
| 任何报错 / 测试失败 / 行为异常 | `memory.py grep --query "<关键词>"`（先搜 lessons，别重踩） |
| 接手任务 / 不知道停在哪 | `memory.py recent` |
| 架构 / 选型决策前 | `memory.py grep --scope decisions --query "<主题>"` |
| docs 导航 | `docs/README.md`（分工）｜`docs/lessons.md`（坑）｜`docs/decisions/`（ADR）｜`docs/module-map.md`（代码地图） |

## 工作协议
- **任务收尾走 /finish**（cycle-close）：复读任务→审查 diff→确定性验证→修复→反思→知识晋升→只更新真正变化的工件→Finish Report→git 落盘
- **知识晋升五路分流**：全局规则(CLAUDE.md)·流程(.dsh/skills/)·架构(docs/decisions/ADR-N)·机械(test/lint/hook)；test/lint/hook 是唯一真强制层
- **机械护栏分层**：pre-commit `fastcheck --quick`（秒级，**不含 pytest**，只读不写文件）→ `state.py finish` 强制跑完整（含 pytest/depguard/memory/audit/**module-map 刷新**）→ pre-push 只跑可选 smoke。安装：`scripts/install_hooks.ps1`。
  ⚠️ **--quick 不是门槛，是门槛的一半**：2026-09-10 事故——脚本清理后 12 条测试永久变红、无人察觉约两天，因为唯一的 commit 拦截层只跑 --quick。**"通过了"必须说明跑的是哪一层。**
- **指针必须指向活着的东西**：本项目跑在 DSH 上，而 `.claude/`（settings.json hooks）与 `.mcp.json` 是 **Claude Code 方言，DSH 不读**。**具体哪些路径失效、以及当初为什么决定不装 CC hook 桥，见 lessons `L11`**——此处只留指针不复述，免得又长出一份要同步的漂移。推论：任何"某机制已生效"的声明都必须配一条能跑的探针
- **知识落地**：可复用经验落 `docs/lessons.md`（坑）或 `docs/decisions/ADR-N`（决策）；检索一律 `memory.py grep/read`
- **HTML 报告铁律**：必须用 `src/amta/report/` 深接口，禁止 scripts/ 下新建独立 HTML 生成脚本
- **CLI 工具原语化铁律**：工具必须提供可组合的原语（数据加载+处理原语+布局），禁止枚举使用场景（`--type a/b/c/d`）。新增需求 = 原语的新组合，不是新的 `--type`。反例：旧 gen_report 有 5 种写死类型，加"原图+干净图对比"得写第 6 种；正例：新 gen_report 只有 `--granularity page|region` + `--stages`，任意组合。
- **模型推理设备铁律**：所有模型推理阶段必须自动检测设备（`cuda if available else cpu`），禁止硬编码 `device="cpu"`。换 GPU 环境后应自动提速，不需要改代码。

## Python 运行规范（强制）
所有 Python 命令用 `uv run python`，禁止裸 `python`（系统 Python 无依赖，`.venv` 是 3.12）。项目包在 `src/` 下，脚本内部已自动处理 PYTHONPATH。详见 AGENTS.md。
