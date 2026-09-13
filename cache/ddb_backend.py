"""
Shared DynamoDB cache backend.

Every cache module (SysCache, ConvCache, TAUCache, CacheController) is a thin
wrapper around this. Table layout: PK "pk" (namespace#key), TTL attribute "ttl"
(epoch seconds — DynamoDB deletes the item automatically, no cron needed).

A per-process in-memory dict sits in front as an L1 cache: on a warm Lambda
invocation reads never leave the process; only cold starts and writes touch
DynamoDB. Falls back to memory-only if boto3/DynamoDB isn't reachable (local
dev without AWS creds) so the app still runs.
"""
import time

from config import settings

try:
    import boto3
    _boto3_available = True
except ImportError:
    _boto3_available = False

_table = None
_l1: dict[str, tuple[str, float, int]] = {}  # pk -> (value, written_at, ttl_seconds)


def _get_table():
    global _table
    if _table is None and _boto3_available:
        try:
            _table = boto3.resource("dynamodb", region_name=settings.AWS_REGION).Table(
                settings.CACHE_TABLE_NAME
            )
        except Exception:
            _table = False  # sentinel: tried and failed, don't retry every call
    return _table or None


def get(namespace: str, key: str) -> str | None:
    pk = f"{namespace}#{key}"
    entry = _l1.get(pk)
    if entry:
        value, written_at, ttl = entry
        if time.time() - written_at < ttl:
            return value
        del _l1[pk]

    table = _get_table()
    if not table:
        return None
    try:
        resp = table.get_item(Key={"pk": pk})
        item = resp.get("Item")
        if not item:
            return None
        value = item["value"]
        remaining_ttl = max(1, int(item.get("ttl", 0) - time.time()))
        _l1[pk] = (value, time.time(), remaining_ttl)
        return value
    except Exception:
        return None


def set(namespace: str, key: str, value: str, ttl: int = 300) -> None:
    pk = f"{namespace}#{key}"
    _l1[pk] = (value, time.time(), ttl)

    table = _get_table()
    if not table:
        return
    try:
        table.put_item(Item={"pk": pk, "value": value, "ttl": int(time.time()) + ttl})
    except Exception:
        pass  # cache is best-effort; never break the request path over it


def delete(namespace: str, key: str) -> None:
    pk = f"{namespace}#{key}"
    _l1.pop(pk, None)
    table = _get_table()
    if not table:
        return
    try:
        table.delete_item(Key={"pk": pk})
    except Exception:
        pass


def clear_namespace(namespace: str) -> None:
    """L1-only clear (used by CacheController.invalidate — a full table scan
    per break-vector fire would be wasteful; expired DynamoDB items age out via TTL)."""
    prefix = f"{namespace}#"
    for pk in [k for k in _l1 if k.startswith(prefix)]:
        del _l1[pk]
