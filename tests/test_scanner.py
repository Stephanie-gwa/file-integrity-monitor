import os
from datetime import datetime

import pytest

from fim.scanner import build_baseline, diff_snapshots, is_excluded, scan_directory
from fim.storage import default_store_dir


def test_scan_directory_hashes_all_files(tmp_path):
    (tmp_path / "a.txt").write_text("one")
    (tmp_path / "b.txt").write_text("two")
    result = scan_directory(tmp_path)
    assert set(result.files) == {"a.txt", "b.txt"}
    assert result.inaccessible == []


def test_scan_directory_recurses_into_subdirectories(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("content")
    result = scan_directory(tmp_path)
    assert "sub/nested.txt" in result.files


def test_scan_directory_excludes_store_dir(tmp_path):
    store = default_store_dir(tmp_path)
    store.mkdir()
    (store / "baseline.json").write_text("{}")
    (tmp_path / "a.txt").write_text("content")

    result = scan_directory(tmp_path, exclude_dirs=[store])
    assert "a.txt" in result.files
    assert not any(p.startswith(".fim/") for p in result.files)
    assert not any(p.startswith(".fim/") for p in result.inaccessible)


def test_scan_directory_nonexistent_root_returns_empty(tmp_path):
    result = scan_directory(tmp_path / "does_not_exist")
    assert result.files == {}
    assert result.inaccessible == []


def test_scan_directory_records_broken_symlink_as_inaccessible(tmp_path):
    target = tmp_path / "missing.txt"
    link = tmp_path / "broken.txt"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlinks not supported on this filesystem")
    result = scan_directory(tmp_path)
    assert "broken.txt" in result.inaccessible
    assert "broken.txt" not in result.files


def test_is_excluded_true_for_path_inside_excluded_dir(tmp_path):
    excluded = tmp_path / ".fim"
    excluded.mkdir()
    inside = excluded / "baseline.json"
    assert is_excluded(inside, tmp_path, [excluded]) is True


def test_is_excluded_false_for_unrelated_path(tmp_path):
    excluded = tmp_path / ".fim"
    other = tmp_path / "a.txt"
    assert is_excluded(other, tmp_path, [excluded]) is False


def test_build_baseline_returns_baseline_and_scan_result(tmp_path):
    (tmp_path / "a.txt").write_text("content")
    baseline, result = build_baseline(tmp_path, exclude_dirs=[default_store_dir(tmp_path)])
    assert "a.txt" in baseline.files
    assert baseline.root == str(tmp_path)
    assert result.files == baseline.files


# ---- diff_snapshots -------------------------------------------------------

def _files(**kwargs):
    from fim.events import FileRecord
    return {k: FileRecord(path=k, size=1, mtime=1.0, sha256=v) for k, v in kwargs.items()}


def test_diff_detects_created_file():
    baseline = _files(a="hash_a")
    current = _files(a="hash_a", b="hash_b")
    alerts = diff_snapshots(baseline, current)
    assert len(alerts) == 1
    assert alerts[0].kind == "created"
    assert alerts[0].path == "b"


def test_diff_detects_deleted_file():
    baseline = _files(a="hash_a", b="hash_b")
    current = _files(a="hash_a")
    alerts = diff_snapshots(baseline, current)
    assert len(alerts) == 1
    assert alerts[0].kind == "deleted"
    assert alerts[0].path == "b"


def test_diff_detects_modified_file_by_hash_change():
    baseline = _files(a="hash_old")
    current = _files(a="hash_new")
    alerts = diff_snapshots(baseline, current)
    assert len(alerts) == 1
    assert alerts[0].kind == "modified"
    assert alerts[0].old_record.sha256 == "hash_old"
    assert alerts[0].new_record.sha256 == "hash_new"


def test_diff_no_alert_when_hash_unchanged():
    baseline = _files(a="same_hash")
    current = _files(a="same_hash")
    assert diff_snapshots(baseline, current) == []


def test_diff_handles_multiple_changes_at_once():
    baseline = _files(a="h1", b="h2", c="h3")
    current = _files(a="h1_changed", d="h4")  # a modified, b deleted, c deleted, d created
    alerts = diff_snapshots(baseline, current)
    kinds = {(a.kind, a.path) for a in alerts}
    assert kinds == {("modified", "a"), ("deleted", "b"), ("deleted", "c"), ("created", "d")}


def test_diff_empty_baseline_and_current_fires_nothing():
    assert diff_snapshots({}, {}) == []


def test_diff_uses_provided_timestamp():
    ts = datetime(2026, 5, 1, 12, 0, 0)
    baseline = _files()
    current = _files(a="h1")
    alerts = diff_snapshots(baseline, current, timestamp=ts)
    assert alerts[0].timestamp == ts
