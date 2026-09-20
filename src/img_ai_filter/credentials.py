"""Native credential-store adapter for the LAN vision fallback.

This module wraps the selected native credential library (keyring) behind the
existing read/write/delete boundary. The adapter never stores the secret in
this process, never loads the library at import time, and performs no GUI or
network access, so unit tests can exercise the full contract without a
desktop session.
"""

from __future__ import annotations

from typing import Any

_ALLOWED_BACKENDS = {
    ("keyring.backends.SecretService", "Keyring"),
    ("keyring.backends.Windows", "WinVaultKeyring"),
    ("keyring.backends.macOS", "Keyring"),
    ("keyring.backends.kwallet", "DBusKeyring"),
    ("keyring.backends.kwallet", "DBusKeyringKWallet4"),
}


class CredentialStoreError(Exception):
    """Raised when the native credential store cannot be used safely.

    The message is fixed and never contains a secret, the account, or the
    backend exception detail.
    """


class KeyringCredentialStore:
    """Credential-store boundary backed by an approved native keyring backend."""

    def __init__(self, keyring: Any = None) -> None:
        self._keyring = keyring

    def _module(self) -> Any:
        if self._keyring is None:
            import keyring

            return keyring
        return self._keyring

    def _backend(self) -> Any:
        module = self._module()
        try:
            backend = module.get_keyring()
        except Exception:
            raise CredentialStoreError(
                "The credential store is unavailable"
            ) from None
        if self._is_approved(backend) is False:
            raise CredentialStoreError("The credential store is not secure")
        return backend

    def _is_approved(self, backend: Any) -> bool:
        return (type(backend).__module__, type(backend).__name__) in _ALLOWED_BACKENDS

    def read(self, service: str, account: str) -> str | None:
        """Return the stored secret for the account, or None when absent."""
        backend = self._backend()
        try:
            return backend.get_password(service, account)
        except Exception:
            raise CredentialStoreError(
                "The credential store is unavailable"
            ) from None

    def write(self, service: str, account: str, secret: str) -> None:
        """Persist the secret for the account in the approved backend."""
        backend = self._backend()
        try:
            backend.set_password(service, account, secret)
        except Exception:
            raise CredentialStoreError(
                "The API key could not be saved securely"
            ) from None

    def delete(self, service: str, account: str) -> None:
        """Delete the stored secret, succeeding silently when none exists."""
        backend = self._backend()
        try:
            existing = backend.get_password(service, account)
        except Exception:
            raise CredentialStoreError(
                "The credential store is unavailable"
            ) from None
        if existing is None:
            return None
        try:
            backend.delete_password(service, account)
        except Exception:
            raise CredentialStoreError(
                "The API key could not be deleted"
            ) from None
        return None