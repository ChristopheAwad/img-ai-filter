"""Evaluation, manifest, metric, orchestration, and report tests."""

import json
from pathlib import Path

import pytest

from img_ai_filter.detection import (
    AnalysisFailure,
    DECODE_FAILURE,
    DetectionResult,
)
from img_ai_filter import evaluation
from img_ai_filter.evaluation import (
    AcceptanceTargets,
    ClassificationMetrics,
    ManifestError,
    load_manifest,
)

HEADER = "path,label,split,source,license\n"


def _rel(name: str) -> str:
    return str(Path(name))


def _manifest_path(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


class FakeDetector:
    name = "fake"

    def __init__(self, results: dict[Path, object]) -> None:
        self._results = results

    def analyze(self, path: Path):
        from img_ai_filter.detection import Detector

        if path in self._results:
            return self._results[path]
        raise AssertionError(f"Unexpected path: {path}")

    @classmethod
    def describe(cls) -> dict[str, str | int]:
        return {"model_bytes": 0}


def _write_images(root: Path, count: int = 3, names: list[str] | None = None) -> list[Path]:
    if names is None:
        names = [f"img-{index}.png" for index in range(count)]
    paths = []
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\n")
        paths.append(path)
    return paths


def _manifest(root: Path, rows: list[str]) -> Path:
    path = root / "manifest.csv"
    path.write_text(HEADER + "".join(rows), encoding="utf-8")
    return path


def test_loads_valid_row_for_every_label_and_split(tmp_path: Path) -> None:
    labels = [
        "ordinary",
        "screenshot",
        "captioned_meme",
        "social_post",
        "reaction_image",
        "comic",
        "image_macro",
        "uncertain",
    ]
    names = [f"file-{index}.png" for index in range(len(labels))]
    _write_images(tmp_path, names=names)
    rows = [
        f"{_rel(name)},{label},tuning,test-source,local-test\n"
        for name, label in zip(names, labels)
    ]
    rows[3] = rows[3].replace("tuning", "holdout")
    manifest = _manifest(tmp_path, rows)

    entries = load_manifest(tmp_path, manifest)

    assert [entry.label for entry in entries] == labels
    assert [entry.split for entry in entries] == ["tuning"] * 3 + ["holdout", "tuning", "tuning", "tuning", "tuning"]


def test_accepts_spaces_and_unicode_filename_without_changing_path(
    tmp_path: Path,
) -> None:
    name = "space and résumé name.png"
    (tmp_path / name).write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest = _manifest(tmp_path, [f"{_rel(name)},ordinary,tuning,test-source,local-test\n"])

    entries = load_manifest(tmp_path, manifest)

    assert str(entries[0].path) == name


def test_rejects_empty_manifest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path, [])

    with pytest.raises(ManifestError, match="empty"):
        load_manifest(tmp_path, manifest)


