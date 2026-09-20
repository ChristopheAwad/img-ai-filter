"""Sequential, GUI-neutral server scan workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

from .image_payload import ImagePayloadError, prepare_image
from .scanner import ScanError, scan_images
from .vision_client import VisionCancelled, VisionClientError, classify_image


class ScanState(Enum):
    COMPLETED = auto()
    COMPLETED_WITH_SKIPS = auto()
    CANCELLED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class ScanCandidate:
    path: Path
    category: str
    reason: str
    confidence: float
    checked: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class ScanSummary:
    state: ScanState
    candidates: tuple[ScanCandidate, ...]
    discovered: int
    analyzed: int
    ordinary: int
    uncertain: int
    failed: int
    skipped_directories: int

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)


_CANDIDATE_CATEGORIES = frozenset(
    {
        "screenshot",
        "captioned_meme",
        "social_post",
        "reaction_image",
        "comic",
        "image_macro",
    }
)


def run_server_scan(
    folder: Path,
    config: Any,
    transport: Any,
    *,
    scan: Callable[..., Any] = scan_images,
    prepare: Callable[..., Any] = prepare_image,
    classify: Callable[..., Any] = classify_image,
    cancel_event: object | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ScanSummary:
    """Discover and classify images one at a time without exposing failures."""
    def cancelled() -> bool:
        return cancel_event is not None and bool(getattr(cancel_event, "is_set")())

    def summary(state: ScanState) -> ScanSummary:
        return ScanSummary(
            state,
            tuple(candidates),
            discovered,
            analyzed,
            ordinary,
            uncertain,
            failed,
            skipped_count,
        )

    candidates: list[ScanCandidate] = []
    discovered = analyzed = ordinary = uncertain = failed = skipped_count = 0
    if cancelled():
        return summary(ScanState.CANCELLED)

    try:
        scan_result = scan(folder)
    except ScanError:
        raise ScanError("The selected folder could not be scanned") from None

    discovered = len(scan_result.images)
    skipped_count = len(scan_result.skipped_directories)
    for path in scan_result.images:
        if cancelled():
            return summary(ScanState.CANCELLED)
        try:
            prepared = prepare(path)
            decision = classify(
                config,
                prepared.data_url,
                transport,
                cancel_event=cancel_event,
            )
        except VisionCancelled:
            return summary(ScanState.CANCELLED)
        except (ImagePayloadError, VisionClientError, OSError):
            failed += 1
        else:
            analyzed += 1
            if decision.category == "ordinary":
                ordinary += 1
            elif decision.category == "uncertain":
                uncertain += 1
            elif decision.category in _CANDIDATE_CATEGORIES:
                candidates.append(
                    ScanCandidate(
                        path,
                        decision.category,
                        decision.reason,
                        decision.confidence,
                    )
                )
        if progress is not None:
            progress(analyzed + failed, discovered)

    if discovered > 0 and analyzed == 0 and failed == discovered:
        state = ScanState.FAILED
    elif failed or skipped_count:
        state = ScanState.COMPLETED_WITH_SKIPS
    else:
        state = ScanState.COMPLETED
    return summary(state)
