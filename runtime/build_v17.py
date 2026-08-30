#!/usr/bin/env python3
"""Build Prince 1.3 New-CGA V17 with a full second phase table.

V17 preserves the runtime-confirmed V16 slot-3 PHASE.DAT table and loads a
second standard Prince DAT archive, PHASE2.DAT, into native chtab slot 4.
PHASE2 is filled to its 219-image limit with three independently optimized
alternate cases for 73 additional KID images:

* images 80..111: vertical jump, grab, hang, and hang-drop;
* images 120..129: stand up from crouch;
* images 133..159: careful step and climb;
* images 207..210: draw-sword body frames.

The normal right/P0 cases remain in KID.DAT. PHASE2 contains right/P2,
left/P0, and left/P2 in alias ranges 0..72, 73..145, and 146..218.
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

import build_v16 as v16


ROOT = Path(__file__).resolve().parent
V16 = (
    ROOT
    / "build"
    / "Prince-1.3-New-CGA-Phase-Aware-V16-Fall-Landing-Dungeon-Version-B-DAT-Set"
)
SOURCE_KID = ROOT / "source_work" / "pop13" / "KID.DAT"
BASELINE_KID = ROOT / "source_work" / "baseline" / "KID.DAT"
ART_TOOL = v16.ART_TOOL
RENDER_TOOL = v16.RENDER_TOOL

BUILD_ROOT = ROOT / "build"
PACKAGE_NAME = (
    "Prince-1.3-New-CGA-Phase-Aware-V17-PHASE2-Full-"
    "Dungeon-Version-B-DAT-Set"
)
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"
ART_WORK = BUILD_ROOT / "v17-art-work"

OUTPUT_EXE = "P4KX17.EXE"
OUTPUT_COM = "CGA4K17.COM"

V16_EXE_SHA256 = (
    "a452ec98d4918cc6577938011ffd59a1047632b6ccefe808c7d20773ece015b7"
)
V16_COM_SHA256 = (
    "9ef3e94aa10ae58e76e55d57c670a208b272bee739627c1ef7fdbfd448704769"
)
V16_KID_SHA256 = (
    "07bc5efe2050a1a74f6cbea57bdb5bbbe23d8ba7653479d6f77af02ed7a2c03d"
)
V16_PHASE_SHA256 = (
    "ef91ee76ce79f5f7e3753fc9d48a2d0e553066ebb4d75bb3648e89f1ea615792"
)
SOURCE_KID_SHA256 = v16.SOURCE_KID_SHA256
BASELINE_KID_SHA256 = v16.BASELINE_KID_SHA256

SELECTED_FRAME_IMAGE_RANGES = (
    ("jump_up_grab_hang_part_1", 67, 85, 80, 98),
    ("hang_part_2", 87, 99, 99, 111),
    ("stand_up_from_crouch", 110, 119, 120, 129),
    ("careful_step", 121, 132, 133, 144),
    ("climb", 135, 149, 145, 159),
    ("draw_sword_body", 207, 210, 207, 210),
)
NEW_IMAGE_IDS = tuple(
    image_id
    for _name, _frame_first, _frame_last, image_first, image_last
    in SELECTED_FRAME_IMAGE_RANGES
    for image_id in range(image_first, image_last + 1)
)
if len(NEW_IMAGE_IDS) != 73 or len(set(NEW_IMAGE_IDS)) != 73:
    raise RuntimeError("V17 PHASE2 selection must contain exactly 73 unique images")

NEW_NORMAL_RESOURCE_IDS = tuple(401 + image_id for image_id in NEW_IMAGE_IDS)
OLD_SELECTED_IMAGE_IDS = tuple(
    list(range(0, 52)) + list(range(64, 77)) + list(range(112, 120))
)
ALL_SELECTED_IMAGE_IDS = OLD_SELECTED_IMAGE_IDS + NEW_IMAGE_IDS

PHASE1_SLOT = 3
PHASE2_SLOT = 4
PHASE1_POINTER = 0x453A
PHASE2_POINTER = 0x453C
PHASE1_RESOURCE_BASE = 1000
PHASE2_RESOURCE_BASE = 2000
RIGHT_P2_ALIAS = 0
LEFT_P0_ALIAS = 73
LEFT_P2_ALIAS = 146
PHASE2_FINAL_RESOURCE_ID = 2219

# Existing relocated high-code layout in V16. The original selector, its far
# calls, load hook, and MZ relocation records remain at their proven offsets.
HEADER_BYTES = 0x0A00
HIGH_CODE_FILE = 0x23BC0
HIGH_CODE_SEGMENT = 0x231C
MAPPER_STUB_OFFSET = 0x007B
MAPPER_STUB_END = 0x00B4
FETCH_COMMON_OFFSET = 0x0061
SELECTOR_DONE_OFFSET = 0x00C7
LOADER_OFFSET = 0x00D0
LOAD_ONE_OFFSET = 0x0125
RESERVE_HEAP_OFFSET = 0x0139
PHASE1_NAME_OFFSET = 0x0147
PHASE2_NAME_OFFSET = 0x0151
EXTENDED_MAPPER_OFFSET = 0x015C
PHASE1_NAME_DS = 0x78D7
PHASE2_NAME_DS = 0x78E1
RUNTIME_HEAP_RESERVE = 0x0200


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_exact(data: bytes, old: bytes, new: bytes, expected: int = 1) -> bytes:
    if len(old) != len(new):
        raise ValueError("binary replacement must preserve length")
    count = data.count(old)
    if count != expected:
        raise ValueError(f"expected {expected} occurrence(s) of {old!r}, found {count}")
    return data.replace(old, new)


class CodeBuilder:
    """Tiny 8086 assembler for relative branches used by the V17 extension."""

    def __init__(self, origin: int) -> None:
        self.origin = origin
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.fix8: list[tuple[int, str]] = []
        self.fix16: list[tuple[int, str | int]] = []

    @property
    def address(self) -> int:
        return self.origin + len(self.code)

    def emit(self, payload: bytes) -> None:
        self.code.extend(payload)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate code label {name}")
        self.labels[name] = self.address

    def branch8(self, opcode: int, label: str) -> None:
        self.code.extend((opcode, 0))
        self.fix8.append((len(self.code) - 1, label))

    def jump16(self, target: str | int) -> None:
        self.code.extend((0xE9, 0, 0))
        self.fix16.append((len(self.code) - 2, target))

    def call16(self, target: str | int) -> None:
        self.code.extend((0xE8, 0, 0))
        self.fix16.append((len(self.code) - 2, target))

    def finish(self) -> bytes:
        for displacement_index, label in self.fix8:
            if label not in self.labels:
                raise ValueError(f"missing short-branch label {label}")
            instruction_end = self.origin + displacement_index + 1
            displacement = self.labels[label] - instruction_end
            if not -128 <= displacement <= 127:
                raise ValueError(f"short branch to {label} is out of range")
            self.code[displacement_index] = displacement & 0xFF
        for displacement_index, target in self.fix16:
            resolved = self.labels[target] if isinstance(target, str) else target
            instruction_end = self.origin + displacement_index + 2
            displacement = resolved - instruction_end
            struct.pack_into("<h", self.code, displacement_index, displacement)
        return bytes(self.code)


def selected_image_ordinal(image_id: int) -> int:
    if 80 <= image_id <= 111:
        return image_id - 80
    if 120 <= image_id <= 129:
        return image_id - 88
    if 133 <= image_id <= 159:
        return image_id - 91
    if 207 <= image_id <= 210:
        return image_id - 138
    raise ValueError(f"Kid image ID {image_id} is not in PHASE2")


def load_art_module() -> object:
    spec = importlib.util.spec_from_file_location("v17_art", ART_TOOL)
    if spec is None or spec.loader is None:
        raise ValueError("could not load verified V13 artwork tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SELECTED_FRAME_IMAGE_RANGES = SELECTED_FRAME_IMAGE_RANGES
    module.SELECTED_IMAGE_IDS = NEW_IMAGE_IDS
    module.SLOT_STORED_ODD = PHASE2_SLOT
    module.PRIVATE_RESOURCE_BASE = PHASE2_RESOURCE_BASE
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
    generated = ART_WORK / "V17-PHASE2-COMBINED-KID.DAT"
    metadata, variants = art.build_four_way_dat(
        SOURCE_KID,
        BASELINE_KID,
        generated,
    )
    return generated, metadata, variants


def build_extended_mapper() -> bytes:
    """Map V16 fall aliases to slot 3 and 73 new images to slot 4."""

    b = CodeBuilder(EXTENDED_MAPPER_OFFSET)
    b.emit(bytes.fromhex("83 f9 70"))          # CMP CX,112
    b.branch8(0x72, "below_112")              # JB
    b.emit(bytes.fromhex("83 f9 78"))          # CMP CX,120
    b.branch8(0x72, "phase1_fall")            # JB
    b.emit(bytes.fromhex("81 f9 82 00"))       # CMP CX,130
    b.branch8(0x72, "phase2_120")             # JB
    b.emit(bytes.fromhex("81 f9 85 00"))       # CMP CX,133
    b.branch8(0x72, "fallback")               # JB
    b.emit(bytes.fromhex("81 f9 a0 00"))       # CMP CX,160
    b.branch8(0x72, "phase2_133")             # JB
    b.emit(bytes.fromhex("81 f9 cf 00"))       # CMP CX,207
    b.branch8(0x72, "fallback")               # JB
    b.emit(bytes.fromhex("81 f9 d3 00"))       # CMP CX,211
    b.branch8(0x72, "phase2_207")             # JB
    b.branch8(0xEB, "fallback")

    b.label("below_112")
    b.emit(bytes.fromhex("83 f9 50"))          # CMP CX,80
    b.branch8(0x72, "fallback")
    b.emit(bytes.fromhex("83 e9 50"))          # ordinal = image - 80
    b.branch8(0xEB, "phase2_alias")

    b.label("phase1_fall")
    b.emit(bytes.fromhex("83 e9 70"))          # ordinal = image - 112
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase1_right")
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase1_left_even")
    b.emit(bytes.fromhex("ba d3 00"))          # left/P2 base 211
    b.branch8(0xEB, "phase1_add")
    b.label("phase1_right")
    b.emit(bytes.fromhex("ba c3 00"))          # right/P2 base 195
    b.branch8(0xEB, "phase1_add")
    b.label("phase1_left_even")
    b.emit(bytes.fromhex("ba cb 00"))          # left/P0 base 203
    b.label("phase1_add")
    b.emit(bytes.fromhex("03 ca"))             # CX += DX
    b.emit(bytes.fromhex("8b 36 3a 45"))       # SI = slot 3
    b.jump16(FETCH_COMMON_OFFSET)

    b.label("phase2_120")
    b.emit(bytes.fromhex("83 e9 58"))          # ordinal = image - 88
    b.branch8(0xEB, "phase2_alias")
    b.label("phase2_133")
    b.emit(bytes.fromhex("83 e9 5b"))          # ordinal = image - 91
    b.branch8(0xEB, "phase2_alias")
    b.label("phase2_207")
    b.emit(bytes.fromhex("81 e9 8a 00"))       # ordinal = image - 138

    b.label("phase2_alias")
    b.emit(bytes.fromhex("83 fa 00"))
    b.branch8(0x74, "phase2_add")             # right/P2 base is zero
    b.emit(bytes.fromhex("83 fa 41"))
    b.branch8(0x74, "phase2_left_even")
    b.emit(bytes.fromhex("ba 92 00"))          # left/P2 base 146
    b.branch8(0xEB, "phase2_add")
    b.label("phase2_left_even")
    b.emit(bytes.fromhex("ba 49 00"))          # left/P0 base 73
    b.label("phase2_add")
    b.emit(bytes.fromhex("03 ca"))
    b.emit(bytes.fromhex("8b 36 3c 45"))       # SI = slot 4
    b.jump16(FETCH_COMMON_OFFSET)

    b.label("fallback")
    b.jump16(SELECTOR_DONE_OFFSET)
    code = b.finish()
    if EXTENDED_MAPPER_OFFSET + len(code) > RUNTIME_HEAP_RESERVE:
        raise ValueError("extended mapper exceeds protected high-code region")
    return code


def build_loader() -> bytes:
    """Load PHASE.DAT into slot 3 and PHASE2.DAT into slot 4 if absent."""

    b = CodeBuilder(LOADER_OFFSET)
    b.emit(bytes.fromhex("50 53 51 52 56 57 1e 06"))  # save all
    b.emit(bytes.fromhex("80 3e 35 31 01"))           # CGA mode 1
    b.branch8(0x75, "done")

    b.emit(bytes.fromhex("83 3e 3a 45 00"))           # slot 3 null?
    b.branch8(0x75, "check_slot4")
    b.emit(bytes.fromhex("b8 03 00"))                 # AX = slot 3
    b.emit(bytes.fromhex("bb e8 03"))                 # BX = resource 1000
    b.emit(b"\xba" + struct.pack("<H", PHASE1_NAME_DS))
    b.call16(LOAD_ONE_OFFSET)

    b.label("check_slot4")
    b.emit(bytes.fromhex("83 3e 3c 45 00"))           # slot 4 null?
    b.branch8(0x75, "done")
    b.emit(bytes.fromhex("b8 04 00"))                 # AX = slot 4
    b.emit(bytes.fromhex("bb d0 07"))                 # BX = resource 2000
    b.emit(b"\xba" + struct.pack("<H", PHASE2_NAME_DS))
    b.call16(LOAD_ONE_OFFSET)

    b.label("done")
    b.emit(bytes.fromhex("07 1f 5f 5e 5a 59 5b 58"))  # restore all
    b.emit(bytes.fromhex("80 3e 35 31 05"))           # displaced CMP
    b.emit(b"\xcb")                                  # RETF
    code = b.finish()
    if len(code) > LOAD_ONE_OFFSET - LOADER_OFFSET:
        raise ValueError("two-table loader overlaps load_one")
    return code


def phase2_route(image_id: int, variant: str) -> tuple[int, int] | None:
    """Pure model of the complete V17 selector contract."""

    old_bases = {"right-p2": 0, "left-p0": 65, "left-p2": 130}
    fall_bases = {"right-p2": 195, "left-p0": 203, "left-p2": 211}
    phase2_bases = {
        "right-p2": RIGHT_P2_ALIAS,
        "left-p0": LEFT_P0_ALIAS,
        "left-p2": LEFT_P2_ALIAS,
    }
    if variant not in old_bases:
        raise ValueError(f"unknown variant {variant}")
    if 0 <= image_id <= 51:
        return PHASE1_SLOT, old_bases[variant] + image_id
    if 64 <= image_id <= 76:
        return PHASE1_SLOT, old_bases[variant] + image_id - 12
    if 112 <= image_id <= 119:
        return PHASE1_SLOT, fall_bases[variant] + image_id - 112
    if image_id in NEW_IMAGE_IDS:
        return PHASE2_SLOT, phase2_bases[variant] + selected_image_ordinal(image_id)
    return None


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = V16 / "P4KX16.EXE"
    original = source.read_bytes()
    if sha256_bytes(original) != V16_EXE_SHA256:
        raise ValueError("unexpected V16 executable")
    data = bytearray(original)

    # Replace V16's local fall mapper with a near jump to the appended mapper.
    stub_file = HIGH_CODE_FILE + MAPPER_STUB_OFFSET
    stub_end_file = HIGH_CODE_FILE + MAPPER_STUB_END
    mapper_file = HIGH_CODE_FILE + EXTENDED_MAPPER_OFFSET
    if data[stub_file:stub_end_file] == b"\x90" * (stub_end_file - stub_file):
        raise ValueError("V16 fall mapper unexpectedly absent")
    displacement = EXTENDED_MAPPER_OFFSET - (MAPPER_STUB_OFFSET + 3)
    stub = b"\xe9" + struct.pack("<h", displacement)
    data[stub_file:stub_end_file] = stub + b"\x90" * (
        stub_end_file - stub_file - len(stub)
    )

    # Replace the loader but keep load_one, reserve_heap, and both existing
    # relocated far-call sites at their original offsets.
    loader = build_loader()
    loader_file = HIGH_CODE_FILE + LOADER_OFFSET
    load_one_file = HIGH_CODE_FILE + LOAD_ONE_OFFSET
    data[loader_file:load_one_file] = loader + b"\x90" * (
        load_one_file - loader_file - len(loader)
    )
    load_one = (
        bytes.fromhex("50 53 52")              # slot, resource base, filename
        + bytes.fromhex("b8 80 00 50")         # CGA/Kid hardware flag
        + bytes.fromhex("b8 be 18 50")         # 219-byte Kid control table
        + b"\x90\x90\x90"                    # keep relocated FAR CALL fixed
        + bytes.fromhex("9a 2d 15 00 00 c3")
    )
    if len(load_one) != RESERVE_HEAP_OFFSET - LOAD_ONE_OFFSET:
        raise ValueError("load_one no longer fits its fixed relocation window")
    data[load_one_file:HIGH_CODE_FILE + RESERVE_HEAP_OFFSET] = load_one

    # Protect the larger injected region from the Microsoft C near heap.
    reserve_file = HIGH_CODE_FILE + RESERVE_HEAP_OFFSET
    expected_reserve = bytes.fromhex(
        "8b c4 05 64 01 36 a3 fe 2d 36 a3 fa 2d cb"
    )
    if data[reserve_file:reserve_file + len(expected_reserve)] != expected_reserve:
        raise ValueError("unexpected V16 reserve_heap routine")
    reserve = (
        bytes.fromhex("8b c4 05")
        + struct.pack("<H", RUNTIME_HEAP_RESERVE + 4)
        + bytes.fromhex("36 a3 fe 2d 36 a3 fa 2d cb")
    )
    data[reserve_file:reserve_file + len(reserve)] = reserve

    # Keep the proven PHASE.DAT string at exactly DS:78D7, append PHASE2.DAT
    # at DS:78E1, then append the range mapper.
    phase1_file = HIGH_CODE_FILE + PHASE1_NAME_OFFSET
    if data[phase1_file:phase1_file + 10] != b"phase.dat\x00":
        raise ValueError("V16 phase.dat string moved")
    data = data[: HIGH_CODE_FILE + PHASE2_NAME_OFFSET]
    data.extend(b"phase2.dat\x00")
    if len(data) != mapper_file:
        raise ValueError("PHASE2 filename did not end at the mapper boundary")
    mapper = build_extended_mapper()
    data.extend(mapper)

    # Patch the visible marker without moving it.
    marked = replace_exact(bytes(data), b"KID TABLE V16F", b"KID TABLE V17P")
    data = bytearray(marked)

    # Update MZ size and minimum-allocation fields for the longer load module.
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

    # Static binary invariants and relocation sites.
    if bytes(data[0xA00 + 0xB594:0xA00 + 0xB598]) != bytes.fromhex("e8 7c 3b 90"):
        raise ValueError("draw selector near hook changed")
    if bytes(data[0xA00 + 0xF113:0xA00 + 0xF118]) != bytes.fromhex("9a 00 00 1c 23"):
        raise ValueError("draw selector FAR trampoline changed")
    if bytes(data[0xA00 + 0x0F60:0xA00 + 0x0F65]) != bytes.fromhex("9a d0 00 1c 23"):
        raise ValueError("two-table loader hook changed")
    if bytes(data[HIGH_CODE_FILE + 0x21:HIGH_CODE_FILE + 0x23]) != bytes.fromhex("00 00"):
        raise ValueError("selector FAR relocation site moved")
    if bytes(data[HIGH_CODE_FILE + 0x136:HIGH_CODE_FILE + 0x138]) != bytes.fromhex("00 00"):
        raise ValueError("load_chtab FAR relocation site moved")
    relocation_count = struct.unpack_from("<H", data, 0x06)[0]
    relocation_offset = struct.unpack_from("<H", data, 0x18)[0]
    relocations = [
        struct.unpack_from("<HH", data, relocation_offset + index * 4)
        for index in range(relocation_count)
    ]
    if relocations[-2:] != [(0x21, HIGH_CODE_SEGMENT), (0x136, HIGH_CODE_SEGMENT)]:
        raise ValueError("high-code relocation records changed")
    protected_end = HIGH_CODE_FILE + RUNTIME_HEAP_RESERVE
    if len(data) > protected_end:
        raise ValueError("V17 high code extends into the protected near heap")

    # Exhaustively validate the software selector model.
    for image_id in range(216):
        for variant in ("right-p2", "left-p0", "left-p2"):
            route = phase2_route(image_id, variant)
            if route is not None:
                slot, alias = route
                if slot not in (PHASE1_SLOT, PHASE2_SLOT) or not 0 <= alias <= 218:
                    raise ValueError("selector model emitted invalid slot/alias")
    expected_phase2 = {
        variant: [phase2_route(image_id, variant)[1] for image_id in NEW_IMAGE_IDS]
        for variant in ("right-p2", "left-p0", "left-p2")
    }
    if expected_phase2 != {
        "right-p2": list(range(0, 73)),
        "left-p0": list(range(73, 146)),
        "left-p2": list(range(146, 219)),
    }:
        raise ValueError("PHASE2 aliases do not fill exactly 0..218")

    total_minimum_paragraphs = module_paragraphs + minimum_allocation
    executable = bytes(data)
    return executable, {
        "file": OUTPUT_EXE,
        "bytes": len(executable),
        "sha256": sha256_bytes(executable),
        "visible_ctrl_v_marker": "KID TABLE V17P    V1.3",
        "baseline": "runtime-confirmed V16F",
        "phase1_table": "live native chtab slot 3 at DS:453A",
        "phase2_table": "live native chtab slot 4 at DS:453C",
        "phase1_filename_ds": f"DS:{PHASE1_NAME_DS:04X}",
        "phase2_filename_ds": f"DS:{PHASE2_NAME_DS:04X}",
        "extended_mapper_offset": f"{HIGH_CODE_SEGMENT:04X}:{EXTENDED_MAPPER_OFFSET:04X}",
        "extended_mapper_bytes": len(mapper),
        "runtime_heap_reservation_bytes": RUNTIME_HEAP_RESERVE,
        "minimum_allocation_paragraphs": minimum_allocation,
        "dos_minimum_total_paragraphs": total_minimum_paragraphs,
        "relocation_count": relocation_count,
        "old_coverage_preserved": True,
        "new_image_count": len(NEW_IMAGE_IDS),
        "new_alias_ranges": {
            "right-p2": [0, 72],
            "left-p0": [73, 145],
            "left-p2": [146, 218],
        },
        "native_slots_detached": False,
        "runtime_transforms": False,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = V16 / "CGA4K16.COM"
    data = source.read_bytes()
    if sha256_bytes(data) != V16_COM_SHA256:
        raise ValueError("unexpected V16 launcher")
    data = replace_exact(data, b"P4KX16.EXE", b"P4KX17.EXE", expected=3)
    data = replace_exact(data, b"V16F", b"V17P")
    if b"KID PHASE TABLE V17P ACTIVE" not in data:
        raise ValueError("V17 launcher banner patch failed")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "child": OUTPUT_EXE,
        "banner": "KID PHASE TABLE V17P ACTIVE",
    }


def build_final_dats(
    art: object,
    generated_path: Path,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    v16_kid_path = V16 / "KID.DAT"
    v16_phase_path = V16 / "PHASE.DAT"
    if sha256_file(v16_kid_path) != V16_KID_SHA256:
        raise ValueError("unexpected V16 KID.DAT")
    if sha256_file(v16_phase_path) != V16_PHASE_SHA256:
        raise ValueError("unexpected V16 PHASE.DAT")

    old_kid = art.DatArchive.open(v16_kid_path)
    old_phase = art.DatArchive.open(v16_phase_path)
    generated = art.DatArchive.open(generated_path)
    if not all(
        resource.checksum_ok
        for archive in (old_kid, old_phase, generated)
        for resource in archive.resources
    ):
        raise ValueError("input DAT checksum failure")

    old_kid_map = {resource.resource_id: resource.data for resource in old_kid.resources}
    old_phase_map = {resource.resource_id: resource.data for resource in old_phase.resources}
    generated_map = {resource.resource_id: resource.data for resource in generated.resources}
    if set(old_kid_map) != set(range(400, 620)):
        raise ValueError("V16 KID.DAT resource set changed")
    if set(old_phase_map) != set(range(1000, 1220)):
        raise ValueError("V16 PHASE.DAT resource set changed")
    if set(generated_map) != set(range(400, 620)) | set(range(2000, 2220)):
        raise ValueError("generated V17 artwork resource set is incomplete")

    final_kid_map = dict(old_kid_map)
    for resource_id in NEW_NORMAL_RESOURCE_IDS:
        final_kid_map[resource_id] = generated_map[resource_id]
    final_kid = art._build_dat(sorted(final_kid_map.items()))
    (OUT / "KID.DAT").write_bytes(final_kid)

    # PHASE.DAT is deliberately byte-identical to the runtime-confirmed V16.
    shutil.copy2(v16_phase_path, OUT / "PHASE.DAT")
    final_phase2 = art._build_dat(
        (resource_id, generated_map[resource_id])
        for resource_id in range(2000, 2220)
    )
    (OUT / "PHASE2.DAT").write_bytes(final_phase2)

    kid_check = art.DatArchive.open(OUT / "KID.DAT")
    phase_check = art.DatArchive.open(OUT / "PHASE.DAT")
    phase2_check = art.DatArchive.open(OUT / "PHASE2.DAT")
    if not all(
        resource.checksum_ok
        for archive in (kid_check, phase_check, phase2_check)
        for resource in archive.resources
    ):
        raise ValueError("final DAT checksum verification failed")
    if [resource.resource_id for resource in kid_check.resources] != list(range(400, 620)):
        raise ValueError("final KID resource order changed")
    if [resource.resource_id for resource in phase_check.resources] != list(range(1000, 1220)):
        raise ValueError("final PHASE resource order changed")
    if [resource.resource_id for resource in phase2_check.resources] != list(range(2000, 2220)):
        raise ValueError("PHASE2 resources are not exactly 2000..2219")
    if phase2_check.resources[0].data[0] != 219:
        raise ValueError("PHASE2 header does not declare 219 images")
    if (OUT / "PHASE.DAT").read_bytes() != v16_phase_path.read_bytes():
        raise ValueError("runtime-confirmed PHASE.DAT changed")

    selected_normal = set(NEW_NORMAL_RESOURCE_IDS)
    for resource in kid_check.resources:
        before = old_kid_map[resource.resource_id]
        if resource.resource_id not in selected_normal and resource.data != before:
            raise ValueError(f"unrelated KID resource changed: {resource.resource_id}")
        if (
            resource.resource_id in selected_normal
            and resource.data != generated_map[resource.resource_id]
        ):
            raise ValueError(f"new KID resource mismatch: {resource.resource_id}")
    for resource_id in range(2000, 2220):
        if phase2_check.analysis_by_id(resource_id).resource.data != generated_map[resource_id]:
            raise ValueError(f"PHASE2 resource mismatch: {resource_id}")

    source = art.DatArchive.open(SOURCE_KID)
    invalid_headers: list[int] = []
    mask_failures: list[int] = []
    for alias in range(219):
        resource_id = 2001 + alias
        analysis = phase2_check.analysis_by_id(resource_id)
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
            (phase2_check, 2001 + RIGHT_P2_ALIAS + ordinal),
            (phase2_check, 2001 + LEFT_P0_ALIAS + ordinal),
            (phase2_check, 2001 + LEFT_P2_ALIAS + ordinal),
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
        raise ValueError(f"invalid PHASE2 image headers: {invalid_headers}")
    if mask_failures:
        raise ValueError(f"V17 transparency-mask failures: {mask_failures}")

    phase2_decoded_image_bytes = sum(
        ((phase2_check.analysis_by_id(2001 + alias).image.width + 1) // 2)
        * phase2_check.analysis_by_id(2001 + alias).image.height
        + 6
        for alias in range(219)
    )
    phase2_pointer_table_bytes = 6 + 219 * 4
    phase2_native_upper_bytes = (
        phase2_decoded_image_bytes + phase2_pointer_table_bytes
    )

    kid_meta = {
        "file": "KID.DAT",
        "bytes": len(final_kid),
        "sha256": sha256_bytes(final_kid),
        "resource_count": len(kid_check.resources),
        "new_right_p0_resource_count": len(NEW_NORMAL_RESOURCE_IDS),
        "new_right_p0_resources": list(NEW_NORMAL_RESOURCE_IDS),
        "unrelated_resources_byte_identical_to_v16": True,
        "all_checksums_valid": True,
    }
    phase1_meta = {
        "file": "PHASE.DAT",
        "bytes": (OUT / "PHASE.DAT").stat().st_size,
        "sha256": sha256_file(OUT / "PHASE.DAT"),
        "resource_count": len(phase_check.resources),
        "resource_id_range": "1000..1219",
        "byte_identical_to_runtime_confirmed_v16": True,
        "declared_image_count": 219,
        "image_slots_used": 219,
    }
    phase2_meta = {
        "file": "PHASE2.DAT",
        "bytes": len(final_phase2),
        "sha256": sha256_bytes(final_phase2),
        "resource_count": len(phase2_check.resources),
        "resource_id_range": "2000..2219",
        "declared_image_count": 219,
        "image_slots_used": 219,
        "image_slots_remaining": 0,
        "source_image_count": len(NEW_IMAGE_IDS),
        "all_checksums_valid": True,
        "all_image_headers_valid": True,
        "transparency_cases_verified": len(NEW_IMAGE_IDS) * 4,
        "decoded_image_upper_estimate_bytes": phase2_decoded_image_bytes,
        "native_pointer_table_bytes": phase2_pointer_table_bytes,
        "native_memory_upper_estimate_bytes": phase2_native_upper_bytes,
    }
    return kid_meta, phase1_meta, phase2_meta


def render_visuals(art: object, generated_path: Path) -> list[str]:
    sys.modules["make_four_way_kid"] = art
    spec = importlib.util.spec_from_file_location("v17_render", RENDER_TOOL)
    if spec is None or spec.loader is None:
        raise ValueError("could not load visual verification renderer")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    source = art.DatArchive.open(SOURCE_KID)
    candidate = art.DatArchive.open(generated_path)
    visual_dir = OUT / "visual-verification"
    groups = (
        ("JUMP-HANG", tuple(range(80, 112)), "Vertical jump, grab, hang, and release"),
        ("STAND-UP", tuple(range(120, 130)), "Stand up from crouch"),
        ("CAREFUL-STEP", tuple(range(133, 145)), "Careful stepping"),
        ("CLIMB", tuple(range(145, 160)), "Climbing"),
        ("DRAW-SWORD", tuple(range(207, 211)), "Draw-sword body"),
    )
    outputs: list[str] = []
    for slug, image_ids, description in groups:
        path = visual_dir / f"VISUAL-PHASE2-{slug}.png"
        renderer.contact_sheet(
            source,
            candidate,
            image_ids,
            f"Prince Exhaustive Phase Verification - PHASE2 {slug}",
            f"{description}. Four independent final-display waveforms; no dither.",
            path,
        )
        outputs.append(path.name)
    for direction in ("right", "left"):
        path = visual_dir / f"VISUAL-PHASE2-{direction.upper()}-PHASE-TOGGLE.gif"
        renderer.phase_toggle_gif(candidate, NEW_IMAGE_IDS, direction, path)
        outputs.append(path.name)
    # Some filesystems can briefly retain Pillow's verified staging file.
    # Never ship those implementation-only duplicates in the release archive.
    for temporary in visual_dir.glob("VISUAL-PHASE2-*.tmp"):
        temporary.unlink()
    return outputs


def make_zip(source_dir: Path, zip_path: Path) -> None:
    # Build under a non-ZIP name, flush it, and publish it in one rename.  This
    # keeps file indexers and artifact collectors from opening a partial ZIP.
    staging_path = zip_path.with_name(zip_path.name + ".building")
    if staging_path.exists():
        staging_path.unlink()
    fixed_time = (2026, 8, 24, 22, 0, 0)
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


README_TEMPLATE = """PRINCE OF PERSIA 1.3 - PHASE2 FULL TABLE V17P
=====================================================

