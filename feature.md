# F-011: AppImage Update Checks and Installation

## Status

Plan written on 2026-09-21 and approved by the user on 2026-09-22. Write and
observe the required failing tests before each production change.

Test-first implementation and automated verification completed on 2026-09-22.
The user completed and approved the desktop GUI verification on 2026-09-22.

F-010 merged in PR #10 on 2026-09-22. Its packaging code is now the starting
point for F-011. Recheck artifact names and release behavior against executable
code and tests rather than copying stale assumptions from this plan.

Approved baseline after synchronizing merged F-010:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
929 passed, 4 skipped, 1 warning in 39.33s
```

Implementation details frozen after reconciliation with F-010:

- Use PEP 440 package and tag versions such as `0.2.0b1` and `v0.2.0b1`.
- Declare `packaging` as a direct runtime dependency for version comparison.
- Require GitHub's SHA-256 release-asset `digest` field for the selected
  AppImage. Keep `SHA256SUMS` as a downloadable release artifact for people and
  packaging verification, but do not make a second updater request for it.
- Keep the manual read-only package workflow and add a separate tag-triggered
  release workflow that creates a draft, uploads exact assets, verifies them,
  and then publishes.

Observed red phases before production changes:

- Settings/release tests failed collection because the setting and release
  module did not exist.
- Transport tests failed collection because the update transport did not exist.
- Installer tests failed collection because the AppImage installer did not
  exist.
- Initial GUI tests reported six missing updater behaviors.
- Cancellation and installation-close lifecycle tests failed before their
  control-state fixes.
- Release workflow tests failed collection before release validation existed.
- The `0.2.0` package-version test observed the prior `0.1.0` value.

Focused verification after implementation:

```text
settings + release: 151 passed
release + transport: 73 passed
settings + release + transport + installer: 198 passed
window update + existing window tests: 118 passed
release workflow + Linux packaging tests: 55 passed
```

Complete offline verification after implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
1063 passed, 4 skipped, 1 warning in 32.42s

git diff --check
clean

.venv/bin/python -m img_ai_filter.release v0.2.0 pyproject.toml
version=0.2.0
prerelease=false

QT_QPA_PLATFORM=offscreen .venv/bin/python -m img_ai_filter --smoke-test
passed
```

Local AppImage construction could not run because the repository's pinned
PyInstaller 6.10.0 does not support the available Python 3.14 interpreter, and
Python 3.11 through 3.13 are not installed locally. The release and packaging
workflows use Python 3.11 and retain the complete build, smoke-test, and checksum
steps. CI artifact construction remains to be confirmed after the change is
pushed through the approved Git workflow.

Current planning-time worktree state:

```text
git status --short --branch
## main...origin/main
?? packaging-build/
```

`packaging-build/` was already untracked and must not be deleted, modified, or
committed as part of planning.

## Purpose

Let an AppImage user check for a newer GitHub release and install it without
opening GitHub or manually replacing the AppImage. The user starts every check.
The app does not make an update request at startup or on a timer.

The first updater-enabled AppImage cannot be delivered by the updater because
older AppImages contain no updater. The user must manually install that one
bootstrap release. Later compatible AppImages can update themselves.

## Frozen Product Decisions

1. Add an explicit **Check for Updates** action to the desktop application.
2. Contact GitHub only after the user selects that action.
3. Do not check on startup, periodically, after a scan, or after a connection
   test.
4. Use stable releases by default.
5. Add a saved **Include test releases** option. When enabled, consider stable
   releases and GitHub pre-releases. Never consider drafts.
6. Support Linux x86-64 AppImage installation first.
7. Source, editable, portable-tar, and other package builds may check for an
   update but must never replace themselves.
8. Download the complete AppImage. Do not add AppImage `.zsync` delta updates in
   F-011.
9. Stream downloads to disk. Do not hold the full AppImage in memory.
10. Show version, stable/test channel, release notes, and download size before
    asking the user to download.
11. Require a second explicit confirmation before installation.
12. Verify the complete AppImage with an expected SHA-256 digest before making
    it executable or replacing any file.
