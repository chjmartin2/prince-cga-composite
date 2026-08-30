#!/usr/bin/env python3
"""Build Prince 1.3 New-CGA V18 with complete phase-aware Kid coverage.

V18 preserves the user-confirmed V17 PHASE.DAT and PHASE2.DAT tables and
loads PHASE3.DAT through Prince's native chtab slot 9.  The final 70 playable
Kid images consume 210 aliases (right/P2, left/P0, left/P2); the remaining
nine aliases are valid, unreachable padding copies.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import zipfile

import build_v17 as v17


ROOT = Path(__file__).resolve().parent
V17 = (
    ROOT
    / "build"
    / "Prince-1.3-New-CGA-Phase-Aware-V17-PHASE2-Full-"
      "Dungeon-Version-B-DAT-Set"
)
SOURCE_KID = ROOT / "source_work" / "pop13" / "KID.DAT"
BASELINE_KID = ROOT / "source_work" / "baseline" / "KID.DAT"
ART_TOOL = v17.ART_TOOL
RENDER_TOOL = v17.RENDER_TOOL

BUILD_ROOT = ROOT / "build"
PACKAGE_NAME = (
    "Prince-1.3-New-CGA-Phase-Aware-V18-PHASE3-Complete-Kid-"
    "Dungeon-Version-B-DAT-Set"
)
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"
ART_WORK = BUILD_ROOT / "v18-art-work"

OUTPUT_EXE = "P4KX18.EXE"
OUTPUT_COM = "CGA4K18.COM"

V17_EXE_SHA256 = (
    "e1d35fe4e88499de00cf8d292150dad8f594ba0c7650715684d4951aa92917a6"
)
V17_COM_SHA256 = (
    "bc1b8d1fef025d4aa1b65640c49ae5a0e9573ff56bdbb844c2715850db2e1eba"
)
V17_KID_SHA256 = (
    "d3544a423d22319792b6b3f7829766283cf31a2cc4d18ae09ec8c8e0de9f3d49"
)
V17_PHASE_SHA256 = (
    "ef91ee76ce79f5f7e3753fc9d48a2d0e553066ebb4d75bb3648e89f1ea615792"
)
V17_PHASE2_SHA256 = (
    "eb5cc5c32da2424b9beb234df21a59153e9fc1e735e8520b8fc18ca12cbf5b19"
)
SOURCE_KID_SHA256 = v17.SOURCE_KID_SHA256
BASELINE_KID_SHA256 = v17.BASELINE_KID_SHA256

# Image IDs are authoritative.  The optimizer's legacy selection carrier also
# has frame fields; for V18 those fields deliberately mirror the image range
# rather than asserting an unverified frame-table number.
SELECTED_IMAGE_GROUPS = (
    ("exit_stairs", 52, 63),
    ("hazard_and_death_reactions", 77, 79),
    ("mouse", 130, 132),
    ("find_pick_up_and_sheathe_sword", 160, 173),
    ("sword_combat", 174, 191),
    ("drink_potion", 192, 206),
    ("collapse_and_death", 211, 215),
)
SELECTED_FRAME_IMAGE_RANGES = tuple(
    (name, image_first, image_last, image_first, image_last)
    for name, image_first, image_last in SELECTED_IMAGE_GROUPS
)
NEW_IMAGE_IDS = tuple(
    image_id
    for _name, image_first, image_last in SELECTED_IMAGE_GROUPS
    for image_id in range(image_first, image_last + 1)
)
if len(NEW_IMAGE_IDS) != 70 or len(set(NEW_IMAGE_IDS)) != 70:
    raise RuntimeError("V18 PHASE3 selection must contain exactly 70 unique images")

V17_IMAGE_IDS = tuple(sorted(set(
    list(range(0, 52))
    + list(range(64, 77))
    + list(range(80, 130))
    + list(range(133, 160))
    + list(range(207, 211))
    + list(range(112, 120))
)))
if len(V17_IMAGE_IDS) != 146:
    raise RuntimeError("V17 coverage model must contain 146 unique images")
if set(V17_IMAGE_IDS) & set(NEW_IMAGE_IDS):
    raise RuntimeError("V18 selection overlaps V17 coverage")
if set(V17_IMAGE_IDS) | set(NEW_IMAGE_IDS) != set(range(216)):
    raise RuntimeError("V18 does not complete all 216 playable Kid images")

NEW_NORMAL_RESOURCE_IDS = tuple(401 + image_id for image_id in NEW_IMAGE_IDS)

PHASE1_SLOT = 3
PHASE2_SLOT = 4
PHASE3_SLOT = 9
PHASE1_POINTER = 0x453A
PHASE2_POINTER = 0x453C
PHASE3_POINTER = 0x4546
PHASE1_RESOURCE_BASE = 1000
PHASE2_RESOURCE_BASE = 2000
PHASE3_RESOURCE_BASE = 3000
RIGHT_P2_ALIAS = 0
LEFT_P0_ALIAS = 70
LEFT_P2_ALIAS = 140
USED_PHASE3_ALIASES = 210
PHASE3_FINAL_RESOURCE_ID = 3219

HEADER_BYTES = v17.HEADER_BYTES
HIGH_CODE_FILE = v17.HIGH_CODE_FILE
HIGH_CODE_SEGMENT = v17.HIGH_CODE_SEGMENT
MAPPER_STUB_OFFSET = v17.MAPPER_STUB_OFFSET
MAPPER_STUB_END = v17.MAPPER_STUB_END
FETCH_COMMON_OFFSET = v17.FETCH_COMMON_OFFSET
SELECTOR_DONE_OFFSET = v17.SELECTOR_DONE_OFFSET
LOADER_OFFSET = v17.LOADER_OFFSET
LOAD_ONE_OFFSET = v17.LOAD_ONE_OFFSET
RESERVE_HEAP_OFFSET = v17.RESERVE_HEAP_OFFSET
PHASE1_NAME_OFFSET = v17.PHASE1_NAME_OFFSET
PHASE2_NAME_OFFSET = v17.PHASE2_NAME_OFFSET
PHASE3_NAME_OFFSET = 0x015C
PHASE3_LOADER_OFFSET = 0x0167
EXTENDED_MAPPER_OFFSET = 0x017B
PHASE1_NAME_DS = v17.PHASE1_NAME_DS
PHASE2_NAME_DS = v17.PHASE2_NAME_DS
PHASE3_NAME_DS = 0x78EC
RUNTIME_HEAP_RESERVE = 0x0300


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_image_ordinal(image_id: int) -> int:
    if 52 <= image_id <= 63:
        return image_id - 52
    if 77 <= image_id <= 79:
        return image_id - 65
    if 130 <= image_id <= 132:
        return image_id - 115
    if 160 <= image_id <= 206:
        return image_id - 142
    if 211 <= image_id <= 215:
        return image_id - 146
    raise ValueError(f"Kid image ID {image_id} is not in PHASE3")


def load_art_module() -> object:
    spec = importlib.util.spec_from_file_location("v18_art", ART_TOOL)
    if spec is None or spec.loader is None:
        raise ValueError("could not load verified V13 artwork tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SELECTED_FRAME_IMAGE_RANGES = SELECTED_FRAME_IMAGE_RANGES
    module.SELECTED_IMAGE_IDS = NEW_IMAGE_IDS
    module.SLOT_STORED_ODD = PHASE3_SLOT
    module.PRIVATE_RESOURCE_BASE = PHASE3_RESOURCE_BASE
    module.STORED_ODD_ALIAS_BASE = RIGHT_P2_ALIAS
    module.MIRRORED_EVEN_ALIAS_BASE = LEFT_P0_ALIAS
    module.MIRRORED_ODD_ALIAS_BASE = LEFT_P2_ALIAS
    module.PRIVATE_VARIANTS = (
        ("right-odd", RIGHT_P2_ALIAS, "right", 2, False),
        ("left-even", LEFT_P0_ALIAS, "left", 0, True),
        ("left-odd", LEFT_P2_ALIAS, "left", 2, True),
    )
    module.selected_image_ordinal = selected_image_ordinal
    return module


def generate_artwork(art: object) -> tuple[Path, dict[str, object], dict[str, object]]:
    if sha256_file(SOURCE_KID) != SOURCE_KID_SHA256:
        raise ValueError("unexpected original VGA KID.DAT")
    if sha256_file(BASELINE_KID) != BASELINE_KID_SHA256:
        raise ValueError("unexpected Exhaustive phase-0 baseline KID.DAT")
    if ART_WORK.exists():
        shutil.rmtree(ART_WORK)
    ART_WORK.mkdir(parents=True)
    generated = ART_WORK / "V18-PHASE3-COMBINED-KID.DAT"
    metadata, variants = art.build_four_way_dat(
        SOURCE_KID,
        BASELINE_KID,
        generated,
    )
    metadata["selected_game_frames"] = {
        name: "not asserted; Kid image IDs are authoritative"
        for name, _first, _last in SELECTED_IMAGE_GROUPS
    }
    return generated, metadata, variants


def _cmp_cx(value: int) -> bytes:
    if 0 <= value <= 127:
        return bytes((0x83, 0xF9, value))
    return b"\x81\xf9" + struct.pack("<H", value)


def _sub_cx(value: int) -> bytes:
    if 0 <= value <= 127:
        return bytes((0x83, 0xE9, value))
    return b"\x81\xe9" + struct.pack("<H", value)


def build_loader() -> bytes:
    """Load the confirmed first two tables, then call the slot-9 helper."""

    b = v17.CodeBuilder(LOADER_OFFSET)
    b.emit(bytes.fromhex("50 53 51 52 56 57 1e 06"))
    b.emit(bytes.fromhex("80 3e 35 31 01"))
    b.branch8(0x75, "done")

    b.emit(bytes.fromhex("83 3e 3a 45 00"))
    b.branch8(0x75, "check_slot4")
    b.emit(bytes.fromhex("b8 03 00 bb e8 03"))
    b.emit(b"\xba" + struct.pack("<H", PHASE1_NAME_DS))
    b.call16(LOAD_ONE_OFFSET)

    b.label("check_slot4")
    b.emit(bytes.fromhex("83 3e 3c 45 00"))
    b.branch8(0x75, "check_slot9")
    b.emit(bytes.fromhex("b8 04 00 bb d0 07"))
    b.emit(b"\xba" + struct.pack("<H", PHASE2_NAME_DS))
    b.call16(LOAD_ONE_OFFSET)

    b.label("check_slot9")
    b.call16(PHASE3_LOADER_OFFSET)
    b.label("done")
    b.emit(bytes.fromhex("07 1f 5f 5e 5a 59 5b 58"))
    b.emit(bytes.fromhex("80 3e 35 31 05 cb"))
    code = b.finish()
    if len(code) > LOAD_ONE_OFFSET - LOADER_OFFSET:
        raise ValueError("three-table loader overlaps load_one")
    return code


def build_phase3_loader() -> bytes:
    """Small appended helper that loads PHASE3.DAT only when slot 9 is null."""

    b = v17.CodeBuilder(PHASE3_LOADER_OFFSET)
    b.emit(bytes.fromhex("83 3e 46 45 00"))
    b.branch8(0x75, "done")
    b.emit(bytes.fromhex("b8 09 00"))
    b.emit(bytes.fromhex("bb b8 0b"))
    b.emit(b"\xba" + struct.pack("<H", PHASE3_NAME_DS))
    b.call16(LOAD_ONE_OFFSET)
    b.label("done")
    b.emit(b"\xc3")
    code = b.finish()
    if PHASE3_LOADER_OFFSET + len(code) != EXTENDED_MAPPER_OFFSET:
        raise ValueError("slot-9 loader does not end at the mapper boundary")
    return code


def build_extended_mapper() -> bytes:
    """Route every case not handled by the original slot-3 selector prefix."""

    b = v17.CodeBuilder(EXTENDED_MAPPER_OFFSET)

    # The patched prefix sends images 52..63 here; images >=77 already arrive.
    b.emit(_cmp_cx(64))
    b.branch8(0x73, "check_77")             # JAE
    b.emit(_sub_cx(52))
    b.jump16("phase3_alias")

    b.label("check_77")
    b.emit(_cmp_cx(77))
    b.branch8(0x73, "check_80")
    b.jump16(SELECTOR_DONE_OFFSET)          # defensive 64..76 fallback

    b.label("check_80")
    b.emit(_cmp_cx(80))
    b.branch8(0x73, "check_112")
    b.emit(_sub_cx(65))                    # 77..79 -> ordinals 12..14
    b.jump16("phase3_alias")

    b.label("check_112")
    b.emit(_cmp_cx(112))
    b.branch8(0x73, "check_120")
    b.emit(_sub_cx(80))
    b.jump16("phase2_alias")

    b.label("check_120")
    b.emit(_cmp_cx(120))
    b.branch8(0x73, "check_130")
    b.emit(_sub_cx(112))
    b.jump16("phase1_fall_alias")

    b.label("check_130")
    b.emit(_cmp_cx(130))
    b.branch8(0x73, "check_133")
    b.emit(_sub_cx(88))                    # 120..129 -> ordinals 32..41
    b.jump16("phase2_alias")

    b.label("check_133")
    b.emit(_cmp_cx(133))
    b.branch8(0x73, "check_160")
    b.emit(_sub_cx(115))                   # 130..132 -> ordinals 15..17
    b.jump16("phase3_alias")

    b.label("check_160")
    b.emit(_cmp_cx(160))
    b.branch8(0x73, "check_207")
    b.emit(_sub_cx(91))                    # 133..159 -> ordinals 42..68
    b.jump16("phase2_alias")

    b.label("check_207")
    b.emit(_cmp_cx(207))
    b.branch8(0x73, "check_211")
    b.emit(_sub_cx(142))                   # 160..206 -> ordinals 18..64
    b.jump16("phase3_alias")

    b.label("check_211")
    b.emit(_cmp_cx(211))
    b.branch8(0x73, "check_216")
    b.emit(_sub_cx(138))                   # 207..210 -> ordinals 69..72
    b.jump16("phase2_alias")

    b.label("check_216")
    b.emit(_cmp_cx(216))
    b.branch8(0x73, "fallback")
    b.emit(_sub_cx(146))                   # 211..215 -> ordinals 65..69
    b.jump16("phase3_alias")

    b.label("phase1_fall_alias")
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase1_right")
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase1_left_even")
    b.emit(bytes.fromhex("ba d3 00"))      # left/P2 base 211
    b.jump16("phase1_add")
    b.label("phase1_right")
    b.emit(bytes.fromhex("ba c3 00"))      # right/P2 base 195
    b.jump16("phase1_add")
    b.label("phase1_left_even")
    b.emit(bytes.fromhex("ba cb 00"))      # left/P0 base 203
    b.label("phase1_add")
    b.emit(bytes.fromhex("03 ca 8b 36 3a 45"))
    b.jump16(FETCH_COMMON_OFFSET)

    b.label("phase2_alias")
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase2_add")
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase2_left_even")
    b.emit(bytes.fromhex("ba 92 00"))      # left/P2 base 146
    b.jump16("phase2_add")
    b.label("phase2_left_even")
    b.emit(bytes.fromhex("ba 49 00"))      # left/P0 base 73
    b.label("phase2_add")
    b.emit(bytes.fromhex("03 ca 8b 36 3c 45"))
    b.jump16(FETCH_COMMON_OFFSET)

    b.label("phase3_alias")
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase3_add")
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase3_left_even")
    b.emit(bytes.fromhex("ba 8c 00"))      # left/P2 base 140
    b.jump16("phase3_add")
    b.label("phase3_left_even")
    b.emit(bytes.fromhex("ba 46 00"))      # left/P0 base 70
    b.label("phase3_add")
    b.emit(bytes.fromhex("03 ca 8b 36 46 45"))
    b.jump16(FETCH_COMMON_OFFSET)

    b.label("fallback")
    b.jump16(SELECTOR_DONE_OFFSET)
    code = b.finish()
    if EXTENDED_MAPPER_OFFSET + len(code) > RUNTIME_HEAP_RESERVE:
        raise ValueError("V18 mapper exceeds protected high-code region")
    return code


def phase_route(image_id: int, variant: str) -> tuple[int, int] | None:
    """Pure model of the complete V18 selector contract."""

    phase1_bases = {"right-p2": 0, "left-p0": 65, "left-p2": 130}
    fall_bases = {"right-p2": 195, "left-p0": 203, "left-p2": 211}
    phase2_bases = {"right-p2": 0, "left-p0": 73, "left-p2": 146}
    phase3_bases = {
        "right-p2": RIGHT_P2_ALIAS,
        "left-p0": LEFT_P0_ALIAS,
        "left-p2": LEFT_P2_ALIAS,
    }
    if variant not in phase1_bases:
        raise ValueError(f"unknown variant {variant}")
    if 0 <= image_id <= 51:
        return PHASE1_SLOT, phase1_bases[variant] + image_id
    if 64 <= image_id <= 76:
        return PHASE1_SLOT, phase1_bases[variant] + image_id - 12
    if 112 <= image_id <= 119:
        return PHASE1_SLOT, fall_bases[variant] + image_id - 112
    if image_id in v17.NEW_IMAGE_IDS:
        return PHASE2_SLOT, {
            "right-p2": 0,
            "left-p0": 73,
            "left-p2": 146,
        }[variant] + v17.selected_image_ordinal(image_id)
    if image_id in NEW_IMAGE_IDS:
        return PHASE3_SLOT, phase3_bases[variant] + selected_image_ordinal(image_id)
    return None


def emulate_mapper(high_code: bytes, image_id: int, variant: str) -> tuple[int, int] | None:
    """Execute the emitted mapper's 8086 subset and report its slot/alias."""

    dx_by_variant = {"right-p2": 0, "left-p0": 65, "left-p2": 130}
    cx = image_id & 0xFFFF
    dx = dx_by_variant[variant]
    si_address: int | None = None
    compare: tuple[int, int] | None = None
    ip = EXTENDED_MAPPER_OFFSET
    for _step in range(300):
        if ip == FETCH_COMMON_OFFSET:
            slot_by_pointer = {
                PHASE1_POINTER: PHASE1_SLOT,
                PHASE2_POINTER: PHASE2_SLOT,
                PHASE3_POINTER: PHASE3_SLOT,
            }
            if si_address not in slot_by_pointer:
                raise ValueError(f"mapper used unexpected slot pointer {si_address}")
            return slot_by_pointer[si_address], cx
        if ip == SELECTOR_DONE_OFFSET:
            return None
        opcode = high_code[ip]
        if high_code[ip:ip + 2] == bytes.fromhex("83 f9"):
            compare = (cx, high_code[ip + 2])
            ip += 3
        elif high_code[ip:ip + 2] == bytes.fromhex("81 f9"):
            compare = (cx, struct.unpack_from("<H", high_code, ip + 2)[0])
            ip += 4
        elif high_code[ip:ip + 2] == bytes.fromhex("83 e9"):
            cx = (cx - high_code[ip + 2]) & 0xFFFF
            ip += 3
        elif high_code[ip:ip + 2] == bytes.fromhex("81 e9"):
            cx = (cx - struct.unpack_from("<H", high_code, ip + 2)[0]) & 0xFFFF
            ip += 4
        elif high_code[ip:ip + 2] == bytes.fromhex("83 fa"):
            compare = (dx, high_code[ip + 2])
            ip += 3
        elif opcode == 0xBA:
            dx = struct.unpack_from("<H", high_code, ip + 1)[0]
            ip += 3
        elif high_code[ip:ip + 2] == bytes.fromhex("03 ca"):
            cx = (cx + dx) & 0xFFFF
            ip += 2
        elif high_code[ip:ip + 2] == bytes.fromhex("8b 36"):
            si_address = struct.unpack_from("<H", high_code, ip + 2)[0]
            ip += 4
        elif opcode in (0x72, 0x73, 0x74, 0x75):
            if compare is None:
                raise ValueError("conditional branch without compare")
            left, right = compare
            take = {
                0x72: left < right,
                0x73: left >= right,
                0x74: left == right,
                0x75: left != right,
            }[opcode]
            displacement = struct.unpack_from("<b", high_code, ip + 1)[0]
            ip = ip + 2 + displacement if take else ip + 2
        elif opcode == 0xEB:
            displacement = struct.unpack_from("<b", high_code, ip + 1)[0]
            ip += 2 + displacement
        elif opcode == 0xE9:
            displacement = struct.unpack_from("<h", high_code, ip + 1)[0]
            ip += 3 + displacement
        else:
            raise ValueError(f"unsupported mapper opcode {opcode:02X} at {ip:04X}")
    raise ValueError("mapper emulator exceeded instruction limit")


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = V17 / "P4KX17.EXE"
    original = source.read_bytes()
    if sha256_bytes(original) != V17_EXE_SHA256:
        raise ValueError("unexpected V17 executable")
    data = bytearray(original)

    # Images 52..63 previously branched directly to selector_done.  Send that
    # one uncovered prefix range through the mapper stub at 007B instead.
    intercept_file = HIGH_CODE_FILE + 0x004E
    expected_intercept = bytes.fromhex("83 f9 40 72 71")
    if data[intercept_file:intercept_file + 5] != expected_intercept:
        raise ValueError("V17 stair fallback branch changed")
    data[intercept_file:intercept_file + 5] = bytes.fromhex("83 f9 40 72 28")

    stub_file = HIGH_CODE_FILE + MAPPER_STUB_OFFSET
    stub_end_file = HIGH_CODE_FILE + MAPPER_STUB_END
    displacement = EXTENDED_MAPPER_OFFSET - (MAPPER_STUB_OFFSET + 3)
    stub = b"\xe9" + struct.pack("<h", displacement)
    data[stub_file:stub_end_file] = stub + b"\x90" * (
        stub_end_file - stub_file - len(stub)
    )

    loader = build_loader()
    loader_file = HIGH_CODE_FILE + LOADER_OFFSET
    load_one_file = HIGH_CODE_FILE + LOAD_ONE_OFFSET
    data[loader_file:load_one_file] = loader + b"\x90" * (
        load_one_file - loader_file - len(loader)
    )
    expected_load_one = (
        bytes.fromhex("50 53 52 b8 80 00 50 b8 be 18 50 90 90 90")
        + bytes.fromhex("9a 2d 15 00 00 c3")
    )
    if data[load_one_file:load_one_file + len(expected_load_one)] != expected_load_one:
        raise ValueError("V17 load_one routine changed")

    reserve_file = HIGH_CODE_FILE + RESERVE_HEAP_OFFSET
    expected_reserve = (
        bytes.fromhex("8b c4 05")
        + struct.pack("<H", v17.RUNTIME_HEAP_RESERVE + 4)
        + bytes.fromhex("36 a3 fe 2d 36 a3 fa 2d cb")
    )
    if data[reserve_file:reserve_file + len(expected_reserve)] != expected_reserve:
        raise ValueError("unexpected V17 reserve_heap routine")
    reserve = (
        bytes.fromhex("8b c4 05")
        + struct.pack("<H", RUNTIME_HEAP_RESERVE + 4)
        + bytes.fromhex("36 a3 fe 2d 36 a3 fa 2d cb")
    )
    data[reserve_file:reserve_file + len(reserve)] = reserve

    phase1_file = HIGH_CODE_FILE + PHASE1_NAME_OFFSET
    phase2_file = HIGH_CODE_FILE + PHASE2_NAME_OFFSET
    if data[phase1_file:phase1_file + 10] != b"phase.dat\x00":
        raise ValueError("V17 phase.dat string moved")
    if data[phase2_file:phase2_file + 11] != b"phase2.dat\x00":
        raise ValueError("V17 phase2.dat string moved")
    data = data[:HIGH_CODE_FILE + PHASE3_NAME_OFFSET]
    data.extend(b"phase3.dat\x00")
    if len(data) != HIGH_CODE_FILE + PHASE3_LOADER_OFFSET:
        raise ValueError("PHASE3 filename did not end at helper boundary")
    phase3_loader = build_phase3_loader()
    data.extend(phase3_loader)
    mapper = build_extended_mapper()
    data.extend(mapper)

    data = bytearray(
        v17.replace_exact(bytes(data), b"KID TABLE V17P", b"KID TABLE V18F")
    )

    header_paragraphs = struct.unpack_from("<H", data, 0x08)[0]
    if header_paragraphs != 0xA0:
        raise ValueError("unexpected MZ header size")
    module_bytes = len(data) - HEADER_BYTES
    module_paragraphs = (module_bytes + 15) // 16
    protected_heap_paragraph = (
        HIGH_CODE_SEGMENT * 16 + RUNTIME_HEAP_RESERVE + 15
    ) // 16
    minimum_allocation = max(0, protected_heap_paragraph - module_paragraphs)
    struct.pack_into("<H", data, 0x0A, minimum_allocation)
    pages = (len(data) + 511) // 512
    final_page_bytes = len(data) & 0x1FF
    struct.pack_into("<HH", data, 0x02, final_page_bytes, pages)

    if data[0xA00 + 0xB594:0xA00 + 0xB598] != bytes.fromhex("e8 7c 3b 90"):
        raise ValueError("draw selector near hook changed")
    if data[0xA00 + 0xF113:0xA00 + 0xF118] != bytes.fromhex("9a 00 00 1c 23"):
        raise ValueError("draw selector FAR trampoline changed")
    if data[0xA00 + 0x0F60:0xA00 + 0x0F65] != bytes.fromhex("9a d0 00 1c 23"):
        raise ValueError("three-table loader hook changed")
    if data[HIGH_CODE_FILE + 0x21:HIGH_CODE_FILE + 0x23] != b"\x00\x00":
        raise ValueError("selector FAR relocation site moved")
    if data[HIGH_CODE_FILE + 0x136:HIGH_CODE_FILE + 0x138] != b"\x00\x00":
        raise ValueError("load_chtab FAR relocation site moved")
    relocation_count = struct.unpack_from("<H", data, 0x06)[0]
    relocation_offset = struct.unpack_from("<H", data, 0x18)[0]
    relocations = [
        struct.unpack_from("<HH", data, relocation_offset + index * 4)
        for index in range(relocation_count)
    ]
    if relocations[-2:] != [(0x21, HIGH_CODE_SEGMENT), (0x136, HIGH_CODE_SEGMENT)]:
        raise ValueError("high-code relocation records changed")
    if len(data) > HIGH_CODE_FILE + RUNTIME_HEAP_RESERVE:
        raise ValueError("V18 high code extends into the protected near heap")

    high_code = bytes(data[HIGH_CODE_FILE:HIGH_CODE_FILE + RUNTIME_HEAP_RESERVE])
    variants = ("right-p2", "left-p0", "left-p2")
    for image_id in range(216):
        for variant in variants:
            route = phase_route(image_id, variant)
            if route is None:
                raise ValueError(f"uncovered V18 selector case {image_id}/{variant}")
            slot, alias = route
            if slot not in (PHASE1_SLOT, PHASE2_SLOT, PHASE3_SLOT):
                raise ValueError("selector model emitted invalid slot")
            if not 0 <= alias <= 218:
                raise ValueError("selector model emitted invalid alias")
    intercepted_ids = tuple(range(52, 64)) + tuple(range(77, 216))
    for image_id in intercepted_ids:
        for variant in variants:
            actual = emulate_mapper(high_code, image_id, variant)
            expected = phase_route(image_id, variant)
            if actual != expected:
                raise ValueError(
                    f"machine mapper mismatch {image_id}/{variant}: "
                    f"{actual} != {expected}"
                )
    expected_phase3 = {
        variant: [phase_route(image_id, variant)[1] for image_id in NEW_IMAGE_IDS]
        for variant in variants
    }
    if expected_phase3 != {
        "right-p2": list(range(0, 70)),
        "left-p0": list(range(70, 140)),
        "left-p2": list(range(140, 210)),
    }:
        raise ValueError("PHASE3 aliases do not fill exactly 0..209")

    total_minimum_paragraphs = module_paragraphs + minimum_allocation
    executable = bytes(data)
    return executable, {
        "file": OUTPUT_EXE,
        "bytes": len(executable),
        "sha256": sha256_bytes(executable),
        "visible_ctrl_v_marker": "KID TABLE V18F    V1.3",
        "baseline": "user-confirmed V17P",
        "phase1_table": "live native chtab slot 3 at DS:453A",
        "phase2_table": "live native chtab slot 4 at DS:453C",
        "phase3_table": "live native chtab slot 9 at DS:4546",
        "phase3_filename_ds": f"DS:{PHASE3_NAME_DS:04X}",
        "extended_mapper_offset": (
            f"{HIGH_CODE_SEGMENT:04X}:{EXTENDED_MAPPER_OFFSET:04X}"
        ),
        "extended_mapper_bytes": len(mapper),
        "phase3_loader_bytes": len(phase3_loader),
        "runtime_heap_reservation_bytes": RUNTIME_HEAP_RESERVE,
        "minimum_allocation_paragraphs": minimum_allocation,
        "dos_minimum_total_paragraphs": total_minimum_paragraphs,
        "relocation_count": relocation_count,
        "all_216_images_covered": True,
        "machine_mapper_cases_verified": len(intercepted_ids) * len(variants),
        "new_image_count": len(NEW_IMAGE_IDS),
        "new_alias_ranges": {
            "right-p2": [0, 69],
            "left-p0": [70, 139],
            "left-p2": [140, 209],
            "padding": [210, 218],
        },
        "native_slots_detached": False,
        "runtime_transforms": False,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = V17 / "CGA4K17.COM"
    data = source.read_bytes()
    if sha256_bytes(data) != V17_COM_SHA256:
        raise ValueError("unexpected V17 launcher")
    data = v17.replace_exact(data, b"P4KX17.EXE", b"P4KX18.EXE", expected=3)
    data = v17.replace_exact(data, b"V17P", b"V18F")
    if b"KID PHASE TABLE V18F ACTIVE" not in data:
        raise ValueError("V18 launcher banner patch failed")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "child": OUTPUT_EXE,
        "banner": "KID PHASE TABLE V18F ACTIVE",
    }