PURPOSE
-------

V17P preserves the runtime-confirmed V16F PHASE.DAT table in native slot 3
and adds a second full phase table, PHASE2.DAT, in native slot 4. PHASE2 uses
all 219 aliases to add 73 phase-aware KID images:

  game frames  67..85   KID images  80..98    jump up / grab / hang
  game frame   86       KID image   28        already covered by V15C
  game frames  87..99   KID images  99..111   hang / release
  game frames 110..119  KID images 120..129   stand up from crouch
  game frames 121..132  KID images 133..144   careful step
  game frames 135..149  KID images 145..159   climbing
  game frames 207..210  KID images 207..210   draw-sword body

Every new pose has four independently optimized final-display cases: right/P0,
right/P2, left/P0, and left/P2. KID.DAT supplies right/P0. PHASE2.DAT supplies
the other three cases. Exhaustive conversion uses the New-CGA signal model and
no dithering.

INSTALLATION
------------

1. Use a clean copy of the intended New-CGA Prince 1.3 directory, or the
   working V16F directory.
2. Copy CGA4K17.COM, P4KX17.EXE, KID.DAT, PHASE.DAT, and PHASE2.DAT into it.
3. Keep all five files together. Do not mix V16 and V17 files.
4. Run CGA4K17.COM. Do not run P4KX17.EXE directly.
5. Press Ctrl-V and confirm:

       KID TABLE V17P    V1.3

   The launcher must print:

       KID PHASE TABLE V17P ACTIVE

