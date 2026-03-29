from __future__ import annotations

from pathlib import Path

import pytest

from jd2021_installer.core.exceptions import DownloadError
from jd2021_installer.extractors.archive_ipk import ArchiveIPKExtractor
from jd2021_installer.extractors.manual_extractor import ManualExtractor
from jd2021_installer.ui.workers.pipeline_workers import (
    ExtractAndNormalizeWorker,
    _validate_ipk_media_presence,
    reprocess_audio,
)


def test_manual_ipk_root_keeps_user_root(tmp_path: Path) -> None:
    root = tmp_path / "manual_ipk_root"
    (root / "world" / "maps" / "MapA").mkdir(parents=True)
    (root / "world" / "maps" / "MapB").mkdir(parents=True)
    (root / "MapB.ogg").write_bytes(b"a" * 1024)
    (root / "MapB_LOW.webm").write_bytes(b"v" * 1024)
    (root / "MapB_musictrack.tpl.ckd").write_bytes(b"m")

    extractor = ManualExtractor(codename="MapB", source_type="ipk", root_dir=str(root))
    extracted = extractor.extract(tmp_path / "output")

    assert extracted == root


def test_manual_ipk_root_supports_legacy_world_jd_layout(tmp_path: Path) -> None:
    root = tmp_path / "manual_ipk_root"
    (root / "world" / "jd2015" / "SongX").mkdir(parents=True)
    (root / "world" / "jd2015" / "SongY").mkdir(parents=True)
    (root / "SongY.ogg").write_bytes(b"a" * 1024)
    (root / "SongY_LOW.webm").write_bytes(b"v" * 1024)
    (root / "SongY_musictrack.tpl.ckd").write_bytes(b"m")

    extractor = ManualExtractor(codename="SongY", source_type="ipk", root_dir=str(root))
    extracted = extractor.extract(tmp_path / "output")

    assert extracted == root
    assert extractor.get_codename() == "SongY"


def test_manual_ipk_root_multimap_codename_mismatch_falls_back(tmp_path: Path) -> None:
    root = tmp_path / "manual_ipk_root"
    (root / "world" / "maps" / "MapA").mkdir(parents=True)
    (root / "world" / "maps" / "MapB").mkdir(parents=True)
    (root / "MapA.ogg").write_bytes(b"a" * 1024)
    (root / "MapA_LOW.webm").write_bytes(b"v" * 1024)
    (root / "MapA_musictrack.tpl.ckd").write_bytes(b"m")

    extractor = ManualExtractor(codename="WrongMap", source_type="ipk", root_dir=str(root))
    extracted = extractor.extract(tmp_path / "output")

    assert extracted == root
    assert extractor.get_codename() == "MapA"


def test_manual_ipk_root_missing_required_media_is_fatal(tmp_path: Path) -> None:
    root = tmp_path / "manual_ipk_root"
    (root / "world" / "maps" / "MapA").mkdir(parents=True)

    extractor = ManualExtractor(codename="MapA", source_type="ipk", root_dir=str(root))

    with pytest.raises(DownloadError, match="Musictrack CKD is required"):
        extractor.extract(tmp_path / "output")


def test_archive_worker_does_not_swallow_unexpected_extraction_errors(tmp_path: Path) -> None:
    ipk_file = tmp_path / "mapa.ipk"
    ipk_file.write_bytes(b"\x50\xEC\x12\xBA" + b"\x00" * 64)

    extractor = ArchiveIPKExtractor(ipk_file)

    def _explode(_output_dir: Path) -> Path:
        raise RuntimeError("boom")

    extractor.extract = _explode  # type: ignore[method-assign]

    worker = ExtractAndNormalizeWorker(extractor=extractor, output_dir=tmp_path / "work")
    errors: list[str] = []
    finished_payloads: list[object] = []

    worker.error.connect(errors.append)
    worker.finished.connect(finished_payloads.append)
    worker.run()

    assert errors and "boom" in errors[0]
    assert finished_payloads and finished_payloads[0] is None


def test_ipk_media_validation_requires_audio(tmp_path: Path) -> None:
    extract_root = tmp_path / "extracted"
    extract_root.mkdir(parents=True)
    (extract_root / "MapA_LOW.webm").write_bytes(b"webm")

    warnings = _validate_ipk_media_presence(extract_root, "MapA", None)
    assert any("No audio file found after IPK extraction" in w for w in warnings)


def test_ipk_media_validation_requires_video(tmp_path: Path) -> None:
    extract_root = tmp_path / "extracted"
    extract_root.mkdir(parents=True)
    (extract_root / "MapA.ogg").write_bytes(b"ogg")

    warnings = _validate_ipk_media_presence(extract_root, "MapA", None)
    assert any("No gameplay video (.webm) found after IPK extraction" in w for w in warnings)


def test_ipk_media_validation_accepts_sidecar_audio_search_root(tmp_path: Path) -> None:
    extract_root = tmp_path / "extracted"
    source_root = tmp_path / "source"
    extract_root.mkdir(parents=True)
    source_root.mkdir(parents=True)

    (extract_root / "MapA_HIGH.webm").write_bytes(b"webm")
    (source_root / "MapA.ogg").write_bytes(b"ogg")

    _validate_ipk_media_presence(extract_root, "MapA", source_root)


def test_reprocess_audio_recovers_missing_ipk_audio_from_source_tree(
    tmp_path: Path,
    sample_normalized_data,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "temp_extraction"
    recovered_audio = (
        source_root
        / "cache"
        / "itf_cooked"
        / "x360"
        / "world"
        / "maps"
        / "sweetbutpsycho"
        / "audio"
        / "sweetbutpsycho.wav.ckd"
    )
    recovered_audio.parent.mkdir(parents=True, exist_ok=True)
    recovered_audio.write_bytes(b"X" * 128)

    map_data = sample_normalized_data
    map_data.codename = "sweetbutpsycho"
    map_data.source_dir = source_root
    map_data.media.audio_path = None

    called: dict[str, Path] = {}

    monkeypatch.setattr(
        "jd2021_installer.ui.workers.pipeline_workers.write_game_files",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "jd2021_installer.installers.media_processor.convert_audio",
        lambda audio_path, *_args, **_kwargs: called.setdefault("audio", Path(audio_path)),
    )
    monkeypatch.setattr(
        "jd2021_installer.installers.media_processor.generate_intro_amb",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "jd2021_installer.installers.media_processor.extract_amb_clips",
        lambda *_args, **_kwargs: 0,
    )

    reprocess_audio(map_data, tmp_path / "game_map", a_offset=0.0, config=None)

    assert map_data.media.audio_path == recovered_audio
    assert called["audio"] == recovered_audio
