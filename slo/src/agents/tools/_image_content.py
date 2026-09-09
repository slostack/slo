"""Detect image files and build LangChain multimodal content blocks for ``read``.

Both ``ChatAnthropic`` and ``ChatOpenAI`` accept the same content-block shape — a
list of dictionaries with a ``type`` key. Images are detected with Pillow magic-byte
sniffing, resized before base64 encoding, and paired with a compact history reference.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Literal, TypedDict

from PIL import Image, UnidentifiedImageError

__all__ = [
    "IMAGE_MAX_EDGE",
    "MAX_ENCODED_BYTES",
    "ImageContent",
    "ImageContentBlock",
    "ImageResizeResult",
    "ImageSource",
    "TextContentBlock",
]


IMAGE_MAX_EDGE: int = 1568
"""Maximum longest edge sent to a provider.

The standard-detail bound controls vision-token cost while preserving useful
screenshot and diagram detail. Raise to 2576 only for high-resolution provider
models when the higher vision-token cost is justified.
"""

MAX_ENCODED_BYTES: int = 5 * 1024 * 1024
"""Maximum inline base64 payload size accepted by the provider."""

SUPPORTED_FORMATS: dict[str, str] = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


class ImageSource(TypedDict):
    """Base64 source metadata in a multimodal image block."""

    type: Literal["base64"]
    media_type: str
    data: str


class ImageContentBlock(TypedDict):
    """Provider-compatible base64 image content block."""

    type: Literal["image"]
    source: ImageSource


class TextContentBlock(TypedDict):
    """Provider-compatible text content block."""

    type: Literal["text"]
    text: str


class ImageResizeResult(TypedDict):
    """Live image content and its compact durable history reference."""

    block: ImageContentBlock
    reference: str


class ImageContent:
    """Image detection, resizing, and multimodal content construction for ``read``."""

    @classmethod
    def is_image(cls, *, path: Path) -> bool:
        """Return whether ``path`` decodes as a supported image.

        WHAT: Inspects Pillow's recognized format without loading image pixels.
        WHO: Called by ``ReadTool`` as its cheap image gate before it dispatches
            to ``build_block``.

        Args:
            path (Path): Filesystem path to inspect.

        Returns:
            bool: True for supported JPEG, PNG, GIF, or WEBP input.
        """
        try:
            with Image.open(path) as image:
                return image.format in SUPPORTED_FORMATS
        except (UnidentifiedImageError, OSError):
            return False

    @classmethod
    def build_block(cls, *, path: Path) -> ImageResizeResult:
        """Build bounded live image content and a compact durable reference.

        WHAT: Reopens the image after ``is_image`` gates it, preserves small-file
            bytes verbatim, and resizes oversized inputs before base64 encoding.
        WHO: Called by ``ReadTool`` for supported image reads; its reference is
            threaded by the executor to history tracing.

        Args:
            path (Path): Filesystem path to a supported image.

        Returns:
            ImageResizeResult: Provider-ready image block and reference containing
                the original path and final dimensions.

        Raises:
            ValueError: If Pillow identifies an unsupported image format.
        """
        with Image.open(path) as image:
            pil_format: str = image.format or ""
            media_type: str | None = SUPPORTED_FORMATS.get(pil_format)
            if media_type is None:
                raise ValueError(f"Unsupported image format for {path}: {image.format}")

            raw, encode_image, width, height = cls._bytes_for_block(
                path=path,
                image=image,
                pil_format=pil_format,
            )
            encoded: str = base64.b64encode(raw).decode("ascii")
            if len(encoded) > MAX_ENCODED_BYTES:
                encoded, media_type = cls._lossy_fallback(image=encode_image)
                cls._validate_encoded_size(encoded=encoded)

        block: ImageContentBlock = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": encoded},
        }
        reference: str = f"[image attached: {path.name}, {width}x{height}, ref {path.resolve()}]"
        return {"block": block, "reference": reference}

    @classmethod
    def _bytes_for_block(
        cls,
        *,
        path: Path,
        image: Image.Image,
        pil_format: str,
    ) -> tuple[bytes, Image.Image, int, int]:
        """Return encode bytes, their source image, and final dimensions.

        WHAT: Preserves bytes for small images; otherwise mode-normalizes and
            re-encodes an edge-bounded image.
        WHO: Called only by ``build_block`` before it applies the encoded-size
            fallback, so the returned image must be the same resized object.

        Args:
            path (Path): Original file path for the byte-identical small path.
            image (Image.Image): Open Pillow image.
            pil_format (str): Pillow format used for the primary re-encode.

        Returns:
            tuple[bytes, Image.Image, int, int]: Encodable bytes, matching image,
                and its width and height.
        """
        if max(image.size) <= IMAGE_MAX_EDGE:
            return path.read_bytes(), image, image.size[0], image.size[1]

        encode_image: Image.Image = cls._normalized_image_for_resize(image=image)
        cls._resize_to_fit(image=encode_image, max_edge=IMAGE_MAX_EDGE)
        buffer: BytesIO = BytesIO()
        encode_image.save(buffer, format=pil_format)
        return buffer.getvalue(), encode_image, encode_image.size[0], encode_image.size[1]

    @classmethod
    def _normalized_image_for_resize(cls, *, image: Image.Image) -> Image.Image:
        """Normalize paletted images before their resize.

        WHAT: Converts ``P`` images to RGB or RGBA so Pillow can resample safely.
        WHO: Called by ``_bytes_for_block`` only for oversized images before the
            format-preserving re-encode.

        Args:
            image (Image.Image): Oversized source image.

        Returns:
            Image.Image: The original image or an independent true-color copy.
        """
        if image.mode != "P":
            return image
        if "transparency" in image.info:
            return image.convert("RGBA")
        return image.convert("RGB")

    @classmethod
    def _lossy_fallback(cls, *, image: Image.Image) -> tuple[str, str]:
        """Encode the already-bounded image as JPEG after a cap overflow.

        WHAT: Applies the one permitted lossy fallback to dense images whose
            primary base64 payload still exceeds ``MAX_ENCODED_BYTES``.
        WHO: Called by ``build_block`` after the primary encoded-size check.

        Args:
            image (Image.Image): Already resized image returned by ``_bytes_for_block``.

        Returns:
            tuple[str, str]: JPEG base64 payload and its media type.
        """
        buffer: BytesIO = BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=80)
        return base64.b64encode(buffer.getvalue()).decode("ascii"), "image/jpeg"

    @classmethod
    def _validate_encoded_size(cls, *, encoded: str) -> None:
        """Reject a fallback payload that remains larger than the provider cap.

        WHAT: Enforces the final ``MAX_ENCODED_BYTES`` invariant after the one
            permitted lossy JPEG fallback.
        WHO: Called by ``build_block`` immediately after ``_lossy_fallback``;
            callers receive the ValueError through the read tool's existing
            image-read error handling.

        Args:
            encoded (str): JPEG base64 data produced by the fallback.

        Raises:
            ValueError: If the single JPEG fallback cannot fit the encoded-size cap.
        """
        if len(encoded) > MAX_ENCODED_BYTES:
            raise ValueError(
                "Image JPEG fallback exceeds MAX_ENCODED_BYTES " f"({len(encoded)} > {MAX_ENCODED_BYTES})"
            )

    @classmethod
    def _resize_to_fit(cls, *, image: Image.Image, max_edge: int) -> None:
        """Shrink an image in place without upscaling or changing aspect ratio.

        WHAT: Applies Pillow's ``thumbnail`` bound.
        WHO: Called by ``_bytes_for_block`` for oversized normalized images.

        Args:
            image (Image.Image): Pillow image mutated in place.
            max_edge (int): Maximum permitted value for either dimension.
        """
        image.thumbnail(size=(max_edge, max_edge))
