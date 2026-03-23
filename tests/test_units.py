import pytest
from pathlib import Path
from jd2021_installer.core.models import NormalizedMapData, SongDescription, MusicTrackStructure, MapMedia

def test_effective_video_start_time_units():
    """Verify NormalizedMapData properly handles overrides in seconds."""
    mt = MusicTrackStructure(
        markers=[0, 48000],
        signatures=[],
        sections=[],
        start_beat=0,
        end_beat=1,
        video_start_time=0.5  # 0.5 seconds
    )
    map_data = NormalizedMapData(
        codename="test",
        song_desc=SongDescription(map_name="test", title="test", artist="test"),
        music_track=mt,
        media=MapMedia()
    )
    
    # Default (no override)
    assert map_data.effective_video_start_time == 0.5
    
    # With override (should be in seconds)
    map_data.video_start_time_override = 1.2
    assert map_data.effective_video_start_time == 1.2

def test_main_window_unit_conversion_logic():
    """Verify logic used in MainWindow for ms->sec conversion."""
    # This simulates the logic in _on_apply_offset
    original_sec = 0.5
    offset_ms = 500.0  # +500ms
    
    new_v_override_sec = original_sec + (offset_ms / 1000.0)
    assert new_v_override_sec == 1.0
    
    # This simulates the logic in _on_readjust
    vo_sec = 0.5
    vo_ms = vo_sec * 1000.0
    assert vo_ms == 500.0
