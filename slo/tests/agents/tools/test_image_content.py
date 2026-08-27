"""Tests for image-content resize and reference generation."""
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from src.agents.tools._image_content import (
    IMAGE_MAX_EDGE,
    MAX_ENCODED_BYTES,
    ImageContent,
)


@pytest.fixture
def png_path(tmp_path: Path) -> Path:
    """Create a small PNG consumed by image-content tests."""
    path: Path = tmp_path / "tiny.png"
    Image.new("RGB", (1, 1), color="red").save(path, format="PNG")
    return path


@pytest.fixture
def text_path(tmp_path: Path) -> Path:
    """Create a text file rejected by image-content helpers."""
    path: Path = tmp_path / "notes.txt"
    path.write_text("hello")
    return path


def test_looks_like_image_recognises_png(png_path: Path) -> None:
    """is_image returns true when Pillow identifies a supported PNG."""
    assert ImageContent.is_image(path=png_path) is True


def test_looks_like_image_rejects_text(text_path: Path) -> None:
    """is_image returns false when Pillow cannot decode a text file."""
    assert ImageContent.is_image(path=text_path) is False


def test_build_image_content_block_shape(png_path: Path) -> None:
    """build_block returns a valid base64 image block within its result."""
    result = ImageContent.build_block(path=png_path)
    block = result["block"]
    assert block["type"] == "image"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "image/png"
    base64.b64decode(block["source"]["data"])


def test_build_image_content_block_rejects_non_image(text_path: Path) -> None:
    """build_block raises when the caller supplies an unsupported image type."""
    with pytest.raises((ValueError, Image.UnidentifiedImageError)):
        ImageContent.build_block(path=text_path)


def test_build_block_returns_image_resize_result(png_path: Path) -> None:
    """build_block supplies both live content and durable-reference data."""
    result = ImageContent.build_block(path=png_path)
    assert set(result) == {"block", "reference"}


def test_build_block_reference_contains_filename_dimensions_and_path(tmp_path: Path) -> None:
    """build_block describes the original name and final dimensions in its reference."""
    path: Path = tmp_path / "myimage.png"
    Image.new("RGB", (100, 80), color="green").save(path, format="PNG")

    result = ImageContent.build_block(path=path)

    assert "myimage.png" in result["reference"]
    assert "100x80" in result["reference"]
    assert str(path.resolve()) in result["reference"]


def test_build_block_resizes_large_image(tmp_path: Path) -> None:
    """build_block bounds the image the provider receives by IMAGE_MAX_EDGE."""
    path: Path = tmp_path / "large.png"
    Image.new("RGB", (3000, 2000), color="red").save(path, format="PNG")

    result = ImageContent.build_block(path=path)
    decoded: bytes = base64.b64decode(result["block"]["source"]["data"])

    with Image.open(BytesIO(decoded)) as output_image:
        assert max(output_image.size) <= IMAGE_MAX_EDGE


def test_build_block_does_not_upscale_or_reencode_small_image(tmp_path: Path) -> None:
    """build_block retains the dimensions and exact bytes of a small image."""
    path: Path = tmp_path / "small.png"
    Image.new("RGB", (100, 80), color="yellow").save(path, format="PNG")
    original_bytes: bytes = path.read_bytes()

    result = ImageContent.build_block(path=path)
    decoded: bytes = base64.b64decode(result["block"]["source"]["data"])

    with Image.open(BytesIO(decoded)) as output_image:
        assert output_image.size == (100, 80)
    assert decoded == original_bytes


def test_build_block_preserves_aspect_ratio_when_resizing(tmp_path: Path) -> None:
    """build_block preserves aspect ratio while shrinking an oversized image."""
    path: Path = tmp_path / "wide.png"
    Image.new("RGB", (3000, 1000), color="cyan").save(path, format="PNG")

    result = ImageContent.build_block(path=path)
    decoded: bytes = base64.b64decode(result["block"]["source"]["data"])

    with Image.open(BytesIO(decoded)) as output_image:
        width, height = output_image.size
    assert width <= IMAGE_MAX_EDGE
    assert abs(width / height - 3.0) < 0.01


def test_build_block_resizes_rgba_png(tmp_path: Path) -> None:
    """build_block resizes a screenshot-like RGBA PNG without conversion failure."""
    path: Path = tmp_path / "rgba.png"
    Image.new("RGBA", (3000, 2000), (255, 0, 0, 128)).save(path, format="PNG")

    result = ImageContent.build_block(path=path)
    decoded: bytes = base64.b64decode(result["block"]["source"]["data"])

    with Image.open(BytesIO(decoded)) as output_image:
        assert max(output_image.size) <= IMAGE_MAX_EDGE


def test_build_block_resizes_paletted_gif(tmp_path: Path) -> None:
    """build_block resizes a paletted GIF without a resample or save error."""
    path: Path = tmp_path / "big.gif"
    Image.new("P", (3000, 2000)).save(path, format="GIF")

    result = ImageContent.build_block(path=path)
    decoded: bytes = base64.b64decode(result["block"]["source"]["data"])

    with Image.open(BytesIO(decoded)) as output_image:
        assert max(output_image.size) <= IMAGE_MAX_EDGE


def test_build_block_keeps_dense_image_base64_data_under_cap(tmp_path: Path) -> None:
    """build_block bounds the final base64 data, not merely decoded bytes."""
    path: Path = tmp_path / "dense.png"
    Image.effect_noise((2000, 2000), 128).convert("RGB").save(path, format="PNG")

    result = ImageContent.build_block(path=path)
    data: str = result["block"]["source"]["data"]

    assert len(data) <= MAX_ENCODED_BYTES


def test_build_block_uses_lossy_fallback_within_feasible_restrictive_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_block keeps its final JPEG base64 data within a feasible lowered cap."""
    import src.agents.tools._image_content as image_content_module

    monkeypatch.setattr(image_content_module, "MAX_ENCODED_BYTES", 1_500_000)
    path: Path = tmp_path / "dense.png"
    Image.effect_noise((3000, 2000), 128).convert("RGB").save(path, format="PNG")

    result = ImageContent.build_block(path=path)
    data: str = result["block"]["source"]["data"]
    decoded: bytes = base64.b64decode(data)

    assert result["block"]["source"]["media_type"] == "image/jpeg"
    assert len(data) <= 1_500_000
    with Image.open(BytesIO(decoded)) as output_image:
        assert output_image.format == "JPEG"
        assert max(output_image.size) <= IMAGE_MAX_EDGE


def test_build_block_raises_when_lossy_fallback_exceeds_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_block rejects an image when its one permitted fallback cannot fit the cap."""
    import src.agents.tools._image_content as image_content_module

    monkeypatch.setattr(image_content_module, "MAX_ENCODED_BYTES", 100_000)
    path: Path = tmp_path / "dense.png"
    Image.effect_noise((3000, 2000), 128).convert("RGB").save(path, format="PNG")

    with pytest.raises(ValueError, match="JPEG fallback"):
        ImageContent.build_block(path=path)
