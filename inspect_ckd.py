"""Quick CKD file header inspector"""
import sys, os

files = [
    r'd:\jd2021pc\Starships\8c69e5b8d670d7f19880388e995ff064.ckd',  # Cover_Generic
    r'd:\jd2021pc\Starships\dbe3c08891c1859cc22bd27c962e2268.ckd',  # Coach_1
    r'd:\jd2021pc\Starships\86e08b8e5c89f8389db5723f136b81d7.ckd',  # Cover_Online (small)
]

for path in files:
    name = os.path.basename(path)
    with open(path, 'rb') as f:
        data = f.read(128)
    
    size = os.path.getsize(path)
    print(f"\n=== {name} ({size:,} bytes) ===")
    print(f"UbiArt Header (0-44): {data[:44].hex()}")
    print(f"  Magic bytes 0-4: {data[:4]}  -> {data[:4].hex()}")
    print(f"  'TEX' at 4-7:    {data[4:7]}  -> {data[4:7].hex()}")
    print(f"After header (44-76): {data[44:76].hex()}")
    print(f"  Possible XTX/DDS/Gfx2 magic: {data[44:52]}")
    
    # Check for known texture format magics
    if data[44:48] == b'DDS ':
        print("  >>> FORMAT: DDS (PC)")
    elif data[44:48] == b'Gfx2':
        print("  >>> FORMAT: GFX2/GTX (Wii U)")
    elif data[44:48] == b'\x00\x00\x00\x04':
        print("  >>> FORMAT: Possibly NX XTX")
    else:
        print(f"  >>> FORMAT: Unknown magic: {data[44:48].hex()}")
