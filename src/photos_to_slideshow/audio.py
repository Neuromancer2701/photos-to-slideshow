"""Audio inspection and slide-timing math."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from mutagen.mp3 import MP3, HeaderNotFoundError

from .errors import FFmpegError, UsageError


@dataclass(frozen=True)
class SlideTiming:
    slide_duration: float  # seconds each slide is on screen
    xfade: float           # crossfade duration (0 means hard cut)
    downgraded_to_cut: bool
    extended_for_min: bool = False  # True if min_slide forced a longer video


def _total(slide: float, n: int, xfade: float) -> float:
    return n * slide - (n - 1) * xfade if n > 1 else slide


def compute_timing(
    audio_duration: float,
    n_photos: int,
    xfade: float,
    min_slide: float = 0.0,
) -> SlideTiming:
    """Compute per-slide duration.

    Default mode (min_slide=0): auto-fit so the slideshow ends with the audio.
    With N frames of duration D and (N-1) crossfades of length X overlapping
    adjacent frames, total video length = N*D - (N-1)*X.
    Solving for D: D = (audio_duration + (N-1)*X) / N.

    If the resulting slide is too short to host a crossfade (D < 2*X), we
    auto-downgrade to hard cuts and recompute D = audio_duration / N.

    If min_slide > 0 and the auto-fit slide would be shorter than min_slide,
    the slide is set to min_slide instead. This makes the video longer than
    one play of the audio; the caller is expected to loop the audio to fill.
    """
    if n_photos < 1:
        raise ValueError("n_photos must be >= 1")

    if n_photos == 1:
        return SlideTiming(
            slide_duration=max(audio_duration, min_slide),
            xfade=0.0,
            downgraded_to_cut=False,
            extended_for_min=min_slide > audio_duration,
        )

    if xfade <= 0:
        natural = audio_duration / n_photos
        if min_slide > natural:
            return SlideTiming(min_slide, 0.0, downgraded_to_cut=False, extended_for_min=True)
        return SlideTiming(natural, 0.0, downgraded_to_cut=False)

    natural = (audio_duration + (n_photos - 1) * xfade) / n_photos
    if min_slide > natural:
        # Extend slide to min_slide; keep crossfade unless it doesn't fit.
        if min_slide < 2 * xfade:
            return SlideTiming(min_slide, 0.0, downgraded_to_cut=True, extended_for_min=True)
        return SlideTiming(min_slide, xfade, downgraded_to_cut=False, extended_for_min=True)

    if natural < 2 * xfade:
        return SlideTiming(audio_duration / n_photos, 0.0, downgraded_to_cut=True)
    return SlideTiming(natural, xfade, downgraded_to_cut=False)


def read_audio_duration(path: Path) -> float:
    """Return MP3 duration in seconds. Raises UsageError on bad/missing file."""
    if not path.exists():
        raise UsageError(f"Audio file not found: {path}")
    try:
        mp3 = MP3(str(path))
    except HeaderNotFoundError as e:
        raise UsageError(f"Not a valid MP3: {path}") from e
    if mp3.info is None or mp3.info.length <= 0:
        raise UsageError(f"Could not determine audio duration: {path}")
    return float(mp3.info.length)


@dataclass(frozen=True)
class AudioSource:
    """One or more audio files plus their summed duration."""
    files: tuple[Path, ...]
    total_duration: float

    @property
    def is_playlist(self) -> bool:
        return len(self.files) > 1


def _natural_sort_key(name: str) -> tuple:
    """Key that sorts 'track2' before 'track10' (digits compared as ints)."""
    return tuple(
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", name.lower())
    )


def resolve_audio_source(path: Path) -> AudioSource:
    """Resolve --audio: a single .mp3 file, or a directory of .mp3 files.

    For a directory, files are taken in natural-sort order (track2 < track10)
    and their durations summed. Non-mp3 entries and subdirectories are
    ignored. Empty directories raise UsageError.
    """
    if path.is_dir():
        mp3s = [
            p for p in path.iterdir()
            if p.is_file() and p.suffix.lower() == ".mp3"
        ]
        if not mp3s:
            raise UsageError(f"No .mp3 files found in directory: {path}")
        mp3s.sort(key=lambda p: _natural_sort_key(p.name))
        total = sum(read_audio_duration(p) for p in mp3s)
        return AudioSource(tuple(mp3s), total)

    if not path.exists():
        raise UsageError(f"Audio path not found: {path}")
    if path.suffix.lower() != ".mp3":
        raise UsageError(
            f"Audio must be an .mp3 file or a directory of .mp3 files: {path}"
        )
    return AudioSource((path,), read_audio_duration(path))


def write_concat_playlist(files: list[Path], dest: Path) -> None:
    """Write an ffmpeg concat-demuxer playlist of absolute paths.

    The concat demuxer expects ``file 'PATH'`` lines. Single quotes inside
    a path are escaped by closing, escaping the quote, and reopening:
    ``'\\''``.
    """
    lines = []
    for f in files:
        abs_str = str(f.resolve())
        escaped = abs_str.replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    dest.write_text("\n".join(lines) + "\n")


def concat_mp3_files(files: list[Path], dest: Path) -> None:
    """Concatenate MP3s into a single file using ``ffmpeg -f concat -c copy``.

    Stream-copies the audio (no re-encode), so this is fast and lossless.
    The resulting file is a normal MP3 that can be looped with
    ``-stream_loop -1`` -- which the concat demuxer itself does not support.
    """
    if not files:
        raise ValueError("concat_mp3_files requires at least one file")
    playlist = dest.with_name(dest.name + ".txt")
    try:
        write_concat_playlist(files, playlist)
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(playlist),
                "-c", "copy", str(dest),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            raise FFmpegError(result.returncode, result.stderr.decode(errors="replace"))
    finally:
        if playlist.exists():
            playlist.unlink()
