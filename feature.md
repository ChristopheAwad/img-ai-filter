# F-006: Scan Timing and History

## Status

The user approved the plan on 2026-09-20. The expanded scan and quarantine
activity-history implementation and automated verification are complete. The
user approved the desktop GUI on 2026-09-21 and authorized PR #7 for merge.

The feature was selected on 2026-09-20. It adds a live elapsed timer, a final
duration for every accepted scan attempt, and a local history of the newest 100
scan attempts.

Before implementation, record the current Git state and run the complete
offline test suite. The last recorded full-suite result from F-004/F-005 was:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
681 passed, 4 skipped, 1 warning in 57.90s
```

F-006 baseline recorded on 2026-09-20 before writing F-006 tests:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
699 passed, 4 skipped, 1 warning in 50.36s
```

The baseline worktree contained the approved planning changes to `feature.md`
and `roadmap.md` plus the unrelated untracked `quar-test/` directory. Do not
modify or commit that directory.

Implemented on 2026-09-20:

- strict GUI-neutral duration formatting and bounded versioned history storage
  in `scan_history.py`;
- live and final scan timing with deterministic injected clocks;
- exact-once records for completed, skipped, cancelled, failed, worker-error,
  and close-triggered attempts;
- the idle-only **Scan History** dialog, newest-first records, privacy
  disclosure, empty state, and confirmed clear action;
- durable product and user documentation.

Focused verification:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_scan_history.py tests/test_window_server.py tests/test_window.py -q
127 passed in 3.29s
```

Final automated verification:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
776 passed, 4 skipped, 1 warning in 57.17s
```

`git diff --check` passes. Artifact inspection found only the existing ignored
development environments/caches and sample data plus the unrelated untracked
`quar-test/` directory. No automated test contacted a network service.

## Goals

1. Show elapsed scan time while a scan is running.
2. Add the final elapsed duration to every completed, completed-with-skips,
   cancelled, or failed scan result.
3. Save one local history record for every scan attempt accepted after transfer
   consent.
4. Include attempts that fail during folder discovery, raise an unexpected
   worker error, are cancelled by the Cancel button, or are cancelled because
   the application is closing.
5. Keep only the newest 100 records.
6. Let the user inspect saved records in a simple in-application dialog.
7. Let the user clear all saved history after an explicit confirmation.
8. Keep scan timing and history failures separate from candidate detection and
   file quarantine behavior.

## Approved Product Decisions

- Measure from immediately after transfer consent is accepted and immediately
  before the scan worker is started until the worker finishes.
- Include folder discovery, image preparation, server requests, cancellation
  shutdown, and worker-failure handling in the duration.
- Do not create a record when consent is declined, scan readiness validation
  fails, or a duplicate scan request is ignored.
- Show elapsed time during list preparation, image progress, and cancellation.
- Refresh the live display once per second. Progress signals may refresh it
  sooner.
- Save duration as a nonnegative integer number of milliseconds.
- Display duration with whole-second precision. Display values below one second
  as `<1 sec`; use `N sec`, `N min N sec`, or `N hr N min N sec` for longer
  values.
- Save the source-folder path and discovered KoboldCpp model name.
- Do not save the endpoint URL or origin.
- Keep the newest 100 records and discard older records automatically.
- Show newest records first in the history dialog.
- Add a **Scan History** button to the main window.
- Disable **Scan History** while any connection, scan, or quarantine operation
  is active. History viewing and clearing never overlap a worker operation.
- Add **Clear History** inside the dialog. Require confirmation and default the
  confirmation to **No**.
- A timing or history-storage failure must never convert a successful scan into
  a failed scan, remove candidate results, or alter source files.
- A history write failure must add a fixed safe warning to the final scan status.
  Never display a raw settings exception.
- If the app is closing during an active scan, save exactly one cancelled record
  before waiting for the worker. Counts that are not yet available are stored as
  unavailable. Do not save a second record when the worker later finishes.
- History applies only to scans completed after F-006 is installed. Do not
  create synthetic records for earlier scans.

## Existing Contracts to Preserve

- Folder selection remains separate from scanning.
- A scan requires a tested loopback/private-LAN KoboldCpp endpoint and explicit
  consent before image transfer.
- Images are analyzed sequentially in a background thread.
- Automated tests never contact a real network service.
- Every server candidate starts unchecked.
- Source files remain unchanged by scanning and history recording.
- A rescan replaces visible candidate results but does not erase history.
- Selecting another source folder clears visible results but does not erase
  history.
- Scan cancellation closes the active transport and allows a later retry.
- Closing during a scan or quarantine operation remains safe.
- Quarantine move records and scan-history records remain separate.
- Existing endpoint and quarantine settings are not changed when history is
  appended, repaired, or cleared.

## Frozen Timing Contract

### Clocks

Use two clocks with different purposes:

- Use `time.perf_counter` for elapsed duration. Never calculate elapsed time by
  subtracting wall-clock timestamps.
- Use `datetime.now(timezone.utc)` for the record's start timestamp.

Inject both callables into `MainWindow` with those functions as production
defaults. Tests must supply deterministic fake clocks. Do not monkeypatch the
global Python clock in GUI tests.

Capture the start monotonic value and UTC timestamp after consent succeeds and
before `_start_operation("scan", ...)` is called. Capture the end monotonic
value when the scan worker finishes. Clamp a negative fake-clock result to zero
instead of storing a negative duration.

For an active scan interrupted by `closeEvent`, calculate and save the duration
at the first accepted close request. Its outcome is `cancelled`. Mark the
attempt as already recorded before waiting for the worker so delayed signals or
repeated close events cannot create duplicate records.

### Live Status

