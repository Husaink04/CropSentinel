"""CropSentinel licensing package."""

from .verifier import (
    LicenseInfo,
    LicenseError,
    LicenseMissingError,
    LicenseInvalidError,
    LicenseExpiredError,
    load_and_verify_license,
)
from .enforcement import (
    SeatEnforcer,
    SeatDecision,
    has_feature,
    ACTIVE_WINDOW_MINUTES,
)

__all__ = [
    "LicenseInfo",
    "LicenseError",
    "LicenseMissingError",
    "LicenseInvalidError",
    "LicenseExpiredError",
    "load_and_verify_license",
    "SeatEnforcer",
    "SeatDecision",
    "has_feature",
    "ACTIVE_WINDOW_MINUTES",
]
