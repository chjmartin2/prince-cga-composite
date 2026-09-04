"""Comparison and composite-editor windows for Prince DAT Explorer."""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from math import ceil, floor
from pathlib import Path
from queue import Empty, Queue
import re
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Callable, Iterable

from engine_phase_usage import (
    PHASE_POLICY_ENGINE,
    PHASE_POLICY_LABELS,
    PHASE_POLICY_MANUAL,
)
from indexed_gif import (
    IndexedGif,
    IndexedGifError,
    read_indexed_gif,
    require_exact_format,
    write_indexed_gif,
)
from composite_converter import (
    CONVERSION_EXHAUSTIVE,
    CONVERSION_MODE_LABELS,
    CONVERSION_MODES,
    CONVERSION_SIMPLE_PALETTE,
    CONVERSION_SIMULATED_NTSC,
    DITHER_BAYER,
    DITHER_FLOYD_STEINBERG,
    DITHER_NONE,
    PHASE_ALL,
    QUALITY_BALANCED,
    QUALITY_FAST,
    QUALITY_HIGH,
    ConversionCancelled,
    ConversionResult,
    ConversionSettings,
    convert_raster_to_exhaustive,
    convert_raster_to_composite,
    convert_raster_to_simple_palette,
    render_all_phase_grid,
    render_simple_palette_bits,
    render_simple_palette_phase_grid,
    resolved_phase_offsets,
)

from composite_project import (
    PHASES,
    PHASE_PROFILE_ALL,
    PHASE_PROFILE_CUSTOM,
    PHASE_PROFILE_FIXED,
    PHASE_PROFILE_LABELS,
    PHASE_PROFILE_PARITY_02,
    PHASE_PROFILE_PARITY_13,
    PHASE_PROFILE_PHASES,
    PROJECT_EXTENSION,
    CompositeEdit,
    CompositeProject,
    CompositeProjectError,
    format_hex_color,
    initial_mode6_bits,
    parse_hex_color,
    predicted_image_for_edit,
    render_edited_composite,
    render_edited_mode6,
    write_phase_manifest,
    write_patched_dat,
)
from composite_signal import render_composite_artifacts
from animation_contact_sheet import (
    animation_image_records,
    render_animation_contact_sheet,
    render_v22_runtime_contact_sheet,
)
from orientation_workspace import (
    Direction,
    OrientationPair,
    V22OrientationWorkspace,
    mirror_mask,
    mirror_raster,
)
from phase_verification import render_phase_verification_sheet
from prince_dat import (
    COMPOSITE_PROFILE_LABELS,
    DISPLAY_MODE_NAMES,
    NTSC_COMPOSITE_MODE,
    DatArchive,
    DatFormatError,
    DecodedImage,
    PrincePalette,
    RenderedRaster,
    ResourceAnalysis,
    composite_pattern_at,
    display_colors,
    display_horizontal_factors,
    hardware_palette_for_resource,
    mode6_bit_at,
    normalized_display_width,
    png_bytes,
    render_display_mode,
    translated_index,
)
from room_sets import ArchiveContext, RoomSetError


MODE_LABELS = tuple(DISPLAY_MODE_NAMES[mode] for mode in DISPLAY_MODE_NAMES)
LABEL_TO_MODE = {label: mode for mode, label in DISPLAY_MODE_NAMES.items()}
COMPARISON_NTSC_MODE = NTSC_COMPOSITE_MODE
COMPARISON_NTSC_LABEL = DISPLAY_MODE_NAMES[NTSC_COMPOSITE_MODE]
COMPARISON_MODE_LABELS = MODE_LABELS
COMPARISON_LABEL_TO_MODE = LABEL_TO_MODE


def render_comparison_mode(
    image: DecodedImage,
    mode: str,
    hardware_palette: PrincePalette | None,
) -> tuple[RenderedRaster, str]:
    """Render one comparison choice and return its presentation-width mode."""

    return (
        render_display_mode(image, mode, hardware_palette),
        "mode6" if mode == COMPARISON_NTSC_MODE else mode,
    )


COMPOSITE_EDITOR_ZOOM_VALUES = (
    "1x",
    "2x",
    "3x",
    "4x",
    "6x",
    "8x",
    "10x",
    "12x",
    "16x",
    "20x",
)
CONVERTER_PREVIEW_ZOOM_VALUES = COMPOSITE_EDITOR_ZOOM_VALUES
EDITOR_PREVIEW_MODES = (
    "vga",
    "ega",
    "cga",
    "mode6",
    "composite",
    "artifact",
)
PREVIEW_VIEW_VALUES = ("original", "edited")
EDITABLE_GIF_MODES = ("mode6", "composite")
MODE6_GIF_PALETTE = ((0, 0, 0), (255, 255, 255))
MODE6_ALPHA_GIF_PALETTE = (
    (0, 0, 0),
    (255, 255, 255),
    (255, 0, 255),
    (0, 255, 255),
)
MODE6_TRANSPARENT_INDEX = 2
BULK_MODE6_GIF_PATTERN = re.compile(
    r"^(?P<resource_id>[0-9]+)(?:_P(?P<phase>[0-3]))?\.gif$",
    re.IGNORECASE,
)
TRANSPARENCY_BRUSH = -1
DEFAULT_TRANSPARENCY_DISPLAY_COLOR = (255, 0, 255)
PHASE_PROFILE_BY_LABEL = {label: profile for profile, label in PHASE_PROFILE_LABELS.items()}
PHASE_POLICY_BY_LABEL = {label: policy for policy, label in PHASE_POLICY_LABELS.items()}

PHASE_SIDECAR_HELP_TEXT = (
    "Press Ctrl+S or choose Project → Save phase-aware sidecar (.pdcproj).\n\n"
    "The sidecar saves:\n"
    "• every edited DAT image, not only the image currently on screen;\n"
    "• every stored P0–P3 variant, including stored slots that are not currently enabled;\n"
    "• enabled runtime coverage, the active edit phase, the DAT fallback, mask state, "
    "and both editable Composite palettes.\n\n"
    "To continue later, open the original source DAT, open the Composite editor, then "
    "choose Project → Open phase-aware sidecar. The source identity is verified before "
    "the project is attached.\n\n"
    "Save patched DAT is different: the original DAT resource format has room for only "
    "one image, so it writes each graphic family's selected DAT fallback. Export the "
    "phase-aware runtime manifest when a game-side packer needs every enabled variant."
)


def _format_phase_set(phases: Iterable[int]) -> str:
    """Return a compact label for one resource's reachable phase set."""

    normalized = tuple(sorted(set(int(phase) for phase in phases)))
    return "+".join(f"P{phase}" for phase in normalized) or "no phases"


def _rgb332_palette() -> tuple[tuple[int, int, int], ...]:
    """Return a deterministic 256-color palette for signal-preview exports."""

    return tuple(
        (
            ((index >> 5) & 0x07) * 255 // 7,
            ((index >> 2) & 0x07) * 255 // 7,
            (index & 0x03) * 255 // 3,
        )
        for index in range(256)
    )


ARTIFACT_GIF_PALETTE = _rgb332_palette()


def parse_bulk_mode6_gif_name(path: str | Path) -> tuple[int, int | None]:
    """Return the resource ID and optional phase encoded by a bulk GIF name."""

    name = Path(path).name
    match = BULK_MODE6_GIF_PATTERN.fullmatch(name)
    if match is None:
        raise IndexedGifError(
            f"{name} is not a bulk Mode-6 name. Use 54.gif for a single-phase "
            "resource or 751_P0.gif / 751_P2.gif for a phase family."
        )
    return int(match.group("resource_id")), (
        int(match.group("phase")) if match.group("phase") is not None else None
    )


def bulk_mode6_gif_name(edit: CompositeEdit, phase: int) -> str:
    """Return the stable resource-ID filename used by archive interchange."""

    if phase not in edit.enabled_phases:
        raise IndexedGifError(
            f"P{phase} is not enabled for resource {edit.resource_id}."
        )
    suffix = "" if len(edit.enabled_phases) == 1 else f"_P{phase}"
    return f"{edit.resource_id}{suffix}.gif"


def _editable_analyses_by_resource_id(
    analyses: Iterable[ResourceAnalysis],
) -> dict[int, ResourceAnalysis]:
    """Build an unambiguous resource-ID lookup for archive GIF interchange."""

    result: dict[int, ResourceAnalysis] = {}
    for analysis in analyses:
        resource_id = analysis.resource.resource_id
        if resource_id in result:
            raise IndexedGifError(
                f"Resource ID {resource_id} occurs more than once in this DAT; "
                "numeric GIF filenames cannot identify those records uniquely."
            )
        result[resource_id] = analysis
    return result


def prepare_bulk_mode6_exports(
    archive: DatArchive,
    project: CompositeProject,
    analyses: Iterable[ResourceAnalysis],
) -> tuple[tuple[str, IndexedGif], ...]:
    """Render every editable resource/phase without changing the live project."""

    editable = tuple(analyses)
    _editable_analyses_by_resource_id(editable)
    candidate = copy.deepcopy(project)
    exports: list[tuple[str, IndexedGif]] = []
    for analysis in editable:
        image = analysis.image
        if image is None:
            continue
        edit = candidate.edit_for_image(
            archive,
            analysis.resource.index,
            image,
        )
        for phase in edit.enabled_phases:
            exports.append(
                (
                    bulk_mode6_gif_name(edit, phase),
                    IndexedGif(
                        edit.bit_width,
                        edit.height,
                        MODE6_ALPHA_GIF_PALETTE,
                        mode6_gif_pixels(edit, edit.variant_bits(phase)),
                        MODE6_TRANSPARENT_INDEX,
                    ),
                )
            )
    return tuple(exports)


def prepare_bulk_mode6_imports(
    archive: DatArchive,
    project: CompositeProject,
    analyses: Iterable[ResourceAnalysis],
    filenames: Iterable[str | Path],
) -> tuple[dict[int, CompositeEdit], int]:
    """Validate a bulk folder and return detached replacement edit records.

    The returned records are safe to install together only after this function
    succeeds. No live project state changes during parsing or validation.
    """

    by_id = _editable_analyses_by_resource_id(analyses)
    grouped: dict[int, dict[int | None, Path]] = {}
    file_count = 0
    for filename in filenames:
        path = Path(filename)
        resource_id, phase = parse_bulk_mode6_gif_name(path)
        analysis = by_id.get(resource_id)
        if analysis is None:
            raise IndexedGifError(
                f"{path.name} names resource {resource_id}, which is not an editable "
                "1-bit or 4-bit image in this DAT."
            )
        files = grouped.setdefault(resource_id, {})
        if phase in files:
            label = f"P{phase}" if phase is not None else "the unsuffixed slot"
            raise IndexedGifError(
                f"Resource {resource_id} has more than one file for {label}."
            )
        files[phase] = path
        file_count += 1
    if not file_count:
        raise IndexedGifError(
            "The selected folder contains no numeric Mode-6 GIFs."
        )

    candidate = copy.deepcopy(project)
    replacements: dict[int, CompositeEdit] = {}
    for resource_id, files in grouped.items():
        analysis = by_id[resource_id]
        image = analysis.image
        if image is None:  # guarded by the editable lookup
            raise IndexedGifError(f"Resource {resource_id} is no longer an image.")
        edit = candidate.edit_for_image(
            archive,
            analysis.resource.index,
            image,
        )
        enabled = edit.enabled_phases
        if len(enabled) == 1:
            phase = enabled[0]
            received = set(files)
            if received == {None}:
                files = {phase: files[None]}
            elif received != {phase}:
                expected = f"{resource_id}.gif or {resource_id}_P{phase}.gif"
                raise IndexedGifError(
                    f"Resource {resource_id} has one enabled slot, P{phase}; use {expected}."
                )
        else:
            if None in files:
                raise IndexedGifError(
                    f"Resource {resource_id} enables {_format_phase_set(enabled)}; "
                    "each GIF needs its _P0 through _P3 suffix."
                )
            received = tuple(sorted(int(phase) for phase in files))
            if received != enabled:
                raise IndexedGifError(
                    f"Resource {resource_id} requires the complete "
                    f"{_format_phase_set(enabled)} set, but the folder contains "
                    f"{_format_phase_set(received)}."
                )

        imported: dict[int, bytes] = {}
        masks: dict[int, bytearray | None] = {}
        for phase_key, path in files.items():
            if phase_key is None:  # normalized above for one-slot resources
                raise IndexedGifError(f"{path.name} has an ambiguous phase.")
            phase = int(phase_key)
            image_gif = read_indexed_gif(path)
            bits, mask = mode6_gif_import(image_gif, edit)
            imported[phase] = bits
            masks[phase] = mask

        carried_masks = [mask for mask in masks.values() if mask is not None]
        if carried_masks and len(carried_masks) != len(masks):
            raise IndexedGifError(
                f"Resource {resource_id} mixes legacy opaque and transparency-aware GIFs."
            )
        if carried_masks and any(mask != carried_masks[0] for mask in carried_masks[1:]):
            raise IndexedGifError(
                f"Every phase GIF for resource {resource_id} must carry the same "
                "transparency mask."
            )

        if carried_masks:
            reference_bits = imported[next(iter(imported))]
            edit.source_zero_mask = bytearray(carried_masks[0])
            edit.mask_reference_bits = bytearray(reference_bits)
            edit.mask_locked = True
            edit.mask_authored = True
        for phase, bits in imported.items():
            edit.set_variant_bits(phase, bits, enable=True, activate=False)
        edit.validate()

        hardware = hardware_palette_for_resource(archive, analysis.resource)
        try:
            for phase, bits in imported.items():
                predicted_image_for_edit(
                    image,
                    edit,
                    hardware,
                    phase=phase,
                )
        except CompositeProjectError as exc:
            raise IndexedGifError(
                f"Resource {resource_id} cannot represent the imported Mode-6 bits "
                f"through its CGA translation table: {exc}"
            ) from exc
        replacements[analysis.resource.index] = copy.deepcopy(edit)

    return replacements, file_count


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
            f"GIF is {image.width}Ã—{image.height}; this pane requires exactly "
            f"{edit.bit_width}Ã—{edit.height}."
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


def render_mode6_editor_raster(
    edit: CompositeEdit,
    bits: bytes | bytearray,
    source_zero_mask: bytes | bytearray,
    transparency_color: tuple[int, int, int],
) -> RenderedRaster:
    """Render Mode-6 bits while making DAT index-zero pixels unambiguous."""

    if len(bits) != edit.bit_width * edit.height:
        raise CompositeProjectError("Mode-6 bit count does not match the edited image.")
    if not source_zero_mask:
        source_zero_mask = bytes(edit.source_width * edit.height)
    if len(source_zero_mask) != edit.source_width * edit.height:
        raise CompositeProjectError("Transparency mask does not match the edited image.")
    if len(transparency_color) != 3 or any(
        not 0 <= channel <= 255 for channel in transparency_color
    ):
        raise CompositeProjectError("Transparency display color must be an RGB triple.")
    output = bytearray(len(bits) * 3)
    for offset, bit in enumerate(bits):
        if source_zero_mask[edit.source_pixel_for_bit_offset(offset)]:
            color = transparency_color
        else:
            color = (255, 255, 255) if bit else (0, 0, 0)
        output[offset * 3:offset * 3 + 3] = bytes(color)
    return RenderedRaster(edit.bit_width, edit.height, bytes(output), 3, "mode6")


def _source_mode6_value(
    edit: CompositeEdit,
    source_x: int,
    y: int,
    source_index: int,
    hardware_palette: PrincePalette | None,
) -> int:
    if edit.source_depth == 1:
        return source_index & 1
    phase = ((y & 1) << 1) | (source_x & 1)
    table = hardware_palette.cga_translation if hardware_palette else ()
    return (
        table[phase * 16 + (source_index & 0x0F)]
        if len(table) == 64
        else source_index & 3
    )


def paint_mode6_dat_pixel(
    edit: CompositeEdit,
    bit_x: int,
    y: int,
    brush: int,
    hardware_palette: PrincePalette | None,
) -> tuple[list[tuple[int, int, int]], bool, bool]:
    """Paint one Mode-6 sample and its DAT index-zero transparency state.

    Returns ``(active_variant_bit_changes, mask_changed, native_one_bit_zero)``.
    A native one-bit DAT has only indices 0 and 1, so its zero/black value is
    necessarily the same stored value used for transparency.
    """

    if brush not in (TRANSPARENCY_BRUSH, 0, 1):
        raise CompositeProjectError("Mode-6 brush must be transparent, black, or white.")
    if not (0 <= bit_x < edit.bit_width and 0 <= y < edit.height):
        return [], False, False
    if len(edit.source_zero_mask) != edit.source_width * edit.height:
        raise CompositeProjectError("This edit has no complete DAT index-zero mask.")
    if len(edit.mask_reference_bits) != edit.bit_width * edit.height:
        raise CompositeProjectError("This edit has no complete DAT mask-reference stream.")

    source_x = bit_x if edit.source_depth == 1 else bit_x // 2
    source_offset = y * edit.source_width + source_x
    row = y * edit.bit_width
    sample_offsets = (
        (row + source_x,)
        if edit.source_depth == 1
        else (row + source_x * 2, row + source_x * 2 + 1)
    )
    variants_before = {
        phase: bytes(variant) for phase, variant in edit.phase_variants.items()
    }
    mask_before = edit.source_zero_mask[source_offset]
    reference_before = bytes(edit.mask_reference_bits)
    locked_before = edit.mask_locked
    authored_before = edit.mask_authored

    native_one_bit_zero = edit.source_depth == 1 and brush in (
        TRANSPARENCY_BRUSH,
        0,
    )
    transparent = brush == TRANSPARENCY_BRUSH or native_one_bit_zero
    edit.source_zero_mask[source_offset] = int(transparent)
    edit.mask_locked = True
    edit.mask_authored = True

    if transparent:
        value = _source_mode6_value(edit, source_x, y, 0, hardware_palette)
        desired = (
            (value & 1,)
            if edit.source_depth == 1
            else ((value >> 1) & 1, value & 1)
        )
        for variant in edit.phase_variants.values():
            for offset, bit in zip(sample_offsets, desired):
                variant[offset] = bit
                edit.mask_reference_bits[offset] = bit
    else:
        if edit.source_depth == 1:
            for variant in edit.phase_variants.values():
                variant[sample_offsets[0]] = brush
        else:
            edit.bits[row + bit_x] = brush

    allowed_indices = (
        (0,)
        if transparent
        else ((1,) if edit.source_depth == 1 else range(1, 16))
    )
    representable = True
    for variant in edit.phase_variants.values():
        if edit.source_depth == 1:
            desired_value = variant[sample_offsets[0]]
        else:
            desired_value = (
                (variant[sample_offsets[0]] << 1)
                | variant[sample_offsets[1]]
            )
        if not any(
            _source_mode6_value(edit, source_x, y, candidate, hardware_palette)
            == desired_value
            for candidate in allowed_indices
        ):
            representable = False
            break
    if not representable:
        for phase, payload in variants_before.items():
            edit.phase_variants[phase][:] = payload
        edit.bits = edit.phase_variants[edit.signal_phase]
        edit.source_zero_mask[source_offset] = mask_before
        edit.mask_reference_bits[:] = reference_before
        edit.mask_locked = locked_before
        edit.mask_authored = authored_before
        kind = "transparent index zero" if transparent else "an opaque nonzero index"
        raise CompositeProjectError(
            f"This DAT palette cannot represent the painted Mode-6 value as {kind}."
        )

    edit.validate()
    active_before = variants_before[edit.signal_phase]
    active_after = edit.variant_bits(edit.signal_phase)
    changes = [
        (offset, active_before[offset], active_after[offset])
        for offset in sample_offsets
        if active_before[offset] != active_after[offset]
    ]
    return changes, bool(mask_before) != transparent, native_one_bit_zero


def raster_rgb332_indices(raster: RenderedRaster) -> bytes:
    """Quantize an RGB raster directly into :data:`ARTIFACT_GIF_PALETTE`."""

    if raster.channels != 3:
        raise IndexedGifError("Only opaque RGB editor panes can be exported to GIF.")
    output = bytearray(raster.width * raster.height)
    for offset in range(raster.width * raster.height):
        position = offset * 3
        red, green, blue = raster.pixels[position : position + 3]
        red_level = (red * 7 + 127) // 255
        green_level = (green * 7 + 127) // 255
        blue_level = (blue * 3 + 127) // 255
        output[offset] = (red_level << 5) | (green_level << 2) | blue_level
    return bytes(output)


def composite_indices_to_bits(
    image: IndexedGif,
    *,
    bit_width: int,
) -> bytes:
    """Expand four-bit GIF palette indices into one row-major Mode-6 stream."""

    expected_width = (bit_width + 3) // 4
    if image.width != expected_width:
        raise IndexedGifError(
            f"Composite GIF width must be exactly {expected_width} pixels."
        )
    output = bytearray(bit_width * image.height)
    for y in range(image.height):
        for cell_x in range(image.width):
            pattern = image.pixels[y * image.width + cell_x]
            for part in range(4):
                bit = (pattern >> (3 - part)) & 1
                bit_x = cell_x * 4 + part
                if bit_x < bit_width:
                    output[y * bit_width + bit_x] = bit
                elif bit:
                    raise IndexedGifError(
                        f"Composite GIF pixel ({cell_x}, {y}) sets padding bits "
                        "outside this resource's editable width."
                    )
    return bytes(output)


def editable_image_analyses(archive: DatArchive) -> tuple[ResourceAnalysis, ...]:
    """Return every image the Composite editor can edit, in DAT index order."""

    return tuple(
        analysis
        for analysis in archive.analyses
        if analysis.image is not None and analysis.image.bits in (1, 4)
    )


def resource_choice_label(
    analysis: ResourceAnalysis,
    position: int,
    total: int,
) -> str:
    """Build a unique, readable label for the editor's image navigator."""

    assert analysis.image is not None
    image = analysis.image
    return (
        f"{position + 1} of {total}  |  Resource {analysis.resource.resource_id} "
        f"(index {analysis.resource.index})  |  {image.width}×{image.height}  |  {image.bits}-bit"
    )


def sidecar_resource_ids_lost_by_replacement(
    existing: CompositeProject,
    replacement: CompositeProject,
) -> tuple[int, ...]:
    """Return resource IDs an unrelated Save-As replacement would discard.

    Normal saves to an already opened project are intentionally whole-file
    rewrites. This helper protects the different case where a new project is
    pointed at an existing sidecar without opening that sidecar first.
    """

    existing_source = (
        existing.source_size,
        existing.source_sha256,
    )
    replacement_source = (
        replacement.source_size,
        replacement.source_sha256,
    )
    if existing_source != replacement_source:
        raise CompositeProjectError(
            "The existing sidecar belongs to a different source DAT."
        )
    missing_indices = sorted(set(existing.edits) - set(replacement.edits))
    return tuple(existing.edits[index].resource_id for index in missing_indices)


def composite_cell_mode6_columns(edit: CompositeEdit, cell_x: int) -> tuple[int, ...]:
    """Return every real mode-6 bit column covered by one composite cell."""

    edit.validate()
    start = cell_x * 4
    if start < 0 or start >= edit.bit_width:
        return ()
    return tuple(range(start, min(start + 4, edit.bit_width)))


def composite_cell_source_columns(edit: CompositeEdit, cell_x: int) -> tuple[int, ...]:
    """Map a composite cell to all affected Prince source-pixel columns."""

    divisor = 1 if edit.source_depth == 1 else 2
    return tuple(
        dict.fromkeys(
            bit_x // divisor
            for bit_x in composite_cell_mode6_columns(edit, cell_x)
        )
    )


def viewport_source_bounds(
    raster_width: int,
    raster_height: int,
    scale: int,
    visible_left: float,
    visible_top: float,
    visible_right: float,
    visible_bottom: float,
    *,
    origin: tuple[int, int] = (10, 10),
    margin: int = 1,
) -> tuple[int, int, int, int]:
    """Return the source-pixel rectangle needed for a zoomed canvas viewport.

    Bounds use the usual half-open convention. The small source-pixel margin
    prevents a blank seam while the canvas scrolls between redraws.
    """

    if raster_width < 0 or raster_height < 0:
        raise ValueError("Raster dimensions cannot be negative.")
    if scale < 1:
        raise ValueError("Viewport scale must be at least one.")
    margin = max(0, int(margin))
    left = floor((visible_left - origin[0]) / scale) - margin
    top = floor((visible_top - origin[1]) / scale) - margin
    right = ceil((visible_right - origin[0]) / scale) + margin
    bottom = ceil((visible_bottom - origin[1]) / scale) + margin
    return (
        max(0, min(raster_width, left)),
        max(0, min(raster_height, top)),
        max(0, min(raster_width, right)),
        max(0, min(raster_height, bottom)),
    )


