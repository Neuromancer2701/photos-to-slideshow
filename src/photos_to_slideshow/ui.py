"""Optional browser-based reorder UI.

Lazy-imported by cli._run only when --reorder is passed, so the default
no-flag path stays dep- and import-free.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
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


_STATIC_PKG = "photos_to_slideshow.static"
_INJECT_TOKEN = "/*__PHOTOS_INJECT__*/"


class _ReorderServer(ThreadingHTTPServer):
    """ThreadingHTTPServer with session state attached."""

    def __init__(self, address: tuple[str, int], photos: list[Path],
                 thumb_dir: Path):
        self.photos = photos
        self.thumb_dir = thumb_dir
        self.done_event = threading.Event()
        self.final_order: list[int] | None = None
        super().__init__(address, _ReorderHandler)


def _build_server(photos: list[Path], thumb_dir: Path) -> _ReorderServer:
    return _ReorderServer(("127.0.0.1", 0), photos, thumb_dir)


class _ReorderHandler(BaseHTTPRequestHandler):
    # Silence the default stderr access log so it doesn't pollute the CLI.
    def log_message(self, format, *args):  # noqa: A002
        pass

    server: _ReorderServer  # type: ignore[assignment]

    def do_GET(self):  # noqa: N802
        if self.path == "/":
            self._serve_index()
        else:
            self.send_error(404)

    def _serve_index(self):
        template = (files(_STATIC_PKG) / "index.html").read_text()
        photos_json = json.dumps([
            {"i": i, "name": p.name}
            for i, p in enumerate(self.server.photos)
        ])
        body = template.replace(
            _INJECT_TOKEN, f"window.PHOTOS = {photos_json};",
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
