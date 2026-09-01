#!/usr/bin/env python3
"""Build V20Z with a New-CGA red pattern for mono color 12.

V20Y restored the chomper-blood masks, but DOSBox testing showed that the
original CGA driver's solid palette-2 mapping is the Mode-6 bit pattern AA,
which decodes as grey with yellow transition artifacts.  V20Z changes only
mono color 12's four scanline bytes from AA to the mask-aware C4 pattern.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
import zipfile

import build_v20y as v20y


ROOT = Path(__file__).resolve().parent
BUILD_ROOT = ROOT / "build"
BASELINE_NAME = "Prince-1.3-New-CGA-V20Y-Chomper-Blood-Stencils"
BASELINE = BUILD_ROOT / BASELINE_NAME
PACKAGE_NAME = "Prince-1.3-New-CGA-V20Z-Chomper-Blood-NTSC-Pattern"
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"

SOURCE_EXE = "P4KX2Y.EXE"
SOURCE_COM = "CGA4K2Y.COM"
OUTPUT_EXE = "P4KX2Z.EXE"
OUTPUT_COM = "CGA4K2Z.COM"

EXPECTED_BASELINE_MANIFEST_SHA256 = (
    "bc20ab8559449686eb7eb38a1491dd23afb0bc428fde2c48b5043923ac39c9e7"
)
EXPECTED_BASELINE_EXE_SHA256 = (
    "7c557c3c844e44f01bcbb26ddc13f7ed963acd201fc4961549965a81b6bcf9dc"
)
EXPECTED_BASELINE_COM_SHA256 = (
    "782c79cbc58ca22a94f5d51432883ab768fd8f439b686e89d4ec85b560c4f3d2"
)
EXPECTED_CDUNGEON_SHA256 = (
    "b5459688c0d4618208fe6a3d233b0eaea18f51153b861195940fe940ea4d8536"
)
EXPECTED_OUTPUT_EXE_SHA256 = (
    "aa91a9547381e052d5f6fbd7bccbf1efd09f19548ce04ea3d5d9a772465eda8d"
)
EXPECTED_OUTPUT_COM_SHA256 = (
    "dc9df42f9ce1d073b187a787dbd49cc780417c079784f2431c4032411f8a0ce2"
)

MZ_HEADER_BYTES = 0xA00
DGROUP_LOAD_OFFSET = 0x1BA30
MONO_PATTERN_TABLE_DGROUP_OFFSET = 0x2A14
MONO_PATTERN_TABLE_FILE_OFFSET = (
    MZ_HEADER_BYTES + DGROUP_LOAD_OFFSET + MONO_PATTERN_TABLE_DGROUP_OFFSET
)
COLOR_12_FILE_OFFSET = MONO_PATTERN_TABLE_FILE_OFFSET + 12 * 4
ORIGINAL_MONO_TABLE = bytes.fromhex(
    "00000000 66996699 eebbeebb dd77dd77"
    "33cc33cc 44114411 88228822 55aa55aa"
    "66666666 55555555 aaffaaff bbbbbbbb"
    "aaaaaaaa 55ff55ff 77777777 ffffffff"
)
ORIGINAL_COLOR_12 = bytes.fromhex("aa aa aa aa")
NTSC_COLOR_12 = bytes.fromhex("c4 c4 c4 c4")


def sha256_bytes(data: bytes) -> str:
    return v20y.sha256_bytes(data)


def sha256_file(path: Path) -> str:
    return v20y.sha256_file(path)


def verify_hash(path: Path, expected: str, label: str) -> None:
    v20y.verify_hash(path, expected, label)


def verify_baseline() -> dict[str, object]:
    manifest_path = BASELINE / "PACKAGE-MANIFEST.JSON"
    verify_hash(manifest_path, EXPECTED_BASELINE_MANIFEST_SHA256, "V20Y package manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package") != BASELINE_NAME:
        raise ValueError("unexpected V20Y package identity")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("V20Y package manifest has no file map")
    for relative, metadata in files.items():
        path = BASELINE / Path(relative)
        if not path.is_file():
            raise ValueError(f"missing V20Y input file: {relative}")
        if path.stat().st_size != metadata["bytes"]:
            raise ValueError(f"V20Y input size mismatch: {relative}")
        if sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"V20Y input hash mismatch: {relative}")
    actual = {
        path.relative_to(BASELINE).as_posix()
        for path in BASELINE.rglob("*")
        if path.is_file()
    }
    expected = set(files) | {"PACKAGE-MANIFEST.JSON", "SHA256SUMS.TXT"}
    if actual != expected:
        raise ValueError("V20Y package contents differ from its manifest")
    verify_hash(BASELINE / SOURCE_EXE, EXPECTED_BASELINE_EXE_SHA256, "V20Y executable")
    verify_hash(BASELINE / SOURCE_COM, EXPECTED_BASELINE_COM_SHA256, "V20Y launcher")
    verify_hash(BASELINE / "CDUNGEON.DAT", EXPECTED_CDUNGEON_SHA256, "V20Y CDUNGEON")
    return manifest


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_EXE).read_bytes()
    data = v20y.v20x.v20w.v20v.v20.replace_exact(
        source, b"BLOOD FIX V20Y", b"BLOOD RED V20Z"
    )
    if (
        source[MONO_PATTERN_TABLE_FILE_OFFSET:MONO_PATTERN_TABLE_FILE_OFFSET + 64]
        != ORIGINAL_MONO_TABLE
    ):
        raise ValueError("V20Y CGA mono-color table changed unexpectedly")
    if source[COLOR_12_FILE_OFFSET:COLOR_12_FILE_OFFSET + 4] != ORIGINAL_COLOR_12:
        raise ValueError("V20Y mono color 12 is not the expected AA pattern")
    patched = bytearray(data)
    patched[COLOR_12_FILE_OFFSET:COLOR_12_FILE_OFFSET + 4] = NTSC_COLOR_12
    data = bytes(patched)

    allowed = set(range(COLOR_12_FILE_OFFSET, COLOR_12_FILE_OFFSET + 4))
    marker_start = data.index(b"BLOOD RED V20Z")
    allowed.update(range(marker_start, marker_start + 14))
    changed = {
        offset for offset, (before, after) in enumerate(zip(source, data)) if before != after
    }
    if not changed <= allowed or not set(range(COLOR_12_FILE_OFFSET, COLOR_12_FILE_OFFSET + 4)) <= changed:
        raise ValueError("V20Z executable changed outside its marker and color table")
    if sha256_bytes(data) != EXPECTED_OUTPUT_EXE_SHA256:
        raise ValueError("V20Z executable hash changed unexpectedly")
    return data, {
        "file": OUTPUT_EXE,
        "bytes": len(data),
        "sha256": EXPECTED_OUTPUT_EXE_SHA256,
        "baseline_file": SOURCE_EXE,
        "baseline_sha256": EXPECTED_BASELINE_EXE_SHA256,
        "visible_ctrl_v_marker": "BLOOD RED V20Z    V1.3",
        "cga_mono_color_12_file_offset": f"0x{COLOR_12_FILE_OFFSET:05X}",
        "old_scanline_patterns": ["10101010"] * 4,
        "new_scanline_patterns": ["11000100"] * 4,
        "other_executable_runtime_bytes_unchanged": True,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_COM).read_bytes()
    replace = v20y.v20x.v20w.v20v.v20.replace_exact
    data = replace(source, b"P4KX2Y.EXE", b"P4KX2Z.EXE", expected=3)
    data = replace(
        data,
        b"BLOOD FIX + CMD V20Y ACTIVE",
        b"BLOOD RED + CMD V20Z ACTIVE",
    )
    pointer = v20y.v20x.v20w.v20v.COMMAND_TAIL_OFFSET_WORD_FILE_OFFSET
    if int.from_bytes(data[pointer:pointer + 2], "little") != v20y.v20x.v20w.v20v.PSP_COMMAND_TAIL_OFFSET:
        raise ValueError("V20Z no longer forwards the parent PSP command tail")
    if sha256_bytes(data) != EXPECTED_OUTPUT_COM_SHA256:
        raise ValueError("V20Z launcher hash changed unexpectedly")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": EXPECTED_OUTPUT_COM_SHA256,
        "baseline_file": SOURCE_COM,
        "baseline_sha256": EXPECTED_BASELINE_COM_SHA256,
        "child": OUTPUT_EXE,
        "banner": "BLOOD RED + CMD V20Z ACTIVE",
        "command_tail_pointer": "CS:0080 (parent PSP command tail)",
        "cpu": "8086/8088 compatible",
    }


README = """PRINCE OF PERSIA 1.3 - CHOMPER BLOOD NTSC PATTERN V20Z
===========================================================

