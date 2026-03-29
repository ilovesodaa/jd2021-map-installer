from pathlib import Path

from jd2021_installer.core.models import MusicTrackStructure
from jd2021_installer.installers.game_writer import _write_musictrack_trk


def test_write_musictrack_trk_derives_preview_loop_when_missing(tmp_path: Path) -> None:
    mt = MusicTrackStructure(
        markers=[0] * 543,
        signatures=[],
        sections=[],
        start_beat=-21,
        end_beat=545,
        video_start_time=0.0,
        preview_entry=0.0,
        preview_loop_start=0.0,
        preview_loop_end=0.0,
    )

    (tmp_path / "Audio").mkdir(parents=True, exist_ok=True)
    _write_musictrack_trk(tmp_path, "judas", mt, vst=-9.6183125)

    content = (tmp_path / "Audio" / "judas.trk").read_text(encoding="utf-8")

    assert "previewEntry = 272.0" in content
    assert "previewLoopStart = 272.0" in content
    assert "previewLoopEnd = 545.0" in content


def test_write_musictrack_trk_preserves_large_preview_values(tmp_path: Path) -> None:
    mt = MusicTrackStructure(
        markers=[0] * 10,
        signatures=[],
        sections=[],
        start_beat=0,
        end_beat=574,
        video_start_time=0.0,
        preview_entry=287.0,
        preview_loop_start=287.0,
        preview_loop_end=574.0,
    )

    (tmp_path / "Audio").mkdir(parents=True, exist_ok=True)
    _write_musictrack_trk(tmp_path, "sample", mt, vst=0.0)

    content = (tmp_path / "Audio" / "sample.trk").read_text(encoding="utf-8")

    assert "previewEntry = 287.0" in content
    assert "previewLoopStart = 287.0" in content
    assert "previewLoopEnd = 574.0" in content
