# Image Filter

Image Filter is a privacy-conscious desktop application for finding screenshots and memes in selected image folders. It does not change files during a scan.

The current experimental MVP connects **Scan Folder** to a user-managed
KoboldCpp vision server on loopback or the private local network. Every
candidate shows a compact preview and review details, and the user can move
exactly the checked candidates into a chosen quarantine folder.

## KoboldCpp detection

The app does not train or package a model. A user-managed KoboldCpp server runs
a vision-capable GGUF model and matching `mmproj`. After explicit consent, the
app sends every supported image to that server one at a time.

The server must be on loopback or the private local network. Before each scan,
the app shows the exact destination, warns when HTTP is unencrypted, and asks
for consent. Public Internet endpoints and redirects are rejected. Every
candidate starts unchecked. Failed and uncertain results are omitted and
included in visible counts.

The app tests KoboldCpp capabilities and discovers the first loaded model before
it enables scanning. The base URL and discovered model are normal app settings.
Completed protected credential support remains dormant because this MVP accepts
only an unprotected KoboldCpp server.

## Quarantine

Each candidate shows a compact preview (maximum 96 by 96 pixels) next to its
path, category, reason, and confidence. Previews are generated in memory during
the scan and are never written to disk.

Select **Select Quarantine Folder** to choose where checked files move. The app
remembers the folder between launches and rejects a folder that overlaps the
source folder or is no longer available. Check the candidates you want to move,
then choose **Move Checked to Quarantine**. The app lists every exact source and
destination path and waits for confirmation before it starts.

A move copies each verified file into the quarantine folder, keeping its
source-relative subfolder. A source that changed after scanning, and a
destination that already exists, are left untouched and reported. On a different
filesystem the app verifies the complete copy before it removes the source.
Every plan and outcome is recorded in `.img-ai-filter-moves.jsonl` inside the
quarantine folder. Quarantine is a move to a user-selected folder, not a delete.

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

1. Start KoboldCpp with a vision-capable GGUF and matching `mmproj`.
2. Enter its `/v1/` base URL. The default is
   `http://192.168.0.239:5001/v1/`.
3. Select **Test Connection**. The app shows the KoboldCpp version and discovered
   model when the server is ready.
4. Select a test folder with **Select Folder**.
5. Select **Scan Folder**, read the transfer warning, and consent only if the
   displayed destination is correct.
6. Optionally select **Select Quarantine Folder**, review the previews, check
   candidates, and choose **Move Checked to Quarantine** after reading the exact
   confirmation details.

Selecting a folder does not search it, load images, or contact the server.
**Scan Folder** is enabled only after a folder is selected and the connection
test has discovered a model.

During an approved scan, supported images are resized and converted to PNG in
memory, then sent sequentially. The app shows only screenshot/meme-style
candidates. It does not rename, move, delete, or edit source images.

## Tests

Activate the virtual environment, then run:

```bash
python -m pytest
```

## Detector evaluation

Image Filter retains separate offline evaluation tooling for future accuracy
work. The server-only MVP can be tested manually without claiming production
accuracy for an arbitrary KoboldCpp model.

The existing geometry evaluation compares candidate decisions on a labeled
local dataset and produces a report without sending data anywhere. Read
`evaluation/README.md` before running:

```bash
python -m img_ai_filter.eval_cli \
    --dataset evaluation/data \
    --manifest evaluation/manifest.csv \
    --split holdout \
    --json evaluation/reports/compare.json \
    --markdown evaluation/reports/compare.md
```

Real benchmark images, endpoint settings, credentials, and the real manifest
stay outside Git. The included
`evaluation/manifest.example.csv` shows the format only. Until the dataset
covers the minimum categories in `feature.md`, every report is marked
exploratory and no detector is selected.
