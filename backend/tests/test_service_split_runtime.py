from __future__ import annotations

import pytest

from agent_control_main import app as agent_control_app
from monitoring_main import app as monitoring_app
from realtime_main import app as realtime_app

def _paths(app) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


def test_agent_control_service_routes_are_scoped():
    paths = _paths(agent_control_app)
    assert "/api/machines/register" in paths
    assert "/api/activity/heartbeat" in paths
    assert "/api/auth/login" not in paths
    assert "/api/analytics/overview" not in paths
    assert "/ws/admin" not in paths


def test_monitoring_service_routes_are_scoped():
    paths = _paths(monitoring_app)
    assert "/api/activity/browser" in paths
    assert "/api/activity/file" in paths
    assert "/api/activity/network" in paths
    assert "/api/auth/login" not in paths
    assert "/ws/admin" not in paths


def test_realtime_service_routes_are_scoped():
    paths = _paths(realtime_app)
    assert "/api/sessions/machines/{machine_id}/capabilities" in paths
    assert "/api/sessions/machines/{machine_id}/start" in paths
    assert "/ws/admin" in paths
    assert "/ws/agent/{machine_id}" in paths
    assert "/api/auth/login" not in paths
