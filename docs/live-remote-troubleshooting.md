# Live / Remote Troubleshooting (Support)

This guide maps user-visible states to fast actions.

## Session States

- `connecting`
  - Meaning: Admin requested session; waiting for agent signaling.
  - Action: Wait up to 15s, then retry once.

- `connected`
  - Meaning: WebRTC media/data channels active.
  - Action: No intervention.

- `reconnecting`
  - Meaning: Agent/network instability detected.
  - Action: Keep session open; if not recovered within 30s, click retry.

- `degraded`
  - Meaning: WebRTC unavailable, JPEG fallback active.
  - Action: Session is still functional for monitoring; verify agent `aiortc` capability for full remote mode.

- `disconnected`
  - Meaning: Session ended or could not be established.
  - Action: Check machine online status and retry.

- `permission_denied`
  - Meaning: User role or token does not allow requested action.
  - Action: Verify RBAC role and tenant binding; retry with authorized account.

## Quick Operator Workflow (<5 min)

1. Confirm machine is online in `/machines`.
2. Open `/live` or `/remote` for that machine.
3. Validate status transitions:
   - `connecting` -> `connected` OR `degraded`.
4. If `disconnected` or repeated `reconnecting`:
   - confirm agent host network stability
   - verify enrollment token and tenant binding
5. If `permission_denied`:
   - verify user has required permission (`screenshots.view` / `remote.access`).

## Escalation Triggers

Escalate to engineering when:

- same tenant sees persistent `degraded` state across multiple machines
- repeated `permission_denied` for valid admin/remote_operator accounts
- `connecting` exceeds 30s on healthy online machines
