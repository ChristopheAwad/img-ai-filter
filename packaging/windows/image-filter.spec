from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


project_root = Path(SPECPATH).parents[1]
entry_point = project_root / "src/img_ai_filter/__main__.py"
resource_dir = project_root / "src/img_ai_filter/resources"
notices = project_root / "packaging/windows/THIRD_PARTY_NOTICES.txt"
icon = project_root / "packaging/windows/ImageFilter.ico"

datas = [
    (str(resource_dir), "img_ai_filter/resources"),
    (str(notices), "."),
]
datas += copy_metadata("img-ai-filter")
datas += collect_data_files("keyring")
datas += collect_data_files("certifi")

a = Analysis(
    [str(entry_point)],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=collect_submodules("keyring") + ["PIL.WebPImagePlugin"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="image-filter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="image-filter",
)
