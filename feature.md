# Feature Plan: Local Detector Evaluation

## Status

Implementation and automated tests are complete. Waiting for the desktop regression check and explicit user approval.

## Goal

Build a repeatable, read-only evaluation process that selects the smallest fully local detector that can distinguish supported trash candidates from ordinary photos.

The evaluation must cover screenshots, captioned memes, social-post screenshots, reaction images, comics, image macros, uncertain candidates, and ordinary photos. It must measure detection quality, false positives, speed, memory use, model size, and installed dependency size.

This feature selects and documents a detector. It does not connect **Scan Folder**, show candidate rows, move files, or change source images.

## Existing Sample Data

The user approved read-only use of `sample-img/`.

Current labels:

| Local file | Expected label |
| --- | --- |
| `sample-img/images.jpeg` | ordinary photo |
| `sample-img/images (1).jpeg` | ordinary photo |
| `sample-img/images (2).jpeg` | screenshot |

These three files are smoke-test inputs only. Their source and reuse rights are not known, so neither the image bytes nor derived image content may be committed. Add `sample-img/` to `.gitignore` before any Git operation. Do not rename, resize, rewrite, move, or delete these files.

The three files are not a valid accuracy benchmark because they contain no memes or uncertain examples and the sample is too small.

## Evaluation Dataset Contract

Use a CSV manifest with one row per image and these exact columns:

- `path`: path relative to a separately supplied dataset root.
- `label`: one of `ordinary`, `screenshot`, `captioned_meme`, `social_post`, `reaction_image`, `comic`, `image_macro`, or `uncertain`.
- `split`: `tuning` or `holdout`.
- `source`: a human-readable source name or `local-user-supplied`.
- `license`: a redistribution license identifier or `local-only`.

Paths must remain relative to the dataset root. Reject absolute paths, `..` traversal, paths that resolve outside the root, directories, symbolic links, unsupported extensions, and duplicate normalized paths. The evaluator must never search outside the listed files.

The committed repository may contain a manifest example that refers only to generated test fixtures. The real local manifest and all local benchmark images must remain ignored by Git.

Build the useful benchmark before comparing detectors. Target at least:

- 150 ordinary photos across people, animals, food, landscapes, indoor scenes, documents, and low-light photos.
- 30 screenshots across desktop and mobile operating systems.
- 25 captioned memes.
- 25 social-post screenshots.
- 25 reaction images.
- 25 comics.
- 25 image macros.
- 30 intentionally uncertain images that reasonably resemble both a photo and a candidate.

Use clearly licensed public images, generated fixtures, or local-only user data. Record the source and license for every row. Do not place the same image, a resized copy, or a recompressed copy in both tuning and holdout splits. Keep approximately 70 percent of every label in `tuning` and 30 percent in `holdout`.

If the minimum dataset cannot be assembled, the report must state that the results are exploratory and must not claim that a production detector was selected.

## Detector Result Contract

Define one immutable result type shared by every evaluated detector:

- `is_candidate`: `True` only for a displayed candidate.
- `category`: one supported candidate category, `uncertain`, or `ordinary`.
- `reason`: a short non-empty user-readable explanation with no model jargon.
- `confidence`: a finite number from `0.0` through `1.0`.
- `default_checked`: `True` only for a high-confidence candidate.

Contract rules:

- Ordinary photos return `is_candidate=False`, `category=ordinary`, and `default_checked=False`.
- Uncertain candidate-like images return `is_candidate=True`, `category=uncertain`, and `default_checked=False`.
- A result can start checked only when `is_candidate=True` and confidence meets the selected high-confidence threshold.
- A failure to decode or analyze an image returns a typed per-file failure. It must not fabricate a low-confidence classification or stop evaluation of later files.
- Reasons must describe observable evidence, such as screen layout or prominent overlaid text. They must not expose raw logits, internal class IDs, or filesystem details.

Define a detector protocol that accepts one image path and returns the result type. The protocol must permit fake detectors in unit tests and must not depend on PySide6.

