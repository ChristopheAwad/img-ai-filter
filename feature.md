# F-003: KoboldCpp Vision Scan MVP

## Status

Approved by the user on 2026-09-19. Automated implementation is complete, and
the user approved the live desktop GUI checklist on 2026-09-19. The user then
explicitly authorized creation and push of a pull request.

Pre-feature baseline:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
325 passed, 2 skipped, 1 warning in 55.17s
```

The warning is the existing Pillow `DecompressionBombWarning` fixture. The skipped tests require Windows junction support.

Pull-request creation and push are authorized. Merge remains subject to the
required review workflow.

Current automated result after implementation:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
545 passed, 2 skipped, 1 warning in 53.03s
```

All tests ran with socket, DNS, and standard-library HTTP entry points blocked
unless a test installed an injected fake. The warning and skips are unchanged
from the baseline.

## Goal

Connect **Scan Folder** to a useful, read-only screenshot and meme scan. Every supported image is analyzed by a user-managed KoboldCpp vision server on loopback or the private LAN. The approved default base URL is:

```text
http://192.168.0.239:5001/v1/
```

The URL remains editable. The app derives the request URL safely:

```text
http://192.168.0.239:5001/v1/chat/completions
```

This server-only design replaces the packaged ONNX classifier and fallback cascade for the MVP. Packaged offline detection remains optional future work. Existing benchmark tools remain available but do not block an explicitly experimental server-only scan.

## Approved Product Decisions

- Use KoboldCpp as the sole detector for the MVP.
- Require a loaded language model with compatible vision `mmproj` support.
- Query KoboldCpp for its version, capabilities, and loaded model before scanning.
- Permit only loopback and private-LAN destinations already accepted by `endpoint.py`.
- Permit plain HTTP on the trusted LAN only after an explicit warning before every scan.
- Explain that every supported image will be transferred to the displayed destination.
- Do not require an API key for the approved server. Preserve completed keyring support for possible future authenticated servers, but keep it out of the MVP GUI path.
- Analyze one image at a time. Do not automatically retry.
- Keep every server candidate unchecked because no model-specific acceptance benchmark exists.
- Omit ordinary and uncertain decisions from candidate results. Count uncertain decisions and failures separately.
- Continue after per-image failures. If every analysis fails, show a clear failed state rather than an empty success.
- Never move, rename, delete, modify, or write beside source images.
- Keep the GUI responsive and allow safe cancellation and shutdown.
- Keep all automated tests offline through injected fake transports. Automated tests must never contact `192.168.0.239`.

## Reused And Added Components

- `scanner.py`: recursive, stable, read-only discovery without symlink traversal.
- `detection.py`: immutable candidate result and per-file failure boundary.
- `endpoint.py`: expanded private-network destination validation.
- `settings.py`: added URL/model persistence boundary.
- `credentials.py`: retained dormant secure API-key support from the scrapped F-002 work.
- `evaluation.py`, `dataset.py`, and their CLIs: retained optional model-evaluation foundation from the scrapped F-002 work.
- `window.py`: folder-selection behavior, status label, result list, and controls.

## Test Coverage First

Write every test group below before its production implementation. Confirm each new group fails for the intended missing behavior. Main session owns tests, integration, the full suite, and approval gates.

### 1. Base URL And Connection Discovery Tests

- Accept `http://192.168.0.239:5001/v1/` and normalize it to an immutable base URL.
- Accept loopback, private IPv4, CGNAT, link-local, unique-local IPv6, and HTTPS using the existing address policy.
- Accept `/v1` and `/v1/` as equivalent base paths.
- Derive exactly `/v1/chat/completions`, `/v1/models`, and origin-level `/api/extra/version` URLs without doubled slashes.
- Reject an exact Chat Completions URL when a base URL is required.
- Reject empty paths, arbitrary paths, query strings, fragments, user information, invalid ports, unsupported schemes, public IPs, multicast, unspecified, broadcast, and unapproved hostnames.
- Keep the model value optional until server discovery succeeds; reject blank discovered model identifiers.
- Use an injected fake transport for capability discovery.
- Require `/api/extra/version` JSON with `result == "KoboldCpp"`, a nonblank version, `llm == true`, `vision == true`, and `protected == false` for this no-key MVP.
- Reject empty bodies, malformed JSON, wrong product, missing fields, wrong field types, no LLM, no vision, and unexpectedly protected servers.
- Parse `/v1/models`; require a nonempty `data` list and a nonblank string `id`; choose the first loaded model deterministically.
- Reject zero models, malformed entries, and oversized discovery responses.
- Test connection refusal, connect timeout, read timeout, cancellation, HTTP errors, redirects, and response-size limits.
- Confirm fixed safe errors contain no response bodies, credentials, image data, or unrelated paths.
- Confirm the module has no GUI import and makes no network call at import time.

