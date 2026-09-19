"""Read-only discovery of supported image files."""

from dataclasses import dataclass
import os
from pathlib import Path
import stat
from typing import TypeAlias


PathInput: TypeAlias = str | os.PathLike[str]
SUPPORTED_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})


class ScanError(ValueError):
    """A selected path cannot be scanned safely."""


@dataclass(frozen=True, slots=True)
class ScanResult:
    images: tuple[Path, ...]
    skipped_directories: tuple[Path, ...]


def _is_windows_reparse_point(path: Path) -> bool:
    if os.name != "nt":
        return False
    try:
        attributes = os.lstat(path).st_file_attributes
    except OSError:
        return True
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def scan_images(folder: PathInput) -> ScanResult:
    """Find supported images below folder without following symbolic links."""
    if isinstance(folder, str) and not folder.strip():
        raise ScanError("Select a folder before scanning.")

    root = Path(folder)
    if not root.exists():
        raise ScanError(f"Selected path does not exist: {root}")
    if root.is_symlink() or _is_windows_reparse_point(root) or not root.is_dir():
        raise ScanError(f"Selected path is not a folder: {root}")

    images: list[Path] = []
    skipped_directories: list[Path] = []
    pending = [root]

    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        path = Path(entry.path)
                        if _is_windows_reparse_point(path):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(path)
                        elif entry.is_file(follow_symlinks=False) and path.suffix.casefold() in SUPPORTED_EXTENSIONS:
                            images.append(path)
                    except OSError:
                        continue
        except OSError as error:
            if directory == root:
                raise ScanError(f"Cannot read selected folder: {error}") from error
            skipped_directories.append(directory)

    sort_key = lambda path: (str(path).casefold(), str(path))
    return ScanResult(
        images=tuple(sorted(images, key=sort_key)),
        skipped_directories=tuple(sorted(skipped_directories, key=sort_key)),
    )
