import os
import re
import urllib.request
import urllib.error
import ssl
import json
import zipfile
import shutil
import argparse
import time
from urllib.parse import urlparse, unquote
from log_config import get_logger
from helpers import DOWNLOAD_TIMEOUT_S

logger = get_logger("map_downloader")

# SSL certificate verification disabled for Ubisoft CDN compatibility.
# Some systems fail to verify Ubisoft's CDN certificates; this is intentional.
ssl._create_default_https_context = ssl._create_unverified_context

_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
               "AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/131.0.0.0 Safari/537.36")
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2   # seconds; doubles each retry
_INTER_REQUEST_DELAY = 0.5  # seconds between sequential downloads

def extract_urls(html_file):
    if not os.path.isfile(html_file):
        raise FileNotFoundError(f"HTML file not found: {html_file}")

    try:
        with open(html_file, "r", encoding="utf-8") as f:
            html = f.read()
    except UnicodeDecodeError as e:
        raise ValueError(f"Cannot read HTML file (encoding error): {e}") from e

    urls = re.findall(r'href="(https?://[^"]+)"', html)

    clean_urls = set()
    for url in urls:
        if "discordapp.net" in url: continue
        url = url.replace("&amp;", "&")
        clean_urls.add(url)
    return list(clean_urls)

def get_filename_from_url(url):
    parsed = urlparse(url)
    path = unquote(parsed.path)  # Decode %XX URL encoding for non-ASCII filenames
    parts = path.split('/')
    if len(parts) >= 2 and "." in parts[-2]:
        return parts[-2]
    return parts[-1]

def extract_codename_from_urls(urls):
    """Extract the map codename from JDU asset URLs.
    URL pattern: https://jd-s3.cdn.ubi.com/public/map/{MapName}/...
    Returns the MapName string, or None if not found.
    """
    for url in urls:
        parsed = urlparse(url)
        parts = parsed.path.strip('/').split('/')
        # Path segments: public / map / {MapName} / ...
        if len(parts) >= 3 and parts[0] == 'public' and parts[1] == 'map':
            codename = parts[2]
            if codename:
                return codename
    return None

