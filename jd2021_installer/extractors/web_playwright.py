"""Playwright-based web extractor for JDU map assets.

Replaces the original Node.js scraper. Uses playwright-python's async
API to fetch map data HTML pages and download associated media files.

The extractor runs Playwright in a background thread (via asyncio)
so it can be safely dispatched from a QThread worker without blocking
the Qt event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import unquote, urlparse

from jd2021_installer.core.config import (
    QUALITY_ORDER,
    QUALITY_PATTERNS,
    SCENE_PLATFORM_PREFERENCE,
    AppConfig,
)
from jd2021_installer.core.exceptions import DownloadError, WebExtractionError
from jd2021_installer.extractors.base import BaseExtractor

logger = logging.getLogger("jd2021.extractors.web_playwright")

# SSL workaround for Ubisoft CDN
ssl._create_default_https_context = ssl._create_unverified_context


# ---------------------------------------------------------------------------
# URL extraction helpers
# ---------------------------------------------------------------------------

def extract_urls_from_html(html_content: str) -> List[str]:
    """Extract all href URLs from HTML content, deduplicating."""
    urls = re.findall(r'href="(https?://[^"]+)"', html_content)
    clean: Set[str] = set()
    for url in urls:
        if "discordapp.net" in url:
            continue
        url = url.replace("&amp;", "&")
        clean.add(url)
    return list(clean)


def extract_urls_from_file(html_file: str | Path) -> List[str]:
    """Read an HTML file and extract URLs."""
    path = Path(html_file)
    if not path.is_file():
        raise FileNotFoundError(f"HTML file not found: {path}")
    content = path.read_text(encoding="utf-8")
    return extract_urls_from_html(content)


def get_filename_from_url(url: str) -> str:
    """Extract the filename from a URL."""
    parsed = urlparse(url)
    path = unquote(parsed.path)
    parts = path.split("/")
    if len(parts) >= 2 and "." in parts[-2]:
        return parts[-2]
    return parts[-1]


def extract_codename_from_urls(urls: List[str]) -> Optional[str]:
    """Extract map codename from JDU asset URLs.

    Pattern: https://jd-s3.cdn.ubi.com/public/map/{MapName}/...
    """
    for url in urls:
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "public" and parts[1] == "map":
            if parts[2]:
                return parts[2]
    return None


# ---------------------------------------------------------------------------
# File downloader
# ---------------------------------------------------------------------------

def _classify_urls(
    urls: List[str], quality: str
) -> Dict[str, Optional[str]]:
    """Classify URLs into video, audio, mainscene, and other assets."""
    video_urls_by_quality: Dict[str, str] = {}
    audio_url: Optional[str] = None
    scene_zips: Dict[str, str] = {}
    other_urls: List[str] = []

    for u in urls:
        for q, pattern in QUALITY_PATTERNS.items():
            if pattern in u:
                video_urls_by_quality[q] = u
                break
        if ".ogg" in u and "AudioPreview" not in u:
            audio_url = u
        elif "MAIN_SCENE" in u and ".zip" in u:
            for plat in ["DURANGO", "NX", "SCARLETT", "ORBIS", "PROSPERO", "PC", "GGP", "WIIU"]:
                if f"MAIN_SCENE_{plat}" in u:
                    scene_zips[plat] = u
                    break
        elif any(ext in u for ext in (".ckd", ".jpg", ".png", ".ad")):
            if "discordapp.net" not in u:
                other_urls.append(u)

    # Select best video
    video_url = None
    preferred_idx = QUALITY_ORDER.index(quality) if quality in QUALITY_ORDER else 0
    search_order = QUALITY_ORDER[preferred_idx:] + QUALITY_ORDER[:preferred_idx]
    for q in search_order:
        if q in video_urls_by_quality:
            video_url = video_urls_by_quality[q]
            break

    # Select best mainscene
    main_scene_url = None
    for plat in SCENE_PLATFORM_PREFERENCE:
        if plat in scene_zips:
            main_scene_url = scene_zips[plat]
            break
    if not main_scene_url and scene_zips:
        main_scene_url = next(iter(scene_zips.values()))

    return {
        "video": video_url,
        "audio": audio_url,
        "mainscene": main_scene_url,
        "others": other_urls,
    }


def download_files(
    urls: List[str],
    download_dir: str | Path,
    quality: str = "ULTRA_HD",
    config: Optional[AppConfig] = None,
    progress_callback=None,
) -> Dict[str, str]:
    """Download map asset files from URLs.

    Args:
        urls:              List of asset URLs.
        download_dir:      Directory to save files to.
        quality:           Preferred video quality tier.
        config:            App configuration (for timeouts, etc.).
        progress_callback: Optional callable(filename, current, total).

    Returns:
        Dict mapping filename → local path for downloaded files.
    """
    if config is None:
        config = AppConfig()

    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)

    classified = _classify_urls(urls, quality)
    important_urls: List[str] = []
    for key in ("video", "audio", "mainscene"):
        if classified[key]:
            important_urls.append(classified[key])
    important_urls.extend(classified.get("others", []))

    unique_urls = list(set(important_urls))
    downloaded: Dict[str, str] = {}
    total = len(unique_urls)

    for idx, url in enumerate(unique_urls):
        fname = get_filename_from_url(url)
        target = str(download_path / fname)

        if os.path.exists(target):
            logger.info("%s already exists, skipping.", fname)
            downloaded[fname] = target
            continue

        logger.info("Downloading %s... (%d/%d)", fname, idx + 1, total)
        if progress_callback:
            progress_callback(fname, idx + 1, total)

        req = urllib.request.Request(url, headers={"User-Agent": config.user_agent})
        for attempt in range(1, config.max_retries + 1):
            try:
                with urllib.request.urlopen(
                    req, timeout=config.download_timeout_s
                ) as response:
                    with open(target, "wb") as f:
                        f.write(response.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    retry_after = int(
                        e.headers.get("Retry-After", config.retry_base_delay_s * attempt)
                    )
                    logger.warning(
                        "Rate limited (429). Waiting %ds (%d/%d)...",
                        retry_after, attempt, config.max_retries,
                    )
                    time.sleep(retry_after)
                    continue
                if e.code in (403, 404):
                    logger.error("HTTP %d for %s -- links may have expired!", e.code, fname)
                    break
                if attempt < config.max_retries:
                    delay = config.retry_base_delay_s * (2 ** (attempt - 1))
                    time.sleep(delay)
                else:
                    logger.error("Failed to download %s: HTTP %d", fname, e.code)
            except Exception as e:
                if attempt < config.max_retries:
                    delay = config.retry_base_delay_s * (2 ** (attempt - 1))
                    time.sleep(delay)
                else:
                    logger.error("Failed to download %s: %s", fname, e)

        time.sleep(config.inter_request_delay_s)
        if os.path.exists(target):
            downloaded[fname] = target

    return downloaded


# ---------------------------------------------------------------------------
# Web extractor class
# ---------------------------------------------------------------------------

class WebPlaywrightExtractor(BaseExtractor):
    """Extractor that downloads map data from JDU web pages.

    Can operate in two modes:
    1. From pre-saved HTML files (legacy workflow)
    2. Using Playwright to scrape live pages (future implementation)
    """

    def __init__(
        self,
        asset_html: Optional[str | Path] = None,
        nohud_html: Optional[str | Path] = None,
        urls: Optional[List[str]] = None,
        codenames: Optional[List[str]] = None,
        quality: str = "ULTRA_HD",
        config: Optional[AppConfig] = None,
    ) -> None:
        self._asset_html = asset_html
        self._nohud_html = nohud_html
        self._urls = urls or []
        self._quality = quality
        self._config = config or AppConfig()
        self._codenames = codenames or []
        self._codename: Optional[str] = self._codenames[0] if self._codenames else None

    def extract(self, output_dir: Path) -> Path:
        """Download files from URLs or HTML pages into output_dir."""
        all_urls = list(self._urls)
        if self._asset_html and Path(self._asset_html).exists():
            all_urls.extend(extract_urls_from_file(self._asset_html))
        if self._nohud_html and Path(self._nohud_html).exists():
            all_urls.extend(extract_urls_from_file(self._nohud_html))

        if not all_urls:
            raise WebExtractionError("No URLs provided for extraction")

        self._codename = extract_codename_from_urls(all_urls)
        download_files(all_urls, output_dir, self._quality, self._config)
        return output_dir

    def get_codename(self) -> Optional[str]:
        return self._codename

    async def scrape_live(self, page_url: str) -> List[str]:
        """Use Playwright to scrape a live page for asset URLs.

        This is the future replacement for the Node.js scraper.

        Args:
            page_url: URL of the JDU asset page.

        Returns:
            List of extracted asset URLs.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise WebExtractionError(
                "playwright is not installed. Run: pip install playwright && playwright install"
            )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(page_url, wait_until="networkidle")
            content = await page.content()
            await browser.close()

        urls = extract_urls_from_html(content)
        self._codename = extract_codename_from_urls(urls)
        return urls
