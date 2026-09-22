from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
import time

from packaging.version import Version
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

import img_ai_filter.window as window_module
from img_ai_filter.settings import INCLUDE_TEST_RELEASES_KEY
from img_ai_filter.update_install import (
    AppImageInstallation,
    FileIdentity,
    InstallResult,
)
from img_ai_filter.update_release import UpdateAsset, UpdateRelease
from img_ai_filter.update_transport import VerifiedDownload
from img_ai_filter.update_transport import UpdateCancelled
from img_ai_filter.window import CandidateSelectionSettingsDialog, MainWindow


def _installation(path: Path) -> AppImageInstallation:
    file_stat = path.stat()
    return AppImageInstallation(
        path=path,
        identity=FileIdentity(
            device=file_stat.st_dev,
            inode=file_stat.st_ino,
            size=file_stat.st_size,
            mtime_ns=file_stat.st_mtime_ns,
        ),
    )


class MemoryStore:
    def __init__(self, seed: dict[str, str] | None = None) -> None:
        self.values = dict(seed or {})
        self.write_error = False

    def read(self, key: str):
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        if self.write_error:
            raise OSError("private settings failure")
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def _release(data: bytes = b"new appimage", prerelease: bool = False) -> UpdateRelease:
    version = Version("0.2.0b1" if prerelease else "0.2.0")
    return UpdateRelease(
        version=version,
        prerelease=prerelease,
        notes="Useful changes.",
        asset=UpdateAsset(
            name=f"ImageFilter-{version}-x86_64.AppImage",
            size=len(data),
            url="https://github.com/ChristopheAwad/img-ai-filter/releases/download/file",
            sha256=hashlib.sha256(data).hexdigest(),
        ),
    )


def test_launch_does_not_check_for_updates(qtbot) -> None:
    calls: list[tuple] = []
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        check_update=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    qtbot.addWidget(window)

    assert window.check_updates_button.text() == "Check for Updates"
    assert window.check_updates_button.isEnabled()
    assert calls == []


def test_manual_check_reports_up_to_date_in_background(qtbot, monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []
    boxes: list[QMessageBox] = []

    def check(version, include_prereleases, cancel_event):
        calls.append((version, include_prereleases))
        assert not cancel_event.is_set()
        return None

    def exec_box(box):
        boxes.append(box)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_box)
    window = MainWindow(
        settings_store=MemoryStore(), application_version="0.1.0", check_update=check
    )
    qtbot.addWidget(window)

    window.check_updates_button.click()
    qtbot.waitUntil(lambda: bool(boxes))

    assert calls == [("0.1.0", False)]
    assert [(b.windowTitle(), b.text()) for b in boxes] == [
        ("Updates", "Image Filter 0.1.0 is up to date.")
    ]
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert window.check_updates_button.isEnabled()


def test_test_release_setting_is_saved_and_used_by_later_check(qtbot, monkeypatch) -> None:
    store = MemoryStore()
    dialog = CandidateSelectionSettingsDialog(store, 90)
    qtbot.addWidget(dialog)
    assert not dialog.include_test_releases_checkbox.isChecked()
    dialog.include_test_releases_checkbox.setChecked(True)
    dialog.save_button.click()

    assert dialog.selected_include_test_releases is True
    assert store.values[INCLUDE_TEST_RELEASES_KEY] == "true"

    calls: list[bool] = []
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok
    )
    window = MainWindow(
        settings_store=store,
        application_version="0.1.0",
        check_update=lambda version, include, cancel: calls.append(include),
    )
    qtbot.addWidget(window)
    window.check_updates_button.click()
    qtbot.waitUntil(lambda: window._update_thread is None)
    assert calls == [True]


def test_available_update_outside_appimage_does_not_download(qtbot, monkeypatch) -> None:
    release = _release()
    downloads: list[object] = []
    boxes: list[QMessageBox] = []

    def exec_box(box):
        boxes.append(box)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_box)
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_environment={},
        check_update=lambda *args: release,
        download_update=lambda *args, **kwargs: downloads.append(args),
    )
    qtbot.addWidget(window)

    window.check_updates_button.click()
    qtbot.waitUntil(lambda: bool(boxes))

    assert "0.2.0" in boxes[0].text()
    assert "AppImage" in boxes[0].text()
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert downloads == []


