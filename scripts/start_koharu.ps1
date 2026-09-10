# 启动 koharu v0.59.1 headless（端口 4000，CPU 推理）
param(
    [int]$Port = 4000,
    [string]$KoharuExe = "D:\我的汉化\workflow\bin\koharu.exe",
    [int]$WaitSeconds = 240
)
$ErrorActionPreference = "Stop"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"

function Test-KoharuHttp {
    param([int]$P)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$P/" -UseBasicParsing -TimeoutSec 3
        return $r.StatusCode -eq 200
    } catch { return $false }
}

if (-not (Test-Path $KoharuExe)) { throw "Koharu binary not found: $KoharuExe" }

if (-not (Test-KoharuHttp -P $Port)) {
    Write-Host "[amta] launching koharu.exe --port $Port --headless --cpu ..."
    Start-Process $KoharuExe -ArgumentList @("--port", "$Port", "--headless", "--cpu") -WindowStyle Hidden
    for ($i = 0; $i -lt $WaitSeconds; $i += 2) {
        if (Test-KoharuHttp -P $Port) { break }
        Start-Sleep -Seconds 2
    }
    if (-not (Test-KoharuHttp -P $Port)) {
        throw "Koharu HTTP not ready on port $Port after ${WaitSeconds}s"
    }
} else {
    Write-Host "[amta] koharu already responding on port $Port"
}
Write-Host "[amta] OK: http://127.0.0.1:$Port/  (api: /api/v1, mcp: /mcp)"
