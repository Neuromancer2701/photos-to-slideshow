"""Input resolution: zip extraction and supported-file discovery."""

from collections.abc import Iterator
from pathlib import Path

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})


def iter_image_files(root: Path) -> Iterator[Path]:
    """Yield supported image files under root, recursively. Order undefined."""
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield p
