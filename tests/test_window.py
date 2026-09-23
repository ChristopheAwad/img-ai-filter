from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QAbstractButton, QCheckBox, QFileDialog, QFrame, QLabel, QPushButton

from img_ai_filter import scanner as scanner_module
from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.scanner import ScanResult
from img_ai_filter.image_payload import SourceIdentity
from img_ai_filter.scan_workflow import ScanCandidate, ScanState, ScanSummary
from img_ai_filter.window import MainWindow
from img_ai_filter.window import ActivityHistoryDialog, CandidateSelectionSettingsDialog


def forbidden_scan(path: Path) -> ScanResult:
    raise AssertionError(f"Folder selection must not scan {path}")


class _EmptyStore:
    def read(self, key: str) -> None:
        return None

    def write(self, key: str, value: str) -> None:
        return None

    def delete(self, key: str) -> None:
        return None


READY_CONFIG = build_vision_endpoint_config(
    "http://192.168.0.239:5001/v1/", model="test-model"
)


def selection_window() -> MainWindow:
    return MainWindow(
        scan=forbidden_scan,
        initial_config=READY_CONFIG,
        settings_store=_EmptyStore(),
    )


def main_action_buttons(window: MainWindow) -> tuple[QAbstractButton, ...]:
    return (
        window.test_connection_button,
        window.select_button,
        window.scan_button,
        window.cancel_button,
        window.activity_history_button,
        window.select_quarantine_button,
        window.move_quarantine_button,
        window.selection_button,
    )


def assert_buttons_are_not_compressed(window: MainWindow) -> None:
    for button in main_action_buttons(window):
        minimum = button.minimumSizeHint()
        assert button.width() >= minimum.width(), button.text()
        assert button.height() >= minimum.height(), button.text()


def assert_widget_is_in_scroll_view(window: MainWindow, widget) -> None:
    viewport = window.content_scroll.viewport()
    widget_rect = QRect(widget.mapTo(viewport, QPoint(0, 0)), widget.size())
    assert viewport.rect().contains(widget_rect)


def test_initial_window_is_waiting_for_a_folder(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)

    assert window.select_button.text() == "Select Folder"
    assert window.scan_button.text() == "Scan Folder"
    assert not window.scan_button.isEnabled()
    assert not window.cancel_button.isEnabled()
    assert window.folder_label.text() == "No folder selected"
    assert window.quarantine_label.text() == "No quarantine folder selected."
    assert not window.move_quarantine_button.isEnabled()
    assert not window.selection_button.isEnabled()
    assert window.status_label.text() == "Select a folder to begin."
    assert window.results_list.count() == 0


def test_review_controls_have_visible_keyboard_focus_styles(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)

    assert "QListWidget#results:focus" in window.results_list.styleSheet()
    assert "QPushButton#secondaryButton:focus" in window.selection_button.styleSheet()
    assert "outline: 0" not in window.results_list.styleSheet()


@pytest.fixture
def application_appearance(qtbot):
    app = QApplication.instance()
    original_palette = QPalette(app.palette())
    original_font = QFont(app.font())
    yield app
    app.setPalette(original_palette)
    app.setFont(original_font)
    app.processEvents()


def _test_palette(background: str, foreground: str, accent: str) -> QPalette:
    palette = QPalette()
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button):
            palette.setColor(group, role, QColor(background))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(group, role, QColor(foreground))
        palette.setColor(group, QPalette.ColorRole.Highlight, QColor(accent))
        palette.setColor(group, QPalette.ColorRole.HighlightedText, QColor(background))
    return palette