13. Obtain the running outer AppImage path from the `APPIMAGE` environment
    variable. Do not infer it only from the working directory or
    `sys.executable`.
14. Replace the AppImage only when its file and parent directory pass all safety
    checks.
15. Keep one recovery backup of the prior AppImage.
16. Ask whether to restart after a successful replacement. Do not restart
    without confirmation.
17. Keep update networking separate from the private-LAN KoboldCpp transport.
    Update support must not weaken endpoint validation, no-redirect behavior,
    response limits, or privacy rules for image analysis.
18. Use injected transports and filesystem/process boundaries so all automated
    tests remain offline and deterministic.
19. Do not send image paths, endpoint settings, scan history, machine identity,
    credentials, or other application data to GitHub.
20. Do not add telemetry or an installation identifier.

## Scope

### Included

- Manual update discovery through GitHub release metadata.
- Stable and opt-in test release channels.
- Strict version and release validation.
- Exact Linux x86-64 AppImage asset selection.
- Bounded metadata requests.
- Streamed AppImage downloads with progress and cancellation.
- SHA-256 verification.
- AppImage environment and path safety checks.
- One retained backup and recoverable replacement.
- Explicit restart prompt.
- A dedicated update worker or controller that keeps Qt responsive.
- A draft-first GitHub release workflow.
- Package version, release tag, metadata, and filename consistency checks.
- Offline unit, integration, Qt, packaging, and workflow tests.
- User documentation and a desktop verification checklist.

### Excluded

- Automatic startup or scheduled checks.
- Silent downloads, installation, or restart.
- Windows or macOS update installation.
- Portable-tar directory replacement.
- Updating source or editable installations.
- Linux package-manager integration.
- AppImage `.zsync` differential downloads.
- Rollback controls inside the GUI.
- Deleting a retained backup automatically after startup.
- Downgrades or same-version reinstalls.
- More than one retained backup.
- Release signing with a project-owned offline key.
- Telemetry, analytics, or unique update identifiers.
- Changes to the KoboldCpp server or image-transfer workflow.

## Security And Trust Boundary

The updater installs executable code from the public Internet. Treat all
release metadata, redirect responses, names, sizes, notes, digests, and bytes as
untrusted input.

F-011 verifies transport security and release integrity through HTTPS, strict
GitHub host rules, exact release/asset matching, and SHA-256. This detects a
corrupt or substituted download when it does not match the trusted release
metadata. It does not protect against compromise of the GitHub repository or
release-publishing credentials. Document this limitation. Project-owned signed
release manifests remain future hardening, not an implied F-011 guarantee.

Never pass GitHub URLs through the private-LAN endpoint validator. Never permit
the vision client to contact public hosts. Implement a separate, narrow update
transport with its own policy.

## Release Contract

1. `pyproject.toml` remains the application version authority.
2. Stable release tags use `vMAJOR.MINOR.PATCH`, for example `v0.2.0`.
3. Test release tags use one documented pre-release form accepted by the chosen
   version parser, for example `v0.2.0b1` or `v0.2.0-beta.1`. Choose one form
   during implementation and use it consistently in package metadata, tags,
   tests, and documentation.
4. A release tag must identify the same normalized version as the packaged
   application.
5. Drafts are never update candidates.
6. A stable-channel check ignores all pre-releases.
7. A test-channel check considers stable and pre-release versions and selects
   the highest valid version newer than the installed version.
8. An equal or older version is not an update.
9. Local versions, malformed versions, and unsupported version forms are not
   update candidates.
10. The required asset name is derived from the validated release version and
    the packaging naming contract. Do not select an asset by substring alone.
11. The first implementation supports exactly Linux x86-64 AppImages.
12. A candidate release must contain exactly one matching AppImage asset.
13. The matching asset must have a positive bounded size and a valid SHA-256
    digest supplied by the approved release metadata contract.
14. Duplicate matching assets, absent assets, absent digests, malformed
    digests, and unsupported architectures make that release unusable.
15. Release notes are display-only untrusted plain text. Do not render remote
    HTML or execute links embedded in notes.
