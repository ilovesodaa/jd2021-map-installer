"""
CKD Texture Decoder for Just Dance (NX/Switch CKD → TGA/PNG)

Pipeline: .ckd → strip 44-byte UbiArt header → .xtx → XTX-Extractor deswizzle → .dds → Pillow → .tga/.png

Usage:
    python ckd_decode.py <input.ckd> [output.tga]
    python ckd_decode.py --batch <folder_with_ckds> [output_folder]
"""

import os
import sys
import struct
import tempfile
import shutil

# Add XTX-Extractor to path
XTX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'XTX-Extractor')
sys.path.insert(0, XTX_DIR)

CKD_HEADER_SIZE = 44  # UbiArt TEX header is always 44 bytes
CKD_MAGIC = b'\x00\x00\x00\x09'
TEX_MAGIC = b'TEX'
NVFD_MAGIC = b'\x44\x46\x76\x4E'  # "DFvN" (NvFD little-endian)


def strip_ckd_header(ckd_path):
    """Strip the 44-byte UbiArt CKD header and return the raw XTX data."""
    with open(ckd_path, 'rb') as f:
        header = f.read(CKD_HEADER_SIZE)
        xtx_data = f.read()

    # Validate CKD header
    if header[:4] != CKD_MAGIC:
        raise ValueError(f"Not a CKD file: missing magic bytes (got {header[:4].hex()})")
    if header[4:7] != TEX_MAGIC:
        raise ValueError(f"Not a texture CKD: missing TEX marker (got {header[4:7]})")

    # Validate XTX payload
    if xtx_data[:4] != NVFD_MAGIC:
        # Check if it's a PC DDS format instead
        if xtx_data[:4] == b'DDS ':
            return xtx_data, 'dds'
        raise ValueError(f"Unknown texture format after CKD header: {xtx_data[:4].hex()} ({xtx_data[:4]})")

    return xtx_data, 'xtx'


def xtx_to_dds(xtx_data):
    """Convert XTX data to DDS using XTX-Extractor's readNv + deswizzle."""
    import xtx_extract

    nv = xtx_extract.readNv(xtx_data)

    if nv.numImages == 0:
        raise ValueError("No images found in XTX data")

    # Process first image
    hdr, result = xtx_extract.get_deswizzled_data(0, nv)

    if hdr == b'' or result == []:
        raise ValueError("Failed to deswizzle XTX texture data")

    # Combine header + all mip levels
    dds_data = hdr
    for mip in result:
        dds_data += mip

    info = {
        'width': nv.width[0],
        'height': nv.height[0],
        'format': xtx_extract.formats.get(nv.format[0], hex(nv.format[0])),
    }

    return dds_data, info


def dds_to_image(dds_data, output_path, quiet=False):
    """Convert DDS data to TGA or PNG using Pillow."""
    try:
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow is not installed. Install it with: pip install Pillow")
        sys.exit(1)

    # Write DDS to temp file for Pillow
    temp_dds = output_path + '.tmp.dds'
    with open(temp_dds, 'wb') as f:
        f.write(dds_data)

    try:
        img = Image.open(temp_dds)
        img.save(output_path)
        if not quiet:
            print(f"  Saved: {output_path} ({img.size[0]}x{img.size[1]})")
    except Exception as e:
        # Pillow can't read all DDS formats; fall back to saving as DDS
        dds_fallback = output_path.rsplit('.', 1)[0] + '.dds'
        shutil.copy2(temp_dds, dds_fallback)
        print(f"  Pillow can't decode this DDS format ({e})")
        print(f"  Saved raw DDS instead: {dds_fallback}")
        print(f"  You can convert it with: magick {dds_fallback} {output_path}")
    finally:
        if os.path.exists(temp_dds):
            os.remove(temp_dds)


def decode_ckd(ckd_path, output_path=None, quiet=False):
    """Full pipeline: CKD → XTX → DDS → TGA/PNG"""
    basename = os.path.basename(ckd_path)
    if not quiet:
        print(f"\nDecoding: {basename}")

    # Determine output path
    if output_path is None:
        output_path = ckd_path.rsplit('.', 1)[0] + '.tga'

    # Step 1: Strip CKD header
    raw_data, fmt = strip_ckd_header(ckd_path)
    if not quiet:
        print(f"  CKD header stripped ({CKD_HEADER_SIZE} bytes), payload format: {fmt}")

    if fmt == 'dds':
        # PC CKD - already DDS, just convert to output format
        if not quiet:
            print(f"  PC DDS format detected, converting directly...")
        dds_to_image(raw_data, output_path, quiet=quiet)
        return True

    # Step 2: XTX → DDS (deswizzle)
    try:
        dds_data, info = xtx_to_dds(raw_data)
        if not quiet:
            print(f"  Deswizzled: {info['width']}x{info['height']}, format: {info['format']}")
    except Exception as e:
        print(f"  ERROR during XTX decode of {basename}: {e}")
        # Save raw XTX so user can try manual conversion
        xtx_fallback = output_path.rsplit('.', 1)[0] + '.xtx'
        with open(xtx_fallback, 'wb') as f:
            f.write(raw_data)
        print(f"  Saved raw XTX: {xtx_fallback}")
        return False

    # Step 3: DDS → TGA/PNG
    dds_to_image(dds_data, output_path, quiet=quiet)
    return True


def batch_decode(input_folder, output_folder=None, quiet=False):
    """Decode all CKD files in a folder."""
    if output_folder is None:
        output_folder = os.path.join(input_folder, 'decoded')
    os.makedirs(output_folder, exist_ok=True)

    ckd_files = [f for f in os.listdir(input_folder) if f.endswith('.ckd')]

    if not ckd_files:
        print(f"No .ckd files found in {input_folder}")
        return

    if not quiet:
        print(f"Found {len(ckd_files)} CKD files in {input_folder}")
        print(f"Output folder: {output_folder}")

    success = 0
    for ckd_file in ckd_files:
        ckd_path = os.path.join(input_folder, ckd_file)
        # Use the CKD filename but change extension safely
        out_name = ckd_file.rsplit('.', 1)[0]
        if not out_name.lower().endswith('.tga'):
            out_name += '.tga'
        out_path = os.path.join(output_folder, out_name)

        if decode_ckd(ckd_path, out_path, quiet=quiet):
            success += 1

    if quiet:
        print(f"    Decoded {success}/{len(ckd_files)} textures.")
    else:
        print(f"\n{'='*40}")
        print(f"Done! {success}/{len(ckd_files)} files decoded successfully.")
        print(f"Output: {output_folder}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Check for --quiet / -q flag
    quiet = '--quiet' in sys.argv or '-q' in sys.argv
    args = [a for a in sys.argv[1:] if a not in ('--quiet', '-q')]

    if args and args[0] == '--batch':
        input_folder = args[1] if len(args) > 1 else '.'
        output_folder = args[2] if len(args) > 2 else None
        batch_decode(input_folder, output_folder, quiet=quiet)
    else:
        ckd_path = args[0] if args else sys.argv[1]
        output_path = args[1] if len(args) > 1 else None
        decode_ckd(ckd_path, output_path, quiet=quiet)
