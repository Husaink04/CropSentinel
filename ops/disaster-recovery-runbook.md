# CropSentinel Disaster Recovery Runbook

## Scope

This runbook covers the Docker/VM-first Wave 6 stack:
- PostgreSQL operational database
- Redis presence/rate-limit state
- MinIO object storage
- ClickHouse analytics storage
- Backend API and gateway

## Targets

- RTO: under 30 minutes
- RPO: under 5 minutes

## Prerequisites

- Latest backup folder from `ops/backup/backup-stack.ps1`
- `.env` with the correct production secrets
- Access to the target Docker host
- DNS or public IP cutover plan for the gateway

## Recovery order

1. Restore `.env`, `docker-compose.yml`, and gateway config.
2. Start `db`, `redis`, `minio`, and `clickhouse`.
3. Restore PostgreSQL from `db/postgres.sql`.
4. Restore object storage payloads from `minio/data`.
5. Restore ClickHouse analytics payloads from `clickhouse/data` if needed.
6. Restore Redis state if preserving presence/rate-limit state matters.
7. Start `backend`, `gateway`, `frontend`, `prometheus`, `grafana`, `loki`, and `promtail`.
8. Validate:
   - `GET /_internal/health/live`
   - `GET /_internal/health/ready`
   - `GET /_internal/ops/status`
   - `GET /_internal/metrics`
   - admin login
   - agent heartbeat
   - one screenshot/report artifact download

## Validation checklist

- PostgreSQL tenant, machine, user, policy, and incident records are present.
- MinIO-backed artifacts download successfully.
- ClickHouse pipeline reports healthy status or is disabled cleanly.
- Redis reconnects and WebSocket broadcasts work across backend instances.
- Prometheus can scrape backend metrics.
- Grafana can read Prometheus and Loki datasources.

## Failure modes to watch

- `event_bus.failed_count` rising in internal metrics
- `analytics_pipeline.failed` or `queue_depth` growing continuously
- missing object storage credentials
- stale `backup-status.json`
- gateway healthy but backend internal readiness failing

## Notes

- Redis is not the durable event backbone. If Redis restore is skipped, live presence can self-heal after agents reconnect.
- ClickHouse can be restored after PostgreSQL if the priority is to recover control-plane operations first.
- Keep the backup status file under `backend/storage/ops/backup-status.json` so internal ops status reflects the last completed run.
