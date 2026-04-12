from pathlib import Path

from jd2021_installer.installers.sku_scene import list_registered_maps


def _write_sku_scene(game_root: Path, content: str) -> None:
    sku_dir = game_root / "data" / "World" / "SkuScenes"
    sku_dir.mkdir(parents=True)
    (sku_dir / "SkuScene_Maps_PC_All.isc").write_text(content, encoding="utf-8")


def test_list_registered_maps_returns_userfriendly_entries_in_order(tmp_path: Path) -> None:
    game_root = tmp_path / "jd21"
    _write_sku_scene(
        game_root,
        """
<ACTORS NAME=\"Actor\"><Actor USERFRIENDLY=\"CryBaby\"></Actor></ACTORS>
<ACTORS NAME=\"Actor\"><Actor USERFRIENDLY=\"GetGetDown\"></Actor></ACTORS>
        """,
    )

    assert list_registered_maps(game_root) == ["CryBaby", "GetGetDown"]


def test_list_registered_maps_deduplicates_case_insensitive_entries(tmp_path: Path) -> None:
    game_root = tmp_path / "jd21"
    _write_sku_scene(
        game_root,
        """
<ACTORS NAME=\"Actor\"><Actor USERFRIENDLY=\"CryBaby\"></Actor></ACTORS>
<ACTORS NAME=\"Actor\"><Actor USERFRIENDLY=\"crybaby\"></Actor></ACTORS>
<ACTORS NAME=\"Actor\"><Actor USERFRIENDLY=\"KOI\"></Actor></ACTORS>
        """,
    )

    assert list_registered_maps(game_root) == ["CryBaby", "KOI"]


def test_list_registered_maps_returns_empty_when_file_missing(tmp_path: Path) -> None:
    game_root = tmp_path / "jd21"

    assert list_registered_maps(game_root) == []
