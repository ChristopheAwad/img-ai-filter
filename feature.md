# Windows CI Repair After F-011

## Purpose

Repair the Windows GitHub Actions failures introduced by PR #12 without
changing the Linux-only AppImage installation contract or weakening any safety
check.

The failing Windows run is:

- Workflow: `Windows tests`
- Run: `35737672850`
- Result: 20 failed tests, 2 teardown errors, 1,022 passed, 27 skipped

This is a bug fix, not a new roadmap feature. Do not add or change a roadmap
item. Do not create a release tag as part of this work.

## Required Outcome

1. The complete test suite passes on Linux.
2. The complete `Windows tests` GitHub Actions workflow passes on Windows.
3. Update discovery remains available on every supported platform.
4. Automatic AppImage installation remains available only on Linux.
5. Windows never calls POSIX-only AppImage filesystem operations.
6. AppImage downloads retain their existing URL, size, digest, cancellation,
   cleanup, and streaming protections.
7. The main window has no horizontal body overflow at its 560-pixel minimum
   width on Windows or Linux.
8. No source image is modified, moved, renamed, or deleted by this repair.
9. No test contacts the network.

## Root Causes Already Confirmed

### 1. Linux-only installation detection runs on Windows

`src/img_ai_filter/update_install.py` calls `os.statvfs()` while inspecting an
`APPIMAGE` environment value. Windows does not provide `os.statvfs`. This
causes failures in `tests/test_update_install.py` and causes two asynchronous
GUI tests to time out with teardown errors.

### 2. Download setup calls `os.fchmod()` on Windows

`src/img_ai_filter/update_transport.py` calls `os.fchmod()` after
`tempfile.mkstemp()`. Windows does not provide `os.fchmod`. The resulting
`AttributeError` is converted to a generic download failure before tests can
exercise digest verification or cancellation.

### 3. The new update button exceeds the minimum window width

`Settings` and `Check for Updates` share a two-column row. Windows font and
style metrics make that row approximately 10 pixels wider than the available
scroll viewport. The horizontal scrollbar is hidden, but the content still has
a horizontal scroll range and is clipped.

### 4. Two GUI tests accidentally depend on real Linux detection

The GUI update-flow tests are intended to test prompts, download orchestration,
installation orchestration, and restart behavior. They currently use a real
temporary `APPIMAGE` path. That makes the GUI tests depend on Linux-specific
filesystem detection and fail on Windows.

## Test-First Work

Write or adjust tests before changing application code. First run the focused
tests and confirm that the new cross-platform regression tests fail for the
expected reasons. Existing failures observed only in GitHub Windows CI also
count as pre-existing failing tests, but add platform simulation where needed
so the failures can be reproduced on Linux.

### A. Unsupported-platform installation tests

File: `tests/test_update_install.py`

1. Import `sys` if the test markers need it.
2. Import the `img_ai_filter.update_install` module under a module alias so its
   imported `sys.platform` value can be monkeypatched in cross-platform tests.
3. Define one clear Linux-only marker, for example:
   `LINUX_ONLY = pytest.mark.skipif(sys.platform != "linux", reason="AppImage installation is supported only on Linux")`.
4. Do not apply the marker to the entire file. Invalid environment parsing and
   restart helper tests are still useful on Windows.
5. Add a regression test that simulates a non-Linux platform by monkeypatching
   `update_install.sys.platform` to `"win32"`.
6. In that test, create an existing regular file, set its mode to executable,
   pass its absolute path as `APPIMAGE`, and assert
   `detect_appimage_installation()` returns `None`.
7. Ensure the non-Linux detection test proves that filesystem probing is not
   attempted. Monkeypatch `Path.lstat`, `Path.stat`, or `os.statvfs` with a
   function that raises `AssertionError` if called, while keeping the test
   small and reliable. The platform guard must execute before path probing.
8. Add a regression test that simulates `"win32"` and directly calls
   `install_appimage()` with valid dataclass-shaped input.
9. Assert the direct call raises `InstallError` with a safe message that states
   AppImage installation is Linux-only or unsupported on this platform.
10. Assert the direct-call rejection occurs before reading, chmodding,
    replacing, or deleting either path. Check the original and update bytes are
    unchanged and no backup exists.
11. Keep the existing parameterized invalid environment test active on every
    platform. It covers `None`, empty string, whitespace, and a relative path.
