"""Transport-injected KoboldCpp vision classification client."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Protocol

from .endpoint import VisionEndpointConfig
from .vision_connection import TransportResponse
from .vision_response import VISION_CATEGORIES, VisionDecision, VisionResponseError, parse_vision_content


VISION_RESPONSE_MAX_BYTES = 64 * 1024
VISION_CONNECT_TIMEOUT = 5.0
VISION_READ_TIMEOUT = 180.0

_TRANSPORT_ERROR = "The image could not be analyzed by KoboldCpp"
_INVALID_RESPONSE = "The KoboldCpp server returned an invalid response"
_DATA_URL_PREFIX = "data:image/png;base64,"

_SYSTEM_PROMPT = (
    "Classify the image by visual structure only. Do not transcribe or quote any "
    "recognized text. Give a short visual-only reason without private details. "
    "Choose exactly one category: ordinary, screenshot, captioned_meme, social_post, "
    "reaction_image, comic, image_macro, or uncertain. Use uncertain when the visual "
    "evidence is insufficient. Return only the requested JSON object."
)
_USER_INSTRUCTION = "Classify this image using the required categories and JSON schema."


class VisionClientError(RuntimeError):
    """Raised when one image cannot be safely classified."""


class VisionCancelled(VisionClientError):
    """Raised when vision classification is cancelled."""


class _Transport(Protocol):
    def request(self, method: str, url: str, **kwargs: object) -> TransportResponse: ...


def _validate_data_url(data_url: str) -> None:
    if not isinstance(data_url, str) or not data_url.startswith(_DATA_URL_PREFIX):
        raise VisionClientError("A PNG image is required")
    encoded = data_url[len(_DATA_URL_PREFIX) :]
    if not encoded:
        raise VisionClientError("A PNG image is required")
    try:
        base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise VisionClientError("A PNG image is required") from None


def _request_body(model: str, data_url: str) -> bytes:
    schema = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": sorted(VISION_CATEGORIES)},
            "reason": {"type": "string", "minLength": 1, "maxLength": 160},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["category", "reason", "confidence"],
        "additionalProperties": False,
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _USER_INSTRUCTION},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": 160,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "vision_decision",
                "strict": True,
                "schema": schema,
            },
        },
    }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _response_content(response: TransportResponse) -> str:
    if response.status != 200:
        raise VisionClientError("The KoboldCpp image request failed")
    if len(response.body) > VISION_RESPONSE_MAX_BYTES:
        raise VisionClientError("The KoboldCpp response is too large")
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise VisionClientError(_INVALID_RESPONSE) from None
    if not isinstance(payload, dict):
        raise VisionClientError(_INVALID_RESPONSE)
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise VisionClientError(_INVALID_RESPONSE)
    choice = choices[0]
    if not isinstance(choice, dict) or choice.get("refusal") not in (None, ""):
        raise VisionClientError(_INVALID_RESPONSE)
    message = choice.get("message")
    if (
        not isinstance(message, dict)
        or message.get("role") != "assistant"
        or message.get("refusal") not in (None, "")
    ):
        raise VisionClientError(_INVALID_RESPONSE)
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise VisionClientError(_INVALID_RESPONSE)
    return content


def classify_image(
    config: VisionEndpointConfig,
    data_url: str,
    transport: _Transport,
    cancel_event: object | None = None,
) -> VisionDecision:
    """Classify one prepared PNG through exactly one injected transport request."""
    model = config.model
    if not isinstance(model, str) or not model.strip():
        raise VisionClientError("A discovered model is required")
    _validate_data_url(data_url)
    if cancel_event is not None and getattr(cancel_event, "is_set")():
        raise VisionCancelled("The image analysis was cancelled")

    try:
        response = transport.request(
            "POST",
            config.chat_completions_url,
            headers={"Content-Type": "application/json"},
            body=_request_body(model.strip(), data_url),
            connect_timeout=VISION_CONNECT_TIMEOUT,
            read_timeout=VISION_READ_TIMEOUT,
            max_response_bytes=VISION_RESPONSE_MAX_BYTES,
            cancel_event=cancel_event,
        )
    except VisionCancelled:
        raise
    except Exception:
        if cancel_event is not None and getattr(cancel_event, "is_set")():
            raise VisionCancelled("The image analysis was cancelled") from None
        raise VisionClientError(_TRANSPORT_ERROR) from None

    if cancel_event is not None and getattr(cancel_event, "is_set")():
        raise VisionCancelled("The image analysis was cancelled")
    content = _response_content(response)
    try:
        return parse_vision_content(content)
    except VisionResponseError:
        raise VisionClientError(_INVALID_RESPONSE) from None
