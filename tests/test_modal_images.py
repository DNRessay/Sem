import re
from pathlib import Path


def test_every_video_image_can_import_the_module():
    src = Path(__file__).resolve().parents[1].joinpath("modal_app/video.py").read_text()
    assert "from fastapi import Request" in src
    images = re.findall(r"^(\w+_image) = (.*?)(?=^\S)", src, flags=re.M | re.S)
    assert {name for name, _ in images} >= {"gpu_image", "api_image", "stitch_image", "music_image"}
    for name, body in images:
        assert "fastapi" in body, f"{name} can't import video.py (no fastapi)"


def test_the_negative_keeps_text_out_and_blocks_bad_anatomy():
    src = Path(__file__).resolve().parents[1].joinpath("modal_app/video.py").read_text()
    negative = src[src.index("_NEGATIVE = ("):src.index("# Wan can't spell")]
    for banned in ("text", "letters", "extra arms", "extra hands", "extra fingers", "motion blur"):
        assert banned in negative
    assert "negative_prompt=_NEGATIVE" in src


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
