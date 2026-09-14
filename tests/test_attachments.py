from gateway.router import _fold_attachments


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
