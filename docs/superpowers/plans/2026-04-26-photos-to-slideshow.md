# photos-to-slideshow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reusable Ubuntu CLI tool `photos-to-slideshow` that turns a folder/zip of photos plus an MP3 into an MP4 slideshow video, sorted by EXIF date, with blur-fill backgrounds and crossfades.

**Architecture:** Python 3 package using `Pillow` + `pillow-heif` for image decoding/compositing, `mutagen` for MP3 duration, and a system `ffmpeg` invocation for video encoding. Pure-logic modules (timing math, EXIF sort) are unit-tested fast; one slow end-to-end test covers the ffmpeg integration.

**Tech Stack:** Python 3.10+, Pillow, pillow-heif, mutagen, tqdm, pytest, ffmpeg (system binary).

**Spec:** `docs/superpowers/specs/2026-04-26-photos-to-slideshow-design.md`

---

## File Structure

```
photos_to_slideshow/
├── pyproject.toml
├── README.md
├── .gitignore
├── docs/superpowers/
│   ├── specs/2026-04-26-photos-to-slideshow-design.md
│   └── plans/2026-04-26-photos-to-slideshow.md
├── src/photos_to_slideshow/
│   ├── __init__.py
│   ├── cli.py          # argparse + main() orchestration; entry point
│   ├── errors.py       # typed exceptions for clean exit-code mapping
│   ├── inputs.py       # zip/dir resolution; supported-file filtering
│   ├── metadata.py     # EXIF date extraction; sort_by_date
│   ├── images.py       # decode (HEIC-aware); blur-fill render_frame
│   ├── audio.py        # MP3 duration; compute_timing math
│   └── render.py       # ffmpeg command construction + invocation
└── tests/
    ├── conftest.py
    ├── fixtures/        # tiny test images + 1s mp3
    ├── test_audio.py
    ├── test_metadata.py
    ├── test_inputs.py
    ├── test_images.py
    └── test_e2e.py
```

Each module has one responsibility; pure-logic functions are isolated from I/O so most tests run without ffmpeg or large files.

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/photos_to_slideshow/__init__.py`, `tests/__init__.py`, `tests/conftest.py`

- [ ] **Step 1: Verify ffmpeg is installed**

Run: `ffmpeg -version`
Expected: prints version. If not, run `sudo apt install -y ffmpeg`.

- [ ] **Step 2: Initialize git**

Run from `/home/count_zero/Repos/photos_to_slideshow`:
```bash
git init -b main
```

- [ ] **Step 3: Create `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
*.egg-info/
.venv/
.pytest_cache/
build/
dist/
*.mp4
tests/fixtures/output_*
```

- [ ] **Step 4: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "photos-to-slideshow"
version = "0.1.0"
description = "Turn a folder of photos plus an MP3 into an MP4 slideshow."
requires-python = ">=3.10"
dependencies = [
    "Pillow>=10.0",
    "pillow-heif>=0.16",
    "mutagen>=1.47",
    "tqdm>=4.66",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
photos-to-slideshow = "photos_to_slideshow.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
markers = ["slow: tests that need ffmpeg and take >1s"]
testpaths = ["tests"]
```

- [ ] **Step 5: Create empty package files**

`src/photos_to_slideshow/__init__.py`:
```python
__version__ = "0.1.0"
```

`tests/__init__.py`: (empty file)

`tests/conftest.py`:
```python
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
```

- [ ] **Step 6: Create venv and install in editable mode**

```bash
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev]"
```

- [ ] **Step 7: Verify install and pytest discovery**

Run: `.venv/bin/pytest --collect-only`
Expected: `0 tests collected` (no errors).

- [ ] **Step 8: Commit**

```bash
git add .gitignore pyproject.toml src/ tests/ docs/
git commit -m "chore: project scaffold with pyproject and test harness"
```

---

## Task 2: Typed Exceptions (`errors.py`)

**Files:**
- Create: `src/photos_to_slideshow/errors.py`

- [ ] **Step 1: Write the module**

```python
"""Typed exceptions used to map failure modes to CLI exit codes.

Exit code mapping (handled in cli.main):
  0   success
  1   UsageError (bad args, unreadable input file, etc.)
  2   NoUsablePhotosError
  3   FFmpegError
  130 KeyboardInterrupt (handled in cli.main, no exception class needed)
"""


class SlideshowError(Exception):
    """Base class for all tool errors."""


class UsageError(SlideshowError):
    """Bad CLI usage or unreadable input file."""


class NoUsablePhotosError(SlideshowError):
    """Input contained no decodable, supported images."""


class FFmpegError(SlideshowError):
    """ffmpeg subprocess returned non-zero."""

    def __init__(self, returncode: int, stderr: str):
        super().__init__(f"ffmpeg failed with code {returncode}")
        self.returncode = returncode
        self.stderr = stderr
```

- [ ] **Step 2: Commit**

```bash
git add src/photos_to_slideshow/errors.py
git commit -m "feat: typed exceptions for exit-code mapping"
```

