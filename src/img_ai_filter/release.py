"""Validate release tags against the packaged application version."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re

from packaging.version import InvalidVersion, Version

from .packaging import project_version


_RELEASE_TAG = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:b(?:[1-9]\d*))?\Z")


class ReleaseValidationError(ValueError):
    """Raised when a tag cannot safely identify this project release."""


@dataclass(frozen=True)
class ValidatedRelease:
    version: Version
    prerelease: bool


def validate_release_tag(tag: str, pyproject_path: Path) -> ValidatedRelease:
    """Return validated release data for an exact canonical stable or beta tag."""
    if not isinstance(tag, str) or _RELEASE_TAG.fullmatch(tag) is None:
        raise ReleaseValidationError(
            "Release tag must be canonical vMAJOR.MINOR.PATCH or vMAJOR.MINOR.PATCHbN"
        )

    tag_version_text = tag[1:]
    try:
        metadata_version_text = project_version(pyproject_path)
        tag_version = Version(tag_version_text)
        metadata_version = Version(metadata_version_text)
    except (ValueError, InvalidVersion) as exc:
        raise ReleaseValidationError(f"Invalid project release version: {exc}") from exc

    if str(tag_version) != tag_version_text:
        raise ReleaseValidationError("Release tag version is not canonical")
    if str(metadata_version) != metadata_version_text:
        raise ReleaseValidationError("Project version is not canonical")
    if tag_version != metadata_version:
        raise ReleaseValidationError(
            f"Release tag {tag!r} does not match project version {metadata_version_text!r}"
        )

    return ValidatedRelease(version=tag_version, prerelease=tag_version.is_prerelease)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("pyproject", type=Path)
    args = parser.parse_args()
    try:
        release = validate_release_tag(args.tag, args.pyproject)
    except ReleaseValidationError as exc:
        parser.exit(1, f"Release validation failed: {exc}\n")
    print(f"version={release.version}")
    print(f"prerelease={'true' if release.prerelease else 'false'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
