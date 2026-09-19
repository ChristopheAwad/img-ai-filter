import pytest

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


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_non_linux_platforms_are_not_changed(platform: str) -> None:
    environment = {"UNRELATED": "kept"}

    configure_native_file_dialogs(platform, environment)

    assert environment == {"UNRELATED": "kept"}
