#!/usr/bin/env python3
"""
CropSentinel — Vendor keypair generator
===================================

RUN THIS ONCE. Creates the Ed25519 keypair that we (HAAK IT Solutions)
use to sign every CropSentinel license file forever.

Outputs:
  - secrets/croppro_license_private.pem    (KEEP OFFLINE, NEVER commit to git)
  - backend/licensing/public_key.pem        (committed, ships with CropSentinel)

If a private_key already exists at the target path, this script REFUSES
to overwrite — re-generating would invalidate every license we've ever
issued. Delete the old file manually if you truly mean to start over.

USAGE
-----
    python tools/generate_keypair.py

After running, immediately:
  1. Back up the private key file somewhere safe and OFFLINE
     (USB drive in a drawer, password manager, hardware token).
  2. Add `secrets/` to .gitignore (already done, but double-check).
  3. Commit backend/licensing/public_key.pem to git — this is public.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make backend importable when running from the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from licensing.keys import (
    generate_keypair,
    save_private_key,
    save_public_key,
)


def main() -> int:
    private_path = PROJECT_ROOT / "secrets" / "croppro_license_private.pem"
    public_path  = PROJECT_ROOT / "backend" / "licensing" / "public_key.pem"

    if private_path.exists():
        print(f"REFUSING TO OVERWRITE: {private_path} already exists.")
        print(
            "If you regenerate the keypair, every existing CropSentinel "
            "license becomes INVALID. Delete the old file manually if "
            "you are absolutely sure."
        )
        return 1

    print("Generating Ed25519 keypair...")
    private_key, public_key = generate_keypair()

    print(f"Writing private key -> {private_path}")
    save_private_key(private_key, private_path)

    print(f"Writing public key  -> {public_path}")
    save_public_key(public_key, public_path)

    print()
    print("Done.")
    print()
    print("NEXT STEPS:")
    print(f"  1. BACK UP the private key somewhere offline:")
    print(f"     {private_path}")
    print(f"  2. Verify 'secrets/' is in .gitignore.")
    print(f"  3. Commit the public key to git:")
    print(f"     git add backend/licensing/public_key.pem")
    print(f"  4. You can now issue licenses using:")
    print(f"     python tools/issue_license.py --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
