from pathlib import Path

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.models import MapMedia, MusicTrackStructure, NormalizedMapData, SongDescription
from jd2021_installer.installers.game_writer import write_game_files
from jd2021_installer.parsers import normalizer


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


def test_extract_song_desc_accepts_id_alias_for_locale_id(monkeypatch, tmp_path: Path) -> None:
    fake_file = tmp_path / "songdesc.tpl.ckd"

    monkeypatch.setattr(normalizer, "_find_ckd_files", lambda *_args, **_kwargs: [str(fake_file)])
    monkeypatch.setattr(
        normalizer,
        "load_ckd",
        lambda *_args, **_kwargs: {
            "COMPONENTS": [
                {
                    "MapName": "AliasMap",
                    "Title": "Alias Title",
                    "Artist": "Alias Artist",
                    "ID": 1337,
                }
            ]
        },
    )

    parsed = normalizer._extract_song_desc(str(tmp_path), codename="AliasMap")

    assert parsed.locale_id == 1337


def test_songdesc_writer_emits_version_loc_id_when_present(tmp_path: Path) -> None:
    codename = "VariantMap"
    target = tmp_path / codename
    song_desc = SongDescription(
        map_name=codename,
        title=codename,
        artist="Artist",
        locale_id=4294967295,
        version_loc_id=15158,
    )

    write_game_files(_build_map_data(codename, song_desc), target, AppConfig())

    content = (target / "SongDesc.tpl").read_text(encoding="utf-8")
    assert "LocaleID = 4294967295," in content
    assert "VersionLocId = 15158," in content
