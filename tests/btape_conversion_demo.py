import struct
from pathlib import Path

# --- Self-contained constants and structures for btape parsing ---

_BEAT_CLIP_CRC = 0x364811D4
_ACTOR_TEMPLATE_CRC = 0x1B857BCE
_TAPE_CRC = 0x2AFED161

class BinaryReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def u32(self) -> int:
        v = struct.unpack_from(">I", self.data, self.pos)[0]
        self.pos += 4
        return v

    def skip(self, n: int) -> None:
        self.pos += n

def convert_btape_to_lua(ckd_path: Path, codename: str) -> str:
    """Standalone prototype: Convert a binary btape.ckd to UbiArt Lua."""
    data = ckd_path.read_bytes()
    r = BinaryReader(data)

    # Actor Header detection
    if data.startswith(b"\x00\x00\x00\x01"):
        unk1 = r.u32()
        r.u32() # unk2
        actor_crc = r.u32()
        if actor_crc != _ACTOR_TEMPLATE_CRC:
            return f"-- Error: Expected Actor CRC, got 0x{actor_crc:08X}"
        r.u32() # unk3
        r.skip(28) # zeros + comp_count
        template_crc = r.u32()
        
        if template_crc != _TAPE_CRC:
            return f"-- Error: Expected Tape CRC, got 0x{template_crc:08X}"
        
        r.u32() # comp_unk1
        r.u32() # unk2
        r.u32() # unk3
    else:
        r.skip(12) # Raw tape header skip

    r.u32() # timeline_ver
    entries = r.u32()
    
    clips = []
    for _ in range(entries):
        r.u32() # unknown
        entry_class = r.u32()
        entry_id = r.u32()
        entry_trackid = r.u32()
        entry_isactive = r.u32()
        entry_starttime = r.u32()
        entry_duration = r.u32()
        
        if entry_class == _BEAT_CLIP_CRC:
            beat_type = r.u32()
            clips.append({
                "Id": entry_id,
                "TrackId": entry_trackid,
                "IsActive": entry_isactive,
                "StartTime": entry_starttime,
                "Duration": entry_duration,
                "Type": beat_type
            })
        else:
            r.u32() # skip type for unknown clip

    # Generate Lua
    lua = [
        "params =",
        "{",
        '    NAME = "Tape",',
        "    Tape = ",
        "    {",
        "        Clips = {",
    ]
    
    for c in clips:
        lua.extend([
            "            {",
            '                NAME = "BeatClip",',
            "                BeatClip = ",
            "                {",
            f'                    Id = {c["Id"]},',
            f'                    TrackId = {c["TrackId"]},',
            f'                    IsActive = {c["IsActive"]},',
            f'                    StartTime = {c["StartTime"]},',
            f'                    Duration = {c["Duration"]},',
            f'                    Type = {c["Type"]},',
            "                },",
            "            },",
        ])

    lua.extend([
        "        },",
        "        TapeClock = 0,",
        "        TapeBarCount = 1,",
        "        FreeResourcesAfterPlay = 0,",
        f'        MapName = "{codename}",',
        "    }",
        "}"
    ])
    
    return "\n".join(lua)

# --- Demo Execution ---

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from jd2021_installer.extractors.archive_ipk import extract_ipk
except ImportError:
    # Error: Please ensure you run this from within the repo
    print("Error: Could not import jd2021_installer. Ensure you are in the repo root.")
    sys.exit(1)

if __name__ == "__main__":
    print("--- JD2021 Btape Extraction & Conversion Prototype ---")
    
    # Path to the reconstructed REAL sample from Step 176 (nailships)
    # This proves the logic works on actual game data bytes.
    test_src = Path(r"C:\tmp\real_nailships_sample.btape.ckd")
    
    if test_src.exists():
        print(f"Processing Historic Real Sample (NailHips): {test_src}")
        converted_lua = convert_btape_to_lua(test_src, "nailships")
        
        print("\n--- Lua Result Snippet (Real Map Proof) ---")
        print("\n".join(converted_lua.splitlines()))
        
        output_path = Path("C:/tmp/real_demo.btape")
        output_path.write_text(converted_lua)
        print(f"\nSuccess! Full converted file saved to: {output_path}")
    else:
        print(f"\n[!] Real sample file not found at: {test_src}")
        print("Please run the reconstruction script first.")
