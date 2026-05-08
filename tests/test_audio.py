import pytest
from pathlib import Path

from photos_to_slideshow.audio import (
    AudioSource,
    SlideTiming,
    compute_timing,
    concat_mp3_files,
    read_audio_duration,
    resolve_audio_source,
    write_concat_playlist,
)
from photos_to_slideshow.errors import UsageError


def test_basic_crossfade_timing():
    # 60 photos, 180s audio, 0.5s xfade
    # D = (180 + 59*0.5) / 60 = 209.5 / 60 = 3.4916...
    t = compute_timing(audio_duration=180.0, n_photos=60, xfade=0.5)
    assert t.slide_duration == pytest.approx(209.5 / 60)
    assert t.xfade == 0.5
    assert t.downgraded_to_cut is False


def test_single_photo_uses_full_audio():
    t = compute_timing(audio_duration=10.0, n_photos=1, xfade=0.5)
    assert t.slide_duration == pytest.approx(10.0)
    assert t.xfade == 0.0  # no transition with one photo
    assert t.downgraded_to_cut is False


def test_cut_transition_when_xfade_zero():
    t = compute_timing(audio_duration=60.0, n_photos=10, xfade=0.0)
    assert t.slide_duration == pytest.approx(6.0)


def test_auto_downgrade_when_slide_too_short_for_xfade():
    # 100 photos in 30s audio with 0.5s xfade -> slide ~0.3s, less than 2*xfade
    t = compute_timing(audio_duration=30.0, n_photos=100, xfade=0.5)
    assert t.downgraded_to_cut is True
    assert t.xfade == 0.0
    assert t.slide_duration == pytest.approx(0.3)


def test_zero_photos_raises():
    with pytest.raises(ValueError):
        compute_timing(audio_duration=10.0, n_photos=0, xfade=0.5)


def test_min_slide_extends_when_natural_too_short():
    # 200 photos, 240s audio, 0.5s xfade -> natural slide ~1.2s
    # min_slide=3.0 should extend each slide to 3s.
    t = compute_timing(audio_duration=240.0, n_photos=200, xfade=0.5, min_slide=3.0)
    assert t.slide_duration == pytest.approx(3.0)
    assert t.xfade == 0.5
    assert t.extended_for_min is True
    assert t.downgraded_to_cut is False


def test_min_slide_below_natural_is_noop():
    # Natural slide 6s; min 2s shouldn't change anything.
    t = compute_timing(audio_duration=60.0, n_photos=10, xfade=0.0, min_slide=2.0)
    assert t.slide_duration == pytest.approx(6.0)
    assert t.extended_for_min is False


def test_min_slide_zero_keeps_old_behavior():
    t = compute_timing(audio_duration=180.0, n_photos=60, xfade=0.5, min_slide=0.0)
    assert t.extended_for_min is False
    assert t.slide_duration == pytest.approx(209.5 / 60)


def test_min_slide_extension_can_force_cut_downgrade():
    # min_slide=0.8 with xfade=0.5: 0.8 < 2*0.5=1.0 -> downgrade to cuts.
    t = compute_timing(audio_duration=10.0, n_photos=200, xfade=0.5, min_slide=0.8)
    assert t.extended_for_min is True
    assert t.downgraded_to_cut is True
    assert t.xfade == 0.0
    assert t.slide_duration == pytest.approx(0.8)


def test_min_slide_with_single_photo_extends():
    t = compute_timing(audio_duration=2.0, n_photos=1, xfade=0.5, min_slide=10.0)
    assert t.slide_duration == pytest.approx(10.0)
    assert t.extended_for_min is True


def test_read_audio_duration_returns_seconds(fixtures_dir: Path):
    dur = read_audio_duration(fixtures_dir / "silent_1s.mp3")
    assert 0.9 < dur < 1.2  # mp3 frame quantization is loose


def test_read_audio_duration_missing_file_raises(tmp_path: Path):
    with pytest.raises(UsageError):
        read_audio_duration(tmp_path / "nope.mp3")


# --- resolve_audio_source ----------------------------------------------------

