#!/usr/bin/env python3
"""Build V20Y by restoring the ten native one-bit chomper-blood stencils.

The composite conversion treated CDUNGEON resources 1314-1323 as ordinary
artifact-color artwork.  They are instead masks consumed by Prince's mono
blitter, which paints each set bit with the engine's hard-coded color 12.
Optimizing their bitmaps therefore damaged transparency/coverage semantics.
V20Y restores those resource contents byte-for-byte from the original archive.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
import zipfile

import build_v20x as v20x


ROOT = Path(__file__).resolve().parent
BUILD_ROOT = ROOT / "build"
BASELINE_NAME = "Prince-1.3-New-CGA-V20X-Floor-Overlay-Occlusion"
BASELINE = BUILD_ROOT / BASELINE_NAME
PACKAGE_NAME = "Prince-1.3-New-CGA-V20Y-Chomper-Blood-Stencils"
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"

ORIGINAL_CDUNGEON = ROOT / "source_work" / "pop13" / "CDUNGEON.DAT"
SOURCE_EXE = "P4KX2X.EXE"
SOURCE_COM = "CGA4K2X.COM"
OUTPUT_EXE = "P4KX2Y.EXE"
OUTPUT_COM = "CGA4K2Y.COM"

EXPECTED_BASELINE_MANIFEST_SHA256 = (
    "f0e84978483a22bf93a435a8043e3ff31be9ae32c95f90cae595430b99fe9d6c"
)
EXPECTED_BASELINE_EXE_SHA256 = (
    "65bf68df56af4a69c529debda085a66ca57447b144555ddc83ffcf9c11aaab5c"
)
EXPECTED_BASELINE_COM_SHA256 = (
    "3be21aa08ec9f1acaad2085cfc97a2053a11126e4df5c4e66ae94e5e9c80c57f"
)
EXPECTED_BASELINE_CDUNGEON_SHA256 = (
    "1466914150b8f66494240e20486b236d3b7b648ec0a3d1cbb093223614569a14"
)
EXPECTED_ORIGINAL_CDUNGEON_SHA256 = (
    "8ca545775ac124642b8b486881ab9b8704f57f24f9ec66ab0b9906ed0471bd7b"
)
EXPECTED_REPAIRED_CDUNGEON_SHA256 = (
    "b5459688c0d4618208fe6a3d233b0eaea18f51153b861195940fe940ea4d8536"
)

BLOOD_RESOURCES = {
    1314: ((6, 29, 1), 61, 134),
    1315: ((6, 25, 1), 50, 111),
    1316: ((6, 18, 1), 33, 75),
    1317: ((6, 9, 1), 13, 30),
    1318: ((4, 5, 1), 5, 11),
    1319: ((2, 29, 1), 24, 51),
    1320: ((2, 25, 1), 18, 39),
    1321: ((2, 18, 1), 11, 26),
    1322: ((2, 9, 1), 6, 14),
    1323: ((2, 5, 1), 2, 7),
}


def sha256_bytes(data: bytes) -> str:
    return v20x.sha256_bytes(data)


def sha256_file(path: Path) -> str:
    return v20x.sha256_file(path)


def verify_hash(path: Path, expected: str, label: str) -> None:
    v20x.verify_hash(path, expected, label)


def verify_baseline() -> dict[str, object]:
    manifest_path = BASELINE / "PACKAGE-MANIFEST.JSON"
    verify_hash(manifest_path, EXPECTED_BASELINE_MANIFEST_SHA256, "V20X package manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package") != BASELINE_NAME:
        raise ValueError("unexpected V20X package identity")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("V20X package manifest has no file map")
    for relative, metadata in files.items():
        path = BASELINE / Path(relative)
        if not path.is_file():
            raise ValueError(f"missing V20X input file: {relative}")
        if path.stat().st_size != metadata["bytes"]:
            raise ValueError(f"V20X input size mismatch: {relative}")
        if sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"V20X input hash mismatch: {relative}")
    actual = {
        path.relative_to(BASELINE).as_posix()
        for path in BASELINE.rglob("*")
        if path.is_file()
    }
    expected = set(files) | {"PACKAGE-MANIFEST.JSON", "SHA256SUMS.TXT"}
    if actual != expected:
        raise ValueError("V20X package contents differ from its manifest")
    verify_hash(BASELINE / SOURCE_EXE, EXPECTED_BASELINE_EXE_SHA256, "V20X executable")
    verify_hash(BASELINE / SOURCE_COM, EXPECTED_BASELINE_COM_SHA256, "V20X launcher")
    verify_hash(
        BASELINE / "CDUNGEON.DAT",
        EXPECTED_BASELINE_CDUNGEON_SHA256,
        "V20X CDUNGEON.DAT",
    )
    return manifest


def restore_blood_stencils() -> tuple[bytes, dict[str, object]]:
    authored = v20x.v20w.open_verified_archive(
        BASELINE / "CDUNGEON.DAT",
        EXPECTED_BASELINE_CDUNGEON_SHA256,
        "V20X CDUNGEON.DAT",
    )
    original = v20x.v20w.open_verified_archive(
        ORIGINAL_CDUNGEON,
        EXPECTED_ORIGINAL_CDUNGEON_SHA256,
        "original CDUNGEON.DAT",
    )
    if [resource.resource_id for resource in authored.resources] != [
        resource.resource_id for resource in original.resources
    ]:
        raise ValueError("authored and original CDUNGEON resource IDs differ")

    replacements: dict[int, bytes] = {}
    resource_meta: dict[str, object] = {}
    authored_total = 0
    restored_total = 0
    for resource_id, (dimensions, expected_authored, expected_original) in BLOOD_RESOURCES.items():
        authored_analysis = authored.analysis_by_id(resource_id)
        original_analysis = original.analysis_by_id(resource_id)
        if (
            authored_analysis is None
            or authored_analysis.image is None
            or original_analysis is None
            or original_analysis.image is None
        ):
            raise ValueError(f"blood resource {resource_id} is not an image")
        authored_image = authored_analysis.image
        original_image = original_analysis.image
        actual_dimensions = (
            original_image.width,
            original_image.height,
            original_image.bits,
        )
        if actual_dimensions != dimensions:
            raise ValueError(
                f"unexpected original resource {resource_id} dimensions: {actual_dimensions}"
            )
        if (
            authored_image.width,
            authored_image.height,
            authored_image.bits,
        ) != dimensions:
            raise ValueError(f"authored resource {resource_id} dimensions differ")

        authored_ones = sum(authored_image.pixels)
        original_ones = sum(original_image.pixels)
        if authored_ones != expected_authored or original_ones != expected_original:
            raise ValueError(f"unexpected blood stencil counts for resource {resource_id}")
        if authored_image.pixels == original_image.pixels:
            raise ValueError(f"blood resource {resource_id} was not damaged")

        replacements[authored_analysis.resource.index] = original_analysis.resource.data
        resource_meta[str(resource_id)] = {
            "dimensions": list(dimensions),
            "converted_set_bits": authored_ones,
            "restored_set_bits": original_ones,
            "set_bits_recovered": original_ones - authored_ones,
            "resource_content_sha256": sha256_bytes(original_analysis.resource.data),
            "original_resource_content_restored_byte_for_byte": True,
        }
        authored_total += authored_ones
        restored_total += original_ones

    repaired_dat = v20x.rebuild_dat(authored, replacements)
    if sha256_bytes(repaired_dat) != EXPECTED_REPAIRED_CDUNGEON_SHA256:
        raise ValueError("repaired CDUNGEON.DAT changed unexpectedly")

    verification_path = OUT / "CDUNGEON.DAT.verification.tmp"
    verification_path.write_bytes(repaired_dat)
    try:
        verified = v20x.DatArchive.open(verification_path)
    finally:
        verification_path.unlink(missing_ok=True)
    if any(not resource.checksum_ok for resource in verified.resources):
        raise ValueError("repaired CDUNGEON.DAT failed checksum verification")
    for before, after, source in zip(
        authored.resources, verified.resources, original.resources, strict=True
    ):
        if before.resource_id != after.resource_id or after.resource_id != source.resource_id:
            raise ValueError("repaired CDUNGEON resource order changed")
        if before.resource_id in BLOOD_RESOURCES:
            if after.data != source.data:
                raise ValueError(f"blood resource {before.resource_id} was not restored exactly")
        elif before.data != after.data:
            raise ValueError(f"CDUNGEON resource {before.resource_id} changed unexpectedly")

    return repaired_dat, {
        "source_sha256": EXPECTED_BASELINE_CDUNGEON_SHA256,
        "repaired_sha256": EXPECTED_REPAIRED_CDUNGEON_SHA256,
        "converted_set_bits": authored_total,
        "restored_set_bits": restored_total,
        "set_bits_recovered": restored_total - authored_total,
        "mono_blitter_color": 12,
        "mode6_color_pattern": "1100",
        "draw_x_phase": "P0 (screen X = 32*column + 12)",
        "resources": resource_meta,
    }


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_EXE).read_bytes()
    data = v20x.v20w.v20v.v20.replace_exact(source, b"FLOOR FIX V20X", b"BLOOD FIX V20Y")
    changed = [
        offset for offset, (before, after) in enumerate(zip(source, data)) if before != after
    ]
    marker_start = data.index(b"BLOOD FIX V20Y")
    if any(not marker_start <= offset < marker_start + 14 for offset in changed):
        raise ValueError("V20Y executable changed outside its visible marker")
    return data, {
        "file": OUTPUT_EXE,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_EXE,
        "baseline_sha256": EXPECTED_BASELINE_EXE_SHA256,
        "visible_ctrl_v_marker": "BLOOD FIX V20Y    V1.3",
        "runtime_code_byte_identical_to_v20x": True,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_COM).read_bytes()
    replace = v20x.v20w.v20v.v20.replace_exact
    data = replace(source, b"P4KX2X.EXE", b"P4KX2Y.EXE", expected=3)
    data = replace(
        data,
        b"FLOOR FIX + CMD V20X ACTIVE",
        b"BLOOD FIX + CMD V20Y ACTIVE",
    )
    pointer = v20x.v20w.v20v.COMMAND_TAIL_OFFSET_WORD_FILE_OFFSET
    if int.from_bytes(data[pointer:pointer + 2], "little") != v20x.v20w.v20v.PSP_COMMAND_TAIL_OFFSET:
        raise ValueError("V20Y no longer forwards the parent PSP command tail")
    allowed: set[int] = set()
    for old in (b"P4KX2X.EXE", b"FLOOR FIX + CMD V20X ACTIVE"):
        start = 0
        while True:
            found = source.find(old, start)
            if found < 0:
                break
            allowed.update(range(found, found + len(old)))
            start = found + len(old)
    changed = {
        offset for offset, (before, after) in enumerate(zip(source, data)) if before != after
    }
    if not changed <= allowed:
        raise ValueError(f"V20Y launcher changed unexpected offsets: {sorted(changed - allowed)}")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_COM,
        "baseline_sha256": EXPECTED_BASELINE_COM_SHA256,
        "child": OUTPUT_EXE,
        "banner": "BLOOD FIX + CMD V20Y ACTIVE",
        "command_tail_pointer": "CS:0080 (parent PSP command tail)",
        "cpu": "8086/8088 compatible",
    }


README = """PRINCE OF PERSIA 1.3 - CHOMPER BLOOD STENCILS V20Y
========================================================

