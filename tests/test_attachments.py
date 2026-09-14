import base64
import io

from gateway.router import _fold_attachments, _is_image


def test_fold_attachments_returns_message_unchanged_when_empty():
    assert _fold_attachments("hello", []) == "hello"
    assert _fold_attachments("hello", None) == "hello"


def test_fold_attachments_appends_fenced_file_blocks():
    result = _fold_attachments("check this file", [{"name": "app.py", "content": "print('hi')"}])
    assert result.startswith("check this file\n\n<attachments>")
    assert '<file name="app.py">' in result
    assert "print('hi')" in result
    assert result.endswith("</attachments>")


def test_fold_attachments_handles_multiple_files():
    result = _fold_attachments("msg", [
        {"name": "a.py", "content": "A"},
        {"name": "b.py", "content": "B"},
    ])
    assert result.count("<file name=") == 2
    assert "a.py" in result and "b.py" in result


def test_fold_attachments_extracts_text_from_base64_pdf():
    from pypdf import PdfWriter

    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    result = _fold_attachments("summarize", [{"name": "doc.pdf", "mime": "application/pdf", "base64": b64}])
    assert '<file name="doc.pdf">' in result  # a blank page extracts to empty text, but shouldn't raise


def test_fold_attachments_extracts_text_from_base64_docx():
    import docx

    buf = io.BytesIO()
    document = docx.Document()
    document.add_paragraph("Hello from a Word doc")
    document.save(buf)
    b64 = base64.b64encode(buf.getvalue()).decode()

    result = _fold_attachments("summarize", [{"name": "doc.docx", "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "base64": b64}])
    assert "Hello from a Word doc" in result


def test_is_image_checks_mime_prefix():
    assert _is_image({"mime": "image/png"}) is True
    assert _is_image({"mime": "application/pdf"}) is False
    assert _is_image({}) is False
