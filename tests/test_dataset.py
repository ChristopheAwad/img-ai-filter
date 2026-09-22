"""Dataset validation tests for the private local benchmark."""

import binascii
import inspect
import io
from pathlib import Path
import struct
import zlib

import pytest
from PIL import Image

from img_ai_filter.dataset import MINIMUM_LABELS, validate_dataset
from img_ai_filter.evaluation import ManifestError

HEADER = "path,label,split,source,license\n"


def _ramp(size: int = 64, kx: float = 1.0, ky: float = 0.0, offset: int = 0) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for x in range(size):
        for y in range(size):
            v = int((x * kx + y * ky) / (size - 1) * 204) + offset + 20
            px[x, y] = (v % 256, (v + 40) % 256, (v + 80) % 256)
    return img


def _noise(index: int, size: int = 32) -> Image.Image:
    img = Image.effect_noise((size, size), 60).convert("RGB")
    img.putpixel(
        (0, 0), ((index * 37) % 256, (index * 53) % 256, (index * 101) % 256)
    )
    return img


def _png_bytes(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()


def _write_png(root: Path, name: str, img: Image.Image) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    return path


def _write_jpeg(root: Path, name: str, img: Image.Image, quality: int = 55) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=quality)
    return path


def _write_oversized_png(path: Path, width: int, height: int) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        block = tag + data
        return (
            struct.pack(">I", len(data))
            + block
            + struct.pack(">I", binascii.crc32(block) & 0xFFFFFFFF)
        )

    row = b"\x00" + b"\x2a\x55\x8b" * width
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    compressor = zlib.compressobj(level=9)
    data = b"".join(compressor.compress(row) for _ in range(height))
    data += compressor.flush()
    out += chunk(b"IDAT", data)
    out += chunk(b"IEND", b"")
    path.write_bytes(bytes(out))


def _write_manifest(root: Path, rows: list[str]) -> Path:
    manifest_path = root / "manifest.csv"
    manifest_path.write_text(HEADER + "".join(rows), encoding="utf-8")
    return manifest_path


def _build_dataset(
    root: Path, overrides: dict[str, dict[str, int]] | None = None
) -> tuple[list[str], Path]:
    counts = {label: dict(MINIMUM_LABELS[label]) for label in MINIMUM_LABELS}
    if overrides:
        for label, sub in overrides.items():
            counts[label].update(sub)
    rows: list[str] = []
    index = 0
    for label in sorted(counts):
        for split in ("tuning", "holdout"):
            for _ in range(counts[label][split]):
                name = f"{label}-{split}-{index}.png"
                _write_png(root, name, _noise(index))
                rows.append(f"{name},{label},{split},test-source,local-test\n")
                index += 1
    return rows, _write_manifest(root, rows)


def test_accepts_the_exact_minimum_verified_dataset(tmp_path: Path) -> None:
    rows, manifest_path = _build_dataset(tmp_path)
    assert len(rows) == 310

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is True
    assert result.exploratory is False
    assert result.errors == ()


def test_rejects_one_below_minimum_count(tmp_path: Path) -> None:
    rows, manifest_path = _build_dataset(tmp_path)
    removed = next(row for row in rows if row.startswith("ordinary-holdout-"))
    rows.remove(removed)
    _write_manifest(tmp_path, rows)

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    assert result.exploratory is True
    joined = "\n".join(result.errors)
    assert "ordinary" in joined
    assert "holdout" in joined
    assert "44" in joined
    assert "45" in joined


def test_rejects_a_missing_required_label(tmp_path: Path) -> None:
    rows, manifest_path = _build_dataset(tmp_path)
    rows = [row for row in rows if not row.startswith("reaction_image-")]
    _write_manifest(tmp_path, rows)

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    joined = "\n".join(result.errors)
    assert "reaction_image" in joined
    assert "0" in joined


