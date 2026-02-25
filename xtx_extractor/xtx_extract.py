#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# XTX Extractor
# Version 0.1
# Copyright (c) 2017 Stella/AboodXD
# GPL-3.0 License
# Original: https://github.com/aboood40091/XTX-Extractor

"""xtx_extract.py: Decode XTX images."""

import struct

from . import dds
from . import swizzle

formats = {0x00000025: 'NVN_FORMAT_RGBA8',
           0x00000038: 'NVN_FORMAT_RGBA8_SRGB',
           0x0000003d: 'NVN_FORMAT_RGB10A2',
           0x0000003c: 'NVN_FORMAT_RGB565',
           0x0000003b: 'NVN_FORMAT_RGB5A1',
           0x00000039: 'NVN_FORMAT_RGBA4',
           0x00000001: 'NVN_FORMAT_R8',
           0x0000000d: 'NVN_FORMAT_RG8',
           0x00000042: 'DXT1',
           0x00000043: 'DXT3',
           0x00000044: 'DXT5',
           0x00000049: 'BC4U',
           0x0000004a: 'BC4S',
           0x0000004b: 'BC5U',
           0x0000004c: 'BC5S'
           }

BCn_formats = [0x42, 0x43, 0x44, 0x49, 0x4a, 0x4b, 0x4c]

bpps = {0x25: 4, 0x38: 4, 0x3d: 4, 0x3c: 2, 0x3b: 2, 0x39: 2, 1: 1, 0xd: 2,
        0x42: 8, 0x43: 16,0x44: 16, 0x49: 8, 0x4a: 8, 0x4b: 16, 0x4c: 16}


class NvData:
    pass


class NvHeader(struct.Struct):
    def __init__(self):
        super().__init__('<4I')

    def data(self, data, pos):
        (self.magic,
         self.size_,
         self.majorVersion,
         self.minorVersion) = self.unpack_from(data, pos)


class NvBlockHeader(struct.Struct):
    def __init__(self):
        super().__init__('<2I2Q3I')

    def data(self, data, pos):
        (self.magic,
         self.size_,
         self.dataSize,
         self.dataOff,
         self.type_,
         self.id,
         self.typeIdx) = self.unpack_from(data, pos)


class NvTextureHeader(struct.Struct):
    def __init__(self):
        super().__init__('<Q8I')

    def data(self, data, pos):
        (self.imageSize,
         self.alignment,
         self.width,
         self.height,
         self.depth,
         self.target,
         self.format_,
         self.numMips,
         self.sliceSize) = self.unpack_from(data, pos)


