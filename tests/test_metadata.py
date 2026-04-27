from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from photos_to_slideshow.metadata import (
    DateSource,
    extract_date,
)


def _make_jpeg(path: Path, exif_datetime: str | None = None) -> Path:
    img = Image.new("RGB", (10, 10), "red")
    if exif_datetime is None:
        img.save(path, "JPEG")
    else:
        exif = img.getexif()
        # 0x9003 = DateTimeOriginal
        exif[0x9003] = exif_datetime
        img.save(path, "JPEG", exif=exif)
    return path


def test_extract_date_from_exif(tmp_path: Path):
    p = _make_jpeg(tmp_path / "a.jpg", "2024:06:15 14:30:00")
    result = extract_date(p)
    assert result.source is DateSource.EXIF
    assert result.timestamp == datetime(2024, 6, 15, 14, 30, 0)


def test_extract_date_falls_back_to_mtime(tmp_path: Path):
    p = _make_jpeg(tmp_path / "b.jpg")  # no EXIF
    import os, time
    target = time.mktime(datetime(2023, 1, 2, 3, 4, 5).timetuple())
    os.utime(p, (target, target))
    result = extract_date(p)
    assert result.source is DateSource.MTIME
    assert result.timestamp == datetime(2023, 1, 2, 3, 4, 5)


def test_extract_date_handles_malformed_exif(tmp_path: Path):
    # Garbage in DateTimeOriginal -> fall back to mtime, not crash
    p = _make_jpeg(tmp_path / "c.jpg", "not a date")
    result = extract_date(p)
    assert result.source is DateSource.MTIME


from photos_to_slideshow.metadata import sort_by_date


def test_sort_by_date_orders_chronologically(tmp_path: Path):
    a = _make_jpeg(tmp_path / "a.jpg", "2024:06:15 14:30:00")
    b = _make_jpeg(tmp_path / "b.jpg", "2024:01:01 09:00:00")
    c = _make_jpeg(tmp_path / "c.jpg", "2024:12:31 23:59:00")
    sorted_paths, fallback_count = sort_by_date([a, b, c])
    assert sorted_paths == [b, a, c]
    assert fallback_count == 0


def test_sort_by_date_counts_mtime_fallbacks(tmp_path: Path):
    a = _make_jpeg(tmp_path / "a.jpg", "2024:06:15 14:30:00")
    b = _make_jpeg(tmp_path / "b.jpg")  # no EXIF -> mtime
    sorted_paths, fallback_count = sort_by_date([a, b])
    assert fallback_count == 1


def test_sort_by_date_tiebreaks_by_filename(tmp_path: Path):
    # Same timestamp, ordering must be stable on filename
    a = _make_jpeg(tmp_path / "z.jpg", "2024:06:15 14:30:00")
    b = _make_jpeg(tmp_path / "a.jpg", "2024:06:15 14:30:00")
    sorted_paths, _ = sort_by_date([a, b])
    assert sorted_paths == [b, a]