Run CGA4K2Z.COM for normal play.
Run CGA4K2Z.COM improved to enable Prince 1.3 cheat/testing commands.

V20Z preserves V20Y's exact original chomper-blood stencils and changes the
CGA mono renderer's color-12 pattern from AA (10101010) to C4 (11000100) on
all four scanline phases. AA is neutral grey in 640x200 composite mode and its
transitions produced a small yellow trace on the floor.

The replacement was selected by decoding all 256 possible byte patterns over
the ten masks at their real offsets on all five lower/front blade frames. C4
keeps 1100 at the narrow foreground blade, while its trailing 0100 darkens the
wider rear/floor pass. Predicted New-CGA means are RGB 146,65,78 on the blade
and 181,56,51 on the rear/floor pass.

The same color-12 entry supplies red potion bubbles, so those should also become
red instead of grey. Every DAT archive and every other executable byte remains
identical to V20Y.

TEST
----

On Level 3, go left from the starting room and let the nearby chomper kill
Prince. Confirm visible red on the moving blade and a darker red spill near the
floor, without the former isolated yellow trace.
"""


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging = zip_path.with_name(zip_path.name + ".building")
    if staging.exists():
        staging.unlink()
    fixed_time = (2026, 8, 31, 22, 0, 0)
    try:
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source_dir.rglob("*")):
                if not path.is_file():
                    continue
                relative = (Path(PACKAGE_NAME) / path.relative_to(source_dir)).as_posix()
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
    for name in (
        SOURCE_EXE,
        SOURCE_COM,
        "README.TXT",
        "PACKAGE-MANIFEST.JSON",
        "SHA256SUMS.TXT",
    ):
        path = OUT / name
        if path.exists():
            path.unlink()

    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    (OUT / "README.TXT").write_text(README, encoding="ascii", newline="\r\n")
    (OUT / "CHOMPER-BLOOD-V20Z-README.TXT").write_text(
        README, encoding="ascii", newline="\r\n"
    )

    for baseline_dat in sorted(BASELINE.glob("*.DAT")):
        if (OUT / baseline_dat.name).read_bytes() != baseline_dat.read_bytes():
            raise ValueError(f"V20Z changed DAT archive {baseline_dat.name}")

    verification = f"""Prince of Persia 1.3 V20Z Chomper Blood Verification
