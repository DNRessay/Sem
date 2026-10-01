"""Month-to-date AWS bill in rand, for the fading line at the top of chat.

Free on purpose: AWS's EstimatedCharges metric from CloudWatch (us-east-1,
needs "Receive Billing Alerts" on in Billing preferences) instead of Cost
Explorer, which charges $0.01 a call. The USD→ZAR rate comes from a keyless
public API. Both are cached for 6 hours."""
import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import boto3
import httpx

from cache import ddb_backend

_TTL = 6 * 3600
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


async def _usd_to_zar() -> float | None:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(_FX_URL)
        return float(r.json()["rates"]["ZAR"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


async def month_to_date() -> dict:
    cached = ddb_backend.get("aws_cost", "mtd")
    if cached:
        return json.loads(cached)
    try:
        usd = await asyncio.to_thread(_estimated_charges_usd)
    except Exception as e:
        return {"ok": False, "error": f"Couldn't read the AWS bill: {str(e)[:200]}"}
    if usd is None:
        return {"ok": False, "error": "No billing data yet — turn on 'Receive Billing Alerts' in AWS Billing preferences"}
    rate = await _usd_to_zar()
    result = {"ok": True, "usd": round(usd, 2), "zar": round(usd * rate, 2) if rate else None,
              "rate": rate, "as_of": int(time.time())}
    ddb_backend.set("aws_cost", "mtd", json.dumps(result), ttl=_TTL)
    return result
