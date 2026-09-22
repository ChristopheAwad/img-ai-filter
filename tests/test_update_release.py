from __future__ import annotations

import json

import pytest

from img_ai_filter.update_release import (
    MAX_APPIMAGE_BYTES,
    MAX_METADATA_BYTES,
    UpdateMetadataError,
    select_update,
)


def _asset(version: str = "0.2.0", **changes) -> dict[str, object]:
    asset: dict[str, object] = {
        "name": f"ImageFilter-{version}-x86_64.AppImage",
        "size": 1024,
        "browser_download_url": (
            f"https://github.com/ChristopheAwad/img-ai-filter/releases/download/"
            f"v{version}/ImageFilter-{version}-x86_64.AppImage"
        ),
        "digest": "sha256:" + "a" * 64,
    }
    asset.update(changes)
    return asset


def _release(version: str = "0.2.0", **changes) -> dict[str, object]:
    release: dict[str, object] = {
        "id": 123,
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": "b" in version,
        "body": "Changes in this release.",
        "assets": [_asset(version)],
    }
    release.update(changes)
    return release


def _body(*releases: dict[str, object]) -> bytes:
    return json.dumps(releases).encode("utf-8")


@pytest.mark.parametrize("body", [b"", b" ", b"not json", b"[", b"\xff"])
def test_invalid_metadata_body_is_rejected(body: bytes) -> None:
    with pytest.raises(UpdateMetadataError):
        select_update(body, installed_version="0.1.0", include_prereleases=False)


@pytest.mark.parametrize("document", [{}, None, True, 1, "releases"])
def test_metadata_requires_top_level_list(document: object) -> None:
    with pytest.raises(UpdateMetadataError):
        select_update(
            json.dumps(document).encode(),
            installed_version="0.1.0",
            include_prereleases=False,
        )


def test_empty_release_list_is_up_to_date() -> None:
    assert select_update(b"[]", installed_version="0.1.0", include_prereleases=False) is None


def test_metadata_size_boundary_is_enforced() -> None:
    valid = _body(_release())
    assert select_update(
        valid,
        installed_version="0.1.0",
        include_prereleases=False,
        max_metadata_bytes=len(valid),
    ) is not None
    with pytest.raises(UpdateMetadataError):
        select_update(
            valid,
            installed_version="0.1.0",
            include_prereleases=False,
            max_metadata_bytes=len(valid) - 1,
        )
    assert MAX_METADATA_BYTES >= len(valid)


def test_drafts_are_ignored() -> None:
    result = select_update(
        _body(_release(draft=True)),
        installed_version="0.1.0",
        include_prereleases=True,
    )
    assert result is None


def test_stable_channel_ignores_prereleases() -> None:
    result = select_update(
        _body(_release("0.3.0b1"), _release("0.2.0")),
        installed_version="0.1.0",
        include_prereleases=False,
    )
    assert result is not None
    assert str(result.version) == "0.2.0"
    assert result.prerelease is False


def test_stable_channel_ignores_legacy_malformed_prerelease_tag() -> None:
    legacy = _release("0.1.0")
    legacy["tag_name"] = "v0.1.0-linux-test"
    legacy["prerelease"] = True

    assert select_update(
        _body(legacy),
        installed_version="0.2.0",
        include_prereleases=False,
    ) is None


def test_test_channel_selects_highest_release_regardless_of_api_order() -> None:
    result = select_update(
        _body(_release("0.2.0"), _release("0.10.0b1"), _release("0.3.0")),
        installed_version="0.1.0",
        include_prereleases=True,
    )
    assert result is not None
    assert str(result.version) == "0.10.0b1"
    assert result.prerelease is True


@pytest.mark.parametrize("installed", ["0.2.0", "0.3.0"])
def test_equal_or_older_release_is_not_an_update(installed: str) -> None:
    assert select_update(
        _body(_release("0.2.0")),
        installed_version=installed,
        include_prereleases=False,
    ) is None


@pytest.mark.parametrize("installed", ["", " 0.1.0", "dev", "1.0+local"])
def test_invalid_installed_version_is_rejected(installed: str) -> None:
    with pytest.raises(UpdateMetadataError):
        select_update(_body(_release()), installed_version=installed, include_prereleases=False)


@pytest.mark.parametrize(
    "changes",
    [
        {"tag_name": ""},
        {"tag_name": "0.2.0"},
        {"tag_name": "vbad"},
        {"draft": 0},
        {"prerelease": 0},
        {"assets": "asset"},
        {"id": True},
    ],
)
def test_malformed_releases_cannot_be_selected(changes: dict[str, object]) -> None:
    with pytest.raises(UpdateMetadataError):
        select_update(
            _body(_release(**changes)),
            installed_version="0.1.0",
            include_prereleases=True,
        )


def test_one_malformed_release_does_not_hide_a_valid_release() -> None:
    result = select_update(
        _body(_release(tag_name="bad"), _release("0.2.0")),
        installed_version="0.1.0",
        include_prereleases=False,
    )
    assert result is not None
    assert str(result.version) == "0.2.0"


@pytest.mark.parametrize(
    "asset_changes",
    [
        {"name": "ImageFilter-0.2.0-linux-x86_64.tar.gz"},
        {"name": "../ImageFilter-0.2.0-x86_64.AppImage"},
        {"name": "ImageFilter-0.2.0-aarch64.AppImage"},
        {"size": 0},
        {"size": -1},
        {"size": True},
        {"size": MAX_APPIMAGE_BYTES + 1},
        {"digest": None},
        {"digest": "sha256:abc"},
        {"digest": "sha512:" + "a" * 64},
        {"browser_download_url": "http://github.com/file"},
        {"browser_download_url": "https://example.com/file"},
    ],
)
def test_invalid_or_incompatible_asset_is_not_selected(asset_changes: dict[str, object]) -> None:
    with pytest.raises(UpdateMetadataError):
        select_update(
            _body(_release(assets=[_asset(**asset_changes)])),
            installed_version="0.1.0",
            include_prereleases=False,
        )


def test_duplicate_exact_assets_are_rejected() -> None:
    asset = _asset()
    with pytest.raises(UpdateMetadataError):
        select_update(
            _body(_release(assets=[asset, dict(asset)])),
            installed_version="0.1.0",
            include_prereleases=False,
        )


def test_asset_at_maximum_size_is_accepted() -> None:
    result = select_update(
        _body(_release(assets=[_asset(size=MAX_APPIMAGE_BYTES)])),
        installed_version="0.1.0",
        include_prereleases=False,
    )
    assert result is not None
    assert result.asset.size == MAX_APPIMAGE_BYTES
    assert result.asset.sha256 == "a" * 64


def test_release_notes_are_bounded_plain_text() -> None:
    result = select_update(
        _body(_release(body="x" * 30_000)),
        installed_version="0.1.0",
        include_prereleases=False,
    )
    assert result is not None
    assert len(result.notes) < 30_000
    assert result.notes.endswith("\n[Release notes truncated]")


def test_selected_asset_uses_exact_packaging_name() -> None:
    result = select_update(
        _body(_release()),
        installed_version="0.1.0",
        include_prereleases=False,
    )
    assert result is not None
    assert result.asset.name == "ImageFilter-0.2.0-x86_64.AppImage"
    assert result.asset.url.startswith("https://github.com/")
