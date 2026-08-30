#!/usr/bin/env python3
"""Build the V15C live-native-table Prince of Persia test package.

V15C is a deliberately narrow runtime integration change over V15B:

* keep PHASE.DAT loaded in Prince's native chtab slot 3;
* have the draw selector read slot 3 directly, as working V14 did;
* remove V15B's cached-pointer/header-guard handoff and its slot detachment;
* retain the exact V14 KID artwork and the separate PHASE.DAT archive.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "work" / "Prince-1.3-New-CGA-Phase-Aware-V15B-Native-Table-Dungeon-Version-B-DAT-Set"
V14 = ROOT / "work_v14" / "Prince-1.3-New-CGA-Phase-Aware-V14-Jumps-Dungeon-Version-B-DAT-Set"
BUILD_ROOT = ROOT / "build"
PACKAGE_NAME = "Prince-1.3-New-CGA-Phase-Aware-V15C-Live-Native-Table-Dungeon-Version-B-DAT-Set"
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"

V15B_EXE_SHA256 = "e741c344a849cd4cecc6503c4bc004af7933e4b47bc0c768a424685c5593fb5a"
V15B_COM_SHA256 = "199f7d5f1d449d9654d93684bf67abbaa5066f85e078d508742a8fc6bccd86a4"
PHASE_SHA256 = "4552e0d15448b54823e1d4bd58c8813675e893df059eb00fecf7cf10354546c0"
KID_SHA256 = "2b5a930ac53121742f26541aea710348c0a69945e98a5de8f1cb503c091d62b4"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_exact(data: bytes, old: bytes, new: bytes, expected: int = 1) -> bytes:
    if len(old) != len(new):
        raise ValueError("binary replacement must preserve length")
    count = data.count(old)
    if count != expected:
        raise ValueError(f"expected {expected} occurrence(s) of {old!r}, found {count}")
    return data.replace(old, new)


def parse_dat(path: Path) -> dict[int, bytes]:
    data = path.read_bytes()
    table_offset = int.from_bytes(data[0:4], "little")
    table_size = int.from_bytes(data[4:6], "little")
    if table_offset + table_size != len(data):
        raise ValueError(f"bad DAT table bounds: {path}")
    count = int.from_bytes(data[table_offset:table_offset + 2], "little")
    if table_size != 2 + count * 8:
        raise ValueError(f"bad DAT table size: {path}")
    resources: dict[int, bytes] = {}
    for index in range(count):
        pos = table_offset + 2 + index * 8
        resource_id = int.from_bytes(data[pos:pos + 2], "little")
        offset = int.from_bytes(data[pos + 2:pos + 6], "little")
        size = int.from_bytes(data[pos + 6:pos + 8], "little")
        record = data[offset:offset + size]
        if len(record) != size:
            raise ValueError(f"truncated DAT resource {resource_id}: {path}")
        resources[resource_id] = record
    return resources


def patch_executable() -> tuple[bytes, dict[str, int | str | bool]]:
    source = SRC / "P4KX5B.EXE"
    data = source.read_bytes()
    if sha256_bytes(data) != V15B_EXE_SHA256:
        raise ValueError("unexpected V15B executable")

    # V15B: mov si,[cached_phase_table].
    # V15C: mov si,[chtab slot 3] -- exactly the native live table V14 used.
    data = replace_exact(data, bytes.fromhex("8b36e278"), bytes.fromhex("8b363a45"))

    # Once the native far pointer is non-null, hand it to Prince exactly as V14 did.
    # The PHASE.DAT records are already validated byte-for-byte during the build.
    guard_start = 0x23C39
    guard_end = 0x23C74
    expected_guard = bytes.fromhex(
        "8ec28bdf26833f00743f26813f0001773826837f02007431"
        "26817f020001772926807f04017722268a47058ae024703c30"
        "75168ac4240f3c04770e"
    )
    if data[guard_start:guard_end] != expected_guard:
        raise ValueError("unexpected V15B selector guard block")
    displacement = guard_end - (guard_start + 2)
    data = data[:guard_start] + bytes((0xEB, displacement)) + b"\x90" * (guard_end - guard_start - 2) + data[guard_end:]

    # Do not detach the successfully loaded native table from chtab slot 3.
    clear_slot = bytes.fromhex("c7063a450000")
    data = replace_exact(data, clear_slot, b"\x90" * len(clear_slot))

    # Do not let V15B's now-unused cached pointer suppress a later native reload.
    # The ordinary slot-3 null check remains, so this has V14's load-once-unless-
    # freed behavior across level/title/cinematic transitions.
    cached_gate_start = 0x23CA2
    cached_gate = bytes.fromhex("a1e2780bc07403e92b00")
    if data[cached_gate_start:cached_gate_start + len(cached_gate)] != cached_gate:
        raise ValueError("unexpected V15B cached-pointer loader gate")
    data = (
        data[:cached_gate_start]
        + b"\x90" * len(cached_gate)
        + data[cached_gate_start + len(cached_gate):]
    )

    # Match the original game's lowercase DAT filename convention.
    data = replace_exact(data, b"PHASE.DAT\x00", b"phase.dat\x00")
    data = replace_exact(data, b"KID TABLE V15B", b"KID TABLE V15C")

    # MZ and hook invariants.
    if data[:2] != b"MZ" or len(data) != 146708:
        raise ValueError("V15C MZ size/header changed unexpectedly")
    header_paragraphs = int.from_bytes(data[8:10], "little")
    if header_paragraphs != 0xA0:
        raise ValueError("unexpected MZ header size")
    draw_hook = 0xA00 + 0xF113
    load_hook = 0xA00 + 0x0F60
    if data[draw_hook:draw_hook + 5] != bytes.fromhex("9a00001c23"):
        raise ValueError("draw hook changed")
    if data[load_hook:load_hook + 5] != bytes.fromhex("9ad0001c23"):
        raise ValueError("load hook changed")
    if data[0x23C1D:0x23C21] != bytes.fromhex("8b363a45"):
        raise ValueError("live-slot selector patch missing")
    if data[0x23CD1:0x23CD7] != b"\x90" * 6:
        raise ValueError("slot detachment still present")
    if data[0x23CA2:0x23CAC] != b"\x90" * 10:
        raise ValueError("cached-pointer loader gate still present")

    return data, {
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "draw_hook": "0000:B594 via trampoline 0000:F113",
        "load_hook": "0000:0F60",
        "high_code": "231C:0000",
        "phase_table_source": "live native chtab slot 3 at DS:453A",
        "slot_detached": False,
        "cached_phase_pointer_used_for_draw": False,
        "cached_phase_pointer_gates_reload": False,
        "v14_selector_semantics": True,
    }


def patch_launcher() -> tuple[bytes, dict[str, int | str]]:
    source = SRC / "CGA4K5B.COM"
    data = source.read_bytes()
    if sha256_bytes(data) != V15B_COM_SHA256:
        raise ValueError("unexpected V15B launcher")
    data = data.replace(b"P4KX5B.EXE", b"P4KX5C.EXE")
    data = data.replace(b"V15B", b"V15C")
    if data.count(b"P4KX5C.EXE") != 3:
        raise ValueError("launcher child-name patch incomplete")
    if b"KID PHASE TABLE V15C ACTIVE" not in data:
        raise ValueError("launcher banner patch incomplete")
    return data, {
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "child": "P4KX5C.EXE",
        "banner": "KID PHASE TABLE V15C ACTIVE",
    }


README = """PRINCE OF PERSIA 1.3 - LIVE NATIVE PHASE TABLE V15C
===================================================

