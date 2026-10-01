import pytest

from tools import aws_read_tool
from tools.aws_read_tool import AwsReadTool


class FakeClient:
    def get_function_configuration(self, FunctionName):
        return {"FunctionName": FunctionName, "Environment": {"Variables": {"GROQ_API_KEY": "gsk_secret"}},
                "ResponseMetadata": {}}

    def filter_log_events(self, logGroupName, **kw):
        return {"events": [{"message": "ERROR boom"}]}


@pytest.fixture(autouse=True)
def fake_boto(monkeypatch):
    monkeypatch.setattr(aws_read_tool.boto3, "client", lambda *a, **k: FakeClient())


@pytest.mark.asyncio
async def test_function_config_is_readable_but_env_is_redacted():
    r = await AwsReadTool().call("lambda", "GetFunctionConfiguration", {"FunctionName": "c-lab"})
    assert r["ok"] and "gsk_secret" not in r["result"] and "[redacted]" in r["result"]


@pytest.mark.asyncio
async def test_logs_can_be_filtered_and_writes_are_refused():
    assert "boom" in (await AwsReadTool().call("logs", "FilterLogEvents", {"logGroupName": "/aws/lambda/x"}))["result"]
    assert not (await AwsReadTool().call("lambda", "DeleteFunction", {}))["ok"]
    assert not (await AwsReadTool().call("lambda", "GetFunction", {}))["ok"]
    assert not (await AwsReadTool().call("secretsmanager", "GetSecretValue", {}))["ok"]
