#!/usr/bin/env python3
"""Build V20 with one shared P0/P2 exhaustive moving-sword conversion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

import build_v19l as v19l


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
EDITOR = REPO / "editor"
sys.path.insert(0, str(EDITOR))

from composite_converter import (  # noqa: E402
    ConversionSettings,
    DITHER_NONE,
    PHASE_ALL,
    QUALITY_HIGH,
    _all_phase_rmse,
    adjusted_signal_target,
    convert_raster_to_exhaustive,
)
from composite_project import (  # noqa: E402
    CompositeEdit,
    encode_image_lzg,
    initial_mode6_bits,
    rebuild_dat,
    source_pixels_for_edit,
)
from prince_dat import (  # noqa: E402
    COMPOSITE_PROFILE_NEW,
    DatArchive,
    decode_prince_image,
    hardware_palette_for_resource,
    mode6_width,
    render_display_mode,
)
from composite_signal import render_composite_artifacts  # noqa: E402


BASELINE = v19l.OUT
SOURCE_PRINCE = ROOT / "source_work" / "pop13" / "PRINCE.DAT"
BUILD_ROOT = ROOT / "build"
PACKAGE_NAME = (
    "Prince-1.3-New-CGA-V20-Shared-P0-P2-Sword-"
    "Dungeon-Version-B-DAT-Set"
)
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"

SOURCE_EXE = "P4KX1L.EXE"
SOURCE_COM = "CGA4K1L.COM"
OUTPUT_EXE = "P4KX20.EXE"
OUTPUT_COM = "CGA4K20.COM"

EXPECTED_BASELINE_MANIFEST_SHA256 = (
    "7394faea6b61f81c8a7cec156d92ba36cb0d42a3d2664769174e2ca66ad37801"
)
EXPECTED_BASELINE_EXE_SHA256 = (
    "1b92a8f4138bffd58b62ecff4d56b708a733da51c1554e6fee52fdfb457b018c"
)
EXPECTED_BASELINE_COM_SHA256 = (
    "c35bf4aa374dcbb29aa5bb514eb31ff84c6150f5524172b4a6529c655a160777"
)
EXPECTED_BASELINE_PRINCE_SHA256 = (
    "e71aa4dec42d22ce76bc146c3d72b0933281b5975dfe868699016d91f450a7c5"
)
EXPECTED_SOURCE_PRINCE_SHA256 = (
    "0ec31ef20c8253530728e40fe78531fee94cb1265c6e6f685c06e6d116e595d8"
)
SWORD_RESOURCE_IDS = tuple(range(701, 735))
REACHABLE_PHASES = (0, 2)
SETTINGS = dict(
    dither=DITHER_NONE,
    dither_amount=0,
    serpentine=True,
    bayer_size=4,
    brightness=0,
    contrast=0,
    saturation=100,
    gamma=1.0,
    color_emphasis=100,
    detail=100,
    quality=QUALITY_HIGH,
    preserve_zero=True,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_exact(data: bytes, old: bytes, new: bytes, expected: int = 1) -> bytes:
    if len(old) != len(new) or data.count(old) != expected:
        raise ValueError(f"expected {expected} equal-length marker(s) {old!r}")
    return data.replace(old, new)


def verify_baseline() -> dict[str, object]:
    manifest_path = BASELINE / "PACKAGE-MANIFEST.JSON"
    if sha256_file(manifest_path) != EXPECTED_BASELINE_MANIFEST_SHA256:
        raise ValueError("unexpected V19L package manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for relative, metadata in manifest["files"].items():
        path = BASELINE / relative
        if not path.is_file():
            raise ValueError(f"missing V19L input file: {relative}")
        if path.stat().st_size != metadata["bytes"]:
            raise ValueError(f"V19L input size mismatch: {relative}")
        if sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"V19L input hash mismatch: {relative}")
    expected = {
        SOURCE_EXE: EXPECTED_BASELINE_EXE_SHA256,
        SOURCE_COM: EXPECTED_BASELINE_COM_SHA256,
        "PRINCE.DAT": EXPECTED_BASELINE_PRINCE_SHA256,
    }
    for name, digest in expected.items():
        if sha256_file(BASELINE / name) != digest:
            raise ValueError(f"unexpected V19L {name}")
    if sha256_file(SOURCE_PRINCE) != EXPECTED_SOURCE_PRINCE_SHA256:
        raise ValueError("unexpected original Prince 1.3 PRINCE.DAT")
    return manifest


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_EXE).read_bytes()
    data = replace_exact(source, b"KID TABLE V19L", b"SWORD UNI V20U")
    changed = [index for index, pair in enumerate(zip(source, data)) if pair[0] != pair[1]]
    marker_start = data.index(b"SWORD UNI V20U")
    if any(not marker_start <= index < marker_start + 14 for index in changed):
        raise ValueError("V20 executable changed outside the visible marker")
    return data, {
        "file": OUTPUT_EXE,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_EXE,
        "baseline_sha256": EXPECTED_BASELINE_EXE_SHA256,
        "visible_ctrl_v_marker": "SWORD UNI V20U    V1.3",
        "binary_offsets_changed_from_v19l": [f"0x{offset:05X}" for offset in changed],
        "runtime_code_byte_identical_to_v19l": True,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = (BASELINE / SOURCE_COM).read_bytes()
    data = replace_exact(source, b"P4KX1L.EXE", b"P4KX20.EXE", expected=3)
    data = replace_exact(
        data,
        b"KID PHASE TABLE V19L ACTIVE",
        b"SWORD UNIVERSAL V20 ACTIVE ",
    )
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "baseline_file": SOURCE_COM,
        "baseline_sha256": EXPECTED_BASELINE_COM_SHA256,
        "child": OUTPUT_EXE,
        "banner": "SWORD UNIVERSAL V20 ACTIVE",
    }


def build_shared_sword() -> tuple[bytes, dict[str, object]]:
    source_archive = DatArchive.open(SOURCE_PRINCE)
    baseline_archive = DatArchive.open(BASELINE / "PRINCE.DAT")
    replacements: dict[int, bytes] = {}
    records: list[dict[str, object]] = []

    def phase_set_mae(bits, width, height, target):
        absolute = 0
        for phase in REACHABLE_PHASES:
            preview = render_composite_artifacts(
                bits,
                width,
                height,
                COMPOSITE_PROFILE_NEW,
                phase_offset=phase,
            )
            for pixel, expected in enumerate(target):
                offset = pixel * 3
                absolute += sum(
                    abs(preview.pixels[offset + channel] - expected[channel])
                    for channel in range(3)
                )
        return absolute / (len(target) * 3 * len(REACHABLE_PHASES))

    for resource_id in SWORD_RESOURCE_IDS:
        source_analysis = source_archive.analysis_by_id(resource_id)
        baseline_analysis = baseline_archive.analysis_by_id(resource_id)
        if source_analysis is None or source_analysis.image is None:
            raise ValueError(f"missing source sword resource {resource_id}")
        if baseline_analysis is None or baseline_analysis.image is None:
            raise ValueError(f"missing baseline sword resource {resource_id}")
        source_image = source_analysis.image
        baseline_image = baseline_analysis.image
        geometry = (source_image.width, source_image.height, source_image.bits)
        if geometry != (
            baseline_image.width,
            baseline_image.height,
            baseline_image.bits,
        ):
            raise ValueError(f"sword geometry changed for resource {resource_id}")

        source_hardware = hardware_palette_for_resource(
            source_archive, source_analysis.resource
        )
        baseline_hardware = hardware_palette_for_resource(
            baseline_archive, baseline_analysis.resource
        )
        source_raster = render_display_mode(source_image, "vga", source_hardware)
        zero_mask = bytearray(value == 0 for value in source_image.pixels)
        bit_width = mode6_width(baseline_image)
        translation = source_hardware.cga_translation
        if len(translation) != 64:
            raise ValueError("moving-sword palette lacks four CGA translation tables")
        allowed_codes = tuple(
            tuple(sorted(set(translation[phase * 16 : phase * 16 + 16])))
            for y in range(baseline_image.height)
            for x in range(baseline_image.width)
            for phase in (((y & 1) << 1) | (x & 1),)
        )
        settings = ConversionSettings(
            phase_offset=PHASE_ALL,
            all_phase_offsets=REACHABLE_PHASES,
            **SETTINGS,
        )
        result = convert_raster_to_exhaustive(
            source_raster,
            bit_width,
            source_image.height,
            COMPOSITE_PROFILE_NEW,
            settings,
            source_zero_mask=zero_mask,
            target_allowed_codes=allowed_codes,
        )
        target = adjusted_signal_target(
            source_raster,
            bit_width,
            source_image.height,
            settings,
        )
        baseline_bits = initial_mode6_bits(baseline_image, baseline_hardware)
        baseline_rmse = _all_phase_rmse(
            baseline_bits,
            bit_width,
            source_image.height,
            COMPOSITE_PROFILE_NEW,
            target,
            REACHABLE_PHASES,
        )
        baseline_mae = phase_set_mae(
            baseline_bits, bit_width, source_image.height, target
        )
        shared_mae = phase_set_mae(
            result.bits, bit_width, source_image.height, target
        )
        if shared_mae > baseline_mae:
            raise ValueError(
                f"shared objective regressed for sword resource {resource_id}"
            )
        edit = CompositeEdit(
            resource_index=baseline_analysis.resource.index,
            resource_id=resource_id,
            source_width=source_image.width,
            height=source_image.height,
            source_depth=source_image.bits,
            bit_width=bit_width,
            bits=bytearray(result.bits),
            mask_locked=True,
            source_zero_mask=zero_mask,
            mask_reference_bits=initial_mode6_bits(source_image, source_hardware),
        )
        pixels = source_pixels_for_edit(
            source_image,
            edit,
            source_hardware,
            bits=result.bits,
        )
        replacement = encode_image_lzg(
            source_analysis.resource.data,
            source_image,
            pixels,
        )
        decoded_replacement = decode_prince_image(replacement)
        if bytearray(value == 0 for value in decoded_replacement.pixels) != zero_mask:
            raise ValueError(f"sword transparency round-trip failed for {resource_id}")
        if initial_mode6_bits(decoded_replacement, source_hardware) != result.bits:
            raise ValueError(f"sword Mode-6 round-trip failed for {resource_id}")
        replacements[baseline_analysis.resource.index] = replacement
        records.append(
            {
                "resource_id": resource_id,
                "width": source_image.width,
                "height": source_image.height,
                "bit_width": bit_width,
                "baseline_p0_p2_rmse": round(baseline_rmse, 6),
                "shared_p0_p2_rmse": round(result.source_rmse, 6),
                "baseline_p0_p2_mae": round(baseline_mae, 6),
                "shared_p0_p2_mae": round(shared_mae, 6),
                "changed_mode6_bits": sum(
                    left != right for left, right in zip(baseline_bits, result.bits)
                ),
                "baseline_transparency_drift_pixels": sum(
                    (left == 0) != (right == 0)
                    for left, right in zip(source_image.pixels, baseline_image.pixels)
                ),
                "content_sha256": sha256_bytes(replacement),
            }
        )

    rebuilt = rebuild_dat(baseline_archive, replacements)
    return rebuilt, {
        "file": "PRINCE.DAT",
        "bytes": len(rebuilt),
        "sha256": sha256_bytes(rebuilt),
        "baseline_sha256": EXPECTED_BASELINE_PRINCE_SHA256,
        "source_vga_sha256": EXPECTED_SOURCE_PRINCE_SHA256,
        "resources": list(SWORD_RESOURCE_IDS),
        "resource_count": len(records),
        "reachable_phases": list(REACHABLE_PHASES),
        "strategy": "one shared exact P0/P2 bitstream per moving-sword resource",
        "runtime_selector_added": False,
        "records": records,
    }


README = """PRINCE OF PERSIA 1.3 - SHARED-PHASE MOVING SWORD V20U
=========================================================