12. Keep the extraction-mode test active on every platform. It must return
    `None` without attempting installation.
13. Keep nonexistent and non-regular path rejection active where it remains
    meaningful, but do not make Windows inspect Linux AppImage permissions.
14. Apply the Linux-only marker to tests whose success requires real AppImage
    detection or POSIX replacement behavior:
    - valid AppImage identity capture;
    - detection without modification;
    - download outside the AppImage directory;
    - changed download size or digest;
    - changed current AppImage identity;
    - successful replacement and retained backup;
    - second installation backup replacement;
    - unsafe backup symlink rejection;
    - final replacement failure and restoration;
    - recovery failure and surviving-path report.
15. Apply a Linux-only marker to symlink tests if Windows symlink creation is
    not guaranteed. Do not remove the test; Linux must continue to run it.
16. Keep restart launch and restart failure tests platform-independent because
    they use an injected launcher and do not perform a real process launch.

Expected initial failures before implementation:

- Simulated Windows detection reaches filesystem probing or returns a detected
  installation.
- Simulated Windows direct installation does not produce the required explicit
  rejection.

### B. Missing `os.fchmod` download test

File: `tests/test_update_transport.py`

1. Import `img_ai_filter.update_transport` under a module alias.
2. Add a test that uses the existing fake response and connection factory.
3. Use a short valid byte payload with an exact `Content-Length` and matching
   SHA-256 digest.
4. Use `monkeypatch.delattr(update_transport.os, "fchmod", raising=False)` to
   simulate Windows on Linux. If deleting an attribute from the shared `os`
   module creates unwanted process-wide effects, instead monkeypatch a small
   module-level capability seam introduced for this purpose. Prefer the
   smallest approach and restore it automatically with `monkeypatch`.
5. Call `download_appimage()` with `tmp_path` and the fake transport.
6. Assert the call succeeds.
7. Assert the returned file is inside `tmp_path`.
8. Assert the returned bytes, byte count, and SHA-256 digest are exact.
9. Assert the connection is closed.
10. Do not weaken or remove existing tests for:
    - bounded streaming;
    - monotonic progress;
    - approved HTTPS redirects;
    - rejected redirect hosts and schemes;
    - response size mismatch;
    - digest mismatch;
    - cancellation cleanup;
    - unapproved initial URLs.

Expected initial failure before implementation:

- The download is converted to `UpdateTransportError("The AppImage download failed")`
  because the missing `os.fchmod` raises before streaming.

### C. GUI update workflow isolation tests

File: `tests/test_window_updates.py`

1. Import `AppImageInstallation` and `FileIdentity` from
   `img_ai_filter.update_install`, or build an equally strict controlled test
   value. Prefer the real dataclasses.
2. Add a small local helper that returns an `AppImageInstallation` for a test
   path. Build its `FileIdentity` from the path's actual `stat()` fields so the
   fixture is internally consistent. The GUI tests will inject fake install
   behavior and must not invoke the real installer.
3. In
   `test_appimage_update_downloads_installs_and_restarts_after_confirmations`,
   monkeypatch `window_module.detect_appimage_installation` to return the
   controlled installation.
4. Keep the injected download, install, and restart functions.
5. Keep the exact stage assertion:
   download, install, restart exact path, close.
6. Keep the exact prompt sequence assertion:
   `Update available`, `Install update?`, `Restart Image Filter?`.
7. In `test_update_notes_are_rendered_as_plain_text`, monkeypatch detection to
   return the controlled installation.
8. Keep the assertion that release notes are rendered as plain text and that
   the default answer is No.
9. Keep `test_available_update_outside_appimage_does_not_download` using an
   empty environment and real detection. This is the cross-platform behavior
   Windows users receive: they can discover the release, but automatic
   installation is unavailable.
10. Extend that non-AppImage test only if needed to assert no download starts
    and the message explains that a writable AppImage is required.
11. Do not skip the GUI orchestration tests on Windows. Mock only the Linux
    filesystem boundary so Windows continues to test the GUI state machine.

Expected result before application changes:

- These adjusted tests can run on Windows without `os.statvfs` because they no
  longer call real AppImage detection for the simulated installable path.
- They should remain green on Linux.

### D. Minimum-width layout tests

File: `tests/test_window.py`

