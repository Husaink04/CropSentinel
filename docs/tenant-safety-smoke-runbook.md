# Tenant Safety Smoke Runbook

Use this when you want a fast answer to one question:

Can tenant A trigger DLP and phishing activity without tenant B seeing it?

This runbook uses the built-in smoke script first, then a short UI check.

## What this verifies

- tenant A can see its own seeded DLP event
- tenant A can see its own seeded phishing event
- tenant B cannot see tenant A markers
- platform portal shows baseline governance only, not tenant incident leakage

## Before you start

Make sure these are running:

- PostgreSQL
- backend on `http://localhost:8000`
- frontend on `http://localhost:5173`

Also make sure:

- you have at least 2 tenants
- tenant A has at least 1 registered machine

Default smoke users created by the script:

- tenant A: `smoke-admin-a`
- tenant B: `smoke-admin-b`
- password for both: `SmokePass!123`

The script will create or reset those users each time.

## Fast path

From the repo root:

```powershell
.\tools\run-tenant-safety-smoke.ps1 -DatabaseUrl "postgresql://postgres:YOUR_PASSWORD@localhost:5432/croppro"
```

If your backend enforces `AGENT_API_KEY`, pass it too:

```powershell
.\tools\run-tenant-safety-smoke.ps1 `
  -DatabaseUrl "postgresql://postgres:YOUR_PASSWORD@localhost:5432/croppro" `
  -AgentApiKey "YOUR_AGENT_API_KEY"
```

If tenant B is not the first non-default tenant, pass its slug:

```powershell
.\tools\run-tenant-safety-smoke.ps1 `
  -DatabaseUrl "postgresql://postgres:YOUR_PASSWORD@localhost:5432/croppro" `
  -TenantBSlug "x-code"
```

## What the script does

1. Finds tenant A and tenant B.
2. Finds one machine in tenant A.
3. Creates or updates the two smoke admins.
4. Seeds one DLP event and one phishing event into tenant A.
5. Logs into the API as tenant A and confirms the markers are visible.
6. Logs into the API as tenant B and confirms the markers are not visible.
7. Logs into the platform API and confirms only baseline governance views are returned.

If the script passes, it prints a JSON summary with:

- machine used
- exact file/domain markers
- event and incident ids
- pass/fail checks

## Quick UI check after the script

Use the exact markers printed by the script.

### Tenant A

Sign in as:

- username: `smoke-admin-a`
- password: `SmokePass!123`

Check:

- `DLP Events`
- `Phishing Protection`
- `Alerts`

Expected:

- the DLP file marker is visible
- the phishing domain marker is visible

### Tenant B

Sign in as:

- username: `smoke-admin-b`
- password: `SmokePass!123`

Check the same pages:

- `DLP Events`
- `Phishing Protection`
- `Alerts`

Expected:

- neither tenant A marker appears

### Platform portal

Sign in at `/platform/login` using the tenant A smoke admin:

- username: `smoke-admin-a`
- password: `SmokePass!123`

Check:

- `/platform/dlp`
- `/platform/phishing`

Expected:

- baseline policies and governance views appear
- seeded tenant markers do not appear

## What failure means

### Script fails with "No machine found"

Tenant A does not have a registered machine yet.

Fix:

- register one agent to tenant A
- rerun the script

### Script fails on DLP or phishing seed POST

Possible causes:

- backend is not running
- wrong `AGENT_API_KEY`
- backend URL is wrong

### Script fails because tenant B sees a marker

Treat this as a release blocker.

Check immediately:

- tenant scoping in the affected list endpoint
- alert creation path
- websocket fanout path
- machine-to-tenant resolution in the ingestion route

### Platform baseline check fails

Treat this as a platform/customer boundary bug.

Check:

- platform route auth
- tenant context middleware
- baseline service response shaping

## Recommended release use

Use this order:

1. `.\tools\run-stability-gates.ps1`
2. `.\tools\run-tenant-safety-smoke.ps1`
3. 2-minute UI check in tenant A, tenant B, and platform portal

If step 2 fails, do not release.
