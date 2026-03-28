from __future__ import annotations

from pathlib import Path

import pytest

from jd2021_installer.extractors.manual_extractor import ManualExtractor
from jd2021_installer.ui.workers.pipeline_workers import _validate_ipk_media_presence


def test_manual_ipk_root_keeps_user_root(tmp_path: Path) -> None:
    root = tmp_path / "manual_ipk_root"
    (root / "world" / "maps" / "MapA").mkdir(parents=True)
    (root / "world" / "maps" / "MapB").mkdir(parents=True)
    (root / "MapB.ogg").write_bytes(b"a" * 1024)
    (root / "MapB_LOW.webm").write_bytes(b"v" * 1024)

    extractor = ManualExtractor(codename="MapB", source_type="ipk", root_dir=str(root))
    extracted = extractor.extract(tmp_path / "output")

    assert extracted == root


def test_manual_ipk_root_supports_legacy_world_jd_layout(tmp_path: Path) -> None:
    root = tmp_path / "manual_ipk_root"
    (root / "world" / "jd2015" / "SongX").mkdir(parents=True)
    (root / "world" / "jd2015" / "SongY").mkdir(parents=True)
    (root / "SongY.ogg").write_bytes(b"a" * 1024)
    (root / "SongY_LOW.webm").write_bytes(b"v" * 1024)

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

    extractor = ManualExtractor(codename="WrongMap", source_type="ipk", root_dir=str(root))
    extracted = extractor.extract(tmp_path / "output")

    assert extracted == root
    assert extractor.get_codename() == "MapA"


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
