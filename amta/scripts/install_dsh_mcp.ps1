# 把 amta 记忆检索注册成 DSH 原生 tool（走 dsh-mcp-client 桥）。
#
# 背景（2026-09-10 实测）：DSH **不读** 项目根的 .mcp.json（那是 Claude Code 的方言）。
# DSH 的 MCP 服务端是**一条 cordis 插件行**，写在 profile 的 cordis.patch.yml 里。
# 不写这一行，scripts/mcp_memory.py 永远连不上，CLAUDE.local.md 里指向的
# memory_search / memory_grep 就是死指针，轨迹里也看不到任何工具调用。
#
# 用法：pwsh -File scripts/install_dsh_mcp.ps1
#       pwsh -File scripts/install_dsh_mcp.ps1 -Profile web   # 默认就是 web
#
# 效果：新会话里出现 mcp__amta-memory__memory_search / memory_read / memory_recent，
#       它们会以独立工具名出现在 GUI 轨迹的 tool 列（可观测），而不是藏在 pwsh 命令串里。
#
# 可逆：脚本先备份 cordis.patch.yml；删掉 mcp-amta-memory 那一段即回退。
param([string]$Profile = 'web')

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$server = Join-Path $root 'scripts\mcp_memory.py'
$patch = Join-Path $env:USERPROFILE ".dsh\profiles\$Profile\cordis.patch.yml"

# 1) 自检：MCP server 必须真的应答 tools/list，否则不写配置（不装连不上的服务）
if (-not (Test-Path $python)) { Write-Host "[install_dsh_mcp] FAIL: 找不到 $python"; exit 1 }
if (-not (Test-Path $server)) { Write-Host "[install_dsh_mcp] FAIL: 找不到 $server"; exit 1 }
$probe = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
$reply = ($probe | & $python $server 2>&1) -join ''
if ($reply -notmatch 'memory_search') {
    Write-Host "[install_dsh_mcp] FAIL: MCP server 未应答 tools/list，不写配置"
    exit 1
}
Write-Host "[install_dsh_mcp] 自检 OK: memory_search / memory_read / memory_recent 已就绪"

# 2) 目标 profile 必须存在
if (-not (Test-Path $patch)) {
    Write-Host "[install_dsh_mcp] FAIL: 找不到 profile 补丁文件 $patch"
    exit 1
}

# 3) 幂等：已有同名行就不重复追加
if ((Get-Content $patch -Raw) -match 'mcp-amta-memory') {
    Write-Host "[install_dsh_mcp] 已注册（mcp-amta-memory 已存在），无需改动"
    exit 0
}

# 4) 备份 + 追加补丁行
$backup = "$patch.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
Copy-Item $patch $backup
$row = @"

# amta 记忆检索 → DSH 原生 tool（由 scripts/install_dsh_mcp.ps1 写入）
- insert:
    - id: mcp-amta-memory
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: amta-memory
        transport: stdio
        command: '$python'
        args: ['scripts/mcp_memory.py']
        cwd: '$root'
"@
# 用 .NET 追加以保证**无 BOM**（PowerShell 5.1 的 -Encoding utf8 会写 BOM，
# 而 BOM 会让 YAML 解析出怪字符；DSH 的 cordis 配置必须是无 BOM 的 UTF-8）。
[System.IO.File]::AppendAllText($patch, $row, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "[install_dsh_mcp] OK: 已写入 $patch（备份：$backup）"
Write-Host "[install_dsh_mcp] 下一步：重启 dsh 或新开会话，确认轨迹 tool 列出现 mcp__amta-memory__memory_search"
exit 0
