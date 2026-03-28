from __future__ import annotations

from pathlib import Path

import pytest

from jd2021_installer.core.exceptions import DownloadError
from jd2021_installer.extractors.manual_extractor import ManualExtractor
from jd2021_installer.ui.workers.pipeline_workers import _validate_ipk_media_presence


def test_manual_ipk_root_keeps_user_root(tmp_path: Path) -> None:
    root = tmp_path / "manual_ipk_root"
    (root / "world" / "maps" / "MapA").mkdir(parents=True)
    (root / "world" / "maps" / "MapB").mkdir(parents=True)

    extractor = ManualExtractor(codename="MapB", source_type="ipk", root_dir=str(root))
    extracted = extractor.extract(tmp_path / "output")

    assert extracted == root


def test_manual_ipk_root_raises_on_multimap_codename_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "manual_ipk_root"
    (root / "world" / "maps" / "MapA").mkdir(parents=True)
    (root / "world" / "maps" / "MapB").mkdir(parents=True)

    extractor = ManualExtractor(codename="WrongMap", source_type="ipk", root_dir=str(root))

    with pytest.raises(DownloadError, match="multiple maps"):
        extractor.extract(tmp_path / "output")


def test_ipk_media_validation_requires_audio(tmp_path: Path) -> None:
    extract_root = tmp_path / "extracted"
    extract_root.mkdir(parents=True)
    (extract_root / "MapA_LOW.webm").write_bytes(b"webm")

    with pytest.raises(RuntimeError, match="No audio file found after IPK extraction"):
        _validate_ipk_media_presence(extract_root, "MapA", None)


def test_ipk_media_validation_requires_video(tmp_path: Path) -> None:
    extract_root = tmp_path / "extracted"
    extract_root.mkdir(parents=True)
    (extract_root / "MapA.ogg").write_bytes(b"ogg")

    with pytest.raises(RuntimeError, match=r"No gameplay video \(.webm\) found after IPK extraction"):
        _validate_ipk_media_presence(extract_root, "MapA", None)


def test_ipk_media_validation_accepts_sidecar_audio_search_root(tmp_path: Path) -> None:
    extract_root = tmp_path / "extracted"
    source_root = tmp_path / "source"
    extract_root.mkdir(parents=True)
    source_root.mkdir(parents=True)

    (extract_root / "MapA_HIGH.webm").write_bytes(b"webm")
    (source_root / "MapA.ogg").write_bytes(b"ogg")

    _validate_ipk_media_presence(extract_root, "MapA", source_root)
