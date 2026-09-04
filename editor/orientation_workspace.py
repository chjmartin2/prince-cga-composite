"""V22 dedicated-orientation workspace model.

The original Prince 1.3 actor DAT is a read-only visual reference.  Edits are
made only to the matching right/P0 and left/P0 resources in a complete
``ORIENT.DAT`` companion, whose layout is part of the V22 runtime ABI.
"""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterable, Literal, Sequence

from composite_converter import (
    CONVERSION_EXHAUSTIVE,
    ConversionResult,
    ConversionSettings,
    DITHER_NONE,
    QUALITY_HIGH,
    convert_raster_to_exhaustive,
)
from composite_project import (
    CompositeEdit,
    CompositeProject,
    CompositeProjectError,
    initial_mode6_bits,
    rebuild_dat,
    replacement_contents,
    source_pixels_for_edit,
)
from composite_signal import render_composite_artifacts
from prince_dat import (
    COMPOSITE_PROFILE_NEW,
    DatArchive,
    DatFormatError,
    DecodedImage,
    PrincePalette,
    RenderedRaster,
    hardware_palette_for_resource,
    render_display_mode,
)


Direction = Literal["right", "left"]


@dataclass(frozen=True)
class OrientationTable:
    name: str
    archive: str
    header_id: int
    source_first: int
    count: int
    right_first: int
    left_first: int
    context: str = ""

    @property
    def resource_ids(self) -> tuple[int, ...]:
        ids = (self.header_id,)
        if self.right_first:
            ids += tuple(range(self.right_first, self.right_first + self.count))
        if self.left_first:
            ids += tuple(range(self.left_first, self.left_first + self.count))
        return ids


TABLES = (
    OrientationTable("Kid right", "KID", 1000, 401, 219, 1001, 0),
    OrientationTable("Kid left", "KID", 2000, 401, 219, 0, 2001),
    OrientationTable("Guard", "GUARD", 3000, 751, 34, 3001, 3035, "Dungeon"),
    OrientationTable("Guard", "GUARD", 4000, 751, 34, 4001, 4035, "Palace"),
    OrientationTable("Fat guard", "FAT", 5000, 751, 34, 5001, 5035),
    OrientationTable("Vizier", "VIZIER", 6000, 751, 34, 6001, 6035),
    OrientationTable("PV 800", "PV", 7000, 801, 17, 7001, 7018),
    OrientationTable("PV 850", "PV", 8000, 851, 38, 8001, 8039),
    OrientationTable("PV 900", "PV", 9000, 901, 30, 9001, 9031),
)

EXPECTED_ORIENT_IDS = tuple(resource_id for table in TABLES for resource_id in table.resource_ids)
EXPECTED_ORIENT_RESOURCE_COUNT = 889
STANDARD_PRINCE13_SOURCE_SHA256 = {
    "KID": "2eaa798041c090a6d54cd0dce4ae770e3da400ef95540cec7ed0ff9db5c2af73",
    "GUARD": "dcedc140dcab0945dea02d24c248642cbff25f1b1288808ffd71a70fc529c5cc",
    "FAT": "83f05175eb614552e0db9b5dc4dc8136cb32e3ce90464fa80ea8b2f0e2d6c1bb",
    "VIZIER": "dfe2725b83dea22538a4dd0137f64e0013175375952654b2c5305c1c1ffe3558",
    "PV": "418be33393e8ae25b724670d74f9b1fd6f1fd2eef38639e2f679701ddb8a4df2",
}

EXHAUSTIVE_P0_SETTINGS = ConversionSettings(
    dither=DITHER_NONE,
    dither_amount=0,
    serpentine=True,
    bayer_size=4,
    brightness=0,
    contrast=0,
    saturation=100,
    gamma=1.0,
    color_emphasis=100,
    detail=100,
    quality=QUALITY_HIGH,
    phase_offset=0,
    preserve_zero=True,
)


@dataclass(frozen=True)
class OrientationPair:
    table: OrientationTable
    ordinal: int
    source_resource_id: int
    right_resource_id: int
    left_resource_id: int

    @property
    def label(self) -> str:
        context = f" / {self.table.context}" if self.table.context else ""
        return f"{self.table.name}{context}: source {self.source_resource_id}"


def archive_family(path: str | Path) -> str:
    stem = Path(path).stem.upper()
    for family in ("GUARD", "VIZIER", "KID", "FAT", "PV"):
        if stem == family or stem.startswith(family + "_") or stem.startswith(family + "-"):
            return family
    return stem


def uses_v22_workspace(path: str | Path) -> bool:
    """Return whether the normal Editor command must use the V22 workflow."""

    return archive_family(path) in {"KID", "GUARD", "FAT", "VIZIER", "PV"}


