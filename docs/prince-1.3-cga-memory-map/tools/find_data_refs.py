#!/usr/bin/env python3
"""Find 16-bit instructions that reference a Prince 1.3 data offset.

The executable is read-only.  EXEPACK expansion uses the repository's
authenticated unpacker, and code is decoded in the two known code ranges.
"""

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
    parser.add_argument("offset", type=parse_hex, help="data offset, hexadecimal")
    args = parser.parse_args()

    try:
        from capstone import CS_ARCH_X86, CS_MODE_16, Cs
        from capstone.x86 import X86_OP_MEM
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("capstone is required (available in the project .venv)") from exc

    unpacked = unpack_exepack(args.executable.read_bytes())
    _, module = mz_load_module(unpacked)
    decoder = Cs(CS_ARCH_X86, CS_MODE_16)
    decoder.detail = True
    decoder.skipdata = True

    ranges = ((0x0000, 0, 0x0CC80), (0x0CC8, 0x0CC80, len(module)))
    matches: list[str] = []
    for segment, linear_start, linear_end in ranges:
        for instruction in decoder.disasm(module[linear_start:linear_end], 0):
            if instruction.mnemonic == ".byte":
                continue
            if any(
                operand.type == X86_OP_MEM
                and operand.mem.disp & 0xFFFF == args.offset
                for operand in instruction.operands
            ):
                matches.append(
                    f"{segment:04X}:{instruction.address:04X}  "
                    f"{instruction.bytes.hex(' '):<24} "
                    f"{instruction.mnemonic:<8} {instruction.op_str}"
                )

    print("\n".join(matches) if matches else f"no references to data:{args.offset:04X}")


if __name__ == "__main__":
    main()
