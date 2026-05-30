param(
  [string]$DatabaseUrl = $env:DATABASE_URL,
  [string]$BackendUrl = $(if ($env:CROPPRO_SERVER) { $env:CROPPRO_SERVER } else { "http://localhost:8000" }),
  [string]$AgentApiKey = $env:AGENT_API_KEY,
  [string]$TenantASlug = "default",
  [string]$TenantBSlug = "",
  [string]$MachineId = "",
  [string]$TenantAUsername = "smoke-admin-a",
  [string]$TenantBUsername = "smoke-admin-b",
  [string]$SmokePassword = "SmokePass!123"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$args = @(
  ".\tools\tenant_safety_smoke.py",
  "--database-url", $DatabaseUrl,
  "--backend-url", $BackendUrl,
  "--tenant-a-slug", $TenantASlug,
  "--tenant-a-username", $TenantAUsername,
  "--tenant-b-username", $TenantBUsername,
  "--smoke-password", $SmokePassword
)

if ($AgentApiKey) { $args += @("--agent-api-key", $AgentApiKey) }
if ($TenantBSlug) { $args += @("--tenant-b-slug", $TenantBSlug) }
if ($MachineId) { $args += @("--machine-id", $MachineId) }

py @args