@pytest.mark.parametrize(
    ("background", "foreground", "accent"),
    [("#fcf9f3", "#171717", "#325cdd"), ("#181c25", "#faf5dc", "#f3d422"),
     ("#000000", "#ffffff", "#ffff00")],
)
def test_main_window_uses_system_palette(
    qtbot, application_appearance, background, foreground, accent
) -> None:
    application_appearance.setPalette(_test_palette(background, foreground, accent))
    window = selection_window()
    qtbot.addWidget(window)
    window.show()
    application_appearance.processEvents()

    for widget, role in (
        (window.centralWidget(), QPalette.ColorRole.Window),
        (window.server_url_input, QPalette.ColorRole.Base),
        (window.results_list, QPalette.ColorRole.Base),
        (window.status_label, QPalette.ColorRole.WindowText),
        (window.test_connection_button, QPalette.ColorRole.ButtonText),
    ):
        assert widget.palette().color(role) == QColor(
            background if role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base) else foreground
        )
    application_appearance.setPalette(_test_palette("#101010", "#f8f8f8", "#00ffff"))
    application_appearance.processEvents()
    application_appearance.processEvents()
    assert window.status_label.palette().color(QPalette.ColorRole.WindowText) == QColor("#f8f8f8")
    assert window.results_list.palette().color(QPalette.ColorRole.Base) == QColor("#101010")
    assert window.selection_button.palette().color(
        QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText
    ) == QColor("#f8f8f8")
    application_appearance.setPalette(_test_palette("#fafafa", "#111111", "#3030ee"))
    application_appearance.processEvents()
    application_appearance.processEvents()
    assert window.results_list.palette().color(QPalette.ColorRole.Base) == QColor("#fafafa")
    assert window.selection_button.palette().color(
        QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText
    ) == QColor("#111111")


def test_large_font_inherits_and_controls_fit_after_live_change(qtbot, application_appearance) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.resize(560, 400)
    window.show()
    application_appearance.processEvents()

    font = QFont(application_appearance.font())
    font.setPointSize(19)
    application_appearance.setFont(font)
    application_appearance.processEvents()
    application_appearance.processEvents()
    for widget in (window.status_label, window.server_url_input, window.select_button,
                   window.results_list, window.application_menu_button):
        assert widget.font().pointSize() == 19
    for button in main_action_buttons(window):
        assert button.font().pointSize() == 19, button.text()
        assert button.sizeHint().height() <= button.height(), button.text()


def test_candidate_row_tracks_large_font_and_palette_after_resize(
    qtbot, application_appearance, tmp_path
) -> None:
    application_appearance.setPalette(_test_palette("#000000", "#ffffff", "#ffff00"))
    font = QFont(application_appearance.font())
    font.setPointSize(19)
    application_appearance.setFont(font)
    window = selection_window()
    qtbot.addWidget(window)
    window.resize(560, 400)
    window.show()
    candidate = ScanCandidate(
        tmp_path / ("very-long-folder-name-" * 6) / "candidate.png", "screenshot",
        "A long reason for review. " * 10, 0.95,
        SourceIdentity(0, "a" * 64), b"not an image", 1, 1,
    )
    window._finish_scan(ScanSummary(ScanState.COMPLETED, (candidate,), 1, 1, 0, 0, 0, 0), None)
    application_appearance.processEvents()

    item = window.results_list.item(0)
    row = window.results_list.itemWidget(item)
    checkbox = row.findChild(QCheckBox, "candidateCheckBox")
    path = row.findChild(QLabel, "candidatePath")
    assert item.data(Qt.ItemDataRole.UserRole) is candidate
    assert item.checkState() == Qt.CheckState.Checked
    assert checkbox.isChecked()
    assert path.palette().color(QPalette.ColorRole.WindowText) == QColor("#ffffff")
    assert path.font().pointSize() == 19
    assert item.sizeHint().height() >= row.layout().sizeHint().height()

    window.resize(820, 600)
    application_appearance.processEvents()
    assert item.sizeHint().height() >= row.layout().sizeHint().height()