### 2. Image Preparation Tests

- Prepare PNG, JPEG, WebP, BMP, and TIFF using Pillow from temporary fixtures.
- Reject symbolic links, missing files, directories, unsupported extensions, empty files, malformed files, extension/content mismatch, zero dimensions, and dimensions above 100,000,000 pixels.
- Apply EXIF orientation in memory.
- Preserve aspect ratio and resize only when the longest edge exceeds 1024 pixels.
- Convert all accepted inputs to PNG in memory with the correct `data:image/png;base64,` prefix.
- Convert palette, grayscale, RGB, and RGBA images safely; preserve transparency where possible.
- Enforce a bounded raw input size and a maximum encoded request-image size of 8 MiB.
- Test values exactly at and one unit over pixel, dimension, raw-byte, and encoded-byte boundaries.
- Confirm returned data is valid base64 and decodes to a valid PNG.
- Confirm source bytes, timestamps, names, locations, EXIF, and permissions remain unchanged on success and failure.
- Confirm no temporary image or transformed copy is written to disk.

### 3. Strict Vision Decision Parser Tests

- Add an intermediate immutable `VisionDecision` for all eight labels, including `uncertain`.
- Require one JSON object with exactly `category`, `reason`, and `confidence`.
- Accept only `ordinary`, `screenshot`, `captioned_meme`, `social_post`, `reaction_image`, `comic`, `image_macro`, or `uncertain`.
- Require a finite numeric confidence from 0 through 1, including exact boundaries.
- Require a short, nonblank user-readable reason; enforce a documented maximum length.
- Reject empty content, whitespace, arrays, primitives, multiple objects, Markdown fences, prose around JSON, trailing data, duplicate keys, missing keys, extra keys, unknown categories, booleans as confidence, NaN, infinity, and out-of-range confidence.
- Reject reasons containing file paths, recognized text, model jargon, image bytes, or endpoint/API details.
- Convert ordinary decisions to non-candidates, approved candidate categories to unchecked candidates, and uncertain decisions to a typed omission.
- Never create a checked server candidate.

### 4. KoboldCpp Request Client Tests

- POST only to the derived `/v1/chat/completions` URL.
- Send `Content-Type: application/json`, no authorization header for this MVP, and no cookies or unrelated headers.
- Send one image only, as an OpenAI `image_url` content item with an in-memory PNG data URL.
- Send a fixed system prompt and fixed classification instruction.
- Request nonstreaming output with deterministic conservative generation settings and a small bounded token count.
- Send `response_format.type == "json_schema"` with the exact decision schema and no extra properties.
- Send the model identifier returned by discovery.
- Accept only a bounded 2xx JSON response with exactly one usable assistant content value under `choices`.
- Test empty choices, multiple unusable choices, missing message/content, content arrays, refusal, malformed envelopes, invalid JSON, oversized response, and unsupported status codes.
- Use five-second connection timeout and 180-second inference/read timeout.
- Reject all redirects; never send an image to a redirect destination.
- Do not retry timeout, disconnect, refusal, invalid output, or HTTP failure.
- Support cancellation by closing the active request and returning a fixed cancellation result.
- Redact server bodies, generated text, image data, endpoint credentials, and source paths from exceptions and logs.
- Confirm the module has no GUI import and all tests use fake transports.

### 5. Server Detector And Scan Workflow Tests

- Analyze each discovered image exactly once and in scanner order.
- Process requests sequentially.
- Return only screenshot/meme-style candidates to the GUI-neutral result summary.
- Keep every candidate unchecked.
- Omit ordinary decisions and count them.
- Omit uncertain decisions and count them.
- Count decode, limit, network, HTTP, cancellation, and invalid-response failures without stopping later images.
- Include unreadable-directory counts from scanner discovery.
- Cover empty folders, no supported files, all ordinary, all candidates, all uncertain, mixed outcomes, first/middle/last failure, every request failing, and cancellation before/during/between files.
- Report discovered, analyzed, candidate, ordinary, uncertain, failed, and skipped-directory counts consistently.
- Treat every-request failure as a failed scan; mixed success/failure is completed with skipped items.
- Never expose image bytes, recognized text, server response text, or credentials in summaries.
- Confirm no source-file mutation in successful, failed, and cancelled scans.

