#!/usr/bin/env python3
"""Build V20V by forwarding the loader's PSP command tail to Prince.

V20V is a deliberately narrow patch over the verified V20U shared-sword
package. It changes no DAT archive and no executable runtime code. The launcher
keeps its DOS EXEC parameter block but changes the command-tail pointer from its
private empty tail at CS:0586 to the parent COM program's PSP tail at CS:0080.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
import zipfile

import build_v20 as v20


ROOT = Path(__file__).resolve().parent
BUILD_ROOT = ROOT / "build"
BASELINE_NAME = (
    "Prince-1.3-New-CGA-V20-Shared-P0-P2-Sword-"
    "Dungeon-Version-B-DAT-Set"
)
BASELINE = BUILD_ROOT / BASELINE_NAME
PACKAGE_NAME = (
    "Prince-1.3-New-CGA-V20V-Command-Tail-Sword-"
    "Dungeon-Version-B-DAT-Set"
)
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"

SOURCE_EXE = "P4KX20.EXE"
SOURCE_COM = "CGA4K20.COM"
OUTPUT_EXE = "P4KX2V.EXE"
OUTPUT_COM = "CGA4K2V.COM"

EXPECTED_BASELINE_MANIFEST_SHA256 = (
    "a31ceecbd81125f39790e8fb5bc66319aef2bd84a818b35b3fceb59f3e085c81"
)
EXPECTED_BASELINE_EXE_SHA256 = (
    "bce926cc781d2725df917d6bb45bbd67e2e46e912845f32eb7a01887f39fde6c"
)
EXPECTED_BASELINE_COM_SHA256 = (
    "f1f013e7841eba67d6d67ee5799d91987ed7c56c09f3701b496f9ebe6fa53ecf"
)

EXEC_PARAMETER_BLOCK_FILE_OFFSET = 0x488
COMMAND_TAIL_OFFSET_WORD_FILE_OFFSET = EXEC_PARAMETER_BLOCK_FILE_OFFSET + 2
EMPTY_COMMAND_TAIL_OFFSET = 0x0586
PSP_COMMAND_TAIL_OFFSET = 0x0080
EXEC_PARAMETER_BLOCK = bytes.fromhex(
    "00 00 86 05 00 00 5c 00 00 00 6c 00 00 00"
)
SEGMENT_INITIALIZER = bytes.fromhex(
    "8c c8 2e a3 8c 05 2e a3 90 05 2e a3 94 05"
)


def sha256_file(path: Path) -> str:
    return v20.sha256_file(path)


def sha256_bytes(data: bytes) -> str:
    return v20.sha256_bytes(data)


def verify_baseline() -> dict[str, object]:
    manifest_path = BASELINE / "PACKAGE-MANIFEST.JSON"
    if not manifest_path.is_file():
        raise ValueError(f"missing V20U package manifest: {manifest_path}")
    if sha256_file(manifest_path) != EXPECTED_BASELINE_MANIFEST_SHA256:
        raise ValueError("unexpected V20U package manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package") != BASELINE_NAME:
        raise ValueError("unexpected V20U package identity")

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("V20U package manifest has no file map")
    for relative, metadata in files.items():
        path = BASELINE / Path(relative)
        if not path.is_file():
            raise ValueError(f"missing V20U input file: {relative}")
        if path.stat().st_size != metadata["bytes"]:
            raise ValueError(f"V20U input size mismatch: {relative}")
        if sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"V20U input hash mismatch: {relative}")

    actual = {
        path.relative_to(BASELINE).as_posix()
        for path in BASELINE.rglob("*")
        if path.is_file()
    }
    expected = set(files) | {"PACKAGE-MANIFEST.JSON", "SHA256SUMS.TXT"}
    if actual != expected:
        raise ValueError("V20U package contents differ from its manifest")
    if sha256_file(BASELINE / SOURCE_EXE) != EXPECTED_BASELINE_EXE_SHA256:
        raise ValueError("unexpected V20U executable")
    if sha256_file(BASELINE / SOURCE_COM) != EXPECTED_BASELINE_COM_SHA256:
        raise ValueError("unexpected V20U launcher")
    return manifest


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_EXE).read_bytes()
    data = v20.replace_exact(source, b"SWORD UNI V20U", b"SWORD CMD V20V")
    changed = [
        offset
        for offset, (before, after) in enumerate(zip(source, data))
        if before != after
    ]
    marker_start = data.index(b"SWORD CMD V20V")
    if any(not marker_start <= offset < marker_start + 14 for offset in changed):
        raise ValueError("V20V executable changed outside its visible marker")
    return data, {
        "file": OUTPUT_EXE,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_EXE,
        "baseline_sha256": EXPECTED_BASELINE_EXE_SHA256,
        "visible_ctrl_v_marker": "SWORD CMD V20V    V1.3",
        "binary_offsets_changed_from_v20u": [
            f"0x{offset:05X}" for offset in changed
        ],
        "runtime_code_byte_identical_to_v20u": True,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_COM).read_bytes()
    block_start = EXEC_PARAMETER_BLOCK_FILE_OFFSET
    block_end = block_start + len(EXEC_PARAMETER_BLOCK)
    if source[block_start:block_end] != EXEC_PARAMETER_BLOCK:
        raise ValueError("V20U EXEC parameter block moved or changed")
    if source.count(SEGMENT_INITIALIZER) != 1:
        raise ValueError("V20U EXEC far-pointer segment initializer changed")

    data = v20.replace_exact(source, b"P4KX20.EXE", b"P4KX2V.EXE", expected=3)
    data = v20.replace_exact(
        data,
        b"SWORD UNIVERSAL V20 ACTIVE ",
        b"CMDTAIL + SWORD V20V ACTIVE",
    )
    mutable = bytearray(data)
    pointer = COMMAND_TAIL_OFFSET_WORD_FILE_OFFSET
    if int.from_bytes(mutable[pointer:pointer + 2], "little") != EMPTY_COMMAND_TAIL_OFFSET:
        raise ValueError("V20U launcher no longer points at its known empty command tail")
    mutable[pointer:pointer + 2] = PSP_COMMAND_TAIL_OFFSET.to_bytes(2, "little")
    data = bytes(mutable)

    if int.from_bytes(data[pointer:pointer + 2], "little") != PSP_COMMAND_TAIL_OFFSET:
        raise ValueError("V20V command-tail pointer patch failed")
    if data.count(SEGMENT_INITIALIZER) != 1:
        raise ValueError("V20V changed the EXEC far-pointer segment initializer")

    allowed: set[int] = {pointer, pointer + 1}
    for old, new in (
        (b"P4KX20.EXE", b"P4KX2V.EXE"),
        (b"SWORD UNIVERSAL V20 ACTIVE ", b"CMDTAIL + SWORD V20V ACTIVE"),
    ):
        start = 0
        while True:
            found = source.find(old, start)
            if found < 0:
                break
            allowed.update(range(found, found + len(old)))
            start = found + len(old)
    changed = {
        offset
        for offset, (before, after) in enumerate(zip(source, data))
        if before != after
    }
    if not changed <= allowed:
        unexpected = sorted(changed - allowed)
        raise ValueError(f"V20V launcher changed unexpected offsets: {unexpected}")

    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_COM,
        "baseline_sha256": EXPECTED_BASELINE_COM_SHA256,
        "child": OUTPUT_EXE,
        "banner": "CMDTAIL + SWORD V20V ACTIVE",
        "exec_parameter_block_file_offset": f"0x{block_start:04X}",
        "command_tail_pointer_before": "CS:0586 (private empty tail)",
        "command_tail_pointer_after": "CS:0080 (parent PSP command tail)",
        "command_tail_offset_word_file_offset": f"0x{pointer:04X}",
        "binary_offsets_changed_from_v20u": [
            f"0x{offset:04X}" for offset in sorted(changed)
        ],
        "cpu": "8086/8088 compatible",
    }


README = """PRINCE OF PERSIA 1.3 - COMMAND-TAIL FORWARDING V20V
======================================================

