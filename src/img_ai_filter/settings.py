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
from pathlib import Path
from typing import Any

from img_ai_filter.endpoint import (
    EndpointConfig,
    EndpointValidationError,
    VisionEndpointConfig,
    build_endpoint_config,
    build_vision_endpoint_config,
)

ENDPOINT_URL_KEY = "endpoint_url"
ENDPOINT_MODEL_KEY = "endpoint_model"
CREDENTIAL_SERVICE = "img_ai_filter"

_SECTION = "settings"


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
