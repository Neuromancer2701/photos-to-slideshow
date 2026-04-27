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