16. The workflow must build and test before release publication.
17. Create the GitHub release as a draft, upload every required asset, verify
    names and digests, and publish only after verification succeeds.
18. Pull-request workflows must never publish a release.
19. Grant `contents: write` only to the release publication job that needs it.
20. Keep the existing read-only packaging workflow or replace it only when the
    new workflow retains its tests, checksum verification, and artifact upload.

## Detailed Test-First Plan

### Phase 0: Rebase Knowledge And Record Baseline

1. Wait until F-010/PR #10 is accepted and merged unless the user explicitly
   directs work on its branch.
2. Read merged `AGENTS.md`, `roadmap.md`, `feature.md`, `project-brief.md`,
   `README.md`, `pyproject.toml`, packaging scripts, packaging tests, and GitHub
   workflows.
3. Inspect Git status and preserve unrelated or untracked files.
4. Confirm the authoritative package version and actual AppImage filename.
5. Confirm how the packaged application obtains `QApplication.applicationVersion`.
6. Confirm whether the built AppImage sets `APPIMAGE` during normal launch and
   what happens in extraction mode.
7. Run the complete network-blocked suite:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

8. Record the exact pass, skip, warning, and duration result in this file before
   changing tests.
9. Inspect the current AppImage and tar artifact without changing source files.
10. Confirm that automated tests still block sockets, DNS, and stdlib HTTP.

### Phase 1: Settings Tests

Add tests before production changes for the saved test-release choice.

1. Missing setting returns `False`.
2. Canonical false value returns `False`.
3. Canonical true value returns `True`.
4. Empty text returns the safe `False` default.
5. Whitespace-padded text returns the safe default unless canonicalization is
   explicitly specified by the implementation contract.
6. Mixed-case or malformed text returns `False`.
7. Non-string store values return `False`.
8. Store read failure returns `False`.
9. Saving `False` writes the canonical false value.
10. Saving `True` writes the canonical true value.
11. Saving non-boolean values fails without writing.
12. Store write failure is reported and does not update active GUI state.
13. A successful round trip preserves both values.
14. Existing endpoint, model, confidence, quarantine, and history settings stay
    unchanged.

Implement only the setting key and small load/save functions needed to pass
these tests. Do not add last-check times because checks are manual-only.

### Phase 2: Version And Release Parsing Tests

Create a GUI-neutral release module and test it with Python data or fake JSON.
No test may use a live HTTP request.

#### Response Boundaries

1. Empty response body is rejected.
2. Whitespace-only response is rejected.
3. Invalid UTF-8 is rejected safely.
4. Invalid JSON is rejected safely.
5. Truncated JSON is rejected safely.
6. A top-level object is rejected when a list is required.
7. A top-level scalar or null is rejected.
8. An empty release list returns a no-update result.
9. A metadata response at the exact configured byte limit is accepted when
   otherwise valid.
10. A metadata response one byte over the limit is rejected before unbounded
    allocation.
11. Excessive release counts are bounded or rejected deterministically.
12. Unknown fields are ignored without weakening required-field validation.

#### Required Release Fields

1. Missing tag, draft flag, pre-release flag, notes, publication identity, or
   assets are handled according to an explicit schema.
2. Wrong field types are rejected; booleans must not be accepted as integers.
3. Blank tag names are rejected.
4. Draft releases are always ignored.
5. Stable mode ignores pre-releases.
6. Test mode includes valid pre-releases and stable releases.
7. Malformed release entries do not crash the whole check.
8. If all entries are malformed or unusable, return a clear metadata error or
   no-usable-release result as fixed by tests; do not silently claim the app is
   current when metadata could not be trusted.
9. Remote release notes remain plain text.
10. Very large notes are truncated to a safe display limit with an explicit
    indication, without altering version selection.

#### Version Boundaries

1. Installed version equal to latest version returns up to date.
2. Installed version newer than every release returns up to date.
3. One patch version newer is selected.
4. One minor version newer is selected.
5. One major version newer is selected.
6. Numeric ordering handles `0.10.0` as newer than `0.9.0`.
7. A stable release is newer than its corresponding pre-release.
8. Test mode selects the highest eligible release independent of API order.
9. Stable mode selects the highest stable release independent of API order.
10. Invalid installed version produces a local configuration error and never
    offers an update.
