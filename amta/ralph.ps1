<#
.SYNOPSIS
    AMTA Ralph Loop — 自治迭代外层循环（Windows 版）

.DESCRIPTION
    每次迭代启动一个新鲜的 claude -p 会话，用 prompt.md 作为强制工作流指令。
    agent 读完 loop_state.json → 执行 next_action → 跑 fastcheck → 更新状态 → 写日志 → commit。
    外层循环负责"踢下一脚"，直到 agent 输出 <promise>COMPLETE</promise>、写入 status=BLOCKED、或达到最大迭代次数。

    v3 新增（trace 驱动）：
    - 心跳监测：spawn 前记下 claude 会话 JSONL（~/.claude/projects/<slug>/<uuid>.jsonl）基准，
      迭代中每 30 秒查一次该文件 mtime，HeartbeatStallSeconds（默认 180s）无新写入即判定卡死并杀进程
      ——比 v2 的 15 分钟"倒计时炸弹"早 5 倍止损。
    - 卡死/超时诊断：杀进程后读 JSONL 尾部（scripts/trace_probe.py tail），
      把"最后一次工具调用 + 卡住位置"写进 ralph-log.md 和 loop_state.escalation，供下轮 agent 接续（不失忆）。
    - BLOCKED 暂停：agent 在 loop_state.json 写 status=BLOCKED（需人裁决）时，
      ralph 停止循环并退出（exit 2），等人裁决后清 status / 改 next_action 再继续——不再空转烧迭代。
    - COMPLETE 时 trace 统计：用 scripts/trace_probe.py stats 汇总本次会话
      （工具调用数 / 最大停顿 / 重复调用），追加到 ralph-log.md——"用 Trace 反查 Harness 哪里待完善"。

    v2 保留：
    - 每次迭代输出存盘到 output/logs/iteration-N-timestamp.txt
    - 迭代超时机制（默认 15 分钟），超时自动杀掉 claude 进程并记录部分输出

    记忆机制：progress lives in files, NOT in LLM context.
    - loop_state.json = 任务状态（agent 每次读写，status=BLOCKED 表示需人裁决）
    - ralph-log.md = append-only 学习日志
    - docs/lessons.md = 可复用经验
    - git = 代码历史

.PARAMETER MaxIterations
    最大迭代次数，默认 10

.PARAMETER PromptFile
    工作流指令文件路径，默认 prompt.md

.PARAMETER IterationTimeoutSeconds
    单次迭代墙钟超时秒数，默认 900（15分钟）。超时后自动杀掉 claude 进程，记录部分输出。

.PARAMETER HeartbeatStallSeconds
    心跳失守阈值：claude 会话 JSONL 连续 N 秒无新写入即判定卡死，默认 180（3 分钟）。
    注意：一次超长工具调用（如长测试/安装）期间 JSONL 不增长，可能误杀——按需调大。

.PARAMETER TraceProjectsDir
    claude 会话目录，默认 ~/.claude/projects。改过 CLAUDE_CONFIG_DIR 时需同步指定。

.EXAMPLE
    .\ralph.ps1
    .\ralph.ps1 -MaxIterations 5
    .\ralph.ps1 -MaxIterations 20 -PromptFile my-prompt.md
    .\ralph.ps1 -IterationTimeoutSeconds 1800
    .\ralph.ps1 -HeartbeatStallSeconds 300
#>

param(
    [int]$MaxIterations = 10,
    [string]$PromptFile = "prompt.md",
    [int]$IterationTimeoutSeconds = 900,
    [int]$HeartbeatStallSeconds = 180,
    [string]$TraceProjectsDir = ""
)

$ErrorActionPreference = "Continue"
$ProjectRoot = $PSScriptRoot
$PromptPath = Join-Path $ProjectRoot $PromptFile
$LogFile = Join-Path $ProjectRoot "ralph-log.md"
$IterationLogDir = Join-Path $ProjectRoot "output\logs"
$LoopStatePath = Join-Path $ProjectRoot "loop_state.json"
$LoopStateCli = Join-Path $ProjectRoot "scripts\loop_state.py"
if (-not $TraceProjectsDir) { $TraceProjectsDir = Join-Path $env:USERPROFILE ".claude\projects" }
$PollIntervalSeconds = 30