Run CGA4K2V.COM for normal play.
Run CGA4K2V.COM improved to enable Prince 1.3 cheat/testing commands.

V20V preserves the DOSBox-confirmed V20U shared moving sword, every DAT
archive, and every KID/HP/hurt-splash runtime mapping. The only functional
change is in the .COM loader: its DOS EXEC parameter block now points at the
parent PSP command tail at CS:0080 instead of a private blank tail. Arguments
typed after CGA4K2V.COM are therefore passed unchanged to P4KX2V.EXE.

STATIC VERIFICATION
-------------------

The build verifies the exact V20U package and hashes, asserts the EXEC block
and its runtime segment initialization, limits launcher changes to filenames,
banner, and the two-byte command-tail offset, verifies all DAT archives are
byte-identical, and tests ZIP integrity and contents.

DOSBox confirmation is still required. Check both normal startup and:

    CGA4K2V.COM improved

The latter should enable the normal Prince 1.3 cheat/testing controls.
"""


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging = zip_path.with_name(zip_path.name + ".building")
    if staging.exists():
        staging.unlink()
    fixed_time = (2026, 8, 30, 20, 0, 0)
    try:
        with zipfile.ZipFile(
            staging,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in sorted(source_dir.rglob("*")):
                if not path.is_file():
                    continue
                relative = (
                    Path(PACKAGE_NAME) / path.relative_to(source_dir)
                ).as_posix()
                info = zipfile.ZipInfo(relative, fixed_time)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        staging.replace(zip_path)
    finally:
        if staging.exists():
            staging.unlink()


def main() -> None:
    baseline_manifest = verify_baseline()
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(BASELINE, OUT)

    stale = (
        SOURCE_EXE,
        SOURCE_COM,
        "README.TXT",
        "SWORD-V20-README.TXT",
        "PACKAGE-MANIFEST.JSON",
        "SHA256SUMS.TXT",
    )
    for name in stale:
        path = OUT / name
        if path.exists():
            path.unlink()

    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    (OUT / "README.TXT").write_text(README, encoding="ascii", newline="\r\n")
    (OUT / "LOADER-V20V-README.TXT").write_text(
        README, encoding="ascii", newline="\r\n"
    )

    for baseline_dat in sorted(BASELINE.glob("*.DAT")):
        output_dat = OUT / baseline_dat.name
        if output_dat.read_bytes() != baseline_dat.read_bytes():
            raise ValueError(f"V20V changed DAT archive {baseline_dat.name}")

    verification = f"""Prince of Persia 1.3 V20V Command-Tail Verification
