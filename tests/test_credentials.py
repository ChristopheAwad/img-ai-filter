"""Native credential-store adapter tests for the LAN vision fallback.

These tests pin the application adapter that wraps the selected credential
library (keyring). They use injected fakes and never touch a real operating-
system vault, a real network service, or the GUI.
"""

from __future__ import annotations

import inspect

import pytest

import img_ai_filter.credentials as credentials_mod
from img_ai_filter.credentials import CredentialStoreError, KeyringCredentialStore
from img_ai_filter.endpoint import build_endpoint_config
from img_ai_filter.settings import (
    CREDENTIAL_SERVICE,
    clear_api_key,
    load_api_key,
    save_api_key,
)

CONFIG = build_endpoint_config("http://127.0.0.1:8000/v1/chat/completions", "vision-model")


# ---------------------------------------------------------------------------
# Fakes shaped like the selected credential library (keyring)
# ---------------------------------------------------------------------------


def _mark_backend(backend_type, module, name) -> type:
    backend_type.__module__ = module
    backend_type.__name__ = name
    return backend_type


class ApprovedKeyringBackend:
    """Fake native backend shaped like keyring.backends.SecretService.Keyring."""

    def __init__(self) -> None:
        self.secrets: dict[tuple[str, str], str] = {}
        self.calls: list[tuple] = []
        self.get_error: type[Exception] | None = None
        self.set_error: type[Exception] | None = None
        self.delete_error: type[Exception] | None = None

    def get_password(self, service: str, account: str) -> str | None:
        self.calls.append(("get", service, account))
        if self.get_error is not None:
            raise self.get_error("vault locked")
        return self.secrets.get((service, account))

    def set_password(self, service: str, account: str, secret: str) -> None:
        self.calls.append(("set", service, account, secret))
        if self.set_error is not None:
            raise self.set_error("save denied")
        self.secrets[(service, account)] = secret

    def delete_password(self, service: str, account: str) -> None:
        self.calls.append(("delete", service, account))
        if self.delete_error is not None:
            raise self.delete_error("delete denied")
        if (service, account) not in self.secrets:
            raise RuntimeError("Password not found")
        self.secrets.pop((service, account))


ApprovedKeyringBackend = _mark_backend(
    ApprovedKeyringBackend, "keyring.backends.SecretService", "Keyring"
)


class ApprovedKeyringBackendWinVault(ApprovedKeyringBackend):
    pass


ApprovedKeyringBackendWinVault = _mark_backend(
    ApprovedKeyringBackendWinVault, "keyring.backends.Windows", "WinVaultKeyring"
)


class FakeKeyringModule:
    def __init__(self, backend, *, get_error: type[Exception] | None = None) -> None:
        self.backend = backend
        self.get_error = get_error

    def get_keyring(self):
        if self.get_error is not None:
            raise self.get_error("no recommended backend available")
        return self.backend


def make_store(backend, *, get_error: type[Exception] | None = None) -> KeyringCredentialStore:
    return KeyringCredentialStore(keyring=FakeKeyringModule(backend, get_error=get_error))


# ---------------------------------------------------------------------------
# Successful read, save, replacement, and deletion on an approved backend
# ---------------------------------------------------------------------------


