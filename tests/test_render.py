from pathlib import Path

from photos_to_slideshow.render import RenderOptions, build_ffmpeg_command


def test_command_includes_each_frame_as_image_input(tmp_path: Path):
    frames = [tmp_path / f"{i:04d}.png" for i in range(3)]
    for f in frames:
        f.write_bytes(b"x")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = tmp_path / "out.mp4"

    opts = RenderOptions(
        slide_duration=2.0,
        xfade=0.5,
        fps=30,
        canvas_size=(1920, 1080),
        audio_fade=1.0,
        end_fade=1.0,
    )
    argv = build_ffmpeg_command(frames, audio, out, opts)

    # One -loop/-t/-i triple per frame
    assert argv.count("-loop") == 3
    assert argv.count(str(audio)) == 1
    assert str(out) == argv[-1]
    assert "-y" in argv
    # Filter graph must reference xfade and afade
    fc_idx = argv.index("-filter_complex")
    fc = argv[fc_idx + 1]
    assert "xfade" in fc
    assert "afade" in fc


def test_command_uses_concat_when_no_xfade(tmp_path: Path):
    frames = [tmp_path / f"{i:04d}.png" for i in range(2)]
    for f in frames:
        f.write_bytes(b"x")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = tmp_path / "out.mp4"

    opts = RenderOptions(
        slide_duration=2.0,
        xfade=0.0,  # cuts only
        fps=30,
        canvas_size=(1920, 1080),
        audio_fade=0.0,
        end_fade=0.0,
    )
    argv = build_ffmpeg_command(frames, audio, out, opts)
    fc = argv[argv.index("-filter_complex") + 1]
    assert "xfade" not in fc
    assert "concat" in fc


def test_command_handles_single_frame(tmp_path: Path):
    frame = tmp_path / "0000.png"
    frame.write_bytes(b"x")
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    out = tmp_path / "out.mp4"

    opts = RenderOptions(
        slide_duration=3.0,
        xfade=0.0,
        fps=30,
        canvas_size=(1920, 1080),
        audio_fade=0.0,
        end_fade=0.0,
    )
    argv = build_ffmpeg_command([frame], audio, out, opts)
    # No filter_complex needed for one frame; or filter chain still well-formed
    assert str(out) == argv[-1]
