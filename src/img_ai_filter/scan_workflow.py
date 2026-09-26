"""Sequential, GUI-neutral server scan workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

from .image_payload import ImagePayloadError, SourceIdentity, prepare_image
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
    identity: SourceIdentity
    thumbnail_png: bytes
    thumbnail_width: int
    thumbnail_height: int
    checked: bool = field(default=False, init=False)


@dataclass(frozen=True, slots=True)
class ScanFailureBreakdown:
    """Safe aggregate failure counts; no image paths or server output."""

    preparation: int = 0
    timeout: int = 0
    connection: int = 0
    server_response: int = 0
    invalid_response: int = 0
    other: int = 0

    def counts(self) -> tuple[int, ...]:
        return (
            self.preparation,
            self.timeout,
            self.connection,
            self.server_response,
            self.invalid_response,
            self.other,
        )


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
    failure_breakdown: ScanFailureBreakdown = field(default_factory=ScanFailureBreakdown)
    filtered: int = 0

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)


CANDIDATE_CATEGORIES = (
    "screenshot",
    "captioned_meme",
    "reaction_image",
    "comic",
    "image_macro",
    "paper_document",
)
_CANDIDATE_CATEGORIES = frozenset(CANDIDATE_CATEGORIES)


def validate_selected_categories(categories: object) -> frozenset[str]:
    """Accept only a nonempty set of the fixed review categories."""
    if not isinstance(categories, (set, frozenset)) or not categories:
        raise ValueError("Choose at least one valid category")
    if not categories <= _CANDIDATE_CATEGORIES:
        raise ValueError("Choose only available categories")
    return frozenset(categories)


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
    selected_categories: frozenset[str] = _CANDIDATE_CATEGORIES,
) -> ScanSummary:
    """Discover and classify images one at a time without exposing failures."""
    selected_categories = validate_selected_categories(selected_categories)

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
            ScanFailureBreakdown(**failure_counts),
            filtered,
        )

    candidates: list[ScanCandidate] = []
    discovered = analyzed = ordinary = uncertain = failed = skipped_count = filtered = 0
    failure_counts = {key: 0 for key in ScanFailureBreakdown.__dataclass_fields__}
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
        except (ImagePayloadError, VisionClientError) as error:
            failed += 1
            kind = "preparation" if isinstance(error, ImagePayloadError) else error.kind
            failure_counts[kind if kind in failure_counts else "other"] += 1
        else:
            analyzed += 1
            if decision.category in selected_categories:
                candidates.append(
                    ScanCandidate(
                        path,
                        decision.category,
                        decision.reason,
                        decision.confidence,
                        prepared.identity,
                        prepared.thumbnail_png,
                        prepared.thumbnail_width,
                        prepared.thumbnail_height,
                    )
                )
            elif decision.category in _CANDIDATE_CATEGORIES:
                filtered += 1
            elif decision.category == "uncertain":
                uncertain += 1
            else:
                ordinary += 1
        if progress is not None:
            progress(analyzed + failed, discovered)

    if discovered > 0 and analyzed == 0 and failed == discovered:
        state = ScanState.FAILED
    elif failed or skipped_count:
        state = ScanState.COMPLETED_WITH_SKIPS
    else:
        state = ScanState.COMPLETED
    return summary(state)
