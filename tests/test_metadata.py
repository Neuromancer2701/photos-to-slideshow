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


def _write_takeout_json(photo_path: Path, taken_timestamp: int,
                        suffix: str = ".supplemental-metadata.json") -> Path:
    """Write a Google Photos Takeout JSON sidecar next to the photo."""
    import json as _json
    sidecar = photo_path.with_name(photo_path.name + suffix)
    sidecar.write_text(_json.dumps({
        "title": photo_path.name,
        "photoTakenTime": {"timestamp": str(taken_timestamp), "formatted": "ignored"},
        "creationTime": {"timestamp": "0", "formatted": "ignored"},
    }))
    return sidecar


def test_extract_date_uses_takeout_json_when_no_exif(tmp_path: Path):
    p = _make_jpeg(tmp_path / "IMG_20150217_200401.jpg")  # no EXIF
    # 1424221441 = Feb 18, 2015 01:04:01 UTC = local time on this box
    _write_takeout_json(p, 1424221441)
    result = extract_date(p)
    assert result.source is DateSource.JSON
    assert result.timestamp == datetime.fromtimestamp(1424221441)


def test_extract_date_prefers_exif_over_takeout_json(tmp_path: Path):
    p = _make_jpeg(tmp_path / "x.jpg", "2024:06:15 14:30:00")
    _write_takeout_json(p, 1000000000)  # would be 2001 if used
    result = extract_date(p)
    assert result.source is DateSource.EXIF
    assert result.timestamp == datetime(2024, 6, 15, 14, 30, 0)


def test_extract_date_supports_legacy_dot_json_suffix(tmp_path: Path):
    p = _make_jpeg(tmp_path / "y.jpg")  # no EXIF
    _write_takeout_json(p, 1424221441, suffix=".json")
    result = extract_date(p)
    assert result.source is DateSource.JSON


def test_extract_date_falls_through_when_takeout_json_malformed(tmp_path: Path):
    p = _make_jpeg(tmp_path / "z.jpg")  # no EXIF
    sidecar = p.with_name(p.name + ".supplemental-metadata.json")
    sidecar.write_text("{ this is not json")
    result = extract_date(p)
    assert result.source is DateSource.MTIME


def test_extract_date_falls_through_when_takeout_json_zero_timestamp(tmp_path: Path):
    p = _make_jpeg(tmp_path / "w.jpg")  # no EXIF
    _write_takeout_json(p, 0)
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


def test_sort_by_date_appends_no_metadata_photos_at_end(tmp_path: Path):
    """Photos without EXIF or JSON go to the end regardless of mtime.

    mtime is often unreliable (downloaded photos take on their download time
    rather than capture time), so we don't let it interleave with real
    capture dates.
    """
    import os, time
    # Photo with real 2024 EXIF
    dated = _make_jpeg(tmp_path / "dated.jpg", "2024:06:15 14:30:00")
    # Photo with NO EXIF -- mtime set to 2020, which would sort BEFORE 'dated'
    # if mtime were treated as a real capture date. Expected: 'dated' first.
    undated = _make_jpeg(tmp_path / "undated.jpg")
    early = time.mktime(datetime(2020, 1, 1).timetuple())
    os.utime(undated, (early, early))
    sorted_paths, fallback_count = sort_by_date([undated, dated])
    assert sorted_paths == [dated, undated]
    assert fallback_count == 1


def test_sort_by_date_orders_undated_group_by_mtime(tmp_path: Path):
    """Within the undated tail, photos sort by mtime (earlier first)."""
    import os
    a = _make_jpeg(tmp_path / "a.jpg")  # no EXIF
    b = _make_jpeg(tmp_path / "b.jpg")  # no EXIF
    os.utime(a, (2000000.0, 2000000.0))  # later
    os.utime(b, (1000000.0, 1000000.0))  # earlier
    sorted_paths, _ = sort_by_date([a, b])
    assert sorted_paths == [b, a]


def test_sort_by_date_takeout_json_counts_as_real_metadata(tmp_path: Path):
    """JSON sidecar counts as real metadata, not a fallback."""
    import os
    dated_exif = _make_jpeg(tmp_path / "exif.jpg", "2024:06:15 14:30:00")
    dated_json = _make_jpeg(tmp_path / "json.jpg")  # no EXIF
    _write_takeout_json(dated_json, 1577836800)  # 2020-01-01 UTC
    undated = _make_jpeg(tmp_path / "undated.jpg")
    os.utime(undated, (0, 0))
    sorted_paths, fallback_count = sort_by_date([undated, dated_exif, dated_json])
    # JSON (2020) < EXIF (2024) < undated (end)
    assert sorted_paths == [dated_json, dated_exif, undated]
    assert fallback_count == 1
