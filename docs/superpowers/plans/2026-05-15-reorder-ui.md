# Reorder UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--reorder` CLI flag that opens a lightweight browser-based drag-and-drop UI to reorder photos before the existing render pipeline runs.

**Architecture:** A new self-contained `ui.py` module boots a `ThreadingHTTPServer` on `127.0.0.1` at an ephemeral port, serves a single HTML page (vanilla JS + vendored SortableJS) plus pre-generated 240px JPEG thumbnails, and blocks the CLI on a `threading.Event` until the user POSTs the locked order. The reordered list replaces `sorted_paths` in `cli._run` and the existing Step 3+ pipeline continues unchanged.

**Tech Stack:** Python 3.10+ stdlib (`http.server`, `threading`, `webbrowser`, `importlib.resources`), Pillow, vendored SortableJS, pytest.

---

## File Structure

**Create:**
- `src/photos_to_slideshow/ui.py` — module containing `generate_thumbnails`, `reorder_via_browser`, `_ReorderServer`, `_ReorderHandler`.
- `src/photos_to_slideshow/static/index.html` — single-page app HTML/CSS/JS.
- `src/photos_to_slideshow/static/sortable.min.js` — vendored SortableJS UMD build.
- `tests/_helpers.py` — shared `make_jpeg` test helper.
- `tests/test_ui.py` — unit + HTTP integration tests for `ui.py`.

**Modify:**
- `src/photos_to_slideshow/cli.py` — add `--reorder` flag, lazy-import `ui`, wire Step 2.5, extend cleanup for `thumb_dir`.
- `pyproject.toml` — declare static assets as package data.
- `tests/test_metadata.py` — import `make_jpeg` from `tests._helpers` (drop the local `_make_jpeg`).

---

## Task 1: Shared test helper

**Files:**
- Create: `tests/_helpers.py`
- Modify: `tests/test_metadata.py`

- [ ] **Step 1: Create the shared helper module**

Write `tests/_helpers.py`:

```python
"""Test helpers shared across test modules."""

from pathlib import Path

from PIL import Image


def make_jpeg(path: Path, exif_datetime: str | None = None) -> Path:
    """Write a 10x10 red JPEG, optionally with an EXIF DateTimeOriginal."""
    img = Image.new("RGB", (10, 10), "red")
    if exif_datetime is None:
        img.save(path, "JPEG")
    else:
        exif = img.getexif()
        exif[0x9003] = exif_datetime  # DateTimeOriginal
        img.save(path, "JPEG", exif=exif)
    return path
```

- [ ] **Step 2: Update test_metadata.py to import the helper**

In `tests/test_metadata.py`, delete the local `_make_jpeg` definition (lines 13-22 currently) and add this import near the other test imports:

```python
from tests._helpers import make_jpeg as _make_jpeg
```

(Aliasing as `_make_jpeg` avoids editing every call site.)

- [ ] **Step 3: Run the metadata tests to verify the move is clean**

Run: `pytest tests/test_metadata.py -q`

Expected: all existing metadata tests still pass.

- [ ] **Step 4: Commit**

```bash
git add tests/_helpers.py tests/test_metadata.py
git commit -m "test: extract make_jpeg helper into tests/_helpers.py"
```

---

## Task 2: `generate_thumbnails`

**Files:**
- Create: `src/photos_to_slideshow/ui.py`
- Test: `tests/test_ui.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ui.py`:

```python
"""Unit + HTTP integration tests for the reorder UI module."""

from pathlib import Path

import pytest
from PIL import Image

from photos_to_slideshow import ui
from tests._helpers import make_jpeg


def test_generate_thumbnails_writes_one_jpeg_per_photo(tmp_path: Path):
    photos = [make_jpeg(tmp_path / f"src{i}.jpg", "2024:01:01 00:00:00")
              for i in range(3)]
    out_dir = tmp_path / "thumbs"
    out_dir.mkdir()
    surviving = ui.generate_thumbnails(photos, out_dir)
    assert surviving == photos
    for i in range(3):
        thumb = out_dir / f"{i}.jpg"
        assert thumb.exists()
        with Image.open(thumb) as img:
            assert max(img.size) <= 240
            assert img.format == "JPEG"


def test_generate_thumbnails_preserves_index_alignment(tmp_path: Path):
    a = make_jpeg(tmp_path / "a.jpg")
    b = make_jpeg(tmp_path / "b.jpg")
    out = tmp_path / "thumbs"
    out.mkdir()
    surviving = ui.generate_thumbnails([a, b], out)
    assert surviving == [a, b]
    assert (out / "0.jpg").exists()
    assert (out / "1.jpg").exists()


def test_generate_thumbnails_skips_unreadable_image(tmp_path: Path, capsys):
    good = make_jpeg(tmp_path / "good.jpg")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"")  # not a valid image
    out = tmp_path / "thumbs"
    out.mkdir()
    surviving = ui.generate_thumbnails([good, bad], out)
    # Only the good one survives; index 0 maps to it, no 1.jpg exists.
    assert surviving == [good]
    assert (out / "0.jpg").exists()
    assert not (out / "1.jpg").exists()
    err = capsys.readouterr().err
    assert "bad.jpg" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ui.py -q`

Expected: `ModuleNotFoundError: No module named 'photos_to_slideshow.ui'`

- [ ] **Step 3: Create the ui module with `generate_thumbnails`**

Create `src/photos_to_slideshow/ui.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ui.py -q`

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/ui.py tests/test_ui.py
git commit -m "feat(ui): add generate_thumbnails for reorder UI"
```

---

## Task 3: Server scaffolding + `GET /` route

**Files:**
- Modify: `src/photos_to_slideshow/ui.py`
- Modify: `tests/test_ui.py`
- Create: `src/photos_to_slideshow/static/index.html` (placeholder, fleshed out in Task 7)

- [ ] **Step 1: Write a placeholder index.html so the route has something to serve**

Create `src/photos_to_slideshow/static/index.html`:

```html
<!doctype html>
<html><head><meta charset="utf-8"><title>Reorder Photos</title></head>
<body>
<script>/*__PHOTOS_INJECT__*/</script>
<p>Reorder UI placeholder — Task 7 replaces this.</p>
</body></html>
```

The literal token `/*__PHOTOS_INJECT__*/` is the injection point; the server replaces it with a `window.PHOTOS = [...]` assignment before sending the response.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_ui.py`:

```python
import contextlib
import json
import threading
import urllib.request

from photos_to_slideshow import ui


@contextlib.contextmanager
def _running_server(photos, thumb_dir):
    server = ui._build_server(photos, thumb_dir)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield server, f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_get_root_serves_html_with_injected_photos(tmp_path: Path):
    a = make_jpeg(tmp_path / "alpha.jpg")
    b = make_jpeg(tmp_path / "beta.jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails([a, b], thumbs)
    with _running_server([a, b], thumbs) as (_, url):
        body = urllib.request.urlopen(url + "/").read().decode("utf-8")
    assert "window.PHOTOS" in body
    assert "alpha.jpg" in body
    assert "beta.jpg" in body
    # Stable IDs are 0 and 1
    assert '"i": 0' in body or '"i":0' in body
    assert '"i": 1' in body or '"i":1' in body
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest tests/test_ui.py::test_get_root_serves_html_with_injected_photos -q`

Expected: `AttributeError: module 'photos_to_slideshow.ui' has no attribute '_build_server'`

- [ ] **Step 4: Implement server, handler, and `GET /` route**

Append to `src/photos_to_slideshow/ui.py`:

```python
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files

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
```

Note: the existing `from PIL import Image` and `from tqdm import tqdm` imports stay at the top; the new imports (`json`, `threading`, `http.server`, `importlib.resources`) should be merged into the existing import block at the top of the file rather than appended at the bottom. Keep the existing `from . import images` import as well.

- [ ] **Step 5: Declare the static dir as package data so `files()` finds it**

Edit `pyproject.toml`. After the `[tool.setuptools.packages.find]` block, add:

```toml
[tool.setuptools.package-data]
photos_to_slideshow = ["static/*"]
```

Then create `src/photos_to_slideshow/static/__init__.py` (empty file) so the path resolves as a package for `importlib.resources.files`:

```bash
touch src/photos_to_slideshow/static/__init__.py
```

- [ ] **Step 6: Run to verify test passes**

