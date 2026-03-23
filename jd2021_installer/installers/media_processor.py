"""Media processor — FFmpeg and Pillow wrappers for map asset processing.

Handles video transcoding, audio format conversion, image processing,
and preview generation.  All heavy subprocess work is designed to run
in a background QThread.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Callable, Optional

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.exceptions import MediaProcessingError

logger = logging.getLogger("jd2021.installers.media_processor")


# ---------------------------------------------------------------------------
# FFmpeg / FFprobe subprocess wrappers
# ---------------------------------------------------------------------------

def run_ffmpeg(
    args: list[str],
    config: Optional[AppConfig] = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    """Run an FFmpeg command and return the result.

    Raises MediaProcessingError on failure.
    """
    cfg = config or AppConfig()
    cmd = [cfg.ffmpeg_path] + args
    logger.debug("FFmpeg: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.returncode != 0:
            raise MediaProcessingError(
                f"FFmpeg failed (exit {result.returncode}): {result.stderr[:500]}"
            )
        return result
    except subprocess.TimeoutExpired:
        raise MediaProcessingError(f"FFmpeg timed out after {timeout}s")
    except FileNotFoundError:
        raise MediaProcessingError(
            f"FFmpeg not found at '{cfg.ffmpeg_path}'. "
            "Ensure FFmpeg is installed and in PATH."
        )


def run_ffprobe(
    args: list[str],
    config: Optional[AppConfig] = None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run an FFprobe command and return the result."""
    cfg = config or AppConfig()
    cmd = [cfg.ffprobe_path] + args

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return result
    except FileNotFoundError:
        raise MediaProcessingError(
            f"FFprobe not found at '{cfg.ffprobe_path}'. "
            "Ensure FFmpeg is installed and in PATH."
        )


def get_video_duration(video_path: str | Path, config: Optional[AppConfig] = None) -> float:
    """Get video duration in seconds using FFprobe."""
    result = run_ffprobe(
        [
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(video_path),
        ],
        config=config,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise MediaProcessingError(f"Cannot determine duration of {video_path}")


# ---------------------------------------------------------------------------
# Video processing
# ---------------------------------------------------------------------------

def copy_video(
    src_path: str | Path,
    dst_path: str | Path,
) -> Path:
    """Copy a video file to the destination, creating dirs as needed."""
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise MediaProcessingError(f"Source video not found: {src}")

    shutil.copy2(src, dst)
    logger.info("Copied video: %s -> %s", src.name, dst)
    return dst


def generate_map_preview(
    video_path: str | Path,
    output_path: str | Path,
    start_time: float = 0.0,
    duration: float = 30.0,
    config: Optional[AppConfig] = None,
) -> Path:
    """Generate a map preview video clip from the main video.

    Creates a lower-quality excerpt for the map selection screen.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    run_ffmpeg(
        [
            "-y",
            "-i", str(video_path),
            "-ss", str(start_time),
            "-t", str(duration),
            "-c:v", "libvpx-vp9",
            "-b:v", "1M",
            "-an",
            str(output),
        ],
        config=config,
    )
    return output


# ---------------------------------------------------------------------------
# Audio processing
# ---------------------------------------------------------------------------

def copy_audio(
    src_path: str | Path,
    dst_path: str | Path,
) -> Path:
    """Copy or transcode an audio file to the destination."""
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise MediaProcessingError(f"Source audio not found: {src}")

    # JD2017 PC requires .wav for stable engine compatibility.
    # If source is .ogg but we are writing .wav, let's transcode:
    if src.suffix.lower() == ".ogg" and dst.suffix.lower() == ".wav":
        logger.info("Transcoding OGG -> WAV: %s -> %s", src.name, dst.name)
        run_ffmpeg([
            "-y",
            "-i", str(src),
            "-c:a", "pcm_s16le",
            "-ar", "48000",
            str(dst)
        ])
    else:
        shutil.copy2(src, dst)
        logger.info("Copied audio: %s -> %s", src.name, dst)
        
    return dst


def generate_audio_preview(
    audio_path: str | Path,
    output_path: str | Path,
    start_time: float = 0.0,
    duration: float = 30.0,
    fade_out: float = 2.0,
    config: Optional[AppConfig] = None,
) -> Path:
    """Generate an audio preview with fade-out."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    run_ffmpeg(
        [
            "-y",
            "-i", str(audio_path),
            "-ss", str(start_time),
            "-t", str(duration),
            "-af", f"afade=t=out:st={duration - fade_out}:d={fade_out}",
            "-c:a", "libvorbis",
            str(output),
        ],
        config=config,
    )
    return output


