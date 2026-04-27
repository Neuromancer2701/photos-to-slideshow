"""Audio inspection and slide-timing math."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SlideTiming:
    slide_duration: float  # seconds each slide is on screen
    xfade: float           # crossfade duration (0 means hard cut)
    downgraded_to_cut: bool


def compute_timing(audio_duration: float, n_photos: int, xfade: float) -> SlideTiming:
    """Compute per-slide duration so the slideshow ends with the audio.

    With N frames of duration D and (N-1) crossfades of length X overlapping
    adjacent frames, total video length = N*D - (N-1)*X.
    Solving for D: D = (audio_duration + (N-1)*X) / N.

    If the resulting slide is too short to host a crossfade (D < 2*X), we
    auto-downgrade to hard cuts and recompute D = audio_duration / N.
    """
    if n_photos < 1:
        raise ValueError("n_photos must be >= 1")

    if n_photos == 1:
        return SlideTiming(slide_duration=audio_duration, xfade=0.0, downgraded_to_cut=False)

    if xfade <= 0:
        return SlideTiming(
            slide_duration=audio_duration / n_photos,
            xfade=0.0,
            downgraded_to_cut=False,
        )

    slide = (audio_duration + (n_photos - 1) * xfade) / n_photos
    if slide < 2 * xfade:
        return SlideTiming(
            slide_duration=audio_duration / n_photos,
            xfade=0.0,
            downgraded_to_cut=True,
        )
    return SlideTiming(slide_duration=slide, xfade=xfade, downgraded_to_cut=False)
