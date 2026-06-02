<p align="center">
  <img src="https://img.shields.io/badge/version-7.x-blue?style=flat-square" alt="Version" />
  <img src="https://img.shields.io/badge/.net-8.0-blueviolet?style=flat-square&logo=.net&logoColor=white" alt=".NET" />
  <img src="https://img.shields.io/badge/react-18-61DAFB?style=flat-square&logo=react&logoColor=white" alt="React" />
  <img src="https://img.shields.io/badge/postgresql-16-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/license-proprietary-red?style=flat-square" alt="License" />
</p>

# CropSentinel

Problem statement:
Organizations lack real-time visibility into employee activity and data movement, exposing them to insider threats, data leaks, and productivity blind spots.

Solution:
CropSentinel is a context-aware endpoint monitoring and data protection platform that provides real-time visibility, detects insider risks, and delivers actionable productivity insights, all in a single, transparent system.

Differentiation:
Unlike traditional tools, CropSentinel combines security and productivity insights with full transparency, offline reliability, and cost-effective deployment.

CropSentinel includes:

- real-time machine monitoring
- live view and remote access
- file, browser, app, input, and network telemetry
- alerting, audit logging, and reporting
- platform-level tenant administration
- enterprise DLP policy, incident, and diagnostics foundations

Branding note:
The product is now named `CropSentinel`. Existing technical identifiers such as `CROPPRO_*` remain as compatibility aliases so already deployed agents and configs continue to work.

## Current Product Shape

### Customer portal
- Dashboard, Machines, Teams, Live View, Remote Access
- App Usage, Browser Logs, Productivity, Input Activity
- File Logs, Network Logs, DLP, Alerts, Reports, Users, Settings

### Platform portal
- Overview
- Tenant Management
- Platform Users
- Enterprise DLP baseline workspace
- Phishing baseline workspace

### Backend
- FastAPI API + WebSocket hub
- PostgreSQL-backed tenant-scoped storage
- RBAC, audit logging, licensing hooks, Sentry integration
- next-gen edge tracing, internal event bus foundation, hybrid-ready object storage abstraction, and optional ClickHouse analytics pipeline

### Agent
- C# (.NET 8 Native AOT) endpoint agent
- WebSocket-first transport with HTTP fallback
- file (with active blocking and delete backup caching), app, browser, input (with privacy hashing), network, screenshot, and WebRTC modules

## Enterprise DLP Status

The codebase now includes an enterprise DLP foundation on top of the legacy DLP event flow.

Implemented:
- versioned DLP policies
- DLP rules and classifiers
- tenant exceptions
- grouped DLP incidents with notes and timeline
- effective policy resolution for tenants
- policy simulation endpoint
- diagnostics endpoint for machine-level DLP status
- masked evidence storage by default
- compatibility with existing `/api/dlp/events` and `/api/dlp/stats`

Current rollout model:
- active enforcement plus detection
- policy actions are computed, stored, and enforced natively on the endpoint
- unsupported endpoint enforcement degrades visibly instead of pretending to block

Key backend endpoints:
- `GET /api/dlp/policy/effective`
- `GET /api/dlp/policies`
- `POST /api/dlp/policies`
- `PUT /api/dlp/policies/{id}`
- `POST /api/dlp/policies/{id}/publish`
- `POST /api/dlp/policies/simulate`
- `GET /api/dlp/classifiers`
- `POST /api/dlp/classifiers`
- `GET /api/dlp/exceptions`
- `POST /api/dlp/exceptions`
- `PUT /api/dlp/exceptions/{id}`
- `GET /api/dlp/incidents`
- `GET /api/dlp/incidents/{id}`
- `PUT /api/dlp/incidents/{id}`
- `GET /api/dlp/diagnostics/machines/{machine_id}`
- `GET /api/platform/dlp/baseline`

## Phishing Protection Status

The codebase now includes a phishing-protection foundation alongside DLP.

Implemented:
- tenant-scoped phishing policy resolution
- platform phishing baseline
- phishing event ingestion and grouped incidents
- warn-only endpoint popup flow for risky browser visits
- phishing analyst queue in customer portal
- phishing diagnostics endpoint for machine-level status

Current rollout model:
- detection plus user warning
- browser-driven coverage first
- unsupported channels degrade visibly instead of silently pretending coverage

Guide:
- [Phishing and DLP testing guide](C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/phishing-dlp-testing-guide.md)
- [Tenant safety smoke runbook](C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/tenant-safety-smoke-runbook.md)

Key backend endpoints:
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

## Architecture

```text
Edge Gateway (Nginx)
        |
Platform Portal (React/Vite) + Customer Portal (React/Vite)
        |
FastAPI API + WebSocket Hub
        |
PostgreSQL + Redis + Event Bus/Object Storage Foundations
        |
Endpoint Agent (C# Native AOT)
```

Core layers:
- `frontend/` contains both customer and platform UIs
- `backend/` contains FastAPI routers, services, repos, DB mixins, tests, and monitoring
- `agent/` contains the net8.0 C# Native AOT Windows endpoint agent (`agent/native/`)

## Tech Stack

### Frontend
- React 18
- Vite 5
- React Router
- Recharts
- Sentry browser SDK

### Backend
- FastAPI
- Uvicorn
- psycopg2
- PyJWT
- bcrypt
- slowapi
- sentry-sdk
- ReportLab
- aiokafka (optional next-gen event bus backend)
- boto3 (optional S3/MinIO object-storage backend)
- built-in ClickHouse HTTP analytics pipeline support for activity offload
- built-in Prometheus-style metrics and JSON-capable structured logging
- extracted runtime entrypoints for `agent-control`, `monitoring`, and `realtime`

