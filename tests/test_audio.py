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
