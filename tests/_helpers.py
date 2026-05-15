"""Test helpers shared across test modules."""

from pathlib import Path

from PIL import Image


def make_jpeg(path: Path, exif_datetime: str | None = None) -> Path:
    """Write a 10x10 red JPEG, optionally with an EXIF DateTimeOriginal."""
    img = Image.new("RGB", (10, 10), "red")
    if exif_datetime is None:
        img.save(path, "JPEG")
    else:
        exif = img.getexif()
        exif[0x9003] = exif_datetime  # DateTimeOriginal
        img.save(path, "JPEG", exif=exif)
    return path
