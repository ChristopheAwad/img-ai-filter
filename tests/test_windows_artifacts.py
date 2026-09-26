from __future__ import annotations

import importlib.util
from pathlib import Path
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS_PATH = ROOT / "tools" / "windows_artifacts.py"


def _load_tools():
    spec = importlib.util.spec_from_file_location("windows_artifacts", TOOLS_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("tools/windows_artifacts.py must be importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_payload(tmp_path: Path) -> Path:
    payload = tmp_path / "image-filter"
    internal = payload / "_internal"
    resources = internal / "img_ai_filter" / "resources"
    resources.mkdir(parents=True)
    (payload / "image-filter.exe").write_bytes(b"MZ")
    (resources / "io.github.img_ai_filter.ImageFilter.svg").write_text(
        "<svg/>", encoding="utf-8"
    )
    certifi_dir = internal / "certifi"
    certifi_dir.mkdir(parents=True)
    (certifi_dir / "cacert.pem").write_text(
        "-----BEGIN CERTIFICATE-----\n", encoding="utf-8"
    )
    (payload / "README.txt").write_text("readme\n", encoding="utf-8")
    (payload / "THIRD_PARTY_NOTICES.txt").write_text("notices\n", encoding="utf-8")
    return payload


def test_validate_windows_payload_accepts_minimum_payload(tmp_path: Path) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)

    tools.validate_windows_payload(payload)


@pytest.mark.parametrize(
    "relative_path",
    [
        "image-filter.exe",
        "_internal/img_ai_filter/resources/io.github.img_ai_filter.ImageFilter.svg",
        "_internal/certifi/cacert.pem",
        "README.txt",
        "THIRD_PARTY_NOTICES.txt",
    ],
)
def test_validate_windows_payload_rejects_missing_required_file(
    tmp_path: Path, relative_path: str
) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    (payload / relative_path).unlink()

    with pytest.raises(tools.WindowsArtifactValidationError, match="Missing"):
        tools.validate_windows_payload(payload)


def test_validate_windows_payload_rejects_forbidden_content(tmp_path: Path) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    forbidden = payload / ".git" / "config"
    forbidden.parent.mkdir()
    forbidden.write_text("secret", encoding="utf-8")

    with pytest.raises(tools.WindowsArtifactValidationError, match="forbidden"):
        tools.validate_windows_payload(payload)


def test_validate_windows_payload_rejects_non_regular_launcher(tmp_path: Path) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    launcher = payload / "image-filter.exe"
    launcher.unlink()
    launcher.mkdir()

    with pytest.raises(tools.WindowsArtifactValidationError, match="launcher|regular"):
        tools.validate_windows_payload(payload)


def test_create_windows_portable_zip_has_one_safe_top_level_directory(
    tmp_path: Path,
) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    output = tmp_path / "ImageFilter-0.1.0-windows-x86_64.zip"
    root_name = "ImageFilter-0.1.0-windows-x86_64"

    tools.create_windows_portable_zip(payload, output, root_name)

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
    assert names
    assert all(name == root_name or name.startswith(root_name + "/") for name in names)
    assert all(not name.startswith("/") and ".." not in Path(name).parts for name in names)
    assert any(name.endswith("image-filter.exe") for name in names)


@pytest.mark.parametrize(
    "root_name", ["", ".", "..", "../escape", "/absolute", "a/b", "C:"]
)
def test_create_windows_portable_zip_rejects_unsafe_root_name(
    tmp_path: Path, root_name: str
) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)

    with pytest.raises(ValueError, match="root"):
        tools.create_windows_portable_zip(payload, tmp_path / "out.zip", root_name)


def test_write_checksums_is_sorted_and_uses_file_names(tmp_path: Path) -> None:
    tools = _load_tools()
    second = tmp_path / "z-setup.exe"
    first = tmp_path / "a.zip"
    second.write_bytes(b"second")
    first.write_bytes(b"first")
    output = tmp_path / "SHA256SUMS-windows"

    tools.write_checksums([second, first], output)

    lines = output.read_text(encoding="ascii").splitlines()
    assert lines == sorted(lines, key=lambda line: line.split("  ", 1)[1])
    assert lines[0].endswith("  a.zip")
    assert lines[1].endswith("  z-setup.exe")
    assert all("/" not in line.split("  ", 1)[1] for line in lines)


def test_write_checksums_rejects_duplicate_file_names(tmp_path: Path) -> None:
    tools = _load_tools()
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = first_dir / "artifact"
    second = second_dir / "artifact"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    with pytest.raises(ValueError, match="duplicate"):
        tools.write_checksums([first, second], tmp_path / "SHA256SUMS-windows")


def test_windows_build_script_uses_validated_payload_for_both_artifacts() -> None:
    script = ROOT / "tools" / "build_windows.py"
    assert script.is_file()
    contents = script.read_text(encoding="utf-8")

    assert "validate_windows_payload" in contents
    assert "create_windows_portable_zip" in contents
    assert "write_checksums" in contents
    assert "windows_artifact_names" in contents
    assert "PyInstaller" in contents
    assert "--iscc" in contents
    assert "ISCC" in contents
    assert "packaging-build" in contents


def test_generate_windows_icon_is_deterministic_source() -> None:
    script = ROOT / "tools" / "generate_windows_icon.py"
    assert script.is_file()
    contents = script.read_text(encoding="utf-8")

    assert "io.github.img_ai_filter.ImageFilter.svg" in contents
    assert "ImageFilter.ico" in contents
