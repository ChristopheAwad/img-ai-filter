# F-009: Confidence-Based Candidate Selection

## Status

Plan written and approved by the user on 2026-09-21. Test-first implementation,
automated verification, and desktop GUI verification are complete. The user
approved the desktop checklist on 2026-09-21.

The worktree was clean before this plan was written:

```text
git status --short --branch
## main...origin/main
```

Approved baseline before test changes:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
828 passed, 4 skipped, 1 warning in 33.36s
```

The required failing settings and GUI tests were written and observed failing
before their production changes.

Focused verification after implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_settings.py tests/test_window_server.py tests/test_window.py \
  tests/test_scan_workflow.py tests/test_quarantine.py -q
287 passed, 2 skipped in 4.13s
```

Complete offline verification after implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
877 passed, 4 skipped, 1 warning in 59.38s

git diff --check
clean
```

## Purpose

Automatically check newly rendered candidates when their KoboldCpp-reported
confidence meets a user-configured high-confidence threshold. This reduces
repetitive review work while preserving manual review, exact-path quarantine
confirmation, and every existing file-safety check.

KoboldCpp confidence is model-reported and is not a calibrated probability.
The interface and documentation must call it confidence, must not claim that a
90% value guarantees 90% accuracy, and must not claim that automatic selection
makes a quarantine decision for the user.

## Goals

1. Check a new candidate automatically when its raw confidence is at or above
   the configured threshold.
2. Leave a new candidate unchecked when its raw confidence is below the
   configured threshold.
3. Use 90% as the default threshold.
4. Let the user configure an integer threshold from 50% through 100% in a
   separate settings dialog.
5. Persist a successfully saved threshold across application launches.
6. Apply a changed threshold only to candidates rendered by a later scan.
7. Preserve all manual checkbox changes in the current result list.
8. Preserve the existing **Select All**/**Clear All** behavior for mixed and
   fully checked result lists.
9. Preserve explicit quarantine confirmation and every source and destination
   safety check.

## Frozen Product Decisions

- Track this work as F-009 because existing durable documentation reserves
  F-008 for the reliability audit.
- Store the threshold as an integer percentage.
- The default is `90`.
- The minimum accepted value is `50`.
- The maximum accepted value is `100`.
- A candidate is automatically checked when
  `candidate.confidence >= threshold / 100`.
- Compare the original floating-point confidence value. Do not compare the
  rounded percentage displayed in the result row.
- The threshold boundary is inclusive. At 90%, confidence `0.9` is checked and
  confidence `0.899999` is unchecked.
- All candidate categories use the same threshold.
- Do not add per-category thresholds.
- Do not add an enable/disable checkbox. A user who wants the most conservative
  behavior can select 100%, but a candidate with confidence exactly `1.0` still
  starts checked.
- Add a visible **Settings** button near **Activity History**.
- The button opens a separate modal settings dialog.
- The dialog contains one integer percentage control labeled clearly as the
  automatic-selection confidence threshold.
- The dialog explains briefly that the threshold affects new scan results only.
- The dialog provides **Save** and **Cancel**.
- **Save** persists the value before updating the active in-memory threshold.
- **Cancel**, dialog rejection, and window-close rejection do not change or
  persist the threshold.
- If persistence fails, keep the dialog open, show a user-readable error, and
  retain the previously active threshold.
- Disable **Settings** while a connection test, scan, or quarantine worker is
  active. This prevents a threshold change during result production.
- A successfully saved threshold applies to the next scan result rendering. It
  does not recalculate check states in rows that already exist.
- A rescan replaces all prior rows under the existing lifecycle. New rows use
  the currently active threshold.
- Automatically checked candidates are only selected for review. They are not
  moved, copied, renamed, deleted, or logged as quarantine events until the user
  explicitly requests and confirms a quarantine operation.
- Keep **Move Checked to Quarantine** subject to the current valid source root,
  valid quarantine root, non-overlap, idle-state, checked-row, exact-path
  confirmation, source-identity, no-overwrite, and verified-copy contracts.
- Do not send the threshold to KoboldCpp and do not alter the vision prompt,
  response parser, candidate categories, scan summary, or activity-history
  schema.

## Existing Contracts To Preserve

- Selecting a source folder does not start a scan.
- Every scan requires a tested loopback or private-LAN KoboldCpp endpoint.
- Every scan requires explicit image-transfer consent.
- Network tests use injected fake transports; automated tests never contact a
  real network service.
- Scanning runs off the GUI thread, processes one image at a time, supports
  cancellation, and does not retry requests.
- Ordinary and uncertain classifications do not appear as candidate rows.
- Failed image analyses do not stop later images.
- Candidate previews remain bounded, in memory, and generated off the GUI
  thread.
- Result rows retain path, category, reason, confidence, thumbnail, tooltip,
  immutable source identity, and scan order.
- **Select All** checks every current candidate when any row is unchecked.
- **Clear All** unchecks every current candidate when all rows are checked.
- Manual row changes immediately update bulk-selection and move-button states.
- A quarantine move requires explicitly checked rows and exact-path
  confirmation.
- A source is revalidated against its scanned identity before a move.
- Existing destinations are never overwritten.
- Cross-filesystem copies are verified before source removal.
- Failed and conflicting rows remain available for correction and retry.
- Scan and quarantine activity history retains its current privacy rules.
- Review checkbox state remains temporary and is never restored after restart.
- No local review-label collection is added.

## Settings Data Contract

Add the following GUI-neutral settings contract in `settings.py`:

- key: `auto_select_confidence_percent`;
- default: integer `90`;
- valid stored form: a base-10 integer string from `50` through `100` inclusive;
- load result: the validated integer threshold plus enough status information
  for the caller to distinguish a valid stored value from a default used for a
  missing or invalid value;
- save input: an actual integer, with booleans rejected even though `bool` is an
  `int` subclass in Python;
- save result: success or failure without leaking raw storage exceptions to the
  interface.

Loading behavior:

- a missing key returns the default `90` and does not write to the store;
- valid `50`, `90`, and `100` values return those exact integers;
- leading or trailing whitespace is not accepted as a valid stored form;
- signs, decimal forms, exponent forms, empty text, and nonnumeric text are
  invalid;
- values below `50` or above `100` are invalid;
- malformed or out-of-range data returns the default `90` without raising;
- a settings-store read exception returns the default `90` without raising;
- loading never repairs, deletes, or overwrites a bad stored value implicitly.

Saving behavior:

- valid integer boundaries and interior values are written as canonical decimal
  strings;
- invalid types and out-of-range values are rejected before a store write;
- a store write exception returns failure without changing the active in-memory
  threshold;
- saving this key does not alter endpoint, quarantine, or activity-history keys.

Use the existing `DEFAULT_HIGH_CONFIDENCE_THRESHOLD` value of `0.9` as the
semantic source for the default where practical. Avoid two independently
maintained default values. Do not couple the production KoboldCpp scan to the
offline `DetectionResult.default_checked` field; the server workflow uses
`ScanCandidate.confidence` directly.

## User Interface Contract

Add a small `CandidateSelectionSettingsDialog` in `window.py` unless existing
code structure clearly requires a separate GUI module. Keep the change local and
do not introduce a general settings framework.

The dialog must:

- have a descriptive title such as **Settings**;
- show one labeled integer percentage control;
- constrain the control to `50` through `100`;
- initialize it from the active threshold supplied by `MainWindow`;
- show the `%` suffix;
- state that matching candidates from future scans start checked;
- state that existing review choices do not change;
- provide standard **Save** and **Cancel** buttons;
- make Save the accepting action and Cancel the rejecting action;
- expose the selected integer only after acceptance;
- remain keyboard accessible through native Qt controls;
- show a concise persistence error without raw exception text if saving fails;
- remain open after a persistence failure so the user can retry or cancel.

The main window must:

- load the threshold once during initialization;
- retain the active threshold as an integer percentage;
- add a **Settings** button near **Activity History** using the existing
  secondary-button visual language and pointing-hand cursor;
- disable **Settings** during any active worker operation;
- leave **Settings** enabled while idle regardless of folder, endpoint, result,
  or quarantine configuration;
- open the modal dialog with the active threshold;
- on Cancel, leave settings storage, active threshold, current rows, status
  text, and control states unchanged;
- on successful Save, update the active threshold without changing current row
  checks;
- avoid replacing the main scan status with a settings success message;
- use the newly active threshold when the next valid `ScanSummary` is rendered.

Result rendering must set each new item's initial check state exactly once:

- confidence below threshold: `Qt.CheckState.Unchecked`;
- confidence equal to threshold: `Qt.CheckState.Checked`;
- confidence above threshold: `Qt.CheckState.Checked`.

After all rows are rendered, the existing control update path must derive:

- **Select All** when at least one row is unchecked;
- **Clear All** when every row is checked;
- move-button readiness from whether any row is checked plus all existing
  quarantine readiness conditions.

## Detailed Test Coverage First

### 1. Baseline And Worktree Inspection

Before changing tests or production code:

1. Run `git status --short --branch`.
2. Preserve any unrelated user or agent changes that appeared after this plan.
3. Run the complete offline baseline exactly:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

4. Record pass, skip, warning, and duration results in this Status section.
5. If the baseline fails, report the failure and determine whether it is related
   before writing feature tests. Do not modify unrelated code to hide it.
6. Confirm `tests/conftest.py` still blocks sockets, DNS, and standard-library
   HTTP for the full test run.

### 2. Settings Load Tests

Write failing GUI-neutral tests in `tests/test_settings.py` before production
changes. Prove:

- the key string is exactly `auto_select_confidence_percent`;
- an absent key returns default `90` with missing/default status;
- absent loading performs no write or delete;
- stored `50`, `51`, `89`, `90`, `99`, and `100` load exactly;
- `49` and `101` fall back to `90` with invalid/default status;
- empty text and whitespace-only text fall back to `90`;
- ` 90`, `90 `, `+90`, `-90`, `090`, `90.0`, `9e1`, `nan`, `inf`, and ordinary
  words are handled according to the canonical integer-string rule above;
- non-string values returned by a fake store do not crash and fall back to `90`;
- store read exceptions do not crash and fall back to `90`;
- malformed loads do not repair, delete, or overwrite storage;
- threshold loading does not read or modify credentials;
- endpoint, quarantine, and history settings remain untouched.

The implementation agent must not loosen these cases by calling `int()` on
arbitrary strings. Validate canonical decimal text before conversion.

### 3. Settings Save Tests

Add failing tests proving:

- `50`, `90`, and `100` save as exact canonical strings;
- representative interior integers save correctly;
- `49`, `101`, negative integers, floats, numeric strings, `None`, and booleans
  are rejected before any write;
- a store write exception reports failure without raising;
- failed save does not alter other stored values;
- successful save changes only the threshold key;
- save then load round-trips the exact valid value;
- save does not change endpoint readiness, quarantine folder state, activity
  history, or credentials.

### 4. Settings Dialog Tests

Write failing `pytest-qt` tests in `tests/test_window_server.py`, or a focused
new GUI test file only if that is materially clearer. Prove:

- the main window exposes a visible **Settings** button while idle;
- the button is enabled at startup without a selected folder or tested endpoint;
- activating the button opens the modal dialog;
- the dialog starts at `90` when the setting is absent or invalid;
- a valid persisted value initializes the control exactly;
- the percentage control has minimum `50`, maximum `100`, and `%` suffix;
- the explanatory future-scan text is visible;
- Save and Cancel controls are visible and keyboard accessible;
- Cancel after editing writes nothing and preserves the active value;
- rejecting with the window close control behaves like Cancel;
- Save persists the selected value and updates the active threshold;
- a persistence failure shows a safe error, does not accept the dialog, and
  preserves the old active value;
- the persistence error does not include raw exception text or stored content;
- retrying Save after a transient failure can succeed;
- opening the dialog again shows the newly saved active value;
- no candidate rows are required to configure the threshold.

Use real Qt button interaction where practical. Do not prove the user-facing
contract only by calling a private handler.

### 5. Initial Auto-Selection Boundary Tests

Replace the F-007 assertion that every confidence starts unchecked with failing
tests for the new contract. Using valid `ScanCandidate` objects, prove at the
default 90% threshold:

- confidence `0.0` starts unchecked;
- confidence `0.5` starts unchecked;
- confidence `0.899999` starts unchecked;
- confidence exactly `0.9` starts checked;
- confidence `0.900001` starts checked;
- confidence exactly `1.0` starts checked.

Prove configured boundary behavior:

- at 50%, `0.499999` is unchecked and `0.5` is checked;
- at 100%, `0.999999` is unchecked and `1.0` is checked;
- at an interior threshold such as 73%, `0.729999` is unchecked and `0.73` is
  checked.

Prove raw-value behavior:

- choose a confidence below the threshold that rounds to the same whole percent
  shown in the row and confirm it remains unchecked;
- choose a confidence exactly at the threshold and confirm it is checked;
- retain the current whole-percent display unless a test demonstrates a user
  safety ambiguity requiring a separate approved product decision.

### 6. Mixed Rows And Bulk Selection Tests

Add or update failing tests proving:

- mixed below-threshold and above-threshold candidates preserve scan order;
- every row preserves its exact `ScanCandidate` object in `UserRole`;
- paths, categories, reasons, confidence text, thumbnails, and tooltips are
  unchanged;
- mixed initial states show enabled **Select All**;
- selecting **Select All** checks both automatically checked and initially
  unchecked rows and changes the control to **Clear All**;
- selecting **Clear All** unchecks all rows regardless of automatic origin;
- manually unchecking an automatically checked row works normally;
- manually checking a below-threshold row works normally;
- the bulk-control label always derives from current check states, not from
  confidence values;
- repeated bulk actions do not change candidate data, order, or count;
- automatic origin is not persisted and requires no extra row metadata.

### 7. Threshold Change Timing Tests

Add failing lifecycle tests proving:

- changing the threshold with current rows visible does not alter any current
  check state;
- current manual changes also remain untouched after Save;
- Cancel leaves current rows untouched;
- a failed Save leaves current rows and active behavior untouched;
- the next rescan clears prior rows under the existing lifecycle;
- newly rendered rows from that rescan use the new threshold;
- changing from 90% to 50% affects only later results;
- changing from 50% to 100% affects only later results;
- restarting the app loads the persisted threshold for later scan results;
- review check states themselves do not survive restart;
- a malformed persisted value after restart safely uses 90%.

### 8. Empty, Failure, And Cancellation Tests

Add or retain tests proving:

- a completed scan with no candidates has no selected rows and disables the bulk
  control;
- a failed scan creates no rows and performs no threshold-based action;
- an invalid worker result creates no rows;
- a cancelled scan creates no rows;
- a worker exception creates no rows;
- per-image analysis failures do not create phantom checked rows;
- ordinary and uncertain classifications remain omitted;
- a threshold-load failure does not prevent startup or scanning;
- a threshold-save failure does not prevent later scans using the old value;
- no private exception or model response appears in status or dialog text.

### 9. Busy State And Stale Signal Tests

Add or update tests proving:

- connection-test start disables **Settings** and completion restores it;
- connection failure restores **Settings**;
- scan start disables **Settings**;
- scan success, failure, and cancellation restore **Settings**;
- quarantine start disables **Settings**;
- quarantine success, partial failure, worker error, and cancellation/close paths
  restore or dispose controls correctly under existing behavior;
- disabled **Settings** cannot open a dialog or mutate the threshold;
- stale connection, scan, or quarantine worker signals cannot reopen, enable, or
  apply settings to a newer operation incorrectly;
- safe application close does not save an unaccepted dialog value or change row
  checks.

### 10. Quarantine Readiness And Safety Tests

Add or retain assertions proving:

- an automatically checked row does not enable moving without a valid
  quarantine folder;
- with valid non-overlapping roots, at least one automatically checked row
  enables **Move Checked to Quarantine** while idle;
- a list containing only below-threshold unchecked rows keeps move disabled;
- manually clearing all automatically checked rows disables move;
- manually checking a below-threshold row can enable move when all folder
  conditions pass;
- only rows checked when the move is requested enter the quarantine plan;
- confirmation lists every exact selected source and destination;
- declining confirmation moves nothing and preserves row checks;
- source identity is revalidated before any move;
- changed sources remain untouched and available for review;
- destination conflicts are never overwritten;
- cross-filesystem verification remains required before source removal;
- successfully moved rows are removed;
- failed and conflicting rows retain their current check states for retry;
- remaining-row bulk-control state is recalculated from check states, not from
  confidence.

### 11. Side-Effect And Privacy Tests

Use injected fake boundaries and temporary files to prove:

- loading, editing, saving, or cancelling the threshold sends no network
  request;
- automatic check initialization sends no network request beyond the scan's
  existing injected classification calls;
- changing checkbox state starts no scan or quarantine operation;
- automatic selection creates no activity-history event;
- threshold configuration does not alter existing activity-history records;
- automatic selection creates no quarantine move-log event;
- no source file is created, edited, renamed, moved, or deleted by threshold
  configuration or row initialization;
- no destination file or thumbnail cache is created;
- endpoint URL, model, credentials, image content, reasons, and paths are not
  stored with the threshold;
- current checkbox state is not added to settings;
- no review-label key, file, model, or dialog is introduced.

### 12. Documentation Tests And Review

Update durable product text after focused production tests pass:

- `README.md` explains the default 90% automatic-selection threshold, Settings
  control, next-scan timing, and model-reported-confidence limitation;
- `README.md` keeps manual review and exact quarantine confirmation explicit;
- `project-brief.md` changes the old all-unchecked decision to the approved
  threshold behavior without rewriting historical shipped records;
- `roadmap.md` keeps F-009 `in progress` until desktop approval and the selected
  Git workflow complete;
- historical F-007 text remains clear that all-unchecked was the contract of
  that shipped feature before F-009;
- F-008 remains reserved for the reliability audit;
- no document calls confidence a calibrated probability;
- no document claims automatic move, deletion, or model accuracy.

### 13. Focused Verification

After implementation, run at minimum:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_settings.py tests/test_window_server.py tests/test_window.py \
  tests/test_scan_workflow.py tests/test_quarantine.py -q
```

