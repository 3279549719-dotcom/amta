# 虚拟环境统一入口修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底根治"运行 Python 脚本时用错解释器（系统 Python 3.14 无依赖 vs 虚拟环境 Python 3.12 有依赖）"的重复问题，统一所有 Python 命令通过 `uv run` 执行，并在项目文档中固化规范。

**Architecture:** 三层防护：(1) `uv run` 作为技术统一入口——自动识别 `.venv`、使用正确 Python 版本、加载所有依赖；(2) AGENTS.md / CLAUDE.md 文档规范——明确告知所有 AI 代理必须用 `uv run`；(3) `run.ps1` 包装脚本——为最常用的管线命令提供短命令入口，内部强制 `uv run`。

**Tech Stack:** uv 0.11.28, Python 3.12 (.venv), PowerShell, Markdown

---

## 问题根因（调查结果）

| 项 | 系统 Python | 项目 .venv |
|---|---|---|
| 版本 | 3.14.7 | 3.12.12 |
| requests | ❌ 未安装 | ✅ 2.34.2 |
| pillow | ❌ 未安装 | ✅ 12.3.0 |
| numpy | ❌ 未安装 | ✅ 2.5.2 |
| hayai-ocr | ❌ 未安装 | ✅ 2.1.0 |

- 项目无 `.python-version`、无 `Makefile`、无 `justfile`、无任何自动激活机制
- `just` 命令未安装，不可用
- `uv run python` 已验证：自动使用 .venv 的 Python 3.12.12，所有依赖正常 import
- 常用入口脚本 27+ 个（scripts/00_run_all, 01_detect, 02_ocr, 03_translate, 04_inpaint, 05_typeset, gen_*, run_*）

## 文件结构

| 操作 | 文件 | 职责 |
|---|---|---|
| Modify | `AGENTS.md` | 添加"Python 运行规范"章节，强制 `uv run` |
| Modify | `CLAUDE.md` | 同步添加运行规范 |
| Create | `run.ps1` | 常用命令包装脚本（管线全跑、单阶段、报告生成） |
| Verify | `scripts/04_inpaint.py` | 用 `uv run` 验证可正常运行 |
| Verify | `scripts/gen_stage4_report.py` | 用 `uv run` 验证可正常运行 |

---

### Task 1: 验证 uv run 能运行项目脚本

**Files:**
- Verify: `scripts/04_inpaint.py`
- Verify: `scripts/gen_stage4_report.py`
- Verify: `scripts/00_run_all.py`

- [ ] **Step 1: 用 uv run 运行 04_inpaint.py --help**

Run:
```powershell
cd "E:\manga translator agent\amta"
uv run python scripts/04_inpaint.py --help
```

Expected: 输出 usage 信息，包含 `--refine-mask` 和 `--engine` 参数，无 ModuleNotFoundError。

- [ ] **Step 2: 用 uv run 运行 gen_stage4_report.py（验证依赖加载）**

Run:
```powershell
cd "E:\manga translator agent\amta"
uv run python -c "from amta.text_mask_refiner import refine_text_mask; from amta.report.stages.mask import from_mask; from amta.report.stages.inpaint import from_inpaint; print('all imports OK')"
```

Expected: 输出 `all imports OK`，无 ImportError。

- [ ] **Step 3: 对比系统 python（确认问题仍然存在，反衬 uv run 的必要性）**

Run:
```powershell
cd "E:\manga translator agent\amta"
python -c "import requests" 2>&1
```

Expected: `ModuleNotFoundError: No module named 'requests'`（确认系统 Python 确实不能用，uv run 是唯一正确入口）。

---

### Task 2: 在 AGENTS.md 添加运行规范

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: 读取当前 AGENTS.md 末尾内容**

Run:
```powershell
cd "E:\manga translator agent\amta"
Get-Content AGENTS.md -Tail 20
```

Expected: 显示文件末尾内容，确认追加位置。

- [ ] **Step 2: 在 AGENTS.md 末尾追加"Python 运行规范"章节**

Append to `AGENTS.md`:

```markdown

---

## Python 运行规范（强制）

**所有 Python 命令必须通过 `uv run` 执行，禁止直接使用 `python` 或 `python.exe`。**

### 为什么
- 系统 Python 是 3.14，没有安装任何项目依赖（requests / pillow / numpy / hayai-ocr）
- 项目虚拟环境 `.venv` 是 Python 3.12，所有依赖已安装
- 直接用 `python script.py` 会报 `ModuleNotFoundError`
- `uv run` 会自动识别 `.venv`、使用正确 Python 版本、加载所有依赖

### 正确写法
```powershell
# 运行脚本
uv run python scripts/04_inpaint.py --work-id xxx --det xxx.json --raw xxx.jpg --out xxx.json

