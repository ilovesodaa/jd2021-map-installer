"""Standalone JDNext bundle extraction strategy and mapping helpers.

This module keeps JDNext extraction decoupled from the main installer flow while
we learn real-world mapPackage behaviors.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from jd2021_installer.core.config import AppConfig
from jd2021_installer.extractors.jdnext_unitypy import (
    JDNextUnpackSummary,
    unpack_jdnext_bundle_with_unitypy,
)


Strategy = Literal["assetstudio_first", "unitypy_first"]


@dataclass
class JDNextMappedSummary:
    mapped_root: str
    map_json: str | None = None
    musictrack_json: str | None = None
    dance_tape_ckd: str | None = None
    karaoke_tape_ckd: str | None = None
    gestures: int = 0
    msm: int = 0
    pictos: int = 0
    menuart: int = 0
    extra_text_assets: int = 0


@dataclass
class JDNextStrategySummary:
    bundle_path: str
    output_dir: str
    strategy: str
    winner: str
    assetstudio_output_dir: str | None = None
    unitypy_output_dir: str | None = None
    unitypy_summary: dict | None = None
    mapped_summary: dict | None = None


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")


def _run_assetstudio_export(
    bundle_path: Path,
    output_dir: Path,
    unity_version: str,
    config: AppConfig | None = None,
) -> Path:
    repo_root = Path(__file__).resolve().parents[2]

    candidates: list[Path] = []
    configured_cli = str(getattr(config, "assetstudio_cli_path", "") or "").strip()
    if configured_cli:
        candidates.append(Path(configured_cli).expanduser())

    configured_root = getattr(config, "third_party_tools_root", None)
    third_party_roots: list[Path] = []
    if configured_root:
        third_party_roots.append(Path(configured_root).expanduser())
    third_party_roots.append(repo_root / "tools")

    seen: set[str] = set()
    for root in third_party_roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.extend(
            [
                root / "Unity2UbiArt" / "bin" / "AssetStudioModCLI" / "AssetStudioModCLI.exe",
                root / "AssetStudioModCLI" / "AssetStudioModCLI.exe",
                root / "AssetStudio" / "AssetStudioModCLI.exe",
            ]
        )

    cli_path = next((p for p in candidates if p.exists()), None)
    if cli_path is None:
        raise FileNotFoundError("AssetStudioModCLI.exe not found under tools")

    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(cli_path),
        str(bundle_path),
        "-m",
        "export",
        "-o",
        str(output_dir),
        "-g",
        "type",
        "--unity-version",
        unity_version,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "AssetStudio export failed with code "
            f"{completed.returncode}: {completed.stderr or completed.stdout}"
        )
    return output_dir


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _extract_val_list(items: list) -> list[int]:
    values: list[int] = []
    for item in items or []:
        if isinstance(item, dict):
            if "VAL" in item:
                try:
                    values.append(int(item["VAL"]))
                except (TypeError, ValueError):
                    continue
            elif "val" in item:
                try:
                    values.append(int(item["val"]))
                except (TypeError, ValueError):
                    continue
    return values


def _extract_signature_list(items: list) -> list[dict]:
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        sig = item.get("MusicSignature", item)
        if not isinstance(sig, dict):
            continue
        try:
            beats = int(sig.get("beats", 4))
            marker = int(float(sig.get("marker", 0)))
        except (TypeError, ValueError):
            continue
        out.append({"beats": beats, "marker": marker})
    return out


def _extract_section_list(items: list) -> list[dict]:
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        sec = item.get("MusicSection", item)
        if not isinstance(sec, dict):
            continue
        try:
            section_type = int(sec.get("sectionType", 0))
            marker = int(float(sec.get("marker", 0)))
        except (TypeError, ValueError):
            continue
        out.append({"sectionType": section_type, "marker": marker})
    return out


def _synthesize_musictrack_tpl_ckd(musictrack_json_path: Path, out_ckd_path: Path) -> bool:
    if not musictrack_json_path.is_file():
        return False
    try:
        raw = json.loads(musictrack_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False

    struct = raw.get("m_structure", {}).get("MusicTrackStructure", {})
    if not isinstance(struct, dict):
        return False

    markers = _extract_val_list(struct.get("markers", []))
    signatures = _extract_signature_list(struct.get("signatures", []))
    sections = _extract_section_list(struct.get("sections", []))

    ckd = {
        "COMPONENTS": [
            {
                "trackData": {
                    "structure": {
                        "markers": markers,
                        "signatures": signatures,
                        "sections": sections,
                        "startBeat": int(struct.get("startBeat", 0) or 0),
                        "endBeat": int(struct.get("endBeat", 0) or 0),
                        "videoStartTime": float(struct.get("videoStartTime", 0.0) or 0.0),
                        "previewEntry": float(struct.get("previewEntry", 0.0) or 0.0),
                        "previewLoopStart": float(struct.get("previewLoopStart", 0.0) or 0.0),
                        "previewLoopEnd": float(struct.get("previewLoopEnd", 0.0) or 0.0),
                        "volume": float(struct.get("volume", 0.0) or 0.0),
                        "fadeInDuration": float(struct.get("fadeInDuration", 0.0) or 0.0),
                        "fadeInType": int(struct.get("fadeInType", 0) or 0),
                        "fadeOutDuration": float(struct.get("fadeOutDuration", 0.0) or 0.0),
                        "fadeOutType": int(struct.get("fadeOutType", 0) or 0),
                    }
                }
            }
        ]
    }
    _write_json(out_ckd_path, ckd)
    return True


def _normalize_color(raw: object) -> list[float]:
    if isinstance(raw, str) and raw.startswith("0x") and len(raw) >= 10:
        try:
            r = int(raw[2:4], 16) / 255.0
            g = int(raw[4:6], 16) / 255.0
            b = int(raw[6:8], 16) / 255.0
            a = int(raw[8:10], 16) / 255.0
            return [a, r, g, b]
        except ValueError:
            pass
    return [1.0, 0.968, 0.164, 0.552]


def _normalize_move_name(raw: object) -> str:
    """Return a bare move stem from variable JDNext MoveName formats."""
    name = str(raw or "").strip()
    if not name:
        return ""

    # Some maps provide full classifier-like paths and/or include the extension.
    name = name.replace("\\", "/")
    if "/" in name:
        name = name.rsplit("/", 1)[-1]

    lowered = name.lower()
    for suffix in (".gesture", ".msm"):
        if lowered.endswith(suffix):
            name = name[: -len(suffix)]
            break

    return name.strip()


def _synthesize_tapes_from_map_json(map_json_path: Path, mapped_root: Path, codename: str) -> tuple[Path | None, Path | None, set[str]]:
    if not map_json_path.exists():
        return None, None, set()
    try:
        data = json.loads(map_json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None, set()

    codename_low = codename.lower()
    dance_data = data.get("DanceData", {}) if isinstance(data, dict) else {}
    karaoke_data = data.get("KaraokeData", {}) if isinstance(data, dict) else {}

    picto_names: set[str] = set()

    dance_clips: list[dict] = []
    for mc in dance_data.get("MotionClips", []) if isinstance(dance_data, dict) else []:
        if not isinstance(mc, dict):
            continue
        move_name = _normalize_move_name(mc.get("MoveName", ""))
        move_type = int(mc.get("MoveType", 0) or 0)
        ext = "gesture" if move_type == 1 else "msm"
        dance_clips.append(
            {
                "__class": "MotionClip",
                "StartTime": int(mc.get("StartTime", 0) or 0),
                "Duration": int(mc.get("Duration", 0) or 0),
                "Id": int(mc.get("Id", 0) or 0),
                "TrackId": int(mc.get("TrackId", 0) or 0),
                "IsActive": int(mc.get("IsActive", 1) or 1),
                "ClassifierPath": f"world/maps/{codename_low}/timeline/moves/{move_name}.{ext}" if move_name else "",
                "GoldMove": int(mc.get("GoldMove", 0) or 0),
                "CoachId": int(mc.get("CoachId", 0) or 0),
                "MoveType": move_type,
                "Color": _normalize_color(mc.get("Color", "")),
            }
        )

    for pc in dance_data.get("PictoClips", []) if isinstance(dance_data, dict) else []:
        if not isinstance(pc, dict):
            continue
        picto_name = str(pc.get("PictoPath", "")).strip()
        if picto_name:
            picto_names.add(picto_name.lower())
        dance_clips.append(
            {
                "__class": "PictogramClip",
                "StartTime": int(pc.get("StartTime", 0) or 0),
                "Duration": int(pc.get("Duration", 0) or 0),
                "Id": int(pc.get("Id", 0) or 0),
                "TrackId": int(pc.get("TrackId", 0) or 0),
                "IsActive": int(pc.get("IsActive", 1) or 1),
                "PictoPath": f"world/maps/{codename_low}/timeline/pictos/{picto_name}.png" if picto_name else "",
                "CoachCount": int(pc.get("CoachCount", 1) or 1),
            }
        )

    for gc in dance_data.get("GoldEffectClips", []) if isinstance(dance_data, dict) else []:
        if not isinstance(gc, dict):
            continue
        dance_clips.append(
            {
                "__class": "GoldEffectClip",
                "StartTime": int(gc.get("StartTime", 0) or 0),
                "Duration": int(gc.get("Duration", 0) or 0),
                "Id": int(gc.get("Id", 0) or 0),
                "TrackId": int(gc.get("TrackId", 0) or 0),
                "IsActive": int(gc.get("IsActive", 1) or 1),
                "EffectType": int(gc.get("EffectType", 1) or 1),
            }
        )

    karaoke_clips: list[dict] = []
    for kc in karaoke_data.get("Clips", []) if isinstance(karaoke_data, dict) else []:
        src = kc.get("KaraokeClip", kc) if isinstance(kc, dict) else {}
        if not isinstance(src, dict):
            continue
        karaoke_clips.append(
            {
                "__class": "KaraokeClip",
                "StartTime": int(src.get("StartTime", 0) or 0),
                "Duration": int(src.get("Duration", 0) or 0),
                "Id": int(src.get("Id", 0) or 0),
                "TrackId": int(src.get("TrackId", 0) or 0),
                "IsActive": int(src.get("IsActive", 1) or 1),
                "Lyrics": str(src.get("Lyrics", "")),
                "Pitch": float(src.get("Pitch", 0.0) or 0.0),
                "IsEndOfLine": int(src.get("IsEndOfLine", 0) or 0),
                "ContentType": int(src.get("ContentType", 0) or 0),
                "SemitoneTolerance": float(src.get("SemitoneTolerance", 5.0) or 5.0),
                "StartTimeTolerance": int(src.get("StartTimeTolerance", 4) or 4),
                "EndTimeTolerance": int(src.get("EndTimeTolerance", 4) or 4),
            }
        )

    dance_out = mapped_root / f"{codename_low}_tml_dance.dtape.ckd"
    karaoke_out = mapped_root / f"{codename_low}_tml_karaoke.ktape.ckd"

    _write_json(
        dance_out,
        {
            "__class": "Tape",
            "Clips": dance_clips,
            "TapeClock": int(dance_data.get("TapeClock", 0) if isinstance(dance_data, dict) else 0),
            "TapeBarCount": int(dance_data.get("TapeBarCount", 1) if isinstance(dance_data, dict) else 1),
            "FreeResourcesAfterPlay": int(dance_data.get("FreeResourcesAfterPlay", 0) if isinstance(dance_data, dict) else 0),
            "MapName": str(data.get("MapName", codename) if isinstance(data, dict) else codename),
            "SoundwichEvent": str(dance_data.get("SoundwichEvent", "") if isinstance(dance_data, dict) else ""),
        },
    )
    _write_json(
        karaoke_out,
        {
            "__class": "Tape",
            "Clips": karaoke_clips,
            "TapeClock": int(karaoke_data.get("TapeClock", 0) if isinstance(karaoke_data, dict) else 0),
            "TapeBarCount": int(karaoke_data.get("TapeBarCount", 1) if isinstance(karaoke_data, dict) else 1),
            "FreeResourcesAfterPlay": int(karaoke_data.get("FreeResourcesAfterPlay", 0) if isinstance(karaoke_data, dict) else 0),
            "MapName": str(data.get("MapName", codename) if isinstance(data, dict) else codename),
            "SoundwichEvent": str(karaoke_data.get("SoundwichEvent", "") if isinstance(karaoke_data, dict) else ""),
        },
    )

    return dance_out, karaoke_out, picto_names


def map_assetstudio_output(assetstudio_out: Path, mapped_root: Path, codename: str | None = None) -> JDNextMappedSummary:
    mapped_root.mkdir(parents=True, exist_ok=True)

    textasset_dir = assetstudio_out / "TextAsset"
    mono_dir = assetstudio_out / "MonoBehaviour"
    texture_dir = assetstudio_out / "Texture2D"
    sprite_dir = assetstudio_out / "Sprite"

    summary = JDNextMappedSummary(mapped_root=str(mapped_root))
    effective_codename = codename or "jdnext"
    effective_codename_low = effective_codename.lower()

    map_json_dst = mapped_root / "monobehaviour" / "map.json"
    if effective_codename and _copy_if_exists(mono_dir / f"{effective_codename}.json", map_json_dst):
        summary.map_json = str(map_json_dst)
    else:
        map_candidates = [p for p in mono_dir.glob("*.json") if p.name.lower() != "musictrack.json"]
        if map_candidates and _copy_if_exists(map_candidates[0], map_json_dst):
            summary.map_json = str(map_json_dst)

    musictrack_dst = mapped_root / "monobehaviour" / "musictrack.json"
    if _copy_if_exists(mono_dir / "MusicTrack.json", musictrack_dst):
        summary.musictrack_json = str(musictrack_dst)
        musictrack_ckd_name = f"{effective_codename_low}_musictrack.tpl.ckd"
        _synthesize_musictrack_tpl_ckd(
            musictrack_dst,
            mapped_root / musictrack_ckd_name,
        )

    picto_names: set[str] = set()
    if summary.map_json:
        dance_ckd, karaoke_ckd, picto_names = _synthesize_tapes_from_map_json(
            Path(summary.map_json),
            mapped_root,
            effective_codename,
        )
        if dance_ckd:
            summary.dance_tape_ckd = str(dance_ckd)
        if karaoke_ckd:
            summary.karaoke_tape_ckd = str(karaoke_ckd)

    moves_platform_dir = mapped_root / "timeline" / "moves" / "x360"
    for src in sorted(textasset_dir.glob("*.gesture")):
        dst = moves_platform_dir / src.name.lower()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        summary.gestures += 1

    for src in sorted(textasset_dir.glob("*.msm")):
        dst = moves_platform_dir / src.name.lower()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        summary.msm += 1

    for src in sorted(textasset_dir.glob("*.txt")):
        dst = mapped_root / "textasset" / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        summary.extra_text_assets += 1

    texture_files = sorted(texture_dir.glob("*.png")) + sorted(sprite_dir.glob("*.png"))
    for src in texture_files:
        low_name = src.stem.lower()
        if low_name in picto_names or "picto" in low_name:
            dst = mapped_root / "pictos" / f"{low_name}.png"
            summary.pictos += 1
        else:
            dst = mapped_root / "menuart" / src.name
            summary.menuart += 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    _write_json(mapped_root / "mapping_summary.json", asdict(summary))
    return summary


def _run_unitypy(
    bundle_path: Path,
    unitypy_out: Path,
    config: AppConfig | None = None,
) -> JDNextUnpackSummary:
    unitypy_out.mkdir(parents=True, exist_ok=True)
    return unpack_jdnext_bundle_with_unitypy(bundle_path, unitypy_out, config=config)


def run_jdnext_bundle_strategy(
    bundle_path: str | Path,
    output_dir: str | Path,
    *,
    strategy: Strategy = "assetstudio_first",
    codename: str | None = None,
    unity_version: str = "2021.3.9f1",
    config: AppConfig | None = None,
) -> JDNextStrategySummary:
    bundle = Path(bundle_path)
    out_root = Path(output_dir)
    if not bundle.is_file():
        raise FileNotFoundError(f"Bundle file not found: {bundle}")

    out_root.mkdir(parents=True, exist_ok=True)
    assetstudio_out = out_root / "assetstudio_raw"
    unitypy_out = out_root / "unitypy_raw"
    mapped_out = out_root / "mapped"

    unitypy_summary: JDNextUnpackSummary | None = None
    assetstudio_success = False
    unitypy_success = False
    assetstudio_error: Exception | None = None
    unitypy_error: Exception | None = None

    if strategy == "assetstudio_first":
        try:
            _run_assetstudio_export(bundle, assetstudio_out, unity_version, config=config)
            assetstudio_success = True
        except Exception as exc:
            assetstudio_error = exc
        if not assetstudio_success:
            try:
                unitypy_summary = _run_unitypy(bundle, unitypy_out, config=config)
                unitypy_success = True
            except Exception as exc:
                unitypy_error = exc
    elif strategy == "unitypy_first":
        try:
            unitypy_summary = _run_unitypy(bundle, unitypy_out, config=config)
            unitypy_success = True
        except Exception as exc:
            unitypy_error = exc
        if not unitypy_success:
            try:
                _run_assetstudio_export(bundle, assetstudio_out, unity_version, config=config)
                assetstudio_success = True
            except Exception as exc:
                assetstudio_error = exc
    else:
        raise ValueError(f"Unsupported strategy: {strategy}")

    if assetstudio_success:
        mapped_summary = map_assetstudio_output(assetstudio_out, mapped_out, codename=codename)
        winner = "assetstudio"
    elif unitypy_success:
        mapped_summary = None
        winner = "unitypy"
    else:
        raise RuntimeError(
            "Both AssetStudio and UnityPy extraction paths failed. "
            f"AssetStudio error: {assetstudio_error!s}; "
            f"UnityPy error: {unitypy_error!s}"
        )

    summary = JDNextStrategySummary(
        bundle_path=str(bundle),
        output_dir=str(out_root),
        strategy=strategy,
        winner=winner,
        assetstudio_output_dir=str(assetstudio_out) if assetstudio_success else None,
        unitypy_output_dir=str(unitypy_out) if unitypy_success else None,
        unitypy_summary=asdict(unitypy_summary) if unitypy_summary is not None else None,
        mapped_summary=asdict(mapped_summary) if mapped_summary is not None else None,
    )
    _write_json(out_root / "strategy_summary.json", asdict(summary))
    return summary
