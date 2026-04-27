"""Command-line entry point for photos-to-slideshow."""

import argparse
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="photos-to-slideshow",
        description="Turn a folder/zip of photos plus an MP3 into an MP4 slideshow.",
    )
    parser.add_argument("--input", type=Path, required=True,
                        help="Directory or .zip of photos")
    parser.add_argument("--audio", type=Path, required=True,
                        help="MP3 soundtrack")
    parser.add_argument("--output", type=Path, default=Path("slideshow.mp4"),
                        help="Output MP4 path (default: ./slideshow.mp4)")
    parser.add_argument("--resolution", default="1920x1080",
                        help="WxH (default: 1920x1080)")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--fit", choices=["blur", "letterbox", "crop"], default="blur",
                        help="(only 'blur' is implemented in v0.1)")
    parser.add_argument("--transition", choices=["crossfade", "cut", "fade-black"],
                        default="crossfade")
    parser.add_argument("--transition-duration", type=float, default=0.5,
                        dest="transition_duration")
    parser.add_argument("--audio-fade", type=float, default=1.0, dest="audio_fade")
    parser.add_argument("--end-fade", type=float, default=1.0, dest="end_fade")
    parser.add_argument("--missing-date", choices=["mtime", "filename", "skip"],
                        default="mtime", dest="missing_date",
                        help="(only 'mtime' is implemented in v0.1)")
    parser.add_argument("--keep-temp", action="store_true", dest="keep_temp")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--quiet", "-q", action="store_true")
    return parser.parse_args(argv)


def parse_resolution(s: str) -> tuple[int, int]:
    try:
        w, h = s.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError) as e:
        from .errors import UsageError
        raise UsageError(f"Invalid --resolution {s!r}: expected WxH like 1920x1080") from e
