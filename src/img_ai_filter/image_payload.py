"""Bounded, read-only image preparation for vision requests."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
import os
from pathlib import Path
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from .scanner import SUPPORTED_EXTENSIONS


MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_ENCODED_PNG_BYTES = 8 * 1024 * 1024
SAFE_MAX_PIXELS = 100_000_000
MAX_DIMENSION = 1024
THUMBNAIL_MAX_EDGE = 96
MAX_THUMBNAIL_BYTES = 256 * 1024

_FORMATS_BY_EXTENSION = {
    ".png": "PNG",
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tif": "TIFF",
    ".tiff": "TIFF",
}


class ImagePayloadError(ValueError):
    """Raised when an image cannot safely be prepared for a request."""


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    byte_count: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PreparedImage:
    data_url: str
    png_bytes: int
    width: int
    height: int
    identity: SourceIdentity
    thumbnail_png: bytes
    thumbnail_width: int
    thumbnail_height: int


def _read_bounded(path: Path) -> bytes:
    try:
        if path.is_symlink():
            raise ImagePayloadError("Symbolic links are not supported")
        if not path.is_file():
            raise ImagePayloadError("The selected image is not a file")
        size = path.stat().st_size
        if size > MAX_INPUT_BYTES:
            raise ImagePayloadError("The image file is too large")
        with path.open("rb") as source:
            data = source.read(MAX_INPUT_BYTES + 1)
    except ImagePayloadError:
        raise
    except (OSError, ValueError, TypeError):
        raise ImagePayloadError("The selected image is not a readable file") from None

    if len(data) > MAX_INPUT_BYTES:
        raise ImagePayloadError("The image file is too large")
    return data


def _validate_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width < 1 or height < 1 or width * height > SAFE_MAX_PIXELS:
        raise ImagePayloadError("The image dimensions are not supported")


def _has_transparency(image: Image.Image) -> bool:
    return "A" in image.getbands() or "transparency" in image.info


def prepare_image(path: str | os.PathLike[str]) -> PreparedImage:
    """Decode and normalize one scanner-supported image entirely in memory."""
    try:
        source_path = Path(path)
        if source_path.is_symlink():
            raise ImagePayloadError("Symbolic links are not supported")
        if not source_path.is_file():
            raise ImagePayloadError("The selected image is not a file")
    except ImagePayloadError:
        raise
    except (TypeError, ValueError):
        raise ImagePayloadError("The selected image is not a file") from None
    except OSError:
        raise ImagePayloadError("The selected image is not a readable file") from None

    suffix = source_path.suffix.casefold()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ImagePayloadError("The image extension is not supported")

    source_bytes = _read_bounded(source_path)
    identity = SourceIdentity(len(source_bytes), hashlib.sha256(source_bytes).hexdigest())
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(BytesIO(source_bytes)) as opened:
                if opened.format != _FORMATS_BY_EXTENSION[suffix]:
                    raise ImagePayloadError("The image format does not match its extension")
                _validate_dimensions(opened)
                opened.load()
                transformed = ImageOps.exif_transpose(opened)
                _validate_dimensions(transformed)
                normalized = transformed.convert(
                    "RGBA" if _has_transparency(transformed) else "RGB"
                )
    except ImagePayloadError:
        raise
    except Image.DecompressionBombError:
        raise ImagePayloadError("The image dimensions are not supported") from None
    except (UnidentifiedImageError, OSError, ValueError):
        raise ImagePayloadError("The image could not be decoded") from None

    thumb = normalized
    tw, th = normalized.size
    if max(tw, th) > THUMBNAIL_MAX_EDGE:
        thumb_scale = THUMBNAIL_MAX_EDGE / max(tw, th)
        thumb_size = (
            max(1, round(tw * thumb_scale)),
            max(1, round(th * thumb_scale)),
        )
        thumb = normalized.resize(thumb_size, Image.Resampling.LANCZOS)

    thumb_output = BytesIO()
    try:
        thumb.save(thumb_output, format="PNG")
    except (OSError, ValueError):
        raise ImagePayloadError("The thumbnail could not be encoded") from None
    thumbnail_png = thumb_output.getvalue()
    if len(thumbnail_png) > MAX_THUMBNAIL_BYTES:
        raise ImagePayloadError("The thumbnail is too large")

    width, height = normalized.size
    if max(width, height) > MAX_DIMENSION:
        scale = MAX_DIMENSION / max(width, height)
        resized_size = (
            max(1, round(width * scale)),
            max(1, round(height * scale)),
        )
        normalized = normalized.resize(resized_size, Image.Resampling.LANCZOS)

    output = BytesIO()
    try:
        normalized.save(output, format="PNG")
    except (OSError, ValueError):
        raise ImagePayloadError("The image could not be encoded for the request") from None
    png = output.getvalue()
    if len(png) > MAX_ENCODED_PNG_BYTES:
        raise ImagePayloadError("The image is too large for the request")

    width, height = normalized.size
    encoded = base64.b64encode(png).decode("ascii")
    thumb_width, thumb_height = thumb.size
    return PreparedImage(
        data_url="data:image/png;base64," + encoded,
        png_bytes=len(png),
        width=width,
        height=height,
        identity=identity,
        thumbnail_png=thumbnail_png,
        thumbnail_width=thumb_width,
        thumbnail_height=thumb_height,
    )
