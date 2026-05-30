param(
    [string]$TestDatabaseUrl = $env:CROPPRO_TEST_DATABASE_URL,
    [switch]$SkipFullBackend
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

function Invoke-Step {
    param(
        [string]$Label,
        [scriptblock]$Action
    )
    Write-Host ""
    Write-Host "== $Label ==" -ForegroundColor Cyan
    & $Action
}

if (-not $TestDatabaseUrl) {
    throw "CROPPRO_TEST_DATABASE_URL is not set. Pass -TestDatabaseUrl or export the env var first."
}

$env:CROPPRO_TEST_DATABASE_URL = $TestDatabaseUrl
$env:SECRET_KEY = if ($env:SECRET_KEY) { $env:SECRET_KEY } else { "test-secret-key-do-not-use-in-prod-48-chars-minimum-padding-padding" }
$env:AGENT_API_KEY = if ($env:AGENT_API_KEY) { $env:AGENT_API_KEY } else { "test-agent-key" }
$env:CROPPRO_LICENSE_ENFORCE = "0"
$env:ENV = "test"

Invoke-Step "Backend critical tenant safety suites" {
    Push-Location $backendDir
    try {
        py -m pytest tests/test_agent_ingestion.py tests/test_tenant_isolation.py tests/test_phishing.py tests/test_monitoring.py -q
    } finally {
        Pop-Location
    }
}

if (-not $SkipFullBackend) {
    Invoke-Step "Full backend suite" {
        Push-Location $backendDir
        try {
            py -m pytest -q
        } finally {
            Pop-Location
        }
    }
}

Invoke-Step "Frontend websocket guard" {
    Push-Location $frontendDir
    try {
        npm.cmd run check:ws-order
    } finally {
        Pop-Location
    }
}

Invoke-Step "Frontend UI/UX guard" {
    Push-Location $frontendDir
    try {
        npm.cmd run check:ui-ux-guards
    } finally {
        Pop-Location
    }
}

Invoke-Step "Frontend production build" {
    Push-Location $frontendDir
    try {
        npm.cmd run build
    } finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "Stability gates passed." -ForegroundColor Green
