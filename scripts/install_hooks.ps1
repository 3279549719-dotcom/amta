# 安装 git hooks：把 core.hooksPath 指向 .githooks（pre-commit / pre-push）
# 用法：powershell -ExecutionPolicy Bypass -File scripts/install_hooks.ps1
$root = Split-Path -Parent $PSScriptRoot
git -C $root config core.hooksPath .githooks
if ($LASTEXITCODE -eq 0) {
    Write-Host "[install_hooks] OK: core.hooksPath -> .githooks"
} else {
    Write-Host "[install_hooks] FAIL"
    exit 1
}