def readNv(f):
    nv = NvData()

    pos = 0

    header = NvHeader()
    header.data(f, pos)

    if header.magic != 0x4E764644: # "NvFD"
        raise ValueError("Invalid file header!")

    if header.majorVersion == 1:
        texHeadBlkType = 2
        dataBlkType = 3
    else:
        raise ValueError("Unsupported XTX version!")

    pos += header.size

    block2 = False
    block3 = False

    images = 0
    imgInfo = 0

    nv.imageSize = []
    nv.alignment = []
    nv.width = []
    nv.height = []
    nv.depth = []
    nv.target = []
    nv.format = []
    nv.numMips = []
    nv.sliceSize = []
    nv.compSel = []
    nv.bpp = []
    nv.realSize = []

    nv.dataSize = []
    nv.data = []

    nv.mipOffsets = []

    while pos < len(f):
        block = NvBlockHeader()
        block.data(f, pos)

        if block.magic != 0x4E764248: # "NvBH"
            raise ValueError("Invalid block header!")

        pos += block.dataOff

        if block.type_ == texHeadBlkType:
            imgInfo += 1
            block2 = True

            texHead = NvTextureHeader()
            texHead.data(f, pos)

            pos += texHead.size

            if texHead.numMips > 17:
                raise ValueError("Invalid number of mipmaps for image " + str(imgInfo - 1))

            mipOffsets = []
            for i in range(17):
                mipOffsets.append(f[i * 4 + 3 + pos] << 24 | f[i * 4 + 2 + pos] << 16 | f[i * 4 + 1 + pos] << 8 | f[i * 4 + pos])

            nv.mipOffsets.append(mipOffsets)

            pos += block.dataSize - texHead.size

            nv.imageSize.append(texHead.imageSize)
            nv.alignment.append(texHead.alignment)
            nv.width.append(texHead.width)
            nv.height.append(texHead.height)
            nv.depth.append(texHead.depth)
            nv.target.append(texHead.target)
            nv.format.append(texHead.format_)
            nv.numMips.append(texHead.numMips)
            nv.sliceSize.append(texHead.sliceSize)

            if texHead.format_ == 1:
                nv.compSel.append([0, 0, 0, 5])

            elif texHead.format_ == 0xd:
                nv.compSel.append([0, 0, 0, 1])

            elif texHead.format_ == 0x3c:
                nv.compSel.append([0, 1, 2, 5])

            else:
                nv.compSel.append([0, 1, 2, 3])

            bpp = bpps[texHead.format_] if texHead.format_ in formats else 0
            nv.bpp.append(bpp)

            if texHead.format_ in BCn_formats:
                nv.realSize.append(((texHead.width + 3) >> 2) * ((texHead.height + 3) >> 2) * bpp)
            else:
                nv.realSize.append(texHead.width * texHead.height * bpp)

        elif block.type_ == dataBlkType:
            images += 1
            block3 = True

            nv.dataSize.append(block.dataSize)
            nv.data.append(f[pos:pos + block.dataSize])
            pos += block.dataSize

        else:
            pos += block.dataSize

    if images != imgInfo:
        raise ValueError("Image count mismatch in XTX file")

    if block2 and not block3:
        raise ValueError("Image info was found but no Image data was found.")
    if not block2 and not block3:
        raise ValueError("No Image was found in this file.")
    if not block2 and block3:
        raise ValueError("Image data was found but no Image info was found.")

    nv.numImages = images

    return nv


def get_deswizzled_data(i, nv):
    numImages = nv.numImages
    numMips = nv.numMips[i]
    width = nv.width[i]
    height = nv.height[i]
    depth = nv.depth[i]
    format_ = nv.format[i]
    realSize = nv.realSize[i]
    data = nv.data[i][:realSize]
    bpp = nv.bpp[i]
    mipOffsets = nv.mipOffsets[i]

    if format_ in formats:
        if format_ in [0x25, 0x38]:
            format__ = 28
        elif format_ == 0x3d:
            format__ = 24
        elif format_ == 0x3c:
            format__ = 85
        elif format_ == 0x3b:
            format__ = 86
        elif format_ == 0x39:
            format__ = 115
        elif format_ == 0x1:
            format__ = 61
        elif format_ == 0xd:
            format__ = 49
        elif format_ == 0x42:
            format__ = "BC1"
        elif format_ == 0x43:
            format__ = "BC2"
        elif format_ == 0x44:
            format__ = "BC3"
        elif format_ == 0x49:
            format__ = "BC4U"
        elif format_ == 0x4a:
            format__ = "BC4S"
        elif format_ == 0x4b:
            format__ = "BC5U"
        elif format_ == 0x4c:
            format__ = "BC5S"

        if depth != 1:
            raise ValueError("Unsupported depth!")

        result = []
        for level in range(numMips):
            if format_ in BCn_formats:
                size = ((max(1, width >> level) + 3) >> 2) * ((max(1, height >> level) + 3) >> 2) * bpp
            else:
                size = max(1, width >> level) * max(1, height >> level) * bpp

            mipOffset = mipOffsets[level]

            data = nv.data[i][mipOffset:mipOffset + size]

            deswizzled = swizzle.deswizzle(max(1, width >> level), max(1, height >> level), format_, data)

            data = deswizzled[:size]

            result.append(data)

        hdr = dds.generateHeader(numMips, width, height, format__, nv.compSel[i], realSize, format_ in BCn_formats)

    else:
        raise ValueError("Unsupported texture format: " + hex(format_))

    return hdr, result
