"""Command-line entry point for photos-to-slideshow."""

import argparse
import sys
import tempfile
import shutil
from pathlib import Path

from tqdm import tqdm

from . import audio as audio_mod
from . import images, inputs, metadata, render
from .errors import FFmpegError, NoUsablePhotosError, SlideshowError, UsageError


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
    parser.add_argument("--min-slide-duration", type=float, default=0.0,
                        dest="min_slide_duration",
                        help="Minimum seconds per slide. If auto-fit would be "
                             "shorter, slides are held longer and the audio "
                             "loops to fill the longer video. (default: 0 = "
                             "auto-fit only, single audio play)")
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


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns the process exit code (0/1/2/3/130)."""
    try:
        args = parse_args(argv)
        return _run(args)
    except UsageError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except NoUsablePhotosError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except FFmpegError as e:
        print(f"ffmpeg failed (code {e.returncode}):\n{e.stderr}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except SlideshowError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _run(args) -> int:
    render.ensure_ffmpeg_available()

    canvas = parse_resolution(args.resolution)

    # Resolve transition into xfade seconds
    if args.transition == "cut":
        xfade = 0.0
    else:
        # crossfade and fade-black both map to xfade duration; we use the
        # default 'fade' xfade transition for both in v0.1
        xfade = args.transition_duration

    # Step 1: resolve input
    resolved = inputs.resolve(args.input)
    frames_dir: Path | None = None
    try:
        # Step 2: scan & sort
        all_paths = list(inputs.iter_image_files(resolved.root))
        if not all_paths:
            raise NoUsablePhotosError(f"No supported images found in {args.input}")
        sorted_paths, mtime_fallbacks = metadata.sort_by_date(all_paths)
        if mtime_fallbacks:
            print(
                f"warning: {mtime_fallbacks} of {len(sorted_paths)} photos lacked "
                f"EXIF date; used file mtime instead",
                file=sys.stderr,
            )

        # Step 3: pre-render frames
        frames_dir = Path(tempfile.mkdtemp(prefix="photos_to_slideshow_frames_"))
        frame_paths: list[Path] = []
        bar = tqdm(
            sorted_paths,
            desc="Rendering frames",
            disable=args.quiet,
            file=sys.stderr,
        )
        for i, src in enumerate(bar):
            try:
                frame = images.render_frame(src, canvas)
            except Exception as e:
                print(f"warning: skipping unreadable image {src}: {e}", file=sys.stderr)
                continue
            out = frames_dir / f"{i:05d}.png"
            frame.save(out, "PNG")
            frame_paths.append(out)

        if not frame_paths:
            raise NoUsablePhotosError("All images failed to decode")

        # Step 4: timing math
        audio_dur = audio_mod.read_audio_duration(args.audio)
        timing = audio_mod.compute_timing(
            audio_dur, len(frame_paths), xfade, min_slide=args.min_slide_duration,
        )
        if timing.downgraded_to_cut:
            print(
                f"warning: slide duration too short for crossfade; "
                f"using hard cuts instead",
                file=sys.stderr,
            )
        if timing.extended_for_min:
            print(
                f"info: holding each slide for {timing.slide_duration:.2f}s "
                f"(min-slide-duration); audio will loop to fill",
                file=sys.stderr,
            )
        elif args.min_slide_duration == 0.0 and timing.slide_duration < 1.5:
            print(
                f"hint: photos are showing for only {timing.slide_duration:.2f}s "
                f"each. Pass --min-slide-duration 3 (or similar) to slow them "
                f"down; the audio will loop to fill the longer video.",
                file=sys.stderr,
            )
        # Clamp audio_fade if song is short
        audio_fade = args.audio_fade
        if audio_fade * 2 > audio_dur:
            audio_fade = audio_dur / 4
            print(
                f"warning: audio shorter than 2x audio-fade; "
                f"clamped audio-fade to {audio_fade:.2f}s",
                file=sys.stderr,
            )

        # Step 5: render video
        opts = render.RenderOptions(
            slide_duration=timing.slide_duration,
            xfade=timing.xfade,
            fps=args.fps,
            canvas_size=canvas,
            audio_fade=audio_fade,
            end_fade=args.end_fade,
        )
        # Ensure output dir exists
        args.output.parent.mkdir(parents=True, exist_ok=True)
        render.render_video_streaming(
            frame_paths, args.audio, args.output, opts,
            verbose=args.verbose, quiet=args.quiet,
        )

        print(str(args.output))  # only output to stdout, so the tool is pipeable
        return 0

    finally:
        # Step 6: cleanup
        if not args.keep_temp:
            resolved.cleanup()
            if frames_dir is not None and frames_dir.exists():
                shutil.rmtree(frames_dir)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
