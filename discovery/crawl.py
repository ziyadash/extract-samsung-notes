"""Read-only crawl of the Samsung Notes folder tree. Writes discovery/tree.json and prints the tree.

Usage:
  .venv/bin/python discovery/crawl.py                                  # rescan everything
  .venv/bin/python discovery/crawl.py --folders MATH3411 "ELEC4612/Labs"
      rescan only these folders (with subfolders) and replace them in the existing tree.json
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from nav import (SKIP_TOP_LEVEL, FolderNotFound, connect, ensure_note_list, go_to,  # noqa: E402
                 parse_folder_paths, read_page)

OUT = Path(__file__).parent / "tree.json"


def visit(d, path, counts):
    subtitle, folders, notes = read_page(d)
    node = {"path": path, "card_count": counts, "subtitle": subtitle, "notes": notes, "children": []}
    print(f"{'  ' * len(path)}{'/'.join(path) or '<root>'}: {len(notes)} notes, {len(folders)} folders"
          f"  [header: {subtitle}, card: {counts}]", flush=True)
    for name, count in folders.items():
        if not path and name in SKIP_TOP_LEVEL:
            continue
        child_path = path + [name]
        go_to(d, child_path)
        node["children"].append(visit(d, child_path, count))
    return node


def graft(tree, node):
    """Put a rescanned subtree into the full tree, replacing the old copy of that folder."""
    parent = tree
    for depth in range(1, len(node["path"])):
        parent = next((c for c in parent["children"] if c["path"] == node["path"][:depth]), None)
        if parent is None:
            raise SystemExit(f"{'/'.join(node['path'][:depth])} is not in tree.json yet; "
                             f"rescan it with --folders {'/'.join(node['path'][:depth])!r}")
    parent["children"] = [c for c in parent["children"] if c["path"] != node["path"]] + [node]


def total(n):
    return len(n["notes"]) + sum(total(c) for c in n["children"])


def nfolders(n):
    return len(n["children"]) + sum(nfolders(c) for c in n["children"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folders", nargs="+", metavar="PATH",
                    help='rescan only these folders, e.g. MATH3411 "TELE3113/Labs/Lab 1"')
    args = ap.parse_args()
    try:
        targets = parse_folder_paths(args.folders) if args.folders else None
    except ValueError as e:
        ap.error(str(e))
    if targets and not OUT.exists():
        ap.error(f"{OUT} doesn't exist yet: run a full scan (no --folders) first")

    d = connect()
    d.app_start("com.samsung.android.app.notes")
    time.sleep(2)
    ensure_note_list(d)
    if targets is None:
        go_to(d, [])
        tree = visit(d, [], None)
    else:
        tree = json.loads(OUT.read_text())
        try:
            for path in targets:  # check every target exists before scanning anything
                go_to(d, path)
        except FolderNotFound as e:
            raise SystemExit(f"tree.json unchanged: {e}")
        for path in targets:
            go_to(d, path)
            graft(tree, visit(d, path, None))
    OUT.write_text(json.dumps(tree, indent=1, ensure_ascii=False))
    print(f"\nTree now has {total(tree)} notes in {nfolders(tree)} folders (incl. the Folders home screen).")


if __name__ == "__main__":
    main()
