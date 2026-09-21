"""Main desktop window."""

from collections.abc import Callable, Iterable
import os
from pathlib import Path
from threading import Event
from typing import Any

from PySide6.QtCore import QSettings, QSize, QThread, QTimer, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
from img_ai_filter.scan_workflow import (
    ScanCandidate,
    ScanState,
    ScanSummary,
    run_server_scan,
)
from img_ai_filter.scanner import ScanError, ScanResult, scan_images
from img_ai_filter.settings import (
    ENDPOINT_URL_KEY,
    QUARANTINE_FOLDER_KEY,
    SettingsStatus,
    clear_quarantine_folder,
    load_quarantine_folder,
    load_vision_endpoint_settings,
    save_quarantine_folder,
    save_vision_endpoint_settings,
)
from img_ai_filter.vision_connection import VisionConnectionError, discover_koboldcpp


DEFAULT_SERVER_URL = "http://192.168.0.239:5001/v1/"


def _quarantine_confirm_parts(
    paths: Iterable[str], folder: str
) -> tuple[str, str, str]:
    path_list = [str(path) for path in paths]
    count = len(path_list)
    word = "file" if count == 1 else "files"
    heading = (
        f"Move {count} checked {word} to the quarantine folder {folder}? "
        "The transfer is a verified byte-for-byte copy, and a source file "
        "that changes after scanning is left in place."
    )
    return "Move checked files to quarantine?", heading, "\n".join(path_list)


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

        folder_row = QHBoxLayout()
        folder_row.setSpacing(16)
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(self.select_button)
        folder_row.addWidget(self.scan_button)
        folder_row.addWidget(self.cancel_button)

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

        self.forget_quarantine_button = QPushButton("Forget Quarantine Folder")
        self.forget_quarantine_button.setObjectName("secondaryButton")
        self.forget_quarantine_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.forget_quarantine_button.clicked.connect(self._forget_quarantine)

        self.move_quarantine_button = QPushButton("Move Checked to Quarantine")
        self.move_quarantine_button.setObjectName("primaryButton")
        self.move_quarantine_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.move_quarantine_button.setEnabled(False)
        self.move_quarantine_button.clicked.connect(self._request_quarantine_move)

        quarantine_row = QHBoxLayout()
        quarantine_row.setSpacing(12)
        quarantine_row.addWidget(self.quarantine_label, 1)
        quarantine_row.addWidget(self.select_quarantine_button)
        quarantine_row.addWidget(self.forget_quarantine_button)
        quarantine_row.addWidget(self.move_quarantine_button)

        self.move_log_label = QLabel("Move log: not written yet.")
        self.move_log_label.setObjectName("model")
        self.move_log_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.move_log_label.setWordWrap(True)

        self.status_label = QLabel("Select a folder to begin.")
        self.status_label.setObjectName("status")

        self.results_list = QListWidget()
        self.results_list.setObjectName("results")
        self.results_list.setAlternatingRowColors(True)
        self.results_list.setIconSize(QSize(96, 96))

        content = QVBoxLayout()
        content.setContentsMargins(28, 24, 28, 28)
        content.setSpacing(12)
        content.addWidget(server_heading)
        content.addLayout(server_row)
        content.addWidget(self.connection_label)
        content.addWidget(self.model_label)
        content.addSpacing(8)
        content.addWidget(folder_heading)
        content.addLayout(folder_row)
        content.addSpacing(8)
        content.addWidget(quarantine_heading)
        content.addLayout(quarantine_row)
        content.addWidget(self.move_log_label)
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
        self.server_url_input.textChanged.connect(self._server_url_edited)
        self.test_connection_button.clicked.connect(self._test_connection)
        self.scan_button.clicked.connect(self._request_scan)
        self.cancel_button.clicked.connect(self._cancel_scan)
        self.results_list.itemChanged.connect(lambda *_: self._update_controls())
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
        if self._thread is not None:
            return
        self._config = None
        self._show_no_model()
        self._update_controls()

    def _update_controls(self) -> None:
        active = self._thread is not None
        ready = self._config is not None and bool(self._config.model)
        quarantine_ready = (
            self._quarantine_folder is not None and not self._quarantine_missing
        )
        self.select_button.setEnabled(not active)
        self.server_url_input.setEnabled(not active)
        self.test_connection_button.setEnabled(not active)
        self.scan_button.setEnabled(
            not active and self._selected_folder is not None and ready
        )
        self.cancel_button.setEnabled(active and self._operation_kind == "scan")
        self.select_quarantine_button.setEnabled(not active)
        self.forget_quarantine_button.setEnabled(not active and quarantine_ready)
        self.move_quarantine_button.setEnabled(
            not active
            and self._selected_folder is not None
            and quarantine_ready
            and self._any_checked()
        )

    def _any_checked(self) -> bool:
        for index in range(self.results_list.count()):
            item = self.results_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                return True
        return False

    def _test_connection(self) -> None:
        if self._thread is not None:
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
        if self._thread is not None:
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
            lambda token=generation, current=thread: self._operation_finished(
                token, current
            )
        )
        self._thread = thread
        self._update_controls()
        thread.start()

    def _is_current(self, generation: int) -> bool:
        return generation == self._generation and not self._closing

    def _operation_progress(self, generation: int, done: int, total: int) -> None:
        if not self._is_current(generation):
            return
        if self._operation_kind == "scan":
            self.status_label.setText(
                f"Scanning: {done} of {total} images processed."
            )
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

    def _operation_finished(self, generation: int, thread: QThread) -> None:
        thread.deleteLater()
        if self._thread is not thread:
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
        cancel_event = Event()
        self._cancel_event = cancel_event
        self.results_list.clear()
        self.status_label.setText("Scanning: preparing the image list.")

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

    def _cancel_scan(self) -> None:
        if self._thread is None or self._operation_kind != "scan":
            return
        if self._cancel_event is not None:
            self._cancel_event.set()
        transport = self._active_transport
        cancel_active = getattr(transport, "cancel_active", None)
        if callable(cancel_active):
            cancel_active()
        self.status_label.setText("Cancelling scan...")

    def _finish_scan(self, summary: Any, error: Exception | None) -> None:
        self.results_list.clear()
        if error is not None:
            if isinstance(error, ScanError):
                self.status_label.setText(str(error))
            else:
                self.status_label.setText("The scan could not be completed.")
            return
        if not isinstance(summary, ScanSummary):
            self.status_label.setText("The scan could not be completed.")
            return

        for candidate in summary.candidates:
            confidence = round(candidate.confidence * 100)
            text = (
                f"{candidate.path} | {candidate.category.replace('_', ' ')} | "
                f"{candidate.reason} | {confidence}%"
            )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            item.setToolTip(
                f"{candidate.path}\n{candidate.category.replace('_', ' ')} "
                f"({confidence}%)\n{candidate.reason}"
            )
            preview = QPixmap.fromImage(QImage.fromData(candidate.thumbnail_png))
            if not preview.isNull():
                item.setIcon(QIcon(preview))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.results_list.addItem(item)
        self.status_label.setText(self._summary_text(summary))

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
        self.status_label.setText("Folder ready. Select Scan Folder to begin.")
        self._update_controls()

    def _choose_quarantine(self) -> None:
        if self._thread is not None:
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

    def _forget_quarantine(self) -> None:
        if self._thread is not None:
            return
        try:
            clear_quarantine_folder(self._settings_store)
        except Exception:
            pass
        self._quarantine_folder = None
        self._quarantine_missing = False
        self.quarantine_label.setText("No quarantine folder selected.")
        self._update_controls()

    def _request_quarantine_move(self) -> None:
        if (
            self._thread is not None
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
            build_quarantine_plan(source_root, quarantine_root, checked)
        except QuarantineError as error:
            QMessageBox.warning(self, "Quarantine", str(error))
            return

        paths = tuple(str(candidate.path) for candidate in checked)
        folder = str(quarantine_root)
        if self._confirm_quarantine is not None:
            accepted = bool(self._confirm_quarantine(paths, folder))
        else:
            title, heading, detailed = _quarantine_confirm_parts(paths, folder)
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
        if error is not None:
            self.status_label.setText("The move could not be completed.")
            return
        if not isinstance(summary, QuarantineSummary):
            self.status_label.setText("The move could not be completed.")
            return

        moved = set()
        skipped = 0
        for outcome in summary.outcomes:
            if outcome.status is MoveStatus.MOVED:
                moved.add(os.path.normcase(os.path.abspath(str(outcome.source))))
            else:
                skipped += 1

        for index in range(self.results_list.count() - 1, -1, -1):
            item = self.results_list.item(index)
            candidate = item.data(Qt.ItemDataRole.UserRole)
            if candidate is not None and (
                os.path.normcase(os.path.abspath(str(candidate.path))) in moved
            ):
                self.results_list.takeItem(index)

        total = len(summary.outcomes)
        moved_count = summary.moved_count
        if summary.state is QuarantineState.COMPLETED:
            self.status_label.setText(
                f"Moved {moved_count} of {total} checked files to quarantine."
            )
        elif summary.state is QuarantineState.COMPLETED_WITH_FAILURES:
            self.status_label.setText(
                f"Quarantine finished with failures: {moved_count} moved, "
                f"{skipped} skipped."
            )
        else:
            failed = summary.failed_count
            conflicts = summary.conflict_count
            self.status_label.setText(
                f"No checked files could be moved: {failed} failed, "
                f"{conflicts} conflicts."
            )
        self.move_log_label.setText(str(summary.quarantine_root / MOVE_LOG_NAME))

    def closeEvent(self, event: Any) -> None:
        self._closing = True
        self._generation += 1
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
            self._thread = None
        event.accept()

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
            QLineEdit#serverUrl {
                background: #ffffff;
                border: 1px solid #c4d2dc;
                border-radius: 4px;
                padding: 9px 11px;
            }
            QLabel#model {
                color: #40566b;
                font-weight: 700;
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
            QPushButton#secondaryButton {
                background: #ffffff;
                border: 2px solid #136f8a;
                border-radius: 4px;
                color: #136f8a;
                font-weight: 700;
                padding: 9px 18px;
            }
            QPushButton#secondaryButton:disabled {
                border-color: #aab7c0;
                color: #8898a4;
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
