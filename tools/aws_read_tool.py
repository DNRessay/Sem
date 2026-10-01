import asyncio
import json
import re

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import settings

# Read-only by construction: only Describe*/List*/Get* operations run, and
# the ones that return secrets or raw data are refused outright. Permissions
# come from the Lambda's own role — attach AWS's ViewOnlyAccess policy to it
# for this tool to see anything beyond what Sem already uses.
_ALLOWED_PREFIXES = ("Describe", "List", "Get")
_DENIED = {
    "GetSecretValue", "GetParameter", "GetParameters", "GetParametersByPath",
    "GetFunction", "GetFunctionConfiguration", "GetObject", "GetItem", "BatchGetItem",
    "GetCredentialsForIdentity", "GetSessionToken", "GetFederationToken", "GetAuthorizationToken",
    "GetPasswordData", "GetQueueAttributes", "GetLoginProfile", "GetAccessKeyLastUsed",
}
_REDACT_KEYS = {"Environment", "Variables", "SecretString", "Password", "AccessKeyId", "SecretAccessKey", "SessionToken"}
_MAX_OUTPUT = 8000


def _redact(value):
    if isinstance(value, dict):
        return {k: ("[redacted]" if k in _REDACT_KEYS else _redact(v)) for k, v in value.items()}
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
        if not op.startswith(_ALLOWED_PREFIXES):
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
