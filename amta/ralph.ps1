<#
.SYNOPSIS
    AMTA Ralph Runner v4 — 一次 claude -p 跑完整使命（Windows）

.DESCRIPTION
    v4（2026-09-06 教训重构）相对 v3 的根本变化：**去掉"分片迭代 + 冷重启"**。
    - claude -p 会自压紧上下文（v2.1.218+ 实证）→ 单个会话就能跑完跨多 commit 的整段使命，
      不需要"每 chunk 一个新 claude -p"。每 chunk 冷启动 = 全量上下文重读 = 纯空耗 token。
    - 墙钟迭代超时**删除**（v3 默认 900s 掐死过 productive agent）。不再按时间杀。
    - 真卡死兜底 = 心跳失守（transcript 长时间无新写入）→ 翻 transcript 尾部**按行为判**
      （productive 中途编辑 → 继续等；重复同一失败 = churn → 停）。
    - attempt 循环 = 崩溃/异常退出后的**整使命重试**（从最后 commit 续），不是分片续跑。

    记忆机制不变（progress lives in files）：
    - loop_state.json = mission/plan/status（agent 边界处读写）
    - git = 代码进度 ground truth（agent 每自然单元 commit）
    - 使命书 prompt.md = 契约（agent 只在 COMPLETE / BLOCKED / 死胡同退出）

.PARAMETER PromptFile
    使命书文件路径，默认 prompt.md

.PARAMETER MaxAttempts
    整使命最多尝试次数（含首跑；仅崩溃/异常退出才触发重试），默认 2

.PARAMETER HeartbeatStallSeconds
    心跳失守阈值：claude transcript JSONL 连续 N 秒无新写入才查一次"是否 churn"。
    默认 1800（30 分钟）——本机 CPU-only，一次长 pytest/fastcheck 可数分钟无新行，别误杀。

.PARAMETER TraceProjectsDir
    claude 会话目录。默认取 $env:CLAUDE_CONFIG_DIR\projects，否则 ~/.claude/projects。

.EXAMPLE
    .\ralph.ps1
    .\ralph.ps1 -PromptFile my-mission.md -MaxAttempts 3
#>

param(
    [string]$PromptFile = "prompt.md",
    [int]$MaxAttempts = 2,
    [int]$HeartbeatStallSeconds = 1800,
    [string]$TraceProjectsDir = ""
)

$ErrorActionPreference = "Continue"
$ProjectRoot = $PSScriptRoot
$PromptPath = Join-Path $ProjectRoot $PromptFile
$LogFile = Join-Path $ProjectRoot "ralph-log.md"
$LoopStatePath = Join-Path $ProjectRoot "loop_state.json"
$OutDir = Join-Path $ProjectRoot "output\ralph"
if (-not $TraceProjectsDir) {
    if ($env:CLAUDE_CONFIG_DIR) {
        $TraceProjectsDir = Join-Path $env:CLAUDE_CONFIG_DIR "projects"
    } else {
        $TraceProjectsDir = Join-Path $env:USERPROFILE ".claude\projects"
    }
}
$PollIntervalSeconds = 30
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

# 前置条件
if (-not (Test-Path $PromptPath)) { Write-Error "Prompt file not found: $PromptPath"; exit 1 }
if (-not (Test-Path $LoopStatePath)) { Write-Error "loop_state.json not found"; exit 1 }

function Add-RalphLog {
    param([string]$Text)
    Add-Content -Path $LogFile -Value $Text -Encoding UTF8
}

function Invoke-TraceProbe {
    param([string[]]$ProbeArgs)
    $script = Join-Path $ProjectRoot "scripts\trace_probe.py"
    return ,@(& uv run python $script @ProbeArgs 2>&1)
}

function Get-LiveSessionJsonl {
    param([string]$AfterIso)
    $lines = @(Invoke-TraceProbe @("live", $TraceProjectsDir, "--after", $AfterIso))
    if ($lines.Count -ge 1 -and $lines[0] -and (Test-Path $lines[0])) {
        return $lines[0].Trim()
    }
    return ""
}

Write-Output "==============================================================="
Write-Output "  AMTA Ralph Runner v4 (single claude -p per mission)"
Write-Output "  Project: $ProjectRoot | Prompt: $PromptFile"
Write-Output "  Max attempts: $MaxAttempts | Heartbeat stall: $HeartbeatStallSeconds s"
Write-Output "  Trace projects dir: $TraceProjectsDir"
Write-Output "==============================================================="

# BLOCKED 即等人类，不开跑
$st = Get-Content $LoopStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($st.status -eq "BLOCKED") {
    Write-Output "RALPH: loop_state.status=BLOCKED — waiting for human decision. escalation=$($st.escalation)"
    exit 2
}

