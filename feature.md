# Tuck Away Settings and Updates

## Status

Implemented, GUI confirmed by user, PR opened.

This is a small user-interface cleanup, not a new product feature. Do not add a
roadmap ID and do not change `roadmap.md`.

## Request

The main window currently gives **Settings** and **Check for Updates** the same
visual weight as normal scan controls. They occupy two full-width rows in the
source-folder action area even though users need them less often.

The quarantine area also has a **Forget Quarantine Folder** button. The user has
said this action is not useful. Selecting another quarantine folder already
provides the useful replacement workflow.

## Goal

1. Put **Settings** and **Check for Updates** in one compact menu in the
   top-right corner of the fixed main-window header.
2. Remove **Forget Quarantine Folder** from the interface and remove its
   main-window behavior.
3. Keep settings, update checks, saved quarantine-folder loading, quarantine
   folder selection, and quarantine moves working as before.
4. Reduce the height of the scrollable controls so the primary workflow is
   easier to see.

## Exact User Interface

File: `src/img_ai_filter/window.py`

1. Add one compact `QToolButton` to the top-right corner of the existing fixed
   header.
2. Give the button visible text `...` so it uses ASCII and does not depend on an
   icon theme.
3. Give the button an accessible name or tooltip such as `Application menu` so
   assistive technology and mouse users can identify it.
4. Make the button open a `QMenu` immediately when clicked. Do not require a
   separate arrow click.
5. Add exactly these actions in this order:
   - `Settings`
   - `Check for Updates`
6. Connect the actions to the existing `_show_settings` and
   `_request_update_check` methods. Do not duplicate those workflows.
7. Keep the title and description on the left side of the header. Align the
   menu button to the top-right so it remains visible when the scrollable body
   moves.
8. Style the compact button for the existing dark header. It must have a clear
   hover state, keyboard focus state, disabled state, and enough size to click
   without looking like a primary action.
9. Remove the full-width `settings_button` and `check_updates_button` from the
   source-folder action grid.
10. Keep **Activity History** in the source-folder action grid. It is part of
    the regular local review workflow and is not included in this cleanup.
11. Remove the **Forget Quarantine Folder** button from the quarantine controls.
12. Place **Select Quarantine Folder** followed directly by **Move Checked to
    Quarantine**. Keep their current primary/secondary emphasis.

## Non-Goals

- Do not redesign the complete main window.
- Do not move **Activity History** into the corner menu.
- Do not add an automatic update check.
- Do not change update transport, release selection, download, installation,
  cancellation, or restart behavior.
- Do not change the settings dialog or its saved values.
- Do not clear an existing saved quarantine folder during startup or shutdown.
- Do not add a replacement forget action to the corner menu, settings dialog,
  context menu, or keyboard shortcut.
- Do not delete `clear_quarantine_folder` from `settings.py`; it is a valid
  settings-layer operation and may have independent unit tests. Remove only its
  unused main-window import and call.
- Do not change how selecting a new quarantine folder validates and saves it.
- Do not change file movement, confirmation, path validation, or move logs.
- Do not contact GitHub or a KoboldCpp server from automated tests.
- Do not commit, push, or open a pull request before all approval gates are
  complete.

## Test-First Coverage

Write the tests in this section before implementation. Run the focused tests
and confirm that the new assertions fail for the expected missing-menu or
still-present-control reason. Automated tests must continue to use injected
functions and must not access the network.

### 1. Header Menu Exists in the Correct Place

File: `tests/test_window.py`

Add a focused test with these checks:

1. Construct the normal `selection_window()` and show it.
2. Find the fixed header and the new application-menu tool button.
3. Assert that the menu button is a child or descendant of the fixed header,
   not of the scroll area's content widget.
4. Assert that the button has visible text `...`.
5. Assert that it has a non-empty accessible name or tooltip identifying it as
   the application menu.
6. Assert that the button is aligned on the right side of the header and does
   not overlap the title or description.
7. Assert that the menu contains exactly `Settings` followed by
   `Check for Updates`.
8. Assert that no full-size main-window push buttons with either of those texts
   remain in the scrollable action grids.

Expected pre-implementation failure: both commands are currently full-width
`QPushButton` objects in the source-folder grid and there is no header menu.

### 2. Menu Actions Open the Existing Workflows

Files: `tests/test_window_server.py`, `tests/test_window_updates.py`

