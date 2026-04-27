from pathlib import Path

import pytest

from photos_to_slideshow.render import (
    RenderOptions,
    Segment,
    build_streaming_ffmpeg_argv,
    compute_segments,
    total_video_duration,
)


# --- compute_segments ---------------------------------------------------------

def test_compute_segments_single_photo():
    segs = compute_segments(1, slide_duration=4.0, xfade=0.5)
    assert segs == [Segment("solo", 0, None, 0.0, 4.0)]
    assert total_video_duration(segs) == pytest.approx(4.0)


def test_compute_segments_cuts_only():
    segs = compute_segments(3, slide_duration=2.0, xfade=0.0)
    assert [s.kind for s in segs] == ["solo", "solo", "solo"]
    assert [s.slide_a for s in segs] == [0, 1, 2]
    assert [s.length for s in segs] == [2.0, 2.0, 2.0]
    assert total_video_duration(segs) == pytest.approx(6.0)


def test_compute_segments_three_photos_with_crossfade():
    # D=5, X=1, N=3 -> total = 3*5 - 2*1 = 13
    segs = compute_segments(3, slide_duration=5.0, xfade=1.0)
    assert [s.kind for s in segs] == ["solo", "xfade", "solo", "xfade", "solo"]
    # First and last solo: D - X = 4. Middle solo: D - 2X = 3.
    assert [s.length for s in segs] == [4.0, 1.0, 3.0, 1.0, 4.0]
    xfades = [s for s in segs if s.kind == "xfade"]
    assert (xfades[0].slide_a, xfades[0].slide_b) == (0, 1)
    assert (xfades[1].slide_a, xfades[1].slide_b) == (1, 2)
    assert total_video_duration(segs) == pytest.approx(13.0)


def test_compute_segments_total_matches_formula_for_many_photos():
    segs = compute_segments(200, slide_duration=2.0, xfade=0.5)
    assert total_video_duration(segs) == pytest.approx(200 * 2.0 - 199 * 0.5)


def test_compute_segments_zero_photos_raises():
    with pytest.raises(ValueError):
        compute_segments(0, slide_duration=2.0, xfade=0.5)


# --- build_streaming_ffmpeg_argv ---------------------------------------------

def _opts(**overrides) -> RenderOptions:
    base = dict(
        slide_duration=2.0,
        xfade=0.5,
        fps=30,
        canvas_size=(1920, 1080),
        audio_fade=1.0,
        end_fade=1.0,
    )
    base.update(overrides)
    return RenderOptions(**base)


def test_argv_uses_rawvideo_stdin_input(tmp_path: Path):
    audio = tmp_path / "a.mp3"
    out = tmp_path / "o.mp4"
    argv = build_streaming_ffmpeg_argv(audio, out, _opts(), total_video=10.0)

    assert "-f" in argv and "rawvideo" in argv
    assert argv.count("-i") == 2
    i_indices = [i for i, a in enumerate(argv) if a == "-i"]
    assert argv[i_indices[0] + 1] == "-"        # first input from stdin
    assert argv[i_indices[1] + 1] == str(audio)  # second input is the audio file
    assert argv[-1] == str(out)
    assert "-y" in argv


def test_argv_audio_input_loops_with_stream_loop(tmp_path: Path):
    """The audio input must be preceded by -stream_loop -1 so the song repeats
    when the video is longer than one play (for --min-slide-duration)."""
    audio = tmp_path / "a.mp3"
    argv = build_streaming_ffmpeg_argv(audio, tmp_path / "o.mp4", _opts(), 10.0)
    audio_idx = [i for i, a in enumerate(argv) if a == "-i" and argv[i + 1] == str(audio)][0]
    # The two args immediately before the audio -i should be "-stream_loop -1".
    assert argv[audio_idx - 2 : audio_idx] == ["-stream_loop", "-1"]


def test_argv_includes_canvas_size_and_fps(tmp_path: Path):
    argv = build_streaming_ffmpeg_argv(
        tmp_path / "a.mp3", tmp_path / "o.mp4",
        _opts(canvas_size=(1280, 720), fps=24),
        total_video=5.0,
    )
    assert "1280x720" in argv
    assert "24" in argv


def test_argv_audio_filter_includes_fades(tmp_path: Path):
    argv = build_streaming_ffmpeg_argv(
        tmp_path / "a.mp3", tmp_path / "o.mp4",
        _opts(audio_fade=2.0, end_fade=0.0),
        total_video=20.0,
    )
    fc = argv[argv.index("-filter_complex") + 1]
    assert "afade=t=in:st=0:d=2.0" in fc
    assert "afade=t=out" in fc and "d=2.0" in fc


def test_argv_video_end_fade_present_when_requested(tmp_path: Path):
    argv = build_streaming_ffmpeg_argv(
        tmp_path / "a.mp3", tmp_path / "o.mp4",
        _opts(end_fade=1.5),
        total_video=10.0,
    )
    fc = argv[argv.index("-filter_complex") + 1]
    assert "fade=t=out" in fc
    assert "d=1.5" in fc
    map_args = [argv[i + 1] for i, a in enumerate(argv) if a == "-map"]
    assert "[vout]" in map_args
    assert "[aout]" in map_args


def test_argv_no_end_fade_maps_raw_video_stream(tmp_path: Path):
    argv = build_streaming_ffmpeg_argv(
        tmp_path / "a.mp3", tmp_path / "o.mp4",
        _opts(end_fade=0.0, audio_fade=0.0),
        total_video=10.0,
    )
    fc = argv[argv.index("-filter_complex") + 1]
    # No video filter when end_fade is disabled
    assert "fade=t=out" not in fc
    map_args = [argv[i + 1] for i, a in enumerate(argv) if a == "-map"]
    assert "0:v" in map_args