---

## Task 3: Timing Math (`audio.compute_timing`)

**Files:**
- Create: `src/photos_to_slideshow/audio.py`
- Test: `tests/test_audio.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audio.py`:
```python
import pytest

from photos_to_slideshow.audio import SlideTiming, compute_timing


def test_basic_crossfade_timing():
    # 60 photos, 180s audio, 0.5s xfade
    # D = (180 + 59*0.5) / 60 = 209.5 / 60 = 3.4916...
    t = compute_timing(audio_duration=180.0, n_photos=60, xfade=0.5)
    assert t.slide_duration == pytest.approx(209.5 / 60)
    assert t.xfade == 0.5
    assert t.downgraded_to_cut is False


def test_single_photo_uses_full_audio():
    t = compute_timing(audio_duration=10.0, n_photos=1, xfade=0.5)
    assert t.slide_duration == pytest.approx(10.0)
    assert t.xfade == 0.0  # no transition with one photo
    assert t.downgraded_to_cut is False


def test_cut_transition_when_xfade_zero():
    t = compute_timing(audio_duration=60.0, n_photos=10, xfade=0.0)
    assert t.slide_duration == pytest.approx(6.0)


def test_auto_downgrade_when_slide_too_short_for_xfade():
    # 100 photos in 30s audio with 0.5s xfade -> slide ~0.3s, less than 2*xfade
    t = compute_timing(audio_duration=30.0, n_photos=100, xfade=0.5)
    assert t.downgraded_to_cut is True
    assert t.xfade == 0.0
    assert t.slide_duration == pytest.approx(0.3)


def test_zero_photos_raises():
    with pytest.raises(ValueError):
        compute_timing(audio_duration=10.0, n_photos=0, xfade=0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'photos_to_slideshow.audio'`.

- [ ] **Step 3: Implement `audio.compute_timing`**

Create `src/photos_to_slideshow/audio.py`:
```python
"""Audio inspection and slide-timing math."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SlideTiming:
    slide_duration: float  # seconds each slide is on screen
    xfade: float           # crossfade duration (0 means hard cut)
    downgraded_to_cut: bool


def compute_timing(audio_duration: float, n_photos: int, xfade: float) -> SlideTiming:
    """Compute per-slide duration so the slideshow ends with the audio.

    With N frames of duration D and (N-1) crossfades of length X overlapping
    adjacent frames, total video length = N*D - (N-1)*X.
    Solving for D: D = (audio_duration + (N-1)*X) / N.

    If the resulting slide is too short to host a crossfade (D < 2*X), we
    auto-downgrade to hard cuts and recompute D = audio_duration / N.
    """
    if n_photos < 1:
        raise ValueError("n_photos must be >= 1")

    if n_photos == 1:
        return SlideTiming(slide_duration=audio_duration, xfade=0.0, downgraded_to_cut=False)

    if xfade <= 0:
        return SlideTiming(
            slide_duration=audio_duration / n_photos,
            xfade=0.0,
            downgraded_to_cut=False,
        )

    slide = (audio_duration + (n_photos - 1) * xfade) / n_photos
    if slide < 2 * xfade:
        return SlideTiming(
            slide_duration=audio_duration / n_photos,
            xfade=0.0,
            downgraded_to_cut=True,
        )
    return SlideTiming(slide_duration=slide, xfade=xfade, downgraded_to_cut=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/audio.py tests/test_audio.py
git commit -m "feat(audio): slide timing math with cut auto-downgrade"
```

---

## Task 4: MP3 Duration Reader (`audio.read_audio_duration`)

**Files:**
- Modify: `src/photos_to_slideshow/audio.py`
- Modify: `tests/test_audio.py`
- Test fixture: `tests/fixtures/silent_1s.mp3`

- [ ] **Step 1: Generate a tiny test MP3 fixture (one-time setup)**

```bash
mkdir -p tests/fixtures
ffmpeg -y -f lavfi -i anullsrc=r=22050:cl=mono -t 1 -q:a 9 tests/fixtures/silent_1s.mp3
```

- [ ] **Step 2: Add the failing test**

Append to `tests/test_audio.py`:
```python
from pathlib import Path
from photos_to_slideshow.audio import read_audio_duration
from photos_to_slideshow.errors import UsageError


def test_read_audio_duration_returns_seconds(fixtures_dir: Path):
    dur = read_audio_duration(fixtures_dir / "silent_1s.mp3")
    assert 0.9 < dur < 1.2  # mp3 frame quantization is loose


def test_read_audio_duration_missing_file_raises(tmp_path: Path):
    with pytest.raises(UsageError):
        read_audio_duration(tmp_path / "nope.mp3")
```

- [ ] **Step 3: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: 2 failures (`ImportError: cannot import name 'read_audio_duration'`).

- [ ] **Step 4: Implement `read_audio_duration`**

