#!/usr/bin/env python3
"""Build the Prince of Persia 1.3 composite phase-lock prototype.

The prototype patches the final screen X coordinate used by draw_mid().  It
does not change Prince's movement or collision coordinates.  Transparent
mid-table sprites are locked to either the even or odd composite carrier
phase, while other blitters (notably the Shadow's OR/XOR pair) are untouched.

The supplied Prince 1.3 executable is Microsoft EXEPACK-compressed.  New code
cannot safely be inserted into that compressed stream, so this tool first
expands it into an ordinary MZ executable and then uses verified linker padding
inside the existing code segment for the 14-byte hook.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
from typing import Final


EXPECTED_PRINCE_SHA256: Final = (
    "24fdc79b4de563348313b50d717e171919191e5c38559f5bdd6a4751d39b7158"
)
EXPECTED_UNPACKED_SHA256: Final = (
    "25f8e465b643ef6c97f0f1260889103e96febd3229063bdcc6746e303dbf78f6"
)
EXPECTED_LAUNCHER_SHA256: Final = (
    "73e62428b4d7830f563d849e6a5ae602327cbea3ff25a4450b50ad5dbd11632e"
)

# Offsets are relative to the unpacked MZ load module, not the file header.
# 0000:B641 is the post-scaling/post-horizontal-flip join in draw_mid().
# 0000:F113 begins 29 bytes of linker padding after a RETF 8 instruction.
HOOK_OFFSET: Final = 0xB641
CAVE_OFFSET: Final = 0xF113
CAVE_CAPACITY: Final = 29

# Original instruction at HOOK_OFFSET plus enough following bytes to make the
# signature specific to the final-X join:
#   LES BX,[BP-06]
#   MOV AX,ES:[BX+04]
#   AND AX,8000
#   MOV [BP-02],AX
HOOK_SIGNATURE: Final = bytes.fromhex(
    "c4 5e fa 26 8b 47 04 25 00 80 89 46 fe"
)

PHASE_OUTPUTS: Final = {
    "even": ("PHEVEN.EXE", "CGAEVEN.COM", b"PHEVEN.EXE"),
    "odd": ("PHODD1.EXE", "CGAODD.COM", b"PHODD1.EXE"),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def unique_offset(data: bytes | bytearray, needle: bytes, description: str) -> int:
    first = data.find(needle)
    if first < 0:
        raise ValueError(f"missing {description}")
    if data.find(needle, first + 1) >= 0:
        raise ValueError(f"expected exactly one {description}")
    return first


def unpack_exepack(packed: bytes) -> bytes:
    """Expand the classic EXEPACK variant used by this Prince 1.3 build."""
    if sha256(packed) != EXPECTED_PRINCE_SHA256:
        raise ValueError(
            "PRINCE.EXE is not the supported US Prince of Persia 1.3 build; "
            f"SHA-256 is {sha256(packed)}"
        )
    if packed[:2] != b"MZ":
        raise ValueError("PRINCE.EXE is not an MZ executable")

    header = list(struct.unpack_from("<14H", packed, 0))
    packed_header_size = header[4] * 16
    load = bytearray(0x100000)
    load[: len(packed) - packed_header_size] = packed[packed_header_size:]

    stub_segment = header[11]
    stub_offset = stub_segment * 16
    original_ip = u16(load, stub_offset)
    original_cs = u16(load, stub_offset + 2)
    original_sp = u16(load, stub_offset + 8)
    original_ss = u16(load, stub_offset + 10)
    expanded_paragraphs = u16(load, stub_offset + 12)

    # EXEPACK expands backward.  Reverse the stream so the RLE operations can
    # be expressed directly without emulating overlapping segmented moves.
    stream = bytes(reversed(load[:stub_offset]))
    cursor = 0
    while cursor < len(stream) and stream[cursor] == 0xFF:
        cursor += 1

    expanded = bytearray()
    block_count = 0
    while True:
        if cursor + 3 > len(stream):
            raise ValueError("truncated EXEPACK control stream")
        control = stream[cursor]
        count = (stream[cursor + 1] << 8) | stream[cursor + 2]
        cursor += 3
        kind = control & 0xFE
        if kind == 0xB0:
            if cursor >= len(stream):
                raise ValueError("truncated EXEPACK fill block")
            expanded.extend(stream[cursor : cursor + 1] * count)
            cursor += 1
        elif kind == 0xB2:
            if cursor + count > len(stream):
                raise ValueError("truncated EXEPACK literal block")
            expanded.extend(stream[cursor : cursor + count])
            cursor += count
        else:
            raise ValueError(
                f"unsupported EXEPACK control {control:02X} after "
                f"{block_count} blocks"
            )
        block_count += 1
        if control & 1:
            break

    if cursor < len(stream):
        expanded.extend(stream[cursor:])
    image = bytes(reversed(expanded))
    if len(image) > expanded_paragraphs * 16:
        raise ValueError("expanded image is larger than EXEPACK's destination")

    # EXEPACK's e_minalloc includes the paragraphs needed to grow the packed
    # load module to its expanded size.  Once the image is stored unpacked,
    # subtract that growth so DOS reserves exactly the same total paragraphs
    # as it did for the packed original.
    packed_load_bytes = len(packed) - packed_header_size
    packed_load_paragraphs = (packed_load_bytes + 15) // 16
    expansion_growth = expanded_paragraphs - packed_load_paragraphs
    if expansion_growth < 0 or expansion_growth > header[5]:
        raise ValueError("invalid EXEPACK expansion/minimum-allocation relationship")
    unpacked_minimum_allocation = header[5] - expansion_growth

    # EXEPACK groups relocations by 64 KiB pages.
    relocations: list[tuple[int, int]] = []
    cursor = stub_offset + 0x12D
    for page in range(16):
        count = u16(load, cursor)
        cursor += 2
        for _ in range(count):
            relocations.append((u16(load, cursor), page << 12))
            cursor += 2

    needed_header_bytes = 0x1E + len(relocations) * 4
    output_header_bytes = ((needed_header_bytes + 511) // 512) * 512
    output_header = bytearray(output_header_bytes)
    total_bytes = output_header_bytes + len(image)
    pages, final_page_bytes = divmod(total_bytes, 512)
    if final_page_bytes:
        pages += 1

    values = [
        0x5A4D,
        final_page_bytes,
        pages,
        len(relocations),
        output_header_bytes // 16,
        unpacked_minimum_allocation,
        header[6],
        original_ss,
        original_sp,
        0,
        original_ip,
        original_cs,
        0x1E,
        0,
    ]
    struct.pack_into("<14H", output_header, 0, *values)
    for index, (offset, segment) in enumerate(relocations):
        struct.pack_into("<HH", output_header, 0x1E + index * 4, offset, segment)

    unpacked = bytes(output_header) + image
    if sha256(unpacked) != EXPECTED_UNPACKED_SHA256:
        raise ValueError("EXEPACK expansion did not reproduce the verified MZ image")
    return unpacked


def mz_load_module(executable: bytes) -> tuple[int, bytes]:
    if executable[:2] != b"MZ":
        raise ValueError("not an MZ executable")
    header_size = u16(executable, 8) * 16
    if not 28 <= header_size < len(executable):
        raise ValueError(f"invalid MZ header size: {header_size}")
    return header_size, executable[header_size:]


def phase_routine(phase: str) -> bytes:
    if phase == "even":
        phase_instruction = bytes.fromhex("80 66 f2 fe")  # AND byte [BP-0E],FE
    elif phase == "odd":
        phase_instruction = bytes.fromhex("80 4e f2 01")  # OR  byte [BP-0E],01
    elif phase == "snap8":
        phase_instruction = bytes.fromhex("80 66 f2 f8")  # AND byte [BP-0E],F8
    else:
        raise ValueError(f"unknown phase: {phase}")

    # [BP-0A] is draw_mid's normalized blitter number.  Restricting the lock
    # to blitter 10h covers ordinary transparent character/object sprites but
    # preserves the Shadow's deliberately offset OR/XOR drawing pair.
    return (
        bytes.fromhex("83 7e f6 10")  # CMP word [BP-0A],10h
        + bytes.fromhex("75 04")      # JNE restore_original_instruction
        + phase_instruction
        + bytes.fromhex("c4 5e fa")  # LES BX,[BP-06] (displaced original)
        + bytes.fromhex("c3")         # RET
    )


def patch_phase_lock(unpacked: bytes, phase: str) -> tuple[bytes, dict[str, int | str]]:
    header_size, original_module = mz_load_module(unpacked)
    module = bytearray(original_module)

    located_hook = unique_offset(module, HOOK_SIGNATURE, "draw_mid final-X signature")
    if located_hook != HOOK_OFFSET:
        raise ValueError(
            f"draw_mid signature moved to {located_hook:04X}h; expected {HOOK_OFFSET:04X}h"
        )

    if module[CAVE_OFFSET - 3 : CAVE_OFFSET] != bytes.fromhex("ca 08 00"):
        raise ValueError("code cave is not immediately after the expected RETF 8")
    if module[CAVE_OFFSET : CAVE_OFFSET + CAVE_CAPACITY] != bytes(CAVE_CAPACITY):
        raise ValueError("verified linker-padding cave is no longer empty")
    if module[CAVE_OFFSET + CAVE_CAPACITY : CAVE_OFFSET + CAVE_CAPACITY + 4] != bytes.fromhex(
        "33 cc 33 cc"
    ):
        raise ValueError("unexpected bytes after the linker-padding cave")

    routine = phase_routine(phase)
    if len(routine) > CAVE_CAPACITY:
        raise AssertionError("phase hook no longer fits the verified code cave")

    relative = (CAVE_OFFSET - (HOOK_OFFSET + 3)) & 0xFFFF
    call = b"\xE8" + relative.to_bytes(2, "little")
    module[HOOK_OFFSET : HOOK_OFFSET + 3] = call
    module[CAVE_OFFSET : CAVE_OFFSET + len(routine)] = routine

    patched = unpacked[:header_size] + bytes(module)
    metadata: dict[str, int | str] = {
        "phase": phase,
        "mz_header_bytes": header_size,
        "load_module_bytes": len(module),
        "minimum_allocation_paragraphs": u16(unpacked, 0x0A),
        "dos_total_allocation_paragraphs": (len(module) + 15) // 16 + u16(unpacked, 0x0A),
        "hook_offset": f"0000:{HOOK_OFFSET:04X}",
        "code_cave_offset": f"0000:{CAVE_OFFSET:04X}",
        "near_call_displacement": f"{relative:04X}",
        "routine_bytes": len(routine),
        "changed_load_module_bytes": 3 + len(routine),
        "sha256": sha256(patched),
    }
    return patched, metadata


def patch_launcher(launcher: bytes, child_name: bytes) -> bytes:
    if sha256(launcher) != EXPECTED_LAUNCHER_SHA256:
        raise ValueError(
            "CGAPRINC.COM is not launcher version 1.2.0; "
            f"SHA-256 is {sha256(launcher)}"
        )
    if len(child_name) != len(b"PRINCE.EXE"):
        raise ValueError("prototype child filename must be exactly ten DOS characters")
    if launcher.count(b"PRINCE.EXE") != 3:
        raise ValueError("unexpected number of PRINCE.EXE strings in CGAPRINC.COM")
    return launcher.replace(b"PRINCE.EXE", child_name)


def build(prince_path: Path, launcher_path: Path, output_dir: Path) -> Path:
    packed = prince_path.read_bytes()
    launcher = launcher_path.read_bytes()
    unpacked = unpack_exepack(packed)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "prototype": "Prince of Persia 1.3 composite sprite phase lock",
        "source_prince": {
            "file": prince_path.name,
            "bytes": len(packed),
            "sha256": sha256(packed),
        },
        "source_launcher": {
            "file": launcher_path.name,
            "bytes": len(launcher),
            "sha256": sha256(launcher),
        },
        "unpacked_baseline": {
            "bytes": len(unpacked),
            "sha256": sha256(unpacked),
        },
        "outputs": {},
    }

    output_records: dict[str, object] = {}
    for phase, (exe_name, com_name, child_name) in PHASE_OUTPUTS.items():
        patched_exe, patch_metadata = patch_phase_lock(unpacked, phase)
        patched_launcher = patch_launcher(launcher, child_name)
        (output_dir / exe_name).write_bytes(patched_exe)
        (output_dir / com_name).write_bytes(patched_launcher)
        output_records[phase] = {
            "executable": {"file": exe_name, **patch_metadata},
            "launcher": {
                "file": com_name,
                "child": child_name.decode("ascii"),
                "bytes": len(patched_launcher),
                "sha256": sha256(patched_launcher),
            },
        }

    manifest["outputs"] = output_records
    manifest_path = output_dir / "prototype-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build even- and odd-phase Prince 1.3 composite sprite prototypes."
    )
    parser.add_argument(
        "prince",
        nargs="?",
        type=Path,
        default=Path("PRINCE.EXE"),
        help="original packed Prince of Persia 1.3 PRINCE.EXE",
    )
    parser.add_argument(
        "--launcher",
        type=Path,
        default=Path("CGAPRINC.COM"),
        help="CGAPRINC.COM version 1.2.0",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("phase-prototype-output"),
        help="directory for PHEVEN/PHODD1 and their launchers",
    )
    args = parser.parse_args()

    manifest = build(args.prince, args.launcher, args.output_dir)
    print(f"built phase-lock prototype: {manifest}")


if __name__ == "__main__":
    main()
