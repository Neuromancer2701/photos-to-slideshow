"""EXIF date extraction and chronological sort."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Pillow's EXIF tag for DateTimeOriginal
_EXIF_DATETIME_ORIGINAL = 0x9003


class DateSource(Enum):
    EXIF = "exif"
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


def extract_date(path: Path) -> DatedPhoto:
    """Return the photo's best-known date with its source.

    Tries EXIF DateTimeOriginal first; falls back to file mtime.
    """
    ts = _read_exif_datetime(path)
    if ts is not None:
        return DatedPhoto(path=path, timestamp=ts, source=DateSource.EXIF)
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return DatedPhoto(path=path, timestamp=mtime, source=DateSource.MTIME)
