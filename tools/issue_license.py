#!/usr/bin/env python3
"""
CropSentinel — License issuer
=========================

Generates a signed license.key file for a customer.

USAGE
-----
Simple form (prompts for fields):
    python tools/issue_license.py

Scripted form:
    python tools/issue_license.py \
        --id CP-2026-0001 \
        --customer "Acme Corp LLC" \
        --tier professional \
        --seats 100 \
        --valid-days 365 \
        --features dlp_v2,live_view,remote_access,sso_saml \
        --out licenses/acme.key

TIERS (preset feature bundles — override with --features if needed)
----------------------------------------------------------------------
  starter       : monitoring, basic_dlp, reports
  professional  : + dlp_v2, live_view, alerts, sso_basic
  enterprise    : + remote_access, sso_saml, audit_export, compliance_reports
  msp           : all of the above + white_label + multi_tenant
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Make backend importable when running from the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from licensing.keys import load_private_key
from licensing.signer import build_payload, sign_license, write_license_file


# ── Tier -> feature bundles ──────────────────────────────────────────────────

TIER_FEATURES = {
    "starter": [
        "monitoring", "basic_dlp", "reports",
    ],
    "professional": [
        "monitoring", "basic_dlp", "reports",
        "dlp_v2", "live_view", "alerts", "sso_basic",
    ],
    "enterprise": [
        "monitoring", "basic_dlp", "reports",
        "dlp_v2", "live_view", "alerts", "sso_basic",
        "remote_access", "sso_saml", "audit_export", "compliance_reports",
    ],
    "msp": [
        "monitoring", "basic_dlp", "reports",
        "dlp_v2", "live_view", "alerts", "sso_basic",
        "remote_access", "sso_saml", "audit_export", "compliance_reports",
        "white_label", "multi_tenant",
    ],
}


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Issue a signed CropSentinel license file.",
    )
    p.add_argument("--id",
                   help="License ID (e.g. CP-2026-0001). Auto-generated if omitted.")
    p.add_argument("--customer", required=True,
                   help="Customer display name, e.g. 'Acme Corp LLC'")
    p.add_argument("--tier",
                   choices=list(TIER_FEATURES.keys()),
                   default="professional",
                   help="Tier preset (default: professional)")
    p.add_argument("--seats", type=int, required=True,
                   help="Maximum concurrent active agents")
    p.add_argument("--valid-days", type=int, default=365,
                   help="License validity in days (default: 365)")
    p.add_argument("--grace-days", type=int, default=14,
                   help="Grace period after expiry (default: 14)")
    p.add_argument("--max-tenants", type=int, default=None,
                   help="Maximum tenants this install may host. "
                        "Defaults: msp=10, all other tiers=1.")
    p.add_argument("--features",
                   help="Comma-separated feature list (overrides tier preset)")
    p.add_argument("--notes", default="",
                   help="Free-form notes shown in admin UI")
    p.add_argument("--hardware-binding", default="",
                   help="Optional machine fingerprint hash to bind the license")
    p.add_argument("--private-key",
                   default=str(PROJECT_ROOT / "secrets" / "croppro_license_private.pem"),
                   help="Path to vendor private key PEM")
    p.add_argument("--out",
                   help="Output path (default: licenses/<customer_slug>.key)")
    return p.parse_args()


def slugify(s: str) -> str:
    out = []
    for ch in s.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_") or "customer"


def main() -> int:
    args = parse_args()

    # Resolve feature set
    if args.features:
        features = [f.strip() for f in args.features.split(",") if f.strip()]
    else:
        features = TIER_FEATURES[args.tier]

    # Resolve max_tenants — MSP defaults to 10, everyone else to 1
    if args.max_tenants is not None:
        max_tenants = args.max_tenants
    else:
        max_tenants = 10 if args.tier == "msp" else 1

    # Resolve license id
    license_id = args.id or f"CP-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Resolve output path
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = PROJECT_ROOT / "licenses" / f"{slugify(args.customer)}.key"

    # Load private key
    private_key_path = Path(args.private_key)
    if not private_key_path.exists():
        print(f"ERROR: private key not found at {private_key_path}")
        print("Run tools/generate_keypair.py first.")
        return 1

    print(f"Loading private key from {private_key_path}")
    private_key = load_private_key(private_key_path)

    # Build + sign
    payload = build_payload(
        license_id    = license_id,
        customer      = args.customer,
        tier          = args.tier,
        max_seats     = args.seats,
        features      = features,
        valid_days    = args.valid_days,
        grace_days    = args.grace_days,
        max_tenants   = max_tenants,
        hardware_binding = args.hardware_binding,
        notes         = args.notes,
    )
    signed = sign_license(payload, private_key)
    write_license_file(signed, out_path)

    print()
    print(f"License issued -> {out_path}")
    print(f"  ID:       {license_id}")
    print(f"  Customer: {args.customer}")
    print(f"  Tier:     {args.tier}")
    print(f"  Seats:    {args.seats}")
    print(f"  Tenants:  {max_tenants}")
    print(f"  Valid:    {args.valid_days} days (+ {args.grace_days} grace)")
    print(f"  Features: {', '.join(features)}")
    print()
    print("Deliver this file to the customer. They place it next to the backend")
    print("as 'license.key' (or set CROPPRO_LICENSE_PATH env var).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
