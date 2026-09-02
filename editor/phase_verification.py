"""Dependency-free phase-verification contact sheets."""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from composite_project import CompositeProject
from composite_signal import render_composite_artifacts
from prince_dat import RenderedRaster


SHEET_BACKGROUND = (19, 21, 25)
CARD_BACKGROUND = (0, 0, 0)
MISSING_BACKGROUND = (38, 42, 49)
GRID = (66, 74, 86)
TEXT = (238, 241, 246)
ACCENT = (92, 190, 255)

# Compact 3x5 capitals keep labels deterministic without Pillow or system fonts.
_GLYPHS = {
    " ": (0, 0, 0, 0, 0), "-": (0, 0, 7, 0, 0), ".": (0, 0, 0, 0, 2),
    "0": (7, 5, 5, 5, 7), "1": (2, 6, 2, 2, 7), "2": (7, 1, 7, 4, 7),
    "3": (7, 1, 7, 1, 7), "4": (5, 5, 7, 1, 1), "5": (7, 4, 7, 1, 7),
    "6": (7, 4, 7, 5, 7), "7": (7, 1, 1, 1, 1), "8": (7, 5, 7, 5, 7),
    "9": (7, 5, 7, 1, 7), "A": (2, 5, 7, 5, 5), "B": (6, 5, 6, 5, 6),
    "C": (7, 4, 4, 4, 7), "D": (6, 5, 5, 5, 6), "E": (7, 4, 6, 4, 7),
    "F": (7, 4, 6, 4, 4), "G": (7, 4, 5, 5, 7), "H": (5, 5, 7, 5, 5),
    "I": (7, 2, 2, 2, 7), "J": (1, 1, 1, 5, 7), "K": (5, 5, 6, 5, 5),
    "L": (4, 4, 4, 4, 7), "M": (5, 7, 7, 5, 5), "N": (5, 7, 7, 7, 5),
    "O": (7, 5, 5, 5, 7), "P": (7, 5, 7, 4, 4), "Q": (7, 5, 5, 7, 1),
    "R": (6, 5, 6, 5, 5), "S": (7, 4, 7, 1, 7), "T": (7, 2, 2, 2, 2),
    "U": (5, 5, 5, 5, 7), "V": (5, 5, 5, 5, 2), "W": (5, 5, 7, 7, 5),
    "X": (5, 5, 2, 5, 5), "Y": (5, 5, 2, 2, 2), "Z": (7, 1, 2, 4, 7),
}


def _fill(pixels, width, left, top, right, bottom, color) -> None:
    left = max(0, min(width, left))
    right = max(left, min(width, right))
    row = bytes(color) * (right - left)
    for y in range(max(0, top), max(0, bottom)):
        start = (y * width + left) * 3
        pixels[start : start + len(row)] = row


def _text(pixels, width, x, y, value, color, *, scale=2) -> None:
    for character in value.upper():
        glyph = _GLYPHS.get(character, _GLYPHS[" "])
        for row, bits in enumerate(glyph):
            for column in range(3):
                if bits & (1 << (2 - column)):
                    _fill(
                        pixels, width,
                        x + column * scale, y + row * scale,
                        x + (column + 1) * scale, y + (row + 1) * scale,
                        color,
                    )
        x += 4 * scale


def _blit_scaled(pixels, sheet_width, raster, left, top, scale) -> None:
    if raster.channels != 3:
        raise ValueError("Phase-verification sheets require RGB rasters.")
    for y in range(raster.height):
        source_row = raster.pixels[y * raster.width * 3 : (y + 1) * raster.width * 3]
        expanded = b"".join(
            source_row[x : x + 3] * scale for x in range(0, len(source_row), 3)
        )
        for repeat in range(scale):
            start = ((top + y * scale + repeat) * sheet_width + left) * 3
            pixels[start : start + len(expanded)] = expanded


def render_phase_verification_sheet(project: CompositeProject) -> RenderedRaster:
    """Render every project edit against each enabled runtime carrier phase."""

    edits = [project.edits[index] for index in sorted(project.edits)]
    if not edits:
        raise ValueError("Open at least one editable image before exporting a sheet.")
    for edit in edits:
        edit.validate()
        project.validate_phase_policy(edit)

    phases = tuple(sorted({phase for edit in edits for phase in edit.enabled_phases}))
    rendered = {
        (edit.resource_index, phase): render_composite_artifacts(
            edit.variant_bits(phase), edit.bit_width, edit.height,
            project.composite_profile, phase_offset=phase,
        )
        for edit in edits
        for phase in edit.enabled_phases
    }
    max_width = max(raster.width for raster in rendered.values())
    max_height = max(raster.height for raster in rendered.values())
    scale = 3 if max_width <= 96 and max_height <= 96 else 2 if max_width <= 200 else 1
    margin, label_width, header_height, row_gap = 12, 56, 34, 8
    panel_width = max_width * scale + 16
    panel_height = max_height * scale + 16
    sheet_width = max(168, margin * 2 + label_width + len(phases) * panel_width)
    sheet_height = header_height + margin + len(edits) * panel_height + (len(edits) - 1) * row_gap + margin
    pixels = bytearray(bytes(SHEET_BACKGROUND) * sheet_width * sheet_height)

    _text(pixels, sheet_width, margin, 8, "PHASE VERIFICATION", TEXT)
    for column, phase in enumerate(phases):
        x = margin + label_width + column * panel_width + 6
        _text(pixels, sheet_width, x, 20, f"P{phase}", ACCENT)

    for row, edit in enumerate(edits):
        top = header_height + margin + row * (panel_height + row_gap)
        _text(pixels, sheet_width, margin, top + 6, f"R{edit.resource_id}", ACCENT)
        for column, phase in enumerate(phases):
            left = margin + label_width + column * panel_width
            _fill(pixels, sheet_width, left, top, left + panel_width - 4, top + panel_height, GRID)
            _fill(
                pixels, sheet_width, left + 1, top + 1,
                left + panel_width - 5, top + panel_height - 1,
                CARD_BACKGROUND if phase in edit.enabled_phases else MISSING_BACKGROUND,
            )
            raster = rendered.get((edit.resource_index, phase))
            if raster is None:
                continue
            image_left = left + 1 + (panel_width - 6 - raster.width * scale) // 2
            image_top = top + 1 + (panel_height - 2 - raster.height * scale) // 2
            _blit_scaled(pixels, sheet_width, raster, image_left, image_top, scale)

    return RenderedRaster(sheet_width, sheet_height, bytes(pixels), 3, "phase-verification")