11. Invalid remote versions are skipped and cannot become candidates.
12. Leading/trailing whitespace is not accepted unless explicitly normalized by
    the fixed tag parser.
13. Downgrades are never offered.
14. Same-version rebuilds are never offered.
15. Local/development version syntax is rejected or handled by one explicit,
    tested rule. Do not guess from string comparison.

#### Asset Selection

1. A release with exactly one expected Linux x86-64 AppImage is accepted.
2. Missing AppImage is rejected as unusable.
3. Duplicate exact-name AppImages are rejected as ambiguous.
4. An ARM AppImage is rejected.
5. A tarball is not selected as an AppImage.
6. A filename that only contains the expected name is rejected.
7. A filename with path separators is rejected.
8. A zero-byte asset is rejected.
9. A negative, boolean, non-integer, or absent size is rejected.
10. An asset at the exact maximum size is accepted.
11. An asset one byte over the maximum is rejected.
12. A missing, malformed, wrong-algorithm, uppercase/lowercase, or wrong-length
    digest follows one strict documented rule.
13. Only the exact selected asset URL is returned to the downloader.
14. Asset API and browser URLs with unsupported schemes are rejected.
15. Duplicate releases with the same normalized version cannot cause unstable
    selection; reject ambiguity or apply one tested deterministic rule.

Implement immutable release/result models, strict parsing, channel filtering,
version comparison, and exact asset selection only after observing these tests
fail.

### Phase 3: Metadata Transport Tests

Create a transport dedicated to public GitHub update metadata. Do not modify the
vision transport to permit public Internet access.

1. Only HTTPS metadata URLs are accepted.
2. User information, fragments, malformed ports, and unexpected paths are
   rejected.
3. The initial metadata host must be the fixed approved GitHub API host.
4. No authentication token is required for public release checks.
5. The request sends a fixed product user agent and an appropriate GitHub API
   media type.
6. The request does not send endpoint settings, paths, machine IDs, or history.
7. Connection timeout produces a safe user-facing error.
8. Read timeout produces a safe error.
9. DNS, TLS, and connection failures do not expose raw exceptions.
10. HTTP 200 with valid bounded content succeeds.
11. HTTP 204, redirects outside the explicit policy, rate limiting, client
    errors, and server errors produce distinct safe results where useful.
12. Metadata redirects are rejected unless there is a concrete documented need
    and an exact allowlist test.
13. Declared content length over the limit is rejected before reading the body.
14. A missing content length still uses a hard streaming read limit.
15. A lying content length cannot bypass the hard limit.
16. Cancellation before request, during connect where supported, and during
    body read stops work and returns a cancellation result.
17. The transport performs no automatic retry.
18. Every transport test injects fake connections or responses.
19. The autouse no-network fixture remains active and passes.

### Phase 4: Streaming Download Tests

Build the artifact downloader behind an injected transport/filesystem boundary.

1. Require HTTPS for every download hop.
2. Permit only the exact documented GitHub release-asset host flow.
3. Reject redirect loops and more than the configured redirect limit.
4. Reject HTTPS-to-HTTP downgrade.
5. Reject redirects to arbitrary hosts, IP literals, user-info URLs, fragments,
   and malformed locations.
6. Do not forward authorization or sensitive headers across hosts.
7. Resolve relative redirect locations safely if the policy allows them.
8. A successful download writes fixed-size chunks instead of one full response.
9. Progress is monotonic and never exceeds the expected size.
10. Unknown content length does not disable the maximum-size limit.
11. Declared content length that differs from release metadata is rejected.
12. Zero-byte response is rejected.
13. Early EOF is rejected.
14. Extra bytes beyond expected size are rejected.
15. A body exactly at the expected and maximum boundaries succeeds.
16. A body one byte above either boundary fails and removes the temporary file.
17. Connection failure before writing leaves no temporary file.
18. Failure after partial writing removes the partial file.
19. Cancellation before writing creates no file.
20. Cancellation after partial writing closes and removes the partial file.
21. Destination write failure returns a safe error and removes what can be
    removed without touching unrelated files.