def test_rejects_manifest_without_header(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n", encoding="utf-8")

    with pytest.raises(ManifestError, match="header|column"):
        load_manifest(tmp_path, manifest)


def test_rejects_missing_required_column(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        f"path,label,split,license\n{_manifest_path(tmp_path, image)},ordinary,tuning,local-test\n",
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="source"):
        load_manifest(tmp_path, manifest)


@pytest.mark.parametrize(
    "broken_row,match",
    [
        (",ordinary,tuning,test-source,local-test\n", "path at line 2"),
        ("img-0.png,,tuning,test-source,local-test\n", "label at line 2"),
        ("img-0.png,ordinary,,test-source,local-test\n", "split at line 2"),
        ("img-0.png,ordinary,tuning,,local-test\n", "source at line 2"),
        ("img-0.png,ordinary,tuning,test-source,\n", "license at line 2"),
    ],
)
def test_rejects_blank_required_field(
    tmp_path: Path, broken_row: str, match: str
) -> None:
    _write_images(tmp_path)
    manifest = _manifest(tmp_path, [broken_row])

    with pytest.raises(ManifestError, match=match):
        load_manifest(tmp_path, manifest)


def test_rejects_unknown_label(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},selfie,tuning,test-source,local-test\n"])

    with pytest.raises(ManifestError, match="label"):
        load_manifest(tmp_path, manifest)


def test_rejects_unknown_split(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,train,test-source,local-test\n"])

    with pytest.raises(ManifestError, match="split"):
        load_manifest(tmp_path, manifest)


@pytest.mark.parametrize(
    "bad_path",
    ["/etc/passwd", "C:\\Windows\\desktop.ini", "\\\\server\\share\\a.png", "a\\..\\b.png"],
)
def test_rejects_absolute_or_windows_path_on_any_platform(
    tmp_path: Path, bad_path: str
) -> None:
    _write_images(tmp_path)
    manifest = _manifest(tmp_path, [f"{bad_path},ordinary,tuning,test-source,local-test\n"])

    with pytest.raises(ManifestError, match="absolute|outside"):
        load_manifest(tmp_path, manifest)


def test_rejects_traversal_outside_root(tmp_path: Path) -> None:
    _write_images(tmp_path)
    outside = tmp_path.parent / "private-image.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")
    manifest = _manifest(tmp_path, [f"{_rel(Path('..') / outside.name)},ordinary,tuning,test-source,local-test\n"])

    with pytest.raises(ManifestError, match="outside"):
        load_manifest(tmp_path, manifest)


def test_rejects_directory_entry(tmp_path: Path) -> None:
    (tmp_path / "folder").mkdir()
    manifest = _manifest(tmp_path, ["folder,ordinary,tuning,test-source,local-test\n"])

    with pytest.raises(ManifestError, match="directory"):
        load_manifest(tmp_path, manifest)


def test_rejects_missing_file(tmp_path: Path) -> None:
    _write_images(tmp_path)
    manifest = _manifest(tmp_path, ["missing.png,ordinary,tuning,test-source,local-test\n"])

    with pytest.raises(ManifestError, match="missing|exist"):
        load_manifest(tmp_path, manifest)


def test_rejects_unsupported_extension(tmp_path: Path) -> None:
    image = tmp_path / "notes.txt"
    image.write_text("data")
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n"])

    with pytest.raises(ManifestError, match="extension"):
        load_manifest(tmp_path, manifest)


def test_rejects_symbolic_link(tmp_path: Path) -> None:
    real = _write_images(tmp_path)[0]
    link = tmp_path / "linked.png"
    try:
        link.symlink_to(real)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, link)},ordinary,tuning,test-source,local-test\n"])

    with pytest.raises(ManifestError, match="symbolic|symlink"):
        load_manifest(tmp_path, manifest)


def test_rejects_duplicate_normalized_path(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    rows = [
        f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n",
        f"{_manifest_path(tmp_path, image)},screenshot,holdout,test-source,local-test\n",
    ]
    manifest = _manifest(tmp_path, rows)

    with pytest.raises(ManifestError, match="duplicate"):
        load_manifest(tmp_path, manifest)


def test_rejects_malformed_csv_with_row_number_only(tmp_path: Path) -> None:
    import csv

    _write_images(tmp_path)
    manifest = tmp_path / "manifest.csv"
    manifest.write_text(
        f"path,label,split,source,license\nimg-0.png,ordinary,tuning,{'s' * 10_000},local-test\n",
        encoding="utf-8",
    )
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(1024)
    try:
        with pytest.raises(ManifestError, match="line 2"):
            load_manifest(tmp_path, manifest)
    finally:
        csv.field_size_limit(previous_limit)


def test_manifest_order_is_stable(tmp_path: Path) -> None:
    images = _write_images(tmp_path, names=["b.png", "a.png", "c.png"])
    rows = [
        f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n" for image in images
    ]
    manifest = _manifest(tmp_path, rows)

    entries = load_manifest(tmp_path, manifest)

    assert [entry.path.name for entry in entries] == ["b.png", "a.png", "c.png"]


def test_evaluate_all_rows_preserves_manifest_identity(tmp_path: Path) -> None:
    images = _write_images(tmp_path)
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n" for image in images])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {image: DetectionResult(False, "ordinary", "fine", 0.5, False) for image in images}
    )

    evaluation_result = evaluation.evaluate_detector(detector, entries, "tuning")

    assert [outcome.rel_path.name for outcome in evaluation_result.outcomes] == [
        entry.path.name for entry in entries
    ]
    assert all(outcome.expected_label == "ordinary" for outcome in evaluation_result.outcomes)