# 运行模块
uv run python -c "import requests; print(requests.__version__)"

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
```
```

- [ ] **Step 3: 验证追加成功**

Run:
```powershell
cd "E:\manga translator agent\amta"
Select-String -Path AGENTS.md -Pattern "uv run" | Select-Object -First 5
```

Expected: 至少匹配到 3 行包含 "uv run" 的内容。

---

### Task 3: 在 CLAUDE.md 同步添加规范

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 读取当前 CLAUDE.md 末尾内容**

Run:
```powershell
cd "E:\manga translator agent\amta"
Get-Content CLAUDE.md -Tail 15
```

Expected: 显示文件末尾内容。

- [ ] **Step 2: 在 CLAUDE.md 末尾追加运行规范摘要**

Append to `CLAUDE.md`:

```markdown

---

## Python 运行规范（强制）

所有 Python 命令必须用 `uv run python`，禁止直接用 `python`。系统 Python 3.14 无依赖，项目 .venv 是 Python 3.12 有全部依赖。`uv run` 自动选对解释器。详见 AGENTS.md。
```

- [ ] **Step 3: 验证追加成功**

Run:
```powershell
cd "E:\manga translator agent\amta"
Select-String -Path CLAUDE.md -Pattern "uv run"
```

Expected: 匹配到包含 "uv run" 的行。

---

### Task 4: 创建 run.ps1 包装脚本

**Files:**
- Create: `run.ps1`

- [ ] **Step 1: 创建 run.ps1**

Write `E:\manga translator agent\amta\run.ps1`:

