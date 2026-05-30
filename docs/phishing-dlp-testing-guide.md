# CropSentinel Phishing and DLP Guide

This guide is for understanding what the two modules do and how to test them in a simple, repeatable way.

Use this guide when you want to answer:

- what DLP does
- what phishing protection does
- how the agent, backend, and UI work together
- how to test safely
- what result you should expect

## 1. Simple Difference

### DLP
DLP means Data Loss Prevention.

It watches for sensitive data movement, for example:

- copying files
- deleting files
- moving files
- uploads
- risky file transfers
- content that matches sensitive patterns like email, API key, card number, password text, or custom regex

Main goal:
Stop or warn about sensitive data leaving the machine or being handled in a risky way.

### Phishing Protection
Phishing protection watches for suspicious websites and suspicious destination activity.

It currently focuses mainly on browser visits and warns the user if a page looks risky.

Examples:

- fake Microsoft login page
- fake Google login page
- suspicious domain with strange TLD like `.zip`
- login page wording on a suspicious domain
- known bad domain from built-in threat intel

Main goal:
Warn the user before they enter credentials or download something dangerous.

## 2. High-Level Flow

### DLP flow
1. User creates, modifies, deletes, or transfers files.
2. Agent watches file activity and DLP-related context.
3. Agent sends events to backend.
4. Backend evaluates policy and groups events into incidents.
5. Alerts and incidents appear in the customer dashboard.

### Phishing flow
1. User opens or visits a website.
2. Agent reads browser history / browser visit data.
3. Agent checks the URL and domain against phishing heuristics.
4. If risky enough, the agent sends a phishing event.
5. Backend stores the event, creates or updates an incident, and sends alert updates to the UI.
6. In `warn_only` mode, the user gets a warning popup on the machine.

## 3. Where to See It in the Product

### Customer portal

- `DLP Events`
- `Phishing Protection`
- `Alerts`
- `File Logs`
- `Browser Logs`

### Platform portal

- `Platform DLP`
- `Platform Phishing`
- `Tenant Management`

## 4. Main Backend Endpoints

### DLP

- `GET /api/dlp/policy/effective`
- `GET /api/dlp/policies`
- `POST /api/dlp/policies`
- `POST /api/dlp/policies/{id}/publish`
- `GET /api/dlp/incidents`
- `GET /api/dlp/incidents/{id}`
- `PUT /api/dlp/incidents/{id}`
- `GET /api/dlp/diagnostics/machines/{machine_id}`

### Phishing

- `GET /api/phishing/policy/effective`
- `GET /api/phishing/policies`
- `POST /api/phishing/policies`
- `PUT /api/phishing/policy`
- `POST /api/phishing/policies/{id}/publish`
- `GET /api/phishing/events`
- `GET /api/phishing/incidents`
- `GET /api/phishing/incidents/{id}`
- `PUT /api/phishing/incidents/{id}`
- `GET /api/phishing/diagnostics/machines/{machine_id}`
- `GET /api/platform/phishing/baseline`
- `PUT /api/platform/phishing/policy`

## 5. What the Agent Is Doing

### DLP agent behavior

- tracks file operations
- may attach deleted file backup data for vault recovery
- sends DLP-related event metadata
- receives effective DLP policy from backend

### Phishing agent behavior

- reads browser history entries
- extracts URL, title, and domain
- applies built-in heuristics
- sends `phishing_alert` events through the existing queue
- shows local warning popup for matched risky visits in `warn_only` mode

## 5A. How to Read Backend Decisions

When support says "I triggered it but nothing appeared", check backend logs for the decision line first.

### DLP decision log

Log name:

- `dlp_decision`

Important fields:

- `tenant_id`
- `machine_id_prefix`
- `file_name`
- `destination_type`
- `severity`
- `action_taken`
- `action_result`
- `matched_rule`
- `exception_applied`
- `unsupported_reason`
- `classifier_hits`

Quick meaning:

- `action_taken=monitor` and `action_result=observed`
  - the event was seen but only matched a monitor-style outcome
- `exception_applied=True`
  - the event was intentionally suppressed by an active exception
- `unsupported_reason=endpoint_enforcement_not_available_in_current_agent_channel`
  - the policy asked for stronger prevention, but the current endpoint/channel can only observe

### Phishing decision log

Log name:

- `phishing_decision`

Important fields:

- `tenant_id`
- `machine_id_prefix`
- `domain`
- `severity`
- `matched`
- `action_taken`
- `action_result`
- `warning_shown`
- `reason_codes`
- `unsupported_reason`

Quick meaning:

- `matched=False`
  - the score stayed below the phishing threshold
- `action_result=allowlisted`
  - the domain was intentionally excluded by allowlist
- `warning_shown=True`
  - the backend requested a warn-only popup on the endpoint
- `reason_codes`
  - explains why the score was raised, for example `known_malicious_domain` or `suspicious_login_combination`

## 6. Safe Test Setup

Use a test tenant if possible.

If you want a repeatable cross-tenant smoke first, run:

```powershell
.\tools\run-tenant-safety-smoke.ps1 -DatabaseUrl "postgresql://postgres:YOUR_PASSWORD@localhost:5432/croppro"
```

Runbook:

- [Tenant safety smoke runbook](C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/tenant-safety-smoke-runbook.md)

Before testing:

1. Make sure backend is running.
2. Make sure frontend is running or built.
3. Make sure agent is registered to the correct tenant.
4. Log in as tenant admin.
5. Keep these pages open:
   - `Alerts`
   - `DLP Events`
   - `Phishing Protection`
   - `File Logs`
   - `Browser Logs`

## 7. How to Test DLP

### Test A: Basic file log
Purpose:
Check that file activity is reaching backend.

Steps:
1. On the agent machine, create a file like `dlp-test-1.txt`.
2. Add some text.
3. Save it.
4. Open `File Logs`.

Expected result:

- a `create` or `modify` file event appears
- machine name is correct
- tenant data stays inside the current tenant only

### Test B: Deleted file recovery / secret vault
Purpose:
Check deleted-file capture.

Steps:
1. Create a small text file.
2. Save it.
3. Wait a few seconds.
4. Delete it.
5. Open `File Logs`.
6. Check if delete event says backed up / recoverable.
7. Open Secret Vault if your UI exposes it.

Expected result:

- delete event appears
- backup status is visible
- if file type is safe and size is small, it should be recoverable

If it fails:

- the file may be too large
- the file may be excluded by skip rules
- the file may have been deleted before the cache captured it

### Test C: Sensitive pattern detection
Purpose:
Check that sensitive content creates DLP hits.

Steps:
1. Create a text file.
2. Put test-only sample content inside, for example:

```text
email: test.user@example.com
password=TempPass123!
api_key=sk-test-123456789
```

3. Save or move the file depending on your DLP setup.
4. Open `DLP Events`.

Expected result:

- DLP raw event appears
- findings show matched pattern types
- event may become a grouped incident
- incident severity depends on policy and matched rule
- backend logs should show one `dlp_decision` entry for the same machine

### Test D: Incident grouping
Purpose:
Check spam reduction.

Steps:
1. Trigger the same sensitive file behavior multiple times within a short time.
2. Open `DLP Events` incident tab.

Expected result:

- backend should group repeated related events into one incident
- event count should go up instead of flooding many incidents

### Test E: Tenant isolation
Purpose:
Check security boundary.

Steps:
1. Trigger DLP events in tenant A.
2. Log in as tenant B admin.
3. Open `DLP Events`, `Alerts`, and `File Logs`.

Expected result:

- tenant B must not see tenant A DLP data

## 8. How to Test Phishing Protection

Important:
Use safe fake domains for testing. Do not visit real malicious domains.

Recommended safe test examples:

- `https://login-microsoftonline-security.com`
- `https://okta-authenticate-secure.com`
- `https://github-verify-login.com`

These are built into the current v1 heuristics as suspicious / known-bad test cases.

### Test A: Browser event visibility
Purpose:
Make sure browser telemetry is working first.

Steps:
1. Open a normal website in Chrome or Edge.
2. Wait for sync.
3. Open `Browser Logs`.

Expected result:

- the visited domain appears

If this fails, phishing detection will also fail because it depends on browser activity.

### Test B: Known bad domain detection
Purpose:
Check the main phishing pipeline.

Steps:
1. Visit one of the safe fake test domains above.
2. Wait for the agent sync interval.
3. Open `Phishing Protection`.
4. Open `Alerts`.

Expected result:

- phishing raw event appears
- phishing incident appears
- severity is usually `high` or `critical`
- alert appears
- local warning popup should appear on the agent machine
- backend logs should show `phishing_decision` with the exact `reason_codes`

### Test C: Suspicious TLD heuristic
Purpose:
Check heuristic scoring.

Steps:
1. Visit a harmless test URL using a suspicious TLD pattern if available.
2. Example shape:
   - `https://some-login-example.zip`
3. Open `Phishing Protection`.

Expected result:

- event may appear with reason code like `suspicious_tld`
- if combined with login wording or lookalike brand signals, it should become an incident

### Test D: Lookalike brand heuristic
Purpose:
Check fake brand domain detection.

Steps:
1. Visit a fake login-style domain that includes a known brand but is not the official domain.
2. Example:
   - `https://microsoft-login-check.example`

Expected result:

- reason code may include `lookalike_brand_domain`
- if the title or URL also includes login wording, score should increase

### Test E: Incident update workflow
Purpose:
Check analyst workflow.

Steps:
1. Open a phishing incident in the `Phishing Protection` page.
2. Change status to `triaged` or `resolved`.
3. Add an assignee or note.
4. Save.

Expected result:

- incident updates successfully
- notes/timeline stay in the correct tenant

### Test F: Allowlist behavior
Purpose:
Check exception handling.

Steps:
1. Add a trusted domain to phishing allowlist.
2. Visit that same domain.
3. Refresh `Phishing Protection`.

Expected result:

- either no incident is created, or event is treated as allowlisted
- it should not raise a normal phishing warning
- backend logs should show `action_result=allowlisted`

## 9. What Good Results Look Like

### DLP good result

- file events visible
- sensitive content hits visible
- incidents grouped
- tenant isolation preserved
- alert appears only inside correct tenant

### Phishing good result

- browser visit visible
- suspicious domain produces event
- incident created or updated
- warning shown to user in `warn_only` mode
- alert visible only in correct tenant

## 10. Common Problems and Meaning

### DLP event not showing
Possible reasons:

- file tracker not running
- event queue not flushing
- backend ingestion error
- file was excluded or unsupported

Check:

- backend logs
- agent logs
- `File Logs`
- `DLP Events`
- `dlp_decision` log line for the same machine

### Deleted file not in vault
Possible reasons:

- file too large
- excluded file type
- delete happened before backup cache was ready

### Phishing event not showing
Possible reasons:

- browser history tracking not working
- test domain not risky enough
- sync interval delay
- agent did not get latest phishing policy

Check:

- `Browser Logs`
- `Phishing Protection`
- backend logs
- agent logs
- `phishing_decision` log line for the same domain

### Warning popup not shown
Possible reasons:

- policy not in `warn_only`
- score below threshold
- local popup call failed on the endpoint

Check:

- effective phishing policy
- latest phishing event severity
- agent log line for phishing warning
- `phishing_decision` should show whether it was below threshold, allowlisted, or warn-only

## 10A. Support Runbook

Use this when a customer says phishing or DLP is not working.

### How to confirm browser tracking is working

1. Open a normal website on the agent machine.
2. Wait one sync cycle.
3. Open `Browser Logs`.

