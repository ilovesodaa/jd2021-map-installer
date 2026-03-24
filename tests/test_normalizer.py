"""Test suite for the Normalizer pipeline.

The critical assertion: given the same CKD content, the normalizer must
produce the exact same NormalizedMapData whether the source is an
HTML-downloaded directory or an extracted IPK archive.
"""

from __future__ import annotations

from pathlib import Path

from jd2021_installer.core.models import NormalizedMapData
from jd2021_installer.parsers.normalizer import normalize


class TestNormalizerParity:
    """Ensure HTML and IPK sources produce identical NormalizedMapData."""

    def test_html_source_produces_valid_data(self, mock_html_dir: Path) -> None:
        """Normalize an HTML-downloaded directory successfully."""
        result = normalize(mock_html_dir)
        assert isinstance(result, NormalizedMapData)
        assert result.codename == "TestMap"
        assert result.song_desc.title == "Test Song"
        assert result.song_desc.artist == "Test Artist"
        assert len(result.music_track.markers) == 5

    def test_ipk_source_produces_valid_data(self, mock_ipk_dir: Path) -> None:
        """Normalize an IPK-extracted directory successfully."""
        result = normalize(mock_ipk_dir)
        assert isinstance(result, NormalizedMapData)
        assert result.codename == "TestMap"
        assert result.song_desc.title == "Test Song"
        assert len(result.music_track.markers) == 5

    def test_html_and_ipk_produce_same_output(
        self, mock_html_dir: Path, mock_ipk_dir: Path
    ) -> None:
        """THE critical parity test: both sources yield identical data."""
        html_result = normalize(mock_html_dir)
        ipk_result = normalize(mock_ipk_dir)

        assert html_result.codename == ipk_result.codename
        assert html_result.song_desc.title == ipk_result.song_desc.title
        assert html_result.song_desc.artist == ipk_result.song_desc.artist
        assert html_result.song_desc.num_coach == ipk_result.song_desc.num_coach
        assert html_result.music_track.markers == ipk_result.music_track.markers
        assert html_result.music_track.start_beat == ipk_result.music_track.start_beat
        assert html_result.music_track.end_beat == ipk_result.music_track.end_beat
        assert html_result.music_track.video_start_time == ipk_result.music_track.video_start_time


class TestNormalizerEdgeCases:
    """Edge case handling in the normalizer."""

    def test_missing_songdesc_uses_defaults(self, tmp_path: Path) -> None:
        """When songdesc CKD is missing, use reasonable defaults."""
        import json
        mt_data = {
            "COMPONENTS": [{
                "trackData": {
                    "structure": {
                        "markers": [0, 2400, 4800],
                        "signatures": [{"beats": 4, "marker": 0}],
                        "sections": [{"sectionType": 0, "marker": 0}],
                        "startBeat": 0,
                        "endBeat": 2,
                        "videoStartTime": 0.0,
                        "volume": 0.0,
                    }
                }
            }]
        }
        (tmp_path / "Test_musictrack.tpl.ckd").write_text(json.dumps(mt_data))

        result = normalize(tmp_path)
        assert result.song_desc.artist == "Unknown Artist"

    def test_raises_on_missing_musictrack(self, tmp_path: Path) -> None:
        """Normalizer must raise if no musictrack CKD exists."""
        import pytest
        from jd2021_installer.core.exceptions import NormalizationError

        (tmp_path / "dummy.txt").write_text("not a ckd")
        with pytest.raises(NormalizationError, match="musictrack"):
            normalize(tmp_path)


class TestNormalizerMusicTrack:
    """Detailed music track parsing tests."""

    def test_markers_are_integers(self, mock_html_dir: Path) -> None:
        result = normalize(mock_html_dir)
        for m in result.music_track.markers:
            assert isinstance(m, int)

    def test_video_start_time_parsed(self, mock_html_dir: Path) -> None:
        result = normalize(mock_html_dir)
        assert result.music_track.video_start_time == -1.5

    def test_video_start_time_synthesis(self) -> None:
        """Verify the marker-based sync offset synthesis for IPK sources (NO 85ms offset)."""
        from jd2021_installer.parsers.normalizer import _extract_music_track, MusicTrackStructure
        import unittest.mock
        
        # Return a real MusicTrackStructure to bypass instance checks
        mock_track = MusicTrackStructure(
            start_beat=-4,
            markers=[0, 50, 100, 150, 200, 250],
            video_start_time=0.0
        )
        
        with unittest.mock.patch("jd2021_installer.parsers.normalizer.load_ckd", return_value=mock_track), \
             unittest.mock.patch("jd2021_installer.parsers.normalizer._find_ckd_files", return_value=["dummy.ckd"]):
            res = _extract_music_track("dummy_dir", "test_map")
            
            # VST = -(marker[4] / 48 / 1000)  [NO 85ms offset for video]
            # = -(200 / 48000) = -0.004166...
            expected = -(200 / 48.0 / 1000.0)
            assert abs(res.video_start_time - expected) < 0.0001


    def test_html_source_forces_marker_sync(self):
        """Metadata vst should be ignored for HTML sources (V1 Parity)."""
        from jd2021_installer.parsers.normalizer import normalize_sync
        from jd2021_installer.core.models import MusicTrackStructure
        import unittest
        
        # Scenario: metadata has -2.658s, but markers indicate -1.139s
        # (Marker at beat 4 = 54687 ticks -> 1139.3 ms)
        mt = MusicTrackStructure(
            markers=[0, 10000, 20000, 40000, 54687],
            start_beat=-4,
            video_start_time=-2.658
        )
        
        sync = normalize_sync(mt, is_html_source=True)
        
        # Expected:
        # prms = 54687 / 48 = 1139.3125
        # video_ms = -1139.3125
        # audio_ms = -(1139.3125 + 85) = -1224.3125
        case = unittest.TestCase()
        case.assertAlmostEqual(sync.video_ms, -1139.3125, places=3)
        case.assertAlmostEqual(sync.audio_ms, -1224.3125, places=3)

    def test_ipk_source_preserves_vst(self):
        """Metadata vst should be preserved for IPK sources if non-zero."""
        from jd2021_installer.parsers.normalizer import normalize_sync
        from jd2021_installer.core.models import MusicTrackStructure
        
        mt = MusicTrackStructure(
            markers=[0, 10000, 20000, 40000, 54687],
            start_beat=-4,
            video_start_time=-2.658
        )
        
        sync = normalize_sync(mt, is_html_source=False)
        
        assert sync.video_ms == -2658.0
        assert sync.audio_ms == 0.0
