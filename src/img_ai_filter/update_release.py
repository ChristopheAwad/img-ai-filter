"""Strict, GUI-neutral selection of compatible GitHub update releases."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.parse import urlsplit

from packaging.version import InvalidVersion, Version

from img_ai_filter.packaging import artifact_names


MAX_METADATA_BYTES = 1_000_000
MAX_APPIMAGE_BYTES = 2_000_000_000
_MAX_NOTES_CHARS = 20_000
_NOTES_SUFFIX = "\n[Release notes truncated]"
_SHA256 = re.compile(r"sha256:([0-9a-f]{64})\Z")


class UpdateMetadataError(ValueError):
    """Release metadata or local version information is invalid."""


@dataclass(frozen=True, slots=True)
class UpdateAsset:
    """Validated AppImage asset needed by a selected release."""

    name: str
    size: int
    url: str
    sha256: str


@dataclass(frozen=True, slots=True)
class UpdateRelease:
    """Validated release selected as an available update."""

    version: Version
    prerelease: bool
    notes: str
    asset: UpdateAsset


def _canonical_version(value: object, *, prefixed: bool) -> Version:
    if not isinstance(value, str):
        raise UpdateMetadataError("Version must be text")
    raw = value[1:] if prefixed and value.startswith("v") else value
    if prefixed and not value.startswith("v"):
        raise UpdateMetadataError("Release tag must start with v")
    try:
        version = Version(raw)
    except InvalidVersion as exc:
        raise UpdateMetadataError("Version is invalid") from exc
    if version.local is not None or raw != str(version):
        raise UpdateMetadataError("Version is not canonical")
    return version


def _asset(document: object, expected_name: str) -> UpdateAsset:
    if not isinstance(document, dict):
        raise UpdateMetadataError("Asset must be an object")
    name = document.get("name")
    size = document.get("size")
    url = document.get("browser_download_url")
    digest = document.get("digest")
    if name != expected_name:
        raise UpdateMetadataError("Release has no compatible AppImage")
    if type(size) is not int or not 0 < size <= MAX_APPIMAGE_BYTES:
        raise UpdateMetadataError("AppImage size is invalid")
    if not isinstance(url, str):
        raise UpdateMetadataError("AppImage URL is invalid")
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise UpdateMetadataError("AppImage URL is invalid")
    match = _SHA256.fullmatch(digest) if isinstance(digest, str) else None
    if match is None:
        raise UpdateMetadataError("AppImage digest is invalid")
    return UpdateAsset(name=name, size=size, url=url, sha256=match.group(1))


def _release(document: object) -> UpdateRelease | None:
    if not isinstance(document, dict):
        raise UpdateMetadataError("Release must be an object")
    release_id = document.get("id")
    draft = document.get("draft")
    prerelease = document.get("prerelease")
    assets = document.get("assets")
    notes = document.get("body")
    if type(release_id) is not int or type(draft) is not bool or type(prerelease) is not bool:
        raise UpdateMetadataError("Release fields have invalid types")
    if not isinstance(assets, list) or not isinstance(notes, str):
        raise UpdateMetadataError("Release fields have invalid types")
    version = _canonical_version(document.get("tag_name"), prefixed=True)
    if prerelease != version.is_prerelease:
        raise UpdateMetadataError("Release channel does not match its tag")
    if draft:
        return None
    expected_name = artifact_names(
        str(version), system="Linux", machine="x86_64"
    ).appimage
    matching = [item for item in assets if isinstance(item, dict) and item.get("name") == expected_name]
    if len(matching) != 1:
        raise UpdateMetadataError("Release must have exactly one compatible AppImage")
    selected_asset = _asset(matching[0], expected_name)
    if len(notes) > _MAX_NOTES_CHARS:
        notes = notes[: _MAX_NOTES_CHARS - len(_NOTES_SUFFIX)] + _NOTES_SUFFIX
    return UpdateRelease(version, prerelease, notes, selected_asset)


def select_update(
    body: bytes,
    *,
    installed_version: str,
    include_prereleases: bool,
    max_metadata_bytes: int = MAX_METADATA_BYTES,
) -> UpdateRelease | None:
    """Return the highest compatible release newer than the installed version."""
    installed = _canonical_version(installed_version, prefixed=False)
    if type(include_prereleases) is not bool:
        raise UpdateMetadataError("Release channel must be boolean")
    if not isinstance(body, bytes) or not body or len(body) > max_metadata_bytes:
        raise UpdateMetadataError("Release metadata size is invalid")
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateMetadataError("Release metadata is invalid") from exc
    if not isinstance(document, list):
        raise UpdateMetadataError("Release metadata must be a list")

    valid: list[UpdateRelease] = []
    errors = 0
    for item in document:
        # Stable checks do not need to interpret historical or future
        # pre-release tag formats.
        if (
            not include_prereleases
            and isinstance(item, dict)
            and item.get("prerelease") is True
        ):
            continue
        try:
            release = _release(item)
        except (UpdateMetadataError, ValueError):
            errors += 1
            continue
        if release is not None:
            valid.append(release)
    if errors and not valid:
        raise UpdateMetadataError("Release metadata contains no usable releases")

    candidates = [
        release
        for release in valid
        if release.version > installed
        and (include_prereleases or not release.prerelease)
    ]
    return max(candidates, key=lambda release: release.version, default=None)
