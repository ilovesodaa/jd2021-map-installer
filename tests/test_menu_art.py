import unittest
from pathlib import Path
import shutil
import tempfile
import os
from jd2021_installer.parsers.normalizer import _discover_media
from jd2021_installer.core.models import MapMedia
from jd2021_installer.installers.media_processor import process_menu_art

from PIL import Image

class TestMenuArt(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.codename = "TestMap"

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _create_dummy_image(self, path):
        img = Image.new('RGBA', (1, 1), color=(255, 0, 0, 255))
        img.save(path, format='TGA')

    def test_cover_discovery_variants(self):
        # Case 1: Only generic cover exists
        self._create_dummy_image(self.test_dir / "TestMap_Cover_Generic.tga.ckd")
        media = _discover_media(self.test_dir, self.codename.lower())
        
        self.assertIsNotNone(media.cover_generic_path)
        self.assertIsNotNone(media.cover_online_path)

    def test_cover_discovery_both(self):
        # Case 2: Both exist
        self._create_dummy_image(self.test_dir / "TestMap_Cover_Generic.tga.ckd")
        self._create_dummy_image(self.test_dir / "TestMap_Cover_Online.tga.ckd")
        media = _discover_media(self.test_dir, self.codename.lower())
        
        self.assertEqual(media.cover_generic_path.name, "TestMap_Cover_Generic.tga.ckd")
        self.assertEqual(media.cover_online_path.name, "TestMap_Cover_Online.tga.ckd")

    def test_menu_art_healing(self):
        # Setup target directory structure
        target = self.test_dir / "target"
        tex_dir = target / "menuart" / "textures"
        tex_dir.mkdir(parents=True)
        
        # Only generic cover in target (decoded)
        self._create_dummy_image(tex_dir / "TestMap_cover_generic.tga")
        
        # Heal
        process_menu_art(target, "TestMap")
        
        # Verify online cover was created
        self.assertTrue((tex_dir / "TestMap_cover_online.tga").exists())

    def test_banner_synthesis_from_bkg(self):
        # Setup
        self._create_dummy_image(self.test_dir / "TestMap_map_bkg.png")
        
        # Discover
        media = _discover_media(self.test_dir, "testmap")
        
        # Verify map_bkg is discovered but banner_bkg stays optional/missing
        self.assertIsNone(media.banner_bkg_path)
        self.assertIsNotNone(media.map_bkg_path)
        self.assertEqual(media.map_bkg_path.name, "TestMap_map_bkg.png")

    def test_bundle_scoping_no_leakage(self):
        # Setup two maps
        map_a_dir = self.test_dir / "MapA"
        map_a_dir.mkdir()
        self._create_dummy_image(map_a_dir / "MapA_banner_bkg.png")
        
        map_b_dir = self.test_dir / "MapB"
        map_b_dir.mkdir()
        # Map B has NO banner
        
        # Discover Map B from the root (simulating bundle scan)
        media_b = _discover_media(self.test_dir, "mapb")
        
        # Verify Map B did NOT "steal" Map A's banner
        self.assertIsNone(media_b.banner_bkg_path)

    def test_media_processor_does_not_synthesize_banner(self):
        # Setup target directory structure
        target = self.test_dir / "target_proc"
        tex_dir = target / "menuart" / "textures"
        tex_dir.mkdir(parents=True)
        
        # Only map_bkg in target
        self._create_dummy_image(tex_dir / "TestMap_map_bkg.tga")
        
        # Heal
        process_menu_art(target, "TestMap")
        
        # Verify banner_bkg remains optional
        self.assertFalse((tex_dir / "TestMap_banner_bkg.tga").exists())

if __name__ == "__main__":
    unittest.main()
