"""Strict, privacy-preserving parsing of vision classification output."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re


VISION_CATEGORIES = frozenset(
    {
        "ordinary",
        "screenshot",
        "captioned_meme",
        "reaction_image",
        "comic",
        "image_macro",
        "paper_document",
        "uncertain",
    }
)
MAX_REASON_LENGTH = 160

_MODEL_JARGON = (
    "logits",
    "tensor",
    "class_id",
    "embedding",
    "feature_vector",
    "onnx",
    "weight",
    "activation",
)
_SENSITIVE_PHRASES = (
    "recognized text",
    "endpoint",
    "api key",
    "api-key",
    "image bytes",
    "base64",
    "data:image",
)
_FILE_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/][^\s]*|(?:[/\\][^\s/\\]+){2,}|(?:^|\s)[/\\][A-Za-z][^\s/\\]*)"
)


class VisionResponseError(ValueError):
    """Raised when model output does not match the decision contract."""


@dataclass(frozen=True, slots=True)
class VisionDecision:
    category: str
    reason: str
    confidence: float

    @property
    def is_candidate(self) -> bool:
        return self.category not in {"ordinary", "uncertain"}

    @property
    def is_uncertain(self) -> bool:
        return self.category == "uncertain"


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise VisionResponseError("The response contains a duplicate field")
        result[key] = value
    return result


def parse_vision_content(content: str) -> VisionDecision:
    """Parse exactly one JSON decision object with no sensitive explanation."""
    if not isinstance(content, str) or not content.strip():
        raise VisionResponseError("The response is invalid")
    try:
        payload = json.loads(content, object_pairs_hook=_object_without_duplicates)
    except VisionResponseError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError):
        raise VisionResponseError("The response is invalid") from None

    if not isinstance(payload, dict):
        raise VisionResponseError("The response is invalid")
    if set(payload) != {"category", "reason", "confidence"}:
        raise VisionResponseError("The response fields are invalid")

    category = payload["category"]
    if not isinstance(category, str) or category not in VISION_CATEGORIES:
        raise VisionResponseError("The response category is invalid")

    confidence = payload["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise VisionResponseError("The response confidence is invalid")

    reason_value = payload["reason"]
    if not isinstance(reason_value, str):
        raise VisionResponseError("The response reason is invalid")
    reason = reason_value.strip()
    lowered = reason.casefold()
    if (
        not reason
        or len(reason) > MAX_REASON_LENGTH
        or _FILE_PATH.search(reason)
        or any(re.search(rf"\b{re.escape(term)}\b", lowered) for term in _MODEL_JARGON)
        or any(phrase in lowered for phrase in _SENSITIVE_PHRASES)
        or "http://" in lowered
        or "https://" in lowered
    ):
        raise VisionResponseError("The response reason is invalid")

    return VisionDecision(category, reason, float(confidence))
