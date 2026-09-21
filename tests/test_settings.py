"""Settings and credential-boundary tests for the LAN vision fallback.

These tests pin how the endpoint URL and model name persist and how the
optional API key crosses an injected credential-store boundary. No test
contacts a real network service, a real credential vault, or the GUI.
"""

from __future__ import annotations

import inspect

import pytest

import img_ai_filter.settings as settings_mod
from img_ai_filter.settings import (
    AUTO_SELECT_CONFIDENCE_KEY,
    DEFAULT_AUTO_SELECT_CONFIDENCE_PERCENT,
    IniSettingsStore,
    SettingsStatus,
    clear_api_key,
    clear_endpoint_settings,
    clear_quarantine_folder,
    load_api_key,
    load_auto_select_confidence,
    load_endpoint_settings,
    load_quarantine_folder,
    save_api_key,
    save_auto_select_confidence,
    save_endpoint_settings,
    save_quarantine_folder,
    QUARANTINE_FOLDER_KEY,
)
from img_ai_filter.endpoint import build_endpoint_config

CONFIG = build_endpoint_config("http://127.0.0.1:8000/v1/chat/completions", "vision-model")


def _loopback_resolver(_hostname: str) -> tuple[str, ...]:
    return ("127.0.0.1",)


class InMemorySettingsStore:
    def __init__(self, seed: dict[str, str] | None = None) -> None:
        self.values: dict[str, str] = dict(seed or {})
        self.writes: list[str] = []

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.writes.append(key)
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class InMemoryCredentialStore:
    def __init__(self) -> None:
        self.secrets: dict[tuple[str, str], str] = {}
        self.records: list[tuple[str, str, str]] = []
        self.read_error: type[Exception] | None = None
        self.write_error: type[Exception] | None = None
        self.delete_error: type[Exception] | None = None

    def read(self, service: str, account: str) -> str | None:
        self.records.append((service, account, "read"))
        if self.read_error is not None:
            raise self.read_error("vault unavailable")
        return self.secrets.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self.records.append((service, account, secret))
        if self.write_error is not None:
            raise self.write_error("vault locked")
        self.secrets[(service, account)] = secret

    def delete(self, service: str, account: str) -> None:
        self.records.append((service, account, "delete"))
        if self.delete_error is not None:
            raise self.delete_error("delete denied")
        self.secrets.pop((service, account), None)


def test_auto_select_confidence_key_and_default_are_stable() -> None:
    assert AUTO_SELECT_CONFIDENCE_KEY == "auto_select_confidence_percent"
    assert DEFAULT_AUTO_SELECT_CONFIDENCE_PERCENT == 90


def test_absent_auto_select_confidence_uses_default_without_write() -> None:
    store = InMemorySettingsStore()

    loaded = load_auto_select_confidence(store)

    assert loaded == 90
    assert store.writes == []


@pytest.mark.parametrize("value", [50, 51, 89, 90, 99, 100])
def test_valid_auto_select_confidence_loads_exactly(value: int) -> None:
    store = InMemorySettingsStore({AUTO_SELECT_CONFIDENCE_KEY: str(value)})

    assert load_auto_select_confidence(store) == value
    assert store.writes == []


@pytest.mark.parametrize(
    "value",
    ["", " ", "49", "101", " 90", "90 ", "+90", "-90", "090", "90.0", "9e1", "nan", "inf", "value"],
)
def test_invalid_auto_select_confidence_uses_default_without_repair(value: str) -> None:
    store = InMemorySettingsStore({AUTO_SELECT_CONFIDENCE_KEY: value})

    assert load_auto_select_confidence(store) == 90
    assert store.values[AUTO_SELECT_CONFIDENCE_KEY] == value
    assert store.writes == []


def test_auto_select_confidence_read_failure_uses_default() -> None:
    class FailingStore:
        def read(self, key):
            raise OSError("private failure")

    assert load_auto_select_confidence(FailingStore()) == 90


@pytest.mark.parametrize("value", [50, 73, 90, 100])
def test_save_auto_select_confidence_round_trips(value: int) -> None:
    store = InMemorySettingsStore()

    assert save_auto_select_confidence(store, value)
    assert store.values[AUTO_SELECT_CONFIDENCE_KEY] == str(value)
    assert load_auto_select_confidence(store) == value


@pytest.mark.parametrize("value", [49, 101, -1, 90.0, "90", None, True, False])
def test_save_auto_select_confidence_rejects_invalid_values(value) -> None:
    store = InMemorySettingsStore()

    assert not save_auto_select_confidence(store, value)
    assert store.writes == []


