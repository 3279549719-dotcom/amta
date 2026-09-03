<#
.SYNOPSIS
    AMTA Ralph Loop — 自治迭代外层循环（Windows 版）

.DESCRIPTION
    每次迭代启动一个新鲜的 claude -p 会话，用 prompt.md 作为强制工作流指令。
    agent 读完 loop_state.json → 执行 next_action → 跑 fastcheck → 更新状态 → 写日志 → commit。
    外层循环负责"踢下一脚"，直到 agent 输出 <promise>COMPLETE</promise> 或达到最大迭代次数。

    记忆机制：progress lives in files, NOT in LLM context.
    - loop_state.json = 任务状态（agent 每次读写）
    - ralph-log.md = append-only 学习日志
    - docs/lessons.md = 可复用经验
    - git = 代码历史

.PARAMETER MaxIterations
    最大迭代次数，默认 10

.PARAMETER PromptFile
    工作流指令文件路径，默认 prompt.md

.EXAMPLE
    .\ralph.ps1
    .\ralph.ps1 -MaxIterations 5
    .\ralph.ps1 -MaxIterations 20 -PromptFile my-prompt.md
#>

param(
    [int]$MaxIterations = 10,
    [string]$PromptFile = "prompt.md"
)

$ErrorActionPreference = "Continue"
$ProjectRoot = $PSScriptRoot
$PromptPath = Join-Path $ProjectRoot $PromptFile
$LogFile = Join-Path $ProjectRoot "ralph-log.md"

# 检查前置条件
if (-not (Test-Path $PromptPath)) {
    Write-Error "Prompt file not found: $PromptPath"
    exit 1
}
if (-not (Test-Path (Join-Path $ProjectRoot "loop_state.json"))) {
    Write-Error "loop_state.json not found. Create it first with current mission and next_action."
    exit 1
}

Write-Output "==============================================================="
Write-Output "  AMTA Ralph Loop starting"
Write-Output "  Project: $ProjectRoot"
Write-Output "  Max iterations: $MaxIterations"
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

    # 显示当前状态
    $statePath = Join-Path $ProjectRoot "loop_state.json"
    if (Test-Path $statePath) {
        $state = Get-Content $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Output "[ralph] Current state:"
        Write-Output "  mission: $($state.mission)"
        Write-Output "  next_action: $($state.next_action)"
        Write-Output "  last_verified: $($state.last_verified)"
    }

    # 启动新鲜 agent 会话
    Write-Output ""
    Write-Output "[ralph] Spawning fresh agent..."
    Write-Output "--- agent output start ---"

    $output = ""
    try {
        # 用变量传 prompt 内容（Windows 方式，避免 stdin 编码问题）
        $output = claude -p $promptContent 2>&1
        $output | ForEach-Object { Write-Output $_ }
    } catch {
        Write-Output "[ralph] Agent error: $_"
        $output = "ERROR: $_"
    }

    Write-Output "--- agent output end ---"
    Pop-Location

    # 检查完成信号
    if ($output -match '<promise>COMPLETE</promise>') {
        Write-Output ""
        Write-Output "==============================================================="
        Write-Output "  RALPH COMPLETE at iteration $i"
        Write-Output "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
        Write-Output "==============================================================="

        # 追加完成日志
        $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
        $completeLog = "`n## $ts RALPH COMPLETE`n- 完成迭代: $i / $MaxIterations`n- 最终状态: 见 loop_state.json`n---`n"
        Add-Content -Path $LogFile -Value $completeLog -Encoding UTF8

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
Add-Content -Path $LogFile -Value $maxLog -Encoding UTF8

exit 1