Append to `src/photos_to_slideshow/audio.py`:
```python
from pathlib import Path

from mutagen.mp3 import MP3, HeaderNotFoundError

from .errors import UsageError


def read_audio_duration(path: Path) -> float:
    """Return MP3 duration in seconds. Raises UsageError on bad/missing file."""
    if not path.exists():
        raise UsageError(f"Audio file not found: {path}")
    try:
        mp3 = MP3(str(path))
    except HeaderNotFoundError as e:
        raise UsageError(f"Not a valid MP3: {path}") from e
    if mp3.info is None or mp3.info.length <= 0:
        raise UsageError(f"Could not determine audio duration: {path}")
    return float(mp3.info.length)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_audio.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add src/photos_to_slideshow/audio.py tests/test_audio.py tests/fixtures/silent_1s.mp3
git commit -m "feat(audio): MP3 duration reader using mutagen"
```

---

## Task 5: EXIF Date Extraction (`metadata.extract_date`)

**Files:**
- Create: `src/photos_to_slideshow/metadata.py`
- Test: `tests/test_metadata.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_metadata.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_metadata.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `extract_date`**

Create `src/photos_to_slideshow/metadata.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_metadata.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/metadata.py tests/test_metadata.py
git commit -m "feat(metadata): EXIF date extraction with mtime fallback"
```

---

## Task 6: Sort by Date (`metadata.sort_by_date`)

**Files:**
- Modify: `src/photos_to_slideshow/metadata.py`
- Modify: `tests/test_metadata.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_metadata.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_metadata.py -v`
Expected: 3 new failures (`ImportError: cannot import name 'sort_by_date'`).

- [ ] **Step 3: Implement `sort_by_date`**

Append to `src/photos_to_slideshow/metadata.py`:
```python
def sort_by_date(paths: list[Path]) -> tuple[list[Path], int]:
    """Return (paths sorted by best-known date asc, count of mtime fallbacks).

    Ties broken by filename for deterministic output.
    """
    dated = [extract_date(p) for p in paths]
    dated.sort(key=lambda d: (d.timestamp, d.path.name))
    fallback = sum(1 for d in dated if d.source is DateSource.MTIME)
    return [d.path for d in dated], fallback
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_metadata.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/metadata.py tests/test_metadata.py
git commit -m "feat(metadata): chronological sort with stable filename tiebreak"
```

---

## Task 7: Supported-File Filter (`inputs.iter_image_files`)

**Files:**
- Create: `src/photos_to_slideshow/inputs.py`
- Test: `tests/test_inputs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_inputs.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_inputs.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `iter_image_files`**

Create `src/photos_to_slideshow/inputs.py`:
```python
"""Input resolution: zip extraction and supported-file discovery."""

from collections.abc import Iterator
from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})


def iter_image_files(root: Path) -> Iterator[Path]:
    """Yield supported image files under root, recursively. Order undefined."""
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield p
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_inputs.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/inputs.py tests/test_inputs.py
git commit -m "feat(inputs): supported-extension recursive file scanner"
```

---

## Task 8: Zip Extraction & Resolve (`inputs.resolve`)

**Files:**
- Modify: `src/photos_to_slideshow/inputs.py`
- Modify: `tests/test_inputs.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_inputs.py`:
```python
import zipfile
from photos_to_slideshow.inputs import resolve
from photos_to_slideshow.errors import UsageError


def test_resolve_returns_directory_unchanged(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    resolved = resolve(tmp_path)
    assert resolved.root == tmp_path
    assert resolved.temp_dir is None  # we did not extract anything


def test_resolve_extracts_zip_to_temp(tmp_path: Path):
    zip_path = tmp_path / "photos.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("nested/a.jpg", b"x")
        zf.writestr("b.png", b"x")
    resolved = resolve(zip_path)
    assert resolved.temp_dir is not None
    assert resolved.temp_dir.exists()
    assert resolved.root == resolved.temp_dir
    found = sorted(p.name for p in resolved.root.rglob("*") if p.is_file())
    assert found == ["a.jpg", "b.png"]
    # Cleanup leaves no trace
    resolved.cleanup()
    assert not resolved.temp_dir.exists()


def test_resolve_missing_path_raises(tmp_path: Path):
    with pytest.raises(UsageError):
        resolve(tmp_path / "nope")


def test_resolve_unsupported_file_raises(tmp_path: Path):
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"x")
    with pytest.raises(UsageError):
        resolve(bad)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_inputs.py -v`
Expected: 4 failures (`ImportError: cannot import name 'resolve'`).

- [ ] **Step 3: Implement `resolve`**