$attempt = 0
$exitCode = 1
while ($attempt -lt $MaxAttempts) {
    $attempt++
    Write-Output ""
    Write-Output "--- Mission attempt $attempt / $MaxAttempts ($(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) ---"

    Push-Location $ProjectRoot
    uv run python scripts/memory.py inject 2>&1 | Out-Null
    $preamble = & uv run python scripts/ralph_context.py preamble --root $ProjectRoot 2>&1 | Out-String
    $resumeNote = ""
    if ($attempt -gt 1) {
        $head = (git -C $ProjectRoot rev-parse --short HEAD 2>&1).Trim()
        $resumeNote = "`n`n[resume] 上次 attempt 异常中断。git HEAD = $head（工作的 ground truth 在 commit 里）。从 loop_state.json 的 plan/next_action 续：先 git status / git log --oneline -5 核实现场再继续，别重做已完成 chunk。"
    }
    $promptWithContext = (Get-Content $PromptPath -Raw -Encoding UTF8) + "`n`n" + $preamble + $resumeNote
    Pop-Location

    # 启动单个 claude -p（默认 stdout 只出最终文本；liveness 看 transcript JSONL）
    $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdoutFile = Join-Path $OutDir "mission-$ts-attempt-$attempt.txt"
    $spawnIso = Get-Date -Format "o"
    $job = Start-Job -ScriptBlock {
        param($prompt, $workDir, $outFile)
        Set-Location $workDir
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
        $OutputEncoding = [System.Text.Encoding]::UTF8
        & claude -p $prompt 2>&1 | Out-File -FilePath $outFile -Encoding utf8
    } -ArgumentList $promptWithContext, $ProjectRoot, $stdoutFile

    # --- 心跳监测：不按时间杀；只查"卡死 + churn" ---
    $jobDone = $false
    $lastSeen = $null
    while (-not $jobDone) {
        if (Wait-Job $job -Timeout $PollIntervalSeconds) { $jobDone = $true; break }
        $live = Get-LiveSessionJsonl -AfterIso $spawnIso
        $probe = if ($live) { (Get-Item $live).LastWriteTime } else { $null }
        if ($null -ne $probe) {
            if ($null -ne $lastSeen -and ((Get-Date) - $probe).TotalSeconds -ge $HeartbeatStallSeconds) {
                # 心跳失守：翻 transcript 尾部判断是 productive 还是 churn
                $diagLines = @(Invoke-TraceProbe @("tail", $live, "--lines", "40"))
                $diagText = ($diagLines | ForEach-Object { $_ }) -join "`n"
                if ($diagText -match "(?i)is_error=True") {
                    Write-Output "[ralph] STALL with errors (churn) after $HeartbeatStallSeconds s — stopping."
                    Stop-Job $job
                    Add-Content -Path $stdoutFile -Value "`n--- RALPH STOPPED (churn) ---`n$diagText" -Encoding UTF8
                    break
                } else {
                    # 无错误迹象 = 可能在跑长工具（fastcheck）或长思考 —— 不杀，重置观察窗
                    Write-Output "[ralph] Transcript quiet $HeartbeatStallSeconds s but no error pattern — extending (likely long tool/think)."
                    $lastSeen = $probe
                }
            }
            if ($null -eq $lastSeen) { $lastSeen = $probe }
        }
    }
    Remove-Job $job -Force -ErrorAction SilentlyContinue

    # --- 判定结果 ---
    $outText = if (Test-Path $stdoutFile) { Get-Content $stdoutFile -Raw -Encoding UTF8 } else { "" }
    $ts2 = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

    # 1) COMPLETE
    if ($outText -match '<promise>COMPLETE</promise>') {
        Write-Output ""
        Write-Output "==============================================================="
        Write-Output "  RALPH COMPLETE (attempt $attempt)"
        Write-Output "  $ts2"
        Write-Output "==============================================================="
        Add-RalphLog "`n## $ts2 RALPH COMPLETE (v4, attempt $attempt)`n- 输出: $stdoutFile`n---`n"
        # DONE commit：把 loop_state 成果搬运成空 commit（git log 扫得到 run 边界）
        $doneMsg = & uv run python scripts/ralph_context.py done-msg --root $ProjectRoot 2>&1 | Out-String
        git -C $ProjectRoot add -A 2>&1 | Out-Null
        git -C $ProjectRoot commit --allow-empty -m $doneMsg 2>&1 | Out-Null
        exit 0
    }

    # 2) BLOCKED（agent 已写 status=BLOCKED 等人）
    $st2 = Get-Content $LoopStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($st2.status -eq "BLOCKED") {
        Write-Output ""
        Write-Output "  RALPH BLOCKED (attempt $attempt) — waiting for human"
        Write-Output "  escalation: $($st2.escalation)"
        Add-RalphLog "`n## $ts2 RALPH BLOCKED (v4, attempt $attempt)`n- 原因: $($st2.escalation)`n---`n"
        exit 2
    }

    # 3) 异常/崩溃/无信号 → 诊断 + 重试
    Write-Output "[ralph] Attempt $attempt ended without COMPLETE/BLOCKED. Diagnosing..."
    $diagText = ""
    $live = Get-LiveSessionJsonl -AfterIso $spawnIso
    if ($live -and (Test-Path $live)) {
        $dl = @(Invoke-TraceProbe @("tail", $live, "--lines", "40"))
        $diagText = ($dl | ForEach-Object { "  $_" }) -join "`n"
    }
    Add-RalphLog "`n## $ts2 RALPH ATTEMPT $attempt FAILED (no COMPLETE/BLOCKED)`n- 输出: $stdoutFile`n- 现场:`n$diagText`n---`n"
    if ($attempt -ge $MaxAttempts) {
        Write-Output ""
        Write-Output "==============================================================="
        Write-Output "  RALPH gave up after $MaxAttempts attempts — needs human."
        Write-Output "  See ralph-log.md + output\ralph\mission-*.txt"
        Write-Output "==============================================================="
        $exitCode = 3
        break
    }
    Write-Output "[ralph] Retrying whole mission from last commit (attempt $($attempt+1))..."
    Start-Sleep -Seconds 5
}

exit $exitCode
