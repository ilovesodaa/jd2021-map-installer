import pytest
import os
from pathlib import Path
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication
from jd2021_installer.core.models import NormalizedMapData, SongDescription, MusicTrackStructure, MapMedia
from jd2021_installer.core.config import AppConfig
from jd2021_installer.ui.widgets.preview_widget import PreviewWidget
from jd2021_installer.ui.workers.pipeline_workers import BatchInstallWorker


def _build_map(codename: str) -> NormalizedMapData:
    return NormalizedMapData(
        codename=codename,
        song_desc=SongDescription(map_name=codename, title=codename, artist="artist"),
        music_track=MusicTrackStructure(
            markers=[0, 48000],
            signatures=[],
            sections=[],
            start_beat=0,
            end_beat=1,
            video_start_time=0.0,
        ),
        media=MapMedia(),
    )


def _get_qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

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


def test_preview_pause_does_not_clear_canvas():
    _get_qapp()
    widget = PreviewWidget()
    pixmap = QPixmap(8, 8)
    widget._canvas.setPixmap(pixmap)
    widget._canvas.setText("")
    widget._playing = True
    widget._toggle_playback()
    assert widget._canvas.text() == ""
    assert widget.is_playing is False


def test_batch_worker_discovered_maps_respect_selection(tmp_path: Path, monkeypatch):
    from jd2021_installer.extractors import archive_ipk
    from jd2021_installer.parsers import normalizer

    ipk = tmp_path / "bundle.ipk"
    ipk.touch()
    extracted = tmp_path / "extracted" / "world" / "maps"
    map_a = extracted / "MapA"
    map_b = extracted / "MapB"
    map_a.mkdir(parents=True)
    map_b.mkdir(parents=True)
    (map_a / "songdesc.tpl.ckd").touch()
    (map_b / "songdesc.tpl.ckd").touch()

    monkeypatch.setattr(archive_ipk, "inspect_ipk", lambda _: ["MapA", "MapB"])
    monkeypatch.setattr(archive_ipk.ArchiveIPKExtractor, "extract", lambda self, _: extracted.parent.parent)
    monkeypatch.setattr(normalizer, "normalize", lambda root, codename=None, search_root=None: _build_map(codename or "MapA"))
    monkeypatch.setattr(BatchInstallWorker, "_install_map_synchronously", lambda self, map_data: None)

    worker = BatchInstallWorker(
        batch_source_dir=ipk,
        target_game_dir=tmp_path / "game",
        config=AppConfig(cache_directory=tmp_path / "cache"),
        selected_maps={"MapB"},
    )
    discovered: list[list[str]] = []
    worker.discovered_maps.connect(lambda names: discovered.append(names))
    worker.run()
    assert discovered
    assert discovered[0] == ["MapB"]


def test_batch_worker_progress_is_monotonic(tmp_path: Path, monkeypatch):
    from jd2021_installer.extractors import archive_ipk
    from jd2021_installer.parsers import normalizer

    ipk = tmp_path / "bundle.ipk"
    ipk.touch()
    extracted = tmp_path / "extracted" / "world" / "maps"
    map_a = extracted / "MapA"
    map_b = extracted / "MapB"
    map_a.mkdir(parents=True)
    map_b.mkdir(parents=True)
    (map_a / "songdesc.tpl.ckd").touch()
    (map_b / "songdesc.tpl.ckd").touch()

    monkeypatch.setattr(archive_ipk, "inspect_ipk", lambda _: ["MapA", "MapB"])
    monkeypatch.setattr(archive_ipk.ArchiveIPKExtractor, "extract", lambda self, _: extracted.parent.parent)
    monkeypatch.setattr(normalizer, "normalize", lambda root, codename=None, search_root=None: _build_map(codename or "MapA"))
    monkeypatch.setattr(BatchInstallWorker, "_install_map_synchronously", lambda self, map_data: None)

    worker = BatchInstallWorker(
        batch_source_dir=ipk,
        target_game_dir=tmp_path / "game",
        config=AppConfig(cache_directory=tmp_path / "cache"),
    )
    progress: list[int] = []
    worker.progress.connect(lambda value: progress.append(value))
    worker.run()
    assert progress
    assert progress[0] > 0
    assert progress[-1] == 100
    assert all(a <= b for a, b in zip(progress, progress[1:]))
