"""Image boundary, decode, and baseline detector tests."""

from pathlib import Path
import struct

import pytest

from img_ai_filter.baseline_detector import GeometryDetector
from img_ai_filter.detection import AnalysisFailure, DetectionError, SAFE_MAX_PIXELS


pytest.importorskip("PIL")

from PIL import Image  # noqa: E402


PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    import zlib

    payload = chunk_type + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload))


def _write_png(path: Path, width: int, height: int, mode: str = "RGB") -> Path:
    image = Image.new(mode, (width, height))
    image.save(path, format="PNG")
    return path


def test_baseline_returns_typed_failure_for_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.png"
    path.write_bytes(b"")

    result = GeometryDetector().analyze(path)

    assert isinstance(result, AnalysisFailure)
    assert result.kind == "decode"


def test_baseline_returns_typed_failure_for_truncated_image(tmp_path: Path) -> None:
    path = _write_png(tmp_path / "ok.png", 4, 4)
    data = path.read_bytes()
    truncated = tmp_path / "truncated.png"
    truncated.write_bytes(data[: len(data) // 2])

    result = GeometryDetector().analyze(truncated)

    assert isinstance(result, AnalysisFailure)
    assert result.kind == "decode"


def test_baseline_returns_typed_failure_for_wrong_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "not-really.png"
    path.write_bytes(b"this is not an image")

    result = GeometryDetector().analyze(path)

    assert isinstance(result, AnalysisFailure)
    assert result.kind == "decode"


def test_baseline_rejects_declared_pixel_dimensions_over_safe_limit(
    tmp_path: Path,
) -> None:
    width = height = int(SAFE_MAX_PIXELS**0.5) + 100
    huge = tmp_path / "huge.png"
    header = PNG_SIG
    header += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    header += _png_chunk(b"IEND", b"")
    huge.write_bytes(header)

    result = GeometryDetector().analyze(huge)

    assert isinstance(result, AnalysisFailure)
    assert result.kind == "decode-limit"


def test_baseline_handles_smallest_valid_image(tmp_path: Path) -> None:
    path = _write_png(tmp_path / "tiny.png", 1, 1)

    result = GeometryDetector().analyze(path)

    assert not isinstance(result, AnalysisFailure)


@pytest.mark.parametrize("mode", ["L", "RGB", "RGBA"])
def test_baseline_handles_grayscale_rgb_rgba(tmp_path: Path, mode: str) -> None:
    path = _write_png(tmp_path / f"{mode}.png", 8, 6, mode)

    result = GeometryDetector().analyze(path)

    assert not isinstance(result, AnalysisFailure)


@pytest.mark.parametrize(
    "width,height,orientation,expected_category",
    [
        (900, 1600, "portrait", "screenshot"),
        (1600, 900, "landscape", "screenshot"),
        (4000, 3000, "landscape", "ordinary"),
        (3000, 4000, "portrait", "ordinary"),
        (800, 800, "square", "screenshot"),
        (200, 6000, "very wide or tall", "ordinary"),
    ],
)
def test_baseline_flags_screen_like_geometry(
    tmp_path: Path,
    width: int,
    height: int,
    orientation: str,
    expected_category: str,
) -> None:
    path = _write_png(tmp_path / f"{width}x{height}-{orientation}.png", width, height)

    result = GeometryDetector().analyze(path)

    assert not isinstance(result, AnalysisFailure)
    assert (result.is_candidate, result.category) == (
        expected_category != "ordinary",
        expected_category,
    )
    assert 0.0 <= result.confidence <= 1.0


def test_baseline_does_not_follow_image_symlink(tmp_path: Path) -> None:
    real = _write_png(tmp_path / "real.png", 8, 8)
    link = tmp_path / "linked.png"
    try:
        link.symlink_to(real)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    result = GeometryDetector().analyze(link)

    assert isinstance(result, AnalysisFailure)
    assert result.kind == "symlink"


def test_baseline_does_not_mutate_image_bytes_or_exif(tmp_path: Path) -> None:
    path = _write_png(tmp_path / "original.png", 8, 8)
    before = path.read_bytes()
    before_stat = path.stat()

    GeometryDetector().analyze(path)
    GeometryDetector().analyze(path)

    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_stat.st_mtime_ns


def test_baseline_reason_is_observable_evidence_not_model_jargon(tmp_path: Path) -> None:
    path = _write_png(tmp_path / "screen.png", 900, 1600)

    result = GeometryDetector().analyze(path)

    assert not isinstance(result, AnalysisFailure)
    from img_ai_filter.detection import DetectionResult

    assert isinstance(result, DetectionResult)
    assert result.reason.lower() not in {"logits", "class_id", "tensor"}


def test_baseline_describe_reports_geometry_only_offline() -> None:
    facts = GeometryDetector.describe()

    assert facts["model_bytes"] == 0
    assert facts["offline"] is True
    assert "pillow" in str(facts.get("dependencies", "")).lower() or "dependencies" in facts