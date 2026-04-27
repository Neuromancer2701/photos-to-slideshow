"""Input resolution: zip extraction and supported-file discovery."""

import shutil
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .errors import UsageError

SUPPORTED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})


def iter_image_files(root: Path) -> Iterator[Path]:
    """Yield supported image files under root, recursively. Order undefined."""
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield p


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
