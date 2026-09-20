"""Bounded, read-only image preparation for KoboldCpp requests."""

from __future__ import annotations

import base64
import binascii
import inspect
import struct
from pathlib import Path
import zlib

from PIL import Image
import pytest

import img_ai_filter.image_payload as image_payload
from img_ai_filter.image_payload import ImagePayloadError, prepare_image


def _save(path: Path, image: Image.Image, format_name: str, **kwargs) -> Path:
    image.save(path, format_name, **kwargs)
    return path


def _decoded_png(data_url: str) -> Image.Image:
    prefix = "data:image/png;base64,"
    assert data_url.startswith(prefix)
    raw = base64.b64decode(data_url.removeprefix(prefix), validate=True)
    from io import BytesIO

    image = Image.open(BytesIO(raw))
    image.load()
    return image


@pytest.mark.parametrize(
    "suffix,format_name",
    [
        (".png", "PNG"),
        (".jpg", "JPEG"),
        (".jpeg", "JPEG"),
        (".webp", "WEBP"),
        (".bmp", "BMP"),
        (".tif", "TIFF"),
        (".tiff", "TIFF"),
    ],
)
def test_prepares_every_supported_format_as_in_memory_png(
    tmp_path: Path, suffix: str, format_name: str
) -> None:
    source = _save(
        tmp_path / f"source{suffix}",
        Image.new("RGB", (32, 20), (12, 34, 56)),
        format_name,
    )

    prepared = prepare_image(source)
    decoded = _decoded_png(prepared.data_url)

    assert prepared.width == 32
    assert prepared.height == 20
    assert prepared.png_bytes > 0
    assert decoded.format == "PNG"
    assert decoded.size == (32, 20)


@pytest.mark.parametrize("size", [(1, 1), (1024, 8), (8, 1024)])
def test_accepts_smallest_and_max_dimension_without_resizing(
    tmp_path: Path, size: tuple[int, int]
) -> None:
    source = _save(tmp_path / "source.png", Image.new("RGB", size), "PNG")

    prepared = prepare_image(source)

    assert (prepared.width, prepared.height) == size


@pytest.mark.parametrize(
    "source_size,expected",
    [
        ((1025, 100), (1024, 100)),
        ((100, 1025), (100, 1024)),
        ((2048, 1024), (1024, 512)),
        ((1024, 2048), (512, 1024)),
    ],
)
def test_resizes_long_edge_to_1024_preserving_aspect_ratio(
    tmp_path: Path,
    source_size: tuple[int, int],
    expected: tuple[int, int],
) -> None:
    source = _save(tmp_path / "source.png", Image.new("RGB", source_size), "PNG")

    prepared = prepare_image(source)

    assert (prepared.width, prepared.height) == expected
    assert _decoded_png(prepared.data_url).size == expected


def test_applies_exif_orientation_in_memory(tmp_path: Path) -> None:
    source = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (40, 20), (10, 20, 30)).save(source, "JPEG", exif=exif)

    prepared = prepare_image(source)

    assert (prepared.width, prepared.height) == (20, 40)
    assert _decoded_png(prepared.data_url).size == (20, 40)


def test_preserves_rgba_transparency(tmp_path: Path) -> None:
    source = _save(
        tmp_path / "alpha.png", Image.new("RGBA", (8, 8), (1, 2, 3, 0)), "PNG"
    )

    decoded = _decoded_png(prepare_image(source).data_url)

    assert decoded.mode == "RGBA"
    assert decoded.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize("content", [b"", b"not an image", b"\x89PNG\r\n\x1a\n"])
def test_rejects_empty_or_malformed_image(tmp_path: Path, content: bytes) -> None:
    source = tmp_path / "broken.png"
    source.write_bytes(content)

    with pytest.raises(ImagePayloadError, match="decoded"):
        prepare_image(source)


def test_rejects_extension_content_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "renamed.jpg"
    Image.new("RGB", (8, 8)).save(source, "PNG")

    with pytest.raises(ImagePayloadError, match="format"):
        prepare_image(source)


