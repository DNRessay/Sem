"""Month-to-date AWS bill in rand, for the fading line at the top of chat.

Free on purpose: AWS's EstimatedCharges metric from CloudWatch (us-east-1,
needs "Receive Billing Alerts" on in Billing preferences) instead of Cost
Explorer, which charges $0.01 a call. The USD→ZAR rate is C-Lab's live
quote when C-Lab is connected, else a keyless daily public rate. Cached for
an hour (the bill itself only updates a few times a day)."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import boto3
import httpx

from cache import ddb_backend

_TTL = 3600
_FX_URL = "https://open.er-api.com/v6/latest/USD"


def _estimated_charges_usd() -> float | None:
    cw = boto3.client("cloudwatch", region_name="us-east-1")  # billing metrics only live here
    now = datetime.now(timezone.utc)
    data = cw.get_metric_statistics(
        Namespace="AWS/Billing", MetricName="EstimatedCharges",
        Dimensions=[{"Name": "Currency", "Value": "USD"}],
        StartTime=now - timedelta(days=2), EndTime=now, Period=21600, Statistics=["Maximum"],
    )
    points = sorted(data.get("Datapoints", []), key=lambda p: p["Timestamp"])
    return float(points[-1]["Maximum"]) if points else None


async def _clab_usd_zar(account_id: str) -> float | None:
    """Live USD/ZAR from C-Lab's markets board (Yahoo ZAR=X) when C-Lab is connected as MCP server "clab"."""
    from storage.neon_store import get_store
    from tools.mcp_client import MCPClient
    try:
        db = await get_store()
        server = next((s for s in await db.list_mcp_servers(account_id) if s["name"] == "clab"), None)
        if not server:
            return None
        result = await MCPClient(server["url"], server.get("auth", ""), timeout=15).call_tool("quote", {"symbol": "ZAR=X"})
        price = json.loads(result["text"]).get("price") if result.get("ok") else None
        return float(price) if price else None
    except Exception:
        return None


async def _usd_to_zar() -> float | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_FX_URL)
        return float(r.json()["rates"]["ZAR"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


async def zar_rate(account_id: str = "owner") -> tuple[float | None, str | None]:
    """USD→ZAR: C-Lab's live quote when connected, else the daily public rate."""
    rate = await _clab_usd_zar(account_id)
    if rate:
        return rate, "C-Lab (live)"
    rate = await _usd_to_zar()
    return rate, "open.er-api.com (daily)" if rate else None


async def month_to_date(account_id: str = "owner") -> dict:
    cached = ddb_backend.get("aws_cost", "mtd")
    if cached:
        return json.loads(cached)
    try:
        usd = await asyncio.to_thread(_estimated_charges_usd)
    except Exception as e:
        return {"ok": False, "error": f"Couldn't read the AWS bill: {str(e)[:200]}"}
    if usd is None:
        return {"ok": False, "error": "No billing data yet — turn on 'Receive Billing Alerts' in AWS Billing preferences"}
    rate, source = await zar_rate(account_id)
    result = {"ok": True, "usd": round(usd, 2), "zar": round(usd * rate, 2) if rate else None,
              "rate": rate, "rate_source": source if rate else None, "as_of": int(time.time())}
    ddb_backend.set("aws_cost", "mtd", json.dumps(result), ttl=_TTL)
    return result