22. Disk-full failure is reported safely.
23. Temporary filenames cannot be controlled by remote asset names.
24. Existing files are never overwritten by the download stage.
25. SHA-256 is computed incrementally while streaming or in one bounded
    file-reading verification pass.
26. Matching digest succeeds.
27. One-byte digest mismatch fails, removes the untrusted temporary artifact,
    and never calls installation.
28. Cancellation and errors do not leave an executable file.
29. Downloaded bytes are never logged.

### Phase 5: Installation Detection And Validation Tests

Create a small GUI-neutral installation module. It must classify the running
installation before enabling installation.

1. Missing `APPIMAGE` reports a non-AppImage installation.
2. Empty or whitespace-only `APPIMAGE` is invalid.
3. A relative path is rejected.
4. A nonexistent path is rejected.
5. A directory is rejected.
6. A non-regular file is rejected.
7. A symlink path follows one safe explicit rule. Prefer rejecting ambiguous
   symlink launch paths rather than replacing a link unexpectedly.
8. A path with a nonexistent parent is rejected.
9. A non-writable AppImage is rejected.
10. A non-writable parent directory is rejected.
11. A read-only filesystem is rejected.
12. AppImage extraction mode is detected and cannot self-install.
13. Source, test, editable, and portable-tar launches cannot self-install.
14. A valid absolute regular executable AppImage in a writable directory is
    eligible.
15. Validation uses the same exact path later passed to installation to avoid a
    check/use mismatch where feasible.
16. File identity is captured and revalidated immediately before replacement so
    a changed AppImage is not backed up or replaced silently.
17. The application does not modify the AppImage during detection.

### Phase 6: Backup, Replacement, And Recovery Tests

Fix exact sibling names in tests. Derive them locally from the validated
AppImage path, not from remote input. Use a unique temporary download name and
one deterministic backup name that the GUI can explain.

1. Installation refuses an unverified download.
2. Installation refuses a missing temporary file.
3. Installation refuses a non-regular temporary file.
4. Installation rechecks size and SHA-256 before replacement.
5. Installation checks enough free space for the chosen backup strategy and
   filesystem behavior.
6. Exact required free space succeeds.
7. One byte below required free space fails before changing the AppImage.
8. The temporary file must be in the same parent directory/filesystem needed
   for atomic final replacement.
9. The new file receives safe executable permissions based on a fixed policy,
   not remote mode bits.
10. Data and directory synchronization calls are injected where needed so
    ordering and failures can be tested.
11. The current AppImage remains unchanged until the new artifact is fully
    downloaded and verified.
12. Existing backup handling follows one fixed rule. Prefer replacing only the
    known prior backup after validation; never overwrite an arbitrary
    directory, symlink, or unrelated file.
13. Backup creation failure leaves the current AppImage unchanged.
14. Final replacement failure triggers recovery from the backup.
15. Successful recovery reports installation failure, not success.
16. Recovery failure reports exact safe manual recovery paths without deleting
    either surviving file.
17. A successful installation leaves the new verified bytes at the original
    AppImage path.
18. A successful installation leaves one prior AppImage backup.
19. A successful installation removes its temporary file.
20. No operation touches source images, quarantine files, settings outside the
    update option, or scan history.
21. A second installation run handles the existing known backup safely.
22. Two attempted installs are serialized; the second is rejected as busy.
23. AppImage identity change between check and replacement aborts safely.
24. New artifact identity change between verification and replacement aborts.
25. Restart is not attempted when installation fails.

Do not claim the pair of backup and final rename operations is one atomic
transaction. The required guarantee is that the final placement uses an atomic
same-filesystem replacement and every intermediate failure has a tested
recovery path.

### Phase 7: Restart Tests

Use an injected process launcher and shutdown boundary.

1. Successful installation offers **Restart Now** and **Later**.
2. Choosing **Later** does not start a process or close the app.
3. Choosing **Restart Now** launches the exact validated AppImage path without
   shell parsing.