1. Add `window.check_updates_button` to `main_action_buttons()`.
2. This automatically includes it in minimum-size, visibility, and long-text
   layout assertions.
3. Keep the minimum test window at exactly 560 by 400 pixels.
4. Keep `horizontalScrollBar().maximum() == 0`. Do not replace this with a check
   that the scrollbar is hidden; hidden overflow is still a defect.
5. Keep the assertion that the content widget is no wider than the viewport.
6. Keep vertical scrolling enabled at the minimum height.
7. Keep all button width and height checks against each button's
   `minimumSizeHint()`.
8. Ensure `ensureWidgetVisible()` can bring `Check for Updates` fully inside the
   viewport.
9. Keep the long folder, quarantine, status, and move-log text wrapping test.
10. Do not lower the application minimum width or reduce button text to make
    the test pass.

The existing Windows CI failure is the required failing reproduction for the
10-pixel overflow. The shared button list change must not weaken it.

## Application Changes

Implement only after the test changes above exist.

### 1. Guard AppImage operations by platform

File: `src/img_ai_filter/update_install.py`

1. Import `sys`.
2. At the start of `detect_appimage_installation()`, before reading the
   `APPIMAGE` value or probing any path, check `sys.platform`.
3. If `sys.platform != "linux"`, return `None`.
4. Do not catch `AttributeError` around `os.statvfs` as the main fix. A broad
   catch would hide an unsupported-platform contract and leave later POSIX
   operations exposed.
5. Keep the existing environment validation:
   missing value, empty value, outer whitespace, relative path, and extraction
   mode all remain non-installable.
6. Keep all Linux checks for:
   - absolute path;
   - regular file and no symlink;
   - regular parent directory;
   - write and execute mode bits;
   - effective write and execute access;
   - read-only filesystem flag;
   - captured device, inode, size, and modification time.
7. At the start of `install_appimage()`, before path or file operations, reject
   `sys.platform != "linux"` with `InstallError` and a safe concise message.
8. Keep type validation and every existing identity, digest, backup, atomic
   replacement, directory sync, restoration, and recovery-error check on
   Linux.
9. Do not add Windows AppImage installation behavior. AppImage is the Linux
   package format supported by this project.
10. Do not change `restart_appimage()` unless a focused test proves a separate
    Windows defect. It uses an injected launcher in tests and is called by the
    application only after a successful Linux installation.

### 2. Make descriptor permission hardening conditional

File: `src/img_ai_filter/update_transport.py`

1. Keep `tempfile.mkstemp()` as the atomic temporary-file creator.
2. Retrieve `os.fchmod` with `getattr(os, "fchmod", None)`.
3. If it exists, call it with the open descriptor and mode `0o600`.
4. If it does not exist, continue using the descriptor returned by
   `mkstemp()`. Do not substitute path-based `chmod` on Windows because Windows
   uses ACLs and the POSIX mode is not an equivalent security guarantee.
5. If an available `fchmod` call itself fails, preserve the current behavior:
   close the descriptor, clean up the temporary path, and report a safe
   download failure.
6. Ensure the descriptor has one owner after every branch. It must either be
   closed explicitly after setup failure or passed exactly once to
   `os.fdopen()`.
7. Do not change URL allowlists, redirect limits, response status handling,
   content-length handling, maximum size, streaming chunk size, cancellation,
   SHA-256 verification, cleanup, or exception redaction.

### 3. Remove horizontal layout overflow

File: `src/img_ai_filter/window.py`

1. Keep Select Folder and Scan Folder in row 0, columns 0 and 1.
2. Keep Cancel and Activity History in row 1, columns 0 and 1.
3. Place Settings in row 2 and span both columns.
4. Place Check for Updates in row 3 and span both columns.
5. Keep both column stretch values at 1.
6. Keep existing button labels, object names, cursors, signals, and minimum-size
   behavior.
7. Do not hide content, reduce fonts, remove minimum sizes, enable horizontal
   scrolling, or increase the 560-pixel minimum window width.
8. Accept the small increase in vertical content height. The body already uses
   vertical scrolling at short heights, and the normal 820 by 1020 window has
   sufficient room.

## Focused Verification

Run these commands from the repository root after implementation.

1. Installer tests:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_update_install.py
```

2. Transport tests:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_update_transport.py
```

