"""Audio inspection and slide-timing math."""

from dataclasses import dataclass
from pathlib import Path

from mutagen.mp3 import MP3, HeaderNotFoundError

from .errors import UsageError


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
