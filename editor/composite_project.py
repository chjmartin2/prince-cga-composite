"""Recoverable composite-edit projects and safe POP1 DAT write-back.

The sidecar keeps the editable 640-bit stream independent from the source DAT.
Writing a patched archive is always a Save-As operation and re-encodes only
changed image resources with Prince's 1 KiB-window LZG codec.
"""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
from typing import Sequence

from engine_phase_usage import (
    ENGINE_AUDIT_ID,
    EnginePhaseUsage,
    PHASE_POLICY_ENGINE,
    PHASE_POLICY_MANUAL,
    PHASE_POLICY_LABELS,
    shifted_runtime_phases,
    usage_for_archive_resource,
)
from prince_dat import (
    COMPOSITE_PROFILE_OLD,
    DEFAULT_COMPOSITE_PROFILE,
    DatArchive,
    DatFormatError,
    DecodedImage,
    DOSBOXX_CGA_COMPOSITE_PROFILES,
    ImageDecodeError,
    PrincePalette,
    RenderedRaster,
    decode_prince_image,
    hardware_palette_for_resource,
    mode6_bit_at,
    mode6_width,
)


PROJECT_KIND = "prince-dat-composite-project"
PROJECT_VERSION = 6
PROJECT_EXTENSION = ".pdcproj"
PHASE_MANIFEST_KIND = "prince-dat-phase-aware-manifest"
PHASE_MANIFEST_VERSION = 3

PHASES = (0, 1, 2, 3)
PHASE_PROFILE_FIXED = "fixed"
PHASE_PROFILE_PARITY_02 = "parity-0-2"
PHASE_PROFILE_PARITY_13 = "parity-1-3"
PHASE_PROFILE_ALL = "all-four"
PHASE_PROFILE_CUSTOM = "custom"
PHASE_PROFILE_LABELS = {
    PHASE_PROFILE_FIXED: "Fixed phase",
    PHASE_PROFILE_PARITY_02: "X parity: P0 + P2",
    PHASE_PROFILE_PARITY_13: "X parity: P1 + P3",
    PHASE_PROFILE_ALL: "All four phases",
    PHASE_PROFILE_CUSTOM: "Custom phases",
}
PHASE_PROFILE_PHASES = {
    PHASE_PROFILE_PARITY_02: (0, 2),
    PHASE_PROFILE_PARITY_13: (1, 3),
    PHASE_PROFILE_ALL: PHASES,
}


class CompositeProjectError(ValueError):
    """Raised for an invalid project or an edit that cannot be represented."""


def default_composite_palettes() -> dict[str, list[tuple[int, int, int]]]:
    """Return independent editable copies of every DOSBox-X CGA profile."""

    return {
        profile: list(colors)
        for profile, colors in DOSBOXX_CGA_COMPOSITE_PROFILES.items()
    }


def normalize_composite_palette(
    value: Sequence[Sequence[int]], *, label: str = "Composite palette"
) -> list[tuple[int, int, int]]:
    """Validate and normalize one 16-entry RGB composite palette."""

    try:
        colors = [tuple(int(component) for component in color) for color in value]
    except (TypeError, ValueError) as exc:
        raise CompositeProjectError(f"{label} must contain 16 RGB triples.") from exc
    if len(colors) != 16 or any(
        len(color) != 3 or any(not 0 <= component <= 255 for component in color)
        for color in colors
    ):
        raise CompositeProjectError(
            f"{label} must contain exactly 16 RGB triples in the range 0–255."
        )
    return colors


def format_hex_color(color: Sequence[int]) -> str:
    """Return an RGB triple as canonical uppercase ``#RRGGBB`` text."""

    if len(color) != 3 or any(not isinstance(value, int) or not 0 <= value <= 255 for value in color):
        raise CompositeProjectError("RGB colors must contain three integers in the range 0–255.")
    return f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"