### Agent
- C# (.NET 8.0 net8.0-windows Native AOT)
- SIPSorcery (Real-time WebRTC media)
- Microsoft.Data.Sqlite (Encrypted offline queueing)
- System.Drawing.Common (Multi-monitor GDI+ virtual screen capture)
- Native Win32 / SCM / impersonation P/Invokes

## Quick Start

### 1. Configure environment

Copy the example file and set required values:

```powershell
Copy-Item .env.example .env
```

Minimum values to review:
- `SECRET_KEY`
- `DATABASE_URL`
- `POSTGRES_PASSWORD` if using Docker
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `AGENT_API_KEY`
- `CORS_ORIGINS`

### 2. Start PostgreSQL

Docker option:

```powershell
docker compose up -d db
```

### 3. Start backend

```powershell
Set-Location backend
py -m pip install -r requirements.txt
py main.py
```

Backend runs on `http://localhost:8000`.

### 4. Start frontend

```powershell
Set-Location frontend
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`.

### 5. Compile and run the native agent in development

```powershell
# Publish the native worker and supervisor service watchdogs
cd installer
powershell -ExecutionPolicy Bypass -File .\build-native-aot.ps1
```

The native agent expects server configuration through `config.env` or generated appsettings.json. In tenant-aware installs it must use the correct enrollment token.

## Common Commands

### Frontend

```powershell
npm --prefix frontend run dev
npm --prefix frontend run build
npm --prefix frontend run check:ws-order
npm --prefix frontend run check:ui-ux-guards
```

### Backend

```powershell
py -m py_compile backend/main.py
pytest backend
py tools/tenant_safety_smoke.py --database-url "postgresql://postgres:YOUR_PASSWORD@localhost:5432/cropsentinel"
```

### Agent (Native)

```powershell
# Compile C# worker project directly
dotnet build agent/native/CropSentinel.AgentNative/CropSentinel.AgentNative.csproj
```

## Project Structure

```text
CropSentinel/
â”œâ”€ agent/
â”‚  â””â”€ native/
â”œâ”€ backend/
â”‚  â”œâ”€ app/
â”‚  â”‚  â”œâ”€ db/
â”‚  â”‚  â”œâ”€ repos/
â”‚  â”‚  â”œâ”€ routers/
â”‚  â”‚  â””â”€ services/
â”‚  â”œâ”€ tests/
â”‚  â”œâ”€ database.py
â”‚  â”œâ”€ main.py
â”‚  â””â”€ models.py
â”œâ”€ docs/
â”œâ”€ frontend/
â”‚  â”œâ”€ scripts/
â”‚  â””â”€ src/
â””â”€ README.md
```

Important backend areas:
- [backend/app/routers](/C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/routers) for HTTP and WebSocket endpoints
- [backend/app/services](/C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/services) for orchestration logic
- [backend/app/db](/C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/app/db) for schema and database methods

Important frontend areas:
- [frontend/src/pages](/C:/Users/husai/OneDrive/Desktop/CropSentinel/frontend/src/pages) for customer and platform pages
- [frontend/src/hooks](/C:/Users/husai/OneDrive/Desktop/CropSentinel/frontend/src/hooks) for auth, websocket, notification, and page context state

## Security and Multi-Tenancy

### Tenant isolation
- tenant-scoped tables and request context
- tenant checks on machine registration and ingestion
- WebSocket broadcast filtering by tenant
- per-tenant settings, alerts, activity, DLP events, policies, incidents, and exceptions

### Auth and RBAC
- JWT auth
- platform and customer sessions are separate
- role-based permissions in backend and frontend

### Monitoring and privacy
- Sentry support for backend and frontend
- DLP masked evidence by default
- input tracking stores hashed patterns instead of raw keystrokes

## Testing and Monitoring

Current repo support includes:
- backend pytest suite in [backend/tests](/C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/tests)
- GitHub Actions workflow under [.github](/C:/Users/husai/OneDrive/Desktop/CropSentinel/.github)
- Sentry integration in backend and frontend
- UI guard scripts for websocket handler ordering and UI state checks
- internal ops endpoints:
  - `GET /_internal/health/live`
  - `GET /_internal/health/ready`
  - `GET /_internal/ops/status`
  - `GET /_internal/metrics`
- backup and restore scripts in [ops/backup](/C:/Users/husai/OneDrive/Desktop/CropSentinel/ops/backup)

Useful docs:
- [backend/tests/README.md](/C:/Users/husai/OneDrive/Desktop/CropSentinel/backend/tests/README.md)
- [docs/github-repo-guide.md](/C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/github-repo-guide.md)
- [docs/monitoring.md](/C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/monitoring.md)
- [docs/live-remote-troubleshooting.md](/C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/live-remote-troubleshooting.md)
- [docs/release-checklist.md](/C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/release-checklist.md)
- [docs/kali-server-deployment-guide.md](/C:/Users/husai/OneDrive/Desktop/CropSentinel/docs/kali-server-deployment-guide.md)
- [ops/disaster-recovery-runbook.md](/C:/Users/husai/OneDrive/Desktop/CropSentinel/ops/disaster-recovery-runbook.md)

## Notes

- Default credentials should never be shown in the UI. Seed values belong in environment configuration only.
- The backend can generate a random JWT secret if `SECRET_KEY` is unset, but that is development-only because tokens will not survive restart.
- Enterprise DLP enforcement actions are modeled and fully enforced natively by the user-mode active blocking system inside the C# Native agent.

<p align="center">
  <strong>CropSentinel</strong><br />
  <sub>Monitor. Detect. Protect.</sub>
</p>