def test_save_auto_select_confidence_handles_write_failure() -> None:
    class FailingStore:
        def write(self, key, value):
            raise OSError("private failure")

    assert not save_auto_select_confidence(FailingStore(), 90)


def _seed_valid(store: InMemorySettingsStore) -> None:
    store.values[settings_mod.ENDPOINT_URL_KEY] = CONFIG.url
    store.values[settings_mod.ENDPOINT_MODEL_KEY] = CONFIG.model


# ---------------------------------------------------------------------------
# Endpoint URL and model persistence
# ---------------------------------------------------------------------------


def test_save_and_restore_endpoint_settings_round_trip(tmp_path) -> None:
    store = IniSettingsStore(tmp_path / "settings.ini")
    save_endpoint_settings(store, CONFIG)

    loaded = load_endpoint_settings(store)

    assert loaded.status is SettingsStatus.READY
    assert loaded.config is not None
    assert loaded.config.url == CONFIG.url
    assert loaded.config.model == CONFIG.model


def test_absent_settings_are_unconfigured_not_corrupt() -> None:
    loaded = load_endpoint_settings(InMemorySettingsStore())

    assert loaded.status is SettingsStatus.UNCONFIGURED
    assert loaded.config is None


def test_valid_stored_settings_load_in_memory_store() -> None:
    store = InMemorySettingsStore()
    _seed_valid(store)

    loaded = load_endpoint_settings(store)

    assert loaded.status is SettingsStatus.READY
    assert loaded.config is not None
    assert loaded.config.origin == CONFIG.origin


def test_stored_localhost_url_loads_with_injected_resolver() -> None:
    store = InMemorySettingsStore(
        {settings_mod.ENDPOINT_URL_KEY: "http://localhost:8000/x", settings_mod.ENDPOINT_MODEL_KEY: "m"}
    )

    loaded = load_endpoint_settings(store, resolver=_loopback_resolver)

    assert loaded.status is SettingsStatus.READY
    assert loaded.config is not None
    assert loaded.config.hostname == "localhost"


@pytest.mark.parametrize(
    "seed",
    [
        {settings_mod.ENDPOINT_URL_KEY: "", settings_mod.ENDPOINT_MODEL_KEY: "m"},
        {settings_mod.ENDPOINT_URL_KEY: "   ", settings_mod.ENDPOINT_MODEL_KEY: "m"},
        {settings_mod.ENDPOINT_URL_KEY: "not a url", settings_mod.ENDPOINT_MODEL_KEY: "m"},
        {settings_mod.ENDPOINT_URL_KEY: "http://8.8.8.8:8000/x", settings_mod.ENDPOINT_MODEL_KEY: "m"},
        {settings_mod.ENDPOINT_URL_KEY: CONFIG.url, settings_mod.ENDPOINT_MODEL_KEY: ""},
        {settings_mod.ENDPOINT_URL_KEY: CONFIG.url, settings_mod.ENDPOINT_MODEL_KEY: "  "},
        {settings_mod.ENDPOINT_URL_KEY: CONFIG.url},
        {settings_mod.ENDPOINT_MODEL_KEY: "m"},
    ],
)
def test_empty_or_malformed_persisted_settings_need_repair(seed: dict[str, str]) -> None:
    loaded = load_endpoint_settings(InMemorySettingsStore(seed))

    assert loaded.status is SettingsStatus.NEEDS_REPAIR
    assert loaded.config is None


def test_clear_endpoint_settings_removes_both_keys() -> None:
    store = InMemorySettingsStore()
    _seed_valid(store)

    clear_endpoint_settings(store)

    assert settings_mod.ENDPOINT_URL_KEY not in store.values
    assert settings_mod.ENDPOINT_MODEL_KEY not in store.values


def test_loading_settings_performs_no_writes() -> None:
    store = InMemorySettingsStore()
    _seed_valid(store)

    load_endpoint_settings(store)

    assert store.writes == []


def test_ini_settings_store_missing_file_reads_none(tmp_path) -> None:
    store = IniSettingsStore(tmp_path / "missing.ini")

    assert store.read(settings_mod.ENDPOINT_URL_KEY) is None


def test_ini_settings_store_delete_removes_only_that_key(tmp_path) -> None:
    store = IniSettingsStore(tmp_path / "settings.ini")
    save_endpoint_settings(store, CONFIG)

    store.delete(settings_mod.ENDPOINT_URL_KEY)

    assert store.read(settings_mod.ENDPOINT_URL_KEY) is None
    assert store.read(settings_mod.ENDPOINT_MODEL_KEY) == CONFIG.model


