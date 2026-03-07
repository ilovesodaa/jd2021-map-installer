import os
import re
import glob
from dataclasses import dataclass, field
from typing import List, Optional

import map_downloader


CKD_HEADER_SIZE = 44  # Standard UbiArt CKD header length


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


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _find_vgmstream() -> Optional[str]:
    """Locate the vgmstream executable in the bundled tools."""
    candidates = [
        # Primary: bundled in tools/vgmstream/ (committed to repo)
        os.path.join(_SCRIPT_DIR, "tools", "vgmstream", "vgmstream.exe"),
        # Legacy: 3rdPartyTools location (local dev installs)
        os.path.join(_SCRIPT_DIR, "3rdPartyTools", "jd2021pc tools",
                     "JDTools - 1.9.0", "bin", "vgmstream.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def _extract_ckd_audio(ckd_path: str, output_dir: str) -> Optional[str]:
    """Strip the 44-byte CKD header from a cooked audio file and write raw audio.

    For standard OGG/WAV payloads the header is simply stripped.  For X360
    proprietary formats (XMA etc.) vgmstream is used to decode to WAV.

    Returns the path of the extracted file, or *None* on failure.
    """
    try:
        with open(ckd_path, "rb") as f:
            data = f.read()
    except OSError:
        return None

    if len(data) <= CKD_HEADER_SIZE:
        return None

    payload = data[CKD_HEADER_SIZE:]

    if payload[:4] == b"OggS":
        ext = ".ogg"
    elif payload[:4] == b"RIFF":
        ext = ".wav"
    else:
        # Proprietary format (XMA, etc.) -- try vgmstream on the raw CKD first,
        # then on just the payload written to a temp file.
        vgm_path = _find_vgmstream()
        if not vgm_path:
            print(f"Warning: unknown CKD audio format and vgmstream not found for {os.path.basename(ckd_path)}")
            return None

        os.makedirs(output_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(ckd_path))[0]
        if base.lower().endswith(".wav") or base.lower().endswith(".ogg"):
            base = base[:-4]
        out_path = os.path.join(output_dir, base + ".wav")

        import subprocess
        import tempfile

        # Attempt 1: feed vgmstream the original CKD file directly
        try:
            res = subprocess.run(
                [vgm_path, "-o", out_path, ckd_path],
                capture_output=True, timeout=60)
            if res.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 100:
                return out_path
        except Exception:
            pass

        # Attempt 2: strip CKD header, write payload to temp file, decode
        try:
            with tempfile.NamedTemporaryFile(suffix=".xma", delete=False) as tmp:
                tmp.write(payload)
                tmp_path = tmp.name
            res = subprocess.run(
                [vgm_path, "-o", out_path, tmp_path],
                capture_output=True, timeout=60)
            os.unlink(tmp_path)
            if res.returncode == 0 and os.path.isfile(out_path) and os.path.getsize(out_path) > 100:
                return out_path
        except Exception as e:
            print(f"Warning: vgmstream fallback failed for {os.path.basename(ckd_path)}: {e}")

        return None

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(ckd_path))[0]
    # Strip embedded extension (e.g. "SongName.wav.ckd" -> "SongName")
    if base.lower().endswith(".wav"):
        base = base[:-4]
    elif base.lower().endswith(".ogg"):
        base = base[:-4]
    out_path = os.path.join(output_dir, base + ext)

    with open(out_path, "wb") as f:
        f.write(payload)
    return out_path


def _pick_audio(folder: str, codename: Optional[str] = None) -> Optional[str]:
    """Find the best audio file in *folder*, checking .ogg, .wav, and .wav.ckd.

    Prefers .ogg over .wav over .wav.ckd.  When a .wav.ckd is the only
    option it is automatically extracted in-place and the resulting raw path
    is returned.  Searches top-level first, then recursively for IPK-style
    nested directory structures.
    """
    # 1. Try exact codename match at top level (.ogg then .wav)
    if codename:
        for ext in (".ogg", ".wav"):
            candidate = os.path.join(folder, f"{codename}{ext}")
            if os.path.isfile(candidate):
                return candidate

    # 2. Glob for any .ogg at top level (excluding previews)
    oggs = [
        f for f in glob.glob(os.path.join(folder, "*.ogg"))
        if "AudioPreview" not in os.path.basename(f)
    ]
    if oggs:
        if codename:
            lower = codename.lower()
            matches = [p for p in oggs if os.path.basename(p).lower().startswith(lower)]
            if matches:
                return matches[0]
        return oggs[0]

    # 3. Glob for any .wav at top level (excluding previews)
    wavs = [
        f for f in glob.glob(os.path.join(folder, "*.wav"))
        if "AudioPreview" not in os.path.basename(f)
    ]
    if wavs:
        if codename:
            lower = codename.lower()
            matches = [p for p in wavs if os.path.basename(p).lower().startswith(lower)]
            if matches:
                return matches[0]
        return wavs[0]

    # 4. Recursive search (for extracted IPK structures with nested dirs)
    #    Try .ogg first, then .wav, then .wav.ckd
    for pattern, is_ckd in [("**/*.ogg", False), ("**/*.wav", False), ("**/*.wav.ckd", True)]:
        hits = glob.glob(os.path.join(folder, pattern), recursive=True)
        # Filter out preview / ambient / autodance files for non-CKD
        if not is_ckd:
            hits = [h for h in hits if "AudioPreview" not in os.path.basename(h)
                    and os.sep + "amb" + os.sep not in h.lower()
                    and "/amb/" not in h.lower()
                    and os.sep + "autodance" + os.sep not in h.lower()
                    and "/autodance/" not in h.lower()]
        else:
            # For CKD, skip ambient CKDs (amb_*.wav.ckd) and autodance
            hits = [h for h in hits if not os.path.basename(h).lower().startswith("amb_")
                    and os.sep + "autodance" + os.sep not in h.lower()
                    and "/autodance/" not in h.lower()]
        if not hits:
            continue
        if codename:
            lower = codename.lower()
            matches = [p for p in hits if os.path.basename(p).lower().startswith(lower)]
            if matches:
                hits = matches
        if is_ckd:
            extracted = _extract_ckd_audio(hits[0], folder)
            if extracted:
                return extracted
        else:
            return hits[0]

    return None


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
    # Only look for audio/video alongside the IPK file, NOT inside
    # ipk_extracted/.  That directory may contain stale data from a
    # previous installation of a different IPK.  Fresh audio/video
    # will be detected after step_04 re-extracts the IPK.
    if not audio_path:
        audio_path = _pick_audio(source_dir, spec.codename)
    if not video_path:
        video_path = _pick_webm(source_dir, spec.codename)

    spec.audio_path = audio_path
    spec.video_path = video_path
    spec.ipk_extracted = os.path.join(source_dir, "ipk_extracted")
    spec.ready_for_prepare = True

    spec.ready_for_install = os.path.isdir(spec.ipk_extracted)
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
        spec.audio_path = _pick_audio(folder, spec.codename)
        spec.video_path = _pick_webm(folder, spec.codename)

        if not os.path.isdir(os.path.join(folder, "world", "maps")):
            spec.errors.append("Unpacked IPK folder must contain world/maps/.")
        if not spec.audio_path:
            spec.errors.append("Audio (.ogg/.wav/.wav.ckd) not found in unpacked source folder.")
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