## Candidates To Compare

Evaluate these approaches against the same manifest and splits:

1. **Metadata and geometry baseline:** dimensions, aspect ratio, available metadata, and other cheap non-content signals. Do not use the filename as classification evidence because user filenames are unreliable.
2. **Local OCR and layout signals:** locally detect text and combine text density and layout signals with the baseline. No image or recognized text may leave the computer. Do not write recognized text to the report.
3. **Local ONNX image-text or image-classification model:** use CPU inference and fixed prompts or classes. The model must have a license that permits packaging and redistribution.
4. **Hybrid:** combine only the strongest measured signals from the earlier approaches. Document every threshold and use the tuning split only when selecting thresholds.

A small trained classifier may be included only if there is enough separately licensed training data. The tuning or holdout images must not be used as training data. Otherwise record it as deferred rather than producing an invalid comparison.

Before adding any OCR or model package, record its exact package name, version, model name, download source, license, SHA-256 digest, compressed size, installed size, supported Python versions, and Linux/Windows/macOS CPU support. Reject candidates with unclear redistribution rights, mandatory network inference, telemetry, unsupported target platforms, or unpinned model assets.

Model downloads may occur only during explicit evaluation setup. Benchmark runs and the future packaged application must work with networking disabled. Automated tests must not download models or require network access.

## Recommended Acceptance Targets

Calculate final selection metrics on the untouched holdout split only.

- High-confidence candidate precision: at least 98 percent.
- All displayed candidate precision: at least 90 percent.
- Ordinary-photo false-positive rate for all displayed candidates: no more than 5 percent.
- Ordinary-photo false-positive rate for default-checked candidates: no more than 1 percent.
- Screenshot recall: at least 90 percent.
- Combined recall for the six non-screenshot candidate categories: at least 80 percent.
- Every uncertain expected example must be reported separately; do not count it as ordinary or force it into a confident category for headline metrics.
- A default-checked result must meet the measured high-confidence threshold selected on the tuning split.
- Median CPU analysis time: no more than 500 milliseconds per image on the recorded evaluation computer.
- 95th-percentile CPU analysis time: no more than 2 seconds per image.
- Peak additional process memory: no more than 1 GiB.
- Packaged model assets: no more than 300 MiB.

Accuracy and false-positive safety take priority over speed and package size. If no candidate meets all targets, do not select the least-bad detector. Report the failed targets and recommend the next bounded experiment.

## Test Coverage First

Write the tests below before implementation. Run them and confirm they fail because the detector and evaluation modules do not exist.

### Result Contract Tests

- Construct a valid ordinary result.
- Construct valid checked and unchecked candidate results at confidence boundaries `0.0` and `1.0` where logically allowed.
- Reject confidence below `0.0`, above `1.0`, `NaN`, positive infinity, and negative infinity.
- Reject an empty or whitespace-only reason.
- Reject an ordinary result marked as a candidate.
- Reject an ordinary or uncertain result marked checked.
- Reject a non-candidate result with a candidate category.
- Reject a candidate result with the ordinary category.
- Verify the result type is immutable.

### Manifest Validation Tests

- Load one valid row for every label and both split values.
- Accept spaces and Unicode in a relative filename without changing the path value.
- Reject an empty manifest.
- Reject a missing required column.
- Reject a blank path, label, split, source, or license.
- Reject an unknown label and unknown split.
- Reject an absolute Unix path and an absolute Windows path on every host platform.
- Reject `..` traversal and a path that resolves outside the dataset root.
- Reject a directory, missing file, unsupported extension, symbolic link, and duplicate normalized path.
- Reject malformed CSV with a clear error that includes the row number but not image content.
- Keep manifest order stable so reports are reproducible.

### Evaluation Tests

