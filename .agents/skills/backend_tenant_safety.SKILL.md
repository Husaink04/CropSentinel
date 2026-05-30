# Backend Tenant Safety

Use this skill when backend work touches auth, tenant scoping, machine enrollment, DLP/phishing incidents, or platform versus tenant boundaries.

## Focus

- `backend/app/routers`
- `backend/app/services`
- `backend/app/repos`
- `backend/tests/test_agent_ingestion.py`
- `backend/tests/test_tenant_isolation.py`

## Workflow

1. Trace the exact route, service, and persistence path.
2. Confirm tenant context is preserved on both read and write paths.
3. Check whether the UI or agent depends on the payload shape.
4. Add or update a regression test for the leak or auth boundary.
5. Report any migration, seed, or env dependency.

## Minimum Verification

```powershell
py -m pytest backend\tests\test_agent_ingestion.py backend\tests\test_tenant_isolation.py -q
```
