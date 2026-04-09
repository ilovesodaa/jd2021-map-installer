import json
from pathlib import Path

from jd2021_installer.core.songdb_update import (
    find_songdb_entry,
    load_songdb_synth,
    synthesize_jdnext_songdb,
)


def test_synthesize_jdnext_songdb_builds_lookup_index(tmp_path: Path):
    source_path = tmp_path / "songdbnext_sample.json"
    source_payload = {
        "uuid-1": {
            "mapName": "SweetButPsycho",
            "parentMapName": "SweetButPsycho",
            "title": "Sweet but Psycho",
            "artist": "Ava Max",
            "credits": "Sample Credits",
            "coachCount": 1,
            "difficulty": 2,
            "sweatDifficulty": 2,
            "originalJDVersion": 2023,
            "tags": ["Main", "Pop"],
            "assetsMetadata": {
                "audioPreviewTrk": json.dumps(
                    {
                        "PreviewEntry": 79.0,
                        "PreviewLoopStart": 79.0,
                        "PreviewLoopEnd": 267.0,
                        "VideoStartTime": -15.0,
                    }
                )
            },
        }
    }
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    result = synthesize_jdnext_songdb(source_path, output_dir=tmp_path)

    assert result.source_entries == 1
    assert result.usable_entries == 1
    assert result.index_keys >= 1
    assert result.output_path.exists()

    loaded = load_songdb_synth(result.output_path)
    assert loaded is not None

    entry = find_songdb_entry("SweetButPsycho", synth_path=result.output_path)
    assert entry is not None
    assert entry.get("map_name") == "SweetButPsycho"
    assert entry.get("preview_loop_end") == 267.0


def test_synthesize_jdnext_songdb_rejects_non_jdnext_payload(tmp_path: Path):
    source_path = tmp_path / "not_songdbnext.json"
    source_path.write_text(json.dumps({"foo": {"title": "x"}}), encoding="utf-8")

    try:
        synthesize_jdnext_songdb(source_path, output_dir=tmp_path)
    except ValueError as exc:
        assert "does not look like a JDNext song database" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid JDNext song database payload")


def test_synthesize_jdnext_songdb_derives_loop_end_from_preview_duration(tmp_path: Path):
    source_path = tmp_path / "songdbnext_duration.json"
    source_payload = {
        "uuid-2": {
            "mapName": "DurationMap",
            "parentMapName": "DurationMap",
            "title": "Duration Map",
            "assetsMetadata": {
                "audioPreviewTrk": json.dumps(
                    {
                        "PreviewEntry": 79.0,
                        "PreviewLoopStart": 79.0,
                        "PreviewLoopEnd": 0.0,
                        "PreviewDuration": 30.0,
                        "Markers": [i * 24000 for i in range(0, 300)],
                    }
                )
            },
        }
    }
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    result = synthesize_jdnext_songdb(source_path, output_dir=tmp_path)
    entry = find_songdb_entry("DurationMap", synth_path=result.output_path)

    assert entry is not None
    # 30 seconds at 48k ticks/s with 24k-per-beat markers = 60 beats forward.
    assert entry.get("preview_loop_end") == 139.0


def test_synthesize_jdnext_songdb_title_collision_prefers_matching_map_name(tmp_path: Path):
    source_path = tmp_path / "songdbnext_title_collision.json"
    source_payload = {
        "uuid-base": {
            "mapName": "Telephone",
            "parentMapName": "Telephone",
            "title": "Telephone",
            "artist": "Lady Gaga",
        },
        "uuid-alt": {
            "mapName": "TelephoneALT",
            "parentMapName": "TelephoneALT",
            "title": "Telephone",
            "artist": "Lady Gaga",
            "tags": ["ALT", "Variant"],
        },
    }
    source_path.write_text(json.dumps(source_payload), encoding="utf-8")

    result = synthesize_jdnext_songdb(source_path, output_dir=tmp_path)
    loaded = load_songdb_synth(result.output_path)
    assert loaded is not None

    title_lookup = find_songdb_entry("Telephone", synth_path=result.output_path)
    alt_lookup = find_songdb_entry("TelephoneALT", synth_path=result.output_path)

    assert title_lookup is not None
    assert alt_lookup is not None
    assert title_lookup.get("map_name") == "Telephone"
    assert alt_lookup.get("map_name") == "TelephoneALT"
