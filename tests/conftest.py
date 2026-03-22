"""Pytest fixtures for the JD2021 Map Installer test suite."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict

import pytest

from jd2021_installer.core.models import (
    DefaultColors,
    MusicSection,
    MusicSignature,
    MusicTrackStructure,
    NormalizedMapData,
    SongDescription,
    MapMedia,
)


@pytest.fixture
def sample_music_track() -> MusicTrackStructure:
    """A minimal valid MusicTrackStructure for testing."""
    return MusicTrackStructure(
        markers=[0, 2400, 4800, 7200, 9600, 12000, 14400, 16800, 19200],
        signatures=[MusicSignature(beats=4, marker=0)],
        sections=[MusicSection(section_type=0, marker=0)],
        start_beat=0,
        end_beat=8,
        video_start_time=0.0,
        volume=-1.5,
    )


@pytest.fixture
def sample_song_desc() -> SongDescription:
    """A minimal valid SongDescription for testing."""
    return SongDescription(
        map_name="TestMap",
        title="Test Song",
        artist="Test Artist",
        num_coach=1,
        jd_version=2021,
        original_jd_version=2021,
    )


@pytest.fixture
def sample_normalized_data(
    sample_music_track: MusicTrackStructure,
    sample_song_desc: SongDescription,
) -> NormalizedMapData:
    """A minimal NormalizedMapData for testing."""
    return NormalizedMapData(
        codename="TestMap",
        song_desc=sample_song_desc,
        music_track=sample_music_track,
    )


@pytest.fixture
def mock_musictrack_json(tmp_path: Path) -> Path:
    """Create a mock JSON musictrack CKD file."""
    data = {
        "COMPONENTS": [{
            "trackData": {
                "structure": {
                    "markers": [0, 2400, 4800, 7200, 9600],
                    "signatures": [{"beats": 4, "marker": 0}],
                    "sections": [{"sectionType": 0, "marker": 0}],
                    "startBeat": 0,
                    "endBeat": 4,
                    "videoStartTime": -1.5,
                    "previewEntry": 0,
                    "previewLoopStart": 0,
                    "previewLoopEnd": 0,
                    "volume": -2.0,
                    "fadeInDuration": 0,
                    "fadeInType": 0,
                    "fadeOutDuration": 0,
                    "fadeOutType": 0,
                }
            }
        }]
    }
    ckd_path = tmp_path / "TestMap_musictrack.tpl.ckd"
    ckd_path.write_text(json.dumps(data), encoding="utf-8")
    return ckd_path


@pytest.fixture
def mock_songdesc_json(tmp_path: Path) -> Path:
    """Create a mock JSON songdesc CKD file."""
    data = {
        "COMPONENTS": [{
            "MapName": "TestMap",
            "JDVersion": 2021,
            "OriginalJDVersion": 2021,
            "Artist": "Test Artist",
            "DancerName": "Test Dancer",
            "Title": "Test Song",
            "NumCoach": 1,
            "MainCoach": -1,
            "Difficulty": 2,
            "SweatDifficulty": 1,
            "backgroundType": 0,
            "LyricsType": 0,
            "Energy": 1,
            "Tags": ["Main"],
            "Status": 3,
            "LocaleID": 4294967295,
            "MojoValue": 0,
            "DefaultColors": {
                "theme": [1.0, 1.0, 1.0, 1.0],
                "lyrics": [1.0, 0.1, 0.2, 0.7],
            },
        }]
    }
    ckd_path = tmp_path / "TestMap_songdesc.tpl.ckd"
    ckd_path.write_text(json.dumps(data), encoding="utf-8")
    return ckd_path


@pytest.fixture
def mock_ipk_dir(tmp_path: Path, mock_musictrack_json: Path, mock_songdesc_json: Path) -> Path:
    """Create a mock extracted IPK directory with CKD files."""
    ipk_dir = tmp_path / "ipk_extracted"
    ipk_dir.mkdir()
    # Copy mock CKDs into the directory
    import shutil
    shutil.copy(mock_musictrack_json, ipk_dir / mock_musictrack_json.name)
    shutil.copy(mock_songdesc_json, ipk_dir / mock_songdesc_json.name)
    return ipk_dir


@pytest.fixture
def mock_html_dir(tmp_path: Path, mock_musictrack_json: Path, mock_songdesc_json: Path) -> Path:
    """Create a mock web-downloaded directory with CKD files.

    Should produce the SAME NormalizedMapData as mock_ipk_dir.
    """
    html_dir = tmp_path / "html_downloaded"
    html_dir.mkdir()
    import shutil
    shutil.copy(mock_musictrack_json, html_dir / mock_musictrack_json.name)
    shutil.copy(mock_songdesc_json, html_dir / mock_songdesc_json.name)
    return html_dir
