#!/usr/bin/env python3
"""Analyze Prince's fixed CGA mono-color patterns for chomper blood."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
EDITOR_ROOT = ROOT.parent / "editor"
if str(EDITOR_ROOT) not in sys.path:
    sys.path.insert(0, str(EDITOR_ROOT))

from composite_project import initial_mode6_bits  # noqa: E402
from composite_signal import COMPOSITE_PROFILE_NEW, decode_mode6_scanline  # noqa: E402
from prince_dat import DatArchive, hardware_palette_for_resource  # noqa: E402


EXE = ROOT / "build" / "Prince-1.3-New-CGA-V20Y-Chomper-Blood-Stencils" / "P4KX2Y.EXE"
MZ_HEADER_BYTES = 0xA00
DGROUP_LOAD_OFFSET = 0x1BA30
MONO_PATTERN_TABLE_DGROUP_OFFSET = 0x2A14
EXPECTED_TABLE = bytes.fromhex(
    "00000000 66996699 eebbeebb dd77dd77"
    "33cc33cc 44114411 88228822 55aa55aa"
    "66666666 55555555 aaffaaff bbbbbbbb"
    "aaaaaaaa 55ff55ff 77777777 ffffffff"
)
CDUNGEON = ROOT / "build" / "Prince-1.3-New-CGA-V20Y-Chomper-Blood-Stencils" / "CDUNGEON.DAT"
TARGET_RED = (190, 0, 48)


def row_rgb(pattern: int) -> tuple[int, int, int]:
    bits = [(pattern >> (7 - (x & 7))) & 1 for x in range(96)]
    decoded = decode_mode6_scanline(bits, COMPOSITE_PROFILE_NEW)
    stable = decoded[24:72]
    return tuple(
        round(sum(pixel[channel] for pixel in stable) / len(stable))
        for channel in range(3)
    )


def expanded_mask_row(pixels: bytes, width: int, y: int) -> list[int]:
    return [
        bit
        for bit in pixels[y * width : (y + 1) * width]
        for _ in range(2)
    ]


def blood_occurrences(archive: DatArchive) -> list[tuple[str, int, list[int], set[int]]]:
    """Return (pass, absolute_y_mod4, base bits, painted hdot positions)."""

    occurrences: list[tuple[str, int, list[int], set[int]]] = []
    for frame in range(5):
        for pass_name, image_id, mask_id in (
            ("back", 1301 + frame, 1314 + frame),
            ("front", 1306 + frame, 1319 + frame),
        ):
            image_analysis = archive.analysis_by_id(image_id)
            mask_analysis = archive.analysis_by_id(mask_id)
            if image_analysis is None or image_analysis.image is None:
                raise ValueError(f"resource {image_id} is not an image")
            if mask_analysis is None or mask_analysis.image is None:
                raise ValueError(f"resource {mask_id} is not an image")
            image = image_analysis.image
            mask = mask_analysis.image
            palette = hardware_palette_for_resource(archive, image_analysis.resource)
            image_bits = initial_mode6_bits(image, palette)
            bit_width = image.width * 2
            relative_y = image.height - mask.height - 6
            if relative_y < 0 or relative_y + mask.height > image.height:
                raise ValueError(f"mask {mask_id} is outside image {image_id}")
            for tile_row in range(3):
                draw_main_y = 62 + tile_row * 63
                blood_top = draw_main_y - mask.height - 5
                for mask_y in range(mask.height):
                    mask_row = expanded_mask_row(mask.pixels, mask.width, mask_y)
                    painted = {
                        24 + x for x, value in enumerate(mask_row) if value
                    }
                    if not painted:
                        continue
                    image_y = relative_y + mask_y
                    row = list(
                        image_bits[image_y * bit_width : (image_y + 1) * bit_width]
                    )
                    occurrences.append(
                        (pass_name, (blood_top + mask_y) & 3, row, painted)
                    )
    return occurrences


def candidate_error(
    pattern: int,
    phase: int,
    occurrences: list[tuple[str, int, list[int], set[int]]],
    pass_name: str | None = None,
) -> tuple[float, tuple[int, int, int], int]:
    total_error = 0.0
    rgb_sum = [0, 0, 0]
    samples = 0
    for occurrence_pass, occurrence_phase, source, painted in occurrences:
        if occurrence_phase != phase or (pass_name and occurrence_pass != pass_name):
            continue
        bits = list(source)
        for x in painted:
            if x < len(bits):
                bits[x] = (pattern >> (7 - (x & 7))) & 1
        decoded = decode_mode6_scanline(bits, COMPOSITE_PROFILE_NEW)
        visible = {
            x + delta
            for x in painted
            for delta in (-1, 0, 1)
            if 0 <= x + delta < len(decoded)
        }
        for x in visible:
            rgb = decoded[x]
            total_error += sum((rgb[c] - TARGET_RED[c]) ** 2 for c in range(3))
            for c in range(3):
                rgb_sum[c] += rgb[c]
            samples += 1
    mean = tuple(round(value / samples) for value in rgb_sum) if samples else (0, 0, 0)
    return total_error / max(samples, 1), mean, samples


def print_mask_optimization(archive: DatArchive) -> None:
    occurrences = blood_occurrences(archive)
    print("\nExact restored masks over their in-use bottom/front blade resources")
    print(f"occurrence scanlines: {len(occurrences)}; target RGB: {TARGET_RED}")
    for phase in range(4):
        ranked = sorted(
            (candidate_error(pattern, phase, occurrences), pattern)
            for pattern in range(256)
        )
        top = ranked[:8]
        print(
            f"phase {phase}: "
            + ", ".join(
                f"{pattern:08b} mean={result[1]} mse={result[0]:.0f}"
                for result, pattern in top
            )
        )
        for pass_name in ("back", "front"):
            pass_ranked = sorted(
                (candidate_error(pattern, phase, occurrences, pass_name), pattern)
                for pattern in range(256)
            )
            result, pattern = pass_ranked[0]
            print(
                f"  {pass_name}: {pattern:08b} mean={result[1]} "
                f"mse={result[0]:.0f} samples={result[2]}"
            )
    print("reference patterns by pass (mean over all four absolute-row phases)")
    aggregate: dict[int, dict[str, tuple[int, int, int]]] = {}
    for pattern in (0xAA, 0xCC, 0x4C, 0x44, 0x40, 0xC4):
        parts = []
        for pass_name in ("back", "front"):
            weighted = [
                candidate_error(pattern, phase, occurrences, pass_name)
                for phase in range(4)
            ]
            samples = sum(item[2] for item in weighted)
            mean = tuple(
                round(
                    sum(item[1][channel] * item[2] for item in weighted)
                    / max(samples, 1)
                )
                for channel in range(3)
            )
            error = sum(item[0] * item[2] for item in weighted) / max(samples, 1)
            parts.append(f"{pass_name} mean={mean} mse={error:.0f}")
        print(f"  {pattern:08b}: " + "; ".join(parts))
    for pattern in range(256):
        aggregate[pattern] = {}
        for pass_name in ("back", "front"):
            weighted = [
                candidate_error(pattern, phase, occurrences, pass_name)
                for phase in range(4)
            ]
            samples = sum(item[2] for item in weighted)
            aggregate[pattern][pass_name] = tuple(
                round(
                    sum(item[1][channel] * item[2] for item in weighted)
                    / max(samples, 1)
                )
                for channel in range(3)
            )
    balanced_target = (170, 45, 55)
    balanced = sorted(
        (
            sum(
                (aggregate[pattern][pass_name][channel] - balanced_target[channel]) ** 2
                for pass_name in ("back", "front")
                for channel in range(3)
            ),
            pattern,
        )
        for pattern in range(256)
    )
    print(f"balanced blade/floor target {balanced_target}")
    for score, pattern in balanced[:12]:
        print(
            f"  {pattern:08b}: back={aggregate[pattern]['back']} "
            f"front={aggregate[pattern]['front']} score={score}"
        )


def main() -> None:
    module = EXE.read_bytes()[MZ_HEADER_BYTES:]
    offset = DGROUP_LOAD_OFFSET + MONO_PATTERN_TABLE_DGROUP_OFFSET
    table = module[offset : offset + 64]
    if table != EXPECTED_TABLE:
        raise ValueError("unexpected CGA mono-color pattern table")

    print("color  four scanline bytes                 per-row New-CGA RGB                    mean RGB       red score")
    for color in range(16):
        patterns = table[color * 4 : color * 4 + 4]
        rows = [row_rgb(pattern) for pattern in patterns]
        mean = tuple(round(sum(row[c] for row in rows) / 4) for c in range(3))
        red_score = mean[0] - max(mean[1], mean[2])
        print(
            f"{color:>2}     "
            f"{' '.join(f'{pattern:08b}' for pattern in patterns)}  "
            f"{str(rows):<43} {str(mean):<15} {red_score:>4}"
        )
    print_mask_optimization(DatArchive.open(CDUNGEON))


if __name__ == "__main__":
    main()
