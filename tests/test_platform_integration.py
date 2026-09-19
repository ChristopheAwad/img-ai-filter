import builtins
import importlib
import sys

import pytest

from img_ai_filter import platform_integration
from img_ai_filter.platform_integration import configure_native_file_dialogs


@pytest.mark.parametrize("platform", ["linux", "linux2"])
def test_linux_uses_desktop_portal_when_no_theme_is_configured(platform: str) -> None:
    environment = {"UNRELATED": "kept"}

    configure_native_file_dialogs(platform, environment)

    assert environment == {
        "QT_QPA_PLATFORMTHEME": "xdgdesktopportal",
        "UNRELATED": "kept",
    }


def test_linux_preserves_existing_platform_theme() -> None:
    environment = {"QT_QPA_PLATFORMTHEME": "gtk3"}

    configure_native_file_dialogs("linux", environment)

    assert environment["QT_QPA_PLATFORMTHEME"] == "gtk3"


def test_linux_replaces_empty_platform_theme_with_desktop_portal() -> None:
    environment = {"QT_QPA_PLATFORMTHEME": ""}

    configure_native_file_dialogs("linux", environment)

    assert environment["QT_QPA_PLATFORMTHEME"] == "xdgdesktopportal"


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_non_linux_platforms_are_not_changed(platform: str) -> None:
    environment = {"UNRELATED": "kept"}

    configure_native_file_dialogs(platform, environment)

    assert environment == {"UNRELATED": "kept"}


def test_entry_point_configures_platform_theme_before_importing_qt(monkeypatch) -> None:
    real_import = builtins.__import__
    configured = False
    seen = []
    monkeypatch.delitem(sys.modules, "img_ai_filter.__main__", raising=False)

    def mark_configured() -> None:
        nonlocal configured
        configured = True

    def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
        seen.append(name)
        if name == "PySide6.QtWidgets":
            assert configured
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(platform_integration, "configure_native_file_dialogs", mark_configured)
    monkeypatch.setattr(builtins, "__import__", checked_import)

    try:
        importlib.import_module("img_ai_filter.__main__")
    finally:
        sys.modules.pop("img_ai_filter.__main__", None)

    assert "PySide6.QtWidgets" in seen
