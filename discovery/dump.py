"""Debug helper: save a screenshot + UI hierarchy of the current screen and print a compact element list.

Usage: .venv/bin/python discovery/dump.py <name>
"""
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import uiautomator2 as u2

OUT = Path(__file__).parent / "dumps"


def summarize(xml: str) -> list[str]:
    lines = []
    for n in ET.fromstring(xml).iter("node"):
        a = n.attrib
        rid = a.get("resource-id", "").split(":id/")[-1]
        text, desc = a.get("text", ""), a.get("content-desc", "")
        flags = "".join(f for f, k in (("C", "clickable"), ("L", "long-clickable"), ("S", "scrollable")) if a.get(k) == "true")
        if not (rid or text or desc or flags):
            continue
        cls = a.get("class", "").split(".")[-1]
        lines.append(f"{cls:<22} id={rid!r:<40} text={text!r:<40} desc={desc!r:<30} {flags:<3} {a.get('bounds')}")
    return lines


def retry(fn, tries=3):
    """The on-device server sometimes drops the first calls after connecting; retry them."""
    for attempt in range(tries):
        try:
            return fn()
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2)


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "screen"
    OUT.mkdir(parents=True, exist_ok=True)
    d = u2.connect()
    xml = retry(d.dump_hierarchy)
    (OUT / f"{name}.xml").write_text(xml)
    retry(lambda: d.screenshot(str(OUT / f"{name}.png")))
    print(d.app_current())
    print("\n".join(summarize(xml)))


if __name__ == "__main__":
    main()