If working:

- the domain appears in browser logs

If not working:

- phishing detection cannot work yet because it depends on browser telemetry first

### How to confirm a phishing popup should have appeared

Check these in order:

1. `Phishing Protection` raw events page
2. `severity` is `medium`, `high`, or `critical`
3. `action_taken` is `warn_user`
4. effective policy `rollout_mode` is `warn_only`

If all four are true:

- a local warning popup was expected on the endpoint

If `action_result` is `allowlisted`:

- a popup is not expected

If there is no event at all:

- the browser event never reached phishing detection

### How to tell no event vs allowlisted vs below threshold

#### No event

- nothing appears in `Phishing Protection`
- usually means browser tracking failed or the backend never received the visit

#### Allowlisted

- event may appear with `action_result=allowlisted`
- no incident is expected
- no normal warning is expected

#### Below threshold

- browser log exists
- phishing event may not exist, or exists without incident creation depending on flow
- domain did not score high enough to cross incident threshold

### Data visible in wrong tenant
This is a blocker issue.

If a phishing or DLP alert from tenant A is visible in tenant B:

1. stop testing
2. capture screenshot
3. note exact machine, tenant, and event time
4. treat it as tenant-isolation bug

## 11. Recommended Basic Test Run

If you want one short end-to-end test session, do this:

1. Open tenant dashboard.
2. Open `File Logs`, `DLP Events`, `Phishing Protection`, and `Alerts`.
3. Create and save a text file.
4. Put test sensitive text into it.
5. Delete the file.
6. Check file logs and vault behavior.
7. Visit one safe fake phishing test domain.
8. Wait for sync.
9. Check phishing event, incident, alert, and local warning popup.
10. Log into another tenant and confirm none of this is visible there.

## 11A. Minimum Release Gate

Do not treat DLP + phishing as release-ready unless all of these are true:

1. DLP event in tenant A is not visible in tenant B.
2. Phishing event in tenant A is not visible in tenant B.
3. Known-bad phishing test domain creates:
   - raw event
   - incident
   - alert
4. DLP flow still works after phishing changes.

## 12. Recommended Next Improvements

The current phishing module is usable, but still v1.

Best next upgrades:

- add automated backend tests for phishing event ingestion
- add tenant-isolation tests for phishing alerts and incidents
- add stronger download correlation
- add clearer machine diagnostics in UI
- add support checklist for phishing-specific troubleshooting

## 13. File Locations for Developers

### DLP backend

- [backend/app/services/dlp_service.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/services/dlp_service.py)
- [backend/app/routers/dlp_enterprise.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/routers/dlp_enterprise.py)
- [backend/app/db/dlp_enterprise_methods.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/db/dlp_enterprise_methods.py)

### Phishing backend

- [backend/app/services/phishing_service.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/services/phishing_service.py)
- [backend/app/routers/phishing.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/routers/phishing.py)
- [backend/app/db/phishing_methods.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/db/phishing_methods.py)

### Agent

- [agent/agent.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/agent/agent.py)
- [agent/file_tracker.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/agent/file_tracker.py)
- [agent/phishing_protection.py](C:/Users/husai/OneDrive/Desktop/CropSentinel/agent/phishing_protection.py)

### Frontend

- [frontend/src/pages/DLPEvents.jsx](C:/Users/husai/OneDrive/Desktop/CropSentinel/frontend/src/pages/DLPEvents.jsx)
- [frontend/src/pages/Phishing.jsx](C:/Users/husai/OneDrive/Desktop/CropSentinel/frontend/src/pages/Phishing.jsx)
- [frontend/src/pages/PlatformDlp.jsx](C:/Users/husai/OneDrive/Desktop/CropSentinel/frontend/src/pages/PlatformDlp.jsx)
- [frontend/src/pages/PlatformPhishing.jsx](C:/Users/husai/OneDrive/Desktop/CropSentinel/frontend/src/pages/PlatformPhishing.jsx)
