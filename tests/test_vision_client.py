"""KoboldCpp OpenAI-compatible vision request and response tests."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import json
from threading import Event

import pytest

from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.vision_client import (
    VISION_RESPONSE_MAX_BYTES,
    VisionCancelled,
    VisionClientError,
    classify_image,
)
from img_ai_filter.vision_connection import TransportResponse


@dataclass
class FakeTransport:
    response: TransportResponse | Exception

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs) -> TransportResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _config():
    return build_vision_endpoint_config(
        "http://192.168.0.239:5001/v1/", model="koboldcpp/vision-model"
    )


def _response(content: object, status: int = 200) -> TransportResponse:
    payload = {
        "id": "response-id",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
    }
    return TransportResponse(
        status=status,
        headers={"content-type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )


def _decision_content() -> str:
    return json.dumps(
        {
            "category": "screenshot",
            "reason": "The image uses a software interface layout.",
            "confidence": 0.91,
        }
    )


def test_sends_one_nonstreaming_schema_constrained_image_request() -> None:
    transport = FakeTransport(_response(_decision_content()))
    data_url = "data:image/png;base64,aW1hZ2U="

    decision = classify_image(_config(), data_url, transport)

    assert decision.category == "screenshot"
    assert decision.confidence == 0.91
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == _config().chat_completions_url
    assert call["connect_timeout"] == 5.0
    assert call["read_timeout"] == 180.0
    assert call["max_response_bytes"] == VISION_RESPONSE_MAX_BYTES
    assert call["cancel_event"] is None
    assert call["headers"] == {"Content-Type": "application/json"}

    payload = json.loads(call["body"])
    assert payload["model"] == "koboldcpp/vision-model"
    assert payload["stream"] is False
    assert payload["temperature"] == 0
    assert payload["max_tokens"] <= 160
    assert payload["response_format"]["type"] == "json_schema"
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["category", "reason", "confidence"]
    assert set(schema["properties"]["category"]["enum"]) == {
        "ordinary",
        "screenshot",
        "captioned_meme",
        "reaction_image",
        "comic",
        "image_macro",
        "uncertain",
    }
    user_content = payload["messages"][1]["content"]
    image_items = [item for item in user_content if item["type"] == "image_url"]
    assert image_items == [{"type": "image_url", "image_url": {"url": data_url}}]
    assert "source" not in json.dumps(payload).lower()


def test_prompt_forbids_recognized_text_and_requires_visual_reason_only() -> None:
    transport = FakeTransport(_response(_decision_content()))

    classify_image(_config(), "data:image/png;base64,aQ==", transport)

    payload = json.loads(transport.calls[0]["body"])
    prompt = json.dumps(payload["messages"]).lower()
    assert "do not transcribe" in prompt
    assert "visual" in prompt
    assert "ordinary" in prompt
    assert "uncertain" in prompt
    assert "social_post" not in prompt


def test_rejects_removed_social_post_response() -> None:
    content = json.dumps(
        {
            "category": "social_post",
            "reason": "The image resembles a social media post.",
            "confidence": 0.95,
        }
    )
    transport = FakeTransport(_response(content))

    with pytest.raises(VisionClientError, match="invalid response"):
        classify_image(_config(), "data:image/png;base64,aQ==", transport)


def test_passes_cancellation_event_to_transport() -> None:
    transport = FakeTransport(_response(_decision_content()))
    cancel = Event()

    classify_image(_config(), "data:image/png;base64,aQ==", transport, cancel_event=cancel)

    assert transport.calls[0]["cancel_event"] is cancel


def test_cancelled_before_request_sends_nothing() -> None:
    transport = FakeTransport(_response(_decision_content()))
    cancel = Event()
    cancel.set()

    with pytest.raises(VisionCancelled):
        classify_image(_config(), "data:image/png;base64,aQ==", transport, cancel_event=cancel)

    assert transport.calls == []


def test_requires_discovered_model_before_sending() -> None:
    config = build_vision_endpoint_config("http://192.168.0.239:5001/v1/")
    transport = FakeTransport(_response(_decision_content()))

    with pytest.raises(VisionClientError, match="model"):
        classify_image(config, "data:image/png;base64,aQ==", transport)

    assert transport.calls == []


@pytest.mark.parametrize("status", [201, 204, 301, 302, 307, 308, 400, 401, 500, 503])
def test_rejects_non_200_status_without_redirect_or_body_leak(status: int) -> None:
    secret = "private-response-body"
    transport = FakeTransport(
        TransportResponse(
            status=status,
            headers={"location": "http://8.8.8.8/steal"},
            body=secret.encode(),
        )
    )

    with pytest.raises(VisionClientError) as raised:
        classify_image(_config(), "data:image/png;base64,aQ==", transport)

    assert len(transport.calls) == 1
    assert secret not in str(raised.value)
    assert "8.8.8.8" not in str(raised.value)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not-json",
        b"[]",
        json.dumps({}).encode(),
        json.dumps({"choices": []}).encode(),
        json.dumps({"choices": [{}]}).encode(),
        json.dumps({"choices": [{"message": {}}]}).encode(),
        json.dumps({"choices": [{"message": {"content": []}}]}).encode(),
        json.dumps({"choices": [{"message": {"content": ""}}]}).encode(),
        json.dumps({"choices": [{"message": {"content": _decision_content()}, "refusal": "no"}]}).encode(),
    ],
)
def test_rejects_invalid_or_refused_response_envelopes(body: bytes) -> None:
    transport = FakeTransport(TransportResponse(200, {}, body))

    with pytest.raises(VisionClientError, match="response"):
        classify_image(_config(), "data:image/png;base64,aQ==", transport)


def test_rejects_oversized_response_even_if_transport_returns_it() -> None:
    transport = FakeTransport(
        TransportResponse(200, {}, b"x" * (VISION_RESPONSE_MAX_BYTES + 1))
    )

    with pytest.raises(VisionClientError, match="large"):
        classify_image(_config(), "data:image/png;base64,aQ==", transport)


def test_transport_failure_is_redacted_and_not_retried() -> None:
    transport = FakeTransport(RuntimeError("private network detail and token"))

    with pytest.raises(VisionClientError) as raised:
        classify_image(_config(), "data:image/png;base64,aQ==", transport)

    assert str(raised.value) == "The image could not be analyzed by KoboldCpp"
    assert len(transport.calls) == 1


def test_transport_failure_after_cancel_event_is_reported_as_cancelled() -> None:
    cancel = Event()

    class CancellingTransport(FakeTransport):
        def request(self, method: str, url: str, **kwargs):
            self.calls.append({"method": method, "url": url, **kwargs})
            cancel.set()
            raise OSError("closed active request")

    transport = CancellingTransport(_response(_decision_content()))

    with pytest.raises(VisionCancelled):
        classify_image(
            _config(),
            "data:image/png;base64,aQ==",
            transport,
            cancel_event=cancel,
        )

    assert len(transport.calls) == 1


def test_invalid_model_content_is_not_exposed() -> None:
    private = "private generated response"
    transport = FakeTransport(_response(private))

    with pytest.raises(VisionClientError) as raised:
        classify_image(_config(), "data:image/png;base64,aQ==", transport)

    assert private not in str(raised.value)


def test_vision_client_has_no_gui_dependency() -> None:
    import img_ai_filter.vision_client as module

    assert "PySide" not in inspect.getsource(module)
