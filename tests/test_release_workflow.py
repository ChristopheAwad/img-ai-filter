from __future__ import annotations

from pathlib import Path

import pytest

from img_ai_filter.release import ReleaseValidationError, validate_release_tag


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"


@pytest.mark.parametrize(
    ("tag", "version", "prerelease"),
    [
        ("v0.2.0", "0.2.0", False),
        ("v0.2.0b1", "0.2.0b1", True),
        ("v10.12.3b14", "10.12.3b14", True),
    ],
)
def test_release_tag_matches_canonical_project_version(
    tmp_path: Path, tag: str, version: str, prerelease: bool
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "app"\nversion = "{version}"\n')

    validated = validate_release_tag(tag, pyproject)

    assert str(validated.version) == version
    assert validated.prerelease is prerelease


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("0.2.0", "0.2.0"),
        ("v0.2", "0.2"),
        ("v0.2.0-beta.1", "0.2.0b1"),
        ("v0.2.0rc1", "0.2.0rc1"),
        ("v0.2.0+local", "0.2.0+local"),
        ("v0.2.1", "0.2.0"),
        ("v0.2.0b1", "0.2.0"),
        (" v0.2.0", "0.2.0"),
    ],
)
def test_release_tag_rejects_unsupported_or_mismatched_values(
    tmp_path: Path, tag: str, version: str
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "app"\nversion = "{version}"\n')

    with pytest.raises(ReleaseValidationError):
        validate_release_tag(tag, pyproject)


def test_release_workflow_is_tag_only_draft_first_and_least_privilege() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "tags:" in text
    assert '"v*"' in text
    assert "pull_request:" not in text
    assert "contents: read" in text
    assert "contents: write" in text
    assert text.index("gh release create") < text.index("gh release upload")
    assert text.index("gh release upload") < text.index("Verify uploaded release assets")
    assert text.index("Verify uploaded release assets") < text.index("--draft=false")
    assert "QT_QPA_PLATFORM: offscreen" in text
    assert "python -m pytest -q" in text
    assert "python tools/build_linux.py" in text
    assert "sha256sum --check SHA256SUMS" in text
    assert "ImageFilter-*-x86_64.AppImage" in text
    assert "ImageFilter-*-linux-x86_64.tar.gz" in text
    assert "SHA256SUMS" in text


def test_manual_packaging_workflow_remains_read_only() -> None:
    text = (ROOT / ".github" / "workflows" / "linux-package.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch:" in text
    assert "contents: read" in text
    assert "contents: write" not in text
    assert "gh release" not in text