Append to `src/photos_to_slideshow/inputs.py`:
```python
import shutil
import tempfile
import zipfile
from dataclasses import dataclass

from .errors import UsageError


@dataclass
class ResolvedInput:
    root: Path
    temp_dir: Path | None  # set if we created a temp dir we own

    def cleanup(self) -> None:
        if self.temp_dir is not None and self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)


def resolve(path: Path) -> ResolvedInput:
    """Resolve a CLI input path to a directory of images.

    - Directory: returned as-is (never modified or deleted by us).
    - .zip file:  extracted to a fresh temp dir we own.
    - Anything else: UsageError.
    """
    if not path.exists():
        raise UsageError(f"Input not found: {path}")

    if path.is_dir():
        return ResolvedInput(root=path, temp_dir=None)

    if path.is_file() and path.suffix.lower() == ".zip":
        temp = Path(tempfile.mkdtemp(prefix="photos_to_slideshow_"))
        try:
            with zipfile.ZipFile(path) as zf:
                zf.extractall(temp)
        except zipfile.BadZipFile as e:
            shutil.rmtree(temp)
            raise UsageError(f"Bad zip file: {path}") from e
        return ResolvedInput(root=temp, temp_dir=temp)

    raise UsageError(f"Unsupported input (must be directory or .zip): {path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_inputs.py -v`
Expected: 6 passed total.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/inputs.py tests/test_inputs.py
git commit -m "feat(inputs): resolve directory or zip to working root with cleanup"
```

---

## Task 9: Image Decode with HEIC Support (`images.decode_image`)

**Files:**
- Create: `src/photos_to_slideshow/images.py`
- Test: `tests/test_images.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_images.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_images.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `decode_image`**

Create `src/photos_to_slideshow/images.py`:
```python
"""Image decoding (HEIC-aware) and frame compositing."""

from pathlib import Path

from PIL import Image, ImageOps

import pillow_heif

# Register HEIC/HEIF decoders with Pillow
pillow_heif.register_heif_opener()


def decode_image(path: Path) -> Image.Image:
    """Open an image, apply EXIF orientation, return an RGB Pillow image."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)  # honor camera rotation
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_images.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/images.py tests/test_images.py
git commit -m "feat(images): decode_image with HEIC support and orientation handling"
```

---

## Task 10: Blur-Fill Frame Compositor (`images.render_frame`)

**Files:**
- Modify: `src/photos_to_slideshow/images.py`
- Modify: `tests/test_images.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_images.py`:
```python
from photos_to_slideshow.images import render_frame


def test_render_frame_landscape_fills_canvas(tmp_path: Path):
    src = tmp_path / "landscape.jpg"
    Image.new("RGB", (1000, 500), "red").save(src, "JPEG")
    out = render_frame(src, canvas_size=(1920, 1080))
    assert out.mode == "RGB"
    assert out.size == (1920, 1080)


def test_render_frame_portrait_fills_canvas(tmp_path: Path):
    src = tmp_path / "portrait.jpg"
    Image.new("RGB", (500, 1000), "green").save(src, "JPEG")
    out = render_frame(src, canvas_size=(1920, 1080))
    assert out.size == (1920, 1080)


def test_render_frame_centers_image(tmp_path: Path):
    """The center pixel of a uniform red landscape should still be red."""
    src = tmp_path / "uniform.jpg"
    Image.new("RGB", (1000, 500), (255, 0, 0)).save(src, "JPEG")
    out = render_frame(src, canvas_size=(1920, 1080))
    cx, cy = 1920 // 2, 1080 // 2
    r, g, b = out.getpixel((cx, cy))
    assert r > 200 and g < 50 and b < 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_images.py -v`
Expected: 3 new failures (`ImportError: cannot import name 'render_frame'`).

- [ ] **Step 3: Implement `render_frame`**

Append to `src/photos_to_slideshow/images.py`:
```python
from PIL import ImageFilter


def render_frame(path: Path, canvas_size: tuple[int, int]) -> Image.Image:
    """Compose a single slide: photo fit-letterboxed onto a blurred copy of itself.

    The blurred background fills the canvas; the photo is centered at max
    aspect-preserved size. Photo content is never cropped.
    """
    canvas_w, canvas_h = canvas_size
    src = decode_image(path)

    # Background: scale to *cover* the canvas, then blur heavily
    bg = ImageOps.fit(src, (canvas_w, canvas_h), method=Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=40))

    # Foreground: scale to *fit* inside the canvas (no crop)
    fg = src.copy()
    fg.thumbnail((canvas_w, canvas_h), Image.Resampling.LANCZOS)

    # Composite centered
    canvas = bg.copy()
    fx = (canvas_w - fg.width) // 2
    fy = (canvas_h - fg.height) // 2
    canvas.paste(fg, (fx, fy))
    return canvas
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_images.py -v`
Expected: 6 passed total.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/images.py tests/test_images.py
git commit -m "feat(images): blur-fill frame compositor at target canvas size"
```

---

## Task 11: ffmpeg Command Construction (`render.build_ffmpeg_command`)

This builds the argv list as a pure function (no subprocess yet) so it can be unit-tested.

**Files:**
- Create: `src/photos_to_slideshow/render.py`
- Modify: `tests/test_e2e.py` (will create later); for now create `tests/test_render.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_render.py`:
```python
from pathlib import Path

from photos_to_slideshow.render import RenderOptions, build_ffmpeg_command