Update the existing settings and update tests rather than duplicating all of
their behavioral coverage:

1. Replace direct `window.settings_button.click()` calls with triggering the
   `Settings` menu action.
2. Keep the existing settings-dialog save, cancel, invalid value, and saved
   threshold assertions unchanged.
3. Replace direct `window.check_updates_button.click()` calls with triggering
   the `Check for Updates` menu action.
4. Keep the existing assertions for no startup check, stable/test release
   choice, up-to-date result, available update, cancellation, error recovery,
   download, installation, and restart unchanged.
5. Assert that triggering each action calls its workflow exactly once.
6. Do not open a real network connection. Continue to inject `check_update`,
   `download_update`, and other update dependencies.

Expected pre-implementation failure: the named menu actions do not exist.

### 3. Busy and Recovery States Apply to Menu Commands

Files: `tests/test_window_server.py`, `tests/test_window_updates.py`

Adapt the existing control-state tests and add only missing assertions:

1. While a scan, connection test, or quarantine move is active, assert that the
   `Settings` and `Check for Updates` menu actions are disabled.
2. While an update operation is active, assert that both actions are disabled.
3. After each operation succeeds, fails, or is cancelled, assert that both
   actions become enabled again.
4. Assert that a failed update check can be requested a second time through the
   menu action.
5. Prefer disabling the individual actions. The menu button can remain
   available so its disabled commands and labels remain discoverable.
6. Keep the existing `Cancel` button rules unchanged.

Boundary expectation: neither menu action can start a second operation while
any scan/update operation is active.

### 4. Empty and Initial States Stay Safe

Files: `tests/test_window.py`, `tests/test_window_server.py`

Verify these initial-state contracts:

1. With no source folder selected, the header menu is present and both actions
   are enabled.
2. With no quarantine folder saved, there is no forget control and moving files
   remains disabled.
3. The quarantine label still says no folder is selected.
4. **Select Quarantine Folder** remains enabled while idle.
5. An empty menu is never shown; both required actions are always created.
6. Application startup still makes no update request.

### 5. Saved and Missing Quarantine Folder States Stay Valid

File: `tests/test_window_server.py`

Remove tests whose only contract is enabling or clicking the forget button.
Keep or adapt tests to prove:

1. A valid saved quarantine folder loads and is displayed at startup.
2. A saved folder that no longer exists is still reported as unavailable.
3. An invalid stored value does not enable a quarantine move.
4. The absence of a forget button does not clear the saved
   `QUARANTINE_FOLDER_KEY` value.
5. Selecting a valid replacement folder writes the new exact path to
   `QUARANTINE_FOLDER_KEY` and updates the label.
6. Cancelling the folder picker preserves the current saved folder and label.
7. A settings-store read or write failure remains sanitized in the visible UI.

Delete the existing
`test_forgetting_quarantine_folder_clears_it_and_disables_move` test because the
product no longer offers that operation from the main window.

### 6. Quarantine Controls Remain Correct

Files: `tests/test_window.py`, `tests/test_window_server.py`

Update quarantine-control assertions as follows:

1. Assert that **Select Quarantine Folder** is present.
2. Assert that **Move Checked to Quarantine** is present.
3. Assert that no `QAbstractButton` in the main window has text containing
   `Forget Quarantine Folder`.
4. Assert that selecting a quarantine folder can enable the move button only
   when a source folder and checked candidate also make the move valid.
5. Assert that move confirmation and exact source/destination behavior are
   unchanged.
6. Assert that no delete action was introduced.

### 7. Small-Window and Scrolling Layout

File: `tests/test_window.py`

Update the existing layout helpers and tests:

1. Remove the deleted full-width settings, update, and forget buttons from
   `main_action_buttons()`.
2. Include the new menu tool button in size and visibility checks where its
   different compact size makes the same assertion meaningful.
3. At the minimum supported window size of 560 by 400, assert that the header
   menu button is visible and not clipped.
4. Scroll the body to the bottom and assert that the fixed header and menu
   button remain in their original positions.
5. Assert that the title and description do not overlap the menu button.
6. Assert that the body still has no horizontal scrollbar.
7. Assert that the remaining quarantine controls can be scrolled fully into
   view and are not compressed below their minimum size hints.
8. At the default window size, assert that the cleanup does not add body
   overflow. If the reduced controls remove existing vertical overflow, accept
   the new smaller range rather than preserving unnecessary blank space.