```powershell
<#
.SYNOPSIS
    AMTA 项目统一命令入口 — 内部强制使用 uv run，杜绝用错 Python 解释器。

.DESCRIPTION
    常用命令包装：
      .\run.ps1 all --pages 1-5           跑全管线(detect+ocr+translate+inpaint+typeset)
      .\run.ps1 detect --pages 1-5        只跑 detect
      .\run.ps1 ocr --pages 1-5           只跑 ocr
      .\run.ps1 translate --pages 1-5     只跑 translate
      .\run.ps1 inpaint --pages 11-20     只跑 inpaint(精修mask+lama-manga)
      .\run.ps1 typeset --pages 1-5       只跑 typeset
      .\run.ps1 report                     生成 stage4 验证报告
      .\run.ps1 test                       跑 pytest
      .\run.ps1 python -c "..."           透传任意 python 命令(自动 uv run)

.NOTES
    所有命令内部都用 uv run python，确保使用项目 .venv(Python 3.12)和全部依赖。
    禁止在项目目录下直接用 python script.py，会用系统 Python 3.14 导致 ModuleNotFoundError。
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("all","detect","ocr","translate","inpaint","typeset","report","test","python")]
    [string]$Command,

    [Parameter(Position=1, ValueFromRemainingArguments=$true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$WorkId = "amta-run"
$SrcDir = "D:\我的汉化\汉化作品\东方\单翼停留之地"

function Invoke-UvPython {
    param([string[]]$CmdArgs)
    $fullArgs = @("run", "python") + $CmdArgs
    & uv @fullArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Parse-Pages {
    param([string]$PagesStr)
    if ($PagesStr -match "^(\d+)-(\d+)$") {
        return @($Matches[1], $Matches[2])
    }
    Write-Error "无效的页码格式: '$PagesStr'，应为 如 1-5 或 11-20"
}

switch ($Command) {
    "all" {
        $start, $end = Parse-Pages $Args[0]
        Invoke-UvPython @("scripts/00_run_all.py", "--work-id", $WorkId,
            "--src-dir", $SrcDir, "--start-page", $start, "--end-page", $end,
            "--with-inpaint", "--with-typeset")
    }
    "detect" {
        $start, $end = Parse-Pages $Args[0]
        for ($n = $start; $n -le $end; $n++) {
            Invoke-UvPython @("scripts/01_detect.py", "--raw", "$SrcDir\$n.jpg",
                "--out", "output\tmp\detect\page_$n`_detection.json")
        }
    }
    "ocr" {
        Write-Output "ocr 阶段通过 00_run_all 调用，暂不支持单独跑"
    }
    "translate" {
        Write-Output "translate 阶段通过 00_run_all 调用，暂不支持单独跑"
    }
    "inpaint" {
        $start, $end = Parse-Pages $Args[0]
        Invoke-UvPython @("scripts/run_stage4_e2e_11_20.py")
        Write-Output "注意: run_stage4_e2e_11_20.py 内部硬编码了 11-20 页范围"
    }
    "typeset" {
        Write-Output "typeset 阶段通过 00_run_all 调用，暂不支持单独跑"
    }
    "report" {
        Invoke-UvPython @("scripts/gen_stage4_report.py")
    }
    "test" {
        & uv run pytest @Args
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "python" {
        Invoke-UvPython $Args
    }
    default {
        Write-Output "用法: .\run.ps1 <command> [args]"
        Write-Output "命令: all, detect, ocr, translate, inpaint, typeset, report, test, python"
        Write-Output "示例: .\run.ps1 all --pages 1-5"
        Write-Output "      .\run.ps1 report"
        Write-Output "      .\run.ps1 python -c `"import requests; print('ok')`""
    }
}
```

- [ ] **Step 2: 验证 run.ps1 可执行**

Run:
```powershell
cd "E:\manga translator agent\amta"
.\run.ps1 python -c "import requests, PIL, numpy; print('run.ps1 uv run OK:', requests.__version__)"
```

Expected: 输出 `run.ps1 uv run OK: 2.34.2`，无错误。

- [ ] **Step 3: 验证 run.ps1 report 命令**

Run:
```powershell
cd "E:\manga translator agent\amta"
.\run.ps1 report
```

Expected: 输出生成报告的日志，最终输出 `报告生成完成`，无 ModuleNotFoundError。

---

### Task 5: 端到端验证

**Files:**
- Verify: 全流程

- [ ] **Step 1: 用 uv run 运行 04_inpaint.py --dry-run（验证完整脚本加载）**

Run:
```powershell
cd "E:\manga translator agent\amta"
uv run python scripts/04_inpaint.py --work-id test --det workspace/touhou-single-wing-fresh/artifacts/page_10_detection.json --raw "D:\我的汉化\汉化作品\东方\单翼停留之地\11.jpg" --out output\tmp\test_dryrun.json --dry-run
```

Expected: 输出 `[04_inpaint] page_10: filled=... inpainted=...`，无错误，生成 dry-run 的 json 文件。

- [ ] **Step 2: 清理 dry-run 测试文件**

Run:
```powershell
cd "E:\manga translator agent\amta"
Remove-Item output\tmp\test_dryrun.json -ErrorAction SilentlyContinue
Write-Output "cleaned"
```

- [ ] **Step 3: 最终确认——系统 python 仍然不能用（反衬规范必要性）**

Run:
```powershell
cd "E:\manga translator agent\amta"
python -c "import amta" 2>&1
```

Expected: `ModuleNotFoundError`（确认系统 Python 确实不能直接用项目代码，必须 uv run）。

---

### Task 6: Commit

**Files:**
- 所有修改和新增文件

- [ ] **Step 1: 查看变更**

Run:
```powershell
cd "E:\manga translator agent\amta"
git status --short
```

Expected: 显示 AGENTS.md, CLAUDE.md (modified), run.ps1 (untracked)。

- [ ] **Step 2: Add 和 Commit**

Run:
```powershell
cd "E:\manga translator agent\amta"
git add AGENTS.md CLAUDE.md run.ps1
git commit -m "chore: 统一 Python 运行入口为 uv run，根治用错解释器问题

- AGENTS.md: 添加强制运行规范（所有 Python 命令必须 uv run）
- CLAUDE.md: 同步规范摘要
- run.ps1: 新增统一命令入口（all/detect/inpaint/report/test/python），内部强制 uv run
- 根因: 系统 Python 3.14 无依赖，项目 .venv Python 3.12 有全部依赖
- 验证: uv run python 可正常 import 所有依赖，系统 python 报 ModuleNotFoundError"
```

Expected: commit 成功，输出 commit hash。

---

## Self-Review

**1. Spec coverage:**
- ✅ 调查清楚问题根因（系统 Python 3.14 无依赖 vs .venv Python 3.12 有依赖）
- ✅ 一次性修好（三层防护：uv run 技术入口 + 文档规范 + run.ps1 包装）
- ✅ 验证步骤完整（每个任务都有验证命令和预期输出）

**2. Placeholder scan:**
- ✅ 无 TBD/TODO
- ✅ 所有代码步骤都有完整代码
- ✅ 所有命令都有预期输出

**3. Type consistency:**
- ✅ run.ps1 中的命令名和实际脚本名一致
- ✅ AGENTS.md 和 CLAUDE.md 中的规范描述一致
- ✅ 路径统一使用项目绝对路径

**4. 风险提示:**
- run.ps1 中的 inpaint 命令目前调用的是硬编码 11-20 页的脚本，后续可优化为支持任意页码范围
- detect 单独跑的输出路径是 output/tmp/detect/，和主管线的 artifacts 目录不一致，后续可统一
- 这些是已知限制，不影响本次"根治用错解释器"的核心目标
