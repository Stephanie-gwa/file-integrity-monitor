"""Directory snapshotting and baseline-vs-current diffing — the
one-shot, hash-based half of file integrity monitoring (the other half
is the real-time watcher in watcher.py).
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from .events import Alert, FileRecord
from .hashing import FileInaccessibleError, hash_file
from .storage import Baseline


@dataclass
class ScanResult:
    files: Dict[str, FileRecord] = field(default_factory=dict)
    inaccessible: List[str] = field(default_factory=list)  # relpaths that couldn't be hashed


def _to_relpath(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_excluded(path: Path, root: Path, exclude_dirs: List[Path]) -> bool:
    """True if `path` is inside any of `exclude_dirs` (compared as resolved,
    absolute paths so a relative vs. absolute mismatch can't slip through)."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    for ex in exclude_dirs:
        try:
            ex_resolved = ex.resolve()
        except OSError:
            ex_resolved = ex
        if resolved == ex_resolved or ex_resolved in resolved.parents:
            return True
    return False


def scan_directory(
    root: Union[str, Path], exclude_dirs: Optional[List[Union[str, Path]]] = None
) -> ScanResult:
    """Walk `root` and hash every regular file, skipping anything inside
    `exclude_dirs` (the tool's own store directory, typically). Files that
    can't be read are recorded in `.inaccessible` rather than raising —
    one unreadable file must never abort an entire scan.
    """
    root = Path(root)
    exclude_paths = [Path(e) for e in (exclude_dirs or [])]

    result = ScanResult()
    if not root.exists():
        return result

    for path in sorted(root.rglob("*")):
        if is_excluded(path, root, exclude_paths):
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            # sockets, FIFOs, broken symlinks, etc. — record as inaccessible
            # rather than silently ignoring them.
            result.inaccessible.append(_to_relpath(path, root))
            continue

        relpath = _to_relpath(path, root)
        try:
            digest = hash_file(path)
            stat = path.stat()
        except (FileInaccessibleError, OSError):
            result.inaccessible.append(relpath)
            continue

        result.files[relpath] = FileRecord(
            path=relpath, size=stat.st_size, mtime=stat.st_mtime, sha256=digest
        )

    return result


def build_baseline(
    root: Union[str, Path], exclude_dirs: Optional[List[Union[str, Path]]] = None
) -> "tuple[Baseline, ScanResult]":
    """Scan `root` and package the result as a Baseline ready to save,
    along with the raw ScanResult (so callers can report inaccessible
    files from the same pass)."""
    root = Path(root)
    result = scan_directory(root, exclude_dirs=exclude_dirs)
    baseline = Baseline(root=str(root), taken_at=datetime.now(), files=result.files)
    return baseline, result


def diff_snapshots(
    baseline_files: Dict[str, FileRecord],
    current_files: Dict[str, FileRecord],
    timestamp: Optional[datetime] = None,
) -> List[Alert]:
    """Compare a baseline's files against a current snapshot and return
    one Alert per created, modified, or deleted file. Comparison is by
    content hash, not mtime/size — a file rewritten with identical
    content is correctly treated as unchanged, and a file whose content
    changed but whose mtime didn't (e.g. a clock issue) is still caught.
    """
    ts = timestamp or datetime.now()
    alerts: List[Alert] = []

    baseline_paths = set(baseline_files)
    current_paths = set(current_files)

    for relpath in sorted(current_paths - baseline_paths):
        rec = current_files[relpath]
        alerts.append(Alert(
            kind="created",
            path=relpath,
            timestamp=ts,
            message=f"New file detected: {relpath}",
            new_record=rec,
        ))

    for relpath in sorted(baseline_paths - current_paths):
        rec = baseline_files[relpath]
        alerts.append(Alert(
            kind="deleted",
            path=relpath,
            timestamp=ts,
            message=f"File deleted: {relpath}",
            old_record=rec,
        ))

    for relpath in sorted(baseline_paths & current_paths):
        old = baseline_files[relpath]
        new = current_files[relpath]
        if old.sha256 != new.sha256:
            alerts.append(Alert(
                kind="modified",
                path=relpath,
                timestamp=ts,
                message=f"File modified: {relpath}",
                old_record=old,
                new_record=new,
            ))

    return alerts
