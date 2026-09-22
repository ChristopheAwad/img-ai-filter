"""Validate and assemble portable Linux release artifacts."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import stat
import tarfile
from typing import Iterable


class ArtifactValidationError(ValueError):
    """The frozen application payload is incomplete or unsafe."""


_REQUIRED_FILES = (
    Path("image-filter"),
    Path("_internal/img_ai_filter/resources/io.github.img_ai_filter.ImageFilter.svg"),
    Path("README.txt"),
    Path("THIRD_PARTY_NOTICES.txt"),
)
_FORBIDDEN_NAMES = {".git"}


def validate_payload(payload: Path) -> None:
    """Validate required payload content and contained symbolic links."""
    payload = Path(payload)
    if payload.is_symlink() or not payload.is_dir():
        raise ArtifactValidationError(f"Missing payload directory: {payload}")

    payload_root = payload.resolve(strict=True)

    for current, directory_names, file_names in os.walk(payload, followlinks=False):
        current_path = Path(current)
        for name in directory_names + file_names:
            candidate = current_path / name
            relative = candidate.relative_to(payload)
            if name in _FORBIDDEN_NAMES:
                raise ArtifactValidationError(f"Payload contains forbidden content: {relative}")
            if candidate.is_symlink():
                target = Path(os.readlink(candidate))
                if target.is_absolute():
                    raise ArtifactValidationError(
                        f"Payload contains an unsafe symbolic link: {relative}"
                    )
                try:
                    resolved = candidate.resolve(strict=True)
                    resolved.relative_to(payload_root)
                except (OSError, RuntimeError, ValueError):
                    raise ArtifactValidationError(
                        f"Payload contains an unsafe symbolic link: {relative}"
                    ) from None

    for required in _REQUIRED_FILES:
        candidate = payload / required
        if not candidate.is_file():
            raise ArtifactValidationError(f"Missing required file: {required}")

    launcher_mode = (payload / "image-filter").stat(follow_symlinks=False).st_mode
    if not launcher_mode & stat.S_IXUSR:
        raise ArtifactValidationError("The image-filter launcher must be executable")



def prepare_appdir(payload: Path, appdir: Path, packaging_dir: Path) -> None:
    """Replace a dedicated AppDir and populate standard AppImage locations."""
    payload = Path(payload)
    appdir = Path(appdir)
    packaging_dir = Path(packaging_dir)
    validate_payload(payload)

    if appdir.is_symlink():
        raise ValueError("AppDir must not be a symbolic link")
    appdir_parent = appdir.parent.resolve(strict=True)
    appdir_path = appdir_parent / appdir.name
    if not appdir.name or appdir.name in {".", ".."} or appdir_path == appdir_parent:
        raise ValueError("AppDir must be a dedicated child directory")
    for protected in (payload.resolve(strict=True), packaging_dir.resolve(strict=True)):
        if (
            appdir_path == protected
            or appdir_path in protected.parents
            or protected in appdir_path.parents
        ):
            raise ValueError("AppDir must not replace a source directory")

    app_id = "io.github.img_ai_filter.ImageFilter"
    desktop = packaging_dir / f"{app_id}.desktop"
    metainfo = packaging_dir / f"{app_id}.metainfo.xml"
    icon = payload / "_internal/img_ai_filter/resources" / f"{app_id}.svg"
    copies = (
        (packaging_dir / "AppRun", appdir / "AppRun"),
        (desktop, appdir / desktop.name),
        (desktop, appdir / "usr/share/applications" / desktop.name),
        (metainfo, appdir / "usr/share/metainfo" / f"{app_id}.appdata.xml"),
        (icon, appdir / f"{app_id}.svg"),
        (icon, appdir / "usr/share/icons/hicolor/scalable/apps" / f"{app_id}.svg"),
    )
    for source, _ in copies:
        if not source.is_file():
            raise ValueError(f"Missing AppDir input: {source}")

    if appdir.exists():
        if not appdir.is_dir():
            raise ValueError("AppDir path must be a directory")
        shutil.rmtree(appdir)

    appdir.mkdir()
    shutil.copytree(payload, appdir / "usr/bin", symlinks=True)
    for source, destination in copies:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def create_tarball(payload: Path, output: Path, root_name: str) -> None:
    """Create a gzip tar archive below one validated top-level directory."""
    root = Path(root_name)
    if (
        not root_name
        or root_name in {".", ".."}
        or root.is_absolute()
        or len(root.parts) != 1
        or "/" in root_name
        or "\\" in root_name
    ):
        raise ValueError("root name must be one safe relative path component")

    payload = Path(payload)
    output = Path(output)
    validate_payload(payload)
    try:
        output.resolve(strict=False).relative_to(payload.resolve(strict=True))
    except ValueError:
        pass
    else:
        raise ValueError("tarball output must be outside the payload root")

    with tarfile.open(output, "w:gz", dereference=False) as archive:
        archive.add(payload, arcname=root_name, recursive=True)


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