# 确保迭代日志目录存在
if (-not (Test-Path $IterationLogDir)) {
    New-Item -ItemType Directory -Path $IterationLogDir -Force | Out-Null
}

# 检查前置条件
if (-not (Test-Path $PromptPath)) {
    Write-Error "Prompt file not found: $PromptPath"
    exit 1
}
if (-not (Test-Path $LoopStatePath)) {
    Write-Error "loop_state.json not found. Create it first with current mission and next_action."
    exit 1
}

# 轻量追加 ralph-log
function Add-RalphLog {
    param([string]$Text)
    Add-Content -Path $LogFile -Value $Text -Encoding UTF8
}

# 调 scripts/trace_probe.py（uv run python，stdlib only），返回行数组
function Invoke-TraceProbe {
    param([string[]]$ProbeArgs)
    $script = Join-Path $ProjectRoot "scripts\trace_probe.py"
    $raw = & uv run python $script @ProbeArgs 2>&1
    return ,@($raw)
}

# 找当前迭代的 claude 会话 JSONL（spawn 后出现、mtime >= after 的最新者）
function Get-LiveSessionJsonl {
    param([string]$AfterIso)
    $lines = @(Invoke-TraceProbe @("live", $TraceProjectsDir, "--after", $AfterIso))
    if ($lines.Count -ge 1 -and $lines[0] -and (Test-Path $lines[0])) {
        return $lines[0].Trim()
    }
    return ""
}

Write-Output "==============================================================="
Write-Output "  AMTA Ralph Loop starting (v3: trace heartbeat + BLOCKED pause)"
Write-Output "  Project: $ProjectRoot"
Write-Output "  Max iterations: $MaxIterations"
Write-Output "  Iteration timeout: $IterationTimeoutSeconds seconds"
Write-Output "  Heartbeat stall: $HeartbeatStallSeconds seconds"
Write-Output "  Trace projects dir: $TraceProjectsDir"
Write-Output "  Prompt: $PromptFile"
Write-Output "==============================================================="

# 读 prompt 内容（每次迭代重新读，允许运行中修改）
$promptContent = Get-Content $PromptPath -Raw -Encoding UTF8

