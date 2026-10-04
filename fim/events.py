"""Plain data structures shared across the scanner, watcher, and CLI."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class FileRecord:
    """Everything the baseline remembers about one file."""

    path: str  # path relative to the monitored root, forward-slash normalized
    size: int
    mtime: float
    sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "size": self.size, "mtime": self.mtime, "sha256": self.sha256}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "FileRecord":
        return FileRecord(path=d["path"], size=d["size"], mtime=d["mtime"], sha256=d["sha256"])


@dataclass
class Alert:
    """One reported change, ready to print, log, or compare in tests."""

    kind: str  # "created" | "modified" | "deleted" | "inaccessible"
    path: str
    timestamp: datetime
    message: str
    old_record: Optional[FileRecord] = None
    new_record: Optional[FileRecord] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
            "old_record": self.old_record.to_dict() if self.old_record else None,
            "new_record": self.new_record.to_dict() if self.new_record else None,
            "detail": self.detail,
        }
