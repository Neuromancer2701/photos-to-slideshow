"""Video assembly: pre-rendered frames + audio -> MP4.

Streams raw RGB frames into ffmpeg via stdin so memory stays flat regardless
of photo count. The previous approach (one -i per photo) opened a decoder
per input and held the entire xfade filter chain in RAM, which OOM'd at a
few hundred photos.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from tqdm import tqdm

from .errors import FFmpegError


@dataclass(frozen=True)
class RenderOptions:
    slide_duration: float
    xfade: float          # 0 means hard cuts
    fps: int
    canvas_size: tuple[int, int]
    audio_fade: float     # seconds for in and out
    end_fade: float       # video fade-to-black at end


@dataclass(frozen=True)
class Segment:
    """A single time-segment of the slideshow timeline."""
    kind: str               # "solo" or "xfade"
    slide_a: int            # solo: visible slide; xfade: fading-out slide
    slide_b: int | None     # xfade: fading-in slide; else None
    start: float            # seconds from video start
    length: float           # seconds


def compute_segments(n_frames: int, slide_duration: float, xfade: float) -> list[Segment]:
    """Decompose the timeline into solo and crossfade segments.

    First/last slides have one fade neighbor, so solo length = D - X.
    Middle slides have two, so solo length = D - 2X.
    With xfade <= 0, every solo length = D and there are no xfade segments.
    Total length = N*D - (N-1)*X.
    """
    if n_frames < 1:
        raise ValueError("n_frames must be >= 1")

    segments: list[Segment] = []
    t = 0.0

    if xfade <= 0 or n_frames == 1:
        for k in range(n_frames):
            segments.append(Segment("solo", k, None, t, slide_duration))
            t += slide_duration
        return segments

    for k in range(n_frames):
        solo_len = slide_duration - xfade if k in (0, n_frames - 1) else slide_duration - 2 * xfade
        segments.append(Segment("solo", k, None, t, solo_len))
        t += solo_len
        if k < n_frames - 1:
            segments.append(Segment("xfade", k, k + 1, t, xfade))
            t += xfade

    return segments


def total_video_duration(segments: list[Segment]) -> float:
    if not segments:
        return 0.0
    last = segments[-1]
    return last.start + last.length


def build_streaming_ffmpeg_argv(
    audio_path: Path,
    output_path: Path,
    opts: RenderOptions,
    total_video: float,
) -> list[str]:
    """Build the ffmpeg argv: one rawvideo input on stdin + one audio input."""
    canvas_w, canvas_h = opts.canvas_size

    argv: list[str] = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{canvas_w}x{canvas_h}",
        "-r", str(opts.fps),
        "-i", "-",
        # Loop audio infinitely; atrim below cuts to total_video. If the video
        # is shorter than one play, only the trimmed portion is used; if the
        # video is longer (because --min-slide-duration extended it), the song
        # repeats to fill.
        "-stream_loop", "-1",
        "-i", str(audio_path),
    ]

    audio_parts = [f"[1:a]atrim=duration={total_video:.6f}"]
    if opts.audio_fade > 0:
        audio_parts.append(f"afade=t=in:st=0:d={opts.audio_fade}")
        audio_parts.append(
            f"afade=t=out:st={(total_video - opts.audio_fade):.6f}:d={opts.audio_fade}"
        )
    audio_filter = ",".join(audio_parts) + "[aout]"

    if opts.end_fade > 0:
        video_filter = (
            f"[0:v]fade=t=out:st={(total_video - opts.end_fade):.6f}:"
            f"d={opts.end_fade}[vout]"
        )
        argv += [
            "-filter_complex", f"{video_filter};{audio_filter}",
            "-map", "[vout]", "-map", "[aout]",
        ]
    else:
        argv += [
            "-filter_complex", audio_filter,
            "-map", "0:v", "-map", "[aout]",
        ]

    argv += [
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    return argv


def render_video_streaming(
    frame_paths: list[Path],
    audio_path: Path,
    output_path: Path,
    opts: RenderOptions,
    verbose: bool = False,
    quiet: bool = False,
) -> None:
    """Encode the slideshow by streaming raw RGB frames into ffmpeg.

    At most two source frames are held in memory at a time (the current slide
    and, during a crossfade, the next slide). ffmpeg sees a single rawvideo
    input on stdin, so its memory is bounded too.
    """
    if not frame_paths:
        raise ValueError("frame_paths must be non-empty")

    segments = compute_segments(len(frame_paths), opts.slide_duration, opts.xfade)
    total_video = total_video_duration(segments)
    argv = build_streaming_ffmpeg_argv(audio_path, output_path, opts, total_video)

    stderr = None if verbose else subprocess.PIPE
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stderr=stderr)

    try:
        _stream_frames(proc.stdin, frame_paths, segments, opts.fps, quiet=quiet)
    except BrokenPipeError:
        # ffmpeg exited early; its stderr explains why and is surfaced below.
        pass
    finally:
        if proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except BrokenPipeError:
                pass

    rc = proc.wait()
    if rc != 0:
        msg = (
            proc.stderr.read().decode(errors="replace")
            if proc.stderr is not None
            else "(no stderr captured; use --verbose to see ffmpeg output)"
        )
        raise FFmpegError(rc, msg)


def _stream_frames(
    stdin,
    frame_paths: list[Path],
    segments: list[Segment],
    fps: int,
    quiet: bool = False,
) -> None:
    """Walk segments and write raw RGB bytes to ffmpeg's stdin."""
    cache: dict[int, Image.Image] = {}

    def get(idx: int) -> Image.Image:
        if idx not in cache:
            img = Image.open(frame_paths[idx])
            if img.mode != "RGB":
                img = img.convert("RGB")
            cache[idx] = img
        return cache[idx]

    def evict_below(min_idx: int) -> None:
        for idx in [k for k in cache if k < min_idx]:
            del cache[idx]

    total_frames = sum(round(seg.length * fps) for seg in segments)
    bar = tqdm(
        total=total_frames,
        desc="Encoding video",
        disable=quiet,
        unit="f",
    )
    try:
        for seg in segments:
            n = round(seg.length * fps)
            if seg.kind == "solo":
                raw = get(seg.slide_a).tobytes()
                for _ in range(n):
                    stdin.write(raw)
                    bar.update(1)
                evict_below(seg.slide_a)
            else:  # xfade
                a = get(seg.slide_a)
                b = get(seg.slide_b)
                for f in range(n):
                    alpha = (f + 1) / n
                    stdin.write(Image.blend(a, b, alpha).tobytes())
                    bar.update(1)
                evict_below(seg.slide_b)
    finally:
        bar.close()


def ensure_ffmpeg_available() -> None:
    """Raise UsageError if ffmpeg is not on PATH."""
    from shutil import which
    from .errors import UsageError
    if which("ffmpeg") is None:
        raise UsageError(
            "ffmpeg not found on PATH. Install with: sudo apt install -y ffmpeg"
        )
