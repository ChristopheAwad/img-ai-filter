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
from img_ai_filter.update_transport import UpdateCancelled, UpdateTransportError
from img_ai_filter.update_windows import WindowsInstallation
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


def _windows_release(kind: str = "zip", extra: bool = True) -> UpdateRelease:
    from img_ai_filter.packaging import windows_artifact_names

    version = Version("0.2.0")
    names = windows_artifact_names("0.2.0", system="Windows", machine="AMD64")
    wanted = names.portable_zip if kind == "zip" else names.installer
    other = names.installer if kind == "zip" else names.portable_zip
    data = b"windows payload"
    asset = UpdateAsset(
        name=wanted,
        size=len(data),
        url=f"https://github.com/ChristopheAwad/img-ai-filter/releases/download/v0.2.0/{wanted}",
        sha256=hashlib.sha256(data).hexdigest(),
    )
    extra_asset = None
    if extra:
        extra_asset = UpdateAsset(
            name=other,
            size=len(data),
            url=f"https://github.com/ChristopheAwad/img-ai-filter/releases/download/v0.2.0/{other}",
            sha256=hashlib.sha256(data).hexdigest(),
        )
    return UpdateRelease(
        version=version,
        prerelease=False,
        notes="Windows changes.",
        asset=asset,
        extra_asset=extra_asset,
    )


def _windows_installation(path: Path, kind: str = "portable") -> WindowsInstallation:
    file_stat = path.stat()
    return WindowsInstallation(
        path=path,
        kind=kind,
        identity=FileIdentity(
            device=file_stat.st_dev,
            inode=file_stat.st_ino,
            size=file_stat.st_size,
            mtime_ns=file_stat.st_mtime_ns,
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

    assert window.check_updates_action.text() == "Check for Updates"
    assert window.check_updates_action.isEnabled()
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

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    assert calls == [("0.1.0", False)]
    assert [(b.windowTitle(), b.text()) for b in boxes] == [
        ("Updates", "Image Filter 0.1.0 is up to date.")
    ]
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert window.check_updates_action.isEnabled()


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
    window.check_updates_action.trigger()
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

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    assert "0.2.0" in boxes[0].text()
    assert "AppImage" in boxes[0].text()
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert downloads == []
    assert window.status_label.text() == (
        "Image Filter 0.2.0 is available. Automatic installation is only "
        "available from a writable AppImage."
    )


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

    window.check_updates_action.trigger()
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

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    assert boxes[0].windowTitle() == "Update available"
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert boxes[0].defaultButton() == boxes[0].button(QMessageBox.StandardButton.No)
    assert "<b>bold</b>" in boxes[0].text()
    assert detected_environments == [{"APPIMAGE": str(current)}]
    assert window.status_label.text() == "Image Filter 0.2.0 was not downloaded."


def test_declining_install_sets_terminal_status(qtbot, monkeypatch, tmp_path) -> None:
    current = tmp_path / "ImageFilter.AppImage"
    current.write_bytes(b"old appimage")
    current.chmod(0o755)
    release = _release()
    downloaded = tmp_path / ".verified.download"

    monkeypatch.setattr(
        window_module,
        "detect_appimage_installation",
        lambda environment: _installation(current),
    )
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    def download(asset, directory, cancel_event, progress):
        downloaded.write_bytes(b"new appimage")
        return VerifiedDownload(
            downloaded,
            downloaded.stat().st_size,
            hashlib.sha256(downloaded.read_bytes()).hexdigest(),
        )

    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_environment={"APPIMAGE": str(current)},
        check_update=lambda *args: release,
        download_update=download,
    )
    qtbot.addWidget(window)

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: window._update_thread is None and not downloaded.exists())

    assert window.status_label.text() == "The update was downloaded but not installed."


