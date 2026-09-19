from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QFileDialog

from img_ai_filter import scanner as scanner_module
from img_ai_filter.scanner import ScanResult
from img_ai_filter.window import MainWindow


def forbidden_scan(path: Path) -> ScanResult:
    raise AssertionError(f"Folder selection must not scan {path}")


def test_initial_window_is_waiting_for_a_folder(qtbot) -> None:
    window = MainWindow(scan=forbidden_scan)
    qtbot.addWidget(window)

    assert window.select_button.text() == "Select Folder"
    assert window.scan_button.text() == "Scan Folder"
    assert not window.scan_button.isEnabled()
    assert window.folder_label.text() == "No folder selected"
    assert window.status_label.text() == "Select a folder to begin."
    assert window.results_list.count() == 0


def test_selecting_folder_only_prepares_it_for_scanning(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    window = MainWindow(scan=forbidden_scan)
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

    window = MainWindow(scan=forbidden_scan)
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))

    window.select_button.click()

    assert window.scan_button.isEnabled()
    assert window.results_list.count() == 0


def test_cancelling_first_picker_keeps_initial_state(qtbot, monkeypatch) -> None:
    window = MainWindow(scan=forbidden_scan)
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
    window = MainWindow(scan=forbidden_scan)
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
    window = MainWindow(scan=forbidden_scan)
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
    window = MainWindow(scan=forbidden_scan)
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
    window = MainWindow(scan=forbidden_scan)
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
    window = MainWindow(scan=forbidden_scan)
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(root))

    window.select_button.click()

    assert window.folder_label.text() == str(root)
    assert window.scan_button.isEnabled()


def test_long_unicode_path_is_preserved_without_validation(qtbot, monkeypatch, tmp_path: Path) -> None:
    selected = tmp_path / ("long folder " * 12) / "résumé"
    window = MainWindow(scan=forbidden_scan)
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
    window = MainWindow(scan=forbidden_scan)
    qtbot.addWidget(window)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(tmp_path))

    window.select_button.click()

    assert source.read_bytes() == original
    assert source.stat().st_mtime_ns == original_stat.st_mtime_ns


def test_window_has_no_move_delete_or_quarantine_action(qtbot) -> None:
    window = MainWindow(scan=forbidden_scan)
    qtbot.addWidget(window)

    button_text = " ".join(button.text().lower() for button in window.findChildren(QAbstractButton))

    assert "move" not in button_text
    assert "delete" not in button_text
    assert "quarantine" not in button_text
