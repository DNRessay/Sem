import time

import pytest
import respx
from httpx import Response

from tools.google._auth import get_google_token


class FakeStore:
    def __init__(self, connector=None):
        self._connector = connector
        self.upserts = []

    async def get_connector(self, account_id, provider):
        return self._connector

    async def upsert_connector(self, account_id, provider, token, refresh_token=None, expires_at=None):
        self.upserts.append((account_id, provider, token, refresh_token, expires_at))


@pytest.mark.asyncio
async def test_returns_error_dict_when_no_connector(monkeypatch):
    store = FakeStore(connector=None)

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    result = await get_google_token("owner", "Calendar")

    assert isinstance(result, dict)
    assert "connect Google first" in result["error"]
    assert "Calendar" in result["error"]


@pytest.mark.asyncio
async def test_returns_the_token_directly_when_not_expiring_soon(monkeypatch):
    connector = {"token": "still-good", "refresh_token": "r1", "expires_at": int(time.time()) + 3600}
    store = FakeStore(connector=connector)

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    result = await get_google_token("owner")

    assert result == "still-good"
    assert store.upserts == []  # no refresh needed


@pytest.mark.asyncio
async def test_refreshes_a_token_expiring_soon_and_persists_it(monkeypatch):
    connector = {"token": "stale", "refresh_token": "r1", "expires_at": int(time.time()) + 10}
    store = FakeStore(connector=connector)

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    with respx.mock:
        respx.post("https://oauth2.googleapis.com/token").mock(
            return_value=Response(200, json={"access_token": "fresh-token", "expires_in": 3599})
        )
        result = await get_google_token("owner")

    assert result == "fresh-token"
    assert store.upserts == [("owner", "google", "fresh-token", "r1", store.upserts[0][4])]
    assert store.upserts[0][4] > int(time.time())


@pytest.mark.asyncio
async def test_a_manually_set_token_with_no_expiry_is_never_refreshed(monkeypatch):
    """A token with no expires_at/refresh_token (there's no manual-paste
    flow for Google today, but the shape should still degrade safely)
    returns as-is rather than erroring."""
    connector = {"token": "no-expiry-known", "refresh_token": None, "expires_at": None}
    store = FakeStore(connector=connector)

    async def fake_get_store():
        return store

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)
    result = await get_google_token("owner")

    assert result == "no-expiry-known"
