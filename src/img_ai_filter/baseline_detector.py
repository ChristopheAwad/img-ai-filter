"""Metadata and geometry baseline candidate detector.

This detector decides from image dimensions and aspect ratio only. It never
opens image content, never reads beyond header metadata, and stays fully
offline. It is deliberately weak: it exists to establish a truthful baseline
for the candidate detection benchmark.

Rules are kept conservative so ordinary photos are rarely misflagged:
- A portrait ratio from 0.5 through 0.62 (common phone screens 9:16 to 9:20)
  becomes a screenshot candidate.
- A landscape ratio from 1.5 through 1.85 (common desktop screens 3:2 to 16:9)
  becomes a screenshot candidate.
- A square image within tolerance of 1.0 (common reaction images and memes)
  becomes a screenshot candidate with a moderate confidence.
- Still-photo ratios such as 4:3 and 3:2 stay ordinary.

No filename is used as evidence. Decode failures and symlinks become typed
per-file failures, never fabricated classifications.
"""

from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the eval extra supplies Pillow
    Image = None  # type: ignore[assignment]

from img_ai_filter.detection import (
    AnalysisFailure,
    DECODE_FAILURE,
    DetectionResult,
    LIMIT_FAILURE,
    ORDINARY,
    SAFE_MAX_PIXELS,
    SCREENSHOT,
    SYMLINK_FAILURE,
)


class GeometryDetector:
    """Decide from image dimensions and aspect ratio only, fully offline."""

    name = "geometry-baseline"

    _PORTRAIT_MIN = 0.50
    _PORTRAIT_MAX = 0.62
    _LANDSCAPE_MIN = 1.50
    _LANDSCAPE_MAX = 1.85
    _SQUARE_TOLERANCE = 0.05

    @staticmethod
    def analyze(path: Path) -> DetectionResult | AnalysisFailure:
        if path.is_symlink():
            return AnalysisFailure(
                path=path,
                kind=SYMLINK_FAILURE,
                message="Symbolic links are not scanned.",
            )
        if Image is None:
            return AnalysisFailure(
                path=path,
                kind="unsupported",
                message="Image decoding is not installed.",
            )

        try:
            with Image.open(path) as image:
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > SAFE_MAX_PIXELS:
                    return AnalysisFailure(
                        path=path,
                        kind=LIMIT_FAILURE,
                        message="Image dimensions exceed the safe decode limit.",
                    )
                ratio = width / height
        except Exception:  # noqa: BLE001 - damaged or foreign content is a per-file failure
            return AnalysisFailure(
                path=path,
                kind=DECODE_FAILURE,
                message="The image cannot be decoded safely.",
            )

        if GeometryDetector._portrait(ratio):
            return DetectionResult(
                is_candidate=True,
                category=SCREENSHOT,
                reason="Portrait ratio matches a phone screen.",
                confidence=0.93,
                default_checked=True,
            )
        if GeometryDetector._landscape(ratio):
            return DetectionResult(
                is_candidate=True,
                category=SCREENSHOT,
                reason="Wide ratio matches a desktop screen.",
                confidence=0.85,
                default_checked=False,
            )
        if GeometryDetector._square(ratio):
            return DetectionResult(
                is_candidate=True,
                category=SCREENSHOT,
                reason="Square ratio matches reaction images and memes.",
                confidence=0.75,
                default_checked=False,
            )
        return DetectionResult(
            is_candidate=False,
            category=ORDINARY,
            reason="Aspect ratio is typical of ordinary photographs.",
            confidence=0.5,
            default_checked=False,
        )

    @staticmethod
    def _portrait(ratio: float) -> bool:
        return GeometryDetector._PORTRAIT_MIN <= ratio <= GeometryDetector._PORTRAIT_MAX

    @staticmethod
    def _landscape(ratio: float) -> bool:
        return GeometryDetector._LANDSCAPE_MIN <= ratio <= GeometryDetector._LANDSCAPE_MAX

    @staticmethod
    def _square(ratio: float) -> bool:
        return abs(ratio - 1.0) <= GeometryDetector._SQUARE_TOLERANCE

    @classmethod
    def describe(cls) -> dict[str, str | int]:
        return {
            "model_bytes": 0,
            "offline": True,
            "approach": "metadata and geometry only; no OCR and no model",
            "dependencies": "pillow",
        }