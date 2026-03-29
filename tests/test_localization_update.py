import json
from pathlib import Path

from jd2021_installer.core.localization_update import (
    resolve_console_save_path,
    update_console_localization,
)


def test_update_console_localization_merges_and_creates_backup(tmp_path: Path):
    source_path = tmp_path / "localisation.hash.json"
    source_data = {
        "15158": {
            "en": "Tango Version",
            "fr": "Version Tango",
            "ja": "タンゴver.",
            "pt-br": "Versão tango",
        },
        "20003319": {
            "en": "Just Dance 2022",
            "fr": "Just Dance 2022",
            "pt-br": "Just Dance 2022",
        },
    }
    source_path.write_text(json.dumps(source_data, ensure_ascii=False), encoding="utf-8")

    console_save_path = tmp_path / "ConsoleSave.json"
    existing = {
        "15158": {
            "masterText": "old",
            "isUsedInMCA": True,
            "translations": [""] * 17,
        }
    }
    console_save_path.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")

    result = update_console_localization(source_path, console_save_path)

    assert result.updated_existing == 1
    assert result.added_new == 1
    assert result.backup_path.is_file()

    updated = json.loads(console_save_path.read_text(encoding="utf-8"))
    assert updated["15158"]["masterText"] == "Tango Version"
    assert updated["15158"]["translations"][2] == "Tango Version"
    assert updated["15158"]["translations"][3] == "Tango Version"
    assert updated["15158"]["translations"][6] == "Version Tango"
    assert updated["15158"]["translations"][12] == "Versão tango"

    assert updated["20003319"]["masterText"] == "Just Dance 2022"
    assert updated["20003319"]["isUsedInMCA"] is False
    assert len(updated["20003319"]["translations"]) == 17


def test_resolve_console_save_path_prefers_existing_localisation_path(tmp_path: Path):
    game_dir = tmp_path / "jd21"
    target = game_dir / "data" / "EngineData" / "Localisation" / "Saves"
    target.mkdir(parents=True)
    save = target / "ConsoleSave.json"
    save.write_text("{}", encoding="utf-8")

    resolved = resolve_console_save_path(game_dir)

    assert resolved == save
