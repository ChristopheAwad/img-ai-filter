# Product Roadmap

This roadmap divides the MVP into small, testable milestones. Each shipped milestone must leave the desktop application in a working state.

## Active Feature Register

### F-001: Candidate Scan Workflow

- **Status:** in progress
- **Tier:** Tier 1, core product workflow
- **Effort:** Medium for workflow and interface changes; candidate-detection effort remains undecided
- **Planning files:** `project-brief.md`, `roadmap.md`, `feature.md`
- **Likely implementation files:** main window, scan/detection boundary, tests, and README; exact files follow the technical decision
- **Depends on:** shipped desktop folder-scanning foundation and a separate candidate-detection decision
- **Blocks:** quarantine workflow, because only reviewed candidates can be moved safely

Dependency graph:

```text
Milestone 1 shipped
        |
        v
F-001 workflow contract and controls
        |
        v
Milestone 3 detector decision and implementation
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
3. Decide how screenshots, memes, and uncertain candidates will be detected locally.
4. Write failing workflow and detector-contract tests.
5. Add explicit folder selection and scan controls.
6. Integrate the selected detector and show candidate-only results.
7. Complete automated and desktop GUI verification.

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

**Status:** in progress as F-001.

- Keep source-folder selection separate from scanning.
- Disable **Scan Folder** until a source folder is selected.
- Clear prior results when a different folder is accepted.
- Preserve the current folder and results when folder selection is cancelled.
- Start discovery and candidate detection only after the user selects **Scan Folder**.
- Show a clear busy state and prevent duplicate scans.
- Show only flagged candidates, never the complete ordinary-photo list.
- Show each candidate's path, flagging reason, confidence, and review check state.
- Start high-confidence candidates checked and uncertain candidates unchecked.
- Allow a completed or failed scan to be retried.
- Replace prior results and review states on every rescan.
- Show clear empty and failure states.
- Keep all scanning and review actions read-only.

Thumbnails are not required for this milestone. They can be reconsidered after useful candidate detection works.

Success: A user explicitly starts a scan and reviews only explained trash candidates without changing any source file.

## Milestone 3: Local Candidate Detection

This milestone supplies the detector required to complete F-001 and Milestone 2. The technical approach is not selected yet.

- Define representative screenshot, meme, uncertain, and ordinary-photo examples.
- Agree on measurable accuracy, false-positive, performance, and package-size targets.
- Compare rules, metadata, OCR, ONNX models, or a hybrid approach.
- Select the smallest fully local approach that meets the agreed targets.
- Return a candidate decision, user-readable reason, and confidence for each analyzed image.
- Mark high-confidence candidates as checked.
- Keep uncertain candidates visible and unchecked.
- Exclude ordinary photos from results.
- Handle unreadable or damaged images without stopping the scan.
- Keep all analysis offline.

Success: The app identifies likely screenshots and memes, explains each result, and leaves the final decision to the user.

## Milestone 4: Quarantine Workflow

- Let the user select a quarantine folder.
- Detect unsafe choices, including overlap with source folders.
- Show a confirmation summary before any move.
- Move only checked files after explicit confirmation.
- Handle name conflicts and partial failures safely.
- Record enough information to explain each result.

Success: A user can move confirmed files to quarantine without deletion or silent data loss.

## Milestone 5: Local Review Labels

- Record user-confirmed labels locally.
- Do not store image content in the label records.
- Make label writes resilient to interruption and invalid prior data.
- Provide a clear description of what is stored and where.

Success: Review decisions can support later classifier evaluation without network access.

## Milestone 6: Cross-Platform Release Readiness

- Test the complete workflow on Linux, Windows, and macOS.
- Package Python, PySide6, ONNX Runtime, models, and other required local assets.
- Verify first launch, upgrades, paths, permissions, and large scans.
- Document installation and troubleshooting.
- Decide signing and distribution separately for each operating system.

Success: A non-technical user can install and run an offline build on each supported operating system.

## Deferred Until After the MVP

- Permanent deletion.
- Duplicate detection.
- Image-quality detection.
- GIF and HEIC support.
- Restoration from quarantine.
- A loopback-only OpenAI-compatible vision provider.
