"""Sequential GUI-neutral KoboldCpp scan workflow tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from img_ai_filter.endpoint import build_vision_endpoint_config
from img_ai_filter.image_payload import ImagePayloadError
from img_ai_filter.scanner import ScanError, ScanResult
from img_ai_filter.scan_workflow import ScanState, run_server_scan
from img_ai_filter.vision_client import VisionCancelled, VisionClientError
from img_ai_filter.vision_response import VisionDecision


CONFIG = build_vision_endpoint_config(
    "http://192.168.0.239:5001/v1/", model="vision-model"
)


@dataclass(frozen=True)
class Prepared:
    data_url: str


def _decision(category: str, confidence: float = 0.8) -> VisionDecision:
    return VisionDecision(category, f"Visual reason for {category}.", confidence)


def _run(
    paths: tuple[Path, ...],
    outcomes: dict[str, VisionDecision | Exception],
    *,
    skipped: tuple[Path, ...] = (),
    cancel_event: Event | None = None,
    progress=None,
):
    prepared: list[Path] = []
    classified: list[str] = []

    def scan(_folder: Path) -> ScanResult:
        return ScanResult(paths, skipped)

    def prepare(path: Path) -> Prepared:
        prepared.append(path)
        outcome = outcomes[path.name]
        if isinstance(outcome, ImagePayloadError):
            raise outcome
        return Prepared(f"data:image/png;base64,{path.name}")

    def classify(_config, data_url, _transport, *, cancel_event=None):
        name = data_url.rsplit(",", 1)[1]
        classified.append(name)
        outcome = outcomes[name]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    summary = run_server_scan(
        Path("/selected"),
        CONFIG,
        object(),
        scan=scan,
        prepare=prepare,
        classify=classify,
        cancel_event=cancel_event,
        progress=progress,
    )
    return summary, prepared, classified


def test_mixed_scan_is_sequential_ordered_and_counted() -> None:
    paths = tuple(Path(f"{name}.png") for name in ("a", "b", "c", "d", "e"))
    outcomes = {
        "a.png": _decision("ordinary", 0.95),
        "b.png": _decision("screenshot", 0.92),
        "c.png": _decision("uncertain", 0.4),
        "d.png": VisionClientError("private body"),
        "e.png": _decision("image_macro", 0.81),
    }
    progress: list[tuple[int, int]] = []

    summary, prepared, classified = _run(
        paths, outcomes, skipped=(Path("blocked"),), progress=lambda done, total: progress.append((done, total))
    )

    assert prepared == list(paths)
    assert classified == [path.name for path in paths]
    assert [candidate.path for candidate in summary.candidates] == [paths[1], paths[4]]
    assert [candidate.category for candidate in summary.candidates] == [
        "screenshot",
        "image_macro",
    ]
    assert all(candidate.checked is False for candidate in summary.candidates)
    assert summary.state is ScanState.COMPLETED_WITH_SKIPS
    assert summary.discovered == 5
    assert summary.analyzed == 4
    assert summary.candidate_count == 2
    assert summary.ordinary == 1
    assert summary.uncertain == 1
    assert summary.failed == 1
    assert summary.skipped_directories == 1
    assert progress == [(1, 5), (2, 5), (3, 5), (4, 5), (5, 5)]
    assert "private body" not in repr(summary)


@pytest.mark.parametrize(
    "category",
    [
        "screenshot",
        "captioned_meme",
        "social_post",
        "reaction_image",
        "comic",
        "image_macro",
    ],
)
def test_each_candidate_category_is_returned_unchecked(category: str) -> None:
    path = Path("one.png")

    summary, _, _ = _run((path,), {path.name: _decision(category, 1.0)})

    candidate = summary.candidates[0]
    assert candidate.category == category
    assert candidate.reason == f"Visual reason for {category}."
    assert candidate.confidence == 1.0
    assert candidate.checked is False
    assert summary.state is ScanState.COMPLETED


def test_empty_folder_completes_with_zero_counts_and_no_requests() -> None:
    summary, prepared, classified = _run((), {})

    assert summary.state is ScanState.COMPLETED
    assert summary.discovered == summary.analyzed == summary.failed == 0
    assert summary.candidates == ()
    assert prepared == classified == []


def test_all_ordinary_and_all_uncertain_are_successful_without_rows() -> None:
    ordinary, _, _ = _run(
        (Path("a.png"), Path("b.png")),
        {"a.png": _decision("ordinary"), "b.png": _decision("ordinary")},
    )
    uncertain, _, _ = _run(
        (Path("a.png"), Path("b.png")),
        {"a.png": _decision("uncertain"), "b.png": _decision("uncertain")},
    )

    assert ordinary.state is ScanState.COMPLETED
    assert ordinary.ordinary == 2
    assert ordinary.candidates == ()
    assert uncertain.state is ScanState.COMPLETED
    assert uncertain.uncertain == 2
    assert uncertain.candidates == ()


@pytest.mark.parametrize("failure_index", [0, 1, 2])
def test_first_middle_or_last_failure_does_not_stop_other_images(
    failure_index: int,
) -> None:
    paths = tuple(Path(f"{index}.png") for index in range(3))
    outcomes = {path.name: _decision("ordinary") for path in paths}
    outcomes[paths[failure_index].name] = VisionClientError("private")

    summary, _, classified = _run(paths, outcomes)

    assert classified == [path.name for path in paths]
    assert summary.analyzed == 2
    assert summary.failed == 1
    assert summary.state is ScanState.COMPLETED_WITH_SKIPS


def test_decode_failure_does_not_call_server_and_later_image_runs() -> None:
    paths = (Path("bad.png"), Path("good.png"))
    summary, prepared, classified = _run(
        paths,
        {
            "bad.png": ImagePayloadError("private path"),
            "good.png": _decision("screenshot"),
        },
    )

    assert prepared == list(paths)
    assert classified == ["good.png"]
    assert summary.failed == 1
    assert summary.candidate_count == 1


def test_every_image_failure_is_failed_scan() -> None:
    paths = (Path("a.png"), Path("b.png"))
    summary, _, _ = _run(
        paths,
        {
            "a.png": VisionClientError("network private"),
            "b.png": VisionClientError("invalid response private"),
        },
    )

    assert summary.state is ScanState.FAILED
    assert summary.discovered == 2
    assert summary.analyzed == 0
    assert summary.failed == 2


def test_unexpected_programming_error_is_not_counted_as_an_image_failure() -> None:
    path = Path("a.png")

    with pytest.raises(TypeError, match="programming defect"):
        _run((path,), {path.name: TypeError("programming defect")})


def test_unexpected_preparation_error_is_not_counted_as_an_image_failure() -> None:
    path = Path("a.png")

    with pytest.raises(TypeError, match="preparation defect"):
        run_server_scan(
            Path("/selected"),
            CONFIG,
            object(),
            scan=lambda _: ScanResult((path,), ()),
            prepare=lambda _: (_ for _ in ()).throw(TypeError("preparation defect")),
            classify=lambda *args, **kwargs: pytest.fail("must not classify"),
        )


def test_cancel_before_scan_returns_cancelled_without_discovery_or_request() -> None:
    cancel = Event()
    cancel.set()
    scan_calls: list[Path] = []

    summary = run_server_scan(
        Path("/selected"),
        CONFIG,
        object(),
        scan=lambda path: scan_calls.append(path) or ScanResult((Path("a.png"),), ()),
        prepare=lambda path: pytest.fail("must not prepare"),
        classify=lambda *args, **kwargs: pytest.fail("must not classify"),
        cancel_event=cancel,
    )

    assert summary.state is ScanState.CANCELLED
    assert scan_calls == []


def test_cancel_between_images_keeps_partial_counts_and_stops() -> None:
    paths = (Path("a.png"), Path("b.png"), Path("c.png"))
    cancel = Event()
    calls = 0

    def classify(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            cancel.set()
        return _decision("ordinary")

    summary = run_server_scan(
        Path("/selected"),
        CONFIG,
        object(),
        scan=lambda _: ScanResult(paths, ()),
        prepare=lambda path: Prepared(f"data:image/png;base64,{path.name}"),
        classify=classify,
        cancel_event=cancel,
    )

    assert summary.state is ScanState.CANCELLED
    assert summary.discovered == 3
    assert summary.analyzed == 1
    assert summary.ordinary == 1
    assert calls == 1


def test_cancel_during_request_returns_cancelled_not_failed() -> None:
    summary, _, _ = _run(
        (Path("a.png"), Path("b.png")),
        {
            "a.png": VisionCancelled("cancelled"),
            "b.png": _decision("ordinary"),
        },
    )

    assert summary.state is ScanState.CANCELLED
    assert summary.failed == 0
    assert summary.analyzed == 0


def test_scanner_failure_is_fixed_and_redacted() -> None:
    private = "/private/folder detail"

    with pytest.raises(ScanError) as raised:
        run_server_scan(
            Path("/selected"),
            CONFIG,
            object(),
            scan=lambda _: (_ for _ in ()).throw(ScanError(private)),
            prepare=lambda path: None,
            classify=lambda *args, **kwargs: None,
        )

    assert private not in str(raised.value)


def test_source_file_is_unchanged_across_mixed_scan(tmp_path: Path) -> None:
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (first, second)}

    _run(
        (first, second),
        {"a.png": _decision("screenshot"), "b.png": VisionClientError("failed")},
    )

    after = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (first, second)}
    assert after == before
