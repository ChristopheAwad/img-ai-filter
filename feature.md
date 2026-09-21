# F-004 and F-005: Safe Quarantine and Candidate Thumbnails

## Status

Implementation is complete and the full automated suite passes. The user
approved the desktop GUI checklist on 2026-09-20, and the feature shipped on
2026-09-20 (PR #6).

F-001 and F-003 shipped on 2026-09-20 in PR #5. This plan covers the next two
selected roadmap features:

- F-004 adds a safe quarantine workflow for checked candidates.
- F-005 adds compact thumbnails for flagged candidates.

Pre-feature baseline on `main` recorded 2026-09-20:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
545 passed, 2 skipped, 1 warning in 40.71s
```

Current full-suite result after implementation on 2026-09-20:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
681 passed, 4 skipped, 1 warning in 57.90s
```

Delivered so far: source identity and bounded in-memory thumbnails in
`image_payload.py`; extended `ScanCandidate` flow in `scan_workflow.py`; the
GUI-neutral `quarantine.py` planner/executor with durable JSONL move log;
persisted quarantine-folder settings; and the full quarantine and thumbnail
GUI in `window.py` (folder picker, readiness gating, confirmation, background
worker, progress, result reconciliation, thumbnails, and safe close behavior).
The manual desktop GUI checklist was approved by the user on 2026-09-20.

## Goals

1. Let the user select and remember a quarantine folder.
2. Move only the candidate rows that the user explicitly checks.
3. Show the exact count, quarantine destination, and selected files before any
   move starts.
4. Preserve each selected file's path relative to the source folder.
5. Never overwrite an existing quarantine file or directory.
6. Detect files that were changed or replaced after scanning and refuse to move
   them.
7. Support quarantine folders on a different filesystem with a verified copy,
   followed by source removal only after verification succeeds.
8. Write a durable local record of planned and completed or failed moves.
9. Show a compact preview beside every flagged candidate without writing a
   thumbnail to disk.
10. Preserve the existing candidate category, reason, confidence, and unchecked
    initial review state.

## Approved Product Decisions

- Preserve the source-relative directory tree below the quarantine folder.
- Skip and report destination conflicts. Never replace, merge, or suffix a
  conflicting name automatically.
- Permit cross-filesystem moves through verified copy and source removal.
- Remember the quarantine folder in normal application settings.
- Validate a remembered quarantine folder again at startup and immediately
  before each move batch.
- Write an append-only `.img-ai-filter-moves.jsonl` record in the quarantine
  root.
- Show compact previews with a maximum width and height of 96 pixels.
- Generate preview bytes in the scan worker. Create Qt image objects only on the
  GUI thread.
- Keep every candidate unchecked when scan results first appear.
- Keep failed or skipped move rows visible and checked so the user can inspect
  or retry them.
- Remove a row only after its source was removed successfully.
- Do not provide cancellation after a confirmed move batch starts. A partial
  move cannot be made reliably reversible by a Cancel button.
- Do not add deletion or restoration. Quarantine is a move to a user-selected
  folder, not permanent deletion.
- Do not persist review checkbox state across application launches.
- Do not add thumbnail files, caches, databases, or hidden files beside source
  images.

## Existing Contracts to Preserve

- Folder selection remains separate from scanning.
- A scan still requires a tested private-LAN or loopback KoboldCpp endpoint and
  explicit transfer consent.
- Scanning remains sequential and responsive in a background thread.
- Only screenshot, meme, social-post, reaction-image, comic, and image-macro
  candidates appear in results.
- Ordinary, uncertain, and failed analyses remain omitted and counted.
- Source discovery does not follow symbolic links or Windows junctions.
- Automated tests never use a real network connection.
- A new scan replaces previous candidates and checkbox states.
- Selecting a different source folder clears previous candidates.
- Closing during a server scan still cancels its active request safely.
- No source file is modified during discovery, image preparation,
  classification, or thumbnail generation.

## Frozen Data Contracts

### Source Identity

Add one immutable GUI-neutral source identity value with these fields:

- `byte_count`: the exact number of bytes read for classification.
- `sha256`: the lowercase 64-character SHA-256 digest of those exact bytes.

Compute the identity from the already bounded source bytes in
`image_payload.py`. Do not reopen the file only to compute the scan identity.
The move workflow must read and hash the current source again and require both
fields to match before it creates a destination file.

The digest is only a local file-change check. Do not display it in ordinary GUI
text or send it to KoboldCpp.

### Prepared Image

Extend the immutable prepared-image result with:

- the source identity;
- bounded PNG thumbnail bytes;
- the thumbnail width and height.

The existing request data URL, PNG byte count, width, and height remain
available and keep their current meaning.

### Scan Candidate

Extend each immutable `ScanCandidate` with:

- its source identity;
- its PNG thumbnail bytes;
- its thumbnail width and height.

The path, category, reason, confidence, and fixed `checked=False` contract stay
unchanged. The mutable review state continues to belong to the Qt result item.

Tests and fakes must construct complete candidates through one small test helper
instead of repeating binary thumbnail and identity values in every GUI test.

### Quarantine Plan

Add `src/img_ai_filter/quarantine.py`. Keep it free of PySide6 imports.

Use immutable values equivalent to:

- `QuarantineItem`: source path, source-relative path, destination path, and
  expected source identity.
- `QuarantinePlan`: canonical source root, canonical quarantine root, ordered
  items, and a unique batch identifier.
- `QuarantineOutcome`: source, destination, fixed status, and safe user-readable
  explanation.
- `QuarantineSummary`: batch identifier, ordered outcomes, moved count, failed
  count, conflict count, and overall state.

Use explicit states for completed, completed with failures, and failed before
any move. Do not infer state from free-form text.

The planner must preserve the order of checked rows. It must reject duplicate
source paths rather than silently execute a path twice.

## Destination Layout

For source root `/photos` and source `/photos/screens/one.png`, quarantine root
`/quarantine` produces:

```text
/quarantine/screens/one.png
```

Create missing relative parent directories below the selected quarantine root.
The quarantine root itself must already exist because it is selected with the
native existing-directory picker. Never create a missing remembered root
silently.

Do not place a dated batch directory between the quarantine root and the
relative path. The move log supplies the batch history.

## Move Record Format

Use this exact filename in the quarantine root:

```text
.img-ai-filter-moves.jsonl
```

Write UTF-8 JSON Lines. Each line is one compact JSON object and ends with one
newline. Each record contains only these fields:

- `schema_version`: integer `1`;
- `batch_id`: nonblank unique string;
- `timestamp_utc`: ISO 8601 UTC timestamp ending in `Z`;
- `event`: `planned`, `moved`, `conflict`, or `failed`;
- `source`: absolute source path string;
- `destination`: absolute destination path string;
- `sha256`: expected lowercase source digest;
- `message`: fixed safe explanation or an empty string.

Open the log in append mode, write one full line per operation, flush, and call
`os.fsync` before continuing. Serialize with standard-library `json`; do not
build JSON manually.

Before touching the first source, append and sync one `planned` record for every
item. If the log cannot be opened or all planned records cannot be made durable,
fail the batch without copying or removing any source.

After each item, append and sync its terminal event. If a terminal log write
fails after a file moved, stop processing later files and report a log failure.
The already durable `planned` record and destination preserve evidence of the
operation. Never attempt to move the destination back automatically.

Do not log image bytes, thumbnail bytes, classification reasons, server output,
credentials, or recognized image text.

## Safe Move Algorithm

Execute items one at a time in plan order.

For each item:

1. Revalidate both roots and their non-overlap.
2. Confirm the source path remains lexically and canonically below the selected
   source root.
3. Reject a symbolic link, Windows reparse point, directory, missing path, or
   unreadable source.
4. Read the source in bounded chunks, calculate SHA-256, and compare its byte
   count and digest with the scan identity.
5. If identity differs, record `failed`; do not create a destination.
6. Create missing destination parent directories below the canonical quarantine
   root. Revalidate every resulting parent and reject links or reparse points.
7. If the destination path already exists as any filesystem object, record
   `conflict`; do not open or alter it.
8. Create the destination with exclusive-create semantics so a concurrent file
   cannot be overwritten after the existence check.
9. Reopen or rewind the validated source, copy in bounded chunks, and calculate
   the copied digest and byte count while writing.
10. Flush and `os.fsync` the destination.
11. Require copied byte count and digest to equal the expected source identity.
12. Apply the source mode and timestamps to the destination. If metadata copy
    fails, treat the move as failed and retain the source.
13. Recheck the current source identity immediately before source removal. If it
    changed during copying, remove the incomplete destination when possible and
    retain the source.
14. Remove the source only after every prior step succeeds.
15. Sync the destination parent directory where the platform supports it.
16. Append and sync the terminal move-log record.

On an ordinary handled failure before source removal, close handles, remove the
new incomplete destination when possible, retain the source, append a `failed`
event, and continue with the next item.

If cleanup of an incomplete destination fails, retain the source and report the
destination as a partial file that needs manual attention. Later retries must
see it as a conflict and must not overwrite it.

If source removal fails after a complete verified destination exists, retain
both copies, report failure, and do not remove the destination. This is a safe
duplicate, not data loss.

Do not use `shutil.move`, because it can switch implicitly between rename and
copy/delete behavior. Do not use a plain rename that can replace an existing
destination on Unix.

## Path Safety Rules

Reject the quarantine selection or move plan when:

- the source root does not exist or is not a directory;
- the quarantine root does not exist or is not a directory;
- either root is a symbolic link or Windows reparse point;
- both roots identify the same directory;
- quarantine is inside source;
- source is inside quarantine;
- canonicalization fails;
- any selected source is outside the source root;
- two selected source paths are duplicates after platform path normalization;
- two items produce the same normalized destination;
- a relative path is empty, absolute, or contains `..` traversal;
- the move-log path is a directory, link, reparse point, or other unsafe object.

Use `Path.resolve`, `os.path.commonpath`, and `os.path.samefile` where applicable.
Handle different Windows drives without treating `ValueError` as safe overlap.
Extract and reuse the existing Windows reparse-point check from `scanner.py`
rather than copying platform detection into multiple modules.

## Thumbnail Behavior

- Create one thumbnail from the EXIF-corrected normalized Pillow image already
  used to create the server request.
- Fit the thumbnail inside 96 by 96 pixels while preserving aspect ratio.
- Never enlarge an image whose width and height already fit the limit.
- Use Pillow LANCZOS resampling when reducing size.
- Preserve transparency by using RGBA when needed; otherwise use RGB.
- Encode the preview as PNG in memory.
- Set a strict encoded thumbnail limit of 256 KiB.
- Keep current source input, decoded-pixel, and format checks.
- Never write a thumbnail or temporary transformed image to disk.
- A thumbnail encoding failure counts as image preparation failure for that
  image, because a displayed candidate must satisfy the new complete candidate
  contract.
- Only candidate thumbnail bytes survive in `ScanSummary`; ordinary and
  uncertain prepared images are released after classification.

In the GUI, set the result list icon size to 96 by 96 pixels. Decode the bounded
PNG bytes into `QPixmap` on the GUI thread after the scan completes. Do not make
Qt image or pixmap objects in `OperationThread`.

If a fake or malformed candidate contains invalid thumbnail bytes, keep the
candidate row and show a stable neutral placeholder instead of crashing or
discarding the candidate.

Keep the current application colors and typography. Do not redesign the entire
window. Increase row height only enough to fit the preview. Keep path, category,
reason, confidence, and checkbox visible. Add a tooltip with the full path and
classification details when the row text is clipped.

## Quarantine GUI Behavior

Add a `Quarantine folder` section below the source-folder controls and above the
status/results area. It contains:

- a selectable path label;
- a `Select Quarantine Folder` button;
- a `Move Checked to Quarantine` button.

Use the native `QFileDialog.getExistingDirectory` picker with
`ShowDirsOnly`. Reopen the picker at the remembered valid quarantine folder.
Closing the picker changes nothing.

Persist an accepted path under `quarantine_folder` in the existing settings
store. A stored missing, non-directory, linked, reparse-point, or overlapping
folder is not ready. Keep its value available for repair messaging, disable the
move action, and require a new valid selection.

Attach the complete `ScanCandidate` to each result item with
`Qt.ItemDataRole.UserRole`.
Never parse the visible `|`-separated text to obtain a path or candidate.

Enable `Move Checked to Quarantine` only when all are true:

- no background operation is active;
- a source folder is selected;
- a valid quarantine folder is selected;
- at least one current result item is checked.

Connect `results_list.itemChanged` to recalculate the action state. Programmatic
row creation and removal must not accidentally start an action.

When the move button is selected:

1. Snapshot the exact checked candidates in visible row order.
2. Build and validate a quarantine plan before showing confirmation.
3. If planning fails, show a safe specific error and change no files.
4. Show a confirmation dialog titled `Move checked files to quarantine?`.
5. State the exact selected count and canonical quarantine root.
6. Put the exact source and destination paths in the dialog's detailed text.
7. Default to `No`.
8. Closing or declining changes nothing and sends no work to a thread.
9. Accepting starts one background `quarantine` operation.
10. Disable server, source, quarantine, scan, result-checkbox, and move controls
    while it runs.
11. Keep Cancel disabled because the confirmed move batch is not cancellable.
12. Show progress as `Moving: X of Y files processed.` without image content.

After completion:

- remove only rows whose outcomes are `moved`;
- retain failed and conflict rows;
- leave retained rows checked;
- show moved, conflict, and failed counts;
- enable retry when checked rows remain and both folders are still valid;
- show the move-log location;
- keep the scan button available for a fresh rescan.

If the worker raises an unexpected exception, show a fixed safe failure message,
retain all rows and checkbox states, and allow retry. Never display raw exception
text that can expose unrelated filesystem paths.

Closing during quarantine waits for the current item and batch to finish. Do
not terminate the worker thread. If it does not finish within the existing
short close wait, ignore the close event and close automatically when the
operation completes.

## Test Coverage First

### 1. Planning and Regression Baseline

- Run `git status --short --branch` and record the worktree state.
- Run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` before tests are
  added and record pass, skip, warning, and duration results in this file.
- Confirm the existing scanner, payload, workflow, settings, worker, endpoint,
  connection, client, evaluation, and GUI tests pass unchanged.
- Keep the test autouse network block active.

### 2. Source Identity and Thumbnail Tests

Extend `tests/test_image_payload.py` or add `tests/test_thumbnail.py` before
changing production code.

- Assert SHA-256 and byte count match the exact original source bytes.
- Cover empty bytes, one byte, exact maximum input bytes, and one byte over the
  maximum using controlled fakes where allocating a large fixture is not useful.
- Cover PNG, JPEG, WebP, BMP, and TIFF.
- Cover `.jpg` and `.jpeg` independently.
- Cover palette, grayscale, RGB, and RGBA inputs.
- Cover transparent and opaque images.
- Cover EXIF rotations that swap width and height.
- Cover square, landscape, portrait, 1 by 1, 95, 96, and 97 pixel longest
  dimensions.
- Cover existing 1024 request-image boundary behavior at, below, and above the
  limit.
- Assert no thumbnail dimension exceeds 96.
- Assert aspect ratio is preserved within integer rounding.
- Assert images at or below 96 are not enlarged.
- Assert PNG thumbnail bytes decode successfully and match reported dimensions.
- Assert encoded thumbnail bytes are at or below 256 KiB.
- Force one byte over the thumbnail byte limit and assert a fixed preparation
  error.
- Cover malformed, empty, missing, directory, unsupported-extension,
  extension/content mismatch, symbolic-link, reparse-point where supported,
  oversized-pixel, oversized-byte, and decode failures.
- Cover thumbnail resize and encode failures through monkeypatched Pillow
  operations.
- Assert source content, mode, timestamps, name, location, and directory entries
  do not change after success or failure.
- Assert no temporary or thumbnail file appears on disk.
- Assert no PySide6 import is added to `image_payload.py`.

Run these tests and verify they fail because the identity and thumbnail contract
does not exist yet.

### 3. Scan Workflow Contract Tests

Update `tests/test_scan_workflow.py` before changing `scan_workflow.py`.

- Assert a candidate receives the exact identity and thumbnail data returned by
  preparation.
- Assert ordinary and uncertain decisions do not add thumbnail data to the
  summary.
- Assert candidate order remains scanner order.
- Assert every candidate still has `checked is False`.
- Assert preparation failure, including thumbnail failure, increments failed and
  scanning continues.
- Assert all-failure state remains failed.
- Assert cancellation before, during, and between images remains unchanged.
- Assert thumbnail bytes and digest are not included in summary status text or
  exception messages.
- Update all candidate fixtures explicitly; do not add permissive production
  defaults that hide missing identity data.

Run the focused tests and verify they fail for the missing fields and data flow.

### 4. Quarantine Path Validation Tests

Add `tests/test_quarantine.py` before adding `quarantine.py`.

- Accept two existing, separate, ordinary directory roots.
- Accept sibling roots and roots on different filesystems through injected
  filesystem operations.
- Reject empty and non-path input with fixed errors.
- Reject missing roots, files used as roots, unreadable roots, symbolic-link
  roots, and Windows reparse-point roots.
- Reject roots that are equal lexically, canonically, or through `samefile`.
- Reject quarantine inside source and source inside quarantine.
- Reject overlap through `..`, symbolic links, case normalization, or alternate
  path spelling.
- Cover filesystem roots, Windows drive roots, UNC-style paths where the tests
  can inject behavior, long paths, spaces, and Unicode.
- Reject candidate paths outside source, equal to source, missing, directories,
  links, and reparse points.
- Reject empty, absolute, and parent-traversing relative destinations.
- Reject duplicate source paths and duplicate normalized destinations.
- Assert valid destination paths preserve the complete source-relative tree.
- Assert planning is read-only and creates no destination directories or logs.

Run the tests and verify import or behavior failures occur because the module is
not implemented.

### 5. Move Record Tests

Write these tests before record implementation.

- Create a new UTF-8 JSON Lines log with mode appropriate for a user-owned local
  file.
- Append without removing valid existing records.
- Require every exact schema field and reject internal attempts to serialize
  extra image or server fields.
- Assert compact valid JSON and one newline per record.
- Assert UTC timestamps and unique nonblank batch identifiers.
- Assert planned records are flushed and synced before destination creation.
- Assert one planned record per item in plan order.
- Assert moved, conflict, and failed terminal events are recorded in outcome
  order.
- Reject a log path that is a directory, link, reparse point, or non-regular
  object.
- Cover missing permissions, open failure, short write, flush failure, fsync
  failure, and serialization failure.
- Assert initial planned-record failure leaves every source and destination
  unchanged.
- Assert terminal-record failure stops later items and leaves a durable planned
  event for the affected item.
- Assert records exclude thumbnail bytes, request data URLs, model output,
  credentials, and classification reasons.

### 6. Quarantine Execution Tests

Write these tests before execution implementation.

- Empty plans are rejected without opening the log.
- A one-item same-filesystem move succeeds.
- A one-item injected cross-filesystem move succeeds through copy and removal.
- Multiple items execute in visible row order.
- Relative subdirectories are created below quarantine only.
- Existing destination files, directories, broken links, and case-normalized
  collisions are conflicts and remain unchanged.
- A destination created between validation and exclusive open is not
  overwritten.
- Source byte count changed after scan is rejected.
- Source digest changed with the same byte count is rejected.
- Source changed during copy is rejected and retained.
- Source changed immediately before removal is rejected and retained.
- Source replaced by file, directory, symbolic link, or reparse point is
  rejected.
- Quarantine root replaced or made overlapping after planning is rejected.
- Destination parent replaced by a link during execution is rejected.
- Copy exact boundary chunk sizes and a final partial chunk.
- Cover source open/read failure, destination parent creation failure,
  exclusive-create failure, destination write failure, short write, flush
  failure, fsync failure, metadata-copy failure, verification mismatch, source
  revalidation failure, source removal failure, and cleanup failure.
- On every pre-removal failure, assert source bytes and metadata remain.
- On source-removal failure, assert the verified destination remains and the
  source remains.
- On successful removal, assert the destination bytes, digest, mode, and
  timestamps match the source.
- Failure on first, middle, and last item produces exact ordered outcomes and
  continues only where the contract permits.
- One conflict does not stop independent later items.
- One ordinary copy failure does not stop independent later items.
- Terminal log failure stops later items.
- Unexpected exceptions are converted to fixed safe errors at the public
  boundary.
- Error text does not expose raw OS messages, unrelated paths, source bytes, or
  digest values.
- No operation writes beside the source files.
- No operation contacts the network or imports PySide6.

### 7. Quarantine Settings Tests

Extend `tests/test_settings.py` before changing `settings.py`.

- Use the exact key `quarantine_folder`.
- Missing key returns unconfigured.
- Save and load a valid canonical existing directory.
- Stored empty text, missing directory, ordinary file, link, reparse point, and
  invalid path return needs-repair.
- Overlap validation uses the current selected source when one is available.
- Settings read failure returns needs-repair rather than crashing startup.
- Settings write failure does not invalidate an already selected in-memory
  folder, but the GUI reports that it was not remembered.
- Saving quarantine settings does not change endpoint settings.
- Clearing or repairing quarantine settings does not change endpoint settings.

### 8. Thumbnail GUI Tests

Extend `tests/test_window_server.py` before changing `window.py`.

- Set result icon size to exactly 96 by 96 device-independent pixels.
- A valid candidate thumbnail produces a non-null icon.
- Portrait, landscape, and transparent thumbnail icons render without changing
  the candidate details.
- Invalid thumbnail bytes produce the neutral placeholder and retain the row.
- Candidate path, category, reason, confidence, and unchecked state remain
  visible.
- Full details are available in a tooltip.
- Only candidate rows exist; ordinary and uncertain images have no rows.
- Qt pixmaps are created on the GUI thread, not in the scan worker.
- A large fake candidate set is added without network activity and the event
  loop remains responsive.
- Retrying a scan replaces old icons, rows, and checkbox states.
- Selecting a new source clears old icons and candidate objects.
- Closing after thumbnail rendering releases the window without a worker leak.

### 9. Quarantine GUI Tests

Add focused GUI tests before adding controls.

- Initial quarantine label clearly says no folder is selected when no valid
  setting exists.
- A valid remembered quarantine folder is displayed after startup.
- An invalid remembered folder shows repair text and leaves move disabled.
- The picker uses native existing-directory mode and opens at the remembered
  valid folder.
- Cancelling first and later quarantine selections preserves all prior state.
- Selecting source then overlapping quarantine is rejected.
- Selecting quarantine then overlapping source prevents move readiness.
- A valid selection is persisted under `quarantine_folder`.
- A persistence failure is reported without discarding the valid in-memory
  selection.
- Every row stores its exact complete candidate in `Qt.ItemDataRole.UserRole`.
- Checking one row enables Move only when both folders are valid and no worker
  is active.
- Unchecking the last checked row disables Move.
- No checked rows means no confirmation and no backend call.
- Confirmation includes exact count and canonical quarantine root.
- Confirmation detailed text includes every exact source and destination.
- Confirmation defaults to No.
- Declining or closing confirmation changes no files, rows, or states.
- Accepting sends only checked candidates in visible order.
- Unchecked candidates are never sent to the quarantine backend.
- During quarantine, server, source, quarantine, scan, row, and duplicate move
  controls are disabled.
- Cancel stays disabled during quarantine.
- The event loop remains responsive while a fake move blocks.
- Progress shows exact processed and total counts.
- Successful rows are removed and unchecked rows remain.
- Conflict and failed rows remain checked.
- Partial completion displays exact moved, conflict, and failed counts plus log
  path.
- Total pre-move failure retains every row and checked state.
- Unexpected worker exceptions display fixed safe text and allow retry.
- A new scan after moves replaces remaining rows normally.
- Stale completion from an older generation cannot alter a newer source or scan.
- Closing during a move waits safely and does not terminate the worker.
- Move and thumbnail additions do not regress connection, consent,
  cancellation, scan retry, or close-during-scan tests.

Replace the old assertion that the window has no quarantine action with positive
tests for the new safe action. Keep the assertion that no Delete action exists.

### 10. Privacy, Artifact, and Full Regression Tests

- Run the complete suite with `QT_QPA_PLATFORM=offscreen`.
- Confirm socket, DNS, and standard-library HTTP remain blocked in tests.
- Confirm no test accesses the live `192.168.0.239` server.
- Confirm source fixtures are unchanged after thumbnail and quarantine failures.
- Confirm generated move logs exist only in temporary test directories.
- Confirm no real image, thumbnail, move log, quarantine folder, model, report,
  API key, or credential is tracked.
- Run `git diff --check`.
- Run `git status --short --ignored` and inspect new ignored artifacts.
- Run `git ls-files sample-img evaluation` and inspect output.

## Implementation Sequence

1. Obtain explicit user approval of this plan.
2. Record baseline Git state and full-suite result in the Status section.
3. Write failing source-identity and thumbnail tests.
4. Run those focused tests and confirm intended failures.
5. Implement source identity and bounded thumbnail creation in
   `image_payload.py`.
6. Write failing scan-contract tests and confirm intended failures.
7. Extend `ScanCandidate` and pass identity/thumbnail data through
   `run_server_scan`.
8. Run payload and workflow tests, then the full suite.
9. Write all failing quarantine path, log, and execution tests.
10. Run them and confirm the module is missing or lacks required behavior.
11. Delegate only the GUI-neutral quarantine module implementation, with this
    complete contract and no ownership of tests, Git, or final integration.
12. Review the delegated diff line by line and integrate only compliant code.
13. Run quarantine tests and fix safety failures before GUI work.
14. Write failing quarantine-settings tests and confirm intended failures.
15. Implement the validated persisted quarantine-folder setting.
16. Write failing thumbnail GUI tests and confirm intended failures.
17. Render compact icons and bind exact candidates to rows.
18. Write failing quarantine GUI tests and confirm intended failures.
19. Add quarantine selection, readiness, confirmation, background operation,
    progress, and result reconciliation to `MainWindow`.
20. Run focused settings, payload, workflow, quarantine, and window tests.
21. Update `project-brief.md`, `README.md`, and durable roadmap descriptions to
    match implemented behavior.
22. Run the full offline suite and artifact/privacy inspection.
23. Ask the user to complete the manual desktop checklist below.
24. Wait for the exact reply `Approved` or bug evidence.
25. Only after GUI approval ask whether to create a PR, commit, or push.

## Expected Files

Planning and documentation:

- `feature.md`
- `roadmap.md`
- `project-brief.md`
- `README.md`

Production:

- `src/img_ai_filter/image_payload.py`
- `src/img_ai_filter/scan_workflow.py`
- `src/img_ai_filter/quarantine.py` (new)
- `src/img_ai_filter/settings.py`
- `src/img_ai_filter/window.py`
- `src/img_ai_filter/scanner.py` or one small filesystem-safety module to expose
  the existing reparse-point helper without importing GUI integration code

Tests:

- `tests/test_image_payload.py`
- `tests/test_scan_workflow.py`
- `tests/test_quarantine.py` (new)
- `tests/test_settings.py`
- `tests/test_window.py`
- `tests/test_window_server.py`
- `tests/test_scanner.py` or focused filesystem-safety tests if the shared helper
  changes

Do not add a separate thumbnail module unless tests show image-payload reuse
cannot keep the contract clear. Do not add a custom result-row widget unless a
plain icon-bearing `QListWidgetItem` cannot preserve readable details and check
behavior.

## Manual GUI Acceptance Checklist

Use only disposable sample files. Keep a separate backup outside both selected
folders. Automated tests do not contact the live server.

1. Create a source folder with two safe sample candidate images in different
   subfolders and one ordinary photo.
2. Create an empty quarantine folder on the same drive.
3. Start KoboldCpp with a vision model and matching `mmproj`.
4. Launch `.venv/bin/python -m img_ai_filter`.
5. Test the server connection and select the source folder.
6. Select the quarantine folder. Close and reopen the app once and confirm the
   quarantine path is remembered.
7. Scan with consent. Confirm only candidates appear and each has a compact,
   correctly oriented preview.
8. Confirm every candidate starts unchecked and still shows path, category,
   reason, and confidence.
9. Check one candidate. Confirm `Move Checked to Quarantine` becomes enabled.
10. Start the move, inspect the exact confirmation details, then decline.
    Confirm no file or move log changed.
11. Start it again and confirm. Confirm only the checked file moves and keeps
    its source-relative subfolder under quarantine.
12. Open `.img-ai-filter-moves.jsonl` and confirm planned and moved records exist
    for that file.
13. Confirm the moved row disappears and unchecked rows remain.
14. Put a different file at the next candidate's destination, check that
    candidate, and try again. Confirm the destination is not overwritten and
    the checked row remains with a conflict count.
15. Rescan a fresh disposable candidate, then modify its source bytes before
    moving it. Confirm the app refuses to move the changed file.
16. If a second drive or mounted filesystem is available, repeat with a new
    quarantine folder there. Confirm the copied destination matches the source
    before the source disappears.
17. Start a multi-file move and try to close the window. Confirm it waits safely
    and closes after the move finishes without a crash.
18. Confirm ordinary photos, unchecked candidates, and conflicted sources were
    not moved.

Reply `Approved` if every step passes. Otherwise provide the error text, a
screenshot, and the number of the failed step.

## Acceptance Criteria

- Every displayed candidate has a bounded, correctly oriented compact preview.
- Preview generation is in memory and does not block the GUI thread.
- The user explicitly checks every file selected for quarantine.
- The app confirms exact planned sources and destinations before moving.
- Quarantine and source roots cannot overlap.
- Existing destinations are never overwritten.
- Changed, replaced, linked, missing, or unreadable sources are never removed.
- Cross-filesystem moves verify complete destination bytes before source
  removal.
- Partial failures cannot cause silent data loss.
- A durable local move record explains planned and terminal outcomes.
- Successful rows disappear; failed and conflict rows remain checked.
- The quarantine folder is remembered and revalidated.
- Existing scan privacy, consent, cancellation, and candidate-only behavior
  remains intact.
- The full automated suite passes without network access.
- The user completes and approves the manual GUI checklist before any Git
  operation is proposed.

## Explicitly Deferred

- Permanent deletion.
- Automatic restoration from quarantine.
- Undo during or after a move batch.
- Automatic destination renaming or deduplication.
- Persisted checkbox state.
- Thumbnail disk cache or database.
- Full-screen image viewer and image editing.
- Parallel server inference.
- Public Internet vision providers.
- Final installers, signing, and distribution.
