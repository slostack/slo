"""Tests for ``src.agents.tools._image_content`` (sub-spec 01.c §5.3)."""
import base64
from pathlib import Path

import pytest
from PIL import Image

from src.agents.tools._image_content import ImageContent


@pytest.fixture
def png_path(tmp_path: Path):
    path = tmp_path / "tiny.png"
    img = Image.new("RGB", (1, 1), color="red")
    img.save(path, format="PNG")
    return path


@pytest.fixture
def text_path(tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    return path


def test_looks_like_image_recognises_png(png_path: Path) -> None:
    assert ImageContent.is_image(path=png_path) is True


def test_looks_like_image_rejects_text(text_path: Path) -> None:
    assert ImageContent.is_image(path=text_path) is False


def test_build_image_content_block_shape(png_path: Path) -> None:
    block = ImageContent.build_block(path=png_path)
    assert block["type"] == "image"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "image/png"
    base64.b64decode(block["source"]["data"])


def test_build_image_content_block_rejects_non_image(text_path: Path) -> None:
    with pytest.raises(Exception):
        ImageContent.build_block(path=text_path)
