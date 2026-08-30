#!/usr/bin/env python3
"""Build the Prince 1.3 Exhaustive VGA Kid phase-stable prototype.

The normal KID table holds the right-facing/even-X case.  One packed private
table adds right/odd, left/even, and left/odd images for the idle, run, turn,
and run-turn frames. All four cases retain the stored-orientation header.
Prince's native flip creates the left-facing cases, while the right cases
compensate for reversal of two-sample CGA pixel groups. Every
direction/phase case is optimized independently with the editor's exact
2,048-state Exhaustive row dynamic program and no dithering.

All added tables live in conventional memory.  The patch contains no XMS,
EMS, DPMI, or 286+ instructions and retains the original MZ allocation size.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from typing import Final, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if (SCRIPT_DIR / "engine").is_dir():
    # Self-contained release archive layout: tools/make_four_way_kid.py and
    # tools/engine/*.py.
    WORKSPACE = SCRIPT_DIR.parent
    ENGINE_DIR = SCRIPT_DIR / "engine"
    PHASE_TOOLS_DIR = SCRIPT_DIR
else:
    WORKSPACE = SCRIPT_DIR.parents[1]
    ENGINE_DIR = WORKSPACE / "pop13_composite_batch" / "engine"
    PHASE_TOOLS_DIR = WORKSPACE / "phase_aware_prototype"
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(PHASE_TOOLS_DIR))

from composite_converter import (  # noqa: E402
    CONVERSION_EXHAUSTIVE,
    ConversionSettings,
    DITHER_NONE,
    QUALITY_HIGH,
    convert_raster_to_exhaustive,
)
from composite_project import (  # noqa: E402
    CompositeEdit,
    encode_image_lzg,
    initial_mode6_bits,
    source_pixels_for_edit,
)
from make_phase_prototype import (  # noqa: E402
    CAVE_CAPACITY,
    CAVE_OFFSET,
    EXPECTED_LAUNCHER_SHA256,
    HOOK_OFFSET,
    HOOK_SIGNATURE,
    mz_load_module,
    patch_launcher,
    sha256,
    unpack_exepack,
)
from prince_dat import (  # noqa: E402
    COMPOSITE_PROFILE_NEW,
    DatArchive,
    RenderedRaster,
    decode_prince_image,
    hardware_palette_for_resource,
    mode6_width,
    render_display_mode,
)


OUTPUT_EXE: Final = "P4KX13.EXE"
OUTPUT_COM: Final = "CGA4K13.COM"
OUTPUT_DAT: Final = "KID.DAT"
CHILD_NAME: Final = b"P4KX13.EXE"

ORIGINAL_VERSION: Final = b"PRINCE OF PERSIA  V1.3"
PROTOTYPE_VERSION: Final = b"KID EXH V13       V1.3"
VERSION_OFFSET: Final = 0x1BB42
ORIGINAL_BANNER: Final = b"PRINCE CGA Palette Launcher 1.2.0"
PROTOTYPE_BANNER: Final = b"KID EXHAUSTIVE V13 ACTIVE        "
V9_CHILD_NAME: Final = b"P4KID9.EXE"
V9_PROTOTYPE_BANNER: Final = b"KID EGA PHASE V9 ACTIVE          "
V9_LAUNCHER_SHA256: Final = (
    "771149deecde92f001704d03dc6198d88bb9444aadd35dcbaceb6039701a2624"
)

# The original Kid loader at 0000:1EFA passes DS:18BE as its final argument
# to load_chtab.  This is its 219-byte per-image CGA loading/control table.
# Private Kid variants must use the same argument instead of the FFFF
# unconditional path so their raw images enter Prince's normal conversion
# pipeline with exactly the same per-image semantics.
KID_TABLE_AUXILIARY_OFFSET: Final = 0x18BE

# CGAPRINC changes the hardware output to 640x200 mode 6, but Prince itself
# remains on its CGA driver and reports gmCga (1) in graphics_mode.  The
# original instruction displaced at LOAD_HOOK_OFFSET compares against
# gmMcgaVga (5), so the injected loader must restore that *different* compare
# immediately before returning to the original JNE.
COMPOSITE_GAME_GRAPHICS_MODE: Final = 1
ORIGINAL_LOAD_COMPARE_GRAPHICS_MODE: Final = 5

# 0000:B594 is the Kid-table CMP immediately before Prince creates the CGA
# working representation used for both Kid color and transparency.  The
# four-byte CMP is replaced by CALL rel16 + NOP.  The low trampoline calls the
# selector, recreates the displaced CMP, and returns with flags intact for the
# original JNE at B598.
#
# V3 selected a private image at the later B641 final-X join.  By that point
# Prince had already converted the normal image; replacing it with a raw 4-bit
# DAT image made the private cases transparent.  Selecting here lets the
# unmodified CGA path convert, own, draw, and free the chosen image normally.
SELECTOR_HOOK_OFFSET: Final = 0xB594
SELECTOR_HOOK_SIGNATURE: Final = bytes.fromhex(
    "83 7e ea 02 75 70 8b 5e e4"
)

# 0000:F60 is the five-byte CGA-mode comparison immediately after the level
# sprite tables have been loaded.  It is replaced by a FAR CALL whose final
# CMP recreates the original flags for the following JNE.
LOAD_HOOK_OFFSET: Final = 0x0F60
LOAD_HOOK_SIGNATURE: Final = bytes.fromhex("80 3e 35 31 05 75 64")

# Microsoft C startup changes SS to the data segment and starts its heap at
# the live stack ceiling.  V1 placed high code two bytes above that ceiling,
# so the first allocations could overwrite it.  Replace the two heap-base
# stores with a FAR call that advances both heap cursors by 512 bytes.  The
# injected code remains between the downward-growing stack and upward-growing
# heap and therefore cannot be touched by either.
STARTUP_HEAP_HOOK_OFFSET: Final = 0x15B69
STARTUP_HEAP_HOOK_SEGMENT: Final = 0x0CC8
STARTUP_HEAP_HOOK_LOGICAL_OFFSET: Final = (
    STARTUP_HEAP_HOOK_OFFSET - STARTUP_HEAP_HOOK_SEGMENT * 16
)
STARTUP_HEAP_SIGNATURE: Final = bytes.fromhex(
    "36 89 26 fe 2d 36 89 26 fa 2d"
)
HEAP_RESERVE_BYTES: Final = 0x0200

# The original image ends at 1F080h.  SS:SP initially points to 221C:1000,
# which is linear 231C0h.  The stack grows down, so the 110h-byte region from
# that address to the unchanged allocation ceiling at 232D0h is safe for code.
HIGH_CODE_SEGMENT: Final = 0x231C
HIGH_CODE_LINEAR: Final = HIGH_CODE_SEGMENT * 16
ORIGINAL_TOTAL_PARAGRAPHS: Final = 9005

# V18 proved that slot 3 survives the level loader and that both directions
# work when every selected image retains the stored-orientation header.  Pack
# all three non-normal cases into disjoint alias ranges in that one table.
# The selector maps the 36 selected source image IDs to ordinals 0..35.
SLOT_STORED_ODD: Final = 3
SLOT_MIRRORED_EVEN: Final = 4
SLOT_MIRRORED_ODD: Final = 9
USE_PRIVATE_MIRRORED_EVEN: Final = False
FORCE_MIRRORED_ODD: Final = False
REQUIRE_BLITTER_10: Final = False
PACK_MIRRORED_ALIASES: Final = True
MIRRORED_EVEN_ALIAS_BASE: Final = 64
MIRRORED_ODD_ALIAS_BASE: Final = 128
PACK_STORED_ODD_ALIAS: Final = True
STORED_ODD_ALIAS_BASE: Final = 0
FIXED_VARIANT_ALIAS_IDS: Final = False
TRACE_STORED_X_LOW2: Final = False
TRACE_MIRRORED_X_LOW2: Final = False
PRIVATE_TABLES: Final = (
    (SLOT_STORED_ODD, 1000, False, 0, "phase-packed"),
)
PRIVATE_RESOURCE_BASE: Final = PRIVATE_TABLES[0][1]
PRIVATE_VARIANTS: Final = (
    ("right-odd", STORED_ODD_ALIAS_BASE, "right", 2, False),
    ("left-even", MIRRORED_EVEN_ALIAS_BASE, "left", 0, True),
    ("left-odd", MIRRORED_ODD_ALIAS_BASE, "left", 2, True),
)

# Authoritative frame-to-image ranges from the Prince 1.3 Kid frame table.
# The complete standing-turn sequence is frames 45..52/images 44..51, while
# the complete run-turn sequence is frames 53..65/images 64..76.  V12
# incorrectly assigned frame 52 to image 64, leaving its real image 51 on the
# single-phase fallback and shifting the run-turn coverage by one image.
SELECTED_FRAME_IMAGE_RANGES: Final = (
    ("start_run_and_stand", 1, 15, 0, 14),
    ("standing_turn", 45, 52, 44, 51),
    ("run_turn", 53, 65, 64, 76),
)
SELECTED_IMAGE_IDS: Final = tuple(
    image_id
    for _name, _frame_first, _frame_last, image_first, image_last
    in SELECTED_FRAME_IMAGE_RANGES
    for image_id in range(image_first, image_last + 1)
)

SETTINGS_BASE: Final = dict(
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
    preserve_zero=True,
)

# Render the original 4-bit Kid resources through their embedded VGA palette
# before optimizing the full-width Mode-6 carrier.  The runtime selector and
# stored-orientation mapping remain identical to the proven V9/V10 path.
SOURCE_DISPLAY_MODE: Final = "vga"
EXPECTED_SOURCE_KID_SHA256: Final = (
    "2eaa798041c090a6d54cd0dce4ae770e3da400ef95540cec7ed0ff9db5c2af73"
)
EXPECTED_PHASE0_BASELINE_KID_SHA256: Final = (
    "f43f0bf4290fead7cea0285903e4013c41d962c4e82915d8b6d9f50b5f6fa762"
)

# The V13 phase-aware objective deliberately contains no cross-phase
# consistency term. Unselected Kid images come from the independently built
# VGA/Exhaustive/No-Dither phase-0 archive identified above.
PHASE_CONSISTENCY: Final = 0
CONVERSION_MODE: Final = CONVERSION_EXHAUSTIVE


class CodeBuilder:
    """Tiny deterministic 8086 byte builder with local branch fixups."""

    def __init__(self) -> None:
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.rel8: list[tuple[int, str]] = []
        self.rel16: list[tuple[int, str]] = []
        self.relocations: list[int] = []

    @property
    def offset(self) -> int:
        return len(self.code)

    def emit(self, data: bytes | Iterable[int]) -> None:
        self.code.extend(data)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate code label: {name}")
        self.labels[name] = self.offset

    def jump8(self, opcode: int, label: str) -> None:
        self.emit((opcode, 0))
        self.rel8.append((self.offset - 1, label))

    def call16(self, label: str) -> None:
        self.emit((0xE8, 0, 0))
        self.rel16.append((self.offset - 2, label))

    def jump16(self, label: str) -> None:
        self.emit((0xE9, 0, 0))
        self.rel16.append((self.offset - 2, label))

    def far_call(self, offset: int, segment: int) -> None:
        start = self.offset
        self.emit(b"\x9a" + struct.pack("<HH", offset, segment))
        self.relocations.append(start + 3)

    def finish(self) -> tuple[bytes, tuple[int, ...]]:
        for displacement_offset, label in self.rel8:
            if label not in self.labels:
                raise ValueError(f"missing code label: {label}")
            displacement = self.labels[label] - (displacement_offset + 1)
            if not -128 <= displacement <= 127:
                raise ValueError(f"short branch to {label} is out of range")
            self.code[displacement_offset] = displacement & 0xFF
        for displacement_offset, label in self.rel16:
            if label not in self.labels:
                raise ValueError(f"missing code label: {label}")
            displacement = self.labels[label] - (displacement_offset + 2)
            struct.pack_into("<H", self.code, displacement_offset, displacement & 0xFFFF)
        return bytes(self.code), tuple(self.relocations)


def _push_all(builder: CodeBuilder) -> None:
    builder.emit(bytes.fromhex("50 53 51 52 56 57 1e 06"))


def _pop_all(builder: CodeBuilder) -> None:
    builder.emit(bytes.fromhex("07 1f 5f 5e 5a 59 5b 58"))


def build_high_code() -> tuple[bytes, dict[str, int], tuple[int, ...]]:
    """Return selector/loader machine code and MZ relocation offsets."""

    if PACK_STORED_ODD_ALIAS and not PACK_MIRRORED_ALIASES:
        raise ValueError("stored-odd alias packing requires the shared alias mapper")
    if (TRACE_STORED_X_LOW2 or TRACE_MIRRORED_X_LOW2) and not (
        PACK_STORED_ODD_ALIAS
        and PACK_MIRRORED_ALIASES
        and FIXED_VARIANT_ALIAS_IDS
    ):
        raise ValueError("X-mod-4 tracing requires fixed shared aliases")
    if TRACE_STORED_X_LOW2 and not 0 <= STORED_ODD_ALIAS_BASE <= 124:
        raise ValueError("stored X-mod-4 aliases must fit IDs 0..127")
    if TRACE_MIRRORED_X_LOW2 and not 0 <= MIRRORED_EVEN_ALIAS_BASE <= 124:
        raise ValueError("mirrored X-mod-4 aliases must fit IDs 0..127")
    if PACK_MIRRORED_ALIASES and not FIXED_VARIANT_ALIAS_IDS:
        alias_ranges = (
            range(STORED_ODD_ALIAS_BASE, STORED_ODD_ALIAS_BASE + len(SELECTED_IMAGE_IDS)),
            range(MIRRORED_EVEN_ALIAS_BASE, MIRRORED_EVEN_ALIAS_BASE + len(SELECTED_IMAGE_IDS)),
            range(MIRRORED_ODD_ALIAS_BASE, MIRRORED_ODD_ALIAS_BASE + len(SELECTED_IMAGE_IDS)),
        )
        if any(group.start < 0 or group.stop > 219 for group in alias_ranges):
            raise ValueError("packed variant aliases exceed the 219-image Kid table")
        flattened = [image_id for group in alias_ranges for image_id in group]
        if len(flattened) != len(set(flattened)):
            raise ValueError("packed variant alias ranges overlap")

    b = CodeBuilder()
    b.label("selector")
    _push_all(b)
    b.emit(bytes.fromhex("80 3e 35 31") + bytes((COMPOSITE_GAME_GRAPHICS_MODE,)))
                                                # Prince's internal CGA mode
    b.jump8(0x75, "selector_early_done")      # JNE done
    b.emit(bytes.fromhex("83 7e ea 02"))       # CMP word [BP-16],2 (Kid)
    b.jump8(0x75, "selector_early_done")
    if REQUIRE_BLITTER_10:
        b.emit(bytes.fromhex("83 7e f6 10"))   # CMP word [BP-0A],10h
        b.jump8(0x75, "selector_early_done")
    # Reproduce the exact X that Prince will draw.  B627 converts the 280-wide
    # logical coordinate to the 320-wide screen coordinate with floor(X*320/280).
    # Testing the pre-scale X made every diagnostic frame choose the one-marker
    # table even while the physical signal changed orange <-> cyan.
    b.emit(bytes.fromhex("ff 76 f2"))           # logical X argument
    b.far_call(0xC716, 0x0000)                 # AX = calc_screen_x_coord(X)
    b.emit(bytes.fromhex("8b 4e e4"))           # CX = original image ID
    b.emit(bytes.fromhex("83 7e ee 00"))       # requested image orientation
    b.jump8(0x74, "mirrored_orientation")

    # B637 subtracts the converted image width for this orientation.  Use the
    # current normal image here; every private variant has identical geometry.
    b.emit(bytes.fromhex("c4 5e fa"))           # ES:BX = normal image
    b.emit(bytes.fromhex("26 2b 47 02"))        # AX -= image width

    # Runtime testing established that this nonzero-orientation branch is
    # rightward travel.  Right/even lives in the normal table; right/odd is a
    # packed alias in private slot 3.
    if TRACE_STORED_X_LOW2:
        # Diagnostic mode: route every stored-orientation draw through one of
        # four fixed aliases selected by the computed final X modulo four.
        # This makes both low coordinate bits visible and removes the parity
        # branch itself from the experiment.
        b.emit(bytes.fromhex("8b d0"))          # DX = final screen X
        b.emit(bytes.fromhex("83 e2 03"))       # DX &= 3
        b.emit(b"\x83\xc2" + bytes((STORED_ODD_ALIAS_BASE,)))
        b.jump8(0xEB, "variant_alias_map")
    else:
        b.emit(bytes.fromhex("a8 01"))          # TEST AL,1
        b.jump8(0x74, "selector_early_done")
    if not TRACE_STORED_X_LOW2 and PACK_STORED_ODD_ALIAS:
        b.emit(b"\xba" + struct.pack("<H", STORED_ODD_ALIAS_BASE))
        b.jump8(0xEB, "variant_alias_map")
    elif not TRACE_STORED_X_LOW2:
        b.emit(b"\xbb" + struct.pack("<H", SLOT_STORED_ODD))
        b.jump8(0xEB, "fetch_variant")

    b.label("mirrored_orientation")
    if TRACE_MIRRORED_X_LOW2:
        b.emit(bytes.fromhex("8b d0"))          # DX = final screen X
        b.emit(bytes.fromhex("83 e2 03"))       # DX &= 3
        b.emit(b"\x83\xc2" + bytes((MIRRORED_EVEN_ALIAS_BASE,)))
        b.jump8(0xEB, "variant_alias_map")
    elif PACK_MIRRORED_ALIASES:
        # Runtime testing established that this zero-orientation branch is
        # leftward travel.  Both cases retain the stored-orientation header so
        # Prince performs its proven native flip.  Convert the selected source
        # image ranges to ordinal 0..35, then add the phase-specific alias base
        # in the one private slot known to survive the level loader.
        b.emit(b"\xba" + struct.pack("<H", MIRRORED_EVEN_ALIAS_BASE))
        b.emit(bytes.fromhex("a8 01"))          # TEST AL,1
        b.jump8(0x74, "variant_alias_map")
        b.emit(b"\xba" + struct.pack("<H", MIRRORED_ODD_ALIAS_BASE))
    if TRACE_MIRRORED_X_LOW2 or PACK_MIRRORED_ALIASES:
        b.label("variant_alias_map")
        b.emit(bytes.fromhex("83 f9 0f"))       # CMP CX,15
        b.jump8(0x72, "mirrored_alias_add")    # IDs 0..14 => ordinal unchanged
        b.emit(bytes.fromhex("83 f9 2c"))       # CMP CX,44
        b.jump8(0x72, "selector_early_done")
        b.emit(bytes.fromhex("83 f9 34"))       # CMP CX,52
        b.jump8(0x72, "mirrored_alias_group_44")
        b.emit(bytes.fromhex("83 f9 40"))       # CMP CX,64
        b.jump8(0x72, "selector_early_done")
        b.emit(bytes.fromhex("83 f9 4d"))       # CMP CX,77
        b.jump8(0x73, "selector_early_done")
        b.emit(bytes.fromhex("83 e9 29"))       # IDs 64..76 => ordinal 23..35
        b.jump8(0xEB, "mirrored_alias_add")
        b.label("mirrored_alias_group_44")
        b.emit(bytes.fromhex("83 e9 1d"))       # IDs 44..51 => ordinal 15..22
        b.label("mirrored_alias_add")
        if FIXED_VARIANT_ALIAS_IDS:
            b.emit(bytes.fromhex("8b ca"))      # CX = one fixed variant ID
        else:
            b.emit(bytes.fromhex("03 ca"))      # CX += alias base in DX
        b.emit(b"\xbb" + struct.pack("<H", SLOT_STORED_ODD))
        b.jump8(0xEB, "fetch_variant")
    elif FORCE_MIRRORED_ODD:
        b.emit(b"\xbb" + struct.pack("<H", SLOT_MIRRORED_ODD))
        b.jump8(0xEB, "fetch_variant")
    else:
        b.emit(bytes.fromhex("a8 01"))          # TEST AL,1
        b.jump8(0x74, "mirrored_even")
        b.emit(b"\xbb" + struct.pack("<H", SLOT_MIRRORED_ODD))
        b.jump8(0xEB, "fetch_variant")
        b.label("mirrored_even")
    if (
        not PACK_MIRRORED_ALIASES
        and not FORCE_MIRRORED_ODD
        and USE_PRIVATE_MIRRORED_EVEN
    ):
        b.emit(b"\xbb" + struct.pack("<H", SLOT_MIRRORED_EVEN))
        b.jump8(0xEB, "fetch_variant")

    b.label("selector_early_done")
    b.jump16("selector_done")

    b.label("fetch_variant")
    b.emit(bytes.fromhex("d1 e3"))             # slot *= 2
    b.emit(bytes.fromhex("8b b7 34 45"))       # SI = chtab_addrs[slot]
    b.emit(bytes.fromhex("0b f6"))
    b.jump8(0x74, "selector_done")
    b.emit(bytes.fromhex("8b d9 d1 e3 d1 e3 03 de"))  # selected image ID * 4 + table
    b.emit(bytes.fromhex("8b 47 06 8b 57 08")) # DX:AX = private image
    # Preserve the exact offset in DI before the destructive OR null test.
    # V3/V4 stored OR(offset,segment) as the offset, which corrupted every
    # private far pointer and could hang the CGA converter.
    b.emit(bytes.fromhex("8b f8 0b c2"))
    b.jump8(0x74, "selector_done")             # sparse miss => normal table

    # Kid slot 2 and private slots 3/4/9 all have chtab_shift zero.  They do
    # not contain a generated second-half mask array.  Prince begins with the
    # same raw image pointer in both locals, then its unchanged B5A4-BFFE CGA
    # path creates/chooses the working representation.  Reproduce that exact
    # state; requiring a nonexistent private mask made every prior selector
    # fall back to the normal one-dot image.
    b.emit(bytes.fromhex("89 7e e6 89 56 e8"))
    b.emit(bytes.fromhex("89 7e fa 89 56 fc"))

    b.label("selector_done")
    _pop_all(b)
    b.emit(b"\xcb")                            # RETF

    b.label("load_variants")
    _push_all(b)
    b.emit(bytes.fromhex("80 3e 35 31") + bytes((COMPOSITE_GAME_GRAPHICS_MODE,)))
    b.jump8(0x75, "load_done")                 # only load tables in CGA mode
    for slot, base, _mirrored, _phase, _name in PRIVATE_TABLES:
        b.emit(b"\xb8" + struct.pack("<H", slot))
        b.emit(b"\xbb" + struct.pack("<H", base))
        b.call16("load_one")
    b.label("load_done")
    _pop_all(b)
    b.emit(
        bytes.fromhex("80 3e 35 31")
        + bytes((ORIGINAL_LOAD_COMPARE_GRAPHICS_MODE,))
    )                                           # displaced original CMP mode 5
    b.emit(b"\xcb")                            # RETF with CMP flags intact

    b.label("load_one")
    b.emit(bytes.fromhex("50 53"))             # slot, resource base
    b.emit(bytes.fromhex("b8 14 04 50"))       # DS:0414 = "kid.dat"
    b.emit(bytes.fromhex("b8 80 00 50"))       # Kid palette hardware flag
    # Match Prince's own Kid-table call exactly instead of using the FFFF
    # unconditional load path.
    b.emit(b"\xb8" + struct.pack("<H", KID_TABLE_AUXILIARY_OFFSET) + b"\x50")
    b.far_call(0x152D, 0x0000)
    b.emit(b"\xc3")                            # RET; callee removed five args

    b.label("reserve_heap")
    # A FAR CALL has already consumed four stack bytes.  Add those back while
    # reserving HEAP_RESERVE_BYTES above the caller's original stack ceiling.
    b.emit(bytes.fromhex("8b c4"))              # MOV AX,SP
    b.emit(b"\x05" + struct.pack("<H", HEAP_RESERVE_BYTES + 4))
    b.emit(bytes.fromhex("36 a3 fe 2d"))        # heap current cursor
    b.emit(bytes.fromhex("36 a3 fa 2d"))        # heap initial cursor
    b.emit(b"\xcb")                            # RETF

    code, relocations = b.finish()
    return code, dict(b.labels), relocations


def _replace_unique(data: bytes, old: bytes, new: bytes, label: str) -> bytes:
    if len(old) != len(new):
        raise ValueError(f"{label} replacement changes binary length")
    if data.count(old) != 1:
        raise ValueError(f"expected exactly one {label}")
    return data.replace(old, new)


def _add_mz_relocations(
    header: bytearray, relocations: Iterable[tuple[int, int]]
) -> None:
    additions = tuple(relocations)
    count = struct.unpack_from("<H", header, 0x06)[0]
    table_offset = struct.unpack_from("<H", header, 0x18)[0]
    end = table_offset + (count + len(additions)) * 4
    if end > len(header):
        raise ValueError("MZ header has insufficient relocation padding")
    for index, (offset, segment) in enumerate(additions, start=count):
        struct.pack_into("<HH", header, table_offset + index * 4, offset, segment)
    struct.pack_into("<H", header, 0x06, count + len(additions))


def patch_executable(unpacked: bytes) -> tuple[bytes, dict[str, object]]:
    header_size, original_module = mz_load_module(unpacked)
    header = bytearray(unpacked[:header_size])
    module = bytearray(original_module)
    if (
        module[
            SELECTOR_HOOK_OFFSET : SELECTOR_HOOK_OFFSET
            + len(SELECTOR_HOOK_SIGNATURE)
        ]
        != SELECTOR_HOOK_SIGNATURE
    ):
        raise ValueError("draw_mid pre-conversion selector hook signature mismatch")
    if module[HOOK_OFFSET : HOOK_OFFSET + len(HOOK_SIGNATURE)] != HOOK_SIGNATURE:
        raise ValueError("draw_mid original final-X join signature mismatch")
    if module[LOAD_HOOK_OFFSET : LOAD_HOOK_OFFSET + len(LOAD_HOOK_SIGNATURE)] != LOAD_HOOK_SIGNATURE:
        raise ValueError("level sprite-loader hook signature mismatch")
    if module[
        STARTUP_HEAP_HOOK_OFFSET : STARTUP_HEAP_HOOK_OFFSET + len(STARTUP_HEAP_SIGNATURE)
    ] != STARTUP_HEAP_SIGNATURE:
        raise ValueError("Microsoft C startup heap-base signature mismatch")
    if module[CAVE_OFFSET : CAVE_OFFSET + CAVE_CAPACITY] != bytes(CAVE_CAPACITY):
        raise ValueError("verified low-segment trampoline cave is occupied")

    high_code, labels, high_relocations = build_high_code()
    capacity = ORIGINAL_TOTAL_PARAGRAPHS * 16 - HIGH_CODE_LINEAR
    if len(high_code) > capacity:
        raise ValueError(f"high code is {len(high_code)} bytes; only {capacity} fit")

    # Pre-conversion hook -> low near trampoline -> relocated high FAR
    # selector.  The trampoline recreates the displaced Kid-table CMP so the
    # original JNE at B598 observes exactly the original flags.
    displacement = (CAVE_OFFSET - (SELECTOR_HOOK_OFFSET + 3)) & 0xFFFF
    module[SELECTOR_HOOK_OFFSET : SELECTOR_HOOK_OFFSET + 4] = (
        b"\xe8" + struct.pack("<H", displacement) + b"\x90"
    )
    trampoline = (
        b"\x9a"
        + struct.pack("<HH", labels["selector"], HIGH_CODE_SEGMENT)
        + bytes.fromhex("83 7e ea 02 c3")
    )
    module[CAVE_OFFSET : CAVE_OFFSET + len(trampoline)] = trampoline

    # Sprite-load comparison -> relocated high FAR loader.  The high routine
    # executes the same CMP directly before RETF, preserving flags for F65.
    module[LOAD_HOOK_OFFSET : LOAD_HOOK_OFFSET + 5] = (
        b"\x9a" + struct.pack("<HH", labels["load_variants"], HIGH_CODE_SEGMENT)
    )

    # Reserve the injected region before Microsoft C's first allocation.  The
    # original ten bytes only copied SP to two heap cursors; our high routine
    # stores original-SP + HEAP_RESERVE_BYTES instead.
    startup_heap_call = b"\x9a" + struct.pack(
        "<HH", labels["reserve_heap"], HIGH_CODE_SEGMENT
    )
    module[
        STARTUP_HEAP_HOOK_OFFSET : STARTUP_HEAP_HOOK_OFFSET + len(STARTUP_HEAP_SIGNATURE)
    ] = startup_heap_call + b"\x90" * (len(STARTUP_HEAP_SIGNATURE) - len(startup_heap_call))

    if len(module) > HIGH_CODE_LINEAR:
        raise ValueError("unpacked load module unexpectedly overlaps high-code region")
    module.extend(bytes(HIGH_CODE_LINEAR - len(module)))
    module.extend(high_code)

    marked = bytes(module)
    if marked.find(ORIGINAL_VERSION) != VERSION_OFFSET:
        raise ValueError("Prince version marker moved from its verified offset")
    marked = _replace_unique(marked, ORIGINAL_VERSION, PROTOTYPE_VERSION, "version marker")
    module = bytearray(marked)

    relocation_records = [
        (LOAD_HOOK_OFFSET + 3, 0),
        (CAVE_OFFSET + 3, 0),
        (STARTUP_HEAP_HOOK_LOGICAL_OFFSET + 3, STARTUP_HEAP_HOOK_SEGMENT),
        *((offset, HIGH_CODE_SEGMENT) for offset in high_relocations),
    ]
    _add_mz_relocations(header, relocation_records)

    module_paragraphs = (len(module) + 15) // 16
    if module_paragraphs > ORIGINAL_TOTAL_PARAGRAPHS:
        raise ValueError("patch would increase Prince's minimum DOS allocation")
    minimum_allocation = ORIGINAL_TOTAL_PARAGRAPHS - module_paragraphs
    struct.pack_into("<H", header, 0x0A, minimum_allocation)
    total_bytes = header_size + len(module)
    pages = (total_bytes + 511) // 512
    final_page_bytes = total_bytes & 0x1FF
    struct.pack_into("<HH", header, 0x02, final_page_bytes, pages)

    executable = bytes(header) + bytes(module)
    metadata: dict[str, object] = {
        "file": OUTPUT_EXE,
        "bytes": len(executable),
        "sha256": sha256(executable),
        "visible_ctrl_v_marker": PROTOTYPE_VERSION.decode("ascii"),
        "draw_hook": f"0000:{SELECTOR_HOOK_OFFSET:04X}",
        "original_final_x_join": f"0000:{HOOK_OFFSET:04X}",
        "load_hook": f"0000:{LOAD_HOOK_OFFSET:04X}",
        "trampoline": f"0000:{CAVE_OFFSET:04X}",
        "high_code": f"{HIGH_CODE_SEGMENT:04X}:0000",
        "high_code_bytes": len(high_code),
        "high_code_capacity": capacity,
        "runtime_heap_reservation_bytes": HEAP_RESERVE_BYTES,
        "startup_heap_hook": (
            f"{STARTUP_HEAP_HOOK_SEGMENT:04X}:"
            f"{STARTUP_HEAP_HOOK_LOGICAL_OFFSET:04X}"
        ),
        "relocations_added": len(relocation_records),
        "minimum_allocation_paragraphs": minimum_allocation,
        "dos_total_allocation_paragraphs": module_paragraphs + minimum_allocation,
        "uses_xms": False,
        "uses_ems": False,
    }
    return executable, metadata


def patch_prototype_launcher(original: bytes) -> bytes:
    source = original
    if sha256(source) == V9_LAUNCHER_SHA256:
        if source.count(V9_CHILD_NAME) != 3 or source.count(V9_PROTOTYPE_BANNER) != 1:
            raise ValueError("V9 launcher does not contain its expected patch markers")
        source = source.replace(V9_CHILD_NAME, b"PRINCE.EXE")
        source = source.replace(V9_PROTOTYPE_BANNER, ORIGINAL_BANNER)
    if sha256(source) != EXPECTED_LAUNCHER_SHA256:
        raise ValueError("wrong CGAPRINC.COM/CGA4K9.COM launcher build")
    child = patch_launcher(source, CHILD_NAME)
    return _replace_unique(child, ORIGINAL_BANNER, PROTOTYPE_BANNER, "launcher banner")


def _mirror_raster(source: RenderedRaster) -> RenderedRaster:
    if source.channels != 3:
        raise ValueError("expected an RGB source raster")
    row_bytes = source.width * 3
    output = bytearray(len(source.pixels))
    for y in range(source.height):
        row = source.pixels[y * row_bytes : (y + 1) * row_bytes]
        for x in range(source.width):
            source_offset = (source.width - 1 - x) * 3
            destination = y * row_bytes + x * 3
            output[destination : destination + 3] = row[source_offset : source_offset + 3]
    return RenderedRaster(source.width, source.height, bytes(output), 3, source.mode)


def _mirror_mask(mask: tuple[bool, ...], width: int, height: int) -> tuple[bool, ...]:
    return tuple(
        mask[y * width + (width - 1 - x)]
        for y in range(height)
        for x in range(width)
    )


def selected_image_ordinal(image_id: int) -> int:
    """Map the three selected Kid ID ranges to packed ordinal 0..35."""

    if 0 <= image_id < 15:
        return image_id
    if 44 <= image_id < 52:
        return image_id - 29
    if 64 <= image_id < 77:
        return image_id - 41
    raise ValueError(f"Kid image ID {image_id} is not selected")


def reverse_mode6_cga_pixel_rows(bits: bytes, width: int, height: int) -> bytes:
    """Reverse two-sample CGA pixels while preserving each pixel's bit order.

    Prince flips original image pixels, not individual 640-column carrier
    samples. Each source pixel becomes two adjacent Mode-6 samples, so the
    right-facing path reverses those two-sample groups as indivisible units.
    """

    if len(bits) != width * height:
        raise ValueError("Mode-6 bitstream dimensions are inconsistent")
    if width & 1:
        raise ValueError("Mode-6 CGA-pixel reversal requires an even width")
    return b"".join(
        b"".join(
            reversed(
                tuple(
                    bits[y * width + x : y * width + x + 2]
                    for x in range(0, width, 2)
                )
            )
        )
        for y in range(height)
    )


def runtime_display_bits(
    stored_bits: bytes,
    width: int,
    height: int,
    direction: str,
) -> bytes:
    """Return the bit order observed on screen for one stored Kid image.

    The right/nonzero path reverses stored two-sample CGA pixel groups. On the
    left/zero path Prince's native flip yields stored Mode-6 order directly.
    """

    if direction == "right":
        return reverse_mode6_cga_pixel_rows(stored_bits, width, height)
    if direction == "left":
        return stored_bits
    raise ValueError(f"unsupported runtime direction: {direction}")


def representable_2bit_codes(image: object, hardware: object) -> tuple[tuple[int, ...], ...] | None:
    bits = getattr(image, "bits")
    if bits == 1:
        return None
    table = getattr(hardware, "cga_translation", ()) if hardware is not None else ()
    pixels = getattr(image, "pixels")
    width = getattr(image, "width")
    height = getattr(image, "height")
    if len(table) != 64:
        return tuple((0, 1, 2, 3) for _ in pixels)
    return tuple(
        tuple(sorted(set(table[phase * 16 : phase * 16 + 16])))
        for y in range(height)
        for x in range(width)
        for phase in (((y & 1) << 1) | (x & 1),)
    )


def _enforce_transparency_mask(
    pixels: bytes,
    edit: CompositeEdit,
    image: object,
    hardware: object,
    zero_mask: tuple[bool, ...],
    target: RenderedRaster,
) -> bytes:
    """Preserve Prince's exact source-index-zero transparency semantics.

    Composite preservation alone constrains a transparent pixel to CGA code
    00, but several nonzero VGA indices can translate to that same code.  A
    mirrored sprite also moves the silhouette, so the unmirrored template is
    not a safe tie-breaker.  Force transparent pixels to source index zero and
    force every opaque pixel away from zero while retaining its optimized CGA
    two-bit code.
    """

    width = getattr(image, "width")
    height = getattr(image, "height")
    if getattr(image, "bits") != 4:
        raise ValueError("four-way Kid prototype expects 4-bit source images")
    if len(pixels) != width * height or len(zero_mask) != len(pixels):
        raise ValueError("transparency mask dimensions are inconsistent")
    table = getattr(hardware, "cga_translation", ()) if hardware is not None else ()
    colors = getattr(hardware, "colors", ()) if hardware is not None else ()
    output = bytearray(pixels)

    def translated(candidate: int, phase: int) -> int:
        return table[phase * 16 + candidate] if len(table) == 64 else candidate & 3

    for offset, transparent in enumerate(zero_mask):
        y, x = divmod(offset, width)
        bit_offset = y * edit.bit_width + x * 2
        desired = (edit.bits[bit_offset] << 1) | edit.bits[bit_offset + 1]
        phase = ((y & 1) << 1) | (x & 1)
        if transparent:
            if translated(0, phase) != desired:
                raise ValueError("optimized transparent pixel is not representable by index zero")
            output[offset] = 0
            continue
        if output[offset] != 0:
            continue
        candidates = [
            candidate
            for candidate in range(1, 16)
            if translated(candidate, phase) == desired
        ]
        if not candidates:
            raise ValueError("opaque CGA code has no nonzero source-index representation")
        rgb_offset = offset * 3
        expected = target.pixels[rgb_offset : rgb_offset + 3]

        def color_error(candidate: int) -> tuple[int, int]:
            color = colors[candidate] if candidate < len(colors) else (0, 0, 0)
            return (
                sum((color[channel] - expected[channel]) ** 2 for channel in range(3)),
                candidate,
            )

        output[offset] = min(candidates, key=color_error)
    return bytes(output)


def _build_dat(resources: Iterable[tuple[int, bytes]]) -> bytes:
    body = bytearray(6)
    records: list[tuple[int, int, int]] = []
    previous_id = -1
    for resource_id, content in resources:
        if resource_id <= previous_id:
            raise ValueError("DAT resource IDs must be strictly increasing")
        previous_id = resource_id
        if len(content) > 0xFFFF:
            raise ValueError(f"resource {resource_id} exceeds the DAT size field")
        offset = len(body)
        checksum = (-1 - sum(content)) & 0xFF
        body.append(checksum)
        body.extend(content)
        records.append((resource_id, offset, len(content)))
    index_offset = len(body)
    index_size = 2 + len(records) * 8
    struct.pack_into("<IH", body, 0, index_offset, index_size)
    body.extend(struct.pack("<H", len(records)))
    for record in records:
        body.extend(struct.pack("<HIH", *record))
    return bytes(body)


def _decoded_raster_rmse(first: object, second: object) -> float:
    first_pixels = getattr(first, "pixels")
    second_pixels = getattr(second, "pixels")
    if (
        getattr(first, "width") != getattr(second, "width")
        or getattr(first, "height") != getattr(second, "height")
        or getattr(first, "channels") != getattr(second, "channels")
        or len(first_pixels) != len(second_pixels)
    ):
        raise ValueError("phase-pair previews have inconsistent dimensions")
    return math.sqrt(
        sum((left - right) ** 2 for left, right in zip(first_pixels, second_pixels))
        / len(first_pixels)
    )


def _encode_variant_result(
    target_analysis: object,
    target_hardware: object,
    display_result: object,
    stored_bits: bytes,
    phase_offset: int,
    raw_zero_mask: tuple[bool, ...],
    raw_target_raster: RenderedRaster,
    encoded_resource_id: int,
    image_id: int,
    orientation_bit: bool,
    direction: str,
    native_flip: bool,
) -> tuple[bytes, dict[str, object]]:
    target_image = getattr(target_analysis, "image")
    target_resource = getattr(target_analysis, "resource")
    edit = CompositeEdit(
        resource_index=target_resource.index,
        resource_id=target_resource.resource_id,
        source_width=target_image.width,
        height=target_image.height,
        source_depth=target_image.bits,
        bit_width=mode6_width(target_image),
        bits=bytearray(stored_bits),
        signal_phase=phase_offset,
    )
    pixels = source_pixels_for_edit(target_image, edit, target_hardware)
    pixels = _enforce_transparency_mask(
        pixels,
        edit,
        target_image,
        target_hardware,
        raw_zero_mask,
        raw_target_raster,
    )
    # V18 proved that every runtime case must retain the stored-orientation
    # header. Prince reverses two-sample source-pixel groups on the right and
    # performs its original native flip on the left. The low
    # format/algorithm bits remain unchanged, so the CGA adapter still performs
    # the normal 4-bit source conversion.
    encoded = bytearray(encode_image_lzg(target_resource.data, target_image, pixels))
    if orientation_bit:
        encoded[5] |= 0x80
    else:
        encoded[5] &= 0x7F
    content = bytes(encoded)
    decoded = decode_prince_image(content)
    if decoded.pixels != pixels:
        raise AssertionError("phase-aware image failed encode/decode verification")
    if tuple(value == 0 for value in decoded.pixels) != raw_zero_mask:
        raise AssertionError("phase-aware image failed transparency-mask verification")
    decoded_stored_bits = bytes(initial_mode6_bits(decoded, target_hardware))
    if decoded_stored_bits != stored_bits:
        raise AssertionError("phase-aware image failed optimized Mode-6 verification")
    displayed_bits = runtime_display_bits(
        decoded_stored_bits,
        edit.bit_width,
        target_image.height,
        direction,
    )
    if displayed_bits != bytes(getattr(display_result, "bits")):
        raise AssertionError("stored image does not reproduce the optimized runtime signal")
    record: dict[str, object] = {
        "image_id": image_id,
        "source_resource_id": target_resource.resource_id,
        "encoded_resource_id": encoded_resource_id,
        "width": target_image.width,
        "height": target_image.height,
        "orientation_bit": bool(content[5] & 0x80),
        "runtime_direction": direction,
        "prince_native_flip": native_flip,
        "phase_offset_mode6_bits": phase_offset,
        "stored_mode6_sha256": hashlib.sha256(decoded_stored_bits).hexdigest(),
        "runtime_mode6_sha256": hashlib.sha256(displayed_bits).hexdigest(),
        "signal_rmse": round(display_result.source_rmse, 6),
        "encoded_bytes": len(content),
    }
    if encoded_resource_id != target_resource.resource_id:
        record["private_resource_id"] = encoded_resource_id
    return content, record


def build_four_way_dat(
    source_path: Path, converted_path: Path, destination: Path
) -> tuple[dict[str, object], dict[str, object]]:
    source_payload = source_path.read_bytes()
    converted_payload = converted_path.read_bytes()
    if sha256(source_payload) != EXPECTED_SOURCE_KID_SHA256:
        raise ValueError("source KID.DAT is not the verified original VGA archive")
    if sha256(converted_payload) != EXPECTED_PHASE0_BASELINE_KID_SHA256:
        raise ValueError(
            "converted KID.DAT is not the verified VGA Exhaustive phase-0 baseline"
        )
    source_archive = DatArchive.open(source_path)
    converted_archive = DatArchive.open(converted_path)
    if [item.resource_id for item in source_archive.resources] != list(range(400, 620)):
        raise ValueError("source KID.DAT does not have the expected 400..619 resources")
    if [item.resource_id for item in converted_archive.resources] != list(range(400, 620)):
        raise ValueError("converted KID.DAT does not have the expected 400..619 resources")

    header = converted_archive.resources[0].data
    if len(header) != 100 or header[0] != 219:
        raise ValueError("KID palette/header does not declare 219 images")

    normal_replacements: dict[int, bytes] = {}
    private_payloads: dict[str, list[tuple[int, bytes]]] = {
        name: [] for name, _alias, _direction, _phase, _flip in PRIVATE_VARIANTS
    }
    variant_records: dict[str, object] = {
        "right-even": {
            "slot": 2,
            "resource_base": 400,
            "alias_base": None,
            "runtime_direction": "right",
            "phase_offset_mode6_bits": 0,
            "prince_native_flip": False,
            "orientation_bit": True,
            "images": [],
        }
    }
    for name, alias_base, direction, phase_offset, native_flip in PRIVATE_VARIANTS:
        variant_records[name] = {
            "slot": SLOT_STORED_ODD,
            "resource_base": PRIVATE_RESOURCE_BASE,
            "alias_base": alias_base,
            "runtime_direction": direction,
            "phase_offset_mode6_bits": phase_offset,
            "prince_native_flip": native_flip,
            "orientation_bit": True,
            "images": [],
        }

    alias_by_name = {
        name: alias_base
        for name, alias_base, _direction, _phase, _flip in PRIVATE_VARIANTS
    }
    pair_metrics: list[dict[str, object]] = []
    for progress, image_id in enumerate(SELECTED_IMAGE_IDS, start=1):
        resource_id = 401 + image_id
        source_analysis = source_archive.analysis_by_id(resource_id)
        target_analysis = converted_archive.analysis_by_id(resource_id)
        if (
            source_analysis is None
            or source_analysis.image is None
            or target_analysis is None
            or target_analysis.image is None
        ):
            raise ValueError(f"missing Kid image resource {resource_id}")
        source_image = source_analysis.image
        target_image = target_analysis.image
        if (source_image.width, source_image.height, source_image.bits) != (
            target_image.width,
            target_image.height,
            target_image.bits,
        ):
            raise ValueError(f"Kid image geometry changed for resource {resource_id}")

        source_hardware = hardware_palette_for_resource(
            source_archive, source_analysis.resource
        )
        target_hardware = hardware_palette_for_resource(
            converted_archive, target_analysis.resource
        )
        base_raster = render_display_mode(
            source_image, SOURCE_DISPLAY_MODE, source_hardware
        )
        base_mask = tuple(value == 0 for value in source_image.pixels)
        allowed_codes = representable_2bit_codes(target_image, target_hardware)
        if allowed_codes is not None and any(
            codes != (0, 1, 2, 3) for codes in allowed_codes
        ):
            raise ValueError(
                f"Kid resource {resource_id} cannot represent all Mode-6 codes"
            )
        bit_width = mode6_width(target_image)

        # The source DAT raster is the editor-left/stored orientation observed
        # in V18. Rightward travel reverses source pixels (two Mode-6 samples
        # per pixel); left travel invokes Prince's native flip and displays the
        # stored Mode-6 order directly. Optimize in final on-screen order, then
        # reverse two-sample groups in right-hand bitstreams for storage.
        for direction, even_name, odd_name, native_flip in (
            ("right", "right-even", "right-odd", False),
            ("left", "left-even", "left-odd", True),
        ):
            display_raster = (
                _mirror_raster(base_raster) if direction == "right" else base_raster
            )
            display_mask = (
                _mirror_mask(base_mask, source_image.width, source_image.height)
                if direction == "right"
                else base_mask
            )
            encoded_cases = []
            phase_results: dict[int, object] = {}
            for name, phase_offset in (
                (even_name, 0),
                (odd_name, 2),
            ):
                settings = ConversionSettings(
                    phase_offset=phase_offset,
                    **SETTINGS_BASE,
                )
                result = convert_raster_to_exhaustive(
                    display_raster,
                    bit_width,
                    target_image.height,
                    COMPOSITE_PROFILE_NEW,
                    settings,
                    source_zero_mask=display_mask,
                )
                phase_results[phase_offset] = result
                display_bits = bytes(result.bits)
                stored_bits = (
                    reverse_mode6_cga_pixel_rows(
                        display_bits,
                        bit_width,
                        target_image.height,
                    )
                    if direction == "right"
                    else display_bits
                )
                encoded_resource_id = (
                    resource_id
                    if name == "right-even"
                    else PRIVATE_RESOURCE_BASE
                    + 1
                    + alias_by_name[name]
                    + selected_image_ordinal(image_id)
                )
                content, record = _encode_variant_result(
                    target_analysis,
                    target_hardware,
                    result,
                    stored_bits,
                    phase_offset,
                    base_mask,
                    base_raster,
                    encoded_resource_id,
                    image_id,
                    True,
                    direction,
                    native_flip,
                )
                encoded_cases.append((name, encoded_resource_id, content, record))

            even_result = phase_results[0]
            odd_result = phase_results[2]
            pair_rmse = _decoded_raster_rmse(
                getattr(even_result, "preview"),
                getattr(odd_result, "preview"),
            )
            for name, encoded_resource_id, content, record in encoded_cases:
                record["phase_pair_rmse"] = round(pair_rmse, 6)
                variant_records[name]["images"].append(record)
                if name == "right-even":
                    normal_replacements[resource_id] = content
                else:
                    private_payloads[name].append((encoded_resource_id, content))
            pair_metrics.append(
                {
                    "image_id": image_id,
                    "runtime_direction": direction,
                    "decoded_pair_rmse": round(pair_rmse, 6),
                    "even_source_rmse": round(
                        float(getattr(even_result, "source_rmse")), 6
                    ),
                    "odd_source_rmse": round(
                        float(getattr(odd_result, "source_rmse")), 6
                    ),
                }
            )
            print(
                f"{even_name}/{odd_name:12s} {progress:02d}/{len(SELECTED_IMAGE_IDS)} "
                f"image={image_id:3d} pair-rmse={pair_rmse:.3f} "
                f"source={getattr(even_result, 'source_rmse'):.3f}/"
                f"{getattr(odd_result, 'source_rmse'):.3f}",
                flush=True,
            )

    appended: list[tuple[int, bytes]] = [(PRIVATE_RESOURCE_BASE, header)]
    for name, _alias, _direction, _phase, _flip in PRIVATE_VARIANTS:
        appended.extend(private_payloads[name])

    resources = [
        (item.resource_id, normal_replacements.get(item.resource_id, item.data))
        for item in converted_archive.resources
    ]
    resources.extend(appended)
    payload = _build_dat(resources)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    verification = DatArchive.open(destination)
    if not all(item.checksum_ok for item in verification.resources):
        raise ValueError("output KID.DAT checksum verification failed")
    private_image_count = len(PRIVATE_VARIANTS) * len(SELECTED_IMAGE_IDS)
    if len(verification.resources) != 220 + 1 + private_image_count:
        raise ValueError("output KID.DAT resource count is incorrect")
    selected_resource_ids = {401 + image_id for image_id in SELECTED_IMAGE_IDS}
    for before, after in zip(converted_archive.resources, verification.resources[:220]):
        if before.resource_id in selected_resource_ids:
            if before.resource_id != after.resource_id:
                raise ValueError("selected normal KID resource ID changed")
            continue
        if (before.resource_id, before.data) != (after.resource_id, after.data):
            raise ValueError("an unselected normal KID resource changed")

    packed_memory_per_variant = sum(
        ((converted_archive.analysis_by_id(401 + image_id).image.width + 1) // 2)
        * converted_archive.analysis_by_id(401 + image_id).image.height
        + 6
        for image_id in SELECTED_IMAGE_IDS
    )
    pointer_table_bytes = 6 + header[0] * 4
    memory_estimate = (
        len(PRIVATE_VARIANTS) * packed_memory_per_variant + pointer_table_bytes
    )
    signal_rmse_values = [
        float(record["signal_rmse"])
        for variant in variant_records.values()
        for record in variant["images"]
    ]
    metadata: dict[str, object] = {
        "file": OUTPUT_DAT,
        "bytes": len(payload),
        "sha256": sha256(payload),
        "normal_resources_preserved_byte_identical": 220 - len(SELECTED_IMAGE_IDS),
        "selected_normal_resources_reencoded": len(SELECTED_IMAGE_IDS),
        "private_resources_added": len(appended),
        "private_table_count": 1,
        "private_image_count": private_image_count,
        "private_alias_ranges": {
            name: [alias_base, alias_base + len(SELECTED_IMAGE_IDS) - 1]
            for name, alias_base, _direction, _phase, _flip in PRIVATE_VARIANTS
        },
        "selected_image_count": len(SELECTED_IMAGE_IDS),
        "selected_image_ids": list(SELECTED_IMAGE_IDS),
        "selected_game_frames": {
            name: f"{frame_first}-{frame_last}"
            for name, frame_first, frame_last, _image_first, _image_last
            in SELECTED_FRAME_IMAGE_RANGES
        },
        "selected_frame_image_mapping": {
            f"frames_{frame_first}_{frame_last}": f"images_{image_first}_{image_last}"
            for _name, frame_first, frame_last, image_first, image_last
            in SELECTED_FRAME_IMAGE_RANGES
        },
        "conventional_memory_upper_estimate_bytes": memory_estimate,
        "conversion_mode": CONVERSION_MODE,
        "phase_consistency_percent": PHASE_CONSISTENCY,
        "source_rmse_average": round(
            sum(signal_rmse_values) / len(signal_rmse_values), 6
        ),
        "source_rmse_maximum": round(max(signal_rmse_values), 6),
        "phase_pair_rmse_average": round(
            sum(float(record["decoded_pair_rmse"]) for record in pair_metrics)
            / len(pair_metrics),
            6,
        ),
        "phase_pairs": pair_metrics,
        "runtime_transform": {
            "right": (
                "stored two-sample CGA pixel groups reversed at display; "
                "sample order inside each group preserved"
            ),
            "left": "Prince native flip yields stored Mode-6 order directly",
            "all_selected_orientation_bits": True,
        },
        "xms_bytes": 0,
        "ems_bytes": 0,
    }
    return metadata, variant_records


def build(
    prince_path: Path,
    launcher_path: Path,
    source_kid_path: Path,
    converted_kid_path: Path,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    packed = prince_path.read_bytes()
    original_launcher = launcher_path.read_bytes()
    unpacked = unpack_exepack(packed)
    executable, executable_metadata = patch_executable(unpacked)
    launcher = patch_prototype_launcher(original_launcher)
    (output_dir / OUTPUT_EXE).write_bytes(executable)
    (output_dir / OUTPUT_COM).write_bytes(launcher)

    dat_metadata, variants = build_four_way_dat(
        source_kid_path, converted_kid_path, output_dir / OUTPUT_DAT
    )
    manifest = {
        "prototype": (
            "Prince of Persia 1.3 Exhaustive VGA Kid phase-stable selector v12"
        ),
        "scope": (
            "VGA-derived phase-aware Kid idle/run/turn/run-turn plus a VGA "
            "Exhaustive no-dither phase-0 baseline for every unselected image"
        ),
        "sources": {
            "prince": {
                "file": prince_path.name,
                "bytes": len(packed),
                "sha256": sha256(packed),
            },
            "launcher": {
                "file": launcher_path.name,
                "bytes": len(original_launcher),
                "sha256": sha256(original_launcher),
            },
            "source_kid": {
                "file": source_kid_path.name,
                "bytes": source_kid_path.stat().st_size,
                "sha256": sha256(source_kid_path.read_bytes()),
                "render_mode": SOURCE_DISPLAY_MODE,
            },
            "converted_kid": {
                "file": converted_kid_path.name,
                "bytes": converted_kid_path.stat().st_size,
                "sha256": sha256(converted_kid_path.read_bytes()),
                "role": (
                    "VGA Exhaustive no-dither phase-0 baseline for all "
                    "unselected normal Kid resources"
                ),
            },
        },
        "conversion_settings": {
            **asdict(ConversionSettings(phase_offset=0, **SETTINGS_BASE)),
            "conversion_mode": CONVERSION_MODE,
            "phase_variants": [0, 2],
            "phase_consistency_percent": PHASE_CONSISTENCY,
            "objective": (
                "four independent final-display waveforms per image; exact "
                "minimum summed absolute RGB error at the selected phase"
            ),
            "profile": COMPOSITE_PROFILE_NEW,
            "dither": "none",
            "detail_percent": 100,
            "color_emphasis_percent": 100,
            "quality_description": "exact 2,048-state row dynamic program",
        },
        "executable": executable_metadata,
        "launcher": {
            "file": OUTPUT_COM,
            "bytes": len(launcher),
            "sha256": sha256(launcher),
            "child": CHILD_NAME.decode("ascii"),
            "banner": PROTOTYPE_BANNER.decode("ascii").rstrip(),
        },
        "kid_dat": dat_metadata,
        "variants": variants,
    }
    manifest_path = output_dir / "MANIFEST.JSON"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prince", type=Path, default=WORKSPACE / "upload" / "PRINCE.EXE")
    parser.add_argument("--launcher", type=Path, default=WORKSPACE / "CGAPRINC.COM")
    parser.add_argument(
        "--source-kid",
        type=Path,
        default=WORKSPACE / "pop13_composite_batch" / "input" / "KID.DAT",
    )
    parser.add_argument(
        "--converted-kid",
        type=Path,
        default=(
            WORKSPACE
            / "pop13_composite_batch"
            / "output"
            / "Prince-of-Persia-New-CGA-Composite"
            / "patched-dats"
            / "KID.DAT"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR / "build")
    args = parser.parse_args()
    manifest = build(
        args.prince,
        args.launcher,
        args.source_kid,
        args.converted_kid,
        args.output_dir,
    )
    print(f"built four-way Kid prototype: {manifest}")


if __name__ == "__main__":
    main()
