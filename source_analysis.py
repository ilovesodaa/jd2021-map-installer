import os
import re
import glob
from dataclasses import dataclass, field
from typing import List, Optional

import map_downloader


SUPPORTED_QUALITIES = [
    "ULTRA_HD",
    "ULTRA",
    "HIGH_HD",
    "HIGH",
    "MID_HD",
    "MID",
    "LOW_HD",
    "LOW",
]


@dataclass
class SourceSpec:
    mode: str
    submode: Optional[str] = None
    source_path: str = ""
    codename: Optional[str] = None
    asset_html: Optional[str] = None
    nohud_html: Optional[str] = None
    ipk_file: Optional[str] = None
    ipk_extracted: Optional[str] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
    ready_for_prepare: bool = False
    ready_for_install: bool = False
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _normalize(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return os.path.abspath(os.path.normpath(path.strip().strip('"').strip("'")))


def _pick_webm(folder: str, codename: Optional[str]) -> Optional[str]:
    candidates = [
        f for f in glob.glob(os.path.join(folder, "*.webm"))
        if "mappreview" not in os.path.basename(f).lower()
        and "videopreview" not in os.path.basename(f).lower()
    ]
    if not candidates:
        return None

    if codename:
        lower = codename.lower()
        matches = [p for p in candidates if os.path.basename(p).lower().startswith(lower)]
        if matches:
            candidates = matches

    for quality in SUPPORTED_QUALITIES:
        q = f"_{quality}.webm"
        for path in candidates:
            if os.path.basename(path).upper().endswith(q):
                return path

    return candidates[0]


def _extract_codename_from_ipk_name(path: str) -> str:
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0]
    stem = re.sub(r"_(x360|durango|scarlett|nx|orbis|prospero)$", "", stem, flags=re.I)
    return stem


def _find_html_pair(folder: str):
    asset = None
    nohud = None
    try:
        for name in os.listdir(folder):
            lower = name.lower()
            full = os.path.join(folder, name)
            if not os.path.isfile(full) or not lower.endswith(".html"):
                continue
            if "nohud" in lower and not nohud:
                nohud = full
            elif "asset" in lower and not asset:
                asset = full
    except OSError:
        return None, None
    return asset, nohud


def analyze_html_mode(asset_html: str, nohud_html: str) -> SourceSpec:
    asset_html = _normalize(asset_html)
    nohud_html = _normalize(nohud_html)
    spec = SourceSpec(mode="html", source_path=os.path.dirname(asset_html or nohud_html or ""))
    spec.asset_html = asset_html
    spec.nohud_html = nohud_html

    if not asset_html or not os.path.isfile(asset_html):
        spec.errors.append("Asset HTML is required.")
    if not nohud_html or not os.path.isfile(nohud_html):
        spec.errors.append("NOHUD HTML is required.")

    if not spec.errors:
        spec.ready_for_prepare = True
        spec.ready_for_install = True
    return spec


def analyze_ipk_file_mode(ipk_file: str, audio_path: str = "", video_path: str = "") -> SourceSpec:
    ipk_file = _normalize(ipk_file)
    audio_path = _normalize(audio_path)
    video_path = _normalize(video_path)
    spec = SourceSpec(mode="ipk", source_path=os.path.dirname(ipk_file or ""), ipk_file=ipk_file)

    if not ipk_file or not os.path.isfile(ipk_file):
        spec.errors.append("A valid .ipk file is required.")
        return spec

    spec.codename = _extract_codename_from_ipk_name(ipk_file)

    source_dir = os.path.dirname(ipk_file)
    if not audio_path:
        guessed = os.path.join(source_dir, f"{spec.codename}.ogg")
        if os.path.isfile(guessed):
            audio_path = guessed
    if not video_path:
        video_path = _pick_webm(source_dir, spec.codename)

    spec.audio_path = audio_path
    spec.video_path = video_path
    spec.ipk_extracted = os.path.join(source_dir, "ipk_extracted")
    spec.ready_for_prepare = True

    if not spec.audio_path:
        spec.errors.append("Audio (.ogg) is required for install.")
    if not spec.video_path:
        spec.errors.append("Gameplay video (.webm) is required for install.")

    spec.ready_for_install = len(spec.errors) == 0 and os.path.isdir(spec.ipk_extracted)
    return spec


