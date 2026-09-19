# Detector evaluation

This folder holds the local, offline evaluation tooling that selects the
candidate detector for the app. It never sends data anywhere: every image,
manifest, report, and model stays on this computer.

## What is committed

- `manifest.example.csv` — a format example only. It is not a real dataset.
- `README.md` — this file.

## What is never committed

Set in `.gitignore` and kept strictly local:

- `evaluation/data/` — the real labeled image dataset.
- `evaluation/manifest.csv` — the real manifest (one row per image).
- `evaluation/models/` — any downloaded model assets.
- `evaluation/reports/` — generated report files.
- `evaluation-report.md` — a generated comparison report.
- `sample-img/` — unlicensed sample images used only for smoke checks.

## Manifest format

One CSV file named `manifest.csv` beside the data folder, with these exact
columns:

- `path` — path relative to the dataset root, forward slashes, never absolute.
- `label` — `ordinary`, `screenshot`, `captioned_meme`, `social_post`,
  `reaction_image`, `comic`, `image_macro`, or `uncertain`.
- `split` — `tuning` (free to tune thresholds) or `holdout` (measured only after
  thresholds are frozen).
- `source` — where the image came from, such as `local-user-supplied`.
- `license` — a redistribution license identifier, or `local-only` for images
  that must never leave this machine.

The loader rejects absolute paths, `..` traversal, Windows drive or UNC paths,
directories, missing files, symbolic links, unsupported extensions, duplicates,
blank fields, unknown labels or splits, and malformed CSV. Errors include the
row number. The evaluator analyzes only the listed files and never searches the
dataset root.

## Requirements

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,eval]'
```

The `eval` extra currently adds Pillow only. No OCR or model dependency has been
accepted yet; candidates are listed in the report.

## Run the evaluation

```bash
python -m pytest
python -m img_ai_filter.eval_cli \
    --dataset evaluation/data \
    --manifest evaluation/manifest.csv \
    --split holdout \
    --json evaluation/reports/compare.json \
    --markdown evaluation/reports/compare.md
```

Reports contain relative paths, labels, decisions, reasons, numeric metrics,
failures, dependency and machine facts, and aggregated timings. They never
contain image bytes or recognized OCR text.

## Current status

The geometry baseline is implemented and tested. The real dataset must reach
the minimum category coverage from `feature.md` before any production decision.
Until then, a report is explicitly exploratory and no detector is selected.