"""Export Samsung Notes to PDFs on this Mac, mirroring the folder tree.

Per folder: select every note → More → Save as → PDF file → Standard PDF → save into
/sdcard/NotesExport on the tablet, wait for the files, adb pull them into output/<folder path>/,
strip Samsung's _YYMMDD_HHMMSS suffix, verify, then clear the staging folder.

Folders already exported are skipped unless they've gained new notes since (the manifest remembers
each folder's notes) or you queued them in the viewer (output/queue.json); then the whole folder is
exported again. Edits to existing notes are otherwise ignored.

Usage:
  .venv/bin/python export_notes.py                                   # everything
  .venv/bin/python export_notes.py --folders MATH3411 ELEC4612 PHYS3116
  .venv/bin/python export_notes.py --folders "TELE3113/Labs/Lab 1"   # one subfolder
  .venv/bin/python export_notes.py --queued                          # only folders queued in the viewer
  .venv/bin/python export_notes.py --dry-run                         # show what would export
"""
import argparse
import json
import shutil
import subprocess
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from nav import (N, SKIP_TOP_LEVEL, FolderNotFound, connect, ensure_note_list, go_to, header_counts,
                 on_note_list, parse_folder_paths, read_page, scroll_to_top)
from naming import assign_names, clean_stem
from reexport_queue import load_queue, save_queue

M = "com.sec.android.app.myfiles:id/"
STAGING = "/sdcard/NotesExport"
STAGING_NAME = "NotesExport"
ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"
MANIFEST = OUTPUT / "manifest.json"
ERRORS = OUTPUT / "errors"
MAX_CONSECUTIVE_FAILURES = 3


class ExportError(Exception):
    pass


# ---------- tablet storage (adb) ----------

def adb(*args, check=True):
    return subprocess.run(["adb", *args], capture_output=True, text=True, check=check).stdout


def staging_files() -> dict[str, int]:
    """PDFs currently in the staging folder, name -> size in bytes."""
    out = adb("shell", f"stat -c '%s %n' {STAGING}/*.pdf 2>/dev/null", check=False)
    files = {}
    for line in out.splitlines():
        size, _, path = line.partition(" ")
        if size.isdigit():
            files[path.rsplit("/", 1)[-1]] = int(size)
    return files


def clear_staging():
    adb("shell", f"mkdir -p {STAGING} && rm -f {STAGING}/*.pdf")


def wait_for_files(expected: int) -> list[str]:
    """Wait until `expected` PDFs exist and none has changed size for 3 s (Samsung writes them gradually)."""
    deadline = time.time() + 60 + 30 * expected
    last, stable_since = None, time.time()
    while time.time() < deadline:
        files = staging_files()
        if len(files) > expected:
            raise ExportError(f"expected {expected} PDFs in staging, found {len(files)}: {sorted(files)}")
        if files != last:
            last, stable_since = files, time.time()
        elif len(files) == expected and time.time() - stable_since >= 3:
            return sorted(files)
        time.sleep(1)
    raise ExportError(f"timed out: {len(last or {})} of {expected} PDFs appeared")


# ---------- Samsung Notes UI ----------

def selected_count(d):
    info = d(resourceId=N + "check_info")
    return info.get_text(timeout=3) if info.exists else None


def select_notes(d, n_notes: int, has_folders: bool):
    """Enter selection mode with exactly the folder's notes selected (never its subfolders).

    Uses ⋮ → Select rather than long-pressing a note: a long-press can register as a tap and open
    the note in the editor.
    """
    scroll_to_top(d)
    d(description="More options", packageName="com.samsung.android.app.notes").click()
    d(resourceId=N + "title", text="Select").click(timeout=5)
    if not d(resourceId=N + "checkbox_withtext").wait(timeout=5):
        raise ExportError("⋮ → Select did not enter selection mode")
    d(resourceId=N + "checkbox_withtext").click()  # "All": also ticks subfolder cards
    time.sleep(0.8)
    if has_folders:
        scroll_to_top(d)
        for folder in d.xpath(f'//*[starts-with(@resource-id, "{N}sub_folder_list_item")][@checked="true"]').all():
            folder.click()
            time.sleep(0.3)
    if not on_note_list(d):
        d.press("back")
        raise ExportError("a note opened during selection; closed it again")
    want = f"{n_notes} selected"
    for _ in range(10):
        if selected_count(d) == want:
            return
        time.sleep(0.3)
    raise ExportError(f"selection shows {selected_count(d)!r}, expected {want!r}")


