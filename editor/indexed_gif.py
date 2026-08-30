"""Dependency-free indexed GIF interchange with strict palette validation.

The composite editor uses GIF as a lossless index container, not as a color
conversion format.  Exported files therefore carry one global color table and
one image.  Importers can require the exact dimensions and palette (including
entry order) before accepting any pixel indices.
"""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Sequence


class IndexedGifError(ValueError):
    """Raised when a GIF is malformed or violates the indexed contract."""


@dataclass(frozen=True)
class IndexedGif:
    width: int
    height: int
    palette: tuple[tuple[int, int, int], ...]
    pixels: bytes


def _normalize_palette(
    palette: Sequence[Sequence[int]],
) -> tuple[tuple[int, int, int], ...]:
    try:
        colors = tuple(
            tuple(int(component) for component in color) for color in palette
        )
    except (TypeError, ValueError) as exc:
        raise IndexedGifError("GIF palette entries must be RGB triples.") from exc
    if len(colors) < 2 or len(colors) > 256 or len(colors) & (len(colors) - 1):
        raise IndexedGifError(
            "GIF palette size must be a power of two between 2 and 256."
        )
    if any(
        len(color) != 3 or any(component < 0 or component > 255 for component in color)
        for color in colors
    ):
        raise IndexedGifError(
            "GIF palette entries must contain three values between 0 and 255."
        )
    return colors


def _pack_codes(codes: Sequence[int], code_size: int) -> bytes:
    """Pack fixed-width GIF LZW codes least-significant bit first."""

    output = bytearray()
    accumulator = 0
    bit_count = 0
    for code in codes:
        accumulator |= int(code) << bit_count
        bit_count += code_size
        while bit_count >= 8:
            output.append(accumulator & 0xFF)
            accumulator >>= 8
            bit_count -= 8
    if bit_count:
        output.append(accumulator & 0xFF)
    return bytes(output)


def _literal_lzw(indices: bytes, minimum_code_size: int) -> bytes:
    """Encode indices with legal, deliberately simple clear/literal pairs.

    Resetting before every literal keeps the code width constant and avoids a
    large compressor dependency.  It is less compact than dictionary LZW but
    remains modest for Prince's small images and is accepted by standard GIF
    readers and editors.
    """

    clear_code = 1 << minimum_code_size
    end_code = clear_code + 1
    codes: list[int] = []
    for index in indices:
        codes.extend((clear_code, index))
    codes.append(end_code)
    return _pack_codes(codes, minimum_code_size + 1)


def _sub_blocks(payload: bytes) -> bytes:
    output = bytearray()
    for offset in range(0, len(payload), 255):
        block = payload[offset : offset + 255]
        output.append(len(block))
        output.extend(block)
    output.append(0)
    return bytes(output)


def indexed_gif_bytes(
    width: int,
    height: int,
    palette: Sequence[Sequence[int]],
    pixels: bytes | bytearray | Sequence[int],
) -> bytes:
    """Encode one opaque, non-interlaced indexed image as GIF87a."""

    if width <= 0 or height <= 0 or width > 0xFFFF or height > 0xFFFF:
        raise IndexedGifError("GIF dimensions must be between 1 and 65535.")
    colors = _normalize_palette(palette)
    try:
        indices = bytes(pixels)
    except (TypeError, ValueError) as exc:
        raise IndexedGifError(
            "GIF pixel indices must be integer values between 0 and 255."
        ) from exc
    if len(indices) != width * height:
        raise IndexedGifError("GIF pixel count does not match its dimensions.")
    if indices and max(indices) >= len(colors):
        raise IndexedGifError("GIF contains a pixel index outside its palette.")

    palette_bits = (len(colors) - 1).bit_length()
    table_size_code = palette_bits - 1
    packed_fields = 0x80 | ((palette_bits - 1) << 4) | table_size_code
    logical_screen = struct.pack(
        "<HHBBB",
        width,
        height,
        packed_fields,
        0,
        0,
    )
    color_table = bytes(component for color in colors for component in color)
    image_descriptor = b"," + struct.pack("<HHHHB", 0, 0, width, height, 0)
    minimum_code_size = max(2, palette_bits)
    compressed = _literal_lzw(indices, minimum_code_size)
    return (
        b"GIF87a"
        + logical_screen
        + color_table
        + image_descriptor
        + bytes((minimum_code_size,))
        + _sub_blocks(compressed)
        + b";"
    )


