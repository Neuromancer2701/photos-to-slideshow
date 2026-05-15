"""Unit + HTTP integration tests for the reorder UI module."""

from pathlib import Path

import pytest
from PIL import Image

from photos_to_slideshow import ui
from tests._helpers import make_jpeg


def test_generate_thumbnails_writes_one_jpeg_per_photo(tmp_path: Path):
    photos = [make_jpeg(tmp_path / f"src{i}.jpg", "2024:01:01 00:00:00")
              for i in range(3)]
    out_dir = tmp_path / "thumbs"
    out_dir.mkdir()
    surviving = ui.generate_thumbnails(photos, out_dir)
    assert surviving == photos
    for i in range(3):
        thumb = out_dir / f"{i}.jpg"
        assert thumb.exists()
        with Image.open(thumb) as img:
            assert max(img.size) <= 240
            assert img.format == "JPEG"


def test_generate_thumbnails_preserves_index_alignment(tmp_path: Path):
    a = make_jpeg(tmp_path / "a.jpg")
    b = make_jpeg(tmp_path / "b.jpg")
    out = tmp_path / "thumbs"
    out.mkdir()
    surviving = ui.generate_thumbnails([a, b], out)
    assert surviving == [a, b]
    assert (out / "0.jpg").exists()
    assert (out / "1.jpg").exists()


def test_generate_thumbnails_skips_unreadable_image(tmp_path: Path, capsys):
    good = make_jpeg(tmp_path / "good.jpg")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"")  # not a valid image
    out = tmp_path / "thumbs"
    out.mkdir()
    surviving = ui.generate_thumbnails([good, bad], out)
    # Only the good one survives; index 0 maps to it, no 1.jpg exists.
    assert surviving == [good]
    assert (out / "0.jpg").exists()
    assert not (out / "1.jpg").exists()
    err = capsys.readouterr().err
    assert "bad.jpg" in err
