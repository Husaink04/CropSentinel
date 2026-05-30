param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path,
    [string]$OutputRoot = "",
    [switch]$SkipRedis,
    [switch]$SkipObjectStorage,
    [switch]$SkipClickHouse
)

$ErrorActionPreference = "Stop"

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $ProjectRoot "backend\\storage\\ops\\backups"
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $OutputRoot $timestamp
$null = New-Item -ItemType Directory -Force -Path $backupDir
$null = New-Item -ItemType Directory -Force -Path (Join-Path $backupDir "db")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $backupDir "redis")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $backupDir "minio")
$null = New-Item -ItemType Directory -Force -Path (Join-Path $backupDir "clickhouse")

$status = @{
    started_at = (Get-Date).ToUniversalTime().ToString("o")
    backup_dir = $backupDir
    targets = @{}
}

Push-Location $ProjectRoot
try {
    $dbTarget = Join-Path $backupDir "db\\postgres.sql"
    docker compose exec -T db pg_dump -U postgres croppro | Set-Content -Path $dbTarget -Encoding UTF8
    $status.targets.postgres = @{
        status = "ok"
        file = $dbTarget
        last_success_at = (Get-Date).ToUniversalTime().ToString("o")
    }

    if (-not $SkipRedis) {
        docker compose exec -T redis sh -lc "redis-cli --rdb /tmp/cropsentinel-backup.rdb"
        docker compose cp redis:/tmp/cropsentinel-backup.rdb (Join-Path $backupDir "redis\\dump.rdb") | Out-Null
        $status.targets.redis = @{
            status = "ok"
            file = (Join-Path $backupDir "redis\\dump.rdb")
            last_success_at = (Get-Date).ToUniversalTime().ToString("o")
        }
    }

    if (-not $SkipObjectStorage) {
        docker compose cp minio:/data (Join-Path $backupDir "minio\\data") | Out-Null
        $status.targets.object_storage = @{
            status = "ok"
            file = (Join-Path $backupDir "minio\\data")
            last_success_at = (Get-Date).ToUniversalTime().ToString("o")
        }
    }

    if (-not $SkipClickHouse) {
        docker compose cp clickhouse:/var/lib/clickhouse (Join-Path $backupDir "clickhouse\\data") | Out-Null
        $status.targets.clickhouse = @{
            status = "ok"
            file = (Join-Path $backupDir "clickhouse\\data")
            last_success_at = (Get-Date).ToUniversalTime().ToString("o")
        }
    }

    $status.completed_at = (Get-Date).ToUniversalTime().ToString("o")
    $status.status = "ok"
}
catch {
    $status.completed_at = (Get-Date).ToUniversalTime().ToString("o")
    $status.status = "failed"
    $status.error = $_.Exception.Message
    throw
}
finally {
    $opsDir = Join-Path $ProjectRoot "backend\\storage\\ops"
    $null = New-Item -ItemType Directory -Force -Path $opsDir
    $statusPath = Join-Path $opsDir "backup-status.json"
    $status | ConvertTo-Json -Depth 10 | Set-Content -Path $statusPath -Encoding UTF8
    Pop-Location
}

Write-Host "Backup complete: $backupDir"
