#!/usr/bin/env python3
"""Build Prince 1.3 New-CGA V19 with all 219 KID images phase-aware.

V19K preserves the user-confirmed V18F package, replaces PHASE3 aliases
210..218 with real variants for KID images 216..218, extends the ordinary
Kid draw mapper, and adds a dedicated phase selector for the two HP icons.
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

import build_v18 as v18


ROOT = Path(__file__).resolve().parent
V18 = (
    ROOT
    / "build"
    / "Prince-1.3-New-CGA-Phase-Aware-V18-PHASE3-Complete-Kid-"
      "Dungeon-Version-B-DAT-Set"
)
SOURCE_KID = v18.SOURCE_KID
BASELINE_KID = v18.BASELINE_KID
ART_TOOL = v18.ART_TOOL
RENDER_TOOL = v18.RENDER_TOOL

BUILD_ROOT = ROOT / "build"
PACKAGE_NAME = (
    "Prince-1.3-New-CGA-Phase-Aware-V19-PHASE3-All-219-KID-"
    "Dungeon-Version-B-DAT-Set"
)
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"
ART_WORK = BUILD_ROOT / "v19-art-work"

OUTPUT_EXE = "P4KX19.EXE"
OUTPUT_COM = "CGA4K19.COM"
VERSION_MARKER = "V19K"

V18_EXE_SHA256 = "53822379b524ad2b9e6d1c3bbcb36df16a5eebf8639cfa342cdc2810f5db1f3c"
V18_COM_SHA256 = "da990f4ec627159d564abbc9d8285f8830c087712c10d0d5ab6d94e5cd584655"
V18_KID_SHA256 = "1845977a3cb833920e88fd1b1aab4f04737d643113dcbc207442d8672cb8c9d9"
V18_PHASE_SHA256 = "ef91ee76ce79f5f7e3753fc9d48a2d0e553066ebb4d75bb3648e89f1ea615792"
V18_PHASE2_SHA256 = "eb5cc5c32da2424b9beb234df21a59153e9fc1e735e8520b8fc18ca12cbf5b19"
V18_PHASE3_SHA256 = "eef7f003e3bf244c4fd0b6c0e9a561dda08d9841484a320b7943a6e699b97694"

NEW_IMAGE_GROUPS = (
    ("kid_hit_point_icons", 216, 217),
    ("kid_hurt_splash", 218, 218),
)
SELECTED_FRAME_IMAGE_RANGES = tuple(
    (name, first, last, first, last)
    for name, first, last in NEW_IMAGE_GROUPS
)
NEW_IMAGE_IDS = (216, 217, 218)
NEW_NORMAL_RESOURCE_IDS = (617, 618, 619)

PHASE3_SLOT = v18.PHASE3_SLOT
PHASE3_POINTER = v18.PHASE3_POINTER
PHASE3_RESOURCE_BASE = v18.PHASE3_RESOURCE_BASE
RIGHT_P2_ALIAS = 210
LEFT_P0_ALIAS = 213
LEFT_P2_ALIAS = 216

HEADER_BYTES = v18.HEADER_BYTES
HIGH_CODE_FILE = v18.HIGH_CODE_FILE
HIGH_CODE_SEGMENT = v18.HIGH_CODE_SEGMENT
FETCH_COMMON_OFFSET = v18.FETCH_COMMON_OFFSET
SELECTOR_DONE_OFFSET = v18.SELECTOR_DONE_OFFSET
PHASE3_LOADER_OFFSET = v18.PHASE3_LOADER_OFFSET
EXTENDED_MAPPER_OFFSET = v18.EXTENDED_MAPPER_OFFSET
RUNTIME_HEAP_RESERVE = v18.RUNTIME_HEAP_RESERVE

# Prince 1.3 draw_kid_hp, module offsets.  Each 12-byte block originally
# loaded a far image pointer directly from native KID chtab slot 2.
HP_EMPTY_POINTER_HOOK = 0x12B3  # image 217
HP_FULL_POINTER_HOOK = 0x12E4   # image 216
HP_EMPTY_SIGNATURE = bytes.fromhex(
    "8b 1e 38 45 ff b7 6c 03 ff b7 6a 03"
)
HP_FULL_SIGNATURE = bytes.fromhex(
    "8b 1e 38 45 ff b7 68 03 ff b7 66 03"
)

# Native table layout: 6-byte header, then 219 far pointers.
KID_FIRST_HP_POINTER_OFFSET = 6 + 216 * 4       # 0366h
PHASE3_FIRST_HP_POINTER_OFFSET = 6 + 210 * 4    # 034Eh


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def selected_image_ordinal(image_id: int) -> int:
    if image_id not in NEW_IMAGE_IDS:
        raise ValueError(f"KID image {image_id} is not a V19 image")
    return image_id - 216


def load_art_module() -> object:
    spec = importlib.util.spec_from_file_location("v19_art", ART_TOOL)
    if spec is None or spec.loader is None:
        raise ValueError("could not load verified V13 artwork optimizer")
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
    if sha256_file(SOURCE_KID) != v18.SOURCE_KID_SHA256:
        raise ValueError("unexpected original VGA KID.DAT")
    if sha256_file(BASELINE_KID) != v18.BASELINE_KID_SHA256:
        raise ValueError("unexpected exhaustive phase-0 baseline KID.DAT")
    if ART_WORK.exists():
        shutil.rmtree(ART_WORK)
    ART_WORK.mkdir(parents=True)
    generated = ART_WORK / "V19-PHASE3-FINAL-KID-IMAGES.DAT"
    metadata, variants = art.build_four_way_dat(
        SOURCE_KID,
        BASELINE_KID,
        generated,
    )
    metadata["selected_game_frames"] = {
        "kid_hit_point_icons": "KID image IDs 216..217",
        "kid_hurt_splash": "KID image ID 218",
    }
    return generated, metadata, variants


def build_extended_mapper_and_hp_helper() -> tuple[bytes, dict[str, int]]:
    """Build the V18 mapper extension plus V19 aliases and HP helper."""

    b = v18.v17.CodeBuilder(EXTENDED_MAPPER_OFFSET)

    # Ranges already routed by V18.  Keep their instruction structure and
    # destinations stable; only the old image >=216 fallback is extended.
    b.emit(v18._cmp_cx(64))
    b.branch8(0x73, "check_77")
    b.emit(v18._sub_cx(52))
    b.jump16("phase3_alias")

    b.label("check_77")
    b.emit(v18._cmp_cx(77))
    b.branch8(0x73, "check_80")
    b.jump16(SELECTOR_DONE_OFFSET)

    b.label("check_80")
    b.emit(v18._cmp_cx(80))
    b.branch8(0x73, "check_112")
    b.emit(v18._sub_cx(65))
    b.jump16("phase3_alias")

    b.label("check_112")
    b.emit(v18._cmp_cx(112))
    b.branch8(0x73, "check_120")
    b.emit(v18._sub_cx(80))
    b.jump16("phase2_alias")

    b.label("check_120")
    b.emit(v18._cmp_cx(120))
    b.branch8(0x73, "check_130")
    b.emit(v18._sub_cx(112))
    b.jump16("phase1_fall_alias")

    b.label("check_130")
    b.emit(v18._cmp_cx(130))
    b.branch8(0x73, "check_133")
    b.emit(v18._sub_cx(88))
    b.jump16("phase2_alias")

    b.label("check_133")
    b.emit(v18._cmp_cx(133))
    b.branch8(0x73, "check_160")
    b.emit(v18._sub_cx(115))
    b.jump16("phase3_alias")

    b.label("check_160")
    b.emit(v18._cmp_cx(160))
    b.branch8(0x73, "check_207")
    b.emit(v18._sub_cx(91))
    b.jump16("phase2_alias")

    b.label("check_207")
    b.emit(v18._cmp_cx(207))
    b.branch8(0x73, "check_211")
    b.emit(v18._sub_cx(142))
    b.jump16("phase3_alias")

    b.label("check_211")
    b.emit(v18._cmp_cx(211))
    b.branch8(0x73, "check_216")
    b.emit(v18._sub_cx(138))
    b.jump16("phase2_alias")

    b.label("check_216")
    b.emit(v18._cmp_cx(216))
    b.branch8(0x73, "check_219")
    b.emit(v18._sub_cx(146))
    b.jump16("phase3_alias")

    b.label("check_219")
    b.emit(v18._cmp_cx(219))
    b.branch8(0x72, "map_final_images")
    b.jump16(SELECTOR_DONE_OFFSET)
    b.label("map_final_images")
    b.emit(v18._sub_cx(216))
    b.jump16("phase3_final_alias")

    b.label("phase1_fall_alias")
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase1_right")
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase1_left_even")
    b.emit(bytes.fromhex("ba d3 00"))
    b.jump16("phase1_add")
    b.label("phase1_right")
    b.emit(bytes.fromhex("ba c3 00"))
    b.jump16("phase1_add")
    b.label("phase1_left_even")
    b.emit(bytes.fromhex("ba cb 00"))
    b.label("phase1_add")
    b.emit(bytes.fromhex("03 ca 8b 36 3a 45"))
    b.jump16(FETCH_COMMON_OFFSET)

    b.label("phase2_alias")
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase2_add")
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase2_left_even")
    b.emit(bytes.fromhex("ba 92 00"))
    b.jump16("phase2_add")
    b.label("phase2_left_even")
    b.emit(bytes.fromhex("ba 49 00"))
    b.label("phase2_add")
    b.emit(bytes.fromhex("03 ca 8b 36 3c 45"))
    b.jump16(FETCH_COMMON_OFFSET)

    b.label("phase3_alias")
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase3_add")
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase3_left_even")
    b.emit(bytes.fromhex("ba 8c 00"))
    b.jump16("phase3_add")
    b.label("phase3_left_even")
    b.emit(bytes.fromhex("ba 46 00"))
    b.label("phase3_add")
    b.emit(bytes.fromhex("03 ca 8b 36 46 45"))
    b.jump16(FETCH_COMMON_OFFSET)

    # Images 216..218 occupy the former PHASE3 padding aliases.
    b.label("phase3_final_alias")
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase3_final_right")
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase3_final_left_even")
    b.emit(bytes.fromhex("ba d8 00"))       # left/P2 base 216
    b.jump16("phase3_final_add")
    b.label("phase3_final_right")
    b.emit(bytes.fromhex("ba d2 00"))       # right/P2 base 210
    b.jump16("phase3_final_add")
    b.label("phase3_final_left_even")
    b.emit(bytes.fromhex("ba d5 00"))       # left/P0 base 213
    b.label("phase3_final_add")
    b.emit(bytes.fromhex("03 ca 8b 36 46 45"))
    b.jump16(FETCH_COMMON_OFFSET)

    # AX is 0 for full HP (image 216) or 1 for empty HP (image 217).
    # Return the selected image far pointer in DX:AX.  The HP X coordinate is
    # 7*index, so index parity directly selects final composite P0 or P2.
    b.label("hp_pointer")
    b.emit(bytes.fromhex("53 51"))           # preserve BX, CX
    b.emit(bytes.fromhex("8b c8"))           # CX = image ordinal
    b.emit(bytes.fromhex("80 3e 35 31 01")) # Prince CGA mode?
    b.branch8(0x75, "hp_p0")
    b.emit(bytes.fromhex("f6 46 fe 01"))    # test byte [BP-2],1
    b.branch8(0x74, "hp_p0")
    b.emit(bytes.fromhex("83 3e 46 45 00")) # slot 9 null?
    b.branch8(0x75, "hp_p2")
    b.emit(bytes.fromhex("51"))              # protect ordinal
    b.call16(PHASE3_LOADER_OFFSET)
    b.emit(bytes.fromhex("59"))
    b.label("hp_p2")
    b.emit(bytes.fromhex("8b 1e 46 45"))    # BX = slot 9
    b.emit(bytes.fromhex("0b db"))           # failed load -> P0
    b.branch8(0x74, "hp_p0")
    b.emit(bytes.fromhex("8b c1 d1 e0 d1 e0"))
    b.emit(b"\x05" + struct.pack("<H", PHASE3_FIRST_HP_POINTER_OFFSET))
    b.branch8(0xEB, "hp_fetch")
    b.label("hp_p0")
    b.emit(bytes.fromhex("8b 1e 38 45"))    # BX = native KID slot 2
    b.emit(bytes.fromhex("8b c1 d1 e0 d1 e0"))
    b.emit(b"\x05" + struct.pack("<H", KID_FIRST_HP_POINTER_OFFSET))
    b.label("hp_fetch")
    b.emit(bytes.fromhex("03 d8"))           # BX += pointer offset
    b.emit(bytes.fromhex("8b 07"))           # AX = image offset
    b.emit(bytes.fromhex("8b 57 02"))        # DX = image segment
    b.emit(bytes.fromhex("59 5b cb"))        # restore, RETF

    code = b.finish()
    if EXTENDED_MAPPER_OFFSET + len(code) > RUNTIME_HEAP_RESERVE:
        raise ValueError("V19 code exceeds the protected high-code region")
    return code, dict(b.labels)


def phase_route(image_id: int, variant: str) -> tuple[int, int] | None:
    old = v18.phase_route(image_id, variant)
    if old is not None:
        return old
    bases = {
        "right-p2": RIGHT_P2_ALIAS,
        "left-p0": LEFT_P0_ALIAS,
        "left-p2": LEFT_P2_ALIAS,
    }
    if variant not in bases:
        raise ValueError(f"unknown phase variant {variant}")
    if image_id in NEW_IMAGE_IDS:
        return PHASE3_SLOT, bases[variant] + selected_image_ordinal(image_id)
    return None


def hp_pointer_model(image_id: int, hp_index: int, graphics_mode: int = 1) -> tuple[int, int]:
    if image_id not in (216, 217):
        raise ValueError("HP selector only accepts KID images 216 and 217")
    ordinal = image_id - 216
    if graphics_mode == 1 and hp_index & 1:
        return PHASE3_SLOT, RIGHT_P2_ALIAS + ordinal
    return 2, image_id


def emulate_hp_helper(
    high_code: bytes,
    helper_offset: int,
    image_id: int,
    hp_index: int,
    graphics_mode: int,
    slot9_loaded: bool,
) -> tuple[int, int, bool]:
    """Execute the HP helper's 8086 subset against synthetic native tables."""

    ordinal = image_id - 216
    ax, bx, cx, dx, bp = ordinal, 0xBEEF, 0xCAFE, 0xD00D, 0x1000
    original_bx, original_cx = bx, cx
    stack: list[int] = []
    zero = False
    ip = helper_offset
    slot2_base = 0x6000
    slot9_base = 0x7000 if slot9_loaded else 0
    memory: dict[int, int] = {}
    for item_ordinal in range(3):
        normal = KID_FIRST_HP_POINTER_OFFSET + item_ordinal * 4
        phase = PHASE3_FIRST_HP_POINTER_OFFSET + item_ordinal * 4
        memory[slot2_base + normal] = 0xA000 + item_ordinal
        memory[slot2_base + normal + 2] = 0x1111
        if slot9_base:
            memory[slot9_base + phase] = 0xB000 + item_ordinal
            memory[slot9_base + phase + 2] = 0x2222

    for _step in range(100):
        opcode = high_code[ip]
        pair = high_code[ip:ip + 2]
        if opcode == 0x53:
            stack.append(bx)
            ip += 1
        elif opcode == 0x51:
            stack.append(cx)
            ip += 1
        elif opcode == 0x59:
            cx = stack.pop()
            ip += 1
        elif opcode == 0x5B:
            bx = stack.pop()
            ip += 1
        elif pair == bytes.fromhex("8b c8"):
            cx = ax
            ip += 2
        elif high_code[ip:ip + 4] == bytes.fromhex("f6 46 fe 01"):
            zero = (hp_index & 1) == 0
            ip += 4
        elif pair == bytes.fromhex("80 3e"):
            address = struct.unpack_from("<H", high_code, ip + 2)[0]
            immediate = high_code[ip + 4]
            if address != 0x3135:
                raise ValueError("HP emulator saw unexpected byte address")
            zero = graphics_mode == immediate
            ip += 5
        elif pair == bytes.fromhex("83 3e"):
            address = struct.unpack_from("<H", high_code, ip + 2)[0]
            immediate = high_code[ip + 4]
            value = slot9_base if address == 0x4546 else None
            if value is None:
                raise ValueError("HP emulator saw unexpected word address")
            zero = value == immediate
            ip += 5
        elif pair == bytes.fromhex("8b 1e"):
            address = struct.unpack_from("<H", high_code, ip + 2)[0]
            bx = {0x4538: slot2_base, 0x4546: slot9_base}[address]
            ip += 4
        elif pair == bytes.fromhex("0b db"):
            zero = bx == 0
            ip += 2
        elif pair == bytes.fromhex("8b c1"):
            ax = cx
            ip += 2
        elif pair == bytes.fromhex("d1 e0"):
            ax = (ax << 1) & 0xFFFF
            ip += 2
        elif opcode == 0x05:
            ax = (ax + struct.unpack_from("<H", high_code, ip + 1)[0]) & 0xFFFF
            ip += 3
        elif pair == bytes.fromhex("03 d8"):
            bx = (bx + ax) & 0xFFFF
            ip += 2
        elif pair == bytes.fromhex("8b 07"):
            ax = memory[bx]
            ip += 2
        elif high_code[ip:ip + 3] == bytes.fromhex("8b 57 02"):
            dx = memory[bx + 2]
            ip += 3
        elif opcode in (0x74, 0x75):
            take = zero if opcode == 0x74 else not zero
            displacement = struct.unpack_from("<b", high_code, ip + 1)[0]
            ip = ip + 2 + displacement if take else ip + 2
        elif opcode == 0xEB:
            displacement = struct.unpack_from("<b", high_code, ip + 1)[0]
            ip += 2 + displacement
        elif opcode == 0xE8:
            displacement = struct.unpack_from("<h", high_code, ip + 1)[0]
            target = ip + 3 + displacement
            if target != PHASE3_LOADER_OFFSET:
                raise ValueError("HP helper called an unexpected target")
            slot9_base = 0x7000
            for item_ordinal in range(3):
                phase = PHASE3_FIRST_HP_POINTER_OFFSET + item_ordinal * 4
                memory[slot9_base + phase] = 0xB000 + item_ordinal
                memory[slot9_base + phase + 2] = 0x2222
            ax, bx, dx = 9, 3000, 0x78EC
            ip += 3
        elif opcode == 0xCB:
            if stack or bx != original_bx or cx != original_cx:
                raise ValueError("HP helper did not preserve its stack/register contract")
            expected = hp_pointer_model(image_id, hp_index, graphics_mode)
            actual = (
                (PHASE3_SLOT, RIGHT_P2_ALIAS + ordinal)
                if (dx, ax) == (0x2222, 0xB000 + ordinal)
                else (2, image_id)
                if (dx, ax) == (0x1111, 0xA000 + ordinal)
                else None
            )
            if actual != expected:
                raise ValueError(f"HP helper mismatch: {actual} != {expected}")
            return actual[0], actual[1], slot9_base != 0
        else:
            raise ValueError(f"unsupported HP opcode {opcode:02X} at {ip:04X}")
    raise ValueError("HP helper emulator exceeded instruction limit")


