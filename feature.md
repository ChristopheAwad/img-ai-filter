# Feature Plan: Desktop Foundation and Folder Scan

## Goal

Create the first working desktop application. The user can select a source folder, scan it recursively, and see all supported image paths. This feature only reads the file system. It does not classify, edit, move, or delete files.

## Test Coverage First

Write these tests before application code. Confirm that the relevant tests fail for the expected missing behavior before implementation starts.

### Scanner Unit Tests

- Return an empty result for an existing empty folder.
- Return an empty result when a folder contains only unsupported files.
- Find PNG, JPG, JPEG, WebP, BMP, TIF, and TIFF files.
- Match supported extensions without regard to letter case.
- Find supported images at the selected folder boundary and in nested folders.
- Exclude files whose names only end with a similar unsupported suffix.
- Return each discovered path once.
- Return results in a stable, predictable order.
- Do not follow a symbolic link to a directory inside the selected tree.
- Do not follow a symbolic link to a directory outside the selected tree.
- Do not include symbolic links to image files.
- Reject a path that does not exist.
- Reject a path that points to a file instead of a folder.
- Report a clear failure when the selected folder cannot be read.
- Continue safely when one nested directory cannot be read, and report that skipped directory.
- Handle an empty path value without scanning the current working directory by accident.

Where symbolic links or permission behavior cannot be created reliably on a platform, mark only that specific test as skipped with a clear reason.

### GUI Tests

- The initial window has a folder selection action and an empty-results message.
- Cancelling the folder dialog does not start a scan or change the current results.
- Selecting a valid empty folder shows a completed scan with zero images.
- Selecting a folder with supported images displays their paths.
- Starting another scan replaces old results instead of combining scans.
- A scan failure shows a useful error and keeps the application responsive.
- No move, delete, or quarantine action is present in this milestone.

Use temporary directories and generated empty files for scanner tests. Do not use personal folders, network access, or files outside the test temporary directory.

## Implementation Plan

1. Add `pyproject.toml` with Python project metadata, PySide6 as the runtime dependency, pytest and pytest-qt as development test dependencies, and pytest configuration.
2. Use a `src/img_ai_filter` package and a `tests` directory.
3. Add a scanner module with a small typed result model containing discovered image paths and skipped-directory warnings.
4. Validate the selected path before traversal.
5. Traverse recursively without following symbolic links.
6. Filter by the supported extensions defined in `project-brief.md`.
7. Sort paths deterministically so tests and the GUI have stable results.
8. Add a PySide6 main window with:
   - a Select Folder button;
   - the selected folder path;
   - a result count;
   - a simple list of discovered image paths;
   - an empty state;
   - an error message for failed scans.
9. Add a package entry point so the app can be launched with `python -m img_ai_filter` from the configured development environment.
10. Keep the scanner independent of PySide6 so later background scanning and classification can reuse it.
11. Add a short README with environment setup, test, and launch commands after those commands have been verified.

## Planned Files

- `pyproject.toml`
- `README.md`
- `src/img_ai_filter/__init__.py`
- `src/img_ai_filter/__main__.py`
- `src/img_ai_filter/scanner.py`
- `src/img_ai_filter/window.py`
- `tests/test_scanner.py`
- `tests/test_window.py`

Exact file names can change if the tests or implementation show that a smaller structure is clearer.

## Boundaries

Included:

- One selected source folder at a time.
- Recursive, read-only discovery.
- PNG, JPEG, WebP, BMP, and TIFF file extensions.
- A basic desktop results list.
- Linux, Windows, and macOS-compatible path handling.

Not included:

- Reading image pixels or validating image contents.
- Thumbnails.
- AI classification, OCR, or ONNX Runtime.
- Confidence values or automatic selection.
- Quarantine folder selection.
- Moving, renaming, restoring, or deleting files.
- Persisted settings or review labels.
- Installers or packaged releases.

## Acceptance Criteria

- The verified setup command installs the project dependencies in a clean development environment.
- All automated tests pass.
- The desktop application launches with the documented command.
- Selecting a folder shows all and only supported, non-symbolic-link image files beneath it.
- Empty scans and failures have clear visible states.
- Scanning does not modify any user file or folder.
- No network service is used.
- The user completes the required desktop GUI check and replies with `Approved` before any Git operation is proposed.

## Manual GUI Check After Implementation

After automated tests pass, provide the exact verified launch command and ask the user to check:

1. The application opens and shows the empty state.
2. Cancelling folder selection makes no change.
3. Selecting a safe test folder shows supported images from it and its nested folders.
4. Unsupported files do not appear.
5. Selecting an empty folder shows zero results without an error.
6. No source file changes during the test.

Use only test data copied or created for this check. Do not use an important personal folder for the first manual test.
