# 启动 llama-server（本地漫画 OCR，OpenAI 兼容 :8118，CPU 推理）
# 用法: .\scripts\start_llama_ocr.ps1 [-Model paddle-manga] [-Quant Q8_0] [-Port 8118]
# 模型目录约定: models/<Model>/ 内含主 GGUF + mmproj GGUF（如 models/paddle-manga/）
# 性能说明（教训 L18）:
#   - 主模型默认用 Q8_0（BF16 是 16BPW 全精度，CPU prompt eval 慢 ~30%）；mmproj 保持 BF16
#     （PaddleOCR-VL mmproj 张量列 4304 非 32 倍数，Q8_0 量化会失败，属预期）
#   - -t 8 / -c 8192 / -b 256 -ub 512 / -fa on / -ctk/-ctv q8_0 / --mlock 为实测最优组合
#     （i5-1135G7 4C8T，t=4 vs t=8 无显著差异，取 8）
#   - 不要加 --cache-reuse：多模态下不支持（日志会提示 disabled）
param(
    [string]$Model = "paddle-manga",   # paddle-manga | paddle-1.6 | ...（models/<Model>/ 子目录）
    [string]$Quant = "auto",           # auto(优先 Q8_0 回退 BF16) | Q8_0 | BF16
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

# 主 GGUF：Q8_0 优先（auto），否则显式指定类型；mmproj 恒用 BF16（Q8_0 量化不支持此 mmproj）
$ggufs = @(Get-ChildItem $ModelDir -Filter *.gguf)
$main = $null
if ($Quant -ne "BF16") {
    $main = $ggufs | Where-Object { $_.Name -like "*-Q8_0*" -and $_.Name -notlike "*mmproj*" } | Select-Object -First 1
}
if (-not $main) {
    $main = $ggufs | Where-Object { $_.Name -notlike "*mmproj*" -and $_.Name -notlike "*-Q8_0*" } | Select-Object -First 1
}
$mmproj = $ggufs | Where-Object { $_.Name -like "*mmproj*" -and $_.Name -notlike "*-Q8_0*" } | Select-Object -First 1
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
                   "--host", "127.0.0.1", "--port", "$Port", "-ngl", "0",
                   "-t", "8", "-c", "8192", "-b", "256", "-ub", "512",
                   "-fa", "on", "-ctk", "q8_0", "-ctv", "q8_0", "--mlock")
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