4. Remote strings never become command arguments.
5. Restart launch failure keeps the current process open and reports that the
   installed AppImage can be started manually.
6. Successful launch requests normal application shutdown.
7. Active scan or quarantine work cannot be abandoned without the existing
   safe close/cancellation behavior.
8. Tests do not start a real external process.

### Phase 8: GUI And Worker Tests

Use Qt tests with fake release, download, install, and process services.

#### Check Action

1. The update action is visible and keyboard accessible while idle.
2. Merely launching the app performs no update request.
3. Opening settings performs no update request.
4. Scanning, testing the server, viewing history, or selecting folders performs
   no update request.
5. Selecting **Check for Updates** starts exactly one background check.
6. A duplicate click cannot start a second check.
7. The GUI remains responsive while checking.
8. The check action has a clear busy state.
9. Closing during a check cancels the operation and does not deliver stale
   signals to a destroyed window.
10. An up-to-date result shows the installed version.
11. A no-usable-release result is distinct from a transport or malformed-data
    failure.
12. Errors use short safe text and never show raw exception representations.

#### Channel Setting

1. Stable-only is shown and used by default.
2. Enabling **Include test releases** requires Save before active state changes.
3. Cancel preserves the prior active and persisted value.
4. Save failure leaves the prior active value in force and keeps the dialog
   available for retry.
5. A new manual check reads the current active channel.
6. Changing the option does not alter an update result already displayed.
7. The interface labels test releases clearly.

#### Update Available Dialog

1. Show installed version, available version, stable/test label, bounded plain
   release notes, and human-readable size.
2. No download starts before the user confirms.
3. Cancel closes the offer without writing a file.
4. Unsupported installation type explains that automatic installation is not
   available; it must not imply that replacement occurred.
5. Invalid or missing release notes do not break layout.
6. Long notes remain bounded and scrollable.

#### Download And Install

1. Confirmation starts exactly one background download.
2. Progress starts at zero and is monotonic.
3. Cancel requests cancellation and waits for safe cleanup.
4. Download failure re-enables a retry path.
5. Digest failure clearly says verification failed and never enables install.
6. Successful verification asks separately for installation confirmation.
7. Rejecting installation leaves the current AppImage unchanged and removes or
   safely handles the verified temporary artifact according to the fixed rule.
8. Installation runs off the GUI thread where filesystem synchronization may
   block.
9. The GUI remains responsive during installation.
10. Successful installation offers restart choices.
11. Installation and recovery errors show useful safe paths when manual action
    is required.
12. Update operation state cannot be confused with scan, server-test, or
    quarantine worker signals.
13. Stale signals from an earlier check/download are ignored.
14. Existing scan and quarantine control-state tests continue to pass.
15. Closing during download or installation follows explicit safe behavior. Do
    not terminate a thread while replacement is in its critical section.

Prefer a dedicated update controller/worker over adding unrelated update cases
to the shared scan/connection/quarantine operation thread. Keep Qt widgets thin;
release selection, download policy, verification, and installation stay
GUI-neutral.

### Phase 9: Packaging And Release Workflow Tests

After F-010 merges, extend its packaging tests before workflow changes.

1. Package version is read from the declared version authority.
2. AppImage filename contains the same normalized version.
3. AppStream metadata version and date agree with the release inputs or are
   generated/validated by tooling.
4. Stable tags normalize to the package version.
5. Test tags normalize to the exact pre-release package version.
6. A mismatched tag fails before building or publishing.
7. Unsupported tag forms fail.
8. The release asset set contains the AppImage, portable tarball if still part
   of F-010, and checksum/integrity metadata required by the contract.
9. Checksums name exact artifacts and reject duplicate names.
10. The release workflow runs the complete network-blocked suite before build.
11. The workflow builds artifacts before creating or publishing a release.
12. The release starts as a draft.
13. Assets upload before publication.
14. Verification runs before publication.
15. Pull requests cannot publish.
16. Normal branch pushes cannot publish unless that exact trigger is explicitly
    approved.
17. Only the publication job receives `contents: write`.
18. Actions and downloaded packaging tools remain pinned according to project
    policy.
