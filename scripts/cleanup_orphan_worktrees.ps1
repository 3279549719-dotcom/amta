# 一次性清理：残留 worktree 物理目录（重启后句柄释放再运行）
# 用法：右键「使用 PowerShell 运行」，或 cd 到仓库根后执行
# 说明：git 注册与分支已清理完毕；以下目录仅剩被进程句柄锁住的 pytest 临时目录，
#       普通权限无法删除（已尝试 rmdir/Remove-Item/robocopy/takeown/icacls），重启后即可删。
$ErrorActionPreference = "Continue"
$root = "E:\manga translator agent\amta\.worktrees"

foreach ($name in @("refactor-modularity", "stage123-deep-interfaces")) {
    $target = Join-Path $root $name
    if (Test-Path $target) {
        Write-Host "Deleting $target ..."
        Remove-Item $target -Recurse -Force
        if (Test-Path $target) {
            Write-Host "  [STILL LOCKED] $target — 若仍失败，重启 Windows 后再跑本脚本"
        } else {
            Write-Host "  [OK] $target"
        }
    } else {
        Write-Host "  [SKIP] $target 已不存在"
    }
}

Write-Host "`n完成。验证：git worktree list 应只剩主树。"