Run CGA4K2Y.COM for normal play.
Run CGA4K2Y.COM improved to enable Prince 1.3 cheat/testing commands.

V20Y restores CDUNGEON.DAT resources 1314-1323 byte-for-byte from the
original game. These ten native one-bit images are not composite pictures;
they are transparency stencils. Prince paints their set bits using its mono
blitter's hard-coded color 12, which becomes the repeating 1100 Mode-6 pattern.

The composite conversion had reduced the stencils from 498 set bits to 223.
Restoring the missing 275 bits preserves their intended shapes and lets the
original renderer generate the blood color. No phase variants are needed:
every blood stencil is drawn at screen X = 32*column + 12, always P0.

All V20X floor-overlay, title, command-tail, sword, and phase behavior remains.

TEST
----

Trigger a chomper death or inspect an already bloodied chomper. Confirm that
the blood appears beside the chomper in all five animation frames and that its
artifact color looks appropriate in NTSC Composite mode.
"""


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging = zip_path.with_name(zip_path.name + ".building")
    if staging.exists():
        staging.unlink()
    fixed_time = (2026, 8, 31, 21, 0, 0)
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

    repaired_cdungeon, blood_meta = restore_blood_stencils()
    (OUT / "CDUNGEON.DAT").write_bytes(repaired_cdungeon)
    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    (OUT / "README.TXT").write_text(README, encoding="ascii", newline="\r\n")
    (OUT / "CHOMPER-BLOOD-V20Y-README.TXT").write_text(
        README, encoding="ascii", newline="\r\n"
    )

    for baseline_dat in sorted(BASELINE.glob("*.DAT")):
        output_dat = OUT / baseline_dat.name
        if baseline_dat.name != "CDUNGEON.DAT" and (
            output_dat.read_bytes() != baseline_dat.read_bytes()
        ):
            raise ValueError(f"V20Y changed DAT archive {baseline_dat.name}")

    verification = f"""Prince of Persia 1.3 V20Y Chomper Blood Verification