If a dedicated dialog test file is added, include it explicitly. Record pass,
skip, warning, and duration results in Status.

### 14. Full Regression And Artifact Inspection

After focused tests pass:

1. Run the complete suite:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

2. Run `git diff --check`.
3. Run `git status --short --ignored` and inspect generated artifacts.
4. Confirm no test contacted a network service.
5. Review the complete diff for accidental changes to endpoint validation,
   transfer consent, confidence parsing, scan summaries, activity history,
   quarantine planning, or file operations.
6. Confirm no persistent checkbox state, image data, candidate reason, or path
   was added to settings.
7. Record all verification results in Status.

## Implementation Sequence

1. Obtain explicit user approval of this complete plan.
2. Inspect the worktree and run the complete network-blocked baseline.
3. Add failing threshold load tests for missing, valid, invalid, boundary, and
   read-failure cases.
4. Add failing threshold save tests for valid, invalid, boundary, type, and
   write-failure cases.
5. Run those tests and confirm they fail because the settings contract is
   missing.
6. Implement the threshold key and minimal GUI-neutral load/save functions in
   `settings.py`.
7. Run the focused settings tests until they pass.
8. Add failing dialog structure, Save, Cancel, close, persistence-failure, and
   retry tests.
9. Add failing main-window Settings-button idle and busy-state tests.
10. Run those tests and confirm they fail for the intended missing UI behavior.
11. Implement the small settings dialog, Settings button, startup load, and
    successful-save state update.
