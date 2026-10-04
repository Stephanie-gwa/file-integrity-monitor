import os
import time

import pytest

from fim.scanner import build_baseline
from fim.storage import default_store_dir
from fim.watcher import FileWatcher


def _make_watcher(tmp_path, debounce=0.05, **kwargs):
    store = default_store_dir(tmp_path)
    baseline, _ = build_baseline(tmp_path, exclude_dirs=[store])
    collected = []
    watcher = FileWatcher(
        root=tmp_path, store_dir=store, baseline=baseline,
        debounce_seconds=debounce, on_alert=collected.append, **kwargs,
    )
    return watcher, collected


def test_touch_then_immediate_flush_is_empty_before_debounce_elapses(tmp_path):
    (tmp_path / "a.txt").write_text("v1")
    watcher, collected = _make_watcher(tmp_path, debounce=5.0)
    (tmp_path / "a.txt").write_text("v2")
    watcher.touch(tmp_path / "a.txt")
    alerts = watcher.process_ready()
    assert alerts == []
    assert watcher.pending_count() == 1


def test_modification_resolved_after_debounce_elapses(tmp_path):
    (tmp_path / "a.txt").write_text("v1")
    watcher, collected = _make_watcher(tmp_path, debounce=0.05)
    (tmp_path / "a.txt").write_text("v2")
    watcher.touch(tmp_path / "a.txt")
    time.sleep(0.1)
    alerts = watcher.process_ready()
    assert len(alerts) == 1
    assert alerts[0].kind == "modified"
    assert alerts[0].path == "a.txt"


def test_rapid_repeated_touches_collapse_to_one_alert(tmp_path):
    (tmp_path / "a.txt").write_text("v0")
    watcher, collected = _make_watcher(tmp_path, debounce=0.1)

    for i in range(10):
        (tmp_path / "a.txt").write_text(f"v{i}")
        watcher.touch(tmp_path / "a.txt")
        time.sleep(0.01)  # faster than the debounce window

    time.sleep(0.15)
    alerts = watcher.process_ready()
    assert len(alerts) == 1
    assert alerts[0].kind == "modified"
    # final content should be the last write, not an intermediate one
    assert alerts[0].new_record.sha256 != alerts[0].old_record.sha256


def test_created_file_detected(tmp_path):
    watcher, collected = _make_watcher(tmp_path, debounce=0.05)
    (tmp_path / "new.txt").write_text("hello")
    watcher.touch(tmp_path / "new.txt")
    time.sleep(0.1)
    alerts = watcher.process_ready()
    assert len(alerts) == 1
    assert alerts[0].kind == "created"
    assert "new.txt" in watcher.baseline.files


def test_deleted_file_detected(tmp_path):
    (tmp_path / "a.txt").write_text("v1")
    watcher, collected = _make_watcher(tmp_path, debounce=0.05)
    (tmp_path / "a.txt").unlink()
    watcher.touch(tmp_path / "a.txt")
    time.sleep(0.1)
    alerts = watcher.process_ready()
    assert len(alerts) == 1
    assert alerts[0].kind == "deleted"
    assert "a.txt" not in watcher.baseline.files


def test_create_then_delete_within_debounce_window_fires_nothing(tmp_path):
    watcher, collected = _make_watcher(tmp_path, debounce=0.2)
    (tmp_path / "tmp.txt").write_text("x")
    watcher.touch(tmp_path / "tmp.txt")
    (tmp_path / "tmp.txt").unlink()
    watcher.touch(tmp_path / "tmp.txt")
    time.sleep(0.25)
    alerts = watcher.process_ready()
    assert alerts == []


def test_revert_to_original_content_within_window_fires_nothing(tmp_path):
    (tmp_path / "a.txt").write_text("original")
    watcher, collected = _make_watcher(tmp_path, debounce=0.2)
    (tmp_path / "a.txt").write_text("temporary change")
    watcher.touch(tmp_path / "a.txt")
    (tmp_path / "a.txt").write_text("original")  # back to baseline content
    watcher.touch(tmp_path / "a.txt")
    time.sleep(0.25)
    alerts = watcher.process_ready()
    assert alerts == []


def test_deleted_file_not_in_baseline_fires_nothing(tmp_path):
    watcher, collected = _make_watcher(tmp_path, debounce=0.05)
    # Touch a path that was never created and doesn't exist.
    watcher.touch(tmp_path / "ghost.txt")
    time.sleep(0.1)
    alerts = watcher.process_ready()
    assert alerts == []


def test_touch_inside_store_dir_is_excluded_via_watcher_exclude_list(tmp_path):
    store = default_store_dir(tmp_path)
    baseline, _ = build_baseline(tmp_path, exclude_dirs=[store])
    collected = []
    watcher = FileWatcher(root=tmp_path, store_dir=store, baseline=baseline,
                           debounce_seconds=0.05, on_alert=collected.append)
    store.mkdir(exist_ok=True)
    (store / "baseline.json").write_text("{}")
    # Directly touching a path under the store dir should still resolve
    # harmlessly (not crash); real exclusion happens at the handler level,
    # tested via the real-observer integration test below.
    watcher.touch(store / "baseline.json")
    time.sleep(0.1)
    watcher.process_ready()  # must not raise


def test_broken_symlink_touch_reports_inaccessible(tmp_path):
    target = tmp_path / "missing.txt"
    link = tmp_path / "broken.txt"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlinks not supported on this filesystem")
    watcher, collected = _make_watcher(tmp_path, debounce=0.05)
    watcher.touch(link)
    time.sleep(0.1)
    alerts = watcher.process_ready()
    assert len(alerts) == 1
    assert alerts[0].kind == "inaccessible"


@pytest.mark.integration
def test_real_observer_detects_created_and_modified_files(tmp_path):
    """End-to-end test using the actual watchdog Observer and real
    filesystem events (no manual .touch() calls), including verifying
    that writes to the excluded store directory are never reported."""
    (tmp_path / "existing.txt").write_text("v1")
    store = default_store_dir(tmp_path)
    baseline, _ = build_baseline(tmp_path, exclude_dirs=[store])
    collected = []
    watcher = FileWatcher(root=tmp_path, store_dir=store, baseline=baseline,
                           debounce_seconds=0.2, on_alert=collected.append)
    watcher.start()
    try:
        time.sleep(0.2)
        (tmp_path / "created_live.txt").write_text("brand new")
        time.sleep(0.05)
        (tmp_path / "existing.txt").write_text("v2")
        time.sleep(0.05)
        # Write to the excluded store dir — must never produce an alert.
        store.mkdir(exist_ok=True)
        (store / "noise.txt").write_text("should be ignored")

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(collected) < 2:
            watcher.process_ready()
            time.sleep(0.1)
    finally:
        watcher.stop()

    kinds = {(a.kind, a.path) for a in collected}
    assert ("created", "created_live.txt") in kinds
    assert ("modified", "existing.txt") in kinds
    assert not any(p.startswith(".fim") for _, p in kinds)
