"""KoboldCpp capability and loaded-model discovery tests."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import json

import pytest

from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.vision_connection import (
    KOBOLDCPP_DISCOVERY_MAX_BYTES,
    TransportResponse,
    VisionConnectionError,
    discover_koboldcpp,
)


@dataclass
class FakeTransport:
    responses: dict[str, TransportResponse | Exception]

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs) -> TransportResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def _response(payload: object, status: int = 200) -> TransportResponse:
    return TransportResponse(
        status=status,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


def _config():
    return build_vision_endpoint_config("http://192.168.0.239:5001/v1/")


def _valid_transport() -> FakeTransport:
    config = _config()
    return FakeTransport(
        {
            config.capabilities_url: _response(
                {
                    "result": "KoboldCpp",
                    "version": "1.121",
                    "protected": False,
                    "llm": True,
                    "vision": True,
                }
            ),
            config.models_url: _response(
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "koboldcpp/Qwen3-VL-8B-Instruct-Q4_K_S",
                            "object": "model",
                        }
                    ],
                }
            ),
        }
    )


def test_discovers_koboldcpp_version_vision_and_first_loaded_model() -> None:
    transport = _valid_transport()

    info = discover_koboldcpp(_config(), transport)

    assert info.version == "1.121"
    assert info.model == "koboldcpp/Qwen3-VL-8B-Instruct-Q4_K_S"
    assert info.vision is True
    assert info.protected is False
    assert [call["method"] for call in transport.calls] == ["GET", "GET"]
    assert [call["url"] for call in transport.calls] == [
        _config().capabilities_url,
        _config().models_url,
    ]
    assert all(call["body"] is None for call in transport.calls)
    assert all(call["max_response_bytes"] == KOBOLDCPP_DISCOVERY_MAX_BYTES for call in transport.calls)


def test_discovery_selects_first_model_deterministically() -> None:
    config = _config()
    transport = _valid_transport()
    transport.responses[config.models_url] = _response(
        {
            "object": "list",
            "data": [
                {"id": "first-model", "object": "model"},
                {"id": "second-model", "object": "model"},
            ],
        }
    )

    assert discover_koboldcpp(config, transport).model == "first-model"


@pytest.mark.parametrize(
    "payload,match",
    [
        ({}, "KoboldCpp"),
        ({"result": "OtherServer", "version": "1", "protected": False, "llm": True, "vision": True}, "KoboldCpp"),
        ({"result": "KoboldCpp", "version": "", "protected": False, "llm": True, "vision": True}, "version"),
        ({"result": "KoboldCpp", "version": "1", "protected": False, "llm": False, "vision": True}, "language model"),
        ({"result": "KoboldCpp", "version": "1", "protected": False, "llm": True, "vision": False}, "vision"),
        ({"result": "KoboldCpp", "version": "1", "protected": True, "llm": True, "vision": True}, "authentication"),
        ({"result": "KoboldCpp", "version": "1", "protected": "false", "llm": True, "vision": True}, "capabilities"),
    ],
)
def test_rejects_incompatible_capability_payloads(payload: object, match: str) -> None:
    config = _config()
    transport = _valid_transport()
    transport.responses[config.capabilities_url] = _response(payload)

    with pytest.raises(VisionConnectionError, match=match):
        discover_koboldcpp(config, transport)

    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"object": "list"},
        {"object": "list", "data": []},
        {"object": "list", "data": [{}]},
        {"object": "list", "data": [{"id": ""}]},
        {"object": "list", "data": [{"id": 123}]},
        {"object": "list", "data": "model"},
    ],
)
def test_rejects_missing_or_invalid_models(payload: object) -> None:
    config = _config()
    transport = _valid_transport()
    transport.responses[config.models_url] = _response(payload)

    with pytest.raises(VisionConnectionError, match="model"):
        discover_koboldcpp(config, transport)


@pytest.mark.parametrize(
    "url_name,status",
    [("capabilities_url", 301), ("capabilities_url", 401), ("capabilities_url", 500), ("models_url", 302), ("models_url", 503)],
)
def test_rejects_redirect_and_error_status_without_exposing_body(
    url_name: str, status: int
) -> None:
    config = _config()
    transport = _valid_transport()
    secret = "private-server-body"
    target = getattr(config, url_name)
    transport.responses[target] = TransportResponse(
        status=status,
        headers={"location": "http://8.8.8.8/steal"},
        body=secret.encode(),
    )

    with pytest.raises(VisionConnectionError) as raised:
        discover_koboldcpp(config, transport)

    assert secret not in str(raised.value)
    assert "8.8.8.8" not in str(raised.value)


@pytest.mark.parametrize("body", [b"", b"not-json", b"[]", b"null"])
def test_rejects_empty_malformed_or_non_object_json(body: bytes) -> None:
    config = _config()
    transport = _valid_transport()
    transport.responses[config.capabilities_url] = TransportResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=body,
    )

    with pytest.raises(VisionConnectionError, match="response"):
        discover_koboldcpp(config, transport)


def test_rejects_oversized_response_even_if_transport_returns_it() -> None:
    config = _config()
    transport = _valid_transport()
    transport.responses[config.capabilities_url] = TransportResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=b"x" * (KOBOLDCPP_DISCOVERY_MAX_BYTES + 1),
    )

    with pytest.raises(VisionConnectionError, match="large"):
        discover_koboldcpp(config, transport)


def test_translates_transport_failure_to_fixed_safe_error() -> None:
    config = _config()
    transport = _valid_transport()
    transport.responses[config.capabilities_url] = RuntimeError(
        "socket failed with private-token"
    )

    with pytest.raises(VisionConnectionError) as raised:
        discover_koboldcpp(config, transport)

    assert str(raised.value) == "The KoboldCpp server could not be reached"
    assert "private-token" not in str(raised.value)


def test_connection_module_has_no_gui_or_image_dependency() -> None:
    import img_ai_filter.vision_connection as module

    source = inspect.getsource(module)
    assert "PySide" not in source
    assert "PIL" not in source
