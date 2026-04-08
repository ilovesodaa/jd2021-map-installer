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

def test_amb_injection_idempotency():
    print("Testing AMB Injection Idempotency...")
    
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
        
        # 2. First injection
        generate_intro_amb(ogg_path, "TestMap", tmp_path, a_offset=-2.145, v_override=-2.145)
        
        content = isc_path.read_text()
        count = content.count("amb_testmap_intro.tpl")
        print(f"Injection count 1: {count}")
        assert count == 1, "First injection failed"
        assert (
            'LUA="World/MAPS/TestMap/audio/AMB/amb_testmap_intro.tpl"' in content
        ), "Intro AMB actor LUA path mismatch"
        
        # 3. Second injection (should be skipped)
        generate_intro_amb(ogg_path, "TestMap", tmp_path, a_offset=-2.145, v_override=-2.145)
        
        content = isc_path.read_text()
        count = content.count("amb_testmap_intro.tpl")
        print(f"Injection count 2: {count}")
        assert count == 1, "Second injection was NOT skipped (redundant!)"
        assert content.count('USERFRIENDLY="amb_testmap_intro"') == 1, "Actor duplicated"
        
        print("✓ AMB Injection Idempotency OK")


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
        # Cutter-style timing: marker[abs(startBeat)] / 48 + 85 => 2919.646 ms -> 2920 ms rounded.
        assert "StartTime = -2920" in updated
        assert "Duration = 2920" in updated
        assert "StartOffset" not in updated

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
