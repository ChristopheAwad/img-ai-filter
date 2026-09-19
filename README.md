# Image Filter

Image Filter is a privacy-first desktop application for finding screenshots and memes in selected image folders. It works locally and does not change files during a scan.

The current milestone separates folder selection from scanning. Candidate detection and quarantine actions are not implemented yet.

## Requirements

- Python 3.11 or newer
- Linux, Windows, or macOS

## Linux and macOS Setup

Run these commands from the project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test,eval]'
```

## Windows PowerShell Setup

Run these commands from the project folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test,eval]"
```

## Launch

Activate the virtual environment, then run:

```bash
python -m img_ai_filter
```

Select a test folder with the **Select Folder** button. The application uses your operating system's folder picker, including its normal navigation and saved locations. If you open the picker again during the same session, it starts at the last folder you selected.

Selecting a folder does not search it or load any images. It displays the selected path and enables **Scan Folder**. Scan behavior will be added after the local candidate detector is selected.

The application does not rename, move, delete, or edit source images during folder selection.

## Tests

Activate the virtual environment, then run:

```bash
python -m pytest
```

## Detector evaluation

Image Filter chooses its local screenshot-and-meme detector through a separate,
fully offline evaluation. The current application does not detect candidates
yet; this evaluation tooling helps select the detector first.

The evaluation compares candidate approaches on a labeled local dataset and
produces a report. It never sends data anywhere. Install the optional
evaluation dependencies and read `evaluation/README.md` before running:

```bash
python -m img_ai_filter.eval_cli \
    --dataset evaluation/data \
    --manifest evaluation/manifest.csv \
    --split holdout \
    --json evaluation/reports/compare.json \
    --markdown evaluation/reports/compare.md
```

Real benchmark images and the real manifest stay outside Git. The included
`evaluation/manifest.example.csv` shows the format only. Until the dataset
covers the minimum categories in `feature.md`, every report is marked
exploratory and no detector is selected.