Run CGA4K20.COM.

This test build keeps every V19L runtime mapping byte-for-byte and changes only
PRINCE.DAT resources 701..734, the moving/carried sword overlay. Each sword
frame has one exhaustive New-CGA bit pattern optimized jointly for its two
reachable composite phases, P0 and P2. There is no sword phase selector, no
new sidecar DAT, and no added runtime code.

TEST ROUTE
----------

Pick up, draw, sheathe, guard, advance, retreat, and strike with the sword.
Repeat at adjacent horizontal positions and facing both directions. Pay special
attention to the colored hilt/detail frames 722..728, 732, and 734. Also check
the Kid body, health icons, hurt splash, level transitions, and restart for
V19L regressions.

Static verification passed. DOSBox confirmation is required.
"""


def make_zip(source_dir: Path, zip_path: Path) -> None:
    staging = zip_path.with_name(zip_path.name + ".building")
    if staging.exists():
        staging.unlink()
    fixed_time = (2026, 8, 30, 18, 0, 0)
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

    stale = (
        SOURCE_EXE,
        SOURCE_COM,
        "README.TXT",
        "KID-V19L-README.TXT",
        "KID-V19L-VERIFICATION.TXT",
        "KID-V19L-MANIFEST.JSON",
        "PACKAGE-MANIFEST.JSON",
        "SHA256SUMS.TXT",
    )
    for name in stale:
        path = OUT / name
        if path.exists():
            path.unlink()

    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    prince_dat, sword_meta = build_shared_sword()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    (OUT / "PRINCE.DAT").write_bytes(prince_dat)
    (OUT / "README.TXT").write_text(README, encoding="ascii", newline="\r\n")
    (OUT / "SWORD-V20-README.TXT").write_text(
        README, encoding="ascii", newline="\r\n"
    )

    rebuilt = DatArchive.open(OUT / "PRINCE.DAT")
    baseline = DatArchive.open(BASELINE / "PRINCE.DAT")
    changed_resources = []
    for resource in rebuilt.resources:
        before = baseline.resource_by_id(resource.resource_id)
        if before is None:
            raise ValueError(f"V20 added unexpected resource {resource.resource_id}")
        if resource.data != before.data:
            changed_resources.append(resource.resource_id)
    if changed_resources != list(SWORD_RESOURCE_IDS):
        raise ValueError(f"unexpected PRINCE.DAT changes: {changed_resources}")
    if len(rebuilt.resources) != len(baseline.resources):
        raise ValueError("V20 changed the PRINCE.DAT resource count")

    unchanged_dat_hashes = {}
    for path in sorted(BASELINE.glob("*.DAT")):
        if path.name == "PRINCE.DAT":
            continue
        output = OUT / path.name
        if output.read_bytes() != path.read_bytes():
            raise ValueError(f"V20 changed unrelated DAT archive {path.name}")
        unchanged_dat_hashes[path.name] = sha256_file(output)

    verification = f"""Prince of Persia 1.3 V20U Shared Sword Verification