def test_appimage_update_downloads_installs_and_restarts_after_confirmations(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    current = tmp_path / "ImageFilter.AppImage"
    current.write_bytes(b"old appimage")
    current.chmod(0o755)
    release = _release()
    stages: list[str] = []
    questions: list[str] = []
    detected_environments: list[dict[str, str]] = []

    def question(parent, title, text, *args):
        questions.append(title)
        return QMessageBox.StandardButton.Yes

    def exec_dialog(box):
        questions.append(box.windowTitle())
        return QMessageBox.StandardButton.Yes

    def download(asset, directory, cancel_event, progress):
        stages.append("download")
        path = directory / ".verified.download"
        data = b"new appimage"
        path.write_bytes(data)
        progress(len(data), len(data))
        return VerifiedDownload(path, len(data), hashlib.sha256(data).hexdigest())

    def install(installation, verified):
        stages.append("install")
        return InstallResult(installation.path, installation.path.with_name(
            installation.path.name + ".backup"
        ))

    def restart(path):
        stages.append(f"restart:{path}")
        return True

    def detect(environment):
        detected_environments.append(environment)
        return _installation(current)

    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(QMessageBox, "exec", exec_dialog)
    monkeypatch.setattr(window_module, "detect_appimage_installation", detect)
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_environment={"APPIMAGE": str(current)},
        check_update=lambda *args: release,
        download_update=download,
        install_update=install,
        restart_update=restart,
    )
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "close", lambda: stages.append("close"))

    window.check_updates_button.click()
    qtbot.waitUntil(lambda: "close" in stages)

    assert stages == ["download", "install", f"restart:{current}", "close"]
    assert questions == ["Update available", "Install update?", "Restart Image Filter?"]
    assert detected_environments == [{"APPIMAGE": str(current)}]


def test_update_notes_are_rendered_as_plain_text(qtbot, monkeypatch, tmp_path) -> None:
    current = tmp_path / "ImageFilter.AppImage"
    current.write_bytes(b"old appimage")
    current.chmod(0o755)
    release = replace(
        _release(),
        notes="<b>bold</b><a href='https://invalid.example/'>link</a>",
    )
    boxes: list[QMessageBox] = []
    detected_environments: list[dict[str, str]] = []

    def exec_dialog(box):
        boxes.append(box)
        return QMessageBox.StandardButton.No

    def detect(environment):
        detected_environments.append(environment)
        return _installation(current)

    monkeypatch.setattr(QMessageBox, "exec", exec_dialog)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    monkeypatch.setattr(window_module, "detect_appimage_installation", detect)
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_environment={"APPIMAGE": str(current)},
        check_update=lambda *args: release,
    )
    qtbot.addWidget(window)

    window.check_updates_button.click()
    qtbot.waitUntil(lambda: bool(boxes))

    assert boxes[0].windowTitle() == "Update available"
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert boxes[0].defaultButton() == boxes[0].button(QMessageBox.StandardButton.No)
    assert "<b>bold</b>" in boxes[0].text()
    assert detected_environments == [{"APPIMAGE": str(current)}]


def test_check_failure_is_safe_and_retry_is_enabled(qtbot, monkeypatch) -> None:
    boxes: list[QMessageBox] = []

    def exec_box(box):
        boxes.append(box)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_box)

    def fail(*args):
        raise RuntimeError("private exception detail")

    window = MainWindow(
        settings_store=MemoryStore(), application_version="0.1.0", check_update=fail
    )
    qtbot.addWidget(window)
    window.check_updates_button.click()
    qtbot.waitUntil(lambda: bool(boxes))

    assert "private exception detail" not in boxes[0].text()
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert window.check_updates_button.isEnabled()


def test_cancel_button_cancels_update_check_and_restores_controls(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok
    )

    def wait_for_cancel(version, include, cancel_event):
        while not cancel_event.is_set():
            time.sleep(0.001)
        raise UpdateCancelled("The update check was cancelled")

    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        check_update=wait_for_cancel,
    )
    qtbot.addWidget(window)
    window.check_updates_button.click()
    qtbot.waitUntil(lambda: window.cancel_button.isEnabled())

    window.cancel_button.click()
    qtbot.waitUntil(lambda: window._update_thread is None)

    assert window.check_updates_button.isEnabled()
    assert "cancel" in window.status_label.text().lower()


def test_close_during_install_does_not_block_gui_thread(qtbot, monkeypatch) -> None:
    window = MainWindow(settings_store=MemoryStore(), application_version="0.1.0")
    qtbot.addWidget(window)

    class RunningThread:
        def isRunning(self):
            return True

        def wait(self, *args):
            raise AssertionError("close must not wait synchronously during installation")

    window._update_thread = RunningThread()
    window._update_kind = "install"
    ignored: list[bool] = []

    class Event:
        def ignore(self):
            ignored.append(True)

        def accept(self):
            raise AssertionError("active installation cannot close immediately")

    window.closeEvent(Event())
    assert ignored == [True]