def reverse_mode6_cga_pixel_rows(
    bits: Sequence[int], width: int, height: int, group_width: int = 2
) -> bytearray:
    """Reverse Prince source-pixel groups without reversing their two bits."""

    if group_width not in (1, 2) or width % group_width or len(bits) != width * height:
        raise CompositeProjectError("Right-facing Mode-6 data has incomplete source-pixel rows.")
    output = bytearray()
    for y in range(height):
        row = bits[y * width : (y + 1) * width]
        groups = [row[x : x + group_width] for x in range(0, width, group_width)]
        for group in reversed(groups):
            output.extend(group)
    return output


def mirror_raster(source: RenderedRaster) -> RenderedRaster:
    pixels = bytearray(len(source.pixels))
    stride = source.channels
    for y in range(source.height):
        for x in range(source.width):
            src = (y * source.width + x) * stride
            dst = (y * source.width + source.width - 1 - x) * stride
            pixels[dst : dst + stride] = source.pixels[src : src + stride]
    return RenderedRaster(source.width, source.height, bytes(pixels), stride, source.mode)


def mirror_mask(mask: Sequence[bool], width: int, height: int) -> tuple[bool, ...]:
    if len(mask) != width * height:
        raise CompositeProjectError("Transparency mask dimensions are inconsistent.")
    return tuple(
        bool(mask[y * width + width - 1 - x])
        for y in range(height)
        for x in range(width)
    )