- Evaluate all valid rows with a fake detector and preserve their manifest identity.
- Continue after one typed decode or inference failure.
- Record a per-file failure without counting it as a classification.
- Reject unexpected detector exceptions as an evaluation failure with the affected relative path.
- Confirm the evaluator never modifies image bytes, timestamps, names, or locations.
- Confirm the evaluator writes no output inside the dataset root.
- Confirm no network API is called by the core evaluator.
- Confirm tuning rows and holdout rows can be reported independently.
- Confirm recognized OCR text and image bytes never appear in report output.
- Handle an empty selected split with a clear validation error instead of dividing by zero.

### Metric Tests

- Calculate true positives, false positives, true negatives, false negatives, precision, recall, and ordinary-photo false-positive rate from a small known matrix.
- Calculate each metric separately for all candidates and default-checked candidates.
- Calculate recall by expected candidate label.
- Keep uncertain examples in a separate section.
- Handle a zero denominator by returning a documented unavailable value, not a misleading zero or an exception.
- Calculate median and 95th-percentile timings for one item, two items, repeated values, and boundary values.
- Compare exact boundary values correctly against every acceptance target.
- Mark a candidate as failed when any required target is unavailable or missed.
- Select the smallest passing candidate by packaged asset size; break an exact size tie with lower median time, then lower peak memory, then stable detector name.
- Select no detector when all candidates fail.

### Image Failure And Boundary Tests

- Report an empty file, truncated image, unsupported encoding, and extension/content mismatch as per-file failures.
- Protect against images whose declared pixel dimensions exceed a documented safe decode limit.
- Handle the smallest valid image without crashing.
- Handle grayscale, RGB, RGBA, portrait, landscape, and very wide or tall images.
- Do not follow an image symlink.
- Do not mutate EXIF metadata or orientation data.

### Regression Tests

- Existing scanner tests continue to pass.
- Existing folder-selection tests continue to pass.
- The application still performs no scan when a folder is selected.
- **Scan Folder** remains disconnected during this evaluation feature.
- No move, delete, or quarantine control is added.
- The complete automated test suite runs without network access and without real model files.

## Implementation Sequence

1. Add local benchmark folders and `sample-img/` to `.gitignore`; do not alter current sample files.
2. Add failing result-contract tests and run them to record the expected missing-module failure.
3. Implement the immutable result type, candidate labels, typed analysis failure, and detector protocol without GUI imports.
4. Run the result-contract tests until they pass.
5. Add failing manifest validation tests and metric tests.
6. Implement strict CSV loading, dataset-root containment checks, split handling, and pure metric functions.
7. Run manifest and metric tests until they pass.
8. Add failing evaluator orchestration, safety, reporting, and per-file failure tests using fake detectors only.
9. Implement evaluation orchestration and deterministic JSON and Markdown reports. Reports contain paths, labels, decisions, reasons, numeric metrics, failures, dependency facts, machine facts, and aggregate timings, but never image bytes or OCR text.
10. Run evaluator tests until they pass.
11. Add generated tiny image fixtures for decode and boundary tests. Keep them test-generated so no third-party image is committed.
12. Add the metadata and geometry baseline. Verify it through unit tests and run it against the tuning split.
13. Assemble and label the minimum local dataset. Validate all source and license fields before benchmarking.
14. Research and record exact OCR and ONNX candidate dependencies and model assets. Stop and ask the user if no candidate has clear redistribution rights and all-platform CPU support.
15. Add evaluation-only optional dependencies. Do not add a model to normal application dependencies before selection.
16. Implement thin detector adapters for the accepted OCR and ONNX candidates. Keep model-specific code outside the result, manifest, metric, and reporting modules.
17. Verify each adapter with a local smoke test. Automated tests use fakes and must remain offline.
18. Tune thresholds only on the tuning split and record each tested threshold.
19. Freeze thresholds before running the holdout split.
20. Run every candidate against the holdout split on the same computer and record machine, operating-system, Python, package, model, timing, memory, and size facts.
21. Generate a comparison report. Select a detector only if it meets every required acceptance target.
22. Update `project-brief.md` with the selected technical decision or with the fact that no approach passed. Update `roadmap.md` with the evaluation outcome while leaving F-001 in progress until candidate-only scan results ship.
23. Update `README.md` with the exact offline evaluation setup and command. State clearly that this is evaluation tooling and that **Scan Folder** is still not connected.
24. Run the complete automated test suite with networking unavailable.
25. Inspect `git status` and ensure no local dataset image, local manifest, model cache, OCR text, or unlicensed model asset is tracked.

