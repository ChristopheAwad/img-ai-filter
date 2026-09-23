# Detector evaluation

This folder holds optional evaluation tooling for detector quality. The current
MVP uses a user-managed KoboldCpp vision server; the existing geometry baseline
and dataset tools remain fully offline.

Any future server evaluation may send images only to an explicitly configured
user-managed server on loopback or the private local network. It must use the
same consent, destination validation, and redaction rules as the desktop app.
Public Internet endpoints are not allowed.

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
- Local endpoint settings, API keys, and cascade connection diagnostics.

## Manifest format

One CSV file named `manifest.csv` beside the data folder, with these exact
columns:

- `path` — path relative to the dataset root, forward slashes, never absolute.
- `label` — `ordinary`, `screenshot`, `captioned_meme`,
  `reaction_image`, `comic`, `image_macro`, `paper_document`, or `uncertain`.
  Use `paper_document` for photos whose main subject is a notebook page or
  printed/handwritten paper document; incidental background paper is ordinary.
- `split` — `tuning` (free to tune thresholds) or `holdout` (measured only after
  thresholds are frozen).
- `source` — where the image came from, such as `local-user-supplied`.
- `license` — a redistribution license identifier, or `local-only` for images
  that must never leave this machine.

The `social_post` label is no longer supported. Relabel existing rows as
`ordinary`, or as `uncertain` when the intended classification is ambiguous.

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

Pillow is a normal runtime dependency because the desktop scan prepares request
images in memory. The `eval` extra is retained for command compatibility but is
currently empty. Main dependencies also include the approved `keyring`
credential-store adapter. No ONNX runtime or packaged production model is part
of the current MVP.

## Run the evaluation

```bash
python -m pytest
python -m img_ai_filter.dataset_cli \
    evaluation/data \
    evaluation/manifest.csv
python -m img_ai_filter.eval_cli \
    --dataset evaluation/data \
    --manifest evaluation/manifest.csv \
    --split holdout \
    --json evaluation/reports/compare.json \
    --markdown evaluation/reports/compare.md
```

The dataset command returns zero only when all images decode, all labels and
splits meet the required counts, and duplicate or cross-split copies are not
found. An incomplete or invalid dataset remains exploratory.

Reports contain relative paths, labels, decisions, reasons, numeric metrics,
failures, dependency and machine facts, and aggregated timings. They never
contain image bytes or recognized OCR text.

## Current status

The geometry baseline and dataset validator are implemented and tested. The MVP
uses a user-managed OpenAI-compatible KoboldCpp vision server for every image.
No model is trained or packaged by this project.

A real dataset must reach the minimum category coverage before making accuracy
claims or enabling checked-by-default results. Until then, reports and the
server-only MVP are experimental. Testing one vision model does not validate a
different model selected by a user. The legacy minimum counts do not yet
include the new `paper_document` label; a small sample is exploratory only.
