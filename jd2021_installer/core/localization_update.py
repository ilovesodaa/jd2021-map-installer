"""Localization merge utilities for updating in-game ConsoleSave entries."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LANGUAGE_CODES_BY_INDEX: tuple[str, ...] = (
    "da",      # 0 Danish
    "de",      # 1 German
    "en",      # 2 English (US)
    "en",      # 3 English (UK)
    "es",      # 4 Spanish
    "fi",      # 5 Finnish
    "fr",      # 6 French
    "it",      # 7 Italian
    "ja",      # 8 Japanese
    "ko",      # 9 Korean
    "nl",      # 10 Dutch
    "nb",      # 11 Norwegian
    "pt-br",   # 12 Portuguese (Brazil)
    "ru",      # 13 Russian
    "sv",      # 14 Swedish
    "zh-cn",   # 15 Simplified Chinese
    "zh-tw",   # 16 Traditional Chinese
)


@dataclass(frozen=True)
class LocalizationUpdateResult:
    """Summary of a localization update operation."""

    updated_existing: int
    added_new: int
    backup_path: Path
    console_save_path: Path


def resolve_console_save_path(game_directory: Path) -> Path:
    """Resolve ConsoleSave.json path from a configured JD2021 directory."""
    base = Path(game_directory)
    candidates = (
        base / "data" / "EngineData" / "Localisation" / "Saves" / "ConsoleSave.json",
        base / "EngineData" / "Localisation" / "Saves" / "ConsoleSave.json",
        base / "data" / "EngineData" / "Localization" / "Saves" / "ConsoleSave.json",
        base / "EngineData" / "Localization" / "Saves" / "ConsoleSave.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "ConsoleSave.json not found. Checked:\n- " + "\n- ".join(str(p) for p in candidates)
    )


def _as_string(value: Any) -> str:
    return "" if value is None else str(value)


def _build_translations_array(loc_entry: dict[str, Any]) -> list[str]:
    translations = [""] * len(LANGUAGE_CODES_BY_INDEX)
    for idx, code in enumerate(LANGUAGE_CODES_BY_INDEX):
        translations[idx] = _as_string(loc_entry.get(code, ""))
    return translations


def _sanitize_translation_record(record: dict[str, Any]) -> None:
    record["masterText"] = _as_string(record.get("masterText", ""))
    if "isUsedInMCA" not in record:
        record["isUsedInMCA"] = False

    raw_translations = record.get("translations")
    safe_translations = [""] * len(LANGUAGE_CODES_BY_INDEX)
    if isinstance(raw_translations, list):
        for idx in range(min(len(raw_translations), len(safe_translations))):
            safe_translations[idx] = _as_string(raw_translations[idx])
    record["translations"] = safe_translations


def update_console_localization(
    localisation_json_path: Path,
    console_save_path: Path,
) -> LocalizationUpdateResult:
    """Merge localisation data into ConsoleSave.json and persist backup + output."""
    source_path = Path(localisation_json_path)
    target_path = Path(console_save_path)

    if not source_path.is_file():
        raise FileNotFoundError(f"Localization file not found: {source_path}")
    if not target_path.is_file():
        raise FileNotFoundError(f"ConsoleSave file not found: {target_path}")

    with source_path.open("r", encoding="utf-8") as f:
        source_data = json.load(f)
    if not isinstance(source_data, dict):
        raise ValueError("Localization JSON must be a top-level object keyed by LocID.")

    with target_path.open("r", encoding="utf-8") as f:
        target_data = json.load(f)
    if not isinstance(target_data, dict):
        raise ValueError("ConsoleSave.json must be a top-level object keyed by LocID.")

    updated_existing = 0
    added_new = 0

    for loc_id, loc_entry in source_data.items():
        if not isinstance(loc_entry, dict):
            continue

        master_text = _as_string(loc_entry.get("en", ""))
        translations = _build_translations_array(loc_entry)

        existing = target_data.get(loc_id)
        if isinstance(existing, dict):
            existing["masterText"] = master_text
            existing["translations"] = translations
            if "isUsedInMCA" not in existing:
                existing["isUsedInMCA"] = False
            updated_existing += 1
        else:
            target_data[loc_id] = {
                "masterText": master_text,
                "isUsedInMCA": False,
                "translations": translations,
            }
            added_new += 1

    for value in target_data.values():
        if isinstance(value, dict):
            _sanitize_translation_record(value)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = target_path.with_name(f"{target_path.stem}.backup_{timestamp}{target_path.suffix}")
    shutil.copy2(target_path, backup_path)

    with target_path.open("w", encoding="utf-8") as f:
        json.dump(target_data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return LocalizationUpdateResult(
        updated_existing=updated_existing,
        added_new=added_new,
        backup_path=backup_path,
        console_save_path=target_path,
    )
