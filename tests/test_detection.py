"""Result-contract tests for the detector boundary."""

import math
from pathlib import Path

import pytest

from img_ai_filter.detection import DetectionResult, DetectionError


def test_valid_ordinary_result_is_rejected_as_candidate() -> None:
    result = DetectionResult(
        is_candidate=False,
        category="ordinary",
        reason="No candidate markers detected.",
        confidence=0.5,
        default_checked=False,
    )

    assert not result.is_candidate
    assert result.category == "ordinary"
    assert result.default_checked is False
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_valid_unchecked_candidate_at_boundary_confidence(confidence: float) -> None:
    result = DetectionResult(
        is_candidate=True,
        category="screenshot",
        reason="Layout matches a screen capture.",
        confidence=confidence,
        default_checked=False,
    )

    assert result.is_candidate
    assert result.default_checked is False


def test_valid_checked_high_confidence_candidate() -> None:
    result = DetectionResult(
        is_candidate=True,
        category="captioned_meme",
        reason="Large overlaid text detected.",
        confidence=0.98,
        default_checked=True,
    )

    assert result.is_candidate
    assert result.default_checked is True


@pytest.mark.parametrize(
    "confidence",
    [-0.001, 1.001, math.nan, math.inf, -math.inf],
)
def test_rejects_non_finite_or_out_of_range_confidence(confidence: float) -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=True,
            category="screenshot",
            reason="Layout matches a screen capture.",
            confidence=confidence,
            default_checked=False,
        )


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_rejects_empty_or_whitespace_reason(reason: str) -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=True,
            category="screenshot",
            reason=reason,
            confidence=0.9,
            default_checked=False,
        )


def test_rejects_ordinary_result_marked_as_candidate() -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=True,
            category="ordinary",
            reason="No candidate markers detected.",
            confidence=0.5,
            default_checked=False,
        )


@pytest.mark.parametrize("category", ["ordinary", "uncertain"])
def test_rejects_ordinary_or_uncertain_result_marked_checked(category: str) -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=True,
            category=category,
            reason="Candidate marker found.",
            confidence=0.99,
            default_checked=True,
        )


def test_rejects_non_candidate_result_with_candidate_category() -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=False,
            category="screenshot",
            reason="Layout matches a screen capture.",
            confidence=0.5,
            default_checked=False,
        )


def test_rejects_candidate_result_with_ordinary_category() -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=True,
            category="ordinary",
            reason="No candidate markers detected.",
            confidence=0.5,
            default_checked=False,
        )


def test_rejects_unknown_category() -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=True,
            category="selfie",
            reason="Layout matches a screen capture.",
            confidence=0.9,
            default_checked=False,
        )


def test_result_is_immutable() -> None:
    result = DetectionResult(
        is_candidate=False,
        category="ordinary",
        reason="No candidate markers detected.",
        confidence=0.5,
        default_checked=False,
    )

    with pytest.raises(AttributeError):
        result.category = "screenshot"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        result.confidence = 1.0  # type: ignore[misc]


def test_reason_must_be_short_user_readable_text() -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=True,
            category="screenshot",
            reason=(
                "raw logits tensor=[1.0, -2.0, 3.0] class_id=42 "
                "model_embedding=[0.1,0.2,0.3]"
            ),
            confidence=0.9,
            default_checked=False,
        )


def test_reason_must_not_contain_filesystem_details() -> None:
    with pytest.raises(DetectionError):
        DetectionResult(
            is_candidate=True,
            category="screenshot",
            reason=f"Found hidden marker in {Path('/secret/cache.db')}",
            confidence=0.9,
            default_checked=False,
        )


def test_module_must_not_import_pyside6() -> None:
    assert "PySide6" not in _module_source()


def _module_source() -> str:
    import inspect

    import img_ai_filter.detection as detection

    return inspect.getsource(detection)