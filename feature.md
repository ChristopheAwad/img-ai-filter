# F-012 Candidate Review UI Reliability

## Status

Implemented with the complete automated suite passing. Desktop GUI confirmed by
the user. Approved for the pull-request workflow.

## Goal

Make the existing candidate-review workflow readable, keyboard-visible, explicit
about empty and blocked states, cancellable during connection tests, and accurate
after every update outcome. Keep the current visual language and all privacy and
file-safety rules.

## Scope

1. Replace each single-line candidate item with a structured row that shows the
   existing 96 by 96 preview, review checkbox, exact path, category, reason, and
   confidence in separate readable regions.
2. Allow long paths and reasons to wrap without creating horizontal scrolling.
3. Preserve candidate data on the `QListWidgetItem` so quarantine and bulk
   selection continue to use the current contracts.
4. Add a visible keyboard-focus treatment to the results list and secondary
   buttons.
5. Show a dedicated message when a successful scan has no candidates.
6. Show a persistent, actionable explanation when valid source and quarantine
   folders overlap or otherwise fail root validation.
7. Enable the existing Cancel button during a connection test and cancel both
   the operation event and active transport.
8. Replace temporary update progress text on every completed, declined,
   invalid, cancelled, and failed outcome.

## Non-Goals

- Do not redesign the full window or implement the `UI Backlog` in
  `roadmap.md`.
- Do not change detection, confidence thresholds, scan ordering, retries, or
  endpoint validation.
- Do not change which candidates start checked.
- Do not change quarantine planning, source identity checks, confirmation,
  move execution, or move logs.
- Do not write previews or thumbnails to disk.
- Do not add network access to tests. Use injected transports and operations.
- Do not change update metadata, download verification, installation, or
  restart security.
- Do not commit, push, or open a pull request before desktop approval.

## Test-First Plan

Write the tests below before implementation. Run each focused group and confirm
that it fails for the intended missing behavior, not because of test setup.

### 1. Candidate Row Content and Identity

File: `tests/test_window_server.py`

1. Complete a fake scan with one candidate containing a short path, category,
   reason, confidence, and valid thumbnail.
2. Assert the list item still stores the exact candidate in
   `Qt.ItemDataRole.UserRole`.
3. Assert the row exposes separate visible text for the path, category, reason,
   and rounded confidence.
4. Assert the row shows the in-memory preview and never creates a file.
5. Assert confidence at, below, and above the saved threshold produces the same
   check states as before.
6. Assert checking the row updates Select All/Clear All and quarantine
   readiness exactly as before.
7. Assert a row with invalid thumbnail bytes remains usable and shows all text.

Expected initial failure: candidates are rendered as one concatenated item text
instead of a structured row.

### 2. Long and Empty Candidate Fields

Files: `tests/test_window_server.py`, `tests/test_window.py`

1. Render a deeply nested path and a long reason at the minimum supported
   window width.
2. Assert the path and reason labels enable word wrapping.
3. Assert the results list and body do not require horizontal scrolling.
4. Assert the row receives enough height to show wrapped content.
5. Test an empty reason only if the candidate data contract permits it; if the
   contract rejects it, retain that validation and do not add UI fallback code.
6. Test the longest valid category and confidence boundary values.
7. Confirm resizing wider does not clip the checkbox, preview, or metadata.

### 3. Keyboard Focus

File: `tests/test_window.py`

1. Show the window and move focus to the results list with Qt focus APIs.
2. Assert the results list accepts keyboard focus.
3. Assert the stylesheet supplies a visible focus treatment instead of
   removing the outline without replacement.
4. Assert every secondary main-window button has a focus style.
5. Use keyboard input to toggle a current candidate and confirm its check state
   changes without a mouse.
6. Do not assert exact rendered pixel colors because platform rendering differs.

### 4. Successful Empty Results

File: `tests/test_window_server.py`

1. Complete a scan with zero candidates and nonzero ordinary images.
2. Assert the result list is empty and an explicit message says that no likely
   screenshots or memes were found.
3. Keep aggregate discovered, analyzed, ordinary, uncertain, failed, unreadable,
   and elapsed information visible.
4. Assert bulk selection and quarantine move stay disabled.
5. Start a later scan and assert the prior empty message is removed while busy.
6. Complete a later scan with candidates and assert candidate rows replace the
   empty state.
7. Confirm failed and cancelled scans do not claim that no candidates were
   found.

### 5. Quarantine Blocked-State Guidance

File: `tests/test_window_server.py`

1. Load or select valid non-overlapping source and quarantine folders and assert
   no warning is shown.
2. Select a new source that contains the saved quarantine folder.
3. Assert moving is disabled and the main window explains that the folders
   overlap and that a different quarantine folder must be selected.
