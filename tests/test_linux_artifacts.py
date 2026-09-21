from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import stat
import tarfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOLS_PATH = ROOT / "tools" / "linux_artifacts.py"


def _load_tools():
    spec = importlib.util.spec_from_file_location("linux_artifacts", TOOLS_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("tools/linux_artifacts.py must be importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_payload(tmp_path: Path) -> Path:
    payload = tmp_path / "image-filter"
    internal = payload / "_internal"
    resources = internal / "img_ai_filter" / "resources"
    resources.mkdir(parents=True)
    executable = payload / "image-filter"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    (resources / "io.github.img_ai_filter.ImageFilter.svg").write_text(
        "<svg/>", encoding="utf-8"
    )
    (payload / "README.txt").write_text("readme\n", encoding="utf-8")
    (payload / "THIRD_PARTY_NOTICES.txt").write_text("notices\n", encoding="utf-8")
    return payload


def test_packaging_inputs_exist_and_are_pinned() -> None:
    spec = ROOT / "packaging" / "linux" / "image-filter.spec"
    requirements = ROOT / "packaging" / "linux" / "requirements.txt"
    apprun = ROOT / "packaging" / "linux" / "AppRun"

    assert spec.is_file()
    assert requirements.is_file()
    assert apprun.is_file()
    requirement_lines = {
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert len(requirement_lines) == 1
    assert next(iter(requirement_lines)).startswith("pyinstaller==")
    constraints = (
        ROOT / "packaging" / "linux" / "runtime-constraints.txt"
    ).read_text(encoding="utf-8")
    assert "PySide6==6.11.2" in constraints
    assert "Pillow==12.3.0" in constraints
    assert "keyring==25.7.0" in constraints
    assert os.access(apprun, os.X_OK)


def test_pyinstaller_spec_has_required_inputs_and_exclusions() -> None:
    contents = (ROOT / "packaging" / "linux" / "image-filter.spec").read_text(
        encoding="utf-8"
    )

    assert "src/img_ai_filter/__main__.py" in contents
    assert "img_ai_filter/resources" in contents
    assert "copy_metadata(\"img-ai-filter\")" in contents
    assert "collect_data_files(\"keyring\")" in contents
    assert "collect_submodules(\"keyring\")" in contents
    assert "PIL.WebPImagePlugin" in contents
    assert "exclude_binaries=True" in contents
    assert "COLLECT(" in contents
    assert "tests" not in contents
    assert "evaluation" not in contents


def test_apprun_resolves_its_own_directory() -> None:
    contents = (ROOT / "packaging" / "linux" / "AppRun").read_text(encoding="utf-8")

    assert "APPDIR" in contents
    assert 'exec "$APPDIR/usr/bin/image-filter" "$@"' in contents
    assert "python" not in contents.lower()


def test_validate_payload_accepts_minimum_complete_payload(tmp_path: Path) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)

    tools.validate_payload(payload)


@pytest.mark.parametrize(
    "relative_path",
    [
        "image-filter",
        "_internal/img_ai_filter/resources/io.github.img_ai_filter.ImageFilter.svg",
        "README.txt",
        "THIRD_PARTY_NOTICES.txt",
    ],
)
def test_validate_payload_rejects_missing_required_file(
    tmp_path: Path, relative_path: str
) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    (payload / relative_path).unlink()

    with pytest.raises(tools.ArtifactValidationError, match="Missing"):
        tools.validate_payload(payload)


def test_validate_payload_rejects_non_executable_launcher(tmp_path: Path) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    (payload / "image-filter").chmod(0o644)

    with pytest.raises(tools.ArtifactValidationError, match="executable"):
        tools.validate_payload(payload)


def test_validate_payload_rejects_forbidden_content(tmp_path: Path) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    forbidden = payload / ".git" / "config"
    forbidden.parent.mkdir()
    forbidden.write_text("secret", encoding="utf-8")

    with pytest.raises(tools.ArtifactValidationError, match="forbidden"):
        tools.validate_payload(payload)


def test_validate_payload_allows_internal_relative_symlink(tmp_path: Path) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    library = payload / "_internal" / "libexample.so.1"
    library.write_bytes(b"library")
    (payload / "_internal" / "libexample.so").symlink_to(library.name)

    tools.validate_payload(payload)


@pytest.mark.parametrize("target", ["/etc/passwd", "../../outside"])
def test_validate_payload_rejects_external_symlink(
    tmp_path: Path, target: str
) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    (payload / "_internal" / "unsafe-link").symlink_to(target)

    with pytest.raises(tools.ArtifactValidationError, match="symbolic link"):
        tools.validate_payload(payload)


def test_create_tarball_has_one_safe_top_level_directory(tmp_path: Path) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)
    output = tmp_path / "ImageFilter-0.1.0-linux-x86_64.tar.gz"

    tools.create_tarball(payload, output, "ImageFilter-0.1.0-linux-x86_64")

    with tarfile.open(output, "r:gz") as archive:
        members = archive.getmembers()
    assert members
    assert all(
        member.name == "ImageFilter-0.1.0-linux-x86_64"
        or member.name.startswith("ImageFilter-0.1.0-linux-x86_64/")
        for member in members
    )
    assert all(not member.name.startswith("/") and ".." not in Path(member.name).parts for member in members)
    launcher = next(member for member in members if member.name.endswith("/image-filter"))
    assert launcher.mode & stat.S_IXUSR


@pytest.mark.parametrize("root_name", ["", ".", "..", "../escape", "/absolute", "a/b"])
def test_create_tarball_rejects_unsafe_root_name(
    tmp_path: Path, root_name: str
) -> None:
    tools = _load_tools()
    payload = _valid_payload(tmp_path)

    with pytest.raises(ValueError, match="root"):
        tools.create_tarball(payload, tmp_path / "out.tar.gz", root_name)


def test_write_checksums_is_sorted_and_uses_file_names(tmp_path: Path) -> None:
    tools = _load_tools()
    second = tmp_path / "z.AppImage"
    first = tmp_path / "a.tar.gz"
    second.write_bytes(b"second")
    first.write_bytes(b"first")
    output = tmp_path / "SHA256SUMS"

    tools.write_checksums([second, first], output)

    lines = output.read_text(encoding="ascii").splitlines()
    assert lines == sorted(lines, key=lambda line: line.split("  ", 1)[1])
    assert lines[0].endswith("  a.tar.gz")
    assert lines[1].endswith("  z.AppImage")
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
        tools.write_checksums([first, second], tmp_path / "SHA256SUMS")


def test_build_script_uses_validated_payload_for_both_artifacts() -> None:
    script = ROOT / "tools" / "build_linux.py"
    assert script.is_file()
    contents = script.read_text(encoding="utf-8")

    assert "validate_payload" in contents
    assert "create_tarball" in contents
    assert "prepare_appdir" in contents
    assert "write_checksums" in contents
    assert "appimagetool" in contents
    assert "--runtime" in contents
    assert "--runtime-file" in contents
    assert "PyInstaller" in contents
    assert "packaging-build" in contents


def test_appimagetool_download_is_versioned_and_verified() -> None:
    workflow = (ROOT / ".github" / "workflows" / "linux-package.yml").read_text(
        encoding="utf-8"
    )

    assert "appimagetool/releases/download/1.9.1/" in workflow
    assert "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0" in workflow
    assert "type2-runtime/releases/download/20251108/runtime-x86_64" in workflow
    assert "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d" in workflow
    assert "sha256sum --check" in workflow
    assert "python-version: \"3.11\"" in workflow
    assert "runtime-constraints.txt" in workflow
    assert "contents: read" in workflow
    assert "actions/upload-artifact@v4" in workflow


def test_packaging_output_is_ignored() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "packaging-build/" in ignored
