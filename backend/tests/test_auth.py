"""Day-2 authentication tests.

Covers the ``/api/auth/login`` happy + failure paths, JWT validation on
protected routes, password storage, and the in-process lockout throttle.

The rate-limit decorator on ``/api/auth/login`` is ``10/15minute`` (slowapi).
The *account lockout* is a separate, stricter gate: 8 failures for the same
username within 15 min → 429 on the 9th attempt. The tests below exercise the
lockout path because it kicks in first and is deterministic — slowapi's
leaky-bucket timing is flakier to assert on.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
async def test_login_with_correct_password_returns_bearer_token(api, make_user):
    user = make_user(username="alice", password="CorrectHorse1!", role="admin")

    resp = await api.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == "alice"
    assert body["role"] == "admin"
    assert body["tenant_id"] == 1
    # Token must be a structurally valid JWT (3 dot-separated segments).
    assert body["access_token"].count(".") == 2


# ---------------------------------------------------------------------------
# Failure paths — all must return 401 with a generic "Invalid credentials"
# message so we don't leak whether the username exists.
# ---------------------------------------------------------------------------
async def test_login_with_wrong_password_returns_401(api, make_user):
    user = make_user(username="bob", password="RealPass!9")

    resp = await api.post(
        "/api/auth/login",
        data={"username": user["username"], "password": "WrongPass!9"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


async def test_login_with_unknown_user_returns_401_not_404(api):
    """Must not leak account existence via status code."""
    resp = await api.post(
        "/api/auth/login",
        data={"username": "nobody-here", "password": "anything"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


async def test_login_for_inactive_user_returns_401(api, make_user):
    user = make_user(username="ghost", password="Passw0rd!Test", active=False)

    resp = await api.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


async def test_login_blocked_when_tenant_suspended(api, make_tenant, make_user, db):
    tenant = make_tenant(slug="suspended-co")
    db.update_tenant(tenant["id"], status="suspended")
    user = make_user(tenant_id=tenant["id"], username="sam", password="Passw0rd!Test")

    resp = await api.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert resp.status_code == 403
    assert "suspended" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# JWT validation on protected routes
# ---------------------------------------------------------------------------
async def test_protected_route_without_auth_header_returns_401(api):
    resp = await api.get("/api/auth/me")
    assert resp.status_code == 401


async def test_protected_route_with_malformed_token_returns_401(api):
    resp = await api.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer this-is-not-a-jwt"},
    )
    assert resp.status_code == 401


async def test_protected_route_with_wrong_signature_returns_401(api):
    """A JWT signed with an attacker's key must be rejected."""
    payload = {
        "sub": "alice",
        "role": "admin",
        "user_id": 1,
        "tenant_id": 1,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    forged = jwt.encode(payload, "attacker-secret-key", algorithm="HS256")

    resp = await api.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 401


async def test_protected_route_with_expired_token_returns_401(api):
    from app.core import ALGORITHM, SECRET_KEY

    payload = {
        "sub": "alice",
        "role": "admin",
        "user_id": 1,
        "tenant_id": 1,
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),  # already expired
    }
    expired = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    resp = await api.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401


async def test_protected_route_with_valid_token_returns_profile(api, auth_headers):
    headers = await auth_headers(role="manager")
    resp = await api.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["role"] == "manager"
    assert profile["tenant_id"] == 1


# ---------------------------------------------------------------------------
# Password storage
# ---------------------------------------------------------------------------
async def test_passwords_are_stored_as_bcrypt_not_plaintext(make_user, db):
    """Defense-in-depth: if the DB leaks, plaintext passwords must not."""
    plain = "VerySecret!Passphrase-2025"
    user = make_user(username="charlie", password=plain)

    stored = db.get_user_by_username(user["username"])
    assert stored is not None
    hash_value = stored["password_hash"]

    assert hash_value != plain, "password_hash column must not contain plaintext"
    assert hash_value.startswith("$2"), "expected bcrypt ($2a/$2b/$2y) prefix"
    assert len(hash_value) >= 60, "bcrypt hashes are 60+ chars"


# ---------------------------------------------------------------------------
# Account lockout after repeated failures
# ---------------------------------------------------------------------------
async def test_account_locks_after_threshold_failed_logins(api, make_user):
    """After LOGIN_FAIL_THRESHOLD (=8) bad attempts the next call returns 429.

    A *successful* login afterwards must be blocked too — the lockout is
    username-scoped and survives a correct password until the window clears.
    """
    from app.core import LOGIN_FAIL_THRESHOLD

    user = make_user(username="dora", password="TheRightOne!9")
    wrong = {"username": user["username"], "password": "wrong"}

    # Burn up to the threshold — each returns 401.
    for _ in range(LOGIN_FAIL_THRESHOLD):
        resp = await api.post("/api/auth/login", data=wrong)
        assert resp.status_code == 401

    # The next attempt — even with the CORRECT password — is locked out.
    resp = await api.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert resp.status_code == 429
    assert "locked" in resp.json()["detail"].lower()


async def test_successful_login_clears_prior_failures(api, make_user):
    """A single correct login should reset the failure counter so a few bad
    tries before it don't later combine with post-login typos to trigger lockout."""
    from app.core import LOGIN_FAIL_THRESHOLD

    user = make_user(username="erin", password="GoodPass!9")

    # 3 bad, 1 good, then 7 more bad — total is (THRESHOLD-1) bad but spread
    # across a success. Without clearing, 3 + 7 = 10 ≥ 8 → would lock out.
    for _ in range(3):
        await api.post("/api/auth/login", data={"username": user["username"], "password": "wrong"})

    ok = await api.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert ok.status_code == 200

    for _ in range(LOGIN_FAIL_THRESHOLD - 1):
        resp = await api.post(
            "/api/auth/login",
            data={"username": user["username"], "password": "wrong"},
        )
        assert resp.status_code == 401  # still 401, not 429 — counter was reset
