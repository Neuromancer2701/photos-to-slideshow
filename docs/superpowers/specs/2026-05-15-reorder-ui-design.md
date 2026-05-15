# Reorder UI — Design

**Date:** 2026-05-15
**Status:** Approved (awaiting implementation plan)

## Purpose

Add an optional `--reorder` flag that opens a lightweight browser-based UI showing thumbnails of all photos in their default chronological order. The user can drag-and-drop tiles to reorder them, then click **"Lock & Render"** to commit the order and continue into the existing render pipeline.

The default (no-flag) behavior is unchanged: photos are sorted by `metadata.sort_by_date` and rendered without any UI.

## Scope

**In scope:**
- Reorder photos via drag-and-drop in the browser.
- Lock the chosen order and feed it into the existing render pipeline.
- Zero new Python dependencies.
- Works offline (no CDN at runtime).

**Out of scope (deliberately deferred):**
- Skip/exclude photos from the slideshow.
- Edit dates per photo.
- Metadata badges (date source) on tiles.
- Persisting the reordered manifest between runs.

## User experience

1. User runs `photos-to-slideshow --reorder --input photos/ --audio song.mp3`.
2. CLI scans + sorts as today, then prints a progress bar while it generates 240px thumbnails.
3. The browser opens to `http://127.0.0.1:<port>`. If no browser is available, the URL is printed to stderr and the CLI keeps blocking.
4. The page shows a responsive grid of thumbnails, each labeled with its filename. A sticky **"Lock & Render"** button is in the top-right.
5. User drags tiles to reorder. Drop target is highlighted.
6. User clicks **"Lock & Render"**. The page shows a "Rendering — you can close this tab" overlay.
7. The CLI continues into frame rendering and ffmpeg encoding exactly as it does today.

To cancel, the user presses Ctrl-C in the terminal; the CLI exits 130 and cleans up temp dirs.

## Architecture

### Integration point

The UI slots between Step 2 (sort) and Step 3 (frame render) in `cli.py:_run`:

```
Step 1: resolve input
Step 2: scan + sort_by_date          → sorted_paths
Step 2.5: reorder UI (new, opt-in)   → reordered_paths   ← only if --reorder
Step 3: pre-render frames
Step 4: timing math
Step 5: render video
Step 6: cleanup
```

When `--reorder` is not passed, none of the UI code is imported — the `ui` module is lazy-imported inside the `if args.reorder:` branch. The default path stays exactly as fast and dep-free as today.

### New file layout

```
src/photos_to_slideshow/
  ui.py                          # new module (~250–350 LOC)
  static/
    index.html                   # new (~120 LOC)
    sortable.min.js              # new, vendored (~45KB)
```

### Module: `ui.py`

Four units, each small and independently testable:

- `generate_thumbnails(paths, out_dir, max_dim=240) -> list[Path]`
  Uses `images.decode_image` (already EXIF-rotates) + Pillow `thumbnail()`. Writes `0.jpg`, `1.jpg`, …, returning the thumb-path list aligned by index with the input. Shows a `tqdm` bar mirroring the frame-render bar in `cli.py:119`. Unreadable images are skipped with a stderr warning (same posture as the frame loop).

- `reorder_via_browser(paths, thumb_dir) -> list[Path]`
  Public entry point. Boots the server on `127.0.0.1:0`, opens the browser, blocks on a `threading.Event` until `POST /lock` arrives. Returns the reordered photo paths. If the user Ctrl-C's the terminal instead of locking, the `KeyboardInterrupt` propagates up to `main` (exit 130).

- `_ReorderHandler(BaseHTTPRequestHandler)`
  Three routes:
  - `GET /` — reads `static/index.html`, injects `window.PHOTOS = [{i, name}, ...]` into a `<script>` tag, returns the page.
  - `GET /thumb/<i>` — streams `thumb_dir/<i>.jpg`. 404 if `<i>` is out of range.
  - `POST /lock` — parses JSON `{"order": [<original_index>, ...]}`, validates it's a permutation of `0..N-1`, stores it on the server instance, sets the done-event, returns `{"ok": true}`. Returns 400 on bad input.

- `_serve_until_locked(server, done_event)`
  Runs `serve_forever` in a daemon thread, waits on `done_event`, then `server.shutdown()`.

### Frontend: `static/index.html`

Single-page app, vanilla JS:

- Header with photo count and sticky **"Lock & Render"** button.
- Responsive CSS grid of tiles. Each tile = `<div data-photo-id="<i>"><img src="/thumb/<i>" loading="lazy"><span>{filename}</span></div>`.
- SortableJS initialized on the grid container. DOM order *is* the current order.
- On button click: `[...grid.children].map(el => +el.dataset.photoId)` → POST `/lock` with `{order}`. On 200, show "Rendering — you can close this tab" overlay. On 400, show inline error banner and keep the page interactive.

### Vendored: `static/sortable.min.js`

SortableJS UMD build, committed verbatim with an attribution comment at the top noting source and version. No CDN at runtime.

## Data flow

