"""Detect image files and build LangChain multimodal content blocks for ``read``.

Both ``ChatAnthropic`` and ``ChatOpenAI`` accept the same content-block
shape — a list of dicts where each dict has a ``type`` key. The schema
this module emits is the Anthropic / OpenAI cross-compatible one.

We detect images by MIME magic bytes via ``PIL.Image.open`` so paths
without extensions still work. Sniffing the first few bytes is cheap and
avoids file-name spoofing.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Literal, TypedDict

from PIL import Image, UnidentifiedImageError


__all__ = [
    "ImageContent",
    "ImageContentBlock",
    "ImageSource",
    "TextContentBlock",
]


SUPPORTED_FORMATS: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


class ImageSource(TypedDict):
    type: Literal["base64"]
    media_type: str
    data: str


class ImageContentBlock(TypedDict):
    type: Literal["image"]
    source: ImageSource


class TextContentBlock(TypedDict):
    type: Literal["text"]
    text: str


class ImageContent:
    """Image detection and multimodal-content-block helpers for ``read``.

    Stateless namespace: all methods are classmethods. The class collects
    the two image primitives — sniffing format and emitting a base64
    Anthropic/OpenAI-compatible content block.
    """

    @classmethod
    def is_image(cls, *, path: Path) -> bool:
        """Return True iff ``path`` is one of the four supported image formats.

        Tries Pillow's ``Image.open`` and inspects the parsed format. Returns
        False on any decode failure — extensionless non-image files end up
        here.

        Args:
            path: Filesystem path to test.

        Returns:
            True iff the file decodes as JPEG/PNG/GIF/WEBP via Pillow.
        """
        try:
            with Image.open(path) as img:
                return img.format in SUPPORTED_FORMATS
        except (UnidentifiedImageError, OSError):
            return False

    @classmethod
    def build_block(cls, *, path: Path) -> ImageContentBlock:
        """Read ``path`` as bytes, base64-encode it, and return a content block.

        Args:
            path: Filesystem path to the image.

        Returns:
            An :class:`ImageContentBlock` suitable for direct inclusion in a
            LangChain multimodal content list.

        Raises:
            ValueError: If the file is not one of the four supported formats.
        """
        with Image.open(path) as img:
            media_type = SUPPORTED_FORMATS.get(img.format or "")
            if media_type is None:
                raise ValueError(f"Unsupported image format for {path}: {img.format}")

        raw = path.read_bytes()
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(raw).decode("ascii"),
            },
        }
