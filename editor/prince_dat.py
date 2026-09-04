"""Prince of Persia DAT archive, graphics, and display-mode support.

This module implements the POP1 resource index and the five image codecs used
by the original DOS game (RAW, RLE, transposed RLE, LZG, and transposed LZG).
It deliberately contains no GUI code so the same decoder can be reused by the
composite editor and its round-trip tests.

The implementation is based on the format work published by the Princed
Development Team.  See THIRD_PARTY_NOTICES.md and LICENSE.txt.
"""

# SPDX-License-Identifier: GPL-2.0-or-later
# Python reimplementation created in 2026; see THIRD_PARTY_NOTICES.md.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import io
import struct
import zlib
from typing import Iterable, Sequence


VERSION = "0.5.0"
NTSC_COMPOSITE_MODE = "ntsc-composite"


class DatFormatError(ValueError):
    """Raised when a file is not a structurally valid POP1 DAT archive."""


class ImageDecodeError(ValueError):
    """Raised when a resource is not a valid supported Prince image."""


COMPRESSION_NAMES = {
    0: "RAW",
    1: "RLE left-to-right",
    2: "RLE top-to-bottom",
    3: "LZG left-to-right",
    4: "LZG top-to-bottom",
}


@dataclass(frozen=True)
class DatResource:
    """One indexed file in a POP1 DAT archive.

    ``data`` excludes the one-byte DAT checksum, matching the behavior of the
    maintained Princed Resources reader.
    """

    index: int
    resource_id: int
    offset: int
    size: int
    stored_checksum: int
    calculated_checksum: int
    checksum_ok: bool
    data: bytes

    @property
    def end_offset(self) -> int:
        """Exclusive end offset, including the checksum byte."""

        return self.offset + self.size + 1


@dataclass(frozen=True)
class PrincePalette:
    key: str
    name: str
    colors: tuple[tuple[int, int, int], ...]
    resource_id: int | None = None
    resource_index: int | None = None
    usable: bool = True
    note: str = ""
    render_mode: str = "indexed"
    row_bits: int = 0
    n_colors: int = 0
    raw_cga: bytes = b""
    raw_ega: bytes = b""
    cga_translation: tuple[int, ...] = ()
    ega_translation: tuple[int, ...] = ()


@dataclass(frozen=True)
class DecodedImage:
    width: int
    height: int
    bits: int
    type_byte: int
    algorithm: int
    packed_pixels: bytes
    pixels: bytes

    @property
    def compression_name(self) -> str:
        return COMPRESSION_NAMES.get(self.algorithm, f"Unknown ({self.algorithm})")


@dataclass(frozen=True)
class RenderedRaster:
    """RGB or RGBA pixels plus their display dimensions.

    Most previews retain the decoded image dimensions.  Mode 6 is different:
    existing 2-bit CGA pixels become two adjacent 1-bit pixels, while the
    simplified composite view combines four of those 1-bit pixels into one
    color-clock sample.
    """

    width: int
    height: int
    pixels: bytes
    channels: int
    mode: str


@dataclass(frozen=True)
class ResourceAnalysis:
    resource: DatResource
    kind: str
    image: DecodedImage | None = None
    palette: PrincePalette | None = None
    decode_error: str = ""


@dataclass
class DatArchive:
    path: Path
    data: bytes
    index_offset: int
    index_size: int
    resources: list[DatResource]
    analyses: list[ResourceAnalysis]
    embedded_palettes: list[PrincePalette]

    @classmethod
    def open(cls, path: str | Path) -> "DatArchive":
        archive_path = Path(path)
        try:
            raw = archive_path.read_bytes()
        except OSError as exc:
            raise DatFormatError(f"Could not read {archive_path}: {exc}") from exc

        resources, index_offset, index_size = parse_pop1_dat(raw)
        analyses: list[ResourceAnalysis] = []
        embedded: list[PrincePalette] = []

        for resource in resources:
            palette = detect_pop1_palette(resource)
            if palette is not None:
                embedded.append(palette)
                analyses.append(ResourceAnalysis(resource, "Palette", palette=palette))
                continue

            if resource.data == b"\x00\x00":
                analyses.append(ResourceAnalysis(resource, "Empty / data"))
                continue

            try:
                image = decode_prince_image(resource.data)
            except ImageDecodeError as exc:
                analyses.append(
                    ResourceAnalysis(resource, "Binary data", decode_error=str(exc))
                )
            else:
                analyses.append(ResourceAnalysis(resource, f"{image.bits}-bit image", image=image))

        return cls(
            path=archive_path,
            data=raw,
            index_offset=index_offset,
            index_size=index_size,
            resources=resources,
            analyses=analyses,
            embedded_palettes=embedded,
        )

    def analysis_for_index(self, index: int) -> ResourceAnalysis:
        return self.analyses[index]

    def resource_by_id(self, resource_id: int) -> DatResource | None:
        return next((r for r in self.resources if r.resource_id == resource_id), None)

    def analysis_by_id(self, resource_id: int) -> ResourceAnalysis | None:
        """Return the analyzed resource with this ID, independent of index order."""

        return next(
            (analysis for analysis in self.analyses if analysis.resource.resource_id == resource_id),
            None,
        )


