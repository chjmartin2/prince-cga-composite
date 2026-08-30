#!/usr/bin/env python3
"""Build Prince 1.3 New-CGA V16 fall/landing phase-aware package.

V16 preserves the runtime-confirmed V15C live native-table architecture and
uses the last 24 aliases in the 219-image PHASE table for eight new four-way
Kid poses:

* game frames 102..109;
* KID image IDs 112..119;
* fall start, freefall, landing, and crouch;
* right/P0 in KID.DAT;
* right/P2, left/P0, and left/P2 in PHASE.DAT.

Artwork is generated from the verified original VGA KID.DAT with the same
independent Exhaustive/no-dither New-CGA optimizer used by V13/V14.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import zipfile


ROOT = Path(__file__).resolve().parent
V15C = (
    ROOT
    / "build"
    / "Prince-1.3-New-CGA-Phase-Aware-V15C-Live-Native-Table-Dungeon-Version-B-DAT-Set"
)
SOURCE_KID = ROOT / "source_work" / "pop13" / "KID.DAT"
BASELINE_KID = ROOT / "source_work" / "baseline" / "KID.DAT"
V13_TOOLS = (
    ROOT
    / "source_work"
    / "v13"
    / "Prince-Kid-VGA-Exhaustive-Phase-Prototype-v13"
    / "tools"
)
ART_TOOL = V13_TOOLS / "make_four_way_kid.py"
RENDER_TOOL = V13_TOOLS / "render_visual_verification.py"

BUILD_ROOT = ROOT / "build"
PACKAGE_NAME = (
    "Prince-1.3-New-CGA-Phase-Aware-V16-Fall-Landing-"
    "Dungeon-Version-B-DAT-Set"
)
OUT = BUILD_ROOT / PACKAGE_NAME
ZIP_PATH = BUILD_ROOT / f"{PACKAGE_NAME}.zip"
ART_WORK = BUILD_ROOT / "v16-art-work"

OUTPUT_EXE = "P4KX16.EXE"
OUTPUT_COM = "CGA4K16.COM"

V15C_EXE_SHA256 = (
    "765ef52aab2e3ddc4c0dea95939b081e115b47bebb8c0aa152225108b0b81505"
)
V15C_COM_SHA256 = (
    "ede3a1c0aa8dc7290d233090dc6ba5183d87b871e6bc820fb714a08b372b59bc"
)
SOURCE_KID_SHA256 = (
    "2eaa798041c090a6d54cd0dce4ae770e3da400ef95540cec7ed0ff9db5c2af73"
)
BASELINE_KID_SHA256 = (
    "f43f0bf4290fead7cea0285903e4013c41d962c4e82915d8b6d9f50b5f6fa762"
)
V15C_KID_SHA256 = (
    "2b5a930ac53121742f26541aea710348c0a69945e98a5de8f1cb503c091d62b4"
)
V15C_PHASE_SHA256 = (
    "4552e0d15448b54823e1d4bd58c8813675e893df059eb00fecf7cf10354546c0"
)

NEW_GAME_FRAMES = tuple(range(102, 110))
NEW_IMAGE_IDS = tuple(range(112, 120))
NEW_NORMAL_RESOURCE_IDS = tuple(401 + image_id for image_id in NEW_IMAGE_IDS)
OLD_SELECTED_IMAGE_IDS = tuple(
    list(range(0, 44)) + list(range(44, 52)) + list(range(64, 77))
)
ALL_SELECTED_IMAGE_IDS = OLD_SELECTED_IMAGE_IDS + NEW_IMAGE_IDS

RIGHT_P2_ALIAS = 195
LEFT_P0_ALIAS = 203
LEFT_P2_ALIAS = 211
PHASE_HEADER_RESOURCE_ID = 1000
PHASE_FINAL_RESOURCE_ID = 1219


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_exact(data: bytes, old: bytes, new: bytes, expected: int = 1) -> bytes:
    if len(old) != len(new):
        raise ValueError("binary replacement must preserve length")
    count = data.count(old)
    if count != expected:
        raise ValueError(f"expected {expected} occurrence(s) of {old!r}, found {count}")
    return data.replace(old, new)


def load_art_module() -> object:
    if not ART_TOOL.is_file():
        raise ValueError(f"missing verified artwork tool: {ART_TOOL}")
    spec = importlib.util.spec_from_file_location("v16_art", ART_TOOL)
    if spec is None or spec.loader is None:
        raise ValueError("could not load verified artwork tool")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    module.SELECTED_FRAME_IMAGE_RANGES = (
        ("fall_landing_crouch", 102, 109, 112, 119),
    )
    module.SELECTED_IMAGE_IDS = NEW_IMAGE_IDS
    module.STORED_ODD_ALIAS_BASE = RIGHT_P2_ALIAS
    module.MIRRORED_EVEN_ALIAS_BASE = LEFT_P0_ALIAS
    module.MIRRORED_ODD_ALIAS_BASE = LEFT_P2_ALIAS
    module.PRIVATE_VARIANTS = (
        ("right-odd", RIGHT_P2_ALIAS, "right", 2, False),
        ("left-even", LEFT_P0_ALIAS, "left", 0, True),
        ("left-odd", LEFT_P2_ALIAS, "left", 2, True),
    )

    def selected_image_ordinal(image_id: int) -> int:
        if 112 <= image_id <= 119:
            return image_id - 112
        raise ValueError(f"Kid image ID {image_id} is not in the V16 block")

    module.selected_image_ordinal = selected_image_ordinal
    return module


def generate_artwork(art: object) -> tuple[Path, dict[str, object], dict[str, object]]:
    if sha256_file(SOURCE_KID) != SOURCE_KID_SHA256:
        raise ValueError("unexpected original VGA KID.DAT")
    if sha256_file(BASELINE_KID) != BASELINE_KID_SHA256:
        raise ValueError("unexpected Exhaustive phase-0 baseline KID.DAT")
    if ART_WORK.exists():
        shutil.rmtree(ART_WORK)
    ART_WORK.mkdir(parents=True)
    generated = ART_WORK / "V16-EIGHT-POSE-COMBINED-KID.DAT"
    metadata, variants = art.build_four_way_dat(
        SOURCE_KID,
        BASELINE_KID,
        generated,
    )
    return generated, metadata, variants


class Rel8Builder:
    """Small local 8086 assembler for the selector extension."""

    def __init__(self, base: int) -> None:
        self.base = base
        self.code = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[int, str]] = []

    @property
    def address(self) -> int:
        return self.base + len(self.code)

    def emit(self, data: bytes) -> None:
        self.code.extend(data)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate mapper label {name}")
        self.labels[name] = self.address

    def branch(self, opcode: int, label: str) -> None:
        self.code.extend((opcode, 0))
        self.fixups.append((len(self.code) - 1, label))

    def jump_absolute(self, target: int) -> None:
        displacement = target - (self.address + 2)
        if not -128 <= displacement <= 127:
            raise ValueError("absolute short jump is out of range")
        self.code.extend((0xEB, displacement & 0xFF))

    def finish(self) -> bytes:
        for displacement_index, label in self.fixups:
            if label not in self.labels:
                raise ValueError(f"missing mapper label {label}")
            instruction_end = self.base + displacement_index + 1
            displacement = self.labels[label] - instruction_end
            if not -128 <= displacement <= 127:
                raise ValueError(f"short branch to {label} is out of range")
            self.code[displacement_index] = displacement & 0xFF
        return bytes(self.code)


def build_fall_mapper() -> bytes:
    """Map KID images 112..119 into the final three alias ranges.

    Entry state is the proven V14/V15C common mapper state: CX is the KID
    image ID and DX is the old variant base (0, 65, or 130). Images below 77
    have already been handled by the original mapper. All other images retain
    ordinary KID fallback except the new 112..119 block.
    """

    mapper_start = 0x23C3B
    fetch_variant = 0x23C1D
    selector_done = 0x23C87
    b = Rel8Builder(mapper_start)
    b.emit(bytes.fromhex("83 f9 70"))          # CMP CX,112
    b.branch(0x72, "fallback")                # JB fallback
    b.emit(bytes.fromhex("83 f9 78"))          # CMP CX,120
    b.branch(0x73, "fallback")                # JAE fallback
    b.emit(bytes.fromhex("83 e9 70"))          # CX = ordinal 0..7
    b.emit(bytes.fromhex("83 fa 00"))          # old base 0 = right/P2
    b.branch(0x74, "right_p2")
    b.emit(bytes.fromhex("83 fa 41"))          # old base 65 = left/P0
    b.branch(0x74, "left_p0")
    b.emit(b"\xba" + struct.pack("<H", LEFT_P2_ALIAS))
    b.branch(0xEB, "add_alias")
    b.label("right_p2")
    b.emit(b"\xba" + struct.pack("<H", RIGHT_P2_ALIAS))
    b.branch(0xEB, "add_alias")
    b.label("left_p0")
    b.emit(b"\xba" + struct.pack("<H", LEFT_P0_ALIAS))
    b.label("add_alias")
    b.emit(bytes.fromhex("03 ca"))             # CX += DX
    b.jump_absolute(fetch_variant)
    b.label("fallback")
    b.jump_absolute(selector_done)
    return b.finish()


def selector_alias(image_id: int, variant: str) -> int | None:
    old_bases = {"right-p2": 0, "left-p0": 65, "left-p2": 130}
    new_bases = {
        "right-p2": RIGHT_P2_ALIAS,
        "left-p0": LEFT_P0_ALIAS,
        "left-p2": LEFT_P2_ALIAS,
    }
    if variant not in old_bases:
        raise ValueError(f"unknown selector variant {variant}")
    if 0 <= image_id <= 51:
        return old_bases[variant] + image_id
    if 64 <= image_id <= 76:
        return old_bases[variant] + image_id - 12
    if 112 <= image_id <= 119:
        return new_bases[variant] + image_id - 112
    return None


def patch_executable() -> tuple[bytes, dict[str, object]]:
    source = V15C / "P4KX5C.EXE"
    data = source.read_bytes()
    if sha256_bytes(data) != V15C_EXE_SHA256:
        raise ValueError("unexpected V15C executable")

    # V15C sends image IDs >=77 to ordinary fallback. Send them into the
    # reclaimed guard area, where V16 accepts exactly IDs 112..119.
    branch_offset = 0x23C16
    mapper_start = 0x23C3B
    if data[branch_offset:branch_offset + 2] != bytes.fromhex("73 6c"):
        raise ValueError("unexpected V15C upper-range selector branch")
    displacement = mapper_start - (branch_offset + 2)
    data = data[:branch_offset] + bytes((0x73, displacement)) + data[branch_offset + 2:]

    mapper_end = 0x23C74
    mapper = build_fall_mapper()
    if len(mapper) > mapper_end - mapper_start:
        raise ValueError("V16 fall mapper does not fit the reclaimed guard area")
    if data[mapper_start:mapper_end] != b"\x90" * (mapper_end - mapper_start):
        raise ValueError("V15C reclaimed selector area is not empty")
    data = (
        data[:mapper_start]
        + mapper
        + b"\x90" * (mapper_end - mapper_start - len(mapper))
        + data[mapper_end:]
    )
    data = replace_exact(data, b"KID TABLE V15C", b"KID TABLE V16F")

    if len(data) != 146708 or data[:2] != b"MZ":
        raise ValueError("V16 executable size/header changed")
    if data[0x23C39:0x23C3B] != bytes.fromhex("eb 39"):
        raise ValueError("live-pointer handoff no longer skips the mapper area")
    if data[0x23C1D:0x23C21] != bytes.fromhex("8b 36 3a 45"):
        raise ValueError("selector no longer reads live native slot 3")
    if data[0x23CD1:0x23CD7] != b"\x90" * 6:
        raise ValueError("native phase slot detachment returned")

    # Exhaustively verify the intended alias contract.
    for image_id in range(216):
        for variant in ("right-p2", "left-p0", "left-p2"):
            alias = selector_alias(image_id, variant)
            if alias is not None and not 0 <= alias <= 218:
                raise ValueError("selector emitted an out-of-range alias")
    expected_new = {
        "right-p2": list(range(195, 203)),
        "left-p0": list(range(203, 211)),
        "left-p2": list(range(211, 219)),
    }
    for variant, expected in expected_new.items():
        actual = [selector_alias(image_id, variant) for image_id in NEW_IMAGE_IDS]
        if actual != expected:
            raise ValueError(f"bad V16 aliases for {variant}: {actual}")

    return data, {
        "file": OUTPUT_EXE,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "visible_ctrl_v_marker": "KID TABLE V16F    V1.3",
        "baseline": "runtime-confirmed V15C",
        "draw_table": "live native chtab slot 3 at DS:453A",
        "mapper_file_range": f"0x{mapper_start:X}..0x{mapper_end - 1:X}",
        "mapper_bytes": len(mapper),
        "old_coverage_preserved": True,
        "new_image_ids": list(NEW_IMAGE_IDS),
        "new_alias_ranges": expected_new,
        "native_slot_detached": False,
        "runtime_transforms": False,
        "cpu": "8086/8088 compatible",
    }


def patch_launcher() -> tuple[bytes, dict[str, object]]:
    source = V15C / "CGA4K5C.COM"
    data = source.read_bytes()
    if sha256_bytes(data) != V15C_COM_SHA256:
        raise ValueError("unexpected V15C launcher")
    data = replace_exact(data, b"P4KX5C.EXE", b"P4KX16.EXE", expected=3)
    data = replace_exact(data, b"V15C", b"V16F")
    if b"KID PHASE TABLE V16F ACTIVE" not in data:
        raise ValueError("V16 launcher banner patch failed")
    return data, {
        "file": OUTPUT_COM,
        "bytes": len(data),
        "sha256": sha256_bytes(data),
        "child": OUTPUT_EXE,
        "banner": "KID PHASE TABLE V16F ACTIVE",
    }


def build_final_dats(
    art: object,
    generated_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    v15c_kid_path = V15C / "KID.DAT"
    v15c_phase_path = V15C / "PHASE.DAT"
    if sha256_file(v15c_kid_path) != V15C_KID_SHA256:
        raise ValueError("unexpected V15C KID.DAT")
    if sha256_file(v15c_phase_path) != V15C_PHASE_SHA256:
        raise ValueError("unexpected V15C PHASE.DAT")

    old_kid = art.DatArchive.open(v15c_kid_path)
    old_phase = art.DatArchive.open(v15c_phase_path)
    generated = art.DatArchive.open(generated_path)
    if not all(resource.checksum_ok for archive in (old_kid, old_phase, generated) for resource in archive.resources):
        raise ValueError("input DAT checksum failure")

    old_kid_map = {resource.resource_id: resource.data for resource in old_kid.resources}
    old_phase_map = {resource.resource_id: resource.data for resource in old_phase.resources}
    generated_map = {resource.resource_id: resource.data for resource in generated.resources}
    if set(old_kid_map) != set(range(400, 620)):
        raise ValueError("V15C KID.DAT is not the expected 220-resource archive")
    if set(old_phase_map) != set(range(1000, 1196)):
        raise ValueError("V15C PHASE.DAT is not the expected 196-resource sidecar")

    final_kid_map = dict(old_kid_map)
    for resource_id in NEW_NORMAL_RESOURCE_IDS:
        final_kid_map[resource_id] = generated_map[resource_id]
    final_kid = art._build_dat(sorted(final_kid_map.items()))
    (OUT / "KID.DAT").write_bytes(final_kid)

    final_phase_map = dict(old_phase_map)
    for resource_id in range(1196, 1220):
        final_phase_map[resource_id] = generated_map[resource_id]
    final_phase = art._build_dat(sorted(final_phase_map.items()))
    (OUT / "PHASE.DAT").write_bytes(final_phase)

    kid_check = art.DatArchive.open(OUT / "KID.DAT")
    phase_check = art.DatArchive.open(OUT / "PHASE.DAT")
    if not all(resource.checksum_ok for archive in (kid_check, phase_check) for resource in archive.resources):
        raise ValueError("final DAT checksum verification failed")
    if [resource.resource_id for resource in kid_check.resources] != list(range(400, 620)):
        raise ValueError("final KID resource order changed")
    if [resource.resource_id for resource in phase_check.resources] != list(range(1000, 1220)):
        raise ValueError("final PHASE resource order is not exactly 1000..1219")
    if phase_check.resources[0].data[0] != 219:
        raise ValueError("final PHASE header does not declare 219 images")

    # Every old normal/private payload is byte-identical except the eight new
    # normal images, and every new payload is exactly the optimizer result.
    new_normal_set = set(NEW_NORMAL_RESOURCE_IDS)
    for resource in kid_check.resources:
        before = old_kid_map[resource.resource_id]
        if resource.resource_id not in new_normal_set and resource.data != before:
            raise ValueError(f"unrelated KID resource changed: {resource.resource_id}")
        if resource.resource_id in new_normal_set and resource.data != generated_map[resource.resource_id]:
            raise ValueError(f"new KID resource mismatch: {resource.resource_id}")
    for resource_id, before in old_phase_map.items():
        if phase_check.analysis_by_id(resource_id).resource.data != before:
            raise ValueError(f"old PHASE resource changed: {resource_id}")
    for resource_id in range(1196, 1220):
        if phase_check.analysis_by_id(resource_id).resource.data != generated_map[resource_id]:
            raise ValueError(f"new PHASE resource mismatch: {resource_id}")

    # Structural and mask verification for all 219 sidecar images.
    source = art.DatArchive.open(SOURCE_KID)
    invalid_headers: list[int] = []
    mask_failures: list[int] = []
    for alias in range(219):
        resource_id = 1001 + alias
        analysis = phase_check.analysis_by_id(resource_id)
        if analysis is None or analysis.image is None:
            invalid_headers.append(resource_id)
            continue
        image = analysis.image
        if not (0 < image.width <= 256 and 0 < image.height <= 256 and image.bits == 4):
            invalid_headers.append(resource_id)
    for image_id in NEW_IMAGE_IDS:
        source_analysis = source.analysis_by_id(401 + image_id)
        if source_analysis is None or source_analysis.image is None:
            raise ValueError(f"source image missing for mask verification: {image_id}")
        source_mask = tuple(value == 0 for value in source_analysis.image.pixels)
        variant_ids = (
            401 + image_id,
            1001 + RIGHT_P2_ALIAS + image_id - 112,
            1001 + LEFT_P0_ALIAS + image_id - 112,
            1001 + LEFT_P2_ALIAS + image_id - 112,
        )
        for resource_id in variant_ids:
            archive = kid_check if resource_id < 1000 else phase_check
            analysis = archive.analysis_by_id(resource_id)
            if analysis is None or analysis.image is None:
                mask_failures.append(resource_id)
                continue
            candidate_mask = tuple(value == 0 for value in analysis.image.pixels)
            if candidate_mask != source_mask:
                mask_failures.append(resource_id)
    if invalid_headers:
        raise ValueError(f"invalid PHASE image headers: {invalid_headers}")
    if mask_failures:
        raise ValueError(f"V16 transparency-mask failures: {mask_failures}")

    kid_meta = {
        "file": "KID.DAT",
        "bytes": len(final_kid),
        "sha256": sha256_bytes(final_kid),
        "resource_count": len(kid_check.resources),
        "new_right_p0_resources": list(NEW_NORMAL_RESOURCE_IDS),
        "unrelated_resources_byte_identical_to_v15c": True,
        "all_checksums_valid": True,
    }
    phase_meta = {
        "file": "PHASE.DAT",
        "bytes": len(final_phase),
        "sha256": sha256_bytes(final_phase),
        "resource_count": len(phase_check.resources),
        "resource_id_range": "1000..1219",
        "declared_image_count": 219,
        "image_slots_used": 219,
        "image_slots_remaining": 0,
        "old_resources_byte_identical_to_v15c": True,
        "new_resources": "1196..1219",
        "all_checksums_valid": True,
        "all_image_headers_valid": True,
    }
    return kid_meta, phase_meta


def render_visuals(art: object, generated_path: Path) -> list[str]:
    # The V13 renderer imports the artwork module by its historical name.
    sys.modules["make_four_way_kid"] = art
    spec = importlib.util.spec_from_file_location("v16_render", RENDER_TOOL)
    if spec is None or spec.loader is None:
        raise ValueError("could not load visual verification renderer")
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    source = art.DatArchive.open(SOURCE_KID)
    candidate = art.DatArchive.open(generated_path)
    visual_dir = OUT / "visual-verification"
    fall_sheet = visual_dir / "VISUAL-FALL-LANDING.png"
    renderer.contact_sheet(
        source,
        candidate,
        NEW_IMAGE_IDS,
        "Prince Exhaustive Phase Verification - FALL / LANDING",
        "Frames 102-109 / images 112-119. Four independent final-display waveforms; no dither.",
        fall_sheet,
    )
    outputs = [fall_sheet.name]
    for direction in ("right", "left"):
        path = visual_dir / f"VISUAL-FALL-LANDING-{direction.upper()}-PHASE-TOGGLE.gif"
        renderer.phase_toggle_gif(candidate, NEW_IMAGE_IDS, direction, path)
        outputs.append(path.name)
    return outputs


def make_zip(source_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    fixed_time = (2026, 8, 24, 21, 0, 0)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            relative = Path(PACKAGE_NAME) / path.relative_to(source_dir)
            info = zipfile.ZipInfo(relative.as_posix(), fixed_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                path.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


README_TEMPLATE = """PRINCE OF PERSIA 1.3 - PHASE-AWARE FALL / LANDING V16F
==============================================================

