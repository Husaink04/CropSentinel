# Monitoring

## Backend Sentry

- Set `SENTRY_DSN` in the backend environment to enable error reporting.
- Optional knobs:
  - `SENTRY_ENVIRONMENT` defaults to `ENV` or `development`
  - `SENTRY_RELEASE` tags deployed builds
  - `SENTRY_TRACES_SAMPLE_RATE` defaults to `0.1`
- Request context is tagged with `tenant_id`, `user_role`, and `endpoint` when available.

## Scrubbing

- Passwords, JWTs, authorization headers, license keys, and TURN credentials are filtered before events are sent.
- Verify scrubbing with `pytest backend/tests/test_monitoring.py`.

## Triage

- Start with the event tags to identify tenant and route.
- Check grouped issues first; resolve noisy duplicates by tightening filters instead of muting whole projects.
- Treat repeated tenant-isolation or auth errors as release blockers.

## Alerting

- In Sentry, create an issue alert for `level:error` on new issues.
- Send alerts to Slack or email depending on what the team already uses.
- Keep performance traces sampled lower than errors unless you are actively investigating latency.

## Agent Registration Signals

The backend now emits deterministic registration failure classes via HTTP status + reason-coded detail:

- `401` + `missing_enrollment_token:*`  
  Agent started without `CROPPRO_ENROLL_TOKEN` on a multi-tenant installation.
- `401` + `invalid_enrollment_token:*`  
  Enrollment token does not map to an active tenant.
- `402` + `tenant_subscription_expired:*` or `tenant_seat_cap:*`  
  Tenant plan state blocks new registrations.
- `403` + `tenant_mismatch:*`  
  Machine is already bound to another tenant.

Sentry tags to filter by:

- `registration_status`
- `registration_error_type`
- `enroll_token_present`

## 5-Minute Tenant-Binding Checklist (Support)

1. On the agent host, open `C:\ProgramData\CropPro\config.env` and confirm:
   - `CROPPRO_SERVER` points to the expected backend
   - `CROPPRO_ENROLL_TOKEN` is present
2. Check local diagnostics: `~/.croppro_agent/registration_status.json`
   - read `status` and `detail`
3. Verify machine appears under the expected tenant in platform/tenant dashboard.
4. Validate isolation:
   - from another tenant admin account, machine must not appear in `/api/machines`.
5. If failing:
   - `401` => token missing/invalid
   - `402` => plan/license/seat issue
   - `403` => machine already bound to different tenant