### 6. Worker And GUI Tests

- Preserve all existing folder-selection tests.
- Add editable server URL settings prefilled with `http://192.168.0.239:5001/v1/`.
- Add **Test Connection**; it sends no image and displays KoboldCpp version, vision capability, and discovered model.
- Disable **Scan Folder** unless a folder is selected and the endpoint/model configuration is ready.
- Clicking **Scan Folder** must show a consent dialog containing the exact origin, the unencrypted-HTTP warning, and the statement that every supported image will leave this computer for the LAN server.
- Declining or closing consent sends nothing and preserves the ready state.
- Accepting consent starts one background scan.
- Disable folder, settings, and duplicate scan controls while active; enable Cancel.
- Test immediate, middle, and late cancellation; stale worker events must not alter a newer scan.
- Keep the event loop responsive while fake requests block.
- Show stable ready, connecting, scanning, completed, completed-with-skips, cancelled, and failed states.
- Show progress without revealing image contents.
- Render candidate path, category, reason, confidence, and unchecked checkbox.
- Do not display ordinary or uncertain rows.
- Show exact summary counts.
- Permit retry after completion, cancellation, and failure; replace old rows and check states.
- Selecting a different folder after completion clears old results.
- Close active connections and stop workers safely when the window closes.
- Keep move, delete, and quarantine actions absent.

### 7. Regression, Offline, And Privacy Tests

- Run all automated tests with `socket.create_connection`, DNS, and common HTTP entry points blocked except injected fakes.
- Existing scanner, detection, endpoint, settings, credentials, evaluation, dataset, CLI, and window tests continue to pass.
- Pillow is a required runtime dependency. Missing settings, keyring, or KoboldCpp do not prevent startup; scanning is disabled with a repair message where appropriate.
- Reports and GUI text contain no API keys, base64 image data, recognized text, private response bodies, or hidden model reasoning.
- Source files remain unchanged.
- The approved private-LAN default endpoint may be tracked. No image, real manifest, generated report, downloaded model, credential, or secret is tracked.

## Implementation Sequence

1. Update `project-brief.md`, `roadmap.md`, README files, and this plan for F-003; preserve F-002 as a permanent scrapped record with postmortem.
2. Record the full-suite baseline and worktree state.
3. Write failing endpoint-base and connection-discovery tests.
4. Implement base URL joining and KoboldCpp capability/model discovery using an injected transport.
5. Run focused endpoint/discovery tests, then the full suite.
6. Write failing image-preparation and strict decision-parser tests.
7. Implement bounded in-memory image preparation and strict parsing.
8. Write failing Chat Completions request/response/privacy tests.
9. Implement the standard-library HTTP transport and KoboldCpp client. Do not add an HTTP dependency.
10. Run focused client tests, then the full suite.
11. Write failing server-detector and GUI-neutral workflow tests.
12. Implement sequential server analysis and summary aggregation.
13. Write failing worker, settings UI, consent, progress, cancellation, result-row, retry, and shutdown tests.
14. Implement background scanning and connect **Scan Folder**.
15. Move Pillow from the optional evaluation extra to normal runtime dependencies only when production image preparation is implemented.
16. Update all documentation and remove contradictory ONNX/fallback statements from current-MVP instructions while keeping deferred history clear.
17. Run focused tests and the complete suite with external networking blocked.
18. Run `git status --short --ignored`, `git diff --check`, and `git ls-files evaluation sample-img`; inspect for images, manifests, reports, models, secrets, and unrelated artifacts.
19. Ask the user to start KoboldCpp with a vision model and matching `mmproj`, launch `.venv/bin/python -m img_ai_filter`, test the connection, consent, and scan `sample-img/`.
20. Ask the user to reply `Approved` or provide the error text, screenshot, and failed step.
21. Only after explicit GUI approval ask whether to commit, push, or create a pull request.

## Manual GUI Acceptance Checklist

Use only safe sample images. Automated tests never contact the live server.