def _add_relocations(data: bytearray, additions: tuple[tuple[int, int], ...]) -> None:
    count = struct.unpack_from("<H", data, 0x06)[0]
    table = struct.unpack_from("<H", data, 0x18)[0]
    end = table + (count + len(additions)) * 4
    if end > HEADER_BYTES:
        raise ValueError("MZ header lacks relocation space")
    for index, record in enumerate(additions, start=count):
        struct.pack_into("<HH", data, table + index * 4, *record)
    struct.pack_into("<H", data, 0x06, count + len(additions))


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = V18 / "P4KX18.EXE"
    original = source.read_bytes()
    if sha256_bytes(original) != V18_EXE_SHA256:
        raise ValueError("unexpected user-confirmed V18 executable")
    data = bytearray(original)

    empty_file = HEADER_BYTES + HP_EMPTY_POINTER_HOOK
    full_file = HEADER_BYTES + HP_FULL_POINTER_HOOK
    if data[empty_file:empty_file + 12] != HP_EMPTY_SIGNATURE:
        raise ValueError("empty-HP pointer hook signature changed")
    if data[full_file:full_file + 12] != HP_FULL_SIGNATURE:
        raise ValueError("full-HP pointer hook signature changed")

    code, labels = build_extended_mapper_and_hp_helper()
    helper_offset = labels["hp_pointer"]
    far_call = b"\x9a" + struct.pack("<HH", helper_offset, HIGH_CODE_SEGMENT)

    def hp_hook(ordinal: int) -> bytes:
        hook = (
            b"\xb8" + struct.pack("<H", ordinal)
            + far_call
            + bytes.fromhex("52 50 90 90")
        )
        if len(hook) != 12:
            raise AssertionError("HP hook must remain 12 bytes")
        return hook

    data[empty_file:empty_file + 12] = hp_hook(1)
    data[full_file:full_file + 12] = hp_hook(0)

    # Rebuild only the appended mapper/helper region; V18 loader, selector,
    # filenames, and all original code stay byte-identical.
    data = data[:HIGH_CODE_FILE + EXTENDED_MAPPER_OFFSET]
    data.extend(code)
    data = bytearray(
        v18.v17.replace_exact(bytes(data), b"KID TABLE V18F", b"KID TABLE V19K")
    )

    old_count = struct.unpack_from("<H", data, 0x06)[0]
    if old_count != 588:
        raise ValueError(f"unexpected V18 relocation count {old_count}")
    table = struct.unpack_from("<H", data, 0x18)[0]
    old_relocations = [
        struct.unpack_from("<HH", data, table + index * 4)
        for index in range(old_count)
    ]
    if old_relocations[-2:] != [(0x21, HIGH_CODE_SEGMENT), (0x136, HIGH_CODE_SEGMENT)]:
        raise ValueError("V18 high-code relocations changed")
    hp_relocations = (
        (HP_EMPTY_POINTER_HOOK + 6, 0),
        (HP_FULL_POINTER_HOOK + 6, 0),
    )
    _add_relocations(data, hp_relocations)

    module_bytes = len(data) - HEADER_BYTES
    module_paragraphs = (module_bytes + 15) // 16
    protected_heap_paragraph = (
        HIGH_CODE_SEGMENT * 16 + RUNTIME_HEAP_RESERVE + 15
    ) // 16
    minimum_allocation = max(0, protected_heap_paragraph - module_paragraphs)
    struct.pack_into("<H", data, 0x0A, minimum_allocation)
    pages = (len(data) + 511) // 512
    struct.pack_into("<HH", data, 0x02, len(data) & 0x1FF, pages)

    if len(data) > HIGH_CODE_FILE + RUNTIME_HEAP_RESERVE:
        raise ValueError("V19 executable overlaps the protected near heap")
    if data[HEADER_BYTES + 0xB594:HEADER_BYTES + 0xB598] != bytes.fromhex("e8 7c 3b 90"):
        raise ValueError("ordinary draw selector hook changed")
    if data[HEADER_BYTES + 0x0F60:HEADER_BYTES + 0x0F65] != bytes.fromhex("9a d0 00 1c 23"):
        raise ValueError("three-table loader hook changed")
    if data[empty_file + 6:empty_file + 8] != struct.pack("<H", HIGH_CODE_SEGMENT):
        raise ValueError("empty-HP FAR target changed")
    if data[full_file + 6:full_file + 8] != struct.pack("<H", HIGH_CODE_SEGMENT):
        raise ValueError("full-HP FAR target changed")

    relocation_count = struct.unpack_from("<H", data, 0x06)[0]
    relocations = [
        struct.unpack_from("<HH", data, table + index * 4)
        for index in range(relocation_count)
    ]
    if relocations[-2:] != list(hp_relocations):
        raise ValueError("HP hook relocation records changed")

    high_code = bytes(data[HIGH_CODE_FILE:HIGH_CODE_FILE + RUNTIME_HEAP_RESERVE])
    variants = ("right-p2", "left-p0", "left-p2")
    for image_id in range(219):
        for variant in variants:
            route = phase_route(image_id, variant)
            if route is None:
                raise ValueError(f"uncovered selector case {image_id}/{variant}")
            slot, alias = route
            if slot not in (v18.PHASE1_SLOT, v18.PHASE2_SLOT, PHASE3_SLOT):
                raise ValueError("selector model emitted an invalid slot")
            if not 0 <= alias <= 218:
                raise ValueError("selector model emitted an invalid alias")

    intercepted_ids = tuple(range(52, 64)) + tuple(range(77, 219))
    for image_id in intercepted_ids:
        for variant in variants:
            actual = v18.emulate_mapper(high_code, image_id, variant)
            expected = phase_route(image_id, variant)
            if actual != expected:
                raise ValueError(
                    f"machine mapper mismatch {image_id}/{variant}: {actual} != {expected}"
                )

    hp_cases = 0
    hp_lazy_load_cases = 0
    for image_id in (216, 217):
        for hp_index in range(10):
            for graphics_mode in (1, 5):
                for loaded in (False, True):
                    _slot, _alias, ended_loaded = emulate_hp_helper(
                        high_code,
                        helper_offset,
                        image_id,
                        hp_index,
                        graphics_mode,
                        loaded,
                    )
                    hp_cases += 1
                    if graphics_mode == 1 and hp_index & 1 and not loaded and ended_loaded:
                        hp_lazy_load_cases += 1

    expected_all_aliases = {
        variant: [
            phase_route(image_id, variant)[1]
            for image_id in v18.NEW_IMAGE_IDS + NEW_IMAGE_IDS
        ]
        for variant in variants
    }
    if expected_all_aliases != {
        "right-p2": list(range(0, 70)) + list(range(210, 213)),
        "left-p0": list(range(70, 140)) + list(range(213, 216)),
        "left-p2": list(range(140, 210)) + list(range(216, 219)),
    }:
        raise ValueError("complete PHASE3 alias map changed")

    executable = bytes(data)
    return executable, {
        "file": OUTPUT_EXE,
        "bytes": len(executable),
        "sha256": sha256_bytes(executable),
        "visible_ctrl_v_marker": "KID TABLE V19K    V1.3",
        "baseline": "user-confirmed V18F",
        "ordinary_draw_hook": "0000:B594",
        "hp_empty_pointer_hook": f"0000:{HP_EMPTY_POINTER_HOOK:04X}",
        "hp_full_pointer_hook": f"0000:{HP_FULL_POINTER_HOOK:04X}",
        "hp_helper": f"{HIGH_CODE_SEGMENT:04X}:{helper_offset:04X}",
        "extended_mapper": f"{HIGH_CODE_SEGMENT:04X}:{EXTENDED_MAPPER_OFFSET:04X}",
        "extended_code_bytes": len(code),
        "extended_code_end": f"{HIGH_CODE_SEGMENT:04X}:{EXTENDED_MAPPER_OFFSET + len(code):04X}",
        "runtime_heap_reservation_bytes": RUNTIME_HEAP_RESERVE,
        "minimum_allocation_paragraphs": minimum_allocation,
        "relocation_count": relocation_count,
        "relocations_added": len(hp_relocations),
        "machine_mapper_cases_verified": len(intercepted_ids) * len(variants),
        "hp_machine_cases_verified": hp_cases,
        "hp_lazy_load_cases_verified": hp_lazy_load_cases,
        "all_219_images_covered": True,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = V18 / "CGA4K18.COM"
    data = source.read_bytes()
    if sha256_bytes(data) != V18_COM_SHA256:
        raise ValueError("unexpected user-confirmed V18 launcher")
    data = v18.v17.replace_exact(data, b"P4KX18.EXE", b"P4KX19.EXE", expected=3)
    data = v18.v17.replace_exact(data, b"V18F", b"V19K")
    if b"KID PHASE TABLE V19K ACTIVE" not in data:
        raise ValueError("V19 launcher banner patch failed")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "child": OUTPUT_EXE,
        "banner": "KID PHASE TABLE V19K ACTIVE",
    }