def test_resolve_audio_source_single_file(fixtures_dir: Path):
    src = resolve_audio_source(fixtures_dir / "silent_1s.mp3")
    assert isinstance(src, AudioSource)
    assert src.files == (fixtures_dir / "silent_1s.mp3",)
    assert 0.9 < src.total_duration < 1.2
    assert src.is_playlist is False


def test_resolve_audio_source_directory_sums_durations(tmp_path: Path, fixtures_dir: Path):
    import shutil
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        shutil.copy(fixtures_dir / "silent_1s.mp3", tmp_path / name)
    src = resolve_audio_source(tmp_path)
    assert len(src.files) == 3
    assert src.is_playlist is True
    # Each clip is ~1s, total should be ~3s
    assert 2.7 < src.total_duration < 3.6


def test_resolve_audio_source_directory_natural_sort(tmp_path: Path, fixtures_dir: Path):
    """track2 must sort before track10 (natural, not lexicographic)."""
    import shutil
    for name in ("track10.mp3", "track1.mp3", "track2.mp3"):
        shutil.copy(fixtures_dir / "silent_1s.mp3", tmp_path / name)
    src = resolve_audio_source(tmp_path)
    assert [p.name for p in src.files] == ["track1.mp3", "track2.mp3", "track10.mp3"]


def test_resolve_audio_source_directory_ignores_non_mp3(tmp_path: Path, fixtures_dir: Path):
    import shutil
    shutil.copy(fixtures_dir / "silent_1s.mp3", tmp_path / "song.mp3")
    (tmp_path / "notes.txt").write_text("hi")
    (tmp_path / "cover.jpg").write_bytes(b"\xff\xd8\xff")
    src = resolve_audio_source(tmp_path)
    assert [p.name for p in src.files] == ["song.mp3"]


def test_resolve_audio_source_directory_case_insensitive_extension(
    tmp_path: Path, fixtures_dir: Path,
):
    import shutil
    shutil.copy(fixtures_dir / "silent_1s.mp3", tmp_path / "SONG.MP3")
    src = resolve_audio_source(tmp_path)
    assert [p.name for p in src.files] == ["SONG.MP3"]


def test_resolve_audio_source_empty_directory_raises(tmp_path: Path):
    with pytest.raises(UsageError):
        resolve_audio_source(tmp_path)


def test_resolve_audio_source_missing_path_raises(tmp_path: Path):
    with pytest.raises(UsageError):
        resolve_audio_source(tmp_path / "nope")


def test_resolve_audio_source_non_mp3_file_raises(tmp_path: Path):
    p = tmp_path / "song.wav"
    p.write_bytes(b"not really wav")
    with pytest.raises(UsageError):
        resolve_audio_source(p)


# --- write_concat_playlist ---------------------------------------------------

def test_write_concat_playlist_writes_file_directives(tmp_path: Path):
    files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    for f in files:
        f.write_bytes(b"")
    dest = tmp_path / "playlist.txt"
    write_concat_playlist(files, dest)
    text = dest.read_text()
    lines = text.strip().splitlines()
    assert lines[0] == f"file '{files[0].resolve()}'"
    assert lines[1] == f"file '{files[1].resolve()}'"


@pytest.mark.slow
def test_concat_mp3_files_produces_summed_duration(tmp_path: Path, fixtures_dir: Path):
    """Stream-copying two ~1s clips into one file should yield ~2s."""
    import shutil
    a = tmp_path / "a.mp3"
    b = tmp_path / "b.mp3"
    shutil.copy(fixtures_dir / "silent_1s.mp3", a)
    shutil.copy(fixtures_dir / "silent_1s.mp3", b)
    out = tmp_path / "combined.mp3"
    concat_mp3_files([a, b], out)
    assert out.exists()
    assert 1.8 < read_audio_duration(out) < 2.4
    # The temp playlist file should be cleaned up
    assert not (tmp_path / "combined.mp3.txt").exists()


def test_write_concat_playlist_escapes_single_quotes(tmp_path: Path):
    weird = tmp_path / "it's a song.mp3"
    weird.write_bytes(b"")
    dest = tmp_path / "playlist.txt"
    write_concat_playlist([weird], dest)
    line = dest.read_text().strip()
    # ffmpeg concat-demuxer escape for ' inside a single-quoted string is '\''
    assert line == f"file '{weird.resolve().parent}/it'\\''s a song.mp3'"
