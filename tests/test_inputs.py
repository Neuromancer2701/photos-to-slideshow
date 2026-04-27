import zipfile
from pathlib import Path

import pytest

from photos_to_slideshow.inputs import iter_image_files, resolve
from photos_to_slideshow.errors import UsageError


def test_iter_image_files_filters_supported_extensions(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    (tmp_path / "b.JPEG").write_bytes(b"x")
    (tmp_path / "c.heic").write_bytes(b"x")
    (tmp_path / "d.png").write_bytes(b"x")
    (tmp_path / "e.txt").write_bytes(b"x")
    (tmp_path / ".DS_Store").write_bytes(b"x")
    found = sorted(iter_image_files(tmp_path))
    assert [p.name for p in found] == ["a.jpg", "b.JPEG", "c.heic", "d.png"]


def test_iter_image_files_recurses_into_subdirs(tmp_path: Path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.jpg").write_bytes(b"x")
    (tmp_path / "top.jpg").write_bytes(b"x")
    found = sorted(p.name for p in iter_image_files(tmp_path))
    assert found == ["deep.jpg", "top.jpg"]


def test_resolve_returns_directory_unchanged(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    resolved = resolve(tmp_path)
    assert resolved.root == tmp_path
    assert resolved.temp_dir is None  # we did not extract anything


def test_resolve_extracts_zip_to_temp(tmp_path: Path):
    zip_path = tmp_path / "photos.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("nested/a.jpg", b"x")
        zf.writestr("b.png", b"x")
    resolved = resolve(zip_path)
    assert resolved.temp_dir is not None
    assert resolved.temp_dir.exists()
    assert resolved.root == resolved.temp_dir
    found = sorted(p.name for p in resolved.root.rglob("*") if p.is_file())
    assert found == ["a.jpg", "b.png"]
    # Cleanup leaves no trace
    resolved.cleanup()
    assert not resolved.temp_dir.exists()


def test_resolve_missing_path_raises(tmp_path: Path):
    with pytest.raises(UsageError):
        resolve(tmp_path / "nope")


def test_resolve_unsupported_file_raises(tmp_path: Path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"x")
    with pytest.raises(UsageError):
        resolve(bad)
