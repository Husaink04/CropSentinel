#!/usr/bin/env python
"""Seed and verify a tenant-isolation smoke run for DLP and phishing."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, parse, request

import psycopg2
from psycopg2.extras import RealDictCursor

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from passwords import hash_password  # noqa: E402


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_local_env() -> None:
    _load_env_file(REPO_ROOT / ".env")
    _load_env_file(REPO_ROOT / "backend" / ".env")


def parse_args() -> argparse.Namespace:
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", ""), help="Postgres database URL")
    parser.add_argument("--backend-url", default=os.environ.get("CROPPRO_SERVER", "http://localhost:8000"), help="Backend base URL")
    parser.add_argument("--agent-api-key", default=os.environ.get("AGENT_API_KEY", ""), help="Optional agent API key")
    parser.add_argument("--tenant-a-slug", default="default", help="Tenant A slug")
    parser.add_argument("--tenant-b-slug", default="", help="Tenant B slug. Defaults to first non-A tenant.")
    parser.add_argument("--machine-id", default="", help="Optional machine id to use for tenant A")
    parser.add_argument("--tenant-a-username", default="smoke-admin-a", help="Tenant A smoke admin username")
    parser.add_argument("--tenant-b-username", default="smoke-admin-b", help="Tenant B smoke admin username")
    parser.add_argument("--smoke-password", default="SmokePass!123", help="Password set on both smoke admins")
    return parser.parse_args()


def require(value: str, message: str) -> str:
    if not value:
        raise SystemExit(message)
    return value


def json_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    form: dict[str, str] | None = None,
) -> dict[str, Any]:
    req_headers = dict(headers or {})
    data: bytes | None = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"
    elif form is not None:
        data = parse.urlencode(form).encode("utf-8")
        req_headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = request.Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=20) as res:
            body = res.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def contains_marker(value: Any, marker: str) -> bool:
    marker = marker.lower()
    if isinstance(value, dict):
        return any(contains_marker(v, marker) for v in value.values())
    if isinstance(value, list):
        return any(contains_marker(v, marker) for v in value)
    return marker in str(value).lower()


def login(backend_url: str, path: str, username: str, password: str) -> str:
    payload = json_request(
        "POST",
        f"{backend_url}{path}",
        form={"username": username, "password": password},
    )
    token = payload.get("access_token", "")
    if not token:
        raise RuntimeError(f"Login did not return access_token for {username} via {path}")
    return token


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_or_update_smoke_user(conn, tenant_id: int, username: str, display_name: str, password: str) -> int:
    password_hash = hash_password(password)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        if row:
            cur.execute(
                """
                UPDATE users
                SET tenant_id = %s,
                    password_hash = %s,
                    display_name = %s,
                    role = 'admin',
                    assigned_machines = '[]',
                    active = TRUE,
                    updated_at = NOW(),
                    created_by = 'tenant_safety_smoke'
                WHERE username = %s
                RETURNING id
                """,
                (tenant_id, password_hash, display_name, username),
            )
            return int(cur.fetchone()["id"])
        cur.execute(
            """
            INSERT INTO users (
                tenant_id, username, password_hash, display_name,
                role, assigned_machines, active, created_by
            )
            VALUES (%s, %s, %s, %s, 'admin', '[]', TRUE, 'tenant_safety_smoke')
            RETURNING id
            """,
            (tenant_id, username, password_hash, display_name),
        )
        return int(cur.fetchone()["id"])


def fetch_one(cur, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


def choose_tenants_and_machine(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    with psycopg2.connect(args.database_url, cursor_factory=RealDictCursor) as conn:
        with conn.cursor() as cur:
            tenant_a = fetch_one(cur, "SELECT id, name, slug FROM tenants WHERE slug = %s", (args.tenant_a_slug,))
            if not tenant_a:
                raise SystemExit(f"Tenant A slug not found: {args.tenant_a_slug}")
            if args.tenant_b_slug:
                tenant_b = fetch_one(cur, "SELECT id, name, slug FROM tenants WHERE slug = %s", (args.tenant_b_slug,))
            else:
                cur.execute(
                    "SELECT id, name, slug FROM tenants WHERE id <> %s ORDER BY id LIMIT 1",
                    (tenant_a["id"],),
                )
                tenant_b = cur.fetchone()
            if not tenant_b:
                raise SystemExit("A second tenant is required for the smoke run. Create tenant B first.")
            tenant_b = dict(tenant_b)

            if args.machine_id:
                machine = fetch_one(
                    cur,
                    "SELECT machine_id, hostname, tenant_id FROM machines WHERE machine_id = %s",
                    (args.machine_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT machine_id, hostname, tenant_id
                    FROM machines
                    WHERE tenant_id = %s
                    ORDER BY last_seen DESC NULLS LAST, first_seen DESC NULLS LAST, machine_id ASC
                    LIMIT 1
                    """,
                    (tenant_a["id"],),
                )
                machine = cur.fetchone()
            if not machine:
                raise SystemExit(
                    f"No machine found for tenant A ({tenant_a['slug']}). Register one machine first or pass --machine-id."
                )
            machine = dict(machine)
            if int(machine["tenant_id"]) != int(tenant_a["id"]):
                raise SystemExit("Selected machine does not belong to tenant A.")

            create_or_update_smoke_user(conn, int(tenant_a["id"]), args.tenant_a_username, "Smoke Admin A", args.smoke_password)
            create_or_update_smoke_user(conn, int(tenant_b["id"]), args.tenant_b_username, "Smoke Admin B", args.smoke_password)
            conn.commit()
            return tenant_a, tenant_b, machine


