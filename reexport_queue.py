"""output/queue.json: folders the user has flagged (in the viewer) to be exported again.

Format: {"ELEC2141/Notes/Week 1": {"queued_at": "...", "notes": ["Lecture 3"]}, ...}
"notes" records which notes prompted it (empty = the folder itself); the whole folder is re-exported
either way, because an export always covers a full folder.
"""
import json
from pathlib import Path

QUEUE = Path(__file__).parent / "output" / "queue.json"


def load_queue() -> dict:
    return json.loads(QUEUE.read_text()) if QUEUE.exists() else {}


def save_queue(queue: dict):
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUEUE.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, indent=1, ensure_ascii=False))
    tmp.replace(QUEUE)
