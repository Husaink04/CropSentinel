from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


EXPECTED_ROUTES = {
    "/api/machines/register": "cropsentinel_agent_control",
    "/api/activity/heartbeat": "cropsentinel_agent_control",
    "/api/activity/browser": "cropsentinel_monitoring",
    "/api/activity/application": "cropsentinel_monitoring",
    "/api/activity/screenshot": "cropsentinel_monitoring",
    "/api/activity/input": "cropsentinel_monitoring",
    "/api/activity/phishing": "cropsentinel_monitoring",
    "/api/activity/batch": "cropsentinel_monitoring",
    "/api/sessions/": "cropsentinel_realtime",
    "/api/": "cropsentinel_backend",
    "/ws/": "cropsentinel_realtime",
    "/_internal/": "cropsentinel_backend",
    "/": "cropsentinel_frontend",
}


def _load_text(path: str | None) -> str:
    if path:
        return Path(path).read_text(encoding="utf-8")
    return sys.stdin.read()


def _parse_locations(config_text: str) -> dict[str, str]:
    locations: dict[str, str] = {}
    current_location: str | None = None
    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        match = re.match(r"location\s+(=)?\s*([^\s{]+)\s*\{", line)
        if match:
            current_location = match.group(2)
            continue
        if current_location and line.startswith("proxy_pass"):
            upstream = line.split("http://", 1)[-1].rstrip(";")
            locations[current_location] = upstream
        if line == "}":
            current_location = None
    return locations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the effective Nginx route map for the split CropSentinel stack. "
                    "Use with `docker compose exec gateway nginx -T | python ops/verify_gateway_routes.py`."
    )
    parser.add_argument("--file", help="Read nginx -T output from a file instead of stdin.")
    args = parser.parse_args()

    locations = _parse_locations(_load_text(args.file))
    failures: list[str] = []
    for path, expected_upstream in EXPECTED_ROUTES.items():
        actual_upstream = locations.get(path)
        if actual_upstream != expected_upstream:
            failures.append(f"{path}: expected {expected_upstream}, found {actual_upstream or 'missing'}")

    if failures:
        print("Gateway route verification failed:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("Gateway route verification passed.")
    for path, upstream in EXPECTED_ROUTES.items():
        print(f"{path} -> {upstream}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