1. Start KoboldCpp at `http://192.168.0.239:5001` with a vision-capable GGUF and matching `mmproj`.
2. Launch the app with `.venv/bin/python -m img_ai_filter`.
3. Confirm the server URL field contains `http://192.168.0.239:5001/v1/`.
4. Click **Test Connection**. Expect KoboldCpp version, vision support, and one discovered model.
5. Select `sample-img/`. Expect no transfer yet.
6. Click **Scan Folder**. Expect an explicit warning naming `http://192.168.0.239:5001` and saying every supported image will be transferred using unencrypted HTTP.
7. Decline once. Expect no request and a ready state.
8. Start again and consent. Expect responsive progress and no duplicate-scan controls.
9. Expect only candidate rows, each unchecked, with path, category, reason, and confidence.
10. Confirm ordinary/uncertain/failure counts are visible and the three source files are unchanged.
11. Retry once, then test Cancel during a scan. Expect clean completion/cancellation and no stale rows.
12. Close the window during a scan. Expect safe shutdown without a crash.

## Implemented Files

- `feature.md`
- `project-brief.md`
- `roadmap.md`
- `README.md`
- `evaluation/README.md`
- `pyproject.toml`
- `docs/research/python-credential-storage.md`
- `src/img_ai_filter/credentials.py`
- `src/img_ai_filter/dataset.py`
- `src/img_ai_filter/dataset_cli.py`
- `src/img_ai_filter/endpoint.py`
- `src/img_ai_filter/evaluation.py`
- `src/img_ai_filter/http_transport.py`
- `src/img_ai_filter/settings.py`
- `src/img_ai_filter/vision_connection.py`
- `src/img_ai_filter/image_payload.py`
- `src/img_ai_filter/vision_response.py`
- `src/img_ai_filter/vision_client.py`
- `src/img_ai_filter/scan_workflow.py`
- `src/img_ai_filter/scan_worker.py`
- `src/img_ai_filter/window.py`
- focused tests matching each GUI-neutral module
- expanded evaluation and window tests

Server detection is implemented by `vision_client.py` plus `scan_workflow.py`, and
the settings controls are part of `window.py`; separate `server_detector.py` and
`settings_dialog.py` modules were not needed.

## Acceptance Criteria

- **Scan Folder** performs a real, responsive scan through KoboldCpp.
- Every transfer requires explicit consent and names the exact destination.
- Only validated private-LAN or loopback endpoints are accepted; redirects are never followed.
- Every supported image is prepared in memory and sent at most once.
- Server output is accepted only through the strict JSON schema and parser.
- Candidate rows are always unchecked.
- Ordinary and uncertain items are omitted and counted.
- Per-image failures do not stop later images; total outage is clearly reported.
- Source files remain unchanged.
- Automated tests pass with real networking unavailable.
- The user completes the desktop checklist and explicitly approves before any Git operation is proposed.

## Explicitly Deferred

- Packaged ONNX or other in-app classifier.
- Classifier-first fallback cascade and uncertain-routing threshold.
- Production accuracy claims and model-specific checked thresholds.
- Requiring the 335-image benchmark before experimental use.
- API-key UI for the approved unprotected KoboldCpp server.
- Public Internet or cloud endpoints.
- Parallel inference and automatic retries.
- Thumbnails.
- Quarantine, move, restore, and deletion.
- Final installers, signing, and distribution.

---

## Bug context (documented by document-bug)

### Bug summary

The KoboldCpp server-only scan is implemented and has now completed its first
live end-to-end image request, but manual acceptance is not complete. The
original live connection failed with `KoboldCpp vision support is not
available` because KoboldCpp 1.121 had loaded only
`gemma-4-E2B-it-Q6_K.gguf`; its separate Gemma 4 vision projector was not
loaded, so `/api/extra/version` reported `"vision": false`. Loading the matching
`mmproj-F16.gguf` fixed connection discovery and allowed a real scan. The app
then analyzed the screenshot currently in the ignored `sample-img/` folder and
correctly classified it as `screenshot` with 95% model-reported confidence.
This proves that discovery, consent, image preparation, transport, strict
response parsing, background workflow, and result rendering work against the
live server. The confidence is an uncalibrated model estimate, so the candidate
correctly remains unchecked. The correct server address is
`http://192.168.0.239:5001/v1/`; the obsolete `.233` address is invalid for this
project. The earlier F-002 design
mentioned in the plan was a packaged ONNX classifier plus LAN fallback; it was
scrapped in favor of this KoboldCpp-only implementation and is not current
architecture.

### Investigation log