# ---------------------------------------------------------------------------
# API key credential-store boundary
# ---------------------------------------------------------------------------


def test_save_then_load_api_key(tmp_path) -> None:
    store = IniSettingsStore(tmp_path / "settings.ini")
    vault = InMemoryCredentialStore()

    saved = save_api_key(vault, CONFIG, "secret-key")

    assert saved.persisted is True
    assert saved.error is None

    loaded = load_api_key(vault, CONFIG)
    assert loaded.key == "secret-key"
    assert loaded.error is None


def test_replace_api_key_overwrites_previous(tmp_path) -> None:
    vault = InMemoryCredentialStore()
    save_api_key(vault, CONFIG, "old-key")

    save_api_key(vault, CONFIG, "new-key")

    assert load_api_key(vault, CONFIG).key == "new-key"


def test_delete_api_key_removes_it(tmp_path) -> None:
    vault = InMemoryCredentialStore()
    save_api_key(vault, CONFIG, "secret-key")

    assert clear_api_key(vault, CONFIG) is True
    assert load_api_key(vault, CONFIG).key is None


def test_load_with_no_key_returns_none_without_error():
    loaded = load_api_key(InMemoryCredentialStore(), CONFIG)

    assert loaded.key is None
    assert loaded.error is None


def test_credential_account_uses_service_and_origin(tmp_path) -> None:
    vault = InMemoryCredentialStore()
    save_api_key(vault, CONFIG, "secret-key")

    (service, account, _), *_ = vault.records

    assert service == settings_mod.CREDENTIAL_SERVICE
    assert account == CONFIG.origin


def test_api_key_never_written_to_normal_settings(tmp_path) -> None:
    store = IniSettingsStore(tmp_path / "settings.ini")
    save_endpoint_settings(store, CONFIG)

    save_api_key(InMemoryCredentialStore(), CONFIG, "top-secret-key")

    raw = (tmp_path / "settings.ini").read_text(encoding="utf-8")
    assert "top-secret-key" not in raw


def test_api_key_never_appears_in_representations(tmp_path) -> None:
    outcome = save_api_key(InMemoryCredentialStore(), CONFIG, "top-secret-key")

    assert "top-secret-key" not in repr(outcome)
    assert "top-secret-key" not in repr(CONFIG)


@pytest.mark.parametrize(
    "error_type",
    [Exception, RuntimeError, OSError],
)
def test_credential_store_read_failures_do_not_crash(error_type: type[Exception]) -> None:
    vault = InMemoryCredentialStore()
    vault.read_error = error_type

    loaded = load_api_key(vault, CONFIG)

    assert loaded.key is None
    assert loaded.error is not None


@pytest.mark.parametrize(
    "error_type",
    [Exception, RuntimeError, OSError],
)
def test_save_failure_reports_not_persisted_without_raising(
    error_type: type[Exception],
) -> None:
    vault = InMemoryCredentialStore()
    vault.write_error = error_type

    outcome = save_api_key(vault, CONFIG, "session-key")

    assert outcome.persisted is False
    assert outcome.error is not None
    assert "session-key" not in (outcome.error or "")


def test_delete_failure_reports_false_without_raising() -> None:
    vault = InMemoryCredentialStore()
    save_api_key(vault, CONFIG, "secret-key")
    vault.delete_error = RuntimeError

    assert clear_api_key(vault, CONFIG) is False
    assert load_api_key(vault, CONFIG).key == "secret-key"


def test_reading_key_does_not_overwrite_or_delete_it() -> None:
    vault = InMemoryCredentialStore()
    save_api_key(vault, CONFIG, "saved-key")

    load_api_key(vault, CONFIG)

    writes = [r for r in vault.records if r[2] not in ("read", "delete")]
    assert writes == [("img_ai_filter", CONFIG.origin, "saved-key")]


def test_module_must_not_import_pyside6() -> None:
    assert "PySide6" not in inspect.getsource(settings_mod)


# ---------------------------------------------------------------------------
# Quarantine folder persistence
# ---------------------------------------------------------------------------


def test_quarantine_folder_key_is_exact() -> None:
    assert QUARANTINE_FOLDER_KEY == "quarantine_folder"


def test_absent_quarantine_setting_is_unconfigured() -> None:
    loaded = load_quarantine_folder(InMemorySettingsStore())

    assert loaded.status is SettingsStatus.UNCONFIGURED
    assert loaded.folder is None