def test_continues_after_typed_failure_and_records_it_without_classifying_it(
    tmp_path: Path,
) -> None:
    good, bad = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, good)},ordinary,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, bad)},screenshot,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            good: DetectionResult(False, "ordinary", "fine", 0.5, False),
            bad: AnalysisFailure(bad, DECODE_FAILURE, "Cannot decode"),
        }
    )

    evaluation_result = evaluation.evaluate_detector(detector, entries, "tuning")

    assert len(evaluation_result.outcomes) == 2
    failures = [o for o in evaluation_result.outcomes if o.failure]
    assert len(failures) == 1
    assert failures[0].failure.message == "Cannot decode"
    assert failures[0].result is None


def test_recall_counts_failed_images_and_fails_recall_target(tmp_path: Path) -> None:
    images = _write_images(tmp_path, count=3)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, images[0])},screenshot,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, images[1])},screenshot,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, images[2])},screenshot,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            images[0]: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
            images[1]: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
            images[2]: AnalysisFailure(images[2], DECODE_FAILURE, "Cannot decode"),
        }
    )
    run = evaluation.with_targets(
        evaluation.evaluate_detector(detector, entries, "tuning"),
        AcceptanceTargets(screenshot_recall=0.9),
    )

    assert run.recall_by_label["screenshot"] == pytest.approx(2 / 3)
    assert run.all_metrics.recall == pytest.approx(2 / 3)
    assert run.target_report.checks["screenshot_recall"] is False
    assert not run.target_report.passed


def test_detector_exception_fails_recall_targets(tmp_path: Path) -> None:
    okay, broken = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, okay)},screenshot,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, broken)},screenshot,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {okay: DetectionResult(True, "screenshot", "screen layout", 0.99, True)}
    )

    class RaisingDetector:
        name = "boom"

        @staticmethod
        def analyze(path):
            if path == broken:
                raise RuntimeError("boom")
            return detector.analyze(path)

        @classmethod
        def describe(cls) -> dict[str, str | int]:
            return {"model_bytes": 0}

    run = evaluation.with_targets(
        evaluation.evaluate_detector(RaisingDetector(), entries, "tuning"),
        AcceptanceTargets(screenshot_recall=0.0),
    )

    assert run.errors
    assert run.recall_by_label["screenshot"] == 1.0
    assert run.target_report.checks["screenshot_recall"] is False
    assert not run.target_report.passed


def test_rejects_unexpected_detector_exception_with_relative_path(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},screenshot,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)

    class ExplodingDetector:
        name = "boom"

        @staticmethod
        def analyze(path):
            raise RuntimeError("boom")

        @classmethod
        def describe(cls) -> dict[str, str | int]:
            return {"model_bytes": 0}

    result = evaluation.evaluate_detector(ExplodingDetector(), entries, "tuning")

    assert len(result.errors) == 1
    assert result.errors[0][0].name == image.name
    assert "boom" in result.errors[0][1]


def test_evaluator_does_not_modify_image_bytes_timestamps_names_or_locations(
    tmp_path: Path,
) -> None:
    image = _write_images(tmp_path)[0]
    before = image.read_bytes()
    before_stat = image.stat()
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {image: DetectionResult(False, "ordinary", "fine", 0.5, False)}
    )

    evaluation.evaluate_detector(detector, entries, "tuning")

    assert image.read_bytes() == before
    assert image.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert image.exists()


def test_evaluator_writes_no_output_inside_dataset_root(tmp_path: Path) -> None:
    image = _write_images(tmp_path, count=1)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {image: DetectionResult(False, "ordinary", "fine", 0.5, False)}
    )

    evaluation.evaluate_detector(detector, entries, "tuning")

    assert sorted(pth.name for pth in tmp_path.iterdir()) == ["img-0.png", "manifest.csv"]


def test_evaluator_calls_no_network_api(tmp_path: Path, monkeypatch) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {image: DetectionResult(False, "ordinary", "fine", 0.5, False)}
    )

    def connect(*args, **kwargs):
        raise AssertionError("Network must not be contacted")

    monkeypatch.setattr("socket.create_connection", connect)

    evaluation.evaluate_detector(detector, entries, "tuning")


