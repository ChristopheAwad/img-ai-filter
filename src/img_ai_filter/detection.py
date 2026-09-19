"""Detector result contract shared by every candidate detector.

This module must stay independent of the GUI and of any optical character
recognition or model library so unit tests can exercise the full contract
without heavy dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Protocol


DetectionError = ValueError


ALL_CATEGORIES = frozenset(
    {
        "ordinary",
        "screenshot",
        "captioned_meme",
        "social_post",
        "reaction_image",
        "comic",
        "image_macro",
        "uncertain",
    }
)

CANDIDATE_CATEGORIES = frozenset(
    {
        "screenshot",
        "captioned_meme",
        "social_post",
        "reaction_image",
        "comic",
        "image_macro",
        "uncertain",
    }
)

ORDINARY = "ordinary"
UNCERTAIN = "uncertain"
SCREENSHOT = "screenshot"
CAPTIONED_MEME = "captioned_meme"
SOCIAL_POST = "social_post"
REACTION_IMAGE = "reaction_image"
COMIC = "comic"
IMAGE_MACRO = "image_macro"

DEFAULT_HIGH_CONFIDENCE_THRESHOLD = 0.9

SAFE_MAX_PIXELS = 100_000_000

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

_FS_INSIDE_REASON = re.compile(
    r"(?:"
    r"[A-Za-z]:[\\/][^\s]*"             # Windows drive path
    r"|(?:[/\\][^\s/\\]+){2,}"          # two or more slash-joined segments
    r"|(?:^|\s)[/\\][A-Za-z][^\s/\\]*"   # absolute token like /etc or \root
    r")"
)


class Detector(Protocol):
    """A detector that turns one image path into a result or a failure."""

    name: str

    @staticmethod
    def analyze(path: Path) -> "DetectionResult | AnalysisFailure": ...

    @classmethod
    def describe(cls) -> dict[str, str | int]:
        """Return stable facts used in evaluation reports."""


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Immutable, validated decision for one image."""

    is_candidate: bool
    category: str
    reason: str
    confidence: float
    default_checked: bool

    def __post_init__(self) -> None:
        if self.category not in ALL_CATEGORIES:
            raise DetectionError(f"Unknown category: {self.category}")

        if not math.isfinite(self.confidence) or not 0.0 <= self.confidence <= 1.0:
            raise DetectionError("Confidence must be a finite number from 0.0 through 1.0")

        if not self.reason.strip():
            raise DetectionError("Reason must not be empty")

        reason_lower = self.reason.strip().lower()
        if any(re.search(rf"\b{re.escape(word)}\b", reason_lower) for word in _MODEL_JARGON):
            raise DetectionError("Reason must not expose model jargon")
        if _FS_INSIDE_REASON.search(self.reason):
            raise DetectionError("Reason must not expose filesystem details")

        if not self.is_candidate and self.category != ORDINARY:
            raise DetectionError("A non-candidate result must use the ordinary category")
        if self.is_candidate and self.category == ORDINARY:
            raise DetectionError("A candidate result must not use the ordinary category")

        if self.category == UNCERTAIN and self.default_checked:
            raise DetectionError("Uncertain results must not start checked")
        if self.category == ORDINARY and self.default_checked:
            raise DetectionError("Ordinary results must not start checked")
        if self.default_checked:
            if not self.is_candidate:
                raise DetectionError("Only candidate results can start checked")
            if self.confidence < DEFAULT_HIGH_CONFIDENCE_THRESHOLD:
                raise DetectionError(
                    "A checked result needs confidence at or above the high-confidence threshold"
                )


@dataclass(frozen=True, slots=True)
class AnalysisFailure:
    """Typed, per-file analysis failure that must not stop evaluation."""

    path: Path
    kind: str
    message: str


DECODE_FAILURE = "decode"
INFERENCE_FAILURE = "inference"
UNSUPPORTED_FAILURE = "unsupported"
LIMIT_FAILURE = "decode-limit"
SYMLINK_FAILURE = "symlink"