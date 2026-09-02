#!/usr/bin/env python3
"""Read words, bytes, or C strings from Prince 1.3's verified data segment."""

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


DATA_SEGMENT = 0x1BA3


def parse_hex(value: str) -> int:
    return int(value, 16)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("offset", type=parse_hex)
    parser.add_argument("--count", type=parse_hex, default=0x40)
    parser.add_argument("--format", choices=("hex", "bytes", "words", "string"), default="hex")
    args = parser.parse_args()

    unpacked = unpack_exepack(args.executable.read_bytes())
    _, module = mz_load_module(unpacked)
    start = DATA_SEGMENT * 16 + args.offset
    data = module[start : start + args.count]
    if args.format == "string":
        data = data.split(b"\0", 1)[0]
        print(data.decode("cp437", errors="replace"))
    elif args.format == "bytes":
        print(" ".join(str(value) for value in data))
    elif args.format == "words":
        words = [int.from_bytes(data[index : index + 2], "little") for index in range(0, len(data) - 1, 2)]
        print(" ".join(f"{value:04X}" for value in words))
    else:
        for row in range(0, len(data), 16):
            chunk = data[row : row + 16]
            text = "".join(chr(value) if 32 <= value < 127 else "." for value in chunk)
            print(f"{args.offset + row:04X}  {chunk.hex(' '):<47}  {text}")


if __name__ == "__main__":
    main()