def test_invalid_update_results_set_terminal_statuses(qtbot, monkeypatch) -> None:
    boxes: list[QMessageBox] = []
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda box: boxes.append(box) or QMessageBox.StandardButton.Ok,
    )
    window = MainWindow(settings_store=MemoryStore(), application_version="0.1.0")
    qtbot.addWidget(window)

    window.status_label.setText("Checking for updates...")
    window._finish_update_check(object())
    assert window.status_label.text() == "The update information could not be used."

    window.status_label.setText("Downloading update...")
    window._finish_update_download(object())
    assert window.status_label.text() == "The downloaded update could not be used."

    window.status_label.setText("Installing update...")
    window._finish_update_install(object())
    assert window.status_label.text() == "The installed update could not be verified."
    assert len(boxes) == 3


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
    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    assert "private exception detail" not in boxes[0].text()
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert window.check_updates_action.isEnabled()


def test_transport_error_is_shown_safely_and_allows_retry(qtbot, monkeypatch) -> None:
    boxes: list[QMessageBox] = []

    def exec_box(box):
        boxes.append(box)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_box)

    def fail(*args):
        raise UpdateTransportError("GitHub could not be reached")

    window = MainWindow(
        settings_store=MemoryStore(), application_version="0.1.0", check_update=fail
    )
    qtbot.addWidget(window)
    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    message = "GitHub could not be reached"
    assert window.status_label.text() == message
    assert boxes[0].windowTitle() == "Updates"
    assert boxes[0].text() == message
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert window.check_updates_action.isEnabled()

    boxes.clear()
    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    assert boxes[0].text() == message
    assert window.check_updates_action.isEnabled()


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
    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: window.cancel_button.isEnabled())

    window.cancel_button.click()
    qtbot.waitUntil(lambda: window._update_thread is None)

    assert window.check_updates_action.isEnabled()
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


def test_windows_source_run_shows_manual_message_without_appimage_text(
    qtbot, monkeypatch
) -> None:
    release = _windows_release()
    downloads: list[object] = []
    boxes: list[QMessageBox] = []
    opened: list[str] = []

    def exec_box(box):
        boxes.append(box)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_box)
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_platform="win32",
        detect_windows_update=lambda: None,
        open_update_url=opened.append,
        check_update=lambda *args: release,
        download_update=lambda *args, **kwargs: downloads.append(args),
    )
    qtbot.addWidget(window)

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    assert "0.2.0" in boxes[0].text()
    assert "AppImage" not in boxes[0].text()
    assert "AppImage" not in window.status_label.text()
    assert ".zip" in boxes[0].text()
    assert "setup" in boxes[0].text()
    assert "SHA256SUMS" in boxes[0].text()
    assert boxes[0].textFormat() == Qt.TextFormat.PlainText
    assert downloads == []
    assert opened == []


def test_windows_manual_dialog_link_opens_releases_page(qtbot, monkeypatch) -> None:
    release = _windows_release()
    boxes: list[QMessageBox] = []
    opened: list[str] = []

    def exec_box(box):
        boxes.append(box)
        link = next(
            button
            for button in box.buttons()
            if button.text() == "Open releases page"
        )
        link.click()
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_box)
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_platform="win32",
        detect_windows_update=lambda: None,
        open_update_url=opened.append,
        check_update=lambda *args: release,
    )
    qtbot.addWidget(window)

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    assert opened == [
        "https://github.com/ChristopheAwad/img-ai-filter/releases/tag/v0.2.0"
    ]


def test_windows_portable_downloads_stages_and_restarts(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    app_dir = tmp_path / "ImageFilter-0.1.0-windows-x86_64"
    app_dir.mkdir()
    exe = app_dir / "image-filter.exe"
    exe.write_bytes(b"old exe")
    release = _windows_release(kind="zip")
    stages: list[str] = []
    scripts: list[str] = []

    def download(asset, directory, cancel_event, progress):
        stages.append("download")
        assert asset.name.endswith(".zip")
        data = b"windows payload"
        path = directory / ".verified.zip"
        path.write_bytes(data)
        progress(len(data), len(data))
        return VerifiedDownload(path, len(data), hashlib.sha256(data).hexdigest())

    def stage(verified, target_dir):
        stages.append("stage")
        staging = target_dir.with_name(target_dir.name + ".update-staging")
        staging.mkdir()
        (staging / "image-filter.exe").write_bytes(b"new")
        return staging

    def run_script(script):
        stages.append("run-script")
        scripts.append(str(script))
        return True

    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_platform="win32",
        detect_windows_update=lambda: _windows_installation(exe, "portable"),
        check_update=lambda *args: release,
        download_update=download,
        stage_windows_update=stage,
        run_restart_script=run_script,
    )
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "close", lambda: stages.append("close"))

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: "close" in stages)

    assert stages == ["download", "stage", "run-script", "close"]
    assert scripts[0].endswith(".update-apply.bat")


