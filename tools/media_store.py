"""Generated ad images and video ads, kept 7 days in S3. The bucket (MEDIA_BUCKET) is private with a lifecycle
rule that deletes everything after 7 days. The app gets a link to /media/file/... signed with SECRET_KEY and valid
just as long; opening it redirects to a short-lived S3 URL, so <img>/<video> work without a login header."""
import asyncio
import base64
import hashlib
import hmac
import re
import time
import uuid
from urllib.parse import quote

from config import settings

KEEP_SECONDS = 7 * 24 * 3600
KEY_RE = re.compile(r"(ads|video)/\d{4}-\d{2}-\d{2}/[a-f0-9]{32}\.(png|jpg|webp|mp4)")
_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "video/mp4": "mp4"}


def enabled() -> bool:
    return bool(settings.MEDIA_BUCKET)


def _client():
    import boto3

    return boto3.client("s3", region_name=settings.MEDIA_REGION)


def sign(key: str, exp: int) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"{key}:{exp}".encode(), hashlib.sha256).hexdigest()[:40]


def link(key: str, exp: int | None = None) -> str:
    exp = exp or int(time.time()) + KEEP_SECONDS
    return f"{settings.PUBLIC_API_URL.rstrip('/')}/media/file/{quote(key)}?exp={exp}&sig={sign(key, exp)}"


def verify(key: str, exp: int, sig: str) -> bool:
    return bool(KEY_RE.fullmatch(key)) and exp > time.time() and hmac.compare_digest(sign(key, exp), sig or "")


async def save(data_b64: str, mime: str, kind: str) -> str | None:
    """Stores the file and returns its 7-day link, or None (no bucket, or S3 failed: the caller keeps base64)."""
    ext = _EXT.get(mime)
    if not enabled() or not ext or kind not in ("ads", "video"):
        return None
    key = f"{kind}/{time.strftime('%Y-%m-%d')}/{uuid.uuid4().hex}.{ext}"
    try:
        body = base64.b64decode(data_b64)
        await asyncio.to_thread(_client().put_object, Bucket=settings.MEDIA_BUCKET, Key=key, Body=body, ContentType=mime)
    except Exception:
        return None
    return link(key)


def presigned(key: str) -> str:
    return _client().generate_presigned_url("get_object", Params={"Bucket": settings.MEDIA_BUCKET, "Key": key}, ExpiresIn=600)