# Quality tiers in descending order. Each tier maps to the URL/filename suffix pattern.
# Patterns are mutually exclusive: "_ULTRA.webm" does NOT appear inside "_ULTRA.hd.webm".
QUALITY_ORDER = [
    "ULTRA_HD", "ULTRA",
    "HIGH_HD",  "HIGH",
    "MID_HD",   "MID",
    "LOW_HD",   "LOW",
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


def find_best_video_file(download_dir, codename, preferred_quality="ULTRA_HD"):
    """Find the best available video file on disk, falling back through quality tiers.

    Args:
        download_dir: Directory containing downloaded video files.
        codename: Map codename used in the filename (e.g. "Starships").
        preferred_quality: Starting quality tier (default ULTRA_HD).

    Returns:
        tuple: (file_path, actual_quality) or (None, None) if no video found.
    """
    quality = preferred_quality.upper()
    if quality not in QUALITY_ORDER:
        quality = "ULTRA_HD"
    preferred_idx = QUALITY_ORDER.index(quality)
    search_order = QUALITY_ORDER[preferred_idx:] + QUALITY_ORDER[:preferred_idx]
    for q in search_order:
        pattern = QUALITY_PATTERNS[q]
        path = os.path.join(download_dir, f"{codename}{pattern}")
        if os.path.exists(path):
            return path, q
    return None, None


def download_files(urls, download_dir, quality="ULTRA_HD", interactive=True):
    os.makedirs(download_dir, exist_ok=True)
    downloaded = {}

    quality = quality.upper()
    if quality not in QUALITY_ORDER:
        logger.warning("Unknown quality '%s', falling back to ULTRA_HD", quality)
        quality = "ULTRA_HD"

    main_scene_zip = None
    video_url = None
    audio_url = None

    # Collect all available mainscene ZIPs by platform
    scene_zips_by_platform = {}

    # Build a map of quality -> URL for all available video URLs
    video_urls_by_quality = {}
    for u in urls:
        for q, pattern in QUALITY_PATTERNS.items():
            if pattern in u:
                video_urls_by_quality[q] = u
                break
        if ".ogg" in u and "AudioPreview" not in u:
            audio_url = u
        elif "MAIN_SCENE" in u and ".zip" in u:
            # Identify platform from URL (e.g. MAIN_SCENE_DURANGO, MAIN_SCENE_NX)
            for plat in ["DURANGO", "NX", "SCARLETT", "ORBIS", "PROSPERO", "PC", "GGP", "WIIU"]:
                if f"MAIN_SCENE_{plat}" in u:
                    scene_zips_by_platform[plat] = u
                    break

    # Select mainscene ZIP: prefer DURANGO (Kinect-compatible with PC),
    # fallback to NX, then any available platform
    SCENE_PREFERENCE = ["DURANGO", "NX", "SCARLETT"]
    for plat in SCENE_PREFERENCE:
        if plat in scene_zips_by_platform:
            main_scene_zip = scene_zips_by_platform[plat]
            if plat != "DURANGO" and "DURANGO" not in scene_zips_by_platform:
                logger.info("    Note: DURANGO mainscene not available, using %s", plat)
            break
    if not main_scene_zip and scene_zips_by_platform:
        # Fallback: pick any available platform
        fallback_plat = next(iter(scene_zips_by_platform))
        main_scene_zip = scene_zips_by_platform[fallback_plat]
        logger.info("    Note: Using %s mainscene (no preferred platform found)", fallback_plat)

    # Select video URL by quality preference (starting from requested, falling back)
    preferred_idx = QUALITY_ORDER.index(quality)
    search_order = QUALITY_ORDER[preferred_idx:] + QUALITY_ORDER[:preferred_idx]
    for q in search_order:
        if q in video_urls_by_quality:
            video_url = video_urls_by_quality[q]
            if q != quality:
                logger.info("    Requested quality %s not available, using %s", quality, q)
            break

    # Check if a video of a DIFFERENT quality already exists in download_dir
    if video_url and os.path.isdir(download_dir):
        requested_fname = get_filename_from_url(video_url)
        existing_webms = [f for f in os.listdir(download_dir)
                          if f.endswith('.webm') and 'MapPreview' not in f and 'VideoPreview' not in f]
        for existing in existing_webms:
            if existing != requested_fname:
                if interactive:
                    print(f"\n    Found existing video: {existing}")
                    print(f"    Requested quality would download: {requested_fname}")
                    print(f"    [R]euse existing  /  [D]ownload new  /  [S]top")
                    choice = input("    Choice [R/D/S]: ").strip().upper()
                    if choice == 'S':
                        raise RuntimeError("User chose to stop. Obtain new HTML links and retry.")
                    elif choice == 'R':
                        video_url = None  # Skip downloading new video
                        break
                else:
                    # Non-interactive (batch/GUI): reuse existing video silently
                    logger.info("    Reusing existing video: %s (skipping %s)", existing, requested_fname)
                    video_url = None
                    break

    important_urls = []
    if video_url: important_urls.append(video_url)
    if audio_url: important_urls.append(audio_url)
    if main_scene_zip: important_urls.append(main_scene_zip)

    for u in urls:
        if ".ckd" in u or ".jpg" in u or ".png" in u or ".ad" in u:
            if "discordapp.net" not in u:
                important_urls.append(u)

    for url in set(important_urls):
        fname = get_filename_from_url(url)
        # Rename url hash files if missing the name
        if len(fname) == 32 and "." not in fname:
            pass  # Keep it, we'll decode later

        target = os.path.join(download_dir, fname)
        if not os.path.exists(target):
            logger.info("Downloading %s...", fname)
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S) as response:
                        with open(target, "wb") as f:
                            f.write(response.read())
                    break  # success
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        retry_after = int(e.headers.get("Retry-After", _RETRY_BASE_DELAY * attempt))
                        logger.warning("    Rate limited (429). Waiting %ds before retry %d/%d...",
                                       retry_after, attempt, _MAX_RETRIES)
                        time.sleep(retry_after)
                        continue
                    if e.code in (403, 404):
                        logger.error("    HTTP %d for %s -- links may have expired!", e.code, fname)
                        if fname.endswith('.webm') and interactive:
                            existing_webms = [f for f in os.listdir(download_dir)
                                              if f.endswith('.webm') and 'MapPreview' not in f and 'VideoPreview' not in f]
                            if existing_webms:
                                print(f"    Existing video found: {existing_webms[0]}")
                                print(f"    [R]euse existing  /  [S]top and get new links")
                                choice = input("    Choice [R/S]: ").strip().upper()
                                if choice != 'R':
                                    raise RuntimeError(f"Links expired (HTTP {e.code}). Obtain new HTML and retry.")
                            else:
                                raise RuntimeError(f"Links expired (HTTP {e.code}). No existing video to reuse. Obtain new HTML and retry.")
                        elif fname.endswith('.webm'):
                            raise RuntimeError(f"Links expired (HTTP {e.code}). Cannot download video.")
                        else:
                            logger.warning("    Skipping %s (HTTP %d)", fname, e.code)
                        break  # non-retryable HTTP error
                    if attempt < _MAX_RETRIES:
                        delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning("    HTTP %d -- retrying in %ds (%d/%d)...",
                                       e.code, delay, attempt, _MAX_RETRIES)
                        time.sleep(delay)
                    else:
                        logger.error("Failed to download %s: HTTP %d", fname, e.code)
                except urllib.error.URLError as e:
                    if attempt < _MAX_RETRIES:
                        delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning("    Network error: %s -- retrying in %ds (%d/%d)...",
                                       e, delay, attempt, _MAX_RETRIES)
                        time.sleep(delay)
                    else:
                        logger.error("Failed to download %s: %s", fname, e)
                except Exception as e:
                    if attempt < _MAX_RETRIES:
                        delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        logger.warning("    Error: %s -- retrying in %ds (%d/%d)...",
                                       e, delay, attempt, _MAX_RETRIES)
                        time.sleep(delay)
                    else:
                        logger.error("Failed to download %s: %s", fname, e)
            time.sleep(_INTER_REQUEST_DELAY)
        else:
            logger.info("%s already exists, skipping download.", fname)
        downloaded[fname] = target

    return downloaded

def run(map_name, asset_html, nohud_html, jd_dir):
    if not jd_dir:
        jd_dir = os.path.dirname(os.path.abspath(__file__))
    map_dir = os.path.join(jd_dir, map_name)
    download_dir = os.path.join(map_dir, "downloads")

    urls1 = extract_urls(asset_html) if os.path.exists(asset_html) else []
    urls2 = extract_urls(nohud_html) if os.path.exists(nohud_html) else []
    all_urls = urls1 + urls2

    logger.info("Found %d URLs.", len(all_urls))
    downloaded = download_files(all_urls, download_dir)
    logger.info("Download complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-name", required=True)
    parser.add_argument("--asset-html", required=True)
    parser.add_argument("--nohud-html", required=True)
    parser.add_argument("--jd-dir", default=None)
    args = parser.parse_args()
    run(args.map_name, args.asset_html, args.nohud_html, args.jd_dir)
