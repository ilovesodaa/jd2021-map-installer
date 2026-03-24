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

if __name__ == "__main__":
    unittest.main()
