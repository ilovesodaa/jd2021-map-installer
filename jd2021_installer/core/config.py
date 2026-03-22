"""Application configuration using Pydantic settings.

Handles paths, quality preferences, and runtime settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    """Top-level application configuration."""

    # Paths
    game_directory: Optional[Path] = None
    download_directory: Path = Path("./downloads")
    cache_directory: Path = Path("./cache")

    # Video quality preference (descending fallback)
    video_quality: str = Field(
        default="ULTRA_HD",
        pattern=r"^(ULTRA_HD|ULTRA|HIGH_HD|HIGH|MID_HD|MID|LOW_HD|LOW)$",
    )

    # Download settings
    download_timeout_s: int = 60
    max_retries: int = 3
    retry_base_delay_s: int = 2
    inter_request_delay_s: float = 0.5
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    # UbiArt engine constants
    ticks_per_ms: int = 48
    max_jd_version: int = 2021
    min_jd_version: int = 2014
    preview_fps: int = 24
    audio_preview_fade_s: float = 2.0

    # FFmpeg configuration
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    class Config:
        env_prefix = "JD2021_"
        env_file = ".env"


# Quality tiers and their filename suffix patterns
QUALITY_ORDER = [
    "ULTRA_HD", "ULTRA",
    "HIGH_HD", "HIGH",
    "MID_HD", "MID",
    "LOW_HD", "LOW",
]

QUALITY_PATTERNS = {
    "ULTRA_HD": "_ULTRA.hd.webm",
    "ULTRA":    "_ULTRA.webm",
    "HIGH_HD":  "_HIGH.hd.webm",
    "HIGH":     "_HIGH.webm",
    "MID_HD":   "_MID.hd.webm",
    "MID":      "_MID.webm",
    "LOW_HD":   "_LOW.hd.webm",
    "LOW":      "_LOW.webm",
}

# Per-platform mainscene ZIP preference order
SCENE_PLATFORM_PREFERENCE = ["DURANGO", "NX", "SCARLETT"]
