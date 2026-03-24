import sys
from pathlib import Path
import os
import shutil
import tempfile

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from unittest.mock import MagicMock
import jd2021_installer.installers.media_processor as mp
mp.run_ffmpeg = MagicMock()
mp.run_ffprobe = MagicMock()

from jd2021_installer.installers.media_processor import generate_intro_amb

def test_amb_injection_idempotency():
    print("Testing AMB Injection Idempotency...")
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        audio_dir = tmp_path / "audio"
        audio_dir.mkdir()
        
        # 1. Create a dummy audio ISC
        isc_path = audio_dir / "TestMap_audio.isc"
        isc_content = '''<?xml version="1.0" encoding="ISO-8859-1"?>
<root>
\t<Scene>
\t\t<ACTORS NAME="Actor">
\t\t\t<Actor USERFRIENDLY="MusicTrack" />
\t\t</ACTORS>
\t\t<sceneConfigs>
\t\t\t<SceneConfigs />
\t\t</sceneConfigs>
\t</Scene>
</root>'''
        isc_path.write_text(isc_content)
        
        # dummy ogg
        ogg_path = tmp_path / "test.ogg"
        ogg_path.write_text("dummy")
        
        # 2. First injection
        generate_intro_amb(ogg_path, "TestMap", tmp_path, a_offset=-2.145, v_override=-2.145)
        
        content = isc_path.read_text()
        count = content.count("amb_testmap_intro.tpl")
        print(f"Injection count 1: {count}")
        assert count == 1, "First injection failed"
        
        # 3. Second injection (should be skipped)
        generate_intro_amb(ogg_path, "TestMap", tmp_path, a_offset=-2.145, v_override=-2.145)
        
        content = isc_path.read_text()
        count = content.count("amb_testmap_intro.tpl")
        print(f"Injection count 2: {count}")
        assert count == 1, "Second injection was NOT skipped (redundant!)"
        
        print("✓ AMB Injection Idempotency OK")

if __name__ == "__main__":
    try:
        test_amb_injection_idempotency()
        print("\nALL AMB TESTS PASSED!")
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {e}")
        sys.exit(1)
