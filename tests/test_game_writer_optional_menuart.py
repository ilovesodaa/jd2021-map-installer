from pathlib import Path

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.models import MapMedia, MusicTrackStructure, NormalizedMapData, SongDescription
from jd2021_installer.installers.game_writer import write_game_files


def _build_map_data(codename: str, media: MapMedia) -> NormalizedMapData:
    return NormalizedMapData(
        codename=codename,
        song_desc=SongDescription(map_name=codename, title=codename, artist="Artist", num_coach=1),
        music_track=MusicTrackStructure(
            markers=[0, 2400, 4800],
            start_beat=0,
            end_beat=2,
            video_start_time=-1.0,
        ),
        media=media,
    )


def test_write_game_files_skips_missing_optional_menuart_actors(tmp_path: Path) -> None:
    codename = "OptionalMap"
    target = tmp_path / codename
    map_data = _build_map_data(codename, MapMedia())

    write_game_files(map_data, target, AppConfig())

    assert (target / f"MenuArt/Actors/{codename}_cover_generic.act").exists()
    assert (target / f"MenuArt/Actors/{codename}_cover_online.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_banner_bkg.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_map_bkg.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_cover_albumbkg.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_cover_albumcoach.act").exists()


def test_write_game_files_includes_discovered_optional_menuart_actors(tmp_path: Path) -> None:
    codename = "OptionalMap"
    target = tmp_path / codename
    map_data = _build_map_data(
        codename,
        MapMedia(
            map_bkg_path=tmp_path / "map_bkg_source.tga",
            cover_albumbkg_path=tmp_path / "album_source.tga",
        ),
    )

    write_game_files(map_data, target, AppConfig())

    assert (target / f"MenuArt/Actors/{codename}_map_bkg.act").exists()
    assert (target / f"MenuArt/Actors/{codename}_cover_albumbkg.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_banner_bkg.act").exists()