def parse_pop1_dat(raw: bytes) -> tuple[list[DatResource], int, int]:
    """Parse a POP1 DAT archive and return its indexed resources."""

    if len(raw) < 8:
        raise DatFormatError("The file is too short to contain a DAT header and index.")

    index_offset, index_size = struct.unpack_from("<IH", raw, 0)
    if index_offset < 6:
        raise DatFormatError(f"Invalid index offset {index_offset}; expected at least 6.")
    if index_size < 2:
        raise DatFormatError(f"Invalid index size {index_size}; expected at least 2.")
    if index_offset + index_size != len(raw):
        raise DatFormatError(
            "The DAT index does not end at end-of-file "
            f"(offset {index_offset} + size {index_size} != {len(raw)})."
        )

    count = struct.unpack_from("<H", raw, index_offset)[0]
    expected_index_size = 2 + count * 8
    if index_size != expected_index_size:
        raise DatFormatError(
            f"The POP1 index declares {count} resources, requiring "
            f"{expected_index_size} bytes, but its header says {index_size}."
        )

    resources: list[DatResource] = []
    for position in range(count):
        record_offset = index_offset + 2 + position * 8
        resource_id, data_offset, data_size = struct.unpack_from("<HIH", raw, record_offset)
        data_end = data_offset + 1 + data_size
        if data_offset < 6 or data_end > index_offset:
            raise DatFormatError(
                f"Resource {resource_id} (index {position}) points outside the data area: "
                f"offset={data_offset}, size={data_size}."
            )

        stored_checksum = raw[data_offset]
        content = raw[data_offset + 1 : data_end]
        calculated_checksum = (-1 - sum(content)) & 0xFF
        checksum_ok = ((1 + stored_checksum + sum(content)) & 0xFF) == 0
        resources.append(
            DatResource(
                index=position,
                resource_id=resource_id,
                offset=data_offset,
                size=data_size,
                stored_checksum=stored_checksum,
                calculated_checksum=calculated_checksum,
                checksum_ok=checksum_ok,
                data=content,
            )
        )

    return resources, index_offset, index_size


def detect_pop1_palette(resource: DatResource) -> PrincePalette | None:
    """Recognize and expand a 100-byte POP1 hardware palette resource.

    The last 48 bytes are four phase-dependent 16-entry translations for CGA
    and EGA, selected by ``((y & 1) * 2 + (x & 1))``.
    """

    data = resource.data
    if len(data) != 100 or data[1:4] != b"\x00\x00\x10":
        return None

    components = data[4:52]
    if len(components) != 48 or any(value > 63 for value in components):
        return None

    colors = tuple(
        (
            _six_to_eight(components[index]),
            _six_to_eight(components[index + 1]),
            _six_to_eight(components[index + 2]),
        )
        for index in range(0, 48, 3)
    )
    raw_cga = bytes(data[52:68])
    raw_ega = bytes(data[68:100])
    cga_translation = tuple(
        (packed >> shift) & 0x03
        for packed in raw_cga
        for shift in (6, 4, 2, 0)
    )
    ega_translation = tuple(
        nibble
        for packed in raw_ega
        for nibble in (packed >> 4, packed & 0x0F)
    )
    usable = any(color != (0, 0, 0) for color in colors)
    note = ""
    if not usable:
        note = "All-black VGA slots; embedded CGA/EGA translations remain usable."
    return PrincePalette(
        key=f"embedded-{resource.index}",
        name=f"Embedded palette — resource {resource.resource_id}",
        colors=colors,
        resource_id=resource.resource_id,
        resource_index=resource.index,
        usable=usable,
        note=note,
        row_bits=int.from_bytes(data[1:3], "little"),
        n_colors=data[3],
        raw_cga=raw_cga,
        raw_ega=raw_ega,
        cga_translation=cga_translation,
        ega_translation=ega_translation,
    )


def _six_to_eight(value: int) -> int:
    return ((value & 0x3F) << 2) | ((value & 0x3F) >> 4)


def decode_prince_image(data: bytes) -> DecodedImage:
    """Decode one resource containing a Prince image.

    The six-byte image header is ``height, width, marker, type``.  Height and
    width are little-endian 16-bit values.  The upper nibble of ``type``
    encodes the pixel depth, and its lower nibble selects compression B0-B4
    (or the corresponding 1-bit/8-bit forms).
    """

    if len(data) < 6:
        raise ImageDecodeError("Resource is shorter than the six-byte image header.")

    height, width = struct.unpack_from("<HH", data, 0)
    marker = data[4]
    type_byte = data[5]
    bits = ((type_byte >> 4) & 0x07) + 1
    algorithm = type_byte & 0x0F

    if not width or not height:
        raise ImageDecodeError("Image width and height must be non-zero.")
    if width > 4096 or height > 4096:
        raise ImageDecodeError(f"Implausible image dimensions {width}×{height}.")
    if marker > 1:
        raise ImageDecodeError(f"Unsupported image marker {marker:#04x}.")
    if bits not in (1, 4, 8):
        raise ImageDecodeError(f"Unsupported encoded pixel depth {bits}.")
    if algorithm not in COMPRESSION_NAMES:
        raise ImageDecodeError(f"Unsupported compression code {algorithm:#x}.")

    if bits == 8:
        width_in_bytes = width
    elif bits == 4:
        width_in_bytes = (width + 1) // 2
    else:
        width_in_bytes = (width + 7) // 8

    expected = width_in_bytes * height
    if expected > 32 * 1024 * 1024:
        raise ImageDecodeError("Decoded image would exceed the 32 MiB safety limit.")

    compressed = data[6:]
    if algorithm == 0:
        expanded = bytes(compressed)
    elif algorithm in (1, 2):
        expanded = _expand_rle(compressed, expected)
    else:
        expanded = _expand_lzg(compressed, expected)

    if len(expanded) < expected:
        raise ImageDecodeError(
            f"Compressed stream produced {len(expanded)} bytes; {expected} are required."
        )
    packed = bytes(expanded[:expected])

    if algorithm in (2, 4):
        transposed = bytearray(expected)
        for cursor, value in enumerate(packed):
            destination = (cursor % height) * width_in_bytes + cursor // height
            if destination >= expected:
                raise ImageDecodeError("Transposed stream addressed outside the image.")
            transposed[destination] = value
        packed = bytes(transposed)

    pixels = _unpack_pixels(packed, width, height, bits, width_in_bytes)
    return DecodedImage(
        width=width,
        height=height,
        bits=bits,
        type_byte=type_byte,
        algorithm=algorithm,
        packed_pixels=packed,
        pixels=pixels,
    )