class V22OrientationWorkspace:
    """Validated linked view of one original actor DAT and full ORIENT.DAT."""

    def __init__(
        self,
        source: DatArchive,
        orient: DatArchive,
        *,
        require_standard_source: bool = True,
    ) -> None:
        self.source = source
        self.orient = orient
        self.family = archive_family(source.path)
        self.tables = tuple(table for table in TABLES if table.archive == self.family)
        if not self.tables:
            raise CompositeProjectError(
                "V22 Runtime Workspace supports KID.DAT, GUARD.DAT, FAT.DAT, "
                "VIZIER.DAT, and PV.DAT. Skeleton and Shadow stay on shared native paths."
            )
        # KID is intentionally allowed to be the user's existing/custom game
        # archive. Its complete 401-619 map and per-frame geometry are the
        # compatibility contract; a stock-file hash adds no runtime safety and
        # prevents the intended custom-art workflow.
        if require_standard_source and self.family != "KID":
            expected = STANDARD_PRINCE13_SOURCE_SHA256[self.family]
            actual = hashlib.sha256(source.data).hexdigest()
            if actual != expected:
                raise CompositeProjectError(
                    f"{source.path.name} is not the standard Prince 1.3 {self.family}.DAT "
                    f"reference (SHA-256 {actual})."
                )
        self._validate_orient_layout()
        self.project = CompositeProject.for_archive(orient)
        self.pairs = tuple(self._build_pairs())
        self._pair_by_key = {
            (pair.table.header_id, pair.source_resource_id): pair for pair in self.pairs
        }
        self._validate_pairs()

    @classmethod
    def open(
        cls,
        source: str | Path,
        orient: str | Path,
        *,
        require_standard_source: bool = True,
    ) -> "V22OrientationWorkspace":
        return cls(
            DatArchive.open(source),
            DatArchive.open(orient),
            require_standard_source=require_standard_source,
        )

    def _validate_orient_layout(self) -> None:
        ids = tuple(resource.resource_id for resource in self.orient.resources)
        if len(ids) != EXPECTED_ORIENT_RESOURCE_COUNT or ids != EXPECTED_ORIENT_IDS:
            raise CompositeProjectError(
                "ORIENT.DAT is not the complete V22 companion: expected the nine fixed "
                "table headers and all 880 images in runtime order."
            )
        if not all(resource.checksum_ok for resource in self.orient.resources):
            raise CompositeProjectError("ORIENT.DAT contains a resource with a bad checksum.")
        for table in TABLES:
            header = self.orient.resource_by_id(table.header_id)
            if header is None or len(header.data) != 100:
                raise CompositeProjectError(f"ORIENT table {table.header_id} has no 100-byte header.")
            expected_count = table.count if table.left_first == 0 or table.right_first == 0 else table.count * 2
            if header.data[0] != expected_count:
                raise CompositeProjectError(
                    f"ORIENT table {table.header_id} declares {header.data[0]} images; "
                    f"V22 requires {expected_count}."
                )

    def _build_pairs(self) -> Iterable[OrientationPair]:
        if self.family == "KID":
            right, left = self.tables
            for ordinal in range(right.count):
                yield OrientationPair(
                    right,
                    ordinal,
                    right.source_first + ordinal,
                    right.right_first + ordinal,
                    left.left_first + ordinal,
                )
            return
        for table in self.tables:
            for ordinal in range(table.count):
                yield OrientationPair(
                    table,
                    ordinal,
                    table.source_first + ordinal,
                    table.right_first + ordinal,
                    table.left_first + ordinal,
                )

    def _analysis(self, archive: DatArchive, resource_id: int):
        analysis = archive.analysis_by_id(resource_id)
        if analysis is None or analysis.image is None:
            raise CompositeProjectError(f"Resource {resource_id} is missing or is not an image.")
        return analysis

    def _validate_pairs(self) -> None:
        for pair in self.pairs:
            source = self._analysis(self.source, pair.source_resource_id).image
            right = self._analysis(self.orient, pair.right_resource_id).image
            left = self._analysis(self.orient, pair.left_resource_id).image
            assert source is not None and right is not None and left is not None
            geometry = (source.width, source.height, source.bits)
            if geometry != (right.width, right.height, right.bits) or geometry != (
                left.width,
                left.height,
                left.bits,
            ):
                raise CompositeProjectError(
                    f"V22 pair for source {pair.source_resource_id} has mismatched geometry."
                )

    def pair(self, source_resource_id: int, *, context: str = "") -> OrientationPair:
        candidates = [pair for pair in self.pairs if pair.source_resource_id == source_resource_id]
        if context:
            candidates = [pair for pair in candidates if pair.table.context.lower() == context.lower()]
        if len(candidates) != 1:
            raise CompositeProjectError(
                f"Source resource {source_resource_id} requires a unique V22 mapping/context."
            )
        return candidates[0]

    def target_analysis(self, pair: OrientationPair, direction: Direction):
        resource_id = pair.right_resource_id if direction == "right" else pair.left_resource_id
        return self._analysis(self.orient, resource_id)

    def hardware_palette(self, pair: OrientationPair) -> PrincePalette:
        analysis = self.target_analysis(pair, "right")
        palette = hardware_palette_for_resource(self.orient, analysis.resource)
        if palette is None:
            raise CompositeProjectError(f"ORIENT table {pair.table.header_id} has no hardware palette.")
        return palette

    def edit(self, pair: OrientationPair, direction: Direction) -> CompositeEdit:
        analysis = self.target_analysis(pair, direction)
        edit = self.project.edit_for_image(self.orient, analysis.resource.index, analysis.image)
        edit.signal_phase = 0
        edit.enabled_phases = (0,)
        edit.fallback_phase = 0
        edit.phase_variants = {0: edit.bits}
        edit.mask_locked = True
        edit.validate()
        return edit

    def source_raster(
        self, pair: OrientationPair, *, transparent: bool = False
    ) -> RenderedRaster:
        source = self._analysis(self.source, pair.source_resource_id).image
        assert source is not None
        return render_display_mode(
            source,
            "vga",
            self.hardware_palette(pair),
            transparent_zero=transparent,
        )

    def runtime_bits(self, pair: OrientationPair, direction: Direction) -> bytearray:
        edit = self.edit(pair, direction)
        bits = bytearray(edit.variant_bits(0))
        return (
            reverse_mode6_cga_pixel_rows(
                bits,
                edit.bit_width,
                edit.height,
                1 if edit.source_depth == 1 else 2,
            )
            if direction == "right"
            else bits
        )

    def runtime_raster(
        self,
        pair: OrientationPair,
        direction: Direction,
        *,
        transparent: bool = False,
    ) -> RenderedRaster:
        edit = self.edit(pair, direction)
        raster = render_composite_artifacts(
            self.runtime_bits(pair, direction),
            edit.bit_width,
            edit.height,
            COMPOSITE_PROFILE_NEW,
            phase_offset=0,
        )
        if not transparent:
            return raster
        source_analysis = self._analysis(self.source, pair.source_resource_id)
        source_image = source_analysis.image
        assert source_image is not None
        mask: Sequence[bool] = tuple(index == 0 for index in source_image.pixels)
        if direction == "right":
            mask = mirror_mask(mask, source_image.width, source_image.height)
        pixels = bytearray(raster.pixels)
        samples_per_pixel = edit.bit_width // source_image.width
        for y in range(source_image.height):
            for source_x in range(source_image.width):
                if not mask[y * source_image.width + source_x]:
                    continue
                shade = 200 if ((source_x // 4) + (y // 4)) & 1 else 232
                for part in range(samples_per_pixel):
                    bit_x = source_x * samples_per_pixel + part
                    offset = (y * edit.bit_width + bit_x) * 3
                    pixels[offset : offset + 3] = bytes((shade, shade, shade))
        return RenderedRaster(raster.width, raster.height, bytes(pixels), 3, raster.mode)

    def display_to_stored_x(self, edit: CompositeEdit, direction: Direction, x: int) -> int:
        if direction == "left":
            return x
        group_width = 1 if edit.source_depth == 1 else 2
        if not 0 <= x < edit.bit_width or edit.bit_width % group_width:
            raise CompositeProjectError("Display coordinate is outside a complete V22 image row.")
        group = x // group_width
        return (
            (edit.bit_width // group_width - 1 - group) * group_width
            + (x % group_width)
        )

    def set_display_bit(
        self, pair: OrientationPair, direction: Direction, x: int, y: int, value: int
    ) -> bool:
        edit = self.edit(pair, direction)
        stored_x = self.display_to_stored_x(edit, direction, x)
        before = bytearray(edit.bits)
        changes = edit.set_bit(stored_x, y, value)
        if changes:
            analysis = self.target_analysis(pair, direction)
            assert analysis.image is not None
            try:
                source_pixels_for_edit(
                    analysis.image,
                    edit,
                    self.hardware_palette(pair),
                    bits=edit.bits,
                )
            except CompositeProjectError:
                edit.bits[:] = before
                raise
            self.project.dirty = True
        return bool(changes)

    def generate_exhaustive(
        self,
        pair: OrientationPair,
        direction: Direction,
        *,
        progress=None,
        cancelled=None,
    ) -> ConversionResult:
        source_analysis = self._analysis(self.source, pair.source_resource_id)
        source_image = source_analysis.image
        assert source_image is not None
        edit = self.edit(pair, direction)
        source = self.source_raster(pair)
        base_mask = tuple(index == 0 for index in source_image.pixels)
        target = mirror_raster(source) if direction == "right" else source
        target_mask = (
            mirror_mask(base_mask, source_image.width, source_image.height)
            if direction == "right"
            else base_mask
        )
        result = convert_raster_to_exhaustive(
            target,
            edit.bit_width,
            edit.height,
            COMPOSITE_PROFILE_NEW,
            EXHAUSTIVE_P0_SETTINGS,
            source_zero_mask=target_mask,
            progress=progress,
            cancelled=cancelled,
        )
        stored = (
            reverse_mode6_cga_pixel_rows(
                result.bits,
                edit.bit_width,
                edit.height,
                1 if edit.source_depth == 1 else 2,
            )
            if direction == "right"
            else bytearray(result.bits)
        )
        previous_bits = bytearray(edit.bits)
        previous_mask = bytearray(edit.source_zero_mask)
        previous_reference = bytearray(edit.mask_reference_bits)
        edit.bits[:] = stored
        edit.phase_variants[0] = edit.bits
        edit.source_zero_mask = bytearray(base_mask)
        edit.mask_reference_bits = bytearray(initial_mode6_bits(source_image, self.hardware_palette(pair)))
        # The reference must follow the target image's representable stream,
        # while source_zero_mask deliberately follows the original silhouette.
        target_image = self.target_analysis(pair, direction).image
        assert target_image is not None
        edit.mask_reference_bits = initial_mode6_bits(target_image, self.hardware_palette(pair))
        edit.mask_locked = True
        try:
            edit.validate()
            source_pixels_for_edit(
                target_image,
                edit,
                self.hardware_palette(pair),
                bits=edit.bits,
            )
        except CompositeProjectError:
            edit.bits[:] = previous_bits
            edit.source_zero_mask = previous_mask
            edit.mask_reference_bits = previous_reference
            raise
        self.project.dirty = True
        return result

    def export(self, destination: str | Path) -> tuple[Path, int, str]:
        target = Path(destination)
        for protected in (self.source.path, self.orient.path):
            try:
                if target.resolve() == protected.resolve():
                    raise CompositeProjectError(
                        "V22 export is Save-As only and cannot overwrite either linked input DAT."
                    )
            except OSError:
                pass
        replacements = replacement_contents(self.orient, self.project)
        payload = rebuild_dat(self.orient, replacements)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            verification = DatArchive.open(temporary)
            ids = tuple(resource.resource_id for resource in verification.resources)
            if ids != EXPECTED_ORIENT_IDS or len(ids) != EXPECTED_ORIENT_RESOURCE_COUNT:
                raise CompositeProjectError("Exported ORIENT.DAT failed complete-layout verification.")
            if not all(resource.checksum_ok for resource in verification.resources):
                raise CompositeProjectError("Exported ORIENT.DAT failed checksum verification.")
            for index, edit in self.project.edits.items():
                analysis = verification.analysis_for_index(index)
                if analysis.image is None:
                    raise CompositeProjectError("An exported orientation resource no longer decodes.")
                palette = hardware_palette_for_resource(verification, analysis.resource)
                if initial_mode6_bits(analysis.image, palette) != edit.variant_bits(0):
                    raise CompositeProjectError(
                        f"Exported resource {edit.resource_id} failed LZG/translation round-trip verification."
                    )
            os.replace(temporary, target)
        except (OSError, DatFormatError):
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
        self.project.dirty = False
        return target, len(replacements), hashlib.sha256(payload).hexdigest()
