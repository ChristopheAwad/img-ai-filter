# Project Brief

## Purpose

A privacy-first desktop app that finds screenshots and memes in user-selected image folders. Users review the results and move confirmed files into a chosen quarantine folder.

## Product Decisions

- Support Linux, Windows, and macOS.
- Use Python, PySide6, ONNX Runtime, and packaged local dependencies.
- Work fully offline with no telemetry or remote services.
- Recursively scan selected folders without following symbolic links.
- Support PNG, JPEG, WebP, BMP, and TIFF initially.
- Recognize screenshots, captioned memes, social-post screenshots, reaction images, comics, and image macros.
- Preselect only high-confidence results and show uncertain results unchecked.
- Never move files without user confirmation.
- Record review labels locally for future classifier evaluation.
- The MVP only moves files to quarantine. It does not delete them.

## Deferred Decisions

- Select rules, OCR, CLIP, a small classifier, or a hybrid after local benchmarking.
- Decide the quarantine folder layout and restoration workflow.
- Add deletion, duplicate detection, image-quality detection, GIF, and HEIC support.
- Consider a loopback-only OpenAI-compatible vision provider.
- Finalize installers, signing, and distribution for each operating system.
