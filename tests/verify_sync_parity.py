import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from jd2021_installer.parsers.normalizer import normalize_sync
from jd2021_installer.core.models import MusicTrackStructure

def test_html_sync_parity():
    print("Testing HTML Sync Parity (Albatraoz example)...")
    
    # Mock MusicTrack based on V1 AUDIO_TIMING.md:
    # v_override = -2.145, marker_preroll_ms = 2060ms
    # So start_beat = -5, markers[5] = 2060 * 48 = 98880
    mt = MusicTrackStructure(
        markers=[0, 10000, 20000, 30000, 40000, 98880], # index 5 is beat 0
        start_beat=-5,
        video_start_time=-2.145
    )
    
    # 1. Test HTML source (should PRESERVE metadata VST)
    sync = normalize_sync(mt, is_html_source=True)
    print(f"HTML Sync: audio_ms={sync.audio_ms}, video_ms={sync.video_ms}")
    
    # Expected: 
    # audio_ms = -(2060 + 85) = -2145
    # video_ms = -2145 (metadata preserved)
    assert abs(sync.audio_ms + 2145.0) < 0.1, f"Audio sync failed: {sync.audio_ms}"
    assert abs(sync.video_ms + 2145.0) < 0.1, f"Video sync failed: {sync.video_ms}"
    print("✓ HTML Sync Parity OK (metadata preserved)")

def test_html_sync_synthesis():
    print("\nTesting HTML Sync Synthesis (VST is 0.0)...")
    
    mt = MusicTrackStructure(
        markers=[0, 10000, 20000, 30000, 40000, 98880],
        start_beat=-5,
        video_start_time=0.0
    )
    
    sync = normalize_sync(mt, is_html_source=True)
    print(f"Synthesized HTML Sync: audio_ms={sync.audio_ms}, video_ms={sync.video_ms}")
    
    # Expected:
    # audio_ms = -(2060 + 85) = -2145
    # video_ms = -2060 (synthesized WITHOUT 85ms as per V1 doc)
    assert abs(sync.audio_ms + 2145.0) < 0.1
    assert abs(sync.video_ms + 2060.0) < 0.1
    print("✓ HTML Sync Synthesis OK")

def test_ipk_sync_parity():
    print("\nTesting IPK Sync (Binary) Parity...")
    
    mt = MusicTrackStructure(
        markers=[0, 10000, 20000, 30000, 40000, 98880],
        start_beat=-5,
        video_start_time=0.0
    )
    
    sync = normalize_sync(mt, is_html_source=False)
    print(f"IPK Sync: audio_ms={sync.audio_ms}, video_ms={sync.video_ms}")
    
    # Expected:
    # audio_ms = 0.0
    # video_ms = -2060.0
    assert sync.audio_ms == 0.0
    assert abs(sync.video_ms + 2060.0) < 0.1
    print("✓ IPK Sync Parity OK")

if __name__ == "__main__":
    try:
        test_html_sync_parity()
        test_html_sync_synthesis()
        test_ipk_sync_parity()
        print("\nALL SYNC TESTS PASSED!")
    except AssertionError as e:
        print(f"\nTEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
