"""
CKD Texture Decoder for Just Dance (NX/Switch/X360/PC CKD -> TGA/PNG)

Supported formats:
  - NX (Switch): CKD -> strip 44-byte header -> XTX -> deswizzle -> DDS -> Pillow -> TGA/PNG
  - PC: CKD -> strip 44-byte header -> DDS -> Pillow -> TGA/PNG
  - X360: CKD -> strip 44-byte header -> parse 52-byte GPU descriptor -> byte-swap + untile -> DDS -> TGA/PNG

Usage:
    python ckd_decode.py <input.ckd> [output.tga]
    python ckd_decode.py --batch <folder_with_ckds> [output_folder]
"""

import os
import sys
import struct
import shutil
from log_config import get_logger

logger = get_logger("ckd_decode")

CKD_HEADER_SIZE = 44  # UbiArt TEX header is always 44 bytes
CKD_MAGIC = b'\x00\x00\x00\x09'
TEX_MAGIC = b'TEX'
NVFD_MAGIC = b'\x44\x46\x76\x4E'  # "DFvN" (NvFD little-endian)

# Xbox 360 GPU texture format codes (from D3DFORMAT)
_X360_FMT_DXT1 = 0x52
_X360_FMT_DXT3 = 0x53
_X360_FMT_DXT5 = 0x54

# X360 GPU descriptor size (resource table + fetch constant, from XPR2)
_X360_GPU_DESC_SIZE = 52


# ---------------------------------------------------------------------------
# Xbox 360 texture untiling (ported from Xenia emulator)
# ---------------------------------------------------------------------------

def _x360_tiled_combine(outer_inner_bytes, bank, pipe, y_lsb):
    """Xenia TiledCombine: assemble tiled address from components."""
    result = (y_lsb << 4) | (pipe << 6) | (bank << 11)
    result |= (outer_inner_bytes & 0b1111)
    result |= (((outer_inner_bytes >> 4) & 0b1) << 5)
    result |= (((outer_inner_bytes >> 5) & 0b111) << 8)
    result |= ((outer_inner_bytes >> 8) << 12)
    return result


def _x360_tiled_2d(x, y, pitch_aligned, bytes_per_block_log2):
    """Xenia Tiled2D: compute tiled byte offset for block (x, y)."""
    outer_blocks = (
        (y >> 5) * (pitch_aligned >> 5) + (x >> 5)
    ) << 6
    inner_blocks = (((y >> 1) & 0b111) << 3) | (x & 0b111)
    outer_inner_bytes = (outer_blocks | inner_blocks) << bytes_per_block_log2
    bank = (y >> 4) & 0b1
    pipe = ((x >> 3) & 0b11) ^ (((y >> 3) & 0b1) << 1)
    return _x360_tiled_combine(outer_inner_bytes, bank, pipe, y & 1)


