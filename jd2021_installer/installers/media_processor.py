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