12. Run the focused settings UI tests until they pass.
13. Replace the all-confidence-unchecked GUI test with failing default and
    configured threshold boundary tests.
14. Add failing raw-confidence, mixed-row, bulk-selection, and move-readiness
    tests.
15. Add failing next-scan-only, rescan, restart, failure, cancellation, busy,
    stale-signal, and side-effect tests.
16. Run all new GUI tests and confirm they fail because result rendering still
    initializes every row unchecked.
17. Change `_finish_scan()` to initialize each new row from raw confidence and
    the active integer threshold.
18. Keep the existing row data, display text, tooltip, thumbnail, ordering, and
    post-render control update behavior unchanged.
19. Run focused GUI, settings, scan, and quarantine tests until they pass.
20. Update `README.md`, `project-brief.md`, and `roadmap.md` to describe only the
    implemented behavior.
21. Run the full network-blocked suite, diff check, artifact inspection, and
    privacy review.
22. Ask the user to complete the manual desktop checklist below.
23. Wait for exact `Approved` or failure evidence.
24. Only after desktop approval ask whether to create a PR, commit, or push.

Do not delegate production implementation until the main session has written
and run the failing tests. The main session retains ownership of tests,
integration, Git operations, approval gates, and the complete-suite verdict.

## Expected Files

Planning and durable documentation:

