# IPK Unpacker - integrated from ubiart-archive-tools
# Original: https://github.com/PartyService/Ubiart-Archive-Tools
# Credits: Party Team, just gemer, Planedec50, leamsii, XpoZed, InvoxiPlayGames

import os
import struct
from pathlib import Path
import zlib
import lzma

# Define endianness as big endian
ENDIANNESS = '>'

# Define structure signs for various sizes
STRUCT_SIGNS = {
    1: 'c',
    2: 'H',
    4: 'I',
    8: 'Q'
}

# Define the structure of the IPK file header
IPK_HEADER_TEMPLATE = {
    'magic': {'size': 4},
    'version': {'size': 4},
    'platformsupported': {'size': 4},
    'base_offset': {'size': 4},
    'num_files': {'size': 4},
    'compressed': {'size': 4},
    'binaryscene': {'size': 4},
    'binarylogic': {'size': 4},
    'datasignature': {'size': 4},
    'enginesignature': {'size': 4},
    'engineversion': {'size': 4},
    'num_files2': {'size': 4},
}


def _get_file_header():
    return {
        'numOffset': {'size': 4},
        'size': {'size': 4},
        'compressed_size': {'size': 4},
        'time_stamp': {'size': 8},
        'offset': {'size': 8},
        'name_size': {'size': 4},
        'file_name': {'size': 0},
        'path_size': {'size': 4},
        'path_name': {'size': 4},
        'checksum': {'size': 4},
        'flag': {'size': 4}
    }


def _unpack(_bytes):
    return struct.unpack(ENDIANNESS + STRUCT_SIGNS[len(_bytes)], _bytes)[0]


def extract(target_file, output_dir=None):
    """Extract an IPK archive to the given output directory.

    Args:
        target_file: Path to the .ipk file (str or Path).
        output_dir:  Directory to extract into (str or Path, optional).

    Raises:
        FileNotFoundError: If target_file does not exist.
        AssertionError:    If the file is not a valid IPK archive.
    """
    target_file = Path(target_file)
    if not target_file.exists():
        raise FileNotFoundError(f"IPK file not found: {target_file}")

    # Read a fresh copy of the header template each call
    ipk_header = {k: dict(v) for k, v in IPK_HEADER_TEMPLATE.items()}

    with open(target_file, 'rb') as file:
        for v in ipk_header:
            ipk_header[v]['value'] = file.read(ipk_header[v]['size'])

        assert ipk_header['magic']['value'] == b'\x50\xEC\x12\xBA', \
            "Not a valid IPK file (bad magic bytes)"

        num_files = _unpack(ipk_header['num_files']['value'])
        print(f"    IPK: Found {num_files} files...")

        file_chunks = []
        for _ in range(num_files):
            fheader = _get_file_header()
            for v in fheader:
                _size = fheader[v]['size']
                if v == 'path_name':
                    _size = _unpack(fheader['path_size']['value'])
                if v == 'file_name':
                    _size = _unpack(fheader['name_size']['value'])
                fheader[v]['value'] = file.read(_size)
            file_chunks.append(fheader)

        if output_dir:
            output_path = Path(output_dir)
            output_path.mkdir(exist_ok=True)
        else:
            output_path = Path(target_file.stem)
            output_path.mkdir(exist_ok=True)

        base_offset = _unpack(ipk_header['base_offset']['value'])

        for k, v in enumerate(file_chunks):
            offset = _unpack(file_chunks[k]['offset']['value'])
            data_size = _unpack(file_chunks[k]['size']['value'])

            path_ori = file_chunks[k]['path_name']['value'].decode()
            if os.path.basename(path_ori) == path_ori:
                file_path = output_path / file_chunks[k]['file_name']['value'].decode()
                file_name = file_chunks[k]['path_name']['value'].decode()
            else:
                file_path = output_path / file_chunks[k]['path_name']['value'].decode()
                file_name = file_chunks[k]['file_name']['value'].decode()

            file.seek(offset + base_offset)
            file_path.mkdir(parents=True, exist_ok=True)

            with open(file_path / file_name, 'wb') as ff:
                raw_data = file.read(data_size)
                try:
                    decompressed = zlib.decompress(raw_data)
                except zlib.error:
                    try:
                        decompressed = lzma.decompress(raw_data)
                    except Exception:
                        decompressed = raw_data
                ff.write(decompressed)

    print(f"    IPK: Extracted {num_files} files to {output_path}")
