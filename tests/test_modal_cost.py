import pytest

from tools import modal_cost


@pytest.mark.asyncio
async def test_spend_against_free_credit_in_rand(monkeypatch):
    store = {}

    async def budget(action, **kw):
        assert action == "budget"
        return {"ok": True, "used_usd": 4.5, "cap_usd": 10}

    async def rate(account_id="owner"):
        return 18.0, "test"

    monkeypatch.setattr(modal_cost, "video_call", budget)
    monkeypatch.setattr(modal_cost, "zar_rate", rate)
    monkeypatch.setattr(modal_cost.settings, "MODAL_VIDEO_URL", "https://m")
    monkeypatch.setattr(modal_cost.ddb_backend, "get", lambda ns, k: store.get(k))
    monkeypatch.setattr(modal_cost.ddb_backend, "set", lambda ns, k, v, ttl=300: store.__setitem__(k, v))
    out = await modal_cost.month_to_date()
    assert out["zar"] == 81.0 and out["free_left_usd"] == 25.5 and out["cap_usd"] == 10
    assert "mtd" in store


@pytest.mark.asyncio
async def test_not_connected(monkeypatch):
    monkeypatch.setattr(modal_cost.settings, "MODAL_VIDEO_URL", "")
    assert (await modal_cost.month_to_date())["ok"] is False
