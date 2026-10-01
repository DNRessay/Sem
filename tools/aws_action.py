"""AWS changes for Sem Code — only ever run after the user taps Approve.
Each request is labelled so the approval card says what kind of change it is:
permissions, something with a running/monthly cost, or a deletion."""
import asyncio
import json
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import settings
from tools.aws_read_tool import _ALLOWED_EXTRA, _ALLOWED_PREFIXES, _redact, _to_pascal

_PERMISSION_SERVICES = {"iam", "sts", "organizations", "sso-admin", "identitystore", "kms", "account"}
_PERMISSION_WORDS = re.compile(r"Policy|Permission|Role|Grant|AccessKey|LoginProfile|Credential|Trust|Principal")
# Services whose create/start calls usually leave something running that bills by the hour or month.
_COSTLY_SERVICES = {
    "ec2", "rds", "elasticache", "eks", "ecs", "redshift", "opensearch", "es", "sagemaker", "lightsail",
    "elbv2", "elb", "route53domains", "globalaccelerator", "dax", "docdb", "neptune", "kafka", "mq", "kinesis",
    "workspaces", "appstream", "directconnect", "apprunner", "memorydb", "fsx", "efs", "transfer", "networkfirewall",
    "shield", "guardduty", "macie2", "inspector2", "securityhub", "config", "savingsplans", "route53",
}
_CREATE_WORDS = ("Create", "Run", "Start", "Purchase", "Allocate", "Register", "Enable", "Request", "Subscribe", "Modify")
_DELETE_WORDS = ("Delete", "Terminate", "Remove", "Deregister", "Release", "Disable", "Stop", "Revoke")
_MAX_OUTPUT = 6000


def classify(service: str, operation: str) -> list[str]:
    op = _to_pascal(operation or "")
    flags = []
    if service in _PERMISSION_SERVICES or _PERMISSION_WORDS.search(op):
        flags.append("PERMISSIONS:")
    if service in _COSTLY_SERVICES and op.startswith(_CREATE_WORDS):
        flags.append("COSTS MONEY (monthly):")
    if op.startswith(_DELETE_WORDS):
        flags.append("DELETES/STOPS:")
    return flags


def check(service: str, operation: str) -> str | None:
    """None if this is a valid change request, else why not."""
    if not re.fullmatch(r"[a-z0-9-]+", service or ""):
        return "service must be a boto3 service name, e.g. 'lambda', 's3'"
    op = _to_pascal(operation or "")
    if not re.fullmatch(r"[A-Z][A-Za-z0-9]+", op):
        return "operation must be an API name like UpdateFunctionConfiguration"
    if op.startswith(_ALLOWED_PREFIXES) or op in _ALLOWED_EXTRA:
        return "that's a read — use the aws tool, which needs no approval"
    return None


async def over_limit() -> str | None:
    """Why new AWS changes are paused, if this month's bill has reached AWS_SPEND_LIMIT_USD."""
    from tools.aws_cost import month_to_date

    bill = await month_to_date()
    if bill.get("ok") and bill["usd"] >= settings.AWS_SPEND_LIMIT_USD:
        return (f"AWS spend this month is ${bill['usd']:.2f}, at or over the ${settings.AWS_SPEND_LIMIT_USD:.2f} limit — "
                "changes are paused (deletes/stops still allowed). Raise AWS_SPEND_LIMIT_USD to continue.")
    return None


async def run(service: str, operation: str, params: dict | None = None, region: str = "") -> dict:
    op = _to_pascal(operation)
    if not op.startswith(_DELETE_WORDS):
        stop = await over_limit()
        if stop:
            return {"ok": False, "error": stop}
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", op).lower()
    try:
        client = boto3.client(service, region_name=region or settings.AWS_REGION)
        fn = getattr(client, snake, None)
        if fn is None:
            return {"ok": False, "error": f"{service} has no operation {op}"}
        result = await asyncio.to_thread(fn, **(params or {}))
    except (ClientError, BotoCoreError, TypeError) as e:
        text = str(e)
        if "AccessDenied" in text or "not authorized" in text:
            text += (" — Sem's AWS role (semblance-chat) may only change Lambda functions (config, code, versions, "
                     "invoke) and S3 objects/buckets; anything else is done in the AWS console.")
        return {"ok": False, "error": text[:600]}
    result.pop("ResponseMetadata", None)
    out = json.dumps(_redact(result), default=str)
    return {"ok": True, "status": f"{service} {op} done", "result": out[:_MAX_OUTPUT]}