- `feature.md`
- `roadmap.md`
- `project-brief.md`
- `README.md`

Production:

- `src/img_ai_filter/settings.py`
- `src/img_ai_filter/window.py`

Tests:

- `tests/test_settings.py`
- `tests/test_window_server.py`
- `tests/test_window.py` only if a general window-control assertion belongs
  there more clearly
- a new focused settings-dialog test file only if keeping those tests separate
  materially improves clarity

Do not modify `scan_workflow.py`, `vision_client.py`, `vision_response.py`,
`http_transport.py`, `quarantine.py`, or `activity_history.py` unless a failing
test demonstrates a contract defect directly required by F-009. Do not add a
runtime dependency, general settings framework, persistent review model,
per-category threshold, automatic move, or new network request.

## Manual Desktop Acceptance Checklist

Use disposable source and quarantine folders. Keep a backup outside both
folders. The automated suite never contacts a live KoboldCpp server.

1. Start KoboldCpp with a vision model and matching `mmproj`.
2. Launch the app with `.venv/bin/python -m img_ai_filter`.
3. Select **Settings** and confirm the threshold initially shows `90%`.
4. Select Cancel and reopen Settings; confirm the value remains `90%`.
5. Save `50%`, reopen Settings, and confirm it remains `50%`.
6. Test the KoboldCpp connection and select a disposable source folder that is
   likely to produce candidates with different confidence values.
