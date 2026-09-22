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
for consent. Public Internet endpoints and redirects are rejected. By default,
candidates with model-reported confidence of 90% or higher start checked; lower
confidence candidates start unchecked. Failed and uncertain results are omitted
and included in visible counts.

The status line shows elapsed time during each approved scan and the final
duration of scans and confirmed quarantine batches. **Activity History** shows
the newest 100 scan and quarantine events across application launches. Scan
records contain the UTC start time, source-folder path, model, outcome,
duration, and aggregate image counts. Quarantine records contain the source and
quarantine roots, duration, aggregate outcomes, and exact source and destination
paths for each file. They do not contain the server address, image content,
candidate reasons, credentials, or server responses. Use **Clear History** in
that dialog to remove app history after confirmation. This does not remove the
quarantine move-log files.

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

## Usage

1. Start KoboldCpp with a vision-capable GGUF and matching `mmproj`.
2. Enter its `/v1/` base URL. The default is
   `http://192.168.0.239:5001/v1/`.
3. Select **Test Connection**. The app shows the KoboldCpp version and discovered
   model when the server is ready.
4. Select a test folder with **Select Folder**.
5. Select **Scan Folder**, read the transfer warning, and consent only if the
   displayed destination is correct.
6. Use **Settings** to change the automatic-selection confidence threshold if
   needed. It accepts 50% through 100% and applies to future scan results only.
7. Optionally select **Select Quarantine Folder**, review the previews, use
   **Select All** or **Clear All** if useful, and choose **Move Checked to
   Quarantine** after reading the exact confirmation details.
8. Select **Activity History** while the app is idle to inspect scan and
   quarantine events or clear the saved app history.

Selecting a folder does not search it, load images, or contact the server.
**Scan Folder** is enabled only after a folder is selected and the connection
test has discovered a model.

During an approved scan, supported images are resized and converted to PNG in
memory, then sent sequentially. The app shows only screenshot/meme-style
candidates. It does not rename, move, delete, or edit source images.

The default automatic-selection threshold is 90%. This confidence is reported
by the selected model and is not a calibrated probability or accuracy
guarantee. **Settings** can save an integer threshold from 50% through 100%.
Changing it does not alter current review choices; the next scan uses it for new
rows. The bulk-selection control changes only current review state: it shows
**Select All** while any row is unchecked, and **Clear All** when every row is
checked. Automatic selection never starts a quarantine move, which still
requires exact-path confirmation.

## Linux Test Package

The Linux x86-64 test distribution includes Python, PySide6, Pillow, keyring,
and the other Python runtime components. It does not include KoboldCpp, a GGUF
vision model, or the matching `mmproj`. Fedora x86-64 is the first manual test
target; this is not yet a signed public release for every Linux distribution.

Verify both downloaded artifacts from their folder:

```bash
sha256sum --check SHA256SUMS
```

To use the AppImage:

```bash
chmod +x ImageFilter-0.2.3-x86_64.AppImage
./ImageFilter-0.2.3-x86_64.AppImage
```

If AppImage mounting is unavailable, extract the fallback without installing
Python or FUSE:

```bash
tar -xzf ImageFilter-0.2.3-linux-x86_64.tar.gz
./ImageFilter-0.2.3-linux-x86_64/image-filter
```

The package still needs a normal Linux desktop, graphics drivers, display
services, and compatible base libraries. Application settings and activity
history use the normal per-user Qt configuration location. Quarantine move logs
are written only in the selected quarantine folder. If startup fails, launch
from a terminal and retain its error text. Portal or FUSE errors do not require
root access; use the tarball fallback when FUSE is the problem.

## AppImage Updates

Select **Check for Updates** when you want Image Filter to check its GitHub
releases. The app does not check at startup or on a timer. The request gives
GitHub and its download infrastructure your IP address and request timing. It
does not send images, image paths, KoboldCpp settings, credentials, activity
history, or a machine identifier.

Stable releases are checked by default. **Settings** can include test releases.
Test releases can contain unfinished changes and have more risk than stable
releases.

When a newer Linux x86-64 AppImage is available, the app shows its version,
channel, notes, and size before download. It streams the file to the current
AppImage folder, verifies GitHub's SHA-256 release digest, asks again before
installation, and keeps the previous file as `<AppImage name>.backup`. It asks
before restarting. HTTPS and SHA-256 protect the transfer from corruption, but
they do not protect against compromise of this project's GitHub publishing
account.

Automatic installation works only when the app runs from a writable AppImage.
Source and portable-tar launches can check availability but do not replace
themselves. The first updater-enabled AppImage must be downloaded manually once;
later AppImages can replace themselves. To recover manually, close Image Filter,
move the current AppImage aside, rename its `.backup` file to the original name,
and ensure it is executable.

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