Keep one `QTimer` owned by `MainWindow`. Set its interval to 1000 milliseconds.
Start it only for an accepted scan and stop it when that scan is finalized or
recorded during close.

The live status forms are:

```text
Scanning: preparing the image list. Elapsed: <duration>.
Scanning: <done> of <total> images processed. Elapsed: <duration>.
Cancelling scan... Elapsed: <duration>.
```

Store the current phase and latest progress values as state. Both timer ticks
and scan progress signals must render from that state. A timer tick must not
replace a progress message with the preparation message.

Connection and quarantine status text must not receive a timer. A stale timer
or progress signal from an old generation must not update a new operation.

### Final Status

Append this exact sentence to the existing terminal scan status:

```text
Elapsed: <duration>.
```

Apply it to valid `ScanSummary` results, `ScanError`, invalid worker results, and
unexpected worker exceptions. If persistence fails, append this additional
fixed sentence:

```text
Scan history could not be saved.
```

Do not append duration to connection-test or quarantine results.

## Frozen History Data Contract

Add `src/img_ai_filter/scan_history.py`. It must not import PySide6 and must not
read the filesystem or use the network.

Define these constants:

```text
SCAN_HISTORY_KEY = "scan_history"
SCAN_HISTORY_SCHEMA_VERSION = 1
SCAN_HISTORY_LIMIT = 100
```

Define an immutable, slotted `ScanHistoryRecord` with exactly these fields:

- `started_at_utc`: nonblank ISO 8601 UTC text ending in `Z`;
- `source_folder`: nonblank absolute folder-path text;
- `model`: nonblank model-name text;
- `outcome`: one of `completed`, `completed_with_skips`, `cancelled`, or
  `failed`;
- `duration_ms`: nonnegative integer;
- `discovered`: nonnegative integer or `None`;
- `analyzed`: nonnegative integer or `None`;
- `candidates`: nonnegative integer or `None`;
- `ordinary`: nonnegative integer or `None`;
- `uncertain`: nonnegative integer or `None`;
- `failed`: nonnegative integer or `None`;
- `skipped_directories`: nonnegative integer or `None`.

Boolean values are not valid integers for any numeric field. A valid summary
record has integer values for all count fields. A worker failure, folder-scan
failure, invalid result, or close-before-summary record uses `None` for every
count field. Do not combine partial values from GUI progress with authoritative
summary counts.

Store one compact JSON object under `SCAN_HISTORY_KEY` using this shape:

```json
{"schema_version":1,"records":[{"started_at_utc":"2026-09-20T12:00:00Z","source_folder":"/example/images","model":"example-model","outcome":"completed","duration_ms":1250,"discovered":4,"analyzed":4,"candidates":1,"ordinary":3,"uncertain":0,"failed":0,"skipped_directories":0}]}
```

The top-level object must contain exactly `schema_version` and `records`. Each
record must contain exactly the frozen record fields. Serialize as compact JSON
with UTF-8-safe characters; do not manually construct JSON.

The history must never contain:

- endpoint URL, origin, host, or IP address;
- image bytes, thumbnail bytes, data URLs, or hashes;
- candidate paths or individual image names;
- classification categories or reasons;
- server request or response bodies;
- credentials, API keys, raw exceptions, or quarantine records.

## History Storage Behavior

Expose small GUI-neutral functions equivalent to:

- `load_scan_history(store) -> tuple[ScanHistoryRecord, ...]`;
- `append_scan_history(store, record) -> bool`;
- `clear_scan_history(store) -> bool`;
- `format_scan_duration(duration_ms) -> str`.

`load_scan_history` behavior:

- Return records in stored oldest-to-newest order. The GUI reverses them for
  display.
- Return an empty tuple for a missing key, store read exception, blank value,
  malformed JSON, non-object top level, unsupported schema, non-list `records`,
  or a payload with no valid records.
- Validate records independently. Keep valid records in order and omit malformed
  records.
- Return at most the newest 100 valid records even if external data contains
  more.
- Never raise because persisted data is invalid or unreadable.

`append_scan_history` behavior:

- Validate the new `ScanHistoryRecord` before touching the store. Programmer
  misuse may raise `ValueError`; normal persistence failures return `False`.
- Read the existing value. If the store read raises, return `False` and do not
  attempt a write because overwriting unknown existing history could lose data.
- Treat missing, blank, malformed, unsupported, or wholly invalid stored data as
  empty repairable history.
- Retain independently valid records from a partly malformed supported payload.
- Append the new record, retain the newest 100, serialize the complete payload,
  and perform one `store.write` call.
- Return `False` if serialization or writing fails. Return `True` only after the
  write call succeeds.
- Do not change any endpoint or quarantine setting.

`clear_scan_history` behavior:

- Delete only `SCAN_HISTORY_KEY`.
- Return `True` when deletion succeeds, including an already missing key.
- Return `False` on a store exception.
- Do not change endpoint or quarantine settings.

## Record Creation Rules

Snapshot these values when consent is accepted:

- the selected source folder;
- the discovered model name;
- the monotonic start value;
- the UTC start timestamp.

Later edits or operation cleanup must not change that snapshot.

Map `ScanSummary.state` as follows:

- `ScanState.COMPLETED` -> `completed`;
- `ScanState.COMPLETED_WITH_SKIPS` -> `completed_with_skips`;
- `ScanState.CANCELLED` -> `cancelled`;
- `ScanState.FAILED` -> `failed`.

Use `failed` with unavailable counts for `ScanError`, an unexpected exception,
or a non-`ScanSummary` result. Use `cancelled` with unavailable counts when a
close request records the attempt before a summary is available.