7. Start a scan and approve transfer only if the displayed private-LAN or
   loopback destination is correct.
8. During scanning, confirm **Settings** is disabled.
9. After completion, confirm candidates at or above 50% start checked and lower
   candidates start unchecked.
10. Confirm no file moved and no quarantine confirmation opened automatically.
11. Change some checkboxes manually, open Settings, save `100%`, and confirm all
    current checkbox choices remain unchanged.
12. Run a new scan and confirm only candidates showing raw confidence exactly
    `1.0`, if any, start checked; manually verify that current rows were replaced.
13. Confirm **Select All** and **Clear All** still operate on every current row.
14. Configure a disposable non-overlapping quarantine folder and confirm move is
    enabled only while at least one row is checked.
15. Request a move and confirm every exact source and destination path is shown
    before any operation starts.
16. Decline confirmation and confirm no file moves and row checks remain.
17. If safe sample files are available, approve one disposable move and confirm
    only checked files move.
18. Restart the application, reopen Settings, and confirm `100%` persisted while
    no prior candidate rows or review checks were restored.
19. Open **Activity History** and confirm settings changes and checkbox changes
    did not create activity events.

Reply `Approved` if every step passes. Otherwise provide the failed step, error
text, and a screenshot.

## Acceptance Criteria

- Missing or invalid threshold settings safely use 90%.
- Valid integer values from 50% through 100% persist exactly.
- The dialog saves only on explicit Save and preserves state on Cancel or
  persistence failure.