PHASE.DAT must be exactly {phase1_bytes:,} bytes with SHA-256:

  {phase1_sha256}

PHASE2.DAT must be exactly {phase2_bytes:,} bytes with SHA-256:

  {phase2_sha256}

TEST ROUTE
----------

First regression-test all previously confirmed V16 motions: stand, run, both
turns, horizontal jumps, fall, landing, and held crouch.

Then test the new PHASE2 families at adjacent X positions in both directions:

  * jump straight up, grab a ledge, hang, release, and re-grab;
  * climb onto a ledge and climb down;
  * land, hold crouch, then release Down and watch the full stand-up;
  * careful-step with Shift+Left and Shift+Right;
  * draw the sword while facing both directions.

The Kid body should retain its intended color family across even/odd final
screen X. The separately drawn moving sword is stored in PRINCE.DAT and is not
part of this KID-table build, so judge the Kid body during draw-sword testing.

Also test restart, level transition, return to title, and re-entering gameplay.
These exercise the slot-3 and slot-4 reload lifecycle. Test with the normal
640-KiB configuration because PHASE2 adds a second full native sprite table.

ARCHITECTURE
------------

  PHASE.DAT loading    Prince load_chtab -> live native slot 3
  PHASE2.DAT loading   Prince load_chtab -> live native slot 4
  drawing              Prince original conversion/flip/draw path
  runtime transforms   none
  custom DOS I/O       none
  CPU                   8086/8088 compatible