def convert_audio(
    audio_path: str | Path,
    map_name: str,
    target_dir: str | Path,
    a_offset: float = 0.0,
    config: Optional[AppConfig] = None,
) -> None:
    """Ported from V1: FFmpeg-based audio padding/trimming.
    
    Generates both .wav (for PC) and .ogg (for menu preview).
    """
    audio_path = Path(audio_path)
    target_dir = Path(target_dir)
    wav_out = target_dir / "Audio" / f"{map_name}.wav"
    ogg_out = target_dir / "Audio" / f"{map_name}.ogg"
    wav_out.parent.mkdir(parents=True, exist_ok=True)

    if not ogg_out.exists():
        if audio_path.suffix.lower() == ".ogg":
            logger.info("Copying menu preview OGG...")
            shutil.copy2(audio_path, ogg_out)
        else:
            logger.info("Converting to menu preview OGG...")
            run_ffmpeg(["-y", "-i", str(audio_path), str(ogg_out)], config=config)

    if a_offset == 0.0:
        logger.info("Converting to 48kHz WAV (no offset)...")
        run_ffmpeg(["-y", "-i", str(audio_path), "-ar", "48000", str(wav_out)], config=config)
    elif a_offset < 0:
        trim_s = abs(a_offset)
        logger.info("Converting to 48kHz WAV (trimming first %.3fs)...", trim_s)
        run_ffmpeg([
            "-y", "-i", str(audio_path), 
            "-ss", f"{trim_s:.6f}",
            "-ar", "48000", str(wav_out)
        ], config=config)
    else:
        delay_ms = int(a_offset * 1000)
        logger.info("Converting to 48kHz WAV (padding %dms silence)...", delay_ms)
        af_filter = f"adelay={delay_ms}|{delay_ms},asetpts=PTS-STARTPTS"
        run_ffmpeg([
            "-y", "-i", str(audio_path), 
            "-af", af_filter,
            "-ar", "48000", str(wav_out)
        ], config=config)


