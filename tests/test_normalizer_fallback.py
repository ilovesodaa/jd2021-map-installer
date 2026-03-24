import sys
import os
from pathlib import Path
import logging

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from jd2021_installer.parsers.normalizer import _find_ckd_files

# Setup basic logging to see the fallback messages
logging.basicConfig(level=logging.DEBUG)

def test_normalizer_fallback():
    print("Testing normalizer fallback logic...")
    
    import shutil
    temp_test_dir = Path("temp/test_normalizer")
    if temp_test_dir.exists():
        shutil.rmtree(temp_test_dir)
    temp_test_dir.mkdir(parents=True)
    
    # Create a structure: temp/test_normalizer/MapA/musictrack.tpl.ckd
    map_dir = temp_test_dir / "MapA"
    map_dir.mkdir()
    (map_dir / "musictrack.tpl.ckd").touch()
    
    # Case 1: Correct codename
    print("\nCase 1: Correct codename 'MapA'")
    results = _find_ckd_files(temp_test_dir, "*musictrack*.tpl.ckd", "MapA")
    if len(results) == 1 and "MapA" in results[0]:
        print("SUCCESS: Found musictrack with correct codename.")
    else:
        print(f"FAILED: Expected 1 result, got {len(results)}")

    # Case 2: Incorrect codename (should fall back now)
    print("\nCase 2: Incorrect codename 'Bundle1'")
    results = _find_ckd_files(temp_test_dir, "*musictrack*.tpl.ckd", "Bundle1")
    if len(results) == 1 and "MapA" in results[0]:
        print("SUCCESS: Found musictrack via fallback despite incorrect codename.")
    else:
        print(f"FAILED: Expected 1 result (fallback), got {len(results)}")

    shutil.rmtree(temp_test_dir)

if __name__ == "__main__":
    test_normalizer_fallback()