Run: `pytest tests/test_ui.py::test_get_root_serves_html_with_injected_photos -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/photos_to_slideshow/ui.py src/photos_to_slideshow/static/ pyproject.toml tests/test_ui.py
git commit -m "feat(ui): serve reorder UI index page with injected photo list"
```

---

## Task 4: `GET /thumb/<i>` route

**Files:**
- Modify: `src/photos_to_slideshow/ui.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui.py`:

```python
def test_get_thumb_returns_jpeg(tmp_path: Path):
    a = make_jpeg(tmp_path / "a.jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails([a], thumbs)
    with _running_server([a], thumbs) as (_, url):
        resp = urllib.request.urlopen(url + "/thumb/0")
        body = resp.read()
        ctype = resp.headers["Content-Type"]
    assert ctype == "image/jpeg"
    assert len(body) > 0
    # JPEG magic bytes
    assert body[:3] == b"\xff\xd8\xff"


def test_get_thumb_out_of_range_returns_404(tmp_path: Path):
    a = make_jpeg(tmp_path / "a.jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails([a], thumbs)
    with _running_server([a], thumbs) as (_, url):
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(url + "/thumb/99")
    assert ei.value.code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_ui.py -k thumb -q`

Expected: both new tests fail with 404 (handler doesn't recognize `/thumb/*` yet).

- [ ] **Step 3: Implement the thumb route**

Replace the `do_GET` body in `_ReorderHandler` with:

```python
    def do_GET(self):  # noqa: N802
        if self.path == "/":
            self._serve_index()
        elif self.path.startswith("/thumb/"):
            self._serve_thumb(self.path[len("/thumb/"):])
        else:
            self.send_error(404)

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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ui.py -k thumb -q`

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/ui.py tests/test_ui.py
git commit -m "feat(ui): serve thumbnails over /thumb/<i>"
```

---

## Task 5: `POST /lock` route + validation

**Files:**
- Modify: `src/photos_to_slideshow/ui.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_ui.py`:

```python
def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_post_lock_with_valid_permutation_returns_ok_and_sets_event(tmp_path: Path):
    photos = [make_jpeg(tmp_path / f"{i}.jpg") for i in range(3)]
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails(photos, thumbs)
    with _running_server(photos, thumbs) as (server, url):
        status, body = _post_json(url + "/lock", {"order": [2, 0, 1]})
    assert status == 200
    assert body == {"ok": True}
    assert server.final_order == [2, 0, 1]
    assert server.done_event.is_set()


def test_post_lock_with_non_permutation_returns_400(tmp_path: Path):
    photos = [make_jpeg(tmp_path / f"{i}.jpg") for i in range(3)]
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails(photos, thumbs)
    with _running_server(photos, thumbs) as (server, url):
        status, _ = _post_json(url + "/lock", {"order": [0, 0, 1]})
    assert status == 400
    assert not server.done_event.is_set()


def test_post_lock_with_wrong_length_returns_400(tmp_path: Path):
    photos = [make_jpeg(tmp_path / f"{i}.jpg") for i in range(3)]
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails(photos, thumbs)
    with _running_server(photos, thumbs) as (server, url):
        status, _ = _post_json(url + "/lock", {"order": [0, 1]})
    assert status == 400
    assert not server.done_event.is_set()


def test_post_lock_with_malformed_json_returns_400(tmp_path: Path):
    photos = [make_jpeg(tmp_path / f"{i}.jpg") for i in range(3)]
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails(photos, thumbs)
    with _running_server(photos, thumbs) as (server, url):
        req = urllib.request.Request(
            url + "/lock",
            data=b"{not json",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as ei:
            urllib.request.urlopen(req)
    assert ei.value.code == 400
    assert not server.done_event.is_set()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_ui.py -k post_lock -q`

Expected: 4 tests fail (no POST handler).

- [ ] **Step 3: Implement the lock route**

Add to `_ReorderHandler`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ui.py -q`

Expected: all tests so far pass (3 thumb-gen + 1 index + 2 thumb route + 4 lock).

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/ui.py tests/test_ui.py
git commit -m "feat(ui): POST /lock validates permutation and signals done"
```

---

## Task 6: `reorder_via_browser` integration

**Files:**
- Modify: `src/photos_to_slideshow/ui.py`
- Modify: `tests/test_ui.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ui.py`:

```python
def test_reorder_via_browser_returns_permuted_paths(tmp_path: Path, monkeypatch):
    photos = [make_jpeg(tmp_path / f"{i}.jpg") for i in range(3)]
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails(photos, thumbs)
    # Don't actually open a browser during the test.
    monkeypatch.setattr(ui, "webbrowser", _StubBrowser())

    # The test must POST /lock from another thread while
    # reorder_via_browser is blocking the main thread on done_event.
    posted: dict = {}

    def post_when_ready():
        # Poll the module global the function will set so we know the URL.
        for _ in range(200):
            url = posted.get("url")
            if url:
                _post_json(url + "/lock", {"order": [2, 0, 1]})
                return
            import time
            time.sleep(0.02)

    poster = threading.Thread(target=post_when_ready, daemon=True)
    poster.start()

    # Patch _build_server to record the URL once the server is bound.
    original_build = ui._build_server

    def recording_build(photos, thumb_dir):
        server = original_build(photos, thumb_dir)
        posted["url"] = f"http://127.0.0.1:{server.server_address[1]}"
        return server

    monkeypatch.setattr(ui, "_build_server", recording_build)

    result = ui.reorder_via_browser(photos, thumbs)
    poster.join(timeout=2)
    assert result == [photos[2], photos[0], photos[1]]


class _StubBrowser:
    def open(self, url: str) -> bool:
        return True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_ui.py::test_reorder_via_browser_returns_permuted_paths -q`

Expected: `AttributeError: module 'photos_to_slideshow.ui' has no attribute 'reorder_via_browser'`

- [ ] **Step 3: Implement `reorder_via_browser`**

Add to `src/photos_to_slideshow/ui.py`. Add `import webbrowser` to the imports near the top and `from .errors import SlideshowError`, then append the function:

```python
import webbrowser  # add to existing import block at top of file
from .errors import SlideshowError  # add to existing import block at top of file


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
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_ui.py -q`

Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/photos_to_slideshow/ui.py tests/test_ui.py
git commit -m "feat(ui): reorder_via_browser glues server, browser, and blocking wait"
```

---

## Task 7: Static frontend (HTML + vendored SortableJS)

**Files:**
- Modify: `src/photos_to_slideshow/static/index.html`
- Create: `src/photos_to_slideshow/static/sortable.min.js`

This task is the JS side. No automated tests — covered by the manual smoke test in Task 9.

- [ ] **Step 1: Vendor SortableJS**

Download SortableJS v1.15.6 UMD build:

```bash
curl -sSL https://cdn.jsdelivr.net/npm/sortablejs@1.15.6/Sortable.min.js \
  -o src/photos_to_slideshow/static/sortable.min.js
```

Then verify by checking that `Sortable` is present in the file:

```bash
grep -c "Sortable" src/photos_to_slideshow/static/sortable.min.js
```

Expected: a number greater than 0.

If you can't reach jsdelivr, pull from `https://github.com/SortableJS/Sortable/raw/refs/tags/1.15.6/Sortable.min.js` instead.

- [ ] **Step 2: Add an attribution comment at the top of the vendored file**

Prepend (you can use any editor or `sed -i '1i ...'`) a single-line comment so the source and version are recorded:

```
/*! SortableJS 1.15.6 — vendored from https://github.com/SortableJS/Sortable (MIT). */
```

The rest of the file remains the minified original.

- [ ] **Step 3: Replace the placeholder `index.html` with the full UI**

Overwrite `src/photos_to_slideshow/static/index.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Reorder Photos</title>
<style>
  body { margin: 0; font-family: system-ui, sans-serif; background: #111; color: #eee; }
  header {
    position: sticky; top: 0; z-index: 10;
    background: #222; padding: 12px 16px;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #333;
  }
  header h1 { font-size: 16px; font-weight: 600; margin: 0; }
  header .count { color: #888; font-weight: 400; margin-left: 8px; }
  #lock {
    padding: 8px 16px; font-size: 14px; font-weight: 600;
    background: #2d7; color: #111; border: 0; border-radius: 4px; cursor: pointer;
  }
  #lock:hover { background: #4e9; }
  #lock:disabled { background: #555; color: #888; cursor: default; }
  #grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px; padding: 16px;
  }
  .tile {
    background: #1a1a1a; border: 1px solid #333; border-radius: 4px;
    overflow: hidden; cursor: grab; user-select: none;
  }
  .tile.sortable-chosen { cursor: grabbing; }
  .tile.sortable-ghost { opacity: 0.4; }
  .tile img { display: block; width: 100%; height: 160px; object-fit: contain; background: #000; }
  .tile .name { padding: 6px 8px; font-size: 11px; color: #aaa; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #toast {
    position: fixed; bottom: 16px; left: 50%; transform: translateX(-50%);
    background: #a33; color: #fff; padding: 8px 16px; border-radius: 4px;
    display: none;
  }
  #done {
    position: fixed; inset: 0; background: rgba(17,17,17,0.95);
    display: none; align-items: center; justify-content: center;
    font-size: 18px;
  }
</style>
</head>
<body>
<header>
  <h1>Reorder Photos <span class="count" id="count"></span></h1>
  <button id="lock">Lock &amp; Render</button>
</header>
<div id="grid"></div>
<div id="toast"></div>
<div id="done">Rendering — you can close this tab.</div>
<script>/*__PHOTOS_INJECT__*/</script>
<script src="/static/sortable.min.js"></script>
<script>
(function () {
  const grid = document.getElementById('grid');
  const lockBtn = document.getElementById('lock');
  const toast = document.getElementById('toast');
  const done = document.getElementById('done');
  document.getElementById('count').textContent = '(' + window.PHOTOS.length + ')';
  for (const p of window.PHOTOS) {
    const tile = document.createElement('div');
    tile.className = 'tile';
    tile.dataset.photoId = p.i;
    tile.innerHTML =
      '<img loading="lazy" src="/thumb/' + p.i + '">' +
      '<div class="name" title="' + p.name + '">' + p.name + '</div>';
    grid.appendChild(tile);
  }
  Sortable.create(grid, { animation: 150 });
  function showToast(msg) {
    toast.textContent = msg;
    toast.style.display = 'block';
    setTimeout(() => { toast.style.display = 'none'; }, 3000);
  }
  lockBtn.addEventListener('click', async () => {
    lockBtn.disabled = true;
    const order = [...grid.children].map(el => +el.dataset.photoId);
    try {
      const resp = await fetch('/lock', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({error: 'unknown'}));
        showToast('Lock failed: ' + (err.error || resp.status));
        lockBtn.disabled = false;
        return;
      }
      done.style.display = 'flex';
    } catch (e) {
      showToast('Network error: ' + e.message);
      lockBtn.disabled = false;
    }
  });
})();
</script>
</body>
</html>
```

- [ ] **Step 4: Serve `/static/sortable.min.js`**

The index.html references `/static/sortable.min.js`. Extend `_ReorderHandler.do_GET` so static files load:

```python
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
```

- [ ] **Step 5: Add a regression test for the static route**

Add to `tests/test_ui.py`:

```python
def test_get_static_sortable_returns_js(tmp_path: Path):
    a = make_jpeg(tmp_path / "a.jpg")
    thumbs = tmp_path / "thumbs"
    thumbs.mkdir()
    ui.generate_thumbnails([a], thumbs)
    with _running_server([a], thumbs) as (_, url):
        resp = urllib.request.urlopen(url + "/static/sortable.min.js")
        body = resp.read().decode("utf-8")
        ctype = resp.headers["Content-Type"]
    assert ctype == "application/javascript"
    assert "Sortable" in body
```

Run: `pytest tests/test_ui.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/photos_to_slideshow/static/ src/photos_to_slideshow/ui.py tests/test_ui.py
git commit -m "feat(ui): drag-and-drop frontend with vendored SortableJS"
```

---

## Task 8: CLI wiring — `--reorder` flag

**Files:**
- Modify: `src/photos_to_slideshow/cli.py`
- Modify: `tests/test_ui.py` (CLI surface test)

- [ ] **Step 1: Write the failing CLI surface test**

Add to `tests/test_ui.py`:

```python
def test_cli_reorder_flag_invokes_reorder_step(tmp_path: Path, monkeypatch):
    from photos_to_slideshow import cli

    # Build a tiny input dir with two dated photos.
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    a = make_jpeg(photos_dir / "a.jpg", "2024:01:01 09:00:00")
    b = make_jpeg(photos_dir / "b.jpg", "2024:01:02 09:00:00")
    # Audio: a placeholder file is fine — render is stubbed.
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"\xff\xfb\x90\x00")  # MPEG sync stub
    out = tmp_path / "out.mp4"

    seen_order: list = []

    def stub_reorder(photos, thumb_dir):
        # Reverse the input to prove the UI's output flows into render.
        return list(reversed(photos))

    def stub_render(frame_paths, audio_input, output, opts, **kwargs):
        # Record the filenames of frames in render order.
        seen_order.extend(p.name for p in frame_paths)
        output.write_bytes(b"fake mp4")

    # Audio module also reads the mp3 — stub it.
    from photos_to_slideshow import audio as audio_mod, render, ui
    monkeypatch.setattr(ui, "reorder_via_browser", stub_reorder)
    monkeypatch.setattr(render, "render_video_streaming", stub_render)
    monkeypatch.setattr(render, "ensure_ffmpeg_available", lambda: None)
    monkeypatch.setattr(audio_mod, "resolve_audio_source",
                        lambda p: audio_mod.AudioSource(
                            files=(audio,), total_duration=10.0))

    rc = cli.main([
        "--input", str(photos_dir),
        "--audio", str(audio),
        "--output", str(out),
        "--reorder",
    ])
    assert rc == 0
    # Frames are named 00000.png, 00001.png in render order.
    # If reorder reversed [a, b] -> [b, a], frame 00000 came from b.
    assert seen_order == ["00000.png", "00001.png"]
    # And the video file the test wrote should exist.
    assert out.exists()
```

This test verifies the wiring (the UI step is called, its output replaces `sorted_paths`, and the render sees the reordered list) without booting a real server or browser.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_ui.py::test_cli_reorder_flag_invokes_reorder_step -q`

Expected: argparse rejects the unknown `--reorder` flag, exit 2 from argparse, test fails.

- [ ] **Step 3: Add the `--reorder` flag and wire it into `_run`**

Edit `src/photos_to_slideshow/cli.py`.

In `parse_args`, add the flag (place it near `--missing-date`):

```python
    parser.add_argument("--reorder", action="store_true",
                        help="Open a browser-based UI to manually reorder "
                             "photos before rendering. Drag thumbnails and "
                             "click 'Lock & Render' to continue.")
```

In `_run`, between the existing Step 2 (sort) block and Step 3 (frame render), add the reorder step. The relevant existing block is:

```python
        sorted_paths, mtime_fallbacks = metadata.sort_by_date(all_paths)
        if mtime_fallbacks:
            print(
                f"warning: {mtime_fallbacks} of {len(sorted_paths)} photos lacked "
                f"EXIF/JSON metadata; placing them at the end of the slideshow",
                file=sys.stderr,
            )

        # Step 3: pre-render frames
```

Insert this new Step 2.5 between the `metadata.sort_by_date` block and the `# Step 3` comment:

```python
        # Step 2.5: optional reorder UI
        thumb_dir: Path | None = None
        if args.reorder:
            if len(sorted_paths) < 2:
                print("info: only one photo, skipping reorder UI",
                      file=sys.stderr)
            else:
                from . import ui  # lazy import — only paid when --reorder is on
                thumb_dir = Path(tempfile.mkdtemp(prefix="photos_to_slideshow_thumbs_"))
                surviving = ui.generate_thumbnails(sorted_paths, thumb_dir)
                if not surviving:
                    raise NoUsablePhotosError(
                        "All images failed to decode for thumbnails")
                sorted_paths = ui.reorder_via_browser(surviving, thumb_dir)
```

Extend the `finally` block at the end of `_run` to clean up `thumb_dir` too:

```python
    finally:
        # Step 6: cleanup
        if not args.keep_temp:
            resolved.cleanup()
            if frames_dir is not None and frames_dir.exists():
                shutil.rmtree(frames_dir)
            if thumb_dir is not None and thumb_dir.exists():
                shutil.rmtree(thumb_dir)
```

(The `thumb_dir = None` initialization above the `try` block makes it visible to `finally` even if the reorder step is skipped.)

- [ ] **Step 4: Run the CLI surface test**

Run: `pytest tests/test_ui.py::test_cli_reorder_flag_invokes_reorder_step -q`

Expected: PASS.

- [ ] **Step 5: Run the entire test suite**

Run: `pytest -q`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/photos_to_slideshow/cli.py tests/test_ui.py
git commit -m "feat(cli): add --reorder flag to invoke browser-based reorder UI"
```

---

## Task 9: Manual smoke test + README touch-up

**Files:**
- Modify: `README.md` (only if it documents CLI flags — if it doesn't, skip the README edit)

- [ ] **Step 1: Manual smoke test (cannot be automated — JS + browser)**

Prepare a fixture directory with ~10–20 real photos (JPEG/HEIC, mix of orientations). You can borrow any folder you have lying around. Pick or create a small MP3.

Run:

```bash
photos-to-slideshow --reorder --input <photos_dir> --audio <song.mp3> --output /tmp/smoke.mp4
```

Verify, in order:
1. `Generating thumbnails` progress bar runs to completion.
2. A browser tab opens to `http://127.0.0.1:<port>`.
3. The grid shows every photo as a thumbnail with its filename underneath.
4. You can drag a tile from any position to any other position; the others reflow with the animation.
5. Click **"Lock & Render"**. The page replaces itself with "Rendering — you can close this tab."
6. The terminal shows the `Rendering frames` progress bar and then ffmpeg output.
7. `/tmp/smoke.mp4` plays in VLC and the photo order matches the order you arranged in the browser.

If any step fails, file the issue with the reproduction details before continuing.

- [ ] **Step 2: Headless run sanity check**

Run the same command without a graphical browser available (e.g., over SSH without `-X`):

```bash
photos-to-slideshow --reorder --input <photos_dir> --audio <song.mp3> --output /tmp/headless.mp4
```

Verify:
- The terminal prints `Open this URL in a browser: http://127.0.0.1:<port>`.
- Opening that URL from another machine (with port forwarding, e.g., `ssh -L <port>:127.0.0.1:<port>`) loads the UI.
- Locking from the remote browser causes the CLI to continue rendering on the host.

- [ ] **Step 3: Ctrl-C cancel sanity check**

Run the reorder command, let the browser open, then press Ctrl-C in the terminal *without* clicking Lock.

Verify:
- The terminal exits with `interrupted` and exit code 130.
- The thumb temp directory under `/tmp/photos_to_slideshow_thumbs_*` is gone (cleanup ran).
- No `slideshow.mp4` / output file is left behind.

- [ ] **Step 4: Update README if it documents CLI flags**

Check whether `README.md` lists the existing flags. If yes, add a one-line entry for `--reorder` matching the help text in `parse_args`. If the README doesn't document flags, no changes needed.

```bash
grep -n "\-\-resolution\|\-\-transition" README.md || echo "README doesn't list flags, skip"
```

- [ ] **Step 5: Final commit (only if README was edited)**

```bash
git add README.md
git commit -m "docs(readme): document --reorder flag"
```

If no README change was needed, this task is complete without a commit.

---

## Notes for the implementing engineer

- **Lazy import:** The `from . import ui` line inside the `if args.reorder:` branch in `cli._run` is deliberate. Without `--reorder`, none of the UI module loads, so the default CLI path stays as fast and dep-free as today.
- **`importlib.resources.files`:** Used instead of `__file__`-relative paths so it works both in dev (editable install) and when installed as a wheel. The empty `static/__init__.py` makes the `static` directory a subpackage so `files("photos_to_slideshow.static")` resolves.
- **Ephemeral port:** Binding to port 0 lets the OS pick a free port. Always read it back via `server.server_address[1]` before printing or opening the browser.
- **Thread safety:** `_ReorderServer.final_order` and `done_event` are written by the request handler thread and read by the main thread. `threading.Event.wait()` and `.set()` are the synchronization primitive; the `final_order` write must happen-before `done_event.set()`, which the code in Task 5 does correctly.
- **No SortableJS tests:** the JS layer is covered by the manual smoke test in Task 9. Adding Selenium/Playwright would balloon the dep tree against an explicit "lightweight" goal.