PURPOSE
-------

V15C fixes the V15B runtime integration failure in which the game ran safely
but silently used only ordinary KID graphics. V15B detached the phase table
from Prince's native chtab slot and made the draw selector depend on a separate
cached near pointer plus new header guards. That handoff never activated during
the DOS test and the guarded fallback hid the failure.

V15C keeps PHASE.DAT in Prince's live native chtab slot 3 and reads that table
directly during drawing, matching the proven V14 selector architecture. It does
not detach the table, does not copy it, and does not use a second cached table
pointer. PHASE.DAT remains a separate standard Prince DAT archive.

The artwork is unchanged from V14/V15B:

  right / P2        keys   0..64
  left / P0         keys  65..129
  left / P2         keys 130..194

INSTALLATION
------------

1. Use a clean copy of the intended New-CGA Prince 1.3 directory.
2. Copy CGA4K5C.COM, P4KX5C.EXE, KID.DAT, and PHASE.DAT into it.
3. Keep all four files together. Do not mix V15A or V15B executables/launchers.
4. Run CGA4K5C.COM. Do not run P4KX5C.EXE directly.
5. Press Ctrl-V in game and confirm:

       KID TABLE V15C    V1.3

   The launcher must print:

       KID PHASE TABLE V15C ACTIVE

PHASE.DAT must be exactly 40,785 bytes with SHA-256:

  4552e0d15448b54823e1d4bd58c8813675e893df059eb00fecf7cf10354546c0

