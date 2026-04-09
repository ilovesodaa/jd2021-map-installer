from __future__ import annotations

from pathlib import Path

from jd2021_installer.installers import media_processor as mp
from jd2021_installer.core.exceptions import MediaProcessingError


def test_extract_ckd_audio_finds_magic_beyond_512_bytes(tmp_path: Path) -> None:
    ckd = tmp_path / "song.wav.ckd"
    out = tmp_path / "out"

    # Simulate CKD with a large metadata block before real RIFF payload.
    payload = b"A" * 2048 + b"RIFF" + b"B" * 128
    ckd.write_bytes(b"H" * mp.CKD_HEADER_SIZE + payload)

    decoded = mp.extract_ckd_audio_v1(ckd, out)

    assert decoded is not None
    decoded_path = Path(decoded)
    assert decoded_path.exists()
    assert decoded_path.suffix.lower() == ".wav"
    assert decoded_path.read_bytes().startswith(b"RIFF")


def test_extract_ckd_audio_uses_ffmpeg_fallback_when_vgmstream_missing(
    tmp_path: Path, monkeypatch
) -> None:
    ckd = tmp_path / "song.wav.ckd"
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)

    # No RIFF/Ogg magic in payload to force proprietary path.
    ckd.write_bytes(b"H" * mp.CKD_HEADER_SIZE + b"X" * 1024)

    ffmpeg_out = out / "song_ffmpeg_fallback.wav"

    def _fake_ffmpeg_decode(payload_file: Path, output_wav: Path) -> bool:
        output_wav.write_bytes(b"RIFF" + b"X" * 32)
        return True

    monkeypatch.setattr(mp, "decode_xma2_audio", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("no vgmstream")))
    monkeypatch.setattr(mp, "_ffmpeg_decode_unknown_payload", _fake_ffmpeg_decode)

    decoded = mp.extract_ckd_audio_v1(ckd, out)

    assert decoded == str(ffmpeg_out)
    assert ffmpeg_out.exists()


def test_extract_ckd_audio_skips_second_vgm_retry_after_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    ckd = tmp_path / "song.wav.ckd"
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)

    # No RIFF/Ogg magic in payload to force proprietary path.
    ckd.write_bytes(b"H" * mp.CKD_HEADER_SIZE + b"X" * 2048)

    calls = {"decode": 0}

    def _fake_decode(*_args, **_kwargs):
        calls["decode"] += 1
        raise MediaProcessingError("vgmstream timed out after 45s decoding song.wav.ckd")

    ffmpeg_out = out / "song_ffmpeg_fallback.wav"

    def _fake_ffmpeg_decode(_payload_file: Path, output_wav: Path) -> bool:
        output_wav.write_bytes(b"RIFF" + b"X" * 64)
        return True

    monkeypatch.setattr(mp, "decode_xma2_audio", _fake_decode)
    monkeypatch.setattr(mp, "_ffmpeg_decode_unknown_payload", _fake_ffmpeg_decode)

    decoded = mp.extract_ckd_audio_v1(ckd, out)

    assert calls["decode"] == 1
    assert decoded == str(ffmpeg_out)
    assert ffmpeg_out.exists()
