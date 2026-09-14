"""Exact Mode-6 indexed GIF samples and source-pixel transparency contract.

Shared by ordinary editor panes and linked ORIENT folder interchange.
"""
# SPDX-License-Identifier: GPL-2.0-or-later
from composite_project import CompositeEdit
from indexed_gif import IndexedGif, IndexedGifError, require_exact_format

MODE6_GIF_PALETTE = ((0, 0, 0), (255, 255, 255))
MODE6_ALPHA_GIF_PALETTE = (
    (0, 0, 0),
    (255, 255, 255),
    (255, 0, 255),
    (0, 255, 255),
)
MODE6_TRANSPARENT_INDEX = 2

def mode6_gif_pixels(
    edit: CompositeEdit,
    bits: bytes | bytearray,
    source_zero_mask: bytes | bytearray | None = None,
) -> bytes:
    """Return Mode-6 GIF indices with transparent samples marked separately."""

    if len(bits) != edit.bit_width * edit.height:
        raise IndexedGifError("Mode-6 bit count does not match the selected image.")
    mask = edit.source_zero_mask if source_zero_mask is None else source_zero_mask
    if not mask:
        mask = bytes(edit.source_width * edit.height)
    if len(mask) != edit.source_width * edit.height:
        raise IndexedGifError("Transparency mask does not match the selected image.")
    return bytes(
        MODE6_TRANSPARENT_INDEX
        if mask[edit.source_pixel_for_bit_offset(offset)]
        else int(bit)
        for offset, bit in enumerate(bits)
    )


def mode6_gif_import(
    image: IndexedGif,
    edit: CompositeEdit,
) -> tuple[bytes, bytearray | None]:
    """Decode legacy opaque or transparency-aware Mode-6 GIF indices.

    ``None`` means the legacy two-color GIF did not carry mask information and
    the current mask must be preserved. A returned mask is source-pixel-sized.
    """

    if (image.width, image.height) != (edit.bit_width, edit.height):
        raise IndexedGifError(
            f"GIF is {image.width} x {image.height}; this pane requires exactly "
            f"{edit.bit_width} x {edit.height}."
        )
    if image.transparent_index is None:
        require_exact_format(
            image,
            width=edit.bit_width,
            height=edit.height,
            palette=MODE6_GIF_PALETTE,
        )
        return bytes(image.pixels), None
    if image.palette != MODE6_ALPHA_GIF_PALETTE:
        raise IndexedGifError(
            "Transparency-aware Mode-6 GIFs must preserve the exported four-entry "
            "black, white, transparent-magenta, reserved-cyan palette."
        )
    if image.transparent_index != MODE6_TRANSPARENT_INDEX:
        raise IndexedGifError("Mode-6 GIF transparency must use palette index 2.")
    if any(index not in (0, 1, MODE6_TRANSPARENT_INDEX) for index in image.pixels):
        raise IndexedGifError("Mode-6 GIF palette index 3 is reserved and cannot be painted.")

    bits = bytes(0 if index == MODE6_TRANSPARENT_INDEX else index for index in image.pixels)
    mask = bytearray(edit.source_width * edit.height)
    for y in range(edit.height):
        for source_x in range(edit.source_width):
            first = y * edit.bit_width + (
                source_x if edit.source_depth == 1 else source_x * 2
            )
            offsets = (first,) if edit.source_depth == 1 else (first, first + 1)
            transparent = tuple(
                image.pixels[offset] == MODE6_TRANSPARENT_INDEX for offset in offsets
            )
            if any(transparent) and not all(transparent):
                raise IndexedGifError(
                    f"Transparent Mode-6 samples only cover part of source pixel "
                    f"x={source_x}, y={y}; both samples must be transparent."
                )
            if edit.source_depth == 1 and image.pixels[first] == 0:
                raise IndexedGifError(
                    "A native 1-bit Prince resource cannot encode opaque black "
                    "separately from transparent index zero."
                )
            mask[y * edit.source_width + source_x] = all(transparent)
    return bits, mask

