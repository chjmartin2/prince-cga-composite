#!/usr/bin/env python3
"""Build V20W from V20V with Amir's title and dungeon artwork.

V20W restores TITLE.DAT resource 54's original index-zero transparency mask
over Amir's authored image.  All pixels outside that mask remain byte-for-byte
identical after decode, so opaque black in the logo outline is preserved.
Amir's current CDUNGEON.DAT is included unchanged as work-in-progress artwork.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path
import zipfile

import build_v20v as v20v


ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parent
EDITOR_ROOT = REPOSITORY_ROOT / "editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))

from composite_project import encode_image_lzg, rebuild_dat  # noqa: E402
from prince_dat import DatArchive, hardware_palette_for_resource  # noqa: E402


BUILD_ROOT = ROOT / "build"
BASELINE_NAME = (
    "Prince-1.3-New-CGA-V20V-Command-Tail-Sword-"
    "Dungeon-Version-B-DAT-Set"
)
BASELINE = BUILD_ROOT / BASELINE_NAME
PACKAGE_NAME = (
    "Prince-1.3-New-CGA-V20W-Amir-Title-R54-"
    "Transparency-CDungeon-WIP"
)
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"

SOURCE_ASSET_ROOT = ROOT / "source_work" / "amir_2026_08_30"
AMIR_TITLE = SOURCE_ASSET_ROOT / "TITLE.DAT"
AMIR_CDUNGEON = SOURCE_ASSET_ROOT / "CDUNGEON.DAT"
ORIGINAL_TITLE = ROOT / "source_work" / "pop13" / "TITLE.DAT"

SOURCE_EXE = "P4KX2V.EXE"
SOURCE_COM = "CGA4K2V.COM"
OUTPUT_EXE = "P4KX2W.EXE"
OUTPUT_COM = "CGA4K2W.COM"

EXPECTED_BASELINE_MANIFEST_SHA256 = (
    "90c2de786049ce825caccaceb777da4a8957c85fd200e963e6d3505ea3a51cce"
)
EXPECTED_BASELINE_EXE_SHA256 = (
    "f77772a2c588390a9795fc49c82f4dc5ec5eb69e34f1efe2da29e009cce8d254"
)
EXPECTED_BASELINE_COM_SHA256 = (
    "8d6cf57ae21260fd821ff3f8d278d3680d574d28bbf593663130d3375453425b"
)
EXPECTED_AMIR_TITLE_SHA256 = (
    "4c41b050218b436fcfa126bfde4b2a068f5f0479d3a4b102e26702ea1db5a295"
)
EXPECTED_AMIR_CDUNGEON_SHA256 = (
    "ec74b03105f47cac467e8568490aa3993bef3f1a961cbf961484bdd549b65ea4"
)
EXPECTED_ORIGINAL_TITLE_SHA256 = (
    "b7eb84651af54c4aed3475aa552e25f77392156f8caa692c9eba094ee69a5690"
)
EXPECTED_REPAIRED_TITLE_SHA256 = (
    "56e8fadd3b418bf2b73c2ca3233535fa936a8a910e8d253790f7b4af7fa04b62"
)
EXPECTED_REPAIRED_RESOURCE_SHA256 = (
    "76aa10921c31e91bf4859084affc83e88b37ff920ebca3ec5e969665cfaf6cba"
)

RESOURCE_ID = 54
EXPECTED_DIMENSIONS = (272, 65, 4)
EXPECTED_TRANSPARENT_PIXELS = 9_799
EXPECTED_REPLACED_BAKED_PIXELS = 3_775
EXPECTED_OPAQUE_BLACK_PIXELS = 1_929


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return v20v.sha256_file(path)


def verify_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise ValueError(f"missing {label}: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"unexpected {label} SHA-256: {actual}")


def verify_baseline() -> dict[str, object]:
    manifest_path = BASELINE / "PACKAGE-MANIFEST.JSON"
    verify_hash(
        manifest_path,
        EXPECTED_BASELINE_MANIFEST_SHA256,
        "V20V package manifest",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package") != BASELINE_NAME:
        raise ValueError("unexpected V20V package identity")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("V20V package manifest has no file map")
    for relative, metadata in files.items():
        path = BASELINE / Path(relative)
        if not path.is_file():
            raise ValueError(f"missing V20V input file: {relative}")
        if path.stat().st_size != metadata["bytes"]:
            raise ValueError(f"V20V input size mismatch: {relative}")
        if sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"V20V input hash mismatch: {relative}")
    actual = {
        path.relative_to(BASELINE).as_posix()
        for path in BASELINE.rglob("*")
        if path.is_file()
    }
    expected = set(files) | {"PACKAGE-MANIFEST.JSON", "SHA256SUMS.TXT"}
    if actual != expected:
        raise ValueError("V20V package contents differ from its manifest")
    verify_hash(BASELINE / SOURCE_EXE, EXPECTED_BASELINE_EXE_SHA256, "V20V executable")
    verify_hash(BASELINE / SOURCE_COM, EXPECTED_BASELINE_COM_SHA256, "V20V launcher")
    return manifest


def open_verified_archive(path: Path, expected_hash: str, label: str) -> DatArchive:
    verify_hash(path, expected_hash, label)
    archive = DatArchive.open(path)
    bad = [resource.resource_id for resource in archive.resources if not resource.checksum_ok]
    if bad:
        raise ValueError(f"{label} has bad DAT checksums: {bad}")
    return archive


def repair_title_resource_54() -> tuple[bytes, dict[str, object]]:
    authored = open_verified_archive(
        AMIR_TITLE, EXPECTED_AMIR_TITLE_SHA256, "Amir TITLE.DAT"
    )
    original = open_verified_archive(
        ORIGINAL_TITLE, EXPECTED_ORIGINAL_TITLE_SHA256, "original TITLE.DAT"
    )
    if [resource.resource_id for resource in authored.resources] != [
        resource.resource_id for resource in original.resources
    ]:
        raise ValueError("Amir and original TITLE.DAT resource IDs differ")

    authored_analysis = authored.analysis_by_id(RESOURCE_ID)
    original_analysis = original.analysis_by_id(RESOURCE_ID)
    if (
        authored_analysis is None
        or authored_analysis.image is None
        or original_analysis is None
        or original_analysis.image is None
    ):
        raise ValueError("TITLE.DAT resource 54 is not a decodable image")
    authored_image = authored_analysis.image
    original_image = original_analysis.image
    dimensions = (authored_image.width, authored_image.height, authored_image.bits)
    if dimensions != EXPECTED_DIMENSIONS:
        raise ValueError(f"unexpected Amir resource 54 dimensions: {dimensions}")
    if (
        original_image.width,
        original_image.height,
        original_image.bits,
    ) != EXPECTED_DIMENSIONS:
        raise ValueError("unexpected original resource 54 dimensions")

    repaired_pixels = bytes(
        0 if original_pixel == 0 else authored_pixel
        for original_pixel, authored_pixel in zip(
            original_image.pixels, authored_image.pixels, strict=True
        )
    )
    original_mask = tuple(pixel == 0 for pixel in original_image.pixels)
    repaired_mask = tuple(pixel == 0 for pixel in repaired_pixels)
    if repaired_mask != original_mask:
        raise ValueError("repaired resource 54 mask does not equal the original mask")
    for masked, before, after in zip(
        original_mask, authored_image.pixels, repaired_pixels, strict=True
    ):
        if not masked and before != after:
            raise ValueError("repair changed an authored opaque resource 54 pixel")
    replaced = sum(
        masked and before != after
        for masked, before, after in zip(
            original_mask, authored_image.pixels, repaired_pixels, strict=True
        )
    )
    if replaced != EXPECTED_REPLACED_BAKED_PIXELS:
        raise ValueError(f"unexpected baked-background replacement count: {replaced}")

    palette = hardware_palette_for_resource(authored, authored_analysis.resource)
    if palette is None or len(palette.cga_translation) != 64:
        raise ValueError("resource 54 has no usable CGA translation table")
    transparent = 0
    opaque_black = 0
    opaque_nonblack = 0
    for y in range(authored_image.height):
        for x in range(authored_image.width):
            offset = y * authored_image.width + x
            source_index = repaired_pixels[offset]
            phase = ((y & 1) << 1) | (x & 1)
            cga_value = palette.cga_translation[phase * 16 + source_index]
            if source_index == 0:
                transparent += 1
            elif cga_value == 0:
                opaque_black += 1
            else:
                opaque_nonblack += 1
    if transparent != EXPECTED_TRANSPARENT_PIXELS:
        raise ValueError(f"unexpected repaired transparency count: {transparent}")
    if opaque_black != EXPECTED_OPAQUE_BLACK_PIXELS:
        raise ValueError(f"unexpected repaired opaque-black count: {opaque_black}")

    replacement = encode_image_lzg(
        authored_analysis.resource.data,
        authored_image,
        repaired_pixels,
    )
    if sha256_bytes(replacement) != EXPECTED_REPAIRED_RESOURCE_SHA256:
        raise ValueError("repaired resource 54 encoding changed unexpectedly")
    repaired_dat = rebuild_dat(
        authored,
        {authored_analysis.resource.index: replacement},
    )
    if sha256_bytes(repaired_dat) != EXPECTED_REPAIRED_TITLE_SHA256:
        raise ValueError("repaired TITLE.DAT changed unexpectedly")

    verification_path = OUT / "TITLE.DAT.verification.tmp"
    verification_path.write_bytes(repaired_dat)
    try:
        verified = DatArchive.open(verification_path)
    finally:
        verification_path.unlink(missing_ok=True)
    if any(not resource.checksum_ok for resource in verified.resources):
        raise ValueError("repaired TITLE.DAT failed checksum verification")
    verified_analysis = verified.analysis_by_id(RESOURCE_ID)
    if verified_analysis is None or verified_analysis.image is None:
        raise ValueError("repaired TITLE.DAT resource 54 did not decode")
    if verified_analysis.image.pixels != repaired_pixels:
        raise ValueError("repaired TITLE.DAT resource 54 failed pixel verification")
    for before, after in zip(authored.resources, verified.resources, strict=True):
        if before.resource_id != after.resource_id:
            raise ValueError("repaired TITLE.DAT resource order changed")
        if before.resource_id != RESOURCE_ID and before.data != after.data:
            raise ValueError(f"TITLE.DAT resource {before.resource_id} changed unexpectedly")

    return repaired_dat, {
        "resource_id": RESOURCE_ID,
        "width": authored_image.width,
        "height": authored_image.height,
        "bits_per_pixel": authored_image.bits,
        "authored_title_sha256": EXPECTED_AMIR_TITLE_SHA256,
        "repaired_title_sha256": EXPECTED_REPAIRED_TITLE_SHA256,
        "repaired_resource_content_sha256": EXPECTED_REPAIRED_RESOURCE_SHA256,
        "transparent_pixels": transparent,
        "opaque_black_pixels": opaque_black,
        "opaque_nonblack_pixels": opaque_nonblack,
        "baked_background_pixels_restored_to_transparency": replaced,
        "all_authored_pixels_outside_original_mask_preserved": True,
        "original_index_zero_mask_restored_exactly": True,
    }


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_EXE).read_bytes()
    data = v20v.v20.replace_exact(source, b"SWORD CMD V20V", b"TITLE R54 V20W")
    changed = [
        offset for offset, (before, after) in enumerate(zip(source, data)) if before != after
    ]
    marker_start = data.index(b"TITLE R54 V20W")
    if any(not marker_start <= offset < marker_start + 14 for offset in changed):
        raise ValueError("V20W executable changed outside its visible marker")
    return data, {
        "file": OUTPUT_EXE,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_EXE,
        "baseline_sha256": EXPECTED_BASELINE_EXE_SHA256,
        "visible_ctrl_v_marker": "TITLE R54 V20W    V1.3",
        "runtime_code_byte_identical_to_v20v": True,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_COM).read_bytes()
    data = v20v.v20.replace_exact(source, b"P4KX2V.EXE", b"P4KX2W.EXE", expected=3)
    data = v20v.v20.replace_exact(
        data,
        b"CMDTAIL + SWORD V20V ACTIVE",
        b"TITLE R54 + CMD V20W ACTIVE",
    )
    if int.from_bytes(
        data[
            v20v.COMMAND_TAIL_OFFSET_WORD_FILE_OFFSET:
            v20v.COMMAND_TAIL_OFFSET_WORD_FILE_OFFSET + 2
        ],
        "little",
    ) != v20v.PSP_COMMAND_TAIL_OFFSET:
        raise ValueError("V20W no longer forwards the parent PSP command tail")
    allowed: set[int] = set()
    for old, new in (
        (b"P4KX2V.EXE", b"P4KX2W.EXE"),
        (b"CMDTAIL + SWORD V20V ACTIVE", b"TITLE R54 + CMD V20W ACTIVE"),
    ):
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
        raise ValueError(f"V20W launcher changed unexpected offsets: {sorted(changed - allowed)}")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_COM,
        "baseline_sha256": EXPECTED_BASELINE_COM_SHA256,
        "child": OUTPUT_EXE,
        "banner": "TITLE R54 + CMD V20W ACTIVE",
        "command_tail_pointer": "CS:0080 (parent PSP command tail)",
        "binary_offsets_changed_from_v20v": [
            f"0x{offset:04X}" for offset in sorted(changed)
        ],
        "cpu": "8086/8088 compatible",
    }


README = """PRINCE OF PERSIA 1.3 - AMIR TITLE RESOURCE 54 FIX V20W
============================================================