Append history exactly once before normal final scan rendering. Track an
explicit per-attempt recorded flag. A retry is a new attempt and creates a new
record even when it uses the same folder and model.

## Duration Formatting

`format_scan_duration` accepts only a nonnegative integer millisecond value.
Reject booleans, negative values, strings, floats, and `None` with `ValueError`.

Use floor division so the display never claims more elapsed whole seconds than
were measured:

- `0` through `999` -> `<1 sec`;
- `1000` through `59999` -> `<seconds> sec`;
- `60000` through `3599999` -> `<minutes> min <remaining seconds> sec`;
- `3600000` and above -> `<hours> hr <remaining minutes> min <remaining seconds> sec`.

Do not add leading zeroes. Keep zero remainder units in minute and hour forms,
for example `1 min 0 sec` and `1 hr 0 min 0 sec`.

## Scan History Dialog

Add a **Scan History** secondary button in the source-folder control area. Keep
the current visual language and do not redesign the main window.

Selecting it opens a modal dialog titled `Scan History`. The dialog must:

- explain `Saved locally. Source folder paths and model names are included.`;
- load current records each time it opens;
- show newest records first;
- use a table with these columns in this exact order: `Started (UTC)`, `Source
  folder`, `Model`, `Result`, `Duration`, and `Counts`;
- display the stored UTC value without silently converting time zones;
- map outcomes to `Completed`, `Completed with skips`, `Cancelled`, or `Failed`;
- format duration only through `format_scan_duration`;
- show counts as `N discovered, N analyzed, N candidates, N ordinary, N
  uncertain, N failed, N unreadable folders`;
- show `Counts unavailable` when any count field is `None`;
- make cells read-only and allow text selection;
- stretch the source-folder column and permit horizontal scrolling for other
  content;
- show `No scan history has been saved.` when there are no valid records;
- disable **Clear History** when there are no records;
- include **Clear History** and **Close** buttons.

When **Clear History** is selected, show a question titled `Clear scan history?`
with text stating that all saved scan timing records will be removed. Offer Yes
and No and default to No.

- No or closing the question changes nothing.
- Yes calls `clear_scan_history`.
- Success empties the table immediately, shows the empty state, and disables
  **Clear History** without closing the dialog.
- Failure retains all rows and shows `Scan history could not be cleared.` Do not
  display a raw exception.

The main-window history button is available when idle, even when no source
folder, server, quarantine folder, or history record exists. Disable it whenever
`self._thread` is not `None`.

## Detailed Test Coverage First

### 1. Baseline and Worktree Inspection

Before adding tests or production code:

1. Run `git status --short --branch` and inspect existing user files. Do not
   delete or modify `quar-test/` or any unrelated untracked data.
2. Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
3. Record pass, skip, warning, and duration results in this file's Status
   section.
4. Stop and report any baseline failure. Do not hide it by changing unrelated
   production code or tests.
5. Confirm the autouse network-blocking fixture remains active.

### 2. Duration Formatter Tests

Add `tests/test_scan_history.py` before creating the production module.

Cover exact values:

- `0`, `1`, `998`, and `999` milliseconds;
- `1000`, `1001`, `1999`, and `59999`;
- `60000`, `60001`, `61000`, and `3599999`;
- `3600000`, `3601000`, and a value greater than 24 hours;
- a very large valid integer;
- negative integers;
- `True`, `False`, float, string, empty string, and `None`.

Assert exact output strings and exact `ValueError` behavior. Run the focused
test and verify it fails because `scan_history.py` does not exist.

### 3. History Model and Parser Tests

Write these tests before implementing persistence:

- Construct a complete valid record for every outcome.
- Accept zero for duration and all counts.
- Reject blank timestamp, source folder, or model.
- Reject a timestamp without `Z` and invalid ISO date/time text.
- Reject relative and blank source-folder text. Use platform-appropriate
  absolute paths in tests.
- Reject unknown outcomes.
- Reject negative duration or counts.
- Reject booleans as numeric values.
- Accept all count fields as `None` together.
- Reject a mixture of integer and `None` count fields.
- Missing key returns an empty tuple.
- Store read failure returns an empty tuple.
- Blank text, malformed JSON, JSON scalar, JSON list, and wrong top-level keys
  return empty.
- Unsupported, missing, string, boolean, and negative schema versions return
  empty.
- Non-list records return empty.
- Missing, extra, or invalid record fields cause only that record to be omitted.
- A mixture of valid and invalid records retains valid records in original
  order.
- More than 100 valid external records returns only the newest 100.
- Unicode folder and model text round-trips.
- Windows drive and UNC-style absolute source paths are covered without making
  Linux tests depend on those paths being present.

### 4. Append and Clear Tests

Write these tests before implementing mutation functions:

- Append to a missing key.
- Append to an empty valid payload.
- Preserve old valid records and append in oldest-to-newest order.
- Repair blank, malformed, unsupported, and wholly invalid prior data by saving
  only the new record.
- Preserve valid records from a partly malformed supported payload.
- Appending record 101 drops only the oldest record.
- Repeated appends always keep exactly the newest 100.
- Serialized output is compact valid JSON with the exact top-level and record
  keys.
- Serialization preserves Unicode without changing record values.
- Exactly one write occurs per successful append.
- Read failure returns `False` and performs no write.
- Write failure returns `False` and preserves the in-memory fake store's prior
  value.
- Invalid new records fail before store read or write.
- Clearing existing history deletes only `SCAN_HISTORY_KEY`.
- Clearing missing history succeeds.
- Delete failure returns `False`.
- Endpoint URL, endpoint model, and quarantine folder keys remain unchanged
  after append, repair, retention trimming, and clear.