def test_existing_candidate_grows_after_font_change(qtbot, application_appearance, tmp_path) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.resize(560, 400)
    window.show()
    candidate = ScanCandidate(
        tmp_path / ("long-path-" * 12) / "example.png", "meme",
        "Review this image because it contains text. " * 12, 0.6,
        SourceIdentity(0, "a" * 64), b"", 1, 1,
    )
    window._finish_scan(ScanSummary(ScanState.COMPLETED, (candidate,), 1, 1, 0, 0, 0, 0), None)
    application_appearance.processEvents()
    item = window.results_list.item(0)
    original_height = item.sizeHint().height()

    font = QFont(application_appearance.font())
    font.setPointSize(19)
    application_appearance.setFont(font)
    application_appearance.processEvents()
    application_appearance.processEvents()
    row = window.results_list.itemWidget(item)
    assert row.findChild(QLabel, "candidatePath").font().pointSize() == 19
    assert item.sizeHint().height() > original_height
    assert item.sizeHint().height() >= row.layout().sizeHint().height()
    assert item.checkState() == Qt.CheckState.Unchecked


def test_selected_candidate_uses_highlight_text_after_theme_change(
    qtbot, application_appearance, tmp_path
) -> None:
    application_appearance.setPalette(_test_palette("#181c25", "#faf5dc", "#f3d422"))
    window = selection_window()
    qtbot.addWidget(window)
    window.show()
    candidate = ScanCandidate(
        tmp_path / "example.png", "meme", "Text on an image", 0.6,
        SourceIdentity(0, "a" * 64), b"", 1, 1,
    )
    window._finish_scan(ScanSummary(ScanState.COMPLETED, (candidate,), 1, 1, 0, 0, 0, 0), None)
    item = window.results_list.item(0)
    row = window.results_list.itemWidget(item)
    path = row.findChild(QLabel, "candidatePath")
    reason = row.findChild(QLabel, "candidateReason")
    window.results_list.setCurrentItem(item)
    application_appearance.processEvents()
    assert path.palette().color(QPalette.ColorRole.WindowText) == QColor("#181c25")
    assert reason.palette().color(QPalette.ColorRole.WindowText) == QColor("#181c25")

    application_appearance.setPalette(_test_palette("#000000", "#ffffff", "#00ffff"))
    application_appearance.processEvents()
    application_appearance.processEvents()
    assert path.palette().color(QPalette.ColorRole.WindowText) == QColor("#000000")
    window.results_list.clearSelection()
    application_appearance.processEvents()
    assert path.palette().color(QPalette.ColorRole.WindowText) == QColor("#ffffff")


def test_child_dialogs_follow_system_palette_and_font(qtbot, application_appearance) -> None:
    application_appearance.setPalette(_test_palette("#000000", "#ffffff", "#ffff00"))
    font = QFont(application_appearance.font())
    font.setPointSize(16)
    application_appearance.setFont(font)
    window = selection_window()
    qtbot.addWidget(window)
    for dialog in (CandidateSelectionSettingsDialog(_EmptyStore(), 90, window),
                   ActivityHistoryDialog(_EmptyStore(), window)):
        qtbot.addWidget(dialog)
        dialog.show()
        application_appearance.processEvents()
        assert dialog.palette().color(QPalette.ColorRole.Window) == QColor("#000000")
        assert dialog.font().pointSize() == 16
        for label in dialog.findChildren(QLabel):
            assert label.palette().color(QPalette.ColorRole.WindowText) == QColor("#ffffff")


def test_application_commands_are_in_fixed_header_menu(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)

    header = window.findChild(QFrame, "header")
    assert window.application_menu_button.parent() is header
    assert window.application_menu_button.text() == "..."
    assert window.application_menu_button.toolTip() == "Application menu"
    assert [action.text() for action in window.application_menu.actions()] == [
        "Settings",
        "Check for Updates",
    ]
    assert not any(
        isinstance(button, QPushButton)
        and button.text() in {"Settings", "Check for Updates"}
        for button in window.findChildren(QAbstractButton)
    )


