"""EXIF date extraction and chronological sort."""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Pillow's EXIF tag for DateTimeOriginal
_EXIF_DATETIME_ORIGINAL = 0x9003

# Suffix on the canonical Google Photos Takeout sidecar. Google truncates this
# to keep total filenames under ~51 chars, so we also glob for any
# ".supplemental-*.json" to catch variants like ".supplemental-meta.json".
# Very old exports use a bare ".json" suffix; we keep that as a final fallback.
_TAKEOUT_CANONICAL_SUFFIX = ".supplemental-metadata.json"
_TAKEOUT_TRUNCATED_GLOB = ".supplemental-*.json"
_TAKEOUT_LEGACY_SUFFIX = ".json"


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


def _iter_takeout_sidecars(path: Path):
    """Yield possible Takeout JSON sidecars for a photo, best match first.

    Order: canonical full suffix -> truncated supplemental-* forms (least
    truncated first) -> legacy bare .json.
    """
    canonical = path.with_name(path.name + _TAKEOUT_CANONICAL_SUFFIX)
    if canonical.exists():
        yield canonical
    # Truncated suffixes like ".supplemental-meta.json" or ".supplemental-m.json".
    # Sort by descending suffix length so a less-truncated form wins.
    truncated = sorted(
        (s for s in path.parent.glob(path.name + _TAKEOUT_TRUNCATED_GLOB)
         if s != canonical),
        key=lambda p: -len(p.name),
    )
    yield from truncated
    legacy = path.with_name(path.name + _TAKEOUT_LEGACY_SUFFIX)
    if legacy.exists() and legacy != canonical:
        yield legacy


def _read_takeout_json_datetime(path: Path) -> datetime | None:
    """Read photoTakenTime from a Google Photos Takeout JSON sidecar.

    The sidecar lives alongside the photo: e.g. ``foo.jpg`` ->
    ``foo.jpg.supplemental-metadata.json``. Google truncates that suffix
    to fit a ~51-character total filename budget (so ``foo.jpg`` may have
    ``foo.jpg.supplemental-meta.json`` instead). The relevant field is::

        "photoTakenTime": {"timestamp": "1424221441", ...}

    Returns None if no sidecar is found, the JSON is unreadable, or the
    timestamp is missing/zero.
    """
    for sidecar in _iter_takeout_sidecars(path):
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
    """Return (paths in slideshow order, count of photos with no real date).

    Photos with EXIF or Takeout JSON dates sort chronologically. Photos
    with only mtime are appended at the end (sorted among themselves by
    mtime). Rationale: mtime is unreliable -- downloaded photos pick up
    their download time rather than capture time -- so letting it
    interleave with real capture dates would misplace those photos in
    the timeline.

    Ties broken by filename for deterministic output.
    """
    dated = [extract_date(p) for p in paths]
    # Sort key: (group, timestamp, name). group=0 for real dates (EXIF/JSON),
    # group=1 for mtime fallbacks, so mtime photos always end up after.
    dated.sort(key=lambda d: (
        1 if d.source is DateSource.MTIME else 0,
        d.timestamp,
        d.path.name,
    ))
    fallback = sum(1 for d in dated if d.source is DateSource.MTIME)
    return [d.path for d in dated], fallback