Run CGA4K2W.COM for normal play.
Run CGA4K2W.COM improved to enable Prince 1.3 cheat/testing commands.

V20W uses Amir's 2026-08-30 TITLE.DAT and CDUNGEON.DAT artwork. TITLE.DAT
resource 54 restores the original index-zero transparency mask over Amir's
authored title logo. This removes 3,775 baked-background pixels while retaining
every opaque authored pixel, including 1,929 opaque-black outline pixels.

CDUNGEON.DAT is included byte-for-byte from Amir's current work-in-progress.
Its separate floor-corner, right-facing climb-overlay, and chomper-blood issues
are not claimed fixed by V20W.

V20W otherwise preserves V20V, including the confirmed command-tail forwarding,
V20U shared moving sword, V19L mappings, and all other DAT archives.

TEST
----

Let the intro reach both the normal title logo and the high-score screen. The
background must show through resource 54 while the black letter outlines remain
opaque. Normal and `improved` launch syntax is unchanged.
"""


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging = zip_path.with_name(zip_path.name + ".building")
    if staging.exists():
        staging.unlink()
    fixed_time = (2026, 8, 31, 18, 0, 0)
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
    open_verified_archive(
        AMIR_CDUNGEON,
        EXPECTED_AMIR_CDUNGEON_SHA256,
        "Amir CDUNGEON.DAT",
    )
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(BASELINE, OUT)

    stale = (
        SOURCE_EXE,
        SOURCE_COM,
        "README.TXT",
        "PACKAGE-MANIFEST.JSON",
        "SHA256SUMS.TXT",
    )
    for name in stale:
        path = OUT / name
        if path.exists():
            path.unlink()

    repaired_title, title_meta = repair_title_resource_54()
    (OUT / "TITLE.DAT").write_bytes(repaired_title)
    shutil.copy2(AMIR_CDUNGEON, OUT / "CDUNGEON.DAT")

    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    (OUT / "README.TXT").write_text(README, encoding="ascii", newline="\r\n")
    (OUT / "TITLE-R54-V20W-README.TXT").write_text(
        README, encoding="ascii", newline="\r\n"
    )

    changed_dats = {"TITLE.DAT", "CDUNGEON.DAT"}
    for baseline_dat in sorted(BASELINE.glob("*.DAT")):
        output_dat = OUT / baseline_dat.name
        if baseline_dat.name not in changed_dats:
            if output_dat.read_bytes() != baseline_dat.read_bytes():
                raise ValueError(f"V20W changed DAT archive {baseline_dat.name}")
    if (OUT / "CDUNGEON.DAT").read_bytes() != AMIR_CDUNGEON.read_bytes():
        raise ValueError("V20W changed Amir's CDUNGEON.DAT")

    verification = f"""Prince of Persia 1.3 V20W Title Resource 54 Verification
