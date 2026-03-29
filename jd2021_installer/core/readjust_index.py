"""Persistent readjust index for installed maps.

Stores enough per-map source metadata to reopen Sync Refinement without
manual source hunting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


INDEX_FILE = Path("map_readjust_index.json")


@dataclass
class ReadjustIndexEntry:
    codename: str
    source_mode: str
    source_root: str
    source_audio: str
    source_video: str
    installed_map_dir: str
    installed_trk: str
    last_audio_ms: float = 0.0
    last_video_ms: float = 0.0
    updated_at: str = ""

    @staticmethod
    def from_dict(raw: dict) -> Optional["ReadjustIndexEntry"]:
        try:
            codename = str(raw.get("codename", "")).strip()
            if not codename:
                return None
            return ReadjustIndexEntry(
                codename=codename,
                source_mode=str(raw.get("source_mode", "unknown")),
                source_root=str(raw.get("source_root", "")),
                source_audio=str(raw.get("source_audio", "")),
                source_video=str(raw.get("source_video", "")),
                installed_map_dir=str(raw.get("installed_map_dir", "")),
                installed_trk=str(raw.get("installed_trk", "")),
                last_audio_ms=float(raw.get("last_audio_ms", 0.0) or 0.0),
                last_video_ms=float(raw.get("last_video_ms", 0.0) or 0.0),
                updated_at=str(raw.get("updated_at", "")),
            )
        except Exception:
            return None


@dataclass
class ReadjustIndex:
    version: int
    entries: list[ReadjustIndexEntry]


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_index(index_file: Path = INDEX_FILE) -> ReadjustIndex:
    if not index_file.exists():
        return ReadjustIndex(version=1, entries=[])

    try:
        data = json.loads(index_file.read_text(encoding="utf-8"))
    except Exception:
        return ReadjustIndex(version=1, entries=[])

    raw_entries = data.get("entries", []) if isinstance(data, dict) else []
    entries: list[ReadjustIndexEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        parsed = ReadjustIndexEntry.from_dict(raw)
        if parsed:
            entries.append(parsed)

    return ReadjustIndex(version=1, entries=entries)


def save_index(index: ReadjustIndex, index_file: Path = INDEX_FILE) -> None:
    payload = {
        "version": 1,
        "entries": [asdict(e) for e in sorted(index.entries, key=lambda x: x.codename.lower())],
    }
    index_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def upsert_entry(entry: ReadjustIndexEntry, index_file: Path = INDEX_FILE) -> None:
    index = load_index(index_file)
    entry.updated_at = _iso_now()

    replaced = False
    for idx, existing in enumerate(index.entries):
        if existing.codename.lower() == entry.codename.lower():
            index.entries[idx] = entry
            replaced = True
            break

    if not replaced:
        index.entries.append(entry)

    save_index(index, index_file)


def update_offsets(
    codename: str,
    *,
    audio_ms: float,
    video_ms: float,
    index_file: Path = INDEX_FILE,
) -> None:
    index = load_index(index_file)
    changed = False
    for entry in index.entries:
        if entry.codename.lower() == codename.lower():
            entry.last_audio_ms = float(audio_ms)
            entry.last_video_ms = float(video_ms)
            entry.updated_at = _iso_now()
            changed = True
            break

    if changed:
        save_index(index, index_file)


def prune_stale_entries(index_file: Path = INDEX_FILE) -> tuple[list[ReadjustIndexEntry], list[ReadjustIndexEntry]]:
    index = load_index(index_file)
    kept: list[ReadjustIndexEntry] = []
    pruned: list[ReadjustIndexEntry] = []

    for entry in index.entries:
        source_root_ok = Path(entry.source_root).is_dir()
        audio_ok = Path(entry.source_audio).is_file()
        video_ok = Path(entry.source_video).is_file()
        installed_ok = Path(entry.installed_map_dir).is_dir()
        if source_root_ok and audio_ok and video_ok and installed_ok:
            kept.append(entry)
        else:
            pruned.append(entry)

    if len(pruned) > 0:
        save_index(ReadjustIndex(version=1, entries=kept), index_file)

    return kept, pruned


def read_video_start_time_from_trk(trk_path: Path) -> Optional[float]:
    if not trk_path.exists():
        return None
    try:
        import re

        content = trk_path.read_text(encoding="utf-8")
        match = re.search(r"videoStartTime\s*=\s*([-+]?\d*\.?\d+)", content)
        if not match:
            return None
        vst = float(match.group(1))
        if abs(vst) > 1000:
            vst /= 48000.0
        return vst
    except Exception:
        return None
