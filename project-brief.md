# Project Brief

## Purpose

A privacy-conscious desktop app that finds screenshots and memes in user-selected image folders. With explicit consent, every supported image is sent to a user-managed KoboldCpp vision server on loopback or the private local network. Users review unchecked candidates before any later quarantine action.

## Core Workflow

1. The user selects one source folder. Folder selection does not start a scan.
2. The user tests a validated KoboldCpp base URL. The application confirms the version, vision capability, and loaded model.
3. The application enables **Scan Folder** after a valid folder is selected and the server configuration is ready.
4. Before every scan, the application names the destination and warns that every supported image will be sent to the KoboldCpp server, including that plain HTTP is unencrypted when selected.
5. After consent, the application analyzes images sequentially through the OpenAI-compatible Chat Completions endpoint.
6. The application shows only images flagged as likely screenshots, memes, or related trash candidates. Ordinary photos do not appear in the results.
7. Every server candidate starts unchecked because no user-selected model has a validated checked-result threshold.
8. If analysis fails or remains uncertain, the image is omitted and included in visible uncertain or failed-analysis counts.
9. Each displayed result explains its source path, flagging reason, and confidence.
10. The user reviews the candidates before any later quarantine action.

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
- Recognize screenshots, captioned memes, social-post screenshots, reaction images, comics, and image macros.
- Exclude ordinary photos from scan results.
- Show a reason and confidence for every displayed candidate.
- Keep every server candidate unchecked unless the exact configured model later passes a separate benchmark.
- Continue after per-image endpoint failures, omit failed items, and show uncertain and failed-analysis counts. Treat a total outage as a failed scan.
- Keep scanning and connection tests off the GUI thread, support cancellation, and close active requests during shutdown.
- Never move files without user confirmation.
- Record review labels locally for future classifier evaluation.
- The MVP only moves files to quarantine. It does not delete them.

## Deferred Decisions

- Reconsider a packaged offline classifier only after the server-only MVP is useful and representative licensed evaluation data exists.
- Reconsider authenticated-server GUI support if a real server requires it; the secure keyring adapter already exists.
- Decide the quarantine folder layout and restoration workflow.
- Add deletion, duplicate detection, image-quality detection, GIF, and HEIC support.
- Add thumbnails after candidate detection and the candidate-only workflow work correctly.
- Consider app-managed vision-server installation only after the user-managed LAN workflow is proven.
- Consider public cloud vision endpoints separately; they are not part of the MVP.
- Finalize installers, signing, and distribution for each operating system.
