"""Quarantine mid-execution safety tests (M1 parent/root TOCTOU, M2 log orphans).

No network. All races are injected through deterministic hooks.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import img_ai_filter.quarantine as quarantine_mod
from img_ai_filter.image_payload import SourceIdentity
from img_ai_filter.quarantine import (
    MOVE_LOG_NAME,
    MoveStatus,
    QuarantineState,
    build_quarantine_plan,
    execute_quarantine_plan,
)


def _file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _identity(path: Path) -> SourceIdentity:
    data = path.read_bytes()
    return SourceIdentity(len(data), hashlib.sha256(data).hexdigest())


def _candidate(path: Path) -> SimpleNamespace:
    return SimpleNamespace(path=path, identity=_identity(path))


def _roots(tmp_path: Path):
    src = tmp_path / "source"
    q = tmp_path / "quarantine"
    src.mkdir()
    q.mkdir()
    return src, q


def test_m1_parent_symlink_after_walk_does_not_redirect_copy(tmp_path):
    src, q = _roots(tmp_path)
    victim = tmp_path / "victim"
    victim.mkdir()
    _file(src / "sub" / "a.png", b"secret-bytes")
    plan = build_quarantine_plan(src, q, [_candidate(src / "sub" / "a.png")])

    real_makedirs = os.makedirs
    hooked = {"done": False}

    def racing_makedirs(path, *args, **kwargs):
        if not hooked["done"] and Path(path) == q / "sub":
            hooked["done"] = True
            (q / "sub").symlink_to(victim, target_is_directory=True)
        return real_makedirs(path, *args, **kwargs)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(os, "makedirs", racing_makedirs)
    try:
        summary = execute_quarantine_plan(plan)
    finally:
        monkeypatch.undo()

    assert hooked["done"]
    assert summary.outcomes[0].status == MoveStatus.FAILED
    assert "symbolic link" in summary.outcomes[0].message
    # Nothing from the source leaked outside the quarantine root.
    assert not (victim / "a.png").exists()
    assert (src / "sub" / "a.png").read_bytes() == b"secret-bytes"


def test_m1_root_swap_mid_loop_fails_closed(tmp_path):
    src, q = _roots(tmp_path)
    _file(src / "a.png", b"aaa")
    _file(src / "b.png", b"bbb")
    plan = build_quarantine_plan(
        src, q, [_candidate(src / "a.png"), _candidate(src / "b.png")]
    )
    victim = tmp_path / "victim"
    victim.mkdir()

    def swapping_progress(done, total):
        if done == 1:
            shutil.rmtree(q)
            q.symlink_to(victim, target_is_directory=True)

    summary = execute_quarantine_plan(plan, progress=swapping_progress)

    assert summary.outcomes[0].status == MoveStatus.MOVED
    assert summary.outcomes[1].status == MoveStatus.FAILED
    assert "changed during the move" in summary.outcomes[1].message
    # Second source never removed; no source bytes written outside.
    assert (src / "b.png").read_bytes() == b"bbb"
    assert not (victim / "b.png").exists()
    assert not (victim / "sub").exists()


def test_m2_conflict_log_failure_rolls_back_orphaned_copies(tmp_path, monkeypatch):
    src, q = _roots(tmp_path)
    for name, data in (("a.png", b"aaa"), ("b.png", b"bbb"), ("c.png", b"ccc")):
        _file(src / name, data)
    # Pre-create destination for c so it takes the conflict path.
    _file(q / "c.png", b"existing")
    plan = build_quarantine_plan(
        src, q,
        [_candidate(src / "a.png"), _candidate(src / "b.png"), _candidate(src / "c.png")],
    )
    original = quarantine_mod._write_move_log_records

    def flaky_log(path, records):
        if records and records[0].get("event") == "conflict":
            raise OSError("conflict log failed")
        return original(path, records)

    monkeypatch.setattr(quarantine_mod, "_write_move_log_records", flaky_log)

    summary = execute_quarantine_plan(plan)

    # Truncation semantic kept (pinned): unprocessed items are dropped...
    assert [o.status for o in summary.outcomes] == [MoveStatus.FAILED]
    # ...but verified copies of a/b were rolled back: no silent duplicates.
    assert not (q / "a.png").exists()
    assert not (q / "b.png").exists()
    assert (src / "a.png").read_bytes() == b"aaa"
    assert (src / "b.png").read_bytes() == b"bbb"
    assert (q / "c.png").read_bytes() == b"existing"


def test_m2_moved_log_failure_keeps_exact_record_error(tmp_path, monkeypatch):
    src, q = _roots(tmp_path)
    _file(src / "a.png", b"aaa")
    plan = build_quarantine_plan(src, q, [_candidate(src / "a.png")])
    original = quarantine_mod._write_move_log_records
    calls = {"count": 0}

    def flaky_log(path, records):
        calls["count"] += 1
        if calls["count"] == 2:  # the "moved" record
            raise OSError("moved log failed")
        return original(path, records)

    monkeypatch.setattr(quarantine_mod, "_write_move_log_records", flaky_log)

    summary = execute_quarantine_plan(plan)

    # Bytes are safe (moved) but provenance is explicit, never silent MOVED.
    assert summary.outcomes[0].status == MoveStatus.FAILED
    assert summary.outcomes[0].message == "The move record could not be updated."
    assert (q / "a.png").read_bytes() == b"aaa"
    assert not (src / "a.png").exists()


def test_m2_failed_record_write_failure_stays_failed_and_intact(tmp_path, monkeypatch):
    src, q = _roots(tmp_path)
    _file(src / "a.png", b"aaa")
    plan = build_quarantine_plan(src, q, [_candidate(src / "a.png")])
    (src / "a.png").write_bytes(b"changed-after-scan")
    original = quarantine_mod._write_move_log_records

    def flaky_log(path, records):
        if records and records[0].get("event") == "failed":
            raise OSError("failed log failed")
        return original(path, records)

    monkeypatch.setattr(quarantine_mod, "_write_move_log_records", flaky_log)

    summary = execute_quarantine_plan(plan)

    assert summary.outcomes[0].status == MoveStatus.FAILED
    assert (src / "a.png").read_bytes() == b"changed-after-scan"
    assert not (q / "a.png").exists()
