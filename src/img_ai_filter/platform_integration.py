"""Operating-system integration configured before Qt starts."""

import os
import sys
from collections.abc import MutableMapping


def configure_native_file_dialogs(
    platform: str = sys.platform,
    environment: MutableMapping[str, str] = os.environ,
) -> None:
    """Use the configured Linux desktop portal without overriding user choices."""
    # An empty value does not select a theme, so treat it as "not set".
    if platform.startswith("linux") and not environment.get("QT_QPA_PLATFORMTHEME"):
        environment["QT_QPA_PLATFORMTHEME"] = "xdgdesktopportal"