def generate_intro_amb(
    ogg_path: str | Path,
    map_name: str,
    target_dir: str | Path,
    a_offset: float,
    v_override: Optional[float] = None,
    marker_preroll_ms: Optional[float] = None,
    config: Optional[AppConfig] = None,
) -> None:
    """Ported from V1: Generate an intro AMB WAV for negative videoStartTime.
    
    Strategy: AMB plays from t=0, covering silence before main WAV.
    """
    ogg_path = Path(ogg_path)
    target_dir = Path(target_dir)
    map_lower = map_name.lower()
    amb_dir = target_dir / "Audio" / "AMB"

    # If no pre-roll silence, silence any existing intro WAV
    if a_offset >= 0 and (v_override is None or v_override >= 0):
        if amb_dir.exists():
            for wav in amb_dir.glob("*_intro.wav"):
                with wave.open(str(wav), 'w') as wf:
                    wf.setnchannels(2)
                    wf.setsampwidth(2)
                    wf.setframerate(48000)
                    wf.writeframes(b'\x00\x00\x00\x00' * 4800)
        return

    amb_dir.mkdir(parents=True, exist_ok=True)

    intro_dur = abs(v_override) if v_override is not None and v_override < 0 else abs(a_offset)
    audio_delay = max(0.0, intro_dur - abs(a_offset))
    
    if marker_preroll_ms is not None:
        audio_content_dur = marker_preroll_ms / 1000.0
        fade_start = audio_delay + audio_content_dur - 0.2
        logger.info("Using marker-based AMB duration: %.3fs", audio_content_dur)
    else:
        audio_content_dur = abs(a_offset) + 1.355
        fade_start = audio_delay + abs(a_offset) + 1.155
    
    amb_duration = audio_delay + audio_content_dur

    intro_wavs = list(amb_dir.glob("*_intro.wav"))
    intro_tpls = list(amb_dir.glob("*_intro.tpl"))

    if intro_tpls:
        intro_name = intro_tpls[0].stem
        intro_wav = intro_wavs[0] if intro_wavs else amb_dir / f"{intro_name}.wav"
    else:
        if intro_wavs:
            intro_wav = intro_wavs[0]
            intro_name = intro_wav.stem
        else:
            intro_name = f"amb_{map_lower}_intro"
            intro_wav = amb_dir / f"{intro_name}.wav"

        wav_rel_path = f"world/maps/{map_lower}/audio/amb/{intro_wav.name}"
        ilu_content = f'''DESCRIPTOR =
{{
\t{{
\t\tNAME = "SoundDescriptor_Template",
\t\tSoundDescriptor_Template =
\t\t{{
\t\t\tname = "{intro_name}",
\t\t\tvolume = 0,
\t\t\tcategory = "amb",
\t\t\tlimitCategory = "",
\t\t\tlimitMode = 0,
\t\t\tmaxInstances = 4294967295,
\t\t\tfiles =
\t\t\t{{
\t\t\t\t{{
\t\t\t\t\tVAL = "{wav_rel_path}",
\t\t\t\t}},
\t\t\t}},
\t\t\tserialPlayingMode = 0,
\t\t\tserialStoppingMode = 0,
\t\t\tparams =
\t\t\t{{
\t\t\t\tNAME = "SoundParams",
\t\t\t\tSoundParams =
\t\t\t\t{{
\t\t\t\t\tloop = 0,
\t\t\t\t\tplayMode = 1,
\t\t\t\t\tplayModeInput = "",
\t\t\t\t\trandomVolMin = 0,
\t\t\t\t\trandomVolMax = 0,
\t\t\t\t\tdelay = 0,
\t\t\t\t\trandomDelay = 0,
\t\t\t\t\trandomPitchMin = 1,
\t\t\t\t\trandomPitchMax = 1,
\t\t\t\t\tfadeInTime = 0,
\t\t\t\t\tfadeOutTime = 0,
\t\t\t\t\tfilterFrequency = 0,
\t\t\t\t\tfilterType = 2,
\t\t\t\t\ttransitionSampleOffset = 0,
\t\t\t\t}},
\t\t\t}},
\t\t\tpauseInsensitiveFlags = 0,
\t\t\toutDevices = 4294967295,
\t\t\tsoundPlayAfterdestroy = 0,
\t\t}},
\t}},
}}
appendTable(component.SoundComponent_Template.soundList,DESCRIPTOR)'''

        tpl_content = f'''params=
{{
\tNAME="Actor_Template",
\tActor_Template=
\t{{
\t\tCOMPONENTS=
\t\t{{
\t\t}}
\t}}
}}
includeReference("EngineData/Misc/Components/SoundComponent.ilu")
includeReference("world/maps/{map_name}/audio/amb/{intro_name}.ilu")'''

        (amb_dir / f"{intro_name}.ilu").write_text(ilu_content, encoding="utf-8")
        (amb_dir / f"{intro_name}.tpl").write_text(tpl_content, encoding="utf-8")
        logger.info("Created intro AMB files: %s.tpl/.ilu", intro_name)

    # Always inject AMB actor if not present
    audio_isc_path = target_dir / "Audio" / f"{map_name}_audio.isc"
    if audio_isc_path.exists():
        isc_data = audio_isc_path.read_text(encoding="utf-8")
        if intro_name not in isc_data:
            amb_actor = (
                f'\t\t<ACTORS NAME="Actor">\n'
                f'\t\t\t<Actor RELATIVEZ="0.000002" SCALE="1.000000 1.000000" xFLIPPED="0"'
                f' USERFRIENDLY="{intro_name}" POS2D="0.000000 0.000000" ANGLE="0.000000"'
                f' INSTANCEDATAFILE="" LUA="World/MAPS/{map_name}/audio/AMB/{intro_name}.tpl">\n'
                f'\t\t\t\t<COMPONENTS NAME="SoundComponent">\n'
                f'\t\t\t\t\t<SoundComponent />\n'
                f'\t\t\t\t</COMPONENTS>\n'
                f'\t\t\t</Actor>\n'
                f'\t\t</ACTORS>\n'
            )
            # Inject before <sceneConfigs>
            new_isc = isc_data.replace("\t\t<sceneConfigs>", amb_actor + "\t\t<sceneConfigs>")
            audio_isc_path.write_text(new_isc, encoding="utf-8")
            logger.info("Injected intro AMB actor into audio ISC")

    delay_ms = int(audio_delay * 1000)
    if delay_ms > 0:
        af_filter = (
            f"adelay={delay_ms}|{delay_ms},asetpts=PTS-STARTPTS,"
            f"afade=t=out:st={fade_start:.3f}:d=0.2"
        )
        logger.info("Intro audio delayed by %.3fs", audio_delay)
    else:
        af_filter = f"afade=t=out:st={fade_start:.3f}:d=0.2"

    run_ffmpeg([
        "-y", "-t", f"{audio_content_dur:.3f}", 
        "-i", str(ogg_path),
        "-af", af_filter, 
        "-ar", "48000", str(intro_wav)
    ], config=config)
    logger.info("Generated intro AMB: %s (%.3fs)", intro_wav.name, amb_duration)


