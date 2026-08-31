from __future__ import annotations

import unittest
from unittest.mock import patch

from composite_converter import (
    CONVERSION_EXHAUSTIVE,
    CONVERSION_MODE_LABELS,
    CONVERSION_MODES,
    CONVERSION_SIMPLE_PALETTE,
    CONVERSION_SIMULATED_NTSC,
    DITHER_BAYER,
    DITHER_FLOYD_STEINBERG,
    DITHER_NONE,
    PHASE_ALL,
    ConversionSettings,
    _dither_exhaustive_bayer_target,
    adjusted_signal_target,
    all_phase_window_costs,
    artifact_window_table,
    convert_raster_to_exhaustive,
    convert_raster_to_composite,
    convert_raster_to_simple_palette,
    dither_signal_target,
    phase_set_window_costs,
    render_all_phase_grid,
    render_simple_palette_bits,
    render_simple_palette_phase_grid,
    vertical_diffusion_neighbors,
)
from composite_signal import decode_mode6_scanline, render_composite_artifacts
from prince_dat import (
    COMPOSITE_PROFILE_OLD,
    DOSBOXX_CGA_COMPOSITE_OLD_COLORS,
    RenderedRaster,
)


class CompositeConverterTests(unittest.TestCase):
    def test_conversion_model_labels_are_exact_and_stable(self) -> None:
        self.assertEqual(
            CONVERSION_MODES,
            (
                CONVERSION_SIMPLE_PALETTE,
                CONVERSION_SIMULATED_NTSC,
                CONVERSION_EXHAUSTIVE,
            ),
        )
        self.assertEqual(
            CONVERSION_MODE_LABELS,
            {
                CONVERSION_SIMPLE_PALETTE: "Simply Palette",
                CONVERSION_SIMULATED_NTSC: "Simulated NTSC",
                CONVERSION_EXHAUSTIVE: "Exhaustive",
            },
        )

    def test_phase_all_is_supported_by_beam_for_a_reachable_subset(self) -> None:
        all_settings = ConversionSettings(
            dither=DITHER_NONE,
            phase_offset=PHASE_ALL,
            all_phase_offsets=(2,),
            preserve_zero=False,
        )
        selected_settings = ConversionSettings(
            dither=DITHER_NONE,
            phase_offset=2,
            preserve_zero=False,
        )
        source = RenderedRaster(2, 1, bytes((20, 50, 220, 210, 40, 20)), 3, "vga")
        universal = convert_raster_to_composite(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            all_settings,
        )
        selected = convert_raster_to_composite(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            selected_settings,
        )

        self.assertEqual(universal.bits, selected.bits)
        self.assertEqual(universal.preview.pixels, selected.preview.pixels)
        self.assertEqual((universal.preview.width, universal.preview.height), (4, 1))

    def test_beam_all_supports_every_dither_and_adjustment_control(self) -> None:
        source = RenderedRaster(
            2,
            2,
            bytes((30, 60, 210, 210, 50, 20, 40, 180, 90, 220, 200, 35)),
            3,
            "vga",
        )
        for dither in (DITHER_NONE, DITHER_BAYER, DITHER_FLOYD_STEINBERG):
            with self.subTest(dither=dither):
                result = convert_raster_to_composite(
                    source,
                    4,
                    2,
                    COMPOSITE_PROFILE_OLD,
                    ConversionSettings(
                        dither=dither,
                        dither_amount=80,
                        bayer_size=2,
                        serpentine=True,
                        brightness=10,
                        contrast=-5,
                        saturation=115,
                        gamma=1.1,
                        color_emphasis=75,
                        detail=70,
                        quality="balanced",
                        phase_offset=PHASE_ALL,
                        all_phase_offsets=(0, 2),
                        preserve_zero=False,
                    ),
                )
                self.assertEqual(len(result.bits), 8)
                self.assertEqual((result.preview.width, result.preview.height), (8, 2))

    def test_all_phase_offsets_must_be_nonempty_unique_and_valid(self) -> None:
        for phases in ((), (0, 0), (0, 4)):
            with self.subTest(phases=phases), self.assertRaises(ValueError):
                ConversionSettings(
                    phase_offset=PHASE_ALL,
                    all_phase_offsets=phases,
                ).validate()

    def test_simple_palette_uses_exact_fixed_color_and_four_bit_pattern(self) -> None:
        color = DOSBOXX_CGA_COMPOSITE_OLD_COLORS[12]
        source = RenderedRaster(2, 1, bytes(color * 2), 3, "vga")
        result = convert_raster_to_simple_palette(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            preserve_zero=False,
        )

        self.assertEqual(result.bits, bytes((1, 1, 0, 0)))
        self.assertEqual((result.preview.width, result.preview.height), (1, 1))
        self.assertEqual(result.preview.pixels, bytes(color))
        self.assertEqual(result.preview.mode, "simple-palette")
        self.assertEqual(result.source_rmse, 0.0)

    def test_simple_palette_all_uses_only_configured_phases(self) -> None:
        source = RenderedRaster(
            2,
            1,
            bytes((30, 70, 220, 30, 70, 220)),
            3,
            "vga",
        )
        universal = convert_raster_to_simple_palette(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            settings=ConversionSettings(
                dither=DITHER_NONE,
                phase_offset=PHASE_ALL,
                all_phase_offsets=(2,),
                preserve_zero=False,
            ),
            preserve_zero=False,
        )
        selected = convert_raster_to_simple_palette(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            settings=ConversionSettings(
                dither=DITHER_NONE,
                phase_offset=2,
                preserve_zero=False,
            ),
            preserve_zero=False,
        )

        self.assertEqual(universal.bits, selected.bits)
        self.assertEqual(universal.preview.pixels, selected.preview.pixels)

    def test_simple_palette_averages_two_320_style_pixels_into_one_cell(self) -> None:
        source = RenderedRaster(
            2,
            1,
            bytes((0, 0, 0, 255, 255, 255)),
            3,
            "vga",
        )
        result = convert_raster_to_simple_palette(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            preserve_zero=False,
        )

        # The unbiased average is mid-gray.  Patterns 5 and 10 have the same
        # fixed RGB value, so deterministic lower-index tie-breaking selects 5.
        self.assertEqual(result.bits, bytes((0, 1, 0, 1)))
        self.assertEqual(
            result.preview.pixels,
            bytes(DOSBOXX_CGA_COMPOSITE_OLD_COLORS[5]),
        )

    def test_simple_palette_uses_exact_average_without_floor_bias(self) -> None:
        source = RenderedRaster(
            2,
            1,
            bytes((65, 0, 65, 66, 0, 65)),
            3,
            "vga",
        )
        result = convert_raster_to_simple_palette(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            preserve_zero=False,
        )

        # The exact mean is (65.5, 0, 65). Flooring red to 65 would tie the
        # black and pattern-8 colors and incorrectly select black by index.
        self.assertEqual(result.bits, bytes((1, 0, 0, 0)))
        self.assertEqual(
            result.preview.pixels,
            bytes(DOSBOXX_CGA_COMPOSITE_OLD_COLORS[8]),
        )

    def test_simple_palette_zero_preservation_is_a_hard_bit_constraint(self) -> None:
        source = RenderedRaster(
            2,
            1,
            bytes((255, 255, 255, 255, 255, 255)),
            3,
            "vga",
        )
        result = convert_raster_to_simple_palette(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            source_zero_mask=(True, False),
            preserve_zero=True,
        )

        self.assertEqual(result.bits[:2], b"\x00\x00")
        self.assertEqual(result.bits, bytes((0, 0, 1, 1)))

    def test_simple_palette_renderer_keeps_adjacent_cells_independent(self) -> None:
        bits = bytes((0, 0, 1, 1, 1, 1, 0, 0))
        preview = render_simple_palette_bits(
            bits,
            8,
            1,
            COMPOSITE_PROFILE_OLD,
        )

        self.assertEqual((preview.width, preview.height), (2, 1))
        self.assertEqual(
            preview.pixels,
            bytes(
                DOSBOXX_CGA_COMPOSITE_OLD_COLORS[3]
                + DOSBOXX_CGA_COMPOSITE_OLD_COLORS[12]
            ),
        )

    def test_twelve_bit_table_matches_full_decoder_at_edges_and_interior(self) -> None:
        bits = tuple(
            int(value)
            for value in "00101110100101100011101010010110"
        )
        phase = 2
        decoded = decode_mode6_scanline(
            bits,
            COMPOSITE_PROFILE_OLD,
            phase_offset=phase,
        )
        table = artifact_window_table(COMPOSITE_PROFILE_OLD, phase)
        padded = (0,) * 5 + bits + (0,) * 6
        reconstructed = []
        for x in range(len(bits)):
            window = 0
            for bit in padded[x : x + 12]:
                window = (window << 1) | bit
            reconstructed.append(table[x & 3][window])
        self.assertEqual(tuple(reconstructed), decoded)

    def test_320_style_source_pixels_are_replicated_to_640_style_signal_samples(self) -> None:
        source = RenderedRaster(
            2,
            1,
            bytes((10, 20, 30, 200, 210, 220)),
            3,
            "vga",
        )
        target = adjusted_signal_target(
            source,
            4,
            1,
            ConversionSettings(dither=DITHER_NONE),
        )
        self.assertEqual(
            target,
            ((10, 20, 30), (10, 20, 30), (200, 210, 220), (200, 210, 220)),
        )

    def test_zero_dither_amount_is_identical_to_no_dither(self) -> None:
        target = tuple((index * 11, index * 7, index * 3) for index in range(16))
        none = dither_signal_target(
            target,
            8,
            2,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(dither=DITHER_NONE),
        )
        floyd_zero = dither_signal_target(
            target,
            8,
            2,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(
                dither=DITHER_FLOYD_STEINBERG,
                dither_amount=0,
            ),
        )
        self.assertEqual(floyd_zero, none)

    def test_bayer_and_floyd_modify_the_full_width_objective(self) -> None:
        target = tuple((110, 120, 130) for _ in range(64))
        bayer = dither_signal_target(
            target,
            16,
            4,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(dither=DITHER_BAYER, dither_amount=100),
        )
        floyd = dither_signal_target(
            target,
            16,
            4,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(dither=DITHER_FLOYD_STEINBERG, dither_amount=100),
        )
        self.assertNotEqual(bayer, target)
        self.assertNotEqual(floyd, target)
        self.assertNotEqual(bayer, floyd)

    def test_converter_returns_the_actual_signal_dimensions_and_decoder_output(self) -> None:
        source = RenderedRaster(
            8,
            2,
            bytes(
                component
                for y in range(2)
                for x in range(8)
                for component in (x * 31, y * 180, 255 - x * 31)
            ),
            3,
            "vga",
        )
        result = convert_raster_to_composite(
            source,
            16,
            2,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(dither=DITHER_NONE, quality="fast"),
        )
        expected = render_composite_artifacts(
            result.bits,
            16,
            2,
            COMPOSITE_PROFILE_OLD,
        )
        self.assertEqual((result.target_width, result.target_height), (16, 2))
        self.assertEqual((result.preview.width, result.preview.height), (16, 2))
        self.assertEqual(result.preview.pixels, expected.pixels)

    def test_preserve_zero_forces_corresponding_signal_bits_off(self) -> None:
        source = RenderedRaster(
            2,
            1,
            bytes((255, 255, 255, 255, 255, 255)),
            3,
            "vga",
        )
        result = convert_raster_to_composite(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(
                dither=DITHER_NONE,
                preserve_zero=True,
                quality="fast",
            ),
            source_zero_mask=(True, False),
        )
        self.assertEqual(result.bits[:2], b"\x00\x00")

    def test_exhaustive_honors_exact_target_mask_reference_bits(self) -> None:
        source = RenderedRaster(
            2,
            1,
            bytes((0, 0, 0, 0, 0, 0)),
            3,
            "vga",
        )
        result = convert_raster_to_exhaustive(
            source,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(
                dither=DITHER_NONE,
                preserve_zero=True,
                phase_offset=0,
            ),
            # -1 remains optimizer-controlled; 0/1 must match the target
            # archive's original transparency-mask reference exactly.
            target_locked_bits=(1, -1, 0, 1),
        )

        self.assertEqual(result.bits[0], 1)
        self.assertEqual(result.bits[2:], b"\x00\x01")

    def test_exhaustive_row_matches_brute_force_selected_phase_minimum(self) -> None:
        source = RenderedRaster(
            4,
            1,
            bytes(
                (
                    20, 35, 210,
                    210, 45, 30,
                    35, 205, 80,
                    220, 210, 40,
                )
            ),
            3,
            "vga",
        )
        settings = ConversionSettings(
            dither=DITHER_NONE,
            preserve_zero=False,
            phase_offset=2,
        )
        target = adjusted_signal_target(source, 8, 1, settings)
        result = convert_raster_to_exhaustive(
            source,
            8,
            1,
            COMPOSITE_PROFILE_OLD,
            settings,
        )

        def selected_phase_cost(bits: tuple[int, ...] | bytes) -> int:
            return sum(
                (actual[channel] - target[x][channel]) ** 2
                for x, actual in enumerate(
                    decode_mode6_scanline(
                        bits,
                        COMPOSITE_PROFILE_OLD,
                        phase_offset=settings.phase_offset,
                    )
                )
                for channel in range(3)
            )

        brute_force_minimum = min(
            selected_phase_cost(
                tuple((pattern >> (7 - x)) & 1 for x in range(8))
            )
            for pattern in range(256)
        )
        self.assertEqual(selected_phase_cost(result.bits), brute_force_minimum)

    def test_all_phase_window_cost_sums_independent_absolute_errors(self) -> None:
        sample_phase = 2
        window = 0x6A5
        targets = (
            (10, 20, 30),
            (80, 50, 25),
            (140, 160, 180),
            (250, 220, 190),
        )
        costs = all_phase_window_costs(
            COMPOSITE_PROFILE_OLD,
            sample_phase,
            targets,
        )
        expected = sum(
            abs(
                artifact_window_table(COMPOSITE_PROFILE_OLD, phase)[sample_phase][
                    window
                ][channel]
                - targets[phase][channel]
            )
            for phase in range(4)
            for channel in range(3)
        )
        self.assertEqual(costs[window], expected)

    def test_phase_set_window_cost_uses_only_requested_phases(self) -> None:
        sample_phase = 1
        window = 0x39A
        phases = (0, 2)
        targets = ((25, 50, 75), (200, 175, 150))
        costs = phase_set_window_costs(
            COMPOSITE_PROFILE_OLD,
            sample_phase,
            phases,
            targets,
        )
        expected = sum(
            abs(
                artifact_window_table(COMPOSITE_PROFILE_OLD, phase)[sample_phase][
                    window
                ][channel]
                - targets[index][channel]
            )
            for index, phase in enumerate(phases)
            for channel in range(3)
        )
        self.assertEqual(costs[window], expected)

    def test_exhaustive_all_matches_brute_force_four_phase_absolute_minimum(self) -> None:
        source = RenderedRaster(
            4,
            1,
            bytes(
                (
                    15, 50, 220,
                    220, 35, 25,
                    25, 200, 95,
                    230, 205, 30,
                )
            ),
            3,
            "vga",
        )
        settings = ConversionSettings(
            dither=DITHER_NONE,
            preserve_zero=False,
            phase_offset=PHASE_ALL,
        )
        target = adjusted_signal_target(source, 8, 1, settings)
        result = convert_raster_to_exhaustive(
            source,
            8,
            1,
            COMPOSITE_PROFILE_OLD,
            settings,
        )

        def all_phase_cost(bits: tuple[int, ...] | bytes) -> int:
            return sum(
                abs(actual[channel] - target[x][channel])
                for phase in range(4)
                for x, actual in enumerate(
                    decode_mode6_scanline(
                        bits,
                        COMPOSITE_PROFILE_OLD,
                        phase_offset=phase,
                    )
                )
                for channel in range(3)
            )

        brute_force_minimum = min(
            all_phase_cost(tuple((pattern >> (7 - x)) & 1 for x in range(8)))
            for pattern in range(256)
        )
        self.assertEqual(all_phase_cost(result.bits), brute_force_minimum)
        self.assertEqual((result.preview.width, result.preview.height), (16, 2))
        self.assertEqual(result.preview.mode, "composite-all-phases")

    def test_exhaustive_all_matches_only_reachable_phase_subset(self) -> None:
        source = RenderedRaster(
            4,
            1,
            bytes(
                (
                    15, 50, 220,
                    220, 35, 25,
                    25, 200, 95,
                    230, 205, 30,
                )
            ),
            3,
            "vga",
        )
        phases = (0, 2)
        settings = ConversionSettings(
            dither=DITHER_NONE,
            preserve_zero=False,
            phase_offset=PHASE_ALL,
            all_phase_offsets=phases,
        )
        target = adjusted_signal_target(source, 8, 1, settings)
        result = convert_raster_to_exhaustive(
            source,
            8,
            1,
            COMPOSITE_PROFILE_OLD,
            settings,
        )

        def reachable_phase_cost(bits: tuple[int, ...] | bytes) -> int:
            return sum(
                abs(actual[channel] - target[x][channel])
                for phase in phases
                for x, actual in enumerate(
                    decode_mode6_scanline(
                        bits,
                        COMPOSITE_PROFILE_OLD,
                        phase_offset=phase,
                    )
                )
                for channel in range(3)
            )

        brute_force_minimum = min(
            reachable_phase_cost(tuple((pattern >> (7 - x)) & 1 for x in range(8)))
            for pattern in range(256)
        )
        self.assertEqual(reachable_phase_cost(result.bits), brute_force_minimum)
        self.assertEqual((result.preview.width, result.preview.height), (16, 1))

    def test_all_phase_preview_grid_copies_each_phase_without_blending(self) -> None:
        bits = tuple(int(bit) for bit in "0010111010010110")
        width = 8
        height = 2
        grid = render_all_phase_grid(
            bits,
            width,
            height,
            COMPOSITE_PROFILE_OLD,
        )
        self.assertEqual((grid.width, grid.height), (16, 4))
        for phase in range(4):
            raster = render_composite_artifacts(
                bits,
                width,
                height,
                COMPOSITE_PROFILE_OLD,
                phase_offset=phase,
            )
            left = (phase & 1) * width
            top = (phase >> 1) * height
            for y in range(height):
                grid_start = ((top + y) * grid.width + left) * 3
                phase_start = y * width * 3
                self.assertEqual(
                    grid.pixels[grid_start : grid_start + width * 3],
                    raster.pixels[phase_start : phase_start + width * 3],
                )

    def test_phase_preview_grids_omit_unused_phases(self) -> None:
        bits = tuple(int(bit) for bit in "00101110")
        phases = (0, 2)
        signal = render_all_phase_grid(
            bits,
            8,
            1,
            COMPOSITE_PROFILE_OLD,
            phases,
        )
        simple = render_simple_palette_phase_grid(
            bits,
            8,
            1,
            COMPOSITE_PROFILE_OLD,
            phases,
        )

        self.assertEqual((signal.width, signal.height), (16, 1))
        self.assertEqual((simple.width, simple.height), (4, 1))
        for panel, phase in enumerate(phases):
            decoded = render_composite_artifacts(
                bits,
                8,
                1,
                COMPOSITE_PROFILE_OLD,
                phase_offset=phase,
            )
            start = panel * 8 * 3
            self.assertEqual(signal.pixels[start : start + 8 * 3], decoded.pixels)
            fixed = render_simple_palette_bits(
                bits,
                8,
                1,
                COMPOSITE_PROFILE_OLD,
                phase_offset=phase,
            )
            start = panel * 2 * 3
            self.assertEqual(simple.pixels[start : start + 2 * 3], fixed.pixels)

    def test_exhaustive_bits_and_preview_follow_selected_phase(self) -> None:
        source = RenderedRaster(
            4,
            1,
            bytes((25, 70, 220, 210, 45, 20, 35, 190, 90, 220, 210, 35)),
            3,
            "vga",
        )
        phase_zero = convert_raster_to_exhaustive(
            source,
            8,
            1,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(
                dither=DITHER_NONE,
                preserve_zero=False,
                phase_offset=0,
            ),
        )
        phase_three = convert_raster_to_exhaustive(
            source,
            8,
            1,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(
                dither=DITHER_NONE,
                preserve_zero=False,
                phase_offset=3,
            ),
        )
        self.assertNotEqual(phase_zero.bits, phase_three.bits)
        self.assertNotEqual(phase_zero.preview.pixels, phase_three.preview.pixels)

    def test_exhaustive_keeps_solid_ega_blue_stable_at_selected_phase(self) -> None:
        source = RenderedRaster(
            32,
            1,
            bytes((0, 0, 170) * 32),
            3,
            "ega",
        )
        result = convert_raster_to_exhaustive(
            source,
            64,
            1,
            COMPOSITE_PROFILE_OLD,
            ConversionSettings(
                dither=DITHER_NONE,
                preserve_zero=False,
                phase_offset=0,
            ),
        )
        decoded = decode_mode6_scanline(
            result.bits,
            COMPOSITE_PROFILE_OLD,
            phase_offset=0,
        )
        interior = decoded[8:-8]
        self.assertLessEqual(len(set(interior)), 4)
        mean = tuple(
            sum(pixel[channel] for pixel in interior) / len(interior)
            for channel in range(3)
        )
        self.assertGreater(mean[2], mean[0] + 40)
        self.assertGreater(mean[2], mean[1] + 40)

    def test_exhaustive_bayer_operates_on_each_signal_pixel(self) -> None:
        target = ((128, 128, 128),) * 4
        output = _dither_exhaustive_bayer_target(
            target,
            4,
            1,
            ConversionSettings(
                dither=DITHER_BAYER,
                dither_amount=100,
                bayer_size=2,
            ),
            None,
        )
        self.assertNotEqual(output[0], output[1])
        self.assertNotEqual(output[1], output[2])

    def test_vertical_diffusion_weights_mirror_for_serpentine_rows(self) -> None:
        self.assertEqual(
            vertical_diffusion_neighbors(10, forward=True),
            ((11, 8.0 / 16.0), (10, 5.0 / 16.0), (9, 3.0 / 16.0)),
        )
        self.assertEqual(
            vertical_diffusion_neighbors(10, forward=False),
            ((9, 8.0 / 16.0), (10, 5.0 / 16.0), (11, 3.0 / 16.0)),
        )
        self.assertEqual(
            sum(weight for _destination, weight in vertical_diffusion_neighbors(10, forward=True)),
            1.0,
        )

    def test_exhaustive_diffusion_waits_until_row_is_chosen(self) -> None:
        source = RenderedRaster(
            2,
            2,
            bytes((100, 100, 100) * 4),
            3,
            "vga",
        )
        optimized_targets: list[
            tuple[tuple[tuple[int, int, int], ...], ...]
        ] = []

        def fake_optimize(target_rows, _profile, _phase, _forced_zero, **_kwargs):
            optimized_targets.append(
                tuple(tuple(target_row) for target_row in target_rows)
            )
            return bytes(len(target_rows[0]))

        with patch(
            "composite_converter._optimize_row_exhaustive",
            side_effect=fake_optimize,
        ), patch(
            "composite_converter._selected_phase_scanline",
            return_value=((0, 0, 0),) * 4,
        ):
            convert_raster_to_exhaustive(
                source,
                4,
                2,
                COMPOSITE_PROFILE_OLD,
                ConversionSettings(
                    dither=DITHER_FLOYD_STEINBERG,
                    dither_amount=100,
                    serpentine=True,
                    preserve_zero=False,
                ),
            )

        self.assertEqual(optimized_targets[0], (((100, 100, 100),) * 4,))
        self.assertEqual(
            optimized_targets[1],
            ((
                (150, 150, 150),
                (200, 200, 200),
                (200, 200, 200),
                (181, 181, 181),
            ),),
        )

    def test_exhaustive_all_diffuses_only_reachable_phase_errors(self) -> None:
        source = RenderedRaster(
            2,
            2,
            bytes((100, 100, 100) * 4),
            3,
            "vga",
        )
        optimized_targets: list[
            tuple[tuple[tuple[int, int, int], ...], ...]
        ] = []

        def fake_optimize(target_rows, _profile, _phase, _forced_zero, **_kwargs):
            optimized_targets.append(
                tuple(tuple(target_row) for target_row in target_rows)
            )
            return bytes(len(target_rows[0]))

        def fake_decode(_bits, _profile, phase_offset):
            value = (0, 50, 100, 200)[phase_offset]
            return ((value, value, value),) * 4

        with patch(
            "composite_converter._optimize_row_exhaustive",
            side_effect=fake_optimize,
        ), patch(
            "composite_converter._selected_phase_scanline",
            side_effect=fake_decode,
        ):
            convert_raster_to_exhaustive(
                source,
                4,
                2,
                COMPOSITE_PROFILE_OLD,
                ConversionSettings(
                    dither=DITHER_FLOYD_STEINBERG,
                    dither_amount=100,
                    serpentine=True,
                    preserve_zero=False,
                    phase_offset=PHASE_ALL,
                    all_phase_offsets=(0, 2),
                ),
            )

        self.assertEqual(
            optimized_targets[0],
            tuple((((100, 100, 100),) * 4) for _phase in (0, 2)),
        )
        self.assertEqual(
            optimized_targets[1],
            (
                (
                    (150, 150, 150),
                    (200, 200, 200),
                    (200, 200, 200),
                    (181, 181, 181),
                ),
                ((100, 100, 100),) * 4,
            ),
        )

    def test_exhaustive_honors_representable_two_bit_codes(self) -> None:
        source = RenderedRaster(1, 1, bytes((255, 255, 255)), 3, "vga")
        settings = ConversionSettings(
            dither=DITHER_NONE,
            dither_amount=0,
            preserve_zero=False,
        )
        code_zero = convert_raster_to_exhaustive(
            source,
            2,
            1,
            COMPOSITE_PROFILE_OLD,
            settings,
            target_allowed_codes=((0,),),
        )
        code_two = convert_raster_to_exhaustive(
            source,
            2,
            1,
            COMPOSITE_PROFILE_OLD,
            settings,
            target_allowed_codes=((2,),),
        )
        self.assertEqual(code_zero.bits, b"\x00\x00")
        self.assertEqual(code_two.bits, b"\x01\x00")

    def test_exhaustive_rejects_invalid_allowed_codes(self) -> None:
        source = RenderedRaster(1, 1, bytes((255, 255, 255)), 3, "vga")
        settings = ConversionSettings(preserve_zero=False)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            convert_raster_to_exhaustive(
                source,
                2,
                1,
                COMPOSITE_PROFILE_OLD,
                settings,
                target_allowed_codes=(),
            )
        with self.assertRaisesRegex(ValueError, "nonempty subsets"):
            convert_raster_to_exhaustive(
                source,
                2,
                1,
                COMPOSITE_PROFILE_OLD,
                settings,
                target_allowed_codes=((1, 4),),
            )


if __name__ == "__main__":
    unittest.main()
