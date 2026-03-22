"""Media processor — FFmpeg and Pillow wrappers for map asset processing.

Handles video transcoding, audio format conversion, image processing,
and preview generation.  All heavy subprocess work is designed to run
in a background QThread.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
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
    """Copy an audio file to the destination."""
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise MediaProcessingError(f"Source audio not found: {src}")

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