========================================================
BASE PASS    Exact verified V20U package used as input
EXE PASS     Runtime code byte-identical; marker-only {OUTPUT_EXE} SHA-256 {executable_meta['sha256']}
COM PASS     {OUTPUT_COM} launches {OUTPUT_EXE}; SHA-256 {launcher_meta['sha256']}
TAIL PASS    EXEC command-tail pointer changed only from CS:0586 to CS:0080
SEG PASS     Existing runtime CS assignment still supplies the far-pointer segment
DAT PASS     Every DAT archive is byte-identical to DOSBox-confirmed V20U
MAP PASS     All V20U KID, HP, hurt-splash, and shared-sword behavior preserved

STATIC VERIFICATION PASSED.
DOSBox command-line verification is still required.
"""
    (OUT / "LOADER-V20V-VERIFICATION.TXT").write_text(
        verification, encoding="ascii", newline="\r\n"
    )

    manifest = {
        "package": PACKAGE_NAME,
        "version": "V20V",
        "status": "static verification passed; DOSBox confirmation pending",
        "baseline": {
            "version": "V20U",
            "package": baseline_manifest["package"],
            "package_manifest_sha256": EXPECTED_BASELINE_MANIFEST_SHA256,
        },
        "scope": {
            "changed_dat_archives": [],
            "changed_executable_runtime_code": False,
            "changed_launcher_behavior": "forward parent PSP command tail",
            "preserved_v20u_shared_sword": True,
            "preserved_v19l_runtime_mappings": True,
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
    }
    (OUT / "LOADER-V20V-MANIFEST.JSON").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    tools_dir = OUT / "tools"
    if tools_dir.exists():
        shutil.rmtree(tools_dir)
    tools_dir.mkdir()
    shutil.copy2(Path(__file__), tools_dir / Path(__file__).name)

    package_manifest = {
        "package": PACKAGE_NAME,
        "status": manifest["status"],
        "baseline_package": baseline_manifest["package"],
        "files": {},
    }
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name not in {
            "PACKAGE-MANIFEST.JSON",
            "SHA256SUMS.TXT",
        }:
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
            checksums.append(
                f"{sha256_file(path)}  {path.relative_to(OUT).as_posix()}"
            )
    (OUT / "SHA256SUMS.TXT").write_text(
        "\n".join(checksums) + "\n", encoding="ascii"
    )

    make_zip(OUT, ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        if archive.testzip() is not None:
            raise ValueError("V20V ZIP integrity check failed")
        expected_names = {
            (Path(PACKAGE_NAME) / path.relative_to(OUT)).as_posix()
            for path in OUT.rglob("*")
            if path.is_file()
        }
        if set(archive.namelist()) != expected_names:
            raise ValueError("V20V ZIP contents differ from package directory")

    print(
        json.dumps(
            {
                "package_dir": str(OUT),
                "zip": str(ZIP_PATH),
                "zip_bytes": ZIP_PATH.stat().st_size,
                "zip_sha256": sha256_file(ZIP_PATH),
                "executable": executable_meta,
                "launcher": launcher_meta,
                "dat_archives_preserved": len(list(BASELINE.glob("*.DAT"))),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