def test_tuning_and_holdout_rows_are_reported_independently(tmp_path: Path) -> None:
    images = _write_images(tmp_path, count=4)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, images[0])},ordinary,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, images[1])},ordinary,holdout,test-source,local-test\n",
            f"{_manifest_path(tmp_path, images[2])},screenshot,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, images[3])},screenshot,holdout,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            images[0]: DetectionResult(False, "ordinary", "fine", 0.5, False),
            images[1]: DetectionResult(False, "ordinary", "fine", 0.5, False),
            images[2]: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
            images[3]: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
        }
    )

    tuning_run = evaluation.evaluate_detector(detector, entries, "tuning")
    holdout_run = evaluation.evaluate_detector(detector, entries, "holdout")

    assert [o.expected_label for o in tuning_run.outcomes] == ["ordinary", "screenshot"]
    assert [o.expected_label for o in holdout_run.outcomes] == ["ordinary", "screenshot"]


def test_empty_selected_split_is_a_clear_validation_error(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector({image: DetectionResult(False, "ordinary", "fine", 0.5, False)})

    with pytest.raises(ValueError, match="empty|holdout"):
        evaluation.evaluate_detector(detector, entries, "holdout")


def test_metric_calculation_on_known_matrix(pytestconfig) -> None:
    expected = [True, True, True, False, False, False]
    predicted = [True, True, False, True, False, False]

    metrics = evaluation.binary_metrics(expected, predicted)

    assert metrics.true_positives == 2
    assert metrics.false_positives == 1
    assert metrics.true_negatives == 2
    assert metrics.false_negatives == 1
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(2 / 3)
    assert metrics.false_positive_rate == pytest.approx(1 / 3)


def test_zero_denominator_metrics_return_none() -> None:
    metrics = evaluation.binary_metrics([True, True], [True, True])

    assert metrics.false_positive_rate is None
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0

    metrics = evaluation.binary_metrics([False, False], [False, False])
    assert metrics.precision is None
    assert metrics.recall is None
    assert metrics.false_positive_rate == 0.0


def test_median_and_percentile_95() -> None:
    assert evaluation.median([1.0]) == 1.0
    assert evaluation.median([1.0, 2.0]) == 1.5
    assert evaluation.median([1.0, 2.0, 3.0]) == 2.0
    assert evaluation.percentile_95([1.0]) == 1.0
    assert evaluation.percentile_95([1.0, 2.0]) == 2.0
    assert evaluation.percentile_95([1.0, 2.0, 3.0]) == 3.0
    assert evaluation.percentile_95([1.0] * 100) == 1.0
    assert evaluation.median([]) is None
    assert evaluation.percentile_95([]) is None


def test_target_boundary_comparison_is_inclusive() -> None:
    from img_ai_filter.evaluation import DetectorEvaluation, TargetReport

    targets = AcceptanceTargets()

    at_boundary = ClassificationMetrics(9, 1, 19, 1, 0.9, 0.9, 0.05)
    checked_boundary = ClassificationMetrics(9, 2, 198, 1, 0.98, 0.9, 0.01)
    run = DetectorEvaluation(
        detector_name="x",
        split="tuning",
        outcomes=(),
        errors=(),
        all_metrics=at_boundary,
        checked_metrics=checked_boundary,
        recall_by_label={"screenshot": 0.9, "image_macro": 0.8},
        median_seconds=0.5,
        p95_seconds=2.0,
        peak_memory_bytes=1024**3,
        model_bytes=300 * 1024**2,
        target_report=None,
    )

    report = evaluation.check_targets(run, targets)

    assert report.checks["candidate_precision"] is True
    assert report.checks["ordinary_candidate_fpr"] is True
    assert report.checks["median_seconds"] is True
    assert report.checks["p95_seconds"] is True
    assert report.checks["screenshot_recall"] is True
    assert report.checks["other_candidate_recall"] is True
    assert report.passed


def test_target_check_requires_all_targets_and_flags_unavailable(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector({image: DetectionResult(False, "ordinary", "fine", 0.5, False)})
    run = evaluation.evaluate_detector(detector, entries, "tuning")
    targets = AcceptanceTargets()

    report = evaluation.check_targets(run, targets)

    assert report.missed
    assert not report.passed


def test_select_best_uses_smallest_model_then_time_then_memory_then_name(
    tmp_path: Path,
) -> None:
    from img_ai_filter.evaluation import (
        DetectorEvaluation,
        ImageOutcome,
        TargetReport,
    )

    def run_for(name: str, model_bytes: int, seconds: float, memory: int):
        return DetectorEvaluation(
            detector_name=name,
            split="tuning",
            outcomes=(),
            errors=(),
            all_metrics=ClassificationMetrics(0, 0, 1, 0, None, None, None),
            checked_metrics=ClassificationMetrics(0, 0, 1, 0, None, None, None),
            recall_by_label={},
            median_seconds=seconds,
            p95_seconds=seconds,
            peak_memory_bytes=memory,
            model_bytes=model_bytes,
            target_report=TargetReport(checks={}, missed=(), passed=True),
        )

    evaluations = [
        run_for("a", 10, 0.5, 1),
        run_for("b", 5, 0.5, 2),
        run_for("c", 5, 0.4, 3),
        run_for("d", 5, 0.4, 1),
    ]

    winner = evaluation.select_best(evaluations)

    assert winner == "d"


def test_select_best_returns_none_when_all_fail(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector({image: DetectionResult(False, "ordinary", "fine", 0.5, False)})
    run = evaluation.with_targets(
        evaluation.evaluate_detector(detector, entries, "tuning"),
        AcceptanceTargets(candidate_precision=0.9999),
    )

    assert not run.target_report.passed
    assert evaluation.select_best([run]) is None


def test_reports_contain_no_ocr_text_or_image_bytes(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},screenshot,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {image: DetectionResult(True, "screenshot", "screen layout", 0.99, True)}
    )
    run = evaluation.evaluate_detector(detector, entries, "tuning")
    targets = AcceptanceTargets()

    markdown = evaluation.render_markdown({"fake": run}, targets, split="tuning")
    payload = json.loads(evaluation.render_json({"fake": run}, targets, split="tuning"))

    assert b"\x89PNG" not in markdown.encode()
    assert "recognized text" not in markdown.lower()
    dumped = json.dumps(payload)
    assert b"\x89PNG" not in dumped.encode()
    assert "recognized text" not in dumped.lower()


def test_report_is_markdown_table_of_targets_and_metrics(tmp_path: Path) -> None:
    image = _write_images(tmp_path)[0]
    manifest = _manifest(tmp_path, [f"{_manifest_path(tmp_path, image)},screenshot,tuning,test-source,local-test\n"])
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {image: DetectionResult(True, "screenshot", "screen layout", 0.99, True)}
    )
    run = evaluation.evaluate_detector(detector, entries, "tuning")
    targets = AcceptanceTargets()

    markdown = evaluation.render_markdown({"fake": run}, targets, split="tuning")

    assert "#" in markdown
    assert "fake" in markdown
    assert "screenshot" in markdown
    assert "Median" in markdown
    assert "precision" in markdown.lower()


def test_uncertain_rows_are_not_candidate_positive_in_all_metrics(
    tmp_path: Path,
) -> None:
    shot, unclear = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, shot)},screenshot,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, unclear)},uncertain,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            shot: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
            unclear: DetectionResult(False, "ordinary", "fine", 0.95, False),
        }
    )

    run = evaluation.evaluate_detector(detector, entries, "tuning")

    assert run.all_metrics.true_positives == 1
    assert run.all_metrics.true_negatives == 0
    assert run.all_metrics.false_negatives == 0
    assert run.all_metrics.recall == 1.0


