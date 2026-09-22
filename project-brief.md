# Project Brief

## Purpose

A privacy-conscious desktop app that finds screenshots and memes in user-selected image folders. With explicit consent, every supported image is sent to a user-managed KoboldCpp vision server on loopback or the private local network. Users review candidates with compact previews and may move the checked ones into a chosen quarantine folder.

## Core Workflow

1. The user selects one source folder. Folder selection does not start a scan.
2. The user tests a validated KoboldCpp base URL. The application confirms the version, vision capability, and loaded model.
3. The application enables **Scan Folder** after a valid folder is selected and the server configuration is ready.
4. Before every scan, the application names the destination and warns that every supported image will be sent to the KoboldCpp server, including that plain HTTP is unencrypted when selected.
5. After consent, the application analyzes images sequentially through the OpenAI-compatible Chat Completions endpoint.
6. The application shows only images flagged as likely screenshots, memes, or related trash candidates. Ordinary photos do not appear in the results.
7. Candidates at or above the saved automatic-selection confidence threshold start checked; lower-confidence candidates start unchecked. The default is 90%, and model-reported confidence is not a calibrated probability.
8. If analysis fails or remains uncertain, the image is omitted and included in visible uncertain or failed-analysis counts.
9. Each displayed result explains its source path, flagging reason, and confidence, and shows a compact in-memory preview.
10. The user reviews all candidates, can select or clear all candidates, adjusts individual checks, and reads each exact source and destination before any quarantine move starts.
11. During each accepted scan, the application shows elapsed time. It adds final duration to scan and confirmed quarantine results and saves bounded local activity history.

Selecting a different folder clears results from the prior folder and enables a new scan. Cancelling folder selection changes nothing. A completed or failed scan can be retried, and each new scan replaces prior results and review states.

## Product Decisions

- Support Linux, Windows, and macOS.
- Use Python, PySide6, Pillow, and packaged local dependencies. KoboldCpp and its model are user-managed services outside this application.
- Do not train or fine-tune a model as part of the MVP.
- Use a user-managed OpenAI-compatible KoboldCpp vision server on loopback or the private local network as the MVP detector.
- Reject public Internet vision endpoints and redirects.
- Require explicit user consent before every scan because every supported image is transferred to the configured server.
- Permit plain HTTP only for validated loopback/private-LAN destinations and show an unencrypted-transfer warning.
- Persist endpoint and discovered model settings normally. Preserve optional protected credential support for possible future authenticated servers, but do not require a key for the approved MVP server.
- Keep folder selection separate from scanning. Never start a scan only because a folder was selected.
- Recursively scan selected folders without following symbolic links.
- Support PNG, JPEG, WebP, BMP, and TIFF initially.
- Recognize screenshots, captioned memes, reaction images, comics, and image macros.
- Exclude ordinary photos from scan results.
- Show a reason and confidence for every displayed candidate.
- Default automatic selection to model-reported confidence of 90% or higher.
- Let the user save an integer threshold from 50% through 100%; apply a changed threshold only to later scan results and never overwrite current review choices.
- Provide one bulk review control that selects all candidates when any are unchecked and clears all candidates when all are checked.
- Continue after per-image endpoint failures, omit failed items, and show uncertain and failed-analysis counts. Treat a total outage as a failed scan.
- Keep scanning and connection tests off the GUI thread, support cancellation, and close active requests during shutdown.
- Never move files without user confirmation.
- Show a compact preview, maximum 96 by 96 pixels, beside every candidate and keep previews and thumbnails in memory only.
- Move only explicitly checked candidates after showing every exact source and destination path and receiving confirmation.
- Preserve the source-relative directory tree below the quarantine folder, never overwrite an existing destination, and verify that a source still matches the scanned file before it is removed.
- Support quarantine folders on a different filesystem through a verified byte-for-byte copy followed by source removal.
- Write a durable append-only JSON Lines move record in the quarantine folder explaining planned, moved, conflict, and failed outcomes.
- Remember and revalidate the chosen quarantine folder; a missing or overlapping folder never enables a move.
- Show live elapsed time from accepted consent through discovery, analysis, cancellation shutdown, or failure.
- Keep the newest 100 combined scan and confirmed quarantine events in application settings. Scan records contain the UTC start time, source-folder path, model name, outcome, duration, and aggregate counts. Quarantine records also contain exact source and destination file paths and safe per-file outcomes.
- Do not put endpoint addresses, scan candidate paths, candidate reasons, image content, thumbnails, credentials, raw exceptions, or server responses in activity history.
- Let the user view newest-first expandable activity history and clear all app records after explicit confirmation. Clearing app history does not change quarantine move logs.
- Do not record review labels. Review check states are temporary and are replaced by every rescan; new rows derive their initial state from the saved confidence threshold.
- The MVP only moves files to quarantine. It does not delete them, and it offers no automatic restoration.
- Provide Fedora x86-64 test artifacts as an AppImage and portable tarball built from one PyInstaller payload. Bundle CPython and Python runtime dependencies; keep KoboldCpp, its GGUF model, and `mmproj` external. Treat normal Linux desktop services and compatible base libraries as host-platform requirements, not application dependencies to install separately.
- Check GitHub for updates only when the user selects **Check for Updates**. Stable releases are the default; a saved setting can include test pre-releases.
- During an update check, send no images, paths, endpoint settings, credentials, history, machine identifier, or telemetry. Document that GitHub still receives the user's IP address and request timing.
- Install updates automatically only for a writable Linux x86-64 AppImage. Stream the complete file, require the exact GitHub SHA-256 asset digest, retain one recovery backup, and ask separately before download, installation, and restart.
- Source and portable-tar launches may report update availability but never replace themselves. Existing AppImages require one final manual download to obtain updater support.
- Publish version-tagged Linux releases through a tested draft-first workflow. Package metadata, tag, and artifact names must agree before publication.

## Deferred Decisions

- Reconsider a packaged offline classifier only after the server-only MVP is useful and representative licensed evaluation data exists.
- Reconsider authenticated-server GUI support if a real server requires it; the secure keyring adapter already exists.
- Add automatic restoration from quarantine and undo for completed move batches.
- Add deletion, duplicate detection, image-quality detection, GIF, and HEIC support.
- Consider app-managed vision-server installation only after the user-managed LAN workflow is proven.
- Consider public cloud vision endpoints separately; they are not part of the MVP.
- Finalize public installers, signing, and distribution for each operating system after the Linux test-distribution feedback.
- Complete a bounded first-launch, settings-recovery, large-scan, accessibility, layout, and connection-error reliability pass before claiming public release readiness.
