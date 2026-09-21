"""GUI-neutral safe quarantine planner and executor tests.

No test makes a network call. All filesystem injections use the module's public
API and its documented internal seams so failures stay deterministic.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import img_ai_filter.quarantine as quarantine_mod
from img_ai_filter.image_payload import SourceIdentity
from img_ai_filter.quarantine import (
    MOVE_LOG_NAME,
    MoveStatus,
    QuarantineError,
    QuarantineState,
    build_quarantine_plan,
    execute_quarantine_plan,
    validate_quarantine_folder,
    validate_quarantine_roots,
)


def _file(path: Path, data: bytes = b"content-bytes") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _identity(path: Path) -> SourceIdentity:
    data = path.read_bytes()
    return SourceIdentity(len(data), hashlib.sha256(data).hexdigest())


def _candidate(path: Path) -> SimpleNamespace:
    return SimpleNamespace(path=path, identity=_identity(path))


def _quarantine_root(tmp_path: Path, name: str = "quarantine") -> Path:
    root = tmp_path.parent / f"{tmp_path.name}-{name}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _make_plan(
    tmp_path: Path,
    source_files: dict[Path, bytes],
    *,
    quarantine: Path | None = None,
) -> tuple[QuarantinePlan, Path, Path, dict[Path, bytes]]:
    source_root = tmp_path / "source"
    candidates: list[SimpleNamespace] = []
    for path, data in source_files.items():
        _file(source_root / path, data)
        candidates.append(_candidate(source_root / path))
    quarantine_root = quarantine or _quarantine_root(tmp_path)
    plan = build_quarantine_plan(source_root, quarantine_root, candidates)
    return plan, source_root, quarantine_root, source_files


def _read_lines(root: Path) -> list[dict[str, Any]]:
    lines = (root / MOVE_LOG_NAME).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _assert_unchanged(path: Path, original: bytes) -> None:
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns > 0


# ---------------------------------------------------------------------------
# Root validation
# ---------------------------------------------------------------------------


def test_accepts_two_existing_separate_directories(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    quarantine = _quarantine_root(tmp_path)

    validate_quarantine_roots(source, quarantine)


def test_accepts_sibling_and_mount_like_roots(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()

    validate_quarantine_roots(a, b)


@pytest.mark.parametrize(
    "build",
    [
        lambda tmp: (tmp / "a", tmp / "a"),
        lambda tmp: (tmp / "a", tmp / "a" / "b"),
        lambda tmp: (tmp / "a" / "b", tmp / "a"),
    ],
)
def test_rejects_equal_and_overlapping_roots(tmp_path: Path, build) -> None:
    left, right = build(tmp_path)
    left.mkdir(parents=True, exist_ok=True)
    right.mkdir(parents=True, exist_ok=True)

    with pytest.raises(QuarantineError):
        validate_quarantine_roots(left, right)


def test_rejects_roots_that_normalize_to_the_same_directory(
    tmp_path: Path,
) -> None:
    source = tmp_path / "a"
    source.mkdir()
    alias = source.parent / "." / "a"

    with pytest.raises(QuarantineError):
        validate_quarantine_roots(source, alias)


def test_rejects_missing_roots(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError):
        validate_quarantine_roots(tmp_path / "missing", tmp_path)
    with pytest.raises(QuarantineError):
        validate_quarantine_roots(tmp_path, tmp_path / "missing")


def test_rejects_root_that_is_a_file(tmp_path: Path) -> None:
    source_file = _file(tmp_path / "source.txt")
    folder = tmp_path / "folder"
    folder.mkdir()

    with pytest.raises(QuarantineError):
        validate_quarantine_roots(source_file, folder)
    with pytest.raises(QuarantineError):
        validate_quarantine_roots(folder, source_file)


def test_rejects_symlink_roots(tmp_path: Path) -> None:
    real_source = tmp_path / "real-source"
    real_source.mkdir()
    link = tmp_path / "source-link"
    try:
        link.symlink_to(real_source, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    with pytest.raises(QuarantineError):
        validate_quarantine_roots(link, tmp_path / "q")
    with pytest.raises(QuarantineError):
        validate_quarantine_roots(real_source, link)


def test_rejects_unreadable_root(tmp_path: Path, monkeypatch) -> None:
    quarantine = tmp_path / "q"
    quarantine.mkdir()
    monkeypatch.setattr(
        quarantine_mod.os, "access", lambda folder, flags: False
    )

    with pytest.raises(QuarantineError):
        validate_quarantine_roots(tmp_path, quarantine)


def test_rejects_empty_or_non_path_input(tmp_path: Path) -> None:
    with pytest.raises(QuarantineError):
        validate_quarantine_roots("", tmp_path)
    with pytest.raises(QuarantineError):
        validate_quarantine_roots(tmp_path, "")


def test_folder_validator_resolves_and_rejects_unsafe_targets(tmp_path: Path) -> None:
    good = tmp_path / "good"
    good.mkdir()
    assert validate_quarantine_folder(good) == good.resolve()

    with pytest.raises(QuarantineError):
        validate_quarantine_folder(tmp_path / "missing")
    with pytest.raises(QuarantineError):
        validate_quarantine_folder(_file(tmp_path / "f.txt"))


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def test_plan_preserves_source_relative_tree(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    nested = _file(source_root / "screens" / "one.png")
    quarantine = _quarantine_root(tmp_path)

    plan = build_quarantine_plan(source_root, quarantine, [_candidate(nested)])

    item = plan.items[0]
    assert item.relative == Path("screens/one.png")
    assert item.destination == quarantine / "screens" / "one.png"
    assert item.source == nested
    assert item.identity == _identity(nested)


def test_plan_returns_canonical_roots_and_unique_batch_id(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_file = _file(source_root / "one.png")
    quarantine = _quarantine_root(tmp_path)

    plan = build_quarantine_plan(source_root, quarantine, [_candidate(source_file)])
    assert plan.source_root == source_root.resolve()
    assert plan.quarantine_root == quarantine.resolve()
    assert plan.batch_id.strip()


def test_plan_batch_ids_are_unique_across_calls(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    file = _file(source_root / "one.png")
    quarantine = _quarantine_root(tmp_path)

    first = build_quarantine_plan(source_root, quarantine, [_candidate(file)])
    second = build_quarantine_plan(source_root, quarantine, [_candidate(file)])

    assert first.batch_id != second.batch_id
    assert first.batch_id.strip()


def test_plan_preserves_candidate_order(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    files = [_file(source_root / f"{name}.png") for name in ("a", "b", "c")]
    quarantine = _quarantine_root(tmp_path)

    plan = build_quarantine_plan(source_root, quarantine, [_candidate(files[2]), _candidate(files[0])])

    assert [item.source for item in plan.items] == [files[2], files[0]]


def test_plan_rejects_empty_candidate_list(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    quarantine = _quarantine_root(tmp_path)

    with pytest.raises(QuarantineError):
        build_quarantine_plan(source_root, quarantine, [])


def test_plan_rejects_candidate_outside_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    outside = _file(tmp_path / "outside.png")
    quarantine = _quarantine_root(tmp_path)

    with pytest.raises(QuarantineError):
        build_quarantine_plan(source_root, quarantine, [_candidate(outside)])


def test_plan_rejects_sibling_spelled_through_parent_traversal(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    escape = Path(tmp_path / "source" / ".." / "outsider.png").resolve()
    _file(escape)
    quarantine = _quarantine_root(tmp_path)

    with pytest.raises(QuarantineError):
        build_quarantine_plan(source_root, quarantine, [_candidate(escape)])


@pytest.mark.parametrize(
    "bad",
    [None, {"path": "x"}, SimpleNamespace(path=None, identity=None)],
)
def test_plan_rejects_malformed_candidates(tmp_path: Path, bad) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    quarantine = _quarantine_root(tmp_path)

    with pytest.raises(QuarantineError):
        build_quarantine_plan(source_root, quarantine, [bad])


def test_plan_rejects_missing_candidate_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    quarantine = _quarantine_root(tmp_path)
    candidate = SimpleNamespace(
        path=source_root / "gone.png", identity=SourceIdentity(0, "a" * 64)
    )

    with pytest.raises(QuarantineError):
        build_quarantine_plan(source_root, quarantine, [candidate])


def test_plan_rejects_directory_candidate(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    target_dir = source_root / "folder"
    target_dir.mkdir(parents=True)
    quarantine = _quarantine_root(tmp_path)
    candidate = SimpleNamespace(
        path=target_dir, identity=SourceIdentity(0, "a" * 64)
    )

    with pytest.raises(QuarantineError):
        build_quarantine_plan(source_root, quarantine, [candidate])


def test_plan_rejects_symbolic_link_candidate(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    quarantine = _quarantine_root(tmp_path)
    real = _file(source_root / "real.png")
    link = source_root / "link.png"
    try:
        link.symlink_to(real)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    with pytest.raises(QuarantineError):
        build_quarantine_plan(source_root, quarantine, [_candidate(link)])


def test_plan_rejects_duplicate_source_paths(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    file = _file(source_root / "one.png")
    quarantine = _quarantine_root(tmp_path)

    with pytest.raises(QuarantineError):
        build_quarantine_plan(
            source_root, quarantine, [_candidate(file), _candidate(file)]
        )


def test_plan_rejects_duplicate_normalized_destinations(tmp_path: Path) -> None:
    if os.path.normcase("A") == "A":
        pytest.skip("Case folding is not meaningful on this filesystem")
    source_root = tmp_path / "source"
    cap = _file(source_root / "A.png")
    lower = _file(source_root / "a.png")
    quarantine = _quarantine_root(tmp_path)

    with pytest.raises(QuarantineError):
        build_quarantine_plan(
            source_root, quarantine, [_candidate(cap), _candidate(lower)]
        )


def test_planning_is_read_only(tmp_path: Path) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("one.png"): b"data"}
    )

    assert (quarantine_root / MOVE_LOG_NAME).exists() is False
    assert sorted(p.name for p in quarantine_root.iterdir()) == []
    assert _assert_unchanged(source_root / "one.png", b"data") is None


# ---------------------------------------------------------------------------
# Move record
# ---------------------------------------------------------------------------


def test_move_log_writes_schema_planned_and_terminal_records(tmp_path: Path) -> None:
    plan, _, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa", Path("s/b.png"): b"bbb"}
    )

    execute_quarantine_plan(plan)

    records = _read_lines(quarantine_root)
    assert len(records) == 4
    expected_fields = {
        "schema_version",
        "batch_id",
        "timestamp_utc",
        "event",
        "source",
        "destination",
        "sha256",
        "message",
    }
    for record in records:
        assert set(record) == expected_fields
        assert record["schema_version"] == 1
        assert record["batch_id"] == plan.batch_id
        assert record["timestamp_utc"].endswith("Z")
        assert record["sha256"]
    assert [record["event"] for record in records] == [
        "planned",
        "planned",
        "moved",
        "moved",
    ]


def test_move_log_records_are_one_compact_json_line_each(tmp_path: Path) -> None:
    plan, _, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )

    execute_quarantine_plan(plan)

    raw = (quarantine_root / MOVE_LOG_NAME).read_text(encoding="utf-8")
    lines = raw.splitlines()
    assert raw.endswith("\n")
    assert len(lines) == 2
    assert all(line.count("\n") == 0 for line in lines)


def test_move_log_append_preserves_existing_valid_records(tmp_path: Path) -> None:
    plan, _, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )
    execute_quarantine_plan(plan)
    first = (quarantine_root / MOVE_LOG_NAME).read_text(encoding="utf-8")

    second_plan, _, _, _ = _make_plan(
        tmp_path, {Path("b.png"): b"bbb"}
    )
    execute_quarantine_plan(second_plan)

    raw = (quarantine_root / MOVE_LOG_NAME).read_text(encoding="utf-8")
    assert raw.startswith(first)
    assert len(_read_lines(quarantine_root)) == 4


def test_log_path_that_is_a_directory_fails_before_any_move(
    tmp_path: Path,
) -> None:
    _, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )
    candidate = _candidate(source_root / "a.png")
    plan = build_quarantine_plan(source_root, quarantine_root, [candidate])
    (quarantine_root / MOVE_LOG_NAME).mkdir()

    with pytest.raises(QuarantineError):
        execute_quarantine_plan(plan)

    assert (source_root / "a.png").read_bytes() == b"aaa"
    assert not (quarantine_root / "a.png").exists()


def test_initial_record_failure_leaves_every_source_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa", Path("b.png"): b"bbb"}
    )

    def failed_log(path, records):
        raise OSError("log unavailable")

    monkeypatch.setattr(quarantine_mod, "_write_move_log_records", failed_log)

    with pytest.raises(QuarantineError):
        execute_quarantine_plan(plan)

    assert (source_root / "a.png").read_bytes() == b"aaa"
    assert (source_root / "b.png").read_bytes() == b"bbb"
    assert not (quarantine_root / MOVE_LOG_NAME).exists()


def test_terminal_record_failure_stops_later_items_and_keeps_planned(
    tmp_path: Path, monkeypatch
) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa", Path("b.png"): b"bbb", Path("c.png"): b"ccc"}
    )
    original = quarantine_mod._write_move_log_records
    calls = {"count": 0}

    def flaky_log(path, records):
        calls["count"] += 1
        if calls["count"] == 3:
            raise OSError("terminal log failed")
        return original(path, records)

    monkeypatch.setattr(quarantine_mod, "_write_move_log_records", flaky_log)

    summary = execute_quarantine_plan(plan)

    assert summary.state is QuarantineState.COMPLETED_WITH_FAILURES
    assert summary.moved_count == 1
    assert summary.failed_count == 1
    assert len(summary.outcomes) == 2
    assert summary.outcomes[0].status is MoveStatus.MOVED
    assert "record" in summary.outcomes[1].message
    assert (source_root / "a.png").exists() is False
    assert (source_root / "b.png").exists() is False
    assert (source_root / "c.png").exists() is True
    assert (quarantine_root / "b.png").read_bytes() == b"bbb"
    records = _read_lines(quarantine_root)
    assert [record["event"] for record in records] == [
        "planned",
        "planned",
        "planned",
        "moved",
    ]


def test_move_log_excludes_image_server_and_reason_content(
    tmp_path: Path,
) -> None:
    plan, _, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"secret-image-bytes"}
    )

    execute_quarantine_plan(plan)

    raw = (quarantine_root / MOVE_LOG_NAME).read_text(encoding="utf-8")
    assert "secret-image-bytes" not in raw
    assert "thumb" not in raw
    assert "data:image/png" not in raw
    assert "reason" not in raw
    assert "captioned meme" not in raw


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_single_item_move_succeeds_and_source_is_removed(tmp_path: Path) -> None:
    original = b"one"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )

    summary = execute_quarantine_plan(plan)

    assert summary.state is QuarantineState.COMPLETED
    assert summary.moved_count == 1
    assert summary.failed_count == 0
    assert summary.conflict_count == 0
    assert (source_root / "a.png").exists() is False
    assert (quarantine_root / "a.png").read_bytes() == original


def test_successful_move_preserves_mode_and_timestamps(tmp_path: Path) -> None:
    original = b"one"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )
    before = (source_root / "a.png").stat()

    execute_quarantine_plan(plan)

    after = (quarantine_root / "a.png").stat()
    assert after.st_mode == before.st_mode
    assert abs(after.st_mtime_ns - before.st_mtime_ns) < 200_000_000
    assert abs(after.st_atime_ns - before.st_atime_ns) < 200_000_000


def test_multiple_items_execute_in_order_with_progress(tmp_path: Path) -> None:
    files = {Path("a.png"): b"aaa", Path("s/b.png"): b"bbb", Path("c.png"): b"ccc"}
    plan, source_root, quarantine_root, _ = _make_plan(tmp_path, files)
    progress: list[tuple[int, int]] = []

    summary = execute_quarantine_plan(plan, progress=lambda done, total: progress.append((done, total)))

    assert summary.state is QuarantineState.COMPLETED
    assert summary.moved_count == 3
    assert [outcome.status for outcome in summary.outcomes] == [
        MoveStatus.MOVED,
        MoveStatus.MOVED,
        MoveStatus.MOVED,
    ]
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert (source_root / "a.png").exists() is False
    assert (source_root / "c.png").exists() is False
    assert (quarantine_root / "s" / "b.png").read_bytes() == b"bbb"


def test_conflict_never_overwrites_existing_destination(tmp_path: Path) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"new-content"}
    )
    destination = quarantine_root / "a.png"
    legacy = b"keep-me"
    _file(destination, legacy)

    summary = execute_quarantine_plan(plan)

    assert summary.state is QuarantineState.FAILED
    assert summary.conflict_count == 1
    assert summary.moved_count == 0
    assert destination.read_bytes() == legacy
    assert (source_root / "a.png").exists()


def test_destination_directory_is_conflict(tmp_path: Path) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"content"}
    )
    (quarantine_root / "a.png").mkdir()

    summary = execute_quarantine_plan(plan)

    assert summary.conflict_count == 1
    assert (quarantine_root / "a.png").is_dir()
    assert (source_root / "a.png").read_bytes() == b"content"


def test_destination_broken_link_is_conflict(tmp_path: Path) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"content"}
    )
    broken = quarantine_root / "a.png"
    try:
        broken.symlink_to(quarantine_root / "nonexistent.png")
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    summary = execute_quarantine_plan(plan)

    assert summary.conflict_count == 1
    assert broken.is_symlink()
    assert (source_root / "a.png").exists()


def test_case_folded_existing_destination_is_conflict(tmp_path: Path) -> None:
    if os.path.normcase("A") == "A":
        pytest.skip("Case folding is not meaningful on this filesystem")
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"content"}
    )
    _file(quarantine_root / "A.png", b"existing")

    summary = execute_quarantine_plan(plan)

    assert summary.conflict_count == 1
    assert (quarantine_root / "A.png").read_bytes() == b"existing"
    assert (source_root / "a.png").exists()


def test_byte_count_change_after_scan_is_rejected(tmp_path: Path) -> None:
    original = b"aaa"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )
    path = source_root / "a.png"
    path.write_bytes(b"different-length-content")

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert summary.moved_count == 0
    assert summary.state is QuarantineState.FAILED
    assert not (quarantine_root / "a.png").exists()
    assert path.read_bytes() == b"different-length-content"


def test_same_length_digest_change_is_rejected(tmp_path: Path) -> None:
    original = b"aaa"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )
    path = source_root / "a.png"
    tampered = b"aab"
    assert len(tampered) == len(original)
    path.write_bytes(tampered)

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert not (quarantine_root / "a.png").exists()
    assert path.read_bytes() == tampered


def test_source_changed_during_copy_is_rejected_and_kept(
    tmp_path: Path, monkeypatch
) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )
    original = quarantine_mod._revalidate_source
    calls = {"count": 0}

    def changed_later(path, expected):
        calls["count"] += 1
        if calls["count"] == 2:
            raise QuarantineError("The source file changed after it was scanned.")
        return original(path, expected)

    monkeypatch.setattr(quarantine_mod, "_revalidate_source", changed_later)

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert calls["count"] == 2
    assert (source_root / "a.png").read_bytes() == b"aaa"
    assert not (quarantine_root / "a.png").exists()


def test_source_replaced_by_symlink_is_rejected(tmp_path: Path) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )
    path = source_root / "a.png"
    destination = quarantine_root / "a.png"
    try:
        path.unlink()
        path.symlink_to(tmp_path / "elsewhere.png")
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert path.is_symlink()
    assert not destination.exists()


def test_source_replaced_by_directory_is_rejected(tmp_path: Path) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )
    path = source_root / "a.png"
    path.unlink()
    path.mkdir()

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert path.is_dir()
    assert not (quarantine_root / "a.png").exists()


def test_missing_source_is_rejected(tmp_path: Path) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )
    (source_root / "a.png").unlink()

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert not (quarantine_root / "a.png").exists()


def test_destination_parent_replaced_by_symlink_is_rejected(
    tmp_path: Path,
) -> None:
    _, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("sub/a.png"): b"aaa"}
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    quarantine_sub = quarantine_root / "sub"
    try:
        quarantine_sub.symlink_to(elsewhere, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Cannot create symbolic links: {error}")
    candidate = _candidate(source_root / "sub" / "a.png")
    plan = build_quarantine_plan(source_root, quarantine_root, [candidate])

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert (source_root / "sub" / "a.png").read_bytes() == b"aaa"
    assert sorted(p.name for p in elsewhere.iterdir()) == []


def test_copy_failure_removes_incomplete_destination_and_keeps_source(
    tmp_path: Path, monkeypatch
) -> None:
    original = b"aaa"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )

    def failed_copy(source, destination, expected):
        _file(destination, b"partial")
        raise QuarantineError("The file could not be copied safely.")

    monkeypatch.setattr(quarantine_mod, "_copy_verified", failed_copy)

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert (source_root / "a.png").read_bytes() == original
    assert not (quarantine_root / "a.png").exists()


def test_verification_mismatch_keeps_source_and_removes_destination(
    tmp_path: Path, monkeypatch
) -> None:
    original = b"aaa"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )

    def mismatched_copy(source, destination, expected):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"wrong")
        raise QuarantineError("The copied file did not match the source.")

    monkeypatch.setattr(quarantine_mod, "_copy_verified", mismatched_copy)

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert "did not match" in summary.outcomes[0].message
    assert (source_root / "a.png").read_bytes() == original
    assert not (quarantine_root / "a.png").exists()


def test_metadata_failure_keeps_source(tmp_path: Path, monkeypatch) -> None:
    original = b"aaa"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )

    def failed_metadata(destination, source_stat):
        raise OSError("metadata denied")

    monkeypatch.setattr(quarantine_mod, "_apply_metadata", failed_metadata)

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert (source_root / "a.png").read_bytes() == original
    assert not (quarantine_root / "a.png").exists()


def test_source_removal_failure_keeps_source_and_verified_destination(
    tmp_path: Path, monkeypatch
) -> None:
    original = b"aaa"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )

    def failed_removal(source):
        raise OSError("lock denied")

    monkeypatch.setattr(quarantine_mod, "_remove_source", failed_removal)

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    assert (source_root / "a.png").read_bytes() == original
    assert (quarantine_root / "a.png").read_bytes() == original


def test_cleanup_failure_reports_partial_and_next_move_sees_conflict(
    tmp_path: Path, monkeypatch
) -> None:
    original = b"aaa"
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): original}
    )

    def failed_copy(source, destination, expected):
        _file(destination, b"partial")
        raise QuarantineError("The file could not be copied safely.")

    def failed_cleanup(destination):
        raise OSError("cleanup denied")

    monkeypatch.setattr(quarantine_mod, "_copy_verified", failed_copy)
    monkeypatch.setattr(quarantine_mod, "_remove_partial_destination", failed_cleanup)

    first = execute_quarantine_plan(plan)

    assert first.failed_count == 1
    assert (source_root / "a.png").read_bytes() == original
    assert (quarantine_root / "a.png").read_bytes() == b"partial"

    second = execute_quarantine_plan(plan)

    assert second.conflict_count == 1
    assert (source_root / "a.png").read_bytes() == original
    assert (quarantine_root / "a.png").read_bytes() == b"partial"


@pytest.mark.parametrize("failure_index", [0, 1, 2])
def test_first_middle_or_last_failure_keeps_order_and_retains_source(
    tmp_path: Path, monkeypatch, failure_index: int
) -> None:
    files = {
        Path("a.png"): b"aaa",
        Path("b.png"): b"bbb",
        Path("c.png"): b"ccc",
    }
    plan, source_root, quarantine_root, _ = _make_plan(tmp_path, files)
    original = quarantine_mod._revalidate_source
    calls = {"count": 0}

    def fail_at(path, expected):
        calls["count"] += 1
        if calls["count"] == failure_index + 1:
            raise QuarantineError("The source file changed after it was scanned.")
        return original(path, expected)

    monkeypatch.setattr(quarantine_mod, "_revalidate_source", fail_at)

    summary = execute_quarantine_plan(plan)

    assert summary.moved_count == 2
    assert summary.failed_count == 1
    assert summary.state is QuarantineState.COMPLETED_WITH_FAILURES
    assert summary.outcomes[failure_index].status is MoveStatus.FAILED
    names = (Path("a.png"), Path("b.png"), Path("c.png"))
    expected_relative = names[failure_index]
    surviving = source_root / expected_relative
    assert surviving.read_bytes() == files[expected_relative]
    others = [p for p in (source_root / "a.png", source_root / "b.png", source_root / "c.png") if p != surviving]
    assert all(not p.exists() for p in others)
    moved_bytes = {item.relative: item.destination.read_bytes() for item in plan.items if item.destination.exists()}
    assert all(moved_bytes[item.relative] == files[item.relative] for item in plan.items if item.relative != expected_relative)


def test_one_conflict_does_not_stop_later_independent_items(
    tmp_path: Path,
) -> None:
    files = {Path("a.png"): b"aaa", Path("b.png"): b"bbb", Path("c.png"): b"ccc"}
    plan, source_root, quarantine_root, _ = _make_plan(tmp_path, files)
    _file(quarantine_root / "b.png", b"taken")

    summary = execute_quarantine_plan(plan)

    assert summary.conflict_count == 1
    assert summary.moved_count == 2
    assert (quarantine_root / "a.png").read_bytes() == b"aaa"
    assert (quarantine_root / "b.png").read_bytes() == b"taken"
    assert (quarantine_root / "c.png").read_bytes() == b"ccc"
    assert (source_root / "b.png").exists()
    assert not (source_root / "a.png").exists()


def test_unexpected_exception_becomes_fixed_safe_error(tmp_path: Path, monkeypatch) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )
    secret = "/private/unrelated/path"

    def boom(path, expected):
        raise RuntimeError(f"internal {secret}")

    monkeypatch.setattr(quarantine_mod, "_revalidate_source", boom)

    summary = execute_quarantine_plan(plan)

    assert summary.failed_count == 1
    message = summary.outcomes[0].message
    assert secret not in message
    assert "internal" not in message
    assert (source_root / "a.png").read_bytes() == b"aaa"


def test_error_text_never_exposes_source_bytes_or_digest(tmp_path: Path) -> None:
    plan, source_root, quarantine_root, _ = _make_plan(
        tmp_path, {Path("a.png"): b"aaa"}
    )
    (source_root / "a.png").write_bytes(b"tampered")

    summary = execute_quarantine_plan(plan)

    assert "tampered" not in summary.outcomes[0].message
    assert "aaa" not in summary.outcomes[0].message
    digest = _identity(source_root / "a.png").sha256
    assert digest not in summary.outcomes[0].message


def test_quarantine_never_writes_beside_source_files(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _file(source_root / "a.png", b"aaa")
    quarantine = _quarantine_root(tmp_path)
    plan = build_quarantine_plan(source_root, quarantine, [_candidate(source_root / "a.png")])

    execute_quarantine_plan(plan)

    assert sorted(p.name for p in source_root.iterdir()) == []
    assert sorted(p.name for p in quarantine.iterdir()) == sorted(
        ["a.png", MOVE_LOG_NAME]
    )


def test_module_has_no_gui_or_network_dependency() -> None:
    source = inspect.getsource(quarantine_mod)
    assert "PySide" not in source
    assert "http" not in source
    assert "socket" not in source
    assert "shutil.move" not in source