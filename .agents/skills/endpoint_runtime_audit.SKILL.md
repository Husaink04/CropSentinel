# Endpoint Runtime Audit

Use this skill when a task touches the Python endpoint agent, DLP capture, queueing, transport, watchdog logic, or Windows service behavior.

## Focus

- `agent/agent.py`
- `agent/file_tracker.py`
- `agent/dlp_engine.py`
- `agent/phishing_protection.py`
- `agent/offline_queue.py`
- `agent/watchdog.py`

## Workflow

1. Confirm whether the behavior is detect-only, warn-only, or enforced.
2. Trace event generation through queueing and delivery.
3. Check OS-specific assumptions, especially Windows services and watchdog paths.
4. Verify backend compatibility for the payload or machine lifecycle flow.
5. Prefer explicit failure over silent false coverage.

## Minimum Verification

```powershell
py -m pytest backend\tests\test_agent_live_document_dlp.py -q
py -m pytest backend\tests\test_dlp_file_inventory.py -q
```
