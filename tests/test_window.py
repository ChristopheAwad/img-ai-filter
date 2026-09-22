from pathlib import Path

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QAbstractButton, QFileDialog, QFrame

from img_ai_filter import scanner as scanner_module
from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.scanner import ScanResult
from img_ai_filter.window import MainWindow


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
        window.settings_button,
        window.select_quarantine_button,
        window.forget_quarantine_button,
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
    assert window.forget_quarantine_button.text() == "Forget Quarantine Folder"
    assert not window.move_quarantine_button.isEnabled()


def test_quarantine_controls_are_in_the_visible_window(qtbot) -> None:
    window = selection_window()
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(window.isVisible)

    assert_widget_is_in_scroll_view(window, window.quarantine_label)
    assert_widget_is_in_scroll_view(window, window.select_quarantine_button)
    assert_widget_is_in_scroll_view(window, window.forget_quarantine_button)
    assert_widget_is_in_scroll_view(window, window.move_quarantine_button)
    assert_widget_is_in_scroll_view(window, window.move_log_label)
