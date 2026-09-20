"""KoboldCpp base URL and discovered model persistence tests."""

from __future__ import annotations

from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.settings import (
    ENDPOINT_MODEL_KEY,
    ENDPOINT_URL_KEY,
    SettingsStatus,
    load_vision_endpoint_settings,
    save_vision_endpoint_settings,
)


class MemoryStore:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def read(self, key: str) -> str | None:
        return self.values.get(key)

    def write(self, key: str, value: str) -> None:
        self.values[key] = value


def test_absent_vision_settings_are_unconfigured() -> None:
    loaded = load_vision_endpoint_settings(MemoryStore())

    assert loaded.status is SettingsStatus.UNCONFIGURED
    assert loaded.config is None


def test_base_without_discovered_model_needs_connection_test() -> None:
    loaded = load_vision_endpoint_settings(
        MemoryStore({ENDPOINT_URL_KEY: "http://192.168.0.239:5001/v1/"})
    )

    assert loaded.status is SettingsStatus.NEEDS_REPAIR
    assert loaded.config is None


def test_save_and_load_vision_config_round_trip() -> None:
    config = build_vision_endpoint_config(
        "http://192.168.0.239:5001/v1/", model="loaded-model"
    )
    store = MemoryStore()

    save_vision_endpoint_settings(store, config)
    loaded = load_vision_endpoint_settings(store)

    assert loaded.status is SettingsStatus.READY
    assert loaded.config == config
    assert store.values == {
        ENDPOINT_URL_KEY: "http://192.168.0.239:5001/v1/",
        ENDPOINT_MODEL_KEY: "loaded-model",
    }


def test_old_chat_completion_url_requires_repair() -> None:
    loaded = load_vision_endpoint_settings(
        MemoryStore(
            {
                ENDPOINT_URL_KEY: "http://192.168.0.239:5001/v1/chat/completions",
                ENDPOINT_MODEL_KEY: "old-model",
            }
        )
    )

    assert loaded.status is SettingsStatus.NEEDS_REPAIR
    assert loaded.config is None


def test_blank_or_invalid_vision_settings_require_repair() -> None:
    for values in (
        {ENDPOINT_URL_KEY: "", ENDPOINT_MODEL_KEY: "model"},
        {ENDPOINT_URL_KEY: "http://8.8.8.8/v1/", ENDPOINT_MODEL_KEY: "model"},
        {ENDPOINT_URL_KEY: "http://127.0.0.1/v1/", ENDPOINT_MODEL_KEY: ""},
        {ENDPOINT_MODEL_KEY: "model"},
    ):
        loaded = load_vision_endpoint_settings(MemoryStore(values))
        assert loaded.status is SettingsStatus.NEEDS_REPAIR
        assert loaded.config is None
