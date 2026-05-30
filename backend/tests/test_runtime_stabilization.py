from __future__ import annotations

import importlib.util
import os

from app.service_roles import (
    AGENT_CONTROL_ROLE,
    FULL_BACKEND_ROLE,
    REALTIME_ROLE,
    owns_schema_management,
    runs_startup_backfill,
    runs_startup_seeding,
)


def test_schema_management_is_backend_only():
    assert owns_schema_management(FULL_BACKEND_ROLE) is True
    assert runs_startup_seeding(FULL_BACKEND_ROLE) is True
    assert runs_startup_backfill(FULL_BACKEND_ROLE) is True

    assert owns_schema_management(AGENT_CONTROL_ROLE) is False
    assert runs_startup_seeding(AGENT_CONTROL_ROLE) is False
    assert runs_startup_backfill(AGENT_CONTROL_ROLE) is False

    assert owns_schema_management(REALTIME_ROLE) is False
    assert runs_startup_seeding(REALTIME_ROLE) is False
    assert runs_startup_backfill(REALTIME_ROLE) is False


def test_gateway_route_verifier_matches_repo_gateway_config():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    verifier_path = os.path.join(repo_root, "ops", "verify_gateway_routes.py")
    spec = importlib.util.spec_from_file_location("verify_gateway_routes", verifier_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    gateway_path = os.path.join(repo_root, "gateway", "nginx.conf")
    with open(gateway_path, "r", encoding="utf-8") as handle:
        locations = module._parse_locations(handle.read())

    for path, expected_upstream in module.EXPECTED_ROUTES.items():
        assert locations.get(path) == expected_upstream, f"{path} should map to {expected_upstream}"