def _x360_untile_dxt(data, pixel_width, pixel_height, block_bytes):
    """Untile Xbox 360 block-compressed (DXT) texture data."""
    bw = max(1, (pixel_width + 3) // 4)
    bh = max(1, (pixel_height + 3) // 4)
    bpp_log2 = {8: 3, 16: 4}[block_bytes]
    pitch_aligned = (bw + 31) & ~31
    output = bytearray(bw * bh * block_bytes)
    for by in range(bh):
        for bx in range(bw):
            src_offset = _x360_tiled_2d(bx, by, pitch_aligned, bpp_log2)
            dst_offset = (by * bw + bx) * block_bytes
            if 0 <= src_offset and src_offset + block_bytes <= len(data):
                output[dst_offset:dst_offset + block_bytes] = (
                    data[src_offset:src_offset + block_bytes])
    return bytes(output)


def _x360_byte_swap_16(data):
    """Swap every pair of bytes (big-endian 16-bit -> little-endian)."""
    out = bytearray(len(data))
    for i in range(0, len(data) - 1, 2):
        out[i] = data[i + 1]
        out[i + 1] = data[i]
    return bytes(out)


def _x360_build_dds(pixel_data, width, height, fourcc, block_bytes):
    """Build a DDS file from raw DXT pixel data."""
    bw = max(1, (width + 3) // 4)
    linear_size = bw * block_bytes

    dds = b'DDS '
    dds += struct.pack('<I', 124)  # header size
    dds += struct.pack('<I', 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000)  # flags
    dds += struct.pack('<I', height)
    dds += struct.pack('<I', width)
    dds += struct.pack('<I', linear_size)
    dds += struct.pack('<I', 0)    # depth
    dds += struct.pack('<I', 1)    # mipmap count
    dds += b'\x00' * (4 * 11)     # reserved

    # Pixel format
    dds += struct.pack('<I', 32)   # pf size
    dds += struct.pack('<I', 0x4)  # DDPF_FOURCC
    dds += fourcc                  # e.g. b'DXT1'
    dds += b'\x00' * 20           # rgb masks

    dds += struct.pack('<I', 0x1000)  # caps: TEXTURE
    dds += b'\x00' * 16              # caps2-4, reserved

    dds += pixel_data
    return dds


def strip_ckd_header(ckd_path):
    """Strip the 44-byte UbiArt CKD header and detect the payload format.

    Returns (payload_bytes, format_str) where format_str is one of:
    'xtx' (NX/Switch), 'dds' (PC), or 'x360'.
    """
    with open(ckd_path, 'rb') as f:
        header = f.read(CKD_HEADER_SIZE)
        payload = f.read()

    # Validate CKD header
    if header[:4] != CKD_MAGIC:
        raise ValueError(
            f"Not a CKD file: missing magic bytes (got {header[:4].hex()})")
    if header[4:7] != TEX_MAGIC:
        raise ValueError(
            f"Not a texture CKD: missing TEX marker (got {header[4:7]})")

    # Detect payload format
    if payload[:4] == NVFD_MAGIC:
        return payload, 'xtx'
    if payload[:4] == b'DDS ':
        return payload, 'dds'

    # Check for Xbox 360 format: 52-byte GPU descriptor + DXT data
    # The descriptor has a format code at offset 32 (big-endian)
    if len(payload) > _X360_GPU_DESC_SIZE:
        fmt_code = struct.unpack_from('>I', payload, 32)[0]
        if fmt_code in (_X360_FMT_DXT1, _X360_FMT_DXT3, _X360_FMT_DXT5):
            return payload, 'x360'

    raise ValueError(
        f"Unknown texture format after CKD header: "
        f"{payload[:4].hex()} ({payload[:4]})")


def x360_to_dds(payload):
    """Decode Xbox 360 CKD payload: GPU descriptor + tiled DXT data -> DDS.

    The payload starts with a 52-byte GPU descriptor (resource table + texture
    fetch constant from XPR2), followed by raw tiled big-endian DXT data.
    """
    if len(payload) <= _X360_GPU_DESC_SIZE:
        raise ValueError("X360 payload too small for GPU descriptor + data")

    # Parse format and dimensions from the GPU fetch constant
    fmt_code = struct.unpack_from('>I', payload, 32)[0]
    size_word = struct.unpack_from('>I', payload, 36)[0]
    width = (size_word & 0x1FFF) + 1
    height = ((size_word >> 13) & 0x1FFF) + 1

    fmt_map = {
        _X360_FMT_DXT1: (b'DXT1', 8),
        _X360_FMT_DXT3: (b'DXT3', 16),
        _X360_FMT_DXT5: (b'DXT5', 16),
    }
    if fmt_code not in fmt_map:
        raise ValueError(f"Unsupported X360 texture format: 0x{fmt_code:02X}")

    fourcc, block_bytes = fmt_map[fmt_code]
    dxt_data = payload[_X360_GPU_DESC_SIZE:]

    # Step 1: Byte-swap (X360 stores 16-bit values big-endian)
    swapped = _x360_byte_swap_16(dxt_data)

    # Step 2: Untile
    untiled = _x360_untile_dxt(swapped, width, height, block_bytes)

    # Step 3: Build DDS
    dds_data = _x360_build_dds(untiled, width, height, fourcc, block_bytes)

    info = {
        'width': width,
        'height': height,
        'format': fourcc.decode('ascii'),
    }
    return dds_data, info


def xtx_to_dds(xtx_data):
    """Convert XTX data to DDS using integrated XTX-Extractor deswizzle."""
    from xtx_extractor import xtx_extract

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
        raise ImportError(
            "Pillow is required for texture decoding. "
            "Install it with: pip install Pillow") from None

    # Write DDS to temp file for Pillow
    temp_dds = output_path + '.tmp.dds'
    with open(temp_dds, 'wb') as f:
        f.write(dds_data)

    try:
        img = Image.open(temp_dds)
        img.save(output_path)
        if not quiet:
            logger.info("  Saved: %s (%dx%d)", output_path, img.size[0], img.size[1])
    except Exception as e:
        # Pillow can't read all DDS formats; fall back to saving as DDS
        dds_fallback = output_path.rsplit('.', 1)[0] + '.dds'
        shutil.copy2(temp_dds, dds_fallback)
        logger.warning("  Pillow can't decode this DDS format (%s)", e)
        logger.warning("  Saved raw DDS instead: %s", dds_fallback)
        logger.info("  You can convert it with: magick %s %s", dds_fallback, output_path)
    finally:
        if os.path.exists(temp_dds):
            os.remove(temp_dds)


def decode_ckd(ckd_path, output_path=None, quiet=False):
    """Full pipeline: CKD -> detect format -> DDS -> TGA/PNG"""
    basename = os.path.basename(ckd_path)
    if not quiet:
        logger.info("\nDecoding: %s", basename)

    # Determine output path
    if output_path is None:
        output_path = ckd_path.rsplit('.', 1)[0] + '.tga'

    # Step 1: Strip CKD header and detect format
    raw_data, fmt = strip_ckd_header(ckd_path)
    if not quiet:
        logger.info("  CKD header stripped (%d bytes), payload format: %s",
                     CKD_HEADER_SIZE, fmt)

    if fmt == 'dds':
        # PC CKD - already DDS, just convert to output format
        if not quiet:
            logger.info("  PC DDS format detected, converting directly...")
        dds_to_image(raw_data, output_path, quiet=quiet)
        return True

    if fmt == 'x360':
        # Xbox 360 CKD - untile and byte-swap to DDS
        try:
            dds_data, info = x360_to_dds(raw_data)
            if not quiet:
                logger.info("  X360 untiled: %dx%d, format: %s",
                             info['width'], info['height'], info['format'])
        except Exception as e:
            logger.error("  ERROR during X360 decode of %s: %s", basename, e)
            return False
        dds_to_image(dds_data, output_path, quiet=quiet)
        return True

    # NX/Switch XTX format
    try:
        dds_data, info = xtx_to_dds(raw_data)
        if not quiet:
            logger.info("  Deswizzled: %dx%d, format: %s",
                         info['width'], info['height'], info['format'])
    except Exception as e:
        logger.error("  ERROR during XTX decode of %s: %s", basename, e)
        # Save raw XTX so user can try manual conversion
        xtx_fallback = output_path.rsplit('.', 1)[0] + '.xtx'
        with open(xtx_fallback, 'wb') as f:
            f.write(raw_data)
        logger.info("  Saved raw XTX: %s", xtx_fallback)
        return False

    # Step 3: DDS -> TGA/PNG
    dds_to_image(dds_data, output_path, quiet=quiet)
    return True


def batch_decode(input_folder, output_folder=None, quiet=False):
    """Decode all CKD files in a folder."""
    if output_folder is None:
        output_folder = os.path.join(input_folder, 'decoded')
    os.makedirs(output_folder, exist_ok=True)

    ckd_files = [f for f in os.listdir(input_folder) if f.endswith('.ckd')]

    if not ckd_files:
        logger.info("No .ckd files found in %s", input_folder)
        return

    if not quiet:
        logger.info("Found %d CKD files in %s", len(ckd_files), input_folder)
        logger.info("Output folder: %s", output_folder)

    success = 0
    for ckd_file in ckd_files:
        ckd_path = os.path.join(input_folder, ckd_file)
        # Use the CKD filename but change extension safely
        out_name = ckd_file.rsplit('.', 1)[0]
        if not any(out_name.lower().endswith(ext) for ext in ('.tga', '.png')):
            out_name += '.tga'
        out_path = os.path.join(output_folder, out_name)

        try:
            if decode_ckd(ckd_path, out_path, quiet=quiet):
                success += 1
            else:
                logger.warning("  Decode returned False for %s", ckd_file)
        except Exception as e:
            logger.warning("  Failed to decode %s: %s", ckd_file, e)

    if quiet:
        logger.info("    Decoded %d/%d textures.", success, len(ckd_files))
    else:
        logger.info("\n%s", '='*40)
        logger.info("Done! %d/%d files decoded successfully.", success, len(ckd_files))
        logger.info("Output: %s", output_folder)


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
