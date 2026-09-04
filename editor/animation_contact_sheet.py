"""Dependency-free animation/image contact sheets for any Prince DAT archive."""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from dataclasses import dataclass

from composite_project import CompositeProject, initial_mode6_bits
from composite_signal import render_composite_artifacts
from phase_verification import ACCENT, CARD_BACKGROUND, GRID, SHEET_BACKGROUND, TEXT, _fill, _text
from prince_dat import DatArchive, RenderedRaster, ResourceAnalysis, hardware_palette_for_resource


MUTED = (159, 170, 184)
KID_FIRST_RESOURCE = 401


@dataclass(frozen=True)
class AnimationFamily:
    slug: str
    first_image: int
    last_image: int

    @property
    def image_ids(self) -> tuple[int, ...]:
        return tuple(range(self.first_image, self.last_image + 1))


# KID is the one archive for which this project has an authoritative family
# map. Other DATs are still exported completely, in their archive order.
KID_ANIMATION_FAMILIES = (
    AnimationFamily("RUN-STAND", 0, 14), AnimationFamily("JUMP", 15, 43),
    AnimationFamily("TURN", 44, 51), AnimationFamily("EXIT-STAIRS", 52, 63),
    AnimationFamily("RUN-TURN", 64, 76), AnimationFamily("HAZARD-DEATH", 77, 79),
    AnimationFamily("JUMP-HANG", 80, 111), AnimationFamily("FALL-LAND", 112, 119),
    AnimationFamily("STAND-UP", 120, 129), AnimationFamily("MOUSE", 130, 132),
    AnimationFamily("CAREFUL-STEP", 133, 144), AnimationFamily("CLIMB", 145, 159),
    AnimationFamily("SWORD-PICKUP", 160, 173), AnimationFamily("SWORD-COMBAT", 174, 191),
    AnimationFamily("POTION", 192, 206), AnimationFamily("DRAW-SWORD", 207, 210),
    AnimationFamily("COLLAPSE-DEATH", 211, 215), AnimationFamily("HP-HURT", 216, 218),
)


def animation_image_records(archive: DatArchive) -> tuple[ResourceAnalysis, ...]:
    """Return every renderable image in stable archive order.

    DAT archives do not label resources as animation frames. Exporting all
    editable images is therefore the only lossless generic discovery rule.
    """

    return tuple(
        analysis for analysis in archive.analyses
        if analysis.image is not None and analysis.image.bits in (1, 4)
    )


def _kid_family_labels() -> dict[int, tuple[str, int]]:
    return {
        KID_FIRST_RESOURCE + image_id: (family.slug, image_id)
        for family in KID_ANIMATION_FAMILIES for image_id in family.image_ids
    }


def _frame_label(archive: DatArchive, analysis: ResourceAnalysis) -> str:
    resource_id = analysis.resource.resource_id
    if archive.path.stem.upper().startswith("KID"):
        known = _kid_family_labels().get(resource_id)
        if known is not None:
            family, image_id = known
            return f"{family} I{image_id:03d} R{resource_id}"
    return f"R{resource_id} I{analysis.resource.index:03d}"


def _runtime_direction_bits(
    stored_bits: bytes, width: int, height: int, direction: str, source_depth: int = 4
) -> bytes:
    """Apply a horizontal runtime-style flip without changing signal pairs."""

    if direction == "left":
        return stored_bits
    if direction != "right":
        raise ValueError(f"Unsupported animation direction: {direction}")
    group_width = 2 if source_depth == 4 else 1
    if width % group_width:
        raise ValueError("Mode-6 width does not contain complete source pixels.")
    output = bytearray(len(stored_bits))
    for y in range(height):
        row = stored_bits[y * width : (y + 1) * width]
        groups = [row[x : x + group_width] for x in range(0, width, group_width)]
        output[y * width : (y + 1) * width] = b"".join(reversed(groups))
    return bytes(output)


