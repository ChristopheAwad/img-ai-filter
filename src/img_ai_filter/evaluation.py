"""Read-only evaluation of candidate detectors on labeled local datasets."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import statistics
from typing import Sequence

from img_ai_filter.detection import (
    AnalysisFailure,
    CANDIDATE_CATEGORIES,
    DetectionResult,
    Detector,
    ORDINARY,
)
from img_ai_filter.scanner import SUPPORTED_EXTENSIONS

TUNING = "tuning"
HOLDOUT = "holdout"
SPLITS = frozenset({TUNING, HOLDOUT})
LABELS = frozenset(
    CANDIDATE_CATEGORIES | {ORDINARY}
)

REQUIRED_COLUMNS = ("path", "label", "split", "source", "license")

_POSIX_ROOT = "/"
_WINDOWS_DRIVE = r"^[A-Za-z]:[\\/]"


ManifestError = ValueError


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One validated row from the manifest. Path stays relative to the root."""

    path: Path
    label: str
    split: str
    source: str
    license: str


@dataclass(frozen=True, slots=True)
class Manifest:
    """A validated dataset manifest bound to its root folder."""

    root: Path
    entries: tuple[ManifestEntry, ...]

    def __iter__(self):
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, index: int) -> ManifestEntry:
        return self.entries[index]


@dataclass(frozen=True, slots=True)
class ImageOutcome:
    """Outcome of analyzing one image."""

    rel_path: Path
    expected_label: str
    split: str
    result: DetectionResult | None
    failure: AnalysisFailure | None
    seconds: float


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float | None
    recall: float | None
    false_positive_rate: float | None


@dataclass(frozen=True, slots=True)
class TargetReport:
    checks: dict[str, bool]
    missed: tuple[str, ...]
    passed: bool


@dataclass(frozen=True, slots=True)
class AcceptanceTargets:
    candidate_precision: float = 0.90
    high_confidence_precision: float = 0.98
    ordinary_candidate_fpr: float = 0.05
    ordinary_checked_fpr: float = 0.01
    screenshot_recall: float = 0.90
    other_candidate_recall: float = 0.80
    high_confidence_threshold: float = 0.9
    median_seconds: float = 0.5
    p95_seconds: float = 2.0
    peak_memory_bytes: int = 1024**3
    model_bytes: int = 300 * 1024**2


@dataclass(frozen=True, slots=True)
class DetectorEvaluation:
    detector_name: str
    split: str
    outcomes: tuple[ImageOutcome, ...]
    errors: tuple[tuple[Path, str], ...]
    all_metrics: ClassificationMetrics
    checked_metrics: ClassificationMetrics
    recall_by_label: dict[str, float | None]
    median_seconds: float | None
    p95_seconds: float | None
    peak_memory_bytes: int
    model_bytes: int
    target_report: TargetReport | None = None


def _is_unsafe_path(raw: str) -> bool:
    if raw.startswith(_POSIX_ROOT):
        return True
    if raw.startswith("\\\\"):
        return True
    return bool(re.match(_WINDOWS_DRIVE, raw))


def _contains_parent_traversal(raw: str) -> bool:
    return any(part == ".." for part in raw.replace("\\", "/").split("/"))


