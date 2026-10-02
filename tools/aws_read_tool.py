import asyncio
import json
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import settings

# Read-only by construction: only Describe*/List*/Get* (plus CloudWatch's
# FilterLogEvents) run, the ones that return secrets or raw data are refused
# outright, and environment variables are redacted from every result (so
# GetFunctionConfiguration is safe). Permissions come from the Lambda's role:
# ViewOnlyAccess plus log reads (template.yaml).
_ALLOWED_PREFIXES = ("Describe", "List", "Get")
_ALLOWED_EXTRA = {"FilterLogEvents", "StartQuery", "BatchGetTraces"}  # logs, Logs Insights, X-Ray traces
_DENIED = {
    "GetSecretValue", "GetParameter", "GetParameters", "GetParametersByPath",
    "GetFunction", "GetObject", "GetItem", "BatchGetItem",
    "GetCredentialsForIdentity", "GetSessionToken", "GetFederationToken", "GetAuthorizationToken",
    "GetPasswordData", "GetQueueAttributes", "GetLoginProfile", "GetAccessKeyLastUsed",
}
_REDACT_KEYS = {"environment", "variables", "secretstring", "secretbinary", "password", "accesskeyid", "secretaccesskey",
                "sessiontoken", "secrets"}  # matched case-insensitively (ECS uses lower-case "environment")
_MAX_OUTPUT = 8000


def _redact(value):
    if isinstance(value, dict):
        return {k: ("[redacted]" if str(k).lower() in _REDACT_KEYS else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _to_pascal(op: str) -> str:
    if "_" in op or op.islower():
        return "".join(part.capitalize() for part in op.split("_"))
    return op


class AwsReadTool:
    async def call(self, service: str, operation: str, params: dict | None = None, region: str = "") -> dict:
        if not re.fullmatch(r"[a-z0-9-]+", service or ""):
            return {"ok": False, "error": "service must be a boto3 service name, e.g. 'lambda', 's3', 'dynamodb'"}
        op = _to_pascal(operation or "")
        if not op.startswith(_ALLOWED_PREFIXES) and op not in _ALLOWED_EXTRA:
            return {"ok": False, "error": "read-only: only Describe*/List*/Get* operations are allowed"}
        if op in _DENIED:
            return {"ok": False, "error": f"{op} can return secrets or raw data, so it's not allowed"}
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", op).lower()
        try:
            client = boto3.client(service, region_name=region or settings.AWS_REGION)
            fn = getattr(client, snake, None)
            if fn is None:
                return {"ok": False, "error": f"{service} has no operation {op}"}
            result = await asyncio.to_thread(fn, **(params or {}))
        except (ClientError, BotoCoreError, TypeError) as e:
            return {"ok": False, "error": str(e)[:500]}
        result.pop("ResponseMetadata", None)
        text = json.dumps(_redact(result), default=str)
        return {"ok": True, "result": text[:_MAX_OUTPUT], "truncated": len(text) > _MAX_OUTPUT}
