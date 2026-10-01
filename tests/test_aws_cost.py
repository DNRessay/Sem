import pytest
import respx
from httpx import Response

from cache import ddb_backend
from tools import aws_cost


@pytest.mark.asyncio
async def test_bill_in_rand_is_cached(monkeypatch):
    ddb_backend.delete("aws_cost", "mtd")
    calls = []

    def fake_usd():
        calls.append(1)
        return 4.5

    monkeypatch.setattr(aws_cost, "_estimated_charges_usd", fake_usd)
    with respx.mock:
        respx.get(aws_cost._FX_URL).mock(return_value=Response(200, json={"rates": {"ZAR": 18.0}}))
        first = await aws_cost.month_to_date()
        second = await aws_cost.month_to_date()
    assert first["zar"] == 81.0 and second == first and len(calls) == 1
    ddb_backend.delete("aws_cost", "mtd")


@pytest.mark.asyncio
async def test_no_billing_data_says_how_to_turn_it_on(monkeypatch):
    ddb_backend.delete("aws_cost", "mtd")
    monkeypatch.setattr(aws_cost, "_estimated_charges_usd", lambda: None)
    result = await aws_cost.month_to_date()
    assert not result["ok"] and "Billing Alerts" in result["error"]
