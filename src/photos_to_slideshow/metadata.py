"""EXIF date extraction and chronological sort."""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# Pillow's EXIF tag for DateTimeOriginal
_EXIF_DATETIME_ORIGINAL = 0x9003

# Google Photos Takeout caps generated sidecar filenames at 51 characters
# and truncates the ".supplemental-metadata" middle (or, if even that doesn't
# fit, the photo name itself) to fit the budget. Examples observed in real
# exports:
#   foo.jpg                       -> foo.jpg.supplemental-metadata.json   (37, fits)
#   PXL_..._152013744~2.jpg       -> ....jpg.supplemental-meta.json       (51, mid trunc)
#   PXL_..._132759207.PORTRAIT~2  -> ....jpg.suppleme.json                (51, mid trunc, hyphen cut)
#   original_<uuid>_PXL_...~2.jpg -> original_<uuid>_.json                (51, photo trunc)
_TAKEOUT_NAME_BUDGET = 51
_TAKEOUT_MIDDLE_FULL = ".supplemental-metadata"
_TAKEOUT_JSON_EXT = ".json"


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


def _predicted_sidecar_names(photo_name: str) -> list[str]:
    """Predict the Takeout sidecar filename(s) for a photo, best match first.

    Applies Google's ~51-char filename budget: try the canonical full suffix,
    then progressively shorter truncations of ".supplemental-metadata", then
    a bare ".json", and finally a photo-name-truncated form when the photo
    name itself is too long to fit anything else.
    """
    names: list[str] = []
    seen: set[str] = set()

    def push(name: str) -> None:
        if name not in seen:
            seen.add(name)
            names.append(name)

    canonical = photo_name + _TAKEOUT_MIDDLE_FULL + _TAKEOUT_JSON_EXT
    push(canonical)

    available = _TAKEOUT_NAME_BUDGET - len(photo_name) - len(_TAKEOUT_JSON_EXT)
    if available > 0:
        # Truncate the middle to `available` chars, longest first so the
        # closest-to-canonical form wins ties.
        max_middle = min(available, len(_TAKEOUT_MIDDLE_FULL))
        for n in range(max_middle, 0, -1):
            push(photo_name + _TAKEOUT_MIDDLE_FULL[:n] + _TAKEOUT_JSON_EXT)
    if available >= 0:
        push(photo_name + _TAKEOUT_JSON_EXT)  # no middle: legacy or zero-budget
    # Photo name longer than the budget: Google truncates the photo name.
    photo_trunc_len = _TAKEOUT_NAME_BUDGET - len(_TAKEOUT_JSON_EXT)
    if len(photo_name) > photo_trunc_len:
        push(photo_name[:photo_trunc_len] + _TAKEOUT_JSON_EXT)

    return names


def _iter_takeout_sidecars(path: Path):
    """Yield existing sidecars for a photo in priority order."""
    for name in _predicted_sidecar_names(path.name):
        sidecar = path.with_name(name)
        if sidecar.exists():
            yield sidecar


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
