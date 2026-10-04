from datetime import datetime

import pytest

from fim.events import Alert, FileRecord
from fim.storage import (
    Baseline,
    append_alert_log,
    baseline_exists,
    default_store_dir,
    load_baseline,
    read_alert_log,
    save_baseline,
)


def _rec(path="a.txt"):
    return FileRecord(path=path, size=5, mtime=123.0, sha256="deadbeef")


def test_default_store_dir_is_dotfim_under_root(tmp_path):
    store = default_store_dir(tmp_path)
    assert store == tmp_path / ".fim"


def test_save_and_load_baseline_roundtrip(tmp_path):
    baseline = Baseline(root=str(tmp_path), taken_at=datetime(2026, 1, 1), files={"a.txt": _rec()})
    store = tmp_path / ".fim"
    save_baseline(baseline, store)

    loaded = load_baseline(store)
    assert loaded.root == str(tmp_path)
    assert loaded.files["a.txt"].sha256 == "deadbeef"


def test_baseline_exists_false_before_save(tmp_path):
    store = tmp_path / ".fim"
    assert baseline_exists(store) is False


def test_baseline_exists_true_after_save(tmp_path):
    baseline = Baseline(root=str(tmp_path), taken_at=datetime(2026, 1, 1), files={})
    store = tmp_path / ".fim"
    save_baseline(baseline, store)
    assert baseline_exists(store) is True


def test_load_baseline_missing_raises_clear_error(tmp_path):
    store = tmp_path / ".fim"
    with pytest.raises(FileNotFoundError, match="fim init"):
        load_baseline(store)


def test_append_and_read_alert_log(tmp_path):
    store = tmp_path / ".fim"
    alert = Alert(kind="created", path="x.txt", timestamp=datetime(2026, 1, 1),
                  message="New file detected: x.txt", new_record=_rec("x.txt"))
    append_alert_log([alert], store)

    entries = read_alert_log(store)
    assert len(entries) == 1
    assert entries[0]["kind"] == "created"
    assert entries[0]["new_record"]["sha256"] == "deadbeef"


def test_append_alert_log_accumulates_across_calls(tmp_path):
    store = tmp_path / ".fim"
    a1 = Alert(kind="created", path="a.txt", timestamp=datetime(2026, 1, 1), message="m")
    a2 = Alert(kind="deleted", path="b.txt", timestamp=datetime(2026, 1, 2), message="m")
    append_alert_log([a1], store)
    append_alert_log([a2], store)
    entries = read_alert_log(store)
    assert len(entries) == 2


def test_read_alert_log_empty_when_no_file(tmp_path):
    store = tmp_path / ".fim"
    assert read_alert_log(store) == []


def test_save_baseline_creates_store_dir(tmp_path):
    store = tmp_path / "nested" / ".fim"
    baseline = Baseline(root=str(tmp_path), taken_at=datetime(2026, 1, 1), files={})
    save_baseline(baseline, store)
    assert store.exists()
    assert (store / "baseline.json").exists()
