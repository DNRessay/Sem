import re
from pathlib import Path


def test_every_video_image_can_import_the_module():
    src = Path(__file__).resolve().parents[1].joinpath("modal_app/video.py").read_text()
    assert "from fastapi import Request" in src
    images = re.findall(r"^(\w+_image) = (.*?)(?=^\S)", src, flags=re.M | re.S)
    assert {name for name, _ in images} >= {"gpu_image", "api_image", "stitch_image", "music_image"}
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


def test_a_short_voiceover_is_slowed_gently_to_fill_the_video():
    import ast

    src = Path(__file__).resolve().parents[1].joinpath("modal_app/video.py").read_text()
    ns = {}
    for node in ast.parse(src).body:
        if (isinstance(node, ast.FunctionDef) and node.name == "voice_tempo") or \
                (isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") in ("VOICE_LEAD", "SLOWEST_VOICE")):
            exec(compile(ast.Module([node], []), "v", "exec"), ns)
    tempo = ns["voice_tempo"]
    assert tempo(13.0, 15.0) == round(13.0 / 14.0, 3)  # a little short: stretched to end just before the video
    assert tempo(8.0, 15.0) == 0.85  # far too short: never slower than 15%
    assert tempo(16.0, 15.0) == 1.0 and tempo(0, 15.0) == 1.0  # too long or unknown: left alone
