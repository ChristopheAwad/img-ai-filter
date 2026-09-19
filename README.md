# Image Filter

Image Filter is a privacy-first desktop application for finding screenshots and memes in selected image folders. It works locally and does not change files during a scan.

The current milestone finds supported images and lists their paths. Classification and quarantine actions are not implemented yet.

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

Select a test folder with the **Select Folder** button. The application searches that folder and its nested folders for PNG, JPEG, WebP, BMP, and TIFF files. It does not follow symbolic links.

## Tests

Activate the virtual environment, then run:

```bash
python -m pytest
```
