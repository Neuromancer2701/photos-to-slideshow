import pytest
from pathlib import Path

from photos_to_slideshow.audio import SlideTiming, compute_timing, read_audio_duration
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


def test_read_audio_duration_returns_seconds(fixtures_dir: Path):
    dur = read_audio_duration(fixtures_dir / "silent_1s.mp3")
    assert 0.9 < dur < 1.2  # mp3 frame quantization is loose


def test_read_audio_duration_missing_file_raises(tmp_path: Path):
    with pytest.raises(UsageError):
        read_audio_duration(tmp_path / "nope.mp3")