def test_save_then_read_round_trip() -> None:
    store = make_store(ApprovedKeyringBackend())

    store.write(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key")

    assert store.read(CREDENTIAL_SERVICE, CONFIG.origin) == "secret-key"


def test_read_absent_key_returns_none() -> None:
    store = make_store(ApprovedKeyringBackend())

    assert store.read(CREDENTIAL_SERVICE, CONFIG.origin) is None


def test_replace_key_overwrites_previous() -> None:
    store = make_store(ApprovedKeyringBackend())
    store.write(CREDENTIAL_SERVICE, CONFIG.origin, "old-key")

    store.write(CREDENTIAL_SERVICE, CONFIG.origin, "new-key")

    assert store.read(CREDENTIAL_SERVICE, CONFIG.origin) == "new-key"


def test_delete_removes_key() -> None:
    store = make_store(ApprovedKeyringBackend())
    store.write(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key")

    store.delete(CREDENTIAL_SERVICE, CONFIG.origin)

    assert store.read(CREDENTIAL_SERVICE, CONFIG.origin) is None


def test_delete_absent_key_is_successful_noop() -> None:
    backend = ApprovedKeyringBackend()
    store = make_store(backend)

    store.delete(CREDENTIAL_SERVICE, CONFIG.origin)

    deletes = [call for call in backend.calls if call[0] == "delete"]
    assert deletes == []
    assert store.read(CREDENTIAL_SERVICE, CONFIG.origin) is None


def test_service_and_account_are_forwarded_unchanged() -> None:
    backend = ApprovedKeyringBackend()
    store = make_store(backend)

    store.write(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key")

    call = backend.calls[0]
    assert call[0] == "set"
    assert call[1] == CREDENTIAL_SERVICE
    assert call[2] == CONFIG.origin


def test_read_does_not_write_or_delete() -> None:
    backend = ApprovedKeyringBackend()
    store = make_store(backend)
    store.write(CREDENTIAL_SERVICE, CONFIG.origin, "saved-key")

    store.read(CREDENTIAL_SERVICE, CONFIG.origin)

    operations = [call[0] for call in backend.calls]
    assert operations == ["set", "get"]


def test_two_approved_backend_classes_are_accepted() -> None:
    for backend_cls in (ApprovedKeyringBackend, ApprovedKeyringBackendWinVault):
        store = make_store(backend_cls())
        store.write(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key")
        assert store.read(CREDENTIAL_SERVICE, CONFIG.origin) == "secret-key"


# ---------------------------------------------------------------------------
# Native backend failure modes never crash and never leak details
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "operation",
    ["read", "write", "delete"],
)
def test_unavailable_backend_raises_safe_error_for_every_operation(operation: str) -> None:
    store = make_store(ApprovedKeyringBackend(), get_error=RuntimeError)

    with pytest.raises(CredentialStoreError) as exc:
        if operation == "read":
            store.read(CREDENTIAL_SERVICE, CONFIG.origin)
        elif operation == "write":
            store.write(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key")
        else:
            store.delete(CREDENTIAL_SERVICE, CONFIG.origin)

    message = str(exc.value)
    assert "secret-key" not in message
    assert "no recommended backend" not in message


@pytest.mark.parametrize(
    "error_type",
    [RuntimeError, PermissionError, OSError, Exception],
)
def test_read_failure_raises_safe_error(error_type: type[Exception]) -> None:
    backend = ApprovedKeyringBackend()
    backend.get_error = error_type
    store = make_store(backend)

    with pytest.raises(CredentialStoreError) as exc:
        store.read(CREDENTIAL_SERVICE, CONFIG.origin)

    message = str(exc.value)
    assert "vault locked" not in message
    assert CONFIG.origin not in message


@pytest.mark.parametrize(
    "error_type",
    [RuntimeError, PermissionError, OSError, Exception],
)
def test_write_failure_raises_safe_error(error_type: type[Exception]) -> None:
    backend = ApprovedKeyringBackend()
    backend.set_error = error_type
    store = make_store(backend)

    with pytest.raises(CredentialStoreError) as exc:
        store.write(CREDENTIAL_SERVICE, CONFIG.origin, "top-secret-key")

    message = str(exc.value)
    assert "top-secret-key" not in message
    assert "save denied" not in message
    assert CONFIG.origin not in message


@pytest.mark.parametrize(
    "error_type",
    [RuntimeError, PermissionError, OSError, Exception],
)
def test_delete_failure_raises_safe_error(error_type: type[Exception]) -> None:
    backend = ApprovedKeyringBackend()
    backend.set_password(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key")
    backend.delete_error = error_type
    store = make_store(backend)

    with pytest.raises(CredentialStoreError) as exc:
        store.delete(CREDENTIAL_SERVICE, CONFIG.origin)

    message = str(exc.value)
    assert "secret-key" not in message
    assert "delete denied" not in message


def test_adapter_never_stores_or_exposes_the_secret() -> None:
    store = make_store(ApprovedKeyringBackend())
    store.write(CREDENTIAL_SERVICE, CONFIG.origin, "top-secret-key")

    assert "top-secret-key" not in repr(store)
    assert "top-secret-key" not in str(store)

    backend = ApprovedKeyringBackend()
    backend.set_error = RuntimeError
    failing_store = make_store(backend)
    with pytest.raises(Exception) as exc:
        failing_store.write(CREDENTIAL_SERVICE, CONFIG.origin, "top-secret-key")
    assert "top-secret-key" not in repr(exc.value)
    assert "top-secret-key" not in str(exc.value)


# ---------------------------------------------------------------------------
# Plain, null, fail, chainer, and third-party backends are rejected
# ---------------------------------------------------------------------------


class PlaintextKeyringBackend(ApprovedKeyringBackend):
    pass


class NullKeyringBackend(ApprovedKeyringBackend):
    pass


class FailKeyringBackend(ApprovedKeyringBackend):
    pass


class ChainerBackend(ApprovedKeyringBackend):
    pass


class ThirdPartyBackend(ApprovedKeyringBackend):
    pass


_INSECURE_BACKENDS = [
    PlaintextKeyringBackend,
    NullKeyringBackend,
    FailKeyringBackend,
    ChainerBackend,
    ThirdPartyBackend,
]


@pytest.mark.parametrize(
    "backend_cls, module, name",
    [
        (PlaintextKeyringBackend, "keyring.backends.file", "PlaintextKeyring"),
        (NullKeyringBackend, "keyring.backends.null", "Keyring"),
        (FailKeyringBackend, "keyring.backends.fail", "Keyring"),
        (ChainerBackend, "keyring.backends.chainer", "ChainerBackend"),
        (ThirdPartyBackend, "keyrings.alt", "PlaintextKeyring"),
        (ThirdPartyBackend, "some.third.party", "CustomBackend"),
    ],
)
def test_insecure_or_unknown_backend_is_rejected_before_any_operation(
    backend_cls: type, module: str, name: str
) -> None:
    backend = _mark_backend(backend_cls, module, name)()
    store = make_store(backend)

    for attempt in (
        lambda: store.read(CREDENTIAL_SERVICE, CONFIG.origin),
        lambda: store.write(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key"),
        lambda: store.delete(CREDENTIAL_SERVICE, CONFIG.origin),
    ):
        with pytest.raises(CredentialStoreError) as exc:
            attempt()
        assert "secret-key" not in str(exc.value)

    assert backend.calls == []


def test_unknown_module_with_approved_name_is_rejected() -> None:
    backend = _mark_backend(PlaintextKeyringBackend, "not.keyring", "Keyring")()

    with pytest.raises(CredentialStoreError):
        make_store(backend).write(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key")


# ---------------------------------------------------------------------------
# Settings integration through the adapter
# ---------------------------------------------------------------------------


def test_settings_boundary_works_through_adapter_backend() -> None:
    store = make_store(ApprovedKeyringBackend())

    saved = save_api_key(store, CONFIG, "secret-key")

    assert saved.persisted is True
    assert saved.error is None
    assert load_api_key(store, CONFIG).key == "secret-key"


def test_settings_reports_failed_save_through_adapter() -> None:
    backend = ApprovedKeyringBackend()
    backend.set_error = RuntimeError
    store = make_store(backend)

    saved = save_api_key(store, CONFIG, "session-key")

    assert saved.persisted is False
    assert saved.error is not None
    assert "session-key" not in (saved.error or "")


def test_settings_reports_unavailable_backend_through_adapter() -> None:
    store = make_store(ApprovedKeyringBackend(), get_error=RuntimeError)

    saved = save_api_key(store, CONFIG, "session-key")

    assert saved.persisted is False
    assert saved.error is not None
    assert "session-key" not in (saved.error or "")


def test_settings_reports_delete_failure_through_adapter() -> None:
    backend = ApprovedKeyringBackend()
    backend.set_password(CREDENTIAL_SERVICE, CONFIG.origin, "secret-key")
    backend.delete_error = PermissionError
    store = make_store(backend)

    assert clear_api_key(store, CONFIG) is False


def test_settings_delete_of_absent_key_through_adapter_succeeds() -> None:
    backend = ApprovedKeyringBackend()
    store = make_store(backend)

    assert clear_api_key(store, CONFIG) is True


# ---------------------------------------------------------------------------
# Module hygiene
# ---------------------------------------------------------------------------


def test_module_must_not_import_pyside6() -> None:
    assert "PySide6" not in inspect.getsource(credentials_mod)


def test_module_performs_no_network_imports() -> None:
    source = inspect.getsource(credentials_mod)
    for token in ("urllib", "requests", "aiohttp", "httpx", "http.client"):
        assert token not in source