@pytest.mark.parametrize("name", ["file.gif", "file.txt", "file.heic"])
def test_rejects_unsupported_extension(tmp_path: Path, name: str) -> None:
    source = tmp_path / name
    source.write_bytes(b"content")

    with pytest.raises(ImagePayloadError, match="supported"):
        prepare_image(source)


def test_rejects_missing_file_and_directory(tmp_path: Path) -> None:
    with pytest.raises(ImagePayloadError, match="file"):
        prepare_image(tmp_path / "missing.png")
    with pytest.raises(ImagePayloadError, match="file"):
        prepare_image(tmp_path)


def test_rejects_symbolic_link(tmp_path: Path) -> None:
    source = _save(tmp_path / "source.png", Image.new("RGB", (8, 8)), "PNG")
    link = tmp_path / "link.png"
    try:
        link.symlink_to(source)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    with pytest.raises(ImagePayloadError, match="Symbolic"):
        prepare_image(link)


def test_rejects_raw_input_over_configured_limit(tmp_path: Path, monkeypatch) -> None:
    source = _save(tmp_path / "source.png", Image.effect_noise((64, 64), 50), "PNG")
    monkeypatch.setattr(image_payload, "MAX_INPUT_BYTES", source.stat().st_size - 1)

    with pytest.raises(ImagePayloadError, match="large"):
        prepare_image(source)


def test_accepts_raw_input_exactly_at_configured_limit(
    tmp_path: Path, monkeypatch
) -> None:
    source = _save(tmp_path / "source.png", Image.new("RGB", (8, 8)), "PNG")
    monkeypatch.setattr(image_payload, "MAX_INPUT_BYTES", source.stat().st_size)

    assert prepare_image(source).png_bytes > 0


def test_rejects_encoded_png_over_configured_limit(tmp_path: Path, monkeypatch) -> None:
    source = _save(tmp_path / "source.png", Image.effect_noise((64, 64), 50), "PNG")
    monkeypatch.setattr(image_payload, "MAX_ENCODED_PNG_BYTES", 10)

    with pytest.raises(ImagePayloadError, match="request"):
        prepare_image(source)


def test_pixel_limit_is_inclusive_and_rejects_one_pixel_over(
    tmp_path: Path, monkeypatch
) -> None:
    accepted = _save(tmp_path / "accepted.png", Image.new("RGB", (10, 10)), "PNG")
    rejected = _save(tmp_path / "rejected.png", Image.new("RGB", (101, 1)), "PNG")
    monkeypatch.setattr(image_payload, "SAFE_MAX_PIXELS", 100)

    assert prepare_image(accepted).png_bytes > 0
    with pytest.raises(ImagePayloadError, match="dimensions"):
        prepare_image(rejected)


def test_encoded_png_limit_is_inclusive(tmp_path: Path, monkeypatch) -> None:
    source = _save(tmp_path / "source.png", Image.new("RGB", (8, 8)), "PNG")
    baseline = prepare_image(source)
    monkeypatch.setattr(
        image_payload, "MAX_ENCODED_PNG_BYTES", baseline.png_bytes
    )

    assert prepare_image(source).png_bytes == baseline.png_bytes


def test_source_and_directory_are_unchanged_and_no_temp_file_is_written(
    tmp_path: Path,
) -> None:
    source = _save(tmp_path / "source.jpg", Image.new("RGB", (2048, 1024)), "JPEG")
    before_bytes = source.read_bytes()
    before_stat = source.stat()
    before_names = sorted(path.name for path in tmp_path.iterdir())

    prepare_image(source)

    assert source.read_bytes() == before_bytes
    assert source.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert source.stat().st_mode == before_stat.st_mode
    assert sorted(path.name for path in tmp_path.iterdir()) == before_names


def test_data_url_contains_only_valid_base64_png(tmp_path: Path) -> None:
    source = _save(tmp_path / "source.png", Image.new("RGB", (8, 8)), "PNG")

    prepared = prepare_image(source)
    encoded = prepared.data_url.split(",", 1)[1]
    raw = base64.b64decode(encoded, validate=True)

    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(raw) == prepared.png_bytes


def test_image_payload_has_no_gui_or_network_dependency() -> None:
    source = inspect.getsource(image_payload)
    assert "PySide" not in source
    assert "socket" not in source
    assert "http" not in source
