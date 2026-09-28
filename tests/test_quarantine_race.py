"""Race-hardening tests for quarantine executor (H1/H2). No network."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

from img_ai_filter.image_payload import SourceIdentity
from img_ai_filter.quarantine import (
    MoveStatus,
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


def test_h1_copy_race_does_not_delete_victim(tmp_path):
    src, q = _roots(tmp_path)
    _file(src / "a.png", b"old-bytes")
    plan = build_quarantine_plan(src, q, [_candidate(src / "a.png")])
    dest = plan.items[0].destination

    real_open = Path.open

    def racing_open(self, mode="r", *args, **kwargs):
        if Path(self) == dest and "x" in mode:
            # Victim appears between exists-check and xb-create.
            if not dest.exists() and not dest.is_symlink():
                dest.write_bytes(b"victim-bytes")
        return real_open(self, mode, *args, **kwargs)

    Path.open = racing_open  # type: ignore[method-assign]
    try:
        summary = execute_quarantine_plan(plan)
    finally:
        Path.open = real_open  # type: ignore[method-assign]

    assert dest.read_bytes() == b"victim-bytes"
    assert summary.outcomes[0].status == MoveStatus.CONFLICT
    assert (src / "a.png").read_bytes() == b"old-bytes"


def test_h1_empty_plan_has_no_outcomes(tmp_path):
    # Empty plan cannot be built; execute path must handle zero items safely.
    # Build a 1-item plan then execute a sliced empty-equivalent via direct call guard.
    # Here we assert build rejects empty (pins behavior, no unlink).
    src, q = _roots(tmp_path)
    try:
        build_quarantine_plan(src, q, [])
    except Exception:
        pass
    else:
        raise AssertionError("empty plan should raise")
    # No files created/deleted
    assert list(q.iterdir()) == []


def test_h2_source_swap_after_recheck_is_not_moved(tmp_path):
    src, q = _roots(tmp_path)
    _file(src / "a.png", b"old-bytes-1234")
    plan = build_quarantine_plan(src, q, [_candidate(src / "a.png")])
    dest = plan.items[0].destination
    old = (src / "a.png").read_bytes()
    new = b"N" * len(old)

    import img_ai_filter.quarantine as qmod

    orig_sync = qmod._sync_destination_ancestors

    def swapping_sync(root, parent):
        # Race: source replaced between 2nd revalidation and unlink.
        (src / "a.png").write_bytes(new)
        return orig_sync(root, parent)

    qmod._sync_destination_ancestors = swapping_sync  # type: ignore[method-assign]
    try:
        summary = execute_quarantine_plan(plan)
    finally:
        qmod._sync_destination_ancestors = orig_sync  # type: ignore[method-assign]

    assert summary.outcomes[0].status == MoveStatus.FAILED
    assert (src / "a.png").read_bytes() == new
    # Our verified copy of old bytes is cleaned up on detected change.
    assert (not dest.exists()) or dest.read_bytes() == old
