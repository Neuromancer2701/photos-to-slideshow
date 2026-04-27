# photos-to-slideshow — Design

**Date:** 2026-04-26
**Status:** Approved (awaiting implementation plan)

## Purpose

A reusable Ubuntu CLI utility that turns a folder (or zip) of photos plus one MP3 into an MP4 slideshow video. Primary user: a school producing year-end recap videos shown via VLC on Windows laptops. Will be run many times across school years and events, so ergonomics and reliability matter.

## Inputs & Output

**Inputs:**
- Photos: a directory or zip archive containing `.jpg`, `.jpeg`, `.heic`, `.heif`, or `.png` files. Nested folders allowed. Non-image files are ignored.
- Audio: a single `.mp3` file used as the soundtrack.

**Output:**
- An H.264 (yuv420p) + AAC MP4 file, default 1920×1080 @ 30 fps. Plays in VLC on Windows and effectively any modern player.

## Behavior

- Photos are sorted by EXIF `DateTimeOriginal` ascending. If a photo lacks that tag, fall back to file mtime. Ties broken by filename. A summary listing how many photos used the fallback is printed at the end.
- Slide duration is auto-fit to the audio so the slideshow ends exactly when the song ends. With `N` photos and crossfade duration `X`, per-slide duration `D = (audio_duration + (N-1) × X) / N`.
- Each photo is shown full-frame using **blur-fill**: the photo is scaled to fit inside 1920×1080 with no cropping, and the empty bars on the sides/top are filled with a blurred copy of the same photo. Mixed portrait/landscape orientations are handled uniformly.
- Default transition between slides is a **0.5 s crossfade**. Configurable via `--transition` (`crossfade`, `cut`, `fade-black`) and `--transition-duration`.
- Audio fades in for 1.0 s at start and fades out for 1.0 s at end.
- Video fades to black for 1.0 s at the end (no title card at start).
- Progress bar shown during the slow image-prep phase.

## Architecture

**Stack:** Python 3 + ffmpeg (system binary, installed via `apt install ffmpeg`).

- Python handles HEIC decoding, EXIF parsing, blur-fill compositing, and orchestration.
- ffmpeg handles video assembly: crossfades (`xfade` filter), audio mux, encoding.

**Why this split:** ffmpeg is the right tool for video encoding and is rock-solid; doing crossfades + audio + scaling inside one ffmpeg pass is reliable. Python handles the parts ffmpeg is bad at.

**Key Python libraries:**
- `Pillow` — image decoding, resizing, blur compositing
- `pillow-heif` — HEIC/HEIF support as a Pillow plugin
- `mutagen` — MP3 duration without invoking ffprobe
- `tqdm` — progress bar

## Pipeline

1. **Resolve input.** If `--input` is a zip, extract to a tool-created temp dir. If a directory, use it as-is (never modified or deleted by the tool).
2. **Scan & sort.** Recursively find supported image files. Read EXIF `DateTimeOriginal` for each; fall back to mtime if absent. Sort ascending; tiebreak by filename. Collect warnings for fallback usage.
3. **Pre-render frames.** For each photo: decode → resize to fit 1920×1080 → composite onto blurred-background canvas → save as `0001.png`, `0002.png`, … in a tool-created temp dir. tqdm progress bar.
4. **Compute timing.** Read MP3 duration; compute per-slide duration. Sanity checks:
   - If `slide_duration < 2 × xfade`, warn and auto-downgrade to `--transition cut`.
   - If `audio_fade × 2 > audio_duration`, clamp `audio_fade = audio_duration / 4` and warn.
5. **Render video.** Single ffmpeg invocation: chained `xfade` filters between PNG frames, `-i` the MP3, apply `afade` in/out, apply `fade=out` for `--end-fade` seconds at the tail of the video stream, encode H.264 (`libx264`, yuv420p) + AAC into MP4.
6. **Cleanup.** Delete only tool-created temp dirs (the zip-extraction dir if any, and the PNG frames dir) unless `--keep-temp` was passed. The user's input directory is never touched.

## CLI Surface

```
photos-to-slideshow \
  --input PATH                  # zip file or directory (required)
  --audio PATH                  # mp3 file (required)
  --output PATH                 # default: ./slideshow.mp4

  --resolution WxH              # default: 1920x1080
  --fps N                       # default: 30
  --fit MODE                    # blur|letterbox|crop  (default: blur)

  --transition MODE             # crossfade|cut|fade-black  (default: crossfade)
  --transition-duration SEC     # default: 0.5

  --audio-fade SEC              # in/out duration (default: 1.0; 0 disables)
  --end-fade SEC                # fade-to-black at end (default: 1.0; 0 disables)

  --missing-date MODE           # mtime|filename|skip  (default: mtime)

  --keep-temp                   # don't delete temp dir (debugging)
  --verbose / -v                # show ffmpeg output
  --quiet / -q                  # suppress progress bar
```

