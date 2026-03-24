import unittest
import os
import shutil
import tempfile
from pathlib import Path
from jd2021_installer.extractors.archive_ipk import _detect_maps_in_dir
from jd2021_installer.parsers.normalizer import _discover_media, _find_ckd_files
from jd2021_installer.core.models import MapMedia

class TestBundleParity(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_detect_maps_standard(self):
        # Create standard layout: world/maps/<codename>
        (self.test_dir / "world" / "maps" / "MapA").mkdir(parents=True)
        (self.test_dir / "world" / "maps" / "MapB").mkdir(parents=True)
        (self.test_dir / "common").mkdir()
        
        maps = _detect_maps_in_dir(self.test_dir)
        self.assertEqual(maps, ["MapA", "MapB"])

    def test_detect_maps_legacy(self):
        # Create legacy layout: world/jd2015/<codename>
        (self.test_dir / "world" / "jd2015" / "MapC").mkdir(parents=True)
        (self.test_dir / "world" / "jd2015" / "MapD").mkdir(parents=True)
        (self.test_dir / "enginedata").mkdir()
        
        maps = _detect_maps_in_dir(self.test_dir)
        self.assertEqual(maps, ["MapC", "MapD"])

    def test_video_scoping_bundle(self):
        # Mock extracted bundle with multiple videos
        map_a_dir = self.test_dir / "world" / "maps" / "MapA"
        map_a_dir.mkdir(parents=True)
        vid_a = map_a_dir / "videos" / "video.webm"
        vid_a.parent.mkdir(parents=True)
        vid_a.touch()
        
        map_b_dir = self.test_dir / "world" / "maps" / "MapB"
        map_b_dir.mkdir(parents=True)
        vid_b = map_b_dir / "videos" / "MapB_ULTRA.webm"
        vid_b.parent.mkdir(parents=True)
        vid_b.touch()
        
        # Discover for MapA
        media = _discover_media(self.test_dir, codename="MapA")
        self.assertEqual(media.video_path, vid_a)
        
        # Discover for MapB
        media = _discover_media(self.test_dir, codename="MapB")
        self.assertEqual(media.video_path, vid_b)

    def test_find_ckd_bundle_scoping(self):
        (self.test_dir / "world" / "maps" / "MapA").mkdir(parents=True)
        mt_a = self.test_dir / "world" / "maps" / "MapA" / "musictrack.tpl.ckd"
        mt_a.touch()
        
        (self.test_dir / "world" / "maps" / "MapB").mkdir(parents=True)
        mt_b = self.test_dir / "world" / "maps" / "MapB" / "musictrack.tpl.ckd"
        mt_b.touch()
        
        res_a = _find_ckd_files(str(self.test_dir), "*musictrack*.tpl.ckd", codename="MapA")
        self.assertEqual(len(res_a), 1)
        self.assertIn("MapA", res_a[0])
        
        res_b = _find_ckd_files(str(self.test_dir), "*musictrack*.tpl.ckd", codename="MapB")
        self.assertEqual(len(res_b), 1)
        self.assertIn("MapB", res_b[0])

    def test_search_root_discovers_bundle_menuart_pictos_moves(self):
        # map subtree used for normalization
        map_subtree = self.test_dir / "world" / "maps" / "MapA"
        map_subtree.mkdir(parents=True)

        # assets in cache layout outside world/maps/<codename>
        cache_root = self.test_dir / "cache" / "itf_cooked" / "x360" / "world" / "maps" / "MapA"
        menuart = cache_root / "menuart" / "textures"
        pictos = cache_root / "timeline" / "pictos"
        moves = cache_root / "timeline" / "moves"
        menuart.mkdir(parents=True)
        pictos.mkdir(parents=True)
        moves.mkdir(parents=True)

        cover = menuart / "MapA_cover_generic.tga.ckd"
        coach = menuart / "MapA_coach_1.tga.ckd"
        cover.touch()
        coach.touch()
        (pictos / "MapA_picto_001.png.ckd").touch()
        (moves / "MapA_move_001.gesture").touch()

        media = _discover_media(map_subtree, codename="MapA", search_root=self.test_dir)

        self.assertEqual(media.cover_generic_path, cover)
        self.assertIn(coach, media.coach_images)
        self.assertEqual(media.pictogram_dir, pictos)
        self.assertEqual(media.moves_dir, moves)

if __name__ == "__main__":
    unittest.main()