## Report Requirements

The final comparison report must include:

- Dataset counts by label and split.
- Duplicate and validation checks performed.
- Candidate name and exact version information.
- Model source, license, digest, and sizes.
- Offline status and platform support.
- Thresholds and tuning procedure.
- Holdout confusion counts and required metrics.
- Results by candidate subtype.
- Separate uncertain-image outcomes.
- Decode and inference failure counts.
- Median and 95th-percentile time.
- Peak additional memory.
- Known limitations and common false positives.
- A pass/fail row for every acceptance target.
- The selected approach and factual reason, or an explicit no-selection result.

Do not present tuning-split results as final quality. Do not hide failed images or average them into successful classifications.

## Planned Files

- `feature.md`
- `.gitignore`
- `pyproject.toml`
- `src/img_ai_filter/detection.py`
- `src/img_ai_filter/evaluation.py`
- model-specific evaluation adapter modules, named only after dependency and license review
- `tests/test_detection.py`
- `tests/test_evaluation.py`
- model-adapter tests that use local fakes or tiny generated fixtures
- `evaluation/README.md`
- `evaluation/manifest.example.csv`
- `evaluation-report.md`
- `project-brief.md`
- `roadmap.md`
- `README.md`

Do not change `src/img_ai_filter/window.py` for this feature unless a regression test requires a test-only correction. Do not connect the scan button.

## Acceptance Criteria

- The detector result contract is strict, immutable, GUI-independent, and fully tested.
- The manifest rejects unsafe or ambiguous input before analysis starts.
- The evaluator is deterministic, read-only, offline, and continues after per-file failures.
- Metric calculations and target decisions are covered by boundary tests.
- Local and unlicensed image data cannot be added to Git by accident.
- The sample folder is used only for local smoke checks and remains unchanged.
- The benchmark has the minimum category coverage, or the report clearly says no production decision can be made.
- Every compared dependency and model has recorded version, license, digest, size, and platform support.
- Holdout results determine selection.
- A detector is selected only if it passes every required target.
- Existing application behavior remains unchanged.
- All automated tests pass without networking or real model downloads.
- After automated tests pass, the user completes a short desktop regression check: launch the app, select a safe sample folder, confirm selection does not scan, and confirm **Scan Folder** remains inactive as an action. The implementation must wait for the user's explicit `Approved` reply before any Git operation is proposed.

## Explicitly Deferred

- Connecting **Scan Folder**.
- Background workers, progress UI, cancellation, and duplicate-scan prevention.
- Candidate result rows and review checkboxes.
- Thumbnails.
- Quarantine, move, restore, and delete actions.
- Local review-label persistence.
- Training a custom classifier without separate, sufficient, licensed training data.
- Packaging the selected model into release installers.

---

## Handoff context (documented by document-bug)

### Summary

The "compare local candidate detectors" feature was implemented test-first and all automated tests pass offline. No detector is selected yet: the real labeled dataset and the OCR/ONNX research steps remain, and the desktop GUI regression check is still waiting for the user's `Approved` reply.

### Implementation progress

Plan steps completed:

- Step 1 `.gitignore`: `sample-img/`, `evaluation/data/`, `evaluation/models/`, `evaluation/manifest.csv`, `evaluation/reports/`, `evaluation-report.md` are ignored.
- Steps 2–4 result contract: `src/img_ai_filter/detection.py` — immutable `DetectionResult`, `AnalysisFailure`, `Detector` protocol (`detection.py:72,86,130`); `DEFAULT_HIGH_CONFIDENCE_THRESHOLD = 0.9` (`detection.py:54`); `SAFE_MAX_PIXELS = 100_000_000` (`detection.py:56`); supported labels in detection.py. GUI-independent, no PySide6 import.
- Steps 5–7 manifest + metrics: `src/img_ai_filter/evaluation.py` — `load_manifest` (`evaluation.py:144`), `binary_metrics` (`:267`), `median` (`:292`), `percentile_95` (`:298`). Warnings-as-errors and boundary tests cover them.
- Steps 8–10 evaluator + reports: `evaluate_detector` (`evaluation.py:306`, tracemalloc peak-memory, per-file failures, deterministic), `check_targets` (`:428`), `select_best` (`:459`), `render_json`/`render_markdown` (`:524,541`).
- Step 11 generated tiny fixtures: `tests/test_baseline_detector.py` creates its own PNGs.
- Step 12 geometry baseline: `src/img_ai_filter/baseline_detector.py` — `GeometryDetector` (`:42`) and `describe()` (`:130`) return dimensions/ratios; no real tuning-split run because no real dataset.
- Step 15 `pyproject.toml`: only eval-only extra added (`eval = ["pillow>=10.0"]`). No model dependency added.
- Step 23 `README.md`: offline eval command documented.
- Steps 22, 24, 25 docs/state: `README.md`, `roadmap.md`, `project-brief.md` updated; full offline suite green (118 passed, 2 skipped Windows junction tests); `git status` shows only source + tests + docs + `evaluation/` example files untracked/modified — `sample-img/` not tracked.

Steps NOT done (require user data or a user decision): 13 (assemble/label minimum dataset), 14 (OCR/ONNX dependency + license research — must stop and ask user if no clear redistribution rights), 16–17 (adapters + smoke tests), 18–19 (tune threshold on tuning split, freeze), 20–21 (holdout benchmark + comparison report + single detector selection).

### Key files and line references

- `src/img_ai_filter/detection.py` — result contract, labels, `AnalysisFailure`, protocol, thresholds.
- `src/img_ai_filter/evaluation.py` — `Manifest`/`ManifestEntry`, CSV validation, metrics, orchestration, JSON/Markdown renderers.
- `src/img_ai_filter/baseline_detector.py` — `GeometryDetector`, the only implemented detector.
- `src/img_ai_filter/eval_cli.py` — `main()` (`:38`) wires geometry-baseline over a manifest; writes `--json`/`--markdown` reports.
- Tests all new and passing: `test_detection.py`, `test_evaluation.py`, `test_baseline_detector.py`, `test_eval_cli.py`.

### Current blocker

None — ready to continue. The next actions are user- or data-gated, not code-gated.

### Next steps for next agent

1. Confirm state first: run `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest` (expected 118 passed, 2 skipped). The plain `pytest` command aborts the Qt window tests without a display; `offscreen` is required. No CI config change was made.
2. Ask the user to complete the desktop regression check (blocker to any Git operation per plan): launch with `.venv/bin/python -m img_ai_filter`, select a safe sample folder, confirm selection does not scan, confirm **Scan Folder** stays inactive; the user must reply `Approved` before any commit/PR.
3. Only after approval ask about next feature step: assemble the real labeled dataset (user-supplied images and labels, min 150 ordinary / 30 screenshots / 25 each meme/etc / 30 uncertain) or run the offline OCR/ONNX dependency research (must stop and ask before choosing a model without clear license/cross-platform CPU support).
4. `git status` currently shows modifications to `.gitignore`, `README.md`, `feature.md`, `project-brief.md`, `pyproject.toml`, `roadmap.md` (all intended), plus untracked new source/test files and `evaluation/` with only `README.md` + `manifest.example.csv`. The stray file named `.venv⁄bin⁄python -m img_ai_filter.txt` at repo root is a leftover artifact; delete it before any commit. Do not commit until the user asks.
