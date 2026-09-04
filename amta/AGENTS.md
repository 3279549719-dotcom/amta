# AGENTS.md

> 规范本体是 `CLAUDE.md`（本文件仅作入口，避免双份漂移）。CLAUDE.md 全文自动加载，含核心事实 + 坑 + 渐进式加载表。

AMTA：会话驱动漫画翻译自动化——DSH 会话=导演，amta Python=执行器，koharu v0.59.1 headless（:4000）=引擎。翻译走 03_translate 脚本直调 DeepSeek API（ADR-014，弃 koharu 内 llm 引擎）；VQA 走 vqa() 抽象（describe_image）。

**最致命坑**：钉 0.59.1；`comic-text-detector-seg` 只细化已有文字框，前置 detector 漏检则 OCR/mask/inpaint 全漏（`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶）。

细节（接口/流程/坑全表）→ 读 `CLAUDE.md`；按需技能见 `.dsh/skills/`（DSH 原生技能根，进 skill catalog 按需加载）。

---

## Python 运行规范（强制）

**所有 Python 命令必须通过 `uv run` 执行，禁止直接使用 `python` 或 `python.exe`。**

### 为什么
- 系统 Python 是 3.14，没有安装任何项目依赖（requests / pillow / numpy / hayai-ocr）
- 项目虚拟环境 `.venv` 是 Python 3.12，所有依赖已安装
- 直接用 `python script.py` 会报 `ModuleNotFoundError`
- `uv run` 会自动识别 `.venv`、使用正确 Python 版本、加载所有依赖
- 项目包在 `src/` 下，运行模块时需设 `PYTHONPATH=src`（项目脚本内部已自动处理）

### 正确写法
```powershell
# 运行脚本
uv run python scripts/04_inpaint.py --work-id xxx --det xxx.json --raw xxx.jpg --out xxx.json

# 运行模块（需设PYTHONPATH）
$env:PYTHONPATH="src"; uv run python -c "import requests; print(requests.__version__)"

# 运行 pytest
uv run pytest tests/ -v
```

### 错误写法（禁止）
```powershell
python scripts/04_inpaint.py ...          # ❌ 用了系统 Python 3.14，无依赖
python -c "import requests"                 # ❌ 同上
.venv\Scripts\python.exe script.py          # ⚠️ 能用但冗长，统一用 uv run
```

### 常用短命令（通过 run.ps1）
```powershell
.\run.ps1 inpaint --pages 11-20    # 跑 inpaint 阶段
.\run.ps1 report                     # 生成 stage4 报告
.\run.ps1 all --pages 1-5           # 跑全管线
.\run.ps1 python -c "..."           # 透传任意 python 命令（自动 uv run）
```

---

## Ralph Loop 运行规范（强制）

> 第二次 Ralph Loop（2026-09-04）收束的规章制度。所有通过 Ralph Loop 执行的任务必须遵守。

### 1. fastcheck 是合并门禁

- `main` 分支必须保持 `py -3.13 scripts/fastcheck.py` **ALL PASS**。
- pre-commit git hook 必须正确安装（`git config core.hooksPath .githooks`）。
- Claude Code **PreToolUse hook**（`.claude/settings.json`）在 git commit/merge 前自动跑快速 fastcheck（compile + ruff + pyright），FAIL 则阻止。
- 新分支合并前必须修复所有 fastcheck 违规，**不允许带 FAIL 合并进 main**。

### 2. 任务必须有可自动验证的验收标准 + 不降级约束

- 每次 Ralph Loop 启动前，`loop_state.json` 必须写清楚：
  - `mission`：整体目标和范围
  - `next_action`：本次迭代具体做什么
  - 验收标准：可自动验证的完成标志（如 fastcheck ALL PASS、pytest N passed）
- **不降级约束**：pytest 通过数不能比基线少；修类型/lint 不能把功能修挂。
- 任务范围必须限定，不允许 loop 跑飞（"只修 fastcheck 违规，不重构"）。

### 3. 三个决策点必须等人确认

Ralph Loop 全自主推进，但以下三个节点必须暂停，等人类确认：

| 决策点 | 说明 |
|---|---|
| **删除文件** | 任何 `rm` / `git rm` / 删除模块的操作 |
| **依赖声明 / 基准方案变更** | 修改 `pyproject.toml` 依赖、变更架构选型、变更核心流程 |
| **合并回 main** | 分支完成后，合并进 main 前必须人类验收 |

其余所有操作（写代码、跑测试、修 bug、写文档、commit 到 feature 分支）Ralph 全自主。

### 4. bug 不累积

- fastcheck 违规必须在**引入它的分支内**修复，不允许带进 main。
- "不是本次产生的 bug"不能成为留在 main 上的理由——要么在本次 loop 中修复，要么在 `loop_state.escalation` 中明确列为待办，下次 loop 处理。
- main 分支长期处于 fastcheck FAIL 状态是不可接受的。

### Hook 配置

- **SessionStart hook**：新会话自动跑 `memory_inject.py` + 输出项目状态（分支、git status、最近 commit、loop_state 摘要）。脚本：`scripts/hook_sessionstart.py`
- **PreToolUse hook**：git commit/merge 前自动跑快速 fastcheck，FAIL 阻止。脚本：`scripts/hook_pretooluse.py`
- 配置文件：`.claude/settings.json`（随 git 提交，团队共享）