- Serialized data contains none of the forbidden privacy fields or injected
  marker secrets.

Run all history tests and make them pass before editing the GUI.

### 5. Main Window Timing Tests

Extend `tests/test_window_server.py` before editing `window.py`. Inject fake
monotonic and UTC clocks through the `MainWindow` constructor.

- Declined consent does not read a start clock, start the timer, or write
  history.
- An ignored request without folder or valid model creates no timing state or
  history.
- Accepted consent snapshots folder, model, monotonic time, and UTC time before
  starting the worker.
- Initial live text contains the preparation state and `<1 sec`.
- A one-second timer tick updates preparation text without progress.
- Progress text includes exact done/total values and elapsed duration.
- Later timer ticks preserve the latest progress values.
- Cancellation text includes live elapsed duration and keeps increasing until
  completion.
- Connection and quarantine operations never start or display the scan timer.
- Worker completion stops the timer and stale timeout signals do not alter final
  status.
- A new retry resets elapsed time rather than continuing the prior duration.
- A negative fake-clock delta is clamped to zero.
- Existing worker generation protection rejects stale progress and timer state.

Use direct timer-event invocation or a controlled Qt wait. Do not make the test
suite sleep for real scan durations.

### 6. Final Status and Record Tests

Write exact tests for:

- completed summary;
- completed-with-skips summary;
- cancelled summary;
- failed summary;
- `ScanError`;
- unexpected private exception;
- invalid non-summary worker result;
- empty-folder completed summary;
- duration below one second, exactly one second, exactly one minute, and over an
  hour;
- history append success and failure.

For each case, assert the exact final status, outcome, duration, timestamp,
source-folder snapshot, model snapshot, and counts. Assert raw exceptions,
endpoint addresses, and private marker text do not appear in the status or
stored JSON.

Assert each accepted attempt writes exactly one record. Run two retries and
assert two ordered records with independent times. Selecting a new source folder
after a completed scan must preserve prior records and use the new path only for
the next attempt.

When append fails, assert candidate rows still render, scan controls recover,
and the final status includes `Scan history could not be saved.` exactly once.

### 7. Close and Cancellation Tests

Extend existing close tests before changing close behavior:

- Explicit Cancel waits for the summary and stores one cancelled record with
  summary counts.
- Closing during list preparation stores one cancelled record with unavailable
  counts.
- Closing during image analysis stores one cancelled record with unavailable
  counts.
- Repeated close events while the worker stops do not duplicate the record.
- A delayed succeeded, failed, finished, progress, or timer signal after close
  cannot append a second record or alter UI state.
- Close still cancels the active transport.
- Close still waits up to the current bounded interval and ignores the close
  event if the worker remains active.
- The window still closes automatically after the delayed worker finishes.
- History write failure during close does not expose an exception, hang, or
  prevent safe shutdown.
- Closing during quarantine does not create scan history.

### 8. History Dialog Tests

Add focused Qt tests before implementing the dialog:

- Main window has a **Scan History** button.
- The button is enabled at startup with no server, folder, or records.
- It is disabled during connection, scan, and quarantine operations and
  re-enabled afterward.
- Opening loads fresh history each time.
- Dialog title and local-storage disclosure are exact.
- Empty history shows the exact empty message and disabled clear button.
- Valid rows display newest first.
- Every exact column appears in the frozen order.
- UTC timestamp and source folder are unchanged.
- Outcome, duration, and counts use the frozen display formats.
- Unavailable counts display `Counts unavailable`.
- Unicode and long paths remain selectable and do not crash layout.
- Table cells cannot be edited.
- Closing the dialog changes no history.
- Selecting Clear opens the exact confirmation with No as default.
- Declining or closing confirmation changes nothing.
- Confirmed clear deletes only history, refreshes to empty state, and keeps the
  dialog open.
- Clear failure retains rows and shows only the fixed safe message.
- Endpoint and quarantine settings remain unchanged by dialog actions.
- Reopening after clear remains empty.

### 9. Regression, Privacy, and Artifact Tests

- Preserve exact existing scan counts and candidate rendering after adding final
  duration text.
- Preserve server consent, cancellation, retry, stale-generation, and safe-close
  tests.
- Preserve quarantine controls, move behavior, thumbnails, and move-log tests.
- Confirm no network calls occur in any new test.
- Confirm no test writes history outside injected in-memory stores or isolated
  temporary settings.
- Confirm no source image, folder entry, mode, timestamp, candidate checkbox, or
  quarantine record changes because timing/history is enabled.
- Search tracked files and test output for endpoint addresses, marker secrets,
  image data URLs, and raw private exceptions.
- Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
- Run `git diff --check`.
- Run `git status --short --ignored` and inspect generated artifacts.
- Do not add or commit `quar-test/`.

## Implementation Sequence

1. Obtain explicit user approval of this plan.
2. Record the baseline Git state and full-suite result in Status.
3. Add failing duration-format tests.
4. Add failing model, parsing, append, retention, clear, corruption, and privacy
   tests.
5. Run the focused tests and confirm failure because the module is absent.
6. Implement only the GUI-neutral `scan_history.py` contract.
7. Run all history tests and fix them before GUI changes.
8. Add failing timing and live-status GUI tests with injected clocks.
9. Add failing terminal-state, persistence-failure, retry, and close tests.
10. Run focused GUI tests and confirm the planned failures.
11. Add injected clocks and per-attempt timing state to `MainWindow`.
12. Add the one-second timer and centralized live scan-status rendering.
13. Add exact-once record creation for normal completion, failures, explicit
    cancellation, and close-triggered cancellation.
