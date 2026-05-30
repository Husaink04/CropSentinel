# CropSentinel Backend Tests

## TL;DR

```bash
# 1. Install dev deps
pip install -r requirements-dev.txt

# 2. Create a disposable test database
createdb croppro_test

# 3. Point the suite at it and run
export CROPPRO_TEST_DATABASE_URL="postgresql://postgres:Husain%400404@localhost:5432/croppro_test"
pytest
```

### One-command local profile (PowerShell)

```powershell
$env:CROPPRO_TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/croppro_test"; `
$env:SECRET_KEY="test-secret-key-do-not-use-in-prod-48-chars-minimum-padding-padding"; `
$env:AGENT_API_KEY="test-agent-key"; `
$env:CROPPRO_LICENSE_ENFORCE="0"; `
python -m pytest
```

### Critical tenant-safety smoke (fast)

```bash
python -m pytest tests/test_agent_ingestion.py tests/test_tenant_isolation.py tests/test_phishing.py -q
```

### If you want the shortest DLP + phishing validation run

```bash
python -m pytest tests/test_phishing.py tests/test_agent_ingestion.py -q
```

### Full local release gate

From the repo root:

```powershell
.\tools\run-stability-gates.ps1 -TestDatabaseUrl "postgresql://postgres:YOUR_PASSWORD@localhost:5432/croppro_test"
```

Tests that require the database are marked `integration` and auto-skip when
`CROPPRO_TEST_DATABASE_URL` is not set. Pure-unit tests (e.g. `test_passwords.py`)
always run.

## Why a real Postgres?

The backend uses raw psycopg2 + SQL that depends on Postgres-only features
(`SERIAL`, `RETURNING`, `NOW()`, `TRUNCATE ... RESTART IDENTITY CASCADE`,
`ON CONFLICT`). Swapping in SQLite would require rewriting the query layer.
Running a dedicated test DB is cheaper than that rewrite.

## Fixtures (see `conftest.py`)

| Fixture | Purpose |
|---|---|
| `api` | `httpx.AsyncClient` bound to the FastAPI app via ASGITransport |
| `db` | The shared `Database` facade |
| `default_tenant` | The id=1 "default" tenant, reseeded between tests |
| `make_tenant(slug=..., tier=...)` | Factory: create a tenant |
| `make_user(tenant_id=..., role=...)` | Factory: create a user (returns plaintext pw) |
| `auth_headers(role="admin")` | Log in as a fresh user, return Bearer headers |

Every test starts with a clean slate — the `_clean_db` autouse fixture
truncates tenant-scoped tables and reseeds tenant id=1.

## Writing a test

```python
async def test_admin_can_list_machines(api, auth_headers):
    headers = await auth_headers(role="admin")
    resp = await api.get("/api/machines", headers=headers)
    assert resp.status_code == 200
```

## Coverage

```bash
pytest --cov=app --cov=database --cov=main --cov-report=term-missing
```

## CI

See `.github/workflows/test.yml` (added in Day 8). CI provisions an ephemeral
Postgres service container, sets `CROPPRO_TEST_DATABASE_URL`, and runs:

- critical tenant-safety suites
- phishing validation suite
- full backend coverage suite

## Warning noise on local Python 3.14

If you run the suite locally on Python 3.14, `pytest-asyncio` can emit a large
number of deprecation warnings from inside the plugin itself. Those are not
CropSentinel product warnings and do not reproduce in CI, because CI currently
targets Python 3.11 and 3.12.

`backend/pytest.ini` filters the known `pytest-asyncio` deprecation spam so
real test failures and real application warnings stay visible.

## Monitoring tests

`test_monitoring.py` is intentionally DB-free so payload-scrubbing checks run
even on machines that do not have a disposable Postgres instance available.