**Server state (set once at server construction, immutable for session):**
- `photos: list[Path]` — the photos that survived thumbnail generation, in post-`sort_by_date` order. If any thumbnails failed, the corresponding photos are dropped *before* the server starts so indices `0..N-1` are dense.
- `thumb_dir: Path`
- `done_event: threading.Event`
- `final_order: list[int] | None` — populated by `POST /lock`.

**Wire format:**
- `GET /` injects `window.PHOTOS = [{i: 0, name: "IMG_001.jpg"}, ...]`. `i` is the stable ID; `name` is display-only.
- `GET /thumb/<i>` — `<i>` is the original index, never changes per drag.
- `POST /lock` body: `{"order": [<original_index>, ...]}` — a permutation of `0..N-1`.

**Client state:** the DOM order of tiles is the current order. No separate JS list.

**End-to-end flow:**

1. `_run` produces `sorted_paths` from `metadata.sort_by_date`.
2. `generate_thumbnails(sorted_paths, thumb_dir)` writes `0.jpg..N-1.jpg`.
3. `reorder_via_browser` boots server, opens browser, blocks on `done_event`.
4. Browser loads `/`, fetches thumbs lazily as the grid scrolls, user drags tiles.
5. User clicks **"Lock & Render"** → JS POSTs the order → server validates → stores `final_order` → sets `done_event` → returns `200 {"ok": true}` → JS shows overlay.
6. Server thread shuts down. `reorder_via_browser` returns `[photos[i] for i in final_order]`.
7. `_run` swaps that list into `sorted_paths` and continues into Step 3 unchanged.

## Error handling

| Failure mode | Behavior |
|---|---|
| Port allocation fails (`OSError` on bind) | Re-raise as `SlideshowError("could not bind local server: …")`. Exit 1. |
| `webbrowser.open()` returns False | Print the URL to stderr; keep blocking on `done_event`. Supports headless/SSH use. |
| User closes the tab without locking | No server-side detection. Hint printed at startup: `Reorder UI: drag thumbnails, click "Lock & Render". Ctrl-C here to cancel.` Ctrl-C → exit 130. |
| `POST /lock` body malformed or non-permutation | Server returns `400 {"error": "..."}`. JS shows inline error banner; page stays interactive so user can retry. Defensive — the UI itself can't generate a bad order. |
| Thumbnail generation fails for one photo | Print warning, skip the photo, continue. Skipped photos are dropped from `photos` before server start. |
| All thumbnails fail | Raise `NoUsablePhotosError` (existing). Exit 2. |
| Only one photo (or zero) | Zero: existing `NoUsablePhotosError` fires before UI step. One: skip the UI entirely with `info: only one photo, skipping reorder UI`. |

The `finally` block in `_run` is extended to clean up `thumb_dir` alongside `frames_dir`, gated on `--keep-temp`.

## CLI surface

New flag:

```
--reorder
    Open a browser-based UI to manually reorder photos before rendering.
    The default chronological order is shown first; drag-and-drop to
    reorder, then click "Lock & Render" to continue.
```

No other CLI changes. No new dependencies in `pyproject.toml`.

## Testing

One new file: `tests/test_ui.py`. No headless-browser dep — the Python side is tested via real HTTP on a loopback server. The JS is covered by one documented manual smoke test.

**Unit-ish (fast, no browser):**
- `test_generate_thumbnails_writes_one_jpeg_per_photo`
- `test_generate_thumbnails_skips_unreadable_image`
- `test_generate_thumbnails_preserves_index_alignment`

**HTTP integration (boot real server on `127.0.0.1:0`, hit via `urllib`):**
- `test_get_root_serves_html_with_injected_photos`
- `test_get_thumb_returns_jpeg`
- `test_get_thumb_out_of_range_returns_404`
- `test_post_lock_with_valid_permutation_returns_ok_and_sets_event`
- `test_post_lock_with_non_permutation_returns_400`
- `test_post_lock_with_wrong_length_returns_400`
- `test_post_lock_with_malformed_json_returns_400`

**Full integration (no browser):**
- `test_reorder_via_browser_returns_permuted_paths` — start `reorder_via_browser` in a thread, simulate the JS client via `urllib`, assert returned order matches the POST'd permutation.

**CLI surface:**
- `test_cli_reorder_flag_invokes_reorder_step` — monkeypatch `ui.reorder_via_browser` and `render.render_video_streaming` to stubs, run `_run`, assert the rendered pipeline sees the reordered list.

**Manual smoke (documented, not automated):**
Run `photos-to-slideshow --reorder` against ~20 fixture photos. Verify browser opens, drag works, "Lock & Render" closes the tab, video renders in the new order.

The `_make_jpeg` helper currently in `tests/test_metadata.py` will move to `tests/conftest.py` so both test modules can use it.

## Non-goals & explicit deferrals

- No persistent reorder manifest. Each `--reorder` session is fresh.
- No mobile/touch testing. Desktop browser only.
- No authentication on the loopback server. It binds to `127.0.0.1` only; assumed safe for a single-user CLI.
- No live preview of the rendered slideshow inside the UI.
