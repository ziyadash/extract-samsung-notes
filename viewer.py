"""Local viewer for the export: the scanned folder tree (discovery/tree.json) coloured by export status
(output/manifest.json). In edit mode, folders and notes can be queued for re-export (output/queue.json),
which `export_notes.py --queued` (or any normal run) picks up.

Usage: .venv/bin/python viewer.py   → opens http://127.0.0.1:8765  (--no-browser to just serve)
"""
import json
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nav import SKIP_TOP_LEVEL
from reexport_queue import load_queue, save_queue

ROOT = Path(__file__).parent
TREE = ROOT / "discovery" / "tree.json"
MANIFEST = ROOT / "output" / "manifest.json"
PAGE = ROOT / "viewer.html"
HOST, PORT = "127.0.0.1", 8765


def read_json(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def mtime(p: Path):
    return datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds") if p.exists() else None


def exportable_folders(tree) -> set[str]:
    """Folder keys that hold notes (the only things an export can target). Home-screen notes are excluded."""
    keys = set()

    def walk(n):
        if n["path"] and n["notes"]:
            keys.add("/".join(n["path"]))
        for c in n["children"]:
            walk(c)
    walk(tree)
    return keys


def state():
    return {
        "tree": read_json(TREE, None),
        "manifest": read_json(MANIFEST, {}),
        "queue": load_queue(),
        "skipped": sorted(SKIP_TOP_LEVEL),
        "scanned_at": mtime(TREE),
        "manifest_at": mtime(MANIFEST),
    }


def change_queue(req: dict) -> dict:
    """{"action": "add"|"remove", "paths": [folder keys], "note": optional title prompting it}."""
    valid = exportable_folders(read_json(TREE, {"path": [], "notes": [], "children": []}))
    paths = req.get("paths") or []
    bad = [p for p in paths if p not in valid]
    if not paths or bad or req.get("action") not in ("add", "remove"):
        raise ValueError(f"invalid request (unknown folders: {bad})" if bad else "invalid request")
    queue = load_queue()
    for p in paths:
        if req["action"] == "remove":
            queue.pop(p, None)
            continue
        entry = queue.setdefault(p, {"queued_at": datetime.now().isoformat(timespec="seconds"), "notes": []})
        if req.get("note") and req["note"] not in entry["notes"]:
            entry["notes"].append(req["note"])
    save_queue(queue)
    return queue


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self.send(200, json.dumps(state(), ensure_ascii=False).encode())
        else:
            self.send(404, b'{"error": "not found"}')

    def do_POST(self):
        if self.path != "/api/queue":
            return self.send(404, b'{"error": "not found"}')
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            queue = change_queue(req)
        except (ValueError, json.JSONDecodeError) as e:
            return self.send(400, json.dumps({"error": str(e)}).encode())
        self.send(200, json.dumps({"queue": queue}, ensure_ascii=False).encode())

    def log_message(self, fmt, *args):  # keep the terminal quiet
        pass


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Viewer running at {url}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