class RasterPane(ttk.LabelFrame):
    """Small scrollable raster panel that retains its Tk photo."""

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent, text=title, padding=4)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self,
            background="#20252b",
            highlightthickness=0,
            cursor="crosshair",
            width=300,
            height=205,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll_y = ttk.Scrollbar(
            self,
            orient=tk.VERTICAL,
            command=self.canvas.yview,
        )
        self.scroll_y.grid(row=0, column=1, sticky="ns")
        self.scroll_x = ttk.Scrollbar(
            self,
            orient=tk.HORIZONTAL,
            command=self.canvas.xview,
        )
        self.scroll_x.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(
            yscrollcommand=self.scroll_y.set,
            xscrollcommand=self.scroll_x.set,
        )
        self.photo: tk.PhotoImage | None = None
        self.raster: RenderedRaster | None = None
        self.origin = (10, 10)
        self.scale = 1
        self.x_zoom = 1
        self.x_subsample = 1

    def _x_edge(self, column: int) -> int:
        """Canvas x coordinate for a raster-column boundary after scaling."""

        numerator = column * self.scale * self.x_zoom
        return self.origin[0] + (numerator + self.x_subsample - 1) // self.x_subsample

    def _y_edge(self, row: int) -> int:
        return self.origin[1] + row * self.scale

    def clear(self, message: str = "No image selected") -> None:
        self.canvas.delete("all")
        self.photo = None
        self.raster = None
        self.canvas.create_text(
            150,
            95,
            text=message,
            fill="#d7dde4",
            width=255,
            justify=tk.CENTER,
        )
        self.canvas.configure(scrollregion=(0, 0, 310, 210))

    def show(
        self,
        raster: RenderedRaster,
        *,
        scale: int = 1,
        x_zoom: int = 1,
        x_subsample: int = 1,
        cell_grid: bool = False,
    ) -> None:
        if raster.channels != 3:
            raise ValueError("RasterPane expects RGB pixels.")
        self.canvas.delete("all")
        self.raster = raster
        self.scale = max(1, int(scale))
        self.x_zoom = max(1, int(x_zoom))
        self.x_subsample = max(1, int(x_subsample))
        ppm = f"P6\n{raster.width} {raster.height}\n255\n".encode("ascii") + raster.pixels
        photo = tk.PhotoImage(data=ppm, format="PPM")
        zoom_x = self.scale * self.x_zoom
        zoom_y = self.scale
        if zoom_x > 1 or zoom_y > 1:
            photo = photo.zoom(zoom_x, zoom_y)
        if self.x_subsample > 1:
            # Zoom first so even zoom levels preserve every narrow mode-6 bit.
            # At 1x, two half-width bits necessarily share one display pixel.
            photo = photo.subsample(self.x_subsample, 1)
        self.photo = photo
        x, y = self.origin
        self.canvas.create_image(x, y, image=photo, anchor=tk.NW, tags=("raster",))
        width = photo.width()
        height = photo.height()
        if cell_grid:
            for gx in dict.fromkeys(
                self._x_edge(column) for column in range(raster.width + 1)
            ):
                self.canvas.create_line(gx, y, gx, y + height, fill="#59636e", tags=("grid",))
            for gy in dict.fromkeys(
                self._y_edge(row) for row in range(raster.height + 1)
            ):
                self.canvas.create_line(x, gy, x + width, gy, fill="#59636e", tags=("grid",))
        self.canvas.configure(scrollregion=(0, 0, x + width + 10, y + height + 10))

    def clear_highlight(self) -> None:
        self.canvas.delete("hover")

    def highlight_cells(self, cells: Iterable[tuple[int, int]]) -> None:
        """Outline raster cells without changing the image or its grid."""

        self.clear_highlight()
        if self.raster is None:
            return
        valid = sorted(
            {
                (column, row)
                for column, row in cells
                if 0 <= column < self.raster.width and 0 <= row < self.raster.height
            }
        )
        for column, row in valid:
            left = self._x_edge(column)
            right = self._x_edge(column + 1)
            top = self._y_edge(row)
            bottom = self._y_edge(row + 1)
            if right <= left or bottom <= top:
                continue
            # A dark outer stroke keeps the yellow locator visible over every
            # adapter color. A center dot marks roomy cells without hiding them.
            minimum_size = min(right - left, bottom - top)
            outer_width = 3 if minimum_size >= 8 else 2 if minimum_size >= 4 else 1
            self.canvas.create_rectangle(
                left,
                top,
                max(left + 1, right - 1),
                max(top + 1, bottom - 1),
                outline="#101418",
                width=outer_width,
                tags=("hover",),
            )
            self.canvas.create_rectangle(
                left,
                top,
                max(left + 1, right - 1),
                max(top + 1, bottom - 1),
                outline="#FFD740",
                width=1,
                tags=("hover",),
            )
            if right - left >= 6 and bottom - top >= 6:
                center_x = (left + right) / 2
                center_y = (top + bottom) / 2
                self.canvas.create_oval(
                    center_x - 1.5,
                    center_y - 1.5,
                    center_x + 1.5,
                    center_y + 1.5,
                    fill="#FFD740",
                    outline="#101418",
                    tags=("hover",),
                )
        self.canvas.tag_raise("hover")

    def local_coordinates(self, event: tk.Event) -> tuple[float, float]:
        return (
            self.canvas.canvasx(event.x) - self.origin[0],
            self.canvas.canvasy(event.y) - self.origin[1],
        )

    def raster_coordinates(self, event: tk.Event) -> tuple[int, int] | None:
        """Map a canvas event to the visible raster cell under the pointer.

        The binary search follows the same rounded boundaries used to draw the
        grid, which keeps direct Mode-6 editing aligned at odd zoom levels.
        """

        if self.raster is None:
            return None
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        if not (
            self._x_edge(0) <= canvas_x < self._x_edge(self.raster.width)
            and self._y_edge(0) <= canvas_y < self._y_edge(self.raster.height)
        ):
            return None

        low = 0
        high = self.raster.width
        while low < high:
            middle = (low + high) // 2
            if canvas_x < self._x_edge(middle + 1):
                high = middle
            else:
                low = middle + 1
        row = int((canvas_y - self.origin[1]) // self.scale)
        if 0 <= low < self.raster.width and 0 <= row < self.raster.height:
            return low, row
        return None


class ViewportRasterPane(RasterPane):
    """Uniformly zoomed raster pane that only materializes visible pixels.

    A 640x200 preview at 20x has a 12,800x4,000 logical canvas, but its Tk
    image stays near the size of the viewport instead of allocating that full
    51.2-million-pixel frame.
    """

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent, title)
        self._viewport_after: str | None = None
        self._pending_center: tuple[float, float] | None = None
        self._rendered_source_bounds: tuple[int, int, int, int] | None = None
        self.cell_grid = False
        self.scroll_x.configure(command=self._xview)
        self.scroll_y.configure(command=self._yview)
        self.canvas.bind("<Configure>", self._viewport_configured, add="+")
        self.canvas.bind("<MouseWheel>", self._vertical_wheel, add="+")
        self.canvas.bind("<Shift-MouseWheel>", self._horizontal_wheel, add="+")
        self.canvas.bind("<Button-4>", self._vertical_wheel, add="+")
        self.canvas.bind("<Button-5>", self._vertical_wheel, add="+")
        self.canvas.bind("<Shift-Button-4>", self._horizontal_wheel, add="+")
        self.canvas.bind("<Shift-Button-5>", self._horizontal_wheel, add="+")

    def _cancel_viewport_redraw(self) -> None:
        if self._viewport_after is None:
            return
        try:
            self.after_cancel(self._viewport_after)
        except tk.TclError:
            pass
        self._viewport_after = None

    def clear(self, message: str = "No image selected") -> None:
        self._cancel_viewport_redraw()
        self._pending_center = None
        self._rendered_source_bounds = None
        self.cell_grid = False
        super().clear(message)
        self.canvas.xview_moveto(0.0)
        self.canvas.yview_moveto(0.0)

    def _visible_source_center(self) -> tuple[float, float] | None:
        raster = self.raster
        if raster is None:
            return None
        view_width = max(1, self.canvas.winfo_width())
        view_height = max(1, self.canvas.winfo_height())
        left = max(0.0, (self.canvas.canvasx(0) - self.origin[0]) / self.scale)
        top = max(0.0, (self.canvas.canvasy(0) - self.origin[1]) / self.scale)
        right = min(
            float(raster.width),
            (self.canvas.canvasx(view_width) - self.origin[0]) / self.scale,
        )
        bottom = min(
            float(raster.height),
            (self.canvas.canvasy(view_height) - self.origin[1]) / self.scale,
        )
        if right <= left or bottom <= top:
            return raster.width / 2.0, raster.height / 2.0
        return (left + right) / 2.0, (top + bottom) / 2.0

    def show(
        self,
        raster: RenderedRaster,
        *,
        scale: int = 1,
        x_zoom: int = 1,
        x_subsample: int = 1,
        cell_grid: bool = False,
    ) -> None:
        if raster.channels != 3:
            raise ValueError("ViewportRasterPane expects RGB pixels.")
        if x_zoom != 1 or x_subsample != 1:
            raise ValueError("ViewportRasterPane supports uniform zoom only.")
        old_center = self._visible_source_center()
        self._cancel_viewport_redraw()
        self.canvas.delete("all")
        self.photo = None
        self.raster = raster
        self.scale = max(1, int(scale))
        self.x_zoom = 1
        self.x_subsample = 1
        self.cell_grid = bool(cell_grid)
        self._rendered_source_bounds = None
        self._pending_center = old_center
        x, y = self.origin
        self.canvas.configure(
            scrollregion=(
                0,
                0,
                x + raster.width * self.scale + 10,
                y + raster.height * self.scale + 10,
            )
        )
        self._draw_grid()
        if old_center is None:
            self.canvas.xview_moveto(0.0)
            self.canvas.yview_moveto(0.0)
        self._schedule_viewport_redraw()

    def _draw_grid(self) -> None:
        """Draw logical cell boundaries without expanding the source image."""

        self.canvas.delete("grid")
        if not self.cell_grid or self.raster is None:
            return
        x, y = self.origin
        width = self._x_edge(self.raster.width) - x
        height = self._y_edge(self.raster.height) - y
        for gx in dict.fromkeys(
            self._x_edge(column) for column in range(self.raster.width + 1)
        ):
            self.canvas.create_line(
                gx,
                y,
                gx,
                y + height,
                fill="#59636e",
                tags=("grid",),
            )
        for gy in dict.fromkeys(
            self._y_edge(row) for row in range(self.raster.height + 1)
        ):
            self.canvas.create_line(
                x,
                gy,
                x + width,
                gy,
                fill="#59636e",
                tags=("grid",),
            )

    def _schedule_viewport_redraw(self) -> None:
        if self.raster is None or self._viewport_after is not None:
            return
        self._viewport_after = self.after_idle(self._redraw_viewport)

    def _viewport_configured(self, _event: tk.Event) -> None:
        self._schedule_viewport_redraw()

    def _xview(self, *args: object) -> None:
        self.canvas.xview(*args)
        self._schedule_viewport_redraw()

    def _yview(self, *args: object) -> None:
        self.canvas.yview(*args)
        self._schedule_viewport_redraw()

    @staticmethod
    def _wheel_units(event: tk.Event) -> int:
        delta = int(getattr(event, "delta", 0))
        if delta:
            return -1 if delta > 0 else 1
        return -1 if int(getattr(event, "num", 5)) == 4 else 1

    def _vertical_wheel(self, event: tk.Event) -> str:
        self._yview("scroll", self._wheel_units(event) * 3, "units")
        return "break"

    def _horizontal_wheel(self, event: tk.Event) -> str:
        self._xview("scroll", self._wheel_units(event) * 3, "units")
        return "break"

    def _center_pending_view(self) -> None:
        center = self._pending_center
        self._pending_center = None
        if center is None or self.raster is None:
            return
        view_width = max(1, self.canvas.winfo_width())
        view_height = max(1, self.canvas.winfo_height())
        scroll_width = self.origin[0] + self.raster.width * self.scale + 10
        scroll_height = self.origin[1] + self.raster.height * self.scale + 10
        desired_left = self.origin[0] + center[0] * self.scale - view_width / 2
        desired_top = self.origin[1] + center[1] * self.scale - view_height / 2
        desired_left = max(0.0, min(max(0, scroll_width - view_width), desired_left))
        desired_top = max(0.0, min(max(0, scroll_height - view_height), desired_top))
        self.canvas.xview_moveto(desired_left / max(1, scroll_width))
        self.canvas.yview_moveto(desired_top / max(1, scroll_height))

    def _redraw_viewport(self) -> None:
        self._viewport_after = None
        raster = self.raster
        if raster is None:
            return
        self._center_pending_view()
        view_width = max(1, self.canvas.winfo_width())
        view_height = max(1, self.canvas.winfo_height())
        bounds = viewport_source_bounds(
            raster.width,
            raster.height,
            self.scale,
            self.canvas.canvasx(0),
            self.canvas.canvasy(0),
            self.canvas.canvasx(view_width),
            self.canvas.canvasy(view_height),
            origin=self.origin,
        )
        if bounds == self._rendered_source_bounds:
            return
        self._rendered_source_bounds = bounds
        left, top, right, bottom = bounds
        self.canvas.delete("raster")
        self.photo = None
        if right <= left or bottom <= top:
            return

        row_bytes = raster.width * 3
        crop_width = right - left
        crop_height = bottom - top
        pixel_rows = (
            raster.pixels[
                row * row_bytes + left * 3 : row * row_bytes + right * 3
            ]
            for row in range(top, bottom)
        )
        ppm = (
            f"P6\n{crop_width} {crop_height}\n255\n".encode("ascii")
            + b"".join(pixel_rows)
        )
        photo = tk.PhotoImage(data=ppm, format="PPM")
        if self.scale > 1:
            photo = photo.zoom(self.scale, self.scale)
        self.photo = photo
        self.canvas.create_image(
            self.origin[0] + left * self.scale,
            self.origin[1] + top * self.scale,
            image=photo,
            anchor=tk.NW,
            tags=("raster",),
        )
        self.canvas.tag_raise("grid")
        self.canvas.tag_raise("hover")