3. GUI update tests:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_window_updates.py
```

4. Main-window layout tests:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_window.py
```

5. Run all four files together to detect shared Qt or monkeypatch leakage:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_update_install.py tests/test_update_transport.py tests/test_window_updates.py tests/test_window.py
```

## Full Verification

1. Run the complete Linux suite:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

2. Confirm no test attempted network access. The autouse network blocker must
   remain enabled and unchanged.
3. Inspect `git diff --check` for whitespace errors.
4. Inspect `git diff` and confirm only intended bug-fix files and this handoff
   plan changed.
5. If the work is later pushed to a branch, wait for the complete GitHub
   `Windows tests` workflow. Local Linux success is not sufficient because the
   original layout defect depends on Windows Qt font and style metrics.
6. Do not create or push `v0.2.0` until Windows CI is green.

## Expected Platform Results

### Linux

- Real writable AppImage detection works.
- Safe AppImage replacement tests run.
- Temporary download permissions are set with `fchmod(0o600)`.
- All GUI update orchestration tests pass.
- Minimum-width layout has no horizontal overflow.

### Windows

- Update checks can discover and display a newer release.
- Real AppImage detection immediately returns `None`.
- Automatic AppImage installation does not start.
- Direct AppImage installation is explicitly rejected.
- Downloads used by isolated transport tests work without `os.fchmod` and
  still verify size and SHA-256.
- GUI orchestration tests use a controlled installation boundary and do not
  call `os.statvfs`.
- Linux filesystem replacement tests are skipped with a clear reason.
- The minimum-width layout has no horizontal scroll range.

## Failure Handling During Implementation

1. If simulated non-Linux tests still touch the filesystem, move the platform
   guard earlier. Do not add broad exception swallowing.
2. If descriptor tests leak a file or handle, inspect every branch between
   `mkstemp()` and `fdopen()`. Do not suppress resource warnings.
3. If the 560-pixel layout still overflows, inspect all button minimum widths
   and layout margins. Do not disable the overflow assertion.
4. If the default 820 by 1020 window starts vertical scrolling, measure the
   added row and spacing before changing dimensions. Prefer reducing redundant
   row spacing only if required; do not compress controls.
5. If GUI tests time out, inspect captured Qt callback exceptions first. A
   timeout is often a secondary result of an exception on the GUI thread.
6. If Linux installer tests fail after adding the platform guard, do not alter
   Linux safety checks unless a test demonstrates an actual regression.
7. If the Windows workflow reveals an additional platform-specific failure,
   record its full traceback and add a local platform-simulation regression
   test before changing application code.

## Files Expected To Change

- `feature.md`
- `src/img_ai_filter/update_install.py`
- `src/img_ai_filter/update_transport.py`
- `src/img_ai_filter/window.py`
- `tests/test_update_install.py`
- `tests/test_update_transport.py`
- `tests/test_window_updates.py`
- `tests/test_window.py`

Do not change the release workflow, package version, roadmap status, update
endpoint allowlist, or release asset naming for this repair.

## Completion Checklist

- [ ] New simulated Windows detection test fails before implementation and
      passes after implementation.
- [ ] New direct non-Linux installation rejection test fails before
      implementation and passes after implementation.
- [ ] New missing-`fchmod` transport test fails before implementation and
      passes after implementation.
- [ ] True Linux installer tests are clearly skipped on Windows, not deleted.
- [ ] GUI orchestration tests run on Windows through mocked detection.
- [ ] Non-AppImage update discovery remains tested on Windows.
- [ ] Check for Updates participates in button size and visibility assertions.
- [ ] Horizontal scroll maximum remains exactly zero at 560 by 400.
- [ ] All focused tests pass.
- [ ] Complete Linux suite passes.
- [ ] `git diff --check` passes.
- [ ] GitHub Windows workflow passes after a later push.
- [ ] No release tag is created while CI is red.

## Implementation Handoff

The implementation agent must follow test-first order:

1. Modify only tests and run focused tests to establish expected failures.
2. Implement the platform guards, conditional `fchmod`, and layout rows.
3. Run focused tests.
4. Run the combined affected suite.
5. Run the complete Linux suite.
6. Report exact pass, fail, and skip counts plus any command that could not be
   run.
7. Do not commit, push, create a pull request, or create a release tag.
