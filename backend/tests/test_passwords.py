import hashlib

from passwords import hash_password, verify_password, upgrade_hash_if_legacy, is_legacy_sha256_hex


def test_bcrypt_roundtrip():
    h = hash_password("secret-password")
    assert h.startswith("$2")
    assert verify_password("secret-password", h)
    assert not verify_password("wrong", h)


def test_legacy_sha256_verify():
    plain = "Admin@CropPro2024"
    legacy = hashlib.sha256(plain.encode()).hexdigest()
    assert is_legacy_sha256_hex(legacy)
    assert verify_password(plain, legacy)
    assert not verify_password("nope", legacy)


def test_upgrade_legacy_to_bcrypt():
    plain = "StopAgent@CropPro"
    legacy = hashlib.sha256(plain.encode()).hexdigest()
    new_hash = upgrade_hash_if_legacy(plain, legacy)
    assert new_hash is not None
    assert new_hash.startswith("$2")
    assert verify_password(plain, new_hash)
    assert upgrade_hash_if_legacy(plain, new_hash) is None
