from __future__ import annotations

import struct
from pathlib import Path

from jd2021_installer.extractors.archive_ipk import inspect_ipk


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