def _windows_norm(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def load_manifest(root: Path, manifest_path: Path) -> Manifest:
    """Load and strictly validate a manifest relative to a dataset root."""
    root = Path(root)
    root_resolved = root.resolve()
    errors: list[str] = []

    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    row_index = 1
    reader = None

    try:
        with open(manifest_path, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not reader.fieldnames:
                raise ManifestError(
                    f"{manifest_path.name}: manifest is empty or has no header"
                )
            columns = [column.strip() for column in reader.fieldnames]
            missing = [column for column in REQUIRED_COLUMNS if column not in columns]
            if missing:
                raise ManifestError(
                    f"{manifest_path.name}: missing required column(s): {', '.join(missing)}"
                )

            for row_index, row in enumerate(reader, start=2):
                if row is None:
                    continue
                entry, error = _parse_row(
                    row, row_index, root, root_resolved, manifest_path, seen
                )
                if entry is not None:
                    entries.append(entry)
                else:
                    errors.append(error or "")
    except csv.Error as error:
        line_num = getattr(getattr(reader, "reader", None), "line_num", None)
        raise ManifestError(
            f"{manifest_path.name}: malformed CSV at line {line_num or row_index}: {error}"
        ) from error

    if not entries:
        if errors:
            raise ManifestError(errors[0])
        raise ManifestError(f"{manifest_path.name}: manifest is empty")

    if errors:
        raise ManifestError(errors[0])

    return Manifest(root=root_resolved, entries=tuple(entries))


def _parse_row(
    row: dict[str, str | None],
    row_index: int,
    root: Path,
    root_resolved: Path,
    manifest_path: Path,
    seen: set[str],
) -> tuple[ManifestEntry | None, str | None]:
    def blank(field: str) -> str | None:
        value = (row.get(field) or "").strip()
        if not value:
            return f"{manifest_path.name}: blank {field} at line {row_index}"
        return None

    for field in REQUIRED_COLUMNS:
        problem = blank(field)
        if problem:
            return None, problem

    raw_path = (row.get("path") or "").strip()
    label = (row.get("label") or "").strip()
    split = (row.get("split") or "").strip()
    source = (row.get("source") or "").strip()
    license = (row.get("license") or "").strip()

    if label not in LABELS:
        return None, f"{manifest_path.name}: unknown label {label!r} at line {row_index}"
    if split not in SPLITS:
        return None, f"{manifest_path.name}: unknown split {split!r} at line {row_index}"

    if _is_unsafe_path(raw_path):
        return None, f"{manifest_path.name}: absolute path at line {row_index}"
    if _contains_parent_traversal(raw_path):
        return None, f"{manifest_path.name}: path outside dataset root at line {row_index}"

    candidate = root / raw_path
    if candidate.is_symlink():
        return None, f"{manifest_path.name}: symbolic link at line {row_index}"
    if candidate.is_dir():
        return None, f"{manifest_path.name}: directory entry at line {row_index}"
    if not candidate.exists():
        return None, f"{manifest_path.name}: missing file at line {row_index}"
    if candidate.suffix.casefold() not in SUPPORTED_EXTENSIONS:
        return None, f"{manifest_path.name}: unsupported extension at line {row_index}"

    inside = False
    try:
        inside = candidate.resolve().is_relative_to(root_resolved)
    except ValueError:
        inside = False
    if not inside:
        return None, f"{manifest_path.name}: path outside dataset root at line {row_index}"

    normalized = _windows_norm(str(candidate.resolve()))
    if normalized in seen:
        return None, f"{manifest_path.name}: duplicate path at line {row_index}"
    seen.add(normalized)

    return (
        ManifestEntry(
            path=Path(raw_path),
            label=label,
            split=split,
            source=source,
            license=license,
        ),
        None,
    )


def _is_candidate_label(label: str) -> bool:
    return label != ORDINARY


def binary_metrics(expected: Sequence[bool], predicted: Sequence[bool]) -> ClassificationMetrics:
    """Compute confusion counts and derived rates, treating missing denominators as None."""
    if len(expected) != len(predicted):
        raise ValueError("expected and predicted must have equal length")

    true_positives = sum(1 for e, p in zip(expected, predicted) if e and p)
    false_positives = sum(1 for e, p in zip(expected, predicted) if not e and p)
    false_negatives = sum(1 for e, p in zip(expected, predicted) if e and not p)
    true_negatives = sum(1 for e, p in zip(expected, predicted) if not e and not p)

    precision = true_positives / (true_positives + false_positives) if (true_positives + false_positives) else None
    recall = true_positives / (true_positives + false_negatives) if (true_positives + false_negatives) else None
    fpr = false_positives / (false_positives + true_negatives) if (false_positives + true_negatives) else None

    return ClassificationMetrics(
        true_positives,
        false_positives,
        true_negatives,
        false_negatives,
        precision,
        recall,
        fpr,
    )


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return statistics.median(values)


def percentile_95(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def evaluate_detector(
    detector: Detector,
    manifest: Manifest,
    split: str,
    targets: AcceptanceTargets | None = None,
) -> DetectorEvaluation:
    """Run one detector over the selected split of a validated manifest."""
    if split not in SPLITS:
        raise ValueError(f"Unknown split: {split!r}")
    selected = [entry for entry in manifest if entry.split == split]
    if not selected:
        raise ValueError(f"No rows for split {split!r}")

    outcomes: list[ImageOutcome] = []
    errors: list[tuple[Path, str]] = []

    import time as _time
    import tracemalloc

    tracemalloc.start()
    peak: int = 0
    for entry in selected:
        full_path = manifest.root / entry.path
        started = _time.perf_counter()
        try:
            result = detector.analyze(full_path)
        except Exception as error:  # noqa: BLE001 - any detector error is an evaluation failure
            elapsed = _time.perf_counter() - started
            peak = max(peak, tracemalloc.get_traced_memory()[1])
            errors.append((entry.path, f"{type(error).__name__.lower()}: {error}"))
            continue
        elapsed = _time.perf_counter() - started
        peak = max(peak, tracemalloc.get_traced_memory()[1])

        if isinstance(result, AnalysisFailure):
            outcomes.append(
                ImageOutcome(
                    rel_path=entry.path,
                    expected_label=entry.label,
                    split=entry.split,
                    result=None,
                    failure=result,
                    seconds=elapsed,
                )
            )
        elif isinstance(result, DetectionResult):
            outcomes.append(
                ImageOutcome(
                    rel_path=entry.path,
                    expected_label=entry.label,
                    split=entry.split,
                    result=result,
                    failure=None,
                    seconds=elapsed,
                )
            )
        else:
            errors.append(
                (entry.path, "detector returned an unsupported value")
            )
    tracemalloc.stop()

    all_pred_clean = [o.result.is_candidate if o.result else False for o in outcomes]
    checked_pred = [o.result.default_checked if o.result else False for o in outcomes]

    all_expected = [_is_candidate_label(o.expected_label) for o in outcomes]
    all_metrics = binary_metrics(all_expected, all_pred_clean)
    checked_metrics = binary_metrics(all_expected, checked_pred)

    recall_by_label: dict[str, float | None] = {}
    for label in sorted(CANDIDATE_CATEGORIES):
        expected_rows = [o for o in outcomes if o.expected_label == label]
        if not expected_rows:
            recall_by_label[label] = None
            continue
        correct = sum(
            1 for o in expected_rows if o.result is not None and o.result.is_candidate
        )
        recall_by_label[label] = correct / len(expected_rows)

    seconds = [o.seconds for o in outcomes]
    try:
        model_bytes = int(detector.describe().get("model_bytes", 0))
    except Exception:  # noqa: BLE001 - description is advisory
        model_bytes = 0

    evaluation_result = DetectorEvaluation(
        detector_name=detector.name,
        split=split,
        outcomes=tuple(outcomes),
        errors=tuple(errors),
        all_metrics=all_metrics,
        checked_metrics=checked_metrics,
        recall_by_label=recall_by_label,
        median_seconds=median(seconds),
        p95_seconds=percentile_95(seconds),
        peak_memory_bytes=peak,
        model_bytes=model_bytes,
    )
    if targets is not None:
        evaluation_result = with_targets(evaluation_result, targets)
    return evaluation_result


def with_targets(
    evaluation_result: DetectorEvaluation, targets: AcceptanceTargets
) -> DetectorEvaluation:
    return DetectorEvaluation(
        detector_name=evaluation_result.detector_name,
        split=evaluation_result.split,
        outcomes=evaluation_result.outcomes,
        errors=evaluation_result.errors,
        all_metrics=evaluation_result.all_metrics,
        checked_metrics=evaluation_result.checked_metrics,
        recall_by_label=evaluation_result.recall_by_label,
        median_seconds=evaluation_result.median_seconds,
        p95_seconds=evaluation_result.p95_seconds,
        peak_memory_bytes=evaluation_result.peak_memory_bytes,
        model_bytes=evaluation_result.model_bytes,
        target_report=check_targets(evaluation_result, targets),
    )


def check_targets(run: DetectorEvaluation, targets: AcceptanceTargets) -> TargetReport:
    """Compare a run against acceptance targets; any unavailable metric fails its target."""
    checks: dict[str, bool] = {}

    def above(name: str, value: float | None, minimum: float) -> None:
        checks[name] = value is not None and value >= minimum

    def below(name: str, value: float | None, maximum: float) -> None:
        checks[name] = value is not None and value <= maximum

    above("candidate_precision", run.all_metrics.precision, targets.candidate_precision)
    above("high_confidence_precision", run.checked_metrics.precision, targets.high_confidence_precision)
    below("ordinary_candidate_fpr", run.all_metrics.false_positive_rate, targets.ordinary_candidate_fpr)
    below("ordinary_checked_fpr", run.checked_metrics.false_positive_rate, targets.ordinary_checked_fpr)
    above("screenshot_recall", run.recall_by_label.get("screenshot"), targets.screenshot_recall)
    other = [
        run.recall_by_label.get(label)
        for label in ("captioned_meme", "social_post", "reaction_image", "comic", "image_macro")
        if run.recall_by_label.get(label) is not None
    ]
    other_recall = sum(other) / len(other) if other else None
    above("other_candidate_recall", other_recall, targets.other_candidate_recall)

    any_failure = any(o.failure is not None for o in run.outcomes) or bool(run.errors)
    if any_failure:
        checks["screenshot_recall"] = False
        checks["other_candidate_recall"] = False

    below("median_seconds", run.median_seconds, targets.median_seconds)
    below("p95_seconds", run.p95_seconds, targets.p95_seconds)
    below("peak_memory_bytes", float(run.peak_memory_bytes), float(targets.peak_memory_bytes))
    below("model_bytes", float(run.model_bytes), float(targets.model_bytes))

    missed = tuple(sorted(name for name, passed in checks.items() if not passed))
    return TargetReport(checks=checks, missed=missed, passed=not missed)


def select_best(evaluations: Sequence[DetectorEvaluation]) -> str | None:
    """Select the smallest passing detector; tie-break by time, memory, then name."""
    eligible = [run for run in evaluations if run.target_report and run.target_report.passed]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda run: (
            run.model_bytes,
            run.median_seconds if run.median_seconds is not None else float("inf"),
            run.peak_memory_bytes,
            run.detector_name,
        ),
    ).detector_name


def _runner_dict(run: DetectorEvaluation) -> dict[str, object]:
    return {
        "detector": run.detector_name,
        "split": run.split,
        "confusion_all": {
            "true_positives": run.all_metrics.true_positives,
            "false_positives": run.all_metrics.false_positives,
            "true_negatives": run.all_metrics.true_negatives,
            "false_negatives": run.all_metrics.false_negatives,
            "precision": run.all_metrics.precision,
            "recall": run.all_metrics.recall,
            "false_positive_rate": run.all_metrics.false_positive_rate,
        },
        "confusion_checked": {
            "true_positives": run.checked_metrics.true_positives,
            "false_positives": run.checked_metrics.false_positives,
            "true_negatives": run.checked_metrics.true_negatives,
            "false_negatives": run.checked_metrics.false_negatives,
            "precision": run.checked_metrics.precision,
            "recall": run.checked_metrics.recall,
            "false_positive_rate": run.checked_metrics.false_positive_rate,
        },
        "recall_by_label": {label: run.recall_by_label[label] for label in sorted(run.recall_by_label)},
        "median_seconds": run.median_seconds,
        "p95_seconds": run.p95_seconds,
        "peak_memory_bytes": run.peak_memory_bytes,
        "model_bytes": run.model_bytes,
        "targets": (dict(run.target_report.checks) if run.target_report else None),
        "targets_passed": bool(run.target_report and run.target_report.passed),
        "targets_missed": list(run.target_report.missed) if run.target_report else [],
        "failures": [
            {"path": str(o.rel_path), "kind": o.failure.kind, "message": o.failure.message}
            for o in run.outcomes
            if o.failure is not None
        ],
        "errors": [{"path": str(path), "message": message} for path, message in run.errors],
        "outcomes": [
            {
                "path": str(o.rel_path),
                "expected_label": o.expected_label,
                "is_candidate": o.result.is_candidate if o.result else None,
                "default_checked": o.result.default_checked if o.result else None,
                "seconds": o.seconds,
            }
            for o in run.outcomes
        ],
    }


def render_json(
    evaluations: dict[str, DetectorEvaluation],
    targets: AcceptanceTargets,
    split: str,
    metadata: dict[str, object] | None = None,
) -> str:
    ordered = {name: evaluations[name] for name in sorted(evaluations)}
    best = select_best(list(ordered.values()))
    payload = {
        "split": split,
        "selected_detector": best,
        "metadata": metadata or {},
        "detectors": {name: _runner_dict(run) for name, run in ordered.items()},
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def render_markdown(
    evaluations: dict[str, DetectorEvaluation],
    targets: AcceptanceTargets,
    split: str,
    metadata: dict[str, object] | None = None,
) -> str:
    lines = [f"# Detector evaluation ({split})", ""]
    ordered = {name: evaluations[name] for name in sorted(evaluations)}
    best = select_best(list(ordered.values()))

    if metadata:
        lines.append("## Environment and dataset")
        lines.append("")
        for key in sorted(metadata):
            lines.append(f"- {key}: {metadata[key]}")
        lines.append("")

    lines.append("## Acceptance targets")
    lines.append("")
    lines.append(f"| Target | Bound |")
    lines.append(f"| --- | --- |")
    lines.append(f"| candidate precision | >= {targets.candidate_precision} |")
    lines.append(f"| high-confidence precision | >= {targets.high_confidence_precision} |")
    lines.append(f"| ordinary-photo candidate FPR | <= {targets.ordinary_candidate_fpr} |")
    lines.append(f"| ordinary-photo checked FPR | <= {targets.ordinary_checked_fpr} |")
    lines.append(f"| screenshot recall | >= {targets.screenshot_recall} |")
    lines.append(f"| other-candidate recall | >= {targets.other_candidate_recall} |")
    lines.append(f"| median seconds | <= {targets.median_seconds} |")
    lines.append(f"| 95th-percentile seconds | <= {targets.p95_seconds} |")
    lines.append(f"| peak memory bytes | <= {targets.peak_memory_bytes} |")
    lines.append(f"| model bytes | <= {targets.model_bytes} |")
    lines.append("")

    for name, run in ordered.items():
        lines.append(f"## {name}")
        lines.append("")
        lines.append("| Metric | All candidates | Default-checked |")
        lines.append("| --- | ---: | ---: |")
        lines.append(f"| precision | {run.all_metrics.precision} | {run.checked_metrics.precision} |")
        lines.append(f"| recall | {run.all_metrics.recall} | {run.checked_metrics.recall} |")
        lines.append(f"| ordinary FPR | {run.all_metrics.false_positive_rate} | {run.checked_metrics.false_positive_rate} |")
        lines.append(f"| true positives | {run.all_metrics.true_positives} | {run.checked_metrics.true_positives} |")
        lines.append(f"| false positives | {run.all_metrics.false_positives} | {run.checked_metrics.false_positives} |")
        lines.append("")
        lines.append("| Recall by label | value |")
        lines.append("| --- | ---: |")
        for label in sorted(run.recall_by_label):
            lines.append(f"| {label} | {run.recall_by_label[label]} |")
        lines.append("")
        lines.append(f"| Median seconds | {run.median_seconds} |")
        lines.append(f"| 95th-percentile seconds | {run.p95_seconds} |")
        lines.append(f"| Peak memory bytes | {run.peak_memory_bytes} |")
        lines.append(f"| Packaged model bytes | {run.model_bytes} |")
        if run.target_report:
            lines.append("")
            lines.append("| Target | Passed |")
            lines.append("| --- | --- |")
            for target in sorted(run.target_report.checks):
                lines.append(f"| {target} | {run.target_report.checks[target]} |")
            lines.append("")
            status = "PASSED" if run.target_report.passed else "MISSED"
            lines.append(f"**Result: {status}**")
        else:
            lines.append("")
            lines.append("No acceptance targets were checked.")
        lines.append("")

    lines.append(f"## Selected detector: {best if best else 'none (no detector passed all targets)'}")
    return "\n".join(lines) + "\n"