PURPOSE
-------

V16F preserves the runtime-confirmed V15C live native-table architecture and
adds phase-aware fall and landing graphics. The new coverage is:

  game frames 102..105   KID images 112..115   start of fall
  game frame  106        KID image  116        sustained freefall
  game frames 107..108   KID images 117..118   landing
  game frame  109        KID image  119        crouched landing pose

Each pose has four independently optimized final-display cases: right/P0,
right/P2, left/P0, and left/P2. The normal KID table supplies right/P0.
PHASE.DAT supplies the other three cases.

INSTALLATION
------------

1. Use a clean copy of the intended New-CGA Prince 1.3 directory, or the
   working V15C directory.
2. Copy CGA4K16.COM, P4KX16.EXE, KID.DAT, and PHASE.DAT into it.
3. Keep all four files together. Do not mix V15C and V16F files.
4. Run CGA4K16.COM. Do not run P4KX16.EXE directly.
5. Press Ctrl-V in game and confirm:

       KID TABLE V16F    V1.3

   The launcher must print:

       KID PHASE TABLE V16F ACTIVE

PHASE.DAT must be exactly {phase_bytes:,} bytes with SHA-256:

  {phase_sha256}

TEST ROUTE
----------

Regression-test stand, run, both turns, standing jump, and running jump in
both directions at adjacent X positions. Those V15C motions must remain
unchanged.

For the new block:

  * step off a ledge in both directions;
  * run off a ledge in both directions;
  * let standing and running jumps transition into a fall;
  * test both a short fall and a sustained freefall;
  * soft-land and medium-land at adjacent X positions;
  * hold the crouched landing pose before standing.

The Prince should retain the same intended color family across even/odd final
screen X. Hard-landing death and the stand-up-from-crouch animation are not
part of V16F and still use their ordinary phase-0 baseline graphics.

ARCHITECTURE
------------

  baseline            runtime-confirmed V15C
  storage             separate standard PHASE.DAT
  loading             Prince's own load_chtab into live native slot 3
  drawing             Prince's original conversion/flip/draw path
  runtime transforms  none
  custom DOS I/O      none
  CPU                  8086/8088 compatible

PHASE TABLE
-----------

  existing right/P2       aliases   0..64
  existing left/P0        aliases  65..129
  existing left/P2        aliases 130..194
  fall/landing right/P2   aliases 195..202
  fall/landing left/P0    aliases 203..210
  fall/landing left/P2    aliases 211..218

All 219 image aliases are now occupied. The next phase-aware motion family
requires a second native table or another verified storage layout.
"""


def main() -> None:
    required = (V15C, SOURCE_KID, BASELINE_KID, ART_TOOL, RENDER_TOOL)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"missing V16 build inputs: {missing}")

    if OUT.exists():
        shutil.rmtree(OUT)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(V15C, OUT)

    for stale in (
        "P4KX5C.EXE",
        "CGA4K5C.COM",
        "KID-V15C-README.TXT",
        "KID-V15C-VERIFICATION.TXT",
        "KID-V15C-MANIFEST.JSON",
    ):
        path = OUT / stale
        if path.exists():
            path.unlink()

    art = load_art_module()
    generated, artwork_meta, variants = generate_artwork(art)
    kid_meta, phase_meta = build_final_dats(art, generated)
    executable, executable_meta = patch_executable()
    launcher, launcher_meta = patch_launcher()
    (OUT / OUTPUT_EXE).write_bytes(executable)
    (OUT / OUTPUT_COM).write_bytes(launcher)
    visual_files = render_visuals(art, generated)

    readme = README_TEMPLATE.format(
        phase_bytes=phase_meta["bytes"],
        phase_sha256=phase_meta["sha256"],
    )
    (OUT / "README.TXT").write_text(readme, encoding="ascii", newline="\r\n")
    (OUT / "KID-V16F-README.TXT").write_text(readme, encoding="ascii", newline="\r\n")

    manifest = {
        "package": PACKAGE_NAME,
        "status": (
            "V16F static/resource/visual verification passed; "
            "DOS runtime verification pending"
        ),
        "baseline": {
            "version": "V15C live native table",
            "runtime_status": "all covered motions confirmed working by user",
        },
        "scope": {
            "action": "fall start, sustained freefall, landing, crouch",
            "game_frames": "102..109",
            "kid_image_ids": list(NEW_IMAGE_IDS),
            "kid_resource_ids": list(NEW_NORMAL_RESOURCE_IDS),
            "new_unique_images": len(NEW_IMAGE_IDS),
            "total_phase_aware_unique_images": len(ALL_SELECTED_IMAGE_IDS),
            "new_final_display_cases": len(NEW_IMAGE_IDS) * 4,
            "total_final_display_cases": len(ALL_SELECTED_IMAGE_IDS) * 4,
        },
        "conversion": {
            "source": "verified original VGA KID.DAT",
            "profile": "new-cga",
            "algorithm": "Exhaustive exact 2,048-state row dynamic program",
            "dither": "none",
            "phase_variants": [0, 2],
            "direction_variants": ["right", "left"],
            "independent_final_display_optimization": True,
            "source_kid_sha256": SOURCE_KID_SHA256,
            "phase0_baseline_sha256": BASELINE_KID_SHA256,
            "artwork_generator_metadata": artwork_meta,
        },
        "runtime_architecture": {
            "sidecar": "PHASE.DAT",
            "sidecar_is_standard_prince_dat": True,
            "loader": "Prince load_chtab",
            "native_slot": 3,
            "native_slot_kept_live": True,
            "selector": "V15C direct live-slot selector plus V16 range mapper",
            "runtime_transform": False,
            "custom_dos_io": False,
        },
        "alias_map": {
            "existing_right_p2": [0, 64],
            "existing_left_p0": [65, 129],
            "existing_left_p2": [130, 194],
            "fall_right_p2": [195, 202],
            "fall_left_p0": [203, 210],
            "fall_left_p2": [211, 218],
            "remaining_aliases": 0,
        },
        "executable": executable_meta,
        "launcher": launcher_meta,
        "kid_dat": kid_meta,
        "phase_dat": phase_meta,
        "new_variants": variants,
        "visual_verification": visual_files,
        "next_architecture_boundary": (
            "a second native table or another verified storage layout is "
            "required before adding another motion family"
        ),
    }
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    (OUT / "KID-V16F-MANIFEST.JSON").write_text(manifest_text, encoding="utf-8")

    verification = f"""Prince of Persia 1.3 V16F Fall/Landing Verification
=========================================================
EXE PASS    {OUTPUT_EXE}: {executable_meta['bytes']} bytes, SHA-256 {executable_meta['sha256']}
LIVE PASS   Selector still reads native chtab slot 3 directly at DS:453A
KEEP PASS   Native slot 3 is not detached after PHASE.DAT loads
MAP PASS    Images 112..119 map to aliases 195..218 in three disjoint ranges
OLD PASS    All 65 previously covered KID images retain their V15C mapping
COM PASS    {OUTPUT_COM}: child={OUTPUT_EXE}, SHA-256 {launcher_meta['sha256']}
KID PASS    8 new right/P0 images; SHA-256 {kid_meta['sha256']}
SIDE PASS   PHASE.DAT: 220/220 resources, SHA-256 {phase_meta['sha256']}
IMAGE PASS  219/219 sidecar image headers decode correctly
MASK PASS   32/32 new direction/phase cases preserve exact source transparency
VIS PASS    Fall/landing contact sheet and both phase-toggle GIFs rendered

STATIC VERIFICATION PASSED.
DOS runtime verification is still required.
"""
    (OUT / "KID-V16F-VERIFICATION.TXT").write_text(
        verification,
        encoding="ascii",
        newline="\r\n",
    )

    tools_dir = OUT / "tools"
    tools_dir.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), tools_dir / Path(__file__).name)

    package_manifest = {**manifest, "files": {}}
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

    checksum_lines = []
    for path in sorted(OUT.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.TXT":
            checksum_lines.append(
                f"{sha256_file(path)}  {path.relative_to(OUT).as_posix()}"
            )
    (OUT / "SHA256SUMS.TXT").write_text(
        "\n".join(checksum_lines) + "\n",
        encoding="ascii",
    )

    make_zip(OUT, ZIP_PATH)
    print(
        json.dumps(
            {
                "package_dir": str(OUT),
                "zip": str(ZIP_PATH),
                "zip_bytes": ZIP_PATH.stat().st_size,
                "zip_sha256": sha256_file(ZIP_PATH),
                "exe": executable_meta,
                "launcher": launcher_meta,
                "kid_dat": kid_meta,
                "phase_dat": phase_meta,
                "visual_verification": visual_files,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