TEST ROUTE
----------

First, stand/run in both directions at adjacent X positions. The Prince should
retain the intended colors as screen-X parity changes. Then test stationary
turn, complete run-turn, standing jump, running jump, falling and landing.
Reproduce the earlier failure route by moving right, leaving the ledge, falling,
landing, and continuing to move.

V15C is a runtime test build. Its binary structure and all sidecar resources
have been verified statically, but the DOS behavior must be confirmed in the
actual emulator configuration.

ARCHITECTURE
------------

  storage             separate standard PHASE.DAT
  loading             Prince's own load_chtab into slot 3
  table lifetime      live in native slot 3
  draw lookup         direct native table lookup, matching V14
  drawing             Prince's original decompressor/flip/draw path
  runtime transforms  none
  custom DOS I/O      none
  CPU                  8086/8088 compatible

Dungeon Version B, palace graphics, all other DAT files, and the 195 phase
resources are byte-identical to the V15B package.
"""


def make_zip(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    fixed_time = (2026, 8, 24, 20, 0, 0)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(PACKAGE_NAME) / path.relative_to(source_dir)
            info = zipfile.ZipInfo(relative.as_posix(), fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> None:
    if not SRC.is_dir() or not V14.is_dir():
        raise SystemExit("materialized V15B and V14 source packages are required")

    if OUT.exists():
        shutil.rmtree(OUT)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC, OUT)

    for stale in ("P4KX5B.EXE", "CGA4K5B.COM", "KID-V15B-README.TXT", "KID-V15B-VERIFICATION.TXT", "KID-V15B-MANIFEST.JSON"):
        path = OUT / stale
        if path.exists():
            path.unlink()

    exe, exe_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / "P4KX5C.EXE").write_bytes(exe)
    (OUT / "CGA4K5C.COM").write_bytes(launcher)

    phase_resources = parse_dat(OUT / "PHASE.DAT")
    v14_resources = parse_dat(V14 / "KID.DAT")
    expected_ids = set(range(1000, 1196))
    if set(phase_resources) != expected_ids:
        raise ValueError("PHASE.DAT does not contain exactly resources 1000..1195")
    mismatches = [resource_id for resource_id in sorted(expected_ids) if phase_resources[resource_id] != v14_resources[resource_id]]
    if mismatches:
        raise ValueError(f"PHASE.DAT differs from V14 resources: {mismatches[:8]}")
    if sha256_file(OUT / "PHASE.DAT") != PHASE_SHA256:
        raise ValueError("PHASE.DAT hash changed")
    if sha256_file(OUT / "KID.DAT") != KID_SHA256:
        raise ValueError("KID.DAT hash changed")

    image_guard_failures = []
    for resource_id in range(1001, 1196):
        data = phase_resources[resource_id][1:]  # skip Prince DAT checksum byte
        height, width = struct.unpack_from("<HH", data, 0)
        marker = data[4]
        image_type = data[5]
        valid = (
            0 < height <= 256
            and 0 < width <= 256
            and marker <= 1
            and (image_type & 0x70) == 0x30
            and (image_type & 0x0F) <= 4
        )
        if not valid:
            image_guard_failures.append(resource_id)
    if image_guard_failures:
        raise ValueError(f"invalid phase image headers: {image_guard_failures}")

    (OUT / "README.TXT").write_text(README, encoding="ascii", newline="\r\n")
    (OUT / "KID-V15C-README.TXT").write_text(README, encoding="ascii", newline="\r\n")

    manifest = {
        "package": PACKAGE_NAME,
        "status": "experimental V15C runtime integration build; static verification passed; DOS runtime verification pending",
        "fix": "keep PHASE.DAT in live native chtab slot 3 and draw from that slot directly",
        "baseline": "V15B version 5",
        "visual_reference": "V14; all 196 resources 1000..1195 are byte-identical",
        "runtime_architecture": {
            "sidecar": "PHASE.DAT",
            "sidecar_is_standard_prince_dat": True,
            "loader": "Prince load_chtab",
            "native_slot": 3,
            "native_slot_kept_live": True,
            "native_slot_detached": False,
            "cached_table_pointer_used_for_draw": False,
            "selector": "direct slot-3 lookup matching V14",
            "runtime_transform": False,
            "custom_dos_io": False,
        },
        "executable": exe_meta,
        "launcher": launcher_meta,
        "kid_dat": {
            "bytes": (OUT / "KID.DAT").stat().st_size,
            "sha256": sha256_file(OUT / "KID.DAT"),
        },
        "phase_dat": {
            "bytes": (OUT / "PHASE.DAT").stat().st_size,
            "sha256": sha256_file(OUT / "PHASE.DAT"),
            "resource_count": len(phase_resources),
            "resource_id_range": "1000..1195",
            "all_resources_byte_identical_to_v14": True,
            "image_resources": 195,
            "all_image_headers_valid": True,
        },
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (OUT / "KID-V15C-MANIFEST.JSON").write_text(manifest_text, encoding="utf-8")

    verification = f"""Prince of Persia 1.3 V15C Live Native-Table Verification