19. Workflow artifact checks remain available for non-release packaging runs.
20. No signing or repository credential is embedded in the application.

Use a release trigger that cannot accidentally publish from ordinary feature
work. If tag-driven publication is selected, document the exact operator steps
and ensure the version/tag consistency check runs before publication. If manual
workflow approval is selected, record and validate the requested tag/version.

### Phase 10: Documentation

Update durable documentation only after behavior is implemented and tested.

1. Add F-011 product decisions to `project-brief.md`.
2. Keep updater details separate from private-LAN image transfer language.
3. Update `README.md` with **Check for Updates**, stable/test behavior, download
   size expectations, backup location, restart behavior, and failure recovery.
4. State that checking contacts GitHub and reveals the user's IP address and
   request timing to GitHub and its delivery infrastructure.
5. State that no image, image path, endpoint, history, credential, or machine ID
   is sent during an update check.
6. State that checks occur only after explicit user action.
7. State that the first updater-enabled release needs one manual installation.
8. State that automatic installation supports AppImage only.
9. Explain source and portable-tar behavior accurately.
10. Explain how to identify and restore the one retained backup manually.
11. Explain stable versus test releases and the additional risk of test builds.
12. Document the HTTPS/SHA-256 trust model without claiming independent release
    signature verification.
13. Document the release operator procedure beside the workflow or in packaging
    documentation.
14. Do not describe F-011 as a cross-platform updater.

## Proposed Module Boundaries

Names may change to match merged F-010 conventions, but responsibilities must
remain separated.

### `src/img_ai_filter/update_release.py`

- Channel enum or equivalent stable/test value.
- Immutable release and asset records.
- Strict GitHub JSON parsing.
- Version normalization and comparison.
- Draft/pre-release filtering.
- Exact asset selection.
- Safe release notes and size presentation data.
- No HTTP, filesystem mutation, Qt widgets, or process launch.

### `src/img_ai_filter/update_transport.py`

- Bounded GitHub metadata requests.
- Strict HTTPS and host/path policy.
- Narrow redirect handling for release assets.
- Streamed file download.
- Timeouts, cancellation, progress, size enforcement, and digest calculation.
- Injectable connection and filesystem boundaries.
- No vision endpoint behavior.

### `src/img_ai_filter/update_install.py`

- Installation-kind detection.
- `APPIMAGE` path validation.
- Current-file identity capture and revalidation.
- Free-space and sibling-path validation.
- Executable permission policy.
- Backup, atomic final replacement, and recovery.
- Structured outcomes with safe user-facing details.
- No HTTP or Qt widgets.

### Qt Integration

- Dedicated update worker/controller lifecycle.
- Update dialog or small sequence of dialogs.
- Settings option for test releases.
- Progress, cancellation, installation confirmation, and restart prompt.
- Inject release, download, install, and process services in tests.

Avoid new helpers that only wrap one line. Keep each phase minimal and reuse
existing settings and worker conventions where their contracts fit.

## Error And User Message Contract

Use concise messages that state what happened and what remains safe.

Required categories:

- App is up to date.
- No compatible release is available.
- GitHub could not be reached.
- GitHub rate limited the check.
- Release information was invalid.
- No compatible Linux x86-64 AppImage was found.
- Download was cancelled.
- Download failed; current AppImage was not changed.
- Download verification failed; current AppImage was not changed.
- Automatic installation is unavailable for this installation type.
- AppImage directory is not writable.
- Not enough disk space.
- Installation failed and the original AppImage was restored.
- Recovery failed; show the surviving original/backup/new paths safely.
- Update installed; restart now or later.
- Restart failed; start the installed AppImage manually.

Do not show raw response bodies, raw exceptions, authorization headers, query
strings, or an attacker-controlled URL. Logging, if any, must follow the same
rule.

## Required Verification

1. Run focused settings and release tests after Phases 1 and 2.
2. Run focused transport/download tests after Phases 3 and 4.
3. Run focused installer/restart tests after Phases 5 through 7.
4. Run focused Qt tests after Phase 8.
5. Run packaging/workflow tests after Phase 9.
6. Run `git diff --check`.
7. Run the complete suite with network blocking:

   ```text
   QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
   ```