def analyze_manual_mode(folder: str, submode: str = "auto") -> SourceSpec:
    folder = _normalize(folder)
    spec = SourceSpec(mode="manual", submode=submode, source_path=folder or "")
    if not folder or not os.path.isdir(folder):
        spec.errors.append("Select a valid source folder.")
        return spec

    asset_html, nohud_html = _find_html_pair(folder)
    ipk_files = glob.glob(os.path.join(folder, "*.ipk"))
    has_world = os.path.isdir(os.path.join(folder, "world"))
    has_cache = os.path.isdir(os.path.join(folder, "cache"))

    detected_submode = submode
    if submode == "auto":
        if ipk_files and (has_world or has_cache):
            detected_submode = "unpacked_ipk"
        elif asset_html or nohud_html:
            detected_submode = "downloaded_assets"
        else:
            detected_submode = "downloaded_assets"
    spec.submode = detected_submode

    if detected_submode == "unpacked_ipk":
        spec.ipk_file = ipk_files[0] if ipk_files else None
        spec.codename = _extract_codename_from_ipk_name(spec.ipk_file) if spec.ipk_file else os.path.basename(folder)

        spec.ipk_extracted = folder
        spec.audio_path = os.path.join(folder, f"{spec.codename}.ogg")
        if not os.path.isfile(spec.audio_path):
            spec.audio_path = None
        spec.video_path = _pick_webm(folder, spec.codename)

        if not os.path.isdir(os.path.join(folder, "world", "maps")):
            spec.errors.append("Unpacked IPK folder must contain world/maps/.")
        if not spec.audio_path:
            spec.errors.append("Audio (.ogg) not found in unpacked source folder.")
        if not spec.video_path:
            spec.errors.append("Gameplay video (.webm) not found in unpacked source folder.")

        spec.ready_for_prepare = len(spec.errors) == 0
        spec.ready_for_install = spec.ready_for_prepare
        return spec

    # downloaded_assets
    spec.asset_html = asset_html
    spec.nohud_html = nohud_html

    # Prefer codename parsed from HTML URLs, then fallback to media names/folder.
    for html_path in (asset_html, nohud_html):
        if not html_path:
            continue
        try:
            urls = map_downloader.extract_urls(html_path)
            parsed = map_downloader.extract_codename_from_urls(urls)
            if parsed:
                spec.codename = parsed
                break
        except Exception:
            pass

    if not spec.codename:
        oggs = [f for f in glob.glob(os.path.join(folder, "*.ogg")) if "AudioPreview" not in os.path.basename(f)]
        if oggs:
            spec.codename = os.path.splitext(os.path.basename(oggs[0]))[0]
        else:
            spec.codename = os.path.basename(folder)

    spec.audio_path = os.path.join(folder, f"{spec.codename}.ogg")
    if not os.path.isfile(spec.audio_path):
        oggs = [f for f in glob.glob(os.path.join(folder, "*.ogg")) if "AudioPreview" not in os.path.basename(f)]
        spec.audio_path = oggs[0] if oggs else None

    spec.video_path = _pick_webm(folder, spec.codename)

    if not (spec.asset_html or spec.nohud_html):
        spec.errors.append("Downloaded assets mode requires assets.html or nohud.html.")
    if not spec.audio_path:
        spec.errors.append("Audio (.ogg) not found in folder.")
    if not spec.video_path:
        spec.errors.append("Gameplay video (.webm) not found in folder.")

    ipk_extracted = os.path.join(folder, "ipk_extracted")
    if os.path.isdir(ipk_extracted):
        spec.ipk_extracted = ipk_extracted
    else:
        spec.warnings.append("ipk_extracted/ not found. Prepare step must extract map scene/IPK first.")

    spec.ready_for_prepare = len(spec.errors) == 0
    spec.ready_for_install = spec.ready_for_prepare and bool(spec.ipk_extracted)
    return spec