=========================================================
BASE PASS    Exact verified V20Y package used as input
EXE PASS     Only marker and color-12 table changed; SHA-256 {EXPECTED_OUTPUT_EXE_SHA256}
COM PASS     {OUTPUT_COM} preserves command-tail forwarding; SHA-256 {EXPECTED_OUTPUT_COM_SHA256}
MASK PASS    Original one-bit resources 1314-1323 remain byte-identical
COLOR PASS   Four color-12 rows changed from AA to mask-aware C4
BLADE PASS   Predicted in-use New-CGA mean RGB 146,65,78
FLOOR PASS   Predicted in-use New-CGA mean RGB 181,56,51
DAT PASS     All 32 DAT archives are byte-identical to V20Y
KEEP PASS    Every other executable runtime byte preserves V20Y

STATIC VERIFICATION PASSED.
DOSBox chomper-blood visual confirmation is still required.
"""
    (OUT / "CHOMPER-BLOOD-V20Z-VERIFICATION.TXT").write_text(
        verification, encoding="ascii", newline="\r\n"
    )

    manifest = {
        "package": PACKAGE_NAME,
        "version": "V20Z",
        "status": "static verification passed; DOSBox chomper-blood confirmation pending",
        "baseline": {
            "version": "V20Y",
            "package": baseline_manifest["package"],
            "package_manifest_sha256": EXPECTED_BASELINE_MANIFEST_SHA256,
        },
        "scope": {
            "changed_dat_archives": [],
            "changed_executable_runtime_bytes": 4,
            "changed_runtime_table": "CGA mono color 12",
            "preserved_chomper_stencils": list(range(1314, 1324)),
            "preserved_floor_overlay_fix": True,
            "preserved_title_resource_54_fix": True,
            "preserved_command_tail_forwarding": True,
        },
        "analysis": {
            "patterns_evaluated": 256,
            "passes": ["six-pixel rear/floor", "two-pixel foreground blade"],
            "frames_per_pass": 5,
            "selected_pattern_hex": "C4",
            "selected_pattern_bits": "11000100",
            "blade_predicted_mean_rgb": [146, 65, 78],
            "rear_floor_predicted_mean_rgb": [181, 56, 51],
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
    }
    (OUT / "CHOMPER-BLOOD-V20Z-MANIFEST.JSON").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    tools_dir = OUT / "tools"
    if tools_dir.exists():
        shutil.rmtree(tools_dir)
    tools_dir.mkdir()
    for tool in (Path(__file__), ROOT / "analyze_chomper_blood.py"):
        shutil.copy2(tool, tools_dir / tool.name)

    package_manifest = {
        "package": PACKAGE_NAME,
        "status": manifest["status"],
        "baseline_package": baseline_manifest["package"],
        "files": {},
    }
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

    checksums = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.TXT":
            checksums.append(f"{sha256_file(path)}  {path.relative_to(OUT).as_posix()}")
    (OUT / "SHA256SUMS.TXT").write_text("\n".join(checksums) + "\n", encoding="ascii")

    make_zip(OUT, ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        if archive.testzip() is not None:
            raise ValueError("V20Z ZIP integrity check failed")
        expected_names = {
            (Path(PACKAGE_NAME) / path.relative_to(OUT)).as_posix()
            for path in OUT.rglob("*")
            if path.is_file()
        }
        if set(archive.namelist()) != expected_names:
            raise ValueError("V20Z ZIP contents differ from package directory")

    print(
        json.dumps(
            {
                "package_dir": str(OUT),
                "zip": str(ZIP_PATH),
                "zip_bytes": ZIP_PATH.stat().st_size,
                "zip_sha256": sha256_file(ZIP_PATH),
                "cdungeon_sha256": sha256_file(OUT / "CDUNGEON.DAT"),
                "executable": executable_meta,
                "launcher": launcher_meta,
                "unchanged_dat_archives": len(list(BASELINE.glob("*.DAT"))),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
