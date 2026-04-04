from pathlib import Path

from jd2021_installer.core.install_summary import build_install_summary
from jd2021_installer.core.models import MapMedia, MapSync, MusicTrackStructure, NormalizedMapData, SongDescription


def _build_map(codename: str) -> NormalizedMapData:
    return NormalizedMapData(
        codename=codename,
        song_desc=SongDescription(title="Test Song"),
        music_track=MusicTrackStructure(),
        media=MapMedia(),
        sync=MapSync(),
    )


def test_install_summary_marks_risky_when_required_missing(tmp_path: Path) -> None:
    codename = "MapA"
    map_dir = tmp_path / codename
    map_dir.mkdir(parents=True)

    summary = build_install_summary(
        _build_map(codename),
        map_dir,
        source_mode="Fetch (Codename)",
        quality="HIGH",
        duration_s=10.0,
        success=True,
    )

    assert summary.status_label == "PARTIAL/RISKY"
    assert summary.missing_required_count > 0


def test_install_summary_success_with_optional_warnings(tmp_path: Path) -> None:
    codename = "MapB"
    map_dir = tmp_path / codename
    (map_dir / "Audio").mkdir(parents=True)
    (map_dir / "Timeline").mkdir(parents=True)
    (map_dir / "VideosCoach").mkdir(parents=True)

    (map_dir / f"{codename}_MAIN_SCENE.isc").write_text("x", encoding="utf-8")
    (map_dir / "SongDesc.tpl").write_text("x", encoding="utf-8")
    (map_dir / "SongDesc.act").write_text("x", encoding="utf-8")
    (map_dir / f"Audio/{codename}.trk").write_text("x", encoding="utf-8")
    (map_dir / f"Audio/{codename}_musictrack.tpl").write_text("x", encoding="utf-8")
    (map_dir / f"Audio/{codename}_sequence.tpl").write_text("x", encoding="utf-8")
    (map_dir / f"Audio/{codename}_audio.isc").write_text("x", encoding="utf-8")
    (map_dir / f"Audio/{codename}.stape").write_text("x", encoding="utf-8")
    (map_dir / "Audio/ConfigMusic.sfi").write_text("x", encoding="utf-8")
    (map_dir / f"Timeline/{codename}_tml.isc").write_text("x", encoding="utf-8")
    (map_dir / f"Timeline/{codename}_TML_Dance.dtape").write_text("x", encoding="utf-8")
    (map_dir / f"Timeline/{codename}_TML_Karaoke.ktape").write_text("x", encoding="utf-8")
    (map_dir / f"VideosCoach/{codename}.webm").write_bytes(b"x")

    summary = build_install_summary(
        _build_map(codename),
        map_dir,
        source_mode="IPK",
        quality="ULTRA_HD",
        duration_s=2.5,
        success=True,
    )

    assert summary.status_label == "SUCCESS (WARNINGS)"
    assert summary.missing_required_count == 0
    assert summary.missing_optional_count > 0