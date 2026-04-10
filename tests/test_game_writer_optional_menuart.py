from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image

from jd2021_installer.core.config import AppConfig
from jd2021_installer.core.models import MapMedia, MusicTrackStructure, NormalizedMapData, SongDescription
from jd2021_installer.installers.game_writer import write_game_files
from jd2021_installer.parsers.normalizer import _discover_media


def _build_map_data(codename: str, media: MapMedia) -> NormalizedMapData:
    return NormalizedMapData(
        codename=codename,
        song_desc=SongDescription(map_name=codename, title=codename, artist="Artist", num_coach=1),
        music_track=MusicTrackStructure(
            markers=[0, 2400, 4800],
            start_beat=0,
            end_beat=2,
            video_start_time=-1.0,
        ),
        media=media,
    )


def test_write_game_files_skips_missing_optional_menuart_actors(tmp_path: Path) -> None:
    codename = "OptionalMap"
    target = tmp_path / codename
    map_data = _build_map_data(codename, MapMedia())

    write_game_files(map_data, target, AppConfig())

    assert (target / f"MenuArt/Actors/{codename}_cover_generic.act").exists()
    assert (target / f"MenuArt/Actors/{codename}_cover_online.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_banner_bkg.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_map_bkg.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_cover_albumbkg.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_cover_albumcoach.act").exists()


def test_write_game_files_includes_discovered_optional_menuart_actors(tmp_path: Path) -> None:
    codename = "OptionalMap"
    target = tmp_path / codename
    map_data = _build_map_data(
        codename,
        MapMedia(
            map_bkg_path=tmp_path / "map_bkg_source.tga",
            cover_albumbkg_path=tmp_path / "album_source.tga",
        ),
    )

    write_game_files(map_data, target, AppConfig())

    assert (target / f"MenuArt/Actors/{codename}_map_bkg.act").exists()
    assert (target / f"MenuArt/Actors/{codename}_cover_albumbkg.act").exists()
    assert not (target / f"MenuArt/Actors/{codename}_banner_bkg.act").exists()


def test_v2_regression_optional_acts_without_codename_prefix(tmp_path: Path) -> None:
    """
    Regression test for V2 issue: "V2 doesn't make enough .act files for images"
    
    This test simulates the scenario described in the ticket where optional assets
    (albumcoach, map_bkg) were missing from the generated map because the source
    files didn't have the codename prefix in their filename. The media discovery
    was incorrectly returning None for these files due to strict codename scoping.
    
    The fix allows optional assets to fallback to first available (without codename
    prefix match) while still preventing bundle mixing for assets with conflicting
    codenames.
    """
    codename = "TestMap"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    
    # Create source files that mimic what a map maker might provide
    # Optional assets WITHOUT codename prefixes (as reported in the issue)
    def create_dummy_image(path: Path) -> None:
        img = Image.new('RGBA', (1, 1), color=(255, 0, 0, 255))
        img.save(path, format='TGA')
    
    # Create required assets WITH codename prefix
    create_dummy_image(source_dir / f"{codename}_cover_generic.tga")
    create_dummy_image(source_dir / f"{codename}_cover_online.tga")
    
    # Create OPTIONAL assets WITHOUT codename prefix (this is what the bug was about)
    create_dummy_image(source_dir / "albumcoach.tga")
    create_dummy_image(source_dir / "map_bkg.tga")
    
    # Step 1: Discover media from source
    discovered_media = _discover_media(str(source_dir), codename)
    
    # Verify that optional assets are discovered even without codename prefix
    assert discovered_media.cover_generic_path is not None, "cover_generic should be discovered"
    assert discovered_media.cover_albumcoach_path is not None, "albumcoach should be discovered without codename prefix"
    assert discovered_media.map_bkg_path is not None, "map_bkg should be discovered without codename prefix"
    
    # Step 2: Build map data with discovered media
    map_data = _build_map_data(codename, discovered_media)
    
    # Step 3: Generate game files and verify .act files are created
    target = tmp_path / "target"
    write_game_files(map_data, target, AppConfig())
    
    # Verify that the .act files for optional assets are created
    # (This was the missing issue reported in the ticket)
    assert (target / f"MenuArt/Actors/{codename}_cover_generic.act").exists(), "cover_generic.act should be created"
    assert (target / f"MenuArt/Actors/{codename}_cover_online.act").exists(), "cover_online.act should be created"
    assert (target / f"MenuArt/Actors/{codename}_cover_albumcoach.act").exists(), \
        "cover_albumcoach.act should be created (was missing in V2)"
    assert (target / f"MenuArt/Actors/{codename}_map_bkg.act").exists(), \
        "map_bkg.act should be created (was missing in V2)"


def test_menuart_isc_is_valid_xml_and_has_single_cover_generic_actor(tmp_path: Path) -> None:
    codename = "XmlMap"
    target = tmp_path / codename
    map_data = _build_map_data(codename, MapMedia())

    write_game_files(map_data, target, AppConfig())

    isc_path = target / f"MenuArt/{codename}_menuart.isc"
    content = isc_path.read_text(encoding="utf-8")

    # Must be parseable and structurally valid (no nested duplicate Actor corruption).
    root = ET.fromstring(content)
    assert root.tag == "root"

    generic_refs = content.count(f"{codename}_cover_generic.act")
    assert generic_refs == 1
