"""Application launch entry point."""

import sys

from PySide6.QtWidgets import QApplication

from img_ai_filter.window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Image Filter")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
