"""Fixed-palette, beam-search, and exhaustive composite conversion.

``Simply Palette`` performs an unbiased nearest-RGB lookup against the fixed
16-color Old/New CGA table at the rough 160×200 cell dimensions.  ``Simulated
NTSC`` retains the full Mode-6 signal optimizer: its objective compares every
decoded Reenigne/Jenner output sample against a same-sized source target.
``Exhaustive`` keeps every decoder state instead of pruning to a beam.  Every
model can target one carrier phase or one shared pattern over the resource's
explicitly reachable phase set; no multi-phase objective averages colors.
"""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from array import array
from dataclasses import dataclass, replace
from functools import lru_cache
import heapq
import math
from typing import Callable, Sequence

from composite_signal import decode_mode6_scanline, render_composite_artifacts
from prince_dat import (
    COMPOSITE_PROFILE_NEW,
    COMPOSITE_PROFILE_OLD,
    DOSBOXX_CGA_COMPOSITE_PROFILES,
    RenderedRaster,
)


RGB = tuple[int, int, int]

DITHER_NONE = "none"
DITHER_FLOYD_STEINBERG = "floyd-steinberg"
DITHER_BAYER = "bayer"
DITHER_MODES = (DITHER_NONE, DITHER_FLOYD_STEINBERG, DITHER_BAYER)

CONVERSION_SIMPLE_PALETTE = "simple-palette"
CONVERSION_SIMULATED_NTSC = "simulated-ntsc"
CONVERSION_EXHAUSTIVE = "exhaustive"
CONVERSION_MODES = (
    CONVERSION_SIMPLE_PALETTE,
    CONVERSION_SIMULATED_NTSC,
    CONVERSION_EXHAUSTIVE,
)
CONVERSION_MODE_LABELS = {
    CONVERSION_SIMPLE_PALETTE: "Simply Palette",
    CONVERSION_SIMULATED_NTSC: "Simulated NTSC",
    CONVERSION_EXHAUSTIVE: "Exhaustive",
}

PHASE_ALL = "all"
PHASE_SELECTIONS = (0, 1, 2, 3, PHASE_ALL)

QUALITY_FAST = "fast"
QUALITY_BALANCED = "balanced"
QUALITY_HIGH = "high"
QUALITY_LEVELS = (QUALITY_FAST, QUALITY_BALANCED, QUALITY_HIGH)

_QUALITY_SEARCH = {
    QUALITY_FAST: 8,
    QUALITY_BALANCED: 32,
    QUALITY_HIGH: 96,
}


class ConversionCancelled(RuntimeError):
    """Raised internally when a superseded live preview stops early."""


@dataclass(frozen=True)
class ConversionSettings:
    """All deterministic controls used by the converter."""

    dither: str = DITHER_FLOYD_STEINBERG
    dither_amount: int = 70
    serpentine: bool = True
    bayer_size: int = 4
    brightness: int = 0
    contrast: int = 0
    saturation: int = 100
    gamma: float = 1.0
    color_emphasis: int = 65
    detail: int = 55
    quality: str = QUALITY_FAST
    phase_offset: int | str = 0
    all_phase_offsets: tuple[int, ...] = (0, 1, 2, 3)
    preserve_zero: bool = True

    def validate(self) -> None:
        if self.dither not in DITHER_MODES:
            raise ValueError(f"Unknown dither mode: {self.dither!r}.")
        if self.quality not in QUALITY_LEVELS:
            raise ValueError(f"Unknown conversion quality: {self.quality!r}.")
        if self.bayer_size not in (2, 4, 8):
            raise ValueError("Bayer matrix size must be 2, 4, or 8.")
        if self.phase_offset not in PHASE_SELECTIONS:
            raise ValueError("Composite phase must be 0, 1, 2, 3, or 'all'.")
        if not self.all_phase_offsets:
            raise ValueError("The all-phase objective requires at least one phase.")
        if any(phase not in (0, 1, 2, 3) for phase in self.all_phase_offsets):
            raise ValueError("All-phase offsets must stay between 0 and 3.")
        if len(set(self.all_phase_offsets)) != len(self.all_phase_offsets):
            raise ValueError("All-phase offsets must not contain duplicates.")
        for value, label, minimum, maximum in (
            (self.dither_amount, "Dither amount", 0, 100),
            (self.brightness, "Brightness", -100, 100),
            (self.contrast, "Contrast", -100, 100),
            (self.saturation, "Saturation", 0, 200),
            (self.color_emphasis, "Color emphasis", 0, 100),
            (self.detail, "Detail", 0, 100),
        ):
            if not minimum <= value <= maximum:
                raise ValueError(f"{label} must be between {minimum} and {maximum}.")
        if not 0.5 <= self.gamma <= 2.5:
            raise ValueError("Gamma must be between 0.5 and 2.5.")


@dataclass(frozen=True)
class ConversionResult:
    bits: bytes
    preview: RenderedRaster
    target_width: int
    target_height: int
    source_rmse: float


def resolved_phase_offsets(settings: ConversionSettings) -> tuple[int, ...]:
    """Return the actual carrier phases participating in this conversion."""

    settings.validate()
    if settings.phase_offset == PHASE_ALL:
        return tuple(sorted(settings.all_phase_offsets))
    return (int(settings.phase_offset),)


def _clamp_byte(value: float) -> int:
    return min(255, max(0, int(round(value))))


def _adjust_color(color: RGB, settings: ConversionSettings) -> RGB:
    red, green, blue = (float(component) for component in color)
    contrast = math.pow(4.0, settings.contrast / 100.0)
    brightness = settings.brightness * 2.55
    red = (red - 127.5) * contrast + 127.5 + brightness
    green = (green - 127.5) * contrast + 127.5 + brightness
    blue = (blue - 127.5) * contrast + 127.5 + brightness

    luminance = red * 0.299 + green * 0.587 + blue * 0.114
    saturation = settings.saturation / 100.0
    red = luminance + (red - luminance) * saturation
    green = luminance + (green - luminance) * saturation
    blue = luminance + (blue - luminance) * saturation

    inverse_gamma = 1.0 / settings.gamma
    adjusted = []
    for component in (red, green, blue):
        normalized = min(1.0, max(0.0, component / 255.0))
        adjusted.append(_clamp_byte(255.0 * math.pow(normalized, inverse_gamma)))
    return (adjusted[0], adjusted[1], adjusted[2])


