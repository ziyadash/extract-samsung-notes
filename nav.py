"""Samsung Notes navigation over uiautomator2: connect, read a folder page, move between folders."""
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import uiautomator2 as u2

N = "com.samsung.android.app.notes:id/"
CONFIG = Path(__file__).parent / "config.json"  # personal settings, not committed (see config.example.json)
# top-level Samsung Notes folders never scanned or exported
SKIP_TOP_LEVEL = set(json.loads(CONFIG.read_text()).get("skip_top_level", [])) if CONFIG.exists() else set()


def connect():
    d = u2.connect()
    for _ in range(3):  # the on-device server sometimes drops the first calls after connecting
        try:
            d.info
            return d
        except Exception:
            time.sleep(2)
    return d


class NoteOpened(Exception):
    pass


def on_note_list(d) -> bool:
    cur = d.app_current()
    return cur.get("package") == "com.samsung.android.app.notes" and cur.get("activity", "").endswith("MemoListActivity")


def ensure_note_list(d):
    """Refuse to automate while a note is open in the editor, so we never tap around inside it."""
    if not on_note_list(d):
        raise SystemExit("Samsung Notes isn't showing the notes list (is a note open?). "
                         "Close it, go back to the folders screen, and rerun.")


def swipe(d, direction, scale):
    """Scroll the list; if that somehow opened a note, close it (Samsung autosaves) and stop."""
    d.swipe_ext(direction, scale=scale)
    if not on_note_list(d):
        d.press("back")
        raise NoteOpened("a swipe opened a note; closed it again")


def expand_folders(d):
    bar = d(resourceId=N + "expand_bar_layout", description="View more")
    if bar.exists:
        bar.click()
        time.sleep(1)


def parse(xml):
    """Return (subtitle, {folder: count}, [(title, date)]) visible in one hierarchy dump."""
    root = ET.fromstring(xml)
    subtitle, folders, notes = None, {}, []
    for n in root.iter("node"):
        rid = n.get("resource-id", "")
        if rid == N + "collapsing_appbar_extended_subtitle":
            subtitle = n.get("text")
        elif rid.startswith(N + "sub_folder_list_item") and n.get("content-desc", "").startswith("Folder, "):
            name, _, count = n.get("content-desc")[len("Folder, "):].rpartition(" , ")
            folders[name] = int(count)
        elif rid == N + "root_cardview":
            title = n.find(f'.//node[@resource-id="{N}title"]')
            date = n.find(f'.//node[@resource-id="{N}time"]')
            if title is not None and date is not None:  # skip cards cut off at the screen edge
                notes.append((title.get("text", "").replace("\u200e", ""), date.get("text", "")))
    return subtitle, folders, notes


def read_page(d):
    """Scroll through the current folder page, collecting subfolder cards and notes (title, date)."""
    expand_folders(d)
    subtitle, folders, notes = None, {}, {}
    while True:
        sub, f, ns = parse(d.dump_hierarchy())
        subtitle = subtitle or sub
        before = len(folders) + len(notes)
        folders.update(f)
        notes.update(dict.fromkeys(ns))
        if len(folders) + len(notes) == before:  # last scroll revealed nothing new: end of page
            break
        swipe(d, "up", 0.7)
        time.sleep(0.4)
    return subtitle, folders, [list(k) for k in notes]


def scroll_to_top(d):
    """Swipe down until the expanded header (big title) is showing, i.e. the page is at the top."""
    for _ in range(15):
        if d(resourceId=N + "collapsing_appbar_extended_title").exists:
            break
        swipe(d, "down", 0.8)
        time.sleep(0.3)
    time.sleep(0.5)  # let any fling settle before tapping


def crumbs(d):
    # read from one dump: iterating a live selector races with screen transitions
    root = ET.fromstring(d.dump_hierarchy())
    return [n.get("text") for n in root.iter("node") if n.get("resource-id") == N + "folderpath_text"]


class FolderNotFound(Exception):
    pass


def open_child(d, name):
    scroll_to_top(d)
    expand_folders(d)
    before = crumbs(d)
    _, folders, _ = parse(d.dump_hierarchy())
    if name not in folders:
        where = "/".join(before) or "the Folders home screen"
        raise FolderNotFound(f"no folder {name!r} in {where}; folders there: {sorted(folders)}")
    d.xpath(f'//*[starts-with(@content-desc, "Folder, {name} , ")]').click()  # card desc: "Folder, NAME , COUNT"
    for _ in range(20):  # wait for the breadcrumb to show the new folder
        if crumbs(d) == before + [name]:
            return
        time.sleep(0.25)
    raise RuntimeError(f"tapped folder {name!r} but breadcrumb shows {crumbs(d)}")


def go_to(d, path):
    """Navigate to a folder path from the Folders root via taps."""
    if d(resourceId=N + "folderpath_home").click_exists(timeout=1):
        for _ in range(20):
            if not crumbs(d):
                break
            time.sleep(0.25)
    for name in path:
        open_child(d, name)


def header_counts(subtitle):
    """Parse the folder header, e.g. "2 folders, 3 notes" / "1 note" -> (folders, notes)."""
    def grab(word):
        m = re.search(rf"(\d+) {word}s?\b", subtitle or "")
        return int(m.group(1)) if m else 0
    return grab("folder"), grab("note")


def parse_folder_paths(values: list[str]) -> list[list[str]]:
    """Validate --folders arguments: each must be "Folder" or "Folder/Sub/SubSub", nothing else.

    Returns the paths as lists of names, with duplicates and paths inside another given path dropped.
    """
    paths = []
    for raw in values:
        parts = raw.split("/")
        if not raw or any(p == "" or p != p.strip() or p in (".", "..") for p in parts):
            raise ValueError(f"invalid folder path {raw!r}: use Folder or Folder/Sub/SubSub "
                             "(no leading/trailing '/', no empty parts, no spaces around '/')")
        if parts[0] in SKIP_TOP_LEVEL:
            raise ValueError(f"{raw!r} is in {parts[0]!r}, which is excluded from exports")
        paths.append(parts)
    kept = []
    for p in sorted(paths, key=len):
        if not any(p[:len(k)] == k for k in kept):  # already covered by an ancestor (or duplicate)
            kept.append(p)
    return kept