### 8. Keyboard and Accessibility Behavior

File: `tests/test_window.py`

Add the smallest reliable Qt tests for these contracts:

1. The menu button accepts keyboard focus.
2. The button opens its menu with normal keyboard activation.
3. The two commands expose their full text in the menu.
4. Disabled actions cannot be triggered during an active operation.
5. Avoid tests that depend on a platform-specific native icon, font glyph, or
   global screen position.

### 9. Obsolete Main-Window Code Is Removed

Files: `src/img_ai_filter/window.py`, relevant tests

After behavioral tests exist, verify by direct code review or focused source
assertions only if necessary:

1. `MainWindow` no longer creates `forget_quarantine_button`.
2. `MainWindow` no longer defines `_forget_quarantine`.
3. `window.py` no longer imports `clear_quarantine_folder`.
4. There are no remaining test references to `forget_quarantine_button`.
5. There are no remaining test references to the deleted full-width
   `settings_button` or `check_updates_button` attributes.
6. Do not add compatibility aliases for the deleted button attributes.

## Implementation Steps

Implement only after the user approves this plan and the new tests fail for the
expected reasons.

### 1. Add Menu Imports

File: `src/img_ai_filter/window.py`

1. Import `QAction` from `PySide6.QtGui`.
2. Import `QMenu` and `QToolButton` from `PySide6.QtWidgets`.
3. Remove `clear_quarantine_folder` from the settings imports after deleting
   the main-window forget behavior.
4. Keep imports sorted consistently with the current file.

### 2. Build the Header Menu

File: `src/img_ai_filter/window.py`

1. Create a `QToolButton` owned by the header.
2. Use a stable object name such as `applicationMenuButton` so tests and style
   rules can locate it without relying only on visible text.
3. Set its text to `...`.
4. Set a tooltip or accessible name to `Application menu`.
5. Set the pointing-hand cursor and a menu-popup mode that opens the menu from
   the whole button.
6. Create a `QMenu` owned by the button.
7. Create and retain a `Settings` action and a `Check for Updates` action as
   explicit `MainWindow` attributes. Stable action attributes allow control
   state updates and tests without searching by translated display text.
8. Connect the actions to `_show_settings` and `_request_update_check`.
9. Add the actions to the menu in the approved order.
10. Attach the menu to the tool button.

### 3. Change the Header Layout

File: `src/img_ai_filter/window.py`

1. Replace the header's single vertical layout with a horizontal outer layout.
2. Put the existing title and description in a nested vertical text layout.
3. Give the text area stretch so long descriptions wrap before the menu button.
4. Put the menu button at the top-right with explicit top alignment.
5. Preserve approximately the current header margins, spacing, colors, and
   bottom accent border.
6. Do not put the header inside `content_scroll`.

### 4. Simplify Main Controls

File: `src/img_ai_filter/window.py`

1. Delete creation and connection of the old settings push button.
2. Delete creation and connection of the old update push button.
3. Remove both old buttons from `folder_buttons`.
4. Keep source-folder controls in this order:
   - row 1: **Select Folder**, **Scan Folder**;
   - row 2: **Cancel**, **Activity History**.
5. Delete creation and connection of the forget-quarantine push button.
6. Remove it from `quarantine_buttons`.
7. Put **Select Quarantine Folder** on the first quarantine row and **Move
   Checked to Quarantine** on the second row.
8. Remove all three deleted buttons from the minimum-size setup loop.
9. Add the compact menu button to an appropriate minimum-size setup only if its
   size hint alone is not sufficient.

### 5. Update Control States

File: `src/img_ai_filter/window.py`

1. In `_update_controls`, remove the forget-button state calculation.
2. Replace `settings_button.setEnabled(not busy)` with the same state on the
   retained settings action.
3. Replace `check_updates_button.setEnabled(not busy)` with the same state on
   the retained update action.
4. Keep the menu tool button enabled unless there is a demonstrated Qt reason
   it must be disabled. Disabled actions communicate command state inside it.
5. Keep all scan, cancel, selection, quarantine selection, and move-button
   conditions unchanged.

### 6. Remove Forget Behavior

File: `src/img_ai_filter/window.py`

1. Delete `_forget_quarantine` in full.
2. Delete its `clear_quarantine_folder` call and all main-window state changes
   that existed only for this command.
