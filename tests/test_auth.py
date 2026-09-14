import time

import pytest

from gateway.auth import (
    InvalidTokenError,
    _decode_token,
    hash_passphrase,
    issue_token,
    verify_passphrase,
)


def test_passphrase_hash_round_trips_and_rejects_wrong_guess():
    stored = hash_passphrase("correct horse battery staple")
    assert verify_passphrase("correct horse battery staple", stored) is True
    assert verify_passphrase("wrong guess", stored) is False


def test_passphrase_hash_is_salted_differently_each_time():
    a = hash_passphrase("same passphrase")
    b = hash_passphrase("same passphrase")
    assert a != b  # different random salts
    assert verify_passphrase("same passphrase", a) is True
    assert verify_passphrase("same passphrase", b) is True


def test_token_issues_and_decodes_expected_claims():
    token = issue_token("owner", "owner")
    payload = _decode_token(token)
    assert payload["sub"] == "owner"
    assert payload["role"] == "owner"
    assert payload["exp"] > time.time()


def test_token_rejects_tampering():
    token = issue_token("owner", "owner")
    with pytest.raises(InvalidTokenError):
        _decode_token(token + "x")


def test_token_rejects_wrong_signing_key(monkeypatch):
    import gateway.auth as auth_mod

    monkeypatch.setattr(auth_mod.settings, "SECRET_KEY", "a-different-secret")
    forged = issue_token("owner", "owner")
    monkeypatch.undo()

    with pytest.raises(InvalidTokenError):
        _decode_token(forged)


def test_token_rejects_expired(monkeypatch):
    import gateway.auth as auth_mod

    monkeypatch.setattr(auth_mod, "TOKEN_TTL_SECONDS", -1)
    expired = issue_token("owner", "owner")

    with pytest.raises(InvalidTokenError, match="expired"):
        _decode_token(expired)