def test_command_includes_each_frame_as_image_input(tmp_path: Path):
    frames = [tmp_path / f"{i:04d}.png" for i in range(3)]
    for f in frames:
        f.write_bytes(b"x")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = tmp_path / "out.mp4"

    opts = RenderOptions(
        slide_duration=2.0,
        xfade=0.5,
        fps=30,
        canvas_size=(1920, 1080),
        audio_fade=1.0,
        end_fade=1.0,
    )
    argv = build_ffmpeg_command(frames, audio, out, opts)

    # One -loop/-t/-i triple per frame
    assert argv.count("-loop") == 3
    assert argv.count(str(audio)) == 1
    assert str(out) == argv[-1]
    assert "-y" in argv
    # Filter graph must reference xfade and afade
    fc_idx = argv.index("-filter_complex")
    fc = argv[fc_idx + 1]
    assert "xfade" in fc
    assert "afade" in fc


def test_command_uses_concat_when_no_xfade(tmp_path: Path):
    frames = [tmp_path / f"{i:04d}.png" for i in range(2)]
    for f in frames:
        f.write_bytes(b"x")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = tmp_path / "out.mp4"

    opts = RenderOptions(
        slide_duration=2.0,
        xfade=0.0,  # cuts only
        fps=30,
        canvas_size=(1920, 1080),
        audio_fade=0.0,
        end_fade=0.0,
    )
    argv = build_ffmpeg_command(frames, audio, out, opts)
    fc = argv[argv.index("-filter_complex") + 1]
    assert "xfade" not in fc
    assert "concat" in fc


