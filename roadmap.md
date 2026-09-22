# Product Roadmap

This roadmap divides the MVP into small, testable milestones. Each shipped milestone must leave the desktop application in a working state.

## Active Feature Register

### F-001: Candidate Scan Workflow

- **Status:** shipped 2026-09-20 (PR #5)
- **Tier:** Tier 1, core product workflow
- **Effort:** Medium after the KoboldCpp detector is available
- **Planning files:** `project-brief.md`, `roadmap.md`, `feature.md`
- **Likely implementation files:** main window, background scan worker, scan/detection boundary, tests, and README
- **Depends on:** shipped desktop folder-scanning foundation and F-003
- **Blocks:** quarantine workflow, because only reviewed candidates can be moved safely

Dependency graph:

```text
Milestone 1 shipped
        |
        v
F-001 workflow contract and controls
        |
        v
F-003 KoboldCpp detector
        |
        v
F-001 candidate-only results shipped
        |
        v
Milestone 4 quarantine workflow
```

Implementation order:

1. Agree on the user-visible scan states and candidate-result contract.
2. Remove the rejected thumbnail-first prototype before new implementation.
3. Complete F-003 and freeze its detector contract.
4. Write failing background-worker, workflow, and result-row tests.
5. Connect the existing scan control without changing folder-selection behavior.
6. Show candidate-only results, review check states, and skipped-analysis counts.
7. Complete automated and desktop GUI verification.

### F-002: Pre-trained Detector With LAN Vision Fallback

- **Status:** scrapped 2026-09-19 — replaced by F-003 after the user chose a KoboldCpp-only MVP to avoid packaged-model selection and unblock private manual testing
- **Tier:** Tier 1, required detection architecture
- **Effort:** Large because it includes dataset work, model evaluation, secure settings, bounded LAN communication, and cross-platform dependencies
- **Planning files:** `feature.md`, `project-brief.md`, `roadmap.md`, `README.md`, `evaluation/README.md`
- **Likely implementation files:** detector and evaluation modules, ONNX adapter and model metadata, endpoint configuration, OpenAI-compatible client, cascade orchestration, credential storage, background worker, main window, tests, and packaging configuration
- **Depends on:** shipped evaluation foundation, a representative labeled dataset, a redistributable pre-trained ONNX model, and a supported operating-system credential-store library
- **Blocks:** none; F-003 replaced this dependency

Postmortem: the packaged ONNX plus LAN fallback design required a 335-image licensed benchmark, model redistribution research, ONNX packaging, preprocessing, integrity checks, threshold tuning, and a cascade before the GUI could perform a useful scan. The user has no benchmark images suitable for the project and chose a user-managed KoboldCpp vision server instead. Completed endpoint validation, settings, secure credentials, strict result contracts, and evaluation tooling are retained. No ONNX runtime or production model was added.

The scrapped design would have classified every image first with a packaged
pre-trained ONNX model, then sent only below-threshold results to a LAN vision
server after consent. This description is retained as historical context and is
not the current MVP architecture.

Dependency graph:

```text
Evaluation foundation shipped
        |
        v
Representative labeled dataset
        |
        v
ONNX candidate research and holdout selection
        |
        v
Strict LAN vision client and secure settings
        |
        v
Classifier-first cascade evaluation
        |
        v
F-002 detector cascade shipped
        |
        v
F-001 candidate scan workflow completed
```

Implementation order:

1. Approve the detailed test-first contract in `feature.md`.
2. Build and validate the labeled tuning and holdout dataset.
3. Research redistributable ONNX classifiers and cross-platform credential storage.
4. Write failing configuration, credential, model-integrity, classifier, vision-client, cascade, privacy, worker, and GUI tests in the order defined by `feature.md`.
5. Select and freeze a primary classifier only after it passes every mandatory holdout target.
6. Implement the strict local-network Chat Completions client with consent, timeouts, no redirects, no retries, and redacted errors.
7. Evaluate the complete cascade with a recorded reference fallback model; never transfer benchmark validation to an untested user-selected model.
8. Integrate background scanning, candidate rows, review checkboxes, completion counts, retry, and safe shutdown.
9. Complete the automated suite and user desktop verification before any Git operation is proposed.

### F-003: KoboldCpp Vision Scan MVP

- **Status:** shipped 2026-09-20 (PR #5)
- **Tier:** Tier 1, core detection architecture
- **Effort:** Medium
- **Planning files:** `feature.md`, `project-brief.md`, `roadmap.md`, `README.md`, `evaluation/README.md`
- **Likely implementation files:** endpoint/settings integration, bounded image preparation, strict OpenAI-compatible client and parser, server detector, scan workflow, background worker, settings dialog, main window, tests, and runtime dependency configuration
- **Depends on:** shipped desktop foundation, existing scanner, and completed private-LAN endpoint validation
- **Blocks:** completion of F-001 and the quarantine workflow

Automated implementation and the live KoboldCpp desktop checklist are complete.
The user approved the GUI behavior on 2026-09-19, and PR #5 merged on
2026-09-20.

KoboldCpp runs the user-selected vision GGUF and matching `mmproj`. The app sends every supported image, one at a time, to a consented loopback or private-LAN OpenAI-compatible endpoint. It accepts only strict structured classifications, shows only screenshot/meme-style candidates, keeps every candidate unchecked, and never changes source files. The approved default base URL is `http://192.168.0.239:5001/v1/`, but it remains editable.

Dependency graph:

```text
Desktop foundation + scanner
        |
        v
Private-LAN endpoint and settings
        |
        v
Strict KoboldCpp client and parser
        |
        v
Background server-only scan workflow
        |
        v
F-001 candidate-only results shipped
```

Implementation order:

1. Approve the detailed test-first contract in `feature.md`.
2. Write failing base-URL, capability-discovery, and model-discovery tests.
3. Implement safe KoboldCpp endpoint joining and connection testing with fake transports.
4. Write failing image-preparation, request, response, privacy, and cancellation tests.
5. Implement bounded in-memory image encoding and the no-redirect, no-retry Chat Completions client.
6. Write failing server workflow, worker, consent, GUI-state, and result-row tests.
7. Connect **Scan Folder** and keep every server candidate unchecked.
8. Run the complete automated suite with live networking blocked.
9. Complete manual desktop verification against the user-managed KoboldCpp server before any Git operation.

### F-004: Safe Quarantine Workflow

- **Status:** shipped 2026-09-20 (PR #6)
- **Tier:** Tier 1, core product workflow
- **Effort:** Large because moving files safely requires path validation, change detection, no-overwrite behavior, verified cross-filesystem copies, durable records, partial-failure handling, background work, and cross-platform tests
- **Planning files:** `feature.md`, `project-brief.md`, `roadmap.md`, `README.md`
- **Likely implementation files:** quarantine planner/executor, settings, main window, platform integration, tests, and documentation
- **Depends on:** shipped F-001 candidate review workflow and stable candidate identity from F-005 image preparation work
- **Blocks:** restoration from quarantine and release-ready end-to-end workflow testing

Move only explicitly checked candidates after showing their exact source and destination paths. Preserve the source-relative directory tree, reject source/quarantine overlap, never overwrite a destination, verify that each source still matches the scanned file, and support other filesystems through copy verification before source removal. Remember and revalidate the quarantine folder. Write a durable local JSON Lines move record. Keep failed or conflicting rows checked for review and retry.

Dependency graph:

```text
F-001 candidate review shipped
        |
        v
F-005 source identity contract
        |
        v
F-004 quarantine planner and executor
        |
        v
F-004 confirmation and background GUI workflow
        |
        v
Milestone 4 shipped
```

Implementation order:

1. Approve the detailed test-first contract in `feature.md`.
2. Add immutable source identity to prepared images and candidates through F-005.
3. Write failing path, overlap, conflict, changed-file, log, copy, verification, cleanup, and partial-failure tests.
4. Implement the GUI-neutral quarantine planner, verified executor, and move record.
5. Write failing persisted-folder, confirmation, worker, progress, result-reconciliation, retry, and shutdown tests.
6. Add quarantine selection and **Move Checked to Quarantine** without adding deletion or restore.
7. Run the complete offline suite and artifact inspection.
8. Complete manual desktop verification with disposable same-drive and cross-drive sample data.

### F-005: Candidate Thumbnails

- **Status:** shipped 2026-09-20 (PR #6)
- **Tier:** Tier 1, review usability
- **Effort:** Medium because previews must be bounded, EXIF-corrected, generated off the GUI thread, kept in memory, and integrated without weakening scan or file safety
- **Planning files:** `feature.md`, `project-brief.md`, `roadmap.md`, `README.md`
- **Likely implementation files:** image preparation, scan workflow contract, main window, tests, and documentation
- **Depends on:** shipped F-003 bounded Pillow image preparation and F-001 candidate rows
- **Blocks:** F-004 changed-file validation through the shared source identity contract

Show a compact preview, approximately 96 by 96 pixels, beside every flagged candidate. Generate bounded PNG preview bytes during background image preparation, pass bytes only for candidates, and construct Qt pixmaps on the GUI thread. Keep path, category, reason, confidence, and unchecked review state visible. Never write thumbnail files or caches.

Dependency graph:

```text
F-003 bounded image preparation shipped
        |
        v
F-005 thumbnail and source identity tests
        |
        v
F-005 scan contract and compact candidate rows
        |
        +------> F-004 safe changed-file validation
```

Implementation order:

1. Approve the detailed test-first contract in `feature.md`.
2. Write failing digest, byte-count, format, orientation, dimensions, transparency, limit, failure, and source-immutability tests.
3. Extend in-memory image preparation with source identity and bounded 96-pixel PNG previews.
4. Write failing scan-contract and GUI tests.
5. Pass preview bytes and identity only with candidates and render compact list icons.
6. Verify responsive GUI behavior, placeholder behavior, rescans, stale-result protection, and shutdown.
7. Run the complete offline suite and manual desktop checklist with F-004.

### F-006: Scan Timing and Activity History

- **Status:** shipped 2026-09-21 (PR #7)
- **Tier:** Tier 2, workflow visibility and local records
- **Effort:** Medium because complete attempt timing must cover discovery, live progress, cancellation, worker failures, safe shutdown, durable bounded history, corruption recovery, and a testable Qt dialog
- **Planning files:** `feature.md`, `project-brief.md`, `roadmap.md`, `README.md`
- **Likely implementation files:** activity-history model and persistence, main-window timing and dialog integration, worker result retention, tests, and documentation
- **Depends on:** shipped F-001/F-003 background candidate scan workflow and the existing injected settings store
- **Blocks:** none; it provides performance evidence useful during Milestone 6 release-readiness testing

Measure every scan attempt accepted after transfer consent and every confirmed quarantine batch. Show a live scan timer and final scan or quarantine duration. Store the newest 100 combined local events. Scan events contain aggregate counts but no image-level content. Quarantine events contain exact source and destination paths with safe per-file outcomes. Do not store endpoint addresses, credentials, image bytes, or raw exceptions. Provide an expandable in-app activity dialog and an explicitly confirmed clear action that leaves quarantine move logs unchanged.

Dependency graph:

```text
F-001/F-003 background scan workflow
                |
                v
F-006 deterministic attempt timing
                |
                v
F-006 bounded local history storage
                |
                v
F-006 history dialog and clear action
                |
                v
Milestone 6 performance evidence
```

Implementation order:

1. Approve the detailed test-first contract in `feature.md`.
2. Record the full offline regression baseline.
3. Write failing duration-format, schema, corruption, retention, persistence-failure, clear, and privacy tests.
4. Implement the GUI-neutral versioned history module over the existing injected settings-store boundary.
5. Write failing live-timer, terminal-state, retry, worker-failure, cancellation, and close tests with injected clocks.
6. Add exact-once scan-attempt timing and history recording without changing `ScanSummary`.
7. Write failing history-dialog and confirmed-clear tests.
8. Add the idle-only history dialog, newest-first records, empty state, and clear action.
9. Run the complete network-blocked suite and inspect privacy and generated artifacts.
10. Complete manual desktop verification before any Git operation.

### F-007: Candidate Bulk Selection

- **Status:** shipped 2026-09-21 (PR #8)
- **Tier:** Tier 1, review usability
- **Effort:** Small because one toggle button reuses the existing review rows and control-state update path
- **Planning files:** `feature.md`, `roadmap.md`, `project-brief.md`, `README.md`
- **Likely implementation files:** main window, GUI review tests, and documentation
- **Depends on:** shipped F-001/F-003 candidate rows and the F-004 checked-row selection contract
- **Blocks:** none; it improves review speed before F-008 and Milestone 6

Add one bulk-selection control beside the result status. It selects every current candidate when any row is unchecked and clears every row when all rows are checked. Every new scan candidate remains unchecked. Bulk changes touch only Qt check states and never start a scan or move, change settings, write history, or alter a source file.

Dependency graph:

```text
F-001 candidate rows shipped
        |
        v
F-007 bulk selection button
        |
        v
F-004 quarantine selection and confirmation unchanged
```

Implementation order:

1. Approve the test-first plan in `feature.md`.
2. Record the network-blocked regression baseline.
3. Write failing empty-state, unchecked-default, and bulk-state GUI tests.
4. Write failing lifecycle, rescan, quarantine, and side-effect tests.
5. Implement the button, control-state calculation, and toggle handler in the main window.
6. Run focused GUI, scan, and quarantine tests.
7. Update durable documentation.
8. Run the complete offline suite and inspect artifacts and privacy.
9. Complete manual desktop verification before any Git operation.

### F-009: Confidence-Based Candidate Selection

- **Status:** shipped 2026-09-21 (PR #9)
- **Tier:** Tier 1, review usability
- **Effort:** Medium because an editable threshold adds validated persistence, a settings dialog, scan-lifecycle boundaries, mixed checkbox states, and quarantine-safety regression coverage
- **Planning files:** `feature.md`, `roadmap.md`, `project-brief.md`, `README.md`
- **Likely implementation files:** settings persistence, main window and settings dialog, GUI review tests, settings tests, and documentation
- **Depends on:** shipped F-001/F-003 candidate confidence results, F-004 checked-row quarantine contract, and F-007 bulk selection
- **Blocks:** none; it reduces repetitive review while preserving manual confirmation

Automatically check newly rendered candidates when their raw model-reported confidence is at or above a persisted user threshold. Default to 90% and allow integer settings from 50% through 100%. Apply a changed threshold only to later scan results so current manual choices are never overwritten. Keep bulk selection, exact-path quarantine confirmation, source validation, no-overwrite behavior, and every other file-safety rule unchanged. Confidence is not a calibrated probability, and automatic selection never starts a move.

F-008 remains reserved for the previously planned reliability audit. F-009 is
used here to avoid assigning that permanent ID to unrelated work.

Dependency graph:

```text
F-001/F-003 candidate results
            |
            v
F-007 bulk selection + F-004 quarantine safety
            |
            v
F-009 validated threshold persistence
            |
            v
F-009 settings dialog and next-scan auto-selection
            |
            v
Manual review and explicit quarantine confirmation unchanged
```

Implementation order:

1. Approve the detailed test-first contract in `feature.md`.
2. Record the complete network-blocked regression baseline.
3. Write failing missing, malformed, boundary, read-failure, write-failure, and round-trip threshold-setting tests.
4. Implement the GUI-neutral integer threshold contract with a safe 90% default and a 50% through 100% range.
5. Write failing Settings-button, dialog, Save, Cancel, persistence-failure, retry, and busy-state tests.
6. Add the small settings dialog and load the active threshold without changing current review rows.
7. Write failing raw-confidence boundary, mixed-row, bulk-selection, rescan, restart, stale-signal, side-effect, and quarantine-readiness tests.
8. Initialize new result-row check states from the active threshold while leaving existing scan and quarantine data contracts unchanged.
9. Update durable documentation without describing confidence as a calibrated probability.
10. Run focused tests, the complete offline suite, diff and artifact checks, and the privacy review.
11. Complete manual desktop verification before any Git operation.

### F-010: Self-Contained Linux Test Distribution

- **Status:** shipped 2026-09-22 (PR #10)
- **Tier:** Tier 2, release readiness and real-data testing
- **Effort:** Large because a portable Qt desktop build requires a frozen Python runtime, native-library and plugin collection, repeatable artifact construction, clean-system smoke tests, desktop metadata, license notices, and Fedora compatibility checks
- **Planning files:** `feature.md`, `roadmap.md`, `project-brief.md`, `README.md`
- **Likely implementation files:** PyInstaller specification and hooks, Linux packaging scripts, application resource loading and icon assets, desktop/AppStream metadata, packaging tests, Linux CI workflow, dependency constraints, and release documentation
- **Depends on:** shipped F-001, F-003, F-004, F-005, F-006, F-007, and F-009 workflows; a normal x86-64 Linux desktop remains the host platform
- **Blocks:** convenient Fedora real-data testing without a separately installed Python environment and informs the broader Milestone 6 compatibility audit

Produce two x86-64 Linux test artifacts from one validated PyInstaller
one-directory build: an AppImage for one-file launch and a compressed portable
directory as a no-FUSE fallback. Bundle CPython, application code, PySide6/Qt,
Pillow, keyring, and their required Python/native runtime components. Keep
KoboldCpp and its vision model external. Treat this as a test distribution, not
a signed public release or a claim that Linux kernel, graphics, display-server,
desktop-portal, and base C-library requirements can be bundled away.

Dependency graph:

```text
Shipped desktop workflows through F-009
                    |
                    v
F-010 frozen one-directory build + artifact tests
                    |
                    v
F-010 portable tarball + AppImage
                    |
                    v
Fedora x86-64 real-data acceptance
                    |
                    v
Milestone 6 compatibility evidence
```

Implementation order:

1. Approve the detailed test-first packaging contract in `feature.md`.
2. Record the complete network-blocked application baseline and inspect the clean build inputs.
3. Write failing metadata, resource, frozen-launch, image-codec, settings-persistence, privacy, and artifact-structure tests.
4. Add the smallest application identity and resource-loading changes required by a frozen Linux executable.
5. Pin packaging tools and create a deterministic PyInstaller one-directory build for Linux x86-64.
6. Prove the frozen program starts without system Python or a source checkout and retains the existing private-LAN, scan, and quarantine contracts.
7. Create the compressed portable-directory artifact and AppImage from the same tested payload.
8. Add Linux CI artifact construction, checksums, license notices, and troubleshooting documentation without publishing a release automatically.
9. Run the complete offline suite, artifact inspection, clean-environment smoke tests, and Fedora manual checklist.
10. Wait for explicit desktop approval before proposing any Git operation.

### F-011: AppImage Update Checks and Installation

- **Status:** shipped 2026-09-22 (PR #12)
- **Tier:** Tier 2, release distribution and maintenance
- **Effort:** Large because executable replacement requires strict release parsing, isolated public-Internet transport, streamed downloads, integrity verification, recoverable same-filesystem replacement, release automation, responsive GUI progress, and failure testing
- **Planning files:** `feature.md`, `roadmap.md`, `project-brief.md`, `README.md`
- **Likely implementation files:** update release model and transport, AppImage installer, settings, main window and update worker, Linux packaging scripts and metadata, GitHub release workflow, tests, and release documentation
- **Depends on:** shipped F-010 Linux AppImage packaging and a stable GitHub release process
- **Blocks:** none; it removes repeated manual AppImage downloads after one updater-enabled release is installed manually

Provide an explicit **Check for Updates** action that contacts GitHub only when
selected. Stable releases are the default, with a saved option to include test
pre-releases. When a newer compatible Linux x86-64 AppImage exists, show its
version, channel, notes, and size before downloading. Stream and verify the
complete artifact, replace only the currently running AppImage, retain one
recovery backup, and ask before restarting. Source and portable-tar builds may
check availability but must never replace their installation. Existing
AppImages without updater code require one final manual download to bootstrap
this feature.

Dependency graph:

```text
F-010 accepted AppImage packaging
                |
                v
Stable version and draft-first GitHub release process
                |
                v
Strict release discovery + optional test channel
                |
                v
Streamed verified AppImage download
                |
                v
Recoverable replacement + explicit restart
```

Implementation order:

1. Approve the detailed test-first contract in `feature.md`.
2. Complete F-010 acceptance and record the network-blocked regression baseline.
3. Write failing settings, version, release-schema, channel, and asset-selection tests.
4. Implement the GUI-neutral release model and manual-only metadata check through an injected transport.
5. Write failing HTTPS, redirect, response-limit, streaming, cancellation, truncation, and digest tests.
6. Implement the dedicated GitHub metadata transport and bounded streaming downloader without weakening private-LAN vision transport rules.
7. Write failing installation-kind, path, permission, space, temporary-file, backup, replacement, recovery, and restart tests.
8. Implement AppImage-only verified installation with one retained backup; never replace source or portable-tar installations.
9. Write failing update-dialog, busy-state, progress, confirmation, cancellation, error, close, and stale-signal GUI tests.
10. Add **Check for Updates**, the saved **Include test releases** option, explicit download/install consent, and restart choice.
11. Add a draft-first release workflow with consistent package versions, tags, artifact names, and SHA-256 metadata.
12. Update durable documentation, run focused tests and the complete offline suite, inspect packaged artifacts, and complete the desktop GUI checklist before any Git operation.

## Milestone 1: Desktop Foundation and Folder Scan

**Status:** shipped 2026-09-19 (PR #1). Native folder-picker follow-up shipped 2026-09-19 (PR #2).

- Create the Python project and test structure.
- Add a PySide6 desktop window.
- Let the user select one source folder.
- Recursively find PNG, JPEG, WebP, BMP, and TIFF files.
- Do not follow symbolic links.
- Show discovered image paths in a review list.
- Keep scanning and file-system logic separate from the GUI.

Success: A user can launch the app, select a folder, and see its supported images without changing any files.

## Milestone 2: Controlled Candidate Scan Workflow

**Status:** shipped 2026-09-20 (PR #5) as F-001 and F-003.

- Keep source-folder selection separate from scanning.
- Disable **Scan Folder** until a source folder is selected.
- Clear prior results when a different folder is accepted.
- Preserve the current folder and results when folder selection is cancelled.
- Start discovery and candidate detection only after the user selects **Scan Folder**.
- Show a clear busy state and prevent duplicate scans.
- Show only flagged candidates, never the complete ordinary-photo list.
- Show each candidate's path, flagging reason, confidence, and review check state.
- Start every unbenchmarked KoboldCpp candidate unchecked.
- Omit unresolved uncertain images and include them in the skipped-analysis count.
- Allow a completed or failed scan to be retried.
- Replace prior results and review states on every rescan.
- Show clear empty and failure states.
- Keep all scanning and review actions read-only.

Thumbnails are not required for this milestone. They can be reconsidered after useful candidate detection works.

Success: A user explicitly starts a scan and reviews only explained trash candidates without changing any source file.

The unchecked-default requirement above records the shipped Milestone 2
behavior. F-007 added **Select All**/**Clear All** without changing it. F-009
supersedes that initial-row rule with a saved high-confidence threshold while
keeping manual review and explicit quarantine confirmation.

## Milestone 3: KoboldCpp Candidate Detection

**Status:** shipped 2026-09-20 (PR #5) as F-003.

This milestone is tracked as F-003 and supplies the detector required to complete F-001 and Milestone 2. F-002 remains as a scrapped historical record. The server-only MVP does not package or train a model.

Evaluation infrastructure landed 2026-09-19: a strict result contract, manifest validation, dependency-free metrics, evaluation orchestration, and offline JSON/Markdown reports (`detection.py`, `evaluation.py`, `eval_cli.py`). The geometry baseline and private dataset validator remain available for future accuracy work, but do not block the experimental KoboldCpp MVP.

- Validate KoboldCpp version, vision capability, and loaded model before scanning.
- Send every supported image only after consent to a user-managed vision server on loopback or the private local network.
- Reject public Internet endpoints and redirects, and report failed analyses as skipped.
- Return a candidate decision, user-readable reason, and confidence for each analyzed image.
- Keep every server candidate unchecked until that exact model is separately benchmarked.
- Omit unresolved uncertain images and report their count.
- Exclude ordinary photos from results.
- Handle unreadable or damaged images without stopping the scan.
- Clearly disclose that every supported image is transferred to the configured LAN server using HTTP or HTTPS.

Success: The app identifies likely screenshots and memes, explains each result, and leaves the final decision to the user.

The unchecked bullet records the shipped F-003 contract. F-009 later adds an
explicit user-controlled confidence threshold without claiming that arbitrary
model confidence is calibrated or benchmarked accuracy.

## Milestone 4: Quarantine Workflow

**Status:** shipped 2026-09-20 as F-004 and F-005 (PR #6).

- Let the user select a quarantine folder.
- Detect unsafe choices, including overlap with source folders.
- Show a confirmation summary before any move.
- Move only checked files after explicit confirmation.
- Handle name conflicts and partial failures safely.
- Record enough information to explain each result.

Success: A user can move confirmed files to quarantine without deletion or silent data loss.

## Milestone 5: Local Review Labels

**Status:** scrapped 2026-09-21 — the user does not need local review-label collection and chose to prioritize review controls and release readiness instead

The proposed milestone would have stored user-confirmed labels locally for later
classifier evaluation without storing image content. It was removed from the
active product scope before implementation. No label records, settings, or UI
will be added.

Postmortem: the application uses a user-managed KoboldCpp model and the user does
not need to build a local evaluation dataset from review decisions. The feature
would add persistence and privacy obligations without improving the selected
release workflow.

## Milestone 6: Cross-Platform Release Readiness

**Status:** planned after F-008 and F-009. The user confirmed this milestone is important.

- Test the complete workflow on Linux, Windows, and macOS.
- Package Python, PySide6, Pillow, and other required local assets.
- Verify first launch, upgrades, paths, permissions, and large scans.
- Document installation and troubleshooting.
- Decide signing and distribution separately for each operating system.

Success: A non-technical user can install the app, configure a supported private-LAN KoboldCpp vision server, and run a clearly disclosed scan on each supported operating system.

## Deferred Until After the MVP

- Permanent deletion.
- Duplicate detection.
- Image-quality detection.
- GIF and HEIC support.
- Restoration from quarantine.
- Public Internet vision providers.
