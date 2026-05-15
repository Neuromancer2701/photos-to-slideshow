"""Optional browser-based reorder UI.

Lazy-imported by cli._run only when --reorder is passed, so the default
no-flag path stays dep- and import-free.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
from tqdm import tqdm

from . import images


def generate_thumbnails(
    paths: list[Path],
    out_dir: Path,
    max_dim: int = 240,
) -> list[Path]:
    """Generate JPEG thumbnails for each photo, written to out_dir/<i>.jpg.

    Returns the subset of paths whose thumbnails were generated successfully,
    in input order. The returned list is index-aligned with the thumbnails:
    surviving[i] corresponds to out_dir/i.jpg. Photos that fail to decode
    are skipped with a stderr warning (same posture as cli._run's frame loop).
    """
    surviving: list[Path] = []
    bar = tqdm(paths, desc="Generating thumbnails", file=sys.stderr)
    for src in bar:
        try:
            img = images.decode_image(src)
        except Exception as e:
            print(f"warning: skipping unreadable image {src}: {e}",
                  file=sys.stderr)
            continue
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        thumb_path = out_dir / f"{len(surviving)}.jpg"
        img.save(thumb_path, "JPEG", quality=85)
        surviving.append(src)
    return surviving