class ComparisonWindow(tk.Toplevel):
    """Two display modes, sourced from linked room archives when applicable."""

    def __init__(
        self,
        parent: tk.Misc,
        context: ArchiveContext,
        analysis: ResourceAnalysis | None,
        on_close: Callable[["ComparisonWindow"], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        self.analysis = analysis
        self.on_close_callback = on_close
        self.title(
            "Linked room-archive comparison"
            if context.is_room_set
            else "Side-by-side display comparison"
        )
        self.geometry("1180x640")
        self.minsize(760, 440)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.left_var = tk.StringVar(value="VGA")
        self.right_var = tk.StringVar(value="CGA" if context.is_room_set else "EGA")
        self.zoom_var = tk.StringVar(value="Fit")
        self.status_var = tk.StringVar()

        controls = ttk.Frame(self, padding=9)
        controls.pack(fill=tk.X)
        ttk.Label(controls, text="Left mode:").pack(side=tk.LEFT)
        left_box = ttk.Combobox(
            controls,
            textvariable=self.left_var,
            state="readonly",
            values=COMPARISON_MODE_LABELS,
            width=20,
        )
        left_box.pack(side=tk.LEFT, padx=(6, 18))
        ttk.Label(controls, text="Right mode:").pack(side=tk.LEFT)
        right_box = ttk.Combobox(
            controls,
            textvariable=self.right_var,
            state="readonly",
            values=COMPARISON_MODE_LABELS,
            width=20,
        )
        right_box.pack(side=tk.LEFT, padx=(6, 18))
        ttk.Label(controls, text="Zoom:").pack(side=tk.LEFT)
        zoom = ttk.Combobox(
            controls,
            textvariable=self.zoom_var,
            state="readonly",
            values=("Fit", "1x", "2x", "3x", "4x", "6x", "8x"),
            width=7,
        )
        zoom.pack(side=tk.LEFT, padx=(6, 0))
        left_box.bind("<<ComboboxSelected>>", lambda _event: self.render())
        right_box.bind("<<ComboboxSelected>>", lambda _event: self.render())
        zoom.bind("<<ComboboxSelected>>", lambda _event: self.render())

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=9, pady=(0, 8))
        self.left_pane = RasterPane(body, "VGA")
        self.right_pane = RasterPane(body, self.right_var.get())
        body.add(self.left_pane, weight=1)
        body.add(self.right_pane, weight=1)
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=6).pack(
            fill=tk.X, side=tk.BOTTOM
        )
        self.bind("<Configure>", self._on_configure)
        self._render_after: str | None = None
        self.render()

    def set_analysis(self, analysis: ResourceAnalysis | None) -> None:
        self.analysis = analysis
        self.render()

    def _scale_for(
        self,
        raster: RenderedRaster,
        pane: RasterPane,
        x_zoom: int,
        x_subsample: int,
    ) -> int:
        if self.zoom_var.get() != "Fit":
            return max(1, int(self.zoom_var.get().rstrip("x")))
        width = max(1, pane.canvas.winfo_width() - 25)
        height = max(1, pane.canvas.winfo_height() - 25)
        display_width = max(1, (raster.width * x_zoom + x_subsample - 1) // x_subsample)
        return max(1, min(12, width // display_width, height // raster.height))

    def render(self) -> None:
        if self.analysis is None:
            self.left_pane.clear("Select a resource in the main window.")
            self.right_pane.clear("Select a resource in the main window.")
            self.status_var.set("No resource selected")
            return
        resource_id = self.analysis.resource.resource_id
        modes = (
            COMPARISON_LABEL_TO_MODE[self.left_var.get()],
            COMPARISON_LABEL_TO_MODE[self.right_var.get()],
        )
        panes = (self.left_pane, self.right_pane)
        labels = (self.left_var.get(), self.right_var.get())
        summaries: list[str] = []
        for mode, pane, label in zip(modes, panes, labels):
            resolved = self.context.analysis_for_display_mode(mode, resource_id)
            if resolved is None:
                source = self.context.source_description(mode)
                pane.configure(text=f"{label} — {source}")
                pane.clear(f"Resource {resource_id} is unavailable in\n{source}.")
                summaries.append(f"{label}: unavailable")
                continue
            archive, analysis = resolved
            if analysis.image is None:
                pane.configure(text=f"{label} — {archive.path.name} (read-only)")
                pane.clear(f"Resource {resource_id} is not an image in\n{archive.path.name}.")
                summaries.append(f"{label}: not an image")
                continue
            image = analysis.image
            hardware = hardware_palette_for_resource(archive, analysis.resource)
            raster, presentation_mode = render_comparison_mode(image, mode, hardware)
            factors = display_horizontal_factors(presentation_mode, image.bits)
            pane.configure(text=f"{label} — {archive.path.name} (read-only)")
            pane.show(
                raster,
                scale=self._scale_for(raster, pane, *factors),
                x_zoom=factors[0],
                x_subsample=factors[1],
            )
            display_width = normalized_display_width(
                raster.width, presentation_mode, image.bits
            )
            summaries.append(
                f"{label}: {archive.path.name} {image.width}×{image.height} → "
                f"{display_width} logical px"
            )
        self.status_var.set(f"Resource {resource_id} • " + " • ".join(summaries))

    def _on_configure(self, _event: tk.Event) -> None:
        if self.zoom_var.get() != "Fit":
            return
        if self._render_after is not None:
            self.after_cancel(self._render_after)
        self._render_after = self.after(120, self._render_after_resize)

    def _render_after_resize(self) -> None:
        self._render_after = None
        self.render()

    def close(self) -> None:
        if self.on_close_callback is not None:
            self.on_close_callback(self)
        self.destroy()


@dataclass
class EditAction:
    resource_index: int
    changes: dict[int, tuple[int, int]]
    phase_before: int | None = None
    phase_after: int | None = None
    variant_phase: int | None = None
    variants_before: dict[int, bytes | None] = field(default_factory=dict)
    variants_after: dict[int, bytes | None] = field(default_factory=dict)
    enabled_before: tuple[int, ...] | None = None
    enabled_after: tuple[int, ...] | None = None
    fallback_before: int | None = None
    fallback_after: int | None = None
    mask_locked_before: bool | None = None
    mask_locked_after: bool | None = None
    mask_authored_before: bool | None = None
    mask_authored_after: bool | None = None
    source_zero_mask_before: bytes | None = None
    source_zero_mask_after: bytes | None = None
    mask_reference_bits_before: bytes | None = None
    mask_reference_bits_after: bytes | None = None


@dataclass
class BulkGifAction:
    """One undo record for an archive-wide, all-or-nothing GIF import."""

    edits_before: dict[int, CompositeEdit | None]
    edits_after: dict[int, CompositeEdit]
    file_count: int


@dataclass(frozen=True)
class ConverterSource:
    mode: str
    description: str
    raster: RenderedRaster
    zero_mask: tuple[bool, ...]


class CompositeConverterDialog(tk.Toplevel):
    """Modal converter for fixed-palette cells or simulated NTSC output."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        resource_id: int,
        sources: dict[str, ConverterSource],
        current_bits: bytes,
        bit_width: int,
        height: int,
        profile: str,
        initial_phase: int,
        enabled_phases: tuple[int, ...] = (),
        selectable_phases: tuple[int, ...] = PHASES,
        current_phase_bits: dict[int, bytes] | None = None,
        mask_locked: bool = False,
        target_locked_bits: tuple[int, ...] | None = None,
        on_apply: Callable[
            [ConversionResult, ConversionSettings, ConverterSource, str], bool
        ],
        on_apply_set: Callable[
            [dict[int, ConversionResult], ConversionSettings, ConverterSource, str], bool
        ]
        | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        if not sources:
            raise ValueError("The converter requires at least one adapter source.")
        self.resource_id = resource_id
        self.sources = sources
        self.current_bits = bytes(current_bits)
        self.bit_width = bit_width
        self.height = height
        self.profile = profile
        self.enabled_phases = tuple(sorted(set(enabled_phases or (initial_phase,))))
        if any(phase not in PHASES for phase in self.enabled_phases):
            raise ValueError("Enabled carrier phases must be between 0 and 3.")
        self.selectable_phases = tuple(sorted(set(selectable_phases)))
        if (
            not self.selectable_phases
            or any(phase not in PHASES for phase in self.selectable_phases)
            or initial_phase not in self.selectable_phases
        ):
            raise ValueError(
                "Selectable carrier phases must include the initial phase and stay between 0 and 3."
            )
        self.default_phase = initial_phase
        self.current_phase_bits = {
            int(phase): bytes(bits)
            for phase, bits in (current_phase_bits or {}).items()
        }
        self.mask_locked = bool(mask_locked)
        self.target_locked_bits = (
            tuple(int(value) for value in target_locked_bits)
            if target_locked_bits is not None
            else None
        )
        if self.target_locked_bits is not None:
            if len(self.target_locked_bits) != self.bit_width * self.height:
                raise ValueError("Target locked-bit dimensions are inconsistent.")
            if any(value not in (-1, 0, 1) for value in self.target_locked_bits):
                raise ValueError("Target locked bits must contain only -1, 0, or 1.")
        self.on_apply = on_apply
        self.on_apply_set = on_apply_set
        self.on_close_callback = on_close
        self._closing = False
        self._initializing = True
        self._generation = 0
        self._debounce_after: str | None = None
        self._poll_after: str | None = None
        self._cancel_event: threading.Event | None = None
        self._results: Queue[
            tuple[
                int,
                str,
                ConversionResult | dict[int, ConversionResult] | None,
                BaseException | None,
            ]
        ] = Queue()
        self._worker_progress: dict[int, tuple[int, int]] = {}
        self._latest_result: ConversionResult | None = None
        self._result_settings: ConversionSettings | None = None
        self._result_mode: str | None = None
        self._current_rasters: dict[int | str, RenderedRaster] = {}
        self._current_simple_rasters: dict[int | str, RenderedRaster] = {}
        self._phase_set_settings: ConversionSettings | None = None
        self._phase_set_source: ConverterSource | None = None

        first_mode = next(
            (mode for mode in ("vga", "ega", "cga") if mode in sources),
            next(iter(sources)),
        )
        self.source_var = tk.StringVar(value=first_mode)
        self.conversion_mode_var = tk.StringVar(value=CONVERSION_SIMULATED_NTSC)
        self.conversion_mode_detail_var = tk.StringVar()
        self.dither_var = tk.StringVar(value=DITHER_FLOYD_STEINBERG)
        self.dither_amount_var = tk.IntVar(value=70)
        self.serpentine_var = tk.BooleanVar(value=True)
        self.bayer_var = tk.StringVar(value="4x4")
        self.brightness_var = tk.IntVar(value=0)
        self.contrast_var = tk.IntVar(value=0)
        self.saturation_var = tk.IntVar(value=100)
        self.gamma_var = tk.IntVar(value=100)
        self.color_emphasis_var = tk.IntVar(value=65)
        self.detail_var = tk.IntVar(value=55)
        self.quality_var = tk.StringVar(value=QUALITY_FAST)
        self.phase_var = tk.StringVar(value=str(initial_phase))
        self._last_single_phase = initial_phase
        self.preserve_zero_var = tk.BooleanVar(value=True)
        self.preview_var = tk.StringVar(value="converted")
        self.preview_zoom_var = tk.StringVar(value="1x")
        self.preview_heading_var = tk.StringVar(value="Simulated NTSC preview:")
        self.phase_note_var = tk.StringVar(
            value=(
                "A selected phase targets one variant. All minimizes one shared pattern "
                "over only this resource's enabled runtime phases."
            )
        )
        self.source_detail_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Preparing conversion…")

        self.title(f"Convert resource {resource_id} to Composite")
        self.geometry("1260x820")
        self.minsize(980, 680)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self._build_ui()
        self._initializing = False
        self._update_source_detail()
        self._update_conversion_mode_detail()
        self._update_conversion_control_states()
        self._show_current_preview()
        self._settings_changed()
        self.after_idle(self.grab_set)

    def _build_ui(self) -> None:
        banner = ttk.Frame(self, padding=(10, 9, 10, 7))
        banner.pack(fill=tk.X)
        profile_label = COMPOSITE_PROFILE_LABELS[self.profile]
        ttk.Label(
            banner,
            text=(
                "Composite conversion • fixed palette, beam NTSC, or exact "
                f"{self.bit_width}×{self.height} selected/reachable-phase NTSC"
            ),
            font=("TkDefaultFont", 10, "bold"),
        ).pack(side=tk.LEFT)
        ttk.Label(
            banner,
            text=f"{profile_label} • resource {self.resource_id}",
            foreground="#44515f",
        ).pack(side=tk.RIGHT)

        body = ttk.Frame(self, padding=(10, 0, 10, 8))
        body.pack(fill=tk.BOTH, expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)

        controls = ttk.Frame(body, width=350)
        controls.grid(row=0, column=0, sticky="nsw", padx=(0, 10))
        controls.grid_propagate(True)

        source_group = ttk.LabelFrame(controls, text="Source", padding=(8, 6))
        source_group.pack(fill=tk.X, pady=(0, 7))
        source_row = ttk.Frame(source_group)
        source_row.pack(fill=tk.X)
        ttk.Label(source_row, text="Source:").pack(side=tk.LEFT, padx=(0, 7))
        for mode in ("vga", "ega", "cga"):
            button = ttk.Radiobutton(
                source_row,
                text=mode.upper(),
                variable=self.source_var,
                value=mode,
                command=self._source_changed,
            )
            button.pack(side=tk.LEFT, padx=(0, 5))
            if mode not in self.sources:
                button.state(["disabled"])
        ttk.Label(
            source_group,
            textvariable=self.source_detail_var,
            foreground="#44515f",
            wraplength=320,
        ).pack(fill=tk.X, pady=(5, 0))

        mode_group = ttk.LabelFrame(
            controls,
            text="Conversion model",
            padding=(8, 6),
        )
        mode_group.pack(fill=tk.X, pady=(0, 7))
        mode_row = ttk.Frame(mode_group)
        mode_row.pack(fill=tk.X)
        for mode in CONVERSION_MODES:
            ttk.Radiobutton(
                mode_row,
                text=CONVERSION_MODE_LABELS[mode],
                variable=self.conversion_mode_var,
                value=mode,
                command=self._conversion_mode_changed,
            ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(
            mode_group,
            textvariable=self.conversion_mode_detail_var,
            foreground="#44515f",
            wraplength=320,
        ).pack(fill=tk.X, pady=(5, 0))

        dither_group = ttk.LabelFrame(controls, text="Dither", padding=(8, 5))
        dither_group.pack(fill=tk.X, pady=(0, 7))
        method_row = ttk.Frame(dither_group)
        method_row.pack(fill=tk.X)
        self.dither_method_buttons: list[ttk.Radiobutton] = []
        for value, label in (
            (DITHER_NONE, "None"),
            (DITHER_FLOYD_STEINBERG, "Error diffusion"),
            (DITHER_BAYER, "Bayer"),
        ):
            button = ttk.Radiobutton(
                method_row,
                text=label,
                variable=self.dither_var,
                value=value,
                command=self._settings_changed,
            )
            button.pack(side=tk.LEFT, padx=(0, 6))
            self.dither_method_buttons.append(button)
        self.dither_amount_scale = self._scale(
            dither_group,
            "Amount",
            self.dither_amount_var,
            0,
            100,
        )
        options = ttk.Frame(dither_group)
        options.pack(fill=tk.X, pady=(1, 0))
        self.serpentine_check = ttk.Checkbutton(
            options,
            text="Serpentine diffusion",
            variable=self.serpentine_var,
            command=self._settings_changed,
        )
        self.serpentine_check.pack(side=tk.LEFT)
        ttk.Label(options, text="Bayer:").pack(side=tk.LEFT, padx=(10, 4))
        self.bayer_combo = ttk.Combobox(
            options,
            textvariable=self.bayer_var,
            values=("2x2", "4x4", "8x8"),
            state="readonly",
            width=5,
        )
        self.bayer_combo.pack(side=tk.LEFT)
        self.bayer_combo.bind("<<ComboboxSelected>>", self._settings_changed)

        input_group = ttk.LabelFrame(controls, text="Input adjustments", padding=(8, 5))
        input_group.pack(fill=tk.X, pady=(0, 7))
        self.input_adjustment_scales = (
            self._scale(input_group, "Brightness", self.brightness_var, -100, 100),
            self._scale(input_group, "Contrast", self.contrast_var, -100, 100),
            self._scale(input_group, "Saturation", self.saturation_var, 0, 200),
            self._scale(input_group, "Gamma ×100", self.gamma_var, 50, 250),
        )

        optimization = ttk.LabelFrame(controls, text="Signal optimization", padding=(8, 5))
        optimization.pack(fill=tk.X, pady=(0, 7))
        self.color_emphasis_scale = self._scale(
            optimization,
            "Color emphasis",
            self.color_emphasis_var,
            0,
            100,
        )
        self.detail_scale = self._scale(
            optimization,
            "Detail preservation",
            self.detail_var,
            0,
            100,
        )
        option_row = ttk.Frame(optimization)
        option_row.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(option_row, text="Quality:").pack(side=tk.LEFT)
        self.quality_combo = ttk.Combobox(
            option_row,
            textvariable=self.quality_var,
            values=(QUALITY_FAST, QUALITY_BALANCED, QUALITY_HIGH),
            state="readonly",
            width=10,
        )
        self.quality_combo.pack(side=tk.LEFT, padx=(5, 12))
        self.quality_combo.bind("<<ComboboxSelected>>", self._settings_changed)
        self.phase_label = ttk.Label(option_row, text="Carrier phase:")
        self.phase_label.pack(side=tk.LEFT)
        self.phase_spinbox = ttk.Spinbox(
            option_row,
            values=("0", "1", "2", "3", PHASE_ALL),
            wrap=True,
            textvariable=self.phase_var,
            width=4,
            command=self._phase_selection_changed,
        )
        self.phase_spinbox.pack(side=tk.LEFT, padx=(5, 0))
        self.phase_spinbox.bind("<Return>", self._phase_selection_changed)
        self.phase_spinbox.bind("<FocusOut>", self._phase_selection_changed)
        self.preserve_zero_check = ttk.Checkbutton(
            optimization,
            text="Preserve source index-zero background",
            variable=self.preserve_zero_var,
            command=self._settings_changed,
        )
        self.preserve_zero_check.pack(anchor=tk.W, pady=(5, 0))
        ttk.Label(
            optimization,
            textvariable=self.phase_note_var,
            foreground="#44515f",
            wraplength=320,
        ).pack(fill=tk.X, pady=(4, 0))

        actions = ttk.Frame(controls)
        actions.pack(fill=tk.X, pady=(2, 0))
        ttk.Button(actions, text="Reset", command=self.reset).pack(side=tk.LEFT)
        ttk.Button(actions, text="Cancel", command=self.close).pack(side=tk.RIGHT)
        self.convert_button = ttk.Button(actions, text="Convert", command=self._accept)
        self.convert_button.pack(side=tk.RIGHT, padx=(0, 6))
        self.convert_button.state(["disabled"])
        self.generate_set_button = ttk.Button(
            actions,
            text="Generate enabled phase set",
            command=self._generate_enabled_phase_set,
        )
        self.generate_set_button.pack(side=tk.RIGHT, padx=(0, 6))

        preview_slot = ttk.Frame(body)
        preview_slot.grid(row=0, column=1, sticky="nsew")
        preview_slot.rowconfigure(1, weight=1)
        preview_slot.columnconfigure(0, weight=1)
        preview_toolbar = ttk.Frame(preview_slot, padding=(4, 2, 4, 5))
        preview_toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(preview_toolbar, textvariable=self.preview_heading_var).pack(
            side=tk.LEFT, padx=(0, 7)
        )
        for value, label in (("converted", "Converted"), ("current", "Current edit")):
            ttk.Radiobutton(
                preview_toolbar,
                text=label,
                variable=self.preview_var,
                value=value,
                command=self._preview_choice_changed,
            ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(preview_toolbar, text="Zoom:").pack(side=tk.RIGHT, padx=(8, 4))
        preview_zoom = ttk.Combobox(
            preview_toolbar,
            textvariable=self.preview_zoom_var,
            values=CONVERTER_PREVIEW_ZOOM_VALUES,
            state="readonly",
            width=5,
        )
        preview_zoom.pack(side=tk.RIGHT)
        preview_zoom.bind("<<ComboboxSelected>>", self._preview_choice_changed)

        self.preview_pane = ViewportRasterPane(
            preview_slot,
            "Composite conversion preview",
        )
        self.preview_pane.grid(row=1, column=0, sticky="nsew")
        self.preview_pane.canvas.configure(cursor="arrow")

        ttk.Label(
            self,
            textvariable=self.status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=6,
        ).pack(fill=tk.X, side=tk.BOTTOM)

    def _scale(
        self,
        parent: tk.Misc,
        label: str,
        variable: tk.Variable,
        minimum: int,
        maximum: int,
    ) -> tk.Scale:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        ttk.Label(row, text=label, width=17, anchor=tk.W).pack(side=tk.LEFT)
        scale = tk.Scale(
            row,
            from_=minimum,
            to=maximum,
            orient=tk.HORIZONTAL,
            variable=variable,
            resolution=1,
            showvalue=True,
            length=190,
            command=self._settings_changed,
            highlightthickness=0,
        )
        scale.pack(side=tk.RIGHT, fill=tk.X, expand=True)
        return scale

    def _phase_selection(self) -> int | str:
        value = str(self.phase_var.get()).strip().lower()
        if value == PHASE_ALL:
            return PHASE_ALL
        try:
            phase = int(value)
        except ValueError as exc:
            raise ValueError("Carrier phase must be 0, 1, 2, 3, or all.") from exc
        if phase not in (0, 1, 2, 3):
            raise ValueError("Carrier phase must be 0, 1, 2, 3, or all.")
        selectable = getattr(self, "selectable_phases", PHASES)
        if phase not in selectable:
            allowed = ", ".join(str(item) for item in selectable)
            raise ValueError(
                f"This resource's phase policy permits only carrier phase(s) {allowed}."
            )
        return phase

    def _phase_selection_changed(self, *_args: object) -> None:
        try:
            phase = self._phase_selection()
        except (ValueError, tk.TclError) as exc:
            self.status_var.set(str(exc))
            return
        if phase != PHASE_ALL:
            self._last_single_phase = int(phase)
        self._settings_changed()

    def _settings(self) -> ConversionSettings:
        phase = self._phase_selection()
        return ConversionSettings(
            dither=self.dither_var.get(),
            dither_amount=int(self.dither_amount_var.get()),
            serpentine=bool(self.serpentine_var.get()),
            bayer_size=int(self.bayer_var.get().split("x", 1)[0]),
            brightness=int(self.brightness_var.get()),
            contrast=int(self.contrast_var.get()),
            saturation=int(self.saturation_var.get()),
            gamma=int(self.gamma_var.get()) / 100.0,
            color_emphasis=int(self.color_emphasis_var.get()),
            detail=int(self.detail_var.get()),
            quality=self.quality_var.get(),
            phase_offset=phase,
            all_phase_offsets=self.enabled_phases,
            preserve_zero=bool(self.preserve_zero_var.get()),
        )

    def _conversion_mode(self) -> str:
        mode = self.conversion_mode_var.get()
        if mode not in CONVERSION_MODES:
            raise ValueError(f"Unknown conversion model: {mode!r}.")
        return mode

    def _update_conversion_mode_detail(self) -> None:
        try:
            mode = self._conversion_mode()
        except ValueError:
            self.conversion_mode_detail_var.set("Select a conversion model.")
            return
        if mode == CONVERSION_SIMPLE_PALETTE:
            self.conversion_mode_detail_var.set(
                "Unbiased nearest RGB at the fixed 16-color rough palette. "
                "No dither, adjustments, detail/color bias, or signal search."
            )
            self.preview_heading_var.set("Simply Palette preview:")
            self.phase_label.configure(text="Carrier phase:")
            self.phase_note_var.set(
                "Phase rotates the fixed four-clock palette. All sums independent "
                f"fixed-palette errors over {_format_phase_set(self.enabled_phases)}."
            )
        elif mode == CONVERSION_SIMULATED_NTSC:
            self.conversion_mode_detail_var.set(
                "Full-width beam NTSC optimization with neighboring-bit artifacts "
                "and adjustable search bias."
            )
            self.preview_heading_var.set("Simulated NTSC preview:")
            self.phase_label.configure(text="Carrier phase:")
            self.phase_note_var.set(
                "All adds independent decoded errors over only "
                f"{_format_phase_set(self.enabled_phases)}; it never averages colors."
            )
        else:
            self.conversion_mode_detail_var.set(
                "Exact 2,048-state row optimization at every signal bit. Select "
                "one phase, or all to minimize summed absolute error across the "
                "enabled runtime phases."
            )
            self.preview_heading_var.set("Exhaustive NTSC preview:")
            self.phase_label.configure(text="Carrier phase:")
            self.phase_note_var.set(
                "All adds separate decoded errors for one universal pattern over "
                f"{_format_phase_set(self.enabled_phases)}. Generate enabled phase "
                "set instead solves each variant independently."
            )

    def _conversion_mode_changed(self) -> None:
        self._update_conversion_mode_detail()
        self._settings_changed()

    def _update_source_detail(self) -> None:
        source = self.sources.get(self.source_var.get())
        self.source_detail_var.set(
            source.description if source is not None else "Source is unavailable."
        )

    def _source_changed(self) -> None:
        self._update_source_detail()
        self._settings_changed()

    def _update_conversion_control_states(self) -> None:
        mode = self._conversion_mode()
        simple = mode == CONVERSION_SIMPLE_PALETTE
        exhaustive = mode == CONVERSION_EXHAUSTIVE
        dither_mode = self.dither_var.get()
        for button in self.dither_method_buttons:
            button.state(["disabled"] if simple else ["!disabled"])
        self.dither_amount_scale.configure(
            state=(
                tk.NORMAL
                if not simple and dither_mode != DITHER_NONE
                else tk.DISABLED
            )
        )
        self.serpentine_check.state(
            ["!disabled"]
            if not simple and dither_mode == DITHER_FLOYD_STEINBERG
            else ["disabled"]
        )
        self.bayer_combo.configure(
            state=(
                "readonly"
                if not simple and dither_mode == DITHER_BAYER
                else "disabled"
            )
        )
        for scale in self.input_adjustment_scales:
            scale.configure(state=tk.DISABLED if simple else tk.NORMAL)
        self.color_emphasis_scale.configure(
            state=tk.DISABLED if simple or exhaustive else tk.NORMAL
        )
        self.detail_scale.configure(
            state=tk.DISABLED if simple or exhaustive else tk.NORMAL
        )
        self.quality_combo.configure(
            state="disabled" if simple or exhaustive else "readonly"
        )
        selectable = tuple(
            str(phase) for phase in getattr(self, "selectable_phases", PHASES)
        )
        self.phase_spinbox.configure(
            values=selectable + (PHASE_ALL,),
            state="normal",
        )
        # A phase-aware mask lock is stronger than the dialog option and may
        # not be disabled for one conversion by accident.
        if getattr(self, "mask_locked", False):
            self.preserve_zero_var.set(True)
            self.preserve_zero_check.state(["disabled"])
        else:
            self.preserve_zero_check.state(["!disabled"])
        generate_set_button = getattr(self, "generate_set_button", None)
        if (
            exhaustive
            and getattr(self, "on_apply_set", None) is not None
            and getattr(self, "enabled_phases", ())
            and generate_set_button is not None
        ):
            generate_set_button.state(["!disabled"])
        elif generate_set_button is not None:
            generate_set_button.state(["disabled"])

    def _settings_changed(self, *_args: object) -> None:
        if self._initializing or self._closing:
            return
        try:
            mode = self._conversion_mode()
            self._update_conversion_control_states()
        except ValueError as exc:
            self.status_var.set(str(exc))
            return
        all_phases = str(self.phase_var.get()).strip().lower() == PHASE_ALL
        phase_text = _format_phase_set(self.enabled_phases)
        self._generation += 1
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._debounce_after is not None:
            self.after_cancel(self._debounce_after)
        self._latest_result = None
        self._result_settings = None
        self._result_mode = None
        self._phase_set_settings = None
        self._phase_set_source = None
        self.convert_button.state(["disabled"])
        if self.preview_var.get() == "current":
            self._show_current_preview()
        else:
            if mode == CONVERSION_SIMPLE_PALETTE:
                self.preview_pane.clear(
                    f"Mapping {(self.bit_width + 3) // 4}×{self.height} fixed-palette "
                    f"cells{' over ' + phase_text if all_phases else ''}…"
                )
            elif mode == CONVERSION_EXHAUSTIVE:
                self.preview_pane.clear(
                    f"Solving exact {self.bit_width}×{self.height} "
                    f"{phase_text + ' universal' if all_phases else 'selected-phase'} signal…"
                )
            else:
                self.preview_pane.clear(
                    f"Optimizing {self.bit_width}×{self.height} decoded Composite "
                    f"output{' over ' + phase_text if all_phases else ''}…"
                )
        if mode == CONVERSION_SIMPLE_PALETTE:
            status = (
                f"Controls changed; fixed-palette {phase_text} universal conversion queued…"
                if all_phases
                else "Controls changed; fixed-palette conversion queued…"
            )
        elif mode == CONVERSION_EXHAUSTIVE:
            status = (
                f"Controls changed; exact {phase_text} universal row conversion queued…"
                if all_phases
                else "Controls changed; exact selected-phase row conversion queued…"
            )
        else:
            status = (
                f"Controls changed; {phase_text} universal beam conversion queued…"
                if all_phases
                else "Controls changed; full-width signal conversion queued…"
            )
        self.status_var.set(status)
        self._debounce_after = self.after(240, self._start_conversion)

    def _generate_enabled_phase_set(self) -> None:
        """Solve every enabled phase independently in one background job."""

        if self.on_apply_set is None:
            self.status_var.set("This editor session does not accept phase-set conversions.")
            return
        try:
            if self._conversion_mode() != CONVERSION_EXHAUSTIVE:
                raise ValueError("Phase-set generation requires Exhaustive conversion.")
            base_settings = self._settings()
            source = self.sources[self.source_var.get()]
        except (KeyError, ValueError, tk.TclError) as exc:
            self.status_var.set(str(exc))
            return
        if not self.enabled_phases:
            self.status_var.set("Enable at least one phase in the main editor first.")
            return

        self._generation += 1
        generation = self._generation
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._debounce_after is not None:
            self.after_cancel(self._debounce_after)
            self._debounce_after = None
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._latest_result = None
        self._result_settings = None
        self._result_mode = None
        self._phase_set_settings = base_settings
        self._phase_set_source = source
        total_rows = self.height * len(self.enabled_phases)
        self._worker_progress[generation] = (0, total_rows)
        self.convert_button.state(["disabled"])
        self.generate_set_button.state(["disabled"])
        phase_text = ", ".join(f"P{phase}" for phase in self.enabled_phases)
        self.status_var.set(
            f"Generating independent Exhaustive variants {phase_text} from "
            f"{source.mode.upper()}…"
        )

        def worker() -> None:
            try:
                results: dict[int, ConversionResult] = {}
                for position, phase in enumerate(self.enabled_phases):
                    if cancel_event.is_set():
                        raise ConversionCancelled()
                    settings = replace(base_settings, phase_offset=phase)

                    def progress(done: int, _total: int, *, offset=position * self.height) -> None:
                        self._worker_progress[generation] = (offset + done, total_rows)

                    results[phase] = convert_raster_to_exhaustive(
                        source.raster,
                        self.bit_width,
                        self.height,
                        self.profile,
                        settings,
                        source_zero_mask=source.zero_mask,
                        target_locked_bits=self.target_locked_bits,
                        cancelled=cancel_event.is_set,
                        progress=progress,
                    )
            except BaseException as exc:  # delivered to Tk's thread
                self._results.put((generation, "phase-set", None, exc))
            else:
                self._worker_progress[generation] = (total_rows, total_rows)
                self._results.put((generation, "phase-set", results, None))

        threading.Thread(
            target=worker,
            name=f"composite-phase-set-{self.resource_id}-{generation}",
            daemon=True,
        ).start()
        self._ensure_polling()

    def _start_conversion(self) -> None:
        self._debounce_after = None
        if self._closing:
            return
        try:
            settings = self._settings()
            settings.validate()
            source = self.sources[self.source_var.get()]
            mode = self._conversion_mode()
        except (KeyError, ValueError, tk.TclError) as exc:
            self.status_var.set(f"Cannot start conversion: {exc}")
            return
        generation = self._generation
        self._phase_set_settings = None
        self._phase_set_source = None
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._worker_progress[generation] = (0, self.height)
        phase_text = _format_phase_set(resolved_phase_offsets(settings))
        if mode == CONVERSION_SIMPLE_PALETTE:
            self.status_var.set(
                f"Mapping {source.mode.upper()} to the fixed "
                f"{(self.bit_width + 3) // 4}×{self.height} palette at "
                f"{phase_text}{' universal objective' if settings.phase_offset == PHASE_ALL else ''}…"
            )
        elif mode == CONVERSION_EXHAUSTIVE:
            if settings.phase_offset == PHASE_ALL:
                self.status_var.set(
                    f"Exactly solving all {self.bit_width}×{self.height} signal bits "
                    f"from {source.mode.upper()} against reachable {phase_text}…"
                )
            else:
                self.status_var.set(
                    f"Exactly solving all {self.bit_width}×{self.height} signal bits "
                    f"from {source.mode.upper()} at carrier phase "
                    f"{settings.phase_offset}…"
                )
        else:
            objective = (
                f"reachable {phase_text} universal"
                if settings.phase_offset == PHASE_ALL
                else f"phase {settings.phase_offset}"
            )
            self.status_var.set(
                f"Optimizing actual {self.bit_width}×{self.height} signal from "
                f"{source.mode.upper()} at {objective} — "
                f"{settings.quality.title()} quality…"
            )

        def worker() -> None:
            try:
                progress = lambda done, total: self._worker_progress.__setitem__(
                    generation, (done, total)
                )
                if mode == CONVERSION_SIMPLE_PALETTE:
                    result = convert_raster_to_simple_palette(
                        source.raster,
                        self.bit_width,
                        self.height,
                        self.profile,
                        settings=settings,
                        source_zero_mask=source.zero_mask,
                        target_locked_bits=self.target_locked_bits,
                        preserve_zero=settings.preserve_zero,
                        cancelled=cancel_event.is_set,
                        progress=progress,
                    )
                elif mode == CONVERSION_EXHAUSTIVE:
                    result = convert_raster_to_exhaustive(
                        source.raster,
                        self.bit_width,
                        self.height,
                        self.profile,
                        settings,
                        source_zero_mask=source.zero_mask,
                        target_locked_bits=self.target_locked_bits,
                        cancelled=cancel_event.is_set,
                        progress=progress,
                    )
                else:
                    result = convert_raster_to_composite(
                        source.raster,
                        self.bit_width,
                        self.height,
                        self.profile,
                        settings,
                        source_zero_mask=source.zero_mask,
                        target_locked_bits=self.target_locked_bits,
                        cancelled=cancel_event.is_set,
                        progress=progress,
                    )
            except BaseException as exc:  # delivered to Tk's thread for display
                self._results.put((generation, mode, None, exc))
            else:
                self._results.put((generation, mode, result, None))

        threading.Thread(
            target=worker,
            name=f"composite-convert-{mode}-{self.resource_id}-{generation}",
            daemon=True,
        ).start()
        self._ensure_polling()

    def _ensure_polling(self) -> None:
        if self._poll_after is None and not self._closing:
            self._poll_after = self.after(90, self._poll_results)

    def _poll_results(self) -> None:
        self._poll_after = None
        if self._closing:
            return
        received_current = False
        while True:
            try:
                generation, mode, result, error = self._results.get_nowait()
            except Empty:
                break
            if generation != self._generation:
                continue
            received_current = True
            if isinstance(error, ConversionCancelled):
                if mode == "phase-set":
                    self.generate_set_button.state(["!disabled"])
                continue
            if error is not None:
                self.status_var.set(f"Conversion failed: {error}")
                self.preview_pane.clear(f"Conversion failed:\n{error}")
                if mode == "phase-set":
                    self.generate_set_button.state(["!disabled"])
                continue
            assert result is not None
            if mode == "phase-set":
                assert isinstance(result, dict)
                settings = self._phase_set_settings
                source = self._phase_set_source
                if settings is None or source is None or self.on_apply_set is None:
                    self.status_var.set("Phase-set result no longer matches this dialog.")
                    continue
                if self.on_apply_set(result, settings, source, CONVERSION_EXHAUSTIVE):
                    self.close()
                    return
                self.generate_set_button.state(["!disabled"])
                continue
            assert isinstance(result, ConversionResult)
            self._latest_result = result
            self._result_settings = self._settings()
            self._result_mode = mode
            self.convert_button.state(["!disabled"])
            if self.preview_var.get() == "converted":
                self._show_raster(result.preview, "Converted")
            result_phases = _format_phase_set(
                resolved_phase_offsets(self._result_settings)
            )
            if mode == CONVERSION_SIMPLE_PALETTE:
                objective = (
                    f"universal over {result_phases}"
                    if self._result_settings.phase_offset == PHASE_ALL
                    else result_phases
                )
                self.status_var.set(
                    f"Ready: mapped fixed-palette cells at {objective} • palette "
                    f"RMSE {result.source_rmse:.1f} • click Convert to replace the "
                    "edited image."
                )
            elif mode == CONVERSION_EXHAUSTIVE:
                if self._result_settings.phase_offset == PHASE_ALL:
                    self.status_var.set(
                        f"Ready: exact {result.target_width}×{result.target_height} "
                        f"{result_phases} universal signal • reachable-phase RMSE "
                        f"{result.source_rmse:.1f} • click Convert to replace the "
                        "edited image."
                    )
                else:
                    self.status_var.set(
                        f"Ready: exact {result.target_width}×{result.target_height} "
                        f"selected-phase signal • source RMSE {result.source_rmse:.1f} • "
                        f"phase {self.phase_var.get()} • click Convert to replace the "
                        "edited image."
                    )
            else:
                objective = (
                    f"universal over {result_phases}"
                    if self._result_settings.phase_offset == PHASE_ALL
                    else result_phases
                )
                self.status_var.set(
                    f"Ready: optimized {result.target_width}×{result.target_height} "
                    f"decoded signal at {objective} • source RMSE "
                    f"{result.source_rmse:.1f} • click Convert to replace the edited image."
                )

        if not received_current:
            progress = self._worker_progress.get(self._generation)
            if progress is not None and progress[1]:
                done, total = progress
                if done:
                    if self._conversion_mode() == CONVERSION_SIMPLE_PALETTE:
                        self.status_var.set(
                            f"Mapping fixed-palette cells… scanline {done} of {total}"
                        )
                    elif self._phase_set_settings is not None and self._latest_result is None:
                        self.status_var.set(
                            f"Generating enabled phase variants… scanline {done} of {total}"
                        )
                    elif self._conversion_mode() == CONVERSION_EXHAUSTIVE:
                        objective = (
                            f"{_format_phase_set(self.enabled_phases)} universal"
                            if str(self.phase_var.get()).strip().lower() == PHASE_ALL
                            else "selected-phase"
                        )
                        self.status_var.set(
                            f"Exact {objective} row solve… scanline {done} of {total}"
                        )
                    else:
                        phase_suffix = (
                            f" over {_format_phase_set(self.enabled_phases)}"
                            if str(self.phase_var.get()).strip().lower() == PHASE_ALL
                            else ""
                        )
                        self.status_var.set(
                            f"Optimizing actual {self.bit_width}×{self.height} signal"
                            f"{phase_suffix}… "
                            f"scanline {done} of {total}"
                        )
        if self._latest_result is None and not received_current:
            self._ensure_polling()

    def _show_raster(self, raster: RenderedRaster, label: str) -> None:
        scale = max(1, int(self.preview_zoom_var.get().rstrip("x")))
        profile_label = COMPOSITE_PROFILE_LABELS[self.profile]
        all_selected = str(self.phase_var.get()).strip().lower() == PHASE_ALL
        phase_text = (
            _format_phase_set(self.enabled_phases)
            if all_selected
            else f"P{self.phase_var.get()}"
        )
        if self._conversion_mode() == CONVERSION_SIMPLE_PALETTE:
            self.preview_pane.configure(
                text=(
                    f"{label} — Simply Palette — {profile_label} fixed 16 colors, "
                    f"{phase_text}{' universal grid' if all_selected else ''}, "
                    f"{raster.width}×{raster.height}, independent four-bit cells"
                )
            )
        elif self._conversion_mode() == CONVERSION_EXHAUSTIVE:
            if all_selected:
                self.preview_pane.configure(
                    text=(
                        f"{label} decoded Composite — Exhaustive exact universal "
                        f"objective — {profile_label}, reachable panels {phase_text} "
                        f"in row-major order, {raster.width}×{raster.height} grid"
                    )
                )
            else:
                self.preview_pane.configure(
                    text=(
                        f"{label} decoded Composite — Exhaustive exact optimum — "
                        f"{profile_label}, phase {self.phase_var.get()}, "
                        f"{raster.width}×{raster.height}, edge artifacts included"
                    )
                )
        else:
            self.preview_pane.configure(
                text=(
                    f"{label} decoded Composite — {profile_label}, "
                    f"{phase_text}{' universal grid' if all_selected else ''}, "
                    f"{raster.width}×{raster.height}, edge artifacts included"
                )
            )
        self.preview_pane.show(raster, scale=scale, x_zoom=1, x_subsample=1)

    def _show_current_preview(self) -> None:
        try:
            mode = self._conversion_mode()
            phase = self._phase_selection()
        except (ValueError, tk.TclError):
            return
        if mode == CONVERSION_SIMPLE_PALETTE:
            raster = self._current_simple_rasters.get(phase)
            if raster is None:
                if phase == PHASE_ALL:
                    raster = render_simple_palette_phase_grid(
                        self.current_bits,
                        self.bit_width,
                        self.height,
                        self.profile,
                        self.enabled_phases,
                    )
                else:
                    preview_bits = self.current_phase_bits.get(
                        int(phase), self.current_bits
                    )
                    raster = render_simple_palette_bits(
                        preview_bits,
                        self.bit_width,
                        self.height,
                        self.profile,
                        phase_offset=int(phase),
                    )
                self._current_simple_rasters[phase] = raster
            self._show_raster(raster, "Current edit")
            return
        raster = self._current_rasters.get(phase)
        if raster is None:
            if phase == PHASE_ALL:
                raster = render_all_phase_grid(
                    self.current_bits,
                    self.bit_width,
                    self.height,
                    self.profile,
                    self.enabled_phases,
                )
            else:
                preview_bits = self.current_phase_bits.get(int(phase), self.current_bits)
                raster = render_composite_artifacts(
                    preview_bits,
                    self.bit_width,
                    self.height,
                    self.profile,
                    phase_offset=int(phase),
                )
            self._current_rasters[phase] = raster
        self._show_raster(raster, "Current edit")

    def _preview_choice_changed(self, *_args: object) -> None:
        if self.preview_var.get() == "current":
            self._show_current_preview()
        elif self._latest_result is not None:
            self._show_raster(self._latest_result.preview, "Converted")
        else:
            all_selected = str(self.phase_var.get()).strip().lower() == PHASE_ALL
            phase_text = _format_phase_set(self.enabled_phases)
            if self._conversion_mode() == CONVERSION_SIMPLE_PALETTE:
                self.preview_pane.clear(
                    f"Mapping {(self.bit_width + 3) // 4}×{self.height} fixed-palette "
                    f"cells{' over ' + phase_text if all_selected else ''}…"
                )
            elif self._conversion_mode() == CONVERSION_EXHAUSTIVE:
                objective = (
                    f"{phase_text} universal"
                    if all_selected
                    else "selected-phase"
                )
                self.preview_pane.clear(
                    f"Solving exact {self.bit_width}×{self.height} {objective} signal…"
                )
            else:
                self.preview_pane.clear(
                    f"Optimizing {self.bit_width}×{self.height} decoded Composite "
                    f"output{' over ' + phase_text if all_selected else ''}…"
                )

    def reset(self) -> None:
        self._initializing = True
        self.conversion_mode_var.set(CONVERSION_SIMULATED_NTSC)
        self.dither_var.set(DITHER_FLOYD_STEINBERG)
        self.dither_amount_var.set(70)
        self.serpentine_var.set(True)
        self.bayer_var.set("4x4")
        self.brightness_var.set(0)
        self.contrast_var.set(0)
        self.saturation_var.set(100)
        self.gamma_var.set(100)
        self.color_emphasis_var.set(65)
        self.detail_var.set(55)
        self.quality_var.set(QUALITY_FAST)
        default_phase = getattr(self, "default_phase", 0)
        self.phase_var.set(str(default_phase))
        self._last_single_phase = default_phase
        self.preserve_zero_var.set(True)
        self._initializing = False
        self._update_conversion_mode_detail()
        self._settings_changed()

    def _accept(self) -> None:
        result = self._latest_result
        if result is None:
            self.status_var.set("Wait for the current conversion to finish.")
            return
        try:
            settings = self._settings()
            mode = self._conversion_mode()
        except (ValueError, tk.TclError) as exc:
            self.status_var.set(f"Invalid conversion setting: {exc}")
            return
        if settings != self._result_settings or mode != self._result_mode:
            self.status_var.set("Controls changed; wait for the updated conversion.")
            return
        source = self.sources[self.source_var.get()]
        if self.on_apply(result, settings, source, mode):
            self.close()

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._cancel_event is not None:
            self._cancel_event.set()
        if self._debounce_after is not None:
            self.after_cancel(self._debounce_after)
            self._debounce_after = None
        if self._poll_after is not None:
            self.after_cancel(self._poll_after)
            self._poll_after = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        if self.on_close_callback is not None:
            self.on_close_callback()
        self.destroy()


class CompositeEditorWindow(tk.Toplevel):
    """Six-pane editor with synchronized Mode-6 and Composite editing."""

    # Non-GUI action tests and third-party extensions may construct a bare
    # instance with ``__new__``. Keep the new linked mode opt-in in that case.
    orientation_workspace: V22OrientationWorkspace | None = None

    def __init__(
        self,
        parent: tk.Misc,
        context: ArchiveContext,
        analysis: ResourceAnalysis | None,
        on_close: Callable[["CompositeEditorWindow"], None] | None = None,
        on_sources_changed: Callable[[], None] | None = None,
        orientation_path: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.context = context
        source_archive = context.composite_target
        if source_archive is None:
            raise RoomSetError(
                f"Load {context.expected_filename('cga')} before opening the composite editor."
            )
        self.orientation_workspace: V22OrientationWorkspace | None = None
        if orientation_path is not None:
            self.orientation_workspace = V22OrientationWorkspace.open(
                source_archive.path,
                orientation_path,
            )
        archive = (
            self.orientation_workspace.orient
            if self.orientation_workspace is not None
            else source_archive
        )
        self.source_archive = source_archive
        self.archive = archive
        self.source_analysis: ResourceAnalysis | None = None
        self.analysis: ResourceAnalysis | None = None
        self.selected_resource_id: int | None = None
        self.on_close_callback = on_close
        self.on_sources_changed_callback = on_sources_changed
        self.project = (
            self.orientation_workspace.project
            if self.orientation_workspace is not None
            else CompositeProject.for_archive(archive)
        )
        self.current_edit: CompositeEdit | None = None
        self.undo_stack: list[EditAction | BulkGifAction] = []
        self.redo_stack: list[EditAction | BulkGifAction] = []
        self._stroke_changes: dict[int, tuple[int, int]] = {}
        self._stroke_seen: set[tuple[int, int]] = set()
        self._stroke_family_before: EditAction | None = None
        self._stroke_transparency_sources: set[int] = set()
        self._render_after: str | None = None
        self._converter_dialog: CompositeConverterDialog | None = None
        self._hover_cell: tuple[int, int] | None = None
        self._hover_bit: tuple[int, int] | None = None
        self._stroke_plane = "composite"
        self._swatch_buttons: list[tk.Button] = []
        self._syncing_phase_controls = False
        self._motion_after: str | None = None
        self._motion_restore_phase: int | None = None
        self._last_gif_directory = archive.path.parent
        self.orientation_direction_var = tk.StringVar(value="right")
        self.orientation_context_var = tk.StringVar(value="Dungeon")
        self.orientation_summary_var = tk.StringVar()
        self.source_vars = {
            adapter: tk.StringVar() for adapter in ("cga", "ega", "vga")
        }
        self.preview_vars = {
            mode: tk.StringVar(value="edited") for mode in EDITOR_PREVIEW_MODES
        }
        if self.orientation_workspace is None:
            self._editable_analyses = editable_image_analyses(self.archive)
        else:
            source_ids = tuple(
                dict.fromkeys(
                    pair.source_resource_id
                    for pair in self.orientation_workspace.pairs
                )
            )
            self._editable_analyses = tuple(
                source_analysis
                for resource_id in source_ids
                if (source_analysis := self.source_archive.analysis_by_id(resource_id))
                is not None
                and source_analysis.image is not None
            )
        self._resource_choices = tuple(
            resource_choice_label(analysis, position, len(self._editable_analyses))
            for position, analysis in enumerate(self._editable_analyses)
        )
        self._resource_position_by_label = {
            label: position for position, label in enumerate(self._resource_choices)
        }
        self._resource_position_by_index = {
            analysis.resource.index: position
            for position, analysis in enumerate(self._editable_analyses)
        }
        self._resource_position_by_id = {
            analysis.resource.resource_id: position
            for position, analysis in enumerate(self._editable_analyses)
        }

        self.title(
            f"Composite editor — {source_archive.path.name} + {archive.path.name}"
            if self.orientation_workspace is not None
            else f"Composite editor — {archive.path.name}"
        )
        self.geometry("1500x980")
        self.minsize(1040, 720)
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.tool_var = tk.StringVar(value="cell")
        self.pencil_var = tk.IntVar(value=1)
        self.transparency_color_var = tk.StringVar(value="#ff00ff")
        self.pattern_var = tk.IntVar(value=6)
        self.zoom_var = tk.StringVar(value="2x")
        self.grid_var = tk.BooleanVar(value=False)
        self.cga_profile_var = tk.StringVar(value=self.project.composite_profile)
        self.red_var = tk.IntVar()
        self.green_var = tk.IntVar()
        self.blue_var = tk.IntVar()
        self.hex_var = tk.StringVar()
        self.selected_label_var = tk.StringVar()
        self.resource_var = tk.StringVar(value="No editable image selected")
        self.resource_choice_var = tk.StringVar()
        self.project_summary_var = tk.StringVar()
        self.phase_policy_var = tk.StringVar(
            value=PHASE_POLICY_LABELS[PHASE_POLICY_MANUAL]
        )
        self.phase_profile_var = tk.StringVar(
            value=PHASE_PROFILE_LABELS[PHASE_PROFILE_FIXED]
        )
        self.active_phase_var = tk.IntVar(value=0)
        self.fallback_phase_var = tk.IntVar(value=0)
        self.phase_enabled_vars = {
            phase: tk.BooleanVar(value=phase == 0) for phase in PHASES
        }
        self.mask_lock_var = tk.BooleanVar(value=False)
        self.motion_preview_var = tk.BooleanVar(value=False)
        self.phase_summary_var = tk.StringVar(value="Select an editable image.")
        self.engine_usage_var = tk.StringVar(
            value="Select an editable image to see its original-engine placement audit."
        )
        self.status_var = tk.StringVar(
            value=(
                "Draw opaque black, opaque white, or DAT index-zero transparency in the Mode-6 pane "
                "(right-click/drag writes opaque black) "
                "or paint four-bit cells in the rough Composite pane; every preview updates live."
            )
        )

        self._build_menu()
        self._build_toolbar()
        self._build_resource_navigator()
        if self.orientation_workspace is None:
            self._build_phase_authoring()
        else:
            self._build_orientation_authoring()
        if self.context.is_room_set:
            self._build_room_sources()
        self._build_previews()
        self._build_palette()
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=6).pack(
            fill=tk.X, side=tk.BOTTOM
        )
        self._bind_shortcuts()
        self._select_pattern(self.pattern_var.get())
        if (
            self.orientation_workspace is not None
            and (
                analysis is None
                or analysis.resource.resource_id not in self._resource_position_by_id
            )
            and self._editable_analyses
        ):
            analysis = self._editable_analyses[0]
        self.set_analysis(analysis)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        project_menu = tk.Menu(menu, tearoff=False)
        if self.orientation_workspace is None:
            project_menu.add_command(label="New phase-aware sidecar", command=self.new_project)
            project_menu.add_command(label="Open phase-aware sidecar…", command=self.open_project)
            project_menu.add_separator()
            project_menu.add_command(
                label="Save phase-aware sidecar (.pdcproj)",
                accelerator="Ctrl+S",
                command=self.save_project,
            )
            project_menu.add_command(
                label="Save phase-aware sidecar as…",
                command=lambda: self.save_project(save_as=True),
            )
            project_menu.add_separator()
            project_menu.add_command(label="Save patched DAT as…", accelerator="Ctrl+Shift+S", command=self.save_patched)
            project_menu.add_command(
                label="Export phase-aware runtime manifest…",
                command=self.export_phase_manifest,
            )
        else:
            project_menu.add_command(
                label="Export complete ORIENT.DAT as…",
                accelerator="Ctrl+S",
                command=self.save_patched,
            )
        project_menu.add_separator()
        project_menu.add_command(label="Close", command=self.close)
        menu.add_cascade(label="Project", menu=project_menu)
        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self.redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Reset composite palette", command=self.reset_palette)
        edit_menu.add_checkbutton(
            label="All-pane pixel grid",
            variable=self.grid_var,
            command=self._grid_changed,
            accelerator="Ctrl+G",
        )
        menu.add_cascade(label="Edit", menu=edit_menu)
        image_menu = tk.Menu(menu, tearoff=False)
        image_menu.add_command(
            label="Convert current image…",
            accelerator="Ctrl+Shift+C",
            command=self.open_converter,
        )
        if self.orientation_workspace is None:
            image_menu.add_command(
                label="Export enabled Mode-6 GIF set…",
                command=lambda: self.export_phase_gif_set("mode6"),
            )
            image_menu.add_command(
                label="Export enabled Composite GIF set…",
                command=lambda: self.export_phase_gif_set("composite"),
            )
            image_menu.add_command(
                label="Import phase GIF set…",
                command=self.import_phase_gif_set,
            )
            image_menu.add_command(
                label="Export resource/phase matrix…",
                command=self.export_phase_verification_sheet,
            )
        image_menu.add_command(
            label=(
                "Export V22 Right/Left runtime contact sheet…"
                if self.orientation_workspace is not None
                else "Export animation contact sheet…"
            ),
            command=self.export_animation_contact_sheet,
        )
        image_menu.add_separator()
        image_menu.add_command(
            label="Export all resources to Mode-6 GIF folder…",
            command=self.export_bulk_mode6_gifs,
        )
        image_menu.add_command(
            label="Import resources from Mode-6 GIF folder…",
            command=self.import_bulk_mode6_gifs,
        )
        image_menu.add_separator()
        image_menu.add_command(
            label="Previous editable image",
            accelerator="Alt+Left",
            command=lambda: self.navigate_resource(-1),
        )
        image_menu.add_command(
            label="Next editable image",
            accelerator="Alt+Right",
            command=lambda: self.navigate_resource(1),
        )
        menu.add_cascade(label="Image", menu=image_menu)
        if self.context.is_room_set:
            references = tk.Menu(menu, tearoff=False)
            references.add_command(
                label="Choose VGA reference DAT…",
                command=lambda: self.choose_room_reference("vga"),
            )
            references.add_command(
                label="Choose EGA reference DAT…",
                command=lambda: self.choose_room_reference("ega"),
            )
            menu.add_cascade(label="Room references", menu=references)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(
            label=(
                "How linked ORIENT.DAT saving works…"
                if self.orientation_workspace is not None
                else "How phase-aware saving works…"
            ),
            command=(
                self.show_orientation_help
                if self.orientation_workspace is not None
                else self.show_phase_sidecar_help
            ),
        )
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)

    def show_phase_sidecar_help(self) -> None:
        """Explain the recoverable sidecar and fallback-only DAT workflows."""

        messagebox.showinfo(
            "Saving phase-aware graphics",
            PHASE_SIDECAR_HELP_TEXT,
            parent=self,
        )

    def show_orientation_help(self) -> None:
        messagebox.showinfo(
            "Saving linked V22 orientation graphics",
            "The opened actor DAT remains a read-only visual and conversion reference.\n\n"
            "Right/P0 and Left/P0 edits are written only by Export complete ORIENT.DAT. "
            "The export always rebuilds and verifies the complete 889-resource companion; "
            "neither linked input DAT can be overwritten.\n\n"
            "The Input / output modes tab contains the normal six-pane editor. The Left / "
            "Right runtime tab shows the two actual in-game results together.",
            parent=self,
        )

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self, padding=(8, 8, 8, 5))
        toolbar.pack(fill=tk.X)
        if self.orientation_workspace is None:
            ttk.Button(toolbar, text="Open sidecar…", command=self.open_project).pack(side=tk.LEFT)
            ttk.Button(toolbar, text="Save phase sidecar", command=self.save_project).pack(side=tk.LEFT, padx=(6, 0))
            ttk.Button(toolbar, text="Save patched DAT…", command=self.save_patched).pack(side=tk.LEFT, padx=(6, 10))
        else:
            ttk.Button(
                toolbar,
                text="Export complete ORIENT.DAT…",
                command=self.save_patched,
            ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(toolbar, text="Convert", command=self.open_converter).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4)
        ttk.Button(toolbar, text="Undo", command=self.undo).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(toolbar, text="Redo", command=self.redo).pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(toolbar, text="Tool:").pack(side=tk.LEFT)
        ttk.Radiobutton(
            toolbar,
            text="Composite cell",
            variable=self.tool_var,
            value="cell",
            command=self._tool_changed,
        ).pack(side=tk.LEFT, padx=(5, 3))
        ttk.Radiobutton(
            toolbar,
            text="Composite bit",
            variable=self.tool_var,
            value="pencil",
            command=self._tool_changed,
        ).pack(side=tk.LEFT, padx=(3, 10))
        ttk.Label(toolbar, text="Mode-6 pencil:").pack(side=tk.LEFT)
        ttk.Radiobutton(toolbar, text="1 (white)", variable=self.pencil_var, value=1).pack(side=tk.LEFT)
        ttk.Radiobutton(toolbar, text="0 (black)", variable=self.pencil_var, value=0).pack(side=tk.LEFT)
        ttk.Radiobutton(
            toolbar,
            text="Transparent",
            variable=self.pencil_var,
            value=TRANSPARENCY_BRUSH,
        ).pack(side=tk.LEFT, padx=(0, 5))
        self.transparency_color_button = tk.Button(
            toolbar,
            text="Select transparent color…",
            command=self.choose_transparency_display_color,
            background=self.transparency_color_var.get(),
            activebackground=self.transparency_color_var.get(),
            foreground="#ffffff",
            activeforeground="#ffffff",
            relief=tk.RAISED,
            borderwidth=2,
        )
        self.transparency_color_button.pack(side=tk.LEFT, padx=(0, 7))
        ttk.Label(toolbar, text="Right-drag: opaque black").pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(toolbar, text="Zoom:").pack(side=tk.LEFT)
        zoom = ttk.Combobox(
            toolbar,
            textvariable=self.zoom_var,
            state="readonly",
            values=COMPOSITE_EDITOR_ZOOM_VALUES,
            width=6,
        )
        zoom.pack(side=tk.LEFT, padx=(5, 10))
        zoom.bind("<<ComboboxSelected>>", lambda _event: self._zoom_changed())
        ttk.Checkbutton(
            toolbar,
            text="Grid",
            variable=self.grid_var,
            command=self._grid_changed,
        ).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(toolbar, textvariable=self.resource_var, anchor=tk.E).pack(
            side=tk.RIGHT, fill=tk.X, expand=True
        )

    def _build_resource_navigator(self) -> None:
        navigator = ttk.Frame(self, padding=(8, 0, 8, 6))
        navigator.pack(fill=tk.X)
        ttk.Label(navigator, text="DAT image:").pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(
            navigator,
            text="◀ Previous",
            command=lambda: self.navigate_resource(-1),
        ).pack(side=tk.LEFT)
        combo = ttk.Combobox(
            navigator,
            textvariable=self.resource_choice_var,
            values=self._resource_choices,
            state="readonly" if self._resource_choices else "disabled",
            width=62,
        )
        combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        combo.bind("<<ComboboxSelected>>", self._resource_selected)
        ttk.Button(
            navigator,
            text="Next ▶",
            command=lambda: self.navigate_resource(1),
        ).pack(side=tk.LEFT)
        ttk.Label(
            navigator,
            textvariable=self.project_summary_var,
            anchor=tk.E,
        ).pack(side=tk.RIGHT, padx=(12, 0))

    def _build_phase_authoring(self) -> None:
        """Build the designer-facing phase-family controls."""

        outer = ttk.LabelFrame(
            self,
            text="Carrier-phase coverage — audited original engine or manual override",
            padding=(8, 6),
        )
        outer.pack(fill=tk.X, padx=8, pady=(0, 6))

        row = ttk.Frame(outer)
        row.pack(fill=tk.X)
        ttk.Label(row, text="Policy:").pack(side=tk.LEFT, padx=(0, 5))
        self.phase_policy_combo = ttk.Combobox(
            row,
            textvariable=self.phase_policy_var,
            values=tuple(PHASE_POLICY_LABELS.values()),
            state="readonly",
            width=31,
        )
        self.phase_policy_combo.pack(side=tk.LEFT, padx=(0, 12))
        self.phase_policy_combo.bind(
            "<<ComboboxSelected>>", self._phase_policy_changed
        )

        ttk.Label(row, text="Coverage:").pack(side=tk.LEFT, padx=(0, 5))
        self.phase_profile_combo = ttk.Combobox(
            row,
            textvariable=self.phase_profile_var,
            values=tuple(PHASE_PROFILE_LABELS.values()),
            state="readonly",
            width=18,
        )
        self.phase_profile_combo.pack(side=tk.LEFT, padx=(0, 12))
        self.phase_profile_combo.bind(
            "<<ComboboxSelected>>", self._phase_profile_changed
        )

        ttk.Label(row, text="Runtime phases:").pack(side=tk.LEFT, padx=(0, 4))
        self.phase_enable_buttons: dict[int, ttk.Checkbutton] = {}
        for phase in PHASES:
            button = ttk.Checkbutton(
                row,
                text=f"P{phase}",
                variable=self.phase_enabled_vars[phase],
                command=self._enabled_phase_toggled,
            )
            button.pack(side=tk.LEFT, padx=(0, 3))
            self.phase_enable_buttons[phase] = button

        ttk.Separator(row, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=7)
        ttk.Label(row, text="Edit variant:").pack(side=tk.LEFT, padx=(0, 4))
        self.phase_edit_buttons: dict[int, ttk.Radiobutton] = {}
        for phase in PHASES:
            button = ttk.Radiobutton(
                row,
                text=f"P{phase}",
                variable=self.active_phase_var,
                value=phase,
                style="Toolbutton",
                command=self._active_phase_changed,
            )
            button.pack(side=tk.LEFT, padx=(0, 3))
            self.phase_edit_buttons[phase] = button

        ttk.Label(row, text="DAT fallback:").pack(side=tk.LEFT, padx=(10, 4))
        self.fallback_phase_combo = ttk.Combobox(
            row,
            textvariable=self.fallback_phase_var,
            values=PHASES,
            state="readonly",
            width=3,
        )
        self.fallback_phase_combo.pack(side=tk.LEFT)
        self.fallback_phase_combo.bind("<<ComboboxSelected>>", self._fallback_phase_changed)

        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X, pady=(6, 0))
        ttk.Checkbutton(
            actions,
            text="Lock source index-zero geometry across variants",
            variable=self.mask_lock_var,
            command=self._mask_lock_changed,
        ).pack(side=tk.LEFT)
        ttk.Checkbutton(
            actions,
            text="Animate runtime phase switching",
            variable=self.motion_preview_var,
            command=self._motion_preview_changed,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(actions, text="Generate phase set…", command=self.open_converter).pack(
            side=tk.LEFT, padx=(12, 0)
        )
        ttk.Button(
            actions,
            text="Export GIF set…",
            command=lambda: self.export_phase_gif_set("mode6"),
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            actions,
            text="Export resource/phase matrix…",
            command=self.export_phase_verification_sheet,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            actions,
            text="Export animation sheet…",
            command=self.export_animation_contact_sheet,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            actions,
            text="Export runtime manifest…",
            command=self.export_phase_manifest,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(
            actions,
            textvariable=self.phase_summary_var,
            foreground="#44515f",
            anchor=tk.E,
        ).pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(12, 0))

        ttk.Label(
            outer,
            textvariable=self.engine_usage_var,
            foreground="#334e68",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=1420,
        ).pack(fill=tk.X, pady=(6, 0))
        ttk.Label(
            outer,
            text=(
                "Ctrl+S / Save phase-aware sidecar keeps every image and every stored P0–P3 "
                "variant. Save patched DAT writes only the selected DAT fallback."
            ),
            foreground="#7a3e00",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=1420,
        ).pack(fill=tk.X, pady=(4, 0))

    def _build_orientation_authoring(self) -> None:
        """Build V22 direction controls without removing the mature editor tools."""

        workspace = self.orientation_workspace
        assert workspace is not None
        outer = ttk.LabelFrame(
            self,
            text="V22 linked orientation artwork — dedicated Right/P0 and Left/P0",
            padding=(8, 6),
        )
        outer.pack(fill=tk.X, padx=8, pady=(0, 6))

        row = ttk.Frame(outer)
        row.pack(fill=tk.X)
        ttk.Label(row, text="Edit orientation:").pack(side=tk.LEFT, padx=(0, 5))
        for value, label in (("right", "Right / P0"), ("left", "Left / P0")):
            ttk.Radiobutton(
                row,
                text=label,
                variable=self.orientation_direction_var,
                value=value,
                style="Toolbutton",
                command=self._orientation_changed,
            ).pack(side=tk.LEFT, padx=(0, 4))

        ttk.Separator(row, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Label(row, text="Guard context:").pack(side=tk.LEFT, padx=(0, 5))
        self.orientation_context_combo = ttk.Combobox(
            row,
            textvariable=self.orientation_context_var,
            values=("Dungeon", "Palace"),
            state="readonly" if workspace.family == "GUARD" else "disabled",
            width=10,
        )
        self.orientation_context_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.orientation_context_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self._orientation_changed(),
        )
        ttk.Button(row, text="Convert current image…", command=self.open_converter).pack(
            side=tk.LEFT
        )
        ttk.Button(
            row,
            text="Show Left / Right runtime",
            command=self.select_orientation_preview,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            row,
            text="Export runtime contact sheet…",
            command=self.export_animation_contact_sheet,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(
            row,
            text="Export complete ORIENT.DAT…",
            command=self.save_patched,
        ).pack(side=tk.RIGHT)

        ttk.Label(
            outer,
            textvariable=self.orientation_summary_var,
            foreground="#334e68",
            anchor=tk.W,
        ).pack(fill=tk.X, pady=(6, 0))
        ttk.Label(
            outer,
            text=(
                "The original actor DAT is the visual/conversion source and is never modified. "
                "All six input/output panes, GIF import/export, conversion modes, palette tools, "
                "undo/redo, and transparency editing operate on the selected ORIENT direction."
            ),
            foreground="#7a3e00",
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=1420,
        ).pack(fill=tk.X, pady=(4, 0))

    def _orientation_pair(self) -> OrientationPair | None:
        workspace = self.orientation_workspace
        if workspace is None or self.selected_resource_id is None:
            return None
        context = (
            self.orientation_context_var.get()
            if workspace.family == "GUARD"
            else ""
        )
        try:
            return workspace.pair(self.selected_resource_id, context=context)
        except CompositeProjectError:
            return None

    def _orientation_changed(self) -> None:
        if self.source_analysis is not None:
            self.set_analysis(self.source_analysis)

    def select_orientation_preview(self) -> None:
        notebook = getattr(self, "preview_notebook", None)
        tab = getattr(self, "orientation_preview_tab", None)
        if notebook is not None and tab is not None:
            notebook.select(tab)

    def _refresh_project_summary(self) -> None:
        if self.orientation_workspace is not None:
            changed = len(self.project.edits)
            self.project_summary_var.set(
                f"ORIENT.DAT: {changed} loaded/edited direction resource(s) • full 889-resource export"
            )
            return
        name = self.project.path.name if self.project.path is not None else "Unsaved sidecar"
        count = len(self.project.edits)
        noun = "image" if count == 1 else "images"
        variants = sum(len(edit.enabled_phases) for edit in self.project.edits.values())
        automatic = sum(
            edit.phase_policy == PHASE_POLICY_ENGINE
            for edit in self.project.edits.values()
        )
        self.project_summary_var.set(
            f"{name}: {count} {noun}, {variants} enabled variant(s), "
            f"{automatic} engine-audited • Ctrl+S saves every stored variant"
        )

    def _sync_resource_navigator(self) -> None:
        if self.selected_resource_id is None:
            self.resource_choice_var.set("")
        else:
            position = self._resource_position_by_id.get(self.selected_resource_id)
            self.resource_choice_var.set(
                self._resource_choices[position] if position is not None else ""
            )
        self._refresh_project_summary()

    def _sync_phase_controls(self) -> None:
        # Several non-GUI regression tests exercise editor actions on a
        # deliberately uninitialized window instance.  The phase bar is a
        # presentation concern, so action/model behavior must remain usable
        # without any Tk variables having been constructed.
        if self.orientation_workspace is not None:
            pair = self._orientation_pair()
            if pair is None:
                self.orientation_summary_var.set("Select a mapped actor frame.")
            else:
                direction = self.orientation_direction_var.get().title()
                target_id = (
                    pair.right_resource_id
                    if direction == "Right"
                    else pair.left_resource_id
                )
                self.orientation_summary_var.set(
                    f"Source {pair.source_resource_id} → editing {direction}/P0 "
                    f"ORIENT resource {target_id}; paired runtime preview keeps both outputs visible."
                )
            return
        if not hasattr(self, "phase_profile_var"):
            return
        edit = self.current_edit
        self._syncing_phase_controls = True
        try:
            if edit is None:
                self.phase_policy_var.set(PHASE_POLICY_LABELS[PHASE_POLICY_MANUAL])
                self.phase_profile_var.set(PHASE_PROFILE_LABELS[PHASE_PROFILE_FIXED])
                self.active_phase_var.set(0)
                self.fallback_phase_var.set(0)
                self.phase_policy_combo.configure(
                    values=tuple(PHASE_POLICY_LABELS.values()), state="disabled"
                )
                self.phase_profile_combo.configure(state="disabled")
                for phase in PHASES:
                    self.phase_enabled_vars[phase].set(phase == 0)
                    self.phase_enable_buttons[phase].state(["disabled"])
                    self.phase_edit_buttons[phase].state(["disabled"])
                self.fallback_phase_combo.configure(values=PHASES, state="disabled")
                self.mask_lock_var.set(False)
                self.phase_summary_var.set("Select an editable image.")
                self.engine_usage_var.set(
                    "Select an editable image to see its original-engine placement audit."
                )
                return
            edit.validate()
            usage_lookup = getattr(self.project, "engine_usage_for_edit", None)
            usage = usage_lookup(edit) if callable(usage_lookup) else None
            automatic = edit.phase_policy == PHASE_POLICY_ENGINE and usage is not None
            available_policies = (
                tuple(PHASE_POLICY_LABELS.values())
                if usage is not None
                else (PHASE_POLICY_LABELS[PHASE_POLICY_MANUAL],)
            )
            self.phase_policy_var.set(PHASE_POLICY_LABELS[edit.phase_policy])
            self.phase_policy_combo.configure(
                values=available_policies,
                state="readonly",
            )
            self.phase_profile_var.set(PHASE_PROFILE_LABELS[edit.phase_profile])
            self.phase_profile_combo.configure(
                state="disabled" if automatic else "readonly"
            )
            self.active_phase_var.set(edit.signal_phase)
            self.fallback_phase_var.set(edit.fallback_phase)
            for phase in PHASES:
                enabled = phase in edit.enabled_phases
                self.phase_enabled_vars[phase].set(enabled)
                self.phase_enable_buttons[phase].state(
                    ["disabled"] if automatic else ["!disabled"]
                )
                self.phase_edit_buttons[phase].state(
                    ["!disabled"] if enabled else ["disabled"]
                )
            self.fallback_phase_combo.configure(
                values=edit.enabled_phases,
                state="readonly",
            )
            self.mask_lock_var.set(edit.mask_locked)
            enabled = "/".join(f"P{phase}" for phase in edit.enabled_phases)
            stored = "/".join(f"P{phase}" for phase in edit.variant_phases)
            lock = "mask locked" if edit.mask_locked else "mask unlocked"
            policy = "Automatic" if automatic else "Manual"
            self.phase_summary_var.set(
                f"{policy} • enabled {enabled} • editing P{edit.signal_phase} • "
                f"DAT P{edit.fallback_phase} • stored {stored} • {lock}"
            )
            if usage is None:
                self.engine_usage_var.set(
                    "No exact original-engine placement record is available for this "
                    "archive/resource; choose coverage manually for the target executable."
                )
            else:
                used = "Used" if usage.used else "Unused compatibility slot"
                self.engine_usage_var.set(
                    f"{used} • required at normalized screen origin: "
                    f"{usage.phase_label}. {usage.summary} Placement: {usage.placement}"
                )
        finally:
            self._syncing_phase_controls = False

    def _phase_policy_changed(self, _event: tk.Event | None = None) -> None:
        if self._syncing_phase_controls or self.current_edit is None:
            return
        policy = PHASE_POLICY_BY_LABEL.get(self.phase_policy_var.get())
        if policy is None:
            self.status_var.set("Choose a valid carrier-phase coverage policy.")
            self._sync_phase_controls()
            return
        edit = self.current_edit
        if policy == PHASE_POLICY_MANUAL:
            if edit.phase_policy != policy:
                edit.phase_policy = policy
                self.project.dirty = True
                self.redo_stack.clear()
            self._sync_phase_controls()
            self.status_var.set(
                "Manual coverage enabled; choose only the phases supported by your custom draw code."
            )
            return

        before = (
            edit.phase_policy,
            edit.enabled_phases,
            edit.signal_phase,
            edit.fallback_phase,
            edit.variant_phases,
        )
        try:
            usage, created = self.project.apply_engine_phase_policy(edit)
        except CompositeProjectError as exc:
            self._sync_phase_controls()
            self.status_var.set(str(exc))
            return
        after = (
            edit.phase_policy,
            edit.enabled_phases,
            edit.signal_phase,
            edit.fallback_phase,
            edit.variant_phases,
        )
        if after != before:
            self.project.dirty = True
            self.redo_stack.clear()
        self._hover_cell = None
        self._hover_bit = None
        self._sync_phase_controls()
        self.render_all()
        cloned_text = (
            " Cloned placeholder "
            + ", ".join(f"P{phase}" for phase in created)
            + "; generate that variant independently."
            if created
            else ""
        )
        self.status_var.set(
            f"Original-engine audit requires {usage.phase_label} for resource "
            f"{edit.resource_id}.{cloned_text}"
        )

    def _phase_profile_changed(self, _event: tk.Event | None = None) -> None:
        if self._syncing_phase_controls or self.current_edit is None:
            return
        if self.current_edit.phase_policy == PHASE_POLICY_ENGINE:
            self._sync_phase_controls()
            self.status_var.set(
                "Coverage is locked to the original-engine placement audit. "
                "Switch Policy to Manual to override it."
            )
            return
        profile = PHASE_PROFILE_BY_LABEL.get(self.phase_profile_var.get())
        if profile is None:
            self.status_var.set("Choose a valid phase-usage profile.")
            self._sync_phase_controls()
            return
        if profile == PHASE_PROFILE_CUSTOM:
            self.status_var.set(
                "Custom phase coverage selected; use the P0–P3 runtime checkboxes."
            )
            return
        phases = (
            (self.current_edit.signal_phase,)
            if profile == PHASE_PROFILE_FIXED
            else PHASE_PROFILE_PHASES[profile]
        )
        self._set_phase_coverage(phases, PHASE_PROFILE_LABELS[profile])

    def _enabled_phase_toggled(self) -> None:
        if self._syncing_phase_controls or self.current_edit is None:
            return
        if self.current_edit.phase_policy == PHASE_POLICY_ENGINE:
            self._sync_phase_controls()
            self.status_var.set(
                "Runtime phases are fixed by the original-engine placement audit."
            )
            return
        phases = tuple(
            phase for phase in PHASES if self.phase_enabled_vars[phase].get()
        )
        if not phases:
            self.phase_enabled_vars[self.current_edit.signal_phase].set(True)
            self.status_var.set("At least one runtime phase must remain enabled.")
            return
        self._set_phase_coverage(phases, "Custom phases")

    def _set_phase_coverage(self, phases: tuple[int, ...], label: str) -> None:
        edit = self.current_edit
        if edit is None:
            return
        if edit.phase_policy == PHASE_POLICY_ENGINE:
            self._sync_phase_controls()
            self.status_var.set(
                "Switch Policy to Manual before changing audited phase coverage."
            )
            return
        before = edit.enabled_phases
        created = edit.set_enabled_phases(phases, create_missing=True)
        if edit.enabled_phases != before or created:
            self.project.dirty = True
            self.redo_stack.clear()
        if len(edit.enabled_phases) > 1 and not edit.mask_locked:
            # New clones normally still match the source mask. Enable the safe
            # default automatically only when it does not rewrite artwork.
            edit.mask_locked = True
            try:
                edit.validate()
            except CompositeProjectError:
                edit.mask_locked = False
            else:
                self.project.dirty = True
        self._sync_phase_controls()
        self.render_all()
        created_text = (
            " Cloned placeholder " + ", ".join(f"P{phase}" for phase in created) +
            "; run Generate phase set to optimize it independently."
            if created
            else ""
        )
        self.status_var.set(
            f"{label} now enables "
            f"{', '.join(f'P{phase}' for phase in edit.enabled_phases)}.{created_text}"
        )

    def _active_phase_changed(self) -> None:
        if self._syncing_phase_controls or self.current_edit is None:
            return
        phase = int(self.active_phase_var.get())
        if phase not in self.current_edit.enabled_phases:
            self.status_var.set(f"P{phase} is not enabled for this graphic family.")
            self._sync_phase_controls()
            return
        self.current_edit.activate_phase(phase, enable=False)
        self.project.dirty = True
        self._hover_cell = None
        self._hover_bit = None
        self._sync_phase_controls()
        self.render_all()
        self.status_var.set(
            f"Editing independent carrier-phase variant P{phase}; other variants were not changed."
        )

    def _fallback_phase_changed(self, _event: tk.Event | None = None) -> None:
        if self._syncing_phase_controls or self.current_edit is None:
            return
        phase = int(self.fallback_phase_var.get())
        if phase not in self.current_edit.enabled_phases:
            self.status_var.set("The legacy DAT fallback must be an enabled phase.")
            self._sync_phase_controls()
            return
        self.current_edit.fallback_phase = phase
        self.project.dirty = True
        self._sync_phase_controls()
        self.status_var.set(
            f"A normal single-image patched DAT will use P{phase}; the runtime manifest keeps all enabled variants."
        )

    def _mask_lock_changed(self) -> None:
        if self._syncing_phase_controls or self.current_edit is None:
            return
        edit = self.current_edit
        requested = bool(self.mask_lock_var.get())
        if not requested:
            edit.mask_locked = False
            self.project.dirty = True
            self._sync_phase_controls()
            self.status_var.set(
                "Source index-zero geometry is unlocked; phase variants may now change mask pixels."
            )
            return

        changed_by_phase: dict[int, int] = {}
        before = {phase: bytes(bits) for phase, bits in edit.phase_variants.items()}
        for phase, bits in edit.phase_variants.items():
            count = 0
            for offset in range(len(bits)):
                source_pixel = edit.source_pixel_for_bit_offset(offset)
                if (
                    edit.source_zero_mask[source_pixel]
                    and bits[offset] != edit.mask_reference_bits[offset]
                ):
                    count += 1
            if count:
                changed_by_phase[phase] = count
        if changed_by_phase:
            detail = ", ".join(
                f"P{phase}: {count} bit(s)" for phase, count in sorted(changed_by_phase.items())
            )
            if not messagebox.askyesno(
                "Restore mask geometry?",
                "Locking source index zero must restore protected signal bits:\n\n"
                f"{detail}\n\nRestore them identically in every stored phase variant?",
                parent=self,
            ):
                self.mask_lock_var.set(False)
                return
            for bits in edit.phase_variants.values():
                for offset in range(len(bits)):
                    source_pixel = edit.source_pixel_for_bit_offset(offset)
                    if edit.source_zero_mask[source_pixel]:
                        bits[offset] = edit.mask_reference_bits[offset]
        edit.mask_locked = True
        try:
            edit.validate()
        except CompositeProjectError as exc:
            edit.mask_locked = False
            self.mask_lock_var.set(False)
            messagebox.showerror("Cannot lock mask", str(exc), parent=self)
            return
        after = {phase: bytes(bits) for phase, bits in edit.phase_variants.items()}
        if before != after:
            self.undo_stack.append(
                EditAction(
                    edit.resource_index,
                    {},
                    phase_before=edit.signal_phase,
                    phase_after=edit.signal_phase,
                    variants_before={phase: bits for phase, bits in before.items()},
                    variants_after={phase: bits for phase, bits in after.items()},
                    enabled_before=edit.enabled_phases,
                    enabled_after=edit.enabled_phases,
                    fallback_before=edit.fallback_phase,
                    fallback_after=edit.fallback_phase,
                    mask_locked_before=False,
                    mask_locked_after=True,
                )
            )
            self.redo_stack.clear()
        self.project.dirty = True
        self._sync_phase_controls()
        self.render_all()
        self.status_var.set(
            "Source index-zero geometry is locked across every stored phase variant."
        )

    def _motion_preview_changed(self) -> None:
        if self._syncing_phase_controls:
            return
        if not self.motion_preview_var.get():
            self._stop_motion_preview(restore=True)
            return
        edit = self.current_edit
        if edit is None or len(edit.enabled_phases) < 2:
            self.motion_preview_var.set(False)
            self.status_var.set("Enable at least two runtime phases to animate switching.")
            return
        self._motion_restore_phase = edit.signal_phase
        self._motion_tick()

    def _motion_tick(self) -> None:
        self._motion_after = None
        edit = self.current_edit
        if edit is None or not self.motion_preview_var.get():
            return
        phases = edit.enabled_phases
        position = phases.index(edit.signal_phase) if edit.signal_phase in phases else -1
        edit.activate_phase(phases[(position + 1) % len(phases)], enable=False)
        self._sync_phase_controls()
        self.render_all()
        self.status_var.set(
            f"Runtime preview selected P{edit.signal_phase}; artwork variants remain independent."
        )
        self._motion_after = self.after(450, self._motion_tick)

    def _stop_motion_preview(self, *, restore: bool) -> None:
        if self._motion_after is not None:
            self.after_cancel(self._motion_after)
            self._motion_after = None
        if (
            restore
            and self.current_edit is not None
            and self._motion_restore_phase in self.current_edit.phase_variants
        ):
            self.current_edit.activate_phase(
                int(self._motion_restore_phase), enable=False
            )
        self._motion_restore_phase = None
        if hasattr(self, "motion_preview_var"):
            self.motion_preview_var.set(False)
        if self.current_edit is not None:
            self._sync_phase_controls()
            self.render_all()

    def _resource_selected(self, _event: tk.Event | None = None) -> None:
        position = self._resource_position_by_label.get(
            self.resource_choice_var.get()
        )
        if position is not None:
            self.set_analysis(self._editable_analyses[position])

    def navigate_resource(self, delta: int) -> None:
        """Move within the editable images without returning to the main window."""

        if not self._editable_analyses:
            self.status_var.set("This DAT contains no editable 1-bit or 4-bit images.")
            return
        current = (
            self._resource_position_by_id.get(self.selected_resource_id)
            if self.selected_resource_id is not None
            else None
        )
        position = 0 if current is None else (current + delta) % len(self._editable_analyses)
        self.set_analysis(self._editable_analyses[position])
        self.status_var.set(
            f"Selected image {position + 1} of {len(self._editable_analyses)}. "
            + (
                f"Editing {self.orientation_direction_var.get().title()}/P0 in linked ORIENT.DAT."
                if self.orientation_workspace is not None
                else f"The sidecar currently stores {len(self.project.edits)} image record(s)."
            )
        )

    def _build_room_sources(self) -> None:
        sources = ttk.LabelFrame(
            self,
            text=f"Linked {self.context.family.title()} archives — matched by resource ID",
            padding=(8, 6),
        )
        sources.pack(fill=tk.X, padx=8, pady=(0, 6))
        sources.columnconfigure(1, weight=1)
        rows = (
            ("cga", "Composite target", None),
            ("vga", "VGA reference", "Choose VGA DAT…"),
            ("ega", "EGA reference", "Choose EGA DAT…"),
        )
        for row, (adapter, label, button_text) in enumerate(rows):
            ttk.Label(sources, text=f"{label}:").grid(row=row, column=0, sticky="e", padx=(0, 7), pady=2)
            ttk.Label(
                sources,
                textvariable=self.source_vars[adapter],
                style="ReadOnly.TLabel" if adapter != "cga" else "TLabel",
            ).grid(row=row, column=1, sticky="w", pady=2)
            if button_text is not None:
                ttk.Button(
                    sources,
                    text=button_text,
                    command=lambda value=adapter: self.choose_room_reference(value),
                ).grid(row=row, column=2, sticky="e", padx=(10, 0), pady=2)
        ttk.Label(
            sources,
            text="Only the C archive can be patched. E and V archives are opened read-only.",
            foreground="#44515f",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))
        self._refresh_source_labels()

    def _refresh_source_labels(self) -> None:
        if not self.context.is_room_set:
            return
        for adapter in ("cga", "ega", "vga"):
            archive = self.context.archives.get(adapter)
            if archive is not None:
                suffix = "editable Save-As target" if adapter == "cga" else "read-only"
                value = f"{archive.path.name} — {suffix}"
            else:
                value = f"Not loaded (expected {self.context.expected_filename(adapter)})"
            self.source_vars[adapter].set(value)

    def choose_room_reference(self, adapter: str) -> None:
        if adapter not in ("vga", "ega") or not self.context.is_room_set:
            return
        current = self.context.archives.get(adapter)
        initial_dir = current.path.parent if current is not None else self.archive.path.parent
        filename = filedialog.askopenfilename(
            parent=self,
            title=f"Choose {adapter.upper()} {self.context.family.title()} reference",
            initialdir=str(initial_dir),
            initialfile=self.context.expected_filename(adapter),
            filetypes=(("Prince DAT files", "*.DAT *.dat"), ("All files", "*.*")),
        )
        if not filename:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            archive = DatArchive.open(filename)
            self.context.attach(adapter, archive)
        except (DatFormatError, RoomSetError) as exc:
            messagebox.showerror("Cannot load room reference", str(exc), parent=self)
            return
        finally:
            self.configure(cursor="")
        self._refresh_source_labels()
        self.render_all()
        if self.on_sources_changed_callback is not None:
            self.on_sources_changed_callback()
        self.status_var.set(
            f"Loaded {archive.path.name} as a read-only {adapter.upper()} reference."
        )

    def _conversion_sources(self) -> dict[str, ConverterSource]:
        """Resolve original VGA/EGA/CGA inputs for the selected resource ID."""

        resource_id = self.selected_resource_id
        if resource_id is None:
            return {}
        sources: dict[str, ConverterSource] = {}
        for mode in ("vga", "ega", "cga"):
            resolved = self.context.analysis_for_display_mode(mode, resource_id)
            if resolved is None:
                continue
            archive, analysis = resolved
            image = analysis.image
            if image is None:
                continue
            hardware = hardware_palette_for_resource(archive, analysis.resource)
            raster = render_display_mode(image, mode, hardware)
            sources[mode] = ConverterSource(
                mode=mode,
                description=(
                    f"{mode.upper()} • {archive.path.name} • "
                    f"{image.width}×{image.height}, {image.bits}-bit source indices"
                ),
                raster=raster,
                zero_mask=tuple(index == 0 for index in image.pixels),
            )
        if (
            self.orientation_workspace is not None
            and self.orientation_direction_var.get() == "right"
        ):
            sources = {
                mode: ConverterSource(
                    mode=source.mode,
                    description=source.description + " • mirrored to actual in-game Right",
                    raster=mirror_raster(source.raster),
                    zero_mask=mirror_mask(
                        source.zero_mask,
                        source.raster.width,
                        source.raster.height,
                    ),
                )
                for mode, source in sources.items()
            }
        return sources

    def _orientation_transform_samples(
        self,
        values: Iterable[int],
    ) -> tuple[int, ...]:
        """Transform stored/display rows for V22 Right; the mapping is its own inverse."""

        edit = self.current_edit
        workspace = self.orientation_workspace
        materialized = tuple(values)
        if (
            workspace is None
            or edit is None
            or self.orientation_direction_var.get() != "right"
        ):
            return materialized
        if len(materialized) != edit.bit_width * edit.height:
            raise CompositeProjectError("V22 signal dimensions changed unexpectedly.")
        return tuple(
            materialized[
                y * edit.bit_width
                + workspace.display_to_stored_x(edit, "right", display_x)
            ]
            for y in range(edit.height)
            for display_x in range(edit.bit_width)
        )

    def _orientation_display_bits(self, values: Iterable[int]) -> bytes:
        return bytes(self._orientation_transform_samples(values))

    def _orientation_stored_bits(self, values: Iterable[int]) -> bytes:
        return bytes(self._orientation_transform_samples(values))

    def open_converter(self) -> None:
        """Open the artifact-aware conversion dialog for the current edit."""

        if self._converter_dialog is not None and self._converter_dialog.winfo_exists():
            self._converter_dialog.lift()
            self._converter_dialog.focus_force()
            return
        edit = self.current_edit
        if edit is None or self.analysis is None or self.analysis.image is None:
            messagebox.showinfo(
                "Convert",
                "Select an editable 1-bit or 4-bit CGA image first.",
                parent=self,
            )
            return
        sources = self._conversion_sources()
        if not sources:
            messagebox.showerror(
                "Convert",
                "No VGA, EGA, or CGA image source is available for this resource ID.",
                parent=self,
            )
            return
        current_bits = bytes(edit.bits)
        current_phase_bits = {
            phase: bytes(bits) for phase, bits in edit.phase_variants.items()
        }
        constraints = edit.locked_bit_constraints()
        apply_callback = self._apply_conversion
        apply_set_callback = self._apply_phase_set_conversion
        if self.orientation_workspace is not None:
            current_bits = self._orientation_display_bits(current_bits)
            current_phase_bits = {
                phase: self._orientation_display_bits(bits)
                for phase, bits in edit.phase_variants.items()
            }
            if constraints is not None:
                constraints = self._orientation_transform_samples(constraints)
            apply_callback = self._apply_orientation_conversion
            apply_set_callback = self._apply_orientation_phase_set_conversion
        self._converter_dialog = CompositeConverterDialog(
            self,
            resource_id=edit.resource_id,
            sources=sources,
            current_bits=current_bits,
            bit_width=edit.bit_width,
            height=edit.height,
            profile=self.project.composite_profile,
            initial_phase=edit.signal_phase,
            enabled_phases=edit.enabled_phases,
            selectable_phases=(
                edit.enabled_phases
                if edit.phase_policy == PHASE_POLICY_ENGINE
                else PHASES
            ),
            current_phase_bits=current_phase_bits,
            mask_locked=edit.mask_locked,
            target_locked_bits=constraints,
            on_apply=apply_callback,
            on_apply_set=apply_set_callback,
            on_close=self._converter_closed,
        )

    def _converter_closed(self) -> None:
        self._converter_dialog = None

    def _apply_orientation_conversion(
        self,
        result: ConversionResult,
        settings: ConversionSettings,
        source: ConverterSource,
        conversion_mode: str,
    ) -> bool:
        stored = replace(result, bits=self._orientation_stored_bits(result.bits))
        return self._apply_conversion(stored, settings, source, conversion_mode)

    def _apply_orientation_phase_set_conversion(
        self,
        results: dict[int, ConversionResult],
        settings: ConversionSettings,
        source: ConverterSource,
        conversion_mode: str,
    ) -> bool:
        stored = {
            phase: replace(result, bits=self._orientation_stored_bits(result.bits))
            for phase, result in results.items()
        }
        return self._apply_phase_set_conversion(
            stored,
            settings,
            source,
            conversion_mode,
        )

    def _apply_conversion(
        self,
        result: ConversionResult,
        settings: ConversionSettings,
        source: ConverterSource,
        conversion_mode: str,
    ) -> bool:
        """Commit one converter result as one undoable editor action."""

        edit = self.current_edit
        analysis = self.analysis
        if edit is None or analysis is None or analysis.image is None:
            messagebox.showerror(
                "Convert",
                "The selected editable image changed while conversion was open.",
                parent=self,
            )
            return False
        if len(result.bits) != len(edit.bits):
            messagebox.showerror(
                "Convert",
                "The converted signal dimensions no longer match the selected image.",
                parent=self,
            )
            return False

        all_phase_objective = settings.phase_offset == PHASE_ALL
        if (
            all_phase_objective
            and resolved_phase_offsets(settings) != edit.enabled_phases
        ):
            messagebox.showerror(
                "Cannot apply conversion",
                "The resource's enabled runtime phases changed while the universal "
                "conversion was running. Reopen Convert and generate it again.",
                parent=self,
            )
            return False
        target_phase = (
            edit.signal_phase
            if all_phase_objective
            else int(settings.phase_offset)
        )
        if (
            edit.phase_policy == PHASE_POLICY_ENGINE
            and target_phase not in edit.enabled_phases
        ):
            messagebox.showerror(
                "Cannot apply conversion",
                f"The original-engine audit does not permit P{target_phase} for "
                f"resource {edit.resource_id}. Switch the phase policy to Manual "
                "before creating a non-audited slot.",
                parent=self,
            )
            return False
        try:
            hardware = hardware_palette_for_resource(
                self.archive,
                analysis.resource,
            )
            # Validate the same inverse translation used by Save patched DAT
            # before changing the live edit or its undo history.
            predicted_image_for_edit(
                analysis.image,
                edit,
                hardware,
                bits=result.bits,
            )
        except CompositeProjectError as exc:
            messagebox.showerror(
                "Cannot apply conversion",
                f"The converted bits cannot be represented by this image's CGA table:\n\n{exc}",
                parent=self,
            )
            return False

        previous_bits = edit.phase_variants.get(target_phase)
        comparison_bits = previous_bits if previous_bits is not None else edit.bits
        changes = {
            offset: (before, after)
            for offset, (before, after) in enumerate(zip(comparison_bits, result.bits))
            if before != after
        }
        phase_before = edit.signal_phase
        enabled_before = edit.enabled_phases
        fallback_before = edit.fallback_phase
        existed_before = target_phase in edit.phase_variants
        if (
            not changes
            and existed_before
            and phase_before == target_phase
            and target_phase in enabled_before
        ):
            model_label = CONVERSION_MODE_LABELS[conversion_mode]
            self.status_var.set(
                f"The {source.mode.upper()} {model_label} conversion already "
                "matches the edited Composite image."
            )
            return True

        before_snapshot = {
            target_phase: bytes(previous_bits) if previous_bits is not None else None
        }
        edit.set_variant_bits(
            target_phase,
            result.bits,
            enable=True,
            activate=True,
        )
        after_snapshot = {target_phase: bytes(edit.variant_bits(target_phase))}
        self.undo_stack.append(
            EditAction(
                edit.resource_index,
                changes,
                phase_before=phase_before,
                phase_after=target_phase,
                variant_phase=target_phase,
                variants_before=before_snapshot,
                variants_after=after_snapshot,
                enabled_before=enabled_before,
                enabled_after=edit.enabled_phases,
                fallback_before=fallback_before,
                fallback_after=edit.fallback_phase,
            )
        )
        self.redo_stack.clear()
        self.project.dirty = True
        for mode in ("mode6", "composite", "artifact"):
            self.preview_vars[mode].set("edited")
        self._sync_phase_controls()
        self._render_edited()
        phase_text = _format_phase_set(resolved_phase_offsets(settings))
        if conversion_mode == CONVERSION_SIMPLE_PALETTE:
            objective = (
                f"universal {phase_text} pattern stored in active P{target_phase}"
                if all_phase_objective
                else f"independent P{target_phase} variant"
            )
            self.status_var.set(
                f"Converted {source.mode.upper()} with Simply Palette as one undo "
                f"action • {len(changes)} bit(s) changed • {objective} • "
                f"palette RMSE {result.source_rmse:.1f}."
            )
        elif conversion_mode == CONVERSION_EXHAUSTIVE:
            if all_phase_objective:
                self.status_var.set(
                    f"Converted {source.mode.upper()} with Exhaustive all into "
                    f"the edited {result.target_width}×{result.target_height} Composite "
                    f"signal as one undo action • {len(changes)} bit(s) changed • "
                    f"universal {phase_text} pattern stored in active P{target_phase} • "
                    f"reachable-phase RMSE {result.source_rmse:.1f}."
                )
            else:
                self.status_var.set(
                    f"Converted {source.mode.upper()} with Exhaustive into the edited "
                    f"{result.target_width}×{result.target_height} Composite signal as one "
                    f"undo action • {len(changes)} bit(s) changed • independent P{target_phase} variant • "
                    f"source RMSE {result.source_rmse:.1f}."
                )
        else:
            objective = (
                f"universal {phase_text} pattern stored in active P{target_phase}"
                if all_phase_objective
                else f"independent P{target_phase} variant"
            )
            self.status_var.set(
                f"Converted {source.mode.upper()} with Simulated NTSC into the edited "
                f"{result.target_width}×{result.target_height} Composite signal as one "
                f"undo action • {len(changes)} bit(s) changed • {objective} • "
                f"source RMSE {result.source_rmse:.1f}."
            )
        return True

    def _apply_phase_set_conversion(
        self,
        results: dict[int, ConversionResult],
        settings: ConversionSettings,
        source: ConverterSource,
        conversion_mode: str,
    ) -> bool:
        """Atomically commit independently solved variants as one undo action."""

        edit = self.current_edit
        analysis = self.analysis
        if edit is None or analysis is None or analysis.image is None:
            messagebox.showerror(
                "Generate phase set",
                "The selected editable image changed while conversion was running.",
                parent=self,
            )
            return False
        expected_phases = edit.enabled_phases
        if tuple(sorted(results)) != expected_phases:
            messagebox.showerror(
                "Generate phase set",
                "The completed phase set no longer matches the enabled runtime phases.",
                parent=self,
            )
            return False
        try:
            hardware = hardware_palette_for_resource(self.archive, analysis.resource)
            for phase, result in sorted(results.items()):
                if len(result.bits) != edit.bit_width * edit.height:
                    raise CompositeProjectError(
                        f"P{phase} conversion dimensions no longer match the image."
                    )
                predicted_image_for_edit(
                    analysis.image,
                    edit,
                    hardware,
                    bits=result.bits,
                )
        except CompositeProjectError as exc:
            messagebox.showerror(
                "Cannot apply phase set",
                "At least one generated variant cannot be represented by this "
                f"resource's CGA table:\n\n{exc}",
                parent=self,
            )
            return False

        active_before = edit.signal_phase
        enabled_before = edit.enabled_phases
        fallback_before = edit.fallback_phase
        before = {
            phase: (
                bytes(edit.phase_variants[phase])
                if phase in edit.phase_variants
                else None
            )
            for phase in results
        }
        changed = 0
        for phase, result in sorted(results.items()):
            previous = edit.phase_variants.get(phase, edit.bits)
            changed += sum(
                before_bit != after_bit
                for before_bit, after_bit in zip(previous, result.bits)
            )
            edit.set_variant_bits(
                phase,
                result.bits,
                enable=True,
                activate=False,
            )
        edit.activate_phase(active_before, enable=False)
        after = {phase: bytes(edit.variant_bits(phase)) for phase in results}
        if before == after:
            self.status_var.set(
                "Every enabled phase already matches the independently generated Exhaustive set."
            )
            return True
        self.undo_stack.append(
            EditAction(
                edit.resource_index,
                {},
                phase_before=active_before,
                phase_after=active_before,
                variants_before=before,
                variants_after=after,
                enabled_before=enabled_before,
                enabled_after=edit.enabled_phases,
                fallback_before=fallback_before,
                fallback_after=edit.fallback_phase,
            )
        )
        self.redo_stack.clear()
        self.project.dirty = True
        for mode in ("mode6", "composite", "artifact"):
            self.preview_vars[mode].set("edited")
        self._sync_phase_controls()
        self._render_edited()
        phases = ", ".join(f"P{phase}" for phase in sorted(results))
        average_rmse = sum(result.source_rmse for result in results.values()) / len(results)
        self.status_var.set(
            f"Generated independent Exhaustive variants {phases} from {source.mode.upper()} "
            f"as one undo action • {changed} aggregate bit change(s) • "
            f"mean per-phase RMSE {average_rmse:.1f}; no targets or decoded colors were averaged."
        )
        return True

    def _build_previews(self) -> None:
        if self.orientation_workspace is not None:
            self.preview_notebook = ttk.Notebook(self)
            self.preview_notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 5))
            modes_tab = ttk.Frame(self.preview_notebook)
            self.orientation_preview_tab = ttk.Frame(self.preview_notebook)
            self.preview_notebook.add(modes_tab, text="Input / output modes")
            self.preview_notebook.add(
                self.orientation_preview_tab,
                text="Left / Right runtime",
            )
            grid_parent = modes_tab
        else:
            grid_parent = self
        grid = ttk.Frame(grid_parent, padding=(0 if self.orientation_workspace is not None else 8, 0, 0 if self.orientation_workspace is not None else 8, 5))
        grid.pack(fill=tk.BOTH, expand=True)
        for column in range(6):
            grid.columnconfigure(column, weight=1, uniform="preview")
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)
        grid.rowconfigure(2, weight=1)
        self.vga_pane = self._build_preview_slot(
            grid,
            "vga",
            "VGA — reference",
            row=0,
            column=0,
            columnspan=2,
            padx=(0, 4),
            pady=(0, 4),
        )
        self.ega_pane = self._build_preview_slot(
            grid,
            "ega",
            "EGA — reference",
            row=0,
            column=2,
            columnspan=2,
            padx=4,
            pady=(0, 4),
        )
        self.cga_pane = self._build_preview_slot(
            grid,
            "cga",
            "CGA — reference",
            row=0,
            column=4,
            columnspan=2,
            padx=(4, 0),
            pady=(0, 4),
        )
        self.mode6_pane = self._build_preview_slot(
            grid,
            "mode6",
            "1-bit / Mode 6 — editable",
            row=1,
            column=0,
            columnspan=3,
            padx=(0, 4),
            pady=(4, 0),
        )
        self.composite_pane = self._build_preview_slot(
            grid,
            "composite",
            "Composite cells — editable rough view",
            row=1,
            column=3,
            columnspan=3,
            padx=(4, 0),
            pady=(4, 0),
        )
        self.artifact_pane = self._build_preview_slot(
            grid,
            "artifact",
            "Composite signal — artifact simulation (read-only)",
            row=2,
            column=0,
            columnspan=6,
            padx=0,
            pady=(8, 0),
            viewport_renderer=True,
        )
        self.artifact_pane.canvas.configure(cursor="arrow")

        mode6_canvas = self.mode6_pane.canvas
        self._bind_mode6_canvas_controls(mode6_canvas)
        mode6_canvas.bind("<Motion>", self._hover_mode6)
        mode6_canvas.bind("<Leave>", self._leave_mode6)

        canvas = self.composite_pane.canvas
        canvas.bind(
            "<ButtonPress-1>",
            lambda event: self._stroke_start(event, False, "composite"),
        )
        canvas.bind(
            "<B1-Motion>",
            lambda event: self._stroke_move(event, False, "composite"),
        )
        canvas.bind("<ButtonRelease-1>", self._stroke_end)
        canvas.bind("<Motion>", self._hover_composite)
        canvas.bind("<Leave>", self._leave_composite)

        if self.orientation_workspace is not None:
            self._build_orientation_previews()

    def _build_orientation_previews(self) -> None:
        """Add the paired actual-runtime preview inside this editor window."""

        tab = self.orientation_preview_tab
        note = ttk.Label(
            tab,
            text=(
                "Both actual in-game outputs are shown together at fixed P0. "
                "Choose which direction the full editor tools modify; Right includes "
                "Prince's runtime source-pixel reversal."
            ),
            foreground="#34566f",
            padding=(8, 7),
        )
        note.pack(fill=tk.X)
        panes = ttk.Panedwindow(tab, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        right_slot = ttk.Frame(panes)
        left_slot = ttk.Frame(panes)
        panes.add(right_slot, weight=1)
        panes.add(left_slot, weight=1)
        ttk.Radiobutton(
            right_slot,
            text="Edit Right / P0 with the full toolset",
            variable=self.orientation_direction_var,
            value="right",
            command=self._orientation_changed,
            style="Toolbutton",
        ).pack(fill=tk.X, pady=(0, 4))
        ttk.Radiobutton(
            left_slot,
            text="Edit Left / P0 with the full toolset",
            variable=self.orientation_direction_var,
            value="left",
            command=self._orientation_changed,
            style="Toolbutton",
        ).pack(fill=tk.X, pady=(0, 4))
        self.orientation_right_pane = RasterPane(
            right_slot,
            "Actual in-game Right / P0",
        )
        self.orientation_left_pane = RasterPane(
            left_slot,
            "Actual in-game Left / P0",
        )
        self.orientation_right_pane.pack(fill=tk.BOTH, expand=True, padx=(0, 4))
        self.orientation_left_pane.pack(fill=tk.BOTH, expand=True, padx=(4, 0))

    def _bind_mode6_canvas_controls(self, canvas: tk.Canvas) -> None:
        """Bind selected left paint and unconditional opaque-black right paint."""

        canvas.bind(
            "<ButtonPress-1>",
            lambda event: self._stroke_start(event, False, "mode6"),
        )
        canvas.bind(
            "<B1-Motion>",
            lambda event: self._stroke_move(event, False, "mode6"),
        )
        canvas.bind("<ButtonRelease-1>", self._stroke_end)
        canvas.bind(
            "<ButtonPress-3>",
            lambda event: self._stroke_start(event, True, "mode6"),
        )
        canvas.bind(
            "<B3-Motion>",
            lambda event: self._stroke_move(event, True, "mode6"),
        )
        canvas.bind("<ButtonRelease-3>", self._stroke_end)

    def _build_preview_slot(
        self,
        parent: ttk.Frame,
        mode: str,
        title: str,
        *,
        row: int,
        column: int,
        columnspan: int,
        padx: int | tuple[int, int],
        pady: int | tuple[int, int],
        viewport_renderer: bool = False,
    ) -> RasterPane:
        """Build one pane with its own persistent Original/Edited selector."""

        slot = ttk.Frame(parent)
        slot.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="nsew",
            padx=padx,
            pady=pady,
        )
        slot.rowconfigure(1, weight=1)
        slot.columnconfigure(0, weight=1)
        selector = ttk.Frame(slot, padding=(4, 0, 4, 2))
        selector.grid(row=0, column=0, sticky="ew")
        ttk.Label(selector, text="Preview:").pack(side=tk.LEFT, padx=(0, 5))
        for value, label in (("original", "Original"), ("edited", "Edited")):
            ttk.Radiobutton(
                selector,
                text=label,
                variable=self.preview_vars[mode],
                value=value,
                style="Toolbutton",
                command=lambda selected=mode: self._preview_view_changed(selected),
            ).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(
            selector,
            text="Export GIF…",
            command=lambda selected=mode: self.export_pane_gif(selected),
        ).pack(side=tk.RIGHT)
        if mode in EDITABLE_GIF_MODES:
            ttk.Button(
                selector,
                text="Import GIF…",
                command=lambda selected=mode: self.import_pane_gif(selected),
            ).pack(side=tk.RIGHT, padx=(0, 5))
        pane_class = ViewportRasterPane if viewport_renderer else RasterPane
        pane = pane_class(slot, title)
        pane.grid(row=1, column=0, sticky="nsew")
        return pane

    def _pane_for_mode(self, mode: str) -> RasterPane:
        pane_attributes = {
            "vga": "vga_pane",
            "ega": "ega_pane",
            "cga": "cga_pane",
            "mode6": "mode6_pane",
            "composite": "composite_pane",
            "artifact": "artifact_pane",
        }
        try:
            attribute = pane_attributes[mode]
        except KeyError as exc:
            raise IndexedGifError(f"Unknown editor pane: {mode!r}.") from exc
        return getattr(self, attribute)

    def _adapter_gif_image(self, mode: str, raster: RenderedRaster) -> IndexedGif:
        resource_id = self.selected_resource_id
        if mode not in ("vga", "ega", "cga") or resource_id is None:
            raise IndexedGifError("No adapter image is selected for GIF export.")
        resolved = self.context.analysis_for_display_mode(mode, resource_id)
        if resolved is None or resolved[1].image is None:
            raise IndexedGifError(
                f"Resource {resource_id} has no {mode.upper()} image to export."
            )
        archive, analysis = resolved
        hardware = hardware_palette_for_resource(archive, analysis.resource)
        if mode == "vga" and analysis.image.bits == 8:
            palette = tuple((index, index, index) for index in range(256))
        else:
            palette = tuple(display_colors(mode, hardware))

        display_image = analysis.image
        is_target_record = (
            self.analysis is not None
            and archive is self.archive
            and analysis.resource.index == self.analysis.resource.index
        )
        if self._preview_choice(mode) == "edited" and is_target_record:
            try:
                predicted = self._predicted_target_image()
            except CompositeProjectError:
                predicted = None
            if predicted is not None:
                display_image = predicted
        if (raster.width, raster.height) != (display_image.width, display_image.height):
            raise IndexedGifError("The visible adapter raster changed during GIF export.")
        indices = bytes(
            translated_index(display_image, x, y, mode, hardware)
            for y in range(display_image.height)
            for x in range(display_image.width)
        )
        return IndexedGif(
            display_image.width,
            display_image.height,
            palette,
            indices,
        )

    def _pane_gif_image(self, mode: str) -> IndexedGif:
        """Build the exact native indexed raster for one visible editor pane."""

        pane = self._pane_for_mode(mode)
        raster = pane.raster
        if raster is None:
            raise IndexedGifError("This pane does not currently contain an image.")

        edit = self.current_edit
        analysis = self.analysis
        if mode == "mode6":
            if edit is None or analysis is None or analysis.image is None:
                raise IndexedGifError("No editable Mode-6 image is selected.")
            if self._preview_choice(mode) == "original":
                hardware = hardware_palette_for_resource(
                    self.archive, analysis.resource
                )
                bits = bytes(initial_mode6_bits(analysis.image, hardware))
                source_zero_mask = bytearray(
                    index == 0 for index in analysis.image.pixels
                )
            else:
                bits = bytes(edit.bits)
                source_zero_mask = edit.source_zero_mask
            if self.orientation_workspace is not None:
                bits = self._orientation_display_bits(bits)
                source_zero_mask = self._orientation_display_mask(source_zero_mask)
            indices = mode6_gif_pixels(edit, bits, source_zero_mask)
            return IndexedGif(
                edit.bit_width,
                edit.height,
                MODE6_ALPHA_GIF_PALETTE,
                indices,
                MODE6_TRANSPARENT_INDEX,
            )

        if mode == "composite":
            if edit is None or analysis is None or analysis.image is None:
                raise IndexedGifError("No editable Composite image is selected.")
            width = (edit.bit_width + 3) // 4
            if self._preview_choice(mode) == "original":
                hardware = hardware_palette_for_resource(
                    self.archive, analysis.resource
                )
                original_bits = self._orientation_display_bits(
                    initial_mode6_bits(analysis.image, hardware)
                )
                values = bytearray(width * edit.height)
                for y in range(edit.height):
                    row = y * edit.bit_width
                    for x in range(width):
                        pattern = 0
                        for part in range(4):
                            bit_x = x * 4 + part
                            pattern = (pattern << 1) | (
                                original_bits[row + bit_x]
                                if bit_x < edit.bit_width
                                else 0
                            )
                        values[y * width + x] = pattern
                indices = bytes(values)
            else:
                display_bits = self._orientation_display_bits(edit.bits)
                values = bytearray(width * edit.height)
                for y in range(edit.height):
                    row = y * edit.bit_width
                    for x in range(width):
                        pattern = 0
                        for part in range(4):
                            bit_x = x * 4 + part
                            pattern = (pattern << 1) | (
                                display_bits[row + bit_x]
                                if bit_x < edit.bit_width
                                else 0
                            )
                        values[y * width + x] = pattern
                indices = bytes(values)
            return IndexedGif(
                width,
                edit.height,
                tuple(self.project.colors),
                indices,
            )

        if mode == "artifact":
            return IndexedGif(
                raster.width,
                raster.height,
                ARTIFACT_GIF_PALETTE,
                raster_rgb332_indices(raster),
            )

        return self._adapter_gif_image(mode, raster)

    def _gif_initial_directory(self, mode: str) -> Path:
        remembered = getattr(self, "_last_gif_directory", None)
        if remembered is not None:
            return Path(remembered)
        if mode in ("vga", "ega", "cga") and self.selected_resource_id is not None:
            resolved = self.context.analysis_for_display_mode(
                mode, self.selected_resource_id
            )
            if resolved is not None:
                return resolved[0].path.parent
        return self.archive.path.parent

    def export_pane_gif(self, mode: str) -> None:
        try:
            image = self._pane_gif_image(mode)
        except IndexedGifError as exc:
            messagebox.showinfo("Export GIF", str(exc), parent=self)
            return
        resource_id = self.selected_resource_id
        if resource_id is None:
            messagebox.showinfo("Export GIF", "Select an image first.", parent=self)
            return
        view = self._preview_choice(mode)
        filename = filedialog.asksaveasfilename(
            parent=self,
            title=f"Export {mode.upper()} pane as fixed-palette GIF",
            initialdir=str(self._gif_initial_directory(mode)),
            initialfile=(
                f"{self.archive.path.stem}_res{resource_id:05d}_P"
                f"{self.current_edit.signal_phase if self.current_edit is not None else 0}_"
                f"{mode}_{view}.gif"
            ),
            defaultextension=".gif",
            filetypes=(("Indexed GIF image", "*.gif"),),
        )
        if not filename:
            return
        self._last_gif_directory = Path(filename).parent
        try:
            write_indexed_gif(
                filename,
                image.width,
                image.height,
                image.palette,
                image.pixels,
                transparent_index=image.transparent_index,
            )
        except (OSError, IndexedGifError) as exc:
            messagebox.showerror("GIF export failed", str(exc), parent=self)
            return
        qualifier = (
            " using the fixed RGB332 signal palette"
            if mode == "artifact"
            else " with its exact indexed palette"
        )
        self.status_var.set(
            f"Exported {mode.upper()} {view} at {image.width}×{image.height}"
            f"{qualifier} to {filename}."
        )

    def _editable_gif_contract(
        self,
        mode: str,
    ) -> tuple[int, int, tuple[tuple[int, int, int], ...]]:
        edit = self.current_edit
        if edit is None:
            raise IndexedGifError("Select an editable image first.")
        if mode == "mode6":
            return edit.bit_width, edit.height, MODE6_GIF_PALETTE
        if mode == "composite":
            return (edit.bit_width + 3) // 4, edit.height, tuple(self.project.colors)
        raise IndexedGifError("Only the Mode-6 and rough Composite panes accept GIF imports.")

    def _validate_imported_bits(
        self,
        bits: bytes,
        source_zero_mask: bytearray | None = None,
        phase: int | None = None,
    ) -> None:
        edit = self.current_edit
        analysis = self.analysis
        if edit is None or analysis is None or analysis.image is None:
            raise IndexedGifError("The selected editable image is no longer available.")
        if len(bits) != len(edit.bits):
            raise IndexedGifError("Imported GIF does not contain the required bit count.")
        try:
            hardware = hardware_palette_for_resource(
                self.archive,
                analysis.resource,
            )
            candidate = edit
            if source_zero_mask is not None:
                candidate = replace(
                    edit,
                    bits=bytearray(bits),
                    phase_variants={edit.signal_phase: bytearray(bits)},
                    enabled_phases=(edit.signal_phase,),
                    fallback_phase=edit.signal_phase,
                    mask_locked=True,
                    mask_authored=True,
                    source_zero_mask=bytearray(source_zero_mask),
                    mask_reference_bits=bytearray(bits),
                )
            predicted_image_for_edit(
                analysis.image,
                candidate,
                hardware,
                phase=phase,
                bits=bits,
            )
        except CompositeProjectError as exc:
            raise IndexedGifError(
                "The GIF's bit pattern cannot be represented by this resource's "
                f"CGA translation table: {exc}"
            ) from exc

    def _commit_imported_bits(
        self,
        mode: str,
        bits: bytes,
        filename: str,
        source_zero_mask: bytearray | None = None,
    ) -> None:
        edit = self.current_edit
        if edit is None:
            raise IndexedGifError("Select an editable image first.")
        changes = {
            offset: (before, after)
            for offset, (before, after) in enumerate(zip(edit.bits, bits))
            if before != after
        }
        mask_changed = (
            source_zero_mask is not None
            and bytearray(source_zero_mask) != edit.source_zero_mask
        )
        mask_state_changed = source_zero_mask is not None and (
            mask_changed
            or not edit.mask_locked
            or not edit.mask_authored
            or bytearray(bits) != edit.mask_reference_bits
        )
        if not changes and not mask_state_changed:
            self.status_var.set(
                f"{Path(filename).name} already matches the edited {mode.upper()} image."
            )
            return
        if source_zero_mask is None:
            edit.bits[:] = bits
            action = EditAction(
                edit.resource_index,
                changes,
                variant_phase=edit.signal_phase,
            )
        else:
            variants_before = {
                phase: bytes(variant)
                for phase, variant in edit.phase_variants.items()
            }
            mask_before = bytes(edit.source_zero_mask)
            reference_before = bytes(edit.mask_reference_bits)
            locked_before = edit.mask_locked
            authored_before = edit.mask_authored
            edit.source_zero_mask = bytearray(source_zero_mask)
            edit.mask_reference_bits = bytearray(bits)
            edit.mask_locked = True
            edit.mask_authored = True
            edit.bits[:] = bits
            for variant in edit.phase_variants.values():
                for offset in range(len(variant)):
                    if edit.source_zero_mask[edit.source_pixel_for_bit_offset(offset)]:
                        variant[offset] = edit.mask_reference_bits[offset]
            variants_after = {
                phase: bytes(variant)
                for phase, variant in edit.phase_variants.items()
            }
            edit.validate()
            action = EditAction(
                edit.resource_index,
                {},
                phase_before=edit.signal_phase,
                phase_after=edit.signal_phase,
                variants_before=variants_before,
                variants_after=variants_after,
                enabled_before=edit.enabled_phases,
                enabled_after=edit.enabled_phases,
                fallback_before=edit.fallback_phase,
                fallback_after=edit.fallback_phase,
                mask_locked_before=locked_before,
                mask_locked_after=True,
                mask_authored_before=authored_before,
                mask_authored_after=True,
                source_zero_mask_before=mask_before,
                source_zero_mask_after=bytes(edit.source_zero_mask),
                mask_reference_bits_before=reference_before,
                mask_reference_bits_after=bytes(edit.mask_reference_bits),
            )
        self.undo_stack.append(action)
        self.redo_stack.clear()
        self.project.dirty = True
        self._hover_cell = None
        self._hover_bit = None
        self.render_all()
        self.status_var.set(
            f"Imported {Path(filename).name} into the {mode.upper()} pane as one "
            f"undo action • {len(changes)} bit(s) changed."
        )

    def import_pane_gif(self, mode: str) -> None:
        if mode not in EDITABLE_GIF_MODES:
            messagebox.showinfo(
                "Import GIF",
                "Only the Mode-6 and rough Composite panes are editable.",
                parent=self,
            )
            return
        if self._preview_choice(mode) != "edited":
            messagebox.showinfo(
                "Import GIF",
                f"Switch the {mode.upper()} pane to Edited before importing.",
                parent=self,
            )
            return
        try:
            width, height, palette = self._editable_gif_contract(mode)
        except IndexedGifError as exc:
            messagebox.showinfo("Import GIF", str(exc), parent=self)
            return
        filename = filedialog.askopenfilename(
            parent=self,
            title=f"Import exact {width}×{height} {mode.upper()} indexed GIF",
            initialdir=str(self._gif_initial_directory(mode)),
            filetypes=(("Indexed GIF image", "*.gif"),),
        )
        if not filename:
            return
        self._last_gif_directory = Path(filename).parent
        try:
            image = read_indexed_gif(filename)
            edit = self.current_edit
            if edit is None:
                raise IndexedGifError("The selected editable image changed during import.")
            if mode == "mode6":
                bits, source_zero_mask = mode6_gif_import(image, edit)
            else:
                require_exact_format(
                    image,
                    width=width,
                    height=height,
                    palette=palette,
                )
                bits = composite_indices_to_bits(image, bit_width=edit.bit_width)
                source_zero_mask = None
            if self.orientation_workspace is not None:
                bits = self._orientation_stored_bits(bits)
                if source_zero_mask is not None:
                    source_zero_mask = self._orientation_display_mask(
                        source_zero_mask
                    )
            self._validate_imported_bits(bits, source_zero_mask)
            self._commit_imported_bits(
                mode,
                bits,
                filename,
                source_zero_mask,
            )
        except (OSError, IndexedGifError) as exc:
            messagebox.showerror(
                "GIF import rejected",
                f"{exc}\n\nThe editor does not resize, recolor, reorder, or remap imported GIFs.",
                parent=self,
            )

    def _phase_variant_gif_image(self, mode: str, phase: int) -> IndexedGif:
        edit = self.current_edit
        if edit is None:
            raise IndexedGifError("Select an editable image first.")
        bits = edit.variant_bits(phase)
        display_bits = (
            self._orientation_display_bits(bits)
            if self.orientation_workspace is not None
            else bytes(bits)
        )
        if mode == "mode6":
            source_zero_mask = (
                self._orientation_display_mask(edit.source_zero_mask)
                if self.orientation_workspace is not None
                else edit.source_zero_mask
            )
            return IndexedGif(
                edit.bit_width,
                edit.height,
                MODE6_ALPHA_GIF_PALETTE,
                mode6_gif_pixels(edit, display_bits, source_zero_mask),
                MODE6_TRANSPARENT_INDEX,
            )
        if mode == "composite":
            width = (edit.bit_width + 3) // 4
            indices = bytearray(width * edit.height)
            for y in range(edit.height):
                row = y * edit.bit_width
                for cell_x in range(width):
                    pattern = 0
                    for part in range(4):
                        bit_x = cell_x * 4 + part
                        pattern = (pattern << 1) | (
                            display_bits[row + bit_x] if bit_x < edit.bit_width else 0
                        )
                    indices[y * width + cell_x] = pattern
            return IndexedGif(
                width,
                edit.height,
                tuple(self.project.colors),
                bytes(indices),
            )
        raise IndexedGifError("Phase GIF sets support Mode-6 or rough Composite images.")

    def export_phase_gif_set(self, mode: str) -> None:
        edit = self.current_edit
        if edit is None:
            messagebox.showinfo("Export phase GIF set", "Select an editable image first.", parent=self)
            return
        if mode not in EDITABLE_GIF_MODES:
            messagebox.showerror("Export phase GIF set", "Choose Mode-6 or Composite.", parent=self)
            return
        destination = filedialog.askdirectory(
            parent=self,
            title=f"Choose folder for enabled {mode.upper()} phase GIFs",
            initialdir=str(self._gif_initial_directory(mode)),
            mustexist=True,
        )
        if not destination:
            return
        folder = Path(destination)
        self._last_gif_directory = folder
        written: list[Path] = []
        try:
            for phase in edit.enabled_phases:
                image = self._phase_variant_gif_image(mode, phase)
                path = folder / (
                    f"{self.archive.path.stem}_res{edit.resource_id:05d}_"
                    f"P{phase}_{mode}.gif"
                )
                write_indexed_gif(
                    path,
                    image.width,
                    image.height,
                    image.palette,
                    image.pixels,
                    transparent_index=image.transparent_index,
                )
                written.append(path)
        except (OSError, IndexedGifError) as exc:
            messagebox.showerror("Phase GIF export failed", str(exc), parent=self)
            return
        phases = ", ".join(f"P{phase}" for phase in edit.enabled_phases)
        self.status_var.set(
            f"Exported exact fixed-palette {mode.upper()} GIF variants {phases} "
            f"to {folder} ({len(written)} file(s))."
        )

    def export_phase_verification_sheet(self) -> None:
        """Export every project resource and enabled phase as one NTSC PNG."""

        if not self.project.edits:
            messagebox.showinfo(
                "Export resource/phase matrix",
                "Open at least one editable image first.",
                parent=self,
            )
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export full-NTSC resource/phase matrix",
            initialdir=str(self._gif_initial_directory("mode6")),
            initialfile=f"{self.archive.path.stem}_phase_verification.png",
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"),),
        )
        if not filename:
            return
        try:
            sheet = render_phase_verification_sheet(self.project)
            destination = Path(filename)
            destination.write_bytes(
                png_bytes(sheet.width, sheet.height, sheet.pixels, channels=3)
            )
        except (OSError, ValueError, CompositeProjectError) as exc:
            messagebox.showerror(
                "Phase-verification export failed", str(exc), parent=self
            )
            return
        self._last_gif_directory = destination.parent
        phases = sorted(
            {
                phase
                for edit in self.project.edits.values()
                for phase in edit.enabled_phases
            }
        )
        phase_text = ", ".join(f"P{phase}" for phase in phases)
        self.status_var.set(
            f"Exported {len(self.project.edits)} resource row(s) across {phase_text} "
            f"as full-NTSC PNG {destination.name}."
        )

    def export_animation_contact_sheet(self) -> None:
        """Export every editable image in the open DAT as one contact sheet."""

        if self.orientation_workspace is not None:
            workspace = self.orientation_workspace
            filename = filedialog.asksaveasfilename(
                parent=self,
                title=f"Export {workspace.family} V22 Right/Left runtime contact sheet",
                initialdir=str(self._gif_initial_directory("mode6")),
                initialfile=f"{workspace.family}-V22-RIGHT-LEFT-P0.png",
                defaultextension=".png",
                filetypes=(("PNG image", "*.png"),),
            )
            if not filename:
                return
            try:
                sheet = render_v22_runtime_contact_sheet(workspace)
                destination = Path(filename)
                destination.write_bytes(
                    png_bytes(sheet.width, sheet.height, sheet.pixels, channels=3)
                )
            except (OSError, ValueError, CompositeProjectError) as exc:
                messagebox.showerror(
                    "Runtime contact-sheet export failed",
                    str(exc),
                    parent=self,
                )
                return
            self._last_gif_directory = destination.parent
            self.status_var.set(
                f"Exported {len(workspace.pairs)} V22 frame pairs as actual Right/P0 "
                f"and Left/P0 runtime views to {destination.name}."
            )
            return

        records = animation_image_records(self.archive)
        if not records:
            messagebox.showinfo(
                "Export animation contact sheet",
                "The open DAT contains no editable 1-bit or 4-bit images.",
                parent=self,
            )
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title=f"Export {self.archive.path.name} animation contact sheet",
            initialdir=str(self._gif_initial_directory("mode6")),
            initialfile=f"{self.archive.path.stem}_animation_contact_sheet.png",
            defaultextension=".png",
            filetypes=(("PNG image", "*.png"),),
        )
        if not filename:
            return
        try:
            sheet = render_animation_contact_sheet(self.archive, self.project)
            destination = Path(filename)
            destination.write_bytes(
                png_bytes(sheet.width, sheet.height, sheet.pixels, channels=3)
            )
        except (OSError, ValueError, CompositeProjectError) as exc:
            messagebox.showerror(
                "Animation contact-sheet export failed", str(exc), parent=self
            )
            return
        self._last_gif_directory = destination.parent
        self.status_var.set(
            f"Exported all {len(records)} editable images from {self.archive.path.name} "
            f"as an R/L P0/P2 contact sheet "
            f"{destination.name}."
        )

    # Kept for extensions which called the v0.4.30 command directly.
    export_kid_animation_contact_sheet = export_animation_contact_sheet

    def import_phase_gif_set(self) -> None:
        edit = self.current_edit
        analysis = self.analysis
        if edit is None or analysis is None or analysis.image is None:
            messagebox.showinfo("Import phase GIF set", "Select an editable image first.", parent=self)
            return
        filenames = filedialog.askopenfilenames(
            parent=self,
            title=(
                "Select exactly one fixed-palette GIF for every enabled phase "
                "(all Mode-6 or all Composite)"
            ),
            initialdir=str(self._gif_initial_directory("mode6")),
            filetypes=(("Indexed GIF images", "*.gif"),),
        )
        if not filenames:
            return
        self._last_gif_directory = Path(filenames[0]).parent
        mode: str | None = None
        imported: dict[int, bytes] = {}
        imported_masks: dict[int, bytearray | None] = {}
        try:
            for filename in filenames:
                name = Path(filename).name
                match = re.search(r"(?:^|[_-])P([0-3])(?:[_-]|\.)", name, re.IGNORECASE)
                if match is None:
                    raise IndexedGifError(
                        f"{name} does not identify a carrier phase using _P0_ through _P3_."
                    )
                phase = int(match.group(1))
                if phase in imported:
                    raise IndexedGifError(f"More than one GIF was selected for P{phase}.")
                lower = name.lower()
                file_mode = (
                    "mode6" if "_mode6" in lower else
                    "composite" if "_composite" in lower else None
                )
                if file_mode is None:
                    raise IndexedGifError(
                        f"{name} must end in a generated _mode6.gif or _composite.gif name."
                    )
                if mode is None:
                    mode = file_mode
                elif mode != file_mode:
                    raise IndexedGifError("Do not mix Mode-6 and Composite GIFs in one import.")
                width, height, palette = self._editable_gif_contract(file_mode)
                image = read_indexed_gif(filename)
                if file_mode == "mode6":
                    bits, candidate_mask = mode6_gif_import(image, edit)
                else:
                    require_exact_format(
                        image,
                        width=width,
                        height=height,
                        palette=palette,
                    )
                    bits = composite_indices_to_bits(
                        image,
                        bit_width=edit.bit_width,
                    )
                    candidate_mask = None
                if self.orientation_workspace is not None:
                    bits = self._orientation_stored_bits(bits)
                    if candidate_mask is not None:
                        candidate_mask = self._orientation_display_mask(
                            candidate_mask
                        )
                self._validate_imported_bits(bits, candidate_mask, phase)
                imported[phase] = bytes(bits)
                imported_masks[phase] = candidate_mask
            if tuple(sorted(imported)) != edit.enabled_phases:
                expected = ", ".join(f"P{phase}" for phase in edit.enabled_phases)
                received = ", ".join(f"P{phase}" for phase in sorted(imported)) or "none"
                raise IndexedGifError(
                    f"The enabled set is {expected}, but the selected files contain {received}."
                )
            carried_masks = [mask for mask in imported_masks.values() if mask is not None]
            if carried_masks and len(carried_masks) != len(imported_masks):
                raise IndexedGifError(
                    "Do not mix legacy opaque and transparency-aware Mode-6 GIFs in one set."
                )
            if carried_masks and any(mask != carried_masks[0] for mask in carried_masks[1:]):
                raise IndexedGifError(
                    "Every phase GIF must carry exactly the same transparency mask."
                )
        except (OSError, IndexedGifError) as exc:
            messagebox.showerror(
                "Phase GIF import rejected",
                f"{exc}\n\nNo variant was changed. The editor never resizes, recolors, or remaps imported GIFs.",
                parent=self,
            )
            return

        shared_mask = next(
            (mask for mask in imported_masks.values() if mask is not None),
            None,
        )
        snapshot_phases = edit.variant_phases if shared_mask is not None else tuple(imported)
        before = {phase: bytes(edit.variant_bits(phase)) for phase in snapshot_phases}
        active_before = edit.signal_phase
        mask_before = bytes(edit.source_zero_mask)
        reference_before = bytes(edit.mask_reference_bits)
        locked_before = edit.mask_locked
        authored_before = edit.mask_authored
        if shared_mask is not None:
            reference_bits = next(iter(imported.values()))
            edit.source_zero_mask = bytearray(shared_mask)
            edit.mask_reference_bits = bytearray(reference_bits)
            edit.mask_locked = True
            edit.mask_authored = True
        changed = 0
        for phase, bits in imported.items():
            changed += sum(a != b for a, b in zip(edit.variant_bits(phase), bits))
            edit.set_variant_bits(phase, bits, enable=True, activate=False)
        if shared_mask is not None:
            for phase, variant in edit.phase_variants.items():
                if phase in imported:
                    continue
                for offset in range(len(variant)):
                    if edit.source_zero_mask[edit.source_pixel_for_bit_offset(offset)]:
                        variant[offset] = edit.mask_reference_bits[offset]
        edit.activate_phase(active_before, enable=False)
        after = {phase: bytes(edit.variant_bits(phase)) for phase in snapshot_phases}
        mask_changed = shared_mask is not None and mask_before != bytes(edit.source_zero_mask)
        mask_state_changed = shared_mask is not None and (
            mask_changed
            or not locked_before
            or not authored_before
            or reference_before != bytes(edit.mask_reference_bits)
        )
        if before == after and not mask_state_changed:
            self.status_var.set("The selected phase GIF set already matches every enabled variant.")
            return
        self.undo_stack.append(
            EditAction(
                edit.resource_index,
                {},
                phase_before=active_before,
                phase_after=active_before,
                variants_before=before,
                variants_after=after,
                enabled_before=edit.enabled_phases,
                enabled_after=edit.enabled_phases,
                fallback_before=edit.fallback_phase,
                fallback_after=edit.fallback_phase,
                mask_locked_before=locked_before if shared_mask is not None else None,
                mask_locked_after=True if shared_mask is not None else None,
                mask_authored_before=authored_before if shared_mask is not None else None,
                mask_authored_after=True if shared_mask is not None else None,
                source_zero_mask_before=mask_before if shared_mask is not None else None,
                source_zero_mask_after=(
                    bytes(edit.source_zero_mask) if shared_mask is not None else None
                ),
                mask_reference_bits_before=(
                    reference_before if shared_mask is not None else None
                ),
                mask_reference_bits_after=(
                    bytes(edit.mask_reference_bits) if shared_mask is not None else None
                ),
            )
        )
        self.redo_stack.clear()
        self.project.dirty = True
        self._sync_phase_controls()
        self.render_all()
        self.status_var.set(
            f"Imported {len(imported)} exact {mode.upper() if mode else ''} phase GIFs "
            f"as one undo action • {changed} aggregate bit change(s)."
        )

    def export_bulk_mode6_gifs(self) -> None:
        """Export the whole editable DAT as resource-ID-named Mode-6 GIFs."""

        if not self._editable_analyses:
            messagebox.showinfo(
                "Bulk Mode-6 GIF export",
                "This DAT contains no editable 1-bit or 4-bit images.",
                parent=self,
            )
            return
        destination = filedialog.askdirectory(
            parent=self,
            title="Choose folder for all editable Mode-6 GIF resources",
            initialdir=str(self._gif_initial_directory("mode6")),
            mustexist=True,
        )
        if not destination:
            return
        folder = Path(destination)
        self._last_gif_directory = folder
        try:
            exports = prepare_bulk_mode6_exports(
                self.archive,
                self.project,
                self._editable_analyses,
            )
        except (CompositeProjectError, IndexedGifError) as exc:
            messagebox.showerror("Bulk Mode-6 GIF export failed", str(exc), parent=self)
            return

        conflicts = [name for name, _image in exports if (folder / name).exists()]
        if conflicts and not messagebox.askyesno(
            "Replace existing bulk GIFs?",
            f"{len(conflicts)} generated filename(s) already exist in {folder}.\n\n"
            "Replace those files with the current DAT/project images? Other files "
            "in the folder will be left alone.",
            parent=self,
        ):
            return
        try:
            for name, image in exports:
                write_indexed_gif(
                    folder / name,
                    image.width,
                    image.height,
                    image.palette,
                    image.pixels,
                    transparent_index=image.transparent_index,
                )
        except (OSError, IndexedGifError) as exc:
            messagebox.showerror(
                "Bulk Mode-6 GIF export failed",
                f"{exc}\n\nSome earlier files may already have been written.",
                parent=self,
            )
            return
        resource_count = len(
            {analysis.resource.resource_id for analysis in self._editable_analyses}
        )
        self.status_var.set(
            f"Exported {len(exports)} exact Mode-6 GIF(s) for {resource_count} "
            f"resource(s) to {folder}. Single-phase names are numeric; phase families "
            "use _P0 through _P3."
        )

    def import_bulk_mode6_gifs(self) -> None:
        """Validate and atomically import resource-ID-named Mode-6 GIFs."""

        folder_text = filedialog.askdirectory(
            parent=self,
            title="Choose folder containing numeric Mode-6 GIF resources",
            initialdir=str(self._gif_initial_directory("mode6")),
            mustexist=True,
        )
        if not folder_text:
            return
        folder = Path(folder_text)
        self._last_gif_directory = folder
        filenames = tuple(
            sorted(
                (
                    path
                    for path in folder.iterdir()
                    if path.is_file() and path.suffix.lower() == ".gif"
                ),
                key=lambda path: path.name.lower(),
            )
        )
        try:
            replacements, file_count = prepare_bulk_mode6_imports(
                self.archive,
                self.project,
                self._editable_analyses,
                filenames,
            )
        except (OSError, CompositeProjectError, IndexedGifError) as exc:
            messagebox.showerror(
                "Bulk Mode-6 GIF import rejected",
                f"{exc}\n\nNo resource was changed. The editor never resizes, "
                "recolors, or remaps imported GIFs.",
                parent=self,
            )
            return

        before = {
            index: copy.deepcopy(self.project.edits.get(index))
            for index in replacements
        }
        changed = {
            index: replacement
            for index, replacement in replacements.items()
            if before[index] != replacement
        }
        if not changed:
            self.status_var.set(
                f"All {file_count} bulk Mode-6 GIF(s) already match the project."
            )
            return
        action = BulkGifAction(
            edits_before={index: before[index] for index in changed},
            edits_after={
                index: copy.deepcopy(replacement)
                for index, replacement in changed.items()
            },
            file_count=file_count,
        )
        for index, replacement in action.edits_after.items():
            self.project.edits[index] = copy.deepcopy(replacement)
        self.undo_stack.append(action)
        self.redo_stack.clear()
        self.project.dirty = True
        self._refresh_after_bulk_gif_action()
        self.status_var.set(
            f"Imported {file_count} exact Mode-6 GIF(s) into {len(changed)} "
            "resource family/families as one undo action."
        )

    def _refresh_after_bulk_gif_action(self) -> None:
        """Reconnect the selected edit after bulk snapshots replace records."""

        if self.analysis is not None and self.analysis.image is not None:
            index = self.analysis.resource.index
            self.current_edit = self.project.edits.get(index)
            if self.current_edit is None:
                self.current_edit = self.project.edit_for_image(
                    self.archive,
                    index,
                    self.analysis.image,
                )
        self._hover_cell = None
        self._hover_bit = None
        self._sync_phase_controls()
        self._refresh_project_summary()
        self.render_all()

    def _build_palette(self) -> None:
        outer = ttk.LabelFrame(
            self,
            text="Composite brush palette — click to select; edit with RGB, HEX, or the color picker",
            padding=(8, 6),
        )
        outer.pack(fill=tk.X, padx=8, pady=(0, 7))

        profile_bar = ttk.Frame(outer)
        profile_bar.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(profile_bar, text="Composite CGA model:").pack(
            side=tk.LEFT, padx=(0, 7)
        )
        for profile, label in COMPOSITE_PROFILE_LABELS.items():
            ttk.Radiobutton(
                profile_bar,
                text=label,
                variable=self.cga_profile_var,
                value=profile,
                style="Toolbutton",
                command=self._composite_profile_changed,
            ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(
            profile_bar,
            text=(
                "Switches rough DOSBox-X swatches and the artifact decoder; "
                "edited bit patterns stay intact."
            ),
            foreground="#44515f",
        ).pack(side=tk.LEFT, padx=(10, 0))

        palette_body = ttk.Frame(outer)
        palette_body.pack(fill=tk.X)
        swatches = ttk.Frame(palette_body)
        swatches.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for index in range(16):
            button = tk.Button(
                swatches,
                text=f"{index:X}\n{index:04b}",
                width=6,
                height=2,
                command=lambda value=index: self._select_pattern(value),
                relief=tk.RAISED,
                borderwidth=2,
            )
            button.grid(row=index // 8, column=index % 8, padx=2, pady=2, sticky="ew")
            button.bind("<Double-Button-1>", lambda _event, value=index: self.choose_color(value))
            swatches.columnconfigure(index % 8, weight=1)
            self._swatch_buttons.append(button)

        editor = ttk.Frame(palette_body, padding=(14, 0, 0, 0))
        editor.pack(side=tk.RIGHT)
        ttk.Label(editor, textvariable=self.selected_label_var).grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 4)
        )
        for column, (label, variable) in enumerate(
            (("R", self.red_var), ("G", self.green_var), ("B", self.blue_var))
        ):
            ttk.Label(editor, text=label).grid(row=1, column=column * 2, sticky="e")
            tk.Spinbox(editor, from_=0, to=255, textvariable=variable, width=4).grid(
                row=1, column=column * 2 + 1, padx=(2, 6)
            )
        ttk.Button(editor, text="Apply RGB", command=self.apply_rgb).grid(
            row=2, column=0, columnspan=3, sticky="ew", pady=(5, 0), padx=(0, 3)
        )
        ttk.Button(editor, text="Choose…", command=self.choose_color).grid(
            row=2, column=3, columnspan=3, sticky="ew", pady=(5, 0), padx=(3, 0)
        )
        ttk.Label(editor, text="HEX").grid(row=3, column=0, sticky="e", pady=(6, 0))
        hex_entry = ttk.Entry(editor, textvariable=self.hex_var, width=10)
        hex_entry.grid(
            row=3, column=1, columnspan=3, sticky="ew", padx=(2, 6), pady=(6, 0)
        )
        hex_entry.bind("<Return>", lambda _event: self.apply_hex())
        ttk.Button(editor, text="Apply HEX", command=self.apply_hex).grid(
            row=3, column=4, columnspan=2, sticky="ew", pady=(6, 0)
        )

    def _composite_profile_changed(self) -> None:
        """Switch the active editable DOSBox-X palette without touching bits."""

        profile = self.cga_profile_var.get()
        try:
            self.project.set_profile(profile)
        except CompositeProjectError as exc:
            self.cga_profile_var.set(self.project.composite_profile)
            messagebox.showerror("Invalid CGA model", str(exc), parent=self)
            return
        self._select_pattern(self.pattern_var.get())
        self._render_edited()
        label = COMPOSITE_PROFILE_LABELS[profile]
        self.status_var.set(
            f"Rough swatches and the artifact signal decoder now use {label}. "
            "Edited bit patterns and patched-DAT output are unchanged."
        )

    def _bind_shortcuts(self) -> None:
        self.bind(
            "<Control-s>",
            lambda _event: (
                self.save_patched()
                if self.orientation_workspace is not None
                else self.save_project()
            ),
        )
        self.bind("<Control-Shift-S>", lambda _event: self.save_patched())
        self.bind("<Control-z>", lambda _event: self.undo())
        self.bind("<Control-y>", lambda _event: self.redo())
        self.bind("<Control-Shift-Z>", lambda _event: self.redo())
        self.bind("<Control-Shift-C>", lambda _event: self.open_converter())
        self.bind("<Control-g>", lambda _event: self._toggle_grid())
        self.bind("<Alt-Left>", lambda _event: self.navigate_resource(-1))
        self.bind("<Alt-Right>", lambda _event: self.navigate_resource(1))

    def set_analysis(self, analysis: ResourceAnalysis | None) -> None:
        if (
            self._converter_dialog is not None
            and self._converter_dialog.winfo_exists()
        ):
            self._converter_dialog.close()
        self._stop_motion_preview(restore=False)
        self._hover_cell = None
        self._hover_bit = None
        self.source_analysis = analysis
        self.selected_resource_id = (
            analysis.resource.resource_id if analysis is not None else None
        )
        self.analysis = None
        self.current_edit = None
        if self.selected_resource_id is None:
            self.resource_var.set("No resource selected")
            self._sync_resource_navigator()
            self._sync_phase_controls()
            self.render_all()
            return

        if self.orientation_workspace is not None:
            pair = self._orientation_pair()
            if pair is None:
                self.resource_var.set(
                    f"Resource {self.selected_resource_id} • no V22 orientation mapping"
                )
                self.status_var.set(
                    "Choose one of the mapped actor animation resources in the selector above."
                )
                self._sync_resource_navigator()
                self._sync_phase_controls()
                self.render_all()
                return
            direction = self.orientation_direction_var.get()
            try:
                target_analysis = self.orientation_workspace.target_analysis(
                    pair,
                    direction,
                )
                self.analysis = target_analysis
                self.current_edit = self.orientation_workspace.edit(pair, direction)
            except CompositeProjectError as exc:
                messagebox.showerror("Cannot edit V22 resource", str(exc), parent=self)
                self._sync_resource_navigator()
                self._sync_phase_controls()
                self.render_all()
                return
            source_image = analysis.image
            target_image = target_analysis.image
            assert source_image is not None and target_image is not None
            position = self._resource_position_by_id.get(self.selected_resource_id)
            image_position = (
                f"Image {position + 1} of {len(self._editable_analyses)} • "
                if position is not None
                else ""
            )
            self.resource_var.set(
                f"{image_position}Source {pair.source_resource_id} • "
                f"{direction.title()}/P0 ORIENT {target_analysis.resource.resource_id} • "
                f"{target_image.width}×{target_image.height}"
            )
            self._sync_resource_navigator()
            self._sync_phase_controls()
            self.render_all()
            return

        resolved = self.context.analysis_for_display_mode(
            "cga", self.selected_resource_id
        )
        if resolved is None:
            self.resource_var.set(
                f"Resource {self.selected_resource_id} • missing from CGA target"
            )
            self.status_var.set(
                f"Resource {self.selected_resource_id} has no matching record in {self.archive.path.name}."
            )
            self._sync_resource_navigator()
            self._sync_phase_controls()
            self.render_all()
            return
        target_archive, target_analysis = resolved
        if target_archive is not self.archive:
            self.resource_var.set("The CGA target changed; reopen the composite editor.")
            self._sync_resource_navigator()
            self._sync_phase_controls()
            self.render_all()
            return
        self.analysis = target_analysis
        if target_analysis.image is None:
            self.resource_var.set(
                f"Resource {self.selected_resource_id} • CGA target is not an image"
            )
            self._sync_resource_navigator()
            self._sync_phase_controls()
            self.render_all()
            return
        image = target_analysis.image
        position = self._resource_position_by_index.get(target_analysis.resource.index)
        image_position = (
            f"Image {position + 1} of {len(self._editable_analyses)} • "
            if position is not None
            else ""
        )
        self.resource_var.set(
            f"{image_position}Resource {target_analysis.resource.resource_id} • "
            f"C target {image.width}×{image.height} • {image.bits}-bit"
        )
        if image.bits not in (1, 4):
            self.status_var.set("This resource is reference-only; composite editing supports 1-bit and 4-bit images.")
            self._sync_resource_navigator()
            self._sync_phase_controls()
            self.render_all()
            return
        try:
            self.current_edit = self.project.edit_for_image(
                self.archive, target_analysis.resource.index, image
            )
        except CompositeProjectError as exc:
            messagebox.showerror("Cannot edit resource", str(exc), parent=self)
        self._sync_resource_navigator()
        self._sync_phase_controls()
        self.render_all()

    def _zoom(self) -> int:
        return max(1, int(self.zoom_var.get().rstrip("x")))

    def _preview_choice(self, mode: str) -> str:
        """Return a validated per-pane view, defaulting safely to Edited."""

        variable = getattr(self, "preview_vars", {}).get(mode)
        value = variable.get() if variable is not None else "edited"
        return value if value in PREVIEW_VIEW_VALUES else "edited"

    def _preview_view_changed(self, mode: str) -> None:
        view = self._preview_choice(mode)
        editable_panes = {
            "mode6": self.mode6_pane,
            "composite": self.composite_pane,
        }
        if mode in editable_panes:
            editable_panes[mode].canvas.configure(
                cursor="crosshair" if view == "edited" else "arrow"
            )
        self.render_all()
        label = (
            "Composite signal"
            if mode == "artifact"
            else DISPLAY_MODE_NAMES[mode]
        )
        detail = "Edits remain intact."
        if self.context.is_room_set and mode in ("vga", "ega"):
            detail = "This linked reference is independent, so both views are unchanged."
        elif mode in ("mode6", "composite") and view == "original":
            detail = "Original is read-only; switch this pane to Edited before drawing."
        elif mode == "artifact":
            detail = (
                "This signal-decoded pane is read-only and includes neighboring-pixel artifacts."
            )
        self.status_var.set(f"{label} pane now shows {view.title()}. {detail}")

    def _predicted_target_image(self) -> DecodedImage | None:
        """Build the exact source-index image the current Save-As would write."""

        if self.current_edit is None or self.analysis is None or self.analysis.image is None:
            return None
        hardware = hardware_palette_for_resource(
            self.archive, self.analysis.resource
        )
        return predicted_image_for_edit(
            self.analysis.image,
            self.current_edit,
            hardware,
        )

    def _orientation_display_mask(
        self,
        mask: Iterable[bool],
    ) -> bytearray:
        edit = self.current_edit
        materialized = tuple(bool(value) for value in mask)
        if (
            self.orientation_workspace is None
            or edit is None
            or self.orientation_direction_var.get() != "right"
        ):
            return bytearray(materialized)
        return bytearray(
            mirror_mask(materialized, edit.source_width, edit.height)
        )

    def _display_edit(
        self,
        bits: Iterable[int],
        source_zero_mask: Iterable[bool],
    ) -> CompositeEdit:
        """Return a render-only edit in actual runtime screen orientation."""

        edit = self.current_edit
        if edit is None:
            raise CompositeProjectError("No V22 direction is selected.")
        display_bits = bytearray(self._orientation_display_bits(bits))
        return replace(
            edit,
            bits=display_bits,
            phase_variants={0: display_bits},
            signal_phase=0,
            enabled_phases=(0,),
            fallback_phase=0,
            mask_locked=False,
            source_zero_mask=self._orientation_display_mask(source_zero_mask),
            mask_reference_bits=bytearray(display_bits),
        )

    def _render_adapter_previews(
        self,
        scale: int,
        predicted_target: DecodedImage | None,
    ) -> None:
        """Render VGA/EGA/CGA, substituting the predicted shared source when valid."""

        resource_id = self.selected_resource_id
        if resource_id is None:
            return
        for mode, pane in (
            ("vga", self.vga_pane),
            ("ega", self.ega_pane),
            ("cga", self.cga_pane),
        ):
            resolved = self.context.analysis_for_display_mode(
                mode, resource_id
            )
            source = self.context.source_description(mode)
            if resolved is None:
                pane.configure(text=f"{mode.upper()} — {source}")
                pane.clear(
                    f"Resource {resource_id} is unavailable in\n{source}."
                )
                continue
            archive, reference = resolved
            if reference.image is None:
                pane.configure(text=f"{mode.upper()} — {archive.path.name}")
                pane.clear(
                    f"Resource {resource_id} is not an image in\n{archive.path.name}."
                )
                continue

            view = self._preview_choice(mode)
            is_target_record = (
                self.analysis is not None
                and archive is self.archive
                and reference.resource.index == self.analysis.resource.index
            )
            use_predicted = (
                view == "edited"
                and predicted_target is not None
                and is_target_record
            )
            display_image = predicted_target if use_predicted else reference.image
            if self.context.is_room_set and mode in ("vga", "ega"):
                suffix = f"{view.upper()}; independent read-only reference"
            elif use_predicted:
                suffix = "EDITED; live patched preview"
            elif view == "edited" and is_target_record:
                suffix = "EDITED preview unavailable; showing original source"
            elif is_target_record:
                suffix = "ORIGINAL source"
            else:
                suffix = f"{view.upper()}; read-only reference"
            pane.configure(text=f"{mode.upper()} — {archive.path.name} ({suffix})")
            hardware = hardware_palette_for_resource(archive, reference.resource)
            x_zoom, x_subsample = display_horizontal_factors(mode, display_image.bits)
            pane.show(
                render_display_mode(display_image, mode, hardware),
                scale=scale,
                x_zoom=x_zoom,
                x_subsample=x_subsample,
                cell_grid=self.grid_var.get(),
            )

    def _render_target_transformed_previews(self, scale: int) -> None:
        """Render the Mode-6 and Composite panes from original or edited bits."""

        if self.current_edit is None or self.analysis is None or self.analysis.image is None:
            self.mode6_pane.clear("No editable CGA image is matched to this resource ID.")
            self.composite_pane.clear("Composite editing requires a matched 1-bit or 4-bit CGA image.")
            self.artifact_pane.clear("Artifact simulation requires a matched 1-bit or 4-bit CGA image.")
            return

        image = self.analysis.image
        hardware = hardware_palette_for_resource(self.archive, self.analysis.resource)
        mode6_zoom, mode6_subsample = display_horizontal_factors("mode6", image.bits)
        composite_zoom, composite_subsample = display_horizontal_factors(
            "composite", image.bits
        )

        mode6_view = self._preview_choice("mode6")
        transparency_var = getattr(self, "transparency_color_var", None)
        transparency_color = (
            parse_hex_color(transparency_var.get())
            if transparency_var is not None
            else DEFAULT_TRANSPARENCY_DISPLAY_COLOR
        )
        if mode6_view == "original":
            mode6_bits = initial_mode6_bits(image, hardware)
            mode6_mask = bytearray(index == 0 for index in image.pixels)
        else:
            mode6_bits = self.current_edit.bits
            mode6_mask = self.current_edit.source_zero_mask
        render_edit = self.current_edit
        if self.orientation_workspace is not None:
            render_edit = self._display_edit(mode6_bits, mode6_mask)
            mode6_bits = render_edit.bits
            mode6_mask = render_edit.source_zero_mask
        mode6_raster = render_mode6_editor_raster(
            render_edit,
            mode6_bits,
            mode6_mask,
            transparency_color,
        )
        self.mode6_pane.configure(
            text=(
                f"1-bit / Mode 6 — {mode6_view.upper()} "
                f"({'read-only' if mode6_view == 'original' else 'editable'}), "
                f"{'½-width' if mode6_subsample == 2 else 'normal-width'} pixels; "
                f"transparent DAT index 0 = #{transparency_color[0]:02x}"
                f"{transparency_color[1]:02x}{transparency_color[2]:02x}"
            )
        )
        self.mode6_pane.show(
            mode6_raster,
            scale=scale,
            x_zoom=mode6_zoom,
            x_subsample=mode6_subsample,
            cell_grid=self.grid_var.get(),
        )

        composite_view = self._preview_choice("composite")
        profile_label = COMPOSITE_PROFILE_LABELS[self.project.composite_profile]
        if self.orientation_workspace is not None:
            composite_source_bits = (
                initial_mode6_bits(image, hardware)
                if composite_view == "original"
                else self.current_edit.bits
            )
            composite_edit = self._display_edit(
                composite_source_bits,
                bytearray(index == 0 for index in image.pixels)
                if composite_view == "original"
                else self.current_edit.source_zero_mask,
            )
            composite_raster = render_edited_composite(
                composite_edit,
                self.project.colors,
            )
        else:
            composite_raster = (
                render_display_mode(
                    image,
                    "composite",
                    hardware,
                    composite_colors=self.project.colors,
                )
                if composite_view == "original"
                else render_edited_composite(self.current_edit, self.project.colors)
            )
        composite_access = "read-only" if composite_view == "original" else "editable"
        self.composite_pane.configure(
            text=(
                f"Composite cells — {profile_label} • {composite_view.upper()} ({composite_access}), "
                f"{composite_zoom}×-width color cells"
            )
        )
        self.composite_pane.show(
            composite_raster,
            scale=scale,
            x_zoom=composite_zoom,
            x_subsample=composite_subsample,
            cell_grid=self.grid_var.get(),
        )

        artifact_view = self._preview_choice("artifact")
        artifact_bits = (
            initial_mode6_bits(image, hardware)
            if artifact_view == "original"
            else self.current_edit.bits
        )
        if self.orientation_workspace is not None:
            artifact_bits = self._orientation_display_bits(artifact_bits)
        artifact_raster = render_composite_artifacts(
            artifact_bits,
            self.current_edit.bit_width,
            self.current_edit.height,
            self.project.composite_profile,
            phase_offset=self.current_edit.signal_phase,
        )
        # The viewport renderer keeps the full logical 640-sample scanline at
        # editor zoom while materializing only the visible source-pixel crop.
        artifact_scale = scale
        self.artifact_pane.configure(
            text=(
                f"Composite signal — {profile_label} • {artifact_view.upper()} "
                f"(read-only, phase {self.current_edit.signal_phase}, full scanline simulation "
                f"with edge artifacts, {artifact_scale}×)"
            )
        )
        self.artifact_pane.show(
            artifact_raster,
            scale=artifact_scale,
            x_zoom=1,
            x_subsample=1,
            cell_grid=self.grid_var.get(),
        )

    def render_all(self) -> None:
        if self.selected_resource_id is None:
            for pane in (
                self.vga_pane,
                self.ega_pane,
                self.cga_pane,
                self.mode6_pane,
                self.composite_pane,
                self.artifact_pane,
            ):
                pane.clear("Select a resource in the main window.")
            self._render_orientation_previews()
            return
        scale = self._zoom()
        predicted_target = None
        try:
            predicted_target = self._predicted_target_image()
        except CompositeProjectError as exc:
            self.status_var.set(f"Live adapter preview unavailable: {exc}")
        self._render_adapter_previews(scale, predicted_target)
        self._render_target_transformed_previews(scale)
        self._render_orientation_previews()
        self._render_hover_markers()

    def _render_orientation_previews(self) -> None:
        workspace = self.orientation_workspace
        right_pane = getattr(self, "orientation_right_pane", None)
        left_pane = getattr(self, "orientation_left_pane", None)
        if workspace is None or right_pane is None or left_pane is None:
            return
        pair = self._orientation_pair()
        if pair is None:
            right_pane.clear("Select a mapped actor frame.")
            left_pane.clear("Select a mapped actor frame.")
            return
        try:
            right = workspace.runtime_raster(pair, "right", transparent=True)
            left = workspace.runtime_raster(pair, "left", transparent=True)
        except CompositeProjectError as exc:
            right_pane.clear(str(exc))
            left_pane.clear(str(exc))
            return
        scale = self._zoom()
        grid = self.grid_var.get()
        active = self.orientation_direction_var.get()
        right_pane.configure(
            text="Actual in-game Right / P0" + (" — EDITING" if active == "right" else "")
        )
        left_pane.configure(
            text="Actual in-game Left / P0" + (" — EDITING" if active == "left" else "")
        )
        right_pane.show(right, scale=scale, cell_grid=grid)
        left_pane.show(left, scale=scale, cell_grid=grid)

    def _render_edited(self) -> None:
        self._render_after = None
        self.render_all()

    def _schedule_edited_render(self) -> None:
        if self._render_after is None:
            self._render_after = self.after(30, self._render_edited)

    def _render_hover_markers(self) -> None:
        for pane in (
            self.vga_pane,
            self.ega_pane,
            self.cga_pane,
            self.mode6_pane,
            self.composite_pane,
            self.artifact_pane,
        ):
            pane.clear_highlight()
        if self.current_edit is None:
            return

        if self._hover_bit is not None:
            bit_x, row = self._hover_bit
            bit_columns = (bit_x,)
            cell_x = bit_x // 4
            source_divisor = 1 if self.current_edit.source_depth == 1 else 2
            source_columns = (bit_x // source_divisor,)
        elif self._hover_cell is not None:
            cell_x, row = self._hover_cell
            source_columns = composite_cell_source_columns(self.current_edit, cell_x)
            bit_columns = composite_cell_mode6_columns(self.current_edit, cell_x)
        else:
            return

        if (
            self.orientation_workspace is not None
            and self.orientation_direction_var.get() == "right"
        ):
            source_columns = tuple(
                self.current_edit.source_width - 1 - column
                for column in source_columns
            )
        source_cells = ((column, row) for column in source_columns)
        # Materialize once because each adapter pane needs the same full set.
        source_cells = tuple(source_cells)
        self.vga_pane.highlight_cells(source_cells)
        self.ega_pane.highlight_cells(source_cells)
        self.cga_pane.highlight_cells(source_cells)
        self.mode6_pane.highlight_cells((column, row) for column in bit_columns)
        self.composite_pane.highlight_cells(((cell_x, row),))
        self.artifact_pane.highlight_cells((column, row) for column in bit_columns)

    def _leave_composite(self, _event: tk.Event | None = None) -> None:
        self._hover_cell = None
        self._render_hover_markers()

    def _leave_mode6(self, _event: tk.Event | None = None) -> None:
        self._hover_bit = None
        self._render_hover_markers()

    def _tool_changed(self) -> None:
        if self.tool_var.get() == "pencil" and self._zoom() < 2:
            self.zoom_var.set("2x")
            self.render_all()
            self.status_var.set(
                "Composite-bit tool selected; zoom increased to 2× so all four bits are addressable."
            )

    def _zoom_changed(self) -> None:
        if self.grid_var.get() and self._zoom() < 4:
            self.zoom_var.set("4x")
            self.status_var.set(
                "All-pane grid requires at least 4× zoom so half-width Mode-6 cells remain visible."
            )
        self.render_all()

    def _grid_changed(self) -> None:
        if self.grid_var.get() and self._zoom() < 4:
            self.zoom_var.set("4x")
            self.status_var.set(
                "All-pane grid enabled; zoom increased to 4× so even half-width Mode-6 cells remain visible."
            )
        self.render_all()

    def _toggle_grid(self) -> None:
        self.grid_var.set(not self.grid_var.get())
        self._grid_changed()

    def _record_stroke_changes(
        self,
        changes: Iterable[tuple[int, int, int]],
    ) -> None:
        changed = False
        for offset, before, after in changes:
            changed = True
            if offset in self._stroke_changes:
                first, _old_after = self._stroke_changes[offset]
                self._stroke_changes[offset] = (first, after)
            else:
                self._stroke_changes[offset] = (before, after)
        if changed:
            self.project.dirty = True
            self._schedule_edited_render()

    def _display_to_stored_bit_x(self, bit_x: int) -> int:
        workspace = self.orientation_workspace
        edit = self.current_edit
        if workspace is None or edit is None:
            return bit_x
        return workspace.display_to_stored_x(
            edit,
            self.orientation_direction_var.get(),
            bit_x,
        )

    def _paint_composite(self, event: tk.Event, erase: bool) -> None:
        edit = self.current_edit
        if edit is None:
            return
        if self._preview_choice("composite") == "original":
            self.status_var.set(
                "Composite is showing the read-only Original. Select Edited in that pane before drawing."
            )
            return
        coordinates = self.composite_pane.raster_coordinates(event)
        if coordinates is None:
            return
        cell_x, y = coordinates
        local_x, local_y = self.composite_pane.local_coordinates(event)
        self._hover_cell = (cell_x, y)
        self._hover_bit = None
        if self.tool_var.get() == "cell":
            key = (cell_x, y)
            if key in self._stroke_seen:
                return
            self._stroke_seen.add(key)
            pattern = 0 if erase else self.pattern_var.get()
            if self.orientation_workspace is None:
                changes = edit.set_pattern(cell_x, y, pattern)
            else:
                changes = []
                for part in range(4):
                    display_bit_x = cell_x * 4 + part
                    if display_bit_x >= edit.bit_width:
                        continue
                    stored_bit_x = self._display_to_stored_bit_x(display_bit_x)
                    value = (pattern >> (3 - part)) & 1
                    changes.extend(edit.set_bit(stored_bit_x, y, value))
        else:
            left = self.composite_pane._x_edge(cell_x) - self.composite_pane.origin[0]
            right = self.composite_pane._x_edge(cell_x + 1) - self.composite_pane.origin[0]
            cell_width = right - left
            if local_y < 0 or cell_width <= 0:
                return
            fraction = (local_x - left) / cell_width
            part = min(3, max(0, int(fraction * 4)))
            display_bit_x = cell_x * 4 + part
            key = (display_bit_x, y)
            if key in self._stroke_seen:
                return
            self._stroke_seen.add(key)
            value = 0 if erase else self.pencil_var.get()
            stored_bit_x = self._display_to_stored_bit_x(display_bit_x)
            changes = edit.set_bit(stored_bit_x, y, value)
        self._record_stroke_changes(changes)

    def _paint_mode6(self, event: tk.Event, erase: bool) -> None:
        edit = self.current_edit
        if edit is None:
            return
        if self._preview_choice("mode6") == "original":
            self.status_var.set(
                "The 1-bit pane is showing the read-only Original. Select Edited before drawing."
            )
            return
        if self.mode6_pane.scale * self.mode6_pane.x_zoom < self.mode6_pane.x_subsample:
            self.zoom_var.set("2x")
            self.render_all()
            self.status_var.set(
                "Zoom increased to 2× so every individual Mode-6 bit is addressable."
            )
            return
        coordinates = self.mode6_pane.raster_coordinates(event)
        if coordinates is None:
            return
        display_bit_x, y = coordinates
        key = (display_bit_x, y)
        if key in self._stroke_seen:
            return
        self._stroke_seen.add(key)
        self._hover_cell = None
        self._hover_bit = (display_bit_x, y)
        bit_x = self._display_to_stored_bit_x(display_bit_x)
        brush = 0 if erase else self.pencil_var.get()
        if len(edit.source_zero_mask) == edit.source_width * edit.height:
            source_x = bit_x if edit.source_depth == 1 else bit_x // 2
            source_offset = y * edit.source_width + source_x
            row = y * edit.bit_width
            sample_offsets = (
                (row + source_x,)
                if edit.source_depth == 1
                else (row + source_x * 2, row + source_x * 2 + 1)
            )
            before_signature = (
                edit.source_zero_mask[source_offset],
                edit.mask_locked,
                edit.mask_authored,
                tuple(edit.mask_reference_bits[offset] for offset in sample_offsets),
                tuple(
                    tuple(variant[offset] for offset in sample_offsets)
                    for variant in edit.phase_variants.values()
                ),
            )
            hardware = (
                hardware_palette_for_resource(self.archive, self.analysis.resource)
                if getattr(self, "analysis", None) is not None
                and self.analysis.image is not None
                else None
            )
            try:
                changes, _mask_changed, native_one_bit_zero = paint_mode6_dat_pixel(
                    edit,
                    bit_x,
                    y,
                    brush,
                    hardware,
                )
            except CompositeProjectError as exc:
                self.status_var.set(f"Mode-6 paint rejected: {exc}")
                return
            after_signature = (
                edit.source_zero_mask[source_offset],
                edit.mask_locked,
                edit.mask_authored,
                tuple(edit.mask_reference_bits[offset] for offset in sample_offsets),
                tuple(
                    tuple(variant[offset] for offset in sample_offsets)
                    for variant in edit.phase_variants.values()
                ),
            )
            family_changed = before_signature != after_signature
            if family_changed:
                if not hasattr(self, "_stroke_transparency_sources"):
                    self._stroke_transparency_sources = set()
                self._stroke_transparency_sources.add(source_offset)
                self.project.dirty = True
            self._record_stroke_changes(changes)
            if family_changed and not changes:
                self._schedule_edited_render()
            if native_one_bit_zero:
                self.status_var.set(
                    "Native 1-bit DAT index 0 is the transparent value; this format cannot store separate opaque black."
                )
        elif brush == TRANSPARENCY_BRUSH:
            self.status_var.set(
                "Transparency painting requires complete DAT index-zero mask metadata."
            )
        else:
            self._record_stroke_changes(edit.set_bit(bit_x, y, brush))

    def _paint(self, event: tk.Event, erase: bool, plane: str = "composite") -> None:
        if plane == "mode6":
            self._paint_mode6(event, erase)
        else:
            self._paint_composite(event, erase)

    def _stroke_start(
        self,
        event: tk.Event,
        erase: bool,
        plane: str = "composite",
    ) -> None:
        self._stroke_changes = {}
        self._stroke_seen = set()
        self._stroke_transparency_sources = set()
        self._stroke_family_before = None
        self._stroke_plane = plane
        edit = self.current_edit
        if (
            plane == "mode6"
            and edit is not None
            and len(edit.source_zero_mask) == edit.source_width * edit.height
        ):
            self._stroke_family_before = EditAction(
                edit.resource_index,
                {},
                phase_before=edit.signal_phase,
                variants_before={
                    phase: bytes(variant)
                    for phase, variant in edit.phase_variants.items()
                },
                enabled_before=edit.enabled_phases,
                fallback_before=edit.fallback_phase,
                mask_locked_before=edit.mask_locked,
                mask_authored_before=edit.mask_authored,
                source_zero_mask_before=bytes(edit.source_zero_mask),
                mask_reference_bits_before=bytes(edit.mask_reference_bits),
            )
        self._paint(event, erase, plane)

    def _stroke_move(
        self,
        event: tk.Event,
        erase: bool,
        plane: str = "composite",
    ) -> None:
        self._paint(event, erase, plane)

    def _stroke_end(self, _event: tk.Event) -> None:
        edit = self.current_edit
        family_before = getattr(self, "_stroke_family_before", None)
        family_committed = False
        if edit is not None and family_before is not None:
            variants_after = {
                phase: bytes(variant)
                for phase, variant in edit.phase_variants.items()
            }
            family_changed = (
                family_before.variants_before != variants_after
                or family_before.mask_locked_before != edit.mask_locked
                or family_before.mask_authored_before != edit.mask_authored
                or family_before.source_zero_mask_before
                != bytes(edit.source_zero_mask)
                or family_before.mask_reference_bits_before
                != bytes(edit.mask_reference_bits)
            )
            if family_changed:
                self.undo_stack.append(
                    EditAction(
                        edit.resource_index,
                        {},
                        phase_before=family_before.phase_before,
                        phase_after=edit.signal_phase,
                        variants_before=family_before.variants_before,
                        variants_after=variants_after,
                        enabled_before=family_before.enabled_before,
                        enabled_after=edit.enabled_phases,
                        fallback_before=family_before.fallback_before,
                        fallback_after=edit.fallback_phase,
                        mask_locked_before=family_before.mask_locked_before,
                        mask_locked_after=edit.mask_locked,
                        mask_authored_before=family_before.mask_authored_before,
                        mask_authored_after=edit.mask_authored,
                        source_zero_mask_before=family_before.source_zero_mask_before,
                        source_zero_mask_after=bytes(edit.source_zero_mask),
                        mask_reference_bits_before=family_before.mask_reference_bits_before,
                        mask_reference_bits_after=bytes(edit.mask_reference_bits),
                    )
                )
                self.redo_stack.clear()
                family_committed = True
                sources = len(getattr(self, "_stroke_transparency_sources", ()))
                self.status_var.set(
                    f"Painted {sources} DAT source pixel(s) through the Mode-6 pane as one undo action; transparency and every stored phase remain synchronized."
                )
        if edit is not None and self._stroke_changes and not family_committed:
            changes = {
                offset: pair
                for offset, pair in self._stroke_changes.items()
                if pair[0] != pair[1]
            }
            if changes:
                self.undo_stack.append(
                    EditAction(
                        edit.resource_index,
                        changes,
                        variant_phase=edit.signal_phase,
                    )
                )
                self.redo_stack.clear()
                plane_label = "1-bit" if self._stroke_plane == "mode6" else "Composite"
                self.status_var.set(
                    f"Painted {len(changes)} bit(s) through the {plane_label} pane in "
                    f"resource {edit.resource_id}; rough and artifact Composite previews updated, "
                    + (
                        "and linked VGA/EGA references remain independent."
                        if self.context.is_room_set
                        else "with live VGA/EGA/CGA previews."
                    )
                )
        self._stroke_changes = {}
        self._stroke_seen = set()
        self._stroke_transparency_sources = set()
        self._stroke_family_before = None

    def _hover_mode6(self, event: tk.Event) -> None:
        edit = self.current_edit
        if edit is None:
            return
        coordinates = self.mode6_pane.raster_coordinates(event)
        if coordinates is None:
            self._leave_mode6()
            return
        bit_x, y = coordinates
        self._hover_cell = None
        self._hover_bit = (bit_x, y)
        self._render_hover_markers()

        view = self._preview_choice("mode6")
        source_x = bit_x if edit.source_depth == 1 else bit_x // 2
        if (
            view == "original"
            and self.analysis is not None
            and self.analysis.image is not None
        ):
            hardware = hardware_palette_for_resource(
                self.archive,
                self.analysis.resource,
            )
            display_bits = self._orientation_display_bits(
                initial_mode6_bits(self.analysis.image, hardware)
            )
            bit = display_bits[y * edit.bit_width + bit_x]
            row = y * edit.bit_width
            pattern = 0
            for part in range(4):
                x = (bit_x // 4) * 4 + part
                pattern = (pattern << 1) | (
                    display_bits[row + x] if x < edit.bit_width else 0
                )
            display_mask = self._orientation_display_mask(
                index == 0 for index in self.analysis.image.pixels
            )
            transparent = bool(
                display_mask[y * edit.source_width + source_x]
            )
        else:
            display_bits = self._orientation_display_bits(edit.bits)
            bit = display_bits[y * edit.bit_width + bit_x]
            row = y * edit.bit_width
            pattern = 0
            for part in range(4):
                x = (bit_x // 4) * 4 + part
                pattern = (pattern << 1) | (
                    display_bits[row + x] if x < edit.bit_width else 0
                )
            display_mask = self._orientation_display_mask(edit.source_zero_mask)
            transparent = bool(
                display_mask
                and display_mask[y * edit.source_width + source_x]
            )
        dat_state = (
            "TRANSPARENT (DAT source index 0)"
            if transparent
            else "opaque DAT source index"
        )
        self.status_var.set(
            f"{view.title()} 1-bit pixel x={bit_x}, y={y} • value {bit} • "
            f"source x={source_x} • {dat_state} • "
            f"rough Composite cell {bit_x // 4} = {pattern:04b}; "
            "the signal pane shows its neighbor-dependent artifact color."
        )

    def _hover_composite(self, event: tk.Event) -> None:
        edit = self.current_edit
        if edit is None:
            return
        coordinates = self.composite_pane.raster_coordinates(event)
        if coordinates is None:
            self._leave_composite()
            return
        x, y = coordinates
        if 0 <= x < (edit.bit_width + 3) // 4 and 0 <= y < edit.height:
            self._hover_bit = None
            self._hover_cell = (x, y)
            self._render_hover_markers()
            view = self._preview_choice("composite")
            if (
                view == "original"
                and self.analysis is not None
                and self.analysis.image is not None
            ):
                hardware = hardware_palette_for_resource(
                    self.archive, self.analysis.resource
                )
                bits = self._orientation_display_bits(
                    initial_mode6_bits(self.analysis.image, hardware)
                )
            else:
                bits = self._orientation_display_bits(edit.bits)
            row = y * edit.bit_width
            pattern = 0
            for part in range(4):
                bit_x = x * 4 + part
                pattern = (pattern << 1) | (
                    bits[row + bit_x] if bit_x < edit.bit_width else 0
                )
            color = self.project.colors[pattern]
            profile_label = COMPOSITE_PROFILE_LABELS[self.project.composite_profile]
            self.status_var.set(
                f"{view.title()} Composite cell x={x}, y={y} • {profile_label} • "
                f"pattern {pattern:04b} (swatch {pattern:X}) • "
                f"rough RGB {color[0]}, {color[1]}, {color[2]} • HEX {format_hex_color(color)} • "
                "signal pane includes edge artifacts"
            )
        else:
            self._leave_composite()

    def undo(self) -> None:
        if not self.undo_stack:
            self.status_var.set("Nothing to undo.")
            return
        action = self.undo_stack.pop()
        if isinstance(action, BulkGifAction):
            self._restore_bulk_gif_action(action, after=False)
            self.redo_stack.append(action)
            self.project.dirty = True
            self._refresh_after_bulk_gif_action()
            self.status_var.set(
                f"Undid one bulk import of {action.file_count} Mode-6 GIF(s)."
            )
            return
        edit = self.project.edits[action.resource_index]
        self._restore_edit_action(edit, action, after=False)
        self.redo_stack.append(action)
        self.project.dirty = True
        if self.current_edit is edit:
            self._sync_phase_controls()
            self._render_edited()
        phase_detail = (
            f" and restored signal phase {action.phase_before}"
            if action.phase_before is not None and action.phase_before != action.phase_after
            else ""
        )
        change_count = len(action.changes) or sum(
            len(bits or b"") for bits in action.variants_before.values()
        )
        label = "phase-variant snapshot" if action.variants_before else "bit change"
        self.status_var.set(f"Undid {change_count} {label}(s){phase_detail}.")

    def redo(self) -> None:
        if not self.redo_stack:
            self.status_var.set("Nothing to redo.")
            return
        action = self.redo_stack.pop()
        if isinstance(action, BulkGifAction):
            self._restore_bulk_gif_action(action, after=True)
            self.undo_stack.append(action)
            self.project.dirty = True
            self._refresh_after_bulk_gif_action()
            self.status_var.set(
                f"Redid one bulk import of {action.file_count} Mode-6 GIF(s)."
            )
            return
        edit = self.project.edits[action.resource_index]
        self._restore_edit_action(edit, action, after=True)
        self.undo_stack.append(action)
        self.project.dirty = True
        if self.current_edit is edit:
            self._sync_phase_controls()
            self._render_edited()
        phase_detail = (
            f" and restored signal phase {action.phase_after}"
            if action.phase_before is not None and action.phase_before != action.phase_after
            else ""
        )
        change_count = len(action.changes) or sum(
            len(bits or b"") for bits in action.variants_after.values()
        )
        label = "phase-variant snapshot" if action.variants_after else "bit change"
        self.status_var.set(f"Redid {change_count} {label}(s){phase_detail}.")

    def _restore_bulk_gif_action(
        self,
        action: BulkGifAction,
        *,
        after: bool,
    ) -> None:
        snapshots: dict[int, CompositeEdit | None] = (
            action.edits_after if after else action.edits_before
        )
        for index, snapshot in snapshots.items():
            if snapshot is None:
                self.project.edits.pop(index, None)
            else:
                self.project.edits[index] = copy.deepcopy(snapshot)

    @staticmethod
    def _restore_edit_action(
        edit: CompositeEdit,
        action: EditAction,
        *,
        after: bool,
    ) -> None:
        snapshots = action.variants_after if after else action.variants_before
        mask_state = action.mask_locked_after if after else action.mask_locked_before
        mask_authored = (
            action.mask_authored_after if after else action.mask_authored_before
        )
        source_zero_mask = (
            action.source_zero_mask_after if after else action.source_zero_mask_before
        )
        mask_reference_bits = (
            action.mask_reference_bits_after
            if after
            else action.mask_reference_bits_before
        )
        enabled = action.enabled_after if after else action.enabled_before
        fallback = action.fallback_after if after else action.fallback_before
        active = action.phase_after if after else action.phase_before
        if mask_state is not None:
            edit.mask_locked = mask_state
        if mask_authored is not None:
            edit.mask_authored = mask_authored
        if source_zero_mask is not None:
            edit.source_zero_mask = bytearray(source_zero_mask)
        if mask_reference_bits is not None:
            edit.mask_reference_bits = bytearray(mask_reference_bits)
        if snapshots:
            for phase, payload in snapshots.items():
                if payload is None:
                    edit.phase_variants.pop(phase, None)
                else:
                    edit.phase_variants[phase] = bytearray(payload)
        else:
            phase = action.variant_phase
            if phase is None:
                phase = edit.signal_phase
            if phase not in edit.phase_variants:
                edit.activate_phase(phase, create=True, enable=True)
            target = edit.phase_variants[phase]
            for offset, (before, new_value) in action.changes.items():
                target[offset] = new_value if after else before
        if enabled is not None:
            edit.enabled_phases = enabled
        if fallback is not None:
            edit.fallback_phase = fallback
        if active is not None:
            if active not in edit.phase_variants:
                edit.activate_phase(active, create=True, enable=True)
            else:
                edit.signal_phase = active
                edit.bits = edit.phase_variants[active]
        elif edit.signal_phase not in edit.phase_variants:
            edit.signal_phase = edit.enabled_phases[0]
            edit.bits = edit.phase_variants[edit.signal_phase]
        else:
            edit.bits = edit.phase_variants[edit.signal_phase]
        edit.validate()

    def _select_pattern(self, index: int) -> None:
        self.pattern_var.set(index)
        color = self.project.colors[index]
        self.red_var.set(color[0])
        self.green_var.set(color[1])
        self.blue_var.set(color[2])
        self.hex_var.set(format_hex_color(color))
        profile_label = COMPOSITE_PROFILE_LABELS[self.project.composite_profile]
        self.selected_label_var.set(
            f"Selected {index:X} / {index:04b} • {profile_label}"
        )
        for position, button in enumerate(self._swatch_buttons):
            swatch = self.project.colors[position]
            luminance = swatch[0] * 0.299 + swatch[1] * 0.587 + swatch[2] * 0.114
            button.configure(
                background="#%02x%02x%02x" % swatch,
                foreground="#111111" if luminance > 150 else "#ffffff",
                activebackground="#%02x%02x%02x" % swatch,
                relief=tk.SUNKEN if position == index else tk.RAISED,
                borderwidth=4 if position == index else 2,
            )

    def apply_rgb(self) -> None:
        try:
            color = (int(self.red_var.get()), int(self.green_var.get()), int(self.blue_var.get()))
            self.project.set_color(self.pattern_var.get(), color)
        except (ValueError, tk.TclError, CompositeProjectError) as exc:
            messagebox.showerror("Invalid RGB color", str(exc), parent=self)
            return
        self._select_pattern(self.pattern_var.get())
        self._render_edited()

    def apply_hex(self) -> None:
        try:
            color = parse_hex_color(self.hex_var.get())
            self.project.set_color(self.pattern_var.get(), color)
        except (ValueError, tk.TclError, CompositeProjectError) as exc:
            messagebox.showerror("Invalid HEX color", str(exc), parent=self)
            return
        self._select_pattern(self.pattern_var.get())
        self._render_edited()

    def choose_color(self, index: int | None = None) -> None:
        if index is not None:
            self._select_pattern(index)
        current = self.project.colors[self.pattern_var.get()]
        _rgb, value = colorchooser.askcolor(
            color="#%02x%02x%02x" % current,
            title=f"Composite swatch {self.pattern_var.get():X} / {self.pattern_var.get():04b}",
            parent=self,
        )
        if value:
            color = parse_hex_color(value)
            self.project.set_color(self.pattern_var.get(), color)
            self._select_pattern(self.pattern_var.get())
            self._render_edited()

    def choose_transparency_display_color(self) -> None:
        current = parse_hex_color(self.transparency_color_var.get())
        _rgb, value = colorchooser.askcolor(
            color=self.transparency_color_var.get(),
            title="Select the editor display color for transparent DAT pixels",
            parent=self,
        )
        if not value:
            return
        color = parse_hex_color(value)
        hex_color = "#%02x%02x%02x" % color
        self.transparency_color_var.set(hex_color)
        luminance = sum(color) / 3
        self.transparency_color_button.configure(
            background=hex_color,
            activebackground=hex_color,
            foreground="#111111" if luminance > 150 else "#ffffff",
            activeforeground="#111111" if luminance > 150 else "#ffffff",
        )
        if color != current:
            self._render_target_transformed_previews(self._zoom())
            self.status_var.set(
                f"Transparent DAT pixels are displayed as {hex_color}; this display color is not saved into the DAT."
            )

    def reset_palette(self) -> None:
        profile = self.project.composite_profile
        label = COMPOSITE_PROFILE_LABELS[profile]
        if not messagebox.askyesno(
            "Reset palette",
            f"Restore all 16 {label} swatches to their DOSBox-X defaults?",
            parent=self,
        ):
            return
        self.project.reset_profile_palette(profile)
        self._select_pattern(self.pattern_var.get())
        self._render_edited()

    def _confirm_discard(self) -> bool:
        if not self.project.dirty:
            return True
        if self.orientation_workspace is not None:
            answer = messagebox.askyesnocancel(
                "Unexported ORIENT.DAT edits",
                "Export the complete edited ORIENT.DAT before continuing?",
                parent=self,
            )
            if answer is None:
                return False
            if answer and not self._export_complete_orient():
                return False
            return True
        answer = messagebox.askyesnocancel(
            "Unsaved phase-aware sidecar",
            "Save every image and stored phase variant to the .pdcproj sidecar before continuing?",
            parent=self,
        )
        if answer is None:
            return False
        if answer and not self.save_project():
            return False
        return True

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self.project = CompositeProject.for_archive(self.archive)
        self.cga_profile_var.set(self.project.composite_profile)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._select_pattern(self.pattern_var.get())
        self.set_analysis(self.analysis)
        self.status_var.set(
            "Started a new phase-aware sidecar; Ctrl+S will save every edited image and stored phase variant."
        )

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        filename = filedialog.askopenfilename(
            parent=self,
            title="Open phase-aware sidecar (.pdcproj)",
            initialdir=str(self.archive.path.parent),
            filetypes=(("Prince phase-aware sidecar", f"*{PROJECT_EXTENSION}"), ("JSON files", "*.json"), ("All files", "*.*")),
        )
        if not filename:
            return
        try:
            project = CompositeProject.load(filename)
            project.verify_archive(self.archive)
        except CompositeProjectError as exc:
            messagebox.showerror("Cannot open project", str(exc), parent=self)
            return
        self.project = project
        self.cga_profile_var.set(self.project.composite_profile)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._select_pattern(self.pattern_var.get())
        self.set_analysis(self.analysis)
        self.status_var.set(
            f"Opened phase-aware sidecar {Path(filename).name} with "
            f"{len(self.project.edits)} image record(s) and "
            f"{sum(len(edit.phase_variants) for edit in self.project.edits.values())} stored phase variant(s). "
            "Use the DAT image selector above to move between them."
        )

    def _same_as_loaded_project(self, destination: Path) -> bool:
        if self.project.path is None:
            return False
        try:
            return destination.resolve() == self.project.path.resolve()
        except OSError:
            return destination.absolute() == self.project.path.absolute()

    def _confirm_sidecar_destination(self, destination: Path) -> bool:
        """Prevent a new/unloaded project from silently erasing stored images."""

        if not destination.exists() or self._same_as_loaded_project(destination):
            return True
        try:
            existing = CompositeProject.load(destination)
            lost_ids = sidecar_resource_ids_lost_by_replacement(
                existing, self.project
            )
        except CompositeProjectError as exc:
            messagebox.showerror(
                "Existing sidecar not replaced",
                f"{destination.name} already exists, but it cannot safely be replaced:\n\n{exc}\n\n"
                "Choose another filename, or open the existing sidecar first if you intend to continue it.",
                parent=self,
            )
            return False
        if lost_ids:
            preview = ", ".join(str(resource_id) for resource_id in lost_ids[:12])
            if len(lost_ids) > 12:
                preview += ", …"
            messagebox.showerror(
                "Existing multi-image sidecar not replaced",
                f"{destination.name} contains {len(existing.edits)} image record(s). "
                f"Replacing it from this project would discard {len(lost_ids)} image(s): {preview}.\n\n"
                "Open that sidecar first and then save it, or choose a new filename. "
                "Save As does not merge unrelated project sessions.",
                parent=self,
            )
            return False
        return messagebox.askyesno(
            "Replace existing sidecar?",
            f"{destination.name} already contains {len(existing.edits)} image record(s).\n\n"
            "Replace it with the complete current multi-image project?",
            parent=self,
        )

    def save_project(self, save_as: bool = False) -> bool:
        destination = self.project.path
        if save_as or destination is None:
            destination_text = filedialog.asksaveasfilename(
                parent=self,
                title="Save every phase variant to sidecar (.pdcproj)",
                initialdir=str(self.archive.path.parent),
                initialfile=f"{self.archive.path.stem}_phase_aware{PROJECT_EXTENSION}",
                defaultextension=PROJECT_EXTENSION,
                filetypes=(("Prince phase-aware sidecar", f"*{PROJECT_EXTENSION}"), ("All files", "*.*")),
            )
            if not destination_text:
                return False
            destination = Path(destination_text)
        if not self._confirm_sidecar_destination(destination):
            return False
        try:
            saved = self.project.save(destination)
        except (OSError, CompositeProjectError) as exc:
            messagebox.showerror("Phase-aware sidecar save failed", str(exc), parent=self)
            return False
        self._refresh_project_summary()
        stored_variants = sum(
            len(edit.phase_variants) for edit in self.project.edits.values()
        )
        enabled_variants = sum(
            len(edit.enabled_phases) for edit in self.project.edits.values()
        )
        self.status_var.set(
            f"Saved {len(self.project.edits)} image record(s), {stored_variants} stored P0–P3 "
            f"variant(s), and {enabled_variants} enabled runtime variant(s) to {saved.name}."
        )
        return True

    def export_phase_manifest(self) -> None:
        if not self.project.edits:
            messagebox.showinfo(
                "Export runtime manifest",
                "Open at least one editable image before exporting a phase-aware manifest.",
                parent=self,
            )
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export lossless phase-aware runtime manifest",
            initialdir=str(self.archive.path.parent),
            initialfile=f"{self.archive.path.stem}_phase_manifest.json",
            defaultextension=".json",
            filetypes=(("Phase-aware JSON manifest", "*.json"), ("All files", "*.*")),
        )
        if not filename:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            path, resources, variants = write_phase_manifest(
                self.archive,
                self.project,
                filename,
            )
        except (OSError, CompositeProjectError) as exc:
            messagebox.showerror("Manifest export failed", str(exc), parent=self)
            return
        finally:
            self.configure(cursor="")
        self.status_var.set(
            f"Exported {variants} enabled phase variant(s) across {resources} resource "
            f"families to {path.name}; exact bits, source indices, LZG payloads, masks, and hashes are included."
        )

    def _export_complete_orient(self) -> bool:
        workspace = self.orientation_workspace
        if workspace is None:
            return False
        initial = workspace.orient.path.with_name("ORIENT-EDITED.DAT")
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export complete V22 ORIENT.DAT",
            initialdir=str(initial.parent),
            initialfile=initial.name,
            defaultextension=".DAT",
            filetypes=(("Prince DAT files", "*.DAT *.dat"), ("All files", "*.*")),
        )
        if not filename:
            return False
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            target, changed, digest = workspace.export(filename)
        except (CompositeProjectError, DatFormatError, OSError, ValueError) as exc:
            messagebox.showerror("V22 export failed", str(exc), parent=self)
            return False
        finally:
            self.configure(cursor="")
        self._refresh_project_summary()
        self.status_var.set(
            f"Exported complete {target.name}: {changed} changed resource(s), SHA-256 {digest}."
        )
        messagebox.showinfo(
            "V22 export verified",
            f"Complete 889-resource ORIENT.DAT written to:\n{target}\n\n"
            f"Changed images: {changed}\nSHA-256: {digest}",
            parent=self,
        )
        return True

    def save_patched(self) -> bool | None:
        if self.orientation_workspace is not None:
            return self._export_complete_orient()
        if self.project.dirty:
            answer = messagebox.askyesnocancel(
                "Save all phase variants first?",
                "Save every image and stored phase variant to the recoverable .pdcproj sidecar "
                "before creating the fallback-only patched DAT?",
                parent=self,
            )
            if answer is None:
                return
            if answer and not self.save_project():
                return
        if self.context.is_room_set:
            warning = (
                f"A new {self.archive.path.name} CGA target will be created; the opened source is "
                "protected from overwrite.\n\n"
                "Only the C archive is rebuilt. The linked EGA and VGA archives are read-only, "
                "independent files and cannot be changed by this operation.\n\n"
                "Changed CGA images are recompressed with Prince's LZG codec. The Old/New CGA RGB "
                "swatches remain preview/project values because the DOS game has no field for them."
            )
        else:
            warning = (
                "A new DAT will be created; the opened source is protected from overwrite.\n\n"
                "Changed images are recompressed with Prince's LZG codec. VGA/EGA reference colors may "
                "change where the CGA translation has more than one inverse source index.\n\n"
                "The Old/New CGA RGB swatches are preview/project values; the DOS game has no field for "
                "the DOSBox-X-derived composite palettes, so those RGB values stay in the sidecar."
            )
        warning += (
            "\n\nPhase-family warning: this legacy DAT writes only each image's selected DAT "
            "fallback variant. Use Ctrl+S / Save phase-aware sidecar to retain every stored "
            "P0–P3 variant, and export the runtime manifest for game-side phase selection."
        )
        if not messagebox.askokcancel(
            "Create patched DAT",
            warning,
            parent=self,
        ):
            return
        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Save patched Prince DAT as",
            initialdir=str(self.archive.path.parent),
            initialfile=f"{self.archive.path.stem}_composite.DAT",
            defaultextension=".DAT",
            filetypes=(("Prince DAT files", "*.DAT *.dat"), ("All files", "*.*")),
        )
        if not filename:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            path, changed = write_patched_dat(self.archive, self.project, filename)
        except (OSError, CompositeProjectError) as exc:
            messagebox.showerror("DAT save failed", str(exc), parent=self)
            return
        finally:
            self.configure(cursor="")
        messagebox.showinfo(
            "Patched DAT created",
            f"Created {path}\n\n{changed} image resource(s) changed and LZG-compressed. "
            "The source DAT was not modified.",
            parent=self,
        )
        self.status_var.set(f"Created verified patched DAT {path.name} ({changed} changed image resource(s)).")

    def close(self) -> None:
        self._stop_motion_preview(restore=True)
        if self._converter_dialog is not None and self._converter_dialog.winfo_exists():
            self._converter_dialog.close()
        if not self._confirm_discard():
            return
        if self.on_close_callback is not None:
            self.on_close_callback(self)
        self.destroy()
