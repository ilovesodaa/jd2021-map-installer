"""Test videoStartTime preservation from source files (IPK/JDNext maps).

Tests the fix for issue: "Map Installer incorrectly overwrites videoStartTime for JDNext/IPK maps"

This tests that:
1. When a JDNext-converted IPK map has a valid non-zero videoStartTime in its source .trk,
   the game_writer preserves that value instead of synthesizing a new one.
2. For Xbox 360 rips with videoStartTime=0.0, the synthesization fallback still works.
3. When source_dir is not available, the synthesization fallback is used.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from jd2021_installer.core.models import (
    NormalizedMapData,
    MusicTrackStructure,
    SongDescription,
    MapSync,
    MapMedia,
)
from jd2021_installer.installers.game_writer import write_game_files


def create_test_map_data(
    codename: str,
    video_start_time: float,
    start_beat: int,
    markers: list,
    source_dir: Path = None,
) -> NormalizedMapData:
    """Create a test NormalizedMapData instance."""
    return NormalizedMapData(
        codename=codename,
        song_desc=SongDescription(
            title="Test Song",
            artist="Test Artist",
            map_name=codename,
            jd_version=2021,
        ),
        music_track=MusicTrackStructure(
            markers=markers,
            start_beat=start_beat,
            end_beat=max(markers) if markers else 0,
            video_start_time=video_start_time,
        ),
        media=MapMedia(),
        sync=MapSync(),
        source_dir=source_dir,
    )


def test_preserve_videostarttime_from_source_trk():
    """Test that valid non-zero videoStartTime is preserved from source .trk file."""
    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        target_dir = tmpdir / "output" / "testsong"
        source_dir = tmpdir / "source" / "testsong"
        
        # Create source directory with .trk containing valid videoStartTime
        audio_dir = source_dir / "Audio"
        audio_dir.mkdir(parents=True)
        
        # Write .trk file with videoStartTime = -15.0 (typical JDNext value)
        trk_content = """structure = { MusicTrackStructure = {
            markers = { { VAL = 48000 } },
            startBeat = -2,
            endBeat = 100,
            videoStartTime = -15.000000,
            volume = 0.0
        }}"""
        (audio_dir / "testsong.trk").write_text(trk_content)
        
        # Create test map with videoStartTime=0.0 but source has -15.0
        map_data = create_test_map_data(
            codename="testsong",
            video_start_time=0.0,  # Parser might set this to 0.0
            start_beat=-2,
            markers=[48000],
            source_dir=source_dir,
        )
        
        # Run write_game_files
        result_vst = write_game_files(map_data, target_dir)
        
        # Verify that the source value (-15.0) was preserved, not synthesized (-1.0)
        assert abs(result_vst - (-15.0)) < 0.01, f"Expected -15.0, got {result_vst}"
        
        # Verify the written .trk contains the preserved value
        written_trk = (target_dir / "Audio" / "testsong.trk").read_text()
        assert "videoStartTime = -15.000000" in written_trk


def test_synthesize_when_source_has_zero():
    """Test that synthesis still works when source has videoStartTime=0.0."""
    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        target_dir = tmpdir / "output" / "xbox360song"
        source_dir = tmpdir / "source" / "xbox360song"
        
        # Create source directory with .trk containing videoStartTime = 0.0 (Xbox 360 rip)
        audio_dir = source_dir / "Audio"
        audio_dir.mkdir(parents=True)
        
        # Create markers with enough entries for start_beat=-2 (need at least 3 markers)
        markers_str = "".join([f"{{ VAL = {i * 48000} }}" for i in range(3)])
        trk_content = f"""structure = {{ MusicTrackStructure = {{
            markers = {{ {markers_str} }},
            startBeat = -2,
            endBeat = 100,
            videoStartTime = 0.000000,
            volume = 0.0
        }}"""
        (audio_dir / "xbox360song.trk").write_text(trk_content)
        
        # Create test map with negative startBeat and markers
        map_data = create_test_map_data(
            codename="xbox360song",
            video_start_time=0.0,
            start_beat=-2,
            markers=[0, 48000, 96000],  # At least 3 markers for index 2
            source_dir=source_dir,
        )
        
        # Run write_game_files
        result_vst = write_game_files(map_data, target_dir)
        
        # Verify synthesis happened (should be approximately -2.0 based on markers[2] = 96000)
        # Expected: -(96000 / 48.0 / 1000.0) = -2.0
        assert abs(result_vst - (-2.0)) < 0.01, f"Expected ~-2.0, got {result_vst}"


def test_no_synthesis_without_source_dir():
    """Test behavior when source_dir is not available."""
    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        target_dir = tmpdir / "output" / "nosource"
        
        # Create test map without source_dir
        map_data = create_test_map_data(
            codename="nosource",
            video_start_time=0.0,
            start_beat=-2,
            markers=[0, 48000, 96000],  # At least 3 markers for index 2
            source_dir=None,  # No source directory
        )
        
        # Run write_game_files
        result_vst = write_game_files(map_data, target_dir)
        
        # Verify synthesis happened since there's no source to check
        # Expected: -(96000 / 48.0 / 1000.0) = -2.0
        assert abs(result_vst - (-2.0)) < 0.01, f"Expected ~-2.0, got {result_vst}"


def test_non_matching_trk_filename():
    """Test that the fix can handle non-matching .trk filenames in source."""
    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        target_dir = tmpdir / "output" / "mismatch"
        source_dir = tmpdir / "source" / "mismatch"
        
        # Create source directory with .trk that doesn't exactly match codename
        audio_dir = source_dir / "Audio"
        audio_dir.mkdir(parents=True)
        
        # Write .trk with a name that contains the codename
        trk_content = """structure = { MusicTrackStructure = {
            markers = { { VAL = 48000 } },
            startBeat = -3,
            endBeat = 100,
            videoStartTime = -8.500000,
            volume = 0.0
        }}"""
        (audio_dir / "mismatch_music.trk").write_text(trk_content)
        
        # Create test map
        map_data = create_test_map_data(
            codename="mismatch",
            video_start_time=0.0,
            start_beat=-3,
            markers=[144000],  # 3 * 48000
            source_dir=source_dir,
        )
        
        # Run write_game_files
        result_vst = write_game_files(map_data, target_dir)
        
        # Should find the .trk with "mismatch" in the name and preserve -8.5
        assert abs(result_vst - (-8.5)) < 0.01, f"Expected -8.5, got {result_vst}"


def test_source_vst_with_tick_values():
    """Test that tick-based videoStartTime values are auto-converted."""
    with TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        target_dir = tmpdir / "output" / "ticks"
        source_dir = tmpdir / "source" / "ticks"
        
        # Create source directory with .trk containing videoStartTime in ticks
        audio_dir = source_dir / "Audio"
        audio_dir.mkdir(parents=True)
        
        # Write .trk with videoStartTime in ticks (720000 ticks = -15 seconds at 48k sample rate)
        # -15 * 1000 * 48 = -720000 (negative)
        trk_content = """structure = { MusicTrackStructure = {
            markers = { { VAL = 48000 } },
            startBeat = -2,
            endBeat = 100,
            videoStartTime = -720000.000000,
            volume = 0.0
        }}"""
        (audio_dir / "ticks.trk").write_text(trk_content)
        
        # Create test map
        map_data = create_test_map_data(
            codename="ticks",
            video_start_time=0.0,
            start_beat=-2,
            markers=[48000],
            source_dir=source_dir,
        )
        
        # Run write_game_files
        result_vst = write_game_files(map_data, target_dir)
        
        # Should auto-convert ticks to seconds: -720000 / 48000 = -15.0
        assert abs(result_vst - (-15.0)) < 0.01, f"Expected -15.0, got {result_vst}"
