import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from jd2021_installer.core.models import MapMedia, NormalizedMapData
from jd2021_installer.parsers.normalizer import _discover_media

def test_coach_discovery_koi():
    print("Testing Coach Discovery (Koi scenario)...")
    
    # Mocking a directory with Koi-like naming
    # Koi_Coach_1.tga.ckd
    # Koi_Coach_1_Phone.png
    # Koi_Coach_2.tga.ckd
    # Koi_Coach_2_Phone.png
    # Koi_Coach_3.tga.ckd
    # Koi_Coach_3_Phone.png
    
    # We'll use a real temp dir to test rglob
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        files = [
            "Koi_Coach_1.tga.ckd",
            "Koi_Coach_1_Phone.png",
            "Koi_Coach_2.tga.ckd",
            "Koi_Coach_2_Phone.png",
            "Koi_Coach_3.tga.ckd",
            "Koi_Coach_3_Phone.png",
            "Koi.ogg",
            "Koi_ULTRA.webm"
        ]
        for f in files:
            (tmp_path / f).write_text("dummy")
            
        media = MapMedia()
        # _discover_media(dir_path: Path, codename: Optional[str] = None) -> MapMedia
        # Wait, _discover_media is internal and modifies media in-place? 
        # Actually it's part of discover_media(directory, codename)
        
        from jd2021_installer.parsers.normalizer import _discover_media
        media = _discover_media(str(tmp_path), "Koi")
        
        print(f"Main Coaches: {[f.name for f in media.coach_images]}")
        print(f"Phone Coaches: {[f.name for f in media.coach_phone_images]}")
        
        assert len(media.coach_images) == 3
        assert len(media.coach_phone_images) == 3
        assert all("_phone" not in f.name.lower() for f in media.coach_images)
        assert all("_phone" in f.name.lower() for f in media.coach_phone_images)
        print("✓ Coach Discovery OK")

def test_coach_mapping_logic():
    print("\nTesting Coach Mapping Logic (Pipeline)...")
    import re
    def _extract_coach_index(path_name: str) -> int:
        match = re.search(r"coach_(\d+)", path_name.lower())
        return int(match.group(1)) if match else 0

    test_cases = [
        ("Koi_Coach_1.tga.ckd", 1),
        ("Koi_Coach_3_Phone.png", 3),
        ("coach_4.tga", 4),
        ("some_other_file.png", 0)
    ]
    
    for name, expected in test_cases:
        actual = _extract_coach_index(name)
        print(f"'{name}' -> {actual} (expected {expected})")
        assert actual == expected
        
    print("✓ Coach Index Extraction OK")

if __name__ == "__main__":
    try:
        test_coach_discovery_koi()
        test_coach_mapping_logic()
        print("\nALL COACH MAPPING TESTS PASSED!")
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {e}")
        sys.exit(1)
