from pathlib import Path

from jd2021_installer.installers.media_processor import copy_moves


def _write_binary_gesture(path: Path, size: int = 512) -> None:
    # Non-text-like binary payload to emulate valid Kinect gesture data.
    pattern = bytes([0x89, 0x10, 0x02, 0xFF, 0x00, 0xC3, 0x7E, 0x19])
    payload = (pattern * ((size // len(pattern)) + 1))[:size]
    path.write_bytes(payload)


def test_copy_moves_only_accepts_kinect_v1_v2_gestures(tmp_path: Path) -> None:
    src = tmp_path / "source_moves"
    x360 = src / "x360"
    durango = src / "durango"
    scarlett = src / "scarlett"
    x360.mkdir(parents=True)
    durango.mkdir(parents=True)
    scarlett.mkdir(parents=True)

    _write_binary_gesture(x360 / "x360_ok.gesture")
    _write_binary_gesture(durango / "durango_ok.gesture")
    _write_binary_gesture(scarlett / "scarlett_should_skip.gesture")

    (x360 / "x360_ok.msm").write_text("msm", encoding="utf-8")
    (scarlett / "scarlett_ok.msm").write_text("msm", encoding="utf-8")

    target = tmp_path / "game_map"
    copied = copy_moves(src, target)
    pc = target / "timeline" / "moves" / "pc"

    assert (pc / "x360_ok.gesture").exists()
    assert (pc / "durango_ok.gesture").exists()
    assert not (pc / "scarlett_should_skip.gesture").exists()

    # MSM is still copied cross-platform.
    assert (pc / "x360_ok.msm").exists()
    assert (pc / "scarlett_ok.msm").exists()

    assert copied == 4


def test_copy_moves_rejects_text_like_or_tiny_gesture_files(tmp_path: Path) -> None:
    src = tmp_path / "source_moves"
    x360 = src / "x360"
    x360.mkdir(parents=True)

    # Tiny and text-like gesture payloads should be rejected.
    (x360 / "tiny_bad.gesture").write_bytes(b"\x01\x02\x03")
    (x360 / "text_bad.gesture").write_text('{"gesture": true}', encoding="utf-8")

    # Valid gesture should still pass.
    _write_binary_gesture(x360 / "good.gesture")

    target = tmp_path / "game_map"
    copied = copy_moves(src, target)
    pc = target / "timeline" / "moves" / "pc"

    assert (pc / "good.gesture").exists()
    assert not (pc / "tiny_bad.gesture").exists()
    assert not (pc / "text_bad.gesture").exists()
    assert copied == 1