def write_indexed_gif(
    path: str | Path,
    width: int,
    height: int,
    palette: Sequence[Sequence[int]],
    pixels: bytes | bytearray | Sequence[int],
) -> None:
    Path(path).write_bytes(indexed_gif_bytes(width, height, palette, pixels))


def _read_sub_blocks(data: bytes, offset: int) -> tuple[bytes, int]:
    output = bytearray()
    while True:
        if offset >= len(data):
            raise IndexedGifError("GIF ended inside an image-data block.")
        size = data[offset]
        offset += 1
        if size == 0:
            return bytes(output), offset
        end = offset + size
        if end > len(data):
            raise IndexedGifError("GIF contains a truncated data sub-block.")
        output.extend(data[offset:end])
        offset = end


class _CodeReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.bit_offset = 0

    def read(self, width: int) -> int | None:
        if self.bit_offset + width > len(self.payload) * 8:
            return None
        value = 0
        for part in range(width):
            absolute = self.bit_offset + part
            value |= ((self.payload[absolute // 8] >> (absolute & 7)) & 1) << part
        self.bit_offset += width
        return value


def _decode_lzw(
    payload: bytes,
    minimum_code_size: int,
    expected_pixels: int,
) -> bytes:
    if minimum_code_size < 2 or minimum_code_size > 8:
        raise IndexedGifError("GIF LZW minimum code size must be between 2 and 8.")

    clear_code = 1 << minimum_code_size
    end_code = clear_code + 1
    reader = _CodeReader(payload)
    output = bytearray()
    table: list[bytes | None]
    code_size: int
    next_code: int
    previous: bytes | None

    def reset() -> None:
        nonlocal table, code_size, next_code, previous
        table = [None] * 4096
        for index in range(clear_code):
            table[index] = bytes((index,))
        code_size = minimum_code_size + 1
        next_code = end_code + 1
        previous = None

    reset()
    saw_end = False
    while True:
        code = reader.read(code_size)
        if code is None:
            break
        if code == clear_code:
            reset()
            continue
        if code == end_code:
            saw_end = True
            break
        if code < next_code and table[code] is not None:
            entry = table[code]
            assert entry is not None
        elif code == next_code and previous is not None:
            entry = previous + previous[:1]
        else:
            raise IndexedGifError("GIF contains an invalid LZW code stream.")

        output.extend(entry)
        if len(output) > expected_pixels:
            raise IndexedGifError("GIF image data contains too many pixel indices.")

        if previous is not None and next_code < 4096:
            table[next_code] = previous + entry[:1]
            next_code += 1
            if next_code == (1 << code_size) and code_size < 12:
                code_size += 1
        previous = entry

    if not saw_end:
        raise IndexedGifError("GIF image data has no LZW end code.")
    if len(output) != expected_pixels:
        raise IndexedGifError(
            f"GIF decoded {len(output)} pixels; expected {expected_pixels}."
        )
    return bytes(output)


def _deinterlace(indices: bytes, width: int, height: int) -> bytes:
    rows = [b""] * height
    source_row = 0
    for start, step in ((0, 8), (4, 8), (2, 4), (1, 2)):
        for destination_row in range(start, height, step):
            begin = source_row * width
            rows[destination_row] = indices[begin : begin + width]
            source_row += 1
    return b"".join(rows)


def decode_indexed_gif(data: bytes) -> IndexedGif:
    """Decode one opaque indexed GIF while preserving its exact indices."""

    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise IndexedGifError("File is not a GIF87a or GIF89a image.")
    width, height, packed, _background, _aspect = struct.unpack_from("<HHBBB", data, 6)
    if width == 0 or height == 0:
        raise IndexedGifError("GIF dimensions must be positive.")
    if not packed & 0x80:
        raise IndexedGifError("GIF must contain one global indexed palette.")
    palette_size = 1 << ((packed & 0x07) + 1)
    offset = 13
    palette_end = offset + palette_size * 3
    if palette_end > len(data):
        raise IndexedGifError("GIF global palette is truncated.")
    palette = tuple(
        tuple(data[position : position + 3])
        for position in range(offset, palette_end, 3)
    )
    offset = palette_end
    image_pixels: bytes | None = None
    transparency = False
    saw_trailer = False

    while offset < len(data):
        marker = data[offset]
        offset += 1
        if marker == 0x3B:
            saw_trailer = True
            break
        if marker == 0x21:
            if offset >= len(data):
                raise IndexedGifError("GIF ended inside an extension block.")
            extension = data[offset]
            offset += 1
            if extension == 0xF9:
                if offset + 6 > len(data) or data[offset] != 4:
                    raise IndexedGifError("GIF graphic-control extension is malformed.")
                transparency = transparency or bool(data[offset + 1] & 0x01)
                if data[offset + 5] != 0:
                    raise IndexedGifError("GIF graphic-control extension is malformed.")
                offset += 6
            else:
                _ignored, offset = _read_sub_blocks(data, offset)
            continue
        if marker != 0x2C:
            raise IndexedGifError(f"GIF contains unknown block marker 0x{marker:02X}.")
        if image_pixels is not None:
            raise IndexedGifError("Animated or multi-frame GIFs cannot be imported.")
        if offset + 9 > len(data):
            raise IndexedGifError("GIF image descriptor is truncated.")
        left, top, image_width, image_height, image_packed = struct.unpack_from(
            "<HHHHB", data, offset
        )
        offset += 9
        if (left, top, image_width, image_height) != (0, 0, width, height):
            raise IndexedGifError(
                "GIF image must fill the logical screen at coordinate 0,0."
            )
        if image_packed & 0x80:
            raise IndexedGifError(
                "GIF must use its global palette; local palettes are not accepted."
            )
        if offset >= len(data):
            raise IndexedGifError("GIF is missing its LZW minimum code size.")
        minimum_code_size = data[offset]
        offset += 1
        compressed, offset = _read_sub_blocks(data, offset)
        image_pixels = _decode_lzw(
            compressed,
            minimum_code_size,
            width * height,
        )
        if image_packed & 0x40:
            image_pixels = _deinterlace(image_pixels, width, height)

    if not saw_trailer:
        raise IndexedGifError("GIF is missing its trailer.")
    if offset != len(data):
        raise IndexedGifError("GIF contains trailing data after its trailer.")
    if image_pixels is None:
        raise IndexedGifError("GIF contains no image frame.")
    if transparency:
        raise IndexedGifError("Transparent GIFs cannot be imported.")
    if image_pixels and max(image_pixels) >= palette_size:
        raise IndexedGifError("GIF contains a pixel index outside its palette.")
    return IndexedGif(width, height, palette, image_pixels)


def read_indexed_gif(path: str | Path) -> IndexedGif:
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise IndexedGifError(f"Could not read GIF: {exc}") from exc
    return decode_indexed_gif(payload)


def require_exact_format(
    image: IndexedGif,
    *,
    width: int,
    height: int,
    palette: Sequence[Sequence[int]],
) -> None:
    """Reject dimensions or a palette that differ from the pane's contract."""

    expected_palette = _normalize_palette(palette)
    if (image.width, image.height) != (width, height):
        raise IndexedGifError(
            f"GIF is {image.width}×{image.height}; this pane requires exactly "
            f"{width}×{height}."
        )
    if len(image.palette) != len(expected_palette):
        raise IndexedGifError(
            f"GIF has {len(image.palette)} palette entries; this pane requires "
            f"exactly {len(expected_palette)}."
        )
    for index, (actual, expected) in enumerate(zip(image.palette, expected_palette)):
        if actual != expected:
            raise IndexedGifError(
                f"GIF palette entry {index} is #{actual[0]:02X}{actual[1]:02X}{actual[2]:02X}; "
                f"this pane requires #{expected[0]:02X}{expected[1]:02X}{expected[2]:02X}."
            )
