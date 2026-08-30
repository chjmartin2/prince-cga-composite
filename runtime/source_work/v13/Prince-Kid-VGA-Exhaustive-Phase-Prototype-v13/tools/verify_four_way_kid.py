#!/usr/bin/env python3
"""Static, structural, and image-level checks for the V13 Exhaustive Kid build."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from make_four_way_kid import (  # noqa: E402
    CHILD_NAME,
    CAVE_OFFSET,
    CONVERSION_MODE,
    EXPECTED_PHASE0_BASELINE_KID_SHA256,
    EXPECTED_SOURCE_KID_SHA256,
    HEAP_RESERVE_BYTES,
    HIGH_CODE_LINEAR,
    HIGH_CODE_SEGMENT,
    HOOK_OFFSET,
    HOOK_SIGNATURE,
    KID_TABLE_AUXILIARY_OFFSET,
)

# Keep the import readable while retaining compatibility with the standalone
# release layout, where make_four_way_kid.py is beside this verifier.
from make_four_way_kid import (  # noqa: E402
    LOAD_HOOK_OFFSET,
    MIRRORED_EVEN_ALIAS_BASE,
    MIRRORED_ODD_ALIAS_BASE,
    ORIGINAL_TOTAL_PARAGRAPHS,
    OUTPUT_COM,
    OUTPUT_DAT,
    OUTPUT_EXE,
    PHASE_CONSISTENCY,
    PRIVATE_RESOURCE_BASE,
    PRIVATE_TABLES,
    PRIVATE_VARIANTS,
    PROTOTYPE_BANNER,
    PROTOTYPE_VERSION,
    SELECTED_FRAME_IMAGE_RANGES,
    SELECTED_IMAGE_IDS,
    SELECTOR_HOOK_OFFSET,
    SELECTOR_HOOK_SIGNATURE,
    SLOT_STORED_ODD,
    SOURCE_DISPLAY_MODE,
    STARTUP_HEAP_HOOK_LOGICAL_OFFSET,
    STARTUP_HEAP_HOOK_OFFSET,
    STARTUP_HEAP_HOOK_SEGMENT,
    STARTUP_HEAP_SIGNATURE,
    STORED_ODD_ALIAS_BASE,
    VERSION_OFFSET,
    WORKSPACE,
    build_high_code,
    mz_load_module,
    patch_executable,
    patch_prototype_launcher,
    reverse_mode6_cga_pixel_rows,
    runtime_display_bits,
    selected_image_ordinal,
    sha256,
    unpack_exepack,
)
from composite_project import initial_mode6_bits  # noqa: E402
from composite_signal import render_composite_artifacts  # noqa: E402
from prince_dat import (  # noqa: E402
    COMPOSITE_PROFILE_NEW,
    DatArchive,
    hardware_palette_for_resource,
    mode6_width,
)


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def declared_mz_size(data: bytes) -> int:
    tail = u16(data, 2)
    pages = u16(data, 4)
    return pages * 512 if tail == 0 else (pages - 1) * 512 + tail


def relocation_records(executable: bytes) -> list[tuple[int, int]]:
    count = u16(executable, 6)
    table = u16(executable, 0x18)
    return [
        struct.unpack_from("<HH", executable, table + index * 4)
        for index in range(count)
    ]


def verify_executable(prince: Path, output: Path) -> None:
    baseline = unpack_exepack(prince.read_bytes())
    expected, metadata = patch_executable(baseline)
    candidate = (output / OUTPUT_EXE).read_bytes()
    if candidate != expected:
        raise ValueError(f"{OUTPUT_EXE} differs from the deterministic patch")
    if candidate[:2] != b"MZ" or declared_mz_size(candidate) != len(candidate):
        raise ValueError("patched MZ size fields are invalid")

    header_size, module = mz_load_module(candidate)
    baseline_header_size, baseline_module = mz_load_module(baseline)
    if header_size != baseline_header_size:
        raise ValueError("MZ header size changed")
    if (
        baseline_module[
            SELECTOR_HOOK_OFFSET : SELECTOR_HOOK_OFFSET
            + len(SELECTOR_HOOK_SIGNATURE)
        ]
        != SELECTOR_HOOK_SIGNATURE
    ):
        raise ValueError("baseline pre-conversion selector signature is invalid")
    module_paragraphs = (len(module) + 15) // 16
    if module_paragraphs + u16(candidate, 0x0A) != ORIGINAL_TOTAL_PARAGRAPHS:
        raise ValueError("minimum DOS allocation changed")
    if HIGH_CODE_LINEAR != (u16(candidate, 0x0E) * 16 + u16(candidate, 0x10)):
        raise ValueError("high code does not begin at the unused initial stack top")
    if len(module) > ORIGINAL_TOTAL_PARAGRAPHS * 16:
        raise ValueError("high code extends beyond the unchanged allocation")

    high_code, labels, high_relocations = build_high_code()
    if module[HIGH_CODE_LINEAR : HIGH_CODE_LINEAR + len(high_code)] != high_code:
        raise ValueError("high selector/loader code mismatch")
    selector = high_code[labels["selector"] : labels["load_variants"]]
    exact_selector_signatures = (
        ("ff 76 f2 9a 16 c7 00 00", 1, "post-scale screen-X conversion"),
        ("c4 5e fa 26 2b 47 02", 1, "right-facing width adjustment"),
        ("a8 01", 2, "two direction-specific parity tests"),
        ("ba 00 00", 1, "right/odd alias base"),
        ("ba 40 00", 1, "left/even alias base"),
        ("ba 80 00", 1, "left/odd alias base"),
        ("03 ca", 1, "ordinal-plus-alias mapping"),
        ("bb 03 00", 1, "single packed slot-3 selection"),
        ("8b d9 d1 e3 d1 e3 03 de", 1, "private image pointer mapping"),
        ("8b f8 0b c2", 1, "non-destructive private-pointer null test"),
        (
            "89 7e e6 89 56 e8 89 7e fa 89 56 fc",
            1,
            "raw color/mask pointer assignment",
        ),
    )
    for signature, count, label in exact_selector_signatures:
        if selector.count(bytes.fromhex(signature)) != count:
            raise ValueError(f"selector has the wrong {label}")
    for signature, label in (
        ("83 f9 0f", "selected IDs 0..14"),
        ("83 f9 2c", "selected range lower bound 44"),
        ("83 f9 34", "selected range upper bound 51"),
        ("83 f9 40", "selected range lower bound 64"),
        ("83 f9 4d", "selected range upper bound 76"),
        ("83 e9 1d", "44..51 ordinal conversion"),
        ("83 e9 29", "64..76 ordinal conversion"),
    ):
        if selector.count(bytes.fromhex(signature)) != 1:
            raise ValueError(f"selector omits {label}")
    if bytes.fromhex("bb 04 00") in selector or bytes.fromhex("bb 09 00") in selector:
        raise ValueError("selector still depends on volatile private slots 4 or 9")
    if bytes.fromhex("83 7e f6 10") in selector:
        raise ValueError("selector still excludes non-10h Kid animation blitters")
    if bytes.fromhex("8b ca") in selector:
        raise ValueError("selector unexpectedly uses fixed diagnostic aliases")
    if bytes.fromhex("8b 04 d1 e8 03 d8") in selector:
        raise ValueError("selector attempts an invalid second-half mask lookup")
    if selector.count(b"\x9a") != 1:
        raise ValueError("selector has an unexpected far call")

    load_one_signature = (
        bytes.fromhex("50 53 b8 14 04 50 b8 80 00 50 b8")
        + struct.pack("<H", KID_TABLE_AUXILIARY_OFFSET)
        + bytes.fromhex("50 9a 2d 15 00 00 c3")
    )
    load_one_offset = labels["load_one"]
    if high_code[
        load_one_offset : load_one_offset + len(load_one_signature)
    ] != load_one_signature:
        raise ValueError("private loader does not use Prince's DS:18BE Kid argument")
    if any(module[len(baseline_module) : HIGH_CODE_LINEAR]):
        raise ValueError("load-module padding before high code is not zero")

    expected_trampoline = (
        b"\x9a"
        + struct.pack("<HH", labels["selector"], HIGH_CODE_SEGMENT)
        + bytes.fromhex("83 7e ea 02 c3")
    )
    if module[CAVE_OFFSET : CAVE_OFFSET + len(expected_trampoline)] != expected_trampoline:
        raise ValueError("selector trampoline mismatch")
    draw_displacement = u16(module, SELECTOR_HOOK_OFFSET + 1)
    if (
        module[SELECTOR_HOOK_OFFSET] != 0xE8
        or module[SELECTOR_HOOK_OFFSET + 3] != 0x90
        or (SELECTOR_HOOK_OFFSET + 3 + draw_displacement) & 0xFFFF != CAVE_OFFSET
    ):
        raise ValueError("draw hook does not target its verified trampoline")
    if (
        module[HOOK_OFFSET : HOOK_OFFSET + len(HOOK_SIGNATURE)]
        != baseline_module[HOOK_OFFSET : HOOK_OFFSET + len(HOOK_SIGNATURE)]
    ):
        raise ValueError("Prince's proven B641 native-flip path was modified")

    expected_load_hook = b"\x9a" + struct.pack(
        "<HH", labels["load_variants"], HIGH_CODE_SEGMENT
    )
    if module[LOAD_HOOK_OFFSET : LOAD_HOOK_OFFSET + 5] != expected_load_hook:
        raise ValueError("level sprite-loader hook mismatch")
    expected_heap_hook = (
        b"\x9a"
        + struct.pack("<HH", labels["reserve_heap"], HIGH_CODE_SEGMENT)
        + b"\x90" * (len(STARTUP_HEAP_SIGNATURE) - 5)
    )
    if module[
        STARTUP_HEAP_HOOK_OFFSET : STARTUP_HEAP_HOOK_OFFSET
        + len(STARTUP_HEAP_SIGNATURE)
    ] != expected_heap_hook:
        raise ValueError("startup heap reservation hook mismatch")
    reserve_routine = (
        bytes.fromhex("8b c4")
        + b"\x05"
        + struct.pack("<H", HEAP_RESERVE_BYTES + 4)
        + bytes.fromhex("36 a3 fe 2d 36 a3 fa 2d cb")
    )
    reserve_offset = labels["reserve_heap"]
    if high_code[reserve_offset : reserve_offset + len(reserve_routine)] != reserve_routine:
        raise ValueError("startup heap reservation routine mismatch")
    if module[VERSION_OFFSET : VERSION_OFFSET + len(PROTOTYPE_VERSION)] != PROTOTYPE_VERSION:
        raise ValueError("Ctrl-V prototype marker mismatch")

    records = relocation_records(candidate)
    required = {
        (LOAD_HOOK_OFFSET + 3, 0),
        (CAVE_OFFSET + 3, 0),
        (STARTUP_HEAP_HOOK_LOGICAL_OFFSET + 3, STARTUP_HEAP_HOOK_SEGMENT),
        *((offset, HIGH_CODE_SEGMENT) for offset in high_relocations),
    }
    if (
        not required.issubset(set(records))
        or len(records) != len(relocation_records(baseline)) + len(required)
    ):
        raise ValueError("new far-call MZ relocations are incomplete")

    for signature, label in (
        (b"\xcd\x2f", "multiplex/XMS interrupt"),
        (b"\xcd\x67", "EMS interrupt"),
        (b"\xcd\x31", "DPMI interrupt"),
    ):
        if signature in high_code:
            raise ValueError(f"custom code contains forbidden {label}")
    expected_0f_offsets = {
        selector.index(bytes.fromhex("83 f9 0f")) + 2,
        selector.index(bytes.fromhex("83 f9 34 72 0f")) + 4,
        selector.index(bytes.fromhex("83 f9 4d 73 0f")) + 4,
    }
    actual_0f_offsets = {offset for offset, value in enumerate(selector) if value == 0x0F}
    if actual_0f_offsets != expected_0f_offsets or high_code.count(b"\x0f") != 3:
        raise ValueError("custom code contains an unexpected 0F byte / 286+ opcode")

    print(
        f"verified {OUTPUT_EXE}: {len(candidate)} bytes, {len(high_code)} injected "
        f"8086 bytes, one packed private table, allocation="
        f"{ORIGINAL_TOTAL_PARAGRAPHS} paras, SHA-256 {metadata['sha256']}"
    )


def verify_launcher(launcher: Path, output: Path) -> None:
    source = launcher.read_bytes()
    candidate = (output / OUTPUT_COM).read_bytes()
    expected = patch_prototype_launcher(source)
    if candidate != expected:
        raise ValueError(f"{OUTPUT_COM} differs from the deterministic launcher patch")
    if candidate.count(PROTOTYPE_BANNER) != 1:
        raise ValueError("prototype launcher banner is missing")
    child_offset = candidate.find(CHILD_NAME + b"\x00")
    if child_offset < 0 or candidate.find(CHILD_NAME + b"\x00", child_offset + 1) >= 0:
        raise ValueError("prototype child executable name is not unique")
    exec_prefix = b"\xba" + (0x100 + child_offset).to_bytes(2, "little") + b"\xbb"
    if candidate.count(exec_prefix) != 1:
        raise ValueError(f"DOS EXEC filename pointer does not target {CHILD_NAME.decode()}")
    print(
        f"verified {OUTPUT_COM}: child={CHILD_NAME.decode()}, visible banner present, "
        f"SHA-256 {sha256(candidate)}"
    )


def private_resource_id(name: str, image_id: int) -> int:
    alias_base = next(
        alias
        for variant_name, alias, _direction, _phase, _flip in PRIVATE_VARIANTS
        if variant_name == name
    )
    return PRIVATE_RESOURCE_BASE + 1 + alias_base + selected_image_ordinal(image_id)


def expected_resource_ids() -> list[int]:
    result = list(range(400, 620))
    result.append(PRIVATE_RESOURCE_BASE)
    for name, _alias, _direction, _phase, _flip in PRIVATE_VARIANTS:
        result.extend(private_resource_id(name, image_id) for image_id in SELECTED_IMAGE_IDS)
    return result


def raster_rmse(first: bytes, second: bytes) -> float:
    if len(first) != len(second):
        raise ValueError("runtime previews have inconsistent dimensions")
    return math.sqrt(
        sum((left - right) ** 2 for left, right in zip(first, second)) / len(first)
    )


def verify_dat(source_kid: Path, converted_kid: Path, output: Path) -> None:
    source = DatArchive.open(source_kid)
    converted = DatArchive.open(converted_kid)
    candidate = DatArchive.open(output / OUTPUT_DAT)
    if [item.resource_id for item in candidate.resources] != expected_resource_ids():
        raise ValueError("packed private KID resource IDs/order are incorrect")
    if not all(item.checksum_ok for item in candidate.resources):
        raise ValueError("KID.DAT contains a failed resource checksum")
    if len(PRIVATE_TABLES) != 1 or PRIVATE_TABLES[0][:2] != (
        SLOT_STORED_ODD,
        PRIVATE_RESOURCE_BASE,
    ):
        raise ValueError("runtime is not configured for one proven slot-3 table")
    private_header = candidate.analysis_by_id(PRIVATE_RESOURCE_BASE)
    if private_header is None or private_header.resource.data != converted.resources[0].data:
        raise ValueError("packed private table does not copy the Kid palette/header")

    manifest = json.loads((output / "MANIFEST.JSON").read_text(encoding="utf-8"))
    manifest_records = manifest["variants"]
    settings = manifest["conversion_settings"]
    if (
        settings["phase_consistency_percent"] != PHASE_CONSISTENCY
        or settings["conversion_mode"] != CONVERSION_MODE
        or manifest["kid_dat"]["conversion_mode"] != CONVERSION_MODE
        or settings["dither"] != "none"
        or settings["detail"] != 100
        or settings["color_emphasis"] != 100
        or settings["quality"] != "high"
        or manifest["sources"]["source_kid"]["render_mode"]
        != SOURCE_DISPLAY_MODE
        or manifest["sources"]["source_kid"]["sha256"]
        != EXPECTED_SOURCE_KID_SHA256
        or manifest["sources"]["converted_kid"]["sha256"]
        != EXPECTED_PHASE0_BASELINE_KID_SHA256
        or "phase-0 baseline" not in manifest["sources"]["converted_kid"]["role"]
        or "minimum summed absolute RGB error" not in settings["objective"]
    ):
        raise ValueError("manifest conversion controls are incorrect")

    expected_variant_metadata = {
        "right-even": (2, 400, None, "right", 0, False),
        **{
            name: (
                SLOT_STORED_ODD,
                PRIVATE_RESOURCE_BASE,
                alias,
                direction,
                phase,
                native_flip,
            )
            for name, alias, direction, phase, native_flip in PRIVATE_VARIANTS
        },
    }
    records_by_name: dict[str, dict[int, dict[str, object]]] = {}
    for name, expected_metadata in expected_variant_metadata.items():
        variant = manifest_records[name]
        actual_metadata = (
            variant["slot"],
            variant["resource_base"],
            variant["alias_base"],
            variant["runtime_direction"],
            variant["phase_offset_mode6_bits"],
            variant["prince_native_flip"],
        )
        if actual_metadata != expected_metadata or variant["orientation_bit"] is not True:
            raise ValueError(f"manifest metadata for {name} is incorrect")
        records_by_name[name] = {
            int(record["image_id"]): record for record in variant["images"]
        }
        if set(records_by_name[name]) != set(SELECTED_IMAGE_IDS):
            raise ValueError(f"manifest image list for {name} is incomplete")

    selected_resource_ids = {401 + image_id for image_id in SELECTED_IMAGE_IDS}
    for before, after in zip(converted.resources, candidate.resources[:220]):
        if before.resource_id in selected_resource_ids:
            if before.resource_id != after.resource_id:
                raise ValueError("selected normal KID resource ID changed")
        elif (before.resource_id, before.data) != (after.resource_id, after.data):
            raise ValueError("an unselected normal converted KID resource changed")

    measured_pair_rmse: list[float] = []
    differing_phase_pairs = 0
    differing_direction_pairs = 0
    for image_id in SELECTED_IMAGE_IDS:
        original_analysis = source.analysis_by_id(401 + image_id)
        if original_analysis is None or original_analysis.image is None:
            raise ValueError(f"source Kid image {401 + image_id} does not decode")
        original = original_analysis.image
        base_mask = tuple(value == 0 for value in original.pixels)
        case_bits: dict[str, bytes] = {}

        for name, (_slot, _base, _alias, direction, phase, native_flip) in (
            (item, expected_variant_metadata[item])
            for item in ("right-even", "right-odd", "left-even", "left-odd")
        ):
            resource_id = (
                401 + image_id
                if name == "right-even"
                else private_resource_id(name, image_id)
            )
            analysis = candidate.analysis_by_id(resource_id)
            if analysis is None or analysis.image is None:
                raise ValueError(f"phase-aware Kid image {resource_id} does not decode")
            image = analysis.image
            if (image.width, image.height, image.bits) != (
                original.width,
                original.height,
                original.bits,
            ):
                raise ValueError(f"{name} image geometry differs from its source")
            if tuple(value == 0 for value in image.pixels) != base_mask:
                raise ValueError(f"{name} image changed its stored transparency mask")
            if not bool(analysis.resource.data[5] & 0x80):
                raise ValueError(f"{name} does not retain the stored-orientation header")

            record = records_by_name[name][image_id]
            if (
                record["runtime_direction"] != direction
                or int(record["phase_offset_mode6_bits"]) != phase
                or bool(record["prince_native_flip"]) != native_flip
                or not bool(record["orientation_bit"])
                or int(record["encoded_resource_id"]) != resource_id
            ):
                raise ValueError(f"manifest record for {name}/{image_id} is incorrect")
            hardware = hardware_palette_for_resource(candidate, analysis.resource)
            stored_bits = bytes(initial_mode6_bits(image, hardware))
            if hashlib.sha256(stored_bits).hexdigest() != record["stored_mode6_sha256"]:
                raise ValueError(f"stored Mode-6 hash differs for {name}/{image_id}")
            displayed = runtime_display_bits(
                stored_bits,
                mode6_width(image),
                image.height,
                direction,
            )
            if hashlib.sha256(displayed).hexdigest() != record["runtime_mode6_sha256"]:
                raise ValueError(f"runtime Mode-6 hash differs for {name}/{image_id}")
            case_bits[name] = displayed

        differing_phase_pairs += case_bits["right-even"] != case_bits["right-odd"]
        differing_phase_pairs += case_bits["left-even"] != case_bits["left-odd"]
        differing_direction_pairs += case_bits["right-even"] != case_bits["left-even"]

        width = mode6_width(original)
        height = original.height
        for even_name, odd_name in (
            ("right-even", "right-odd"),
            ("left-even", "left-odd"),
        ):
            even_preview = render_composite_artifacts(
                case_bits[even_name],
                width,
                height,
                COMPOSITE_PROFILE_NEW,
                phase_offset=0,
            )
            odd_preview = render_composite_artifacts(
                case_bits[odd_name],
                width,
                height,
                COMPOSITE_PROFILE_NEW,
                phase_offset=2,
            )
            rmse = raster_rmse(even_preview.pixels, odd_preview.pixels)
            for name in (even_name, odd_name):
                if abs(float(records_by_name[name][image_id]["phase_pair_rmse"]) - rmse) > 0.000001:
                    raise ValueError(f"decoded phase-pair RMSE differs for {name}/{image_id}")
            measured_pair_rmse.append(rmse)

    if differing_phase_pairs != len(SELECTED_IMAGE_IDS) * 2:
        raise ValueError("one or more even/odd runtime encodings are identical")
    if differing_direction_pairs != len(SELECTED_IMAGE_IDS):
        raise ValueError("one or more right/left runtime encodings are identical")
    average_pair_rmse = sum(measured_pair_rmse) / len(measured_pair_rmse)
    manifest_dat = manifest["kid_dat"]
    if abs(float(manifest_dat["phase_pair_rmse_average"]) - average_pair_rmse) > 0.000001:
        raise ValueError("average decoded phase-pair RMSE differs from the manifest")
    source_rmse_values = [
        float(record["signal_rmse"])
        for records in records_by_name.values()
        for record in records.values()
    ]
    average_source_rmse = sum(source_rmse_values) / len(source_rmse_values)
    if (
        abs(float(manifest_dat["source_rmse_average"]) - average_source_rmse)
        > 0.000001
        or abs(float(manifest_dat["source_rmse_maximum"]) - max(source_rmse_values))
        > 0.000001
    ):
        raise ValueError("aggregate source RMSE differs from the manifest")
    expected_alias_ranges = {
        name: [alias, alias + len(SELECTED_IMAGE_IDS) - 1]
        for name, alias, _direction, _phase, _flip in PRIVATE_VARIANTS
    }
    expected_game_frames = {
        name: f"{frame_first}-{frame_last}"
        for name, frame_first, frame_last, _image_first, _image_last
        in SELECTED_FRAME_IMAGE_RANGES
    }
    expected_frame_image_mapping = {
        f"frames_{frame_first}_{frame_last}": f"images_{image_first}_{image_last}"
        for _name, frame_first, frame_last, image_first, image_last
        in SELECTED_FRAME_IMAGE_RANGES
    }
    if (
        manifest_dat["normal_resources_preserved_byte_identical"]
        != 220 - len(SELECTED_IMAGE_IDS)
        or manifest_dat["selected_normal_resources_reencoded"]
        != len(SELECTED_IMAGE_IDS)
        or manifest_dat["private_table_count"] != 1
        or manifest_dat["private_image_count"]
        != len(PRIVATE_VARIANTS) * len(SELECTED_IMAGE_IDS)
        or manifest_dat["private_resources_added"]
        != 1 + len(PRIVATE_VARIANTS) * len(SELECTED_IMAGE_IDS)
        or manifest_dat["private_alias_ranges"] != expected_alias_ranges
        or manifest_dat["selected_game_frames"] != expected_game_frames
        or manifest_dat["selected_frame_image_mapping"]
        != expected_frame_image_mapping
        or manifest_dat["xms_bytes"] != 0
        or manifest_dat["ems_bytes"] != 0
    ):
        raise ValueError("KID.DAT manifest counts or memory metadata are incorrect")
    payload = (output / OUTPUT_DAT).read_bytes()
    if sha256(payload) != manifest_dat["sha256"] or len(payload) != manifest_dat["bytes"]:
        raise ValueError("KID.DAT manifest size/hash mismatch")

    print(
        f"verified {OUTPUT_DAT}: {len(candidate.resources)} resources, "
        f"{len(PRIVATE_VARIANTS) * len(SELECTED_IMAGE_IDS)} packed private images "
        f"in one slot-3 table, independent pair RMSE="
        f"{average_pair_rmse:.3f}, exact stored silhouettes, memory estimate="
        f"{manifest_dat['conventional_memory_upper_estimate_bytes']} bytes, "
        f"SHA-256 {sha256(payload)}"
    )


def verify_runtime_transform_contract() -> None:
    probe = bytes((0, 0, 0, 1, 1, 0, 1, 1))
    expected = bytes((1, 1, 1, 0, 0, 1, 0, 0))
    if reverse_mode6_cga_pixel_rows(probe, 8, 1) != expected:
        raise AssertionError("right transform does not reverse two-sample CGA pixels")
    if runtime_display_bits(probe, 8, 1, "right") != expected:
        raise AssertionError("right runtime transform differs from CGA-pixel reversal")
    if runtime_display_bits(probe, 8, 1, "left") != probe:
        raise AssertionError("left runtime transform changed stored Mode-6 order")
    if expected == probe[::-1]:
        raise AssertionError("right regression probe cannot distinguish bit reversal")
    print("verified runtime transform: right reverses CGA pixel groups, not carrier bits")


def verify_frame_image_map() -> None:
    """Lock the Prince 1.3 animation frame-to-KID-image mapping."""

    expected_ranges = (
        ("start_run_and_stand", 1, 15, 0, 14),
        ("standing_turn", 45, 52, 44, 51),
        ("run_turn", 53, 65, 64, 76),
    )
    expected_ids = (
        tuple(range(0, 15))
        + tuple(range(44, 52))
        + tuple(range(64, 77))
    )
    if SELECTED_FRAME_IMAGE_RANGES != expected_ranges:
        raise AssertionError("authoritative Kid frame/image ranges changed")
    if SELECTED_IMAGE_IDS != expected_ids:
        raise AssertionError("selected Kid IDs do not match the frame table")
    for ordinal, image_id in enumerate(expected_ids):
        if selected_image_ordinal(image_id) != ordinal:
            raise AssertionError(f"packed ordinal differs for Kid image {image_id}")
    print(
        "verified frame map: frames 45..52 -> images 44..51; "
        "frames 53..65 -> images 64..76"
    )


def verify_selector_matrix() -> None:
    alias_bases = {
        "right-odd": STORED_ODD_ALIAS_BASE,
        "left-even": MIRRORED_EVEN_ALIAS_BASE,
        "left-odd": MIRRORED_ODD_ALIAS_BASE,
    }

    def selected_case(
        graphics: int,
        chtab: int,
        logical_x: int,
        orientation: int,
        image_width: int,
        image_id: int,
    ) -> tuple[str, int | None]:
        if graphics != 1 or chtab != 2 or image_id not in SELECTED_IMAGE_IDS:
            return "normal-fallback", None
        screen_x = logical_x * 320 // 280
        if orientation:
            screen_x -= image_width
            if not (screen_x & 1):
                return "right-even", None
            name = "right-odd"
        else:
            name = "left-odd" if screen_x & 1 else "left-even"
        return name, alias_bases[name] + selected_image_ordinal(image_id)

    observed: set[str] = set()
    for image_id in SELECTED_IMAGE_IDS:
        for orientation in (0x0000, 0x8000):
            for logical_x in range(280):
                name, alias = selected_case(
                    1,
                    2,
                    logical_x,
                    orientation,
                    24,
                    image_id,
                )
                observed.add(name)
                if alias is not None and not 0 <= alias < 219:
                    raise AssertionError("selector produced an out-of-range alias")
    if observed != {"right-even", "right-odd", "left-even", "left-odd"}:
        raise AssertionError("selector matrix does not reach all four runtime cases")
    if selected_case(5, 2, 0, 0, 24, 0) != ("normal-fallback", None):
        raise AssertionError("selector is not CGA-only")
    if selected_case(1, 5, 0, 0, 24, 0) != ("normal-fallback", None):
        raise AssertionError("selector is not Kid-only")
    if selected_case(1, 2, 0, 0, 24, 15) != ("normal-fallback", None):
        raise AssertionError("selector does not preserve unselected Kid images")
    print(
        "verified selector matrix: right/even normal, "
        f"right/odd aliases {STORED_ODD_ALIAS_BASE}.."
        f"{STORED_ODD_ALIAS_BASE + len(SELECTED_IMAGE_IDS) - 1}, "
        f"left/even aliases {MIRRORED_EVEN_ALIAS_BASE}.."
        f"{MIRRORED_EVEN_ALIAS_BASE + len(SELECTED_IMAGE_IDS) - 1}, "
        f"left/odd aliases {MIRRORED_ODD_ALIAS_BASE}.."
        f"{MIRRORED_ODD_ALIAS_BASE + len(SELECTED_IMAGE_IDS) - 1}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prince", type=Path, default=WORKSPACE / "upload" / "PRINCE.EXE")
    parser.add_argument("--launcher", type=Path, default=WORKSPACE / "CGAPRINC.COM")
    parser.add_argument(
        "--source-kid",
        type=Path,
        default=WORKSPACE / "pop13_composite_batch" / "input" / "KID.DAT",
    )
    parser.add_argument(
        "--converted-kid",
        type=Path,
        default=(
            WORKSPACE
            / "pop13_composite_batch"
            / "output"
            / "Prince-of-Persia-New-CGA-Composite"
            / "patched-dats"
            / "KID.DAT"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=SCRIPT_DIR / "build")
    args = parser.parse_args()
    verify_executable(args.prince, args.output_dir)
    verify_launcher(args.launcher, args.output_dir)
    verify_dat(args.source_kid, args.converted_kid, args.output_dir)
    verify_runtime_transform_contract()
    verify_frame_image_map()
    verify_selector_matrix()
    print("all V13 Exhaustive VGA phase-stable Kid checks passed")


if __name__ == "__main__":
    main()
