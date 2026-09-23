"""Main desktop window."""

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from importlib.metadata import version as package_version
import os
from pathlib import Path
from threading import Event
import time
from typing import Any

from PySide6.QtCore import QEvent, QSettings, QSize, QTimer, Qt
from PySide6.QtGui import QAction, QIcon, QImage, QPalette, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from img_ai_filter.endpoint import (
    EndpointValidationError,
    VisionEndpointConfig,
    build_vision_endpoint_config,
)
from img_ai_filter.http_transport import StandardHttpTransport
from img_ai_filter.quarantine import (
    MOVE_LOG_NAME,
    MoveStatus,
    QuarantineError,
    QuarantineState,
    QuarantineSummary,
    build_quarantine_plan,
    execute_quarantine_plan,
    validate_quarantine_folder,
    validate_quarantine_roots,
)
from img_ai_filter.scan_worker import OperationThread
from img_ai_filter.activity_history import (
    QuarantineFileHistory,
    QuarantineHistoryRecord,
    ScanHistoryRecord,
    append_activity_history,
    clear_activity_history,
    format_duration,
    load_activity_history,
)
from img_ai_filter.scan_workflow import (
    ScanCandidate,
    ScanState,
    ScanSummary,
    run_server_scan,
)
from img_ai_filter.scanner import ScanError, ScanResult, scan_images
from img_ai_filter.settings import (
    ENDPOINT_URL_KEY,
    MAX_AUTO_SELECT_CONFIDENCE_PERCENT,
    MIN_AUTO_SELECT_CONFIDENCE_PERCENT,
    QUARANTINE_FOLDER_KEY,
    SettingsStatus,
    load_auto_select_confidence,
    load_include_test_releases,
    load_quarantine_folder,
    load_vision_endpoint_settings,
    save_quarantine_folder,
    save_auto_select_confidence,
    save_include_test_releases,
    save_vision_endpoint_settings,
)
from img_ai_filter.update_install import (
    AppImageInstallation,
    InstallError,
    InstallResult,
    detect_appimage_installation,
    install_appimage,
    restart_appimage,
)
from img_ai_filter.update_release import UpdateMetadataError, UpdateRelease, select_update
from img_ai_filter.update_transport import (
    UpdateCancelled,
    UpdateTransportError,
    VerifiedDownload,
    download_appimage,
    fetch_release_metadata,
)
from img_ai_filter.vision_connection import VisionConnectionError, discover_koboldcpp


DEFAULT_SERVER_URL = "http://192.168.0.239:5001/v1/"


def _application_version() -> str:
    value = QApplication.applicationVersion()
    if value:
        return value
    try:
        return package_version("img-ai-filter")
    except Exception:
        return "0.0.0"


def _check_update(version: str, include: bool, cancel_event: Event) -> UpdateRelease | None:
    metadata = fetch_release_metadata(cancel_event=cancel_event)
    return select_update(
        metadata, installed_version=version, include_prereleases=include
    )


def _download_update(asset, directory: Path, cancel_event: Event, progress):
    return download_appimage(
        asset, directory=directory, cancel_event=cancel_event, progress=progress
    )


