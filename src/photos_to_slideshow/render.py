"""ffmpeg command construction and invocation."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import FFmpegError


@dataclass(frozen=True)
class RenderOptions:
    slide_duration: float
    xfade: float          # 0 means hard cuts via concat
    fps: int
    canvas_size: tuple[int, int]
    audio_fade: float     # seconds for in and out
    end_fade: float       # video fade-to-black at end


def _video_filter_xfade(n_frames: int, opts: RenderOptions) -> tuple[str, float]:
    """Build the xfade chain. Returns (filter_string, total_video_seconds).

    Each input frame is shown for slide_duration s. Frame i begins crossfading
    into frame i+1 at offset = (i+1)*slide_duration - (i+1)*xfade.
    Total length = N*D - (N-1)*X.
    """
    D = opts.slide_duration
    X = opts.xfade
    parts: list[str] = []
    prev = "[0:v]"
    for i in range(1, n_frames):
        offset = i * D - i * X
        out_label = f"[v{i}]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={X}:offset={offset:.6f}{out_label}"
        )
        prev = out_label
    total = n_frames * D - (n_frames - 1) * X
    # Always end the chain with a [vout] label, optionally with end fade.
    if opts.end_fade > 0:
        parts.append(
            f"{prev}fade=t=out:st={(total - opts.end_fade):.6f}:d={opts.end_fade}[vout]"
        )
    else:
        parts.append(f"{prev}null[vout]")
    return ";".join(parts), total


def _video_filter_concat(n_frames: int, opts: RenderOptions) -> tuple[str, float]:
    """Build a concat-based filter chain (hard cuts)."""
    inputs = "".join(f"[{i}:v]" for i in range(n_frames))
    parts = [f"{inputs}concat=n={n_frames}:v=1:a=0[vcat]"]
    total = n_frames * opts.slide_duration
    if opts.end_fade > 0:
        parts.append(
            f"[vcat]fade=t=out:st={(total - opts.end_fade):.6f}:d={opts.end_fade}[vout]"
        )
    else:
        parts.append("[vcat]null[vout]")
    return ";".join(parts), total


def _audio_filter(audio_input_index: int, total_video: float, opts: RenderOptions) -> str:
    """Build the audio filter: trim to video length plus optional fade in/out."""
    parts = [f"[{audio_input_index}:a]atrim=duration={total_video:.6f}"]
    if opts.audio_fade > 0:
        parts.append(f"afade=t=in:st=0:d={opts.audio_fade}")
        parts.append(
            f"afade=t=out:st={(total_video - opts.audio_fade):.6f}:d={opts.audio_fade}"
        )
    return ",".join(parts) + "[aout]"


def build_ffmpeg_command(
    frames: list[Path],
    audio: Path,
    output: Path,
    opts: RenderOptions,
) -> list[str]:
    """Construct the full ffmpeg argv. Pure function — no execution."""
    if not frames:
        raise ValueError("frames must be non-empty")

    argv: list[str] = ["ffmpeg", "-y"]

    # One image input per frame: -loop 1 -t D -i frame.png
    for f in frames:
        argv += ["-loop", "1", "-t", f"{opts.slide_duration:.6f}", "-i", str(f)]

    # Audio input
    audio_idx = len(frames)
    argv += ["-i", str(audio)]

    # Build filter graph
    if opts.xfade > 0 and len(frames) > 1:
        v_filter, total = _video_filter_xfade(len(frames), opts)
    else:
        v_filter, total = _video_filter_concat(len(frames), opts)
    a_filter = _audio_filter(audio_idx, total, opts)
    filter_complex = f"{v_filter};{a_filter}"

    argv += ["-filter_complex", filter_complex]
    argv += ["-map", "[vout]", "-map", "[aout]"]
    argv += [
        "-r", str(opts.fps),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "medium",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-movflags", "+faststart",
        str(output),
    ]
    return argv


def run_ffmpeg(argv: list[str], verbose: bool = False) -> None:
    """Run ffmpeg, streaming stderr if verbose, raising FFmpegError on failure."""
    stderr = None if verbose else subprocess.PIPE
    proc = subprocess.run(argv, stderr=stderr, text=True)
    if proc.returncode != 0:
        msg = proc.stderr or "(no stderr captured; use --verbose to see output)"
        raise FFmpegError(proc.returncode, msg)


def ensure_ffmpeg_available() -> None:
    """Raise UsageError if ffmpeg is not on PATH."""
    from shutil import which
    from .errors import UsageError
    if which("ffmpeg") is None:
        raise UsageError(
            "ffmpeg not found on PATH. Install with: sudo apt install -y ffmpeg"
        )
