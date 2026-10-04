import json

from fim.cli import main


def test_init_creates_baseline(tmp_path, capsys):
    target = tmp_path / "watched"
    target.mkdir()
    (target / "a.txt").write_text("hello")

    rc = main(["init", "--dir", str(target)])
    assert rc == 0
    assert (target / ".fim" / "baseline.json").exists()
    out = capsys.readouterr().out
    assert "1 file(s) recorded" in out


def test_check_without_baseline_fails_cleanly(tmp_path, capsys):
    target = tmp_path / "watched"
    target.mkdir()
    rc = main(["check", "--dir", str(target)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "fim init" in err


def test_check_detects_created_modified_deleted(tmp_path, capsys):
    target = tmp_path / "watched"
    target.mkdir()
    (target / "a.txt").write_text("v1")
    (target / "b.txt").write_text("v1")
    main(["init", "--dir", str(target)])
    capsys.readouterr()

    (target / "a.txt").write_text("v2")       # modified
    (target / "b.txt").unlink()               # deleted
    (target / "c.txt").write_text("new")      # created

    rc = main(["check", "--dir", str(target)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "MODIFIED" in out and "a.txt" in out
    assert "DELETED" in out and "b.txt" in out
    assert "CREATED" in out and "c.txt" in out


def test_check_with_update_flag_refreshes_baseline(tmp_path, capsys):
    target = tmp_path / "watched"
    target.mkdir()
    (target / "a.txt").write_text("v1")
    main(["init", "--dir", str(target)])
    capsys.readouterr()

    (target / "a.txt").write_text("v2")
    main(["check", "--dir", str(target), "--update"])
    capsys.readouterr()

    rc = main(["check", "--dir", str(target)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "No changes detected" in out


def test_check_writes_json_report(tmp_path, capsys):
    target = tmp_path / "watched"
    target.mkdir()
    (target / "a.txt").write_text("v1")
    main(["init", "--dir", str(target)])
    capsys.readouterr()

    (target / "a.txt").write_text("v2")
    json_path = tmp_path / "alerts.json"
    main(["check", "--dir", str(target), "--json", str(json_path)])
    capsys.readouterr()

    data = json.loads(json_path.read_text())
    assert len(data) == 1
    assert data[0]["kind"] == "modified"


def test_log_empty_before_any_check(tmp_path, capsys):
    target = tmp_path / "watched"
    target.mkdir()
    (target / "a.txt").write_text("v1")
    main(["init", "--dir", str(target)])
    capsys.readouterr()

    rc = main(["log", "--dir", str(target)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "No alerts logged yet" in out


def test_log_shows_entries_after_check(tmp_path, capsys):
    target = tmp_path / "watched"
    target.mkdir()
    (target / "a.txt").write_text("v1")
    main(["init", "--dir", str(target)])
    capsys.readouterr()
    (target / "a.txt").write_text("v2")
    main(["check", "--dir", str(target)])
    capsys.readouterr()

    rc = main(["log", "--dir", str(target)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "MODIFIED" in out


def test_demo_runs_end_to_end_and_shows_all_alert_kinds(tmp_path, capsys):
    demo_dir = tmp_path / "demo"
    rc = main(["demo", "--dir", str(demo_dir)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CREATED" in out
    assert "MODIFIED" in out
    assert "DELETED" in out


def test_custom_store_location_is_respected(tmp_path, capsys):
    target = tmp_path / "watched"
    target.mkdir()
    (target / "a.txt").write_text("v1")
    store = tmp_path / "elsewhere"

    rc = main(["init", "--dir", str(target), "--store", str(store)])
    assert rc == 0
    assert (store / "baseline.json").exists()
    assert not (target / ".fim").exists()


def test_no_command_prints_help(capsys):
    rc = main([])
    assert rc == 1