def _blit_fit(
    pixels: bytearray, sheet_width: int, raster: RenderedRaster,
    left: int, top: int, box_width: int, box_height: int,
) -> None:
    """Nearest-neighbor fit that handles tiny sprites and full screens."""

    if raster.channels != 3:
        raise ValueError("Animation contact sheets require RGB rasters.")
    scale = min(box_width / raster.width, box_height / raster.height)
    drawn_width = max(1, int(raster.width * scale))
    drawn_height = max(1, int(raster.height * scale))
    target_left = left + (box_width - drawn_width) // 2
    target_top = top + (box_height - drawn_height) // 2
    for target_y in range(drawn_height):
        source_y = min(raster.height - 1, target_y * raster.height // drawn_height)
        for target_x in range(drawn_width):
            source_x = min(raster.width - 1, target_x * raster.width // drawn_width)
            source = (source_y * raster.width + source_x) * 3
            target = ((target_top + target_y) * sheet_width + target_left + target_x) * 3
            pixels[target : target + 3] = raster.pixels[source : source + 3]


def render_animation_contact_sheet(
    archive: DatArchive, project: CompositeProject
) -> RenderedRaster:
    """Render every editable image in the open DAT as R/L P0/P2 cards."""

    records = animation_image_records(archive)
    if not records:
        raise ValueError("The open DAT contains no editable 1-bit or 4-bit images.")
    rendered: dict[tuple[int, str, int], RenderedRaster] = {}
    for analysis in records:
        image = analysis.image
        assert image is not None
        edit = project.edits.get(analysis.resource.index)
        if edit is not None:
            edit.validate()
        hardware = hardware_palette_for_resource(archive, analysis.resource)
        original = bytes(initial_mode6_bits(image, hardware))
        width = len(original) // image.height
        for phase in (0, 2):
            stored = bytes(edit.variant_bits(phase)) if (
                edit is not None and phase in edit.phase_variants
            ) else original
            for direction in ("right", "left"):
                displayed = _runtime_direction_bits(
                    stored, width, image.height, direction, image.bits
                )
                rendered[(analysis.resource.index, direction, phase)] = render_composite_artifacts(
                    displayed, width, image.height, project.composite_profile, phase_offset=phase
                )

    panel_width, panel_height = 150, 112
    label_width = 18
    card_width = label_width + panel_width * 2 + 10
    card_height = 24 + 2 * (12 + panel_height) + 8
    columns = 4
    rows = (len(records) + columns - 1) // columns
    margin, gap, header = 12, 8, 52
    sheet_width = margin * 2 + columns * card_width + (columns - 1) * gap
    sheet_height = header + margin + rows * card_height + (rows - 1) * gap + margin
    pixels = bytearray(bytes(SHEET_BACKGROUND) * sheet_width * sheet_height)
    _text(pixels, sheet_width, margin, 8, f"{archive.path.name.upper()} ANIMATION CONTACT SHEET", TEXT, scale=3)
    _text(
        pixels, sheet_width, margin, 34,
        f"{len(records)} IMAGES   R L RUNTIME ORIENTATION   P0 P2 CARRIER PHASE", MUTED,
    )

    for ordinal, analysis in enumerate(records):
        column, row = ordinal % columns, ordinal // columns
        left = margin + column * (card_width + gap)
        top = header + margin + row * (card_height + gap)
        _fill(pixels, sheet_width, left, top, left + card_width, top + card_height, GRID)
        _fill(pixels, sheet_width, left + 1, top + 1, left + card_width - 1, top + card_height - 1, (31, 35, 42))
        _text(pixels, sheet_width, left + 6, top + 5, _frame_label(archive, analysis), ACCENT)
        for direction_index, direction in enumerate(("right", "left")):
            row_top = top + 24 + direction_index * (12 + panel_height)
            _text(pixels, sheet_width, left + 5, row_top + panel_height // 2, direction[0], TEXT)
            for phase_index, phase in enumerate((0, 2)):
                panel_left = left + label_width + phase_index * panel_width
                _text(pixels, sheet_width, panel_left + 3, row_top, f"P{phase}", MUTED)
                panel_top = row_top + 12
                _fill(pixels, sheet_width, panel_left, panel_top, panel_left + panel_width - 3, panel_top + panel_height, CARD_BACKGROUND)
                raster = rendered[(analysis.resource.index, direction, phase)]
                _blit_fit(pixels, sheet_width, raster, panel_left + 2, panel_top + 2, panel_width - 7, panel_height - 4)

    return RenderedRaster(sheet_width, sheet_height, bytes(pixels), 3, "animation-contact-sheet")


# Source compatibility for callers of the v0.4.30 KID-only function.
render_kid_animation_contact_sheet = render_animation_contact_sheet


def render_v22_runtime_contact_sheet(workspace) -> RenderedRaster:
    """Render only the two views the V22 executable can actually draw."""

    pairs = workspace.pairs
    panel_width, panel_height = 150, 112
    card_width = panel_width * 2 + 10
    card_height = 24 + panel_height + 8
    columns = 4
    rows = (len(pairs) + columns - 1) // columns
    margin, gap, header = 12, 8, 52
    sheet_width = margin * 2 + columns * card_width + (columns - 1) * gap
    sheet_height = header + margin + rows * card_height + (rows - 1) * gap + margin
    pixels = bytearray(bytes(SHEET_BACKGROUND) * sheet_width * sheet_height)
    _text(
        pixels,
        sheet_width,
        margin,
        8,
        f"{workspace.source.path.name.upper()} V22 RUNTIME CONTACT SHEET",
        TEXT,
        scale=3,
    )
    _text(
        pixels,
        sheet_width,
        margin,
        34,
        f"{len(pairs)} SOURCE FRAMES   ACTUAL RIGHT/P0 + LEFT/P0",
        MUTED,
    )
    for ordinal, pair in enumerate(pairs):
        column, row = ordinal % columns, ordinal // columns
        left = margin + column * (card_width + gap)
        top = header + margin + row * (card_height + gap)
        _fill(pixels, sheet_width, left, top, left + card_width, top + card_height, GRID)
        _fill(
            pixels,
            sheet_width,
            left + 1,
            top + 1,
            left + card_width - 1,
            top + card_height - 1,
            (31, 35, 42),
        )
        context = f" {pair.table.context.upper()}" if pair.table.context else ""
        _text(
            pixels,
            sheet_width,
            left + 6,
            top + 5,
            f"SRC {pair.source_resource_id}{context}",
            ACCENT,
        )
        for direction_index, direction in enumerate(("right", "left")):
            panel_left = left + direction_index * panel_width + 5
            _text(pixels, sheet_width, panel_left + 3, top + 15, direction.upper() + "/P0", MUTED)
            panel_top = top + 24
            _fill(
                pixels,
                sheet_width,
                panel_left,
                panel_top,
                panel_left + panel_width - 3,
                panel_top + panel_height,
                CARD_BACKGROUND,
            )
            raster = workspace.runtime_raster(pair, direction)
            _blit_fit(
                pixels,
                sheet_width,
                raster,
                panel_left + 2,
                panel_top + 2,
                panel_width - 7,
                panel_height - 4,
            )
    return RenderedRaster(sheet_width, sheet_height, bytes(pixels), 3, "v22-runtime-contact-sheet")