def test_header_menu_stays_visible_at_minimum_window_size(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.resize(560, 400)
    window.show()

    qtbot.waitUntil(window.isVisible)

    button = window.application_menu_button
    header = window.findChild(QFrame, "header")
    title = window.findChild(QLabel, "title")
    button_rect = QRect(button.mapTo(header, QPoint(0, 0)), button.size())
    title_rect = QRect(title.mapTo(header, QPoint(0, 0)), title.size())
    assert button.isVisible()
    assert header.rect().contains(button_rect)
    assert not button_rect.intersects(title_rect)


def test_window_has_no_forget_quarantine_action(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)

    assert not any(
        "forget quarantine" in button.text().lower()
        for button in window.findChildren(QAbstractButton)
    )


def test_minimum_window_size_does_not_compress_action_buttons(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.resize(560, 400)
    window.show()

    qtbot.waitUntil(window.isVisible)

    assert_buttons_are_not_compressed(window)
    for button in main_action_buttons(window):
        window.content_scroll.ensureWidgetVisible(button)
        qtbot.wait(1)
        assert_widget_is_in_scroll_view(window, button)


def test_minimum_window_uses_vertical_not_horizontal_body_scrolling(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.resize(560, 400)
    window.show()

    qtbot.waitUntil(window.isVisible)

    assert window.content_scroll.horizontalScrollBar().maximum() == 0
    assert (
        window.content_scroll.widget().width()
        <= window.content_scroll.viewport().width()
    )
    assert window.content_scroll.verticalScrollBar().maximum() > 0
    assert window.folder_label.width() > 0
    assert window.quarantine_label.width() > 0


def test_short_window_keeps_header_visible_when_body_scrolls(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.resize(560, 400)
    window.show()

    qtbot.waitUntil(window.isVisible)
    header = window.findChild(QFrame, "header")
    assert header is not None
    header_position = header.pos()

    window.content_scroll.ensureWidgetVisible(window.results_list)
    qtbot.wait(1)

    assert window.content_scroll.verticalScrollBar().value() > 0
    assert header.isVisible()
    assert header.pos() == header_position
    assert (
        window.results_list.height()
        >= window.results_list.minimumSizeHint().height()
    )


def test_default_window_size_does_not_compress_action_buttons(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(window.isVisible)

    assert_buttons_are_not_compressed(window)
    assert window.content_scroll.horizontalScrollBar().maximum() == 0
    assert window.content_scroll.verticalScrollBar().maximum() == 0
    assert_widget_is_in_scroll_view(window, window.results_list)


def test_long_main_window_text_wraps_without_horizontal_overflow(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    repeated = "very long folder name " * 20
    window.folder_label.setText(repeated)
    window.quarantine_label.setText(repeated)
    window.status_label.setText(repeated)
    window.move_log_label.setText(repeated)
    window.resize(560, 400)
    window.show()

    qtbot.waitUntil(window.isVisible)

    assert window.folder_label.wordWrap()
    assert window.quarantine_label.wordWrap()
    assert window.status_label.wordWrap()
    assert window.move_log_label.wordWrap()
    assert window.content_scroll.horizontalScrollBar().maximum() == 0
    assert window.folder_label.width() > 0
    assert window.folder_label.height() > 0
    assert window.quarantine_label.width() > 0
    assert window.quarantine_label.height() > 0
    assert_buttons_are_not_compressed(window)


def test_selecting_folder_only_prepares_it_for_scanning(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))

    window.select_button.click()

    assert window.folder_label.text() == str(tmp_path)
    assert window.status_label.text() == "Folder ready. Select Scan Folder to begin."
    assert window.scan_button.isEnabled()
    assert window.results_list.count() == 0


def test_selecting_large_folder_does_not_inspect_or_display_files(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    for index in range(1_000):
        (tmp_path / f"image-{index}.png").write_bytes(b"not decoded")

    def forbidden_traversal(path):
        raise AssertionError(f"Folder selection must not traverse {path}")

    monkeypatch.setattr(scanner_module.os, "scandir", forbidden_traversal)

    window = selection_window()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))

    window.select_button.click()

    assert window.scan_button.isEnabled()
    assert window.results_list.count() == 0


def test_cancelling_first_picker_keeps_initial_state(qtbot, monkeypatch) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: "")

    window.select_button.click()

    assert window.folder_label.text() == "No folder selected"
    assert window.status_label.text() == "Select a folder to begin."
    assert not window.scan_button.isEnabled()
    assert window.results_list.count() == 0


def test_cancelling_later_picker_preserves_complete_state(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    selections = iter([str(tmp_path), ""])
    window = selection_window()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: next(selections))

    window.select_button.click()
    window.results_list.addItem("existing candidate")
    window.status_label.setText("Existing scan status")
    window.select_button.click()

    assert window.folder_label.text() == str(tmp_path)
    assert window.status_label.text() == "Existing scan status"
    assert window.scan_button.isEnabled()
    assert window.results_list.item(0).text() == "existing candidate"


def test_selecting_different_folder_clears_old_result_state(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    selections = iter([str(first), str(second)])
    window = selection_window()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: next(selections))

    window.select_button.click()
    window.results_list.addItem("old candidate")
    window.status_label.setText("Old scan status")
    window.select_button.click()

    assert window.folder_label.text() == str(second)
    assert window.status_label.text() == "Folder ready. Select Scan Folder to begin."
    assert window.scan_button.isEnabled()
    assert window.results_list.count() == 0


def test_folder_picker_requests_native_directory_only_mode(qtbot, monkeypatch) -> None:
    calls = []
    window = selection_window()
    qtbot.addWidget(window)

    def capture_dialog(*args):
        calls.append(args)
        return ""

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", capture_dialog)

    window.select_button.click()

    assert calls[0][2] == ""
    options = calls[0][3]
    assert options & QFileDialog.Option.ShowDirsOnly
    assert not options & QFileDialog.Option.DontUseNativeDialog


def test_folder_picker_reopens_at_last_selected_folder(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    starting_folders = []
    selections = iter([str(tmp_path), "", ""])
    window = selection_window()
    qtbot.addWidget(window)

    def choose_folder(parent, caption, starting_folder, options):
        starting_folders.append(starting_folder)
        return next(selections)

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", choose_folder)

    window.select_button.click()
    window.select_button.click()
    window.select_button.click()

    assert starting_folders == ["", str(tmp_path), str(tmp_path)]
    assert window.folder_label.text() == str(tmp_path)
    assert window.status_label.text() == "Folder ready. Select Scan Folder to begin."


def test_boundary_path_is_preserved_without_scanning(qtbot, monkeypatch, tmp_path: Path) -> None:
    root = Path(tmp_path.anchor)
    window = selection_window()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(root))

    window.select_button.click()

    assert window.folder_label.text() == str(root)
    assert window.scan_button.isEnabled()


def test_long_unicode_path_is_preserved_without_validation(qtbot, monkeypatch, tmp_path: Path) -> None:
    selected = tmp_path / ("long folder " * 12) / "résumé"
    window = selection_window()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(selected))

    window.select_button.click()

    assert window.folder_label.text() == str(selected)
    assert window.scan_button.isEnabled()


def test_folder_selection_does_not_change_source_file(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "source.png"
    original = b"source bytes"
    source.write_bytes(original)
    original_stat = source.stat()
    window = selection_window()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))

    window.select_button.click()

    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns


def test_window_has_no_delete_action(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)

    button_text = " ".join(button.text().lower() for button in window.findChildren(QAbstractButton))

    assert "delete" not in button_text


def test_window_has_quarantine_controls_but_no_move_without_quarantine(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)

    assert window.select_quarantine_button.text() == "Select Quarantine Folder"
    assert window.move_quarantine_button.text() == "Move Checked to Quarantine"
    assert not window.move_quarantine_button.isEnabled()


def test_quarantine_controls_are_in_the_visible_window(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(window.isVisible)

    assert_widget_is_in_scroll_view(window, window.quarantine_label)
    assert_widget_is_in_scroll_view(window, window.select_quarantine_button)
    assert_widget_is_in_scroll_view(window, window.move_quarantine_button)
    assert_widget_is_in_scroll_view(window, window.move_log_label)