- Tested `http://192.168.0.239:5001/api/extra/version` without sending an image
  -> KoboldCpp returned version `1.121`, `llm: true`, `protected: false`, and
  `vision: false`. This confirmed that endpoint validation and connectivity were
  working and ruled out an Image Filter networking bug.
- Tested `http://192.168.0.239:5001/v1/models` without sending an image -> the
  loaded model was `koboldcpp/gemma-4-E2B-it-Q6_K`. This ruled out a missing
  language model.
- Checked the Gemma 4 model metadata -> Gemma 4 E2B is multimodal, but the
  Unsloth GGUF release stores the vision encoder/projector separately. Its model
  repository includes `mmproj-F16.gguf` and `mmproj-BF16.gguf`; the Q6_K text
  GGUF alone does not make KoboldCpp report vision support.
- Checked KoboldCpp 1.121 launcher source -> the control is under **Loaded
  Files**, labeled **Mmproj File**. It is not shown in **Quick Launch** and
  KoboldCpp does not infer the projector from the text-model filename. The CLI
  equivalent is `--mmproj /path/to/mmproj-F16.gguf`.
- Loaded the matching `mmproj-F16.gguf` and restarted KoboldCpp -> **Test
  Connection** succeeded. Because `discover_koboldcpp()` requires `vision ==
  true` in `src/img_ai_filter/vision_connection.py:74-113`, this confirms the
  restarted server advertised active vision support.
- Ran a live scan on the ignored `sample-img/` folder -> one screenshot was sent
  and correctly returned as a `screenshot` candidate with 95% model-reported
  confidence. The user confirmed the source was a screenshot, not an ordinary
  photo. No classification false positive occurred.
- The request prompt and JSON schema are in
  `src/img_ai_filter/vision_client.py:23-92`; strict output validation is in
  `src/img_ai_filter/vision_response.py:77-122`; sequential aggregation is in
  `src/img_ai_filter/scan_workflow.py:60-138`; GUI connection, consent, scan,
  and result rendering are in `src/img_ai_filter/window.py:244-487`.
- Automated implementation passed
  `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` with `545 passed, 2
  skipped, 1 warning in 53.03s`. `tests/conftest.py` blocks real socket, DNS,
  and standard-library HTTP access unless a test replaces it with a fake.
- Artifact inspection found only `evaluation/README.md` and
  `evaluation/manifest.example.csv` tracked below `evaluation/`; `sample-img/`
  remains ignored. No model, real image, report, manifest, or secret was added.
- No commit, push, branch, pull request, or other Git write operation was
  performed.

### Implementation progress

- Implementation-sequence steps 1 through 18 are complete. Production modules
  now include endpoint validation/discovery, bounded in-memory image
  preparation, strict response parsing, a no-redirect standard-library HTTP
  transport, sequential workflow aggregation, background operation threads,
  persisted server/model settings, consent, cancellation, summaries, and
  unchecked candidate rows.
- Steps 19 and 20 are complete. Live KoboldCpp discovery, image scanning, retry,
  cancellation, and close-during-scan behavior passed the desktop checklist.
  The user replied `Approved` on 2026-09-19.
- Step 21 is authorized. The user explicitly requested a pushed pull request
  after approving the desktop behavior.
- The approved default is `http://192.168.0.239:5001/v1/`. The obsolete `.233`
  address is not valid for any project fixture or documentation example.

### Current blocker

There is no remaining implementation or manual-acceptance blocker. The matching
Gemma 4 projector is loaded, and the first live screenshot was correctly
classified as `screenshot`.

### Next steps for next agent

1. Read this appended handoff first, then inspect
   `src/img_ai_filter/vision_client.py`, `src/img_ai_filter/window.py`,
   `tests/test_vision_client.py`, and `tests/test_window_server.py`. Do not assume
   the earlier `.233` address is still correct.
2. Keep the approved default at `http://192.168.0.239:5001/v1/`. The obsolete
   `.233` address must not be used in code, tests, or documentation.
3. Re-run the focused default/settings/window tests, then run
   `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`. Keep all automated
   tests offline; do not contact the live server from tests.
4. Do not tune the prompt for the first live result. The user confirmed that the
   source was a screenshot and the `screenshot` category was correct. Continue
   to treat confidence as an uncalibrated model estimate and keep candidates
   unchecked.
5. Preserve the completed GUI approval and proceed with the user-authorized pull
   request. Do not perform any later merge or unrelated Git operation without
   following the repository workflow.
