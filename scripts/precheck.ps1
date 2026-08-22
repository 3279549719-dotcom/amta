# AMTA precheck: verify koharu headless is reachable on port 4000 before running.
# Exit codes: 0 = koharu reachable; 1 = not reachable (run `npm start` first).
param(
    [int]$Port = 4000,
    [int]$TimeoutSec = 5
)

function Test-KoharuHttp {
    param([int]$P)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$P/" -UseBasicParsing -TimeoutSec $TimeoutSec
        return $r.StatusCode -eq 200
    } catch { return $false }
}

if (Test-KoharuHttp -P $Port) {
    Write-Host "[precheck] OK: koharu reachable on port $Port"
    exit 0
}

Write-Host "[precheck] FAIL: koharu not reachable on port $Port"
Write-Host "[precheck] Start it first: npm start"
exit 1