def _expand_rle(data: bytes, expected: int) -> bytes:
    output = bytearray()
    cursor = 0
    safety_limit = expected + 1024

    while cursor < len(data):
        control = data[cursor]
        cursor += 1
        if control >= 0x80:
            count = 0x100 - control
            if cursor >= len(data):
                raise ImageDecodeError("RLE repeat block is missing its value byte.")
            output.extend((data[cursor],) * count)
            cursor += 1
        else:
            count = control + 1
            if cursor + count > len(data):
                raise ImageDecodeError("RLE literal block runs past end-of-resource.")
            output.extend(data[cursor : cursor + count])
            cursor += count

        if len(output) > safety_limit:
            raise ImageDecodeError("RLE stream expands far beyond the declared image size.")

    return bytes(output)


def _expand_lzg(data: bytes, expected: int) -> bytes:
    """Expand Prince's 1 KiB-window LZ Groody stream."""

    # The original decoder prepends a zero-filled 1024-byte history window.
    output = bytearray(1024 + expected + 128)
    output_cursor = 1024
    input_cursor = 0
    target = 1024 + expected

    while input_cursor < len(data) and output_cursor < target:
        mask = data[input_cursor]
        input_cursor += 1

        for _ in range(8):
            if input_cursor >= len(data) or output_cursor >= target:
                break

            if mask & 1:
                output[output_cursor] = data[input_cursor]
                output_cursor += 1
                input_cursor += 1
            else:
                if input_cursor + 1 >= len(data):
                    raise ImageDecodeError("LZG back-reference is truncated.")
                first = data[input_cursor]
                second = data[input_cursor + 1]
                input_cursor += 2

                encoded_location = 66 + ((first & 0x03) << 8) + second
                repetition = 3 + (first >> 2)
                location = (output_cursor - encoded_location) & 0x3FF
                if location == 0:
                    location = 0x400

                for _ in range(repetition):
                    if output_cursor >= target:
                        break
                    source = output_cursor - location
                    if source < 0:
                        raise ImageDecodeError("LZG back-reference precedes its history window.")
                    output[output_cursor] = output[source]
                    output_cursor += 1

            mask >>= 1

    return bytes(output[1024:output_cursor])


