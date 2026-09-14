"""Passphrase hashing — split out from gateway/auth.py so it has zero
dependencies beyond the stdlib. scripts/seed_accounts.py needs exactly this
(to hash a passphrase before writing it to Neon) and nothing else from
gateway/auth.py, which pulls in FastAPI; keeping this import-light means the
one-off seed workflow only needs `pip install asyncpg`, not the full app."""

import hashlib
import hmac
import os

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _SCRYPT_DKLEN = 16384, 8, 1, 64


def hash_passphrase(passphrase: str, salt: bytes | None = None) -> str:
    """Returns 'salt_hex:hash_hex'. Verify with verify_passphrase, never compare directly."""
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(
        passphrase.encode(), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCRYPT_DKLEN,
    )
    return f"{salt.hex()}:{digest.hex()}"


def verify_passphrase(passphrase: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split(":")
    except ValueError:
        return False
    candidate = hash_passphrase(passphrase, salt=bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, stored_hash)