================================================================
BASE PASS    Exact verified V20V package used as input
EXE PASS     Runtime code byte-identical; marker-only {OUTPUT_EXE} SHA-256 {executable_meta['sha256']}
COM PASS     {OUTPUT_COM} preserves V20V command-tail forwarding; SHA-256 {launcher_meta['sha256']}
TITLE PASS   Repaired TITLE.DAT SHA-256 {title_meta['repaired_title_sha256']}
MASK PASS    Original 9,799-pixel index-zero mask restored exactly
BLACK PASS   1,929 opaque-black resource 54 pixels remain nonzero source indices
ART PASS     Every Amir-authored resource 54 pixel outside the mask is preserved
CDUN PASS    Amir CDUNGEON.DAT copied byte-for-byte; SHA-256 {EXPECTED_AMIR_CDUNGEON_SHA256}
DAT PASS     All DAT archives other than TITLE/CDUNGEON are byte-identical to V20V

STATIC VERIFICATION PASSED.
DOSBox title/high-score visual confirmation is still required.
"""
    (OUT / "TITLE-R54-V20W-VERIFICATION.TXT").write_text(
        verification, encoding="ascii", newline="\r\n"
    )

    manifest = {
        "package": PACKAGE_NAME,
        "version": "V20W",
        "status": "static verification passed; DOSBox title/high-score confirmation pending",
        "baseline": {
            "version": "V20V",
            "package": baseline_manifest["package"],
            "package_manifest_sha256": EXPECTED_BASELINE_MANIFEST_SHA256,
            "command_tail_forwarding_confirmed_in_dosbox": True,
        },
        "scope": {
            "changed_dat_archives": ["CDUNGEON.DAT", "TITLE.DAT"],
            "changed_executable_runtime_code": False,
            "preserved_v20v_command_tail_forwarding": True,
            "preserved_v20u_shared_sword": True,
            "preserved_v19l_runtime_mappings": True,
            "cdungeon_status": "Amir work-in-progress copied unchanged",
        },
        "title_resource_54": title_meta,
        "cdungeon": {
            "source": "Amir 2026-08-30 work-in-progress",
            "sha256": EXPECTED_AMIR_CDUNGEON_SHA256,
            "bytes": AMIR_CDUNGEON.stat().st_size,
            "copied_byte_identical": True,
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
    }
    (OUT / "TITLE-R54-V20W-MANIFEST.JSON").write_text(
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
            raise ValueError("V20W ZIP integrity check failed")
        expected_names = {
            (Path(PACKAGE_NAME) / path.relative_to(OUT)).as_posix()
            for path in OUT.rglob("*")
            if path.is_file()
        }
        if set(archive.namelist()) != expected_names:
            raise ValueError("V20W ZIP contents differ from package directory")

    print(
        json.dumps(
            {
                "package_dir": str(OUT),
                "zip": str(ZIP_PATH),
                "zip_bytes": ZIP_PATH.stat().st_size,
                "zip_sha256": sha256_file(ZIP_PATH),
                "executable": executable_meta,
                "launcher": launcher_meta,
                "title_resource_54": title_meta,
                "cdungeon_sha256": EXPECTED_AMIR_CDUNGEON_SHA256,
                "unchanged_dat_archives": len(list(BASELINE.glob("*.DAT"))) - 2,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