def save_selected_as_pdf(d, n_notes: int):
    d(resourceId=N + "bottom_overflow").click()
    d(resourceId=N + "title", text="Save as").click(timeout=5)
    d(resourceId=N + "item_text", text="PDF file").click(timeout=5)
    d(resourceId=N + "format_standard").click(timeout=5)

    # My Files folder picker: always opens at the storage root
    if not d(resourceId=M + "menu_done").wait(timeout=10):
        raise ExportError("folder picker did not open")
    d(resourceId=M + "recycler_view").scroll.to(text=STAGING_NAME)
    d(resourceId=M + "main_text", text=STAGING_NAME).click(timeout=5)
    for _ in range(12):
        path = [e.get_text() for e in d(resourceId=M + "path")] if d(resourceId=M + "path").exists else []
        if path[-1:] == [STAGING_NAME]:
            break
        time.sleep(0.25)
    else:
        raise ExportError(f"picker is at {path}, not {STAGING_NAME}")
    d(resourceId=M + "menu_done").click()

    if n_notes == 1:  # single-note export asks for a file name; keep Samsung's default (renamed on the Mac)
        if d(resourceId=N + "text_input_dialog").wait(timeout=8):
            d(resourceId="android:id/button1", text="Save").click()


def leave_selection_mode(d):
    if d(resourceId=N + "check_info").exists:
        d(resourceId=N + "action_done").click_exists(timeout=2)


def recover(d):
    """Get back to a usable Samsung Notes screen after a failure."""
    for _ in range(4):
        if d.app_current().get("package") == "com.samsung.android.app.notes" and \
                not d(resourceId=M + "menu_done").exists and not d(resourceId=N + "check_info").exists:
            return
        d.press("back")
        time.sleep(0.8)
    d.app_stop("com.samsung.android.app.notes")
    d.app_start("com.samsung.android.app.notes")
    time.sleep(2)


# ---------- Mac side ----------

def is_complete_pdf(p: Path) -> bool:
    data = p.read_bytes()
    return data[:5] == b"%PDF-" and b"%%EOF" in data[-1024:]


def pull_folder(path: list[str], files: list[str], titles: list[str]) -> tuple[list[str], list[str]]:
    """Pull staged PDFs into output/<path>/ with clean names. Returns (written names, warnings)."""
    incoming = OUTPUT / ".incoming"
    shutil.rmtree(incoming, ignore_errors=True)
    incoming.mkdir(parents=True)
    for f in files:
        adb("pull", f"{STAGING}/{f}", str(incoming / f))
        if not is_complete_pdf(incoming / f):
            raise ExportError(f"pulled file is not a complete PDF: {f}")

    dest = OUTPUT.joinpath(*path)
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*.pdf"):  # previous export of this folder (or a failed attempt): replaced wholesale
        old.unlink()
    names = assign_names(files)
    for f, name in names.items():
        (incoming / f).rename(dest / name)
    shutil.rmtree(incoming)

    warnings = []
    stems = {clean_stem(f) for f in files}
    missing = [t for t in titles if t not in stems]
    if missing:  # titles with characters Samsung changes in filenames (e.g. "/") land here; not fatal
        warnings.append(f"titles without an exact filename match: {missing}")
    return sorted(names.values()), warnings


# ---------- manifest / errors ----------

def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def save_manifest(manifest: dict):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    tmp.replace(MANIFEST)


def save_error_artifacts(d, key: str) -> Path:
    folder = ERRORS / f"{datetime.now():%Y%m%d-%H%M%S}_{key.replace('/', '__')}"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        d.screenshot(str(folder / "screen.png"))
        (folder / "hierarchy.xml").write_text(d.dump_hierarchy())
    except Exception as e:  # artifacts are best effort
        (folder / "artifact_error.txt").write_text(repr(e))
    return folder


# ---------- traversal ----------

