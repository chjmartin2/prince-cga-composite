#!/usr/bin/env python3
"""Build V20X by repairing the three dungeon floor-overlay masks.

Amir's Mode-6 designs for CDUNGEON resources 232, 350, and 351 used source
index zero for black samples inside the original opaque silhouette.  Prince
treats index zero as transparency, so the climbing Prince showed through the
floor overlay.  V20X substitutes a nonzero index with the same CGA value at
those positions, restoring occlusion without changing one Mode-6 signal bit.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
import zipfile

import build_v20w as v20w


ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = ROOT.parent
EDITOR_ROOT = REPOSITORY_ROOT / "editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))

from composite_project import encode_image_lzg, rebuild_dat  # noqa: E402
from prince_dat import DatArchive, hardware_palette_for_resource  # noqa: E402


BUILD_ROOT = ROOT / "build"
BASELINE_NAME = (
    "Prince-1.3-New-CGA-V20W-Amir-Title-R54-"
    "Transparency-CDungeon-WIP"
)
BASELINE = BUILD_ROOT / BASELINE_NAME
PACKAGE_NAME = "Prince-1.3-New-CGA-V20X-Floor-Overlay-Occlusion"
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"

ORIGINAL_CDUNGEON = ROOT / "source_work" / "pop13" / "CDUNGEON.DAT"
SOURCE_EXE = "P4KX2W.EXE"
SOURCE_COM = "CGA4K2W.COM"
OUTPUT_EXE = "P4KX2X.EXE"
OUTPUT_COM = "CGA4K2X.COM"

EXPECTED_BASELINE_MANIFEST_SHA256 = (
    "d5d08ef65716cadd2345356968f44ff511958cfb5786da64b082646d87824a1c"
)
EXPECTED_BASELINE_EXE_SHA256 = (
    "a90508c271823ca182df83ad63a8d5c49a9971e2df7c68f8303691e4f2a0a3e5"
)
EXPECTED_BASELINE_COM_SHA256 = (
    "88f211da85b5055634642a42de3337f69db7834c53ed9ae1629c2181e1336646"
)
EXPECTED_BASELINE_CDUNGEON_SHA256 = (
    "ec74b03105f47cac467e8568490aa3993bef3f1a961cbf961484bdd549b65ea4"
)
EXPECTED_ORIGINAL_CDUNGEON_SHA256 = (
    "8ca545775ac124642b8b486881ab9b8704f57f24f9ec66ab0b9906ed0471bd7b"
)
EXPECTED_REPAIRED_CDUNGEON_SHA256 = (
    "1466914150b8f66494240e20486b236d3b7b648ec0a3d1cbb093223614569a14"
)

FLOOR_RESOURCES = {
    232: {
        "dimensions": (18, 8, 4),
        "restored": 16,
        "transparent": 64,
        "content_sha256": "b625ae2e1104ea658ca8ad7772128a2eac709d7ce98efb118e94dcb8dc008584",
    },
    350: {
        "dimensions": (22, 10, 4),
        "restored": 25,
        "transparent": 100,
        "content_sha256": "c0f37a7148870e3aa760d3a9537470327efef2cd5c3faa1a7b29c1f4851c4ef6",
    },
    351: {
        "dimensions": (21, 10, 4),
        "restored": 25,
        "transparent": 100,
        "content_sha256": "a4b872f5b14aba5cc280456418bf1e26389d1e6bd671f734d5256f2f47bdcbc8",
    },
}


def sha256_bytes(data: bytes) -> str:
    return v20w.sha256_bytes(data)


def sha256_file(path: Path) -> str:
    return v20w.sha256_file(path)


def verify_hash(path: Path, expected: str, label: str) -> None:
    v20w.verify_hash(path, expected, label)


def verify_baseline() -> dict[str, object]:
    manifest_path = BASELINE / "PACKAGE-MANIFEST.JSON"
    verify_hash(manifest_path, EXPECTED_BASELINE_MANIFEST_SHA256, "V20W package manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("package") != BASELINE_NAME:
        raise ValueError("unexpected V20W package identity")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("V20W package manifest has no file map")
    for relative, metadata in files.items():
        path = BASELINE / Path(relative)
        if not path.is_file():
            raise ValueError(f"missing V20W input file: {relative}")
        if path.stat().st_size != metadata["bytes"]:
            raise ValueError(f"V20W input size mismatch: {relative}")
        if sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"V20W input hash mismatch: {relative}")
    actual = {
        path.relative_to(BASELINE).as_posix()
        for path in BASELINE.rglob("*")
        if path.is_file()
    }
    expected = set(files) | {"PACKAGE-MANIFEST.JSON", "SHA256SUMS.TXT"}
    if actual != expected:
        raise ValueError("V20W package contents differ from its manifest")
    verify_hash(BASELINE / SOURCE_EXE, EXPECTED_BASELINE_EXE_SHA256, "V20W executable")
    verify_hash(BASELINE / SOURCE_COM, EXPECTED_BASELINE_COM_SHA256, "V20W launcher")
    verify_hash(
        BASELINE / "CDUNGEON.DAT",
        EXPECTED_BASELINE_CDUNGEON_SHA256,
        "V20W CDUNGEON.DAT",
    )
    return manifest


def repair_floor_overlays() -> tuple[bytes, dict[str, object]]:
    authored = v20w.open_verified_archive(
        BASELINE / "CDUNGEON.DAT",
        EXPECTED_BASELINE_CDUNGEON_SHA256,
        "V20W CDUNGEON.DAT",
    )
    original = v20w.open_verified_archive(
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
    total_restored = 0
    for resource_id, expected in FLOOR_RESOURCES.items():
        authored_analysis = authored.analysis_by_id(resource_id)
        original_analysis = original.analysis_by_id(resource_id)
        if (
            authored_analysis is None
            or authored_analysis.image is None
            or original_analysis is None
            or original_analysis.image is None
        ):
            raise ValueError(f"floor overlay resource {resource_id} is not an image")
        authored_image = authored_analysis.image
        original_image = original_analysis.image
        dimensions = (authored_image.width, authored_image.height, authored_image.bits)
        if dimensions != expected["dimensions"]:
            raise ValueError(f"unexpected resource {resource_id} dimensions: {dimensions}")
        if (
            original_image.width,
            original_image.height,
            original_image.bits,
        ) != dimensions:
            raise ValueError(f"original resource {resource_id} dimensions differ")

        palette = hardware_palette_for_resource(authored, authored_analysis.resource)
        if palette is None or len(palette.cga_translation) != 64:
            raise ValueError(f"resource {resource_id} has no CGA translation table")
        repaired = bytearray(authored_image.pixels)
        restored = 0
        replacement_indices: set[int] = set()
        for y in range(authored_image.height):
            for x in range(authored_image.width):
                offset = y * authored_image.width + x
                was_opaque = original_image.pixels[offset] != 0
                is_transparent = authored_image.pixels[offset] == 0
                if original_image.pixels[offset] == 0 and not is_transparent:
                    raise ValueError(
                        f"resource {resource_id} authors opacity outside the original mask"
                    )
                if not was_opaque or not is_transparent:
                    continue
                phase = ((y & 1) << 1) | (x & 1)
                desired = palette.cga_translation[phase * 16]
                candidates = [
                    index
                    for index in range(1, 16)
                    if palette.cga_translation[phase * 16 + index] == desired
                ]
                if not candidates:
                    raise ValueError(
                        f"resource {resource_id} cannot encode opaque CGA value {desired}"
                    )
                repaired[offset] = min(candidates)
                replacement_indices.add(repaired[offset])
                restored += 1

        if restored != expected["restored"]:
            raise ValueError(
                f"resource {resource_id} restored {restored}, expected {expected['restored']}"
            )
        if replacement_indices != {4}:
            raise ValueError(
                f"resource {resource_id} used unexpected opaque indices {replacement_indices}"
            )
        if tuple(pixel == 0 for pixel in repaired) != tuple(
            pixel == 0 for pixel in original_image.pixels
        ):
            raise ValueError(f"resource {resource_id} mask was not restored exactly")
        if repaired.count(0) != expected["transparent"]:
            raise ValueError(f"resource {resource_id} transparency count is wrong")

        for y in range(authored_image.height):
            for x in range(authored_image.width):
                offset = y * authored_image.width + x
                phase = ((y & 1) << 1) | (x & 1)
                before = palette.cga_translation[
                    phase * 16 + authored_image.pixels[offset]
                ]
                after = palette.cga_translation[phase * 16 + repaired[offset]]
                if before != after:
                    raise ValueError(
                        f"resource {resource_id} changed Mode-6 value at x={x}, y={y}"
                    )
                if authored_image.pixels[offset] != 0 and (
                    repaired[offset] != authored_image.pixels[offset]
                ):
                    raise ValueError(
                        f"resource {resource_id} changed an authored nonzero index"
                    )

        replacement = encode_image_lzg(
            authored_analysis.resource.data,
            authored_image,
            bytes(repaired),
        )
        content_hash = sha256_bytes(replacement)
        if content_hash != expected["content_sha256"]:
            raise ValueError(f"resource {resource_id} encoding changed unexpectedly")
        replacements[authored_analysis.resource.index] = replacement
        resource_meta[str(resource_id)] = {
            "dimensions": list(dimensions),
            "opaque_pixels_restored": restored,
            "replacement_source_index": 4,
            "transparent_pixels": repaired.count(0),
            "mode6_bitstream_byte_identical_to_amir": True,
            "original_mask_restored_exactly": True,
            "resource_content_sha256": content_hash,
        }
        total_restored += restored

    repaired_dat = rebuild_dat(authored, replacements)
    if sha256_bytes(repaired_dat) != EXPECTED_REPAIRED_CDUNGEON_SHA256:
        raise ValueError("repaired CDUNGEON.DAT changed unexpectedly")

    verification_path = OUT / "CDUNGEON.DAT.verification.tmp"
    verification_path.write_bytes(repaired_dat)
    try:
        verified = DatArchive.open(verification_path)
    finally:
        verification_path.unlink(missing_ok=True)
    if any(not resource.checksum_ok for resource in verified.resources):
        raise ValueError("repaired CDUNGEON.DAT failed checksum verification")
    for before, after in zip(authored.resources, verified.resources, strict=True):
        if before.resource_id != after.resource_id:
            raise ValueError("repaired CDUNGEON resource order changed")
        if before.resource_id not in FLOOR_RESOURCES and before.data != after.data:
            raise ValueError(
                f"CDUNGEON resource {before.resource_id} changed unexpectedly"
            )

    return repaired_dat, {
        "source_sha256": EXPECTED_BASELINE_CDUNGEON_SHA256,
        "repaired_sha256": EXPECTED_REPAIRED_CDUNGEON_SHA256,
        "total_opaque_pixels_restored": total_restored,
        "mode6_bitstreams_byte_identical_to_amir": True,
        "resource_268_changed": False,
        "resources": resource_meta,
    }


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_EXE).read_bytes()
    data = v20w.v20v.v20.replace_exact(source, b"TITLE R54 V20W", b"FLOOR FIX V20X")
    changed = [
        offset for offset, (before, after) in enumerate(zip(source, data)) if before != after
    ]
    marker_start = data.index(b"FLOOR FIX V20X")
    if any(not marker_start <= offset < marker_start + 14 for offset in changed):
        raise ValueError("V20X executable changed outside its visible marker")
    return data, {
        "file": OUTPUT_EXE,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_EXE,
        "baseline_sha256": EXPECTED_BASELINE_EXE_SHA256,
        "visible_ctrl_v_marker": "FLOOR FIX V20X    V1.3",
        "runtime_code_byte_identical_to_v20w": True,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_COM).read_bytes()
    replace = v20w.v20v.v20.replace_exact
    data = replace(source, b"P4KX2W.EXE", b"P4KX2X.EXE", expected=3)
    data = replace(
        data,
        b"TITLE R54 + CMD V20W ACTIVE",
        b"FLOOR FIX + CMD V20X ACTIVE",
    )
    pointer = v20w.v20v.COMMAND_TAIL_OFFSET_WORD_FILE_OFFSET
    if int.from_bytes(data[pointer:pointer + 2], "little") != v20w.v20v.PSP_COMMAND_TAIL_OFFSET:
        raise ValueError("V20X no longer forwards the parent PSP command tail")
    allowed: set[int] = set()
    for old in (b"P4KX2W.EXE", b"TITLE R54 + CMD V20W ACTIVE"):
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
        raise ValueError(f"V20X launcher changed unexpected offsets: {sorted(changed - allowed)}")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_COM,
        "baseline_sha256": EXPECTED_BASELINE_COM_SHA256,
        "child": OUTPUT_EXE,
        "banner": "FLOOR FIX + CMD V20X ACTIVE",
        "command_tail_pointer": "CS:0080 (parent PSP command tail)",
        "cpu": "8086/8088 compatible",
    }


README = """PRINCE OF PERSIA 1.3 - FLOOR OVERLAY OCCLUSION V20X
=======================================================