def adjusted_signal_target(
    source: RenderedRaster,
    width: int,
    height: int,
    settings: ConversionSettings,
) -> tuple[RGB, ...]:
    """Adjust and resample a source into the exact signal-output dimensions.

    Integer upscales use pixel replication, which maps each ordinary 320-wide
    VGA/EGA/CGA pixel to two 640-wide color-clock samples without introducing
    a synthetic blur.
    """

    settings.validate()
    if source.channels != 3:
        raise ValueError("Composite conversion requires an RGB source raster.")
    if min(source.width, source.height, width, height) <= 0:
        raise ValueError("Source and target dimensions must be positive.")
    if len(source.pixels) != source.width * source.height * 3:
        raise ValueError("Source raster dimensions are inconsistent.")

    adjusted_source = []
    for offset in range(0, len(source.pixels), 3):
        adjusted_source.append(
            _adjust_color(
                (
                    source.pixels[offset],
                    source.pixels[offset + 1],
                    source.pixels[offset + 2],
                ),
                settings,
            )
        )

    output: list[RGB] = []
    for y in range(height):
        source_y = min(source.height - 1, (y * source.height) // height)
        row = source_y * source.width
        for x in range(width):
            source_x = min(source.width - 1, (x * source.width) // width)
            output.append(adjusted_source[row + source_x])
    return tuple(output)


def _rotate_pattern_for_phase(pattern: int, phase_offset: int) -> int:
    """Rotate one four-bit color-clock cell into a carrier-phase lookup."""

    if not 0 <= pattern <= 15:
        raise ValueError("Composite pattern must be between 0 and 15.")
    if phase_offset not in (0, 1, 2, 3):
        raise ValueError("Composite phase must be between 0 and 3.")
    if phase_offset == 0:
        return pattern
    return ((pattern >> phase_offset) | (pattern << (4 - phase_offset))) & 0xF


def _combine_phase_rasters(
    rasters: Sequence[RenderedRaster],
    *,
    mode: str,
) -> RenderedRaster:
    """Place one to four equal rasters in a compact, unblended preview grid."""

    if not rasters:
        raise ValueError("A phase preview requires at least one raster.")
    width = rasters[0].width
    height = rasters[0].height
    channels = rasters[0].channels
    if any(
        (raster.width, raster.height, raster.channels) != (width, height, channels)
        for raster in rasters
    ):
        raise ValueError("Phase preview rasters must have equal dimensions.")
    columns = 1 if len(rasters) == 1 else 2
    rows = (len(rasters) + columns - 1) // columns
    grid_width = width * columns
    grid_height = height * rows
    output = bytearray(grid_width * grid_height * channels)
    for index, raster in enumerate(rasters):
        left = (index % columns) * width
        top = (index // columns) * height
        for y in range(height):
            source_start = y * width * channels
            destination_start = ((top + y) * grid_width + left) * channels
            output[destination_start : destination_start + width * channels] = (
                raster.pixels[source_start : source_start + width * channels]
            )
    return RenderedRaster(
        grid_width,
        grid_height,
        bytes(output),
        channels,
        mode,
    )


def render_simple_palette_bits(
    bits: Sequence[int],
    width: int,
    height: int,
    profile: str,
    *,
    channels: int = 3,
    phase_offset: int = 0,
) -> RenderedRaster:
    """Render Mode-6 bits as independent fixed-palette four-bit cells.

    This is intentionally the idealized 160×200 interpretation: neighboring
    cells never bleed into one another. Carrier phase rotates the fixed four-
    clock lookup but does not invoke the neighbor-dependent signal decoder.
    """

    if width <= 0 or height <= 0 or len(bits) != width * height:
        raise ValueError("Simple-palette bit dimensions are inconsistent.")
    if channels not in (3, 4):
        raise ValueError("Simple-palette rendering supports only RGB and RGBA.")
    if phase_offset not in (0, 1, 2, 3):
        raise ValueError("Composite phase must be between 0 and 3.")
    try:
        colors = DOSBOXX_CGA_COMPOSITE_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown composite profile: {profile!r}.") from exc

    cell_width = (width + 3) // 4
    output = bytearray(cell_width * height * channels)
    cursor = 0
    for y in range(height):
        row = y * width
        for cell in range(cell_width):
            pattern = 0
            for part in range(4):
                x = cell * 4 + part
                if x < width and bits[row + x]:
                    pattern |= 1 << (3 - part)
            display_pattern = _rotate_pattern_for_phase(pattern, phase_offset)
            output[cursor : cursor + 3] = bytes(colors[display_pattern])
            if channels == 4:
                output[cursor + 3] = 255
            cursor += channels
    return RenderedRaster(
        cell_width,
        height,
        bytes(output),
        channels,
        "simple-palette",
    )


def render_simple_palette_phase_grid(
    bits: Sequence[int],
    width: int,
    height: int,
    profile: str,
    phase_offsets: Sequence[int],
) -> RenderedRaster:
    """Render only the requested idealized carrier phases without blending."""

    phases = tuple(sorted(set(int(phase) for phase in phase_offsets)))
    if not phases or any(phase not in (0, 1, 2, 3) for phase in phases):
        raise ValueError("Phase previews require one or more phases between 0 and 3.")
    return _combine_phase_rasters(
        tuple(
            render_simple_palette_bits(
                bits,
                width,
                height,
                profile,
                phase_offset=phase,
            )
            for phase in phases
        ),
        mode="simple-palette-phase-set",
    )


def convert_raster_to_simple_palette(
    source: RenderedRaster,
    target_width: int,
    target_height: int,
    profile: str,
    *,
    settings: ConversionSettings | None = None,
    source_zero_mask: Sequence[bool] | None = None,
    target_locked_bits: Sequence[int | None] | None = None,
    preserve_zero: bool = True,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ConversionResult:
    """Quantize directly to the fixed 16-color, 160-style Composite palette.

    Selection uses ordinary, unweighted squared RGB distance. There is no
    dither, signal decoding, edge/detail weighting, color emphasis, quality
    search, brightness, contrast, saturation, or gamma adjustment. A selected
    phase rotates the fixed lookup. ``all`` adds the independent errors for
    the settings' reachable phases. A source-index-zero mask remains an
    optional hard transparency constraint rather than a color-selection bias.
    """

    try:
        colors = DOSBOXX_CGA_COMPOSITE_PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"Unknown composite profile: {profile!r}.") from exc
    requested = settings or ConversionSettings(
        dither=DITHER_NONE,
        dither_amount=0,
        phase_offset=0,
        preserve_zero=preserve_zero,
    )
    requested.validate()
    neutral = ConversionSettings(
        dither=DITHER_NONE,
        dither_amount=0,
        brightness=0,
        contrast=0,
        saturation=100,
        gamma=1.0,
        color_emphasis=100,
        detail=0,
        quality=QUALITY_FAST,
        phase_offset=requested.phase_offset,
        all_phase_offsets=requested.all_phase_offsets,
        preserve_zero=preserve_zero,
    )
    phase_offsets = resolved_phase_offsets(neutral)
    phase_colors = tuple(
        tuple(
            colors[_rotate_pattern_for_phase(pattern, phase)]
            for pattern in range(16)
        )
        for phase in phase_offsets
    )
    target = adjusted_signal_target(
        source,
        target_width,
        target_height,
        neutral,
    )
    forced_bits = _conversion_forced_bits(
        source_zero_mask,
        source.width,
        source.height,
        target_width,
        target_height,
        target_locked_bits=target_locked_bits,
        preserve_zero=preserve_zero,
    )

    cell_width = (target_width + 3) // 4
    bits = bytearray(target_width * target_height)
    squared = 0.0
    sample_count = 0
    for y in range(target_height):
        if cancelled is not None and cancelled():
            raise ConversionCancelled()
        row = y * target_width
        allowed = _allowed_patterns_for_row(forced_bits, row, target_width)
        for cell in range(cell_width):
            start = cell * 4
            stop = min(target_width, start + 4)
            count = stop - start
            channel_sums = tuple(
                sum(target[row + x][channel] for x in range(start, stop))
                for channel in range(3)
            )
            pattern = min(
                allowed[cell],
                key=lambda candidate: sum(
                    (
                        colors_for_phase[candidate][channel] * count
                        - channel_sums[channel]
                    )
                    ** 2
                    for colors_for_phase in phase_colors
                    for channel in range(3)
                ),
            )
            for part in range(4):
                x = start + part
                if x < target_width:
                    bits[row + x] = (pattern >> (3 - part)) & 1
            squared += sum(
                (
                    colors_for_phase[pattern][channel]
                    - channel_sums[channel] / count
                )
                ** 2
                for colors_for_phase in phase_colors
                for channel in range(3)
            )
            sample_count += 3 * len(phase_offsets)
        if progress is not None:
            progress(y + 1, target_height)

    if neutral.phase_offset == PHASE_ALL:
        preview = render_simple_palette_phase_grid(
            bits,
            target_width,
            target_height,
            profile,
            phase_offsets,
        )
    else:
        preview = render_simple_palette_bits(
            bits,
            target_width,
            target_height,
            profile,
            phase_offset=phase_offsets[0],
        )
    return ConversionResult(
        bits=bytes(bits),
        preview=preview,
        target_width=target_width,
        target_height=target_height,
        source_rmse=math.sqrt(squared / sample_count),
    )


def resample_zero_mask(
    mask: Sequence[bool] | None,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
) -> tuple[bool, ...] | None:
    if mask is None:
        return None
    if len(mask) != source_width * source_height:
        raise ValueError("Source zero mask dimensions are inconsistent.")
    output = []
    for y in range(target_height):
        source_y = min(source_height - 1, (y * source_height) // target_height)
        row = source_y * source_width
        for x in range(target_width):
            source_x = min(source_width - 1, (x * source_width) // target_width)
            output.append(bool(mask[row + source_x]))
    return tuple(output)


def _conversion_forced_bits(
    source_zero_mask: Sequence[bool] | None,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    *,
    target_locked_bits: Sequence[int | None] | None,
    preserve_zero: bool,
) -> tuple[int, ...] | None:
    """Resolve optional transparency constraints at target signal resolution.

    ``-1`` means editable; zero and one are exact required signal values.  A
    phase-aware editor mask is already expressed at Mode-6 resolution and
    takes precedence over a selected VGA/EGA/CGA source's index-zero mask.
    """

    if not preserve_zero:
        return None
    target_count = target_width * target_height
    if target_locked_bits is not None:
        if len(target_locked_bits) != target_count:
            raise ValueError("Target locked-bit dimensions are inconsistent.")
        normalized = tuple(
            -1 if value is None else int(value)
            for value in target_locked_bits
        )
        if any(value not in (-1, 0, 1) for value in normalized):
            raise ValueError("Target locked bits must contain only -1, 0, or 1.")
        return normalized
    zero_mask = resample_zero_mask(
        source_zero_mask,
        source_width,
        source_height,
        target_width,
        target_height,
    )
    if zero_mask is None:
        return None
    return tuple(0 if locked else -1 for locked in zero_mask)


def _pattern_bits(pattern: int) -> tuple[int, int, int, int]:
    return tuple((pattern >> shift) & 1 for shift in (3, 2, 1, 0))


@lru_cache(maxsize=8)
def artifact_window_table(
    profile: str,
    phase_offset: int,
) -> tuple[tuple[RGB, ...], ...]:
    """Return exact output for every 12-bit neighborhood and sample phase.

    The Reenigne/Jenner sample at ``x`` depends on the twelve input bits from
    ``x - 5`` through ``x + 6``.  The returned four tables are indexed by
    ``x & 3`` and then by that 12-bit window.  This is what lets the optimizer
    score decoded 640-column samples directly without repeatedly decoding a
    whole scanline for each trial bit.
    """

    if profile not in (COMPOSITE_PROFILE_OLD, COMPOSITE_PROFILE_NEW):
        raise ValueError(f"Unknown composite profile: {profile!r}.")
    if phase_offset not in (0, 1, 2, 3):
        raise ValueError("Composite phase must be between 0 and 3.")
    phase_tables: list[tuple[RGB, ...]] = []
    for sample_phase in range(4):
        table: list[RGB] = []
        # Seven border samples put the requested output at local x=12.  Since
        # 12 mod 4 is zero, adding sample_phase to the decoder phase reproduces
        # the absolute phase of the real output sample.
        local_phase = (phase_offset + sample_phase) & 3
        for window in range(4096):
            window_bits = tuple((window >> shift) & 1 for shift in range(11, -1, -1))
            bits = (0,) * 7 + window_bits + (0,) * 7
            decoded = decode_mode6_scanline(
                bits,
                profile,
                phase_offset=local_phase,
            )
            table.append(decoded[12])
        phase_tables.append(tuple(table))
    return tuple(phase_tables)


@lru_cache(maxsize=8)
def nominal_pattern_colors(profile: str, phase_offset: int) -> tuple[RGB, ...]:
    """Average the steady decoded four-sample output of each repeating cell."""

    colors = []
    for pattern in range(16):
        bits = _pattern_bits(pattern) * 9
        decoded = decode_mode6_scanline(
            bits,
            profile,
            phase_offset=phase_offset,
        )
        samples = decoded[16:20]
        colors.append(
            tuple(sum(sample[channel] for sample in samples) // 4 for channel in range(3))
        )
    return tuple(colors)


def _difference_cost(actual: RGB, target: RGB, color_emphasis: int) -> int:
    red = actual[0] - target[0]
    green = actual[1] - target[1]
    blue = actual[2] - target[2]
    rgb = red * red + green * green + blue * blue
    luma = (77 * red + 150 * green + 29 * blue) // 256
    luma_cost = 3 * luma * luma
    return (
        (100 - color_emphasis) * luma_cost + color_emphasis * rgb
    ) // 100


def _cell_average(target: Sequence[RGB], row: int, start: int, width: int) -> RGB:
    stop = min(width, start + 4)
    count = stop - start
    return tuple(
        sum(target[row + x][channel] for x in range(start, stop)) // count
        for channel in range(3)
    )


def _allowed_patterns_for_row(
    forced_bits: Sequence[int] | None,
    row: int,
    width: int,
) -> tuple[tuple[int, ...], ...]:
    cells = (width + 3) // 4
    allowed = []
    for cell in range(cells):
        candidates = []
        for pattern in range(16):
            valid = True
            for part in range(4):
                x = cell * 4 + part
                required = 0 if x >= width else (
                    forced_bits[row + x]
                    if forced_bits is not None
                    else -1
                )
                if required in (0, 1) and ((pattern >> (3 - part)) & 1) != required:
                    valid = False
                    break
            if valid:
                candidates.append(pattern)
        allowed.append(tuple(candidates))
    return tuple(allowed)


def _bayer_matrix(size: int) -> tuple[tuple[int, ...], ...]:
    matrix = ((0,),)
    while len(matrix) < size:
        old = matrix
        length = len(old)
        matrix = tuple(
            tuple(
                4 * old[y % length][x % length]
                + ((0, 2), (3, 1))[y // length][x // length]
                for x in range(length * 2)
            )
            for y in range(length * 2)
        )
    return matrix


def dither_signal_target(
    target: Sequence[RGB],
    width: int,
    height: int,
    profile: str,
    settings: ConversionSettings,
    zero_mask: Sequence[bool] | None = None,
    *,
    forced_bits: Sequence[int] | None = None,
) -> tuple[RGB, ...]:
    """Create the full-width target used by the artifact optimizer."""

    if len(target) != width * height:
        raise ValueError("Signal target dimensions are inconsistent.")
    if zero_mask is not None and len(zero_mask) != len(target):
        raise ValueError("Signal zero-mask dimensions are inconsistent.")
    if forced_bits is not None:
        if len(forced_bits) != len(target):
            raise ValueError("Signal locked-bit dimensions are inconsistent.")
        if any(value not in (-1, 0, 1) for value in forced_bits):
            raise ValueError("Signal locked bits must contain only -1, 0, or 1.")
    if settings.dither == DITHER_NONE or settings.dither_amount == 0:
        return tuple(target)

    cells = (width + 3) // 4
    strength = settings.dither_amount / 100.0
    colors = nominal_pattern_colors(profile, settings.phase_offset)
    output = list(target)
    constraint_bits = (
        tuple(forced_bits)
        if forced_bits is not None
        else (
            tuple(0 if locked else -1 for locked in zero_mask)
            if zero_mask is not None
            else None
        )
    )
    protected_mask = (
        tuple(value in (0, 1) for value in constraint_bits)
        if constraint_bits is not None
        else None
    )

    if settings.dither == DITHER_BAYER:
        matrix = _bayer_matrix(settings.bayer_size)
        levels = settings.bayer_size * settings.bayer_size
        for y in range(height):
            row = y * width
            for cell in range(cells):
                threshold = (
                    (matrix[y % settings.bayer_size][cell % settings.bayer_size] + 0.5)
                    / levels
                    - 0.5
                )
                # A luminance displacement of one modest palette interval at
                # 100% produces ordered texture without destroying hue.
                displacement = threshold * 96.0 * strength
                for x in range(cell * 4, min(width, cell * 4 + 4)):
                    if protected_mask is not None and protected_mask[row + x]:
                        continue
                    original = target[row + x]
                    output[row + x] = tuple(
                        _clamp_byte(component + displacement)
                        for component in original
                    )
        return tuple(output)

    current = [[0.0, 0.0, 0.0] for _ in range(cells + 2)]
    for y in range(height):
        next_row = [[0.0, 0.0, 0.0] for _ in range(cells + 2)]
        forward = not settings.serpentine or not (y & 1)
        cell_order = range(cells) if forward else range(cells - 1, -1, -1)
        row = y * width
        allowed = _allowed_patterns_for_row(constraint_bits, row, width)
        for cell in cell_order:
            incoming = tuple(
                min(96.0, max(-96.0, current[cell + 1][channel]))
                for channel in range(3)
            )
            start = cell * 4
            stop = min(width, start + 4)
            count = stop - start
            average = tuple(
                sum(target[row + x][channel] for x in range(start, stop)) / count
                + incoming[channel]
                for channel in range(3)
            )
            pattern = min(
                allowed[cell],
                key=lambda candidate: sum(
                    (colors[candidate][channel] - average[channel]) ** 2
                    for channel in range(3)
                ),
            )
            error = tuple(
                (average[channel] - colors[pattern][channel]) * strength
                for channel in range(3)
            )
            for x in range(start, stop):
                if protected_mask is not None and protected_mask[row + x]:
                    continue
                output[row + x] = tuple(
                    _clamp_byte(target[row + x][channel] + incoming[channel])
                    for channel in range(3)
                )

            direction = 1 if forward else -1
            neighbors = (
                (current, cell + 1 + direction, 7.0 / 16.0),
                (next_row, cell + 1 - direction, 3.0 / 16.0),
                (next_row, cell + 1, 5.0 / 16.0),
                (next_row, cell + 1 + direction, 1.0 / 16.0),
            )
            for row_errors, destination, weight in neighbors:
                if not 0 <= destination < len(row_errors):
                    continue
                for channel in range(3):
                    row_errors[destination][channel] += error[channel] * weight
        current = next_row
    return tuple(output)


def _detail_weights(target: Sequence[RGB], width: int, height: int, detail: int) -> tuple[int, ...]:
    luminance = tuple((77 * red + 150 * green + 29 * blue) // 256 for red, green, blue in target)
    weights = []
    for y in range(height):
        row = y * width
        for x in range(width):
            center = luminance[row + x]
            gradient = 0
            if x:
                gradient = max(gradient, abs(center - luminance[row + x - 1]))
            if x + 1 < width:
                gradient = max(gradient, abs(center - luminance[row + x + 1]))
            if y:
                gradient = max(gradient, abs(center - luminance[row - width + x]))
            if y + 1 < height:
                gradient = max(gradient, abs(center - luminance[row + width + x]))
            weights.append(100 + (detail * 3 * gradient) // 255)
    return tuple(weights)


def _optimize_row(
    targets: Sequence[Sequence[RGB]],
    weight_sets: Sequence[Sequence[int]],
    row: int,
    width: int,
    window_sets: Sequence[Sequence[Sequence[RGB]]],
    forced_bits: Sequence[int] | None,
    settings: ConversionSettings,
) -> bytes:
    """Optimize one decoded scanline over one or more carrier phases."""

    beam_width = _QUALITY_SEARCH[settings.quality]
    # state -> (cost, packed real-bit path, number of real bits)
    states: dict[int, tuple[int, int, int]] = {0: (0, 0, 0)}
    real_end = 5 + width

    # Five implicit zero border bits are already represented by state zero.
    # Append all real bits, then six fixed zero border bits so the last six
    # decoded samples receive their complete x+6 neighborhood.
    for position in range(5, width + 11):
        real_x = position - 5
        is_real = position < real_end
        required = (
            forced_bits[row + real_x]
            if is_real and forced_bits is not None
            else -1
        )
        choices = (0,) if not is_real else (
            (required,) if required in (0, 1) else (0, 1)
        )
        expanded: dict[int, tuple[int, int, int]] = {}
        for state, (path_cost, path, path_length) in states.items():
            for bit in choices:
                window = (state << 1) | bit
                next_state = window & 0x7FF
                total = path_cost
                if position >= 11:
                    output_x = position - 11
                    offset = row + output_x
                    total += sum(
                        (
                            _difference_cost(
                                windows[output_x & 3][window],
                                target[offset],
                                settings.color_emphasis,
                            )
                            * weights[offset]
                        )
                        for target, weights, windows in zip(
                            targets,
                            weight_sets,
                            window_sets,
                            strict=True,
                        )
                    )
                next_path = (path << 1) | bit if is_real else path
                next_length = path_length + 1 if is_real else path_length
                previous = expanded.get(next_state)
                if previous is None or total < previous[0]:
                    expanded[next_state] = (total, next_path, next_length)
        if position >= 11 and len(expanded) > beam_width:
            states = dict(
                heapq.nsmallest(
                    beam_width,
                    expanded.items(),
                    key=lambda item: item[1][0],
                )
            )
        else:
            states = expanded

    _cost, packed, bit_count = min(states.values(), key=lambda value: value[0])
    if bit_count != width:
        raise RuntimeError("Internal composite optimizer path length mismatch.")
    return packed.to_bytes((width + 7) // 8, "big")[-((width + 7) // 8) :]


def optimize_signal_bits(
    target: Sequence[RGB],
    width: int,
    height: int,
    profile: str,
    settings: ConversionSettings,
    *,
    phase_targets: Sequence[Sequence[RGB]] | None = None,
    forced_bits: Sequence[int] | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> bytes:
    """Optimize every sample over the selected or reachable carrier phases."""

    settings.validate()
    if len(target) != width * height:
        raise ValueError("Signal target dimensions are inconsistent.")
    if forced_bits is not None:
        if len(forced_bits) != len(target):
            raise ValueError("Signal locked-bit dimensions are inconsistent.")
        if any(value not in (-1, 0, 1) for value in forced_bits):
            raise ValueError("Signal locked bits must contain only -1, 0, or 1.")
    phase_offsets = resolved_phase_offsets(settings)
    if phase_targets is None:
        targets = tuple(tuple(target) for _phase in phase_offsets)
    else:
        if len(phase_targets) != len(phase_offsets):
            raise ValueError(
                "Signal phase-target count must match the optimized phase count."
            )
        targets = tuple(tuple(phase_target) for phase_target in phase_targets)
    if any(len(phase_target) != width * height for phase_target in targets):
        raise ValueError("Signal phase-target dimensions are inconsistent.")
    window_sets = tuple(
        artifact_window_table(profile, phase_offset)
        for phase_offset in phase_offsets
    )
    weight_sets = tuple(
        _detail_weights(phase_target, width, height, settings.detail)
        for phase_target in targets
    )
    bits = bytearray(width * height)
    for y in range(height):
        if cancelled is not None and cancelled():
            raise ConversionCancelled()
        row = y * width
        packed_row = _optimize_row(
            targets,
            weight_sets,
            row,
            width,
            window_sets,
            forced_bits,
            settings,
        )
        padding = len(packed_row) * 8 - width
        for x in range(width):
            bits[row + x] = (
                packed_row[(x + padding) // 8]
                >> (7 - ((x + padding) & 7))
            ) & 1
        if progress is not None:
            progress(y + 1, height)
    return bytes(bits)


@lru_cache(maxsize=512)
def selected_phase_window_costs(
    profile: str,
    phase_offset: int,
    sample_phase: int,
    target: RGB,
) -> array:
    """Return selected-phase RGB squared error for all signal windows."""

    if sample_phase not in (0, 1, 2, 3):
        raise ValueError("Composite sample phase must be between 0 and 3.")
    colors = artifact_window_table(profile, phase_offset)[sample_phase]
    return array(
        "I",
        (
            (colors[window][0] - target[0]) ** 2
            + (colors[window][1] - target[1]) ** 2
            + (colors[window][2] - target[2]) ** 2
            for window in range(4096)
        ),
    )


@lru_cache(maxsize=512)
def phase_set_window_costs(
    profile: str,
    sample_phase: int,
    phase_offsets: tuple[int, ...],
    targets: tuple[RGB, ...],
) -> array:
    """Return summed absolute RGB error for independent phase decodes.

    No target or decoded color is averaged. Each phase is compared with its
    own target RGB value, then every absolute component error is added. Separate
    targets matter when vertical diffusion has produced a different incoming
    residual for each reachable phase.
    """

    if sample_phase not in (0, 1, 2, 3):
        raise ValueError("Composite sample phase must be between 0 and 3.")
    if (
        not phase_offsets
        or any(phase not in (0, 1, 2, 3) for phase in phase_offsets)
        or len(set(phase_offsets)) != len(phase_offsets)
    ):
        raise ValueError("Phase-set optimization requires unique phases from 0 to 3.")
    if len(targets) != len(phase_offsets):
        raise ValueError("Phase-set optimization requires one target per phase.")
    colors = tuple(
        artifact_window_table(profile, phase)[sample_phase]
        for phase in phase_offsets
    )
    return array(
        "I",
        (
            sum(
                abs(colors[index][window][channel] - targets[index][channel])
                for index in range(len(phase_offsets))
                for channel in range(3)
            )
            for window in range(4096)
        ),
    )


def all_phase_window_costs(
    profile: str,
    sample_phase: int,
    targets: tuple[RGB, ...],
) -> array:
    """Compatibility wrapper for the original four-phase objective."""

    return phase_set_window_costs(
        profile,
        sample_phase,
        (0, 1, 2, 3),
        targets,
    )


def _optimize_row_exhaustive(
    target_rows: Sequence[Sequence[RGB]],
    profile: str,
    phase_offset: int | str,
    forced_bits: Sequence[int] | None = None,
    *,
    allowed_codes: Sequence[Sequence[int]] | None = None,
    phase_offsets: Sequence[int] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> bytes:
    """Find the globally minimum-error row over every possible bit pattern.

    The decoder has a twelve-bit horizontal dependency, so the previous eleven
    bits completely describe the future.  Keeping all 2,048 such states makes
    this an exact Viterbi/dynamic-programming solution: no full row is omitted,
    but the equivalent ``2 ** width`` paths are merged whenever their decoder
    history becomes identical.
    """

    if phase_offset not in PHASE_SELECTIONS:
        raise ValueError("Composite phase must be 0, 1, 2, 3, or 'all'.")
    if phase_offset == PHASE_ALL:
        requested_phases = range(4) if phase_offsets is None else phase_offsets
        objective_phases = tuple(
            sorted(set(int(phase) for phase in requested_phases))
        )
        if (
            not objective_phases
            or any(phase not in (0, 1, 2, 3) for phase in objective_phases)
        ):
            raise ValueError(
                "All-phase optimization requires one or more phases from 0 to 3."
            )
    else:
        objective_phases = (int(phase_offset),)
    expected_rows = len(objective_phases)
    if len(target_rows) != expected_rows:
        raise ValueError(
            f"Exhaustive phase {phase_offset!r} requires {expected_rows} target row(s)."
        )
    width = len(target_rows[0]) if target_rows else 0
    if width <= 0:
        raise ValueError("Exhaustive rows must contain at least one target pixel.")
    if any(len(target_row) != width for target_row in target_rows):
        raise ValueError("Exhaustive target rows must have equal dimensions.")
    if forced_bits is not None:
        if len(forced_bits) != width:
            raise ValueError("Exhaustive row locked-bit dimensions are inconsistent.")
        if any(value not in (-1, 0, 1) for value in forced_bits):
            raise ValueError("Exhaustive locked bits must contain only -1, 0, or 1.")
    if allowed_codes is not None:
        if width & 1 or len(allowed_codes) != width // 2:
            raise ValueError("Exhaustive allowed-code dimensions are inconsistent.")
        if any(
            not codes or any(code not in (0, 1, 2, 3) for code in codes)
            for codes in allowed_codes
        ):
            raise ValueError("Exhaustive allowed codes must be nonempty subsets of 0..3.")

    state_count = 1 << 11
    state_high_bit = 1 << 10
    infinity = 1 << 60
    previous = [infinity] * state_count
    previous[0] = 0
    parent_high_bits: list[bytearray] = []

    # Five black samples are implicit in the initial all-zero state.  Append
    # every real bit and then six black samples to finalize the rightmost six
    # decoded pixels.
    step_count = width + 6
    for step in range(step_count):
        if cancelled is not None and not (step & 7) and cancelled():
            raise ConversionCancelled()
        real_bit = step < width
        required = (
            forced_bits[step]
            if real_bit and forced_bits is not None
            else -1
        )
        output_x = step - 6
        if output_x < 0:
            costs = None
        elif phase_offset == PHASE_ALL:
            costs = phase_set_window_costs(
                profile,
                output_x & 3,
                objective_phases,
                tuple(target_row[output_x] for target_row in target_rows),
            )
        else:
            costs = selected_phase_window_costs(
                profile,
                int(phase_offset),
                output_x & 3,
                target_rows[0][output_x],
            )

        current = [infinity] * state_count
        parents = bytearray(state_count)
        if not real_bit or required == 0:
            next_states = range(0, state_count, 2)
        elif required == 1:
            next_states = range(1, state_count, 2)
        else:
            next_states = range(state_count)
        for next_state in next_states:
            if (
                real_bit
                and (step & 1)
                and allowed_codes is not None
                and (next_state & 3) not in allowed_codes[step // 2]
            ):
                continue
            low_predecessor = next_state >> 1
            high_predecessor = low_predecessor | state_high_bit
            low_cost = previous[low_predecessor]
            high_cost = previous[high_predecessor]
            if low_cost == infinity and high_cost == infinity:
                continue
            if costs is not None:
                if low_cost != infinity:
                    low_cost += costs[next_state]
                if high_cost != infinity:
                    high_cost += costs[next_state | (1 << 11)]
            if high_cost < low_cost:
                current[next_state] = high_cost
                parents[next_state] = 1
            else:
                current[next_state] = low_cost
        previous = current
        parent_high_bits.append(parents)

    final_state = min(range(state_count), key=previous.__getitem__)
    if previous[final_state] == infinity:
        raise RuntimeError("No legal exhaustive Composite row could be encoded.")

    row_bits = bytearray(width)
    state = final_state
    for step in range(step_count - 1, -1, -1):
        if step < width:
            row_bits[step] = state & 1
        parent_high = parent_high_bits[step][state]
        state = (state >> 1) | (parent_high << 10)
    if state:
        raise RuntimeError("Internal exhaustive Composite backtrack mismatch.")
    return bytes(row_bits)


def _dither_exhaustive_bayer_target(
    target: Sequence[RGB],
    width: int,
    height: int,
    settings: ConversionSettings,
    zero_mask: Sequence[bool] | None,
) -> tuple[RGB, ...]:
    """Apply Bayer displacement at the actual signal-pixel resolution."""

    if settings.dither != DITHER_BAYER or settings.dither_amount == 0:
        return tuple(target)
    matrix = _bayer_matrix(settings.bayer_size)
    levels = settings.bayer_size * settings.bayer_size
    strength = settings.dither_amount / 100.0
    output = list(target)
    for y in range(height):
        row = y * width
        for x in range(width):
            offset = row + x
            if zero_mask is not None and zero_mask[offset]:
                continue
            threshold = (
                (matrix[y % settings.bayer_size][x % settings.bayer_size] + 0.5)
                / levels
                - 0.5
            )
            displacement = threshold * 96.0 * strength
            output[offset] = tuple(
                _clamp_byte(component + displacement)
                for component in target[offset]
            )
    return tuple(output)


def _selected_phase_scanline(
    bits: Sequence[int],
    profile: str,
    phase_offset: int,
) -> tuple[RGB, ...]:
    """Decode one selected row at the same phase used by its optimizer."""

    return decode_mode6_scanline(
        bits,
        profile,
        phase_offset=phase_offset,
    )


def render_all_phase_grid(
    bits: Sequence[int],
    width: int,
    height: int,
    profile: str,
    phase_offsets: Sequence[int] = (0, 1, 2, 3),
) -> RenderedRaster:
    """Render requested phases independently in a compact lossless grid.

    Phases use ascending row-major order. One phase occupies one panel, two use
    one row, and three or four use two rows. Pixels are copied verbatim from
    each decoder output; the grid never blends or averages them.
    """

    phases = tuple(sorted(set(int(phase) for phase in phase_offsets)))
    if not phases or any(phase not in (0, 1, 2, 3) for phase in phases):
        raise ValueError("Phase previews require one or more phases between 0 and 3.")
    rasters = tuple(
        render_composite_artifacts(
            bits,
            width,
            height,
            profile,
            phase_offset=phase,
        )
        for phase in phases
    )
    return _combine_phase_rasters(
        rasters,
        mode="composite-all-phases",
    )


def vertical_diffusion_neighbors(
    x: int,
    *,
    forward: bool,
) -> tuple[tuple[int, float], tuple[int, float], tuple[int, float]]:
    """Return down-forward/down/down-back destinations and their weights."""

    direction = 1 if forward else -1
    return (
        (x + direction, 8.0 / 16.0),
        (x, 5.0 / 16.0),
        (x - direction, 3.0 / 16.0),
    )


def convert_raster_to_exhaustive(
    source: RenderedRaster,
    target_width: int,
    target_height: int,
    profile: str,
    settings: ConversionSettings,
    *,
    source_zero_mask: Sequence[bool] | None = None,
    target_locked_bits: Sequence[int | None] | None = None,
    target_allowed_codes: Sequence[Sequence[int]] | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ConversionResult:
    """Encode exact rows for one phase or a reachable-phase universal objective.

    Bayer displacement is applied to the complete 640-style target before the
    row search.  Error diffusion is deliberately vertical-only: a completed
    row's residual is distributed 8/16 down-forward, 5/16 straight down, and
    3/16 down-backward.  Serpentine mode mirrors forward/backward on alternate
    rows.  No color-emphasis, detail, or quality bias participates in this
    objective. In ``all`` mode the optimizer sums absolute RGB error across
    the explicitly reachable phase decodes, and diffusion retains one
    independent residual buffer per phase rather than combining them.
    """

    settings.validate()
    adjusted = adjusted_signal_target(source, target_width, target_height, settings)
    forced_bits = _conversion_forced_bits(
        source_zero_mask,
        source.width,
        source.height,
        target_width,
        target_height,
        target_locked_bits=target_locked_bits,
        preserve_zero=settings.preserve_zero,
    )
    if target_allowed_codes is not None:
        if target_width & 1:
            raise ValueError("Target allowed codes require an even signal width.")
        expected_codes = (target_width // 2) * target_height
        if len(target_allowed_codes) != expected_codes:
            raise ValueError("Target allowed-code dimensions are inconsistent.")
        normalized_allowed_codes = tuple(
            tuple(sorted(set(int(code) for code in codes)))
            for codes in target_allowed_codes
        )
        if any(
            not codes or any(code not in (0, 1, 2, 3) for code in codes)
            for codes in normalized_allowed_codes
        ):
            raise ValueError("Target allowed codes must be nonempty subsets of 0..3.")
    else:
        normalized_allowed_codes = None
    protected_mask = (
        tuple(value in (0, 1) for value in forced_bits)
        if forced_bits is not None
        else None
    )
    objective = _dither_exhaustive_bayer_target(
        adjusted,
        target_width,
        target_height,
        settings,
        protected_mask,
    )

    diffuse = (
        settings.dither == DITHER_FLOYD_STEINBERG
        and settings.dither_amount > 0
    )
    strength = settings.dither_amount / 100.0
    phase_offsets = resolved_phase_offsets(settings)
    incoming = [
        [[0.0, 0.0, 0.0] for _ in range(target_width)]
        for _phase in phase_offsets
    ]
    bits = bytearray(target_width * target_height)

    for y in range(target_height):
        if cancelled is not None and cancelled():
            raise ConversionCancelled()
        row_offset = y * target_width
        base_row = objective[row_offset : row_offset + target_width]
        if diffuse:
            target_rows = tuple(
                tuple(
                    base_row[x]
                    if protected_mask is not None and protected_mask[row_offset + x]
                    else tuple(
                        _clamp_byte(
                            base_row[x][channel]
                            + incoming[phase_index][x][channel]
                        )
                        for channel in range(3)
                    )
                    for x in range(target_width)
                )
                for phase_index in range(len(phase_offsets))
            )
        else:
            target_rows = tuple(tuple(base_row) for _phase in phase_offsets)
        row_forced_bits = (
            forced_bits[row_offset : row_offset + target_width]
            if forced_bits is not None
            else None
        )
        row_allowed_codes = (
            normalized_allowed_codes[
                y * (target_width // 2) : (y + 1) * (target_width // 2)
            ]
            if normalized_allowed_codes is not None
            else None
        )
        row_bits = _optimize_row_exhaustive(
            target_rows,
            profile,
            settings.phase_offset,
            row_forced_bits,
            allowed_codes=row_allowed_codes,
            phase_offsets=phase_offsets,
            cancelled=cancelled,
        )
        bits[row_offset : row_offset + target_width] = row_bits

        if diffuse and y + 1 < target_height:
            actual_rows = tuple(
                _selected_phase_scanline(row_bits, profile, phase_offset)
                for phase_offset in phase_offsets
            )
            next_incoming = [
                [[0.0, 0.0, 0.0] for _ in range(target_width)]
                for _phase in phase_offsets
            ]
            forward = not settings.serpentine or not (y & 1)
            for phase_index, actual in enumerate(actual_rows):
                target_row = target_rows[phase_index]
                for x in range(target_width):
                    if protected_mask is not None and protected_mask[row_offset + x]:
                        continue
                    error = tuple(
                        (target_row[x][channel] - actual[x][channel]) * strength
                        for channel in range(3)
                    )
                    for destination, weight in vertical_diffusion_neighbors(
                        x,
                        forward=forward,
                    ):
                        if not 0 <= destination < target_width:
                            continue
                        next_offset = row_offset + target_width + destination
                        if protected_mask is not None and protected_mask[next_offset]:
                            continue
                        for channel in range(3):
                            next_incoming[phase_index][destination][channel] += (
                                error[channel] * weight
                            )
            incoming = next_incoming
        if progress is not None:
            progress(y + 1, target_height)

    if cancelled is not None and cancelled():
        raise ConversionCancelled()
    if settings.phase_offset == PHASE_ALL:
        preview = render_all_phase_grid(
            bits,
            target_width,
            target_height,
            profile,
            phase_offsets,
        )
        source_rmse = _all_phase_rmse(
            bits,
            target_width,
            target_height,
            profile,
            adjusted,
            phase_offsets,
        )
    else:
        preview = render_composite_artifacts(
            bits,
            target_width,
            target_height,
            profile,
            phase_offset=int(settings.phase_offset),
        )
        source_rmse = _signal_rmse(preview, adjusted)
    return ConversionResult(
        bits=bytes(bits),
        preview=preview,
        target_width=target_width,
        target_height=target_height,
        source_rmse=source_rmse,
    )


def _signal_rmse(preview: RenderedRaster, target: Sequence[RGB]) -> float:
    squared = 0
    for pixel, expected in enumerate(target):
        offset = pixel * 3
        squared += sum(
            (preview.pixels[offset + channel] - expected[channel]) ** 2
            for channel in range(3)
        )
    return math.sqrt(squared / (len(target) * 3))


def _all_phase_rmse(
    bits: Sequence[int],
    width: int,
    height: int,
    profile: str,
    target: Sequence[RGB],
    phase_offsets: Sequence[int] = (0, 1, 2, 3),
) -> float:
    """Return a reporting-only RMSE over separate phase renderings."""

    phases = tuple(phase_offsets)
    if not phases:
        raise ValueError("Phase-set RMSE requires at least one phase.")
    squared = 0
    for phase in phases:
        preview = render_composite_artifacts(
            bits,
            width,
            height,
            profile,
            phase_offset=phase,
        )
        for pixel, expected in enumerate(target):
            offset = pixel * 3
            squared += sum(
                (preview.pixels[offset + channel] - expected[channel]) ** 2
                for channel in range(3)
            )
    return math.sqrt(squared / (len(target) * 3 * len(phases)))


def convert_raster_to_composite(
    source: RenderedRaster,
    target_width: int,
    target_height: int,
    profile: str,
    settings: ConversionSettings,
    *,
    source_zero_mask: Sequence[bool] | None = None,
    target_locked_bits: Sequence[int | None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ConversionResult:
    """Convert an adapter raster into an artifact-optimized Mode-6 bitstream."""

    settings.validate()
    phase_offsets = resolved_phase_offsets(settings)
    adjusted = adjusted_signal_target(source, target_width, target_height, settings)
    forced_bits = _conversion_forced_bits(
        source_zero_mask,
        source.width,
        source.height,
        target_width,
        target_height,
        target_locked_bits=target_locked_bits,
        preserve_zero=settings.preserve_zero,
    )
    # Error diffusion quantizes against phase-specific nominal colors. Keep one
    # target per reachable phase so the all-phase beam objective can add their
    # independent costs without averaging either target or decoded RGB.
    phase_targets = tuple(
        dither_signal_target(
            adjusted,
            target_width,
            target_height,
            profile,
            replace(settings, phase_offset=phase_offset),
            forced_bits=forced_bits,
        )
        for phase_offset in phase_offsets
    )
    bits = optimize_signal_bits(
        phase_targets[0],
        target_width,
        target_height,
        profile,
        settings,
        phase_targets=phase_targets,
        forced_bits=forced_bits,
        cancelled=cancelled,
        progress=progress,
    )
    if cancelled is not None and cancelled():
        raise ConversionCancelled()
    if settings.phase_offset == PHASE_ALL:
        preview = render_all_phase_grid(
            bits,
            target_width,
            target_height,
            profile,
            phase_offsets,
        )
        source_rmse = _all_phase_rmse(
            bits,
            target_width,
            target_height,
            profile,
            adjusted,
            phase_offsets,
        )
    else:
        preview = render_composite_artifacts(
            bits,
            target_width,
            target_height,
            profile,
            phase_offset=int(settings.phase_offset),
        )
        source_rmse = _signal_rmse(preview, adjusted)
    return ConversionResult(
        bits=bits,
        preview=preview,
        target_width=target_width,
        target_height=target_height,
        source_rmse=source_rmse,
    )
