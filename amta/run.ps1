<#
.SYNOPSIS
    AMTA unified command entry - forces uv run internally, never uses wrong Python.

.DESCRIPTION
    Wrapper for common commands:
      .\run.ps1 all --pages 1-5           Run full pipeline
      .\run.ps1 detect --pages 1-5        Run detect only
      .\run.ps1 inpaint --pages 11-20     Run inpaint only (refined mask + lama-manga)
      .\run.ps1 report                     Generate stage4 verification report
      .\run.ps1 test                       Run pytest
      .\run.ps1 python -c "..."           Pass through any python command (auto uv run)

.NOTES
    All commands use uv run python internally, ensuring project .venv (Python 3.12)
    and all dependencies. Never use `python script.py` directly - that uses system
    Python 3.14 which has no project dependencies and will raise ModuleNotFoundError.
#>

# No param() block - use $args to avoid PowerShell parameter prefix matching
# (e.g. -c would ambiguously match -Command). $args[0] = command, rest = args.
$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$WorkId = "amta-run"
$SrcDir = "D:\我的汉化\汉化作品\东方\单翼停留之地"

$Command = if ($args.Count -gt 0) { $args[0] } else { "" }
$CmdArgs = if ($args.Count -gt 1) { $args[1..($args.Count - 1)] } else { @() }

$validCommands = @("all","detect","ocr","translate","inpaint","typeset","report","test","python")
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

function Parse-Pages {
    param([string]$PagesStr)
    if ($PagesStr -match "^(\d+)-(\d+)$") {
        return @($Matches[1], $Matches[2])
    }
    Write-Error "Invalid page range: '$PagesStr'. Use format like 1-5 or 11-20"
}

switch ($Command) {
    "all" {
        $pagesIdx = [Array]::IndexOf($CmdArgs, "--pages")
        if ($pagesIdx -lt 0 -or $pagesIdx + 1 -ge $CmdArgs.Count) {
            Write-Error "Usage: .\run.ps1 all --pages 1-5"
        }
        $start, $end = Parse-Pages $CmdArgs[$pagesIdx + 1]
        Invoke-UvPython @("scripts/00_run_all.py", "--work-id", $WorkId,
            "--src-dir", $SrcDir, "--start-page", $start, "--end-page", $end,
            "--with-inpaint", "--with-typeset")
    }
    "detect" {
        $pagesIdx = [Array]::IndexOf($CmdArgs, "--pages")
        if ($pagesIdx -lt 0 -or $pagesIdx + 1 -ge $CmdArgs.Count) {
            Write-Error "Usage: .\run.ps1 detect --pages 1-5"
        }
        $start, $end = Parse-Pages $CmdArgs[$pagesIdx + 1]
        $outDir = Join-Path $ProjectRoot "output\tmp\detect"
        if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
        for ($n = $start; $n -le $end; $n++) {
            Invoke-UvPython @("scripts/01_detect.py", "--raw", "$SrcDir\$n.jpg",
                "--out", "$outDir\page_$n`_detection.json")
        }
        Write-Output "detect done: page_$start - page_$end -> $outDir"
    }
    "ocr" {
        Write-Output "ocr stage runs via 00_run_all, not supported standalone yet"
    }
    "translate" {
        Write-Output "translate stage runs via 00_run_all, not supported standalone yet"
    }
    "inpaint" {
        Write-Output "Note: run_stage4_e2e_11_20.py has hardcoded page range 11-20"
        Invoke-UvPython @("scripts/run_stage4_e2e_11_20.py")
    }
    "typeset" {
        Write-Output "typeset stage runs via 00_run_all, not supported standalone yet"
    }
    "report" {
        Invoke-UvPython @("scripts/gen_stage4_report.py")
    }
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
        Write-Output "  all --pages 1-5        Run full pipeline (detect+ocr+translate+inpaint+typeset)"
        Write-Output "  detect --pages 1-5     Run detect only"
        Write-Output "  inpaint --pages 11-20  Run inpaint only (refined mask + lama-manga)"
        Write-Output "  report                  Generate stage4 verification report"
        Write-Output "  test                    Run pytest"
        Write-Output '  python -c "..."         Pass through any python command (auto uv run)'
        Write-Output ""
        Write-Output "Examples:"
        Write-Output "  .\run.ps1 all --pages 1-5"
        Write-Output "  .\run.ps1 report"
        Write-Output '  .\run.ps1 python -c "import requests; print(''ok'')"'
    }
}