# ---------------------------------------------------------------------------
# Image processing (Pillow)
# ---------------------------------------------------------------------------

def convert_image(
    src_path: str | Path,
    dst_path: str | Path,
    target_size: Optional[tuple[int, int]] = None,
) -> Path:
    """Convert an image file to a different format, optionally resizing.

    Uses Pillow for format detection and conversion.
    """
    try:
        from PIL import Image
    except ImportError:
        raise MediaProcessingError("Pillow is not installed. Run: pip install Pillow")

    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise MediaProcessingError(f"Source image not found: {src}")

    img = Image.open(src)
    if target_size:
        img = img.resize(target_size, Image.Resampling.LANCZOS)

    img.save(dst)
    logger.info("Converted image: %s -> %s", src.name, dst)
    return dst


def generate_cover_tga(
    src_path: str | Path,
    dst_path: str | Path,
    size: tuple[int, int] = (720, 720),
) -> Path:
    """Convert a cover image to TGA format for the game engine."""
    return convert_image(src_path, dst_path, target_size=size)


# ---------------------------------------------------------------------------
# vgmstream — Xbox 360 XMA2 audio decoding
# ---------------------------------------------------------------------------

# Default path relative to project root; can be overridden via AppConfig
VGMSTREAM_DEFAULT_PATH = Path("tools/vgmstream/vgmstream-cli.exe")


def is_xma2_audio(file_path: str | Path) -> bool:
    """Quick check: does this look like an Xbox 360 .wav.ckd (XMA2) file?

    Matches filenames like ``music.wav.ckd`` which contain XMA2-encoded
    audio payloads (as opposed to ``.ogg`` or standard ``.wav``).
    """
    name = Path(file_path).name.lower()
    return name.endswith(".wav.ckd")


