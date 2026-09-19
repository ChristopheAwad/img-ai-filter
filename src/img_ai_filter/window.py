"""Main desktop window."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from img_ai_filter.scanner import ScanResult, scan_images


class MainWindow(QMainWindow):
    def __init__(
        self,
        scan: Callable[[Path], ScanResult] = scan_images,
    ) -> None:
        super().__init__()
        self._scan = scan
        self._selected_folder: Path | None = None

        self.setWindowTitle("Image Filter")
        self.resize(820, 560)
        self.setMinimumSize(560, 400)

        title = QLabel("Review images, locally")
        title.setObjectName("title")
        description = QLabel(
            "Choose a folder, then start a scan when you are ready. Your files stay unchanged."
        )
        description.setObjectName("description")
        description.setWordWrap(True)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(28, 24, 28, 22)
        header_layout.setSpacing(7)
        header_layout.addWidget(title)
        header_layout.addWidget(description)

        folder_heading = QLabel("Source folder")
        folder_heading.setObjectName("sectionHeading")
        self.folder_label = QLabel("No folder selected")
        self.folder_label.setObjectName("folderPath")
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.folder_label.setWordWrap(True)

        self.select_button = QPushButton("Select Folder")
        self.select_button.setObjectName("primaryButton")
        self.select_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_button.clicked.connect(self._choose_folder)

        self.scan_button = QPushButton("Scan Folder")
        self.scan_button.setObjectName("primaryButton")
        self.scan_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_button.setEnabled(False)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(16)
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(self.select_button)
        folder_row.addWidget(self.scan_button)

        self.status_label = QLabel("Select a folder to begin.")
        self.status_label.setObjectName("status")

        self.results_list = QListWidget()
        self.results_list.setObjectName("results")
        self.results_list.setAlternatingRowColors(True)

        content = QVBoxLayout()
        content.setContentsMargins(28, 24, 28, 28)
        content.setSpacing(12)
        content.addWidget(folder_heading)
        content.addLayout(folder_row)
        content.addSpacing(6)
        content.addWidget(self.status_label)
        content.addWidget(self.results_list, 1)

        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(header)
        root_layout.addLayout(content, 1)

        root = QWidget()
        root.setLayout(root_layout)
        self.setCentralWidget(root)
        self._apply_style()

    def _choose_folder(self) -> None:
        starting_folder = str(self._selected_folder) if self._selected_folder else ""
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select image folder",
            starting_folder,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not selected:
            return

        folder = Path(selected)
        self._selected_folder = folder
        self.folder_label.setText(str(folder))
        self.results_list.clear()
        self.status_label.setText("Folder ready. Select Scan Folder to begin.")
        self.scan_button.setEnabled(True)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #edf3f7;
                color: #132238;
                font-size: 14px;
            }
            QFrame#header {
                background: #132238;
                border-bottom: 4px solid #2ba4b8;
            }
            QLabel#title {
                background: transparent;
                color: #ffffff;
                font-size: 26px;
                font-weight: 700;
            }
            QLabel#description {
                background: transparent;
                color: #c8d7e4;
                font-size: 14px;
            }
            QLabel#sectionHeading {
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#folderPath {
                background: #ffffff;
                border: 1px solid #c4d2dc;
                border-radius: 4px;
                padding: 9px 11px;
            }
            QLabel#status {
                color: #40566b;
                padding: 2px 0;
            }
            QPushButton#primaryButton {
                background: #136f8a;
                border: 2px solid #136f8a;
                border-radius: 4px;
                color: #ffffff;
                font-weight: 700;
                padding: 9px 18px;
            }
            QPushButton#primaryButton:hover {
                background: #0d5b72;
                border-color: #0d5b72;
            }
            QPushButton#primaryButton:focus {
                border-color: #132238;
            }
            QPushButton#primaryButton:disabled {
                background: #aab7c0;
                border-color: #aab7c0;
                color: #edf3f7;
            }
            QListWidget#results {
                alternate-background-color: #f5f8fa;
                background: #ffffff;
                border: 1px solid #c4d2dc;
                border-radius: 4px;
                outline: 0;
                padding: 4px;
            }
            QListWidget#results::item {
                padding: 7px 8px;
            }
            QListWidget#results::item:selected {
                background: #d6edf2;
                color: #132238;
            }
            """
        )
