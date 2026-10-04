import re
from pathlib import Path


def test_every_video_image_can_import_the_module():
    src = Path(__file__).resolve().parents[1].joinpath("modal_app/video.py").read_text()
    assert "from fastapi import Request" in src
    images = re.findall(r"^(\w+_image) = (.*?)(?=^\S)", src, flags=re.M | re.S)
    assert {name for name, _ in images} >= {"gpu_image", "api_image", "stitch_image"}
    for name, body in images:
        assert "fastapi" in body, f"{name} can't import video.py (no fastapi)"