def test_uncertain_rows_do_not_inflate_false_positives(tmp_path: Path) -> None:
    ordinary, unclear = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, ordinary)},ordinary,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, unclear)},uncertain,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            ordinary: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
            unclear: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
        }
    )

    run = evaluation.evaluate_detector(detector, entries, "tuning")

    assert run.all_metrics.true_positives == 0
    assert run.all_metrics.false_positives == 1
    assert run.all_metrics.precision == 0.0


def test_recall_by_label_excludes_uncertain(tmp_path: Path) -> None:
    shot, unclear = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, shot)},screenshot,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, unclear)},uncertain,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            shot: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
            unclear: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
        }
    )

    run = evaluation.evaluate_detector(detector, entries, "tuning")

    assert run.recall_by_label["screenshot"] == 1.0
    assert "uncertain" not in run.recall_by_label
    assert run.recall_by_label["comic"] is None


def test_uncertain_routing_rate_is_none_when_no_uncertain_rows(
    tmp_path: Path,
) -> None:
    image = _write_images(tmp_path, count=1)[0]
    manifest = _manifest(
        tmp_path,
        [f"{_manifest_path(tmp_path, image)},ordinary,tuning,test-source,local-test\n"],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {image: DetectionResult(False, "ordinary", "fine", 0.5, False)}
    )

    run = evaluation.evaluate_detector(detector, entries, "tuning")

    assert run.uncertain_routing_rate is None


