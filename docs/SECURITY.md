# CropSentinel — Security Threat Model

Last reviewed: 2026-04-21 (HIGH priority hardening pass)

This document captures the current authentication/authorization model, the
attack surface we explicitly defend against, and the risks we've accepted.
Update it whenever auth flow changes.

---

## 1. Authentication surfaces

| Surface                 | Credential type                       | Transport         |
|-------------------------|----------------------------------------|-------------------|
| Customer dashboard      | JWT bearer token (localStorage)        | HTTPS + Bearer    |
| Platform admin portal   | JWT bearer token (localStorage, separate key) | HTTPS + Bearer |
| Agent → server WS/HTTP  | `X-CropPro-Agent-Key` header (shared secret) | HTTPS         |

**No HTTP cookies are used for authentication.** This is deliberate — it is
the primary reason we do not require CSRF tokens (see §3).

---

## 2. Brute-force protection

Implemented in `backend/main.py`:

* **IP rate limit** — slowapi, `10 requests / 15 min` on `/api/auth/login` and
  `/api/platform/login`. Keyed by `get_remote_address`. Blocks naive scripted
  attacks from a single source.
* **Per-username lockout** — in-memory sliding-window tracker at module
  scope. `LOGIN_FAIL_THRESHOLD` (default 8) failed attempts within
  `LOGIN_FAIL_WINDOW` (default 900s / 15 min) locks the account for
  `LOGIN_LOCKOUT_SECONDS` (default 900s). Clears on successful login.
  Blocks an attacker rotating source IPs against a single account.
* **Audit logging** — every success and failure writes an `audit_log`
  entry (`login_failed`, `login_locked`, `login`, `platform_login`).

Known gap: the per-username tracker is per-worker (process-local). For
multi-worker deployments where this must be authoritative, back it with
Redis. The IP limit still backstops fleet-wide abuse.

---

## 3. CSRF

**Not applicable in the current design.**

Why:

1. All browser ↔ API requests carry `Authorization: Bearer <jwt>`. The
   browser only attaches this header when our own JS code explicitly sets
   it (via `useApi`). A cross-site request from `evil.com` cannot read the
   token out of `localStorage` and cannot force its inclusion — browsers
   do not auto-send custom headers cross-origin.
2. CORS is restricted to the configured origin list (`_cors`). Cross-origin
   requests without matching `Access-Control-Allow-Origin` are blocked by
   the browser.
3. No endpoint reads `request.cookies` for auth. A grep for `cookie` in
   `backend/main.py` returns zero matches. Keep it that way.

**If this ever changes** — if we add a `Set-Cookie`-based session
(e.g. for an SSR path or to support non-JS clients) — CSRF tokens become
mandatory on every state-changing request. Rule of thumb: cookies in,
CSRF tokens in.

Related concern: **XSS is a bigger risk** because a token in localStorage
is readable by any script that runs on our origin. Mitigations:

* Strict CSP (TODO — not yet enforced; see §5).
* `React.lazy` + no `dangerouslySetInnerHTML` outside the chart library.
* All user-supplied strings rendered via React's default text escaping.

---

## 4. Agent channel hardening

* Shared-secret header `X-CropPro-Agent-Key` required on every
  `/api/activity/*` endpoint and on the agent WebSocket upgrade.
* If `ENV=production` and `AGENT_API_KEY` is not set, the server refuses
  to start — an open agent channel would let anyone stream fabricated
  activity into customer tenants.
* Per-tenant enrollment via `X-CropPro-Enroll-Token` binds an agent to
  a tenant at registration time; the token maps to `tenant_id` and is
  what prevents one tenant's agent from writing into another tenant's
  activity tables.

---

## 5. Storage & resource limits

* **Screenshot storage quota** — `SCREENSHOT_QUOTA_MB` (default 500 MB)
  per tenant. Enforced probabilistically (every ~20th insert runs a SUM
  + oldest-first GC) to prevent one runaway agent from filling the
  volume for every other tenant. `0` disables the GC for development.
* **TODO** — no equivalent quota yet on activity logs (browser/app/file/
  network). Today bounded only by retention policy. Track as follow-up.

---

## 6. Accepted risks

| Risk | Mitigation / acceptance                                            |
|------|--------------------------------------------------------------------|
| JWT leaked via XSS in user-generated field (e.g. company name) | React auto-escapes; strict CSP pending. |
| Shared `AGENT_API_KEY` rotates slowly (restart required) | OK for now; move to per-tenant keys next. |
| In-memory lockout is per-worker | Single-worker deployments are unaffected; Redis backer planned. |
| `image_data` stored as base64 text, not BYTEA | ~33% bloat accepted; driver compatibility wins. |

---

## 7. When to revisit

Trigger a re-review when:

* We add any cookie-based session (CSRF story changes).
* We go multi-worker in production (per-username lockout needs Redis).
* We ship per-tenant API keys for agents (AGENT_API_KEY semantics change).
* We enable CSP or SRI (XSS surface changes).