3. Do not add an automatic clear path elsewhere.
4. Keep `_choose_quarantine` as the only main-window way to set or replace the
   saved quarantine folder.
5. Keep loading and validation of the saved quarantine folder unchanged.

### 7. Style the Compact Menu

File: `src/img_ai_filter/window.py`

1. Add narrowly scoped style rules for `QToolButton#applicationMenuButton`.
2. Use colors that meet the existing dark-header contrast direction.
3. Keep padding compact and preserve a practical click target.
4. Add hover, focus, and disabled rules.
5. Do not alter global `QToolButton` or `QMenu` styling unless required for
   readability.
6. Confirm the popup menu remains readable with the application's global
   foreground and background rules.

## Verification Sequence

Run all commands from the repository root.

### 1. Confirm Tests Fail First

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  tests/test_window.py \
  tests/test_window_server.py \
  tests/test_window_updates.py
```

Before implementation, confirm failures specifically show that the header menu
does not exist, old buttons still exist, or tests still use old button
attributes. Do not proceed if failures come from accidental network access,
test collection errors, or unrelated behavior.

### 2. Implement the Smallest UI Change

Follow the implementation steps above. Do not refactor unrelated main-window
logic while changing the layouts and controls.

### 3. Run Focused Tests

Run the same focused command and require every test to pass.

### 4. Search for Obsolete References

Search source and tests for:

```text
forget_quarantine_button
_forget_quarantine
settings_button
check_updates_button
Forget Quarantine Folder
```

There must be no obsolete main-window or test references. A settings-layer
`clear_quarantine_folder` definition and its direct unit tests may remain.

### 5. Run the Full Network-Blocked Suite

Run:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

All tests must pass. Do not weaken the automatic network blocker.

### 6. Desktop GUI Test

After automated tests pass, ask the user to launch:

```bash
.venv/bin/python -m img_ai_filter
```

Use safe sample folders and complete this checklist:

1. Confirm the `...` menu is visible in the top-right of the dark header.
2. Open it with the mouse and confirm it contains **Settings** and **Check for
   Updates** in that order.
3. Open it with the keyboard and confirm both commands are readable.
4. Select **Settings**, change no value, cancel, and confirm the main window
   remains usable.
5. Open **Settings** again, save an intended test value, and confirm the normal
   settings workflow still works.
6. Select **Check for Updates** and confirm the same update result or safe error
   appears as before.
7. Confirm no **Forget Quarantine Folder** control appears anywhere.
8. Select a quarantine folder, then select a different one. Confirm the label
   shows the second exact path.
9. Cancel a later quarantine-folder picker and confirm the second path remains.
10. Select a source folder containing copies of safe sample images. Confirm
    scan and quarantine controls still behave normally.
11. Resize the window to its minimum size. Confirm the header menu remains
    visible, title text does not overlap it, and horizontal scrolling does not
    appear.
12. Scroll to the bottom and confirm the menu stays fixed in the header.

Ask the user to reply with exactly `Approved` if all steps pass. If a step
fails, ask for the error text, a screenshot, and the failed step number.

## Acceptance Criteria

- One compact application menu appears in the top-right corner of the fixed
  header.
- The menu contains **Settings** and **Check for Updates** in that order.
- The old full-width settings and update buttons are absent.
- Both menu actions execute the existing workflows exactly once.
- Both actions are disabled during active work and restored afterward.
- Startup does not check for updates.
- **Forget Quarantine Folder** is absent from the complete main window.
- The main window has no forget handler, button attribute, or unused clear
  import.
- Existing saved quarantine folders still load and validate.
- Selecting another quarantine folder safely replaces the saved path.
- Cancelling folder selection preserves the current path.
- Quarantine moves and their safety rules are unchanged.
- The menu remains visible and usable at the minimum window size.
- No automated test contacts the network.
- Focused tests and the full test suite pass.
- The user approves the desktop GUI checklist.

## Approval Gates

1. Wait for user approval of this plan.
2. Write the failing tests before implementation.
3. Confirm the focused tests fail for the expected reasons.
4. Implement the smallest change described above.
5. Run focused tests and the full suite.
6. Ask the user to perform the desktop GUI checklist.
7. Wait for explicit `Approved` from the user.
8. Only after approval ask whether the user wants a pull request, commit, or
   push.
