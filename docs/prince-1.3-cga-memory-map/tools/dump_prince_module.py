#!/usr/bin/env python3
"""Hex-dump an authenticated, EXEPACK-expanded Prince load-module range."""

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
    parser.add_argument("segment", type=parse_hex)
    parser.add_argument("offset", type=parse_hex)
    parser.add_argument("length", type=parse_hex)
    parser.add_argument("--words", action="store_true")
    args = parser.parse_args()

    _, module = mz_load_module(unpack_exepack(args.executable.read_bytes()))
    start = args.segment * 16 + args.offset
    data = module[start : start + args.length]
    if args.words:
        print(
            " ".join(
                f"{int.from_bytes(data[index:index + 2], 'little'):04X}"
                for index in range(0, len(data) - 1, 2)
            )
        )
        return
    for row in range(0, len(data), 16):
        chunk = data[row : row + 16]
        printable = "".join(chr(value) if 32 <= value < 127 else "." for value in chunk)
        print(f"{args.segment:04X}:{args.offset + row:04X}  {chunk.hex(' '):<47}  {printable}")


if __name__ == "__main__":
    main()
