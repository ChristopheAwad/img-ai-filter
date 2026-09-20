"""Transport-neutral KoboldCpp capability and model discovery."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Mapping, Protocol

from .endpoint import VisionEndpointConfig


KOBOLDCPP_DISCOVERY_MAX_BYTES = 64 * 1024
_DISCOVERY_CONNECT_TIMEOUT = 5.0
_DISCOVERY_READ_TIMEOUT = 5.0
_UNREACHABLE_ERROR = "The KoboldCpp server could not be reached"


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class VisionConnectionError(RuntimeError):
    """Raised when KoboldCpp discovery cannot establish a usable server."""


@dataclass(frozen=True, slots=True)
class KoboldCppInfo:
    version: str
    model: str
    vision: bool
    protected: bool


class _Transport(Protocol):
    def request(self, method: str, url: str, **kwargs: object) -> TransportResponse: ...


def _request_json_object(
    transport: _Transport, url: str, request_name: str
) -> dict[str, object]:
    try:
        response = transport.request(
            "GET",
            url,
            body=None,
            connect_timeout=_DISCOVERY_CONNECT_TIMEOUT,
            read_timeout=_DISCOVERY_READ_TIMEOUT,
            max_response_bytes=KOBOLDCPP_DISCOVERY_MAX_BYTES,
        )
    except Exception:
        raise VisionConnectionError(_UNREACHABLE_ERROR) from None

    if response.status != 200:
        raise VisionConnectionError(f"The KoboldCpp {request_name} request failed")
    if len(response.body) > KOBOLDCPP_DISCOVERY_MAX_BYTES:
        raise VisionConnectionError("The KoboldCpp response is too large")

    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise VisionConnectionError(
            "The KoboldCpp server returned an invalid response"
        ) from None
    if not isinstance(payload, dict):
        raise VisionConnectionError(
            "The KoboldCpp server returned an invalid response"
        )
    return payload


def discover_koboldcpp(
    config: VisionEndpointConfig, transport: _Transport
) -> KoboldCppInfo:
    """Discover and validate KoboldCpp capabilities and its first loaded model."""
    capabilities = _request_json_object(
        transport, config.capabilities_url, "capabilities"
    )
    if capabilities.get("result") != "KoboldCpp":
        raise VisionConnectionError("The server is not a KoboldCpp server")

    version = capabilities.get("version")
    if not isinstance(version, str) or not version.strip():
        raise VisionConnectionError("The KoboldCpp version is invalid")

    protected = capabilities.get("protected")
    llm = capabilities.get("llm")
    vision = capabilities.get("vision")
    if not all(type(value) is bool for value in (protected, llm, vision)):
        raise VisionConnectionError("The KoboldCpp capabilities are invalid")
    if protected:
        raise VisionConnectionError("KoboldCpp authentication is not supported")
    if not llm:
        raise VisionConnectionError("KoboldCpp has no language model loaded")
    if not vision:
        raise VisionConnectionError("KoboldCpp vision support is not available")

    models = _request_json_object(transport, config.models_url, "models")
    data = models.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise VisionConnectionError("The KoboldCpp model response is invalid")
    model = data[0].get("id")
    if not isinstance(model, str) or not model.strip():
        raise VisionConnectionError("The KoboldCpp model identifier is invalid")

    return KoboldCppInfo(
        version=version.strip(),
        model=model.strip(),
        vision=vision,
        protected=protected,
    )
