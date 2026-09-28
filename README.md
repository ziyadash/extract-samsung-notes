# Samsung Notes exporter

Bulk-export every note in the Samsung Notes Android app to PDFs on a Mac, keeping the app's folder
structure. No root, no reverse-engineering of `.sdocx`: a Python script drives the tablet's UI over
ADB with [uiautomator2](https://github.com/openatx/uiautomator2) and uses the app's own
**Save as → PDF** export, one folder at a time.

```
Samsung Notes                    output/
─────────────                    ───────
TELE3113/                        TELE3113/
  Labs/                            Labs/
    Lab 1/                           Lab 1/
      Prelab                           Prelab.pdf
      Report                           Report.pdf
  Notes/                           Notes/
    Week 1                           Week 1.pdf
    …                                …
```

It keeps a manifest of what's been exported, so reruns only pick up folders that are new, failed,
gained notes, or that you queued for re-export. A local web viewer shows the whole tree coloured by
status and lets you queue things for re-export.

## How it works

For each Samsung Notes folder that holds notes:

1. **⋮ → Select → All**, then untick any subfolder cards, so exactly the folder's notes are selected
   (checked against the note count in the folder header).
2. **More → Save as → PDF file → Standard PDF**, and pick the staging folder `/sdcard/NotesExport`
   in the file picker.
3. Wait until the expected number of PDFs exist and have stopped growing (Samsung writes them gradually).
4. `adb pull` them into `output/<folder path>/`, check each is a complete PDF, and strip Samsung's
   `_YYMMDD_HHMMSS` suffix (`Week 1_250223_101544.pdf` → `Week 1.pdf`; same-name notes get ` (2)`).
5. Record the folder in `output/manifest.json` and clear the staging folder.

A failed folder saves a screenshot and UI dump to `output/errors/`, is marked `failed`, and is
retried on the next run. The run stops after 3 consecutive failures.

## Setup

Needs a Mac (or Linux) with Python 3.11+ and `adb`, and an Android tablet/phone with Samsung Notes.

```bash
brew install android-platform-tools
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp config.example.json config.json   # list top-level folders to never touch, or leave it empty
```

On the tablet: Settings → About → Software information → tap **Build number** 7 times, then
Developer options → **USB debugging** on. Plug it in, accept the prompt, and check `adb devices`
lists it. Open Samsung Notes on the **Folders** screen (not inside a note) before running anything.
The scripts keep the screen awake while it's plugged in (`svc power stayon usb`).

## Usage

```bash
# Read-only scan of the folder tree → discovery/tree.json (feeds the viewer)
.venv/bin/python discovery/crawl.py
.venv/bin/python discovery/crawl.py --folders MATH3411 "TELE3113/Labs"   # rescan just these

# Export (skips folders with nothing new)
.venv/bin/python -u export_notes.py
.venv/bin/python -u export_notes.py --folders MATH3411 ELEC4612   # only these (and subfolders)
.venv/bin/python -u export_notes.py --queued                      # only what you queued in the viewer
.venv/bin/python -u export_notes.py --dry-run                     # show what would be exported

# Viewer → http://127.0.0.1:8765
.venv/bin/python viewer.py
```

`--folders` accepts only `Folder` or `Folder/Sub/SubSub` paths, and checks every one exists on the
tablet before doing anything.

### The viewer

Every folder and note from the last scan, coloured by status: **exported**, **not exported**,
**new notes** (exported folder that has gained notes), **queued**, **failed**, **excluded**. Search,
filter by status, and click anything for details (last export, files, errors). Switch to **Edit** to
queue notes or folders for re-export; queuing a note queues its folder, since exports are per folder.
The queue lives in `output/queue.json`, and `export_notes.py --queued` works through it.

## When is a folder exported again?

- It has never been exported, or its last attempt failed.
- It has notes that weren't in its last export (new or renamed notes). Edits to existing notes don't count.
- You queued it in the viewer.

A re-export replaces the folder's PDFs wholesale, so there are never duplicates, even after a crash.

**Don't delete or move files inside `output/`**: the manifest won't know, and the folder won't be
re-exported. Copy PDFs out instead, and use the viewer's queue to re-export. To start over, delete
the whole `output/` directory.

## Caveats

- Built against Samsung Notes 4.4 on a Galaxy Tab S6 Lite (Android 14, One UI, English, portrait).
  The UI selectors (resource IDs and labels) may differ on other versions or languages; use
  `discovery/dump.py` to inspect a screen.
- Loose notes on the Folders home screen are never exported.
- Notes are identified by title and the date shown in the list; two notes with the same title and
  date in one folder are counted from the folder header rather than individually.

## Tests

```bash
.venv/bin/python -m pytest -q
```