def _native_table_memory(archive: object, resource_base: int) -> tuple[int, int, int]:
    decoded = 0
    for alias in range(219):
        analysis = archive.analysis_by_id(resource_base + 1 + alias)
        if analysis is None or analysis.image is None:
            raise ValueError(f"missing native table image {resource_base + 1 + alias}")
        image = analysis.image
        decoded += ((image.width + 1) // 2) * image.height + 6
    pointers = 6 + 219 * 4
    return decoded, pointers, decoded + pointers


def build_final_dats(
    art: object,
    generated_path: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]:
    v17_kid_path = V17 / "KID.DAT"
    v17_phase1_path = V17 / "PHASE.DAT"
    v17_phase2_path = V17 / "PHASE2.DAT"
    expected = {
        v17_kid_path: V17_KID_SHA256,
        v17_phase1_path: V17_PHASE_SHA256,
        v17_phase2_path: V17_PHASE2_SHA256,
    }
    for path, checksum in expected.items():
        if sha256_file(path) != checksum:
            raise ValueError(f"unexpected V17 input: {path.name}")

    old_kid = art.DatArchive.open(v17_kid_path)
    old_phase1 = art.DatArchive.open(v17_phase1_path)
    old_phase2 = art.DatArchive.open(v17_phase2_path)
    generated = art.DatArchive.open(generated_path)
    if not all(
        resource.checksum_ok
        for archive in (old_kid, old_phase1, old_phase2, generated)
        for resource in archive.resources
    ):
        raise ValueError("input DAT checksum failure")

    old_kid_map = {resource.resource_id: resource.data for resource in old_kid.resources}
    generated_map = {
        resource.resource_id: resource.data for resource in generated.resources
    }
    if set(old_kid_map) != set(range(400, 620)):
        raise ValueError("V17 KID.DAT resource set changed")
    expected_generated_ids = set(range(400, 620)) | set(range(3000, 3211))
    if set(generated_map) != expected_generated_ids:
        raise ValueError("generated V18 artwork resource set is incomplete")

    final_kid_map = dict(old_kid_map)
    for resource_id in NEW_NORMAL_RESOURCE_IDS:
        final_kid_map[resource_id] = generated_map[resource_id]
    final_kid = art._build_dat(sorted(final_kid_map.items()))
    (OUT / "KID.DAT").write_bytes(final_kid)

    # Preserve both user-confirmed tables byte-for-byte.
    shutil.copy2(v17_phase1_path, OUT / "PHASE.DAT")
    shutil.copy2(v17_phase2_path, OUT / "PHASE2.DAT")

    phase3_items: list[tuple[int, bytes]] = [
        (PHASE3_RESOURCE_BASE, generated_map[PHASE3_RESOURCE_BASE])
    ]
    phase3_items.extend(
        (resource_id, generated_map[resource_id])
        for resource_id in range(3001, 3211)
    )
    # chtab headers always declare 219 images.  The final nine aliases are
    # unreachable by the selector and duplicate the first nine valid images.
    for alias in range(210, 219):
        source_alias = alias - 210
        phase3_items.append((3001 + alias, generated_map[3001 + source_alias]))
    final_phase3 = art._build_dat(phase3_items)
    (OUT / "PHASE3.DAT").write_bytes(final_phase3)

    kid_check = art.DatArchive.open(OUT / "KID.DAT")
    phase1_check = art.DatArchive.open(OUT / "PHASE.DAT")
    phase2_check = art.DatArchive.open(OUT / "PHASE2.DAT")
    phase3_check = art.DatArchive.open(OUT / "PHASE3.DAT")
    final_archives = (kid_check, phase1_check, phase2_check, phase3_check)
    if not all(
        resource.checksum_ok
        for archive in final_archives
        for resource in archive.resources
    ):
        raise ValueError("final DAT checksum verification failed")
    expected_orders = (
        (kid_check, list(range(400, 620)), "KID"),
        (phase1_check, list(range(1000, 1220)), "PHASE"),
        (phase2_check, list(range(2000, 2220)), "PHASE2"),
        (phase3_check, list(range(3000, 3220)), "PHASE3"),
    )
    for archive, expected_ids, name in expected_orders:
        actual_ids = [resource.resource_id for resource in archive.resources]
        if actual_ids != expected_ids:
            raise ValueError(f"{name} resource order changed")
    if phase3_check.resources[0].data[0] != 219:
        raise ValueError("PHASE3 header does not declare 219 images")
    if (OUT / "PHASE.DAT").read_bytes() != v17_phase1_path.read_bytes():
        raise ValueError("runtime-confirmed PHASE.DAT changed")
    if (OUT / "PHASE2.DAT").read_bytes() != v17_phase2_path.read_bytes():
        raise ValueError("runtime-confirmed PHASE2.DAT changed")

    selected_normal = set(NEW_NORMAL_RESOURCE_IDS)
    changed_from_v17: list[int] = []
    for resource in kid_check.resources:
        before = old_kid_map[resource.resource_id]
        if resource.data != before:
            changed_from_v17.append(resource.resource_id)
        if resource.resource_id not in selected_normal and resource.data != before:
            raise ValueError(f"unrelated KID resource changed: {resource.resource_id}")
        if (
            resource.resource_id in selected_normal
            and resource.data != generated_map[resource.resource_id]
        ):
            raise ValueError(f"new KID resource mismatch: {resource.resource_id}")
    if changed_from_v17 != list(NEW_NORMAL_RESOURCE_IDS):
        raise ValueError("V18 did not change exactly the 70 selected KID resources")
    for resource_id in range(3000, 3211):
        actual = phase3_check.analysis_by_id(resource_id).resource.data
        if actual != generated_map[resource_id]:
            raise ValueError(f"PHASE3 resource mismatch: {resource_id}")
    for alias in range(210, 219):
        actual = phase3_check.analysis_by_id(3001 + alias).resource.data
        expected_padding = generated_map[3001 + alias - 210]
        if actual != expected_padding:
            raise ValueError(f"PHASE3 padding mismatch: alias {alias}")

    source = art.DatArchive.open(SOURCE_KID)
    invalid_headers: list[int] = []
    mask_failures: list[int] = []
    for alias in range(219):
        resource_id = 3001 + alias
        analysis = phase3_check.analysis_by_id(resource_id)
        if analysis is None or analysis.image is None:
            invalid_headers.append(resource_id)
            continue
        image = analysis.image
        if not (0 < image.width <= 256 and 0 < image.height <= 256 and image.bits == 4):
            invalid_headers.append(resource_id)
    for image_id in NEW_IMAGE_IDS:
        source_analysis = source.analysis_by_id(401 + image_id)
        if source_analysis is None or source_analysis.image is None:
            raise ValueError(f"source image missing: {image_id}")
        source_mask = tuple(value == 0 for value in source_analysis.image.pixels)
        ordinal = selected_image_ordinal(image_id)
        cases = (
            (kid_check, 401 + image_id),
            (phase3_check, 3001 + RIGHT_P2_ALIAS + ordinal),
            (phase3_check, 3001 + LEFT_P0_ALIAS + ordinal),
            (phase3_check, 3001 + LEFT_P2_ALIAS + ordinal),
        )
        for archive, resource_id in cases:
            analysis = archive.analysis_by_id(resource_id)
            if analysis is None or analysis.image is None:
                mask_failures.append(resource_id)
                continue
            candidate_mask = tuple(value == 0 for value in analysis.image.pixels)
            if candidate_mask != source_mask:
                mask_failures.append(resource_id)
    if invalid_headers:
        raise ValueError(f"invalid PHASE3 image headers: {invalid_headers}")
    if mask_failures:
        raise ValueError(f"V18 transparency-mask failures: {mask_failures}")

    phase1_memory = _native_table_memory(phase1_check, PHASE1_RESOURCE_BASE)
    phase2_memory = _native_table_memory(phase2_check, PHASE2_RESOURCE_BASE)
    phase3_memory = _native_table_memory(phase3_check, PHASE3_RESOURCE_BASE)
    kid_meta = {
        "file": "KID.DAT",
        "bytes": len(final_kid),
        "sha256": sha256_bytes(final_kid),
        "resource_count": len(kid_check.resources),
        "new_right_p0_resource_count": len(NEW_NORMAL_RESOURCE_IDS),
        "new_right_p0_resources": list(NEW_NORMAL_RESOURCE_IDS),
        "unrelated_resources_byte_identical_to_v17": True,
        "all_216_playable_images_phase_aware": True,
        "all_checksums_valid": True,
    }
    phase1_meta = {
        "file": "PHASE.DAT",
        "bytes": (OUT / "PHASE.DAT").stat().st_size,
        "sha256": sha256_file(OUT / "PHASE.DAT"),
        "resource_count": len(phase1_check.resources),
        "resource_id_range": "1000..1219",
        "byte_identical_to_user_confirmed_v17": True,
        "declared_image_count": 219,
        "image_slots_used": 219,
        "native_memory_upper_estimate_bytes": phase1_memory[2],
    }
    phase2_meta = {
        "file": "PHASE2.DAT",
        "bytes": (OUT / "PHASE2.DAT").stat().st_size,
        "sha256": sha256_file(OUT / "PHASE2.DAT"),
        "resource_count": len(phase2_check.resources),
        "resource_id_range": "2000..2219",
        "byte_identical_to_user_confirmed_v17": True,
        "declared_image_count": 219,
        "image_slots_used": 219,
        "native_memory_upper_estimate_bytes": phase2_memory[2],
    }
    phase3_meta = {
        "file": "PHASE3.DAT",
        "bytes": len(final_phase3),
        "sha256": sha256_bytes(final_phase3),
        "resource_count": len(phase3_check.resources),
        "resource_id_range": "3000..3219",
        "declared_image_count": 219,
        "image_slots_used": 219,
        "routed_aliases": 210,
        "padding_aliases": 9,
        "padding_alias_range": [210, 218],
        "source_image_count": len(NEW_IMAGE_IDS),
        "all_checksums_valid": True,
        "all_image_headers_valid": True,
        "transparency_cases_verified": len(NEW_IMAGE_IDS) * 4,
        "decoded_image_upper_estimate_bytes": phase3_memory[0],
        "native_pointer_table_bytes": phase3_memory[1],
        "native_memory_upper_estimate_bytes": phase3_memory[2],
    }
    return kid_meta, phase1_meta, phase2_meta, phase3_meta


def render_visuals(art: object, generated_path: Path) -> list[str]:
    sys.modules["make_four_way_kid"] = art
    spec = importlib.util.spec_from_file_location("v18_render", RENDER_TOOL)
    if spec is None or spec.loader is None:
        raise ValueError("could not load visual verification renderer")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    source = art.DatArchive.open(SOURCE_KID)
    candidate = art.DatArchive.open(generated_path)
    visual_dir = OUT / "visual-verification"
    visual_dir.mkdir(parents=True, exist_ok=True)
    groups = (
        ("EXIT-STAIRS", tuple(range(52, 64)), "Run up the level-exit stairs"),
        ("HAZARD-DEATH", tuple(range(77, 80)), "Hazard and death reactions"),
        ("MOUSE", tuple(range(130, 133)), "Mouse animation"),
        (
            "SWORD-PICKUP-SHEATHE",
            tuple(range(160, 174)),
            "Find, pick up, and sheathe the sword",
        ),
        ("SWORD-COMBAT", tuple(range(174, 192)), "Sword-combat body frames"),
        ("POTION-DRINK", tuple(range(192, 207)), "Drink potion"),
        ("COLLAPSE-DEATH", tuple(range(211, 216)), "Collapse and death"),
    )
    outputs: list[str] = []
    for slug, image_ids, description in groups:
        path = visual_dir / f"VISUAL-PHASE3-{slug}.png"
        renderer.contact_sheet(
            source,
            candidate,
            image_ids,
            f"Prince Exhaustive Phase Verification - PHASE3 {slug}",
            f"{description}. Four independent final-display waveforms; no dither.",
            path,
        )
        outputs.append(path.name)
    for direction in ("right", "left"):
        path = visual_dir / f"VISUAL-PHASE3-{direction.upper()}-PHASE-TOGGLE.gif"
        renderer.phase_toggle_gif(candidate, NEW_IMAGE_IDS, direction, path)
        outputs.append(path.name)
    for temporary in visual_dir.glob("VISUAL-PHASE3-*.tmp"):
        temporary.unlink()
    return outputs


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging_path = zip_path.with_name(zip_path.name + ".building")
    if staging_path.exists():
        staging_path.unlink()
    fixed_time = (2026, 8, 25, 3, 0, 0)
    try:
        with zipfile.ZipFile(
            staging_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(source_dir.rglob("*")):
                if not path.is_file():
                    continue
                relative = Path(PACKAGE_NAME) / path.relative_to(source_dir)
                info = zipfile.ZipInfo(relative.as_posix(), fixed_time)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(
                    info,
                    path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
        with staging_path.open("rb") as archive_file:
            os.fsync(archive_file.fileno())
        staging_path.replace(zip_path)
        directory_fd = os.open(
            zip_path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if staging_path.exists():
            staging_path.unlink()
        raise


README_TEMPLATE = """PRINCE OF PERSIA 1.3 - COMPLETE KID PHASE COVERAGE V18F
================================================================

PURPOSE
-------

V18F preserves the user-confirmed V17P PHASE.DAT and PHASE2.DAT tables and
adds PHASE3.DAT in native Prince chtab slot 9. The final 70 playable Kid images
now receive four independently optimized final-display cases: right/P0,
right/P2, left/P0, and left/P2.

PHASE3 covers:

  KID images  52..63    run up the level-exit stairs
  KID images  77..79    hazard and death reactions
  KID images 130..132   mouse animation
  KID images 160..173   find, pick up, and sheathe the sword
  KID images 174..191   sword-combat body frames
  KID images 192..206   drink potion
  KID images 211..215   collapse and death

Together, PHASE.DAT, PHASE2.DAT, and PHASE3.DAT cover every playable KID image
0..215. Conversion uses the New-CGA signal model, exhaustive exact row search,
and no dithering.

INSTALLATION
------------

1. Start with a clean intended New-CGA Prince 1.3 directory or working V17P.
2. Copy these six files into that directory:

       CGA4K18.COM
       P4KX18.EXE
       KID.DAT
       PHASE.DAT
       PHASE2.DAT
       PHASE3.DAT

3. Keep all six files together. Do not mix files from V16, V17, and V18.
4. Run CGA4K18.COM. Do not run P4KX18.EXE directly.
5. Press Ctrl-V and confirm:

       KID TABLE V18F    V1.3

   The launcher must print:

       KID PHASE TABLE V18F ACTIVE

EXPECTED TABLES
---------------

PHASE.DAT:  {phase1_bytes:,} bytes
SHA-256:    {phase1_sha256}

PHASE2.DAT: {phase2_bytes:,} bytes
SHA-256:    {phase2_sha256}

PHASE3.DAT: {phase3_bytes:,} bytes
SHA-256:    {phase3_sha256}

TEST ROUTE
----------

First regression-test the user-confirmed V17 motions in both directions:
stand, run, both turns, horizontal and vertical jumps, grab, hang, release,
climb, fall, landing, held crouch, stand up, careful step, and draw sword.

Then test the new V18 families at adjacent horizontal positions and in both
directions wherever the game permits:

  * run up the stairs at a level exit and continue into the next level;
  * find and pick up the sword, draw it, and sheathe it;
  * advance, retreat, guard, strike, and receive attacks during sword combat;
  * trigger loose-floor, spike, chopper, fall, and death reactions;
  * observe the mouse sequence;
  * drink each available potion type;
  * trigger collapse and death sequences.

Also test restart, level transition, return to title, story interludes, and
re-entering gameplay. These exercise all three native-table reload lifecycles.
Use the normal 640-KiB configuration.

The separately drawn moving sword graphic is stored in PRINCE.DAT and is not
part of the KID-table conversion. During combat, judge the Kid body separately
from that sword overlay.

ARCHITECTURE
------------

  PHASE.DAT loading     Prince load_chtab -> live native slot 3
  PHASE2.DAT loading    Prince load_chtab -> live native slot 4
  PHASE3.DAT loading    Prince load_chtab -> live native slot 9
  drawing               Prince original conversion/flip/draw path
  runtime transforms    none
  custom DOS I/O        none
  CPU                    8086/8088 compatible

TABLE CAPACITY
--------------

PHASE3 routes 210 aliases for the remaining 70 images:

  right/P2 aliases       0..69
  left/P0 aliases       70..139
  left/P2 aliases      140..209

Aliases 210..218 are valid but unreachable padding copies, required because a
native Kid chtab declares 219 images. No playable KID images remain uncovered.

MEMORY
------

PHASE3.DAT is {phase3_bytes:,} compressed bytes. Its 219 decoded images plus
native pointer table have an upper estimate of {phase3_memory_bytes:,} bytes.
The upper estimate for all three phase tables together is
{all_phase_memory_bytes:,} bytes. Prince allocates normal individual sprite
objects; the patch adds no custom bulk allocation and uses no XMS or EMS.
Actual DOS runtime testing remains required.
"""


def main() -> None:
    required = (V17, SOURCE_KID, BASELINE_KID, ART_TOOL, RENDER_TOOL)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"missing V18 build inputs: {missing}")

    if OUT.exists():
        shutil.rmtree(OUT)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(V17, OUT)

    for stale in (
        "P4KX17.EXE",
        "CGA4K17.COM",
        "KID-V17P-README.TXT",
        "KID-V17P-VERIFICATION.TXT",
        "KID-V17P-MANIFEST.JSON",
        "PACKAGE-MANIFEST.JSON",
        "SHA256SUMS.TXT",
    ):
        path = OUT / stale
        if path.exists():
            path.unlink()

    art = load_art_module()
    generated, artwork_meta, variants = generate_artwork(art)
    kid_meta, phase1_meta, phase2_meta, phase3_meta = build_final_dats(
        art, generated
    )
    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    visual_files = render_visuals(art, generated)

    all_phase_memory = sum(
        table["native_memory_upper_estimate_bytes"]
        for table in (phase1_meta, phase2_meta, phase3_meta)
    )
    readme = README_TEMPLATE.format(
        phase1_bytes=phase1_meta["bytes"],
        phase1_sha256=phase1_meta["sha256"],
        phase2_bytes=phase2_meta["bytes"],
        phase2_sha256=phase2_meta["sha256"],
        phase3_bytes=phase3_meta["bytes"],
        phase3_sha256=phase3_meta["sha256"],
        phase3_memory_bytes=phase3_meta["native_memory_upper_estimate_bytes"],
        all_phase_memory_bytes=all_phase_memory,
    )
    (OUT / "README.TXT").write_text(readme, encoding="ascii", newline="\r\n")
    (OUT / "KID-V18F-README.TXT").write_text(
        readme,
        encoding="ascii",
        newline="\r\n",
    )

    manifest = {
        "package": PACKAGE_NAME,
        "status": (
            "V18F static/resource/machine-mapper/visual verification passed; "
            "DOS runtime verification pending"
        ),
        "baseline": {
            "version": "V17P with live native slots 3 and 4",
            "runtime_status": (
                "all V17 covered motions confirmed working by user in both "
                "directions and phases"
            ),
        },
        "scope": {
            "actions": [name for name, _first, _last in SELECTED_IMAGE_GROUPS],
            "image_groups": [
                {"name": name, "kid_images": [first, last]}
                for name, first, last in SELECTED_IMAGE_GROUPS
            ],
            "new_image_ids": list(NEW_IMAGE_IDS),
            "new_unique_images": len(NEW_IMAGE_IDS),
            "total_phase_aware_unique_images": 216,
            "kid_playable_image_total": 216,
            "remaining_unique_images": 0,
            "new_final_display_cases": len(NEW_IMAGE_IDS) * 4,
            "total_final_display_cases": 216 * 4,
        },
        "conversion": {
            "source": "verified original VGA KID.DAT",
            "profile": "new-cga",
            "algorithm": "Exhaustive exact 2,048-state row dynamic program",
            "dither": "none",
            "phase_variants": [0, 2],
            "direction_variants": ["right", "left"],
            "independent_final_display_optimization": True,
            "source_kid_sha256": SOURCE_KID_SHA256,
            "phase0_baseline_sha256": BASELINE_KID_SHA256,
            "artwork_generator_metadata": artwork_meta,
        },
        "runtime_architecture": {
            "sidecars": ["PHASE.DAT", "PHASE2.DAT", "PHASE3.DAT"],
            "sidecars_are_standard_prince_dat": True,
            "loader": "Prince load_chtab",
            "native_slots": {"PHASE.DAT": 3, "PHASE2.DAT": 4, "PHASE3.DAT": 9},
            "native_slots_kept_live": True,
            "selector": "direct live-slot lookup with complete range mapper",
            "runtime_transform": False,
            "custom_dos_io": False,
            "cpu": "8086/8088",
        },
        "phase3_alias_map": {
            "right_p2": [0, 69],
            "left_p0": [70, 139],
            "left_p2": [140, 209],
            "valid_unreachable_padding": [210, 218],
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
        "kid_dat": kid_meta,
        "phase_dat": phase1_meta,
        "phase2_dat": phase2_meta,
        "phase3_dat": phase3_meta,
        "all_phase_tables_native_memory_upper_estimate_bytes": all_phase_memory,
        "new_variants": variants,
        "visual_verification": visual_files,
        "next_architecture_boundary": (
            "All 216 playable KID images are covered; separately drawn "
            "PRINCE.DAT objects remain outside the Kid-table architecture"
        ),
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (OUT / "KID-V18F-MANIFEST.JSON").write_text(
        manifest_text,
        encoding="utf-8",
    )

    verification = f"""Prince of Persia 1.3 V18F Complete Kid Verification
========================================================
EXE PASS     {OUTPUT_EXE}: {executable_meta['bytes']} bytes, SHA-256 {executable_meta['sha256']}
SLOT3 PASS   PHASE.DAT is byte-identical to user-confirmed V17
SLOT4 PASS   PHASE2.DAT is byte-identical to user-confirmed V17
SLOT9 PASS   PHASE3.DAT loads through Prince load_chtab at DS:4546
MAP PASS     All 216 playable Kid images have three exact alternate routes
EMU PASS     {executable_meta['machine_mapper_cases_verified']}/{executable_meta['machine_mapper_cases_verified']} emitted mapper cases match the software model
COM PASS     {OUTPUT_COM}: child={OUTPUT_EXE}, SHA-256 {launcher_meta['sha256']}
KID PASS     Exactly 70 new right/P0 resources; SHA-256 {kid_meta['sha256']}
PHASE1 PASS  220/220 resources, SHA-256 {phase1_meta['sha256']}
PHASE2 PASS  220/220 resources, SHA-256 {phase2_meta['sha256']}
PHASE3 PASS  220/220 resources, SHA-256 {phase3_meta['sha256']}
IMAGE PASS   219/219 PHASE3 image headers decode correctly
MASK PASS    {phase3_meta['transparency_cases_verified']}/{phase3_meta['transparency_cases_verified']} new direction/phase cases preserve source transparency
PAD PASS     Aliases 210..218 are valid unreachable padding copies
VIS PASS     Seven contact sheets and two full-table phase-toggle GIFs rendered
MEM PASS     Injected code stays inside the 768-byte protected high region
CPU PASS     Selector and loader use only 8086/8088 instructions

STATIC VERIFICATION PASSED.
DOS runtime verification is still required.
"""
    (OUT / "KID-V18F-VERIFICATION.TXT").write_text(
        verification,
        encoding="ascii",
        newline="\r\n",
    )

    tools_dir = OUT / "tools"
    tools_dir.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), tools_dir / Path(__file__).name)

    package_manifest = {**manifest, "files": {}}
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name not in {
            "PACKAGE-MANIFEST.JSON",
            "SHA256SUMS.TXT",
        }:
            relative = path.relative_to(OUT).as_posix()
            package_manifest["files"][relative] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    (OUT / "PACKAGE-MANIFEST.JSON").write_text(
        json.dumps(package_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    checksum_lines = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.TXT":
            checksum_lines.append(
                f"{sha256_file(path)}  {path.relative_to(OUT).as_posix()}"
            )
    (OUT / "SHA256SUMS.TXT").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="ascii",
    )

    make_zip(OUT, ZIP_PATH)
    print(json.dumps({
        "package_dir": str(OUT),
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "exe": executable_meta,
        "launcher": launcher_meta,
        "kid_dat": kid_meta,
        "phase_dat": phase1_meta,
        "phase2_dat": phase2_meta,
        "phase3_dat": phase3_meta,
        "all_phase_memory_upper_estimate_bytes": all_phase_memory,
        "visual_verification": visual_files,
    }, indent=2))


if __name__ == "__main__":
    main()
