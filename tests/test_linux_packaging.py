from __future__ import annotations

import configparser
from pathlib import Path
import tomllib
import xml.etree.ElementTree as ET

from packaging.requirements import Requirement
from packaging.version import Version
import pytest

from img_ai_filter.packaging import (
    APP_ID,
    artifact_names,
    application_icon_path,
    project_version,
)


ROOT = Path(__file__).resolve().parents[1]
LINUX_DIR = ROOT / "packaging" / "linux"


def _certifi_requirement() -> Requirement:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [Requirement(item) for item in data["project"]["dependencies"]]
    matches = [requirement for requirement in requirements if requirement.name == "certifi"]
    if len(matches) != 1:
        raise AssertionError("pyproject must declare exactly one certifi dependency")
    return matches[0]


def _certifi_pin() -> tuple[str, str]:
    for line in (LINUX_DIR / "runtime-constraints.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("certifi"):
            name, separator, version = stripped.partition("==")
            if name != "certifi" or not separator or not version or "==" in version:
                raise AssertionError("certifi pin must use one exact == version")
            return name, version
    raise AssertionError("runtime-constraints must pin certifi exactly")


def test_project_version_comes_from_pyproject() -> None:
    assert project_version(ROOT / "pyproject.toml") == "0.2.3"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("", "project.version"),
        ("[project]\n", "project.version"),
        ("[project]\nversion = 1\n", "project.version"),
        ("[project]\nversion = ''\n", "project.version"),
        ("not toml", "pyproject.toml"),
    ],
)
def test_project_version_rejects_invalid_metadata(
    tmp_path: Path, contents: str, message: str
) -> None:
    metadata = tmp_path / "pyproject.toml"
    metadata.write_text(contents, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        project_version(metadata)


def test_project_version_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pyproject.toml"):
        project_version(tmp_path / "pyproject.toml")


def test_artifact_names_are_versioned_for_linux_x86_64() -> None:
    names = artifact_names("0.1.0", system="Linux", machine="x86_64")

    assert names.appimage == "ImageFilter-0.1.0-x86_64.AppImage"
    assert names.tarball == "ImageFilter-0.1.0-linux-x86_64.tar.gz"
    assert names.payload_directory == "ImageFilter-0.1.0-linux-x86_64"


@pytest.mark.parametrize(
    ("system", "machine"),
    [("Windows", "AMD64"), ("Darwin", "x86_64"), ("Linux", "aarch64")],
)
def test_artifact_names_reject_unsupported_targets(
    system: str, machine: str
) -> None:
    with pytest.raises(ValueError, match="Linux x86_64"):
        artifact_names("0.1.0", system=system, machine=machine)


def test_desktop_metadata_matches_application_identity() -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(LINUX_DIR / f"{APP_ID}.desktop", encoding="utf-8")

    entry = parser["Desktop Entry"]
    assert entry["Type"] == "Application"
    assert entry["Name"] == "Image Filter"
    assert entry["Exec"] == "image-filter"
    assert entry["Icon"] == APP_ID
    assert entry["Terminal"] == "false"
    assert "Graphics" in entry["Categories"].split(";")
    assert "%" not in entry["Exec"]


def test_appstream_metadata_matches_application_identity() -> None:
    root = ET.parse(LINUX_DIR / f"{APP_ID}.metainfo.xml").getroot()

    assert root.tag == "component"
    assert root.findtext("id") == APP_ID
    assert root.findtext("name") == "Image Filter"
    assert root.findtext("summary")
    assert root.findtext("metadata_license")
    launchable = root.find("launchable")
    assert launchable is not None
    assert launchable.attrib == {"type": "desktop-id"}
    assert launchable.text == f"{APP_ID}.desktop"
    release = root.find("releases/release")
    assert release is not None
    assert release.attrib["version"] == project_version(ROOT / "pyproject.toml")


def test_application_icon_resolves_outside_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    icon = application_icon_path()

    assert icon.is_file()
    assert icon.suffix == ".svg"
    assert APP_ID in icon.name


def test_application_icon_resolves_from_frozen_resource_root(tmp_path: Path) -> None:
    resource_root = tmp_path / "frozen"
    icon_dir = resource_root / "img_ai_filter" / "resources"
    icon_dir.mkdir(parents=True)
    expected = icon_dir / f"{APP_ID}.svg"
    expected.write_text("<svg/>", encoding="utf-8")

    assert application_icon_path(resource_root=resource_root) == expected


def test_missing_application_icon_returns_none(tmp_path: Path) -> None:
    assert application_icon_path(resource_root=tmp_path) is None


def test_entrypoint_supports_bounded_packaged_smoke_test() -> None:
    contents = (ROOT / "src" / "img_ai_filter" / "__main__.py").read_text(
        encoding="utf-8"
    )

    assert "--smoke-test" in contents
    assert "certifi.where()" in contents
    assert "ssl.create_default_context" in contents
    assert "app.processEvents()" in contents
    assert "window.close()" in contents


def test_pyproject_declares_bounded_certifi_runtime_dependency() -> None:
    requirement = _certifi_requirement()

    assert list(requirement.specifier), (
        "certifi runtime dependency must use a bounded version range"
    )
    assert any(
        specification.operator in {"<", "<=", "=="}
        for specification in requirement.specifier
    ), "certifi runtime dependency must declare an upper bound"


def test_runtime_constraints_pin_certifi_exactly() -> None:
    name, version = _certifi_pin()

    assert name == "certifi"
    assert version


def test_certifi_pin_satisfies_pyproject_requirement() -> None:
    requirement = _certifi_requirement()
    _, version = _certifi_pin()

    assert Version(version) in requirement.specifier


def test_linux_spec_collects_certifi_data_files() -> None:
    spec = (LINUX_DIR / "image-filter.spec").read_text(encoding="utf-8")

    assert 'collect_data_files("certifi")' in spec or (
        "collect_data_files('certifi')" in spec
    )


def test_third_party_notices_document_certifi_mozilla_license() -> None:
    notices = (LINUX_DIR / "THIRD_PARTY_NOTICES.txt").read_text(
        encoding="utf-8"
    ).lower()

    assert "certifi" in notices
    assert "mozilla public license" in notices
