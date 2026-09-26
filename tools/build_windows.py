"""Build the supported Windows release artifacts on a Windows host."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

from windows_artifacts import (
    create_windows_portable_zip,
    validate_windows_payload,
    write_checksums,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iscc", required=True, type=Path, help="Path to ISCC.exe")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from img_ai_filter.packaging import project_version, windows_artifact_names

    try:
        version = project_version(root / "pyproject.toml")
        names = windows_artifact_names(version)
        iscc = args.iscc.resolve(strict=True)
        if not iscc.is_file():
            raise ValueError("--iscc must name an ISCC.exe file")

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
                str(root / "packaging/windows/image-filter.spec"),
            ],
            cwd=root,
            check=True,
        )

        payload = dist_dir / "image-filter"
        shutil.copy2(
            root / "packaging/windows/THIRD_PARTY_NOTICES.txt",
            payload / "THIRD_PARTY_NOTICES.txt",
        )
        shutil.copy2(root / "packaging/windows/README.txt", payload / "README.txt")
        validate_windows_payload(payload)

        portable = build_dir / names.portable_zip
        create_windows_portable_zip(payload, portable, names.payload_directory)

        installer = build_dir / names.installer
        subprocess.run(
            [
                str(iscc),
                f"/DAppVersion={version}",
                str(root / "packaging/windows/installer.iss"),
            ],
            cwd=root,
            check=True,
        )
        if not installer.is_file():
            raise ValueError(f"Inno Setup did not create {installer}")

        write_checksums([installer, portable], build_dir / "SHA256SUMS-windows")
        print(installer)
        print(portable)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Windows packaging failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
