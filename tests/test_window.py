from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QFileDialog

from img_ai_filter.scanner import ScanError, ScanResult
from img_ai_filter.window import MainWindow


def test_initial_window_has_folder_action_and_empty_state(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.select_button.text() == "Select Folder"
    assert window.status_label.text() == "Select a folder to begin."
    assert window.results_list.count() == 0


def test_cancelling_folder_dialog_keeps_current_results(qtbot, monkeypatch) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.folder_label.setText("Existing folder")
    window.results_list.addItem("existing.png")
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: "")

    window.select_button.click()

    assert window.folder_label.text() == "Existing folder"
    assert window.results_list.item(0).text() == "existing.png"


def test_valid_empty_folder_shows_completed_empty_scan(qtbot, monkeypatch, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path))

    window.select_button.click()

    assert window.folder_label.text() == str(tmp_path)
    assert window.status_label.text() == "No supported images found."
    assert window.results_list.count() == 0


def test_supported_images_are_displayed(qtbot, monkeypatch, tmp_path: Path) -> None:
    images = (tmp_path / "one.png", tmp_path / "nested" / "two.jpg")
    window = MainWindow(scan=lambda path: ScanResult(images=images, skipped_directories=()))
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path))

    window.select_button.click()

    assert window.status_label.text() == "2 images found."
    assert [window.results_list.item(index).text() for index in range(2)] == [str(path) for path in images]


def test_new_scan_replaces_old_results(qtbot, monkeypatch, tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.jpg"
    results = iter(
        [
            ScanResult(images=(first,), skipped_directories=()),
            ScanResult(images=(second,), skipped_directories=()),
        ]
    )
    window = MainWindow(scan=lambda path: next(results))
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path))

    window.select_button.click()
    window.select_button.click()

    assert window.results_list.count() == 1
    assert window.results_list.item(0).text() == str(second)


def test_scan_failure_is_visible_and_controls_remain_available(qtbot, monkeypatch, tmp_path: Path) -> None:
    def fail_scan(path: Path) -> ScanResult:
        raise ScanError("Cannot read selected folder: access denied")

    window = MainWindow(scan=fail_scan)
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(tmp_path))

    window.select_button.click()

    assert window.status_label.text() == "Cannot read selected folder: access denied"
    assert window.select_button.isEnabled()
    assert window.results_list.count() == 0


def test_window_has_no_move_delete_or_quarantine_action(qtbot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)

    button_text = " ".join(button.text().lower() for button in window.findChildren(QAbstractButton))

    assert "move" not in button_text
    assert "delete" not in button_text
    assert "quarantine" not in button_text
