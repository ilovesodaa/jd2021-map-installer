from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from jd2021_installer.extractors.jdnext_unitypy import unpack_jdnext_bundle_with_unitypy


class _FakeImage:
    def save(self, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b"PNG")


class _FakeObj:
    def __init__(self, type_name: str, path_id: int, obj_payload, name_hint: str = "") -> None:
        self.type = SimpleNamespace(name=type_name)
        self.path_id = path_id
        self._payload = obj_payload
        self._name_hint = name_hint

    def parse_as_object(self):
        return self._payload

    def parse_as_dict(self):
        return {"type": self.type.name, "path_id": self.path_id}

    def peek_name(self):
        return self._name_hint


class _FakeEnv:
    def __init__(self, objects):
        self.objects = objects


def test_unpack_jdnext_bundle_with_fake_unitypy(monkeypatch, tmp_path: Path):
    bundle = tmp_path / "mapPackage.bundle"
    bundle.write_bytes(b"fake")

    texture_obj = SimpleNamespace(m_Name="Cover", image=_FakeImage())
    audio_obj = SimpleNamespace(samples={"song.wav": b"WAVDATA"})
    text_obj = SimpleNamespace(m_Name="Config", m_Script="hello")

    fake_env = _FakeEnv(
        [
            _FakeObj("Texture2D", 1, texture_obj),
            _FakeObj("AudioClip", 2, audio_obj),
            _FakeObj("TextAsset", 3, text_obj),
            _FakeObj("MonoBehaviour", 4, SimpleNamespace()),
            _FakeObj("SomethingUnknown", 5, SimpleNamespace()),
        ]
    )

    fake_unitypy = SimpleNamespace(load=lambda _src: fake_env)
    monkeypatch.setitem(sys.modules, "UnityPy", fake_unitypy)

    out = tmp_path / "out"
    summary = unpack_jdnext_bundle_with_unitypy(bundle, out)

    assert summary.total_objects == 5
    assert summary.exported_objects == 5
    assert summary.textures == 1
    assert summary.audio_clips == 1
    assert summary.text_assets == 1
    assert summary.mono_behaviours == 1
    assert (out / "textures" / "Cover.png").exists()
    assert (out / "audio" / "song.wav").exists()
    assert (out / "text" / "Config.txt").exists()
    assert (out / "summary.json").exists()
    assert (out / "objects_index.json").exists()


def test_unpack_raises_for_missing_bundle(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        unpack_jdnext_bundle_with_unitypy(tmp_path / "missing.bundle", tmp_path / "out")
