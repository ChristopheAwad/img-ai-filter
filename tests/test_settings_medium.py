"""Settings, history durability, and eval CLI tests (M8). No network."""

from __future__ import annotations

from pathlib import Path

import pytest

from img_ai_filter.activity_history import (
    SCAN_HISTORY_KEY,
    append_activity_history,
    clear_activity_history,
    load_activity_history,
)
from img_ai_filter.settings import (
    ENDPOINT_MODEL_KEY,
    ENDPOINT_URL_KEY,
    IniSettingsStore,
    SettingsStatus,
    load_endpoint_settings,
    load_vision_endpoint_settings,
)


class FailingStore:
    def read(self, key):
        raise OSError("store unavailable")

    def write(self, key, value):
        raise OSError("store unavailable")

    def delete(self, key):
        raise OSError("store unavailable")


class DictStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def read(self, key):
        return self.values.get(key)

    def write(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)


def test_m8_endpoint_loaders_survive_store_failure_and_bad_types():
    for loader in (load_endpoint_settings, load_vision_endpoint_settings):
        loaded = loader(FailingStore())
        assert loaded.status is SettingsStatus.NEEDS_REPAIR
        assert loaded.config is None
        loaded = loader(DictStore({ENDPOINT_URL_KEY: 12345, ENDPOINT_MODEL_KEY: "m"}))
        assert loaded.status is SettingsStatus.NEEDS_REPAIR
        assert loaded.config is None


def test_m8_ini_write_is_crash_safe(tmp_path: Path, monkeypatch):
    from img_ai_filter.settings import save_endpoint_settings
    from img_ai_filter.endpoint import build_endpoint_config

    path = tmp_path / "settings.ini"
    store = IniSettingsStore(path)
    config = build_endpoint_config("http://127.0.0.1:5001/v1/", model="m")
    save_endpoint_settings(store, config)
    before = path.read_bytes()

    import img_ai_filter.settings as settings_module

    def exploding_replace(src, dst):
        raise OSError("crash during replace")

    monkeypatch.setattr(settings_module.os, "replace", exploding_replace)
    with pytest.raises(OSError):
        save_endpoint_settings(store, config)
    # Old content intact: no truncate-then-write data loss.
    assert path.read_bytes() == before
    assert store.read(ENDPOINT_URL_KEY) == "http://127.0.0.1:5001/v1/"


def _scan_record(n: int):
    from img_ai_filter.activity_history import ScanHistoryRecord

    return ScanHistoryRecord(
        started_at_utc="2026-09-20T12:00:00.000000Z",
        source_folder=f"/src/{n}",
        model="m",
        outcome="completed",
        duration_ms=1000,
        discovered=1,
        analyzed=1,
        candidates=0,
        ordinary=1,
        uncertain=0,
        failed=0,
        skipped_directories=0,
    )


def test_m8_corrupt_history_recovers_from_backup_and_clear_removes_it():
    store = DictStore()
    for n in range(3):
        assert append_activity_history(store, _scan_record(n)) is True
    assert len(load_activity_history(store)) == 3

    store.values[SCAN_HISTORY_KEY] = "corrupt{"
    recovered = load_activity_history(store)
    assert len(recovered) == 3

    assert append_activity_history(store, _scan_record(9)) is True
    assert len(load_activity_history(store)) == 4

    assert clear_activity_history(store) is True
    assert load_activity_history(store) == ()
    assert all("backup" not in key for key in store.values)


def test_m8_eval_cli_reports_errors_and_missing_manifest(tmp_path: Path, capsys):
    from img_ai_filter import eval_cli

    code = eval_cli.main(["--dataset", str(tmp_path), "--manifest", str(tmp_path / "no.csv")])
    assert code != 0

    dataset = tmp_path / "data"
    dataset.mkdir()
    from PIL import Image

    Image.new("RGB", (900, 1600)).save(dataset / "phone.png", format="PNG")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,label,split,source,license\nphone.png,screenshot,holdout,t,l\n",
        encoding="utf-8",
    )
    code = eval_cli.main(
        ["--dataset", str(dataset), "--manifest", str(manifest), "--split", "holdout"]
    )
    assert code == 0


def test_m8_eval_cli_exit_code_reflects_detector_errors(tmp_path: Path, monkeypatch):
    from img_ai_filter import eval_cli
    import img_ai_filter.evaluation as evaluation_module

    dataset = tmp_path / "data"
    dataset.mkdir()
    from PIL import Image

    Image.new("RGB", (900, 1600)).save(dataset / "phone.png", format="PNG")
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        "path,label,split,source,license\nphone.png,screenshot,holdout,t,l\n",
        encoding="utf-8",
    )

    real_evaluate = evaluation_module.evaluate_detector

    def failing_evaluate(detector, manifest_arg, split, targets=None):
        import dataclasses
        from pathlib import Path as P

        result = real_evaluate(detector, manifest_arg, split, targets=targets)
        return dataclasses.replace(
            result, errors=result.errors + ((P("phone.png"), "valueerror: boom"),)
        )

    monkeypatch.setattr(eval_cli, "evaluate_detector", failing_evaluate)
    code = eval_cli.main(
        ["--dataset", str(dataset), "--manifest", str(manifest), "--split", "holdout"]
    )
    assert code != 0