8. Confirm no test bypasses the no-network fixture.
9. Build the AppImage through the approved F-010 command.
10. Inspect its version, filename, executable mode, and runtime environment.
11. Test metadata and download behavior with fakes before any manual live check.
12. Perform a manual update using disposable copies of two AppImage versions.
13. Never use the only copy of an AppImage for destructive manual testing.
14. Record focused and complete test results in this file.

## Required Desktop GUI Checklist

After implementation and all automated tests pass, ask the user to run the
exact launch command appropriate to the merged packaging branch. At minimum,
provide this source-launch fallback:

```text
python -m img_ai_filter
```

Ask the user to use disposable AppImage copies and complete this checklist:

1. Start the app and confirm no update dialog or network activity appears by
   itself.
2. Open settings and confirm **Include test releases** is off by default.
3. Select **Check for Updates** and confirm a clear checking state appears.
4. Confirm an up-to-date build reports its current version clearly.
5. Enable test releases, save, reopen settings, and confirm the option persists.
6. Check again and confirm test releases are clearly labeled when available.
7. On a disposable older AppImage, review version, notes, size, and channel
   before accepting download.
8. Confirm progress appears and the app remains responsive.
9. Cancel one download and confirm the current AppImage still starts and no
   executable partial download remains.
10. Retry, complete the download, and confirm installation asks separately.
11. Install and choose **Later**; confirm the app stays open.
12. Close and start the same AppImage path; confirm the new version appears.
13. Confirm one backup of the old AppImage exists.
14. Repeat with a non-writable disposable directory and confirm installation is
    refused without changing files.
15. Launch from source or the portable tarball and confirm it does not claim it
    can replace itself.
16. Confirm normal folder selection, server testing, scanning, candidate review,
    and quarantine still behave as before.

Ask the user to reply with exactly `Approved` when every step passes, or provide
the error text, a screenshot, and the checklist step that failed.

Do not ask about commits, pushes, or pull requests until the user explicitly
approves the desktop checklist.

## Implementation Handoff Checklist

The implementation agent must follow this order:

1. Confirm F-010 is merged or obtain explicit permission to work on its branch.
2. Reconcile this plan with merged code and report material conflicts before
   implementation.
3. Record the baseline suite.
4. Write failing Phase 1 tests and run them.
5. Implement only Phase 1 and rerun focused tests.
6. Repeat the failing-test-first cycle for every later phase.
7. Do not delegate production implementation until the main session has written
   and observed the relevant failing tests.
8. Keep all automated network use fake and injected.
9. Preserve unrelated worktree files, including `packaging-build/`.
10. Review every delegated diff against this contract.
11. Run the complete suite only after focused tests pass.
12. Update documentation to match implemented behavior, not planned behavior.
13. Give the user the exact GUI command and checklist.
14. Wait for explicit `Approved`.
15. Only after approval ask whether the user wants a PR, commit, or push.

## Acceptance Criteria

F-011 is complete only when all of these are true:

1. Update checks occur only after explicit user action.
2. Stable-only and opt-in test channel behavior are persisted and tested.
3. Release parsing and version comparison reject malformed and ambiguous input.
4. Only a newer compatible Linux x86-64 AppImage can be selected.
5. Downloads are HTTPS-only, bounded, streamed, cancellable, and verified.
6. The current AppImage is unchanged until verification completes.
7. Replacement retains one backup and has tested recovery behavior.
8. Source and portable-tar installations are never replaced.
9. Restart requires user confirmation and does not use shell parsing.
10. The GUI remains responsive and safe during check, download, installation,
    cancellation, shutdown, and stale signals.
11. The release workflow publishes only complete tested draft releases.
12. Package version, release tag, metadata, and artifact names agree.
13. Existing scan, LAN privacy, review, history, and quarantine contracts remain
    unchanged.
14. The complete network-blocked automated suite passes.
15. Packaged artifact inspection passes.
16. Durable documentation states the privacy and trust limits accurately.
17. The user completes and approves the desktop checklist.