Run CGA4K2X.COM for normal play.
Run CGA4K2X.COM improved to enable Prince 1.3 cheat/testing commands.

V20X repairs CDUNGEON.DAT floor-overlay resources 232, 350, and 351.
Sixty-six black signal samples inside the original opaque silhouettes had been
stored as source index zero, which Prince treats as transparency. They now use
opaque source index 4, which translates to the same CGA 00 value. The complete
Mode-6 bitstreams and Amir's artifact-color designs are therefore unchanged.

Resource 268 is the gate-top mask, not the climbing floor overlay, and remains
byte-identical. All other V20W content, including the title resource 54 fix and
command-tail forwarding, is preserved.

TEST
----

Climb up and down ledges while facing right, especially the reported tower
location. Prince should remain behind the diagonal floor overlays. If only a
big-pillar-top arrangement still fails, report the exact room: the original
engine has a separate draw-condition bug for that tile combination.
"""


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging = zip_path.with_name(zip_path.name + ".building")
    if staging.exists():
        staging.unlink()
    fixed_time = (2026, 8, 31, 20, 0, 0)
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

    repaired_cdungeon, floor_meta = repair_floor_overlays()
    (OUT / "CDUNGEON.DAT").write_bytes(repaired_cdungeon)
    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    (OUT / "README.TXT").write_text(README, encoding="ascii", newline="\r\n")
    (OUT / "FLOOR-OVERLAY-V20X-README.TXT").write_text(
        README, encoding="ascii", newline="\r\n"
    )

    for baseline_dat in sorted(BASELINE.glob("*.DAT")):
        output_dat = OUT / baseline_dat.name
        if baseline_dat.name != "CDUNGEON.DAT" and (
            output_dat.read_bytes() != baseline_dat.read_bytes()
        ):
            raise ValueError(f"V20X changed DAT archive {baseline_dat.name}")

    verification = f"""Prince of Persia 1.3 V20X Floor Overlay Verification
