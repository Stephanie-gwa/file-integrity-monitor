"""Chunked SHA-256 hashing, with the error handling that the rest of
the project leans on: a file can disappear, become unreadable, or turn
out to be something other than a regular file (a socket, a broken
symlink, a directory tool just renamed into) between the moment we
decide to hash it and the moment we actually open it. None of that
should ever crash a scan or a watch session.
"""

from pathlib import Path
from typing import Optional

CHUNK_SIZE = 65536


class FileInaccessibleError(Exception):
    """Raised when a file can't be hashed — missing, unreadable, or not
    a regular file. Always carries a short, specific reason."""

    def __init__(self, path: str, reason: str):
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def hash_file(path: "Path | str") -> str:
    """Return the hex SHA-256 digest of a file's contents.

    Raises FileInaccessibleError (never a raw OSError) if the file can't
    be read — missing, a permissions problem, or not a regular file.
    """
    import hashlib

    p = Path(path)

    try:
        if p.is_symlink() and not p.exists():
            raise FileInaccessibleError(str(path), "broken symlink")
        if not p.is_file():
            raise FileInaccessibleError(str(path), "not a regular file")
    except OSError as exc:
        raise FileInaccessibleError(str(path), f"could not stat file: {exc}") from None

    digest = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise FileInaccessibleError(str(path), "file disappeared before it could be read") from None
    except PermissionError as exc:
        raise FileInaccessibleError(str(path), "permission denied") from None
    except OSError as exc:
        raise FileInaccessibleError(str(path), f"read error: {exc}") from None

    return digest.hexdigest()


def try_hash_file(path: "Path | str") -> Optional[str]:
    """Convenience wrapper: returns the digest, or None if the file is
    inaccessible for any of the reasons hash_file() handles."""
    try:
        return hash_file(path)
    except FileInaccessibleError:
        return None
