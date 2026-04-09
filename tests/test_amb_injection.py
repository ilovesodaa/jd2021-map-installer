import sys
from pathlib import Path
import os
import shutil
import tempfile
import wave

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from unittest.mock import MagicMock
import jd2021_installer.installers.media_processor as mp
import jd2021_installer.installers.ambient_processor as ap
mp.run_ffmpeg = MagicMock()
mp.run_ffprobe = MagicMock()

from jd2021_installer.installers.media_processor import generate_intro_amb
from jd2021_installer.installers.ambient_processor import process_ambient_directory
from jd2021_installer.installers.ambient_processor import _inject_intro_amb_soundset_clip


def _write_test_wav(path: Path, duration_ms: int = 250) -> None:
    frames = int(round(48000 * (duration_ms / 1000.0)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(48000)
        wf.writeframes(b"\x00\x00\x00\x00" * frames)

def test_intro_generation_does_not_inject_audio_isc_actor():
    print("Testing intro generation does not inject audio ISC actor...")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        
        # 1. Create a dummy audio ISC
        isc_path = audio_dir / "TestMap_audio.isc"
        isc_content = '''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
\t<Scene>
\t\t<ACTORS NAME="Actor">
\t\t\t<Actor USERFRIENDLY="MusicTrack" />
\t\t</ACTORS>
\t\t<sceneConfigs>
\t\t\t<SceneConfigs />
\t\t</sceneConfigs>
\t</Scene>
</root>'''
        isc_path.write_text(isc_content)
        
        # dummy ogg
        ogg_path = tmp_path / "test.ogg"
        ogg_path.write_text("dummy")
        
        # 2. First generation
        generate_intro_amb(ogg_path, "TestMap", tmp_path, a_offset=-2.145, v_override=-2.145)
        
        content = isc_path.read_text()
        count = content.count("amb_testmap_intro.tpl")
        print(f"Intro actor refs after first generation: {count}")
        assert count == 0, "Intro AMB actor should not be injected in audio ISC"
        
        # 3. Second generation should remain actor-free
        generate_intro_amb(ogg_path, "TestMap", tmp_path, a_offset=-2.145, v_override=-2.145)
        
        content = isc_path.read_text()
        count = content.count("amb_testmap_intro.tpl")
        print(f"Intro actor refs after second generation: {count}")
        assert count == 0, "Intro AMB actor should not be injected in audio ISC"
        
        print("✓ Intro generation stays tape-driven")


def test_marker_preroll_controls_intro_duration_even_with_negative_offset():
    """When marker pre-roll exists, intro cut length should follow marker timing."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()

        isc_path = audio_dir / "Demo_audio.isc"
        isc_path.write_text(
            """<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene>
		<ACTORS NAME="Actor">
			<Actor USERFRIENDLY="MusicTrack" />
		</ACTORS>
		<sceneConfigs>
			<SceneConfigs />
		</sceneConfigs>
	</Scene>
</root>"""
        )

        ogg_path = tmp_path / "demo.ogg"
        ogg_path.write_text("dummy")

        mp.run_ffmpeg.reset_mock()
        generate_intro_amb(
            ogg_path,
            "Demo",
            tmp_path,
            a_offset=-4.974,
            v_override=-4.873,
            marker_preroll_ms=4974.0,
        )

        assert mp.run_ffmpeg.call_count == 1, "Expected AMB FFmpeg generation call"
        ffmpeg_args = mp.run_ffmpeg.call_args[0][0]
        t_idx = ffmpeg_args.index("-t")
        used_duration = float(ffmpeg_args[t_idx + 1])

        # Marker-based rule: use marker pre-roll (rounded to 3 decimals in command).
        assert used_duration == 4.974, f"Unexpected intro duration: {used_duration}"


def test_intro_generation_does_not_apply_forced_fadeout_filter():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        (audio_dir / "Demo_audio.isc").write_text(
            """<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>
<root><Scene><ACTORS NAME=\"Actor\"><Actor USERFRIENDLY=\"MusicTrack\" /></ACTORS><sceneConfigs><SceneConfigs /></sceneConfigs></Scene></root>""",
            encoding="utf-8",
        )

        ogg_path = tmp_path / "demo.ogg"
        ogg_path.write_text("dummy")

        mp.run_ffmpeg.reset_mock()
        generate_intro_amb(
            ogg_path,
            "Demo",
            tmp_path,
            a_offset=-4.974,
            v_override=-4.873,
            marker_preroll_ms=4974.0,
        )

        assert mp.run_ffmpeg.call_count == 1
        ffmpeg_args = mp.run_ffmpeg.call_args[0][0]
        assert "afade=t=out" not in " ".join(ffmpeg_args)


def test_process_ambient_directory_preserves_generated_intro_wav(monkeypatch):
    """A decoded source intro must not overwrite a generated intro WAV."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        source_dir = tmp_path / "source"
        target_dir = tmp_path / "target"
        source_wav_ckd = (
            source_dir
            / "cache"
            / "itf_cooked"
            / "pc"
            / "world"
            / "maps"
            / "testmap"
            / "audio"
            / "amb"
            / "amb_testmap_intro.wav.ckd"
        )
        source_wav_ckd.parent.mkdir(parents=True, exist_ok=True)
        source_wav_ckd.write_bytes(b"source intro ckd")

        audio_dir = target_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        (audio_dir / "testmap_audio.isc").write_text(
            """<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
	<Scene>
		<ACTORS NAME="Actor">
			<Actor USERFRIENDLY="MusicTrack" />
		</ACTORS>
		<sceneConfigs>
			<SceneConfigs />
		</sceneConfigs>
	</Scene>
</root>""",
            encoding="utf-8",
        )

        generated_intro = target_dir / "Audio" / "AMB" / "amb_testmap_intro.wav"
        _write_test_wav(generated_intro, duration_ms=432)
        original_bytes = generated_intro.read_bytes()

        decoded_intro = tmp_path / "decoded" / "amb_testmap_intro.wav"
        _write_test_wav(decoded_intro, duration_ms=2060)

        monkeypatch.setattr(mp, "extract_ckd_audio_v1", lambda *_args, **_kwargs: decoded_intro)

        process_ambient_directory(source_dir, target_dir, "testmap", attempt_enabled=True)

        assert generated_intro.read_bytes() == original_bytes


def test_existing_intro_clip_is_normalized_with_cutter_timing_for_jdu_mode():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        codename = "GetGetDown"
        map_lower = codename.lower()

        amb_dir = tmp_path / "Audio" / "AMB"
        amb_dir.mkdir(parents=True, exist_ok=True)
        (amb_dir / "AMB_GetGetDown_Intro.tpl").write_text("tpl", encoding="utf-8")

        trk_path = tmp_path / "Audio" / f"{codename}.trk"
        trk_path.parent.mkdir(parents=True, exist_ok=True)
        trk_path.write_text(
            """structure = { MusicTrackStructure = {
markers = { { VAL = 0 }, { VAL = 22677 }, { VAL = 45354 }, { VAL = 68031 }, { VAL = 90709 }, { VAL = 113386 }, { VAL = 136063 } },
startBeat = -6,
videoStartTime = -2.834000,
} }""",
            encoding="utf-8",
        )

        tape_path = tmp_path / "Cinematics" / f"{codename}_MainSequence.tape"
        tape_path.parent.mkdir(parents=True, exist_ok=True)
        tape_path.write_text(
            f"""params =
{{
    NAME = \"Tape\",
    Tape =
    {{
        Clips =
        {{
            {{
                NAME = \"SoundSetClip\",
                SoundSetClip =
                {{
                    Id = 1,
                    TrackId = 2,
                    IsActive = 1,
                    StartTime = -144,
                    Duration = 432,
                    SoundSetPath = \"world/maps/{map_lower}/audio/amb/amb_getgetdown_intro.tpl\",
                    SoundChannel = 0,
                    StartOffset = 0.000000,
                    StopsOnEnd = 0,
                    AccountedForDuration = 0,
                }},
            }},
        }},
        TapeClock = 0,
    }},
}}""",
            encoding="utf-8",
        )

        changed = _inject_intro_amb_soundset_clip(tmp_path, codename, attempt_enabled=True)
        assert changed is True

        updated = tape_path.read_text(encoding="utf-8")
        # Preserve existing clip timing when HideUserInterfaceClip is absent.
        assert "StartTime = -144" in updated
        assert "Duration = 432" in updated
        assert "StartOffset" not in updated


def test_process_ambient_directory_disabled_removes_intro_clip_from_tape():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        codename = "Balance"
        map_lower = codename.lower()

        source_dir = tmp_path / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        target_dir = tmp_path / "target"
        amb_dir = target_dir / "Audio" / "AMB"
        amb_dir.mkdir(parents=True, exist_ok=True)

        (amb_dir / "amb_balance_intro.tpl").write_text("intro", encoding="utf-8")
        (amb_dir / "amb_balance_intro.ilu").write_text("intro", encoding="utf-8")
        _write_test_wav(amb_dir / "amb_balance_intro.wav", duration_ms=900)

        (amb_dir / "amb_balance_outro.tpl").write_text("outro", encoding="utf-8")
        (amb_dir / "amb_balance_outro.ilu").write_text("outro", encoding="utf-8")
        _write_test_wav(amb_dir / "amb_balance_outro.wav", duration_ms=900)

        tape_path = target_dir / "Cinematics" / f"{codename}_MainSequence.tape"
        tape_path.parent.mkdir(parents=True, exist_ok=True)
        tape_path.write_text(
            f"""params =
{{
    NAME = \"Tape\",
    Tape =
    {{
        Clips =
        {{
            {{
                NAME = \"SoundSetClip\",
                SoundSetClip =
                {{
                    Id = 1,
                    TrackId = 2,
                    IsActive = 1,
                    StartTime = -354,
                    Duration = 1135,
                    SoundSetPath = \"world/maps/{map_lower}/audio/amb/amb_balance_intro.tpl\",
                    SoundChannel = 0,
                    StopsOnEnd = 0,
                    AccountedForDuration = 0,
                }},
            }},
            {{
                NAME = \"SoundSetClip\",
                SoundSetClip =
                {{
                    Id = 2,
                    TrackId = 3,
                    IsActive = 1,
                    StartTime = 11712,
                    Duration = 216,
                    SoundSetPath = \"world/maps/{map_lower}/audio/amb/amb_balance_outro.tpl\",
                    SoundChannel = 0,
                    StopsOnEnd = 0,
                    AccountedForDuration = 0,
                }},
            }},
        }},
        Tracks =
        {{
            {{
                TapeTrack =
                {{
                    Id = 2,
                    Name = \"AMB_Balance_Intro.tpl\",
                }},
            }},
            {{
                TapeTrack =
                {{
                    Id = 3,
                    Name = \"AMB_Balance_Outro.tpl\",
                }},
            }},
        }},
        TapeClock = 2,
    }},
}}""",
            encoding="utf-8",
        )

        process_ambient_directory(source_dir, target_dir, codename, attempt_enabled=False)

        updated_tape = tape_path.read_text(encoding="utf-8")
        assert "amb_balance_intro.tpl" not in updated_tape
        assert "AMB_Balance_Intro.tpl" not in updated_tape
        assert "amb_balance_outro.tpl" in updated_tape
        assert not (amb_dir / "amb_balance_intro.tpl").exists()
        assert not (amb_dir / "amb_balance_intro.ilu").exists()
        assert not (amb_dir / "amb_balance_intro.wav").exists()
        assert (amb_dir / "amb_balance_outro.tpl").exists()


def test_intro_clip_uses_tail_startoffset_for_long_intro_wav_without_hideui():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        codename = "BIRDSOFAFEATHER"
        map_lower = codename.lower()

        amb_dir = tmp_path / "Audio" / "AMB"
        amb_dir.mkdir(parents=True, exist_ok=True)
        (amb_dir / "amb_birdsofafeather_intro.tpl").write_text("tpl", encoding="utf-8")
        _write_test_wav(amb_dir / "amb_birdsofafeather_intro.wav", duration_ms=15000)

        tape_path = tmp_path / "Cinematics" / f"{codename}_MainSequence.tape"
        tape_path.parent.mkdir(parents=True, exist_ok=True)
        tape_path.write_text(
            f'''params =
{{
    NAME = "Tape",
    Tape =
    {{
        Clips = {{
            {{
                NAME = "SoundSetClip",
                SoundSetClip =
                {{
                    Id = 1,
                    TrackId = 2,
                    IsActive = 1,
                    StartTime = -288,
                    Duration = 240,
                    SoundSetPath = "world/maps/{map_lower}/audio/amb/amb_birdsofafeather_intro.tpl",
                    SoundChannel = 0,
                    StopsOnEnd = 0,
                    AccountedForDuration = 0,
                }},
            }},
        }},
        TapeClock = 0,
    }},
}}''',
            encoding="utf-8",
        )

        changed = _inject_intro_amb_soundset_clip(tmp_path, codename, attempt_enabled=True)
        assert changed is True

        updated = tape_path.read_text(encoding="utf-8")
        assert "StartTime = -288" in updated
        assert "Duration = 240" in updated
        # 15.000s wav with 0.240s clip should target the tail (~14.760s)
        assert "StartOffset = 14.760000" in updated


def test_intro_clip_tail_startoffset_uses_beat_scaled_duration_when_markers_exist():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        codename = "BIRDSOFAFEATHER"
        map_lower = codename.lower()

        amb_dir = tmp_path / "Audio" / "AMB"
        amb_dir.mkdir(parents=True, exist_ok=True)
        (amb_dir / "amb_birdsofafeather_intro.tpl").write_text("tpl", encoding="utf-8")
        _write_test_wav(amb_dir / "amb_birdsofafeather_intro.wav", duration_ms=15000)

        trk_path = tmp_path / "Audio" / f"{codename}.trk"
        trk_path.parent.mkdir(parents=True, exist_ok=True)
        trk_path.write_text(
            """structure = { MusicTrackStructure = {
markers = { { VAL = 0 }, { VAL = 27408 }, { VAL = 54816 }, { VAL = 82224 }, { VAL = 109632 }, { VAL = 137040 }, { VAL = 164448 }, { VAL = 191856 }, { VAL = 219264 }, { VAL = 246672 }, { VAL = 274080 }, { VAL = 301488 }, { VAL = 328896 }, { VAL = 356304 } },
startBeat = -12,
videoStartTime = -15.000000,
} }""",
            encoding="utf-8",
        )

        tape_path = tmp_path / "Cinematics" / f"{codename}_MainSequence.tape"
        tape_path.parent.mkdir(parents=True, exist_ok=True)
        tape_path.write_text(
            f'''params =
{{
    NAME = "Tape",
    Tape =
    {{
        Clips = {{
            {{
                NAME = "SoundSetClip",
                SoundSetClip =
                {{
                    Id = 1,
                    TrackId = 2,
                    IsActive = 1,
                    StartTime = -288,
                    Duration = 240,
                    SoundSetPath = "world/maps/{map_lower}/audio/amb/amb_birdsofafeather_intro.tpl",
                    SoundChannel = 0,
                    StopsOnEnd = 0,
                    AccountedForDuration = 0,
                }},
            }},
        }},
        TapeClock = 0,
    }},
}}''',
            encoding="utf-8",
        )

        changed = _inject_intro_amb_soundset_clip(tmp_path, codename, attempt_enabled=True)
        assert changed is True

        updated = tape_path.read_text(encoding="utf-8")
        # With beat-scaled timing: 240 units at 571ms/beat = 5710ms window.
        # 15.000s - 5.710s = 9.290s expected StartOffset.
        assert "StartOffset = 9.290000" in updated


def test_existing_intro_window_is_shifted_to_end_at_zero_when_it_ends_early():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        codename = "SweetbutPsycho"
        map_lower = codename.lower()

        amb_dir = tmp_path / "Audio" / "AMB"
        amb_dir.mkdir(parents=True, exist_ok=True)
        (amb_dir / "amb_sweetbutpsycho_intro.tpl").write_text("tpl", encoding="utf-8")

        trk_path = tmp_path / "Audio" / f"{codename}.trk"
        trk_path.parent.mkdir(parents=True, exist_ok=True)
        trk_path.write_text(
            """structure = { MusicTrackStructure = {
markers = { { VAL = 0 }, { VAL = 21648 }, { VAL = 43296 }, { VAL = 64944 }, { VAL = 86592 }, { VAL = 108240 }, { VAL = 129888 } },
startBeat = -13,
videoStartTime = -13.985000,
} }""",
            encoding="utf-8",
        )

        tape_path = tmp_path / "Cinematics" / f"{codename}_MainSequence.tape"
        tape_path.parent.mkdir(parents=True, exist_ok=True)
        tape_path.write_text(
            f'''params =
{{
    NAME = "Tape",
    Tape =
    {{
        Clips = {{
            {{
                NAME = "SoundSetClip",
                SoundSetClip =
                {{
                    Id = 1,
                    TrackId = 2,
                    IsActive = 1,
                    StartTime = -312,
                    Duration = 264,
                    SoundSetPath = "world/maps/{map_lower}/audio/amb/amb_sweetbutpsycho_intro.tpl",
                    SoundChannel = 0,
                    StopsOnEnd = 0,
                    AccountedForDuration = 0,
                }},
            }},
        }},
        TapeClock = 0,
    }},
}}''',
            encoding="utf-8",
        )

        changed = _inject_intro_amb_soundset_clip(tmp_path, codename, attempt_enabled=True)
        assert changed is True

        updated = tape_path.read_text(encoding="utf-8")
        assert "StartTime = -264" in updated
        assert "Duration = 264" in updated

if __name__ == "__main__":
    try:
        test_amb_injection_idempotency()
        print("\nALL AMB TESTS PASSED!")
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {e}")
        sys.exit(1)
