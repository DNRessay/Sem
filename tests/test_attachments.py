import base64
import io

import pytest

from gateway.router import _fold_attachments, _is_image


class _NoopStore:
    async def save_agent_event(self, session_id, agent, action):
        pass


@pytest.fixture(autouse=True)
def _stub_store(monkeypatch):
    async def fake_get_store():
        return _NoopStore()

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)


@pytest.mark.asyncio
async def test_fold_attachments_returns_message_unchanged_when_empty():
    assert await _fold_attachments("hello", [], "sess1") == "hello"
    assert await _fold_attachments("hello", None, "sess1") == "hello"


@pytest.mark.asyncio
async def test_fold_attachments_appends_fenced_file_blocks():
    result = await _fold_attachments("check this file", [{"name": "app.py", "content": "print('hi')"}], "sess1")
    assert result.startswith("check this file\n\n<attachments>")
    assert '<file name="app.py">' in result
    assert "print('hi')" in result
    assert result.endswith("</attachments>")


@pytest.mark.asyncio
async def test_fold_attachments_handles_multiple_files():
    result = await _fold_attachments("msg", [
        {"name": "a.py", "content": "A"},
        {"name": "b.py", "content": "B"},
    ], "sess1")
    assert result.count("<file name=") == 2
    assert "a.py" in result and "b.py" in result


@pytest.mark.asyncio
async def test_fold_attachments_extracts_text_from_base64_pdf():
    from pypdf import PdfWriter

    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    result = await _fold_attachments("summarize", [{"name": "doc.pdf", "mime": "application/pdf", "base64": b64}], "sess1")
    assert '<file name="doc.pdf">' in result  # a blank page extracts to empty text, but shouldn't raise


@pytest.mark.asyncio
async def test_fold_attachments_extracts_text_from_base64_docx():
    import docx

    buf = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("Hello from a Word doc")
    document.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    result = await _fold_attachments("summarize", [{"name": "doc.docx", "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "base64": b64}], "sess1")
    assert "Hello from a Word doc" in result


@pytest.mark.asyncio
async def test_fold_attachments_logs_a_blocked_event_when_extraction_fails(monkeypatch):
    """A malformed PDF used to crash the whole /chat request with an
    unhandled exception; now it degrades to empty text and logs a visible
    "blocked" agent event instead."""
    events = []

    class RecordingStore:
        async def save_agent_event(self, session_id, agent, action):
            events.append((session_id, agent, action))

    async def fake_get_store():
        return RecordingStore()

    monkeypatch.setattr("storage.neon_store.get_store", fake_get_store)

    b64 = base64.b64encode(b"not a real pdf").decode()
    result = await _fold_attachments(
        "summarize", [{"name": "broken.pdf", "mime": "application/pdf", "base64": b64}], "sess1",
    )

    assert '<file name="broken.pdf">' in result
    assert len(events) == 1
    session_id, agent, action = events[0]
    assert session_id == "sess1"
    assert agent == "file"
    assert action.startswith("blocked:broken.pdf")


def test_is_image_checks_mime_prefix():
    assert _is_image({"mime": "image/png"}) is True
    assert _is_image({"mime": "application/pdf"}) is False
    assert _is_image({}) is False
