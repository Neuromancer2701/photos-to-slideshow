"""Unit + HTTP integration tests for the reorder UI module."""

import contextlib
import json
import threading
import urllib.error
import urllib.request
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


class _StubBrowser:
    def open(self, url: str) -> bool:
        return True


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
        # Poll the dict the wrapped _build_server populates with the URL.
        import time
        for _ in range(200):
            url = posted.get("url")
            if url:
                _post_json(url + "/lock", {"order": [2, 0, 1]})
                return
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
