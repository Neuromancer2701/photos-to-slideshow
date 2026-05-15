"""Optional browser-based reorder UI.

Lazy-imported by cli._run only when --reorder is passed, so the default
no-flag path stays dep- and import-free.
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from PIL import Image
from tqdm import tqdm

from . import images
from .errors import SlideshowError


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
        elif self.path.startswith("/thumb/"):
            self._serve_thumb(self.path[len("/thumb/"):])
        elif self.path == "/static/sortable.min.js":
            self._serve_static("sortable.min.js", "application/javascript")
        else:
            self.send_error(404)

    def _serve_static(self, name: str, content_type: str):
        try:
            data = (files(_STATIC_PKG) / name).read_bytes()
        except (FileNotFoundError, OSError):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_thumb(self, index_str: str):
        try:
            i = int(index_str)
        except ValueError:
            self.send_error(404)
            return
        if not (0 <= i < len(self.server.photos)):
            self.send_error(404)
            return
        thumb_path = self.server.thumb_dir / f"{i}.jpg"
        try:
            data = thumb_path.read_bytes()
        except OSError:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        if self.path == "/lock":
            self._handle_lock()
        else:
            self.send_error(404)

    def _handle_lock(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
            order = payload["order"]
        except (ValueError, KeyError, TypeError):
            self._send_json(400, {"error": "malformed JSON or missing 'order'"})
            return
        n = len(self.server.photos)
        if not (isinstance(order, list) and len(order) == n
                and sorted(order) == list(range(n))):
            self._send_json(400, {"error": "order must be a permutation of 0..N-1"})
            return
        self.server.final_order = order
        self.server.done_event.set()
        self._send_json(200, {"ok": True})

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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


def reorder_via_browser(photos: list[Path], thumb_dir: Path) -> list[Path]:
    """Open a browser UI to drag-reorder photos. Returns the new order.

    Blocks the calling thread on the server's done_event until the user
    clicks "Lock & Render" in the UI. Ctrl-C from the terminal propagates
    a KeyboardInterrupt, which cli.main catches as exit 130.
    """
    try:
        server = _build_server(photos, thumb_dir)
    except OSError as e:
        raise SlideshowError(f"could not bind local server: {e}") from e
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Reorder UI: {url}", file=sys.stderr)
    print(
        'Reorder UI: drag thumbnails, click "Lock & Render". '
        "Ctrl-C here to cancel.",
        file=sys.stderr,
    )
    if not webbrowser.open(url):
        print(f"Open this URL in a browser: {url}", file=sys.stderr)
    try:
        server.done_event.wait()
    finally:
        server.shutdown()
        thread.join(timeout=2)
    assert server.final_order is not None  # done_event implies this is set
    return [photos[i] for i in server.final_order]
