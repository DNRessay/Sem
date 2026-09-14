import base64
import hashlib
import hmac
import json
import time

from fastapi import HTTPException, Request

from config import settings
from gateway.passphrase import hash_passphrase, verify_passphrase  # noqa: F401 (re-exported)

TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


class InvalidTokenError(Exception):
    pass


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def issue_token(account_id: str, role: str) -> str:
    """A minimal hand-rolled HS256-signed token (header.payload.signature, all
    base64url) — not the PyJWT library, which unconditionally imports the
    `cryptography` package even for plain HMAC use. We only ever need HMAC-SHA256
    here, so stdlib hmac/hashlib covers it with far less surface area and one
    less (and heavier) dependency to keep working across Lambda/CI."""
    header = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub": account_id, "role": role, "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }).encode())
    signing_input = f"{header}.{payload}"
    signature = hmac.new(settings.SECRET_KEY.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def _decode_token(token: str) -> dict:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise InvalidTokenError("Malformed token")

    expected_sig = hmac.new(
        settings.SECRET_KEY.encode(), f"{header_b64}.{payload_b64}".encode(), hashlib.sha256,
    ).digest()
    try:
        given_sig = _b64url_decode(sig_b64)
    except Exception:
        raise InvalidTokenError("Malformed signature")
    if not hmac.compare_digest(given_sig, expected_sig):
        raise InvalidTokenError("Bad signature")

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        raise InvalidTokenError("Malformed payload")
    if payload.get("exp", 0) < time.time():
        raise InvalidTokenError("Token expired")
    return payload


async def require_account(request: Request) -> dict:
    """FastAPI dependency — raises 401 unless a valid Bearer token is present.
    Use on every route that touches conversation content or owner profile data;
    this is what actually stops a random visitor to the public frontend URL
    from using the assistant or seeing anything in it."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    try:
        payload = _decode_token(auth_header[len("Bearer "):])
    except InvalidTokenError as e:
        raise HTTPException(401, str(e))
    return {"account_id": payload["sub"], "role": payload["role"]}
