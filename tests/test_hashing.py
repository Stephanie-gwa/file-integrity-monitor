import hashlib
import os

import pytest

from fim.hashing import FileInaccessibleError, hash_file, try_hash_file


def test_hash_matches_hashlib_reference(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert hash_file(f) == expected


def test_hash_is_stable_across_calls(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("some content")
    assert hash_file(f) == hash_file(f)


def test_hash_differs_for_different_content(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("one")
    f2.write_text("two")
    assert hash_file(f1) != hash_file(f2)


def test_hash_handles_large_file_in_chunks(tmp_path):
    f = tmp_path / "big.bin"
    data = os.urandom(200_000)  # larger than CHUNK_SIZE
    f.write_bytes(data)
    assert hash_file(f) == hashlib.sha256(data).hexdigest()


def test_hash_missing_file_raises_inaccessible(tmp_path):
    missing = tmp_path / "does_not_exist.txt"
    with pytest.raises(FileInaccessibleError):
        hash_file(missing)


def test_hash_directory_raises_inaccessible(tmp_path):
    d = tmp_path / "subdir"
    d.mkdir()
    with pytest.raises(FileInaccessibleError):
        hash_file(d)


def test_hash_broken_symlink_raises_inaccessible(tmp_path):
    target = tmp_path / "nonexistent_target.txt"
    link = tmp_path / "broken_link.txt"
    try:
        os.symlink(target, link)
    except OSError:
        pytest.skip("symlinks not supported on this filesystem")
    with pytest.raises(FileInaccessibleError):
        hash_file(link)


def test_try_hash_file_returns_none_instead_of_raising(tmp_path):
    missing = tmp_path / "nope.txt"
    assert try_hash_file(missing) is None


def test_try_hash_file_returns_digest_for_real_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert try_hash_file(f) == hash_file(f)


def test_empty_file_hashes_to_known_sha256_of_empty_string(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    assert hash_file(f) == hashlib.sha256(b"").hexdigest()
