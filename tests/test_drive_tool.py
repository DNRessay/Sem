import pytest
import respx
from httpx import Response

from tools.google.drive_tool import DriveTool

FILES = "https://www.googleapis.com/drive/v3/files"
UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"


@pytest.mark.asyncio
async def test_query_returns_error_when_not_connected(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return {"error": "No Google connector configured for this account — connect Google first (Drive needs it)."}

    monkeypatch.setattr("tools.google.drive_tool.get_google_token", fake_get_token)
    result = await DriveTool().query("list_files")
    assert "connect Google first" in result["error"]


@pytest.mark.asyncio
async def test_list_files_returns_the_files(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.drive_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.get(FILES).mock(return_value=Response(200, json={"files": [
            {"id": "f1", "name": "Note 1", "mimeType": "text/plain", "modifiedTime": "2026-09-15T00:00:00Z"},
        ]}))
        result = await DriveTool().query("list_files")

    assert result["files"][0]["name"] == "Note 1"


@pytest.mark.asyncio
async def test_read_file_requires_file_id(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.drive_tool.get_google_token", fake_get_token)
    result = await DriveTool().query("read_file")
    assert result == {"error": "file_id required"}


@pytest.mark.asyncio
async def test_read_file_returns_content(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.drive_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.get(f"{FILES}/f1").mock(return_value=Response(200, text="the note content"))
        result = await DriveTool().query("read_file", file_id="f1")

    assert result == {"file_id": "f1", "content": "the note content"}


@pytest.mark.asyncio
async def test_create_note_uploads_multipart(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.drive_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.post(f"{UPLOAD}?uploadType=multipart").mock(return_value=Response(200, json={"id": "new1"}))
        result = await DriveTool().query("create_note", title="Shopping list", content="milk, eggs")

    assert result == {"file_id": "new1", "title": "Shopping list"}


@pytest.mark.asyncio
async def test_append_note_requires_file_id(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.drive_tool.get_google_token", fake_get_token)
    result = await DriveTool().query("append_note", content="more stuff")
    assert result == {"error": "file_id required"}


@pytest.mark.asyncio
async def test_append_note_reads_then_rewrites_the_full_content(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.drive_tool.get_google_token", fake_get_token)
    with respx.mock:
        respx.get(f"{FILES}/f1").mock(return_value=Response(200, text="existing line"))
        route = respx.patch(f"{UPLOAD}/f1?uploadType=media").mock(return_value=Response(200, json={"id": "f1"}))
        result = await DriveTool().query("append_note", file_id="f1", content="new line")

    assert result == {"file_id": "f1", "appended": True}
    assert route.calls[0].request.content == b"existing line\nnew line"


@pytest.mark.asyncio
async def test_unknown_action_returns_a_clear_error(monkeypatch):
    async def fake_get_token(account_id, scope_hint=""):
        return "tok"

    monkeypatch.setattr("tools.google.drive_tool.get_google_token", fake_get_token)
    result = await DriveTool().query("delete_file")
    assert "Unknown drive action" in result["error"]
