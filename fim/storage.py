"""Baseline and alert-log persistence.

The monitor's own bookkeeping — its baseline snapshot and its alert
log — lives in a "store directory". By default that's a `.fim/`
subdirectory of the monitored root, and it is *always* excluded from
scanning/watching (see `scanner.default_excludes` /
`watcher.FIMEventHandler`) specifically so the tool never reports its
own baseline/log writes as changes to the directory it's watching.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Union

from .events import Alert, FileRecord

BASELINE_FILENAME = "baseline.json"
ALERT_LOG_FILENAME = "alerts.log.jsonl"
DEFAULT_STORE_DIRNAME = ".fim"


def default_store_dir(root: Union[str, Path]) -> Path:
    """Where this root's baseline/log live if the caller doesn't say otherwise."""
    return Path(root) / DEFAULT_STORE_DIRNAME


class Baseline:
    """An in-memory baseline: monitored root + the FileRecord for every
    file that was present when it was taken."""

    def __init__(self, root: str, taken_at: datetime, files: Dict[str, FileRecord]):
        self.root = root
        self.taken_at = taken_at
        self.files = files  # relpath -> FileRecord

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "taken_at": self.taken_at.isoformat(),
            "files": {path: rec.to_dict() for path, rec in self.files.items()},
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Baseline":
        return Baseline(
            root=d["root"],
            taken_at=datetime.fromisoformat(d["taken_at"]),
            files={path: FileRecord.from_dict(rec) for path, rec in d["files"].items()},
        )


def save_baseline(baseline: Baseline, store_dir: Union[str, Path]) -> Path:
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / BASELINE_FILENAME
    path.write_text(json.dumps(baseline.to_dict(), indent=2, sort_keys=False), encoding="utf-8")
    return path


def load_baseline(store_dir: Union[str, Path]) -> Baseline:
    path = Path(store_dir) / BASELINE_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"No baseline found at {path}. Run `fim init` first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return Baseline.from_dict(data)


def baseline_exists(store_dir: Union[str, Path]) -> bool:
    return (Path(store_dir) / BASELINE_FILENAME).exists()


def append_alert_log(alerts: List[Alert], store_dir: Union[str, Path]) -> Path:
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)
    path = store_dir / ALERT_LOG_FILENAME
    with open(path, "a", encoding="utf-8") as f:
        for alert in alerts:
            f.write(json.dumps(alert.to_dict()) + "\n")
    return path


def read_alert_log(store_dir: Union[str, Path]) -> List[Dict[str, Any]]:
    path = Path(store_dir) / ALERT_LOG_FILENAME
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries
