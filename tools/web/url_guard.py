"""Fetching URLs the model (or a web page it read) picked: only public http(s) addresses, checked again on
every redirect, so a prompt injection can't point SEMBLANCE at localhost (Lambda's runtime API lives on
127.0.0.1), the cloud metadata address or anything on a private network."""
import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

MAX_REDIRECTS = 5


class BlockedURL(Exception):
    pass


async def check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedURL("only http(s) web addresses can be fetched")
    host = parts.hostname
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        raise BlockedURL(f"can't resolve {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise BlockedURL(f"{host} points to a private or local address")


async def safe_get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    """GET that refuses non-public targets; `client` must not follow redirects itself."""
    for _ in range(MAX_REDIRECTS + 1):
        await check_url(url)
        r = await client.get(url, follow_redirects=False, **kwargs)
        if r.is_redirect and r.headers.get("location"):
            url = urljoin(str(r.url), r.headers["location"])
            continue
        return r
    raise BlockedURL("too many redirects")
