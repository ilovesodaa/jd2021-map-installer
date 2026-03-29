from pathlib import Path

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.models import MapMedia, MusicTrackStructure, NormalizedMapData, SongDescription
from jd2021_installer.installers.game_writer import write_game_files


def _build_map_data(codename: str, song_desc: SongDescription) -> NormalizedMapData:
    return NormalizedMapData(
        codename=codename,
        song_desc=song_desc,
        music_track=MusicTrackStructure(
            markers=[0, 2400, 4800],
            start_beat=0,
            end_beat=2,
            video_start_time=-1.0,
        ),
        media=MapMedia(),
    )


def _read_songdesc_tpl(target: Path) -> str:
    return (target / "SongDesc.tpl").read_text(encoding="utf-8")


def test_songdesc_uses_2021_engine_for_modern_out_of_range_source(tmp_path: Path) -> None:
    codename = "ModernSource"
    target = tmp_path / codename
    song_desc = SongDescription(
        map_name=codename,
        title=codename,
        artist="Artist",
        jd_version=2026,
        original_jd_version=2026,
    )

    write_game_files(_build_map_data(codename, song_desc), target, AppConfig())

    content = _read_songdesc_tpl(target)
    assert "JDVersion = 2021" in content
    assert "OriginalJDVersion = 2026" in content


def test_songdesc_uses_2016_engine_for_legacy_source(tmp_path: Path) -> None:
    codename = "LegacySource"
    target = tmp_path / codename
    song_desc = SongDescription(
        map_name=codename,
        title=codename,
        artist="Artist",
        jd_version=3,
        original_jd_version=3,
    )

    write_game_files(_build_map_data(codename, song_desc), target, AppConfig())

    content = _read_songdesc_tpl(target)
    assert "JDVersion = 2016" in content
    assert "OriginalJDVersion = 3" in content


def test_songdesc_rejects_non_numeric_versions_with_safe_fallback(tmp_path: Path) -> None:
    codename = "NonNumeric"
    target = tmp_path / codename
    song_desc = SongDescription(
        map_name=codename,
        title=codename,
        artist="Artist",
        jd_version="WII2",  # type: ignore[arg-type]
        original_jd_version="WII2",  # type: ignore[arg-type]
    )

    write_game_files(_build_map_data(codename, song_desc), target, AppConfig())

    content = _read_songdesc_tpl(target)
    assert "JDVersion = 2021" in content
    assert "OriginalJDVersion = 2021" in content
