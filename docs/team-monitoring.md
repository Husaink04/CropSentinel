# Team-Based Monitoring System

This document describes the production-ready Team module added to CropSentinel.

## 1. SQL Schema

```sql
CREATE TABLE IF NOT EXISTS teams (
    id          UUID        PRIMARY KEY,
    tenant_id   INTEGER     NOT NULL DEFAULT 1 REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    description TEXT        DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_teams_tenant_name ON teams(tenant_id, name);

CREATE TABLE IF NOT EXISTS team_memberships (
    id          BIGSERIAL   PRIMARY KEY,
    team_id     UUID        NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    machine_id  TEXT        NOT NULL REFERENCES machines(machine_id) ON DELETE CASCADE,
    added_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(team_id, machine_id)
);
CREATE INDEX IF NOT EXISTS idx_team_memberships_team ON team_memberships(team_id);
CREATE INDEX IF NOT EXISTS idx_team_memberships_machine ON team_memberships(machine_id);
```

## 2. FastAPI Routes

- `POST /api/teams` create team
- `GET /api/teams` list teams (paginated, `X-Total-Count`)
- `PUT /api/teams/{team_id}` update team
- `DELETE /api/teams/{team_id}` delete team
- `POST /api/teams/{team_id}/machines` assign machine
- `GET /api/teams/{team_id}/machines` list team machines (paginated, search, status, date range)
- `DELETE /api/teams/{team_id}/machines/{machine_id}` remove machine from team
- `GET /api/machines/{machine_id}/productivity` machine productivity summary
- `GET /api/teams/{team_id}/productivity` team aggregated productivity summary

## 3. Productivity Logic

- Machine-level:
  - Active time from app activity and/or input activity buckets.
  - Idle time from input buckets with no keyboard/mouse events (fallback heuristic when input logs are absent).
  - Productive app time from `settings.productive_apps`.
  - Productive/unproductive browser time from `settings.productive_domains` and `settings.unproductive_domains`.
  - Score normalized to `0-100`, with idle penalty and unproductive-domain penalty.
- Team-level:
  - Aggregates over team memberships only.
  - Computes `total_machines`, `active_machines`, `avg_productivity`, `alerts_count`, app usage, low-productivity list, and daily trend.

## 4. React Components Structure

- `/teams` -> `frontend/src/pages/Teams.jsx`
  - Team list
  - Create/update/delete controls
  - Pagination and search
- `/teams/:teamId` -> `frontend/src/pages/TeamDashboard.jsx`
  - KPI cards
  - Productivity trend chart
  - App usage pie
  - Low productivity highlight
  - Team machine table
  - Assign/remove machine controls
- `/machines/:machineId/productivity` -> `frontend/src/pages/MachineProductivity.jsx`
  - Score gauge
  - Active vs idle breakdown
  - Top apps
  - Activity timeline

## 5. Sample API Responses

### `GET /api/machines/{id}/productivity`

```json
{
  "machine_id": "ENG-LAP-01",
  "hostname": "ENG-LAP-01",
  "username": "alice",
  "last_seen": "2026-04-25T11:20:00+00:00",
  "active_time_seconds": 24300,
  "idle_time_seconds": 4200,
  "top_apps": [
    { "app_name": "VS Code", "total_seconds": 8100 },
    { "app_name": "Chrome", "total_seconds": 6900 }
  ],
  "productivity_score": 82,
  "productive_app_seconds": 8100,
  "productive_browser_seconds": 5400,
  "unproductive_browser_seconds": 900,
  "timeline": [
    { "type": "active", "label": "Detected input activity", "seconds": 24300 },
    { "type": "idle", "label": "Detected idle windows", "seconds": 4200 }
  ]
}
```

### `GET /api/teams/{id}/productivity`

```json
{
  "team": {
    "id": "f3f8638f-8a52-4a57-af9a-6cf628d96f95",
    "tenant_id": 2,
    "name": "Engineering",
    "description": "Core product engineering",
    "created_at": "2026-04-22T10:00:00+00:00"
  },
  "total_machines": 25,
  "active_machines": 18,
  "avg_productivity": 78,
  "alerts_count": 3,
  "total_active_time_seconds": 181200,
  "aggregated_app_usage": [
    { "app_name": "VS Code", "total_seconds": 46200 },
    { "app_name": "Chrome", "total_seconds": 38400 }
  ],
  "low_productivity_machines": [
    {
      "machine_id": "ENG-LAP-09",
      "hostname": "ENG-LAP-09",
      "username": "john",
      "productivity_score": 32,
      "last_seen": "2026-04-25T09:10:00+00:00"
    }
  ],
  "team_trends": [
    { "date": "2026-04-20", "avg_productivity": 72, "total_active_time_seconds": 22500 },
    { "date": "2026-04-21", "avg_productivity": 76, "total_active_time_seconds": 24900 },
    { "date": "2026-04-22", "avg_productivity": 81, "total_active_time_seconds": 26600 }
  ]
}
```

## Security and Scale Notes

- Tenant isolation is enforced at query level using `tenant_id` filters and scoped joins.
- APIs are paginated to avoid large payloads.
- Team and machine aggregation is pre-filtered to avoid cross-tenant scans.
- RBAC permissions added:
  - `teams.view`
  - `teams.manage`
