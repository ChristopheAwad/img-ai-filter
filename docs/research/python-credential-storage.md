# Research: Cross-platform Credential Storage (2026-09-19)

This record satisfied the credential-store research gate in the now-scrapped
F-002 plan before the dependency was added to `pyproject.toml` and the adapter
was implemented. The adapter is retained for possible future authenticated
servers but is not used by the F-003 MVP GUI.

## Decision

**Selected: `keyring==25.7.0`** as the sole credential-store dependency, wrapped
by an application adapter that explicitly allowlists only the native secure
backends and refuses every other backend.

Direct platform-native implementations (win32 Credential Manager via ctypes,
macOS `security`, Linux `SecretStorage`) were considered and rejected because
they would require three separate, unmaintained code paths, duplicate the mature
cross-platform abstraction that `keyring` already provides, and complicate
freezing on all three desktop operating systems. `keyring` is the community
standard, is actively maintained, and isolates the app from backend details.

## Package facts (keyring 25.7.0)

- **Name / version:** `keyring` 25.7.0, released 2025-11-16.
- **Source:** PyPI `keyring`; upstream https://github.com/jaraco/keyring.
- **Maintainer:** Jason R. Coombs (single PyPI maintainer).
- **License:** MIT (SPDX license expression on PyPI).
- **Python support:** `>=3.9`. Project minimum is 3.11; satisfied.
- **Distribution:** pure-Python wheel `keyring-25.7.0-py3-none-any.whl`
  (39.2 kB). Runs on all target platforms and architectures, including x86-64
  and ARM, because it is platform-independent Python.
- **Wheel SHA-256:** `be4a0b195f149690c166e850609a477c532ddbfbaed96a404d4e43f8d5e2689f`
- **sdist SHA-256:** `fe01bd85eb3f8fb3dd0405defdeac9a5b4f6f0439edbb3149577f244a2e8245b`
- **Runtime dependencies:**
  - Windows: `pywin32-ctypes>=0.2.0`
  - Linux: `SecretStorage>=3.2`, `jeepney>=0.4.2`
  - Python < 3.12: `importlib_metadata>=4.11.4`
  - Always: `jaraco.classes`, `jaraco.context`, `jaraco.functools`
  - All runtime dependencies are MIT-licensed. Installed size measured when the
    dependency is installed during implementation and recorded in `feature.md`.

## Native backends per operating system

| OS | Backend used | Note |
| --- | --- | --- |
| Windows | Windows Credential Locker | via `pywin32-ctypes` |
| macOS | Keychain (macOS 11+; Python 3.8.7+ with universal2 binary) | |
| Linux (GNOME/DE with Secret Service) | Freedesktop Secret Service | requires D-Bus session + `SecretStorage` |
| Linux (KDE) | KWallet | requires `dbus-python` (best installed as a system package) |

`keyring` auto-selects the highest-priority viable backend at runtime. The
application never relies on auto-selection alone: the adapter validates the
active backend instance against an explicit allowlist of the native secure
backend classes and refuses all others.

## Required behavior verification

### Linux with no usable Secret Service

When no recommended backend is available (e.g. headless Linux without a D-Bus
Secret Service daemon), `keyring.get_keyring()` raises `RuntimeError`
("No recommended backend was available..."). The adapter converts this into the
application's safe "credential store unavailable" result. The API key is kept in
process memory only and is clearly reported as not persisted. **No plaintext
fallback occurs.** `keyrings.alt` (which contains the "possibly-insecure"
backends) must be explicitly installed to be available and is not a dependency of
this project.

### Plaintext and insecure backends

A plaintext file backend (`keyring.backends.file.PlaintextKeyring`) and the
degenerate backends (`keyring.backends.null.Keyring`, `keyring.backends.fail.Keyring`)
can be activated only through explicit configuration (config file, environment
variable, or `set_keyring()`), never by default auto-selection. The adapter
rejects any backend that is not on the native allowlist before reading or saving,
so a user-configured or third-party insecure backend cannot receive the API key.
Third-party backends (e.g. `keyrings.alt`, `gsheet-keyring`) register through
entry points and would appear via auto-selection only where viable; the allowlist
rejects them too.

### Exceptions and failure modes

| Condition | keyring behavior | Adapter result |
| --- | --- | --- |
| Password not present | `get_password` returns `None` | read returns `None`, no error |
| Cannot initialize backend | `keyring.errors.InitError` | safe error; key stays session-only |
| Cannot set password | `keyring.errors.PasswordSetError` | safe save failure |
| Cannot delete password / absent on delete | `keyring.errors.PasswordDeleteError` | adapter treats absent key as successful no-op; real failures surface as safe errors |
| Base error | `keyring.errors.KeyringError` | safe error |
| No recommended backend | `RuntimeError` at `get_keyring()` | safe error |

`delete_password` raises when the password does not exist, so the adapter
performs delete as: read first; if absent, return success; otherwise call delete
and surface genuine failures.

### Packaging / freezing

`keyring` is plain Python with no compiled extensions on macOS; `pywin32-ctypes`
is a pure-Python ctypes wrapper; `SecretStorage`/`jeepney` are pure Python. No
C compilation is needed at build time, which keeps PyInstaller/freezing simple.
Linux `dbus-python` compensation remains a documented packaging caveat for the
KWallet path; the Secret Service path (via `SecretStorage`/`jeepney`, pure
Python) is the Linux target.

## Safe-by-design application boundary

- The adapter exposes the existing `read(service, account)`,
  `write(service, account, secret)`, `delete(service, account)` methods against
  service `img_ai_filter` and the validated endpoint origin as the account.
- Every keyring exception is translated to fixed, user-safe messages that never
  contain backend exception text, account details, or the secret.
- The adapter, its exceptions, and its results never include the API key in
  `repr` or `str`.
- The adapter performs no network access and imports no GUI code (module-level
  no-PySide6 rule enforced by a test).
- Automated tests inject a fake `keyring` module; they never touch a real vault.

## Rejection rationale for direct-native implementations

A hand-written native layer would need private, platform-specific credential
APIs that cannot be meaningfully unit-tested on this Linux development machine,
increase triple-platform maintenance, and invite subtle failures in frozen
builds. `keyring` already encodes the correct native behavior and is tested
across platforms by its own suite. Controlled at the adapter boundary it
satisfies every requirement of the research gate.

## Measured installed facts (keyring 25.7.0)

Measured on this machine after `pip install "keyring>=25.7.0,<26"` during
implementation, recorded 2026-09-19.

- Installed version: `keyring 25.7.0` (confirmed via `pip show keyring`).
- Transitive dependencies reported by `pip show keyring` (`Requires:`):
  `jaraco.classes, jaraco.context, jaraco.functools, jeepney, SecretStorage`.
  In this environment pip additionally installed newer builds of
  `cffi`, `cryptography`, `pycparser`, and `more-itertools` to satisfy the
  platform's dependency resolution.
- Installed-on-disk size of the `keyring` package directory:
  `344K	.venv/lib64/python3.14/site-packages/keyring` (`du -sh`).
- Native backend classes present in keyring 25.7.0 that are constructible
  without parameters and used by the allowlist:
  `keyring.backends.SecretService.Keyring`,
  `keyring.backends.Windows.WinVaultKeyring`,
  `keyring.backends.macOS.Keyring`,
  `keyring.backends.kwallet.DBusKeyring`,
  `keyring.backends.kwallet.DBusKeyringKWallet4`.
