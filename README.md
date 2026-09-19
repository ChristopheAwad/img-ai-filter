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
python -m pip install -e '.[test]'
```

## Windows PowerShell Setup

Run these commands from the project folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
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
