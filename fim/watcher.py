"""Real-time monitoring: filesystem events (via `watchdog`) tell us
*when* something in the watched directory might have changed; we then
re-hash that specific file and compare it against the baseline to
decide definitively *what* changed (created / modified / deleted), or
whether nothing actually changed at all.

Rapid repeated changes
-----------------------
Editors, package managers, and build tools routinely fire several raw
filesystem events for what a person would call "one edit" (write, then
flush, then touch the mtime, etc.), and some tools write-then-delete a
temp file as part of an atomic save. Reacting to every raw event
individually would flood the alert log with noise and misclassify
plenty of those intermediate states.

Instead, every touched path is only *marked dirty* with a timestamp.
A separate flush step only resolves a path once it has been quiet for
`debounce_seconds` — at which point we hash it exactly once and emit
at most one alert for the whole burst (or zero, if the net effect was
no change at all, e.g. a save that reverted to the original content).
"""

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .events import Alert, FileRecord
from .hashing import FileInaccessibleError, hash_file
from .scanner import is_excluded
from .storage import Baseline

DEFAULT_DEBOUNCE_SECONDS = 0.75
DEFAULT_POLL_INTERVAL = 0.1


class _TouchHandler(FileSystemEventHandler):
    """Translates raw watchdog events into "this path might have
    changed" notifications, filtering out directories and anything
    inside an excluded directory (the tool's own store, typically)."""

    def __init__(self, root: Path, exclude_dirs: List[Path], on_touch: Callable[[Path], None]):
        self.root = root
        self.exclude_dirs = exclude_dirs
        self.on_touch = on_touch

    def _maybe_touch(self, raw_path: str) -> None:
        path = Path(raw_path)
        if is_excluded(path, self.root, self.exclude_dirs):
            return
        self.on_touch(path)

    def on_created(self, event):
        if not event.is_directory:
            self._maybe_touch(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._maybe_touch(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._maybe_touch(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._maybe_touch(event.src_path)
            self._maybe_touch(event.dest_path)


@dataclass
class FileWatcher:
    """Owns the live baseline, the debounced "dirty path" queue, and
    (optionally) a real watchdog Observer. `process_ready()` can also be
    driven manually/synchronously, which is what the test suite does to
    exercise debounce behavior without timing-sensitive sleeps.
    """

    root: Path
    store_dir: Path
    baseline: Baseline
    exclude_dirs: List[Path] = field(default_factory=list)
    debounce_seconds: float = DEFAULT_DEBOUNCE_SECONDS
    on_alert: Optional[Callable[[Alert], None]] = None

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        self.store_dir = Path(self.store_dir)
        resolved_excludes = [Path(e) for e in self.exclude_dirs]
        if self.store_dir not in resolved_excludes:
            resolved_excludes.append(self.store_dir)
        self.exclude_dirs = resolved_excludes

        self._pending: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._observer: Optional[Observer] = None
        self._stop_flag = threading.Event()

    # ---- touching / queuing -------------------------------------------------

    def _relpath(self, path: Path) -> Optional[str]:
        # Deliberately normalize rather than fully resolve(): resolve()
        # follows symlinks, which for a *broken* symlink silently swaps in
        # its (non-existent) target path and loses track of the symlink
        # itself — exactly the file we need to report as inaccessible.
        try:
            abs_path = path if path.is_absolute() else (self.root / path)
            abs_path = Path(os.path.normpath(str(abs_path)))
            return abs_path.relative_to(self.root).as_posix()
        except (ValueError, OSError):
            return None

    def touch(self, path: Union[str, Path]) -> None:
        """Mark a path as possibly-changed, resetting its debounce timer.
        Public so tests (and, in principle, other event sources) can drive
        the queue directly without a real filesystem watch."""
        relpath = self._relpath(Path(path))
        if relpath is None:
            return
        with self._lock:
            self._pending[relpath] = time.monotonic()

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def _flush_ready(self) -> List[str]:
        now = time.monotonic()
        ready = []
        with self._lock:
            for relpath, last in list(self._pending.items()):
                if now - last >= self.debounce_seconds:
                    ready.append(relpath)
                    del self._pending[relpath]
        return ready

    # ---- resolving a quieted-down path --------------------------------------

    def process_ready(self) -> List[Alert]:
        """Resolve every path that has been quiet for >= debounce_seconds
        against the current baseline, update the baseline in place, and
        return the (possibly empty) list of resulting alerts."""
        alerts: List[Alert] = []
        for relpath in self._flush_ready():
            alert = self._resolve(relpath)
            if alert is not None:
                alerts.append(alert)
                if self.on_alert:
                    self.on_alert(alert)
        return alerts

    def _resolve(self, relpath: str) -> Optional[Alert]:
        full_path = self.root / relpath
        ts = datetime.now()
        existing = self.baseline.files.get(relpath)

        # Distinguish "truly gone" (a plain is_file() check would also call
        # a broken symlink "gone", but it's really present-and-unreadable —
        # that needs to surface as inaccessible, not get silently dropped).
        try:
            truly_absent = not full_path.exists() and not full_path.is_symlink()
        except OSError:
            truly_absent = True

        if truly_absent:
            if existing is None:
                # Created and deleted again within one debounce window
                # (e.g. an editor's atomic-save temp file) — no net change.
                return None
            del self.baseline.files[relpath]
            return Alert(
                kind="deleted", path=relpath, timestamp=ts,
                message=f"File deleted: {relpath}", old_record=existing,
            )

        try:
            digest = hash_file(full_path)
            stat = full_path.stat()
        except FileInaccessibleError as exc:
            return Alert(
                kind="inaccessible", path=relpath, timestamp=ts,
                message=f"Could not read {relpath}: {exc.reason}",
                detail={"reason": exc.reason},
            )

        new_record = FileRecord(path=relpath, size=stat.st_size, mtime=stat.st_mtime, sha256=digest)

        if existing is None:
            self.baseline.files[relpath] = new_record
            return Alert(
                kind="created", path=relpath, timestamp=ts,
                message=f"New file detected: {relpath}", new_record=new_record,
            )

        if existing.sha256 != new_record.sha256:
            self.baseline.files[relpath] = new_record
            return Alert(
                kind="modified", path=relpath, timestamp=ts,
                message=f"File modified: {relpath}", old_record=existing, new_record=new_record,
            )

        # Same hash as baseline — net no-op (e.g. edited then reverted
        # within the debounce window). Refresh the stored record (mtime
        # may differ) but emit no alert.
        self.baseline.files[relpath] = new_record
        return None

    # ---- lifecycle ------------------------------------------------------------

    def start(self) -> None:
        handler = _TouchHandler(self.root, self.exclude_dirs, self.touch)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.root), recursive=True)
        self._observer.start()

    def stop(self) -> None:
        self._stop_flag.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

    def run_forever(self, poll_interval: float = DEFAULT_POLL_INTERVAL) -> None:
        """Blocking: start the real watchdog observer and keep flushing
        debounced changes until stop() is called or Ctrl-C is pressed."""
        self.start()
        try:
            while not self._stop_flag.is_set():
                self.process_ready()
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