class Run:
    def __init__(self, d, dry_run: bool):
        self.d, self.dry_run = d, dry_run
        self.manifest = load_manifest()
        self.queue = load_queue()
        self.consecutive_failures = 0
        self.exported = 0

    def needs_export(self, key, notes, n_notes) -> bool:
        """New folders and failed ones export; done ones only if they gained notes (edits are ignored)."""
        prev = self.manifest.get(key, {})
        if key in self.queue:
            print("    queued in the viewer", flush=True)
            return True
        if prev.get("status") == "failed":
            print("    retrying (last attempt failed)", flush=True)
            return True
        if not prev:
            print("    new folder", flush=True)
            return True
        added = Counter(t for t, _ in notes) - Counter(t for t, _ in prev.get("notes", []))
        if "notes" not in prev:  # exported before note lists were recorded: only the count is known
            added = Counter() if n_notes <= prev.get("count", 0) else added
        if not added and n_notes <= prev.get("count", 0):
            print("    no new notes, skipping", flush=True)
            return False
        print(f"    new notes: {sorted(added.elements())} -> re-exporting folder "
              f"({prev.get('count')} -> {n_notes} PDFs)", flush=True)
        return True

    def export_folder(self, path, notes, n_notes, has_folders):
        key = "/".join(path)
        if not self.needs_export(key, notes, n_notes) or self.dry_run:
            return
        titles = [t for t, _ in notes]
        d = self.d
        started = time.time()
        try:
            clear_staging()
            select_notes(d, n_notes, has_folders)
            save_selected_as_pdf(d, n_notes)
            files = wait_for_files(n_notes)
            leave_selection_mode(d)
            names, warnings = pull_folder(path, files, titles)
            clear_staging()
        except Exception as e:
            artifacts = save_error_artifacts(d, key)
            prev = self.manifest.get(key, {})
            self.manifest[key] = {
                "status": "failed", "expected": n_notes, "error": f"{type(e).__name__}: {e}",
                "artifacts": str(artifacts.relative_to(ROOT)), "at": datetime.now().isoformat(),
                # keep what the last successful export produced: those PDFs are still in output/
                "last_done": prev.get("last_done") if prev.get("status") == "failed" else (prev or None),
            }
            save_manifest(self.manifest)
            print(f"    FAILED: {e}  (artifacts: {artifacts.relative_to(ROOT)})", flush=True)
            self.consecutive_failures += 1
            if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                raise SystemExit(f"Stopping: {self.consecutive_failures} folders failed in a row.")
            recover(d)
            return
        self.consecutive_failures = 0
        self.exported += len(names)
        self.manifest[key] = {"status": "done", "count": len(names), "notes": notes, "files": names,
                              "warnings": warnings,
                              "seconds": round(time.time() - started, 1), "at": datetime.now().isoformat()}
        save_manifest(self.manifest)
        if key in self.queue:
            self.queue = load_queue()  # re-read: the viewer may have changed it during the run
            self.queue.pop(key, None)
            save_queue(self.queue)
        print(f"    exported {len(names)} PDFs in {time.time() - started:.0f}s"
              + (f"  WARN: {'; '.join(warnings)}" if warnings else ""), flush=True)

    def visit(self, path, recurse=True):
        subtitle, folders, notes = read_page(self.d)
        n_folders, n_notes = header_counts(subtitle)
        n_notes = max(n_notes, len(notes))  # header is authoritative; duplicates collapse in `notes`
        print(f"{'  ' * len(path)}{'/'.join(path) or '<Folders>'}: {n_notes} notes, {len(folders)} folders",
              flush=True)
        if path and n_notes:  # loose notes on the Folders home screen are excluded
            self.export_folder(path, sorted(notes), n_notes, bool(folders))
        for name in folders if recurse else []:
            if not path and name in SKIP_TOP_LEVEL:
                continue
            child = path + [name]
            go_to(self.d, child)
            self.visit(child)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folders", nargs="+", metavar="PATH",
                    help='only these folders (with their subfolders), e.g. MATH3411 "TELE3113/Labs/Lab 1"')
    ap.add_argument("--queued", action="store_true", help="only the folders queued in the viewer (not their subfolders)")
    ap.add_argument("--dry-run", action="store_true", help="show which folders would be exported, export nothing")
    args = ap.parse_args()
    if args.folders and args.queued:
        ap.error("use either --folders or --queued, not both")
    try:
        if args.queued:  # each queued folder on its own: a queued parent must not hide a queued child
            targets = [parse_folder_paths([k])[0] for k in load_queue()]
            if not targets:
                raise SystemExit("Nothing is queued (output/queue.json is empty).")
        else:
            targets = parse_folder_paths(args.folders) if args.folders else [[]]
    except ValueError as e:
        ap.error(str(e))

    d = connect()
    adb("shell", "svc power stayon usb")  # a sleeping/locked screen breaks the UI automation
    d.app_start("com.samsung.android.app.notes")
    time.sleep(2)
    ensure_note_list(d)
    try:  # check every target exists before exporting anything
        for path in targets:
            go_to(d, path)
    except FolderNotFound as e:
        raise SystemExit(f"Nothing exported: {e}")
    run = Run(d, args.dry_run)
    try:
        for path in targets:
            go_to(d, path)
            run.visit(path, recurse=not args.queued)
    finally:
        failed = [k for k, v in run.manifest.items() if v.get("status") == "failed"]
        print(f"\nExported {run.exported} PDFs this run. Failed folders: {failed or 'none'}")


if __name__ == "__main__":
    main()
