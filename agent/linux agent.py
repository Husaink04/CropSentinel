"""Linux-only CropSentinel agent launcher.

This keeps the shared monitoring implementation in agent.py, while giving the
Linux installer a stable, OS-specific entrypoint to invoke from systemd.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


def main() -> int:
    if platform.system() != "Linux":
        sys.stderr.write("linux agent.py can only run on Linux.\n")
        return 1

    script_dir = Path(__file__).resolve().parent
    os.chdir(script_dir)
    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    from agent import main as shared_main

    shared_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
