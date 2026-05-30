# Sprint Release Checklist (Stability & Tenant Safety)

Use this checklist before promoting to production.

Fast path:

- PowerShell: `.\tools\run-stability-gates.ps1 -TestDatabaseUrl "postgresql://postgres:YOUR_PASSWORD@localhost:5432/croppro_test"`

## 1. Backend Safety Gates

- Run critical tenant suites:
  - `python -m pytest backend/tests/test_agent_ingestion.py backend/tests/test_tenant_isolation.py -q`
- Run phishing validation suite:
  - `python -m pytest backend/tests/test_phishing.py -q`
- Run full backend suite with coverage:
  - `python -m pytest --cov=app --cov=database --cov=main --cov-fail-under=60`
- Confirm no regressions in agent registration outcomes:
  - `401` missing/invalid enrollment token paths
  - `402` plan/seat-cap paths
  - `403` tenant mismatch path

## 2. Frontend Stability Gates

- Validate websocket callback declaration order guard:
  - `npm --prefix frontend run check:ws-order`
- Build frontend bundle:
  - `npm --prefix frontend run build`
- Smoke-check pages in browser:
  - `/live` loads without init errors
  - `/remote` loads without init errors
  - reconnect path works and degraded mode (WebRTC -> JPEG) still renders

## 3. Observability Gates

- Verify Sentry DSN configured for backend and frontend.
- Confirm registration tags are visible in Sentry events:
  - `registration_status`
  - `registration_error_type`
  - `enroll_token_present`
- Confirm scrubbing of sensitive fields (password/JWT/license key) remains active.

## 4. Repo Hygiene

- Ensure temp artifacts are absent:
  - `agent/agent.py.tmp.*`
  - accidental non-source folders/files
- Confirm `.gitignore` includes temp artifact patterns.

## 5. Support Readiness

- Confirm `docs/monitoring.md` 5-minute tenant-binding checklist is current.
- Confirm operator runbook includes registration outcome handling for `401/402/403`.
- Confirm phishing/DLP guide includes:
  - browser tracking verification
  - popup expected/not-expected guidance
  - allowlisted vs below-threshold troubleshooting

## 6. Tenant Safety Smoke

- Run the repeatable smoke seed + API verification:
  - `.\tools\run-tenant-safety-smoke.ps1 -DatabaseUrl "postgresql://postgres:YOUR_PASSWORD@localhost:5432/croppro"`
- Review the short operator runbook if the smoke fails:
  - [Tenant safety smoke runbook](C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/tenant-safety-smoke-runbook.md)
- Trigger one DLP event in tenant A and confirm tenant B does not see it.
- Trigger one phishing event in tenant A and confirm tenant B does not see it.
- Confirm the platform portal shows phishing baseline governance only, not tenant incident queue data.

## 7. Go/No-Go Rule

Release is blocked if any of the following is true:

- critical tenant-safety tests fail
- phishing validation tests fail
- coverage falls below 60%
- `/live` or `/remote` throws initialization/runtime error in smoke test
- known cross-tenant ingestion route remains open
