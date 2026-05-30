# UI/UX Regression Checklist (Pre-Release)

Run this checklist before production deployment.

## 1) Shell / Navigation

- Sidebar labels and routes match page titles.
- Topbar shows page title + breadcrumb path.
- Role-based nav visibility has no dead links.
- Current context pill appears on data-heavy pages (teams, machines, users, live, remote).

## 2) Canonical Page States

For each key page (`/machines`, `/teams`, `/teams/:id`, `/alerts`, `/users`, `/live`, `/remote`):

- `loading`: spinner renders while first fetch runs.
- `empty`: clear empty-state copy when response is valid but empty.
- `error`: inline blocking banner with retry action.
- `ready`: primary content renders.
- `partial`: stale content remains visible while banner indicates refresh error (where applicable).

## 3) Realtime Reliability (Live + Remote)

- `connecting`: visible status banner while negotiation starts.
- `connected`: viewer active without warnings.
- `reconnecting`: banner appears after unstable network event.
- `degraded`: explicit JPEG fallback status shown.
- `disconnected` / `permission_denied`: actionable failure messaging shown.
- Retry action is present when reconnect is possible.

## 4) Table + Form Consistency

- Search/filter controls are above tables and never clipped on tablet/mobile.
- Pagination controls are visible and keyboard reachable.
- Create/edit buttons disable during in-flight save.
- Validation errors are shown before submit; success/failure messages surface through notification center.

## 5) Accessibility + Responsive

- Keyboard-only navigation works for sidebar, filters, row actions, modals, and remote controls.
- Focus ring is visible in dark/light themes.
- Reduced-motion preference suppresses non-essential animations.
- Mobile/tablet layouts keep topbar actions and filter controls accessible.

## 6) Release Gate

Required:

- `npm --prefix frontend run check:ws-order`
- `npm --prefix frontend run check:ui-ux-guards`
- `npm --prefix frontend run build`

Release blocker if any key flow fails:

- Teams flow (`/teams`, `/teams/:id`)
- Machine detail/access flow (`/machines`, `/machines/:id`)
- Live/remote flow (`/live`, `/remote`)
- Platform tenant flow (`/platform`, `/platform/tenants`)