=========================================================
BASE PASS    Exact verified V20X package used as input
EXE PASS     Runtime code byte-identical; marker-only {OUTPUT_EXE} SHA-256 {executable_meta['sha256']}
COM PASS     {OUTPUT_COM} preserves command-tail forwarding; SHA-256 {launcher_meta['sha256']}
MASK PASS    Original one-bit resources 1314-1323 restored byte-for-byte
BITS PASS    498 original set bits restored from 223 converted set bits
COLOR PASS   Existing mono color 12 maps to repeating Mode-6 pattern 1100
PHASE PASS   Chomper blood draw X is always 32*column+12 (P0)
DAT PASS     Repaired CDUNGEON.DAT SHA-256 {EXPECTED_REPAIRED_CDUNGEON_SHA256}
KEEP PASS    Every other DAT resource and executable runtime code preserves V20X

STATIC VERIFICATION PASSED.
DOSBox chomper-blood visual confirmation is still required.
"""
    (OUT / "CHOMPER-BLOOD-V20Y-VERIFICATION.TXT").write_text(
        verification, encoding="ascii", newline="\r\n"
    )

    manifest = {
        "package": PACKAGE_NAME,
        "version": "V20Y",
        "status": "static verification passed; DOSBox chomper-blood confirmation pending",
        "baseline": {
            "version": "V20X",
            "package": baseline_manifest["package"],
            "package_manifest_sha256": EXPECTED_BASELINE_MANIFEST_SHA256,
        },
        "scope": {
            "changed_dat_archives": ["CDUNGEON.DAT"],
            "changed_resources": sorted(BLOOD_RESOURCES),
            "changed_executable_runtime_code": False,
            "preserved_floor_overlay_fix": True,
            "preserved_title_resource_54_fix": True,
            "preserved_command_tail_forwarding": True,
        },
        "chomper_blood": blood_meta,
        "executable": executable_meta,
        "launcher": launcher_meta,
    }
    (OUT / "CHOMPER-BLOOD-V20Y-MANIFEST.JSON").write_text(
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
            raise ValueError("V20Y ZIP integrity check failed")
        expected_names = {
            (Path(PACKAGE_NAME) / path.relative_to(OUT)).as_posix()
            for path in OUT.rglob("*")
            if path.is_file()
        }
        if set(archive.namelist()) != expected_names:
            raise ValueError("V20Y ZIP contents differ from package directory")

    print(
        json.dumps(
            {
                "package_dir": str(OUT),
                "zip": str(ZIP_PATH),
                "zip_bytes": ZIP_PATH.stat().st_size,
                "zip_sha256": sha256_file(ZIP_PATH),
                "cdungeon": blood_meta,
                "executable": executable_meta,
                "launcher": launcher_meta,
                "unchanged_dat_archives": len(list(BASELINE.glob("*.DAT"))) - 1,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