14. Run timing, scan, cancellation, and close tests.
15. Add failing history-dialog tests.
16. Implement the idle-only **Scan History** button and modal dialog.
17. Run dialog and settings regression tests.
18. Update `project-brief.md` and `README.md` to describe local path retention,
    the 100-record limit, duration meaning, and clear action.
19. Update this Status section with implemented files and focused-test results.
20. Run the complete offline suite, `git diff --check`, and privacy/artifact
    inspection.
21. Ask the user to complete the manual desktop checklist below.
22. Wait for the exact reply `Approved` or bug evidence.
23. Only after desktop approval ask whether to create a PR, commit, or push.

Do not delegate implementation until the failing tests exist. If delegating the
GUI-neutral module, give the agent the frozen schema, validation, repair,
retention, privacy, and return-value contracts. The main session retains
ownership of all tests, GUI integration, Git operations, and the full-suite
verdict.

## Expected Files

Planning and documentation:

- `feature.md`
- `roadmap.md`
- `project-brief.md`
- `README.md`

Production:

- `src/img_ai_filter/scan_history.py` (new)
- `src/img_ai_filter/window.py`

Tests:

- `tests/test_scan_history.py` (new)
- `tests/test_window.py`
- `tests/test_window_server.py`
- `tests/test_settings.py` only if existing settings-store contract coverage is
  the clearest place for a shared regression assertion

Do not add a database, filesystem history log, new runtime dependency, generic
analytics framework, or timing fields to `ScanSummary`. Timing is a desktop
attempt concern and includes failures for which no `ScanSummary` exists.

## Manual Desktop Acceptance Checklist

Use only disposable sample files. Keep a backup outside the selected source and
quarantine folders. The automated tests do not contact the live server.

1. Start KoboldCpp with a vision model and matching `mmproj`.
2. Launch `.venv/bin/python -m img_ai_filter`.
3. Select **Scan History** before scanning. Confirm the dialog opens and shows
   either prior F-006 records or `No scan history has been saved.`
4. Close the dialog, test the server connection, and select a disposable source
   folder containing several supported images.
5. Start a scan and accept transfer. Confirm preparation status immediately
   shows elapsed time.
6. Confirm image progress and elapsed time update while the scan runs.
7. Confirm **Scan History** is disabled until the scan ends.
8. Let the scan finish. Confirm the final status contains the normal counts and
   a plausible final duration.
9. Open **Scan History**. Confirm the newest row contains the UTC start time,
   exact source-folder path, model, outcome, duration, and counts.
10. Close and reopen the application. Confirm the same history row remains.
11. Start another scan, wait briefly, then select Cancel. Confirm the final
    status and newest history row both show cancellation and a plausible
    duration.
12. Start another scan and close the app while it is running. Reopen the app and
    confirm exactly one new cancelled row exists with `Counts unavailable`.
13. Confirm no endpoint address, image name, candidate reason, or image content
    appears in the history dialog.
14. Select **Clear History**, then decline. Confirm all rows remain.
15. Select **Clear History** again and confirm. Confirm the dialog stays open,
    shows the empty message, and disables its clear button.
16. Restart the application and confirm history remains empty.
17. Run one final scan and confirm scanning, thumbnails, candidate checkboxes,
    and quarantine moving still work normally.

Reply `Approved` if every step passes. Otherwise provide the error text, a
screenshot, and the number of the failed step.

## Acceptance Criteria

- Every accepted scan attempt has one measured duration.
- Live elapsed time remains responsive without blocking scanning.
- Every normal terminal state displays and stores the final duration.
- Worker failures and close-triggered cancellation are recorded safely.
- No attempt is duplicated by retries, close events, or stale signals.
- The newest 100 records persist across launches and older records are removed.
- The history dialog accurately shows records and can clear them after explicit
  confirmation.
- Corrupt history cannot crash startup, scanning, or the dialog.
- History-storage failures do not change scan results or source files.
- Stored history includes source folder and model but excludes endpoint and
  image-level private data.
- Existing scan, cancellation, quarantine, and privacy behavior remains intact.
- The complete automated suite passes with networking blocked.
- The user approves the desktop checklist before any Git operation is proposed.

## Explicitly Deferred

- Per-image inference timing.
- Average, median, percentile, trend, or model-comparison charts.
- Exporting scan history.
- Filtering, sorting, searching, or deleting individual history records.
- Configurable retention limits.
- Pausing or resuming scans.
- Persisting live progress after a crash or forced process termination.
- Recording endpoint addresses, candidate paths, image names, or reasons.
- Uploading analytics or telemetry.
- Adding timing to connection tests or quarantine moves.

---

## Bug context (documented by document-bug)

### Bug summary

The uncommitted F-006 implementation works for scan timing and scan history, but
the user found during desktop testing that **Scan History** does not record
quarantine activity. This makes the history incomplete: a scan can be reviewed
later, but there is no in-app record showing which checked files were moved,
which destinations conflicted, which moves failed, or how long the quarantine
batch took. The quarantine backend already writes authoritative per-file events
to `.img-ai-filter-moves.jsonl`, but `ScanHistoryRecord` and
`ScanHistoryDialog` are scan-only and never consume a `QuarantineSummary`.

The user approved this expansion:

- history covers scan attempts and confirmed quarantine move batches only;
- each quarantine batch is one top-level event with expandable per-file details;
- scan and quarantine events share one newest-100 combined retention limit;
- quarantine elapsed duration is recorded and shown;
- exact source and destination paths are stored locally for quarantine files;
- clearing app history does not delete `.img-ai-filter-moves.jsonl`;
- connection tests, folder selections, declined consent, declined move
  confirmation, and other user actions are not history events.