def test_uncertain_routing_rate_is_zero_when_all_above_threshold(
    tmp_path: Path,
) -> None:
    images = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, images[0])},uncertain,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, images[1])},uncertain,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            images[0]: DetectionResult(False, "ordinary", "fine", 0.95, False),
            images[1]: DetectionResult(False, "ordinary", "fine", 0.98, False),
        }
    )

    run = evaluation.evaluate_detector(detector, entries, "tuning")

    assert run.uncertain_routing_rate == 0.0


def test_uncertain_routing_rate_uses_strictly_below_threshold(
    tmp_path: Path,
) -> None:
    images = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, images[0])},uncertain,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, images[1])},uncertain,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            images[0]: DetectionResult(False, "ordinary", "fine", 0.5, False),
            images[1]: DetectionResult(False, "ordinary", "fine", 0.49, False),
        }
    )
    targets = AcceptanceTargets(high_confidence_threshold=0.5)

    run = evaluation.evaluate_detector(detector, entries, "tuning", targets)

    assert run.uncertain_routing_rate == 0.5


def test_uncertain_routing_rate_is_hundred_percent_below_default_threshold(
    tmp_path: Path,
) -> None:
    images = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, images[0])},uncertain,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, images[1])},uncertain,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            images[0]: DetectionResult(False, "ordinary", "fine", 0.3, False),
            images[1]: DetectionResult(False, "ordinary", "fine", 0.6, False),
        }
    )

    run = evaluation.evaluate_detector(detector, entries, "tuning")

    assert run.uncertain_routing_rate == 1.0


def test_uncertain_routing_rate_denominator_uses_only_valid_results(
    tmp_path: Path,
) -> None:
    routed, failed = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, routed)},uncertain,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, failed)},uncertain,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            routed: DetectionResult(False, "ordinary", "fine", 0.3, False),
            failed: AnalysisFailure(failed, DECODE_FAILURE, "Cannot decode"),
        }
    )

    run = evaluation.evaluate_detector(detector, entries, "tuning")

    assert run.uncertain_routing_rate == 1.0


def test_uncertain_analysis_failure_does_not_fail_candidate_recall_targets(
    tmp_path: Path,
) -> None:
    shot, unclear = _write_images(tmp_path, count=2)
    manifest = _manifest(
        tmp_path,
        [
            f"{_manifest_path(tmp_path, shot)},screenshot,tuning,test-source,local-test\n",
            f"{_manifest_path(tmp_path, unclear)},uncertain,tuning,test-source,local-test\n",
        ],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {
            shot: DetectionResult(True, "screenshot", "screen layout", 0.99, True),
            unclear: AnalysisFailure(unclear, DECODE_FAILURE, "Cannot decode"),
        }
    )

    run = evaluation.with_targets(
        evaluation.evaluate_detector(detector, entries, "tuning"),
        AcceptanceTargets(screenshot_recall=0.9),
    )

    assert run.target_report.checks["screenshot_recall"] is True


def test_reports_include_uncertain_routing_rate(tmp_path: Path) -> None:
    image = _write_images(tmp_path, count=1)[0]
    manifest = _manifest(
        tmp_path,
        [f"{_manifest_path(tmp_path, image)},uncertain,tuning,test-source,local-test\n"],
    )
    entries = load_manifest(tmp_path, manifest)
    detector = FakeDetector(
        {image: DetectionResult(False, "ordinary", "fine", 0.5, False)}
    )
    run = evaluation.evaluate_detector(detector, entries, "tuning")
    targets = AcceptanceTargets()

    markdown = evaluation.render_markdown({"fake": run}, targets, split="tuning")
    payload = json.loads(evaluation.render_json({"fake": run}, targets, split="tuning"))

    assert "uncertain routing rate" in markdown
    assert "100%" in markdown
    assert payload["detectors"]["fake"]["uncertain_routing_rate"] == 1.0
