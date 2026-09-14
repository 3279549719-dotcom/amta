<#
.SYNOPSIS
    AMTA 便捷入口 — 强制走 uv run，杜绝用错 Python。

.DESCRIPTION
    ## 2026-09-12 大扫除记录（重要）

    本脚本原有 9 个分支，其中 5 个（all / detect / ocr / translate / typeset）
    调用 `scripts/00_run_all.py` / `01_detect.py` / `02_ocr.py` / `03_translate.py`——
    **这些编号脚本早已全部删除**（统一入口变成了 `scripts/run_pipeline.py`）。
    那 5 个分支里，两个直接报 FileNotFound，三个打印
    "runs via 00_run_all, not supported standalone yet"——把人指向一个不存在的东西。

    这就是"手写路径清单必然腐烂"的又一个实例：删脚本时没有任何机械检查盯着本文件。
    现已接入守卫（`tests/test_reference_integrity.py` 的 S4）：操作文档/脚本里点名的
    `scripts/*.py` 必须真实存在，否则测试变红。**以后删脚本，不要再靠记性。**

    ## 2026-09-14 二次清理

    inpaint 分支（run_stage4_e2e_11_20.py）和 report 分支（gen_stage4_report.py）
    指向的脚本均已归档到 scripts/archive/，两个分支移除。生成报告请直接用统一入口
    `scripts/gen_report.py`。

    ## 跑管线请用统一入口（不在本脚本里）

        uv run python scripts/run_pipeline.py --work-id <id> --src-dir <dir> `
            --start-page N --end-page M --stages detect,ocr,translate,inpaint,typeset

    详见 CLAUDE.md 的「关键入口」表。本脚本只保留真正还成立的几个便捷分支。

.NOTES
    所有 Python 命令走 `uv run python`，确保用项目 .venv。
#>

# 无 param() 块：用 $args 避免 PowerShell 参数前缀匹配歧义
# （例如 -c 会歧义匹配 -Command）。$args[0] = 命令，其余为参数。
$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

$Command = if ($args.Count -gt 0) { $args[0] } else { "" }
$CmdArgs = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }

$validCommands = @("test", "python")
if ($Command -and ($validCommands -notcontains $Command)) {
    Write-Output "Unknown command: '$Command'"
    $Command = ""
}

function Invoke-UvPython {
    param([string[]]$CmdArgs)
    $fullArgs = @("run", "python") + $CmdArgs
    & uv @fullArgs
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

switch ($Command) {
    "test" {
        & uv run pytest @CmdArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "python" {
        Invoke-UvPython $CmdArgs
    }
    default {
        Write-Output "Usage: .\run.ps1 COMMAND [args]"
        Write-Output ""
        Write-Output "Commands:"
        Write-Output "  test                 Run pytest"
        Write-Output '  python -c "..."      Pass through any python command (auto uv run)'
        Write-Output ""
        Write-Output "跑管线用统一入口（不在这里）："
        Write-Output "  uv run python scripts/run_pipeline.py --work-id <id> --src-dir <dir> --start-page N --end-page M --stages <阶段>"
        Write-Output ""
        Write-Output "生成报告用统一入口："
        Write-Output "  uv run python scripts/gen_report.py --work-id <id> [--granularity region|page] [--stages <阶段>]"
    }
}
