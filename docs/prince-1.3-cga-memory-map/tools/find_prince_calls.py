#!/usr/bin/env python3
"""Find direct calls to a verified Prince 1.3 segmented address."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[3]
PHASE_TOOLS = (
    ROOT
    / "runtime"
    / "source_work"
    / "v13"
    / "Prince-Kid-VGA-Exhaustive-Phase-Prototype-v13"
    / "tools"
)
sys.path.insert(0, str(PHASE_TOOLS))

from make_phase_prototype import mz_load_module, unpack_exepack  # noqa: E402


def parse_hex(value: str) -> int:
    return int(value, 16)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("target_segment", type=parse_hex)
    parser.add_argument("target_offset", type=parse_hex)
    args = parser.parse_args()

    try:
        from capstone import CS_ARCH_X86, CS_MODE_16, Cs
        from capstone.x86 import X86_OP_IMM
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("capstone is required (available in the project .venv)") from exc

    unpacked = unpack_exepack(args.executable.read_bytes())
    _, module = mz_load_module(unpacked)
    decoder = Cs(CS_ARCH_X86, CS_MODE_16)
    decoder.detail = True
    decoder.skipdata = True

    # The executable has the main code at module segment 0000 and the C
    # runtime/data-adjacent code at 0CC8.  Decode each independently so near
    # branch targets remain meaningful.
    ranges = ((0x0000, 0, 0x0CC80), (0x0CC8, 0x0CC80, len(module)))
    matches: list[str] = []
    for segment, linear_start, linear_end in ranges:
        code = module[linear_start:linear_end]
        for instruction in decoder.disasm(code, 0):
            if instruction.mnemonic not in {"call", "lcall"}:
                continue
            operands = instruction.operands
            matched = False
            if instruction.mnemonic == "call" and segment == args.target_segment:
                matched = (
                    len(operands) == 1
                    and operands[0].type == X86_OP_IMM
                    and operands[0].imm & 0xFFFF == args.target_offset
                )
            elif instruction.bytes[:1] == b"\x9a" and len(instruction.bytes) == 5:
                offset = int.from_bytes(instruction.bytes[1:3], "little")
                target_segment = int.from_bytes(instruction.bytes[3:5], "little")
                matched = (
                    target_segment == args.target_segment
                    and offset == args.target_offset
                )
            if matched:
                matches.append(
                    f"{segment:04X}:{instruction.address:04X}  "
                    f"{instruction.bytes.hex(' '):<16} {instruction.mnemonic} "
                    f"{instruction.op_str}"
                )

    if matches:
        print("\n".join(matches))
    else:
        print(f"no direct calls to {args.target_segment:04X}:{args.target_offset:04X}")


if __name__ == "__main__":
    main()
