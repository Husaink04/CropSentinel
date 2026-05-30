"""
CropSentinel Licensing — Seat Enforcement
=====================================

Counts currently-active machines against the licensed `max_seats` and
decides whether a new machine registration should be allowed.

DESIGN
------
A naive implementation would `COUNT(*)` on the machines table on every
agent heartbeat. At 500 agents that's hundreds of extra DB queries per
minute for a value that barely changes. Instead we keep a cached count
and refresh it on a short interval.

Seat definition: a "seat" is a machine whose `last_seen` is within
ACTIVE_WINDOW_MINUTES of now. Dormant machines do not count.

ENFORCEMENT POLICY
------------------
- **Known machines** (machine_id already in the DB) are always allowed
  to re-register. Otherwise a reboot would lock people out.
- **New machines** are blocked with HTTP 402 when at or above `max_seats`.
- **Unlicensed dev mode** (app.state.license is None) bypasses all checks
  but logs a warning.
- **Grace period** licenses still enforce — grace is about expiry dates,
  not seat counts.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("croppro.licensing")


# ── Config ──────────────────────────────────────────────────────────────────

ACTIVE_WINDOW_MINUTES = 15     # how recently a machine must have heartbeat'd
CACHE_TTL_SECONDS     = 30     # how long the cached count is considered fresh


# ── Result type ─────────────────────────────────────────────────────────────

@dataclass
class SeatDecision:
    """Result returned to the caller (the /register endpoint)."""
    allowed:       bool
    reason:        str             # human-readable reason
    active_seats:  int
    max_seats:     int
    is_new_machine: bool

    def to_dict(self) -> dict:
        return {
            "allowed":        self.allowed,
            "reason":         self.reason,
            "active_seats":   self.active_seats,
            "max_seats":      self.max_seats,
            "is_new_machine": self.is_new_machine,
        }


# ── Enforcer ────────────────────────────────────────────────────────────────

class SeatEnforcer:
    """
    Thread-safe cached seat counter + registration gate.

    One instance is created at startup and lives on app.state.seat_enforcer.
    """

    def __init__(self, db, license_info_provider, bootstrap_mode_provider=None):
        """
        Args:
            db:                   the database module (backend.database.db)
            license_info_provider: callable returning the current LicenseInfo,
                                   or None if unlicensed. We accept a callable
                                   instead of a direct reference so hot-reloaded
                                   licenses (future) work transparently.
        """
        self._db = db
        self._get_license = license_info_provider
        self._is_bootstrap = bootstrap_mode_provider or (lambda: False)
        self._lock = threading.Lock()
        self._cached_count: int = 0
        self._cached_at: float = 0.0

    # ── Count access ─────────────────────────────────────────────────────

    def active_count(self, force_refresh: bool = False) -> int:
        """
        Return the cached active-seat count, refreshing if stale.
        Thread-safe.
        """
        now = time.monotonic()
        with self._lock:
            if force_refresh or (now - self._cached_at) > CACHE_TTL_SECONDS:
                try:
                    self._cached_count = self._db.count_active_machines(
                        window_minutes=ACTIVE_WINDOW_MINUTES,
                    )
                    self._cached_at = now
                except Exception as e:
                    logger.warning(
                        "SeatEnforcer: failed to refresh active count: %s", e
                    )
                    # Keep the old value rather than failing the request
            return self._cached_count

    def invalidate(self):
        """Force the next active_count() call to hit the DB."""
        with self._lock:
            self._cached_at = 0.0

    # ── Registration gate ────────────────────────────────────────────────

    def check_registration(self, machine_id: str) -> SeatDecision:
        """
        Decide whether a given machine is allowed to register.

        Returns a SeatDecision. The caller is responsible for enforcing the
        decision (raising HTTPException, writing audit_log, etc).
        """
        license_info = self._get_license()

        # ── Unlicensed dev mode: allow everything, but log ──────────────
        if license_info is None:
            if self._is_bootstrap():
                return SeatDecision(
                    allowed=False,
                    reason=(
                        "A valid platform license is required before agent enrollment "
                        "can begin. Sign in to platform administration and upload the "
                        "customer license.key file."
                    ),
                    active_seats=0,
                    max_seats=0,
                    is_new_machine=True,
                )
            logger.warning(
                "SeatEnforcer: allowing registration in UNLICENSED dev mode (machine_id=%s)",
                machine_id,
            )
            return SeatDecision(
                allowed=True,
                reason="Unlicensed dev mode — no enforcement",
                active_seats=0,
                max_seats=0,
                is_new_machine=True,
            )

        max_seats = license_info.max_seats

        # ── Known machine: always allow re-registration ─────────────────
        try:
            is_known = self._db.machine_exists(machine_id)
        except Exception as e:
            logger.warning("SeatEnforcer: machine_exists check failed: %s", e)
            is_known = False

        active = self.active_count()

        if is_known:
            return SeatDecision(
                allowed=True,
                reason="Known machine — re-registration allowed",
                active_seats=active,
                max_seats=max_seats,
                is_new_machine=False,
            )

        # ── New machine: check against seat cap ─────────────────────────
        if active >= max_seats:
            # Double-check with a fresh read before rejecting, to avoid a
            # 30-second stale cache causing a spurious denial at the boundary.
            active = self.active_count(force_refresh=True)
            if active >= max_seats:
                return SeatDecision(
                    allowed=False,
                    reason=(
                        f"License seat limit reached: {active}/{max_seats} "
                        f"active machines. Contact HAAK IT Solutions to upgrade."
                    ),
                    active_seats=active,
                    max_seats=max_seats,
                    is_new_machine=True,
                )

        return SeatDecision(
            allowed=True,
            reason="Within seat limit",
            active_seats=active + 1,  # optimistic post-registration count
            max_seats=max_seats,
            is_new_machine=True,
        )


# ── Convenience: feature flag check ─────────────────────────────────────────

def has_feature(license_info, feature_name: str) -> bool:
    """
    Shortcut for 'is this feature available under the current license?'
    Returns True in unlicensed dev mode (everything unlocked for development).
    """
    if license_info is None:
        return True
    return license_info.has_feature(feature_name)