def parse_hex_color(value: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB`` (or unprefixed ``RRGGBB``) into an RGB triple."""

    text = value.strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) != 6:
        raise CompositeProjectError(
            "HEX colors must use six digits in #RRGGBB form, for example #006300."
        )
    try:
        return tuple(int(text[position : position + 2], 16) for position in (0, 2, 4))
    except ValueError as exc:
        raise CompositeProjectError(
            "HEX colors must use only digits 0–9 and letters A–F in #RRGGBB form."
        ) from exc


def archive_sha256(archive: DatArchive) -> str:
    return hashlib.sha256(archive.data).hexdigest()


def pack_bits(bits: Sequence[int]) -> bytes:
    """Pack a byte-per-bit sequence MSB first."""

    output = bytearray((len(bits) + 7) // 8)
    for index, bit in enumerate(bits):
        if bit not in (0, 1):
            raise CompositeProjectError("The editable stream contains a value other than 0 or 1.")
        if bit:
            output[index // 8] |= 1 << (7 - (index & 7))
    return bytes(output)


def unpack_bits(packed: bytes, count: int) -> bytearray:
    if count < 0 or len(packed) != (count + 7) // 8:
        raise CompositeProjectError("Packed project bit count is inconsistent.")
    return bytearray(
        (packed[index // 8] >> (7 - (index & 7))) & 1
        for index in range(count)
    )


def initial_mode6_bits(
    image: DecodedImage, hardware_palette: PrincePalette | None
) -> bytearray:
    width = mode6_width(image)
    return bytearray(
        mode6_bit_at(image, x, y, hardware_palette)[0]
        for y in range(image.height)
        for x in range(width)
    )


@dataclass
class CompositeEdit:
    resource_index: int
    resource_id: int
    source_width: int
    height: int
    source_depth: int
    bit_width: int
    bits: bytearray
    signal_phase: int = 0
    phase_variants: dict[int, bytearray] = field(default_factory=dict)
    enabled_phases: tuple[int, ...] = ()
    fallback_phase: int | None = None
    phase_policy: str = PHASE_POLICY_MANUAL
    mask_locked: bool = False
    source_zero_mask: bytearray = field(default_factory=bytearray)
    mask_reference_bits: bytearray = field(default_factory=bytearray)
    mask_authored: bool = False

    def __post_init__(self) -> None:
        self.bits = bytearray(self.bits)
        normalized_variants = {
            int(phase): bytearray(variant)
            for phase, variant in self.phase_variants.items()
        }
        if not normalized_variants:
            normalized_variants[self.signal_phase] = self.bits
        elif self.signal_phase not in normalized_variants:
            normalized_variants[self.signal_phase] = self.bits
        self.phase_variants = normalized_variants
        self.bits = self.phase_variants[self.signal_phase]
        self.enabled_phases = self._normalize_phases(
            self.enabled_phases or (self.signal_phase,)
        )
        if self.fallback_phase is None:
            self.fallback_phase = self.signal_phase
        self.source_zero_mask = bytearray(self.source_zero_mask)
        self.mask_reference_bits = bytearray(self.mask_reference_bits)

    @staticmethod
    def _normalize_phases(phases: Sequence[int]) -> tuple[int, ...]:
        normalized = tuple(sorted({int(phase) for phase in phases}))
        if not normalized or any(phase not in PHASES for phase in normalized):
            raise CompositeProjectError(
                "A phase-aware edit must enable at least one carrier phase from 0 through 3."
            )
        return normalized

    @property
    def phase_profile(self) -> str:
        if len(self.enabled_phases) == 1:
            return PHASE_PROFILE_FIXED
        for profile, phases in PHASE_PROFILE_PHASES.items():
            if self.enabled_phases == phases:
                return profile
        return PHASE_PROFILE_CUSTOM

    @property
    def variant_phases(self) -> tuple[int, ...]:
        return tuple(sorted(self.phase_variants))

    def variant_bits(self, phase: int | None = None) -> bytearray:
        selected = self.signal_phase if phase is None else int(phase)
        try:
            return self.phase_variants[selected]
        except KeyError as exc:
            raise CompositeProjectError(
                f"Resource {self.resource_id} has no phase-{selected} variant."
            ) from exc

    def activate_phase(
        self,
        phase: int,
        *,
        create: bool = False,
        template_phase: int | None = None,
        enable: bool = True,
    ) -> bool:
        """Select one variant, optionally cloning a missing slot.

        Returns ``True`` when a new variant slot was created.  The public
        ``bits`` attribute remains an alias for the active slot so the legacy
        painting, rendering, and converter code can continue to operate on a
        byte-per-bit buffer.
        """

        phase = int(phase)
        if phase not in PHASES:
            raise CompositeProjectError("Carrier phase must be between 0 and 3.")
        created = False
        if phase not in self.phase_variants:
            if not create:
                raise CompositeProjectError(
                    f"Resource {self.resource_id} has no phase-{phase} variant."
                )
            template = self.signal_phase if template_phase is None else int(template_phase)
            self.phase_variants[phase] = bytearray(self.variant_bits(template))
            created = True
        self.signal_phase = phase
        self.bits = self.phase_variants[phase]
        if enable and phase not in self.enabled_phases:
            self.enabled_phases = self._normalize_phases((*self.enabled_phases, phase))
        return created

    def set_enabled_phases(
        self,
        phases: Sequence[int],
        *,
        create_missing: bool = True,
    ) -> tuple[int, ...]:
        """Set runtime phase coverage and return newly cloned phase slots."""

        normalized = self._normalize_phases(phases)
        created: list[int] = []
        template = self.signal_phase
        for phase in normalized:
            if phase not in self.phase_variants:
                if not create_missing:
                    raise CompositeProjectError(
                        f"Resource {self.resource_id} has no phase-{phase} variant."
                    )
                self.phase_variants[phase] = bytearray(self.variant_bits(template))
                created.append(phase)
        self.enabled_phases = normalized
        if self.signal_phase not in normalized:
            self.signal_phase = normalized[0]
            self.bits = self.phase_variants[self.signal_phase]
        if self.fallback_phase not in normalized:
            self.fallback_phase = normalized[0]
        return tuple(created)

    def set_variant_bits(
        self,
        phase: int,
        bits: Sequence[int],
        *,
        enable: bool = True,
        activate: bool = True,
    ) -> bool:
        """Replace one variant and return whether its slot was newly created."""

        phase = int(phase)
        replacement = bytearray(bits)
        if len(replacement) != self.bit_width * self.height:
            raise CompositeProjectError("Phase variant bit count is inconsistent.")
        if any(bit not in (0, 1) for bit in replacement):
            raise CompositeProjectError("Phase variant contains a value other than 0 or 1.")
        self.validate_mask_bits(replacement)
        created = phase not in self.phase_variants
        self.phase_variants[phase] = replacement
        if enable and phase not in self.enabled_phases:
            self.enabled_phases = self._normalize_phases((*self.enabled_phases, phase))
        if activate:
            self.signal_phase = phase
            self.bits = replacement
        elif self.signal_phase == phase:
            self.bits = replacement
        return created

    def source_pixel_for_bit_offset(self, offset: int) -> int:
        y, bit_x = divmod(offset, self.bit_width)
        source_x = bit_x if self.source_depth == 1 else bit_x // 2
        return y * self.source_width + source_x

    def bit_is_mask_locked(self, offset: int) -> bool:
        return bool(
            self.mask_locked
            and self.source_zero_mask
            and self.source_zero_mask[self.source_pixel_for_bit_offset(offset)]
        )

    def validate_mask_bits(self, bits: Sequence[int]) -> None:
        if not self.mask_locked or not self.source_zero_mask:
            return
        if len(self.mask_reference_bits) != self.bit_width * self.height:
            raise CompositeProjectError(
                "The phase-aware transparency-mask reference is missing or inconsistent."
            )
        for offset, value in enumerate(bits):
            if self.bit_is_mask_locked(offset) and value != self.mask_reference_bits[offset]:
                raise CompositeProjectError(
                    "The candidate changes a source index-zero mask pixel at "
                    f"Mode-6 offset {offset}. Disable mask locking only if that geometry change is intentional."
                )

    def locked_bit_constraints(self) -> tuple[int, ...] | None:
        """Return exact Mode-6 constraints for converter optimization.

        ``-1`` marks an editable bit. Protected source-index-zero pixels carry
        the original zero-mask reference value, allowing even unusual hardware
        tables whose index zero does not translate to digital ``00``.
        """

        if not self.mask_locked:
            return None
        self.validate()
        return tuple(
            self.mask_reference_bits[offset]
            if self.bit_is_mask_locked(offset)
            else -1
            for offset in range(self.bit_width * self.height)
        )

    def validate(self) -> None:
        if min(self.source_width, self.height, self.bit_width) <= 0:
            raise CompositeProjectError("Project image dimensions must be positive.")
        if self.source_depth not in (1, 4):
            raise CompositeProjectError(
                f"Composite editing does not support {self.source_depth}-bit resources."
            )
        expected_width = self.source_width if self.source_depth == 1 else self.source_width * 2
        if self.bit_width != expected_width:
            raise CompositeProjectError("Project bit width does not match its source image.")
        if self.signal_phase not in (0, 1, 2, 3):
            raise CompositeProjectError("Project composite signal phase must be between 0 and 3.")
        # Compatibility for callers from pre-phase-aware releases that changed
        # ``signal_phase`` directly as preview metadata.
        if self.signal_phase not in self.phase_variants:
            aliases = [
                phase for phase, variant in self.phase_variants.items() if variant is self.bits
            ]
            if len(self.phase_variants) == 1 and aliases:
                previous = aliases[0]
                self.phase_variants.pop(previous)
                self.phase_variants[self.signal_phase] = self.bits
                self.enabled_phases = tuple(
                    self.signal_phase if phase == previous else phase
                    for phase in self.enabled_phases
                )
                if self.fallback_phase == previous:
                    self.fallback_phase = self.signal_phase
            else:
                self.phase_variants[self.signal_phase] = bytearray(self.bits)
        self.bits = self.phase_variants[self.signal_phase]
        self.enabled_phases = self._normalize_phases(self.enabled_phases)
        if self.signal_phase not in self.enabled_phases:
            raise CompositeProjectError(
                "The active editor carrier phase must be enabled for this graphic family."
            )
        if any(phase not in self.phase_variants for phase in self.enabled_phases):
            raise CompositeProjectError("An enabled carrier phase has no stored graphic variant.")
        if self.fallback_phase not in self.enabled_phases:
            raise CompositeProjectError(
                "The legacy DAT fallback must be an enabled carrier phase."
            )
        if self.phase_policy not in PHASE_POLICY_LABELS:
            raise CompositeProjectError(
                f"Unknown phase-coverage policy: {self.phase_policy!r}."
            )
        expected_count = self.bit_width * self.height
        source_count = self.source_width * self.height
        if self.source_zero_mask and len(self.source_zero_mask) != source_count:
            raise CompositeProjectError("Source index-zero mask dimensions are inconsistent.")
        if self.mask_reference_bits and len(self.mask_reference_bits) != expected_count:
            raise CompositeProjectError("Transparency-mask reference dimensions are inconsistent.")
        if self.mask_locked and bool(self.source_zero_mask) != bool(self.mask_reference_bits):
            raise CompositeProjectError("A locked transparency mask requires its reference bits.")
        for phase, variant in self.phase_variants.items():
            if phase not in PHASES:
                raise CompositeProjectError("Project contains an invalid carrier-phase slot.")
            if len(variant) != expected_count:
                raise CompositeProjectError(
                    f"Phase-{phase} bit stream length does not match its dimensions."
                )
            if any(bit not in (0, 1) for bit in variant):
                raise CompositeProjectError(
                    f"Phase-{phase} bit stream contains an invalid value."
                )
            self.validate_mask_bits(variant)

    def pattern_at(self, cell_x: int, y: int) -> int:
        if not (0 <= cell_x < (self.bit_width + 3) // 4 and 0 <= y < self.height):
            raise IndexError("Composite cell is outside the edited image.")
        pattern = 0
        row = y * self.bit_width
        for part in range(4):
            bit_x = cell_x * 4 + part
            pattern = (pattern << 1) | (
                self.bits[row + bit_x] if bit_x < self.bit_width else 0
            )
        return pattern

    def set_pattern(self, cell_x: int, y: int, pattern: int) -> list[tuple[int, int, int]]:
        """Set a four-bit cell and return ``(offset, before, after)`` changes."""

        if not 0 <= pattern <= 15:
            raise ValueError("Composite pattern must be between 0 and 15.")
        if not (0 <= cell_x < (self.bit_width + 3) // 4 and 0 <= y < self.height):
            return []
        changes: list[tuple[int, int, int]] = []
        row = y * self.bit_width
        for part in range(4):
            bit_x = cell_x * 4 + part
            if bit_x >= self.bit_width:
                continue
            offset = row + bit_x
            after = (pattern >> (3 - part)) & 1
            if self.bit_is_mask_locked(offset):
                continue
            before = self.bits[offset]
            if before != after:
                self.bits[offset] = after
                changes.append((offset, before, after))
        return changes

    def set_bit(self, bit_x: int, y: int, value: int) -> list[tuple[int, int, int]]:
        if value not in (0, 1):
            raise ValueError("Pencil value must be zero or one.")
        if not (0 <= bit_x < self.bit_width and 0 <= y < self.height):
            return []
        offset = y * self.bit_width + bit_x
        if self.bit_is_mask_locked(offset):
            return []
        before = self.bits[offset]
        if before == value:
            return []
        self.bits[offset] = value
        return [(offset, before, value)]


@dataclass
class CompositeProject:
    source_name: str
    source_size: int
    source_sha256: str
    composite_profile: str = DEFAULT_COMPOSITE_PROFILE
    profile_colors: dict[str, list[tuple[int, int, int]]] = field(
        default_factory=default_composite_palettes
    )
    edits: dict[int, CompositeEdit] = field(default_factory=dict)
    path: Path | None = None
    dirty: bool = False

    @property
    def colors(self) -> list[tuple[int, int, int]]:
        """Editable RGB table for the currently selected CGA model."""

        self._validate_profiles()
        return self.profile_colors[self.composite_profile]

    @colors.setter
    def colors(self, value: Sequence[Sequence[int]]) -> None:
        self._validate_profiles()
        self.profile_colors[self.composite_profile] = normalize_composite_palette(value)

    def _validate_profiles(self) -> None:
        if self.composite_profile not in DOSBOXX_CGA_COMPOSITE_PROFILES:
            raise CompositeProjectError(
                f"Unknown composite CGA profile: {self.composite_profile!r}."
            )
        if set(self.profile_colors) != set(DOSBOXX_CGA_COMPOSITE_PROFILES):
            raise CompositeProjectError(
                "Project must contain both the Old CGA and New CGA composite palettes."
            )
        for profile, colors in tuple(self.profile_colors.items()):
            self.profile_colors[profile] = normalize_composite_palette(
                colors, label=f"{profile} composite palette"
            )

    def set_profile(self, profile: str) -> None:
        """Select the DOSBox-X CGA model without changing edited pixel patterns."""

        if profile not in DOSBOXX_CGA_COMPOSITE_PROFILES:
            raise CompositeProjectError(f"Unknown composite CGA profile: {profile!r}.")
        self._validate_profiles()
        if self.composite_profile != profile:
            self.composite_profile = profile
            self.dirty = True

    def reset_profile_palette(self, profile: str | None = None) -> None:
        """Restore one profile to its source-derived DOSBox-X defaults."""

        selected = profile or self.composite_profile
        if selected not in DOSBOXX_CGA_COMPOSITE_PROFILES:
            raise CompositeProjectError(f"Unknown composite CGA profile: {selected!r}.")
        defaults = list(DOSBOXX_CGA_COMPOSITE_PROFILES[selected])
        if self.profile_colors.get(selected) != defaults:
            self.profile_colors[selected] = defaults
            self.dirty = True

    @classmethod
    def for_archive(cls, archive: DatArchive) -> "CompositeProject":
        return cls(archive.path.name, len(archive.data), archive_sha256(archive))

    def verify_archive(self, archive: DatArchive) -> None:
        if self.source_size != len(archive.data) or self.source_sha256 != archive_sha256(archive):
            raise CompositeProjectError(
                "This sidecar belongs to a different source DAT. Open the exact original archive first."
            )

    def engine_usage_for_edit(self, edit: CompositeEdit):
        """Return the original-engine audit record associated with an edit."""

        return usage_for_archive_resource(self.source_name, edit.resource_id)

    def validate_phase_policy(self, edit: CompositeEdit) -> None:
        """Ensure an automatic edit still matches the audited engine contract."""

        if edit.phase_policy != PHASE_POLICY_ENGINE:
            return
        usage = self.engine_usage_for_edit(edit)
        if usage is None:
            raise CompositeProjectError(
                "Automatic original-engine coverage is unavailable for this archive/resource. "
                "Use the manual policy for custom graphics."
            )
        if edit.enabled_phases != usage.required_phases:
            required = ", ".join(f"P{phase}" for phase in usage.required_phases)
            raise CompositeProjectError(
                "Automatic original-engine coverage for resource "
                f"{edit.resource_id} must enable exactly {required}."
            )

    def apply_engine_phase_policy(
        self, edit: CompositeEdit
    ) -> tuple[EnginePhaseUsage, tuple[int, ...]]:
        """Apply the audited phase set and return ``(usage, cloned_slots)``."""

        usage = self.engine_usage_for_edit(edit)
        if usage is None:
            raise CompositeProjectError(
                "No original DOS engine audit is available for this archive/resource."
            )
        created = edit.set_enabled_phases(usage.required_phases, create_missing=True)
        edit.phase_policy = PHASE_POLICY_ENGINE
        self.validate_phase_policy(edit)
        return usage, created

    def edit_for_image(
        self,
        archive: DatArchive,
        resource_index: int,
        image: DecodedImage,
    ) -> CompositeEdit:
        self.verify_archive(archive)
        if image.bits not in (1, 4):
            raise CompositeProjectError(
                f"Composite editing supports 1-bit and 4-bit resources, not {image.bits}-bit."
            )
        resource = archive.resources[resource_index]
        existing = self.edits.get(resource_index)
        if existing is not None:
            existing.validate()
            self.validate_phase_policy(existing)
            identity = (
                existing.resource_id,
                existing.source_width,
                existing.height,
                existing.source_depth,
            )
            expected = (resource.resource_id, image.width, image.height, image.bits)
            if identity != expected:
                raise CompositeProjectError("Project image metadata no longer matches the source DAT.")
            palette = hardware_palette_for_resource(archive, resource)
            expected_zero_mask = bytearray(index == 0 for index in image.pixels)
            expected_reference = initial_mode6_bits(image, palette)
            if (
                not existing.mask_authored
                and existing.source_zero_mask
                and existing.source_zero_mask != expected_zero_mask
            ):
                raise CompositeProjectError(
                    "Project transparency-mask metadata no longer matches the source DAT."
                )
            if (
                not existing.mask_authored
                and existing.mask_reference_bits
                and existing.mask_reference_bits != expected_reference
            ):
                raise CompositeProjectError(
                    "Project transparency-mask reference no longer matches the source DAT."
                )
            # Versions 1–3 did not serialize mask metadata. Attach it without
            # changing their unlocked behavior so the designer can opt in.
            if not existing.mask_authored:
                existing.source_zero_mask = expected_zero_mask
                existing.mask_reference_bits = expected_reference
            existing.validate()
            return existing

        palette = hardware_palette_for_resource(archive, resource)
        original_bits = initial_mode6_bits(image, palette)
        usage = usage_for_archive_resource(archive.path.name, resource.resource_id)
        enabled_phases = usage.required_phases if usage is not None else (0,)
        initial_phase = enabled_phases[0]
        edit = CompositeEdit(
            resource_index=resource_index,
            resource_id=resource.resource_id,
            source_width=image.width,
            height=image.height,
            source_depth=image.bits,
            bit_width=mode6_width(image),
            bits=original_bits,
            signal_phase=initial_phase,
            phase_variants={
                phase: bytearray(original_bits) for phase in enabled_phases
            },
            enabled_phases=enabled_phases,
            fallback_phase=initial_phase,
            phase_policy=(
                PHASE_POLICY_ENGINE if usage is not None else PHASE_POLICY_MANUAL
            ),
            source_zero_mask=bytearray(index == 0 for index in image.pixels),
            mask_reference_bits=bytearray(original_bits),
            mask_locked=False,
        )
        edit.validate()
        self.validate_phase_policy(edit)
        self.edits[resource_index] = edit
        return edit

    def set_color(self, index: int, color: Sequence[int]) -> None:
        if not 0 <= index < 16 or len(color) != 3 or any(not 0 <= value <= 255 for value in color):
            raise CompositeProjectError("Composite colors must be 16 RGB triples in the range 0–255.")
        new_color = tuple(int(value) for value in color)
        if self.colors[index] != new_color:
            self.colors[index] = new_color
            self.dirty = True

    def to_dict(self) -> dict:
        self._validate_profiles()
        serialized_edits = []
        for index in sorted(self.edits):
            edit = self.edits[index]
            edit.validate()
            self.validate_phase_policy(edit)
            active_bits = edit.variant_bits()
            serialized_edits.append(
                {
                    "resource_index": edit.resource_index,
                    "resource_id": edit.resource_id,
                    "source_width": edit.source_width,
                    "height": edit.height,
                    "source_depth": edit.source_depth,
                    "bit_width": edit.bit_width,
                    # Retain the legacy active-stream snapshot so a v4 payload
                    # remains easy to inspect and test migrations against.
                    "bit_count": len(active_bits),
                    "bits_base64": base64.b64encode(pack_bits(active_bits)).decode("ascii"),
                    "signal_phase": edit.signal_phase,
                    "enabled_phases": list(edit.enabled_phases),
                    "fallback_phase": edit.fallback_phase,
                    "phase_policy": edit.phase_policy,
                    "mask_locked": edit.mask_locked,
                    "mask_authored": edit.mask_authored,
                    "source_zero_count": len(edit.source_zero_mask),
                    "source_zero_base64": base64.b64encode(
                        pack_bits(edit.source_zero_mask)
                    ).decode("ascii"),
                    "mask_reference_count": len(edit.mask_reference_bits),
                    "mask_reference_base64": base64.b64encode(
                        pack_bits(edit.mask_reference_bits)
                    ).decode("ascii"),
                    "phase_variants": [
                        {
                            "phase": phase,
                            "bit_count": len(bits),
                            "bits_base64": base64.b64encode(pack_bits(bits)).decode("ascii"),
                        }
                        for phase, bits in sorted(edit.phase_variants.items())
                    ],
                }
            )
        return {
            "kind": PROJECT_KIND,
            "version": PROJECT_VERSION,
            "source": {
                "name": self.source_name,
                "size": self.source_size,
                "sha256": self.source_sha256,
            },
            "composite_profile": self.composite_profile,
            "composite_palettes": {
                profile: [list(color) for color in self.profile_colors[profile]]
                for profile in DOSBOXX_CGA_COMPOSITE_PROFILES
            },
            # Retained as a readable active-palette snapshot for older tooling.
            "composite_palette": [list(color) for color in self.colors],
            "edits": serialized_edits,
            "saved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    @classmethod
    def from_dict(cls, value: dict) -> "CompositeProject":
        try:
            version = int(value["version"])
            if value["kind"] != PROJECT_KIND or version not in (
                1,
                2,
                3,
                4,
                5,
                PROJECT_VERSION,
            ):
                raise CompositeProjectError("Unsupported composite project format or version.")
            source = value["source"]
            if version == 1:
                # v0.4.4 and earlier had one cga_composite (early-card) table.
                profile = COMPOSITE_PROFILE_OLD
                palettes = default_composite_palettes()
                palettes[profile] = normalize_composite_palette(
                    value["composite_palette"], label="Legacy composite palette"
                )
            else:
                profile = str(value["composite_profile"])
                raw_palettes = value["composite_palettes"]
                if not isinstance(raw_palettes, dict):
                    raise CompositeProjectError("Project composite palettes are invalid.")
                palettes = {
                    key: normalize_composite_palette(
                        raw_palettes[key], label=f"{key} composite palette"
                    )
                    for key in DOSBOXX_CGA_COMPOSITE_PROFILES
                }
            project = cls(
                source_name=str(source["name"]),
                source_size=int(source["size"]),
                source_sha256=str(source["sha256"]),
                composite_profile=profile,
                profile_colors=palettes,
            )
            project._validate_profiles()
            for item in value["edits"]:
                count = int(item["bit_count"])
                active_phase = int(item.get("signal_phase", 0))
                active_bits = unpack_bits(
                    base64.b64decode(item["bits_base64"], validate=True), count
                )
                if version >= 4:
                    raw_variants = item.get("phase_variants", ())
                    if not isinstance(raw_variants, list) or not raw_variants:
                        raise CompositeProjectError(
                            "A phase-aware project edit must contain at least one variant."
                        )
                    variants: dict[int, bytearray] = {}
                    for raw_variant in raw_variants:
                        phase = int(raw_variant["phase"])
                        variant_count = int(raw_variant["bit_count"])
                        if phase in variants:
                            raise CompositeProjectError(
                                "Project contains a duplicate carrier-phase variant."
                            )
                        variants[phase] = unpack_bits(
                            base64.b64decode(
                                raw_variant["bits_base64"], validate=True
                            ),
                            variant_count,
                        )
                    if active_phase not in variants:
                        raise CompositeProjectError(
                            "The active carrier phase has no stored graphic variant."
                        )
                    if variants[active_phase] != active_bits:
                        raise CompositeProjectError(
                            "The active bitstream snapshot does not match its phase variant."
                        )
                    source_zero_count = int(item.get("source_zero_count", 0))
                    source_zero_mask = unpack_bits(
                        base64.b64decode(
                            item.get("source_zero_base64", ""), validate=True
                        ),
                        source_zero_count,
                    )
                    mask_reference_count = int(item.get("mask_reference_count", 0))
                    mask_reference_bits = unpack_bits(
                        base64.b64decode(
                            item.get("mask_reference_base64", ""), validate=True
                        ),
                        mask_reference_count,
                    )
                    enabled_phases = tuple(int(phase) for phase in item["enabled_phases"])
                    fallback_phase = int(item["fallback_phase"])
                    mask_locked = bool(item.get("mask_locked", True))
                    mask_authored = (
                        bool(item.get("mask_authored", False))
                        if version >= 6
                        else False
                    )
                    phase_policy = (
                        str(item.get("phase_policy", PHASE_POLICY_MANUAL))
                        if version >= 5
                        else PHASE_POLICY_MANUAL
                    )
                else:
                    variants = {active_phase: bytearray(active_bits)}
                    enabled_phases = (active_phase,)
                    fallback_phase = active_phase
                    phase_policy = PHASE_POLICY_MANUAL
                    # Legacy projects could deliberately edit index zero, so
                    # migration preserves that behavior until the designer
                    # explicitly enables mask locking.
                    mask_locked = False
                    mask_authored = False
                    source_zero_mask = bytearray()
                    mask_reference_bits = bytearray()
                edit = CompositeEdit(
                    resource_index=int(item["resource_index"]),
                    resource_id=int(item["resource_id"]),
                    source_width=int(item["source_width"]),
                    height=int(item["height"]),
                    source_depth=int(item["source_depth"]),
                    bit_width=int(item["bit_width"]),
                    bits=active_bits,
                    signal_phase=active_phase,
                    phase_variants=variants,
                    enabled_phases=enabled_phases,
                    fallback_phase=fallback_phase,
                    phase_policy=phase_policy,
                    mask_locked=mask_locked,
                    mask_authored=mask_authored,
                    source_zero_mask=source_zero_mask,
                    mask_reference_bits=mask_reference_bits,
                )
                edit.validate()
                project.validate_phase_policy(edit)
                if edit.resource_index in project.edits:
                    raise CompositeProjectError("Project contains a duplicate resource edit.")
                project.edits[edit.resource_index] = edit
            return project
        except CompositeProjectError:
            raise
        except (KeyError, TypeError, ValueError, base64.binascii.Error) as exc:
            raise CompositeProjectError(f"Invalid composite project: {exc}") from exc

    @classmethod
    def load(cls, path: str | Path) -> "CompositeProject":
        project_path = Path(path)
        try:
            value = json.loads(project_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CompositeProjectError(f"Could not read project: {exc}") from exc
        project = cls.from_dict(value)
        project.path = project_path
        project.dirty = False
        return project

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self.path
        if destination is None:
            raise CompositeProjectError("Choose a sidecar project filename first.")
        payload = json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n"
        _atomic_write(destination, payload.encode("utf-8"))
        self.path = destination
        self.dirty = False
        return destination


def render_edited_mode6(edit: CompositeEdit, *, channels: int = 3) -> RenderedRaster:
    edit.validate()
    if channels not in (3, 4):
        raise ValueError("Renderer supports only RGB and RGBA pixels.")
    output = bytearray(edit.bit_width * edit.height * channels)
    cursor = 0
    for bit in edit.bits:
        color = (255, 255, 255) if bit else (0, 0, 0)
        output[cursor : cursor + 3] = bytes(color)
        if channels == 4:
            output[cursor + 3] = 255
        cursor += channels
    return RenderedRaster(edit.bit_width, edit.height, bytes(output), channels, "mode6")


def render_edited_composite(
    edit: CompositeEdit,
    colors: Sequence[tuple[int, int, int]],
    *,
    channels: int = 3,
) -> RenderedRaster:
    edit.validate()
    if channels not in (3, 4):
        raise ValueError("Renderer supports only RGB and RGBA pixels.")
    if len(colors) != 16:
        raise ValueError("Composite rendering requires exactly 16 colors.")
    width = (edit.bit_width + 3) // 4
    output = bytearray(width * edit.height * channels)
    cursor = 0
    for y in range(edit.height):
        for x in range(width):
            color = colors[edit.pattern_at(x, y)]
            output[cursor : cursor + 3] = bytes(color)
            if channels == 4:
                output[cursor + 3] = 255
            cursor += channels
    return RenderedRaster(width, edit.height, bytes(output), channels, "composite")


def source_pixels_for_edit(
    image: DecodedImage,
    edit: CompositeEdit,
    hardware_palette: PrincePalette | None,
    *,
    phase: int | None = None,
    bits: Sequence[int] | None = None,
) -> bytes:
    """Invert edited CGA bits back to representable Prince source indices."""

    edit.validate()
    if (image.width, image.height, image.bits) != (
        edit.source_width,
        edit.height,
        edit.source_depth,
    ):
        raise CompositeProjectError("Edited dimensions do not match the decoded source image.")
    if phase is not None and bits is not None:
        raise CompositeProjectError("Choose either a stored phase variant or explicit bits.")
    selected_bits = edit.variant_bits(phase) if bits is None else bytearray(bits)
    if len(selected_bits) != edit.bit_width * edit.height:
        raise CompositeProjectError("Candidate phase variant dimensions are inconsistent.")
    edit.validate_mask_bits(selected_bits)
    if edit.source_zero_mask and not edit.mask_authored:
        expected_mask = bytearray(index == 0 for index in image.pixels)
        if edit.source_zero_mask != expected_mask:
            raise CompositeProjectError(
                "The stored index-zero mask does not match the decoded source image."
            )
    if image.bits == 1:
        return bytes(selected_bits)
    if image.bits != 4:
        raise CompositeProjectError("Only 1-bit and 4-bit images can be written back.")

    table = hardware_palette.cga_translation if hardware_palette else ()
    colors = (
        hardware_palette.colors
        if hardware_palette is not None and hardware_palette.usable
        else tuple((index * 17, index * 17, index * 17) for index in range(16))
    )
    result = bytearray(image.width * image.height)
    for y in range(image.height):
        for x in range(image.width):
            bit_offset = y * edit.bit_width + x * 2
            desired = (selected_bits[bit_offset] << 1) | selected_bits[bit_offset + 1]
            source_offset = y * image.width + x
            original = image.pixels[source_offset] & 0x0F
            phase = ((y & 1) << 1) | (x & 1)

            def translated(candidate: int) -> int:
                return table[phase * 16 + candidate] if len(table) == 64 else candidate & 3

            original_allowed = True
            if edit.mask_locked and edit.source_zero_mask:
                original_allowed = (
                    original == 0
                    if edit.source_zero_mask[source_offset]
                    else original != 0
                )
            if translated(original) == desired and original_allowed:
                result[source_offset] = original
                continue
            candidates = [candidate for candidate in range(16) if translated(candidate) == desired]
            if edit.mask_locked and edit.source_zero_mask:
                if edit.source_zero_mask[source_offset]:
                    candidates = [candidate for candidate in candidates if candidate == 0]
                else:
                    candidates = [candidate for candidate in candidates if candidate != 0]
            if not candidates:
                raise CompositeProjectError(
                    f"Pattern {desired:02b} cannot be represented at source x={x}, y={y}."
                )
            original_color = colors[original] if original < len(colors) else (0, 0, 0)
            result[source_offset] = min(
                candidates,
                key=lambda candidate: (
                    sum(
                        (colors[candidate][channel] - original_color[channel]) ** 2
                        for channel in range(3)
                    )
                    if candidate < len(colors)
                    else 1 << 30,
                    candidate,
                ),
            )
    return bytes(result)


def predicted_image_for_edit(
    image: DecodedImage,
    edit: CompositeEdit,
    hardware_palette: PrincePalette | None,
    *,
    phase: int | None = None,
    bits: Sequence[int] | None = None,
) -> DecodedImage:
    """Return the exact source-index image that Save-As would encode.

    The composite project stores desired mode-6 bits, but VGA, EGA, and CGA
    all render from Prince's shared source indices.  This helper runs the same
    deterministic inverse translation used by :func:`replacement_contents`
    and substitutes only the decoded pixel stream.  GUI previews can therefore
    show the adapter impact before a patched DAT is written.
    """

    return replace(
        image,
        pixels=source_pixels_for_edit(
            image,
            edit,
            hardware_palette,
            phase=phase,
            bits=bits,
        ),
    )


def _pack_image_pixels(image: DecodedImage, pixels: bytes) -> bytes:
    """Pack byte-per-pixel indices into Prince's row-major image representation."""

    if len(pixels) != image.width * image.height:
        raise CompositeProjectError("Replacement pixel count is invalid.")
    packed = bytearray()
    for y in range(image.height):
        row = pixels[y * image.width : (y + 1) * image.width]
        if image.bits == 1:
            for start in range(0, image.width, 8):
                value = 0
                for part in range(8):
                    value <<= 1
                    if start + part < image.width:
                        value |= row[start + part] & 1
                packed.append(value)
        elif image.bits == 4:
            for start in range(0, image.width, 2):
                high = row[start] & 0x0F
                low = row[start + 1] & 0x0F if start + 1 < image.width else 0
                packed.append((high << 4) | low)
        else:
            raise CompositeProjectError("Only 1-bit and 4-bit images can be encoded.")
    return bytes(packed)


def _vertical_lzg_order(packed: bytes, image: DecodedImage) -> bytes:
    """Return the packed-byte order consumed by Prince's transposed B4 codec."""

    if image.bits == 4:
        row_width = (image.width + 1) // 2
    elif image.bits == 1:
        row_width = (image.width + 7) // 8
    else:  # pragma: no cover - write-back currently rejects 8-bit images
        row_width = image.width
    return bytes(
        packed[y * row_width + byte_x]
        for byte_x in range(row_width)
        for y in range(image.height)
    )


def _lzg_longest_matches(data: bytes) -> tuple[list[int], list[int]]:
    """Find the longest legal LZG match and distance at every input byte."""

    size = len(data)
    match_lengths = [0] * size
    match_distances = [0] * size
    positions: dict[bytes, list[int]] = {}

    for cursor in range(size):
        if cursor + 3 > size:
            continue
        key = data[cursor : cursor + 3]
        maximum = min(66, size - cursor)
        best_length = 0
        best_distance = 0

        # Positions are appended in ascending order. Searching newest first
        # tends to find overlapping runs quickly and the 1 KiB limit lets us
        # stop as soon as a candidate falls outside the history window.
        for previous in reversed(positions.get(key, ())):
            if previous < cursor - 1024:
                break
            distance = cursor - previous
            length = 3
            while (
                length < maximum
                and data[cursor + length] == data[cursor - distance + length]
            ):
                length += 1
            if length > best_length:
                best_length = length
                best_distance = distance
                if length == maximum:
                    break

        # Prince initializes the full 1 KiB ring to zero. A distance of 1024
        # therefore supplies useful matches before enough real output exists.
        if key == b"\x00\x00\x00" and cursor < 1024:
            distance = 1024
            length = 3
            while length < maximum:
                source = cursor - distance + length
                source_value = 0 if source < 0 else data[source]
                if data[cursor + length] != source_value:
                    break
                length += 1
            if length > best_length:
                best_length = length
                best_distance = distance

        match_lengths[cursor] = best_length
        match_distances[cursor] = best_distance
        positions.setdefault(key, []).append(cursor)

    return match_lengths, match_distances


def encode_lzg(data: bytes) -> bytes:
    """Encode bytes with Prince's B3/B4 LZ Groody packet format.

    The parser is chosen with dynamic programming because a back-reference is
    two bytes while a literal is one, and every eight tokens share one mask
    byte. This produces a smaller archive than a purely greedy parse while
    remaining byte-for-byte compatible with the original ring-buffer decoder.
    """

    if not data:
        return b""
    match_lengths, match_distances = _lzg_longest_matches(data)
    size = len(data)
    infinity = size * 3 + 1
    costs = [[infinity] * 8 for _ in range(size + 1)]
    choices = [[1] * 8 for _ in range(size)]
    for slot in range(8):
        costs[size][slot] = 0

    for cursor in range(size - 1, -1, -1):
        for slot in range(8):
            next_slot = (slot + 1) & 7
            mask_cost = 1 if slot == 0 else 0
            best_cost = mask_cost + 1 + costs[cursor + 1][next_slot]
            best_length = 1
            for length in range(3, match_lengths[cursor] + 1):
                candidate = mask_cost + 2 + costs[cursor + length][next_slot]
                # Prefer the longer copy on a size tie; it requires fewer
                # decoder iterations without changing the archive size.
                if candidate <= best_cost:
                    best_cost = candidate
                    best_length = length
            costs[cursor][slot] = best_cost
            choices[cursor][slot] = best_length

    encoded = bytearray()
    cursor = 0
    slot = 0
    mask_offset = 0
    while cursor < size:
        if slot == 0:
            mask_offset = len(encoded)
            encoded.append(0)
        length = choices[cursor][slot]
        if length == 1:
            encoded[mask_offset] |= 1 << slot
            encoded.append(data[cursor])
        else:
            distance = match_distances[cursor]
            output_cursor = 1024 + cursor
            encoded_location = 66 + ((output_cursor - distance - 66) & 0x3FF)
            encoded.extend(
                (
                    ((length - 3) << 2) | ((encoded_location - 66) >> 8),
                    (encoded_location - 66) & 0xFF,
                )
            )
        cursor += length
        slot = (slot + 1) & 7
    return bytes(encoded)


def encode_image_lzg(original_content: bytes, image: DecodedImage, pixels: bytes) -> bytes:
    """Encode replacement pixels as a compatible Prince B3/B4 LZG resource."""

    if len(original_content) < 6 or len(pixels) != image.width * image.height:
        raise CompositeProjectError("Replacement pixel count is invalid.")
    packed = _pack_image_pixels(image, pixels)
    # Preserve the source resource's storage orientation. RAW/B1/B3 are
    # row-major; B2/B4 are packed one byte-column at a time.
    algorithm = 4 if image.algorithm in (2, 4) else 3
    compressor_input = _vertical_lzg_order(packed, image) if algorithm == 4 else packed
    header = bytearray(original_content[:6])
    header[5] = (header[5] & 0xF0) | algorithm
    content = bytes(header) + encode_lzg(compressor_input)
    if len(content) > 0xFFFF:
        raise CompositeProjectError("The LZG replacement exceeds the DAT size field.")
    try:
        decoded = decode_prince_image(content)
    except ImageDecodeError as exc:  # pragma: no cover - guarded internal invariant
        raise CompositeProjectError(f"Replacement image could not be decoded: {exc}") from exc
    if decoded.pixels != pixels:
        raise CompositeProjectError("Internal error: replacement image failed its round-trip check.")
    return content


def replacement_contents(
    archive: DatArchive, project: CompositeProject
) -> dict[int, bytes]:
    project.verify_archive(archive)
    replacements: dict[int, bytes] = {}
    for index, edit in project.edits.items():
        edit.validate()
        project.validate_phase_policy(edit)
        if not 0 <= index < len(archive.resources):
            raise CompositeProjectError(f"Project refers to missing resource index {index}.")
        analysis = archive.analysis_for_index(index)
        if analysis.image is None:
            raise CompositeProjectError(f"Resource {edit.resource_id} is no longer an image.")
        resource = analysis.resource
        if edit.resource_id != resource.resource_id:
            raise CompositeProjectError("Project resource ID does not match the source DAT.")
        palette = hardware_palette_for_resource(archive, resource)
        original_bits = initial_mode6_bits(analysis.image, palette)
        fallback_bits = edit.variant_bits(edit.fallback_phase)
        original_mask = bytearray(index == 0 for index in analysis.image.pixels)
        if fallback_bits == original_bits and edit.source_zero_mask == original_mask:
            continue
        pixels = source_pixels_for_edit(
            analysis.image,
            edit,
            palette,
            phase=edit.fallback_phase,
        )
        replacements[index] = encode_image_lzg(resource.data, analysis.image, pixels)
    return replacements


def rebuild_dat(archive: DatArchive, replacements: dict[int, bytes]) -> bytes:
    """Rebuild a DAT, preserving order, IDs, and every unchanged payload."""

    unknown = set(replacements) - set(range(len(archive.resources)))
    if unknown:
        raise CompositeProjectError(f"Replacement indexes do not exist: {sorted(unknown)}")
    body = bytearray(6)
    records: list[tuple[int, int, int]] = []
    for resource in archive.resources:
        content = replacements.get(resource.index, resource.data)
        if len(content) > 0xFFFF:
            raise CompositeProjectError(
                f"Resource {resource.resource_id} exceeds the 65,535-byte DAT field."
            )
        offset = len(body)
        checksum = (-1 - sum(content)) & 0xFF
        body.extend(bytes((checksum,)))
        body.extend(content)
        records.append((resource.resource_id, offset, len(content)))

    index_offset = len(body)
    index_size = 2 + len(records) * 8
    if index_offset > 0xFFFFFFFF or index_size > 0xFFFF:
        raise CompositeProjectError("Rebuilt DAT exceeds its index field limits.")
    struct.pack_into("<IH", body, 0, index_offset, index_size)
    body.extend(struct.pack("<H", len(records)))
    for record in records:
        body.extend(struct.pack("<HIH", *record))
    return bytes(body)


def write_patched_dat(
    archive: DatArchive,
    project: CompositeProject,
    destination: str | Path,
) -> tuple[Path, int]:
    """Atomically write and reopen a Save-As DAT, returning changed count."""

    project.verify_archive(archive)
    target = Path(destination)
    try:
        if target.resolve() == archive.path.resolve():
            raise CompositeProjectError(
                "The opened source DAT cannot be overwritten. Choose a new Save-As filename."
            )
    except OSError:
        pass
    replacements = replacement_contents(archive, project)
    payload = rebuild_dat(archive, replacements)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            verification = DatArchive.open(temporary)
        except DatFormatError as exc:
            raise CompositeProjectError(f"Written DAT failed structural verification: {exc}") from exc
        if [resource.resource_id for resource in verification.resources] != [
            resource.resource_id for resource in archive.resources
        ]:
            raise CompositeProjectError("Written DAT failed resource-order verification.")
        if not all(resource.checksum_ok for resource in verification.resources):
            raise CompositeProjectError("Written DAT failed checksum verification.")
        for index, expected_content in replacements.items():
            analysis = verification.analysis_for_index(index)
            if analysis.image is None:
                raise CompositeProjectError("Written replacement no longer decodes as an image.")
            expected = project.edits[index]
            palette = hardware_palette_for_resource(verification, analysis.resource)
            if (
                initial_mode6_bits(analysis.image, palette)
                != expected.variant_bits(expected.fallback_phase)
            ):
                raise CompositeProjectError("Written replacement failed composite-bit verification.")
            if verification.resources[index].data != expected_content:
                raise CompositeProjectError("Written replacement content changed during verification.")
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    return target, len(replacements)


def phase_manifest_dict(
    archive: DatArchive,
    project: CompositeProject,
    *,
    global_phase_bias: int = 0,
) -> dict:
    """Build a lossless interchange manifest for the future DOS draw hook.

    The final EXE storage format is intentionally not assumed.  Every enabled
    phase contains the exact Mode-6 stream, deterministic inverse source
    indices, and a complete LZG image payload.  A later packer can therefore
    choose pointer tables, added DAT resources, or a separate archive without
    asking the graphic designer to regenerate artwork.
    """

    project.verify_archive(archive)
    if global_phase_bias not in PHASES:
        raise CompositeProjectError("Global phase bias must be between 0 and 3.")
    if global_phase_bias and any(
        edit.phase_policy == PHASE_POLICY_ENGINE for edit in project.edits.values()
    ):
        raise CompositeProjectError(
            "Automatic original-engine variants are normalized to a P0 screen origin. "
            "Use global phase bias 0, or switch affected records to Manual and generate "
            "the shifted phase slots after hardware/emulator calibration."
        )
    resources: list[dict] = []
    for index in sorted(project.edits):
        edit = project.edits[index]
        edit.validate()
        project.validate_phase_policy(edit)
        if not 0 <= index < len(archive.resources):
            raise CompositeProjectError(f"Project refers to missing resource index {index}.")
        analysis = archive.analysis_for_index(index)
        if analysis.image is None:
            raise CompositeProjectError(f"Resource {edit.resource_id} is no longer an image.")
        if analysis.resource.resource_id != edit.resource_id:
            raise CompositeProjectError("Project resource ID does not match the source DAT.")
        hardware = hardware_palette_for_resource(archive, analysis.resource)
        variants: list[dict] = []
        for phase in edit.enabled_phases:
            bits = edit.variant_bits(phase)
            pixels = source_pixels_for_edit(
                analysis.image,
                edit,
                hardware,
                phase=phase,
            )
            lzg_payload = encode_image_lzg(
                analysis.resource.data,
                analysis.image,
                pixels,
            )
            packed = pack_bits(bits)
            variants.append(
                {
                    "phase": phase,
                    "bit_count": len(bits),
                    "packed_bits_base64": base64.b64encode(packed).decode("ascii"),
                    "packed_bits_sha256": hashlib.sha256(packed).hexdigest(),
                    "source_pixel_count": len(pixels),
                    "source_pixels_base64": base64.b64encode(pixels).decode("ascii"),
                    "source_pixels_sha256": hashlib.sha256(pixels).hexdigest(),
                    "lzg_resource_size": len(lzg_payload),
                    "lzg_resource_base64": base64.b64encode(lzg_payload).decode("ascii"),
                    "lzg_resource_sha256": hashlib.sha256(lzg_payload).hexdigest(),
                }
            )
        zero_mask_packed = pack_bits(edit.source_zero_mask)
        mask_reference_packed = pack_bits(edit.mask_reference_bits)
        engine_usage = project.engine_usage_for_edit(edit)
        engine_usage_manifest = (
            engine_usage.to_manifest_dict() if engine_usage is not None else None
        )
        if engine_usage_manifest is not None:
            engine_usage_manifest["required_phases_at_manifest_bias"] = list(
                shifted_runtime_phases(
                    engine_usage.required_phases,
                    global_phase_bias,
                )
            )
        resources.append(
            {
                "resource_index": edit.resource_index,
                "resource_id": edit.resource_id,
                "source_width": edit.source_width,
                "height": edit.height,
                "source_depth": edit.source_depth,
                "mode6_width": edit.bit_width,
                "enabled_phases": list(edit.enabled_phases),
                "phase_profile": edit.phase_profile,
                "phase_policy": edit.phase_policy,
                "engine_phase_usage": engine_usage_manifest,
                "fallback_phase": edit.fallback_phase,
                "mask_locked": edit.mask_locked,
                "mask_authored": edit.mask_authored,
                "source_zero_count": len(edit.source_zero_mask),
                "source_zero_mask_base64": base64.b64encode(zero_mask_packed).decode(
                    "ascii"
                ),
                "source_zero_mask_sha256": hashlib.sha256(zero_mask_packed).hexdigest(),
                "mask_reference_bit_count": len(edit.mask_reference_bits),
                "mask_reference_bits_base64": base64.b64encode(
                    mask_reference_packed
                ).decode("ascii"),
                "mask_reference_bits_sha256": hashlib.sha256(
                    mask_reference_packed
                ).hexdigest(),
                "variants": variants,
            }
        )
    return {
        "kind": PHASE_MANIFEST_KIND,
        "version": PHASE_MANIFEST_VERSION,
        "source": {
            "name": project.source_name,
            "size": project.source_size,
            "sha256": project.source_sha256,
        },
        "composite_profile": project.composite_profile,
        "global_phase_bias": global_phase_bias,
        "phase_period_mode6_pixels": 4,
        "original_engine_audit": ENGINE_AUDIT_ID,
        "original_engine_coordinate_contract": (
            "Integral 320-column destination/crop coordinates become two Mode-6 samples; "
            "at global bias 0 only P0 and P2 are reachable."
        ),
        "packed_bit_order": "row-major, MSB-first within each byte",
        "source_pixel_order": "row-major, one unpacked palette index per byte",
        "lzg_payload_scope": "complete Prince image resource, excluding DAT checksum byte",
        "runtime_phase_formula": (
            "(global_phase_bias + destination_640_x - cropped_source_640_x) & 3"
        ),
        "missing_phase_policy": "use the resource fallback_phase",
        "resources": resources,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def write_phase_manifest(
    archive: DatArchive,
    project: CompositeProject,
    destination: str | Path,
    *,
    global_phase_bias: int = 0,
) -> tuple[Path, int, int]:
    """Atomically write the phase-aware interchange manifest.

    Returns the path, resource-family count, and enabled variant count.
    """

    target = Path(destination)
    manifest = phase_manifest_dict(
        archive,
        project,
        global_phase_bias=global_phase_bias,
    )
    payload = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    _atomic_write(target, payload.encode("utf-8"))
    variants = sum(len(resource["variants"]) for resource in manifest["resources"])
    return target, len(manifest["resources"]), variants


def _atomic_write(destination: Path, payload: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
