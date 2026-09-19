# Feature Plan: Selection-Only Scan Boundary

## Status

Implementation and automated tests are complete. The user approved the desktop GUI check.

## Goal

Align the desktop application with the first part of the candidate-scan workflow without choosing a detector yet.

The application will let the user select a source folder without scanning it. **Scan Folder** will be disabled until a folder is selected and enabled after a folder is accepted. This change stops at that ready-to-scan boundary. It will not define or implement what happens when **Scan Folder** is selected.

Remove the rejected thumbnail-first prototype. Folder selection must not traverse the selected folder, decode images, generate thumbnails, or display image rows.

## Test Coverage First

Write these tests before application code. Run the new tests and confirm that they fail because the current application scans during folder selection or lacks the required Scan control.

### Initial State

- The window shows **Select Folder**.
- The window shows **Scan Folder**.
- **Scan Folder** is disabled and visibly unavailable before a folder is selected.
- The source-folder label says that no folder is selected.
- The status tells the user to select a folder.
- The result list is empty.
- Constructing and showing the window does not call the scanner.

### Accepted Folder

- Accepting a valid folder stores and displays the exact selected path.
- Accepting a folder enables **Scan Folder**.
- The status says that the folder is ready to scan; it must not claim that a scan completed.
- Accepting a folder does not call the scanner.
- Accepting a folder does not traverse nested directories.
- Accepting a folder does not decode images or create thumbnails.
- Accepting an empty folder has the same ready state as a folder containing files.
- Accepting a folder containing thousands of files does not inspect or display those files.
- The result list remains empty after selection.

Use scanner test doubles that fail immediately if called. File-content and large-folder tests may create representative directory entries, but they must not rely on personal files or external services.

### Cancellation

- Cancelling the first folder picker keeps **Scan Folder** disabled.
- Cancelling the first folder picker keeps the initial labels and empty results.
- Cancelling after a folder was accepted preserves the selected folder exactly.
- Cancelling after a folder was accepted keeps **Scan Folder** enabled.
- Cancellation does not call the scanner or clear existing state.

### Replacement And Boundary Paths

- Selecting a different folder replaces the displayed source path.
- Selecting a different folder clears any prior result rows and status from the old folder.
- The replacement folder is ready to scan and **Scan Folder** remains enabled.
- Selecting the filesystem root or another valid boundary path preserves the exact picker value without resolving or rewriting it.
- Long and Unicode folder paths are displayed without changing their values.
- A selected folder that disappears immediately after selection still reaches the ready state because validation and scanning are deferred.

### Invalid And Failure Paths

- An empty picker result is treated as cancellation, not as an error.
- Folder selection itself does not report image-read, nested-folder, or detector failures because it performs none of those operations.
- Existing picker exceptions are outside this change; the operating system dialog remains responsible for choosing a directory.
- No scan failure behavior is added because scan execution is deferred.

### Safety And Regression Coverage

- Folder selection does not create, modify, rename, move, or delete source files.
- The native directory-only picker remains in use.
- Reopening the picker starts at the most recently accepted folder.
- Existing platform-integration, scanner, and native-picker tests continue to pass where their behavior is unchanged.
- Thumbnail modules, thumbnail tests, preview injection, icon-grid setup, image metadata, and thumbnail README text are removed.
- No ordinary image paths or thumbnails appear as selection results.

## User-Visible State Model

| State | Select Folder | Scan Folder | Source label | Result area |
| --- | --- | --- | --- | --- |
| No folder | Enabled | Disabled | No folder selected | Empty |
| Folder ready | Enabled | Enabled | Exact selected path | Empty |
| Picker cancelled with no folder | Enabled | Disabled | No folder selected | Empty |
| Picker cancelled with active folder | Enabled | Enabled | Existing path | Preserved |
| Different folder accepted | Enabled | Enabled | New exact path | Cleared |

## Implementation Plan

1. Replace thumbnail-oriented window tests with failing selection-state tests.
2. Confirm the new tests fail for the expected current behavior.
3. Remove `src/img_ai_filter/preview.py` and `tests/test_preview.py`.
4. Remove preview loading, image decoding, thumbnail icons, checkboxes, image metadata, icon-grid settings, and thumbnail-specific styles from the main window.
5. Add a **Scan Folder** button beside or near **Select Folder**.
6. Initialize **Scan Folder** as disabled.
7. Change folder acceptance so it only stores and displays the exact folder path, clears stale results, sets a ready status, and enables **Scan Folder**.
8. Keep picker cancellation non-destructive.
9. Do not connect **Scan Folder** to discovery or candidate detection in this change.
10. Update the README so it describes folder selection as a separate, non-scanning action and does not claim thumbnails exist.
11. Run the complete automated test suite.
12. Ask the user to verify the initial, selected, cancelled, and replacement-folder states in the desktop GUI.

## Planned Files

- `feature.md`
- `src/img_ai_filter/window.py`
- `tests/test_window.py`
- `src/img_ai_filter/preview.py` (remove)
- `tests/test_preview.py` (remove)
- `README.md`

Do not alter `project-brief.md` or `roadmap.md` in this change. They already define the complete candidate-scan workflow and detector dependency.

## Deferred At The Ready-To-Scan Boundary

- The action performed when **Scan Folder** is selected.
- Supported-image discovery during an explicit scan.
- Synchronous or background scan execution.
- Progress reporting and busy-state controls.
- Screenshot and meme detection.
- Candidate confidence and reason values.
- Candidate-only result rows and review check states.
- Scan empty, partial-failure, and complete-failure behavior.
- Quarantine, move, restore, and delete actions.
- Thumbnails after useful candidate detection exists.

## Acceptance Criteria

- **Scan Folder** is disabled before a folder is selected.
- Accepting a folder enables **Scan Folder** without reading the folder contents.
- Selection shows the exact folder path and a ready-to-scan status.
- Selection never calls the scanner, decodes an image, or creates a thumbnail.
- No image rows appear because of folder selection.
- Cancellation preserves the full current state.
- Selecting a different folder clears stale result state without scanning.
- The thumbnail prototype and its documentation are removed.
- All automated tests pass.
- The user completes the desktop GUI check and replies with `Approved` before any Git operation is proposed.