========================================================
BASE PASS    Exact verified V19L package used as input
EXE PASS     Runtime code byte-identical; marker-only {OUTPUT_EXE} SHA-256 {executable_meta['sha256']}
COM PASS     {OUTPUT_COM} launches {OUTPUT_EXE}; SHA-256 {launcher_meta['sha256']}
SWORD PASS   PRINCE.DAT resources 701..734 are the only changed resource payloads
PHASE PASS   34 shared patterns optimized exhaustively over reachable P0 and P2
MASK PASS    All source-index-zero sword transparency masks preserved
COUNT PASS   PRINCE.DAT resource IDs, order, and count preserved
DAT PASS     Other {len(unchanged_dat_hashes)} DAT archives byte-identical to V19L
MAP PASS     All V19L KID, HP, and hurt-splash runtime code preserved

STATIC VERIFICATION PASSED.
DOSBox runtime verification is still required.
"""
    (OUT / "SWORD-V20-VERIFICATION.TXT").write_text(
        verification, encoding="ascii", newline="\r\n"
    )

    manifest = {
        "package": PACKAGE_NAME,
        "version": "V20U",
        "status": "static/resource verification passed; DOSBox confirmation pending",
        "baseline": {
            "version": "V19L",
            "package": baseline_manifest["package"],
            "package_manifest_sha256": EXPECTED_BASELINE_MANIFEST_SHA256,
        },
        "scope": {
            "changed_dat_archives": ["PRINCE.DAT"],
            "changed_resources": list(SWORD_RESOURCE_IDS),
            "unchanged_runtime_mapping": True,
            "sword_phase_variants": False,
            "sword_shared_reachable_phases": list(REACHABLE_PHASES),
        },
        "conversion": {
            "mode": "exhaustive",
            "profile": COMPOSITE_PROFILE_NEW,
            "source_display": "vga",
            "dither": "none",
            "preserve_source_zero": True,
            "objective": "one shared pattern over P0 and P2",
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
        "sword": sword_meta,
        "unchanged_dat_sha256": unchanged_dat_hashes,
    }
    (OUT / "SWORD-V20-MANIFEST.JSON").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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
    (OUT / "SHA256SUMS.TXT").write_text(
        "\n".join(checksums) + "\n", encoding="ascii"
    )

    make_zip(OUT, ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH) as archive:
        if archive.testzip() is not None:
            raise ValueError("V20 ZIP integrity check failed")
        expected_names = {
            (Path(PACKAGE_NAME) / path.relative_to(OUT)).as_posix()
            for path in OUT.rglob("*")
            if path.is_file()
        }
        if set(archive.namelist()) != expected_names:
            raise ValueError("V20 ZIP contents differ from package directory")

    print(
        json.dumps(
            {
                "package_dir": str(OUT),
                "zip": str(ZIP_PATH),
                "zip_bytes": ZIP_PATH.stat().st_size,
                "zip_sha256": sha256_file(ZIP_PATH),
                "executable": executable_meta,
                "launcher": launcher_meta,
                "sword": {
                    key: value for key, value in sword_meta.items() if key != "records"
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
