"""
CropSentinel — Database Reset
========================

DANGEROUS. Drops every CropSentinel table and recreates them from scratch.

USAGE:
    python tools/reset_database.py            # interactive (asks to confirm)
    python tools/reset_database.py --yes      # non-interactive

This is the canonical path for upgrading a pre-v5 (single-tenant) database
to v5 (multi-tenant). All existing CropSentinel data will be deleted.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `backend` importable when running from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Wipe and recreate the CropSentinel database.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the interactive confirmation prompt.")
    args = parser.parse_args()

    print("=" * 60)
    print("CropSentinel Database Reset")
    print("=" * 60)
    print()
    print("This will DROP and RECREATE every CropSentinel table:")
    print("  tenants, machines, users, browser_activity, app_activity,")
    print("  screenshots, alert_rules, alert_logs, input_activity,")
    print("  audit_logs, file_activity, deleted_file_backups,")
    print("  network_activity, dlp_events, settings")
    print()
    print("ALL EXISTING DATA WILL BE PERMANENTLY DELETED.")
    print()

    if not args.yes:
        try:
            answer = input("Type 'WIPE' to confirm: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return 1
        if answer != "WIPE":
            print("Aborted — confirmation not given.")
            return 1

    # Force the database layer into reset mode and re-init.
    os.environ["CROPPRO_RESET_DB"] = "1"

    from backend import database  # noqa: E402  (deferred import on purpose)

    db = database.Database()
    db.init_db()

    print()
    print("Database reset complete. Default tenant (id=1) seeded.")
    print("You can now start the backend normally:")
    print("    python backend/main.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
