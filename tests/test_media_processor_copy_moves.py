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


def test_copy_moves_synthesizes_fallback_gestures_when_none_survive(tmp_path: Path) -> None:
    game_root = tmp_path / "maps_root"
    target = game_root / "jdnext_map"

    src = tmp_path / "source_moves"
    scarlett = src / "scarlett"
    durango = src / "durango"
    scarlett.mkdir(parents=True)
    durango.mkdir(parents=True)

    # Unsupported platform gestures are collected as expected names.
    _write_binary_gesture(scarlett / "jdnext_a.gesture")
    _write_binary_gesture(scarlett / "jdnext_b.gesture")

    # MSM files are copied, but fallback gesture names should come from dtape.
    (durango / "unused_from_msm_only.msm").write_text("msm", encoding="utf-8")

    timeline = target / "timeline"
    timeline.mkdir(parents=True, exist_ok=True)
    (timeline / "jdnext_map_TML_Dance.dtape").write_text(
        'params = { Tape = { Clips = {\n'
        '  { MotionClip = { ClassifierPath = "world/maps/jdnext_map/timeline/moves/jdnext_c.msm" } },\n'
        '  { MotionClip = { ClassifierPath = "world/maps/jdnext_map/timeline/moves/jdnext_d.gesture" } }\n'
        '} } }',
        encoding="utf-8",
    )

    copied = copy_moves(src, target)
    pc = target / "timeline" / "moves" / "pc"

    assert (pc / "jdnext_a.gesture").exists()
    assert (pc / "jdnext_b.gesture").exists()
    assert (pc / "jdnext_c.gesture").exists()
    assert (pc / "jdnext_d.gesture").exists()
    assert (pc / "unused_from_msm_only.msm").exists()
    assert not (pc / "unused_from_msm_only.gesture").exists()
    assert copied == 5


def test_copy_moves_uses_bundled_generic_template(tmp_path: Path) -> None:
    src = tmp_path / "source_moves"
    scarlett = src / "scarlett"
    scarlett.mkdir(parents=True)
    _write_binary_gesture(scarlett / "need_fallback.gesture")

    target = tmp_path / "game_map"
    copied = copy_moves(src, target)

    pc = target / "timeline" / "moves" / "pc"
    out = pc / "need_fallback.gesture"
    assert out.exists()
    assert copied == 1

    bundled = Path(__file__).resolve().parents[1] / "assets" / "gesture_templates" / "discorope.gesture"
    assert bundled.exists()
    assert out.read_bytes() == bundled.read_bytes()
