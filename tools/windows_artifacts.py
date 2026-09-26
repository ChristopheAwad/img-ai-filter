"""Validate and assemble portable Windows release artifacts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import zipfile
from typing import Iterable


class WindowsArtifactValidationError(ValueError):
    """The frozen Windows application payload is incomplete or unsafe."""


_REQUIRED_FILES = (
    Path("image-filter.exe"),
    Path("_internal/img_ai_filter/resources/io.github.img_ai_filter.ImageFilter.svg"),
    Path("_internal/certifi/cacert.pem"),
    Path("README.txt"),
    Path("THIRD_PARTY_NOTICES.txt"),
)
_FORBIDDEN_NAMES = {".git"}
_LAUNCHER = Path("image-filter.exe")


def validate_windows_payload(payload: Path) -> None:
    """Validate required payload content and contained symbolic links."""
    payload = Path(payload)
    if payload.is_symlink() or not payload.is_dir():
        raise WindowsArtifactValidationError(f"Missing payload directory: {payload}")

    payload_root = payload.resolve(strict=True)

    for current, directory_names, file_names in os.walk(payload, followlinks=False):
        current_path = Path(current)
        for name in directory_names + file_names:
            candidate = current_path / name
            relative = candidate.relative_to(payload)
            if name in _FORBIDDEN_NAMES:
                raise WindowsArtifactValidationError(
                    f"Payload contains forbidden content: {relative}"
                )
            if candidate.is_symlink():
                target = Path(os.readlink(candidate))
                if target.is_absolute():
                    raise WindowsArtifactValidationError(
                        f"Payload contains an unsafe symbolic link: {relative}"
                    )
                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(payload_root)
                except (OSError, RuntimeError, ValueError):
                    raise WindowsArtifactValidationError(
                        f"Payload contains an unsafe symbolic link: {relative}"
                    ) from None

    for required in _REQUIRED_FILES:
        if not (payload / required).exists():
            raise WindowsArtifactValidationError(f"Missing required file: {required}")

    launcher = payload / _LAUNCHER
    if launcher.is_symlink() or not launcher.is_file():
        raise WindowsArtifactValidationError(
            f"The {_LAUNCHER} launcher must be a regular file"
        )


def create_windows_portable_zip(payload: Path, output: Path, root_name: str) -> None:
    """Create a deflated ZIP below one validated top-level directory."""
    root = Path(root_name)
    if (
        not root_name
        or root_name in {".", ".."}
        or root.is_absolute()
        or len(root.parts) != 1
        or "/" in root_name
        or "\\" in root_name
        or ":" in root_name
    ):
        raise ValueError("root name must be one safe relative path component")

    payload = Path(payload)
    output = Path(output)
    validate_windows_payload(payload)
    try:
        output.resolve(strict=False).relative_to(payload.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ValueError("ZIP output must be outside the payload root")

    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for current, _, file_names in os.walk(payload):
            current_path = Path(current)
            for name in sorted(file_names):
                source = current_path / name
                relative = source.relative_to(payload)
                archive.write(
                    source, arcname=f"{root_name}/{relative.as_posix()}"
                )


def write_checksums(artifacts: Iterable[Path], output: Path) -> None:
    """Write sorted SHA-256 entries using artifact basenames only."""
    paths = [Path(artifact) for artifact in artifacts]
    names = [path.name for path in paths]
    if len(names) != len(set(names)):
        raise ValueError("duplicate artifact file name")

    entries: list[tuple[str, str]] = []
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"artifact must be a regular file: {path}")
        digest = hashlib.sha256()
        with path.open("rb") as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                digest.update(chunk)
        entries.append((path.name, digest.hexdigest()))

    contents = "".join(
        f"{digest}  {name}\n" for name, digest in sorted(entries)
    )
    Path(output).write_text(contents, encoding="ascii")
