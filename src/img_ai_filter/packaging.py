"""Application identity and Linux packaging metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import platform
import sys
import tomllib


APP_ID = "io.github.img_ai_filter.ImageFilter"


@dataclass(frozen=True)
class ArtifactNames:
    appimage: str
    tarball: str
    payload_directory: str


@dataclass(frozen=True)
class WindowsArtifactNames:
    installer: str
    portable_zip: str
    payload_directory: str


def project_version(pyproject_path: Path) -> str:
    """Read a non-empty string project version from pyproject.toml."""
    try:
        with pyproject_path.open("rb") as metadata:
            document = tomllib.load(metadata)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Unable to read pyproject.toml: {exc}") from exc

    project = document.get("project")
    version = project.get("version") if isinstance(project, dict) else None
    if not isinstance(version, str) or not version.strip():
        raise ValueError("pyproject.toml must define project.version as a non-empty string")
    return version


def artifact_names(
    version: str,
    *,
    system: str | None = None,
    machine: str | None = None,
) -> ArtifactNames:
    """Return release artifact names for the supported Linux target."""
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    if (system, machine) != ("Linux", "x86_64"):
        raise ValueError("Release artifacts support only Linux x86_64")

    stem = f"ImageFilter-{version}"
    payload_directory = f"{stem}-linux-x86_64"
    return ArtifactNames(
        appimage=f"{stem}-x86_64.AppImage",
        tarball=f"{payload_directory}.tar.gz",
        payload_directory=payload_directory,
    )


def windows_artifact_names(
    version: str,
    *,
    system: str | None = None,
    machine: str | None = None,
) -> WindowsArtifactNames:
    """Return release artifact names for the supported Windows target."""
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    if (system, machine) != ("Windows", "AMD64"):
        raise ValueError("Windows artifacts support only Windows x86_64")

    stem = f"ImageFilter-{version}"
    payload_directory = f"{stem}-windows-x86_64"
    return WindowsArtifactNames(
        installer=f"{payload_directory}-setup.exe",
        portable_zip=f"{payload_directory}.zip",
        payload_directory=payload_directory,
    )


def application_icon_path(*, resource_root: Path | None = None) -> Path | None:
    """Resolve the application icon in a source install or frozen bundle."""
    if resource_root is None:
        frozen_root = getattr(sys, "_MEIPASS", None)
        if frozen_root is None:
            icon = Path(__file__).resolve().parent / "resources" / f"{APP_ID}.svg"
        else:
            icon = Path(frozen_root) / "img_ai_filter" / "resources" / f"{APP_ID}.svg"
    else:
        icon = resource_root / "img_ai_filter" / "resources" / f"{APP_ID}.svg"
    return icon if icon.is_file() else None