for ($i = 1; $i -le $MaxIterations; $i++) {
    Write-Output ""
    Write-Output "==============================================================="
    Write-Output "  Iteration $i of $MaxIterations"
    Write-Output "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    Write-Output "==============================================================="

    # 整个迭代都在项目目录下运行（memory inject + claude -p 都需要项目上下文）
    Push-Location $ProjectRoot

    # 迭代前刷新记忆注入（确保 CLAUDE.local.md 是最新的 loop_state）
    Write-Output "[ralph] Refreshing memory injection..."
    uv run python scripts/memory_inject.py 2>&1 | ForEach-Object { Write-Output "  [memory_inject] $_" }

    # 显示当前状态（含 status）
    if (Test-Path $LoopStatePath) {
        $state = Get-Content $LoopStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Output "[ralph] Current state:"
        Write-Output "  mission: $($state.mission)"
        Write-Output "  next_action: $($state.next_action)"
        Write-Output "  last_verified: $($state.last_verified)"
        Write-Output "  status: $($state.status)"
    }

    # 开工注入：跑 memory_index + git log，拼进 prompt（agent 一睁眼就看到最新清单和脉络，实时）
    Write-Output "[ralph] Building preamble (memory_index + git log)..."
    $preamble = & uv run python scripts/ralph_context.py preamble --root $ProjectRoot 2>&1 | Out-String
    $promptWithContext = $promptContent + "`n`n" + $preamble

    # 启动新鲜 agent 会话
    Write-Output ""
    Write-Output "[ralph] Spawning fresh agent (timeout: $IterationTimeoutSeconds s, heartbeat: $HeartbeatStallSeconds s)..."
    Write-Output "--- agent output start ---"

    $output = @()
    $timedOut = $false
    $heartbeatMiss = $false
    $stallJsonl = ""
    $spawnIso = Get-Date -Format "o"

    try {
        $job = Start-Job -ScriptBlock {
            param($prompt, $workDir)
            Set-Location $workDir
            claude -p $prompt 2>&1
        } -ArgumentList $promptWithContext, $ProjectRoot

        # --- 心跳监测：spawn 后每 30s 查一次本次会话 JSONL 的 mtime，连续失守即杀 ---
        $jobCompleted = $false
        $elapsed = 0
        $lastHeartbeatSeen = $null

        while (-not $jobCompleted) {
            if (Wait-Job $job -Timeout $PollIntervalSeconds) {
                $jobCompleted = $true
                break
            }
            $elapsed += $PollIntervalSeconds
            if ($elapsed -ge $IterationTimeoutSeconds) {
                $timedOut = $true
                $stallJsonl = Get-LiveSessionJsonl -AfterIso $spawnIso
                break
            }
            $live = Get-LiveSessionJsonl -AfterIso $spawnIso
            if ($live) {
                $mt = (Get-Item $live).LastWriteTime
                if ($null -ne $lastHeartbeatSeen -and ((Get-Date) - $mt).TotalSeconds -ge $HeartbeatStallSeconds) {
                    $heartbeatMiss = $true
                    $stallJsonl = $live
                    break
                }
                $lastHeartbeatSeen = $mt
            }
        }

        if (-not $jobCompleted) {
            # 卡死/超时：杀掉，收集部分输出
            Stop-Job $job
            $partialOutput = Receive-Job $job
            if ($heartbeatMiss) {
                Write-Output ""
                Write-Output "[ralph] HEARTBEAT MISS: session JSONL unchanged for $HeartbeatStallSeconds s, killed."
            } else {
                Write-Output ""
                Write-Output "[ralph] TIMEOUT: iteration $i exceeded $IterationTimeoutSeconds seconds, killed."
            }
            Write-Output "[ralph] Partial output (last 30 lines):"
            $partialOutput | Select-Object -Last 30 | ForEach-Object { Write-Output $_ }
            $output = $partialOutput
            $timedOut = $true
        } else {
            $output = Receive-Job $job
            $output | ForEach-Object { Write-Output $_ }
        }
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Output "[ralph] Agent error: $_"
        $output = "ERROR: $_"
    }

    Write-Output "--- agent output end ---"

    # 迭代输出存盘（卡住了能翻日志看在干嘛）
    $timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $iterationLogFile = Join-Path $IterationLogDir "iteration-$i-$timestamp.txt"
    $output | Out-File -FilePath $iterationLogFile -Encoding UTF8
    if ($timedOut) {
        $killReason = if ($heartbeatMiss) { "HEARTBEAT MISS (jsonl $HeartbeatStallSeconds s 无写入)" } else { "TIMEOUT ($IterationTimeoutSeconds s)" }
        Add-Content -Path $iterationLogFile -Value "`n--- RALPH KILLED ($killReason) ---`nIteration $i killed at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')." -Encoding UTF8
    }
    Write-Output "[ralph] Iteration log saved to: $iterationLogFile"

    Pop-Location

    # --- 卡死/超时：trace 诊断写 ralph-log + loop_state.escalation（下轮不失忆） ---
    if ($timedOut) {
        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $killReason = if ($heartbeatMiss) { "心跳丢失（session jsonl $HeartbeatStallSeconds 秒未更新）" } else { "迭代超时 $IterationTimeoutSeconds 秒" }
        $diagText = ""
        if ($stallJsonl -and (Test-Path $stallJsonl)) {
            $diagLines = @(Invoke-TraceProbe @("tail", $stallJsonl, "--lines", "60"))
            $diagText = ($diagLines | ForEach-Object { "  $_" }) -join "`n"
        } else {
            $diagText = "  （未能定位本次会话 JSONL）"
        }
        $stallLog = "`n## $ts RALPH ITERATION STOPPED`n- 迭代: $i / $MaxIterations`n- 原因: $killReason`n- 现场诊断:`n$diagText`n- 部分输出: 见 $iterationLogFile`n- 处理: 自动杀掉，继续下一次迭代`n---`n"
        Add-RalphLog $stallLog

        # escalation 写一行（压成单行），供下轮 agent 接续
        $diagOneLine = (($diagText -replace "`r?`n", " ") -replace "\s+", " ").Trim()
        $escalationMsg = "迭代 $i $killReason；现场：$diagOneLine"
        uv run python $LoopStateCli --root $ProjectRoot update --field "escalation=$escalationMsg" 2>&1 | Out-Null

        Write-Output "[ralph] Iteration $i stopped, continuing to next iteration..."
        Start-Sleep -Seconds 3
        continue
    }

    # --- 检查 BLOCKED（agent 标记需人裁决）→ 停止循环，不等下一轮 ---
    $blocked = $false
    $blockedReason = ""
    if (Test-Path $LoopStatePath) {
        $st = Get-Content $LoopStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($st.status -eq "BLOCKED") {
            $blocked = $true
            $blockedReason = [string]$st.escalation
        }
    }
    if ($blocked) {
        Write-Output ""
        Write-Output "==============================================================="
        Write-Output "  RALPH BLOCKED at iteration $i — waiting for human decision"
        Write-Output "  Reason: $blockedReason"
        Write-Output "  Resume: clear status (or set next_action) in loop_state.json, re-run ralph.ps1"
        Write-Output "==============================================================="
        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $blockedLog = "`n## $ts RALPH BLOCKED`n- 迭代: $i / $MaxIterations`n- 原因: $blockedReason`n- 处理: 停止循环，等人裁决后清 status 继续`n---`n"
        Add-RalphLog $blockedLog
        exit 2
    }

    # 检查完成信号
    if ($output -match '<promise>COMPLETE</promise>') {
        Write-Output ""
        Write-Output "==============================================================="
        Write-Output "  RALPH COMPLETE at iteration $i"
        Write-Output "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        Write-Output "==============================================================="

        # 追加完成日志 + trace 统计（全绿：工具调用数/最大停顿/重复调用 → 反查 Harness）
        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $traceStatsText = ""
        $live = Get-LiveSessionJsonl -AfterIso $spawnIso
        if ($live) {
            $statLines = @(Invoke-TraceProbe @("stats", $live))
            $traceStatsText = ($statLines | ForEach-Object { "  $_" }) -join "`n"
        }
        $completeLog = "`n## $ts RALPH COMPLETE`n- 完成迭代: $i / $MaxIterations`n- 最终状态: 见 loop_state.json`n- 迭代日志: $iterationLogFile`n- trace 统计:`n$traceStatsText`n---`n"
        Add-RalphLog $completeLog

        # 收尾 DONE：从 loop_state 搬运 agent 写好的成果/遗留，空 commit 标记 run 结束（git log 可扫到 run 边界）
        Write-Output "[ralph] Writing DONE commit (from loop_state)..."
        $doneMsg = & uv run python scripts/ralph_context.py done-msg --root $ProjectRoot 2>&1 | Out-String
        git -C $ProjectRoot add -A 2>&1 | Out-Null
        git -C $ProjectRoot commit --allow-empty -m $doneMsg 2>&1 | ForEach-Object { Write-Output "  [ralph] $_" }

        exit 0
    }

    # 迭代间短暂休息（给文件系统和 git 喘息时间）
    Write-Output "[ralph] Iteration $i complete. Continuing..."
    Start-Sleep -Seconds 3
}

# 达到最大迭代次数
Write-Output ""
Write-Output "==============================================================="
Write-Output "  RALPH reached max iterations ($MaxIterations) without COMPLETE signal"
Write-Output "  Check loop_state.json and ralph-log.md for status"
Write-Output "==============================================================="

$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
$maxLog = "`n## $ts RALPH MAX ITERATIONS`n- 达到最大迭代次数: $MaxIterations`n- 未收到 COMPLETE 信号`n- 最终状态: 见 loop_state.json`n---`n"
Add-RalphLog $maxLog

exit 1
