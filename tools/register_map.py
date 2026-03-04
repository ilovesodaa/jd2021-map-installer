"""
Register maps into JD2021 SkuScene XML (.isc) files.

Creates or updates SkuScene ISC files for all platform SKU variants,
adding Actor nodes and CoverflowSkuSongs entries for each map.

Usage:
    python tools/register_map.py --maps Starships Temperature --output path/to/output
    python tools/register_map.py --json input.json --output path/to/output
"""

import argparse
import json
import os
import xml.etree.ElementTree as ET


ENCODING = "ISO-8859-1"

# SKU identifiers → output filenames
SKU_FILENAMES = {
    "jd2018-all-platforms-light":   "SkuScene_Maps_All_Platforms_Light.isc",
    "jd2019-event":                 "Skuscene_Maps_Event.isc",
    "jd2021-ggp-all":               "SkuScene_Maps_GGP_All.isc",
    "jd2021-nx-all":                "SkuScene_Maps_NX_All.isc",
    "jd2018-nx-evt":                "SkuScene_Maps_NX_event.isc",
    "jd2021-pc-all":                "SkuScene_Maps_PC_All.isc",
    "jd2019-ps4-e3":                "SkuScene_Maps_PS4_E3.isc",
    "jd2021-ps4-scea":              "SkuScene_Maps_PS4_SCEA.isc",
    "jd2021-ps4-scee":              "SkuScene_Maps_PS4_SCEE.isc",
    "jd2021-ps5-scea":              "SkuScene_Maps_PS5_SCEA.isc",
    "jd2021-ps5-scee":              "SkuScene_Maps_PS5_SCEE.isc",
    "jd2020-pc-all":                "Skuscene_MAPS_SHA_4MAPS.isc",
    "jd2021-xboxsx-all":            "Skuscene_MAPS_XboxSX_ALL.isc",
    "jd2021-xone-all":              "SkuScene_Maps_XOne_All.isc",
    "jd2019-xone-e3":               "Skuscene_MAPS_XOne_E3.isc",
    "Very_Light":                   "SkuScene_Very_Light.isc",
}

# Default SKU for the primary template file
DEFAULT_SKU = "jd2021-pc-all"

TEMPLATE_XML = f"""\
<?xml version="1.0" encoding="{ENCODING}"?>
<root>
    <Scene>
        <ACTORS NAME="Actor">
            <Actor RELATIVEZ="0.000000" SCALE="1.000000 1.000000" xFLIPPED="0" \
USERFRIENDLY="skuscene_db" POS2D="0 0" ANGLE="0.000000" INSTANCEDATAFILE="" \
LUA="World/SkuScenes/skuscene_base.tpl">
                <COMPONENTS NAME="JD_SongDatabaseComponent">
                    <JD_SongDatabaseComponent/>
                </COMPONENTS>
            </Actor>
        </ACTORS>
        <sceneConfigs>
            <SceneConfigs activeSceneConfig="0">
                <sceneConfigs NAME="JD_SongDatabaseSceneConfig">
                    <JD_SongDatabaseSceneConfig SKU="{DEFAULT_SKU}" \
RatingUI="World/ui/screens/boot_warning/boot_warning_esrb.isc">
                    </JD_SongDatabaseSceneConfig>
                </sceneConfigs>
            </SceneConfigs>
        </sceneConfigs>
    </Scene>
</root>
"""


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _indent_xml(elem, level=0):
    """Add whitespace indentation to an ElementTree element in-place."""
    pad = "\n" + "    " * level
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = pad + "    "
        for child in elem:
            _indent_xml(child, level + 1)
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = pad
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = pad


def _map_exists(root, map_name):
    """Check whether a map is already registered in the tree."""
    for actor in root.iter("Actor"):
        if actor.get("USERFRIENDLY") == map_name:
            return True
    return False


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def add_map(tree, map_name):
    """Add a map's Actor and CoverflowSkuSongs to the tree.
    Returns True if the map was added, False if it already existed."""
    root = tree.getroot()
    if _map_exists(root, map_name):
        return False

    scene = root.find("Scene")

    # Build Actor node
    actors = ET.Element("ACTORS", NAME="Actor")
    actor = ET.SubElement(actors, "Actor", {
        "RELATIVEZ": "0.000000",
        "SCALE": "1.000000 1.000000",
        "xFLIPPED": "0",
        "USERFRIENDLY": map_name,
        "POS2D": "0 0",
        "ANGLE": "0.000000",
        "INSTANCEDATAFILE": f"world/maps/{map_name}/songdesc.act",
        "LUA": f"world/maps/{map_name}/songdesc.tpl",
    })
    comps = ET.SubElement(actor, "COMPONENTS", NAME="JD_SongDescComponent")
    ET.SubElement(comps, "JD_SongDescComponent")

    # Insert before sceneConfigs
    inserted = False
    for i, child in enumerate(scene):
        if child.tag == "sceneConfigs":
            scene.insert(i, actors)
            inserted = True
            break
    if not inserted:
        scene.append(actors)

    # Add CoverflowSkuSongs
    config = root.find(".//JD_SongDatabaseSceneConfig")
    if config is not None:
        for suffix in ("cover_generic", "cover_online"):
            cf = ET.SubElement(config, "CoverflowSkuSongs")
            ET.SubElement(cf, "CoverflowSong", {
                "name": map_name,
                "cover_path": f"world/maps/{map_name}/menuart/actors/{map_name}_{suffix}.act",
            })

    return True


def set_sku(tree, sku):
    """Update the SKU attribute on the JD_SongDatabaseSceneConfig element."""
    config = tree.getroot().find(".//JD_SongDatabaseSceneConfig")
    if config is not None:
        config.set("SKU", sku)


def process_maps(map_names, output_dir):
    """Register each map into all SKU variant ISC files."""
    os.makedirs(output_dir, exist_ok=True)

    # Ensure the primary template exists
    primary = os.path.join(output_dir, SKU_FILENAMES[DEFAULT_SKU])
    if not os.path.exists(primary):
        with open(primary, "w", encoding=ENCODING) as f:
            f.write(TEMPLATE_XML)

    for map_name in map_names:
        for sku, filename in SKU_FILENAMES.items():
            out_path = os.path.join(output_dir, filename)

            if os.path.exists(out_path):
                tree = ET.parse(out_path)
            else:
                # Copy from primary template
                tree = ET.parse(primary)

            added = add_map(tree, map_name)
            set_sku(tree, sku)
            _indent_xml(tree.getroot())

            tree.write(out_path, encoding=ENCODING, xml_declaration=True)

            status = "added" if added else "already exists"
            print(f"[{status}] {map_name} -> {filename}")


def load_maps_json(path):
    """Load map names from a JSON file.
    Expects ``[{"JD_Song": ["MapA", "MapB"]}, ...]``."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    maps = []
    for obj in data:
        maps.extend(obj.get("JD_Song", []))
    return maps


def main():
    parser = argparse.ArgumentParser(
        description="Register maps into JD2021 SkuScene ISC files.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--maps", nargs="+", help="Map codenames to register")
    group.add_argument("--json", help="JSON file containing map names")
    parser.add_argument("--output", required=True,
                        help="Output directory for generated ISC files")
    args = parser.parse_args()

    if args.json:
        map_names = load_maps_json(args.json)
    else:
        map_names = args.maps

    if not map_names:
        print("No maps to register.")
        return

    process_maps(map_names, args.output)
    print(f"\nDone — processed {len(map_names)} map(s) across {len(SKU_FILENAMES)} SKU files.")


if __name__ == "__main__":
    main()
