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
import json
import logging
import os
import platform
import re
import requests
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Set, cast
from urllib.parse import unquote, urlparse
from html import unescape

from jd2021_installer.core.config import (
    QUALITY_ORDER,
    QUALITY_PATTERNS,
    SCENE_PLATFORM_PREFERENCE,
    AppConfig,
)
from jd2021_installer.core.exceptions import DownloadError, WebExtractionError
from jd2021_installer.extractors.archive_ipk import extract_ipk
from jd2021_installer.extractors.base import BaseExtractor
from jd2021_installer.extractors.jdnext_bundle_strategy import (
    _run_assetstudio_export,
    run_jdnext_bundle_strategy,
)

logger = logging.getLogger("jd2021.extractors.web_playwright")

# SSL workaround for Ubisoft CDN
ssl._create_default_https_context = ssl._create_unverified_context

# Discord DOM selectors (must be updated if Discord changes its UI)
_SEL_TEXTBOX = '[role="textbox"][data-slate-editor="true"]'
_SEL_AUTOCOMPLETE_OPTION = '[role="option"]'
_SEL_MESSAGE_ACCESSORIES = 'div[id^="message-accessories-"]'
_SEL_MESSAGE_LIST_ITEMS = 'li[id^="chat-messages-"]'

# CDN link validation patterns
_UBI_CDN_HOST_PATTERN = re.compile(r"https?://[^\s\"']*(?:cdn\.ubi\.com|cdn\.ubisoft\.cn)", re.IGNORECASE)
_MAP_PATH_PATTERN = re.compile(r"/(?:public|private)/(?:map|jdnext/maps)/", re.IGNORECASE)


def _is_browser_closed_error(exc: BaseException) -> bool:
    """Return True when Playwright indicates the page/context/browser was closed."""
    text = str(exc).lower()
    return (
        "target page, context or browser has been closed" in text
        or "browser has been closed" in text
        or "target closed" in text
    )


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


def _extract_embed_title_from_html(html_content: str) -> Optional[str]:
    match = re.search(r"<div class=\"embedTitle[^\"]*\">\s*<span>([^<]+)</span>", html_content, re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).strip()
    # Keep filesystem-safe codename characters only.
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "", raw)
    return safe or None


def _parse_retry_after_seconds(header_value: Optional[str], fallback: int) -> int:
    """Parse Retry-After header as seconds, returning a safe fallback on failure."""
    if not header_value:
        return max(1, int(fallback))
    try:
        return max(1, int(header_value.strip()))
    except (TypeError, ValueError):
        return max(1, int(fallback))


def _is_nohud_video_url(url: str) -> bool:
    """Return True for NOHUD gameplay video URLs from private map CDN paths."""
    parsed = urlparse(url)
    path_low = parsed.path.lower()
    if "/private/" not in path_low:
        return False
    if "/map/" not in path_low and "/maps/" not in path_low:
        return False
    name_low = get_filename_from_url(url).lower()
    if not name_low.endswith(".webm"):
        return False
    if "mappreview" in name_low or "videopreview" in name_low:
        return False
    return True


def _is_valid_webm_file(path: Path, config: AppConfig) -> bool:
    """Validate webm integrity.

    Prefers ffmpeg null-decode for robust corruption detection. Falls back to
    EBML magic check if ffmpeg is unavailable.
    """
    try:
        if not path.exists() or path.stat().st_size <= 1024:
            return False
    except OSError:
        return False

    try:
        with open(path, "rb") as fh:
            header = fh.read(4)
        if header != b"\x1a\x45\xdf\xa3":
            return False
    except OSError:
        return False

    cmd = [
        config.ffmpeg_path,
        "-v", "error",
        "-i", str(path),
        "-f", "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(15, min(config.download_timeout_s, 180)),
            check=False,
        )
        if proc.returncode != 0:
            return False
        if proc.stderr and proc.stderr.strip():
            return False
        return True
    except (FileNotFoundError, OSError):
        logger.debug("ffmpeg not available for integrity check; using header-only validation.")
        return True
    except subprocess.TimeoutExpired:
        logger.warning("Timed out while validating webm integrity for %s", path.name)
        return False


def _download_with_powershell(url: str, target: Path, timeout_s: int) -> bool:
    """Fallback downloader for Windows environments where Python DNS fails.

    Uses Invoke-WebRequest in a separate PowerShell process.
    """
    if platform.system().lower() != "windows":
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$ProgressPreference='SilentlyContinue'; "
        f"Invoke-WebRequest -Uri '{url}' -OutFile '{str(target)}' -TimeoutSec {int(timeout_s)}"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode == 0 and target.exists() and target.stat().st_size > 1024
    except (OSError, ValueError):
        return False


def _resolve_host_via_public_dns(host: str) -> Optional[str]:
    """Resolve host using public DNS via PowerShell to avoid local ISP DNS issues."""
    if platform.system().lower() != "windows":
        return None
    cmd = (
        "try { "
        f"$r = Resolve-DnsName '{host}' -Type A -Server 1.1.1.1 -ErrorAction Stop | "
        "Where-Object { $_.Type -eq 'A' } | Select-Object -First 1 -ExpandProperty IPAddress; "
        "if ($r) { Write-Output $r } "
        "} catch { }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True,
            text=True,
            check=False,
        )
        ip = (completed.stdout or "").strip()
        return ip or None
    except OSError:
        return None