The original scan-only plan above is retained as implementation history. This
handoff amendment supersedes every statement above that says quarantine records
or quarantine timing are excluded, that the dialog is named **Scan History**,
or that schema version 1 is the final schema.

### Investigation log

- Implemented scan-only history in
  `src/img_ai_filter/scan_history.py:45-191` with strict
  `ScanHistoryRecord`, version-1 JSON parsing, newest-100 retention, clear, and
  duration formatting. The module is GUI-neutral and all current unit tests
  pass.
- Implemented the scan-only dialog in
  `src/img_ai_filter/window.py:116-217`. It has six scan columns and loads only
  `ScanHistoryRecord` values, so it has no representation for move batches or
  child file outcomes.
- Implemented exact-once scan recording in
  `src/img_ai_filter/window.py:817-872`. It maps `ScanSummary` to history and
  appends terminal elapsed time, but it is called only from `_finish_scan` and
  scan shutdown handling.
- Inspected quarantine startup in
  `src/img_ai_filter/window.py:969-1027`. A validated `QuarantinePlan` already
  provides ordered source and destination paths before confirmation. Timing and
  history snapshots must begin only after the user confirms the plan.
- Inspected quarantine completion in
  `src/img_ai_filter/window.py:1029-1072`. A valid `QuarantineSummary` already
  provides `batch_id`, quarantine root, ordered `MoveOutcome` values, batch
  state, and exact moved/conflict/failed counts. This is the correct source for
  a completed in-app history event.
- Inspected the backend contract in
  `src/img_ai_filter/quarantine.py:35-88`. `MoveStatus` is `MOVED`, `CONFLICT`,
  or `FAILED`; `QuarantineState` is `COMPLETED`,
  `COMPLETED_WITH_FAILURES`, or `FAILED`; every `MoveOutcome` contains source,
  destination, status, and a safe message.
- Confirmed that `.img-ai-filter-moves.jsonl` is a separate durable audit log
  written by the quarantine backend. App history must supplement it, not parse,
  replace, truncate, or delete it.
- Identified a shutdown edge case in
  `src/img_ai_filter/window.py:1074-1097`: closing sets `_closing`, increments
  the generation, waits for the non-cancellable quarantine worker, and can skip
  normal `_finish_quarantine` processing. The continuation must capture a
  finished worker result during shutdown so a confirmed move is recorded
  exactly once without guessing its outcome.
- No quarantine-history implementation or tests have been attempted. The only
  completed code is the scan-only F-006 baseline.

### Implementation progress

Completed and currently uncommitted:

- `src/img_ai_filter/scan_history.py` implements strict scan records, version-1
  persistence, retention, corruption handling, clear, and duration formatting.
- `src/img_ai_filter/window.py` implements injected clocks, live scan elapsed
  time, final scan duration, exact-once scan records, close-triggered cancelled
  scan records, and the scan-only history dialog.
- `tests/test_scan_history.py` contains 70 GUI-neutral tests.
- `tests/test_window_server.py` contains deterministic timing, persistence,
  dialog, clear, retry, failure, and close tests. Its local autouse fixture
  replaces `_QSettingsStore` so tests do not write real platform settings.
- `README.md`, `project-brief.md`, `roadmap.md`, and the original plan above
  describe the scan-only implementation.
