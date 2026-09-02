#!/usr/bin/env python3
"""Disassemble verified Prince 1.3 load-module ranges for memory research.

This utility never writes or modifies the supplied executable.  It delegates
EXEPACK expansion to the repository's already authenticated unpacker and emits
16-bit 8086 disassembly to standard output.
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
    parser.add_argument("segment", type=parse_hex, help="load-module segment, hexadecimal")
    parser.add_argument("offset", type=parse_hex, help="segment offset, hexadecimal")
    parser.add_argument("length", type=parse_hex, help="byte count, hexadecimal")
    args = parser.parse_args()

    try:
        from capstone import CS_ARCH_X86, CS_MODE_16, Cs
    except ImportError as exc:  # pragma: no cover - environment diagnostic
        raise SystemExit("capstone is required (available in the project .venv)") from exc

    unpacked = unpack_exepack(args.executable.read_bytes())
    _, module = mz_load_module(unpacked)
    linear = args.segment * 16 + args.offset
    end = linear + args.length
    if linear < 0 or end > len(module):
        raise SystemExit(
            f"range {linear:#x}..{end:#x} is outside the {len(module):#x}-byte module"
        )

    decoder = Cs(CS_ARCH_X86, CS_MODE_16)
    for instruction in decoder.disasm(module[linear:end], args.offset):
        encoded = instruction.bytes.hex(" ")
        print(
            f"{args.segment:04X}:{instruction.address:04X}  "
            f"{encoded:<24} {instruction.mnemonic:<8} {instruction.op_str}"
        )


if __name__ == "__main__":
    main()