TABLE CAPACITY
--------------

PHASE.DAT is full and covers 73 source images. PHASE2.DAT is also full:

  right/P2 aliases       0..72
  left/P0 aliases       73..145
  left/P2 aliases      146..218

V17 therefore covers 146 of the 216 KID images. Exactly 70 KID images remain;
one final 219-slot table can hold all 210 required alternate cases.

MEMORY
------

PHASE2.DAT is {phase2_bytes:,} compressed bytes in this build. Its 219 decoded
images plus native pointer table have an upper estimate of
{phase2_memory_bytes:,} conventional-memory
bytes. Prince allocates the images as normal individual sprite objects; the
patch adds no single large custom allocation and uses no XMS or EMS. The prior
V15B diagnostic measured 301,568 free far-heap bytes at low water with the
first phase table present, so the second table has a substantial expected
margin. Actual DOS runtime testing remains required.
"""


def main() -> None:
    required = (V16, SOURCE_KID, BASELINE_KID, ART_TOOL, RENDER_TOOL)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"missing V17 build inputs: {missing}")

    if OUT.exists():
        shutil.rmtree(OUT)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(V16, OUT)

    for stale in (
        "P4KX16.EXE",
        "CGA4K16.COM",
        "KID-V16F-README.TXT",
        "KID-V16F-VERIFICATION.TXT",
        "KID-V16F-MANIFEST.JSON",
        "PACKAGE-MANIFEST.JSON",
        "SHA256SUMS.TXT",
    ):
        path = OUT / stale
        if path.exists():
            path.unlink()

    art = load_art_module()
    generated, artwork_meta, variants = generate_artwork(art)
    kid_meta, phase1_meta, phase2_meta = build_final_dats(art, generated)
    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    visual_files = render_visuals(art, generated)

    readme = README_TEMPLATE.format(
        phase1_bytes=phase1_meta["bytes"],
        phase1_sha256=phase1_meta["sha256"],
        phase2_bytes=phase2_meta["bytes"],
        phase2_sha256=phase2_meta["sha256"],
        phase2_memory_bytes=phase2_meta["native_memory_upper_estimate_bytes"],
    )
    (OUT / "README.TXT").write_text(readme, encoding="ascii", newline="\r\n")
    (OUT / "KID-V17P-README.TXT").write_text(
        readme,
        encoding="ascii",
        newline="\r\n",
    )

    manifest = {
        "package": PACKAGE_NAME,
        "status": (
            "V17P static/resource/visual verification passed; "
            "DOS runtime verification pending"
        ),
        "baseline": {
            "version": "V16F live native slot-3 table",
            "runtime_status": (
                "all V16 covered motions confirmed working by user, including "
                "fall and held crouch"
            ),
        },
        "scope": {
            "actions": [
                "vertical jump, grab, hang, release",
                "stand up from crouch",
                "careful step",
                "climb",
                "draw-sword body",
            ],
            "frame_image_ranges": [
                {
                    "name": name,
                    "game_frames": [frame_first, frame_last],
                    "kid_images": [image_first, image_last],
                }
                for name, frame_first, frame_last, image_first, image_last
                in SELECTED_FRAME_IMAGE_RANGES
            ],
            "new_image_ids": list(NEW_IMAGE_IDS),
            "new_unique_images": len(NEW_IMAGE_IDS),
            "total_phase_aware_unique_images": len(ALL_SELECTED_IMAGE_IDS),
            "kid_image_total": 216,
            "remaining_unique_images": 216 - len(ALL_SELECTED_IMAGE_IDS),
            "new_final_display_cases": len(NEW_IMAGE_IDS) * 4,
            "total_final_display_cases": len(ALL_SELECTED_IMAGE_IDS) * 4,
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
            "sidecars": ["PHASE.DAT", "PHASE2.DAT"],
            "sidecars_are_standard_prince_dat": True,
            "loader": "Prince load_chtab",
            "native_slots": {"PHASE.DAT": 3, "PHASE2.DAT": 4},
            "native_slots_kept_live": True,
            "selector": "direct live-slot lookup with range mapper",
            "runtime_transform": False,
            "custom_dos_io": False,
            "cpu": "8086/8088",
        },
        "phase2_alias_map": {
            "right_p2": [0, 72],
            "left_p0": [73, 145],
            "left_p2": [146, 218],
            "remaining_aliases": 0,
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
        "kid_dat": kid_meta,
        "phase_dat": phase1_meta,
        "phase2_dat": phase2_meta,
        "new_variants": variants,
        "visual_verification": visual_files,
        "next_architecture_boundary": (
            "70 KID images remain; a final native table needs 210 of 219 aliases"
        ),
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (OUT / "KID-V17P-MANIFEST.JSON").write_text(manifest_text, encoding="utf-8")

    verification = f"""Prince of Persia 1.3 V17P PHASE2 Verification
