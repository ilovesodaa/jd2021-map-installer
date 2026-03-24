"""Autodance and stape processor.

Ports V1 step_11 behavior for maps that ship real autodance data by
converting autodance CKDs and optional stape CKDs into game-ready Lua files.
"""

from __future__ import annotations

import re
from pathlib import Path

from jd2021_installer.installers.tape_converter import convert_tape_file


def _path_has_codename_component(path: Path, codename: str) -> bool:
    parts = [p.lower() for p in path.as_posix().split("/") if p]
    return codename.lower() in parts


def _filename_matches_codename(path: Path, codename: str) -> bool:
    cn = codename.lower()
    return bool(re.match(rf"^{re.escape(cn)}(?:[^a-z0-9]|$)", path.name.lower()))


def _scoped_candidates(source_dir: Path, pattern: str, codename: str) -> list[Path]:
    candidates = list(source_dir.rglob(pattern))
    scoped = [p for p in candidates if _path_has_codename_component(p, codename)]
    if not scoped:
        scoped = [p for p in candidates if _filename_matches_codename(p, codename)]
    return sorted(scoped, key=lambda p: p.as_posix().lower())


def process_autodance_directory(source_dir: Path, target_dir: Path, codename: str) -> int:
    """Convert real autodance assets from source into target/autodance.

    Returns count of converted/copied outputs.
    """
    out_dir = target_dir / "autodance"
    out_dir.mkdir(parents=True, exist_ok=True)

    converted = 0

    # Main autodance template
    tpl_candidates = _scoped_candidates(source_dir, "*autodance*.tpl.ckd", codename)
    if tpl_candidates:
        dst_tpl = out_dir / f"{codename}_autodance.tpl"
        if convert_tape_file(tpl_candidates[0], dst_tpl):
            converted += 1

    # Autodance data payloads
    for ext in ("adtape", "adrecording", "advideo"):
        cands = _scoped_candidates(source_dir, f"*.{ext}.ckd", codename)
        if not cands:
            continue
        dst = out_dir / f"{codename}.{ext}"
        if convert_tape_file(cands[0], dst):
            converted += 1

    # Optional loose media in autodance folders
    ad_dirs = _scoped_candidates(source_dir, "autodance", codename)
    for ad_dir in ad_dirs:
        if not ad_dir.is_dir():
            continue
        for item in ad_dir.iterdir():
            if item.suffix.lower() == ".ckd":
                continue
            dst = out_dir / item.name
            if not dst.exists():
                dst.write_bytes(item.read_bytes())
                converted += 1

    return converted


def process_stape_file(source_dir: Path, target_dir: Path, codename: str) -> bool:
    """Convert an optional .stape.ckd into target/audio/<codename>.stape."""
    stape_candidates = _scoped_candidates(source_dir, "*.stape.ckd", codename)
    if not stape_candidates:
        return False

    out = target_dir / "audio" / f"{codename}.stape"
    out.parent.mkdir(parents=True, exist_ok=True)
    return convert_tape_file(stape_candidates[0], out)
