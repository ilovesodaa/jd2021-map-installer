"""Playwright-based web extractor for JDU map assets.

Replaces the original Node.js JDH_Downloader script (fetch.mjs).
Uses playwright-python's async API to automate Discord slash commands
(``/assets`` and ``/nohud``) and download associated media files.

The extractor runs Playwright in a background thread (via ``asyncio.run()``)
so it can be safely dispatched from a QThread worker without blocking
the Qt event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import requests
import shutil
import ssl
import time
import urllib.error
import urllib.request
import zipfile
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
from jd2021_installer.extractors.archive_ipk import extract_ipk
from jd2021_installer.extractors.base import BaseExtractor

logger = logging.getLogger("jd2021.extractors.web_playwright")

# SSL workaround for Ubisoft CDN
ssl._create_default_https_context = ssl._create_unverified_context

# Discord DOM selectors (must be updated if Discord changes its UI)
_SEL_TEXTBOX = '[role="textbox"][data-slate-editor="true"]'
_SEL_AUTOCOMPLETE_OPTION = '[role="option"]'
_SEL_MESSAGE_ACCESSORIES = 'div[id^="message-accessories-"]'

# CDN link validation pattern
_CDN_PATTERN = re.compile(r'href="(https?://jd-s3\.cdn\.ubi\.com[^"]+)"', re.IGNORECASE)


# ---------------------------------------------------------------------------
# URL extraction helpers
# ---------------------------------------------------------------------------

def extract_urls_from_html(html_content: str) -> List[str]:
    """Extract all URLs from HTML content, deduplicating.
    Finds links even outside of href attributes, useful for Discord embeds
    where the actual CDN link is plaintext inside an anchor tag.
    """
    urls = re.findall(r'(https?://[^\s<"\']+)', html_content)
    clean: Set[str] = set()
    for url in urls:
        if "discordapp.net" in url:
            continue
        # Strip trailing punctuation that might be captured from text around the URL
        url = url.rstrip(").,!;?")
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
            if ".ckd" in u or ".ad" in u or ("discordapp.net" not in u):
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
    # Prioritize: mainscene > audio > video > others
    def priority(u):
        if "MAIN_SCENE" in u: return 0
        if ".ogg" in u or ".wav" in u: return 1
        if any(pat in u for pat in QUALITY_PATTERNS.values()): return 2
        return 3
    
    unique_urls.sort(key=priority)
    
    downloaded: Dict[str, str] = {}
    total = len(unique_urls)

    session = requests.Session()
    session.headers.update({"User-Agent": config.user_agent})
    session.headers.update({"Referer": "https://discord.com/"})

    for idx, url in enumerate(unique_urls):
        fname = get_filename_from_url(url)
        target = download_path / fname

        # Check if already in cache and not empty
        if target.exists() and target.stat().st_size > 1024:
            logger.info("%s already in cache, skipping download.", fname)
            downloaded[fname] = str(target)
            continue
        
        if target.exists():
            target.unlink()

        # Check if already installed
        codename = download_path.name
        game_map_dir = None
        if config.game_directory:
            base_game_dir = config.game_directory
            while base_game_dir.name.lower() in ("world", "data"):
                base_game_dir = base_game_dir.parent
            game_map_dir = base_game_dir / "data" / "World" / "MAPS" / codename
            
        found_in_game = False
        if game_map_dir and game_map_dir.exists():
            for fpath in game_map_dir.rglob(fname):
                if fpath.is_file() and fpath.stat().st_size > 1024:
                    import shutil
                    logger.info("Found %s in existing game installation, copying to cache...", fname)
                    shutil.copy2(fpath, target)
                    found_in_game = True
                    break
        
        if found_in_game:
            downloaded[fname] = str(target)
            continue

        logger.info("Downloading %s... (%d/%d)", fname, idx + 1, total)
        if progress_callback:
            progress_callback(fname, idx + 1, total)

        success = False
        for attempt in range(1, config.max_retries + 1):
            try:
                with session.get(url, stream=True, timeout=config.download_timeout_s) as r:
                    if r.status_code == 403:
                        logger.warning("HTTP 403 for %s (Attempt %d/%d)", fname, attempt, config.max_retries)
                        if attempt < config.max_retries:
                            time.sleep(config.retry_base_delay_s * attempt)
                            continue
                        else:
                            break
                            
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    
                    with open(target, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            if chunk:
                                f.write(chunk)
                    
                    # Verify download success (non-zero size)
                    if target.stat().st_size > 1024:
                        success = True
                        break
                    else:
                        logger.warning("Download produced empty file for %s", fname)
            except Exception as e:
                logger.warning("Download error for %s: %s (Attempt %d/%d)", fname, e, attempt, config.max_retries)
                if attempt < config.max_retries:
                    time.sleep(config.retry_base_delay_s * (2 ** (attempt - 1)))
                else:
                    break

        if success:
            downloaded[fname] = str(target)
        else:
            logger.error("Failed to download %s after %d attempts", fname, config.max_retries)

        time.sleep(config.inter_request_delay_s)

    return downloaded


# ---------------------------------------------------------------------------
# Discord automation helpers  (ported from V1 fetch.mjs)
# ---------------------------------------------------------------------------

async def _wait_for_login(page, timeout_s: int = 300) -> None:
    """Wait for Discord login — detects the chat textbox."""
    textbox = page.locator(_SEL_TEXTBOX)
    try:
        await textbox.wait_for(timeout=15_000)
        logger.info("Already logged in to Discord.")
    except Exception:
        logger.info(
            "Please log in to Discord in the browser window. "
            "Waiting up to %d seconds...", timeout_s
        )
        await textbox.wait_for(timeout=timeout_s * 1000)
        logger.info("Login detected.")
        await page.wait_for_timeout(3000)


async def _get_last_accessory_id(page) -> Optional[str]:
    """Return the DOM id of the last message-accessories element."""
    accessories = page.locator(_SEL_MESSAGE_ACCESSORIES)
    count = await accessories.count()
    if count == 0:
        return None
    return await accessories.nth(count - 1).get_attribute("id")


async def _send_slash_command(
    page, *, command: str, choices: List[str], codename: str
) -> None:
    """Automate the Discord slash-command picker UI.

    1. Focus textbox, type ``/<command>``
    2. Click matching autocomplete option
    3. Click each ``choice`` (e.g. "jdu") in dropdown params
    4. Type the codename, press Enter
    """
    textbox = page.locator(_SEL_TEXTBOX)
    await textbox.click()
    await page.wait_for_timeout(200)

    # Type command
    await page.keyboard.type(f"/{command}", delay=30)

    cmd_option = (
        page.locator(_SEL_AUTOCOMPLETE_OPTION)
        .filter(has_text=re.compile(command, re.IGNORECASE))
        .first
    )
    try:
        await cmd_option.wait_for(timeout=8000)
        await cmd_option.click()
        logger.info("Selected /%s command.", command)
    except Exception:
        raise WebExtractionError(
            f"Could not find /{command} in the autocomplete. "
            "Make sure the bot is in this server and the command exists."
        )

    await page.wait_for_timeout(300)

    # Handle dropdown choices (e.g. game = "jdu")
    for choice in choices:
        choice_option = (
            page.locator(_SEL_AUTOCOMPLETE_OPTION)
            .filter(has_text=re.compile(rf"^\s*{re.escape(choice)}\s*$", re.IGNORECASE))
            .first
        )
        try:
            await choice_option.wait_for(timeout=8000)
            await choice_option.click()
            logger.info("Selected choice: %s", choice)
        except Exception:
            # Looser match fallback
            loose = (
                page.locator(_SEL_AUTOCOMPLETE_OPTION)
                .filter(has_text=choice)
                .first
            )
            try:
                await loose.wait_for(timeout=3000)
                await loose.click()
                logger.info("Selected choice (loose): %s", choice)
            except Exception:
                raise WebExtractionError(
                    f'Could not find "{choice}" in the parameter options.'
                )
        await page.wait_for_timeout(200)

    # Type codename and send
    await page.keyboard.type(codename, delay=20)
    logger.info("Typed codename: %s", codename)
    await page.wait_for_timeout(200)
    await page.keyboard.press("Enter")
    logger.info("Command sent.")


async def _wait_for_new_embed(
    page, previous_last_id: Optional[str], timeout_s: int = 60
) -> str:
    """Poll for a new message-accessories element (the bot's response).

    Waits until the element is stable (no "Loading" text, has children)
    for 3 consecutive checks.
    """
    logger.info("Waiting for bot response...")
    deadline = asyncio.get_event_loop().time() + timeout_s

    while asyncio.get_event_loop().time() < deadline:
        result = await page.evaluate(
            """(prevId) => {
                const all = document.querySelectorAll('div[id^="message-accessories-"]');
                if (all.length === 0) return null;
                const last = all[all.length - 1];
                const textContent = last.textContent || '';
                return {
                    id: last.id,
                    hasChildren: last.children.length > 0,
                    isLoading: textContent.includes('Loading'),
                };
            }""",
            previous_last_id,
        )

        if (
            result
            and result["id"] != previous_last_id
            and result["hasChildren"]
            and not result["isLoading"]
        ):
            # Stability check: 3 × 500 ms
            stable = True
            for _ in range(3):
                await page.wait_for_timeout(500)
                latest = await page.evaluate(
                    """() => {
                        const all = document.querySelectorAll(
                            'div[id^="message-accessories-"]');
                        if (all.length === 0) return null;
                        const last = all[all.length - 1];
                        const tc = last.textContent || '';
                        return {
                            id: last.id,
                            hasChildren: last.children.length > 0,
                            isLoading: tc.includes('Loading'),
                        };
                    }"""
                )
                if (
                    not latest
                    or latest["id"] != result["id"]
                    or not latest["hasChildren"]
                    or latest["isLoading"]
                ):
                    stable = False
                    break
            if stable:
                logger.info("Bot response detected (%s).", result["id"])
                return result["id"]

        await page.wait_for_timeout(500)

    raise WebExtractionError(
        "Timed out waiting for the bot response. "
        "The bot might be offline or the command may have failed."
    )


async def _extract_embed_html(page, accessory_id: str) -> str:
    """Extract the outerHTML of the identified embed element."""
    await page.wait_for_timeout(1500)  # Let rendering finish

    html = await page.evaluate(
        """(id) => {
            const el = document.getElementById(id);
            return el ? el.outerHTML : null;
        }""",
        accessory_id,
    )
    if not html:
        raise WebExtractionError(
            f'Could not find element with id "{accessory_id}" in the DOM.'
        )
    return html


def _has_valid_cdn_links(html: str) -> bool:
    """Return True if the embed contains valid jd-s3.cdn.ubi.com links."""
    return bool(_CDN_PATTERN.search(html))


async def _fetch_command_with_retry(
    page,
    *,
    command: str,
    choices: List[str],
    codename: str,
    label: str,
    max_retries: int = 2,
    bot_timeout_s: int = 60,
) -> str:
    """Send a slash command, wait for bot response, extract and validate HTML.

    Retries up to ``max_retries`` times if the response has no valid CDN links.
    """
    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.info("Retrying %s (attempt %d/%d)...", label, attempt + 1, max_retries + 1)
            await page.wait_for_timeout(3000)

        try:
            pre_id = await _get_last_accessory_id(page)
            await _send_slash_command(page, command=command, choices=choices, codename=codename)
            embed_id = await _wait_for_new_embed(page, pre_id, timeout_s=bot_timeout_s)
            html = await _extract_embed_html(page, embed_id)

            if _has_valid_cdn_links(html):
                logger.info("Extracted %s embed HTML.", label)
                return html

            logger.warning(
                "%s response has no valid CDN links (bot may have returned an error).",
                label,
            )
        except WebExtractionError as e:
            if attempt == max_retries:
                raise
            logger.warning("%s attempt %d failed: %s", label, attempt + 1, e)

    raise WebExtractionError(
        f"{label} response contained no valid download links after "
        f"{max_retries + 1} attempts.\n"
        "The bot may not have data for this codename."
    )


# ---------------------------------------------------------------------------
# Web extractor class
# ---------------------------------------------------------------------------

class WebPlaywrightExtractor(BaseExtractor):
    """Extractor that downloads JDU map data via Discord bot automation.

    Operates in two modes:
    1. **From pre-saved HTML files** — legacy workflow, uses local
       ``assets.html`` / ``nohud.html``.
    2. **Live Fetch** — launches a persistent-profile Chromium browser,
       automates Discord slash commands (``/assets jdu <codename>`` and
       ``/nohud <codename>``), captures the bot's embed HTML, then
       downloads the CDN URLs.
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
        """Download files into download_root and extract them into output_dir."""
        all_urls = list(self._urls)
        if self._asset_html and Path(self._asset_html).exists():
            all_urls.extend(extract_urls_from_file(self._asset_html))
        if self._nohud_html and Path(self._nohud_html).exists():
            all_urls.extend(extract_urls_from_file(self._nohud_html))

        # Live fetch: scrape Discord for each codename
        if not all_urls and self._codenames:
            for codename in self._codenames:
                try:
                    scraped = asyncio.run(self._scrape_codename(codename))
                    all_urls.extend(scraped)
                except Exception as e:
                    logger.error("Failed to scrape codename '%s': %s", codename, e)
                    raise

        if not all_urls:
            raise WebExtractionError("No URLs provided for extraction")

        self._codename = extract_codename_from_urls(all_urls) or self._codename
        codename = self._codename or "UnknownMap"
        
        # 1. Determine download directory (respect hand-picked HTML location if available)
        if self._asset_html and Path(self._asset_html).is_file():
            download_dir = Path(self._asset_html).parent
        else:
            download_dir = self._config.download_root / codename
            download_dir.mkdir(parents=True, exist_ok=True)

        downloaded = download_files(all_urls, download_dir, self._quality, self._config)
        
        # 1b. Check for missing critical files (possible link expiration)
        missing_critical = False
        classified = _classify_urls(all_urls, self._quality)
        for key in ("video", "audio", "mainscene"):
            url = classified[key]
            if url:
                fname = get_filename_from_url(url)
                if fname not in downloaded:
                    missing_critical = True
                    break
        
        if missing_critical and self._codenames:
            logger.warning("Critical files missing (Expired links?). Attempting one re-scrape...")
            scraped_fresh = []
            for codename in self._codenames:
                try:
                    scraped_fresh.extend(asyncio.run(self._scrape_codename(codename)))
                except: pass
            if scraped_fresh:
                all_urls = list(set(all_urls + scraped_fresh))
                download_files(all_urls, download_dir, self._quality, self._config)

        # 2. Extract/Assemble into temporary output_dir
        extract_dir = output_dir / codename
        extract_dir.mkdir(parents=True, exist_ok=True)
        
        # Post-download: extract MAIN_SCENE_*.zip from download_dir into extract_dir
        self._extract_scene_zips(download_dir, extract_dir)
        
        # Copy non-extracted assets (e.g. video, audio) to extract_dir for normalizer
        for f in os.listdir(download_dir):
            src_file = download_dir / f
            dst_file = extract_dir / f
            if src_file.is_file() and not f.endswith(".zip") and not dst_file.exists():
                logger.debug("Copying %s to extraction dir", f)
                shutil.copy2(src_file, dst_file)

        return extract_dir

    def get_codename(self) -> Optional[str]:
        return self._codename

    @staticmethod
    def _extract_scene_zips(src_dir: Path, dst_dir: Path) -> None:
        """Extract MAIN_SCENE_*.zip files from src_dir into dst_dir.

        Mirrors V1 ``step_03_extract_scenes``.  After downloading, the
        normalizer expects loose ``.ckd`` files — not a ZIP.
        """
        scene_zips: list[str] = []
        for f in os.listdir(src_dir):
            if "SCENE" in f.upper() and f.endswith(".zip"):
                scene_zips.append(f)

        if not scene_zips:
            logger.debug("No scene ZIPs found in %s — skipping extraction.", src_dir)
            return

        # Prefer DURANGO > NX > SCARLETT > any
        selected: Optional[str] = None
        for plat in SCENE_PLATFORM_PREFERENCE:
            matches = [z for z in scene_zips if f"MAIN_SCENE_{plat}" in z.upper()]
            if matches:
                selected = matches[14] if len(matches) > 14 else matches[0] # Safety
                selected = matches[0]
                break

        if selected:
            zip_path = src_dir / selected
            logger.info("Extracting scene ZIP: %s", selected)
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(dst_dir)
        else:
            # Fallback: extract all scene ZIPs
            for f in scene_zips:
                zip_path = src_dir / f
                logger.info("Extracting scene ZIP (fallback): %s", f)
                with zipfile.ZipFile(zip_path, "r") as z:
                    z.extractall(dst_dir)

        # -- Unpack any .ipk files found after ZIP extraction (mirrors V1 step_04) ---
        for ipk in dst_dir.glob("*.ipk"):
            logger.info("Unpacking IPK found in scene ZIP: %s", ipk.name)
            try:
                extract_ipk(ipk, dst_dir)
                # Delete IPK after extraction to keep normalization directory clean
                ipk.unlink()
            except Exception as e:
                logger.warning("Failed to unpack IPK %s: %s", ipk.name, e)

    # ------------------------------------------------------------------
    # Live Discord scraping  (async, called via asyncio.run from QThread)
    # ------------------------------------------------------------------

    async def _scrape_codename(self, codename: str) -> List[str]:
        """Full fetch flow for one codename: launch browser → login →
        ``/assets`` → ``/nohud`` → save HTML → return extracted URLs.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise WebExtractionError(
                "playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            )

        channel_url = self._config.discord_channel_url
        if not channel_url:
            raise WebExtractionError(
                "discord_channel_url is not configured. "
                "Set it in your installer_settings.json or via the Settings dialog."
            )

        profile_dir = str(self._config.browser_profile_dir.resolve())

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"],
            )

            page = context.pages[0] if context.pages else await context.new_page()

            try:
                logger.info("Fetching codename: %s", codename)

                # Navigate to Discord channel
                logger.info("Navigating to Discord channel...")
                await page.goto(channel_url, wait_until="domcontentloaded")
                await _wait_for_login(page, self._config.fetch_login_timeout_s)

                # Wait for channel messages to load
                try:
                    await (
                        page.locator(_SEL_MESSAGE_ACCESSORIES)
                        .first
                        .wait_for(timeout=15_000)
                    )
                except Exception:
                    pass  # Channel might be empty

                bot_timeout = self._config.fetch_bot_response_timeout_s

                # Step 1: /assets jdu <codename>
                logger.info("[1/2] /assets jdu %s", codename)
                assets_html = await _fetch_command_with_retry(
                    page,
                    command="assets",
                    choices=["jdu"],
                    codename=codename,
                    label="assets",
                    bot_timeout_s=bot_timeout,
                )
                await page.wait_for_timeout(500)

                # Step 2: /nohud <codename>
                logger.info("[2/2] /nohud %s", codename)
                nohud_html = await _fetch_command_with_retry(
                    page,
                    command="nohud",
                    choices=[],
                    codename=codename,
                    label="nohud",
                    bot_timeout_s=bot_timeout,
                )

                # Save HTML to output dir for caching / debugging
                output_dir = self._config.cache_directory / codename
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "assets.html").write_text(assets_html, encoding="utf-8")
                (output_dir / "nohud.html").write_text(nohud_html, encoding="utf-8")
                logger.info("Saved HTML to %s", output_dir)

            finally:
                await context.close()

        # Extract all URLs from both pages
        all_urls = extract_urls_from_html(assets_html) + extract_urls_from_html(nohud_html)
        self._codename = extract_codename_from_urls(all_urls) or codename
        return all_urls

    async def scrape_live(self, page_url: str) -> List[str]:
        """Legacy method — kept for backward compatibility.

        For a simple URL scrape (non-Discord), navigates to the URL and
        extracts href links from the page content.
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
