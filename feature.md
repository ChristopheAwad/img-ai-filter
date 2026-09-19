# Feature Plan: Native Folder Picker

## Goal

Replace Qt's limited fallback folder dialog with the operating system's native folder picker when one is available. On the KDE development system, the picker must provide normal file-explorer navigation such as back, forward, parent-folder access, and KDE Places. The application must remain compatible with GNOME, Cinnamon, Windows, and macOS native dialogs.

The picker will reopen at the source folder most recently selected during the current application session. Scanning remains read-only and unchanged.

## Test Coverage First

Write these tests before application code. Run them and confirm that the new tests fail for the expected missing behavior before implementation starts.

### Platform Integration Tests

- On Linux with no existing Qt platform theme, select the XDG desktop portal integration.
- On Linux with an existing `QT_QPA_PLATFORMTHEME` value, preserve that value instead of overriding the user's desktop configuration.
- On Windows, do not add a Linux platform-theme setting.
- On macOS, do not add a Linux platform-theme setting.
- Treat Linux platform identifiers such as `linux` and `linux2` as Linux.
- Keep unrelated environment values unchanged.

These tests must use an isolated environment mapping. They must not modify the test process's real desktop environment.

### Folder Picker GUI Tests

- The first picker opening has no application-selected starting folder, allowing the native dialog to choose its normal default.
- After a successful folder selection, opening the picker again starts in that selected folder.
- A selected empty folder becomes the remembered starting folder even when no images are found.
- A selected folder remains remembered when scanning it fails.
- Cancelling the first picker does not set a remembered folder or start a scan.
- Cancelling a later picker keeps the prior folder, results, status, and remembered starting folder unchanged.
- Selecting the filesystem root or another valid boundary folder passes that exact path to the scanner without path rewriting.
- Folder selection continues to use directory-only mode and does not enable Qt's `DontUseNativeDialog` option.
- Existing empty-result, supported-image, replacement-scan, unreadable-folder, and no-destructive-action tests continue to pass.

Native dialog chrome and operating-system pinned locations cannot be reliably inspected by headless automated tests. Verify them with the manual GUI check below.

## Implementation Plan

1. Add a small platform-integration function that accepts a platform name and environment mapping so its behavior can be tested without changing the real test environment.
2. On Linux only, set `QT_QPA_PLATFORMTHEME` to `xdgdesktopportal` when the user has not already selected a Qt platform theme.
3. Call the integration function before importing or initializing PySide6 in the application entry point.
4. Keep `QFileDialog` in native mode. Do not set `DontUseNativeDialog` and do not build a custom file explorer.
5. Explicitly request directory-only selection.
6. Store the last accepted source folder in the main window for the lifetime of that window.
7. Pass the stored folder back to the next native picker as its starting location.
8. Keep cancellation non-destructive and preserve all current scan behavior.
9. Update the README to describe the native picker and session-only starting-folder behavior.
10. Run the complete automated test suite.

## Planned Files

- `feature.md`
- `src/img_ai_filter/platform_integration.py`
- `src/img_ai_filter/__main__.py`
- `src/img_ai_filter/window.py`
- `tests/test_platform_integration.py`
- `tests/test_window.py`
- `README.md`

Exact file names can change if tests show that a smaller structure is clearer.

## Platform Behavior

- KDE Plasma: use the XDG portal, which should open KDE's native folder picker and KDE Places.
- GNOME and Cinnamon: use the user's configured XDG portal backend or preserve an existing Qt platform-theme choice.
- Windows: allow Qt to use the native Windows folder dialog.
- macOS: allow Qt to use the native macOS folder dialog.
- Linux without a working portal: Qt can fall back to its available dialog. Do not make folder selection fail only because native integration is unavailable.

Pinned folders and navigation controls belong to the operating system's picker. The application will not maintain a second, conflicting set of bookmarks.

## Boundaries

Included:

- Native folder-dialog integration.
- KDE-first manual verification.
- Cross-platform-safe configuration.
- Remembering the last accepted folder for the current session.
- Existing recursive scan behavior.

Not included:

- A custom in-app file explorer.
- Persisting the last folder after the application closes.
- Adding, removing, or editing operating-system pinned locations.
- Thumbnail results or changes to the scan-results list.
- Multiple source folders.
- Classification, quarantine, move, or delete actions.

## Acceptance Criteria

- All automated tests pass.
- The KDE development system opens a native folder picker with normal navigation controls and KDE Places.
- The native picker can open a pinned location and select a folder from it.
- Reopening the picker starts at the last accepted source folder.
- Cancelling the picker does not alter the active folder or scan results.
- GNOME, Cinnamon, Windows, and macOS behavior is not blocked by KDE-specific code.
- Selecting and scanning a folder does not modify user files.
- The user completes the required KDE GUI check and replies with `Approved` before any Git operation is proposed.

## Manual GUI Check After Implementation

After automated tests pass, launch the application on the KDE development desktop and use only safe test folders.

1. Open the application and select **Select Folder**.
2. Confirm that KDE's native folder picker opens.
3. Confirm that back, forward, and parent-folder navigation are available.
4. Open a pinned location from KDE Places and select a safe folder.
5. Confirm that the application scans that folder and displays the result count.
6. Open **Select Folder** again and confirm that it starts at the folder selected in step 4.
7. Navigate elsewhere, cancel, and confirm that the prior source folder and results remain unchanged.
8. Confirm that no source file changed during the test.

Reply with `Approved` if every step passes. If a step fails, provide the step number, visible error text, and a screenshot when possible.