4. Test the inverse containment case.
5. Test a quarantine folder that becomes missing after it was selected.
6. Assert malformed, missing, and permission-related validation messages are
   sanitized through the existing `QuarantineError` text.
7. Select a valid replacement and assert the warning clears and moving becomes
   available only when a candidate is checked.
8. Confirm invalid roots never reach plan construction or file movement.

### 6. Connection Cancellation

File: `tests/test_window_server.py`

1. Inject a blocking discovery operation and a transport with a recorded
   `cancel_active` call.
2. Start a connection test and assert the existing Cancel button is enabled.
3. Click Cancel and assert the cancellation event is set, `cancel_active` is
   called once, and the button becomes disabled while shutdown completes.
4. Assert no scan, update, quarantine, or second connection can start while the
   connection worker is stopping.
5. Finish with the normal cancellation exception and assert controls recover.
6. Test a transport without `cancel_active`; cancellation must remain safe.
7. Test a race where discovery completes as Cancel is clicked; show one valid
   final state and ignore stale worker signals.
8. Confirm closing the window still cancels an active connection request.

### 7. Update Status Completion

File: `tests/test_window_updates.py`

Cover each path with injected update operations and message-box responses:

1. No release: `Image Filter is up to date.`
2. Invalid release object: final status says update information could not be
   used.
3. Release available from a non-writable or non-AppImage launch: final status
   reports availability and that automatic installation is unavailable.
4. User declines download: final status reports that the update was not
   downloaded.
5. Invalid verified download: final status says the download could not be used.
6. User declines installation: remove the temporary download and report that
   installation was not started.
7. Invalid install result: final status says installation could not be verified.
8. User declines restart after successful installation: retain the existing
   installed status.
9. Cancellation and known failures: retain their safe final messages.
10. Unexpected failures: retain the generic safe final message.
11. After every terminal path, assert no status contains `Checking`,
    `Downloading`, `Installing`, or an ellipsis that implies active work.
12. Assert controls and menu actions recover after every terminal path.

### 8. Regression and Side-Effect Coverage

Files: `tests/test_window.py`, `tests/test_window_server.py`,
`tests/test_window_updates.py`

1. Rescanning clears prior row widgets, check states, and empty-state text.
2. Selecting a different source clears prior results as before.
3. Cancelling folder selection preserves current rows and review choices.
4. Select All and Clear All affect every structured row.
5. Quarantine confirmation receives the same exact candidate paths.
6. Move reconciliation removes successful rows and retains failed or conflict
   rows with the correct check states.
7. Scan history and quarantine history content remain unchanged.
8. No test opens a socket, resolves DNS, or accesses the public Internet.

## Implementation Tasks

1. Add the smallest reusable candidate-row widget or row-construction helper in
   `src/img_ai_filter/window.py`. Keep it in that module unless reuse is proven.
2. Use separate labels for path and reason, enable wrapping, and keep concise
   category/confidence metadata visually secondary.
3. Keep the `QListWidgetItem` as the owner of candidate data and check state.
   Synchronize any custom checkbox with the item state without duplicate event
   loops. Prefer the native item checkbox if it remains visible with the custom
   row widget.
4. Set each item size hint from the row's layout so wrapped text gets sufficient
   height after insertion and resizing.
5. Add one dedicated results empty-state label near or within the review area.
   Hide it in initial, busy, failure, cancellation, and candidate-present states.
6. Track the current quarantine-root validation message in `_update_controls`
   and show it near the quarantine controls. Clear it immediately when roots are
   valid or incomplete rather than unsafe.
7. Extend the existing cancel-button state to connection operations. Generalize
   the cancel handler name only if doing so improves clarity without broad
   churn.
8. Set the operation cancel event and call the active transport's optional
   `cancel_active` method for connection cancellation, matching scan shutdown.
9. Add explicit status assignment before every terminal return in update check,
   download, and install completion handlers.
10. Replace the results-list `outline: 0` rule with a visible focus border and
    add a matching focus rule for secondary buttons.
11. Keep colors within the current navy, blue-gray, white, and teal palette.
    Do not add gradients, decorative shadows, or new card containers.

## Verification

1. Run the focused GUI tests changed for F-012.
2. Run the complete suite with
   `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`.
3. Inspect the diff for accidental changes to privacy, endpoint, quarantine,
   update-verification, or history contracts.
4. Launch with `python -m img_ai_filter` after activating `.venv`.
5. Ask the user to verify a long candidate path, long reason, keyboard focus,
   empty scan, overlapping quarantine folder, cancelled connection test, and
   declined update actions at default and minimum window sizes.
6. Wait for an explicit `Approved` before asking about a commit, push, or PR.