- New candidates at or above the raw-confidence threshold start checked.
- New candidates below the threshold start unchecked.
- Changing the threshold never rewrites existing manual review choices.
- The next scan uses the new threshold and replaces old review state.
- Bulk selection remains correct for mixed, all-checked, and all-unchecked rows.
- Automatic selection never starts or bypasses quarantine confirmation.
- Every quarantine source and destination safety contract remains active.
- Settings and automatic selection create no network, filesystem, move-log, or
  activity-history side effects.
- No checkbox state or review label is persisted.
- Documentation describes confidence accurately and does not promise calibrated
  probability or model accuracy.
- The complete automated suite passes with networking blocked.
- The user approves the desktop checklist before any Git operation is proposed.

## Explicitly Deferred

- Calibrating confidence against a representative labeled dataset.
- Claiming a statistical probability or accuracy guarantee.
- Per-category thresholds.
- Decimal threshold input.
- A threshold below 50% or above 100%.
- A separate automatic-selection enable/disable toggle.
- Recalculating current rows when the threshold changes.
- Persisting manual review state.
- Recording local review labels.
- Sorting or filtering by confidence or category.
- Automatically starting quarantine.
- Skipping exact-path confirmation.
- Permanent deletion or automatic restoration.
- F-008 reliability-audit implementation.
- Milestone 6 packaging, signing, and distribution.
