from pathlib import Path

import pytest

from photos_to_slideshow.inputs import iter_image_files


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
