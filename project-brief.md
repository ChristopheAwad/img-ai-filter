# Project Brief

## Purpose

A privacy-first desktop app that finds screenshots and memes in user-selected image folders. Users review the results and move confirmed files into a chosen quarantine folder.

## Core Workflow

1. The user selects one source folder. Folder selection does not start a scan.
2. The application enables **Scan Folder** after a valid folder is selected.
3. The user starts discovery and candidate detection with **Scan Folder**.
4. The application shows only images flagged as likely screenshots, memes, or related trash candidates. Ordinary photos do not appear in the results.
5. High-confidence candidates start checked. Uncertain candidates remain visible but start unchecked.
6. Each result explains its source path, flagging reason, and confidence.
7. The user reviews the candidates before any later quarantine action.

Selecting a different folder clears results from the prior folder and enables a new scan. Cancelling folder selection changes nothing. A completed or failed scan can be retried, and each new scan replaces prior results and review states.

## Product Decisions

- Support Linux, Windows, and macOS.
- Use Python, PySide6, ONNX Runtime, and packaged local dependencies.
- Work fully offline with no telemetry or remote services.
- Keep folder selection separate from scanning. Never start a scan only because a folder was selected.
- Recursively scan selected folders without following symbolic links.
- Support PNG, JPEG, WebP, BMP, and TIFF initially.
- Recognize screenshots, captioned memes, social-post screenshots, reaction images, comics, and image macros.
- Exclude ordinary photos from scan results.
- Show a reason and confidence for every displayed candidate.
- Preselect only high-confidence results and show uncertain results unchecked.
- Never move files without user confirmation.
- Record review labels locally for future classifier evaluation.
- The MVP only moves files to quarantine. It does not delete them.

## Deferred Decisions

- Select rules, OCR, CLIP, a small classifier, or a hybrid after local benchmarking.
- Decide the quarantine folder layout and restoration workflow.
- Add deletion, duplicate detection, image-quality detection, GIF, and HEIC support.
- Add thumbnails after candidate detection and the candidate-only workflow work correctly.
- Consider a loopback-only OpenAI-compatible vision provider.
- Finalize installers, signing, and distribution for each operating system.
