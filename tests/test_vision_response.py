"""Strict parsing of KoboldCpp classification content."""

from __future__ import annotations

import inspect
import json
import math

import pytest

import img_ai_filter.vision_response as vision_response
from img_ai_filter.vision_response import VisionResponseError, parse_vision_content


LABELS = [
    "ordinary",
    "screenshot",
    "captioned_meme",
    "reaction_image",
    "comic",
    "image_macro",
    "uncertain",
]


def _content(
    category: str = "screenshot",
    reason: str = "The image uses a software interface layout.",
    confidence: object = 0.9,
) -> str:
    return json.dumps(
        {"category": category, "reason": reason, "confidence": confidence}
    )


@pytest.mark.parametrize("category", LABELS)
def test_accepts_every_exact_category(category: str) -> None:
    decision = parse_vision_content(_content(category=category))

    assert decision.category == category
    assert decision.reason == "The image uses a software interface layout."
    assert decision.confidence == 0.9
    assert decision.is_candidate is (category not in {"ordinary", "uncertain"})
    assert decision.is_uncertain is (category == "uncertain")


@pytest.mark.parametrize("confidence", [0, 0.0, 0.5, 1, 1.0])
def test_accepts_finite_confidence_boundaries(confidence: float) -> None:
    assert parse_vision_content(_content(confidence=confidence)).confidence == confidence


@pytest.mark.parametrize(
    "content",
    [
        "",
        "   \n\t",
        "[]",
        "null",
        "true",
        "42",
        '```json\n{"category":"ordinary","reason":"Photo.","confidence":1}\n```',
        'Result: {"category":"ordinary","reason":"Photo.","confidence":1}',
        '{"category":"ordinary","reason":"Photo.","confidence":1} trailing',
        '{"category":"ordinary","reason":"Photo.","confidence":1}{"category":"ordinary","reason":"Photo.","confidence":1}',
    ],
)
def test_rejects_empty_non_object_fenced_or_surrounded_content(content: str) -> None:
    with pytest.raises(VisionResponseError):
        parse_vision_content(content)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"category": "ordinary"},
        {"category": "ordinary", "reason": "Photo."},
        {"category": "ordinary", "confidence": 0.5},
        {"category": "ordinary", "reason": "Photo.", "confidence": 0.5, "extra": 1},
    ],
)
def test_requires_exactly_three_fields(payload: dict[str, object]) -> None:
    with pytest.raises(VisionResponseError, match="fields"):
        parse_vision_content(json.dumps(payload))


def test_rejects_duplicate_json_keys() -> None:
    content = (
        '{"category":"ordinary","category":"screenshot",'
        '"reason":"Photo.","confidence":0.5}'
    )

    with pytest.raises(VisionResponseError, match="duplicate"):
        parse_vision_content(content)


@pytest.mark.parametrize("category", ["", "photo", "Screenshot", None, 1])
def test_rejects_unknown_or_malformed_category(category: object) -> None:
    with pytest.raises(VisionResponseError, match="category"):
        parse_vision_content(_content(category=category))


def test_rejects_removed_social_post_category() -> None:
    with pytest.raises(VisionResponseError, match="category"):
        parse_vision_content(_content(category="social_post"))


@pytest.mark.parametrize(
    "confidence",
    [True, False, None, "0.5", -0.01, 1.01, float("nan"), float("inf")],
)
def test_rejects_invalid_confidence(confidence: object) -> None:
    with pytest.raises(VisionResponseError, match="confidence"):
        parse_vision_content(_content(confidence=confidence))


@pytest.mark.parametrize(
    "reason",
    [
        "",
        "   ",
        "x" * 161,
        "/home/chris/private/image.png",
        r"C:\\Users\\Chris\\image.png",
        "The logits select class_id 4.",
        "Recognized text: private account number 1234",
        "Endpoint http://192.168.0.239 returned this result.",
        "The API key was accepted.",
    ],
)
def test_rejects_empty_long_or_sensitive_reason(reason: str) -> None:
    with pytest.raises(VisionResponseError, match="reason"):
        parse_vision_content(_content(reason=reason))


def test_strips_safe_reason_whitespace() -> None:
    decision = parse_vision_content(_content(reason="  Software interface layout.  "))

    assert decision.reason == "Software interface layout."


def test_decision_is_immutable() -> None:
    decision = parse_vision_content(_content())

    with pytest.raises((AttributeError, TypeError)):
        decision.category = "ordinary"


def test_response_module_has_no_gui_network_or_image_dependency() -> None:
    source = inspect.getsource(vision_response)
    assert "PySide" not in source
    assert "socket" not in source
    assert "PIL" not in source