def seed_events(args: argparse.Namespace, machine_id: str, tag: str) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    headers = {}
    if args.agent_api_key:
        headers["X-CropPro-Agent-Key"] = args.agent_api_key

    dlp_marker = f"tenant-smoke-{tag}.txt"
    phishing_domain = f"github-verify-login-{tag}.zip"
    timestamp = datetime.now(timezone.utc).isoformat()

    dlp_payload = {
        "machine_id": machine_id,
        "timestamp": timestamp,
        "file_path": f"C:/tenant-smoke/{dlp_marker}",
        "file_name": dlp_marker,
        "file_ext": ".txt",
        "file_size": 256,
        "risk": "high",
        "risk_level": "high",
        "risk_score": 92,
        "findings": [{"type": "api_key", "count": 1}],
        "event_type": "file_transfer",
        "channel": "file",
        "destination": "usb",
        "destination_type": "usb",
        "destination_label": f"tenant-smoke-usb-{tag}",
        "actor_username": args.tenant_a_username,
        "app_name": "smoke-seed",
        "classifier_hits": [{"name": "credentials_api_key", "count": 1}],
        "confidence": 0.98,
        "action_taken": "warn_user",
        "action_result": "observed",
        "masked_evidence": [{"type": "api_key", "preview": "sk-test-****"}],
        "content_fingerprint": f"tenant-smoke-{tag}",
    }
    phishing_payload = {
        "machine_id": machine_id,
        "timestamp": timestamp,
        "event_type": "browser_visit",
        "channel": "browser",
        "url": f"https://{phishing_domain}/signin",
        "domain": phishing_domain,
        "page_title": f"GitHub sign in verification smoke {tag}",
        "app_name": "chrome",
        "process_name": "chrome.exe",
        "destination_label": f"tenant-smoke-phishing-{tag}",
        "actor_username": args.tenant_a_username,
    }

    dlp_result = json_request("POST", f"{args.backend_url}/api/dlp/events", headers=headers, payload=dlp_payload)
    phishing_result = json_request("POST", f"{args.backend_url}/api/activity/phishing", headers=headers, payload=phishing_payload)
    return dlp_result, phishing_result, dlp_marker, phishing_domain


