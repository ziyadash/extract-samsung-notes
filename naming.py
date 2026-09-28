"""Turn Samsung Notes export filenames into clean ones: "Week 1_250223_101544.pdf" -> "Week 1.pdf"."""
import re

# Samsung appends _YYMMDD_HHMMSS (note's modified time), plus " (n)" if that name already existed.
_SUFFIX = re.compile(r"_\d{6}_\d{6}(?: \(\d+\))?$")


def clean_stem(filename: str) -> str:
    """Strip the .pdf extension and Samsung's timestamp suffix. Other underscores are kept."""
    stem = filename[:-4] if filename.lower().endswith(".pdf") else filename
    return _SUFFIX.sub("", stem).strip() or stem


def assign_names(filenames: list[str]) -> dict[str, str]:
    """Map each exported filename to a unique clean filename, adding " (2)", " (3)"… on collisions.

    Filenames are processed in sorted order so reruns give the same result.
    """
    used: set[str] = set()
    out = {}
    for f in sorted(filenames):
        stem = clean_stem(f)
        name, n = stem, 1
        while name.lower() in used:  # macOS filesystems are case-insensitive
            n += 1
            name = f"{stem} ({n})"
        used.add(name.lower())
        out[f] = name + ".pdf"
    return out
