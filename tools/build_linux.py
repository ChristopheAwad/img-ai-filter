"""Build the supported Linux release artifacts without downloading tools."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from linux_artifacts import (
    create_tarball,
    prepare_appdir,
    validate_payload,
    write_checksums,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appimagetool", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from img_ai_filter.packaging import artifact_names, project_version

    try:
        names = artifact_names(project_version(root / "pyproject.toml"))
        appimagetool = args.appimagetool.resolve(strict=True)
        if not appimagetool.is_file() or not os.access(appimagetool, os.X_OK):
            raise ValueError("--appimagetool must name an executable file")
        runtime = args.runtime.resolve(strict=True)
        if not runtime.is_file():
            raise ValueError("--runtime must name a regular file")

        build_dir = root / "packaging-build"
        dist_dir = build_dir / "dist"
        work_dir = build_dir / "work"
        build_dir.mkdir(exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--distpath",
                str(dist_dir),
                "--workpath",
                str(work_dir),
                str(root / "packaging/linux/image-filter.spec"),
            ],
            cwd=root,
            check=True,
        )

        payload = dist_dir / "image-filter"
        shutil.copy2(
            root / "packaging/linux/THIRD_PARTY_NOTICES.txt",
            payload / "THIRD_PARTY_NOTICES.txt",
        )
        shutil.copy2(root / "packaging/linux/README.txt", payload / "README.txt")
        validate_payload(payload)
        tarball = build_dir / names.tarball
        create_tarball(payload, tarball, names.payload_directory)

        appdir = build_dir / "ImageFilter.AppDir"
        prepare_appdir(payload, appdir, root / "packaging/linux")
        appimage = build_dir / names.appimage
        environment = os.environ.copy()
        environment["ARCH"] = "x86_64"
        subprocess.run(
            [
                str(appimagetool),
                "--runtime-file",
                str(runtime),
                str(appdir),
                str(appimage),
            ],
            cwd=root,
            env=environment,
            check=True,
        )
        write_checksums([appimage, tarball], build_dir / "SHA256SUMS")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Linux packaging failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