@pytest.mark.parametrize(
    "tuning_count,holdout_count,share_text",
    [
        (25, 15, "0.625"),
        (31, 9, "0.775"),
    ],
)
def test_rejects_tuning_share_outside_65_through_75(
    tmp_path: Path, tuning_count: int, holdout_count: int, share_text: str
) -> None:
    _, manifest_path = _build_dataset(
        tmp_path,
        {"comic": {"tuning": tuning_count, "holdout": holdout_count}},
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    assert any(share_text in error for error in result.errors)


def test_accepts_exact_65_and_75_percent_tuning_share_boundaries(
    tmp_path: Path,
) -> None:
    for share, tuning, holdout in [(0.65, 26, 14), (0.75, 30, 10)]:
        root = tmp_path / str(share)
        rows, manifest_path = _build_dataset(
            root, {"comic": {"tuning": tuning, "holdout": holdout}}
        )
        assert len(rows) == 310 - 25 + 40

        result = validate_dataset(root, manifest_path)

        assert result.valid is True, f"share {share}: {result.errors}"
        assert result.exploratory is False


def test_rejects_exact_duplicate_bytes_with_different_names_and_extensions(
    tmp_path: Path,
) -> None:
    base = _write_png(tmp_path, "a.png", _ramp())
    (tmp_path / "b.png").write_bytes(base.read_bytes())
    (tmp_path / "copy.jpg").write_bytes(base.read_bytes())
    manifest_path = _write_manifest(
        tmp_path,
        [
            "a.png,ordinary,tuning,test-source,local-test\n",
            "b.png,ordinary,tuning,test-source,local-test\n",
            "copy.jpg,ordinary,holdout,test-source,local-test\n",
        ],
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    joined = "\n".join(result.errors)
    assert "duplicate content" in joined
    assert "a.png" in joined
    assert "b.png" in joined
    assert "copy.jpg" in joined


def test_rejects_resized_image_copy_across_splits(tmp_path: Path) -> None:
    img = _ramp(size=64, kx=1.0)
    tuning = _write_png(tmp_path, "tuning/full.png", img)
    resized = img.resize((32, 32), Image.LANCZOS)
    holdout = _write_png(tmp_path, "holdout/small.png", resized)
    manifest_path = _write_manifest(
        tmp_path,
        [
            f"{tuning.relative_to(tmp_path)},screenshot,tuning,test-source,local-test\n",
            f"{holdout.relative_to(tmp_path)},screenshot,holdout,test-source,local-test\n",
        ],
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    joined = "\n".join(result.errors)
    assert "possible same-image copy" in joined
    assert "full.png" in joined
    assert "small.png" in joined


def test_rejects_recompressed_image_copy_across_splits(tmp_path: Path) -> None:
    img = _ramp(size=64, kx=1.0)
    png = _write_png(tmp_path, "tuning/original.png", img)
    jpg = _write_jpeg(tmp_path, "holdout/recompressed.jpg", img, quality=55)
    manifest_path = _write_manifest(
        tmp_path,
        [
            f"{png.relative_to(tmp_path)},screenshot,tuning,test-source,local-test\n",
            f"{jpg.relative_to(tmp_path)},screenshot,holdout,test-source,local-test\n",
        ],
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    joined = "\n".join(result.errors)
    assert "possible same-image copy" in joined
    assert "original.png" in joined
    assert "recompressed.jpg" in joined
    assert "tuning" in joined
    assert "holdout" in joined


def test_does_not_flag_unrelated_content_across_splits(tmp_path: Path) -> None:
    horizontal = _write_png(tmp_path, "tuning/horizontal.png", _ramp(kx=1.0))
    vertical = _write_png(tmp_path, "holdout/vertical.png", _ramp(kx=0.0, ky=1.0))
    manifest_path = _write_manifest(
        tmp_path,
        [
            f"{horizontal.relative_to(tmp_path)},screenshot,tuning,test-source,local-test\n",
            f"{vertical.relative_to(tmp_path)},screenshot,holdout,test-source,local-test\n",
        ],
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert not any("possible same-image copy" in error for error in result.errors)


@pytest.mark.parametrize(
    "content", [b"", b"\x89PNG\r\n\x1a\n", b"this is not an image at all"]
)
def test_rejects_image_that_cannot_be_decoded(
    tmp_path: Path, content: bytes
) -> None:
    broken = tmp_path / "broken.png"
    broken.write_bytes(content)
    manifest_path = _write_manifest(
        tmp_path,
        [f"{broken.name},ordinary,tuning,test-source,local-test\n"],
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    joined = "\n".join(result.errors)
    assert "cannot decode" in joined
    assert "broken.png" in joined


def test_rejects_extension_content_mismatch(tmp_path: Path) -> None:
    mismatched = tmp_path / "photo.jpg"
    mismatched.write_bytes(_png_bytes(_ramp(size=8)))
    manifest_path = _write_manifest(
        tmp_path,
        [f"{mismatched.name},ordinary,tuning,test-source,local-test\n"],
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    joined = "\n".join(result.errors)
    assert "format mismatch" in joined
    assert "photo.jpg" in joined


def test_rejects_oversized_pixel_image(tmp_path: Path) -> None:
    huge = tmp_path / "huge.png"
    _write_oversized_png(huge, 20000, 6000)
    manifest_path = _write_manifest(
        tmp_path, [f"{huge.name},ordinary,tuning,test-source,local-test\n"]
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    joined = "\n".join(result.errors)
    assert "oversized" in joined
    assert "cannot decode" not in joined


def test_valid_smallest_images_are_not_misreported_as_decode_failures(
    tmp_path: Path,
) -> None:
    Image.new("RGB", (1, 1), (9, 9, 9)).save(tmp_path / "tiny.png", "PNG")
    Image.new("RGB", (1, 1), (9, 9, 9)).save(tmp_path / "tiny.jpg", "JPEG")
    manifest_path = _write_manifest(
        tmp_path,
        [
            "tiny.png,ordinary,tuning,test-source,local-test\n",
            "tiny.jpg,ordinary,holdout,test-source,local-test\n",
        ],
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    joined = "\n".join(result.errors)
    assert "cannot decode" not in joined
    assert "format mismatch" not in joined
    assert "oversized" not in joined


def test_errors_use_relative_paths_and_never_include_image_bytes(
    tmp_path: Path,
) -> None:
    base = _write_png(tmp_path, "a.png", _ramp())
    (tmp_path / "b.png").write_bytes(base.read_bytes())
    manifest_path = _write_manifest(
        tmp_path,
        [
            "a.png,ordinary,tuning,test-source,local-test\n",
            "b.png,ordinary,tuning,test-source,local-test\n",
        ],
    )

    result = validate_dataset(tmp_path, manifest_path)

    joined = "\n".join(result.errors)
    assert b"\x89PNG" not in joined.encode()
    assert b"\x2a\x55\x8b" not in joined.encode()
    assert str(tmp_path) not in joined


def test_propagates_manifest_loader_rejections(tmp_path: Path) -> None:
    image = _write_png(tmp_path, "x.png", _ramp(size=8))
    manifest_path = _write_manifest(
        tmp_path,
        [
            f"{image.name},ordinary,tuning,test-source,local-test\n",
            f"{image.name},ordinary,tuning,test-source,local-test\n",
        ],
    )

    with pytest.raises(ManifestError, match="duplicate"):
        validate_dataset(tmp_path, manifest_path)


def test_propagates_blank_source_rejection(tmp_path: Path) -> None:
    image = _write_png(tmp_path, "x.png", _ramp(size=8))
    manifest_path = _write_manifest(
        tmp_path, [f"{image.name},ordinary,tuning,,local-test\n"]
    )

    with pytest.raises(ManifestError, match="source"):
        validate_dataset(tmp_path, manifest_path)


def test_keeps_an_incomplete_dataset_explicitly_exploratory(tmp_path: Path) -> None:
    image = _write_png(tmp_path, "one.png", _ramp(size=8))
    manifest_path = _write_manifest(
        tmp_path,
        [f"{image.name},ordinary,tuning,test-source,local-test\n"],
    )

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is False
    assert result.exploratory is True
    assert any("ordinary" in error and "tuning" in error for error in result.errors)


def test_dataset_validation_runs_without_network(tmp_path: Path, monkeypatch) -> None:
    def connect(*args, **kwargs):
        raise AssertionError("Network must not be contacted")

    monkeypatch.setattr("socket.create_connection", connect)

    rows, manifest_path = _build_dataset(tmp_path)

    result = validate_dataset(tmp_path, manifest_path)

    assert result.valid is True
    assert len(rows) == 310


def test_dataset_module_source_has_no_gui_dependency() -> None:
    import img_ai_filter.dataset as module

    source = inspect.getsource(module)
    assert "PySide6" not in source
    assert "PySide" not in source


def test_dataset_cli_reports_complete_dataset(
    tmp_path: Path, capsys
) -> None:
    from img_ai_filter.dataset_cli import main

    _, manifest_path = _build_dataset(tmp_path)

    code = main([str(tmp_path), str(manifest_path)])

    assert code == 0
    assert "dataset=valid" in capsys.readouterr().out.lower()


def test_dataset_cli_reports_exploratory_for_incomplete_dataset(
    tmp_path: Path, capsys
) -> None:
    from img_ai_filter.dataset_cli import main

    image = _write_png(tmp_path, "one.png", _ramp(size=8))
    manifest_path = _write_manifest(
        tmp_path,
        [f"{image.name},ordinary,tuning,test-source,local-test\n"],
    )

    code = main([str(tmp_path), str(manifest_path)])

    assert code == 1
    assert "exploratory" in capsys.readouterr().out.lower()


def test_dataset_cli_reports_missing_manifest_file(tmp_path: Path, capsys) -> None:
    from img_ai_filter.dataset_cli import main

    code = main([str(tmp_path), str(tmp_path / "missing.csv")])

    assert code == 1
    assert "cannot read" in capsys.readouterr().err.lower()
