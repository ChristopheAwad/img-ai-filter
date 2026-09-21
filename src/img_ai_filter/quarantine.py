"""GUI-neutral "safe quarantine" backend that moves verified image files.

This module copies verified checked image files byte-for-byte from a
user-selected source folder into a user-selected quarantine folder. It never
overwrites an existing file, leaves the source behind if anything changed,
and writes a durable append-only JSONL move log next to the quarantine folder.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any
import uuid

from .image_payload import SourceIdentity
from .scanner import is_windows_reparse_point


MOVE_LOG_NAME = ".img-ai-filter-moves.jsonl"
COPY_CHUNK_SIZE = 1024 * 1024


class QuarantineError(ValueError):
    """Raised when a quarantine operation cannot proceed safely."""


class MoveStatus(Enum):
    MOVED = auto()
    CONFLICT = auto()
    FAILED = auto()


class QuarantineState(Enum):
    COMPLETED = auto()
    COMPLETED_WITH_FAILURES = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class QuarantineItem:
    source: Path
    relative: Path
    destination: Path
    identity: SourceIdentity


@dataclass(frozen=True, slots=True)
class QuarantinePlan:
    source_root: Path
    quarantine_root: Path
    items: tuple[QuarantineItem, ...]
    batch_id: str


@dataclass(frozen=True, slots=True)
class MoveOutcome:
    source: Path
    destination: Path
    status: MoveStatus
    message: str


@dataclass(frozen=True, slots=True)
class QuarantineSummary:
    batch_id: str
    quarantine_root: Path
    outcomes: tuple[MoveOutcome, ...]
    state: QuarantineState

    @property
    def moved_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is MoveStatus.MOVED)

    @property
    def failed_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is MoveStatus.FAILED)

    @property
    def conflict_count(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.status is MoveStatus.CONFLICT)


def _make_batch_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("B%Y%m%dT%H%M%S%fZ")
    return stamp + "-" + uuid.uuid4().hex[:8]


def validate_quarantine_folder(path) -> Path:
    """Return the canonical path of a usable quarantine folder."""
    try:
        value = os.fspath(path)
    except TypeError:
        raise QuarantineError("The quarantine folder path is invalid.") from None
    if isinstance(value, bytes):
        value = os.fsdecode(value)
    if not value.strip():
        raise QuarantineError("The quarantine folder path is invalid.")
    candidate = Path(value)
    if candidate.is_symlink() or is_windows_reparse_point(candidate):
        raise QuarantineError("Symbolic links are not accepted as quarantine folders.")
    if not candidate.is_dir():
        raise QuarantineError("The quarantine folder is not an existing directory.")
    if not os.access(candidate, os.R_OK | os.X_OK):
        raise QuarantineError("The quarantine folder is not readable.")
    return candidate.resolve()


def _same_or_overlap(left: Path, right: Path) -> bool:
    left = left.resolve()
    right = right.resolve()
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def validate_quarantine_roots(source_root, quarantine_root) -> None:
    """Reject roots that are unsafe, missing, shared, or overlapping."""
    source = validate_quarantine_folder(source_root)
    quarantine = validate_quarantine_folder(quarantine_root)
    if _same_or_overlap(source, quarantine):
        raise QuarantineError("The source and quarantine folders must be separate.")


def build_quarantine_plan(source_root, quarantine_root, candidates, *, batch_id=None) -> QuarantinePlan:
    """Plan verified source files for a later safe quarantine move."""
    validate_quarantine_roots(source_root, quarantine_root)
    try:
        candidate_list = list(candidates)
    except TypeError:
        raise QuarantineError("No candidates were provided.") from None
    if not candidate_list:
        raise QuarantineError("No candidates were provided.")

    resolved_source = Path(source_root).resolve()
    resolved_quarantine = Path(quarantine_root).resolve()
    items = []
    seen_sources = set()
    seen_destinations = set()
    for candidate in candidate_list:
        try:
            path_value = os.fspath(candidate.path)
            identity = candidate.identity
            identity.byte_count
            identity.sha256
        except (AttributeError, TypeError, ValueError):
            raise QuarantineError("A candidate is not usable.") from None
        if not str(path_value).strip():
            raise QuarantineError("A candidate is not usable.")
        candidate_path = Path(path_value)
        if candidate_path.is_symlink() or is_windows_reparse_point(candidate_path):
            raise QuarantineError("Symbolic links are not accepted as source files.")
        if not candidate_path.is_file():
            raise QuarantineError("The candidate is not a regular file.")
        abs_path = Path(os.path.abspath(os.fspath(candidate_path)))
        resolved_path = abs_path.resolve()
        if not resolved_path.is_relative_to(resolved_source):
            raise QuarantineError("The candidate is outside the source folder.")
        relative = resolved_path.relative_to(resolved_source)
        destination = resolved_quarantine / relative
        if resolved_path in seen_sources:
            raise QuarantineError("Duplicate source paths are not allowed.")
        seen_sources.add(resolved_path)
        normalized_destination = os.path.normcase(os.path.normpath(str(destination)))
        if normalized_destination in seen_destinations:
            raise QuarantineError("Duplicate destinations are not allowed.")
        seen_destinations.add(normalized_destination)
        items.append(
            QuarantineItem(
                source=resolved_path,
                relative=relative,
                destination=destination,
                identity=identity,
            )
        )
    if batch_id is None:
        batch_id = _make_batch_id()
    return QuarantinePlan(resolved_source, resolved_quarantine, tuple(items), batch_id)


def _move_log_record(plan: QuarantinePlan, item: QuarantineItem, event: str, message: str) -> dict[str, Any]:
    """Build one JSONL record with exactly the durable schema fields."""
    return {
        "schema_version": 1,
        "batch_id": plan.batch_id,
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "event": event,
        "source": str(item.source),
        "destination": str(item.destination),
        "sha256": item.identity.sha256,
        "message": message,
    }


def _safety_walk(quarantine_root: Path, destination: Path) -> None:
    """Reject symbolic links in the destination parent chain."""
    relative_parent = destination.parent.relative_to(quarantine_root)
    current = quarantine_root
    for part in relative_parent.parts:
        current = current / part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode) or is_windows_reparse_point(current):
                raise QuarantineError("A quarantine destination path is a symbolic link.")
        except FileNotFoundError:
            continue
        except OSError:
            raise QuarantineError("The quarantine destination could not be inspected.") from None


CONFLICT_MESSAGE = "A file with the same name already exists in the quarantine folder."
SAFE_ERROR_MESSAGE = "The file could not be moved safely."
RECORD_ERROR_MESSAGE = "The move record could not be updated."
REMOVE_ERROR_MESSAGE = "The source file could not be moved away after a verified copy."


def _record_failure(
    log_path: Path,
    plan: QuarantinePlan,
    item: QuarantineItem,
    message: str,
) -> bool:
    """Best-effort append of a FAILED terminal record. Returns success."""
    try:
        _write_move_log_records(log_path, [_move_log_record(plan, item, "failed", message)])
        return True
    except (OSError, QuarantineError):
        return False


def execute_quarantine_plan(plan, *, progress: Callable[[int, int], None] | None = None) -> QuarantineSummary:
    """Execute a plan safely, writing a durable log and moving verified files."""
    validate_quarantine_roots(plan.source_root, plan.quarantine_root)
    log_path = plan.quarantine_root / MOVE_LOG_NAME

    planned_records = [
        _move_log_record(plan, item, "planned", "")
        for item in plan.items
    ]
    try:
        _write_move_log_records(log_path, planned_records)
    except OSError:
        raise QuarantineError("The move log could not be written before any move.") from None

    total = len(plan.items)
    results: list[MoveOutcome | None] = [None] * total
    copied = [False] * total
    stopped = False

    for index, item in enumerate(plan.items):
        if stopped:
            break
        try:
            _revalidate_source(item.source, item.identity)
            source_stat = item.source.stat()
            _safety_walk(plan.quarantine_root, item.destination)
        except QuarantineError as error:
            try:
                _remove_partial_destination(item.destination)
            except OSError:
                pass
            _record_failure(log_path, plan, item, str(error))
            results[index] = MoveOutcome(item.source, item.destination, MoveStatus.FAILED, str(error))
            if progress is not None:
                progress(index + 1, total)
            continue
        except Exception:
            try:
                _remove_partial_destination(item.destination)
            except OSError:
                pass
            _record_failure(log_path, plan, item, SAFE_ERROR_MESSAGE)
            results[index] = MoveOutcome(item.source, item.destination, MoveStatus.FAILED, SAFE_ERROR_MESSAGE)
            if progress is not None:
                progress(index + 1, total)
            continue
        if item.destination.is_symlink() or item.destination.exists():
            try:
                _write_move_log_records(log_path, [_move_log_record(plan, item, "conflict", CONFLICT_MESSAGE)])
            except OSError:
                results[index] = MoveOutcome(item.source, item.destination, MoveStatus.FAILED, RECORD_ERROR_MESSAGE)
                stopped = True
            else:
                results[index] = MoveOutcome(item.source, item.destination, MoveStatus.CONFLICT, CONFLICT_MESSAGE)
            if progress is not None:
                progress(index + 1, total)
            continue
        try:
            _copy_verified(item.source, item.destination, item.identity)
            _apply_metadata(item.destination, source_stat)
        except QuarantineError as error:
            try:
                _remove_partial_destination(item.destination)
            except OSError:
                pass
            _record_failure(log_path, plan, item, str(error))
            results[index] = MoveOutcome(item.source, item.destination, MoveStatus.FAILED, str(error))
            if progress is not None:
                progress(index + 1, total)
            continue
        except Exception:
            try:
                _remove_partial_destination(item.destination)
            except OSError:
                pass
            _record_failure(log_path, plan, item, SAFE_ERROR_MESSAGE)
            results[index] = MoveOutcome(item.source, item.destination, MoveStatus.FAILED, SAFE_ERROR_MESSAGE)
            if progress is not None:
                progress(index + 1, total)
            continue
        copied[index] = True

    if stopped:
        outcomes = tuple(outcome for outcome in results if outcome is not None)
    else:
        for index, item in enumerate(plan.items):
            if not copied[index]:
                continue
            try:
                _revalidate_source(item.source, item.identity)
            except QuarantineError as error:
                try:
                    _remove_partial_destination(item.destination)
                except OSError:
                    pass
                _record_failure(log_path, plan, item, str(error))
                results[index] = MoveOutcome(
                    item.source, item.destination, MoveStatus.FAILED, str(error)
                )
                if progress is not None:
                    progress(index + 1, total)
                continue
            except Exception:
                try:
                    _remove_partial_destination(item.destination)
                except OSError:
                    pass
                _record_failure(log_path, plan, item, SAFE_ERROR_MESSAGE)
                results[index] = MoveOutcome(
                    item.source,
                    item.destination,
                    MoveStatus.FAILED,
                    SAFE_ERROR_MESSAGE,
                )
                if progress is not None:
                    progress(index + 1, total)
                continue

            _sync_directory(item.destination.parent)
            try:
                _remove_source(item.source)
            except Exception:
                _record_failure(log_path, plan, item, REMOVE_ERROR_MESSAGE)
                results[index] = MoveOutcome(
                    item.source,
                    item.destination,
                    MoveStatus.FAILED,
                    REMOVE_ERROR_MESSAGE,
                )
                if progress is not None:
                    progress(index + 1, total)
                continue
            try:
                _write_move_log_records(log_path, [_move_log_record(plan, item, "moved", "")])
            except OSError:
                results[index] = MoveOutcome(item.source, item.destination, MoveStatus.FAILED, RECORD_ERROR_MESSAGE)
                if progress is not None:
                    progress(index + 1, total)
                break
            results[index] = MoveOutcome(item.source, item.destination, MoveStatus.MOVED, "")
            if progress is not None:
                progress(index + 1, total)
        outcomes = tuple(outcome for outcome in results if outcome is not None)

    summary = QuarantineSummary(plan.batch_id, plan.quarantine_root, outcomes, QuarantineState.COMPLETED)
    moved = summary.moved_count
    failed = summary.failed_count
    conflicted = summary.conflict_count
    if moved > 0 and (failed > 0 or conflicted > 0):
        state = QuarantineState.COMPLETED_WITH_FAILURES
    elif moved == 0 and (failed > 0 or conflicted > 0):
        state = QuarantineState.FAILED
    else:
        state = QuarantineState.COMPLETED
    return QuarantineSummary(plan.batch_id, plan.quarantine_root, outcomes, state)


def _revalidate_source(path: Path, expected: SourceIdentity) -> None:
    """Reject a source that no longer matches its scanned identity."""
    try:
        if path.is_symlink() or is_windows_reparse_point(path):
            raise QuarantineError("The source file changed after it was scanned.")
        if not path.is_file():
            raise QuarantineError("The source file changed after it was scanned.")
        size = os.stat(path).st_size
        if size != expected.byte_count:
            raise QuarantineError("The source file changed after it was scanned.")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while True:
                chunk = source.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
        if digest.hexdigest() != expected.sha256:
            raise QuarantineError("The source file changed after it was scanned.")
    except OSError:
        raise QuarantineError("The source file changed after it was scanned.") from None


def _copy_verified(source: Path, destination: Path, expected: SourceIdentity) -> None:
    """Copy a source file into an exclusive destination and verify the copy."""
    try:
        os.makedirs(destination.parent, exist_ok=True)
        with destination.open("xb") as dst:
            with source.open("rb") as src:
                while True:
                    chunk = src.read(COPY_CHUNK_SIZE)
                    if not chunk:
                        break
                    dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        byte_count = 0
        digest = hashlib.sha256()
        with destination.open("rb") as dst:
            while True:
                chunk = dst.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                byte_count += len(chunk)
                digest.update(chunk)
        if byte_count != expected.byte_count or digest.hexdigest() != expected.sha256:
            raise QuarantineError("The copied file did not match the source.")
    except FileExistsError:
        raise QuarantineError("The destination already exists.") from None
    except OSError:
        raise QuarantineError("The file could not be copied safely.") from None


def _apply_metadata(destination: Path, source_stat) -> None:
    """Apply the source mode and timestamps to the copied destination."""
    os.chmod(destination, stat.S_IMODE(source_stat.st_mode))
    os.utime(destination, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))


def _remove_partial_destination(destination: Path) -> None:
    """Remove a partial destination, ignoring a missing file."""
    try:
        destination.unlink()
    except FileNotFoundError:
        pass


def _remove_source(source: Path) -> None:
    """Remove a fully verified source file."""
    os.unlink(source)


def _sync_directory(directory: Path) -> None:
    """Best-effort sync of a directory entry on supported platforms."""
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_move_log_records(log_path: Path, records: list[dict[str, Any]]) -> None:
    """Append JSONL records to a move log, preserving existing content."""
    if log_path.is_symlink() or (
        log_path.exists() and is_windows_reparse_point(log_path)
    ):
        raise QuarantineError("Symbolic links are not accepted as move logs.")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(log_path, flags, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, separators=(",", ":")) + "\n")
        file.flush()
        os.fsync(file.fileno())
    _sync_directory(log_path.parent)