def _update_message(parent, icon: QMessageBox.Icon, text: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle("Updates")
    box.setText(text)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def _quarantine_confirm_parts(
    items: Iterable[tuple[str, str]], folder: str
) -> tuple[str, str, str]:
    item_list = [(str(source), str(destination)) for source, destination in items]
    count = len(item_list)
    word = "file" if count == 1 else "files"
    heading = (
        f"Move {count} checked {word} to the quarantine folder {folder}? "
        "The transfer is a verified byte-for-byte copy, and a source file "
        "that changes after scanning is left in place."
    )
    detailed = "\n".join(
        f"Source: {source}\nDestination: {destination}"
        for source, destination in item_list
    )
    return "Move checked files to quarantine?", heading, detailed


class _QSettingsStore:
    """Adapt Qt's platform settings to the application's settings interface."""

    def __init__(self) -> None:
        self._settings = QSettings("img-ai-filter", "Image Filter")

    def read(self, key: str) -> str | None:
        value = self._settings.value(key, None)
        return None if value is None else str(value)

    def write(self, key: str, value: str) -> None:
        self._settings.setValue(key, value)

    def delete(self, key: str) -> None:
        self._settings.remove(key)


class ActivityHistoryDialog(QDialog):
    """Display locally saved scan and quarantine activity."""

    _COLUMNS = (
        "Type",
        "Started (UTC)",
        "Source",
        "Model / Destination",
        "Result",
        "Duration",
        "Counts / Message",
    )
    _RESULTS = {
        "completed": "Completed",
        "completed_with_skips": "Completed with skips",
        "cancelled": "Cancelled",
        "failed": "Failed",
    }

    def __init__(self, store: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self.setWindowTitle("Activity History")
        self.resize(1050, 460)

        self.disclosure_label = QLabel(
            "Saved locally. Scan source folders and model names are included. "
            "Quarantine records include exact source and destination file paths."
        )
        self.disclosure_label.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self._COLUMNS))
        self.tree.setHeaderLabels(self._COLUMNS)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self.empty_label = QLabel("No activity history has been saved.")

        self.clear_button = QPushButton("Clear History")
        close_button = QPushButton("Close")
        self.clear_button.clicked.connect(self._clear_history)
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.disclosure_label)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.tree, 1)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        records = tuple(reversed(load_activity_history(self._store)))
        self.tree.clear()
        for record in records:
            if isinstance(record, ScanHistoryRecord):
                counts = "Counts unavailable"
                if record.discovered is not None:
                    counts = (
                        f"{record.discovered} discovered, {record.analyzed} analyzed, "
                        f"{record.candidates} candidates, {record.ordinary} ordinary, "
                        f"{record.uncertain} uncertain, {record.failed} failed, "
                        f"{record.skipped_directories} unreadable folders"
                    )
                values = ("Scan", record.started_at_utc, record.source_folder,
                          record.model, self._RESULTS[record.outcome],
                          format_duration(record.duration_ms), counts)
                self.tree.addTopLevelItem(QTreeWidgetItem(values))
                continue
            counts = "Counts unavailable" if record.moved is None else (
                f"{record.moved} moved, {record.conflicts} "
                f"{'conflict' if record.conflicts == 1 else 'conflicts'}, "
                f"{record.failed} failed"
            )
            results = {"completed": "Completed", "completed_with_failures": "Completed with failures", "failed": "Failed"}
            parent = QTreeWidgetItem(("Quarantine", record.started_at_utc,
                record.source_folder, record.quarantine_folder, results[record.outcome],
                format_duration(record.duration_ms), counts))
            child_results = {"moved": "Moved", "conflict": "Conflict", "failed": "Failed", "unknown": "Unknown"}
            for item in record.files:
                parent.addChild(QTreeWidgetItem(("File", "", item.source,
                    item.destination, child_results[item.status], "", item.message)))
            self.tree.addTopLevelItem(parent)
        present = bool(records)
        self.empty_label.setVisible(not present)
        self.tree.setVisible(present)
        self.clear_button.setEnabled(present)

    def _clear_history(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear activity history?",
            "All saved app history will be removed. Quarantine move-log files will remain.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if clear_activity_history(self._store):
            self.reload()
        else:
            QMessageBox.warning(
                self, "Activity History", "Activity history could not be cleared."
            )


class CandidateSelectionSettingsDialog(QDialog):
    """Configure automatic selection for candidates from future scans."""

    def __init__(
        self, store: Any, threshold: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._store = store
        self.selected_threshold = threshold
        self.selected_include_test_releases = load_include_test_releases(store)
        self.setWindowTitle("Settings")

        label = QLabel("Automatic-selection confidence threshold")
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(
            MIN_AUTO_SELECT_CONFIDENCE_PERCENT, MAX_AUTO_SELECT_CONFIDENCE_PERCENT
        )
        label.setBuddy(self.threshold_spin)
        self.threshold_spin.setSuffix("%")
        self.threshold_spin.setValue(threshold)
        field = QHBoxLayout()
        field.addWidget(label)
        field.addWidget(self.threshold_spin)

        self.explanation_label = QLabel(
            "Candidates from future scans start checked when their model-reported "
            "confidence meets this threshold. Existing review choices do not change."
        )
        self.explanation_label.setWordWrap(True)
        self.include_test_releases_checkbox = QCheckBox(
            "Include test releases when checking for updates"
        )
        self.include_test_releases_checkbox.setChecked(
            self.selected_include_test_releases
        )
        self.error_label = QLabel()
        self.error_label.setObjectName("status")

        self.save_button = QPushButton("Save")
        self.save_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel")
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addLayout(field)
        layout.addWidget(self.explanation_label)
        layout.addWidget(self.include_test_releases_checkbox)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

    def _save(self) -> None:
        value = self.threshold_spin.value()
        include = self.include_test_releases_checkbox.isChecked()
        old_threshold = self.selected_threshold
        old_include = self.selected_include_test_releases
        if value != old_threshold and not save_auto_select_confidence(self._store, value):
            self.error_label.setText("The automatic-selection threshold could not be saved.")
            return
        if include != old_include and not save_include_test_releases(self._store, include):
            if value != old_threshold:
                save_auto_select_confidence(self._store, old_threshold)
            self.error_label.setText("The update release channel could not be saved.")
            return
        self.selected_threshold = value
        self.selected_include_test_releases = include
        self.accept()


class MainWindow(QMainWindow):
    def __init__(
        self,
        scan: Callable[[Path], ScanResult] = scan_images,
        *,
        settings_store: Any = None,
        transport_factory: Callable[[], Any] = StandardHttpTransport,
        discover: Callable[..., Any] = discover_koboldcpp,
        run_scan: Callable[..., ScanSummary] = run_server_scan,
        run_quarantine: Callable[..., Any] | None = None,
        confirm_quarantine: Callable[[tuple[str, ...], str], bool] | None = None,
        confirm_transfer: Callable[[str, bool], bool] | None = None,
        initial_config: VisionEndpointConfig | None = None,
        resolver: Callable[..., Any] | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        application_version: str | None = None,
        update_environment: Any = None,
        check_update: Callable[..., Any] = _check_update,
        download_update: Callable[..., Any] = _download_update,
        install_update: Callable[..., Any] = install_appimage,
        restart_update: Callable[..., Any] = restart_appimage,
    ) -> None:
        super().__init__()
        self._scan = scan
        self._settings_store = settings_store if settings_store is not None else _QSettingsStore()
        self._transport_factory = transport_factory
        self._discover = discover
        self._run_scan = run_scan
        self._run_quarantine = (
            run_quarantine if run_quarantine is not None else MainWindow._default_run_quarantine
        )
        self._confirm_quarantine = confirm_quarantine
        self._confirm_transfer = confirm_transfer
        self._resolver = resolver
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._application_version = application_version or _application_version()
        self._update_environment = os.environ if update_environment is None else update_environment
        self._check_update = check_update
        self._download_update = download_update
        self._install_update = install_update
        self._restart_update = restart_update
        self._include_test_releases = load_include_test_releases(self._settings_store)
        self._update_thread: OperationThread | None = None
        self._update_cancel_event: Event | None = None
        self._update_kind: str | None = None
        self._update_result: Any = None
        self._update_error: Exception | None = None
        self._update_generation = 0
        self._update_installation: AppImageInstallation | None = None
        self._verified_update: VerifiedDownload | None = None
        self._selected_folder: Path | None = None
        self._results_folder: Path | None = None
        self._quarantine_folder: Path | None = None
        self._quarantine_missing = False
        self._stored_quarantine_raw: str | None = None
        self._moving = False
        self._config: VisionEndpointConfig | None = None
        self._thread: OperationThread | None = None
        self._active_transport: Any = None
        self._cancel_event: Event | None = None
        self._operation_kind: str | None = None
        self._operation_result: Any = None
        self._operation_error: Exception | None = None
        self._generation = 0
        self._closing = False
        self._candidate_row_refresh_pending = False
        self._scan_started_monotonic: float | None = None
        self._scan_started_at_utc: str | None = None
        self._scan_source_folder: str | None = None
        self._scan_model: str | None = None
        self._scan_recorded = False
        self._scan_phase = "preparing"
        self._scan_progress: tuple[int, int] | None = None
        self._scan_generation: int | None = None
        self._quarantine_started_monotonic: float | None = None
        self._quarantine_started_at_utc: str | None = None
        self._quarantine_source_folder: str | None = None
        self._quarantine_folder_snapshot: str | None = None
        self._quarantine_batch_id: str | None = None
        self._quarantine_items: tuple[tuple[str, str], ...] = ()
        self._quarantine_recorded = False
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(1000)
        self._scan_timer.timeout.connect(self._render_live_scan_status)
        self._auto_select_confidence_percent = load_auto_select_confidence(
            self._settings_store
        )

        server_url = DEFAULT_SERVER_URL
        if initial_config is not None:
            self._config = initial_config
            server_url = initial_config.base_url
        else:
            try:
                raw_url = self._settings_store.read(ENDPOINT_URL_KEY)
                if raw_url is not None:
                    server_url = raw_url
                loaded = load_vision_endpoint_settings(
                    self._settings_store, resolver=self._resolver
                )
                if loaded.status is SettingsStatus.READY:
                    self._config = loaded.config
            except Exception:
                self._config = None

        try:
            self._stored_quarantine_raw = self._settings_store.read(QUARANTINE_FOLDER_KEY)
            loaded_quarantine = load_quarantine_folder(self._settings_store)
            if loaded_quarantine.status is SettingsStatus.READY:
                self._quarantine_folder = loaded_quarantine.folder
            elif self._stored_quarantine_raw is not None and str(self._stored_quarantine_raw).strip():
                self._quarantine_missing = True
        except Exception:
            self._quarantine_folder = None

        self.setWindowTitle("Image Filter")
        self.resize(820, 1020)
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
        header.setBackgroundRole(QPalette.ColorRole.Button)
        header.setAutoFillBackground(True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(28, 24, 28, 22)
        header_layout.setSpacing(16)
        header_text_layout = QVBoxLayout()
        header_text_layout.setSpacing(7)
        header_text_layout.addWidget(title)
        header_text_layout.addWidget(description)
        header_layout.addLayout(header_text_layout, 1)

        self.application_menu_button = QToolButton(header)
        self.application_menu_button.setObjectName("applicationMenuButton")
        self.application_menu_button.setText("...")
        self.application_menu_button.setToolTip("Application menu")
        self.application_menu_button.setAccessibleName("Application menu")
        self.application_menu_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.application_menu_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.application_menu = QMenu(self.application_menu_button)
        self.settings_action = QAction("Settings", self)
        self.settings_action.triggered.connect(self._show_settings)
        self.check_updates_action = QAction("Check for Updates", self)
        self.check_updates_action.triggered.connect(self._request_update_check)
        self.application_menu.addAction(self.settings_action)
        self.application_menu.addAction(self.check_updates_action)
        self.application_menu_button.setMenu(self.application_menu)
        header_layout.addWidget(
            self.application_menu_button, 0, Qt.AlignmentFlag.AlignTop
        )

        server_heading = QLabel("KoboldCpp server")
        server_heading.setObjectName("sectionHeading")
        self.server_url_input = QLineEdit(server_url)
        self.server_url_input.setObjectName("serverUrl")
        self.server_url_input.setPlaceholderText("KoboldCpp server URL")
        self.test_connection_button = QPushButton("Test Connection")
        self.test_connection_button.setObjectName("primaryButton")
        self.test_connection_button.setCursor(Qt.CursorShape.PointingHandCursor)

        server_row = QHBoxLayout()
        server_row.setSpacing(16)
        server_row.addWidget(self.server_url_input, 1)
        server_row.addWidget(self.test_connection_button)

        self.connection_label = QLabel()
        self.connection_label.setObjectName("status")
        self.model_label = QLabel()
        self.model_label.setObjectName("model")
        if self._config is not None and self._config.model:
            self.connection_label.setText("Saved server is vision ready.")
            self.model_label.setText(f"Model: {self._config.model}")
        else:
            self._show_no_model()

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

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.setEnabled(False)

        self.activity_history_button = QPushButton("Activity History")
        self.activity_history_button.setObjectName("secondaryButton")
        self.activity_history_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.activity_history_button.clicked.connect(self._show_activity_history)

        folder_buttons = QGridLayout()
        folder_buttons.setSpacing(8)
        folder_buttons.addWidget(self.select_button, 0, 0)
        folder_buttons.addWidget(self.scan_button, 0, 1)
        folder_buttons.addWidget(self.cancel_button, 1, 0)
        folder_buttons.addWidget(self.activity_history_button, 1, 1)
        for column in range(2):
            folder_buttons.setColumnStretch(column, 1)

        quarantine_heading = QLabel("Quarantine folder")
        quarantine_heading.setObjectName("sectionHeading")
        self.quarantine_label = QLabel()
        self.quarantine_label.setObjectName("folderPath")
        self.quarantine_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.quarantine_label.setWordWrap(True)
        if self._quarantine_folder is not None:
            self.quarantine_label.setText(str(self._quarantine_folder))
        elif self._quarantine_missing and self._stored_quarantine_raw:
            self.quarantine_label.setText(
                f"{self._stored_quarantine_raw} is not available. Select a valid quarantine folder."
            )
        else:
            self.quarantine_label.setText("No quarantine folder selected.")

        self.select_quarantine_button = QPushButton("Select Quarantine Folder")
        self.select_quarantine_button.setObjectName("secondaryButton")
        self.select_quarantine_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_quarantine_button.clicked.connect(self._choose_quarantine)

        self.quarantine_validation_label = QLabel()
        self.quarantine_validation_label.setObjectName("status")
        self.quarantine_validation_label.setWordWrap(True)
        self.quarantine_validation_label.hide()

        self.move_quarantine_button = QPushButton("Move Checked to Quarantine")
        self.move_quarantine_button.setObjectName("primaryButton")
        self.move_quarantine_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.move_quarantine_button.setEnabled(False)
        self.move_quarantine_button.clicked.connect(self._request_quarantine_move)

        quarantine_buttons = QGridLayout()
        quarantine_buttons.setSpacing(12)
        quarantine_buttons.addWidget(self.select_quarantine_button, 0, 0)
        quarantine_buttons.addWidget(self.move_quarantine_button, 1, 0)
        quarantine_buttons.setColumnStretch(0, 1)

        self.move_log_label = QLabel("Move log: not written yet.")
        self.move_log_label.setObjectName("model")
        self.move_log_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.move_log_label.setWordWrap(True)

        self.status_label = QLabel("Select a folder to begin.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)

        self.selection_button = QPushButton("Select All")
        self.selection_button.setObjectName("secondaryButton")
        self.selection_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.selection_button.setEnabled(False)
        self.selection_button.clicked.connect(self._toggle_selection)

        results_status_row = QHBoxLayout()
        results_status_row.setSpacing(12)
        results_status_row.addWidget(self.status_label, 1)
        results_status_row.addWidget(self.selection_button)

        self.results_list = QListWidget()
        self.results_list.setObjectName("results")
        self.results_list.setAlternatingRowColors(True)
        self.results_list.setIconSize(QSize(96, 96))
        results_policy = self.results_list.sizePolicy()
        results_policy.setVerticalPolicy(QSizePolicy.Policy.Ignored)
        self.results_list.setSizePolicy(results_policy)

        self.results_empty_label = QLabel(
            "No likely screenshots or memes were found."
        )
        self.results_empty_label.setObjectName("status")
        self.results_empty_label.setWordWrap(True)
        self.results_empty_label.hide()

        content_widget = QWidget()
        content = QVBoxLayout(content_widget)
        content.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        content.setContentsMargins(20, 24, 20, 28)
        content.setSpacing(10)
        content.addWidget(server_heading)
        content.addLayout(server_row)
        content.addWidget(self.connection_label)
        content.addWidget(self.model_label)
        content.addSpacing(8)
        content.addWidget(folder_heading)
        content.addWidget(self.folder_label)
        content.addLayout(folder_buttons)
        content.addSpacing(8)
        content.addWidget(quarantine_heading)
        content.addWidget(self.quarantine_label)
        content.addWidget(self.quarantine_validation_label)
        content.addLayout(quarantine_buttons)
        content.addWidget(self.move_log_label)
        content.addSpacing(6)
        content.addLayout(results_status_row)
        content.addWidget(self.results_empty_label)
        content.addWidget(self.results_list, 1)

        self.content_scroll = QScrollArea()
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.content_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.content_scroll.setWidget(content_widget)

        root_layout = QVBoxLayout()
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(header)
        root_layout.addWidget(self.content_scroll, 1)

        root = QWidget()
        root.setLayout(root_layout)
        self.setCentralWidget(root)
        self._apply_style()
        QApplication.instance().installEventFilter(self)
        self.results_list.viewport().installEventFilter(self)
        for button in (
            self.test_connection_button,
            self.select_button,
            self.scan_button,
            self.cancel_button,
            self.activity_history_button,
            self.select_quarantine_button,
            self.move_quarantine_button,
            self.selection_button,
        ):
            button.setMinimumSize(button.minimumSizeHint())
        self.results_list.setMinimumHeight(
            self.results_list.minimumSizeHint().height()
        )
        self.server_url_input.textChanged.connect(self._server_url_edited)
        self.test_connection_button.clicked.connect(self._test_connection)
        self.scan_button.clicked.connect(self._request_scan)
        self.cancel_button.clicked.connect(self._cancel_operation)
        self.results_list.itemChanged.connect(self._candidate_item_changed)
        self.results_list.itemSelectionChanged.connect(self._update_candidate_selection_colors)
        self._update_controls()

    @staticmethod
    def _default_run_quarantine(
        candidates, source_root, quarantine_root, *, progress=None
    ):
        """Build and execute a verified quarantine plan in one background step."""
        plan = build_quarantine_plan(source_root, quarantine_root, candidates)
        return execute_quarantine_plan(plan, progress=progress)

    def _show_no_model(self) -> None:
        self.connection_label.setText("Test the server connection before scanning.")
        self.model_label.setText("Model: not discovered")

    def _server_url_edited(self) -> None:
        if self._thread is not None or self._update_thread is not None:
            return
        self._config = None
        self._show_no_model()
        self._update_controls()

    def _update_controls(self) -> None:
        active = self._thread is not None
        update_active = self._update_thread is not None
        busy = active or update_active
        ready = self._config is not None and bool(self._config.model)
        quarantine_ready = (
            self._quarantine_folder is not None and not self._quarantine_missing
        )
        move_roots_ready = False
        quarantine_validation_message = ""
        if quarantine_ready and self._selected_folder is not None:
            try:
                validate_quarantine_roots(
                    self._selected_folder,
                    self._quarantine_folder,
                )
            except QuarantineError as error:
                quarantine_validation_message = str(error)
            else:
                move_roots_ready = True
        self.quarantine_validation_label.setText(quarantine_validation_message)
        self.quarantine_validation_label.setVisible(bool(quarantine_validation_message))
        self.select_button.setEnabled(not busy)
        self.server_url_input.setEnabled(not busy)
        self.test_connection_button.setEnabled(not busy)
        self.scan_button.setEnabled(
            not busy and self._selected_folder is not None and ready
        )
        self.cancel_button.setEnabled(
            (active and self._operation_kind in {"connection", "scan"})
            or (update_active and self._update_kind in {"check", "download"})
        )
        self.select_quarantine_button.setEnabled(not busy)
        self.move_quarantine_button.setEnabled(
            not busy
            and move_roots_ready
            and self._any_checked()
        )
        selection_text, selection_ready = self._selection_button_state()
        self.selection_button.setText(selection_text)
        self.selection_button.setEnabled(not busy and selection_ready)
        self.activity_history_button.setEnabled(not busy)
        self.settings_action.setEnabled(not busy)
        self.check_updates_action.setEnabled(not busy)

    def _selection_button_state(self) -> tuple[str, bool]:
        count = self.results_list.count()
        if count == 0:
            return "Select All", False
        for index in range(count):
            if self.results_list.item(index).checkState() != Qt.CheckState.Checked:
                return "Select All", True
        return "Clear All", True

    def _candidate_item_changed(self, item: QListWidgetItem) -> None:
        row = self.results_list.itemWidget(item)
        if row is not None:
            checkbox = row.findChild(QCheckBox, "candidateCheckBox")
            if checkbox is not None:
                checkbox.blockSignals(True)
                checkbox.setChecked(item.checkState() == Qt.CheckState.Checked)
                checkbox.blockSignals(False)
        self._update_controls()

    def _toggle_selection(self) -> None:
        count = self.results_list.count()
        if count == 0:
            return
        text, _ = self._selection_button_state()
        target = (
            Qt.CheckState.Unchecked
            if text == "Clear All"
            else Qt.CheckState.Checked
        )
        for index in range(count):
            self.results_list.item(index).setCheckState(target)
        self._update_controls()

    def _any_checked(self) -> bool:
        for index in range(self.results_list.count()):
            item = self.results_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                return True
        return False

    def _test_connection(self) -> None:
        if self._thread is not None or self._update_thread is not None:
            return
        try:
            config = build_vision_endpoint_config(
                self.server_url_input.text(), None, resolver=self._resolver
            )
        except EndpointValidationError as error:
            self._config = None
            self.connection_label.setText(str(error))
            self.model_label.setText("Model: not discovered")
            self._update_controls()
            return

        self._config = None
        self.connection_label.setText("Connecting to KoboldCpp...")
        self.model_label.setText("Model: not discovered")

        def operation(progress: Callable[[int, int], None]) -> Any:
            transport = self._transport_factory()
            self._active_transport = transport
            return self._discover(config, transport)

        self._start_operation("connection", operation)

    def _start_operation(
        self,
        kind: str,
        operation: Callable[[Callable[[int, int], None]], Any],
    ) -> None:
        if self._thread is not None or self._update_thread is not None:
            return
        self._generation += 1
        generation = self._generation
        self._operation_kind = kind
        self._operation_result = None
        self._operation_error = None

        thread = OperationThread(operation, self)
        thread.progress.connect(
            lambda done, total, token=generation: self._operation_progress(
                token, done, total
            )
        )
        thread.succeeded.connect(
            lambda result, token=generation: self._operation_succeeded(token, result)
        )
        thread.failed.connect(
            lambda error, token=generation: self._operation_failed(token, error)
        )
        thread.finished.connect(
            lambda token=generation: self._operation_finished(token)
        )
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._update_controls()
        thread.start()

    def _is_current(self, generation: int) -> bool:
        return generation == self._generation and not self._closing

    def _operation_progress(self, generation: int, done: int, total: int) -> None:
        if not self._is_current(generation):
            return
        if self._operation_kind == "scan":
            self._scan_phase = "progress"
            self._scan_progress = (done, total)
            self._render_live_scan_status()
        elif self._operation_kind == "quarantine":
            self.status_label.setText(
                f"Moving: {done} of {total} files processed."
            )

    def _operation_succeeded(self, generation: int, result: Any) -> None:
        if self._is_current(generation):
            self._operation_result = result

    def _operation_failed(self, generation: int, error: Exception) -> None:
        if self._is_current(generation):
            self._operation_error = error

    def _operation_finished(self, generation: int) -> None:
        # The start guards permit only one application operation at a time.
        thread = self._thread
        if thread is None:
            return

        kind = self._operation_kind
        result = self._operation_result
        error = self._operation_error
        current = self._is_current(generation)
        self._thread = None
        self._active_transport = None
        self._cancel_event = None
        self._operation_kind = None
        self._operation_result = None
        self._operation_error = None
        if not current:
            if self._closing and kind == "quarantine":
                self._record_quarantine(thread.result, thread.error)
            if self._closing:
                QTimer.singleShot(0, self.close)
            return
        if kind == "connection":
            self._finish_connection(result, error)
        elif kind == "scan":
            self._finish_scan(result, error)
        elif kind == "quarantine":
            self._finish_quarantine(result, error)
        self._update_controls()

    def _finish_connection(self, info: Any, error: Exception | None) -> None:
        if error is not None:
            self._config = None
            if isinstance(error, VisionConnectionError):
                self.connection_label.setText(str(error))
            else:
                self.connection_label.setText(
                    "The connection test could not be completed."
                )
            self.model_label.setText("Model: not discovered")
            return

        try:
            config = build_vision_endpoint_config(
                self.server_url_input.text(), info.model, resolver=self._resolver
            )
        except (EndpointValidationError, AttributeError):
            self._config = None
            self.connection_label.setText("The connection test could not be completed.")
            self.model_label.setText("Model: not discovered")
            return

        self._config = config
        self.connection_label.setText(f"KoboldCpp {info.version} is vision ready.")
        self.model_label.setText(f"Model: {config.model}")
        try:
            save_vision_endpoint_settings(self._settings_store, config)
        except Exception:
            pass

    def _request_scan(self) -> None:
        if (
            self._thread is not None
            or self._update_thread is not None
            or self._selected_folder is None
            or self._config is None
            or not self._config.model
        ):
            return

        is_http = self._config.origin.startswith("http://")
        if self._confirm_transfer is not None:
            accepted = bool(self._confirm_transfer(self._config.origin, is_http))
        else:
            text = (
                "Every supported image will leave this computer and be sent to "
                f"{self._config.origin}."
            )
            if is_http:
                text += " This connection uses unencrypted HTTP."
            accepted = (
                QMessageBox.question(
                    self,
                    "Send images to the server?",
                    text,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                == QMessageBox.StandardButton.Yes
            )
        if not accepted:
            return

        folder = self._selected_folder
        config = self._config
        try:
            self._scan_started_monotonic = self._monotonic()
        except Exception:
            self._scan_started_monotonic = None
        try:
            started_at = self._utc_now()
            if not isinstance(started_at, datetime):
                raise TypeError("The UTC clock must return a datetime")
        except Exception:
            started_at = datetime.now(timezone.utc)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        self._scan_started_at_utc = (
            started_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        self._scan_source_folder = str(folder)
        self._scan_model = config.model
        self._scan_recorded = False
        self._scan_phase = "preparing"
        self._scan_progress = None
        cancel_event = Event()
        self._cancel_event = cancel_event
        self.results_list.clear()
        self.results_empty_label.hide()
        def operation(progress: Callable[[int, int], None]) -> ScanSummary:
            transport = self._transport_factory()
            self._active_transport = transport
            return self._run_scan(
                folder,
                config,
                transport,
                scan=self._scan,
                cancel_event=cancel_event,
                progress=progress,
            )

        self._start_operation("scan", operation)
        self._scan_generation = self._generation
        self._render_live_scan_status()
        self._scan_timer.start()

    def _cancel_operation(self) -> None:
        if self._update_thread is not None and self._update_kind in {"check", "download"}:
            if self._update_cancel_event is not None:
                self._update_cancel_event.set()
            self.status_label.setText("Cancelling update operation...")
            self.cancel_button.setEnabled(False)
            return
        if self._thread is None or self._operation_kind not in {"connection", "scan"}:
            return
        if self._cancel_event is not None:
            self._cancel_event.set()
        transport = self._active_transport
        cancel_active = getattr(transport, "cancel_active", None)
        if callable(cancel_active):
            cancel_active()
        if self._operation_kind == "connection":
            self.connection_label.setText("Cancelling connection test...")
            self.cancel_button.setEnabled(False)
        else:
            self._scan_phase = "cancelling"
            self._render_live_scan_status()

    def _finish_scan(self, summary: Any, error: Exception | None) -> None:
        duration_ms, saved = self._record_scan(summary, error)
        self.results_list.clear()
        self.results_empty_label.hide()
        if error is not None:
            if isinstance(error, ScanError):
                status = str(error)
            else:
                status = "The scan could not be completed."
            self.status_label.setText(self._final_scan_status(status, duration_ms, saved))
            return
        if not isinstance(summary, ScanSummary):
            self.status_label.setText(self._final_scan_status(
                "The scan could not be completed.", duration_ms, saved
            ))
            return

        for candidate in summary.candidates:
            confidence = round(candidate.confidence * 100)
            category = candidate.category.replace("_", " ")
            item = QListWidgetItem(str(candidate.path))
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            item.setToolTip(
                f"{candidate.path}\n{category} "
                f"({confidence}%)\n{candidate.reason}"
            )
            preview = QPixmap.fromImage(QImage.fromData(candidate.thumbnail_png))
            if not preview.isNull():
                preview = preview.scaled(
                    96,
                    96,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            threshold = self._auto_select_confidence_percent / 100
            item.setCheckState(
                Qt.CheckState.Checked
                if candidate.confidence >= threshold
                else Qt.CheckState.Unchecked
            )
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.results_list.addItem(item)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(8, 7, 8, 7)
            row_layout.setSpacing(12)
            checkbox = QCheckBox()
            checkbox.setObjectName("candidateCheckBox")
            checkbox.setAccessibleName(f"Select {candidate.path}")
            checkbox.setChecked(item.checkState() == Qt.CheckState.Checked)
            checkbox.toggled.connect(
                lambda checked, candidate_item=item: candidate_item.setCheckState(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
            )
            row_layout.addWidget(checkbox, 0, Qt.AlignmentFlag.AlignVCenter)
            if not preview.isNull():
                preview_label = QLabel()
                preview_label.setObjectName("candidatePreview")
                preview_label.setPixmap(preview)
                preview_label.setFixedSize(96, 96)
                preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row_layout.addWidget(preview_label)
            details = QVBoxLayout()
            details.setSpacing(4)
            path_label = QLabel(str(candidate.path))
            path_label.setObjectName("candidatePath")
            path_label.setWordWrap(True)
            meta_label = QLabel(f"{category} | {confidence}%")
            meta_label.setObjectName("candidateMeta")
            reason_label = QLabel(candidate.reason)
            reason_label.setObjectName("candidateReason")
            reason_label.setWordWrap(True)
            details.addWidget(path_label)
            details.addWidget(meta_label)
            details.addWidget(reason_label)
            details.addStretch(1)
            row_layout.addLayout(details, 1)
            row.adjustSize()
            item.setSizeHint(QSize(0, max(110, row.sizeHint().height())))
            self.results_list.setItemWidget(item, row)
        self._refresh_heading_fonts()
        self._refresh_candidate_rows()
        self.results_empty_label.setVisible(
            not summary.candidates
            and summary.state
            in {ScanState.COMPLETED, ScanState.COMPLETED_WITH_SKIPS}
        )
        self.status_label.setText(
            self._final_scan_status(self._summary_text(summary), duration_ms, saved)
        )

    def _elapsed_ms(self) -> int:
        if self._scan_started_monotonic is None:
            return 0
        try:
            return max(0, int((self._monotonic() - self._scan_started_monotonic) * 1000))
        except Exception:
            return 0

    def _render_live_scan_status(self) -> None:
        if (
            self._thread is None
            or self._operation_kind != "scan"
            or self._scan_generation != self._generation
        ):
            return
        elapsed = format_duration(self._elapsed_ms())
        if self._scan_phase == "cancelling":
            text = "Cancelling scan..."
        elif self._scan_phase == "progress" and self._scan_progress is not None:
            done, total = self._scan_progress
            text = f"Scanning: {done} of {total} images processed."
        else:
            text = "Scanning: preparing the image list."
        self.status_label.setText(f"{text} Elapsed: {elapsed}.")

    def _record_scan(
        self,
        summary: Any,
        error: Exception | None,
        *,
        forced_outcome: str | None = None,
    ) -> tuple[int, bool]:
        self._scan_timer.stop()
        duration_ms = self._elapsed_ms()
        if self._scan_recorded:
            return duration_ms, True
        self._scan_recorded = True
        valid_summary = error is None and isinstance(summary, ScanSummary)
        outcomes = {
            ScanState.COMPLETED: "completed",
            ScanState.COMPLETED_WITH_SKIPS: "completed_with_skips",
            ScanState.CANCELLED: "cancelled",
            ScanState.FAILED: "failed",
        }
        outcome = (
            forced_outcome
            or (outcomes.get(summary.state, "failed") if valid_summary else "failed")
        )
        counts = (
            (
                summary.discovered,
                summary.analyzed,
                summary.candidate_count,
                summary.ordinary,
                summary.uncertain,
                summary.failed,
                summary.skipped_directories,
            )
            if valid_summary
            else (None,) * 7
        )
        try:
            record = ScanHistoryRecord(
                self._scan_started_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                self._scan_source_folder or str(Path.cwd()),
                self._scan_model or "Unknown",
                outcome,
                duration_ms,
                *counts,
            )
            saved = append_activity_history(self._settings_store, record)
        except Exception:
            saved = False
        return duration_ms, saved

    @staticmethod
    def _final_scan_status(status: str, duration_ms: int, saved: bool) -> str:
        result = f"{status} Elapsed: {format_duration(duration_ms)}."
        if not saved:
            result += " Activity history could not be saved."
        return result

    def _show_activity_history(self) -> None:
        if self._thread is not None or self._update_thread is not None:
            return
        ActivityHistoryDialog(self._settings_store, self).exec()

    def _show_settings(self) -> None:
        if self._thread is not None or self._update_thread is not None:
            return
        dialog = CandidateSelectionSettingsDialog(
            self._settings_store,
            self._auto_select_confidence_percent,
            self,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._auto_select_confidence_percent = dialog.selected_threshold
            self._include_test_releases = getattr(
                dialog,
                "selected_include_test_releases",
                load_include_test_releases(self._settings_store),
            )

    def _request_update_check(self) -> None:
        if self._thread is not None or self._update_thread is not None:
            return
        cancel_event = Event()
        self._update_cancel_event = cancel_event
        self.status_label.setText("Checking for updates...")

        def operation(progress: Callable[[int, int], None]) -> Any:
            return self._check_update(
                self._application_version,
                self._include_test_releases,
                cancel_event,
            )

        self._start_update_operation("check", operation)

    def _start_update_operation(
        self,
        kind: str,
        operation: Callable[[Callable[[int, int], None]], Any],
    ) -> None:
        if self._thread is not None or self._update_thread is not None:
            return
        self._update_generation += 1
        generation = self._update_generation
        self._update_kind = kind
        self._update_result = None
        self._update_error = None
        thread = OperationThread(operation, self)
        thread.progress.connect(
            lambda done, total, token=generation: self._update_progress(
                token, done, total
            )
        )
        thread.succeeded.connect(
            lambda result, token=generation: self._update_succeeded(token, result)
        )
        thread.failed.connect(
            lambda error, token=generation: self._update_failed(token, error)
        )
        thread.finished.connect(
            lambda token=generation: self._update_finished(token)
        )
        thread.finished.connect(thread.deleteLater)
        self._update_thread = thread
        self._update_controls()
        thread.start()

    def _update_is_current(self, generation: int) -> bool:
        return generation == self._update_generation and not self._closing

    def _update_progress(self, generation: int, done: int, total: int) -> None:
        if not self._update_is_current(generation) or self._update_kind != "download":
            return
        self.status_label.setText(f"Downloading update: {done} of {total} bytes.")

    def _update_succeeded(self, generation: int, result: Any) -> None:
        if self._update_is_current(generation):
            self._update_result = result

    def _update_failed(self, generation: int, error: Exception) -> None:
        if self._update_is_current(generation):
            self._update_error = error

    def _update_finished(self, generation: int) -> None:
        # The start guards permit only one application operation at a time.
        if self._update_thread is None:
            return
        kind = self._update_kind
        result = self._update_result
        error = self._update_error
        current = self._update_is_current(generation)
        self._update_thread = None
        self._update_cancel_event = None
        self._update_kind = None
        self._update_result = None
        self._update_error = None
        if not current:
            if self._closing:
                QTimer.singleShot(0, self.close)
            return
        if error is not None:
            if isinstance(error, UpdateCancelled):
                message = "The update operation was cancelled."
            elif isinstance(error, (UpdateTransportError, UpdateMetadataError, InstallError)):
                message = str(error)
            else:
                message = "The update operation could not be completed."
            self.status_label.setText(message)
            _update_message(self, QMessageBox.Icon.Warning, message)
            self._update_controls()
            return
        if kind == "check":
            self._finish_update_check(result)
        elif kind == "download":
            self._finish_update_download(result)
        elif kind == "install":
            self._finish_update_install(result)
        self._update_controls()

    def _finish_update_check(self, release: Any) -> None:
        if release is None:
            self.status_label.setText("Image Filter is up to date.")
            _update_message(
                self,
                QMessageBox.Icon.Information,
                f"Image Filter {self._application_version} is up to date.",
            )
            return
        if not isinstance(release, UpdateRelease):
            self.status_label.setText("The update information could not be used.")
            _update_message(
                self,
                QMessageBox.Icon.Warning,
                "The update information could not be used.",
            )
            return
        installation = detect_appimage_installation(self._update_environment)
        if installation is None:
            self.status_label.setText(
                f"Image Filter {release.version} is available. Automatic installation "
                "is only available from a writable AppImage."
            )
            _update_message(
                self,
                QMessageBox.Icon.Information,
                f"Image Filter {release.version} is available, but automatic installation is only available from a writable AppImage.",
            )
            return
        channel = "test" if release.prerelease else "stable"
        text = (
            f"Image Filter {release.version} ({channel}) is available.\n"
            f"Download size: {release.asset.size} bytes.\n\n"
            f"{release.notes}\n\n"
            "Checking and downloading contacts GitHub and shares your IP address with GitHub. Download this update?"
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Update available")
        box.setText(text)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        answer = box.exec()
        if answer != QMessageBox.StandardButton.Yes:
            self.status_label.setText(
                f"Image Filter {release.version} was not downloaded."
            )
            return
        self._update_installation = installation
        cancel_event = Event()
        self._update_cancel_event = cancel_event
        self.status_label.setText("Downloading update...")

        def operation(progress: Callable[[int, int], None]) -> Any:
            return self._download_update(
                release.asset,
                installation.path.parent,
                cancel_event,
                progress,
            )

        self._start_update_operation("download", operation)

    @staticmethod
    def _remove_verified_download(download: Any) -> None:
        if not isinstance(download, VerifiedDownload):
            return
        try:
            download.path.unlink(missing_ok=True)
        except OSError:
            pass

    def _finish_update_download(self, download: Any) -> None:
        if not isinstance(download, VerifiedDownload) or self._update_installation is None:
            self._remove_verified_download(download)
            self.status_label.setText("The downloaded update could not be used.")
            _update_message(
                self, QMessageBox.Icon.Warning, "The downloaded update could not be used."
            )
            return
        self._verified_update = download
        answer = QMessageBox.question(
            self,
            "Install update?",
            "The update was downloaded and verified. Install it now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self._remove_verified_download(download)
            self._verified_update = None
            self._update_installation = None
            self.status_label.setText("The update was downloaded but not installed.")
            return
        installation = self._update_installation
        self.status_label.setText("Installing update...")

        def operation(progress: Callable[[int, int], None]) -> Any:
            return self._install_update(installation, download)

        self._start_update_operation("install", operation)

    def _finish_update_install(self, result: Any) -> None:
        self._verified_update = None
        self._update_installation = None
        if not isinstance(result, InstallResult):
            self.status_label.setText("The installed update could not be verified.")
            _update_message(
                self, QMessageBox.Icon.Warning, "The installed update could not be verified."
            )
            return
        self.status_label.setText("The update was installed.")
        answer = QMessageBox.question(
            self,
            "Restart Image Filter?",
            "The update was installed. Restart Image Filter now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._restart_update(result.path):
            self.close()
        else:
            _update_message(
                self, QMessageBox.Icon.Warning, "Image Filter could not be restarted."
            )

    @staticmethod
    def _summary_text(summary: ScanSummary) -> str:
        prefixes = {
            ScanState.COMPLETED: "Completed",
            ScanState.COMPLETED_WITH_SKIPS: "Completed with skips",
            ScanState.CANCELLED: "Cancelled",
            ScanState.FAILED: "Failed",
        }

        def count(value: int, singular: str, plural: str | None = None) -> str:
            word = singular if value == 1 else (plural or singular + "s")
            return f"{value} {word}"

        return (
            f"{prefixes[summary.state]}: "
            f"{count(summary.discovered, 'discovered', 'discovered')}, "
            f"{count(summary.analyzed, 'analyzed', 'analyzed')}, "
            f"{count(summary.candidate_count, 'candidate')}, "
            f"{count(summary.ordinary, 'ordinary', 'ordinary')}, "
            f"{count(summary.uncertain, 'uncertain', 'uncertain')}, "
            f"{count(summary.failed, 'failed', 'failed')}, "
            f"{count(summary.skipped_directories, 'unreadable folder')}."
        )

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
        self.results_empty_label.hide()
        self.status_label.setText("Folder ready. Select Scan Folder to begin.")
        self._update_controls()

    def _choose_quarantine(self) -> None:
        if self._thread is not None or self._update_thread is not None:
            return
        starting_folder = (
            str(self._quarantine_folder) if self._quarantine_folder is not None else ""
        )
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select quarantine folder",
            starting_folder,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not selected:
            return

        folder = Path(selected)
        try:
            if self._selected_folder is not None:
                validate_quarantine_roots(self._selected_folder, folder)
            else:
                validate_quarantine_folder(folder)
        except QuarantineError as error:
            QMessageBox.warning(self, "Quarantine folder", str(error))
            return

        self._quarantine_folder = folder
        self._quarantine_missing = False
        self.quarantine_label.setText(str(folder))
        if not save_quarantine_folder(self._settings_store, folder):
            QMessageBox.warning(
                self,
                "Quarantine folder",
                "The quarantine folder could not be remembered.",
            )
        self._update_controls()

    def _request_quarantine_move(self) -> None:
        if (
            self._thread is not None
            or self._update_thread is not None
            or self._selected_folder is None
            or self._quarantine_folder is None
        ):
            return
        checked = [
            self.results_list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self.results_list.count())
            if self.results_list.item(index).checkState() == Qt.CheckState.Checked
        ]
        if not checked:
            return

        source_root = self._selected_folder
        quarantine_root = self._quarantine_folder
        try:
            plan = build_quarantine_plan(source_root, quarantine_root, checked)
        except QuarantineError as error:
            QMessageBox.warning(self, "Quarantine", str(error))
            return

        paths = tuple(str(candidate.path) for candidate in checked)
        folder = str(quarantine_root)
        if self._confirm_quarantine is not None:
            accepted = bool(self._confirm_quarantine(paths, folder))
        else:
            items = tuple(
                (str(item.source), str(item.destination)) for item in plan.items
            )
            title, heading, detailed = _quarantine_confirm_parts(items, folder)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(title)
            box.setText(heading)
            box.setDetailedText(detailed)
            move_button = box.addButton("Move", QMessageBox.ButtonRole.YesRole)
            box.addButton(QMessageBox.StandardButton.No)
            box.setDefaultButton(box.button(QMessageBox.StandardButton.No))
            box.exec()
            accepted = box.clickedButton() is move_button
        if not accepted:
            return

        try:
            self._quarantine_started_monotonic = self._monotonic()
        except Exception:
            self._quarantine_started_monotonic = None
        try:
            started_at = self._utc_now()
            if not isinstance(started_at, datetime):
                raise TypeError("The UTC clock must return a datetime")
        except Exception:
            started_at = datetime.now(timezone.utc)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        self._quarantine_started_at_utc = started_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        self._quarantine_source_folder = str(plan.source_root)
        self._quarantine_folder_snapshot = str(plan.quarantine_root)
        self._quarantine_batch_id = plan.batch_id
        self._quarantine_items = tuple(
            (str(item.source), str(item.destination)) for item in plan.items
        )
        self._quarantine_recorded = False

        self.status_label.setText(
            f"Moving: 0 of {len(checked)} files processed."
        )

        def operation(progress: Callable[[int, int], None]) -> QuarantineSummary:
            return self._run_quarantine(
                checked,
                source_root,
                quarantine_root,
                progress=progress,
            )

        self._moving = True
        self._start_operation("quarantine", operation)

    def _finish_quarantine(self, summary: Any, error: Exception | None) -> None:
        self._moving = False
        duration_ms, saved = self._record_quarantine(summary, error)
        if error is not None:
            self.status_label.setText(self._final_quarantine_status(
                "The move could not be completed.", duration_ms, saved
            ))
            return
        if not isinstance(summary, QuarantineSummary):
            self.status_label.setText(self._final_quarantine_status(
                "The move could not be completed.", duration_ms, saved
            ))
            return

        moved = set()
        skipped = 0
        for outcome in summary.outcomes:
            if outcome.status is MoveStatus.MOVED:
                moved.add(os.path.normcase(str(Path(outcome.source).resolve())))
            else:
                skipped += 1

        for index in range(self.results_list.count() - 1, -1, -1):
            item = self.results_list.item(index)
            candidate = item.data(Qt.ItemDataRole.UserRole)
            if candidate is not None and (
                os.path.normcase(str(Path(candidate.path).resolve())) in moved
            ):
                self.results_list.takeItem(index)

        total = len(summary.outcomes)
        moved_count = summary.moved_count
        if summary.state is QuarantineState.COMPLETED:
            status = f"Moved {moved_count} of {total} checked files to quarantine."
        elif summary.state is QuarantineState.COMPLETED_WITH_FAILURES:
            status = (f"Quarantine finished with failures: {moved_count} moved, "
                      f"{skipped} skipped.")
        else:
            failed = summary.failed_count
            conflicts = summary.conflict_count
            status = (f"No checked files could be moved: {failed} failed, "
                      f"{conflicts} conflicts.")
        self.status_label.setText(self._final_quarantine_status(status, duration_ms, saved))
        self.move_log_label.setText(str(summary.quarantine_root / MOVE_LOG_NAME))

    def _quarantine_elapsed_ms(self) -> int:
        if self._quarantine_started_monotonic is None:
            return 0
        try:
            return max(0, int((self._monotonic() - self._quarantine_started_monotonic) * 1000))
        except Exception:
            return 0

    def _record_quarantine(
        self, summary: Any, error: Exception | None
    ) -> tuple[int, bool]:
        duration_ms = self._quarantine_elapsed_ms()
        if self._quarantine_started_at_utc is None:
            return duration_ms, True
        if self._quarantine_recorded:
            return duration_ms, True
        self._quarantine_recorded = True
        valid = error is None and isinstance(summary, QuarantineSummary)
        if valid:
            outcomes = {
                QuarantineState.COMPLETED: "completed",
                QuarantineState.COMPLETED_WITH_FAILURES: "completed_with_failures",
                QuarantineState.FAILED: "failed",
            }
            files = tuple(
                QuarantineFileHistory(
                    str(item.source), str(item.destination), {
                        MoveStatus.MOVED: "moved",
                        MoveStatus.CONFLICT: "conflict",
                        MoveStatus.FAILED: "failed",
                    }[item.status], item.message
                )
                for item in summary.outcomes
            )
            values = (
                str(summary.quarantine_root), summary.batch_id,
                outcomes.get(summary.state, "failed"), summary.moved_count,
                summary.conflict_count, summary.failed_count, files,
            )
        else:
            message = "Outcome unavailable. Check the quarantine move log."
            files = tuple(
                QuarantineFileHistory(source, destination, "unknown", message)
                for source, destination in self._quarantine_items
            )
            values = (
                self._quarantine_folder_snapshot or str(Path.cwd()),
                self._quarantine_batch_id or "Unknown", "failed", None, None, None,
                files,
            )
        try:
            record = QuarantineHistoryRecord(
                self._quarantine_started_at_utc,
                self._quarantine_source_folder or str(Path.cwd()),
                values[0], values[1], values[2], duration_ms,
                values[3], values[4], values[5], values[6],
            )
            saved = append_activity_history(self._settings_store, record)
        except Exception:
            saved = False
        return duration_ms, saved

    @staticmethod
    def _final_quarantine_status(status: str, duration_ms: int, saved: bool) -> str:
        result = f"{status} Elapsed: {format_duration(duration_ms)}."
        if not saved:
            result += " Activity history could not be saved."
        return result

    def closeEvent(self, event: Any) -> None:
        if (
            self._thread is not None
            and self._operation_kind == "scan"
            and not self._scan_recorded
        ):
            self._record_scan(None, None, forced_outcome="cancelled")
        self._closing = True
        self._generation += 1
        self._update_generation += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
        transport = self._active_transport
        cancel_active = getattr(transport, "cancel_active", None)
        if callable(cancel_active):
            cancel_active()
        thread = self._thread
        if thread is not None:
            thread.quit()
            thread.wait(2000)
            if thread.isRunning():
                event.ignore()
                return
            if self._operation_kind == "quarantine":
                self._record_quarantine(thread.result, thread.error)
            self._thread = None
        update_thread = self._update_thread
        if update_thread is not None:
            if self._update_kind == "install" and update_thread.isRunning():
                event.ignore()
                return
            if self._update_cancel_event is not None:
                self._update_cancel_event.set()
            update_thread.quit()
            update_thread.wait(2000)
            if update_thread.isRunning():
                event.ignore()
                return
            self._update_thread = None
        event.accept()

    def _apply_style(self) -> None:
        # A stylesheet on the whole window freezes the inherited application
        # palette and font on some Qt platforms. Scope focus rules to controls.
        self._refresh_heading_fonts()
        for button in (self.cancel_button, self.activity_history_button,
                       self.select_quarantine_button, self.selection_button):
            button.setStyleSheet(
                "QPushButton#secondaryButton:focus { border: 2px solid palette(highlight); }"
            )
        self.results_list.setStyleSheet(
            "QListWidget#results:focus { border: 2px solid palette(highlight); }"
            "QListWidget#results::indicator { width: 0; height: 0; }"
        )

    def eventFilter(self, watched: Any, event: QEvent) -> bool:
        if watched is QApplication.instance() and event.type() == QEvent.Type.ApplicationFontChange:
            QTimer.singleShot(0, self._refresh_font_layout)
        elif watched is QApplication.instance() and event.type() == QEvent.Type.ApplicationPaletteChange:
            QTimer.singleShot(0, self._refresh_palette)
        elif (hasattr(self, "results_list")
              and watched is self.results_list.viewport()
              and event.type() == QEvent.Type.Resize):
            self._schedule_candidate_row_refresh()
        return super().eventFilter(watched, event)

    def _schedule_candidate_row_refresh(self) -> None:
        if self._closing or self._candidate_row_refresh_pending:
            return
        self._candidate_row_refresh_pending = True
        QTimer.singleShot(0, self._run_candidate_row_refresh)

    def _run_candidate_row_refresh(self) -> None:
        self._candidate_row_refresh_pending = False
        self._refresh_candidate_rows()

    def _refresh_font_layout(self) -> None:
        if self._closing:
            return
        # A widget-local focus stylesheet can pin the list's old font.
        self.results_list.setFont(QApplication.font())
        heading_font = QApplication.font()
        heading_font.setBold(True)
        for index in range(self.results_list.count()):
            row = self.results_list.itemWidget(self.results_list.item(index))
            if row is not None:
                row.setFont(QApplication.font())
                for child in row.findChildren(QWidget):
                    child.setFont(heading_font if child.objectName() in {
                        "candidatePath", "candidateMeta"
                    } else QApplication.font())
        self._refresh_heading_fonts()
        for button in (self.test_connection_button, self.select_button,
                       self.scan_button, self.cancel_button,
                       self.activity_history_button, self.select_quarantine_button,
                       self.move_quarantine_button, self.selection_button):
            button.setFont(QApplication.font())
            button.setMinimumSize(button.minimumSizeHint())
            button.setMinimumHeight(button.sizeHint().height() + 2)
            button.updateGeometry()
        self.content_scroll.widget().layout().activate()
        self.content_scroll.widget().adjustSize()
        self._refresh_candidate_rows()

    def _refresh_palette(self) -> None:
        if self._closing:
            return
        # Qt keeps the old palette for controls with local focus stylesheets.
        palette = QApplication.palette()
        self.results_list.setPalette(palette)
        for button in (self.cancel_button, self.activity_history_button,
                       self.select_quarantine_button, self.selection_button):
            button.setPalette(palette)
        self._update_candidate_selection_colors()

    def _update_candidate_selection_colors(self) -> None:
        for index in range(self.results_list.count()):
            item = self.results_list.item(index)
            row = self.results_list.itemWidget(item)
            if row is None:
                continue
            for name in ("candidatePath", "candidateMeta", "candidateReason"):
                label = row.findChild(QLabel, name)
                if label is None:
                    continue
                if item.isSelected():
                    palette = QPalette(QApplication.palette())
                    for group in (QPalette.ColorGroup.Active,
                                  QPalette.ColorGroup.Inactive,
                                  QPalette.ColorGroup.Disabled):
                        palette.setColor(group, QPalette.ColorRole.WindowText,
                                         palette.color(group, QPalette.ColorRole.HighlightedText))
                    label.setPalette(palette)
                else:
                    label.setPalette(QPalette())

    def _refresh_heading_fonts(self) -> None:
        heading_font = QApplication.font()
        heading_font.setBold(True)
        for label in self.findChildren(QLabel):
            if label.objectName() in {"title", "sectionHeading", "model",
                                      "candidatePath", "candidateMeta"}:
                label.setFont(heading_font)

    def _refresh_candidate_rows(self) -> None:
        if self._closing:
            return
        for index in range(self.results_list.count()):
            item = self.results_list.item(index)
            row = self.results_list.itemWidget(item)
            if row is None:
                continue
            layout = row.layout()
            margins = layout.contentsMargins()
            checkbox = row.findChild(QCheckBox, "candidateCheckBox")
            preview = row.findChild(QLabel, "candidatePreview")
            path = row.findChild(QLabel, "candidatePath")
            meta = row.findChild(QLabel, "candidateMeta")
            reason = row.findChild(QLabel, "candidateReason")
            if checkbox is None or path is None or meta is None or reason is None:
                continue
            width = (self.results_list.viewport().width() - margins.left()
                     - margins.right() - checkbox.sizeHint().width()
                     - (preview.width() if preview is not None else 0)
                     - layout.spacing() * (3 if preview is not None else 2) - 8)
            width = max(1, width)
            text_height = (path.heightForWidth(width) + meta.sizeHint().height()
                           + reason.heightForWidth(width) + 8)
            height = (max(checkbox.sizeHint().height(),
                          preview.height() if preview is not None else 0,
                          text_height) + margins.top() + margins.bottom())
            height = max(height, layout.sizeHint().height())
            if item.sizeHint().height() != height:
                item.setSizeHint(QSize(0, height))