def verify_customer_scope(backend_url: str, token: str, dlp_marker: str, phishing_domain: str, expect_present: bool) -> dict[str, bool]:
    headers = auth_headers(token)
    dlp_events = json_request("GET", f"{backend_url}/api/dlp/events?limit=20", headers=headers)
    phishing_events = json_request("GET", f"{backend_url}/api/phishing/events?limit=20", headers=headers)
    phishing_incidents = json_request("GET", f"{backend_url}/api/phishing/incidents?limit=20", headers=headers)
    alerts = json_request("GET", f"{backend_url}/api/alerts/logs?limit=20", headers=headers)

    checks = {
        "dlp_marker": contains_marker(dlp_events, dlp_marker),
        "phishing_domain_events": contains_marker(phishing_events, phishing_domain),
        "phishing_domain_incidents": contains_marker(phishing_incidents, phishing_domain),
        "alerts_have_marker": contains_marker(alerts, dlp_marker) or contains_marker(alerts, phishing_domain),
    }
    if expect_present:
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            raise RuntimeError(f"Tenant A verification failed: missing expected markers in {', '.join(failed)}")
    else:
        failed = [name for name, passed in checks.items() if passed]
        if failed:
            raise RuntimeError(f"Tenant B isolation failed: leaked markers visible in {', '.join(failed)}")
    return checks


def verify_platform_scope(backend_url: str, token: str, dlp_marker: str, phishing_domain: str) -> dict[str, bool]:
    headers = auth_headers(token)
    dlp_baseline = json_request("GET", f"{backend_url}/api/platform/dlp/baseline", headers=headers)
    phishing_baseline = json_request("GET", f"{backend_url}/api/platform/phishing/baseline", headers=headers)
    checks = {
        "dlp_baseline_no_marker": not contains_marker(dlp_baseline, dlp_marker) and not contains_marker(dlp_baseline, phishing_domain),
        "phishing_baseline_no_marker": not contains_marker(phishing_baseline, dlp_marker) and not contains_marker(phishing_baseline, phishing_domain),
        "dlp_baseline_has_policies": bool(dlp_baseline.get("policies") or dlp_baseline.get("classifiers")),
        "phishing_baseline_has_policies": bool(phishing_baseline.get("policies")),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError(f"Platform baseline verification failed: {', '.join(failed)}")
    return checks


def main() -> int:
    args = parse_args()
    args.database_url = require(args.database_url, "DATABASE_URL is required. Pass --database-url or set DATABASE_URL.")
    args.backend_url = require(args.backend_url, "BACKEND_URL is required.")
    tag = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    tenant_a, tenant_b, machine = choose_tenants_and_machine(args)
    dlp_result, phishing_result, dlp_marker, phishing_domain = seed_events(args, machine["machine_id"], tag)

    tenant_a_token = login(args.backend_url, "/api/auth/login", args.tenant_a_username, args.smoke_password)
    tenant_b_token = login(args.backend_url, "/api/auth/login", args.tenant_b_username, args.smoke_password)
    platform_token = login(args.backend_url, "/api/platform/login", args.tenant_a_username, args.smoke_password)

    tenant_a_checks = verify_customer_scope(args.backend_url, tenant_a_token, dlp_marker, phishing_domain, expect_present=True)
    tenant_b_checks = verify_customer_scope(args.backend_url, tenant_b_token, dlp_marker, phishing_domain, expect_present=False)
    platform_checks = verify_platform_scope(args.backend_url, platform_token, dlp_marker, phishing_domain)

    result = {
        "status": "passed",
        "backend_url": args.backend_url,
        "tenant_a": {
            "id": tenant_a["id"],
            "slug": tenant_a["slug"],
            "username": args.tenant_a_username,
        },
        "tenant_b": {
            "id": tenant_b["id"],
            "slug": tenant_b["slug"],
            "username": args.tenant_b_username,
        },
        "machine": {
            "machine_id": machine["machine_id"],
            "hostname": machine.get("hostname", ""),
        },
        "markers": {
            "dlp_file_name": dlp_marker,
            "phishing_domain": phishing_domain,
        },
        "seed_results": {
            "dlp_event_id": dlp_result.get("id"),
            "dlp_incident_id": dlp_result.get("incident_id"),
            "phishing_event_id": phishing_result.get("event_id"),
            "phishing_incident_id": phishing_result.get("incident_id"),
        },
        "verification": {
            "tenant_a": tenant_a_checks,
            "tenant_b": tenant_b_checks,
            "platform": platform_checks,
        },
        "ui_follow_up": {
            "customer_urls": [
                "http://localhost:5173/dlp",
                "http://localhost:5173/phishing",
                "http://localhost:5173/alerts",
            ],
            "platform_urls": [
                "http://localhost:5173/platform/dlp",
                "http://localhost:5173/platform/phishing",
            ],
        },
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