def test_windows_installer_downloads_and_launches_setup(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    app_dir = tmp_path / "Image Filter"
    app_dir.mkdir()
    exe = app_dir / "image-filter.exe"
    exe.write_bytes(b"old exe")
    release = _windows_release(kind="setup")
    stages: list[str] = []
    launched: list[str] = []

    def download(asset, directory, cancel_event, progress):
        stages.append("download")
        assert asset.name.endswith("-setup.exe")
        data = b"windows payload"
        path = directory / ".verified.exe"
        path.write_bytes(data)
        return VerifiedDownload(path, len(data), hashlib.sha256(data).hexdigest())

    def launch(path):
        launched.append(str(path))
        return True

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes
    )
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_platform="win32",
        detect_windows_update=lambda: _windows_installation(exe, "installed"),
        check_update=lambda *args: release,
        download_update=download,
        launch_installer_update=launch,
    )
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "close", lambda: stages.append("close"))

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: "close" in stages)

    assert stages == ["download", "close"]
    assert launched and launched[0].endswith(".verified.exe")
    assert "installer was launched" in window.status_label.text().lower()


def test_windows_installer_kind_with_only_zip_stays_manual(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    app_dir = tmp_path / "Image Filter"
    app_dir.mkdir()
    exe = app_dir / "image-filter.exe"
    exe.write_bytes(b"old exe")
    release = _windows_release(kind="zip", extra=False)
    downloads: list[object] = []
    boxes: list[QMessageBox] = []

    def exec_box(box):
        boxes.append(box)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_box)
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_platform="win32",
        detect_windows_update=lambda: _windows_installation(exe, "installed"),
        open_update_url=lambda url: None,
        check_update=lambda *args: release,
        download_update=lambda *args, **kwargs: downloads.append(args),
    )
    qtbot.addWidget(window)

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: bool(boxes))

    assert downloads == []
    assert "AppImage" not in boxes[0].text()
    assert "matching file" in boxes[0].text()


def test_windows_decline_download_sets_terminal_status(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    exe = app_dir / "image-filter.exe"
    exe.write_bytes(b"old exe")
    release = _windows_release(kind="zip")
    downloads: list[object] = []

    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No
    )
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_platform="win32",
        detect_windows_update=lambda: _windows_installation(exe, "portable"),
        check_update=lambda *args: release,
        download_update=lambda *args, **kwargs: downloads.append(args),
    )
    qtbot.addWidget(window)

    window.check_updates_action.trigger()
    qtbot.waitUntil(lambda: window._update_thread is None)

    assert window.status_label.text() == "Image Filter 0.2.0 was not downloaded."
    assert downloads == []


def test_windows_invalid_download_sets_terminal_status(
    qtbot, monkeypatch, tmp_path: Path
) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    exe = app_dir / "image-filter.exe"
    exe.write_bytes(b"old exe")
    monkeypatch.setattr(
        QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok
    )
    window = MainWindow(
        settings_store=MemoryStore(),
        application_version="0.1.0",
        update_platform="win32",
    )
    qtbot.addWidget(window)
    window._update_windows_installation = _windows_installation(exe, "portable")

    window.status_label.setText("Downloading update...")
    window._finish_windows_download(object())
    assert window.status_label.text() == "The downloaded update could not be used."
