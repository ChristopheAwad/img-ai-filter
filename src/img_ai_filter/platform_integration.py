"""Operating-system integration configured before Qt starts."""

import os
import sys
from collections.abc import MutableMapping


def configure_native_file_dialogs(
    platform: str = sys.platform,
    environment: MutableMapping[str, str] = os.environ,
) -> None:
    """Use the configured Linux desktop portal without overriding user choices."""
    if platform.startswith("linux"):
        environment.setdefault("QT_QPA_PLATFORMTHEME", "xdgdesktopportal")
