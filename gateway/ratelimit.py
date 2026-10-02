"""Fixed-window attempt counters in the DynamoDB cache (shared by every Lambda instance).
Not atomic, so a burst can overshoot by a few; good enough to stop guessing at scale."""
from cache import ddb_backend

_NS = "ratelimit"


def client_ip(request) -> str:
    # The Function URL puts the caller first in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def used(bucket: str, key: str) -> int:
    try:
        return int(ddb_backend.get(_NS, f"{bucket}:{key}") or 0)
    except ValueError:
        return 0


def blocked(bucket: str, key: str, limit: int) -> bool:
    return used(bucket, key) >= limit


def record(bucket: str, key: str, window_seconds: int) -> int:
    n = used(bucket, key) + 1
    ddb_backend.set(_NS, f"{bucket}:{key}", str(n), ttl=window_seconds)
    return n


def clear(bucket: str, key: str) -> None:
    ddb_backend.delete(_NS, f"{bucket}:{key}")