def decode_xma2_audio(
    input_ckd: str | Path,
    output_wav: str | Path,
    vgmstream_path: Optional[str | Path] = None,
    timeout: int = 120,
) -> Path:
    """Decode an Xbox 360 XMA2 audio file to WAV using vgmstream-cli.

    This wraps ``vgmstream-cli.exe -o <output> <input>`` in a blocking
    ``subprocess.run`` call.  Because it is designed to be invoked from
    the normalizer pipeline (which already runs inside a QThread), the
    blocking call will **not** freeze the GUI.

    Args:
        input_ckd:      Path to the ``.wav.ckd`` input file.
        output_wav:     Path where the decoded ``.wav`` will be written.
        vgmstream_path: Override path to vgmstream-cli.exe.
        timeout:        Maximum seconds before the process is killed.

    Returns:
        The resolved ``output_wav`` Path on success.

    Raises:
        MediaProcessingError: If the binary is missing or decoding fails.
    """
    input_ckd = Path(input_ckd)
    output_wav = Path(output_wav)
    output_wav.parent.mkdir(parents=True, exist_ok=True)

    vgm_bin = Path(vgmstream_path).resolve() if vgmstream_path else VGMSTREAM_DEFAULT_PATH.resolve()
    if not vgm_bin.exists():
        raise MediaProcessingError(
            f"vgmstream-cli binary not found at {vgm_bin}. "
            "Place vgmstream-cli.exe in tools/vgmstream/."
        )

    cmd = [str(vgm_bin), "-o", str(output_wav), str(input_ckd)]
    logger.info("Decoding X360 audio: %s", input_ckd.name)
    logger.debug("vgmstream cmd: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if result.stdout:
            logger.debug("vgmstream stdout: %s", result.stdout.strip())
        logger.info("Decoded X360 audio → %s", output_wav.name)
        return output_wav
    except subprocess.CalledProcessError as e:
        raise MediaProcessingError(
            f"vgmstream failed (exit {e.returncode}):\n"
            f"  stdout: {e.stdout[:300]}\n  stderr: {e.stderr[:300]}"
        )
    except subprocess.TimeoutExpired:
        raise MediaProcessingError(
            f"vgmstream timed out after {timeout}s decoding {input_ckd.name}"
        )
    except FileNotFoundError:
        raise MediaProcessingError(
            f"Could not execute vgmstream at '{vgm_bin}'. "
            "Check that the binary is not blocked by antivirus."
        )


def copy_moves(
    moves_src_dir: str | Path,
    target_dir: str | Path,
) -> int:
    """Extract and merge .gesture and .msm files cross-platform to PC format.

    Args:
        moves_src_dir: The extracted root 'moves' folder containing 'nx', 'durango', etc.
        target_dir: The map's root installation target directory.

    Returns:
        The number of valid move skeleton files copied.
    """
    src_root = Path(moves_src_dir)
    if not src_root.is_dir():
        return 0

    pc_moves_dir = Path(target_dir) / "Timeline" / "Moves" / "PC"
    total_copied = 0

    KINECT_PLATFORMS = {"DURANGO", "SCARLETT", "X360"}

    # Pass 1: Copy Kinect-compatible gestures and universally compatible MSMs
    for plat_dir in src_root.iterdir():
        if not plat_dir.is_dir() or plat_dir.name.upper() == "PC":
            continue
            
        plat_name = plat_dir.name.upper()

        if plat_name in KINECT_PLATFORMS:
            for gesture_file in plat_dir.glob("*.gesture"):
                dest = pc_moves_dir / gesture_file.name
                if not dest.exists():
                    pc_moves_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(gesture_file, dest)
                    total_copied += 1

        for msm_file in plat_dir.glob("*.msm"):
            dest = pc_moves_dir / msm_file.name
            if not dest.exists():
                pc_moves_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(msm_file, dest)
                total_copied += 1

    # Pass 2: Substitute ORBIS (PS4) exclusive gestures with Kinect base gestures
    pc_gestures = {f.name for f in pc_moves_dir.glob("*.gesture")}
    
    for plat_dir in src_root.iterdir():
        if not plat_dir.is_dir() or plat_dir.name.upper() in KINECT_PLATFORMS or plat_dir.name.upper() == "PC":
            continue
            
        for gesture_file in plat_dir.glob("*.gesture"):
            fname = gesture_file.name
            if fname in pc_gestures or (pc_moves_dir / fname).exists():
                continue
                
            stem = gesture_file.stem
            base = stem.rstrip("0123456789")
            sub_src = pc_moves_dir / (base + ".gesture")
            
            if base != stem and sub_src.exists():
                pc_moves_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sub_src, pc_moves_dir / fname)
                total_copied += 1

    if total_copied:
        logger.info("Merged %d gesture/msm file(s) from %s into PC/", total_copied, src_root)

    return total_copied