def _download_with_curl_resolve(url: str, target: Path, timeout_s: int) -> bool:
    """Use curl --resolve to bypass system DNS for a specific host."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return False
    ip = _resolve_host_via_public_dns(host)
    if not ip:
        return False

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            [
                "curl.exe",
                "--location",
                "--silent",
                "--show-error",
                "--connect-timeout",
                str(max(5, int(timeout_s))),
                "--max-time",
                str(max(10, int(timeout_s) * 2)),
                "--resolve",
                f"{host}:443:{ip}",
                "--output",
                str(target),
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode == 0 and target.exists() and target.stat().st_size > 1024
    except OSError:
        return False


def _download_single_file(url: str, target: Path, config: AppConfig) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with requests.get(
            url,
            stream=True,
            timeout=config.download_timeout_s,
            headers={"User-Agent": config.user_agent, "Referer": "https://discord.com/"},
        ) as r:
            r.raise_for_status()
            with open(target, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
        return target.exists() and target.stat().st_size > 1024
    except Exception:
        return False


def _try_jdnext_missing_fallbacks(
    *,
    all_urls: List[str],
    classified: Dict[str, object],
    downloaded: Dict[str, str],
    download_dir: Path,
    config: AppConfig,
) -> None:
    """Best-effort recovery for JDNext when private links fail in this environment.

    - mapPackage: try cached local mapPackage bundle from temp/jdnext_downloads.
    Preview audio/video are intentionally excluded.
    """
    expected_video = cast(Optional[str], classified.get("video"))
    expected_audio = cast(Optional[str], classified.get("audio"))
    expected_scene = cast(Optional[str], classified.get("mainscene"))

    _ = expected_video
    _ = expected_audio

    if expected_scene:
        expected_scene_name = get_filename_from_url(expected_scene)
        if expected_scene_name not in downloaded:
            local_cache = Path(__file__).resolve().parents[2] / "temp" / "jdnext_downloads"
            candidates = []
            if local_cache.exists():
                candidates.extend(local_cache.glob("*mapPackage*.bundle"))
                candidates.extend(local_cache.glob("*_mapPackage.bundle"))
                candidates.extend(local_cache.glob("*.bundle"))
            for cand in candidates:
                try:
                    if cand.is_file() and cand.stat().st_size > 1024:
                        target = download_dir / expected_scene_name
                        shutil.copy2(cand, target)
                        downloaded[expected_scene_name] = str(target)
                        logger.warning("JDNext fallback: reusing local bundle cache for %s", expected_scene_name)
                        break
                except OSError:
                    continue


def _extract_jdnext_aux_texture_bundles(
    *,
    download_dir: Path,
    extract_dir: Path,
    mainscene_name: str,
    codename: str,
) -> int:
    """Decode JDNext non-mapPackage bundles and copy loose texture payloads.

    These bundles usually contain Cover/Coach/Title/background images that are
    not present in mapPackage payloads.
    """
    copied = 0
    strategy_aux_root = extract_dir / "jdnext_strategy" / "aux_bundles"
    menuart_root = extract_dir / "menuart"
    menuart_root.mkdir(parents=True, exist_ok=True)

    mainscene_name_low = mainscene_name.lower()
    for bundle_path in sorted(download_dir.glob("*.bundle")):
        if bundle_path.name.lower() == mainscene_name_low:
            continue

        export_dir = strategy_aux_root / bundle_path.stem
        try:
            _run_assetstudio_export(bundle_path, export_dir, "2021.3.9f1")
        except Exception as exc:
            logger.debug("JDNext aux bundle export failed (%s): %s", bundle_path.name, exc)
            continue

        for asset_dir_name in ("Texture2D", "Sprite"):
            asset_dir = export_dir / asset_dir_name
            if not asset_dir.exists():
                continue

            for src in asset_dir.glob("*.png"):
                dst_name = src.name
                if not dst_name.lower().startswith(codename.lower() + "_") and dst_name.lower().startswith(("cover", "coach", "banner", "map_", "title")):
                    dst_name = f"{codename}_{dst_name}"
                dst = menuart_root / dst_name
                if dst.exists():
                    continue
                shutil.copy2(src, dst)
                copied += 1

    if copied:
        logger.info("JDNext aux bundle texture import: copied %d texture(s)", copied)
    return copied


# ---------------------------------------------------------------------------
# File downloader
# ---------------------------------------------------------------------------

def _classify_urls(
    urls: List[str], quality: str, config: Optional[AppConfig] = None
) -> Dict[str, object]:
    """Classify URLs into video, audio, mainscene, and other assets."""
    jdnext_video_re = re.compile(r"/video_(ultra|high|mid|low)\.(hd|vp8|vp9)\.webm/", re.IGNORECASE)

    video_urls_by_quality: Dict[str, str] = {}
    jdnext_variant_by_quality: Dict[str, str] = {}
    audio_url: Optional[str] = None
    scene_zips: Dict[str, str] = {}
    other_urls: List[str] = []

    for u in urls:
        u_low = u.lower()
        if any(token in u_low for token in ("audiopreview", "videopreview", "mappreview")):
            continue

        jdnext_q: Optional[str] = None
        jdnext_variant: Optional[str] = None
        m = jdnext_video_re.search(u)
        if m:
            tier = m.group(1).upper()
            variant = m.group(2).lower()
            jdnext_variant = variant
            # JDNext tier mapping:
            # - *_HD tiers use .hd variants
            # - non-HD tiers use .vp9 variants (later converted to VP8 on install)
            # - .vp8 is treated as fallback for *_HD only
            if variant == "hd":
                jdnext_q = f"{tier}_HD"
            elif variant == "vp9":
                jdnext_q = tier
            elif variant == "vp8":
                jdnext_q = f"{tier}_HD"
        for q, pattern in QUALITY_PATTERNS.items():
            if pattern in u:
                video_urls_by_quality[q] = u
                break
        if jdnext_q:
            existing_variant = jdnext_variant_by_quality.get(jdnext_q)
            if existing_variant is None:
                video_urls_by_quality[jdnext_q] = u
                if jdnext_variant:
                    jdnext_variant_by_quality[jdnext_q] = jdnext_variant
            elif jdnext_variant == "hd" and existing_variant == "vp8":
                # Prefer .hd when both .hd and .vp8 are present for the HD slot.
                video_urls_by_quality[jdnext_q] = u
                jdnext_variant_by_quality[jdnext_q] = jdnext_variant
        if (
            (
                ".ogg" in u
                or ".opus" in u
            )
            and "audiopreview" not in u.lower()
        ):
            audio_url = u
        elif "MAIN_SCENE" in u and ".zip" in u:
            for plat in ["X360", "DURANGO", "SCARLETT", "NX", "ORBIS", "PROSPERO", "PC", "GGP", "WIIU"]:
                if f"MAIN_SCENE_{plat}" in u:
                    scene_zips[plat] = u
                    break
        elif "mappackage" in u.lower() and ".bundle" in u.lower():
            scene_zips["MAP_PACKAGE"] = u
        elif any(ext in u.lower() for ext in (".ckd", ".jpg", ".jpeg", ".png", ".ad", ".bundle", ".opus")):
            if ".ckd" in u.lower() or ".ad" in u.lower() or ("discordapp.net" not in u):
                other_urls.append(u)

    # Select best video
    video_url = None

    def _build_quality_search_order(selected_quality: str) -> List[str]:
        tiers = ["ULTRA", "HIGH", "MID", "LOW"]
        selected = (selected_quality or "ULTRA_HD").upper()
        cfg = config or AppConfig()
        vp9_mode = getattr(cfg, "vp9_handling_mode", "reencode_to_vp8")

        if selected.endswith("_HD"):
            selected_tier = selected[:-3]
            selected_is_hd = True
        else:
            selected_tier = selected
            selected_is_hd = False

        if selected_tier not in tiers:
            selected_tier = "ULTRA"

        # Compatibility mode requested by user: avoid VP9 tiers entirely and
        # pick the next compatible HD tier down.
        if vp9_mode == "fallback_compatible_down":
            start_idx = tiers.index(selected_tier)
            if not selected_is_hd:
                start_idx = min(start_idx + 1, len(tiers) - 1)
            return [f"{tier}_HD" for tier in tiers[start_idx:]]

        prefer_hd_first = selected_is_hd

        start_idx = tiers.index(selected_tier)
        ordered_tiers = tiers[start_idx:]

        order: List[str] = []
        for tier in ordered_tiers:
            if prefer_hd_first:
                order.extend([f"{tier}_HD", tier])
            else:
                order.extend([tier, f"{tier}_HD"])

        # Ensure uniqueness while preserving order
        deduped: List[str] = []
        for item in order:
            if item in QUALITY_ORDER and item not in deduped:
                deduped.append(item)
        return deduped

    search_order = _build_quality_search_order(quality)
    for q in search_order:
        if q in video_urls_by_quality:
            video_url = video_urls_by_quality[q]
            break

    # Select best mainscene/map package
    main_scene_url = None
    for plat in SCENE_PLATFORM_PREFERENCE:
        if plat in scene_zips:
            main_scene_url = scene_zips[plat]
            break
    if not main_scene_url and "MAP_PACKAGE" in scene_zips:
        main_scene_url = scene_zips["MAP_PACKAGE"]
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

    classified = _classify_urls(urls, quality, config)
    important_urls: List[str] = []
    for key in ("video", "audio", "mainscene"):
        value = cast(Optional[str], classified.get(key))
        if value:
            important_urls.append(value)
    important_urls.extend(cast(List[str], classified.get("others", [])))

    unique_urls = list(set(important_urls))
    # Prioritize: mainscene > audio > video > others
    def priority(u):
        if "MAIN_SCENE" in u or "mappackage" in u.lower(): return 0
        if ".ogg" in u or ".wav" in u: return 1
        if ".opus" in u: return 1
        if any(pat in u for pat in QUALITY_PATTERNS.values()): return 2
        if re.search(r"/video_(ultra|high|mid|low)\.(hd|vp9|vp8)\.webm/", u, re.IGNORECASE): return 2
        return 3
    
    unique_urls.sort(key=priority)
    
    downloaded: Dict[str, str] = {}
    total = len(unique_urls)
    selected_video_url = classified.get("video")
    selected_video_fname = get_filename_from_url(selected_video_url) if selected_video_url else None

    session = requests.Session()
    session.headers.update({"User-Agent": config.user_agent})
    session.headers.update({"Referer": "https://discord.com/"})

    for idx, url in enumerate(unique_urls):
        fname = get_filename_from_url(url)
        target = download_path / fname
        is_nohud_video = _is_nohud_video_url(url)

        # Check if already in cache and not empty
        if target.exists() and target.stat().st_size > 1024:
            if is_nohud_video and not _is_valid_webm_file(target, config):
                logger.warning("Cached NOHUD video %s is corrupt, redownloading...", fname)
                target.unlink(missing_ok=True)
            else:
                logger.info("%s already in cache, skipping download.", fname)
                downloaded[fname] = str(target)
                continue
        
        if target.exists():
            target.unlink()

        # Respect selected tier: do not silently substitute a different cached
        # gameplay quality when the requested file is missing.

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
                    if is_nohud_video and not _is_valid_webm_file(target, config):
                        logger.warning("Installed NOHUD video %s failed integrity check, redownloading...", fname)
                        target.unlink(missing_ok=True)
                        continue
                    found_in_game = True
                    break
        
        if found_in_game:
            downloaded[fname] = str(target)
            continue

        logger.info("Downloading %s... (%d/%d)", fname, idx + 1, total)
        if progress_callback:
            progress_callback(fname, idx + 1, total)

        success = False
        prefer_curl_resolve = "cdn-jdhelper.ramaprojects.ru" in url.lower()
        if prefer_curl_resolve:
            logger.info("Using curl --resolve as primary downloader for %s", fname)
            if _download_with_curl_resolve(url, target, config.download_timeout_s):
                if is_nohud_video and not _is_valid_webm_file(target, config):
                    logger.warning("curl --resolve primary download produced corrupt NOHUD video %s", fname)
                    target.unlink(missing_ok=True)
                else:
                    success = True

        if success:
            downloaded[fname] = str(target)
            time.sleep(config.inter_request_delay_s)
            continue

        for attempt in range(1, config.max_retries + 1):
            try:
                with session.get(url, stream=True, timeout=config.download_timeout_s) as r:
                    if r.status_code == 429:
                        retry_after = _parse_retry_after_seconds(
                            r.headers.get("Retry-After"),
                            config.retry_base_delay_s * attempt,
                        )
                        logger.warning(
                            "Rate limited (429) for %s. Waiting %ds before retry %d/%d...",
                            fname,
                            retry_after,
                            attempt,
                            config.max_retries,
                        )
                        if attempt < config.max_retries:
                            time.sleep(retry_after)
                            continue
                        else:
                            break

                    if r.status_code in (403, 404):
                        logger.warning(
                            "HTTP %d for %s (links may have expired).",
                            r.status_code,
                            fname,
                        )
                        break
                            
                    r.raise_for_status()
                    total_size = int(r.headers.get('content-length', 0))
                    
                    with open(target, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024*1024):
                            if chunk:
                                f.write(chunk)
                    
                    # Verify download success (non-zero size)
                    if target.stat().st_size > 1024:
                        if is_nohud_video and not _is_valid_webm_file(target, config):
                            logger.warning(
                                "Downloaded NOHUD video %s failed integrity check (attempt %d/%d)",
                                fname,
                                attempt,
                                config.max_retries,
                            )
                            target.unlink(missing_ok=True)
                            if attempt < config.max_retries:
                                time.sleep(config.retry_base_delay_s * (2 ** (attempt - 1)))
                                continue
                            break
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
            if prefer_curl_resolve:
                logger.warning("Trying curl --resolve fallback download for %s", fname)
                if _download_with_curl_resolve(url, target, config.download_timeout_s):
                    if is_nohud_video and not _is_valid_webm_file(target, config):
                        logger.warning("curl --resolve downloaded corrupt NOHUD video %s", fname)
                        target.unlink(missing_ok=True)
                    else:
                        logger.info("curl --resolve fallback succeeded for %s", fname)
                        downloaded[fname] = str(target)
                        time.sleep(config.inter_request_delay_s)
                        continue

                logger.warning("Trying PowerShell fallback download for %s", fname)
                if _download_with_powershell(url, target, config.download_timeout_s):
                    if is_nohud_video and not _is_valid_webm_file(target, config):
                        logger.warning("PowerShell fallback downloaded corrupt NOHUD video %s", fname)
                        target.unlink(missing_ok=True)
                    else:
                        logger.info("PowerShell fallback succeeded for %s", fname)
                        downloaded[fname] = str(target)
                        time.sleep(config.inter_request_delay_s)
                        continue
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
    except Exception as exc:
        if _is_browser_closed_error(exc):
            raise WebExtractionError("Browser was closed by user. Fetch cancelled.") from exc
        logger.info(
            "Please log in to Discord in the browser window. "
            "Waiting up to %d seconds...", timeout_s
        )
        try:
            await textbox.wait_for(timeout=timeout_s * 1000)
        except Exception as inner_exc:
            if _is_browser_closed_error(inner_exc):
                raise WebExtractionError("Browser was closed by user. Fetch cancelled.") from inner_exc
            raise
        logger.info("Login detected.")
        await page.wait_for_timeout(3000)


async def _get_last_accessory_id(page) -> Optional[str]:
    """Return the DOM id of the last message-accessories element."""
    accessories = page.locator(_SEL_MESSAGE_ACCESSORIES)
    count = await accessories.count()
    if count == 0:
        return None
    return await accessories.nth(count - 1).get_attribute("id")


async def _get_last_message_id(page) -> Optional[str]:
    """Return the DOM id of the last message list item."""
    messages = page.locator(_SEL_MESSAGE_LIST_ITEMS)
    count = await messages.count()
    if count == 0:
        return None
    return await messages.nth(count - 1).get_attribute("id")


async def _wait_for_new_message(
    page, previous_last_message_id: Optional[str], timeout_s: int = 60
) -> str:
    """Poll for a newly appended message list item."""
    logger.info("Waiting for bot message response...")
    deadline = asyncio.get_event_loop().time() + timeout_s

    while asyncio.get_event_loop().time() < deadline:
        result = await page.evaluate(
            """(prevId) => {
                const all = document.querySelectorAll('li[id^="chat-messages-"]');
                if (all.length === 0) return null;
                const last = all[all.length - 1];
                const textContent = last.textContent || '';
                const hasContent = !!last.querySelector('[id^="message-content-"]');
                const hasAccessories = !!last.querySelector('[id^="message-accessories-"]');
                return {
                    id: last.id,
                    hasContent,
                    hasAccessories,
                    isLoading: textContent.includes('Loading'),
                };
            }""",
            previous_last_message_id,
        )

        if (
            result
            and result["id"] != previous_last_message_id
            and (result["hasContent"] or result["hasAccessories"])
            and not result["isLoading"]
        ):
            stable = True
            for _ in range(3):
                await page.wait_for_timeout(350)
                latest = await page.evaluate(
                    """() => {
                        const all = document.querySelectorAll('li[id^="chat-messages-"]');
                        if (all.length === 0) return null;
                        const last = all[all.length - 1];
                        return {
                            id: last.id,
                            isLoading: (last.textContent || '').includes('Loading'),
                        };
                    }"""
                )
                if not latest or latest["id"] != result["id"] or latest["isLoading"]:
                    stable = False
                    break
            if stable:
                logger.info("Bot message response detected (%s).", result["id"])
                return result["id"]

        await page.wait_for_timeout(400)

    raise WebExtractionError(
        "Timed out waiting for bot message response. "
        "The bot might be offline or the button interaction failed."
    )


async def _extract_message_payload(page, message_id: str) -> Dict[str, str]:
    """Extract message content/accessories payload for a message list item."""
    payload = await page.evaluate(
        """(msgId) => {
            const root = document.getElementById(msgId);
            if (!root) return null;
            const content = root.querySelector('[id^="message-content-"]');
            const accessories = root.querySelector('[id^="message-accessories-"]');
            return {
                message_id: msgId,
                content_html: content ? content.innerHTML : '',
                content_text: content ? (content.textContent || '') : '',
                accessories_html: accessories ? accessories.outerHTML : '',
                combined_html: root.outerHTML,
            };
        }""",
        message_id,
    )
    if not payload:
        raise WebExtractionError(f"Could not extract payload for message id: {message_id}")
    return cast(Dict[str, str], payload)


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
    """Return True if embed contains valid Ubisoft map CDN links.

    Supports both legacy/public and newer/private hosts used by NOHUD.
    """
    for url in extract_urls_from_html(html):
        if _UBI_CDN_HOST_PATTERN.search(url) and _MAP_PATH_PATTERN.search(url):
            return True
    return False


def _has_gameplay_video_links(html: str) -> bool:
    """Return True if the embed contains at least one gameplay .webm link."""
    for url in extract_urls_from_html(html):
        # Ubisoft CDN links may wrap the real filename in a hashed path segment,
        # so resolve the effective filename instead of relying on raw URL suffix.
        lower_name = get_filename_from_url(url).lower()
        if not lower_name.endswith(".webm"):
            continue
        if "mappreview" in lower_name or "videopreview" in lower_name:
            continue
        return True
    return False


def _is_valid_embed_response(html: str, require_gameplay_video: bool = False) -> bool:
    """Validate an embed response before accepting it as usable."""
    if not _has_valid_cdn_links(html):
        return False
    if require_gameplay_video and not _has_gameplay_video_links(html):
        return False
    return True


def _strip_html_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def _extract_embed_fields_from_html(html: str) -> Dict[str, str]:
    """Extract Discord embed field name/value pairs from an accessory HTML block."""
    fields: Dict[str, str] = {}
    pattern = re.compile(
        r'<div class="embedFieldName[^\"]*">\s*<span>(.*?)</span>\s*</div>\s*'
        r'<div class="embedFieldValue[^\"]*">(.*?)</div>',
        re.IGNORECASE | re.DOTALL,
    )
    for raw_name, raw_value in pattern.findall(html):
        name = unescape(_strip_html_tags(raw_name)).strip().rstrip(":")
        value = unescape(_strip_html_tags(raw_value)).strip()
        if not name:
            continue
        if name in fields:
            fields[name] = f"{fields[name]}\n{value}".strip()
        else:
            fields[name] = value
    return fields


def _parse_bool_text(value: str) -> Optional[bool]:
    v = (value or "").strip().lower()
    # Keep numeric strings (0/1) numeric; coach_count uses these values.
    if v in {"true", "yes", "on"}:
        return True
    if v in {"false", "no", "off"}:
        return False
    return None


def _canonicalize_other_info_field(name: str) -> Optional[str]:
    k = re.sub(r"[^a-z0-9]+", "", name.lower())
    if "sweat" in k and "difficulty" in k:
        return "sweat_difficulty"
    if "difficulty" in k:
        return "difficulty"
    if "additionaltitle" in k:
        return "additional_title"
    if "camera" in k and "support" in k:
        return "camera_support"
    if "lyrics" in k and "color" in k:
        return "lyrics_color"
    if "title" in k and "logo" in k:
        return "title_logo"
    if "map" in k and "length" in k:
        return "map_length"
    if "original" in k and "version" in k:
        return "original_jd_version"
    if "coach" in k and "count" in k:
        return "coach_count"
    return None


def _extract_kv_pairs_from_text(text: str) -> Dict[str, str]:
    """Extract key/value pairs from plain text response lines (Key: Value)."""
    result: Dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if key in result and value:
            result[key] = f"{result[key]}\n{value}".strip()
        else:
            result[key] = value
    return result


def _extract_labeled_value(text: str, label_pattern: str) -> str:
    """Return the last "<label>: <value>" match from flattened message text."""
    src = re.sub(r"\s+", " ", text or "").strip()
    if not src:
        return ""

    matches = list(
        re.finditer(rf"{label_pattern}\s*:\s*(.+?)(?=$)", src, re.IGNORECASE)
    )
    if not matches:
        return ""
    return matches[-1].group(1).strip()


def _parse_jdnext_button_payloads(metadata_payloads: Dict[str, Dict[str, str]]) -> Dict[str, object]:
    """Parse button response payloads into a structured metadata dict."""
    sections: Dict[str, Dict[str, object]] = {}
    parsed: Dict[str, object] = {
        "sections": sections,
        "tags": [],
        "coach_names": [],
        "credits": "",
        "other_info": {},
    }

    for key, payload in metadata_payloads.items():
        html_src = str(payload.get("accessories_html") or payload.get("content_html") or "")
        text_src = str(payload.get("content_text") or "")
        html_fields = _extract_embed_fields_from_html(html_src)
        text_fields = _extract_kv_pairs_from_text(text_src)
        merged_fields = dict(html_fields)
        for field_name, field_value in text_fields.items():
            if field_name in merged_fields and field_value:
                merged_fields[field_name] = f"{merged_fields[field_name]}\n{field_value}".strip()
            else:
                merged_fields[field_name] = field_value

        combined_text = unescape(_strip_html_tags(payload.get("combined_html", "")))
        combined_text = re.sub(r"\s+", " ", combined_text).strip()
        sections[key] = {
            "fields": merged_fields,
            "text": combined_text,
            "message_id": payload.get("message_id", ""),
        }

    # Tags
    tag_fields = sections.get("tags", {}).get("fields", {}) if sections.get("tags") else {}
    tags: List[str] = []
    for _, value in cast(Dict[str, str], tag_fields).items():
        for token in re.split(r"[,/\\|\n]", value):
            tag = token.strip()
            if tag and tag.lower() not in {"tags", "tag"}:
                tags.append(tag)

    if not tags and sections.get("tags"):
        tag_text = str(sections.get("tags", {}).get("text", "") or "")
        tail = _extract_labeled_value(tag_text, r"tags")
        if tail:
            for token in re.split(r"[,/\\|\n]", tail):
                tag = token.strip()
                if tag and tag.lower() not in {"tags", "tag"}:
                    tags.append(tag)
    parsed["tags"] = list(dict.fromkeys(tags))

    # Coaches (preserve order from Coach 1..4 when present)
    coach_fields = sections.get("coaches", {}).get("fields", {}) if sections.get("coaches") else {}
    coach_ordered: List[str] = []
    indexed: List[tuple[int, str]] = []
    for name, value in cast(Dict[str, str], coach_fields).items():
        m = re.search(r"(\d+)", name)
        if m:
            indexed.append((int(m.group(1)), value.strip()))
        elif value.strip():
            coach_ordered.append(value.strip())
    if indexed:
        for _, value in sorted(indexed, key=lambda pair: pair[0]):
            if value:
                coach_ordered.append(value)

    if not coach_ordered and sections.get("coaches"):
        coach_text = str(sections.get("coaches", {}).get("text", "") or "")
        tail = _extract_labeled_value(coach_text, r"coaches?\s*'?\s*names")
        if tail:
            for token in re.split(r"[,/\\|\n]", tail):
                coach = token.strip()
                if coach:
                    coach_ordered.append(coach)
    parsed["coach_names"] = list(dict.fromkeys([v for v in coach_ordered if v]))

    # Credits
    credit_fields = sections.get("credits", {}).get("fields", {}) if sections.get("credits") else {}
    if credit_fields:
        parsed["credits"] = "\n".join(
            [v for v in cast(Dict[str, str], credit_fields).values() if v]
        ).strip()
    if not parsed["credits"] and sections.get("credits"):
        credit_text = str(sections.get("credits", {}).get("text", "") or "")
        parsed["credits"] = _extract_labeled_value(credit_text, r"credits")

    # Other info
    other_fields = sections.get("other_info", {}).get("fields", {}) if sections.get("other_info") else {}
    other_info: Dict[str, object] = {}
    for name, value in cast(Dict[str, str], other_fields).items():
        canonical = _canonicalize_other_info_field(name)
        if not canonical:
            continue
        bool_val = _parse_bool_text(value)
        other_info[canonical] = bool_val if bool_val is not None else value.strip()
    parsed["other_info"] = other_info

    return parsed


async def _click_button_from_accessory(
    page,
    *,
    accessory_id: str,
    label_patterns: List[re.Pattern[str]],
) -> bool:
    """Click a button within a specific message accessory by label pattern."""
    base = page.locator(f"#{accessory_id} button")
    for pattern in label_patterns:
        candidate = base.filter(has_text=pattern).first
        try:
            if await candidate.count() > 0:
                await candidate.click()
                return True
        except Exception:
            continue
    return False


async def _fetch_jdnext_button_metadata(
    page,
    *,
    assets_accessory_id: str,
    timeout_s: int,
) -> Dict[str, Dict[str, str]]:
    """Click JDNext metadata buttons and capture each reply message payload."""
    button_map: Dict[str, List[re.Pattern[str]]] = {
        "tags": [re.compile(r"^\s*tags\s*$", re.IGNORECASE)],
        "coaches": [
            re.compile(r"coach(?:es)?\s*'?\s*names", re.IGNORECASE),
            re.compile(r"coach\s*names", re.IGNORECASE),
        ],
        "credits": [re.compile(r"^\s*credits\s*$", re.IGNORECASE)],
        "other_info": [
            re.compile(r"other\s*info", re.IGNORECASE),
            re.compile(r"other\s*information", re.IGNORECASE),
        ],
    }
    payloads: Dict[str, Dict[str, str]] = {}

    for key, patterns in button_map.items():
        pre_msg_id = await _get_last_message_id(page)
        clicked = await _click_button_from_accessory(
            page,
            accessory_id=assets_accessory_id,
            label_patterns=patterns,
        )
        if not clicked:
            logger.warning("Could not find JDNext metadata button for %s", key)
            continue

        response_msg_id = await _wait_for_new_message(page, pre_msg_id, timeout_s=timeout_s)
        payloads[key] = await _extract_message_payload(page, response_msg_id)
        await page.wait_for_timeout(300)

    return payloads


async def _fetch_command_with_retry(
    page,
    *,
    command: str,
    choices: List[str],
    codename: str,
    label: str,
    max_retries: int = 2,
    bot_timeout_s: int = 60,
    require_gameplay_video: bool = False,
) -> str:
    """Send a slash command, wait for bot response, extract and validate HTML.

    Retries up to ``max_retries`` times if the response has no valid CDN links.
    """
    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.info("Retrying %s (attempt %d/%d)...", label, attempt + 1, max_retries + 1)
            try:
                await page.wait_for_timeout(3000)
            except Exception as exc:
                if _is_browser_closed_error(exc):
                    raise WebExtractionError("Browser was closed by user. Fetch cancelled.") from exc
                raise

        try:
            pre_id = await _get_last_accessory_id(page)
            await _send_slash_command(page, command=command, choices=choices, codename=codename)
            embed_id = await _wait_for_new_embed(page, pre_id, timeout_s=bot_timeout_s)
            html = await _extract_embed_html(page, embed_id)

            if _is_valid_embed_response(html, require_gameplay_video=require_gameplay_video):
                logger.info("Extracted %s embed HTML.", label)
                return html

            if require_gameplay_video:
                logger.warning(
                    "%s response has no valid gameplay video links (bot may have returned an error).",
                    label,
                )
            else:
                logger.warning(
                    "%s response has no valid CDN links (bot may have returned an error).",
                    label,
                )
        except WebExtractionError as e:
            if attempt == max_retries:
                raise
            logger.warning("%s attempt %d failed: %s", label, attempt + 1, e)
        except Exception as e:
            if _is_browser_closed_error(e):
                raise WebExtractionError("Browser was closed by user. Fetch cancelled.") from e
            if attempt == max_retries:
                raise
            logger.warning("%s attempt %d failed: %s", label, attempt + 1, e)

    if require_gameplay_video:
        raise WebExtractionError(
            f"{label} response contained no valid gameplay video links after "
            f"{max_retries + 1} attempts.\n"
            "The bot may not have data for this codename, or NOHUD links are invalid/expired."
        )

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
         automates Discord slash commands (JDU: ``/assets jdu <codename>`` +
         ``/nohud <codename>``; JDNext: ``/asset server:jdnext codename:<codename>``),
         captures the bot's embed HTML, then
       downloads the CDN URLs.
    """

    def __init__(
        self,
        asset_html: Optional[str | Path] = None,
        nohud_html: Optional[str | Path] = None,
        urls: Optional[List[str]] = None,
        codenames: Optional[List[str]] = None,
        source_game: str = "jdu",
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
        self._source_game = (source_game or "jdu").strip().lower() or "jdu"

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

        # V1-style guardrails: fail fast if key media links are missing.
        classified_required = _classify_urls(all_urls, self._quality, self._config)
        missing_required: list[str] = []
        if not classified_required.get("mainscene"):
            if self._source_game == "jdnext":
                missing_required.append("mapPackage bundle")
            else:
                missing_required.append("MAIN_SCENE zip")
        if not classified_required.get("audio"):
            if self._source_game == "jdnext":
                missing_required.append("full audio (.opus/.ogg)")
            else:
                missing_required.append("full audio (.ogg)")
        if not classified_required.get("video"):
            missing_required.append("gameplay video (.webm)")

        if missing_required:
            raise WebExtractionError(
                "Missing required download links: "
                + ", ".join(missing_required)
                + ". The bot likely returned an error, or the HTML links are stale/invalid."
            )

        inferred_codename = extract_codename_from_urls(all_urls)
        if not inferred_codename and self._codenames:
            inferred_codename = self._codenames[0]
        if not inferred_codename and self._asset_html and Path(self._asset_html).exists():
            try:
                html_content = Path(self._asset_html).read_text(encoding="utf-8", errors="ignore")
                inferred_codename = _extract_embed_title_from_html(html_content)
            except OSError:
                pass

        self._codename = inferred_codename or self._codename
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
        classified = _classify_urls(all_urls, self._quality, self._config)
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
                refreshed = download_files(all_urls, download_dir, self._quality, self._config)
                downloaded.update(refreshed)

        # V1 parity: fail fast when critical assets remain unavailable.
        classified = _classify_urls(all_urls, self._quality, self._config)
        still_missing: list[str] = []
        for key in ("video", "audio", "mainscene"):
            url = classified.get(key)
            if not url:
                continue
            fname = get_filename_from_url(url)
            if fname not in downloaded:
                still_missing.append(f"{key}:{fname}")

        if still_missing:
            if self._source_game == "jdnext":
                _try_jdnext_missing_fallbacks(
                    all_urls=all_urls,
                    classified=classified,
                    downloaded=downloaded,
                    download_dir=download_dir,
                    config=self._config,
                )
                still_missing = []
                for key in ("video", "audio", "mainscene"):
                    url = classified.get(key)
                    if not url:
                        continue
                    fname = get_filename_from_url(url)
                    if fname not in downloaded:
                        still_missing.append(f"{key}:{fname}")

        if still_missing:
            raise WebExtractionError(
                "Critical download(s) missing after retry: "
                + ", ".join(still_missing)
                + ". Links may have expired; fetch fresh assets/nohud HTML and retry."
            )

        # 2. Extract/Assemble into temporary output_dir
        extract_dir = output_dir / codename
        extract_dir.mkdir(parents=True, exist_ok=True)

        if self._source_game == "jdnext":
            mainscene_url = cast(Optional[str], classified.get("mainscene"))
            if mainscene_url:
                mainscene_name = get_filename_from_url(mainscene_url)
                mainscene_path = download_dir / mainscene_name
                if mainscene_path.exists() and mainscene_path.suffix.lower() == ".bundle":
                    strategy_dir = extract_dir / "jdnext_strategy"
                    try:
                        summary = run_jdnext_bundle_strategy(
                            mainscene_path,
                            strategy_dir,
                            strategy="assetstudio_first",
                            codename=codename,
                        )
                        mapped_root = strategy_dir / "mapped"
                        if mapped_root.exists():
                            for child in mapped_root.iterdir():
                                dst = extract_dir / child.name
                                if child.is_dir():
                                    shutil.copytree(child, dst, dirs_exist_ok=True)
                                else:
                                    shutil.copy2(child, dst)
                        logger.info("JDNext mapPackage strategy winner: %s", summary.winner)
                    except Exception as exc:
                        logger.warning("JDNext mapPackage strategy extraction failed: %s", exc)

                    try:
                        _extract_jdnext_aux_texture_bundles(
                            download_dir=download_dir,
                            extract_dir=extract_dir,
                            mainscene_name=mainscene_name,
                            codename=codename,
                        )
                    except Exception as exc:
                        logger.warning("JDNext auxiliary texture extraction failed: %s", exc)
        
        # Post-download: extract MAIN_SCENE_*.zip from download_dir into extract_dir
        self._extract_scene_zips(download_dir, extract_dir)
        
        # Copy non-extracted assets (e.g. video, audio) to extract_dir for normalizer
        for f in os.listdir(download_dir):
            src_file = download_dir / f
            dst_file = extract_dir / f
            low_name = f.lower()
            if any(token in low_name for token in ("audiopreview", "videopreview", "mappreview")):
                continue
            if src_file.is_file() and not f.endswith(".zip") and not dst_file.exists():
                logger.debug("Copying %s to extraction dir", f)
                shutil.copy2(src_file, dst_file)

        return extract_dir

    def get_codename(self) -> Optional[str]:
        return self._codename

    @staticmethod
    def _extract_scene_zips(src_dir: Path, dst_dir: Optional[Path] = None) -> None:
        """Extract MAIN_SCENE_*.zip files from src_dir into dst_dir.

        Mirrors V1 ``step_03_extract_scenes``.  After downloading, the
        normalizer expects loose ``.ckd`` files — not a ZIP.
        """
        if dst_dir is None:
            dst_dir = src_dir

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
        JDU: ``/assets`` → ``/nohud``; JDNext: ``/asset server:jdnext``;
        then save HTML and return extracted URLs.
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

                nohud_html: Optional[str] = None
                jdnext_metadata_payloads: Dict[str, Dict[str, str]] = {}
                if self._source_game == "jdnext":
                    logger.info("[1/1] /asset server:jdnext %s", codename)
                    assets_html = await _fetch_command_with_retry(
                        page,
                        command="asset",
                        choices=["jdnext"],
                        codename=codename,
                        label="asset",
                        bot_timeout_s=bot_timeout,
                        require_gameplay_video=True,
                    )
                    assets_accessory_id = await _get_last_accessory_id(page)
                    if assets_accessory_id:
                        try:
                            jdnext_metadata_payloads = await _fetch_jdnext_button_metadata(
                                page,
                                assets_accessory_id=assets_accessory_id,
                                timeout_s=bot_timeout,
                            )
                        except Exception as meta_exc:
                            logger.warning("JDNext metadata button capture failed: %s", meta_exc)
                else:
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
                # Save HTML to download dir for caching / debugging / portability
                # We use download_root which is 'mapDownloads'
                output_dir = self._config.download_root / codename
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "assets.html").write_text(assets_html, encoding="utf-8")
                if nohud_html is not None:
                    (output_dir / "nohud.html").write_text(nohud_html, encoding="utf-8")
                if self._source_game == "jdnext" and jdnext_metadata_payloads:
                    meta_dir = output_dir / "jdnext_metadata"
                    meta_dir.mkdir(parents=True, exist_ok=True)
                    for key, payload in jdnext_metadata_payloads.items():
                        (meta_dir / f"{key}.message.html").write_text(
                            payload.get("combined_html", ""),
                            encoding="utf-8",
                        )
                        (meta_dir / f"{key}.content.txt").write_text(
                            payload.get("content_text", ""),
                            encoding="utf-8",
                        )
                    metadata_summary = _parse_jdnext_button_payloads(jdnext_metadata_payloads)
                    (output_dir / "jdnext_metadata.json").write_text(
                        json.dumps(metadata_summary, indent=2, sort_keys=True),
                        encoding="utf-8",
                    )
                logger.info("Saved HTML to %s", output_dir)

            finally:
                try:
                    await context.close()
                except Exception:
                    # Context may already be closed if user manually closed browser.
                    pass

        # Extract URLs from the fetched HTML payload(s)
        all_urls = extract_urls_from_html(assets_html)
        if nohud_html is not None:
            all_urls += extract_urls_from_html(nohud_html)
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