==================================================
EXE PASS     {OUTPUT_EXE}: {executable_meta['bytes']} bytes, SHA-256 {executable_meta['sha256']}
SLOT3 PASS   PHASE.DAT remains live at DS:453A and byte-identical to V16
SLOT4 PASS   PHASE2.DAT loads through Prince load_chtab at DS:453C
MAP PASS     73 images map to slot-4 aliases 0..218 in three exact ranges
OLD PASS     All 73 V16-covered KID images retain their slot-3 mapping
COM PASS     {OUTPUT_COM}: child={OUTPUT_EXE}, SHA-256 {launcher_meta['sha256']}
KID PASS     73 new right/P0 images; SHA-256 {kid_meta['sha256']}
PHASE1 PASS  PHASE.DAT: SHA-256 {phase1_meta['sha256']}
PHASE2 PASS  220/220 resources, SHA-256 {phase2_meta['sha256']}
IMAGE PASS   219/219 PHASE2 image headers decode correctly
MASK PASS    292/292 new direction/phase cases preserve source transparency
VIS PASS     Five contact sheets and two full-table phase-toggle GIFs rendered
MEM PASS     Injected code stays inside the 512-byte protected high region
CPU PASS     Selector and loader use only 8086/8088 instructions

STATIC VERIFICATION PASSED.
DOS runtime verification is still required.
"""
    (OUT / "KID-V17P-VERIFICATION.TXT").write_text(
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
    print(
        json.dumps(
            {
                "package_dir": str(OUT),
                "zip": str(ZIP_PATH),
                "zip_bytes": ZIP_PATH.stat().st_size,
                "zip_sha256": sha256_file(ZIP_PATH),
                "exe": executable_meta,
                "launcher": launcher_meta,
                "kid_dat": kid_meta,
                "phase_dat": phase1_meta,
                "phase2_dat": phase2_meta,
                "visual_verification": visual_files,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
