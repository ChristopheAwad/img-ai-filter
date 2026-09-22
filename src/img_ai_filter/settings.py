"""Persist LAN-endpoint URL/model settings and an optional API key.

This module stores the local-area-network endpoint URL and model name and
moves the optional API key across an injected credential-store boundary. It
stays independent of the GUI and of any HTTP client, and it never stores the
API key in normal settings.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
import configparser
from dataclasses import dataclass
from enum import Enum, auto
import os
from pathlib import Path
import re
from typing import Any

from img_ai_filter.endpoint import (
    EndpointConfig,
    EndpointValidationError,
    VisionEndpointConfig,
    build_endpoint_config,
    build_vision_endpoint_config,
)
from img_ai_filter.detection import DEFAULT_HIGH_CONFIDENCE_THRESHOLD
from img_ai_filter.scanner import is_windows_reparse_point

ENDPOINT_URL_KEY = "endpoint_url"
ENDPOINT_MODEL_KEY = "endpoint_model"
AUTO_SELECT_CONFIDENCE_KEY = "auto_select_confidence_percent"
INCLUDE_TEST_RELEASES_KEY = "include_test_releases"
DEFAULT_AUTO_SELECT_CONFIDENCE_PERCENT = round(DEFAULT_HIGH_CONFIDENCE_THRESHOLD * 100)
MIN_AUTO_SELECT_CONFIDENCE_PERCENT = 50
MAX_AUTO_SELECT_CONFIDENCE_PERCENT = 100
CREDENTIAL_SERVICE = "img_ai_filter"

_SECTION = "settings"
_CANONICAL_PERCENT = re.compile(r"(?:[1-9][0-9]?|100)\Z")


def load_auto_select_confidence(store: Any) -> int:
    """Load a canonical high-confidence percentage or use the safe default."""
    try:
        raw = store.read(AUTO_SELECT_CONFIDENCE_KEY)
    except Exception:
        return DEFAULT_AUTO_SELECT_CONFIDENCE_PERCENT
    if not isinstance(raw, str) or _CANONICAL_PERCENT.fullmatch(raw) is None:
        return DEFAULT_AUTO_SELECT_CONFIDENCE_PERCENT
    value = int(raw)
    if not MIN_AUTO_SELECT_CONFIDENCE_PERCENT <= value <= MAX_AUTO_SELECT_CONFIDENCE_PERCENT:
        return DEFAULT_AUTO_SELECT_CONFIDENCE_PERCENT
    return value


def save_auto_select_confidence(store: Any, value: object) -> bool:
    """Persist a validated integer percentage without exposing store errors."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not MIN_AUTO_SELECT_CONFIDENCE_PERCENT
        <= value
        <= MAX_AUTO_SELECT_CONFIDENCE_PERCENT
    ):
        return False
    try:
        store.write(AUTO_SELECT_CONFIDENCE_KEY, str(value))
    except Exception:
        return False
    return True


def load_include_test_releases(store: Any) -> bool:
    """Load only the canonical persisted true value."""
    try:
        raw = store.read(INCLUDE_TEST_RELEASES_KEY)
    except Exception:
        return False
    return isinstance(raw, str) and raw == "true"


def save_include_test_releases(store: Any, value: object) -> bool:
    """Persist a boolean using its canonical lowercase representation."""
    if type(value) is not bool:
        return False
    try:
        store.write(INCLUDE_TEST_RELEASES_KEY, "true" if value else "false")
    except Exception:
        return False
    return True


class SettingsStatus(Enum):
    """Current state of the persisted endpoint settings."""

    UNCONFIGURED = auto()
    READY = auto()
    NEEDS_REPAIR = auto()


@dataclass(frozen=True, slots=True)
class EndpointSettings:
    """Loaded endpoint settings with their validation status."""

    status: SettingsStatus
    config: EndpointConfig | None


@dataclass(frozen=True, slots=True)
class VisionEndpointSettings:
    """Loaded KoboldCpp endpoint settings with their validation status."""

    status: SettingsStatus
    config: VisionEndpointConfig | None


def load_endpoint_settings(
    store: Any,
    *,
    resolver: Callable[[str], Sequence[str]] | None = None,
) -> EndpointSettings:
    """Load and validate the stored endpoint URL and model name."""
    url = store.read(ENDPOINT_URL_KEY)
    model = store.read(ENDPOINT_MODEL_KEY)

    if url is None and model is None:
        return EndpointSettings(SettingsStatus.UNCONFIGURED, None)
    if url is None or model is None:
        return EndpointSettings(SettingsStatus.NEEDS_REPAIR, None)

    try:
        config = build_endpoint_config(url, model, resolver=resolver)
    except EndpointValidationError:
        return EndpointSettings(SettingsStatus.NEEDS_REPAIR, None)

    return EndpointSettings(SettingsStatus.READY, config)


def save_endpoint_settings(store: Any, config: EndpointConfig) -> None:
    """Write the endpoint URL and model name to the settings store."""
    store.write(ENDPOINT_URL_KEY, config.url)
    store.write(ENDPOINT_MODEL_KEY, config.model)


def load_vision_endpoint_settings(
    store: Any,
    *,
    resolver: Callable[[str], Sequence[str]] | None = None,
) -> VisionEndpointSettings:
    """Load and validate a stored KoboldCpp base URL and discovered model."""
    url = store.read(ENDPOINT_URL_KEY)
    model = store.read(ENDPOINT_MODEL_KEY)
    if url is None and model is None:
        return VisionEndpointSettings(SettingsStatus.UNCONFIGURED, None)
    if url is None or model is None:
        return VisionEndpointSettings(SettingsStatus.NEEDS_REPAIR, None)

    try:
        config = build_vision_endpoint_config(url, model, resolver=resolver)
    except EndpointValidationError:
        return VisionEndpointSettings(SettingsStatus.NEEDS_REPAIR, None)
    if not config.model:
        return VisionEndpointSettings(SettingsStatus.NEEDS_REPAIR, None)
    return VisionEndpointSettings(SettingsStatus.READY, config)


