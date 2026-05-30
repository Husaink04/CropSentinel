param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\\..")).Path,
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [switch]$RestoreRedis,
    [switch]$RestoreObjectStorage,
    [switch]$RestoreClickHouse
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $BackupDir)) {
    throw "Backup directory not found: $BackupDir"
}

Push-Location $ProjectRoot
try {
    $dbDump = Join-Path $BackupDir "db\\postgres.sql"
    if (Test-Path $dbDump) {
        Get-Content -Path $dbDump -Raw | docker compose exec -T db psql -U postgres -d croppro
    }

    if ($RestoreRedis) {
        $redisDump = Join-Path $BackupDir "redis\\dump.rdb"
        if (Test-Path $redisDump) {
            docker compose cp $redisDump redis:/tmp/cropsentinel-restore.rdb | Out-Null
            Write-Host "Redis restore file copied to container. Restart redis with persistence enabled to complete restore."
        }
    }

    if ($RestoreObjectStorage) {
        $minioDir = Join-Path $BackupDir "minio\\data"
        if (Test-Path $minioDir) {
            Write-Host "Object storage restore requires replacing MinIO data while the service is stopped."
            Write-Host "Saved backup path: $minioDir"
        }
    }

    if ($RestoreClickHouse) {
        $clickhouseDir = Join-Path $BackupDir "clickhouse\\data"
        if (Test-Path $clickhouseDir) {
            Write-Host "ClickHouse restore requires replacing ClickHouse data while the service is stopped."
            Write-Host "Saved backup path: $clickhouseDir"
        }
    }
}
finally {
    Pop-Location
}

Write-Host "Restore workflow completed."