==========================================================
EXE PASS   P4KX5C.EXE: {exe_meta['bytes']} bytes, SHA-256 {exe_meta['sha256']}
HOOK PASS  Draw and load hooks still target high segment 231C
LIVE PASS  Selector reads Prince chtab slot 3 directly at DS:453A
KEEP PASS  Native slot 3 is not detached or cleared after PHASE.DAT loads
DRAW PASS  Non-null native pointers follow V14's direct handoff to Prince
COM PASS   CGA4K5C.COM: child=P4KX5C.EXE, SHA-256 {launcher_meta['sha256']}
DAT PASS   KID.DAT: SHA-256 {sha256_file(OUT / 'KID.DAT')}
SIDE PASS  PHASE.DAT: 196/196 exact V14 resources, SHA-256 {sha256_file(OUT / 'PHASE.DAT')}
IMAGE PASS 195/195 phase image headers are structurally valid

STATIC VERIFICATION PASSED.
DOS runtime verification is still required.
"""
    (OUT / "KID-V15C-VERIFICATION.TXT").write_text(verification, encoding="ascii", newline="\r\n")

    tools_dir = OUT / "tools"
    tools_dir.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), tools_dir / Path(__file__).name)

    package_manifest = {
        **manifest,
        "files": {},
    }
    # PACKAGE-MANIFEST deliberately excludes itself and SHA256SUMS to avoid recursive hashes.
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name not in {"PACKAGE-MANIFEST.JSON", "SHA256SUMS.TXT"}:
            rel = path.relative_to(OUT).as_posix()
            package_manifest["files"][rel] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    (OUT / "PACKAGE-MANIFEST.JSON").write_text(json.dumps(package_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    checksum_lines = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.TXT":
            checksum_lines.append(f"{sha256_file(path)}  {path.relative_to(OUT).as_posix()}")
    (OUT / "SHA256SUMS.TXT").write_text("\n".join(checksum_lines) + "\n", encoding="ascii")

    make_zip(OUT, ZIP_PATH)
    print(json.dumps({
        "package_dir": str(OUT),
        "zip": str(ZIP_PATH),
        "zip_bytes": ZIP_PATH.stat().st_size,
        "zip_sha256": sha256_file(ZIP_PATH),
        "exe": exe_meta,
        "launcher": launcher_meta,
    }, indent=2))


if __name__ == "__main__":
    main()