def _unpack_pixels(
    packed: bytes, width: int, height: int, bits: int, width_in_bytes: int
) -> bytes:
    pixels = bytearray(width * height)
    destination = 0

    for y in range(height):
        row_offset = y * width_in_bytes
        for x in range(width):
            if bits == 8:
                value = packed[row_offset + x]
            elif bits == 4:
                byte = packed[row_offset + x // 2]
                value = byte >> 4 if (x & 1) == 0 else byte & 0x0F
            else:
                byte = packed[row_offset + x // 8]
                value = (byte >> (7 - (x & 7))) & 1
            pixels[destination] = value
            destination += 1

    return bytes(pixels)


# Canonical IBM RGBI colors.  These are also the default colors used by PR.
RGBI_COLORS: tuple[tuple[int, int, int], ...] = (
    (0x00, 0x00, 0x00),
    (0x00, 0x00, 0xAA),
    (0x00, 0xAA, 0x00),
    (0x00, 0xAA, 0xAA),
    (0xAA, 0x00, 0x00),
    (0xAA, 0x00, 0xAA),
    (0xAA, 0x55, 0x00),
    (0xAA, 0xAA, 0xAA),
    (0x55, 0x55, 0x55),
    (0x55, 0x55, 0xFF),
    (0x55, 0xFF, 0x55),
    (0x55, 0xFF, 0xFF),
    (0xFF, 0x55, 0x55),
    (0xFF, 0x55, 0xFF),
    (0xFF, 0xFF, 0x55),
    (0xFF, 0xFF, 0xFF),
)


# Source-derived color-clock lookups for simplified mode-6 composite previews.
# Each index is four adjacent high-resolution bits, leftmost bit first.  The
# two tables are DOSBox-X machine=cga_composite (early/old card) and
# machine=cga_composite2 (late/new card) outputs for mode control 0x1A, color
# select 0x0F, and hue offset 0.  See docs/DOSBOXX_COMPOSITE_PALETTE.md.
DOSBOXX_CGA_COMPOSITE_OLD_COLORS: tuple[tuple[int, int, int], ...] = (
    (0x00, 0x00, 0x00),  # 0000 #000000
    (0x00, 0x63, 0x00),  # 0001 #006300
    (0x00, 0x42, 0xE2),  # 0010 #0042E2
    (0x00, 0x9F, 0xFD),  # 0011 #009FFD
    (0xA6, 0x00, 0x5E),  # 0100 #A6005E
    (0x77, 0x73, 0x7A),  # 0101 #77737A
    (0xD1, 0x4D, 0xFF),  # 0110 #D14DFF
    (0x99, 0xAC, 0xFF),  # 0111 #99ACFF
    (0x4D, 0x40, 0x00),  # 1000 #4D4000
    (0x00, 0xB9, 0x00),  # 1001 #00B900
    (0x77, 0x73, 0x7A),  # 1010 #77737A
    (0x00, 0xEB, 0x91),  # 1011 #00EB91
    (0xFF, 0x44, 0x00),  # 1100 #FF4400
    (0xDF, 0xC4, 0x00),  # 1101 #DFC400
    (0xFF, 0x85, 0xF0),  # 1110 #FF85F0
    (0xFF, 0xFC, 0xFF),  # 1111 #FFFCFF
)


DOSBOXX_CGA_COMPOSITE_NEW_COLORS: tuple[tuple[int, int, int], ...] = (
    (0x00, 0x00, 0x00),  # 0000 #000000
    (0x00, 0x66, 0x29),  # 0001 #006629
    (0x00, 0x47, 0xFF),  # 0010 #0047FF
    (0x00, 0x94, 0xFF),  # 0011 #0094FF
    (0xBE, 0x00, 0x30),  # 0100 #BE0030
    (0x77, 0x73, 0x7A),  # 0101 #77737A
    (0xFF, 0x41, 0xFF),  # 0110 #FF41FF
    (0xBF, 0x9C, 0xFF),  # 0111 #BF9CFF
    (0x1E, 0x52, 0x00),  # 1000 #1E5200
    (0x00, 0xCC, 0x00),  # 1001 #00CC00
    (0x77, 0x73, 0x7A),  # 1010 #77737A
    (0x00, 0xEF, 0xBC),  # 1011 #00EFBC
    (0xFF, 0x55, 0x00),  # 1100 #FF5500
    (0xB9, 0xD6, 0x00),  # 1101 #B9D600
    (0xFF, 0x7F, 0xC6),  # 1110 #FF7FC6
    (0xFF, 0xFC, 0xFF),  # 1111 #FFFCFF
)


COMPOSITE_PROFILE_OLD = "old-cga"
COMPOSITE_PROFILE_NEW = "new-cga"
DEFAULT_COMPOSITE_PROFILE = COMPOSITE_PROFILE_NEW
COMPOSITE_PROFILE_LABELS = {
    COMPOSITE_PROFILE_OLD: "Old CGA",
    COMPOSITE_PROFILE_NEW: "New CGA",
}
DOSBOXX_CGA_COMPOSITE_PROFILES = {
    COMPOSITE_PROFILE_OLD: DOSBOXX_CGA_COMPOSITE_OLD_COLORS,
    COMPOSITE_PROFILE_NEW: DOSBOXX_CGA_COMPOSITE_NEW_COLORS,
}
DEFAULT_COMPOSITE_COLORS = DOSBOXX_CGA_COMPOSITE_PROFILES[
    DEFAULT_COMPOSITE_PROFILE
]

# Backwards-compatible public name used by v0.4.4 projects and callers.  It
# deliberately continues to mean DOSBox-X's original/early CGA model.
DOSBOXX_CGA_COMPOSITE_COLORS = DOSBOXX_CGA_COMPOSITE_OLD_COLORS


def _fold_four(colors: Sequence[tuple[int, int, int]]) -> tuple[tuple[int, int, int], ...]:
    return tuple(colors[index & 3] for index in range(16))


BUILTIN_PALETTES: tuple[PrincePalette, ...] = (
    PrincePalette("rgbi", "RGBI 16-color source indices", RGBI_COLORS),
    PrincePalette(
        "cga4-high",
        "CGA mode 4 high — cyan / magenta / white",
        _fold_four(((0, 0, 0), (85, 255, 255), (255, 85, 255), (255, 255, 255))),
    ),
    PrincePalette(
        "cga4-low",
        "CGA mode 4 low — cyan / magenta / light gray",
        _fold_four(((0, 0, 0), (0, 170, 170), (170, 0, 170), (170, 170, 170))),
    ),
    PrincePalette(
        "cga5-high",
        "Tweaked CGA mode 5 high — cyan / red / white",
        _fold_four(((0, 0, 0), (85, 255, 255), (255, 85, 85), (255, 255, 255))),
    ),
    PrincePalette(
        "cga5-low",
        "Tweaked CGA mode 5 low — cyan / red / light gray",
        _fold_four(((0, 0, 0), (0, 170, 170), (170, 0, 0), (170, 170, 170))),
    ),
    PrincePalette(
        "mono",
        "Mode 6 digital — 640×200 B/W, 2× source width",
        ((0, 0, 0), (255, 255, 255)),
        render_mode="mode6",
    ),
    PrincePalette(
        "composite-simple",
        "Simple composite — 160×200 DOSBox-X New CGA artifact colors",
        DEFAULT_COMPOSITE_COLORS,
        note=(
            "DOSBox-X cga_composite2 (New CGA), mode 6, foreground F, default hue; "
            "fixed four-bit cells without neighboring-pixel effects."
        ),
        render_mode="composite-simple",
    ),
    PrincePalette(
        "gray",
        "Index diagnostic — grayscale",
        tuple((index, index, index) for index in range(256)),
    ),
)


def available_palettes(archive: DatArchive) -> list[PrincePalette]:
    return list(BUILTIN_PALETTES) + list(archive.embedded_palettes)


def palette_by_key(archive: DatArchive, key: str) -> PrincePalette | None:
    return next((palette for palette in available_palettes(archive) if palette.key == key), None)


def choose_auto_palette(
    archive: DatArchive, resource: DatResource, image: DecodedImage
) -> PrincePalette:
    """Choose a useful preview palette without pretending CGA has a VGA palette."""

    if image.bits == 1:
        return _builtin("mono")
    if image.bits == 8:
        return _builtin("gray")

    stem = archive.path.stem.upper()
    if stem.startswith("C"):
        return _builtin("cga4-high")
    if stem.startswith("E"):
        return _builtin("rgbi")

    preceding = [
        palette
        for palette in archive.embedded_palettes
        if palette.usable
        and palette.resource_index is not None
        and palette.resource_index <= resource.index
    ]
    if preceding:
        return preceding[-1]

    usable = [palette for palette in archive.embedded_palettes if palette.usable]
    return usable[0] if usable else _builtin("rgbi")


def _builtin(key: str) -> PrincePalette:
    palette = next((item for item in BUILTIN_PALETTES if item.key == key), None)
    if palette is None:  # pragma: no cover - developer error
        raise KeyError(key)
    return palette


DISPLAY_MODE_NAMES = {
    "vga": "VGA",
    "ega": "EGA",
    "cga": "CGA",
    "mode6": "640×200 digital",
    "composite": "Composite",
    NTSC_COMPOSITE_MODE: "NTSC Composite",
}


def auto_display_mode(archive: DatArchive) -> str:
    """Infer the DOS video family from the conventional archive prefix."""

    stem = archive.path.stem.upper()
    if stem.startswith("C"):
        return "cga"
    if stem.startswith("E"):
        return "ega"
    return "vga"


def hardware_palette_for_resource(
    archive: DatArchive, resource: DatResource
) -> PrincePalette | None:
    """Return the hardware table governing a resource.

    Prince archives normally place a palette before the images that use it.
    If an unusual archive has no preceding palette, the closest following
    palette is preferable to silently discarding its hardware translations.
    """

    preceding = [
        palette
        for palette in archive.embedded_palettes
        if palette.resource_index is not None and palette.resource_index <= resource.index
    ]
    if preceding:
        return preceding[-1]
    following = [
        palette
        for palette in archive.embedded_palettes
        if palette.resource_index is not None
    ]
    return following[0] if following else None


def translated_index(
    image: DecodedImage,
    x: int,
    y: int,
    mode: str,
    hardware_palette: PrincePalette | None = None,
) -> int:
    """Translate one decoded source index through the embedded DOS table."""

    if not (0 <= x < image.width and 0 <= y < image.height):
        raise IndexError("Source pixel is outside the image.")
    source_index = image.pixels[y * image.width + x]
    if image.bits == 1:
        return source_index & 1
    if mode == "vga":
        return source_index
    phase = ((y & 1) << 1) | (x & 1)
    if mode in ("cga", "mode6", "composite", NTSC_COMPOSITE_MODE):
        table = hardware_palette.cga_translation if hardware_palette else ()
        return table[phase * 16 + (source_index & 0x0F)] if len(table) == 64 else source_index & 3
    if mode == "ega":
        table = hardware_palette.ega_translation if hardware_palette else ()
        return table[phase * 16 + (source_index & 0x0F)] if len(table) == 64 else source_index & 15
    raise ValueError(f"Unknown display mode: {mode}")


def display_colors(
    mode: str, hardware_palette: PrincePalette | None = None
) -> tuple[tuple[int, int, int], ...]:
    """Return the physical color set for a semantic display mode."""

    if mode == "vga":
        if hardware_palette is not None and hardware_palette.usable:
            return hardware_palette.colors
        return RGBI_COLORS
    if mode == "ega":
        return RGBI_COLORS
    if mode == "cga":
        return _builtin("cga4-high").colors[:4]
    if mode == "mode6":
        return _builtin("mono").colors
    if mode == "composite":
        return DEFAULT_COMPOSITE_COLORS
    if mode == NTSC_COMPOSITE_MODE:
        raise ValueError("NTSC Composite colors depend on neighboring signal bits.")
    raise ValueError(f"Unknown display mode: {mode}")


def display_horizontal_factors(mode: str, image_bits: int) -> tuple[int, int]:
    """Return ``(zoom, subsample)`` for normalized on-screen pixel width.

    Prince's ordinary VGA/EGA/CGA source pixels establish the editor's logical
    width.  A translated mode-6 raster contains two bits for each ordinary
    4-bit source pixel, so each bit is displayed at half width.  Conversely,
    one simplified Composite cell represents four mode-6 bits and is widened
    to cover the same logical source area.  Native 1-bit resources already use
    mode-6 pixels, so their Composite cells need four-times horizontal width.

    These factors affect GUI presentation only.  Rendered rasters and exported
    PNG dimensions remain the exact 640- or 160-column data representations.
    """

    if mode in ("mode6", NTSC_COMPOSITE_MODE):
        return (1, 1) if image_bits == 1 else (1, 2)
    if mode == "composite":
        return (4, 1) if image_bits == 1 else (2, 1)
    return (1, 1)


def normalized_display_width(width: int, mode: str, image_bits: int) -> int:
    """Return the GUI width after applying :func:`display_horizontal_factors`."""

    if width <= 0:
        raise ValueError("Display width must be positive.")
    zoom, subsample = display_horizontal_factors(mode, image_bits)
    return (width * zoom + subsample - 1) // subsample


def render_rgb(
    image: DecodedImage,
    palette: PrincePalette,
    *,
    transparent_zero: bool = False,
    checkerboard: bool = True,
) -> bytes:
    """Render decoded indices into packed RGB bytes for the GUI."""

    colors = palette.colors
    output = bytearray(image.width * image.height * 3)
    destination = 0
    for offset, index in enumerate(image.pixels):
        x = offset % image.width
        y = offset // image.width
        if transparent_zero and index == 0 and checkerboard:
            value = 0xC8 if ((x // 4) + (y // 4)) & 1 else 0xE8
            color = (value, value, value)
        else:
            color = colors[index] if index < len(colors) else (255, 0, 255)
        output[destination : destination + 3] = bytes(color)
        destination += 3
    return bytes(output)


def render_rgba(
    image: DecodedImage, palette: PrincePalette, *, transparent_zero: bool = False
) -> bytes:
    colors = palette.colors
    output = bytearray(image.width * image.height * 4)
    destination = 0
    for index in image.pixels:
        color = colors[index] if index < len(colors) else (255, 0, 255)
        output[destination : destination + 3] = bytes(color)
        output[destination + 3] = 0 if (transparent_zero and index == 0) else 255
        destination += 4
    return bytes(output)


def mode6_width(image: DecodedImage) -> int:
    """Return the number of 1-bit pixels produced by a mode-6 reinterpretation."""

    return image.width if image.bits == 1 else image.width * 2


def mode6_bit_at(
    image: DecodedImage,
    x: int,
    y: int,
    hardware_palette: PrincePalette | None = None,
) -> tuple[int, int, int]:
    """Return ``(bit, source_x, source_index)`` for one mode-6 output pixel.

    Native 1-bit resources already contain high-resolution pixels.  For the
    4-bit resources used by Prince, the embedded phase-dependent CGA table is
    applied first.  Its translated two-bit value is then read from most-
    significant to least-significant bit.  With no hardware table, the low two
    source bits provide a backwards-compatible diagnostic fallback.
    """

    output_width = mode6_width(image)
    if not (0 <= x < output_width and 0 <= y < image.height):
        raise IndexError("Mode-6 pixel is outside the image.")

    if image.bits == 1:
        source_x = x
        source_index = image.pixels[y * image.width + source_x]
        return source_index & 1, source_x, source_index

    source_x = x // 2
    source_index = image.pixels[y * image.width + source_x]
    cga_value = translated_index(
        image, source_x, y, "cga", hardware_palette
    )
    shift = 1 if (x & 1) == 0 else 0
    return (cga_value >> shift) & 1, source_x, source_index


def composite_pattern_at(
    image: DecodedImage,
    sample_x: int,
    y: int,
    hardware_palette: PrincePalette | None = None,
) -> tuple[int, int, int]:
    """Return pattern and inclusive source-x range for one color-clock sample."""

    bit_width = mode6_width(image)
    sample_width = (bit_width + 3) // 4
    if not (0 <= sample_x < sample_width and 0 <= y < image.height):
        raise IndexError("Composite sample is outside the image.")

    first_bit = sample_x * 4
    pattern = 0
    source_x_values: list[int] = []
    for bit_offset in range(4):
        bit_x = first_bit + bit_offset
        pattern <<= 1
        if bit_x < bit_width:
            bit, source_x, _source_index = mode6_bit_at(
                image, bit_x, y, hardware_palette
            )
            pattern |= bit
            source_x_values.append(source_x)

    return pattern, min(source_x_values), max(source_x_values)


def _render_transformed(
    image: DecodedImage,
    palette: PrincePalette,
    *,
    channels: int,
    transparent_zero: bool,
    checkerboard: bool,
) -> RenderedRaster:
    if channels not in (3, 4):
        raise ValueError("Preview renderer supports only RGB and RGBA pixels.")

    if palette.render_mode == "mode6":
        width = mode6_width(image)
        mode = "mode6"
    elif palette.render_mode == "composite-simple":
        width = (mode6_width(image) + 3) // 4
        mode = "composite-simple"
    else:
        pixels = (
            render_rgb(
                image,
                palette,
                transparent_zero=transparent_zero,
                checkerboard=checkerboard,
            )
            if channels == 3
            else render_rgba(image, palette, transparent_zero=transparent_zero)
        )
        return RenderedRaster(image.width, image.height, pixels, channels, "indexed")

    output = bytearray(width * image.height * channels)
    destination = 0
    for y in range(image.height):
        for x in range(width):
            if mode == "mode6":
                bit, _source_x, source_index = mode6_bit_at(image, x, y)
                color = palette.colors[bit]
                transparent = transparent_zero and source_index == 0
            else:
                pattern, source_start, source_end = composite_pattern_at(image, x, y)
                color = palette.colors[pattern]
                source_row = y * image.width
                transparent = transparent_zero and all(
                    image.pixels[source_row + source_x] == 0
                    for source_x in range(source_start, source_end + 1)
                )

            if channels == 3 and transparent and checkerboard:
                value = 0xC8 if ((x // 4) + (y // 4)) & 1 else 0xE8
                color = (value, value, value)

            output[destination : destination + 3] = bytes(color)
            if channels == 4:
                output[destination + 3] = 0 if transparent else 255
            destination += channels

    return RenderedRaster(width, image.height, bytes(output), channels, mode)


def render_preview_rgb(
    image: DecodedImage,
    palette: PrincePalette,
    *,
    transparent_zero: bool = False,
    checkerboard: bool = True,
) -> RenderedRaster:
    """Render a GUI preview, including mode-6 and simple-composite transforms."""

    return _render_transformed(
        image,
        palette,
        channels=3,
        transparent_zero=transparent_zero,
        checkerboard=checkerboard,
    )


def render_preview_rgba(
    image: DecodedImage,
    palette: PrincePalette,
    *,
    transparent_zero: bool = False,
) -> RenderedRaster:
    """Render an exportable preview, including transformed display dimensions."""

    return _render_transformed(
        image,
        palette,
        channels=4,
        transparent_zero=transparent_zero,
        checkerboard=False,
    )


def render_display_mode(
    image: DecodedImage,
    mode: str,
    hardware_palette: PrincePalette | None = None,
    *,
    composite_colors: Sequence[tuple[int, int, int]] = DEFAULT_COMPOSITE_COLORS,
    transparent_zero: bool = False,
    checkerboard: bool = True,
    channels: int = 3,
) -> RenderedRaster:
    """Render VGA, EGA, CGA, mode 6, or composite from one shared source.

    Unlike the legacy diagnostic palette renderer, this routine honors the
    embedded four-phase CGA/EGA translations before choosing physical colors.
    """

    if mode not in DISPLAY_MODE_NAMES:
        raise ValueError(f"Unknown display mode: {mode}")
    if channels not in (3, 4):
        raise ValueError("Display renderer supports only RGB and RGBA pixels.")
    if mode == "composite" and len(composite_colors) != 16:
        raise ValueError("Composite rendering requires exactly 16 colors.")

    if mode == NTSC_COMPOSITE_MODE:
        # Imported lazily because the signal decoder builds on this module's
        # RenderedRaster and composite-profile definitions.
        from composite_signal import render_composite_artifacts

        bit_width = mode6_width(image)
        mode6_bits = bytearray(
            mode6_bit_at(image, x, y, hardware_palette)[0]
            for y in range(image.height)
            for x in range(bit_width)
        )
        return render_composite_artifacts(
            mode6_bits,
            bit_width,
            image.height,
            DEFAULT_COMPOSITE_PROFILE,
            channels=channels,
        )

    if mode == "mode6":
        width = mode6_width(image)
    elif mode == "composite":
        width = (mode6_width(image) + 3) // 4
    else:
        width = image.width
    height = image.height
    colors = display_colors(mode, hardware_palette) if mode != "composite" else tuple(composite_colors)
    if mode == "vga" and image.bits == 8:
        # POP1's 100-byte records expose only 16 VGA colors.  Preserve the
        # useful legacy diagnostic for rare eight-bit resources.
        colors = tuple((index, index, index) for index in range(256))
    output = bytearray(width * height * channels)
    destination = 0

    for y in range(height):
        for x in range(width):
            if mode in ("vga", "ega", "cga"):
                source_x = x
                source_index = image.pixels[y * image.width + source_x]
                index = translated_index(image, source_x, y, mode, hardware_palette)
            elif mode == "mode6":
                index, source_x, source_index = mode6_bit_at(
                    image, x, y, hardware_palette
                )
            else:
                index, source_start, source_end = composite_pattern_at(
                    image, x, y, hardware_palette
                )
                source_x = source_start
                row = y * image.width
                source_index = 0 if all(
                    image.pixels[row + sx] == 0
                    for sx in range(source_start, source_end + 1)
                ) else 1

            transparent = transparent_zero and source_index == 0
            color = colors[index] if index < len(colors) else (255, 0, 255)
            if channels == 3 and transparent and checkerboard:
                value = 0xC8 if ((x // 4) + (y // 4)) & 1 else 0xE8
                color = (value, value, value)
            output[destination : destination + 3] = bytes(color)
            if channels == 4:
                output[destination + 3] = 0 if transparent else 255
            destination += channels

    return RenderedRaster(width, height, bytes(output), channels, mode)


def write_display_png(
    path: str | Path,
    image: DecodedImage,
    mode: str,
    hardware_palette: PrincePalette | None = None,
    *,
    composite_colors: Sequence[tuple[int, int, int]] = DEFAULT_COMPOSITE_COLORS,
    transparent_zero: bool = False,
) -> None:
    rendered = render_display_mode(
        image,
        mode,
        hardware_palette,
        composite_colors=composite_colors,
        transparent_zero=transparent_zero,
        checkerboard=False,
        channels=4,
    )
    Path(path).write_bytes(
        png_bytes(rendered.width, rendered.height, rendered.pixels, channels=4)
    )


def png_bytes(
    width: int, height: int, pixels: bytes, *, channels: int = 3
) -> bytes:
    """Encode RGB or RGBA pixels as a dependency-free PNG."""

    if width <= 0 or height <= 0:
        raise ValueError("PNG dimensions must be positive.")
    if channels not in (3, 4):
        raise ValueError("PNG encoder supports only RGB and RGBA pixels.")
    if len(pixels) != width * height * channels:
        raise ValueError("Pixel byte count does not match PNG dimensions.")

    color_type = 2 if channels == 3 else 6
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    row_bytes = width * channels
    scanlines = b"".join(
        b"\x00" + pixels[row : row + row_bytes]
        for row in range(0, len(pixels), row_bytes)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(scanlines, 9))
        + _png_chunk(b"IEND", b"")
    )


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = zlib.crc32(kind)
    checksum = zlib.crc32(payload, checksum) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def write_image_png(
    path: str | Path,
    image: DecodedImage,
    palette: PrincePalette,
    *,
    transparent_zero: bool = False,
) -> None:
    rendered = render_preview_rgba(image, palette, transparent_zero=transparent_zero)
    Path(path).write_bytes(
        png_bytes(rendered.width, rendered.height, rendered.pixels, channels=4)
    )


def write_jasc_palette(path: str | Path, palette: PrincePalette) -> None:
    lines = ["JASC-PAL", "0100", str(len(palette.colors))]
    lines.extend(f"{r} {g} {b}" for r, g, b in palette.colors)
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")


def hex_dump(data: bytes, *, maximum: int = 4096) -> str:
    shown = data[:maximum]
    lines: list[str] = []
    for offset in range(0, len(shown), 16):
        chunk = shown[offset : offset + 16]
        hex_part = " ".join(f"{value:02X}" for value in chunk).ljust(47)
        text_part = "".join(chr(value) if 32 <= value < 127 else "." for value in chunk)
        lines.append(f"{offset:08X}  {hex_part}  |{text_part}|")
    if len(data) > maximum:
        lines.append(f"\n… {len(data) - maximum:,} additional bytes not shown …")
    return "\n".join(lines)


def extract_all(
    archive: DatArchive,
    destination: str | Path,
    *,
    selected_palette_key: str = "auto",
    selected_display_mode: str | None = None,
    transparent_zero: bool = False,
) -> tuple[int, int]:
    """Extract every indexed resource and write a CSV manifest.

    Images become PNGs; palettes become JASC PAL plus a lossless BIN; every
    other resource becomes BIN.  Returns ``(image_count, other_count)``.
    """

    output_dir = Path(destination)
    output_dir.mkdir(parents=True, exist_ok=True)
    image_count = 0
    other_count = 0
    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest)
    writer.writerow(
        (
            "index",
            "resource_id",
            "offset_hex",
            "size",
            "checksum",
            "kind",
            "width",
            "height",
            "bits",
            "compression",
            "exported_file",
        )
    )

    seen_names: set[str] = set()
    for analysis in archive.analyses:
        resource = analysis.resource
        base = f"res{resource.resource_id:05d}"
        if base in seen_names:
            base += f"_index{resource.index:03d}"
        seen_names.add(base)

        width = height = bits = ""
        compression = ""
        exported: list[str] = []
        if analysis.image is not None:
            image = analysis.image
            filename = f"{base}.png"
            if selected_display_mode is not None:
                mode = (
                    auto_display_mode(archive)
                    if selected_display_mode == "auto"
                    else selected_display_mode
                )
                write_display_png(
                    output_dir / filename,
                    image,
                    mode,
                    hardware_palette_for_resource(archive, resource),
                    transparent_zero=transparent_zero,
                )
            else:
                if selected_palette_key == "auto":
                    palette = choose_auto_palette(archive, resource, image)
                else:
                    palette = palette_by_key(archive, selected_palette_key)
                    if palette is None:
                        palette = choose_auto_palette(archive, resource, image)
                write_image_png(
                    output_dir / filename,
                    image,
                    palette,
                    transparent_zero=transparent_zero,
                )
            exported.append(filename)
            image_count += 1
            width, height, bits = image.width, image.height, image.bits
            compression = image.compression_name
        elif analysis.palette is not None:
            raw_name = f"{base}.bin"
            pal_name = f"{base}.pal"
            (output_dir / raw_name).write_bytes(resource.data)
            write_jasc_palette(output_dir / pal_name, analysis.palette)
            exported.extend((raw_name, pal_name))
            other_count += 1
        else:
            filename = f"{base}.bin"
            (output_dir / filename).write_bytes(resource.data)
            exported.append(filename)
            other_count += 1

        writer.writerow(
            (
                resource.index,
                resource.resource_id,
                f"0x{resource.offset:08X}",
                resource.size,
                "OK" if resource.checksum_ok else "BAD",
                analysis.kind,
                width,
                height,
                bits,
                compression,
                ";".join(exported),
            )
        )

    (output_dir / "manifest.csv").write_text(manifest.getvalue(), encoding="utf-8-sig")
    return image_count, other_count


def iter_images(archive: DatArchive) -> Iterable[ResourceAnalysis]:
    return (analysis for analysis in archive.analyses if analysis.image is not None)
