from __future__ import annotations

import struct
from pathlib import Path

import pytest

from jd2021_installer.core.exceptions import IPKExtractionError
from jd2021_installer.extractors.archive_ipk import inspect_ipk, validate_ipk_magic


def _pack_u32(value: int) -> bytes:
    return struct.pack(">I", value)


def _pack_u64(value: int) -> bytes:
    return struct.pack(">Q", value)


def _build_fake_ipk(path: Path, entries: list[tuple[str, str]]) -> None:
    header = b"".join(
        [
            b"\x50\xEC\x12\xBA",
            _pack_u32(1),
            _pack_u32(0),
            _pack_u32(0),
            _pack_u32(len(entries)),
            _pack_u32(0),
            _pack_u32(0),
            _pack_u32(0),
            _pack_u32(0),
            _pack_u32(0),
            _pack_u32(0),
            _pack_u32(len(entries)),
        ]
    )

    body = bytearray()
    for file_name, path_name in entries:
        file_bytes = file_name.encode("utf-8")
        path_bytes = path_name.encode("utf-8")
        body += _pack_u32(0)
        body += _pack_u32(0)
        body += _pack_u32(0)
        body += _pack_u64(0)
        body += _pack_u64(0)
        body += _pack_u32(len(file_bytes))
        body += file_bytes
        body += _pack_u32(len(path_bytes))
        body += path_bytes
        body += _pack_u32(0)
        body += _pack_u32(0)

    path.write_bytes(header + bytes(body))


def test_inspect_ipk_detects_maps_from_swapped_path_fields(tmp_path: Path) -> None:
    ipk_path = tmp_path / "bundle_swapped.ipk"
    _build_fake_ipk(
        ipk_path,
        [
            ("world/maps/mapa/audio", "mapa_musictrack.tpl.ckd"),
            ("world/maps/mapb/audio", "mapb_musictrack.tpl.ckd"),
        ],
    )

    discovered = inspect_ipk(ipk_path)
    assert discovered == ["mapa", "mapb"]


def test_inspect_ipk_detects_legacy_world_jd_layout(tmp_path: Path) -> None:
    ipk_path = tmp_path / "legacy_bundle.ipk"
    _build_fake_ipk(
        ipk_path,
        [
            ("world/jd2015/songx/audio", "songx_musictrack.tpl.ckd"),
            ("world/jd2015/songy/audio", "songy_musictrack.tpl.ckd"),
        ],
    )

    discovered = inspect_ipk(ipk_path)
    assert discovered == ["songx", "songy"]


def test_validate_ipk_magic_rejects_invalid_archive(tmp_path: Path) -> None:
    invalid_ipk = tmp_path / "invalid.ipk"
    invalid_ipk.write_bytes(b"BAD!" + b"\x00" * 16)

    with pytest.raises(IPKExtractionError, match="bad magic bytes"):
        validate_ipk_magic(invalid_ipk)


def test_validate_ipk_magic_accepts_valid_archive_header(tmp_path: Path) -> None:
    valid_ipk = tmp_path / "valid.ipk"
    valid_ipk.write_bytes(b"\x50\xEC\x12\xBA" + b"\x00" * 16)

    validate_ipk_magic(valid_ipk)