- Automated baseline after the scan-only implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
776 passed, 4 skipped, 1 warning in 57.17s
```

- `git diff --check` passed after that run.
- The user manually confirmed the scan timing/history behavior works, then
  reported the missing quarantine records. Desktop approval is therefore not
  complete and no commit, push, or PR may occur yet.

Not started:

- mixed scan/quarantine schema version 2;
- version-1 record migration;
- quarantine batch timing and exact-once recording;
- expandable per-file move details;
- **Activity History** naming and privacy text;
- revised documentation, full-suite verification, and desktop acceptance.

### Approved combined activity-history contract

#### Naming and scope

- Rename the main-window button and dialog from **Scan History** to
  **Activity History**.
- Track only accepted scan attempts and confirmed quarantine batches.
- Do not record a scan when transfer consent is declined.
- Do not record a quarantine event when planning fails, no rows are checked,
  confirmation is declined/closed, or readiness rejects the request.
- Keep the newest 100 top-level events combined. Per-file quarantine children
  do not count toward the limit.
- Keep the persisted settings key value `scan_history` so the user's existing
  local scan records are discoverable without key migration or data loss.
- Rename the GUI-neutral module to `src/img_ai_filter/activity_history.py` and
  its unit test to `tests/test_activity_history.py` during implementation. Do
  not leave duplicate scan/activity modules.

#### Version-2 storage schema

Use one compact JSON object under the existing `scan_history` settings key:

```json
{"schema_version":2,"records":[{"type":"scan"},{"type":"quarantine"}]}
```

The abbreviated example shows only the discriminating field. Production JSON
must contain every exact field defined below. The top-level object contains
exactly `schema_version` and `records`.

Keep immutable, slotted `ScanHistoryRecord` with its existing fields and add a
serialized `type` value of `scan` in version 2. Existing scan behavior and field
validation remain unchanged.

Add immutable, slotted `QuarantineFileHistory` with exactly:

- `source`: nonblank absolute source-path text;
- `destination`: nonblank absolute destination-path text;
- `status`: `moved`, `conflict`, `failed`, or `unknown`;
- `message`: string; an empty string is valid.

Add immutable, slotted `QuarantineHistoryRecord` with exactly:

- `started_at_utc`: valid UTC ISO 8601 text ending in `Z`;
- `source_folder`: nonblank absolute source-root text;
- `quarantine_folder`: nonblank absolute quarantine-root text;
- `batch_id`: nonblank text;
- `outcome`: `completed`, `completed_with_failures`, or `failed`;
- `duration_ms`: nonnegative integer, never boolean;
- `moved`: nonnegative integer or `None`;
- `conflicts`: nonnegative integer or `None`;
- `failed`: nonnegative integer or `None`;
- `files`: nonempty ordered tuple of `QuarantineFileHistory`.

For a valid `QuarantineSummary`, all three counts are integers, equal their
corresponding child statuses, and sum to the number of files. No child has
`unknown` status.

For an unexpected worker exception or invalid non-summary result, all three
counts are `None`, `outcome` is `failed`, and every planned file is retained in
visible order with status `unknown` and this fixed message:

```text
Outcome unavailable. Check the quarantine move log.
```

Do not use partial GUI progress to claim a file outcome. Do not expose raw
exceptions.

Add a tagged union type for the two record classes and generic GUI-neutral
functions equivalent to:

- `load_activity_history(store) -> tuple[HistoryRecord, ...]`;
- `append_activity_history(store, record) -> bool`;
- `clear_activity_history(store) -> bool`;
- `format_duration(duration_ms) -> str`.

There are no external Python API consumers, so remove the old scan-specific
function names after updating application code and tests. Preserve persisted
version-1 data, not obsolete internal function aliases.

#### Version-1 compatibility

- Accept the exact version-1 schema implemented in the current
  `scan_history.py`.
- Convert each independently valid version-1 record to an in-memory
  `ScanHistoryRecord`.
- Preserve order and retain only the newest 100 valid records.
- Do not rewrite settings merely because history was viewed.
- On the next successful append of either event type, serialize all retained
  records as version 2 and include `type: scan` for migrated scan records.
- Invalid version-1 records remain independently skippable as they are now.
- Continue treating unsupported versions as empty repairable history on append.

#### Privacy and durability

Combined history intentionally stores exact source and destination file paths
for quarantine child rows. Update the disclosure accordingly.

Never store:

- endpoint URL, origin, host, or IP address;
- image bytes, thumbnails, data URLs, source hashes, or source identities;
- scan candidate paths, image names from scan-only results, categories, or
  reasons;
- server requests/responses, credentials, API keys, or raw exceptions;
- move-log JSON records or their SHA-256 values.

The per-file quarantine message must come only from a validated
`MoveOutcome.message` or the fixed unknown-outcome message. The existing move
backend already converts normal failures to safe messages.

Clearing Activity History deletes only the settings history key. It must not
open, modify, truncate, or delete `.img-ai-filter-moves.jsonl` in any quarantine
folder. Endpoint and quarantine-folder settings remain unchanged.

#### Quarantine timing and record creation

- Snapshot source root, quarantine root, ordered planned source/destination
  pairs, monotonic start, and UTC start immediately after move confirmation and
  before `_start_operation("quarantine", ...)`.
- Measure elapsed time with the existing injected monotonic clock and store
  integer milliseconds. Clamp negative deltas to zero. Clock failure falls back
  to zero duration and safe current UTC exactly as scan timing does.
- Do not add a live quarantine timer in this amendment. Existing
  `Moving: X of Y files processed.` progress remains unchanged.
- Append `Elapsed: <duration>.` to every terminal quarantine status.
- Append `Activity history could not be saved.` when persistence fails, without
  changing row reconciliation, move counts, move logs, or file outcomes.
- Map `QuarantineState.COMPLETED` to `completed`,
  `COMPLETED_WITH_FAILURES` to `completed_with_failures`, and `FAILED` to
  `failed`.
- A valid summary uses its authoritative `batch_id`, quarantine root, ordered
  outcomes, and counts.
- An unexpected exception or invalid result uses the pre-confirmation plan's
  batch ID and planned paths with unavailable outcomes.
- Track an explicit per-batch recorded flag. Every confirmed batch creates
  exactly one event, including retries using the same files.

#### Close during quarantine

Quarantine remains non-cancellable. Never record it as cancelled and never stop
or terminate the worker.

Extend `OperationThread` in `src/img_ai_filter/scan_worker.py` so it retains its
terminal `result` or `error` in addition to emitting existing signals. Set these
attributes inside `run()` before emitting. Do not expose a traceback or change
signal behavior.

When the window closes during quarantine:

- keep the existing bounded wait and ignored-close behavior;
- if the thread finishes during `closeEvent`, read its retained terminal value
  only after `wait()` confirms it stopped, record the batch exactly once, and
  then accept close;
- if the wait times out, ignore close; when the worker later finishes,
  `_operation_finished` must use the retained value to record the batch even
  though `_closing` makes normal UI completion stale, then schedule close;
- do not reconcile result rows or show dialogs while the window is closing;
- a history persistence failure must not prevent shutdown;
- delayed signals and repeated close events must not duplicate the record.

Add focused `OperationThread` tests for retained success/error values and do not
special-case quarantine logic inside the generic worker.

#### Activity History dialog

Replace `ScanHistoryDialog` with `ActivityHistoryDialog` and use a read-only
expandable `QTreeWidget`.

Use these columns in exact order:

```text
Type | Started (UTC) | Source | Model / Destination | Result | Duration | Counts / Message
```

Top-level scan rows:

- `Type`: `Scan`;
- `Source`: source folder;
- `Model / Destination`: model;
- existing scan result, duration, and count formatting remain unchanged;
- no child rows.

Top-level quarantine rows:

- `Type`: `Quarantine`;
- `Source`: source root;
- `Model / Destination`: quarantine root;
- `Result`: `Completed`, `Completed with failures`, or `Failed`;
- `Duration`: shared duration formatter;
- `Counts / Message`: `N moved, N conflicts, N failed`, or
  `Counts unavailable`.

Each quarantine child row:

- `Type`: `File`;
- `Started (UTC)`: empty;
- `Source`: exact source path;
- `Model / Destination`: exact destination path;
- `Result`: `Moved`, `Conflict`, `Failed`, or `Unknown`;
- `Duration`: empty;
- `Counts / Message`: safe message, which may be empty.

Show newest top-level events first while preserving file order inside each move
batch. Make paths selectable, keep rows non-editable, permit horizontal
scrolling, and let the user expand/collapse batches.

Use this exact disclosure:

```text
Saved locally. Scan source folders and model names are included. Quarantine records include exact source and destination file paths.
```

Use `No activity history has been saved.` for the empty state. Rename clear
confirmation to `Clear activity history?` and state that app history will be
removed but quarantine move-log files will remain. Default to No. On clear
failure show only `Activity history could not be cleared.`

#### Combined retention

- The limit of 100 applies to top-level scan and quarantine events in stored
  chronological order.
- Child file count does not affect retention.
- Appending event 101 removes only the oldest top-level event, regardless of
  type.
- Loading an externally oversized version-2 payload returns only the newest 100
  independently valid top-level events.

### Required test-first continuation

The next agent must own tests in the main session and must not implement first.

1. Run `git status --short --branch` and confirm all current F-006 files remain
   uncommitted. Do not modify or add `quar-test/`.
2. Run the full network-blocked baseline exactly:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

   Expected starting result is `776 passed, 4 skipped, 1 warning`. Record the
   actual result in this handoff before editing production code.
3. Replace/extend the GUI-neutral tests first. Cover strict quarantine file and
   batch models, exact version-2 fields, version-1 migration, mixed corruption,
   mixed append order, combined 100-event retention, Unicode/Windows paths,
   unavailable outcomes, count/status consistency, privacy exclusions, write
   failure, and clear behavior.
4. Run those tests and confirm failures against the scan-only module.
5. Rename and implement the GUI-neutral activity-history module. Run all focused
   storage tests before any Qt work.
6. Add failing `OperationThread` retained-result and retained-error tests. Then
   implement only the generic terminal-value retention.
7. Add failing quarantine integration tests for completed, partial, conflict,
   failed, invalid-result, unexpected-error, write-failure, retry, ordering,
   timing boundaries, and clock failures.
8. Add failing close-during-quarantine tests for fast completion within the
   wait, delayed completion after an ignored close, repeated close, exact-once
   persistence, no UI reconciliation while closing, and persistence failure.
9. Implement quarantine snapshots, timing, terminal status, exact-once records,
   and close handling in `window.py`. Preserve move safety and non-cancellation.
10. Replace scan-only dialog tests with mixed expandable tree tests. Cover exact
    columns/text, scan rows, quarantine parents/children, newest-first parent
    order, child order, empty state, clear decline/success/failure, long Unicode
    paths, and move-log preservation.
11. Implement **Activity History** and update main-window control-state tests.
12. Update `README.md`, `project-brief.md`, `roadmap.md`, and the Status section
    here to describe combined activity history and exact-path retention.
13. Run focused tests, then the full offline suite, `git diff --check`, worktree
    inspection, and privacy/artifact searches. Automated tests must never touch
    the real network or real platform settings.
14. Give the user a revised desktop checklist. Wait for explicit `Approved`
    before asking about commit, push, or PR.

### Revised desktop acceptance checklist

Use disposable sample files and keep backups outside both selected folders.

1. Launch `.venv/bin/python -m img_ai_filter` and open **Activity History**.
2. Confirm existing scan-only records from schema version 1 still appear.
3. Run a scan and confirm live/final scan timing and a new scan row still work.
4. Select a quarantine folder, check at least two candidates, confirm a move,
   and verify the final move status includes elapsed time.
5. Open **Activity History** and confirm the newest top-level row is a
   quarantine batch with correct roots, result, duration, and counts.
6. Expand it and confirm each source, destination, status, and message matches
   the completed move.
7. Cause a destination conflict in disposable data. Confirm a partial/failed
   batch and its child conflict are recorded without overwriting the destination.
8. Start a multi-file move and close the window. Reopen it and confirm exactly
   one accurate quarantine event exists.
9. Confirm scan and quarantine events share newest-first ordering.
10. Confirm the dialog stores no endpoint, image bytes, hash, candidate reason,
    credential, or raw exception.
11. Decline **Clear Activity History** and confirm all rows and move logs remain.
12. Confirm clear, verify app history becomes empty, and verify every existing
    `.img-ai-filter-moves.jsonl` remains unchanged.
13. Restart and confirm cleared app history stays empty.
14. Confirm scanning, thumbnails, review checkboxes, move conflicts, and
    quarantine safety still work.

Reply `Approved` only if every step passes. Otherwise provide the failed step,
error text, and screenshot.

### Current blocker

None. Desktop GUI approval was received on 2026-09-21. Final automated
verification completed with 798 passed, 4 skipped, and 1 expected Pillow
warning after the review follow-up tests were added.

### Next steps for next agent

1. Read this entire appended amendment before touching code. Treat it as the
   current authority where it conflicts with the scan-only plan above.
2. Inspect `git status` and preserve every current uncommitted F-006 change.
3. Do not touch the unrelated untracked `quar-test/` directory; it contains the
   user's manual quarantine data and move log.
4. Run the full baseline and record it.
5. Start with failing version-2/migration tests in the GUI-neutral history test
   file. Do not edit production history or GUI code until those failures are
   demonstrated.
6. PR #7 was opened after desktop approval. The user authorized the requested
   review follow-ups and merge without another review pass.