def build_final_dats(
    art: object,
    generated_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    expected = {
        V18 / "KID.DAT": V18_KID_SHA256,
        V18 / "PHASE.DAT": V18_PHASE_SHA256,
        V18 / "PHASE2.DAT": V18_PHASE2_SHA256,
        V18 / "PHASE3.DAT": V18_PHASE3_SHA256,
    }
    for path, checksum in expected.items():
        if sha256_file(path) != checksum:
            raise ValueError(f"unexpected V18 input {path.name}")

    old_kid = art.DatArchive.open(V18 / "KID.DAT")
    old_phase3 = art.DatArchive.open(V18 / "PHASE3.DAT")
    generated = art.DatArchive.open(generated_path)
    for archive in (old_kid, old_phase3, generated):
        if not all(resource.checksum_ok for resource in archive.resources):
            raise ValueError("input DAT checksum failure")

    old_kid_map = {r.resource_id: r.data for r in old_kid.resources}
    old_phase3_map = {r.resource_id: r.data for r in old_phase3.resources}
    generated_map = {r.resource_id: r.data for r in generated.resources}
    expected_generated = (
        set(range(400, 620))
        | {PHASE3_RESOURCE_BASE}
        | set(range(3211, 3220))
    )
    if set(generated_map) != expected_generated:
        raise ValueError(
            "generated final-image resource set changed: "
            f"{sorted(set(generated_map) ^ expected_generated)}"
        )

    final_kid_map = dict(old_kid_map)
    for resource_id in NEW_NORMAL_RESOURCE_IDS:
        final_kid_map[resource_id] = generated_map[resource_id]
    final_kid = art._build_dat(sorted(final_kid_map.items()))
    (OUT / "KID.DAT").write_bytes(final_kid)

    final_phase3_map = dict(old_phase3_map)
    for resource_id in range(3211, 3220):
        final_phase3_map[resource_id] = generated_map[resource_id]
    final_phase3 = art._build_dat(sorted(final_phase3_map.items()))
    (OUT / "PHASE3.DAT").write_bytes(final_phase3)

    kid_check = art.DatArchive.open(OUT / "KID.DAT")
    phase3_check = art.DatArchive.open(OUT / "PHASE3.DAT")
    if [r.resource_id for r in kid_check.resources] != list(range(400, 620)):
        raise ValueError("KID resource order changed")
    if [r.resource_id for r in phase3_check.resources] != list(range(3000, 3220)):
        raise ValueError("PHASE3 resource order changed")
    if not all(
        resource.checksum_ok
        for archive in (kid_check, phase3_check)
        for resource in archive.resources
    ):
        raise ValueError("final DAT checksum verification failed")
    if phase3_check.resources[0].data[0] != 219:
        raise ValueError("PHASE3 no longer declares 219 images")

    changed_kid = [
        resource_id
        for resource_id in range(400, 620)
        if final_kid_map[resource_id] != old_kid_map[resource_id]
    ]
    if any(resource_id not in NEW_NORMAL_RESOURCE_IDS for resource_id in changed_kid):
        raise ValueError("an unrelated KID resource changed")
    for resource_id in NEW_NORMAL_RESOURCE_IDS:
        if final_kid_map[resource_id] != generated_map[resource_id]:
            raise ValueError(f"KID resource {resource_id} does not match optimizer output")

    changed_phase3 = [
        resource_id
        for resource_id in range(3000, 3220)
        if final_phase3_map[resource_id] != old_phase3_map[resource_id]
    ]
    if changed_phase3 != list(range(3211, 3220)):
        raise ValueError(f"PHASE3 changed unexpected resources: {changed_phase3}")
    for resource_id in range(3211, 3220):
        if final_phase3_map[resource_id] != generated_map[resource_id]:
            raise ValueError(f"PHASE3 resource {resource_id} mismatch")

    source = art.DatArchive.open(SOURCE_KID)
    invalid_headers: list[int] = []
    for resource_id in range(3001, 3220):
        analysis = phase3_check.analysis_by_id(resource_id)
        if analysis is None or analysis.image is None:
            invalid_headers.append(resource_id)
            continue
        image = analysis.image
        if not (0 < image.width <= 256 and 0 < image.height <= 256 and image.bits == 4):
            invalid_headers.append(resource_id)
    if invalid_headers:
        raise ValueError(f"invalid PHASE3 image headers: {invalid_headers}")

    mask_cases = 0
    for image_id in NEW_IMAGE_IDS:
        source_analysis = source.analysis_by_id(401 + image_id)
        if source_analysis is None or source_analysis.image is None:
            raise ValueError(f"missing source image {image_id}")
        source_mask = tuple(pixel == 0 for pixel in source_analysis.image.pixels)
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
                raise ValueError(f"missing final image resource {resource_id}")
            candidate_mask = tuple(pixel == 0 for pixel in analysis.image.pixels)
            if candidate_mask != source_mask:
                raise ValueError(f"transparency mask changed in resource {resource_id}")
            mask_cases += 1

    for path in V18.glob("*.DAT"):
        if path.name in {"KID.DAT", "PHASE3.DAT"}:
            continue
        output_path = OUT / path.name
        if output_path.read_bytes() != path.read_bytes():
            raise ValueError(f"unrelated DAT changed: {path.name}")

    phase3_memory = v18._native_table_memory(phase3_check, PHASE3_RESOURCE_BASE)
    kid_meta = {
        "file": "KID.DAT",
        "bytes": len(final_kid),
        "sha256": sha256_bytes(final_kid),
        "resource_count": len(kid_check.resources),
        "selected_resources": list(NEW_NORMAL_RESOURCE_IDS),
        "changed_from_v18_resources": changed_kid,
        "all_219_images_phase_aware": True,
        "all_checksums_valid": True,
    }
    phase3_meta = {
        "file": "PHASE3.DAT",
        "bytes": len(final_phase3),
        "sha256": sha256_bytes(final_phase3),
        "resource_count": len(phase3_check.resources),
        "resource_id_range": "3000..3219",
        "declared_image_count": 219,
        "image_slots_used": 219,
        "routed_aliases": 219,
        "padding_aliases": 0,
        "new_aliases": list(range(210, 219)),
        "new_resource_ids": list(range(3211, 3220)),
        "changed_from_v18_resources": changed_phase3,
        "all_image_headers_valid": True,
        "transparency_cases_verified": mask_cases,
        "decoded_image_upper_estimate_bytes": phase3_memory[0],
        "native_pointer_table_bytes": phase3_memory[1],
        "native_memory_upper_estimate_bytes": phase3_memory[2],
    }
    return kid_meta, phase3_meta


def render_visuals(art: object, generated_path: Path) -> list[str]:
    sys.modules["make_four_way_kid"] = art
    spec = importlib.util.spec_from_file_location("v19_render", RENDER_TOOL)
    if spec is None or spec.loader is None:
        raise ValueError("could not load visual verification renderer")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    source = art.DatArchive.open(SOURCE_KID)
    candidate = art.DatArchive.open(generated_path)
    visual_dir = OUT / "visual-verification"
    visual_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[str] = []

    sheet = visual_dir / "VISUAL-PHASE3-KID-HP-AND-HURT.png"
    renderer.contact_sheet(
        source,
        candidate,
        NEW_IMAGE_IDS,
        "Prince Exhaustive Phase Verification - Final KID Images",
        "Images 216-217: HP icons. Image 218: hurt splash. Four final-display cases.",
        sheet,
    )
    outputs.append(sheet.name)
    for direction in ("right", "left"):
        path = visual_dir / f"VISUAL-PHASE3-FINAL-KID-{direction.upper()}-TOGGLE.gif"
        renderer.phase_toggle_gif(candidate, NEW_IMAGE_IDS, direction, path)
        outputs.append(path.name)
    for temporary in visual_dir.glob("VISUAL-PHASE3-FINAL-KID-*.tmp"):
        temporary.unlink()
    return outputs


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging = zip_path.with_name(zip_path.name + ".building")
    if staging.exists():
        staging.unlink()
    fixed_time = (2026, 8, 25, 4, 0, 0)
    try:
        with zipfile.ZipFile(
            staging,
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
        with staging.open("rb") as handle:
            os.fsync(handle.fileno())
        staging.replace(zip_path)
    except BaseException:
        if staging.exists():
            staging.unlink()
        raise


README_TEMPLATE = """PRINCE OF PERSIA 1.3 - ALL 219 KID IMAGES PHASE-AWARE V19K
==================================================================

V19K is a focused extension of the user-confirmed V18F package. It replaces
the nine PHASE3 padding aliases with real variants for the last three KID
images:

  KID image 216 / resource 617   full Kid hit-point icon
  KID image 217 / resource 618   empty Kid hit-point icon
  KID image 218 / resource 619   Kid hurt splash

PHASE3 now uses every alias:

  0..209    V18 moving Kid/mouse variants
  210..212  images 216..218 right/P2
  213..215  images 216..218 left/P0
  216..218  images 216..218 left/P2

The hurt splash uses Prince's ordinary phase-aware moving-object draw path.
The HP icons use a dedicated selector because Prince draws them directly to
the screen. HP positions are X=7*index: even indices use KID/P0 and odd indices
use PHASE3/P2. No runtime image transform is used.

INSTALLATION
------------

Copy these six files together into the intended Prince 1.3 New-CGA directory:

  CGA4K19.COM
  P4KX19.EXE
  KID.DAT
  PHASE.DAT
  PHASE2.DAT
  PHASE3.DAT

Run CGA4K19.COM, not the EXE directly. Ctrl-V must show:

  KID TABLE V19K    V1.3

The launcher must print:

  KID PHASE TABLE V19K ACTIVE

Do not mix V19 files with older package versions.

FINAL TESTS
-----------

1. Display at least four Kid health icons. Check full and empty icons at
   positions 1, 2, 3, and 4; adjacent icons alternate P0/P2.
2. Lose and regain health so both icon images are drawn in both parities.
3. Take sword damage while facing each direction, at two adjacent horizontal
   positions. Also trigger spike, chopper, fall, and landing damage splashes.
4. Regression-test the V18 motions, especially sword pickup/combat, level-exit
   stairs, fall/landing, jumps, climbing, turns, and potion drinking.
5. Test restart, level transition, title return, and story interludes.

Use the normal 640-KiB DOS configuration.

CHECKSUMS
---------

KID.DAT:    {kid_sha256}
PHASE.DAT:  {phase1_sha256}
PHASE2.DAT: {phase2_sha256}
PHASE3.DAT: {phase3_sha256}
"""


def main() -> None:
    required = (V18, SOURCE_KID, BASELINE_KID, ART_TOOL, RENDER_TOOL)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"missing V19 build inputs: {missing}")

    if OUT.exists():
        shutil.rmtree(OUT)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(V18, OUT)
    for stale in (
        "P4KX18.EXE",
        "CGA4K18.COM",
        "KID-V18F-README.TXT",
        "KID-V18F-VERIFICATION.TXT",
        "KID-V18F-MANIFEST.JSON",
        "PACKAGE-MANIFEST.JSON",
        "SHA256SUMS.TXT",
    ):
        path = OUT / stale
        if path.exists():
            path.unlink()

    art = load_art_module()
    generated, artwork_meta, variants = generate_artwork(art)
    kid_meta, phase3_meta = build_final_dats(art, generated)
    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    visual_files = render_visuals(art, generated)

    phase1_sha = sha256_file(OUT / "PHASE.DAT")
    phase2_sha = sha256_file(OUT / "PHASE2.DAT")
    if phase1_sha != V18_PHASE_SHA256 or phase2_sha != V18_PHASE2_SHA256:
        raise ValueError("confirmed PHASE/PHASE2 tables changed")

    readme = README_TEMPLATE.format(
        kid_sha256=kid_meta["sha256"],
        phase1_sha256=phase1_sha,
        phase2_sha256=phase2_sha,
        phase3_sha256=phase3_meta["sha256"],
    )
    (OUT / "README.TXT").write_text(readme, encoding="ascii", newline="\r\n")
    (OUT / "KID-V19K-README.TXT").write_text(
        readme,
        encoding="ascii",
        newline="\r\n",
    )

    manifest = {
        "package": PACKAGE_NAME,
        "status": (
            "V19K static/resource/machine-helper/visual verification passed; "
            "DOS runtime verification pending"
        ),
        "baseline": {
            "version": "V18F",
            "runtime_status": "all V18 motions confirmed working by user",
            "exe_sha256": V18_EXE_SHA256,
            "kid_sha256": V18_KID_SHA256,
            "phase3_sha256": V18_PHASE3_SHA256,
        },
        "scope": {
            "new_image_ids": list(NEW_IMAGE_IDS),
            "new_resource_ids": list(NEW_NORMAL_RESOURCE_IDS),
            "new_unique_images": 3,
            "total_phase_aware_kid_images": 219,
            "remaining_kid_images": 0,
            "new_final_display_cases": 12,
            "total_final_display_cases": 219 * 4,
        },
        "conversion": {
            "source": "verified original VGA KID.DAT",
            "profile": "new-cga",
            "algorithm": "Exhaustive exact 2,048-state row dynamic program",
            "dither": "none",
            "phase_variants": [0, 2],
            "direction_variants": ["right", "left"],
            "artwork_generator_metadata": artwork_meta,
        },
        "runtime_architecture": {
            "ordinary_kid_and_hurt_splash": "existing V18 draw_mid selector",
            "hp_icons": "two direct pointer hooks selecting KID/P0 or PHASE3/P2",
            "hp_final_x": "7*hit_point_index",
            "hp_phase_rule": "even index -> P0; odd index -> P2",
            "phase3_lazy_load_from_hp_helper": True,
            "native_slots": {"PHASE.DAT": 3, "PHASE2.DAT": 4, "PHASE3.DAT": 9},
            "runtime_transform": False,
            "cpu": "8086/8088",
        },
        "phase3_alias_map": {
            "v18_existing": [0, 209],
            "final_right_p2": [210, 212],
            "final_left_p0": [213, 215],
            "final_left_p2": [216, 218],
            "padding": [],
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
        "kid_dat": kid_meta,
        "phase_dat": {
            "sha256": phase1_sha,
            "byte_identical_to_user_confirmed_v18": True,
        },
        "phase2_dat": {
            "sha256": phase2_sha,
            "byte_identical_to_user_confirmed_v18": True,
        },
        "phase3_dat": phase3_meta,
        "new_variants": variants,
        "visual_verification": visual_files,
        "remaining_kid_phase_work": [],
    }
    (OUT / "KID-V19K-MANIFEST.JSON").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    verification = f"""Prince of Persia 1.3 V19K All-219-KID Verification
=========================================================
EXE PASS     {OUTPUT_EXE}: {executable_meta['bytes']} bytes, SHA-256 {executable_meta['sha256']}
BASE PASS    User-confirmed V18F used as the exact executable/art baseline
MAP PASS     All 219 KID image IDs have three exact alternate routes
EMU PASS     {executable_meta['machine_mapper_cases_verified']}/{executable_meta['machine_mapper_cases_verified']} intercepted mapper cases match the software model
HP PASS      {executable_meta['hp_machine_cases_verified']}/{executable_meta['hp_machine_cases_verified']} emitted HP-helper cases select exact P0/P2 far pointers
LOAD PASS    {executable_meta['hp_lazy_load_cases_verified']} odd-HP cases verify lazy PHASE3 loading
RELOC PASS   Two relocated HP-helper FAR calls; {executable_meta['relocation_count']} total MZ relocations
COM PASS     {OUTPUT_COM}: child={OUTPUT_EXE}, SHA-256 {launcher_meta['sha256']}
KID PASS     Selected resources 617..619 match exhaustive optimizer output
PHASE1 PASS  Byte-identical to user-confirmed V18, SHA-256 {phase1_sha}
PHASE2 PASS  Byte-identical to user-confirmed V18, SHA-256 {phase2_sha}
PHASE3 PASS  Exactly resources 3211..3219 replace V18 padding, SHA-256 {phase3_meta['sha256']}
IMAGE PASS   219/219 PHASE3 image headers decode correctly
MASK PASS    {phase3_meta['transparency_cases_verified']}/{phase3_meta['transparency_cases_verified']} new final-display cases preserve source transparency
FILL PASS    PHASE3 aliases 0..218 are all real routed images; zero padding aliases
DAT PASS     Every unrelated DAT is byte-identical to V18
MEM PASS     Injected code ends at {executable_meta['extended_code_end']} inside the 768-byte protected region
CPU PASS     New code uses only 8086/8088 instructions

STATIC VERIFICATION PASSED.
DOS runtime verification is still required.
"""
    (OUT / "KID-V19K-VERIFICATION.TXT").write_text(
        verification,
        encoding="ascii",
        newline="\r\n",
    )

    tools_dir = OUT / "tools"
    tools_dir.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), tools_dir / Path(__file__).name)

    package_manifest = {**manifest, "files": {}}
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name not in {"PACKAGE-MANIFEST.JSON", "SHA256SUMS.TXT"}:
            relative = path.relative_to(OUT).as_posix()
            package_manifest["files"][relative] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    (OUT / "PACKAGE-MANIFEST.JSON").write_text(
        json.dumps(package_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    checksums = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.TXT":
            checksums.append(f"{sha256_file(path)}  {path.relative_to(OUT).as_posix()}")
    (OUT / "SHA256SUMS.TXT").write_text(
        "\n".join(checksums) + "\n",
        encoding="ascii",
    )

    make_zip(OUT, ZIP_PATH)
    print(json.dumps({
        "package_dir": str(OUT),
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "executable": executable_meta,
        "launcher": launcher_meta,
        "kid_dat": kid_meta,
        "phase3_dat": phase3_meta,
        "visual_verification": visual_files,
    }, indent=2))


if __name__ == "__main__":
    main()
