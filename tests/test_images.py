from pathlib import Path

import pytest
from PIL import Image

from photos_to_slideshow.images import decode_image


def test_decode_jpeg_returns_rgb(tmp_path: Path):
    p = tmp_path / "a.jpg"
    Image.new("RGB", (50, 30), "blue").save(p, "JPEG")
    img = decode_image(p)
    assert img.mode == "RGB"
    assert img.size == (50, 30)


def test_decode_applies_exif_orientation(tmp_path: Path):
    """An image flagged as rotated 90° should come back already rotated."""
    p = tmp_path / "rot.jpg"
    src = Image.new("RGB", (40, 20), "red")
    exif = src.getexif()
    exif[0x0112] = 6  # Orientation: rotate 270 CW (i.e., 90 CCW)
    src.save(p, "JPEG", exif=exif)
    img = decode_image(p)
    # After auto-rotate, dimensions should be transposed
    assert img.size == (20, 40)


def test_decode_unreadable_raises(tmp_path: Path):
    p = tmp_path / "bad.jpg"
    p.write_bytes(b"not actually an image")
    with pytest.raises(Exception):
        decode_image(p)
