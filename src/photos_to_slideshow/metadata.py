"""EXIF date extraction and chronological sort."""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Pillow's EXIF tag for DateTimeOriginal
_EXIF_DATETIME_ORIGINAL = 0x9003

# Suffixes Google Photos Takeout uses for the JSON sidecar that lives next
# to a photo. Tried in order; the newer "supplemental-metadata" form has been
# the standard since late 2024 but the older bare ".json" form still appears
# in old exports.
_TAKEOUT_SIDECAR_SUFFIXES = (".supplemental-metadata.json", ".json")


class DateSource(Enum):
    EXIF = "exif"
    JSON = "json"      # Google Photos Takeout sidecar (.supplemental-metadata.json)
    MTIME = "mtime"


@dataclass(frozen=True)
class DatedPhoto:
    path: Path
    timestamp: datetime
    source: DateSource


def _read_exif_datetime(path: Path) -> datetime | None:
    try:
        with Image.open(path) as img:
            exif = img.getexif()
    except (UnidentifiedImageError, OSError):
        return None
    raw = exif.get(_EXIF_DATETIME_ORIGINAL)
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def _read_takeout_json_datetime(path: Path) -> datetime | None:
    """Read photoTakenTime from a Google Photos Takeout JSON sidecar.

    The sidecar lives alongside the photo: e.g. ``foo.jpg`` ->
    ``foo.jpg.supplemental-metadata.json``. The relevant field is::

        "photoTakenTime": {"timestamp": "1424221441", ...}

    Returns None if no sidecar is found, the JSON is unreadable, or the
    timestamp is missing/zero.
    """
    for suffix in _TAKEOUT_SIDECAR_SUFFIXES:
        sidecar = path.with_name(path.name + suffix)
        if not sidecar.exists():
            continue
        try:
            data = json.loads(sidecar.read_text())
            ts = data.get("photoTakenTime", {}).get("timestamp")
            if ts is None:
                continue
            seconds = int(ts)
            if seconds <= 0:
                continue
            # fromtimestamp without tz arg returns local naive time, matching
            # how EXIF DateTimeOriginal is parsed (also naive). Both sources
            # therefore sort consistently.
            return datetime.fromtimestamp(seconds)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return None


def extract_date(path: Path) -> DatedPhoto:
    """Return the photo's best-known date with its source.

    Order of preference: EXIF DateTimeOriginal -> Google Takeout JSON
    sidecar (photoTakenTime) -> file mtime.
    """
    ts = _read_exif_datetime(path)
    if ts is not None:
        return DatedPhoto(path=path, timestamp=ts, source=DateSource.EXIF)
    ts = _read_takeout_json_datetime(path)
    if ts is not None:
        return DatedPhoto(path=path, timestamp=ts, source=DateSource.JSON)
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return DatedPhoto(path=path, timestamp=mtime, source=DateSource.MTIME)


def sort_by_date(paths: list[Path]) -> tuple[list[Path], int]:
    """Return (paths sorted by best-known date asc, count of mtime fallbacks).

    Ties broken by filename for deterministic output.
    """
    dated = [extract_date(p) for p in paths]
    dated.sort(key=lambda d: (d.timestamp, d.path.name))
    fallback = sum(1 for d in dated if d.source is DateSource.MTIME)
    return [d.path for d in dated], fallback
