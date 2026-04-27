# photos-to-slideshow

A Linux CLI that turns a folder (or zip) of photos plus an MP3 into an MP4
slideshow video. Photos are sorted by EXIF date taken; mixed orientations
are handled with a blurred-background fill so nothing gets cropped.

Built for school year-end recap videos played in VLC on Windows laptops.

## Install

System dependency:
```bash
sudo apt install -y ffmpeg
```

Python install (recommended in a venv):
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Running it

After install, the `photos-to-slideshow` script lives at `.venv/bin/photos-to-slideshow`.
Either activate the venv first, or invoke it by full path.

Activate the venv (then `photos-to-slideshow` is on your PATH for this shell):
```bash
source .venv/bin/activate
photos-to-slideshow --input ./photos --audio ./song.mp3
```

Or invoke without activating:
```bash
.venv/bin/photos-to-slideshow --input ./photos --audio ./song.mp3
```

If you want it available globally (no venv activation needed), install via
[`pipx`](https://pipx.pypa.io) instead of pip:
```bash
pipx install /path/to/photos_to_slideshow
photos-to-slideshow --input ./photos --audio ./song.mp3
```

## Usage

Minimal:
```bash
photos-to-slideshow --input ./photos --audio ./song.mp3
```

Or with a zip:
```bash
photos-to-slideshow --input photos.zip --audio song.mp3 --output recap.mp4
```

The slideshow length is auto-fit to the song length: each photo is shown
for `(audio_duration + (N-1) * crossfade) / N` seconds.

### Common flags

| Flag | Default | Notes |
|---|---|---|
| `--input` | (required) | directory or `.zip` of photos |
| `--audio` | (required) | `.mp3` soundtrack |
| `--output` | `./slideshow.mp4` | output path |
| `--resolution` | `1920x1080` | output frame size |
| `--fps` | `30` | output framerate |
| `--transition` | `crossfade` | `crossfade` \| `cut` \| `fade-black` |
| `--transition-duration` | `0.5` | crossfade duration in seconds |
| `--audio-fade` | `1.0` | fade-in/out duration; `0` to disable |
| `--end-fade` | `1.0` | video fade-to-black at end |
| `--keep-temp` | off | keep working temp dirs (debugging) |
| `--verbose` / `-v` | off | show ffmpeg output |
| `--quiet` / `-q` | off | suppress progress bar |

## Supported formats

Input: `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`. Photos missing EXIF date use
file mtime as the fallback; a summary is printed at the end.

Output: H.264 (yuv420p) + AAC in MP4. Plays in VLC on Windows and any modern player.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                # all tests
.venv/bin/pytest -m "not slow"  # skip the e2e ffmpeg test
```
