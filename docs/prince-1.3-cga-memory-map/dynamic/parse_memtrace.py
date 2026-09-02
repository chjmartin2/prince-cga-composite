#!/usr/bin/env python3
"""Decode MEMTRACE.COM's MTRACE.BIN into CSV and a compact text summary."""

from __future__ import annotations

import argparse
import csv
import struct
from pathlib import Path


HEADER = struct.Struct("<8s12H")
RECORD_V1 = struct.Struct("<IBB9HBB3H")
RECORD_V2 = struct.Struct("<IBB9HBB3H16s")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()

    raw = args.trace.read_bytes()
    if len(raw) < HEADER.size:
        raise SystemExit("trace is shorter than its 32-byte header")
    values = HEADER.unpack_from(raw)
    magic = values[0]
    if magic != b"P13MTRC1":
        raise SystemExit(f"unexpected trace magic {magic!r}")
    version, record_size, keep_paras = values[1:4]
    base_total, base_largest, base_count = values[7:10]
    record_struct = {1: RECORD_V1, 2: RECORD_V2}.get(version)
    if record_struct is None or record_size != record_struct.size:
        raise SystemExit(
            f"unsupported version/record size: {version}/{record_size}"
        )
    payload = raw[HEADER.size :]
    if len(payload) % record_size:
        raise SystemExit("trace ends with a partial record")

    names = [
        "ticks",
        "op",
        "cf",
        "in_bx",
        "in_es",
        "in_owner",
        "out_ax",
        "out_bx",
        "pre_free",
        "pre_largest",
        "post_free",
        "post_largest",
        "pre_mcb_count",
        "post_mcb_count",
        "out_owner",
        "caller_cs",
        "sequence",
    ]
    if version >= 2:
        names.append("name")
    rows = [dict(zip(names, record_struct.unpack_from(payload, off)))
            for off in range(0, len(payload), record_size)]
    if version >= 2:
        for row in rows:
            row["name"] = row["name"].split(b"\0", 1)[0].decode(
                "cp437", errors="replace"
            )

    print(
        f"format={version} records={len(rows)} wrapper={keep_paras} paras "
        f"({keep_paras * 16} bytes) base_free={base_total} paras "
        f"base_largest={base_largest} paras base_mcbs={base_count}"
    )
    counts = {}
    for row in rows:
        counts[row["op"]] = counts.get(row["op"], 0) + 1
    labels = {
        0x3D: "open",
        0x3E: "close",
        0x48: "alloc",
        0x49: "free",
        0x4A: "resize",
        0xF0: "start",
        0xFF: "end",
    }
    print("events=" + ", ".join(
        f"{labels.get(op, hex(op))}:{count}" for op, count in sorted(counts.items())
    ))
    ordinary = [row for row in rows if row["op"] in (0x48, 0x49, 0x4A)]
    failed = [row for row in ordinary if row["cf"]]
    if ordinary:
        min_total = min(row["post_free"] for row in ordinary)
        min_largest = min(row["post_largest"] for row in ordinary)
        max_mcbs = max(row["post_mcb_count"] for row in ordinary)
        print(
            f"minimum_post_free={min_total} paras ({min_total * 16} bytes) "
            f"minimum_post_largest={min_largest} paras "
            f"maximum_mcb_count={max_mcbs} failures={len(failed)}"
        )

    csv_path = args.csv or args.trace.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=names, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            cooked = row.copy()
            cooked["op"] = labels.get(row["op"], f"0x{row['op']:02X}")
            writer.writerow(cooked)
    print(f"csv={csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
