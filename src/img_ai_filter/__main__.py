"""Application launch entry point."""

import ssl
import sys
from importlib.metadata import PackageNotFoundError, version

from img_ai_filter.platform_integration import configure_native_file_dialogs

configure_native_file_dialogs()

import certifi
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from img_ai_filter.packaging import application_icon_path
from img_ai_filter.window import MainWindow


def _application_version() -> str:
    try:
        return version("img-ai-filter")
    except PackageNotFoundError:
        return "0.0.0"


def main() -> int:
    smoke_test = sys.argv[1:] == ["--smoke-test"]
    if smoke_test:
        ssl.create_default_context(cafile=certifi.where())
    app = QApplication(sys.argv)
    app.setApplicationName("Image Filter")
    app.setApplicationVersion(_application_version())
    icon = application_icon_path()
    if icon is not None:
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    if smoke_test:
        app.processEvents()
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
