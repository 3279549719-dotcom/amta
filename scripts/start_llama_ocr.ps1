# 启动 llama-server（本地漫画 OCR，OpenAI 兼容 :8118，CPU 推理）
# 用法: .\scripts\start_llama_ocr.ps1 [-Model paddle-manga] [-Port 8118]
# 模型目录约定: models/<Model>/ 内含主 GGUF + mmproj GGUF（如 models/paddle-manga/）
param(
    [string]$Model = "paddle-manga",   # paddle-manga | paddle-1.6 | ...（models/<Model>/ 子目录）
    [int]$Port = 8118,
    [string]$LlamaExe = "",
    [int]$WaitSeconds = 120
)
$ErrorActionPreference = "Stop"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"

$Root = Split-Path -Parent $PSScriptRoot
if (-not $LlamaExe) { $LlamaExe = Join-Path $Root "models\llama-cpp\llama-server.exe" }
$ModelDir = Join-Path $Root "models\$Model"

if (-not (Test-Path $LlamaExe)) { throw "llama-server binary not found: $LlamaExe" }
if (-not (Test-Path $ModelDir)) { throw "model dir not found: $ModelDir" }

# 主 GGUF（文件名不含 mmproj）+ 多模态投影 mmproj GGUF
$ggufs = @(Get-ChildItem $ModelDir -Filter *.gguf)
$main = $ggufs | Where-Object { $_.Name -notlike "*mmproj*" } | Select-Object -First 1
$mmproj = $ggufs | Where-Object { $_.Name -like "*mmproj*" } | Select-Object -First 1
if (-not $main -or -not $mmproj) {
    throw "model dir $ModelDir must contain a main GGUF and a *mmproj* GGUF"
}

function Test-LlamaHttp {
    param([int]$P)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$P/v1/models" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

if (-not (Test-LlamaHttp -P $Port)) {
    Write-Host "[amta] launching llama-server --model $($main.Name) --mmproj $($mmproj.Name) --port $Port ..."
    $llamaArgs = @("--model", $main.FullName, "--mmproj", $mmproj.FullName,
                   "--host", "127.0.0.1", "--port", "$Port", "-ngl", "0")
    Start-Process $LlamaExe -ArgumentList $llamaArgs -WindowStyle Hidden
    for ($i = 0; $i -lt $WaitSeconds; $i += 2) {
        if (Test-LlamaHttp -P $Port) { break }
        Start-Sleep -Seconds 2
    }
    if (-not (Test-LlamaHttp -P $Port)) {
        throw "llama-server not ready on port $Port after ${WaitSeconds}s"
    }
} else {
    Write-Host "[amta] llama-server already responding on port $Port"
}
Write-Host "[amta] OK: http://127.0.0.1:$Port/  (OpenAI compatible /v1)"