==========================================================
BASE PASS    Exact verified V20W package used as input
EXE PASS     Runtime code byte-identical; marker-only {OUTPUT_EXE} SHA-256 {executable_meta['sha256']}
COM PASS     {OUTPUT_COM} preserves command-tail forwarding; SHA-256 {launcher_meta['sha256']}
MASK PASS    Original masks restored for resources 232, 350, and 351
BITS PASS    Every Mode-6 signal value is byte-identical to Amir's artwork
OPAQUE PASS  66 transparent index-zero holes replaced by opaque index 4
R268 PASS    Gate-top mask resource 268 remains byte-identical
DAT PASS     Repaired CDUNGEON.DAT SHA-256 {EXPECTED_REPAIRED_CDUNGEON_SHA256}
KEEP PASS    All other DAT archives and executable runtime code preserve V20W

STATIC VERIFICATION PASSED.
DOSBox right-facing tower-climb confirmation is still required.
"""
    (OUT / "FLOOR-OVERLAY-V20X-VERIFICATION.TXT").write_text(
        verification, encoding="ascii", newline="\r\n"
    )

    manifest = {
        "package": PACKAGE_NAME,
        "version": "V20X",
        "status": "static verification passed; DOSBox tower-climb confirmation pending",
        "baseline": {
            "version": "V20W",
            "package": baseline_manifest["package"],
            "package_manifest_sha256": EXPECTED_BASELINE_MANIFEST_SHA256,
        },
        "scope": {
            "changed_dat_archives": ["CDUNGEON.DAT"],
            "changed_resources": sorted(FLOOR_RESOURCES),
            "changed_executable_runtime_code": False,
            "preserved_title_resource_54_fix": True,
            "preserved_command_tail_forwarding": True,
            "known_separate_risk": "original big-pillar-top climb draw-condition bug",
        },
        "floor_overlays": floor_meta,
        "executable": executable_meta,
        "launcher": launcher_meta,
    }
    (OUT / "FLOOR-OVERLAY-V20X-MANIFEST.JSON").write_text(
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
            raise ValueError("V20X ZIP integrity check failed")
        expected_names = {
            (Path(PACKAGE_NAME) / path.relative_to(OUT)).as_posix()
            for path in OUT.rglob("*")
            if path.is_file()
        }
        if set(archive.namelist()) != expected_names:
            raise ValueError("V20X ZIP contents differ from package directory")

    print(
        json.dumps(
            {
                "package_dir": str(OUT),
                "zip": str(ZIP_PATH),
                "zip_bytes": ZIP_PATH.stat().st_size,
                "zip_sha256": sha256_file(ZIP_PATH),
                "cdungeon": floor_meta,
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
