import re
from pathlib import Path


def test_every_video_image_can_import_the_module():
    src = Path(__file__).resolve().parents[1].joinpath("modal_app/video.py").read_text()
    assert "from fastapi import Request" in src
    images = re.findall(r"^(\w+_image) = (.*?)(?=^\S)", src, flags=re.M | re.S)
    assert {name for name, _ in images} >= {"gpu_image", "api_image", "stitch_image"}
    for name, body in images:
        assert "fastapi" in body, f"{name} can't import video.py (no fastapi)"


def test_quoted_words_lift_the_no_text_negative():
    import ast

    src = Path(__file__).resolve().parents[1].joinpath("modal_app/video.py").read_text()
    tree = ast.parse(src)
    ns = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("_NEGATIVE", "_NEGATIVE_WITH_TEXT"):
            exec(compile(ast.Module([node], []), "v", "exec"), ns)
        if isinstance(node, ast.FunctionDef) and node.name == "negative_for":
            exec(compile(ast.Module([node], []), "v", "exec"), ns)
    plain, named = ns["negative_for"]("a laptop opens"), ns["negative_for"]('the screen shows the word "VICINIC" in gold')
    assert "letters" in plain and "words" in plain
    assert "letters" not in named and "words" not in named and "字幕" not in named and "misspelled" in named
