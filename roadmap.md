# Product Roadmap

This roadmap divides the MVP into small, testable milestones. Each milestone should leave the desktop application in a working state.

## Milestone 1: Desktop Foundation and Folder Scan

- Create the Python project and test structure.
- Add a PySide6 desktop window.
- Let the user select one source folder.
- Recursively find PNG, JPEG, WebP, BMP, and TIFF files.
- Do not follow symbolic links.
- Show discovered image paths in a review list.
- Keep scanning and file-system logic separate from the GUI.

Success: A user can launch the app, select a folder, and see its supported images without changing any files.

## Milestone 2: Image Review Experience

- Generate local thumbnails without modifying source images.
- Show images in a responsive review grid or list.
- Add checked and unchecked selection controls.
- Add basic image details and scan progress.
- Handle unreadable or damaged images without stopping the review.

Success: A user can inspect discovered images and change their selections safely.

## Milestone 3: Local Candidate Detection

- Build a representative local benchmark dataset.
- Compare rules, OCR, ONNX models, or a hybrid approach.
- Select the smallest approach that meets agreed accuracy and performance targets.
- Mark high-confidence candidates as checked.
- Show uncertain candidates unchecked.
- Keep all analysis offline.

Success: The app identifies likely screenshots and memes while leaving the final decision to the user.

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
