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
