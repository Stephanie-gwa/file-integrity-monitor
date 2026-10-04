"""Builds the sample folder the CLI defaults its demo to, and the
deterministic sequence of changes `fim demo` applies to it afterward so
a complete created/modified/deleted/inaccessible walkthrough works with
zero manual file editing.
"""

import os
from pathlib import Path
from typing import Union

DEFAULT_SAMPLE_DIR = "sample_data/watched_demo"


def create_sample_folder(path: Union[str, Path]) -> Path:
    """Create (or reset) a small demo directory with a few ordinary
    files plus one broken symlink, so the monitor's "inaccessible" path
    has something real to report even when running as root (where a
    plain permission-denied file wouldn't actually be inaccessible)."""
    root = Path(path)
    root.mkdir(parents=True, exist_ok=True)

    (root / "readme.txt").write_text(
        "This is a sample folder used to demo the file integrity monitor.\n"
        "Nothing in here is sensitive — it's safe to create, edit, and delete freely.\n",
        encoding="utf-8",
    )
    (root / "config.ini").write_text(
        "[demo]\nmode = sample\nversion = 1\n", encoding="utf-8"
    )
    (root / "notes.md").write_text(
        "# Notes\n\n- This file will be modified during the demo.\n", encoding="utf-8"
    )

    subdir = root / "subdir"
    subdir.mkdir(exist_ok=True)
    (subdir / "nested.txt").write_text("A file in a nested directory.\n", encoding="utf-8")

    # A broken symlink: reliably "inaccessible" to hash regardless of who
    # runs the demo (unlike a chmod'd file, which running as root defeats).
    broken_link = root / "broken_link.txt"
    target = root / "this_target_does_not_exist.txt"
    try:
        if broken_link.exists() or broken_link.is_symlink():
            broken_link.unlink()
        os.symlink(target, broken_link)
    except OSError:
        pass  # symlinks unsupported on this filesystem; demo still works without it

    return root


def apply_demo_changes(path: Union[str, Path]) -> None:
    """Deterministically create, modify, and delete specific files in the
    sample folder, for `fim demo` to show off all three alert kinds in a
    single, scripted pass."""
    root = Path(path)

    # created
    (root / "new_file.txt").write_text("This file did not exist in the baseline.\n", encoding="utf-8")

    # modified
    notes = root / "notes.md"
    notes.write_text(notes.read_text(encoding="utf-8") + "- This line was added after the baseline.\n",
                      encoding="utf-8")

    # deleted
    (root / "config.ini").unlink()
