from fim.sample_data import apply_demo_changes, create_sample_folder
from fim.scanner import build_baseline, diff_snapshots, scan_directory
from fim.storage import default_store_dir


def test_create_sample_folder_populates_expected_files(tmp_path):
    folder = tmp_path / "demo"
    create_sample_folder(folder)
    assert (folder / "readme.txt").exists()
    assert (folder / "config.ini").exists()
    assert (folder / "notes.md").exists()
    assert (folder / "subdir" / "nested.txt").exists()


def test_create_sample_folder_is_idempotent(tmp_path):
    folder = tmp_path / "demo"
    create_sample_folder(folder)
    create_sample_folder(folder)  # should not raise, should not duplicate oddly
    assert (folder / "readme.txt").exists()


def test_apply_demo_changes_produces_all_three_alert_kinds(tmp_path):
    folder = tmp_path / "demo"
    create_sample_folder(folder)
    store = default_store_dir(folder)
    baseline, _ = build_baseline(folder, exclude_dirs=[store])

    apply_demo_changes(folder)

    current = scan_directory(folder, exclude_dirs=[store])
    alerts = diff_snapshots(baseline.files, current.files)
    kinds = {a.kind for a in alerts}
    assert kinds == {"created", "modified", "deleted"}


def test_broken_symlink_in_sample_folder_is_inaccessible(tmp_path):
    folder = tmp_path / "demo"
    create_sample_folder(folder)
    store = default_store_dir(folder)
    result = scan_directory(folder, exclude_dirs=[store])
    # Either the symlink was created (most POSIX systems) and reported as
    # inaccessible, or symlinks aren't supported here and it's simply absent.
    if (folder / "broken_link.txt").is_symlink():
        assert "broken_link.txt" in result.inaccessible
