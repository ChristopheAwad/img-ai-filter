import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest

from img_ai_filter import scanner
from img_ai_filter.scanner import ScanError, scan_images


def touch_files(root: Path, names: list[str]) -> list[Path]:
    paths = [root / name for name in names]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return paths


def create_windows_junction(junction: Path, target: Path) -> None:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"Cannot create a Windows junction: {result.stderr.strip()}")


def test_empty_folder_returns_empty_result(tmp_path: Path) -> None:
    result = scan_images(tmp_path)

    assert result.images == ()
    assert result.skipped_directories == ()


def test_folder_with_only_unsupported_files_returns_empty_result(tmp_path: Path) -> None:
    touch_files(tmp_path, ["notes.txt", "archive.zip", "almost.png.bak"])

    assert scan_images(tmp_path).images == ()


def test_finds_all_supported_extensions_without_regard_to_case(tmp_path: Path) -> None:
    expected = touch_files(
        tmp_path,
        [
            "a.png",
            "b.JPG",
            "c.jpeg",
            "d.WeBp",
            "e.bmp",
            "f.TIF",
            "g.tiff",
        ],
    )

    assert scan_images(tmp_path).images == tuple(sorted(expected, key=lambda path: str(path).casefold()))


def test_finds_images_at_root_and_in_nested_folders(tmp_path: Path) -> None:
    expected = touch_files(tmp_path, ["root.png", "one/two/nested.jpg"])

    assert scan_images(tmp_path).images == tuple(sorted(expected, key=lambda path: str(path).casefold()))


def test_similar_unsupported_suffixes_are_excluded(tmp_path: Path) -> None:
    touch_files(tmp_path, ["image.png.txt", "image.jpeg-backup", "png"])

    assert scan_images(tmp_path).images == ()


def test_each_path_is_returned_once_in_stable_order(tmp_path: Path) -> None:
    expected = touch_files(tmp_path, ["z.png", "A.jpg", "middle.webp"])
    ordered = tuple(sorted(expected, key=lambda path: str(path).casefold()))

    assert scan_images(tmp_path).images == ordered
    assert scan_images(tmp_path).images == ordered
    assert len(set(ordered)) == len(ordered)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="Symbolic links are not supported")
def test_does_not_follow_directory_symlink_inside_tree(tmp_path: Path) -> None:
    real_folder = tmp_path / "real"
    expected = touch_files(real_folder, ["image.png"])
    link = tmp_path / "linked"
    try:
        link.symlink_to(real_folder, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    assert scan_images(tmp_path).images == tuple(expected)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="Symbolic links are not supported")
def test_does_not_follow_directory_symlink_outside_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    touch_files(outside, ["private.png"])
    try:
        (source / "linked").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    assert scan_images(source).images == ()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="Symbolic links are not supported")
def test_does_not_include_image_symlinks(tmp_path: Path) -> None:
    original = touch_files(tmp_path, ["original.png"])[0]
    try:
        (tmp_path / "copy.png").symlink_to(original)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    assert scan_images(tmp_path).images == (original,)


def test_windows_reparse_attribute_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reparse_stat = SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
    monkeypatch.setattr(scanner.os, "name", "nt")
    monkeypatch.setattr(scanner.os, "lstat", lambda path: reparse_stat)

    assert scanner._is_windows_reparse_point(tmp_path)


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions are only available on Windows")
def test_does_not_follow_windows_junction_outside_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    outside = tmp_path / "outside"
    source.mkdir()
    touch_files(outside, ["private.png"])
    junction = source / "linked"
    create_windows_junction(junction, outside)

    assert scan_images(source).images == ()


@pytest.mark.skipif(os.name != "nt", reason="Windows junctions are only available on Windows")
def test_rejects_windows_junction_as_selected_root(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    junction = tmp_path / "selected"
    create_windows_junction(junction, target)

    with pytest.raises(ScanError, match="not a folder"):
        scan_images(junction)


def test_missing_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ScanError, match="does not exist"):
        scan_images(tmp_path / "missing")


def test_file_path_is_rejected(tmp_path: Path) -> None:
    file_path = touch_files(tmp_path, ["image.png"])[0]

    with pytest.raises(ScanError, match="not a folder"):
        scan_images(file_path)


@pytest.mark.parametrize("empty_path", ["", "   "])
def test_empty_path_is_rejected_without_scanning_current_directory(empty_path: str) -> None:
    with pytest.raises(ScanError, match="Select a folder"):
        scan_images(empty_path)


def test_unreadable_root_reports_clear_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_access(path: os.PathLike[str]) -> None:
        raise PermissionError("access denied")

    monkeypatch.setattr(scanner.os, "scandir", deny_access)

    with pytest.raises(ScanError, match="Cannot read selected folder"):
        scan_images(tmp_path)


def test_unreadable_nested_folder_is_skipped_and_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readable_image = touch_files(tmp_path, ["readable.png"])[0]
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    real_scandir = os.scandir

    def deny_nested(path: os.PathLike[str]):
        if Path(path) == blocked:
            raise PermissionError("access denied")
        return real_scandir(path)

    monkeypatch.setattr(scanner.os, "scandir", deny_nested)

    result = scan_images(tmp_path)

    assert result.images == (readable_image,)
    assert result.skipped_directories == (blocked,)
