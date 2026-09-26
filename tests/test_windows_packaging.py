from __future__ import annotations

from pathlib import Path

from PIL import Image
import pytest

from img_ai_filter.packaging import (
    project_version,
    windows_artifact_names,
)


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "packaging" / "windows"

INNOSETUP_SHA256 = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732"


def test_windows_artifact_names_are_versioned() -> None:
    names = windows_artifact_names("0.1.0", system="Windows", machine="AMD64")

    assert names.installer == "ImageFilter-0.1.0-windows-x86_64-setup.exe"
    assert names.portable_zip == "ImageFilter-0.1.0-windows-x86_64.zip"
    assert names.payload_directory == "ImageFilter-0.1.0-windows-x86_64"


@pytest.mark.parametrize(
    ("system", "machine"),
    [("Linux", "x86_64"), ("Windows", "ARM64"), ("Darwin", "arm64")],
)
def test_windows_artifact_names_reject_unsupported_targets(
    system: str, machine: str
) -> None:
    with pytest.raises(ValueError, match="Windows x86_64"):
        windows_artifact_names("0.1.0", system=system, machine=machine)


def test_windows_artifact_names_use_project_version() -> None:
    version = project_version(ROOT / "pyproject.toml")

    names = windows_artifact_names(version, system="Windows", machine="AMD64")

    assert version in names.installer
    assert version in names.portable_zip


def test_windows_spec_has_required_inputs_and_exclusions() -> None:
    contents = (WINDOWS_DIR / "image-filter.spec").read_text(encoding="utf-8")

    assert "src/img_ai_filter/__main__.py" in contents
    assert "img_ai_filter/resources" in contents
    assert 'copy_metadata("img-ai-filter")' in contents
    assert 'collect_data_files("keyring")' in contents
    assert 'collect_submodules("keyring")' in contents
    assert 'collect_data_files("certifi")' in contents
    assert "PIL.WebPImagePlugin" in contents
    assert "icon=" in contents
    assert "console=False" in contents
    assert "upx=False" in contents
    assert "exclude_binaries=True" in contents
    assert "COLLECT(" in contents
    assert "tests" not in contents
    assert "evaluation" not in contents


def test_windows_icon_is_multi_size_ico() -> None:
    icon = WINDOWS_DIR / "ImageFilter.ico"

    assert icon.is_file()
    with Image.open(icon) as image:
        assert image.format == "ICO"
        available = set(image.ico.sizes())
    expected = {(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)}
    assert expected <= available


def test_windows_installer_script_is_safe_and_per_user() -> None:
    contents = (WINDOWS_DIR / "installer.iss").read_text(encoding="utf-8")

    assert "AppId=" in contents
    assert "PrivilegesRequired=lowest" in contents
    assert "{localappdata}\\Programs\\Image Filter" in contents
    assert "SetupIconFile=ImageFilter.ico" in contents
    assert "UninstallDisplayIcon" in contents
    assert "packaging-build\\dist\\image-filter" in contents
    assert "[Icons]" in contents
    assert "[Files]" in contents
    assert "{#AppVersion}" in contents
    assert project_version(ROOT / "pyproject.toml") not in contents


def test_windows_notices_document_required_licenses() -> None:
    notices = (WINDOWS_DIR / "THIRD_PARTY_NOTICES.txt").read_text(
        encoding="utf-8"
    ).lower()

    assert "certifi" in notices
    assert "mozilla public license" in notices
    assert "pyside6" in notices
    assert "pyinstaller" in notices


def test_windows_requirements_and_constraints_are_pinned() -> None:
    requirement_lines = [
        line.strip()
        for line in (WINDOWS_DIR / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(requirement_lines) == 1
    assert requirement_lines[0].startswith("pyinstaller==")

    constraints = (WINDOWS_DIR / "runtime-constraints.txt").read_text(encoding="utf-8")
    assert "PySide6==6.11.2" in constraints
    assert "Pillow==12.3.0" in constraints
    assert "keyring==25.7.0" in constraints
    assert "certifi==2026.7.22" in constraints
    assert "packaging==26.3" in constraints


def test_windows_package_workflow_is_hardened() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "windows-package.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert 'python-version: "3.11"' in workflow
    assert "innosetup-6.7.3.exe" in workflow
    assert INNOSETUP_SHA256 in workflow
    assert "Get-FileHash" in workflow or "sha256sum" in workflow
    assert "tools/build_windows.py" in workflow
    assert "--smoke-test" in workflow
    assert "contents: read" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "runtime-constraints.txt" in workflow


def test_release_workflow_builds_and_publishes_windows() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "build-windows:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "packaging/windows/requirements.txt" in workflow
    assert "innosetup-6.7.3.exe" in workflow
    assert INNOSETUP_SHA256 in workflow
    assert "-windows-x86_64-setup.exe" in workflow
    assert "-windows-x86_64.zip" in workflow
    assert "shell: pwsh" in workflow


def test_windows_artifacts_are_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "innosetup-*.exe" in ignored


def test_readme_documents_windows_install_and_portable_use() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "windows-x86_64-setup.exe" in readme
    assert "windows-x86_64.zip" in readme
    assert "SmartScreen" in readme
    assert "administrator" in readme
