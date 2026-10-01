import json

import pytest
import respx
from httpx import Response

from agents.code_agent import CodeAgent
from tools.aws_read_tool import AwsReadTool
from tools.code_workspace import CodeWorkspace

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class FakeWorkspace:
    provider, repo = "github", "me/app"

    def __init__(self):
        self.calls = []

    async def read_file(self, path):
        self.calls.append(("read_file", path))
        return {"ok": True, "content": "def add(a, b):\n    return a - b\n", "path": path}

    async def edit_file(self, path, old, new, replace_all=False):
        self.calls.append(("edit_file", path, old, new))
        return {"ok": True, "path": path, "replacements": 1}

    async def bash(self, command, timeout=60):
        self.calls.append(("bash", command))
        return {"ok": True, "exit_code": 0, "output": "1 passed"}

    async def write_file(self, path, content):
        self.calls.append(("write_file", path))
        return {"ok": True}


def _tool_call(call_id, name, args):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _reply(content="", calls=None):
    return Response(200, json={"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": calls}}]})


@pytest.fixture(autouse=True)
def groq_only(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "LOCAL_LLM_URL", "")


@pytest.mark.asyncio
async def test_agent_loops_through_tools_until_a_final_answer():
    ws = FakeWorkspace()
    with respx.mock:
        route = respx.post(GROQ_URL).mock(side_effect=[
            _reply("Looking.", [_tool_call("c1", "read_file", {"path": "app.py"})]),
            _reply("", [_tool_call("c2", "edit_file", {"path": "app.py", "old": "a - b", "new": "a + b"}),
                        _tool_call("c3", "bash", {"command": "pytest -q"})]),
            _reply("Fixed add() and tests pass."),
        ])
        events = [e async for e in CodeAgent(ws).run("fix add")]

    assert [c[0] for c in ws.calls] == ["read_file", "edit_file", "bash"]
    assert [e["type"] for e in events] == ["text", "tool", "result", "tool", "result", "tool", "result", "text", "done"]
    assert events[-2]["text"] == "Fixed add() and tests pass."
    third_request = json.loads(route.calls[2].request.content)
    tool_msgs = [m for m in third_request["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c1", "c2", "c3"]
    assert "1 passed" in tool_msgs[-1]["content"]


@pytest.mark.asyncio
async def test_plan_mode_only_offers_and_allows_read_only_tools():
    ws = FakeWorkspace()
    with respx.mock:
        route = respx.post(GROQ_URL).mock(side_effect=[
            _reply("", [_tool_call("c1", "write_file", {"path": "x.py", "content": "x"})]),
            _reply("1. Change add()"),
        ])
        events = [e async for e in CodeAgent(ws, mode="plan").run("plan it")]

    offered = {t["function"]["name"] for t in json.loads(route.calls[0].request.content)["tools"]}
    assert offered == {"list_dir", "read_file", "grep", "aws"}
    assert ws.calls == []
    assert events[1] == {"type": "result", "id": "c1", "name": "write_file", "ok": False, "output": "plan mode is read-only"}


@pytest.mark.asyncio
async def test_bad_tool_arguments_are_reported_back_not_crashed_on():
    ws = FakeWorkspace()
    bad = {"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{not json"}}
    with respx.mock:
        respx.post(GROQ_URL).mock(side_effect=[_reply("", [bad]), _reply("ok")])
        events = [e async for e in CodeAgent(ws).run("go")]
    assert events[1]["ok"] is False and "not valid JSON" in events[1]["output"]
    assert ws.calls == []


@pytest.mark.asyncio
async def test_model_error_ends_the_run_with_an_error_event():
    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=Response(500, json={"error": "boom"}))
        events = [e async for e in CodeAgent(FakeWorkspace()).run("go")]
    assert events == [{"type": "error", "text": "model error 500: {'error': 'boom'}"}]


@pytest.mark.asyncio
async def test_step_limit_stops_a_runaway_loop():
    with respx.mock:
        respx.post(GROQ_URL).mock(return_value=_reply("", [_tool_call("c", "bash", {"command": "true"})]))
        events = [e async for e in CodeAgent(FakeWorkspace(), max_steps=3).run("go")]
    assert events[-1]["type"] == "error" and "3 steps" in events[-1]["text"]


@pytest.mark.asyncio
async def test_workspace_bash_is_gated_before_it_reaches_modal(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "MODAL_REPO_URL", "https://modal.example/repo")
    with respx.mock:
        route = respx.post("https://modal.example/repo").mock(return_value=Response(200, json={"ok": True}))
        result = await CodeWorkspace("github", "me/app").bash("rm -rf /")
    assert result["blocked"] and route.call_count == 0


@pytest.mark.asyncio
async def test_workspace_sends_the_code_namespace(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "MODAL_REPO_URL", "https://modal.example/repo")
    monkeypatch.setattr(settings, "MODAL_REPO_SECRET", "s3")
    with respx.mock:
        route = respx.post("https://modal.example/repo").mock(return_value=Response(200, json={"ok": True}))
        await CodeWorkspace("github", "me/app").edit_file("a.py", "x", "y")
    sent = json.loads(route.calls[0].request.content)
    assert sent["namespace"] == "code" and sent["action"] == "edit_file"
    assert route.calls[0].request.headers["authorization"] == "Bearer s3"


@pytest.mark.asyncio
async def test_aws_tool_refuses_writes_and_secret_reads():
    aws = AwsReadTool()
    assert "read-only" in (await aws.call("s3", "DeleteBucket"))["error"]
    assert "not allowed" in (await aws.call("secretsmanager", "GetSecretValue"))["error"]
    assert "not allowed" in (await aws.call("lambda", "get_function_configuration"))["error"]


@pytest.mark.asyncio
async def test_aws_tool_redacts_environment_variables(monkeypatch):
    class FakeClient:
        def list_functions(self):
            return {"Functions": [{"FunctionName": "f", "Environment": {"Variables": {"KEY": "secret"}}}],
                    "ResponseMetadata": {}}

    monkeypatch.setattr("tools.aws_read_tool.boto3.client", lambda *a, **k: FakeClient())
    result = await AwsReadTool().call("lambda", "ListFunctions")
    assert result["ok"] and "secret" not in result["result"] and "[redacted]" in result["result"]