def save_vision_endpoint_settings(store: Any, config: VisionEndpointConfig) -> None:
    """Persist a canonical KoboldCpp base URL and nonblank discovered model."""
    if not isinstance(config.model, str) or not config.model.strip():
        raise ValueError("A discovered model is required")
    store.write(ENDPOINT_URL_KEY, config.base_url)
    store.write(ENDPOINT_MODEL_KEY, config.model.strip())


def clear_endpoint_settings(store: Any) -> None:
    """Remove the stored endpoint URL and model name."""
    store.delete(ENDPOINT_URL_KEY)
    store.delete(ENDPOINT_MODEL_KEY)


@dataclass(frozen=True, slots=True)
class ApiKeyLoad:
    """Result of loading the optional API key."""

    key: str | None
    error: str | None


def load_api_key(credentials: Any, config: EndpointConfig) -> ApiKeyLoad:
    """Load the API key for the config origin, falling back on error."""
    account = config.origin
    try:
        value = credentials.read(CREDENTIAL_SERVICE, account)
    except Exception:
        return ApiKeyLoad(key=None, error="The credential store is unavailable")
    return ApiKeyLoad(key=value, error=None)


@dataclass(frozen=True, slots=True)
class ApiKeySave:
    """Result of persisting the optional API key."""

    persisted: bool
    error: str | None


def save_api_key(credentials: Any, config: EndpointConfig, key: str) -> ApiKeySave:
    """Store the API key in the credential store, falling back on error."""
    account = config.origin
    try:
        credentials.write(CREDENTIAL_SERVICE, account, key)
    except Exception:
        return ApiKeySave(persisted=False, error="The API key could not be saved securely")
    return ApiKeySave(persisted=True, error=None)


def clear_api_key(credentials: Any, config: EndpointConfig) -> bool:
    """Delete the API key, reporting False if the credential store fails."""
    account = config.origin
    try:
        credentials.delete(CREDENTIAL_SERVICE, account)
    except Exception:
        return False
    return True


class IniSettingsStore:
    """File-backed settings store using an INI file under a settings section."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _parser(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(
            interpolation=None,
            inline_comment_prefixes=None,
        )
        parser.optionxform = str
        return parser

    def _load(self) -> configparser.ConfigParser:
        parser = self._parser()
        try:
            parser.read(self.path, encoding="utf-8")
        except (configparser.Error, OSError):
            return self._parser()
        return parser

    def read(self, key: str) -> str | None:
        """Return the stored value for key, or None when absent or unreadable."""
        parser = self._load()
        if not parser.has_section(_SECTION) or not parser.has_option(_SECTION, key):
            return None
        return parser.get(_SECTION, key)

    def write(self, key: str, value: str) -> None:
        """Store value for key, preserving any other keys already present."""
        parser = self._load()
        if not parser.has_section(_SECTION):
            parser.add_section(_SECTION)
        parser.set(_SECTION, key, value)
        with open(self.path, "w", encoding="utf-8") as file:
            parser.write(file)

    def delete(self, key: str) -> None:
        """Remove key while preserving every other stored key."""
        parser = self._load()
        if not parser.has_section(_SECTION) or not parser.has_option(_SECTION, key):
            return None
        parser.remove_option(_SECTION, key)
        with open(self.path, "w", encoding="utf-8") as file:
            parser.write(file)


QUARANTINE_FOLDER_KEY = "quarantine_folder"


@dataclass(frozen=True, slots=True)
class QuarantineFolderSettings:
    """Loaded quarantine folder with its validation status."""

    status: SettingsStatus
    folder: Path | None


def load_quarantine_folder(
    store: Any,
    *,
    folder_check: Callable[[Path], bool] | None = None,
) -> QuarantineFolderSettings:
    """Load and validate the stored quarantine folder path."""
    try:
        raw = store.read(QUARANTINE_FOLDER_KEY)
    except Exception:
        return QuarantineFolderSettings(SettingsStatus.NEEDS_REPAIR, None)
    if raw is None:
        return QuarantineFolderSettings(SettingsStatus.UNCONFIGURED, None)
    if not str(raw).strip():
        return QuarantineFolderSettings(SettingsStatus.NEEDS_REPAIR, None)
    folder = Path(str(raw).strip())
    check = folder_check if folder_check is not None else _default_quarantine_folder_check
    if not check(folder):
        return QuarantineFolderSettings(SettingsStatus.NEEDS_REPAIR, None)
    return QuarantineFolderSettings(SettingsStatus.READY, folder)


def _default_quarantine_folder_check(folder: Path) -> bool:
    """Reject unavailable or unsafe stored quarantine folders."""
    try:
        if folder.is_symlink() or is_windows_reparse_point(folder):
            return False
        return folder.is_dir() and os.access(
            folder, os.R_OK | os.W_OK | os.X_OK
        )
    except OSError:
        return False


def save_quarantine_folder(store: Any, folder) -> bool:
    """Persist the quarantine folder; report False if the store fails."""
    try:
        store.write(QUARANTINE_FOLDER_KEY, str(folder))
    except Exception:
        return False
    return True


def clear_quarantine_folder(store: Any) -> None:
    """Remove the stored quarantine folder path."""
    store.delete(QUARANTINE_FOLDER_KEY)
