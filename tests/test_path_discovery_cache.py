from pathlib import Path

from jd2021_installer.core import path_discovery


def test_deep_scan_for_game_dir_uses_cache(tmp_path: Path, monkeypatch):
    game_root = tmp_path / "jd21"
    sku_dir = game_root / "data" / "World" / "SkuScenes"
    sku_dir.mkdir(parents=True)
    (sku_dir / "SkuScene_Maps_PC_All.isc").write_text("ok", encoding="utf-8")

    real_walk = path_discovery.os.walk
    walk_calls = {"count": 0}

    def _counting_walk(root, *args, **kwargs):
        walk_calls["count"] += 1
        return real_walk(root, *args, **kwargs)

    path_discovery.clear_deep_scan_cache()
    monkeypatch.setattr(path_discovery.os, "walk", _counting_walk)

    first = path_discovery.deep_scan_for_game_dir(tmp_path)
    second = path_discovery.deep_scan_for_game_dir(tmp_path)

    assert first == game_root
    assert second == game_root
    assert walk_calls["count"] == 1


def test_clear_deep_scan_cache_for_root_forces_rescan(tmp_path: Path, monkeypatch):
    game_root = tmp_path / "jd21"
    sku_dir = game_root / "data" / "World" / "SkuScenes"
    sku_dir.mkdir(parents=True)
    (sku_dir / "SkuScene_Maps_PC_All.isc").write_text("ok", encoding="utf-8")

    real_walk = path_discovery.os.walk
    walk_calls = {"count": 0}

    def _counting_walk(root, *args, **kwargs):
        walk_calls["count"] += 1
        return real_walk(root, *args, **kwargs)

    path_discovery.clear_deep_scan_cache()
    monkeypatch.setattr(path_discovery.os, "walk", _counting_walk)

    assert path_discovery.deep_scan_for_game_dir(tmp_path) == game_root
    path_discovery.clear_deep_scan_cache(tmp_path)
    assert path_discovery.deep_scan_for_game_dir(tmp_path) == game_root

    assert walk_calls["count"] == 2