def test_valid_stored_quarantine_folder_loads(tmp_path) -> None:
    store = InMemorySettingsStore({QUARANTINE_FOLDER_KEY: str(tmp_path)})

    loaded = load_quarantine_folder(store)

    assert loaded.status is SettingsStatus.READY
    assert loaded.folder == tmp_path


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_or_whitespace_quarantine_needs_repair(value: str) -> None:
    loaded = load_quarantine_folder(
        InMemorySettingsStore({QUARANTINE_FOLDER_KEY: value})
    )

    assert loaded.status is SettingsStatus.NEEDS_REPAIR
    assert loaded.folder is None


def test_stored_missing_directory_quarantine_needs_repair(tmp_path) -> None:
    loaded = load_quarantine_folder(
        InMemorySettingsStore({QUARANTINE_FOLDER_KEY: str(tmp_path / "gone")})
    )

    assert loaded.status is SettingsStatus.NEEDS_REPAIR


def test_stored_ordinary_file_quarantine_needs_repair(tmp_path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("not a folder")

    loaded = load_quarantine_folder(
        InMemorySettingsStore({QUARANTINE_FOLDER_KEY: str(target)})
    )

    assert loaded.status is SettingsStatus.NEEDS_REPAIR


def test_stored_symlink_quarantine_needs_repair(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    loaded = load_quarantine_folder(
        InMemorySettingsStore({QUARANTINE_FOLDER_KEY: str(link)})
    )

    assert loaded.status is SettingsStatus.NEEDS_REPAIR


def test_stored_reparse_point_quarantine_needs_repair(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        settings_mod,
        "is_windows_reparse_point",
        lambda folder: folder == tmp_path,
    )

    loaded = load_quarantine_folder(
        InMemorySettingsStore({QUARANTINE_FOLDER_KEY: str(tmp_path)})
    )

    assert loaded.status is SettingsStatus.NEEDS_REPAIR
    assert loaded.folder is None


def test_stored_unwritable_quarantine_needs_repair(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings_mod.os, "access", lambda folder, flags: False)

    loaded = load_quarantine_folder(
        InMemorySettingsStore({QUARANTINE_FOLDER_KEY: str(tmp_path)})
    )

    assert loaded.status is SettingsStatus.NEEDS_REPAIR
    assert loaded.folder is None


def test_quarantine_folder_check_can_be_injected(tmp_path) -> None:
    store = InMemorySettingsStore({QUARANTINE_FOLDER_KEY: str(tmp_path)})

    rejected = load_quarantine_folder(
        store, folder_check=lambda _folder: False
    )
    accepted = load_quarantine_folder(
        store, folder_check=lambda _folder: True
    )

    assert rejected.status is SettingsStatus.NEEDS_REPAIR
    assert accepted.status is SettingsStatus.READY


def test_quarantine_read_failure_returns_needs_repair() -> None:
    class FailingReadStore:
        def read(self, key):
            raise OSError("store unavailable")

    loaded = load_quarantine_folder(FailingReadStore())

    assert loaded.status is SettingsStatus.NEEDS_REPAIR
    assert loaded.folder is None


def test_loading_quarantine_settings_performs_no_writes(tmp_path) -> None:
    store = InMemorySettingsStore({QUARANTINE_FOLDER_KEY: str(tmp_path)})

    load_quarantine_folder(store)

    assert store.writes == []


def test_save_quarantine_folder_persists_value(tmp_path) -> None:
    store = InMemorySettingsStore()

    persisted = save_quarantine_folder(store, tmp_path)

    assert persisted is True
    assert store.values[QUARANTINE_FOLDER_KEY] == str(tmp_path)


def test_save_quarantine_folder_failure_reports_false(tmp_path) -> None:
    class FailingWriteStore:
        def write(self, key, value):
            raise OSError("disk full")

    assert save_quarantine_folder(FailingWriteStore(), tmp_path) is False


def test_quarantine_settings_do_not_touch_endpoint_keys(tmp_path) -> None:
    store = InMemorySettingsStore()
    _seed_valid(store)

    save_quarantine_folder(store, tmp_path)

    assert store.values[settings_mod.ENDPOINT_URL_KEY] == CONFIG.url
    assert store.values[settings_mod.ENDPOINT_MODEL_KEY] == CONFIG.model


def test_clear_quarantine_folder_removes_only_its_key(tmp_path) -> None:
    store = InMemorySettingsStore(
        {QUARANTINE_FOLDER_KEY: str(tmp_path)}
    )
    _seed_valid(store)

    clear_quarantine_folder(store)

    assert QUARANTINE_FOLDER_KEY not in store.values
    assert store.values[settings_mod.ENDPOINT_URL_KEY] == CONFIG.url
    assert store.values[settings_mod.ENDPOINT_MODEL_KEY] == CONFIG.model