**Required flags:** only `--input` and `--audio`. Typical use: `photos-to-slideshow --input photos.zip --audio song.mp3`.

**Exit codes:** `0` success, `1` usage / input error, `2` no usable photos, `3` ffmpeg failure, `130` user interrupt.

## Module Breakdown

```
photos_to_slideshow/
├── pyproject.toml
├── README.md
├── src/photos_to_slideshow/
│   ├── __init__.py
│   ├── cli.py          # argparse + orchestration
│   ├── inputs.py       # resolve zip/dir → list of image paths; temp dir mgmt
│   ├── metadata.py     # EXIF date extraction, sort, missing-date fallback
│   ├── images.py       # decode (HEIC-aware), resize, blur-fill compositor
│   ├── audio.py        # MP3 duration, timing math
│   ├── render.py       # ffmpeg command construction + invocation
│   └── errors.py       # typed exceptions for clean exit-code mapping
└── tests/
    ├── test_metadata.py
    ├── test_audio.py
    ├── test_images.py
    ├── test_inputs.py
    └── test_e2e.py
```

**Boundary contracts:**
- `inputs.resolve(path) → list[Path]` — caller doesn't care if it was a zip
- `metadata.sort_by_date(paths, fallback) → (sorted_paths, warnings)` — pure function
- `audio.compute_timing(audio_dur, n_photos, xfade) → SlideTiming` — pure math
- `images.render_frame(src_path, canvas_size, fit_mode) → PIL.Image` — single-photo, no side effects
- `render.build_video(frame_paths, audio_path, timing, output_path, opts)` — only place that shells out to ffmpeg

This isolates slow code (image prep, ffmpeg) from logic code (sorting, math), so unit tests stay fast and the slow integration test is one well-defined e2e.

## Edge Cases & Error Handling

| Situation | Behavior |
|---|---|
| Input is a zip with nested folders | Recursively collect supported images |
| Input dir mixes images with junk (`.DS_Store`, PDFs, videos) | Filter to supported extensions only |
| Zero usable photos found | Exit 2 with clear message |
| Single photo | Render anyway; no transitions; `slide_dur = audio_dur` |
| HEIC file fails to decode | Warn, skip, continue |
| Photo missing EXIF date | Use mtime; print summary at end |
| All photos missing EXIF | Proceed with mtime; single warning |
| MP3 unreadable / corrupt | Exit 1 with mutagen error |
| `slide_dur < 2 × xfade` | Warn, auto-downgrade to `--transition cut` |
| `audio_fade × 2 > audio_dur` (very short song) | Clamp `audio_fade` to `audio_dur / 4`; warn |
| `slide_dur > 30s` | Warn (probable user mistake), continue |
| Mixed orientations | Handled by blur-fill; no special case |
| Output path exists | Overwrite |
| Output dir doesn't exist | Create it |
| ffmpeg not installed | Detect at startup; fail fast with `apt install ffmpeg` hint |
| Disk full / write fails mid-render | ffmpeg exit code propagates; partial mp4 deleted |
| User Ctrl-C | Trap SIGINT, clean up temp dir, exit 130 |
| Two photos with identical timestamp | Stable secondary sort by filename |

**Logging convention:** warnings and progress to stderr; only the final output path printed to stdout, so the tool is pipeable.

## Testing

**Unit tests (fast, no ffmpeg):**
- `test_metadata.py` — EXIF parsing happy path, missing-EXIF fallback to mtime, identical-timestamp tiebreaker, all sort modes
- `test_audio.py` — timing math: `compute_timing(audio_dur=180, n=60, xfade=0.5)` produces expected slide duration; edge cases (`n=1`, `xfade ≥ slide_dur` triggers cut downgrade)
- `test_inputs.py` — zip extraction, nested dirs, junk-file filtering, empty input
- `test_images.py` — blur-fill produces a 1920×1080 RGB image regardless of source orientation; HEIC decodes; corrupt file raises typed exception

**Integration test (slow, needs ffmpeg):**
- `test_e2e.py` — fixture: 3 small JPEGs (one portrait, two landscape) + a 6-second MP3 → run full CLI → assert:
  - `slideshow.mp4` exists
  - duration is 6.0 s ± 0.1 s
  - video stream is 1920×1080 H.264; audio is AAC

Marked with `@pytest.mark.slow` so unit tests stay quick during dev.

**Manual smoke test:** README documents a one-liner using a small `examples/` folder so a human can spot-check visual output occasionally.

## Deferred / Out of Scope

- Title card with text (would need font rendering); easy to add later as `--title-text "..."`
- Ken Burns pan/zoom effect; possible v2 via `--fit kenburns`
- Multiple audio tracks or playlist support
- Live preview / GUI
- Output formats other than MP4
