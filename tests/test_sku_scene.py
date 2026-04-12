from pathlib import Path

from jd2021_installer.installers.sku_scene import list_registered_maps


def _write_sku_scene(game_root: Path, body: str) -> None:
    sku_path = game_root / "data" / "World" / "SkuScenes" / "SkuScene_Maps_PC_All.isc"
    sku_path.parent.mkdir(parents=True, exist_ok=True)
    sku_path.write_text(body, encoding="utf-8")


def test_list_registered_maps_reads_actor_songdesc_entries(tmp_path: Path) -> None:
    game_root = tmp_path / "jd21"
    _write_sku_scene(
        game_root,
        """
<Scene>
    <ACTORS NAME="Actor">
        <Actor USERFRIENDLY="GetGetDown" LUA="world/maps/GetGetDown/songdesc.tpl"></Actor>
    </ACTORS>
    <ACTORS NAME="Actor">
        <Actor USERFRIENDLY="MrBlueSky" LUA="world/maps/MrBlueSky/songdesc.tpl"></Actor>
    </ACTORS>
</Scene>
""".strip(),
    )

    assert list_registered_maps(game_root) == ["GetGetDown", "MrBlueSky"]


def test_list_registered_maps_deduplicates_case_insensitive(tmp_path: Path) -> None:
    game_root = tmp_path / "jd21"
    _write_sku_scene(
        game_root,
        """
<Scene>
    <ACTORS NAME="Actor">
        <Actor USERFRIENDLY="GetGetDown" LUA="world/maps/GetGetDown/songdesc.tpl"></Actor>
    </ACTORS>
    <ACTORS NAME="Actor">
        <Actor USERFRIENDLY="getgetdown" LUA="world/maps/getgetdown/songdesc.tpl"></Actor>
    </ACTORS>
</Scene>
""".strip(),
    )

    assert list_registered_maps(game_root) == ["GetGetDown"]


def test_list_registered_maps_ignores_mismatched_actor_and_path(tmp_path: Path) -> None:
    game_root = tmp_path / "jd21"
    _write_sku_scene(
        game_root,
        """
<Scene>
    <ACTORS NAME="Actor">
        <Actor USERFRIENDLY="MapA" LUA="world/maps/MapB/songdesc.tpl"></Actor>
    </ACTORS>
    <ACTORS NAME="Actor">
        <Actor USERFRIENDLY="MapC" LUA="world/maps/MapC/songdesc.tpl"></Actor>
    </ACTORS>
</Scene>
""".strip(),
    )

    assert list_registered_maps(game_root) == ["MapC"]
