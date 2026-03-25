# iCloud Re-Sync Tool

A lightweight GUI utility that forces iCloud to re-sync files by updating their Last Modified timestamps ("touching" them). Useful when iCloud gets stuck and stops syncing certain files or folders.

## How It Works

The tool recursively touches every file in a selected folder, updating its modification timestamp to the current time. iCloud detects the change and re-uploads the files.

## Features

- Browse or drag-and-drop folders (and files) into the app
- Recursive subfolder processing (optional)
- Option to include/exclude hidden files
- Progress indicator and detailed log output

## Requirements

- Python 3.8+
- tkinter (included with most Python installations)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate.bat     # Windows
pip install -r requirements.txt
```

## Usage

```bash
.venv/bin/python icloud_resync.py
```

1. Select a folder using **Browse**, type a path, or drag-and-drop a folder/file onto the window.
2. Configure options (recursive, hidden files).
3. Click **Touch All Files**.

## Building a Portable .exe (Windows)

Run `build.bat` from the project root. It activates the venv automatically if present, installs PyInstaller, and outputs a standalone `.exe` to the `dist/` folder.

## License

MIT