def test_command_handles_single_frame(tmp_path: Path):
    frame = tmp_path / "0000.png"
    frame.write_bytes(b"x")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = tmp_path / "out.mp4"

    opts = RenderOptions(
        slide_duration=3.0,
        xfade=0.0,
        fps=30,
        canvas_size=(1920, 1080),
        audio_fade=0.0,
        end_fade=0.0,
    )
    argv = build_ffmpeg_command([frame], audio, out, opts)
    # No filter_complex needed for one frame; or filter chain still well-formed
    assert str(out) == argv[-1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `build_ffmpeg_command`**

Create `src/photos_to_slideshow/render.py`:
```python
"""ffmpeg command construction and invocation."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RenderOptions:
    slide_duration: float
    xfade: float          # 0 means hard cuts via concat
    fps: int
    canvas_size: tuple[int, int]
    audio_fade: float     # seconds for in and out
    end_fade: float       # video fade-to-black at end


def _video_filter_xfade(n_frames: int, opts: RenderOptions) -> tuple[str, float]:
    """Build the xfade chain. Returns (filter_string, total_video_seconds).

    Each input frame is shown for slide_duration s. Frame i begins crossfading
    into frame i+1 at offset = (i+1)*slide_duration - (i+1)*xfade.
    Total length = N*D - (N-1)*X.
    """
    D = opts.slide_duration
    X = opts.xfade
    parts: list[str] = []
    prev = "[0:v]"
    for i in range(1, n_frames):
        offset = i * D - i * X
        out_label = f"[v{i}]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={X}:offset={offset:.6f}{out_label}"
        )
        prev = out_label
    total = n_frames * D - (n_frames - 1) * X
    # Always end the chain with a [vout] label, optionally with end fade.
    if opts.end_fade > 0:
        parts.append(
            f"{prev}fade=t=out:st={(total - opts.end_fade):.6f}:d={opts.end_fade}[vout]"
        )
    else:
        parts.append(f"{prev}null[vout]")
    return ";".join(parts), total


def _video_filter_concat(n_frames: int, opts: RenderOptions) -> tuple[str, float]:
    """Build a concat-based filter chain (hard cuts)."""
    inputs = "".join(f"[{i}:v]" for i in range(n_frames))
    parts = [f"{inputs}concat=n={n_frames}:v=1:a=0[vcat]"]
    total = n_frames * opts.slide_duration
    if opts.end_fade > 0:
        parts.append(
            f"[vcat]fade=t=out:st={(total - opts.end_fade):.6f}:d={opts.end_fade}[vout]"
        )
    else:
        parts.append("[vcat]null[vout]")
    return ";".join(parts), total


def _audio_filter(audio_input_index: int, total_video: float, opts: RenderOptions) -> str:
    """Build the audio filter: trim to video length plus optional fade in/out."""
    parts = [f"[{audio_input_index}:a]atrim=duration={total_video:.6f}"]
    if opts.audio_fade > 0:
        parts.append(f"afade=t=in:st=0:d={opts.audio_fade}")
        parts.append(
            f"afade=t=out:st={(total_video - opts.audio_fade):.6f}:d={opts.audio_fade}"
        )
    return ",".join(parts) + "[aout]"


def build_ffmpeg_command(
    frames: list[Path],
    audio: Path,
    output: Path,
    opts: RenderOptions,
) -> list[str]:
    """Construct the full ffmpeg argv. Pure function — no execution."""
    if not frames:
        raise ValueError("frames must be non-empty")

    argv: list[str] = ["ffmpeg", "-y"]

    # One image input per frame: -loop 1 -t D -i frame.png
    for f in frames:
        argv += ["-loop", "1", "-t", f"{opts.slide_duration:.6f}", "-i", str(f)]

    # Audio input
    audio_idx = len(frames)
    argv += ["-i", str(audio)]

    # Build filter graph
    if opts.xfade > 0 and len(frames) > 1:
        v_filter, total = _video_filter_xfade(len(frames), opts)
    else:
        v_filter, total = _video_filter_concat(len(frames), opts)
    a_filter = _audio_filter(audio_idx, total, opts)
    filter_complex = f"{v_filter};{a_filter}"

    argv += ["-filter_complex", filter_complex]
    argv += ["-map", "[vout]", "-map", "[aout]"]
    argv += [
        "-r", str(opts.fps),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]
    return argv
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_render.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/render.py tests/test_render.py
git commit -m "feat(render): pure ffmpeg command construction with xfade and concat paths"
```

---

## Task 12: ffmpeg Subprocess Runner (`render.run_ffmpeg`)

**Files:**
- Modify: `src/photos_to_slideshow/render.py`

- [ ] **Step 1: Implement `run_ffmpeg`**

Append to `src/photos_to_slideshow/render.py`:
```python
import subprocess

from .errors import FFmpegError


def run_ffmpeg(argv: list[str], verbose: bool = False) -> None:
    """Run ffmpeg, streaming stderr if verbose, raising FFmpegError on failure."""
    stderr = None if verbose else subprocess.PIPE
    proc = subprocess.run(argv, stderr=stderr, text=True)
    if proc.returncode != 0:
        msg = proc.stderr or "(no stderr captured; use --verbose to see output)"
        raise FFmpegError(proc.returncode, msg)


def ensure_ffmpeg_available() -> None:
    """Raise UsageError if ffmpeg is not on PATH."""
    from shutil import which
    from .errors import UsageError
    if which("ffmpeg") is None:
        raise UsageError(
            "ffmpeg not found on PATH. Install with: sudo apt install -y ffmpeg"
        )
```

- [ ] **Step 2: Commit**

```bash
git add src/photos_to_slideshow/render.py
git commit -m "feat(render): subprocess runner and ffmpeg-availability check"
```

---

## Task 13: CLI Argparse (`cli.parse_args`)

**Files:**
- Create: `src/photos_to_slideshow/cli.py`

- [ ] **Step 1: Implement `parse_args` (testable in isolation)**

Create `src/photos_to_slideshow/cli.py`:
```python
"""Command-line entry point for photos-to-slideshow."""

import argparse
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="photos-to-slideshow",
        description="Turn a folder/zip of photos plus an MP3 into an MP4 slideshow.",
    )
    parser.add_argument("--input", type=Path, required=True,
                        help="Directory or .zip of photos")
    parser.add_argument("--audio", type=Path, required=True,
                        help="MP3 soundtrack")
    parser.add_argument("--output", type=Path, default=Path("slideshow.mp4"),
                        help="Output MP4 path (default: ./slideshow.mp4)")
    parser.add_argument("--resolution", default="1920x1080",
                        help="WxH (default: 1920x1080)")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--fit", choices=["blur", "letterbox", "crop"], default="blur",
                        help="(only 'blur' is implemented in v0.1)")
    parser.add_argument("--transition", choices=["crossfade", "cut", "fade-black"],
                        default="crossfade")
    parser.add_argument("--transition-duration", type=float, default=0.5,
                        dest="transition_duration")
    parser.add_argument("--audio-fade", type=float, default=1.0, dest="audio_fade")
    parser.add_argument("--end-fade", type=float, default=1.0, dest="end_fade")
    parser.add_argument("--missing-date", choices=["mtime", "filename", "skip"],
                        default="mtime", dest="missing_date",
                        help="(only 'mtime' is implemented in v0.1)")
    parser.add_argument("--keep-temp", action="store_true", dest="keep_temp")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")
    return parser.parse_args(argv)


def parse_resolution(s: str) -> tuple[int, int]:
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError) as e:
        from .errors import UsageError
        raise UsageError(f"Invalid --resolution {s!r}: expected WxH like 1920x1080") from e
```

- [ ] **Step 2: Sanity check argparse**

Run:
```bash
.venv/bin/python -c "from photos_to_slideshow.cli import parse_args; print(parse_args(['--input','x','--audio','y']))"
```
Expected: prints a `Namespace(...)` with `input=PosixPath('x')`, `audio=PosixPath('y')`, defaults for the rest. (We don't yet have a `__main__` block; `--help` from the CLI script comes online in Task 14.)

- [ ] **Step 3: Commit**

```bash
git add src/photos_to_slideshow/cli.py
git commit -m "feat(cli): argparse with all flags from spec"
```

---

## Task 14: CLI Orchestration (`cli.main`)

**Files:**
- Modify: `src/photos_to_slideshow/cli.py`

- [ ] **Step 1: Implement `main`**

Append to `src/photos_to_slideshow/cli.py`:
```python
import sys
import tempfile
import shutil
from pathlib import Path

from tqdm import tqdm

from . import audio as audio_mod
from . import images, inputs, metadata, render
from .errors import FFmpegError, NoUsablePhotosError, SlideshowError, UsageError


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code (0/1/2/3/130)."""
    try:
        args = parse_args(argv)
        return _run(args)
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except NoUsablePhotosError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except FFmpegError as e:
        print(f"ffmpeg failed (code {e.returncode}):\n{e.stderr}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except SlideshowError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _run(args) -> int:
    render.ensure_ffmpeg_available()

    canvas = parse_resolution(args.resolution)

    # Resolve transition into xfade seconds
    if args.transition == "cut":
        xfade = 0.0
    else:
        # crossfade and fade-black both map to xfade duration; we use the
        # default 'fade' xfade transition for both in v0.1
        xfade = args.transition_duration

    # Step 1: resolve input
    resolved = inputs.resolve(args.input)
    frames_dir: Path | None = None
    try:
        # Step 2: scan & sort
        all_paths = list(inputs.iter_image_files(resolved.root))
        if not all_paths:
            raise NoUsablePhotosError(f"No supported images found in {args.input}")
        sorted_paths, mtime_fallbacks = metadata.sort_by_date(all_paths)
        if mtime_fallbacks:
            print(
                f"warning: {mtime_fallbacks} of {len(sorted_paths)} photos lacked "
                f"EXIF date; used file mtime instead",
                file=sys.stderr,
            )

        # Step 3: pre-render frames
        frames_dir = Path(tempfile.mkdtemp(prefix="photos_to_slideshow_frames_"))
        frame_paths: list[Path] = []
        bar = tqdm(
            sorted_paths,
            desc="Rendering frames",
            disable=args.quiet,
            file=sys.stderr,
        )
        for i, src in enumerate(bar):
            try:
                frame = images.render_frame(src, canvas)
            except Exception as e:
                print(f"warning: skipping unreadable image {src}: {e}", file=sys.stderr)
                continue
            out = frames_dir / f"{i:05d}.png"
            frame.save(out, "PNG")
            frame_paths.append(out)

        if not frame_paths:
            raise NoUsablePhotosError("All images failed to decode")

        # Step 4: timing math
        audio_dur = audio_mod.read_audio_duration(args.audio)
        timing = audio_mod.compute_timing(audio_dur, len(frame_paths), xfade)
        if timing.downgraded_to_cut:
            print(
                f"warning: slide duration too short for crossfade; "
                f"using hard cuts instead",
                file=sys.stderr,
            )
        # Clamp audio_fade if song is short
        audio_fade = args.audio_fade
        if audio_fade * 2 > audio_dur:
            audio_fade = audio_dur / 4
            print(
                f"warning: audio shorter than 2x audio-fade; "
                f"clamped audio-fade to {audio_fade:.2f}s",
                file=sys.stderr,
            )

        # Step 5: render video
        opts = render.RenderOptions(
            slide_duration=timing.slide_duration,
            xfade=timing.xfade,
            fps=args.fps,
            canvas_size=canvas,
            audio_fade=audio_fade,
            end_fade=args.end_fade,
        )
        # Ensure output dir exists
        args.output.parent.mkdir(parents=True, exist_ok=True)
        argv_ff = render.build_ffmpeg_command(frame_paths, args.audio, args.output, opts)
        render.run_ffmpeg(argv_ff, verbose=args.verbose)

        print(str(args.output))  # only output to stdout, so the tool is pipeable
        return 0

    finally:
        # Step 6: cleanup
        if not args.keep_temp:
            resolved.cleanup()
            if frames_dir is not None and frames_dir.exists():
                shutil.rmtree(frames_dir)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
```

- [ ] **Step 2: Sanity smoke test (no real run yet)**

Run: `.venv/bin/python -m photos_to_slideshow.cli --help`
Expected: full help text printed, exit 0.

- [ ] **Step 3: Commit**

```bash
git add src/photos_to_slideshow/cli.py
git commit -m "feat(cli): main orchestration with progress, warnings, cleanup"
```

---

## Task 15: End-to-End Test

**Files:**
- Create: `tests/test_e2e.py`
- Test fixtures: a few JPEGs + reuse `silent_1s.mp3`

- [ ] **Step 1: Add the e2e test (auto-generates fixtures)**

Create `tests/test_e2e.py`:
```python
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from photos_to_slideshow.cli import main


def _make_jpeg(path: Path, color: str, size: tuple[int, int],
               exif_dt: str) -> None:
    img = Image.new("RGB", size, color)
    exif = img.getexif()
    exif[0x9003] = exif_dt  # DateTimeOriginal
    img.save(path, "JPEG", exif=exif)


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True)
    return float(out.strip())


@pytest.mark.slow
def test_end_to_end_creates_playable_mp4(tmp_path: Path, fixtures_dir: Path):
    # Three photos: landscape, portrait, landscape — chronological order
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    _make_jpeg(photos_dir / "a.jpg", "red",   (1000, 500), "2024:01:01 09:00:00")
    _make_jpeg(photos_dir / "b.jpg", "green", (500, 1000), "2024:01:02 09:00:00")
    _make_jpeg(photos_dir / "c.jpg", "blue",  (1000, 500), "2024:01:03 09:00:00")

    audio = fixtures_dir / "silent_1s.mp3"
    output = tmp_path / "out.mp4"

    rc = main([
        "--input", str(photos_dir),
        "--audio", str(audio),
        "--output", str(output),
        "--quiet",
    ])
    assert rc == 0
    assert output.exists()

    # Duration should be close to audio length (~1s)
    dur = _ffprobe_duration(output)
    assert 0.7 < dur < 1.5, f"unexpected duration {dur}"
```

- [ ] **Step 2: Run the e2e test**

Run: `.venv/bin/pytest tests/test_e2e.py -v -m slow`
Expected: 1 passed. (May take a few seconds.)

- [ ] **Step 3: Run the full test suite**

Run: `.venv/bin/pytest -v`
Expected: all tests pass (slow tests included by default unless `-m "not slow"`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: end-to-end CLI run produces playable mp4"
```

---

## Task 16: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README**

Create `README.md`:
```markdown
# photos-to-slideshow

A Linux CLI that turns a folder (or zip) of photos plus an MP3 into an MP4
slideshow video. Photos are sorted by EXIF date taken; mixed orientations
are handled with a blurred-background fill so nothing gets cropped.

Built for school year-end recap videos played in VLC on Windows laptops.

## Install

System dependency:
```bash
sudo apt install -y ffmpeg
```

Python install (recommended in a venv):
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

Minimal:
```bash
photos-to-slideshow --input ./photos --audio ./song.mp3
```

Or with a zip:
```bash
photos-to-slideshow --input photos.zip --audio song.mp3 --output recap.mp4
```

The slideshow length is auto-fit to the song length: each photo is shown
for `(audio_duration + (N-1) * crossfade) / N` seconds.

### Common flags

| Flag | Default | Notes |
|---|---|---|
| `--input` | (required) | directory or `.zip` of photos |
| `--audio` | (required) | `.mp3` soundtrack |
| `--output` | `./slideshow.mp4` | output path |
| `--resolution` | `1920x1080` | output frame size |
| `--fps` | `30` | output framerate |
| `--transition` | `crossfade` | `crossfade` \| `cut` \| `fade-black` |
| `--transition-duration` | `0.5` | crossfade duration in seconds |
| `--audio-fade` | `1.0` | fade-in/out duration; `0` to disable |
| `--end-fade` | `1.0` | video fade-to-black at end |
| `--keep-temp` | off | keep working temp dirs (debugging) |
| `--verbose` / `-v` | off | show ffmpeg output |
| `--quiet` / `-q` | off | suppress progress bar |

## Supported formats

Input: `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`. Photos missing EXIF date use
file mtime as the fallback; a summary is printed at the end.

Output: H.264 (yuv420p) + AAC in MP4. Plays in VLC on Windows and any modern player.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                # all tests
.venv/bin/pytest -m "not slow"  # skip the e2e ffmpeg test
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: README with install, usage, and flag reference"
```

---

## Final Verification

- [ ] **Step 1: Full test suite**

Run: `.venv/bin/pytest -v`
Expected: all green.

- [ ] **Step 2: Manual smoke test**

```bash
mkdir -p /tmp/p2s_smoke && cd /tmp/p2s_smoke
# Generate three colored test photos with EXIF dates
.venv_path=/home/count_zero/Repos/photos_to_slideshow/.venv
$.venv_path/bin/python - <<'PY'
from PIL import Image
from pathlib import Path
for i, c in enumerate(["red", "green", "blue"], 1):
    img = Image.new("RGB", (800, 600), c)
    exif = img.getexif(); exif[0x9003] = f"2024:01:0{i} 09:00:00"
    img.save(f"/tmp/p2s_smoke/{i}.jpg", "JPEG", exif=exif)
PY
# Use the silent test mp3 from the repo
cp /home/count_zero/Repos/photos_to_slideshow/tests/fixtures/silent_1s.mp3 /tmp/p2s_smoke/song.mp3
/home/count_zero/Repos/photos_to_slideshow/.venv/bin/photos-to-slideshow \
  --input /tmp/p2s_smoke \
  --audio /tmp/p2s_smoke/song.mp3 \
  --output /tmp/p2s_smoke/out.mp4
ls -lh /tmp/p2s_smoke/out.mp4
```
Expected: `out.mp4` exists with non-zero size.

- [ ] **Step 3: Confirm git log is clean**

Run: `git log --oneline`
Expected: ~16 atomic commits, one per task.
