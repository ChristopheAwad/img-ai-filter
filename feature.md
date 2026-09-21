# F-007: Candidate Bulk Selection

## Status

Approved by the user on 2026-09-21. Implementation in progress.

Baseline worktree and suite result before test changes:

```text
git status --short --branch
## main...origin/main
 M README.md
 M feature.md
 M project-brief.md
 M roadmap.md
?? quar-test/

QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
798 passed, 4 skipped, 1 warning in 56.98s
```

Implemented in:

- `src/img_ai_filter/window.py`: `selection_button`, `_selection_button_state`,
  `_toggle_selection`, and `_update_controls` integration.
- `tests/test_window_server.py`: 19 new bulk-selection tests.

Focused result after implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/test_window_server.py tests/test_window.py tests/test_scan_workflow.py \
  tests/test_quarantine.py tests/test_scan_worker.py -q
191 passed, 2 skipped
```

The user selected this reduced scope on 2026-09-21:

- add one bulk review button that switches between **Select All** and
  **Clear All**;
- keep every candidate unchecked when scan results first appear;
- do not implement confidence-based automatic selection in this feature;
- keep review state temporary and do not create local review labels.

## Goals

1. Let the user check every current candidate with one action.
2. Let the user clear every current candidate with the same control.
3. Keep the control synchronized with individual checkbox changes.
4. Preserve the current unchecked default for every new scan result.
5. Preserve quarantine confirmation and every existing file-safety check.
6. Make no network, filesystem, history, or settings change when selection
   changes.

## Frozen Product Decisions

- Add one button named `selection_button` in code and tests.
- Show **Select All** when at least one current candidate is unchecked.
- Show **Clear All** when every current candidate is checked.
- Selecting **Select All** checks every current candidate row.
- Selecting **Clear All** unchecks every current candidate row.
- A manual checkbox change updates the button text immediately.
- With zero rows, show **Select All** and disable the button.
- Disable the button while any connection, scan, or quarantine worker is active.
- Re-enable and recalculate the button after the operation finishes.
- A new scan clears prior rows and selections under the existing lifecycle.
- Every candidate from a completed scan starts unchecked, regardless of
  category or confidence.
- After quarantine removes successfully moved rows, calculate the button state
  from the rows that remain.
- Failed and conflicting quarantine rows retain their current checked states
  under the existing retry contract.
- Bulk selection changes only Qt row check states.
- Bulk selection never starts a scan or move, bypasses confirmation, edits a
  source file, writes history, writes settings, or sends a network request.
- **Move Checked to Quarantine** keeps its current readiness rules and becomes
  enabled only when the folder, overlap, idle, and checked-row conditions pass.
- Do not add selection persistence, a configurable threshold, filtering, or a
  second bulk-selection button.

## Existing Contracts To Preserve

- Folder selection does not start a scan.
- A scan requires a tested private-LAN or loopback KoboldCpp endpoint.
- Every scan requires explicit transfer consent.
- Scanning runs off the GUI thread and supports cancellation.
- Ordinary and uncertain results do not appear as candidate rows.
- Failed image analyses do not stop later images.
- Candidate previews stay in memory and are created off the GUI thread.
- Every displayed candidate initially has `Qt.CheckState.Unchecked`.
- A quarantine move requires explicitly checked rows and exact-path
  confirmation.
- Source identity is revalidated before a move.
- Existing destinations are never overwritten.
- Cross-filesystem copies are verified before source removal.
- Failed and conflicting move rows remain available for correction and retry.
- Activity history and quarantine move logs keep their current contracts.
- Automated tests never contact a network service.

## User Interface Contract

Add the button beside the candidate-results status area, directly above the
result list. Use the existing `secondaryButton` style and pointing-hand cursor.
The native button remains keyboard accessible.

Centralize button text and enabled-state calculation in the existing control
update path:

- zero rows: **Select All**, disabled;
- one or more rows with at least one unchecked: **Select All**, enabled while
  idle;
- one or more rows with all checked: **Clear All**, enabled while idle;
- any active worker: retain the correct text but disable the button.

On click, read the complete row state before changing any row:

- if every row is checked, uncheck every row;
- otherwise, check every row.

After the batch change, update all controls so the button label and quarantine
move readiness are correct. Qt can emit `itemChanged` once per changed row. The
implementation must remain correct if those signals run. Use signal blocking
only if focused tests show it is necessary; do not add a generic selection
model or new abstraction.

## Detailed Test Coverage First

### 1. Baseline And Worktree Inspection

Before writing tests:

1. Run `git status --short --branch`.
2. Preserve existing uncommitted planning and documentation changes.
3. Do not modify or add the unrelated untracked `quar-test/` directory.
4. Run the complete offline suite exactly:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

5. Record the pass, skip, warning, and duration result in this Status section.
6. Stop and report a baseline failure. Do not alter unrelated code to hide it.
7. Confirm `tests/conftest.py` still blocks sockets, DNS, and standard-library
   HTTP for the complete test run.

### 2. Initial And Empty-State Tests

Modify `tests/test_window_server.py` before production code. Add tests that
prove:

- `selection_button` exists at startup;
- its initial text is **Select All**;
- it is disabled when there are no candidate rows;
- a completed scan with no candidates leaves disabled **Select All**;
- a failed scan leaves disabled **Select All**;
- an invalid worker result leaves disabled **Select All**;
- a cancelled scan leaves disabled **Select All**;
- a worker exception leaves disabled **Select All**;
- every candidate still renders unchecked, including confidence `0.0`, `0.80`,
  a value above `0.80`, and `1.0`;
- candidate paths, categories, reasons, confidences, thumbnails, tooltips,
  source identities, and row order remain unchanged.

Retain or update the existing candidate-row test so it continues to assert the
unchecked default. Do not add or change a confidence threshold in
`scan_workflow.py`.

### 3. Bulk Button State And Interaction Tests

Add failing tests before implementing the button:

- one unchecked row enables **Select All**;
- mixed checked and unchecked rows enable **Select All**;
- all checked rows enable **Clear All**;
- selecting **Select All** checks every row and changes the text to
  **Clear All**;
- selecting **Clear All** unchecks every row and changes the text to
  **Select All**;
- manually checking the last unchecked row changes the text to **Clear All**;
- manually unchecking one row changes the text to **Select All**;
- a single-row list toggles correctly in both directions;
- repeated clicks preserve candidate count, order, and `UserRole` objects;
- the button remains usable without a quarantine folder;
- without a quarantine folder, the move button remains disabled after
  selecting all;
- with a valid quarantine folder, selecting all enables the move button;
- clearing all disables the move button;
- clicking the disabled empty control changes no state and raises no exception.

Use direct `pytest-qt` button interaction. Calling a private handler alone is
not sufficient proof of the user-facing behavior.

### 4. Busy-State And Lifecycle Tests

Extend existing operation tests before production changes:

- connection start disables selection and completion restores it without
  changing row checks;
- connection failure restores selection without changing row checks;
- scan start clears prior rows and disables selection;
- scan completion with rows restores enabled **Select All** and every new row
  starts unchecked;
- scan completion without rows leaves disabled **Select All**;
- scan cancellation leaves the correct empty-result state;
- scan retry uses only the new rows and does not retain old manual checks;
- quarantine start disables selection without changing row checks;
- quarantine completion with all selected rows moved leaves disabled
  **Select All**;
- partial move success removes moved rows and derives the label from remaining
  row states;
- conflicts and failures retain checked rows and show **Clear All** when every
  remaining row is checked;
- mixed remaining row states show **Select All**;
- a quarantine worker error preserves rows and restores selection behavior;
- stale worker signals cannot enable or relabel controls for a newer operation;
- safe-close behavior does not invoke bulk selection or mutate row states.

### 5. Quarantine Safety Tests

Add or retain assertions proving:

- quarantine receives only rows checked when the move is requested;
- **Select All** followed by clearing one row excludes that row from the plan;
- **Clear All** prevents a move request;
- confirmation still lists every exact selected source and destination;
- declining confirmation moves nothing and preserves row states;
- existing conflicts are never overwritten;
- successfully moved rows are removed;
- failed and conflicting rows remain available for retry;
- source identity validation remains active;
- source files are not changed merely by selecting or clearing rows.

### 6. Side-Effect And Privacy Tests

Use injected fake boundaries and temporary files to prove:

- selecting or clearing all makes no network request;
- selecting or clearing all writes no application setting;
- selecting or clearing all writes no activity-history record;
- selecting or clearing all writes no quarantine move-log event;
- selecting or clearing all creates, moves, edits, or deletes no source file;
- selecting or clearing all creates no thumbnail cache;
- no review state survives a rescan;
- no review state survives an application restart;
- no review-label key, file, model, or dialog is introduced.

Do not test network behavior with a live service. The autouse network blocker
must remain enabled.

### 7. Documentation Review

Update durable product text to match the reduced scope:

- `README.md` says candidates initially remain unchecked and describes the
  **Select All**/**Clear All** toggle;
- `project-brief.md` keeps candidates unchecked and describes optional bulk
  selection;
- `roadmap.md` adds F-007 with status `in progress`, scope, dependency graph,
  files, and implementation order;
- remove current claims that confidence above `0.80` automatically checks a
  candidate;
- preserve historical descriptions of already shipped behavior;
- preserve the decision to scrap local review labels;
- preserve the planned F-008 reliability pass and Milestone 6 ordering.

Do not describe the feature as shipped before desktop approval and the chosen
Git workflow complete.

### 8. Full Regression And Artifact Inspection

After focused tests pass:

1. Run focused GUI tests for selection, scan lifecycle, and quarantine
   reconciliation.
2. Run the complete suite:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

3. Run `git diff --check`.
4. Run `git status --short --ignored` and inspect generated artifacts.
5. Confirm no test contacted a network service.
6. Confirm `quar-test/` was not modified or added.
7. Review the complete diff for accidental changes to endpoint validation,
   scanning, activity history, confidence parsing, or quarantine safety.
8. Record focused and full-suite results in this Status section.

## Implementation Sequence

1. Obtain explicit user approval of this complete plan.
2. Inspect the worktree and record the network-blocked baseline.
3. Add failing initial, empty-result, and unchecked-default GUI tests.
4. Add failing button text, enabled-state, manual-change, and click tests.
5. Add failing connection, scan, retry, quarantine, stale-signal, and close
   transition tests.
6. Add failing side-effect and quarantine-selection tests where existing tests
   do not already prove the contracts.
7. Run the focused GUI tests and confirm each new test fails for the intended
   missing-button behavior.
8. Add `selection_button` beside the result status area using the existing
   secondary-button style.
9. Connect the button to one small bulk-selection handler.
10. Extend `_update_controls()` to set button text and enabled state from the
    current rows and active-operation state.
11. Keep `_finish_scan()` row initialization unchanged at unchecked.
12. Recalculate controls after result rendering, manual item changes, operation
    state changes, and quarantine row reconciliation through the existing
    control-update path.
13. Run focused GUI, scan, and quarantine tests until they pass.
14. Update `README.md`, `project-brief.md`, and `roadmap.md` to match only the
    implemented scope.
15. Run the complete offline suite, diff check, artifact inspection, and privacy
    review.
16. Ask the user to complete the desktop checklist below.
17. Wait for exact `Approved` or failure evidence.
18. Only after desktop approval ask whether to create a PR, commit, or push.

Do not delegate production implementation until the main session has written
and run the failing tests. The main session retains ownership of tests,
integration, Git operations, approval gates, and the full-suite verdict.

## Expected Files

Planning and durable documentation:

- `feature.md`
- `roadmap.md`
- `project-brief.md`
- `README.md`

Production:

- `src/img_ai_filter/window.py`

Tests:

- `tests/test_window_server.py`
- `tests/test_window.py` only if a general main-window control assertion belongs
  there more clearly

Do not modify `src/img_ai_filter/scan_workflow.py` for this feature. Do not add
a database, settings key, label file, runtime dependency, generic selection
model, confidence threshold, or persistent review-state layer.

## Manual Desktop Acceptance Checklist

Use disposable source and quarantine folders. Keep a backup outside both
folders. The automated suite does not contact a live KoboldCpp server.

1. Start KoboldCpp with a vision model and matching `mmproj`.
2. Launch `.venv/bin/python -m img_ai_filter`.
3. Confirm **Select All** is visible but disabled before candidate rows exist.
4. Test the server, select a disposable source folder, start a scan, and accept
   transfer.
5. While scanning, confirm **Select All** remains disabled.
6. After completion, confirm every candidate starts unchecked, regardless of
   displayed confidence.
7. Confirm **Select All** is enabled when candidate rows exist.
8. Select **Select All** and confirm every row becomes checked and the button
   changes to **Clear All**.
9. Select **Clear All** and confirm every row becomes unchecked and the button
   changes to **Select All**.
10. Change individual checkboxes and confirm the button says **Clear All** only
    when every row is checked.
11. Without a quarantine folder, confirm bulk selection works but the move
    button stays disabled.
12. Configure a disposable quarantine folder and confirm the move button is
    enabled only while at least one row is checked.
13. Select all, clear one row manually, request a move, and confirm the exact
    path list excludes the cleared row.
14. Decline that confirmation and confirm no file moves.
15. Confirm a move with disposable files and verify only checked files move.
16. If practical, create a destination conflict and confirm its row remains
    checked for retry while no destination is overwritten.
17. Run a new scan and confirm prior manual checks are discarded and every new
    candidate starts unchecked.
18. Open **Activity History** and confirm checkbox changes created no activity
    record; scans and confirmed moves still create records.
19. Restart the app and confirm no candidate review state is restored.

Reply `Approved` if every step passes. Otherwise provide the failed step, error
text, and a screenshot.

## Acceptance Criteria

- The bulk control accurately selects all, clears all, and follows manual edits.
- Every newly rendered candidate remains unchecked.
- Empty and busy states cannot mutate review selections.
- Rescans replace old selections with new unchecked rows.
- Existing move readiness and exact-path confirmation remain intact.
- Existing quarantine conflict, failure, retry, and source-safety behavior
  remains intact.
- Selection changes create no persisted labels, settings, history, or files.
- No confidence-based selection behavior is added.
- The complete automated suite passes with networking blocked.
- The user approves the desktop checklist before any Git operation is proposed.

## Explicitly Deferred

- Confidence-based automatic selection.
- Persisting review state.
- Recording local review labels or building a training dataset from checks.
- A configurable confidence threshold.
- Per-category thresholds.
- Sorting or filtering candidates by confidence or category.
- Selecting only visible or filtered rows.
- Automatically moving selected candidates.
- Skipping quarantine confirmation.
- F-008 reliability-audit implementation.
- Milestone 6 packaging, signing, and distribution.
