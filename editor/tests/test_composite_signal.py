from __future__ import annotations

import unittest

from composite_signal import decode_mode6_scanline, render_composite_artifacts
from prince_dat import COMPOSITE_PROFILE_NEW, COMPOSITE_PROFILE_OLD


class CompositeSignalTests(unittest.TestCase):
    SAMPLE_BITS = (
        0, 0, 0, 0,
        1, 1, 1, 1,
        0, 1, 0, 1,
        1, 0, 1, 0,
    )

    def test_old_cga_scanline_matches_cga_image_studio_reference(self) -> None:
        self.assertEqual(
            decode_mode6_scanline(self.SAMPLE_BITS, COMPOSITE_PROFILE_OLD),
            (
                (12, 0, 0), (59, 0, 0), (90, 47, 100), (159, 157, 180),
                (241, 212, 238), (255, 225, 255), (229, 199, 246), (148, 147, 163),
                (109, 142, 125), (76, 142, 93), (131, 166, 116), (177, 179, 156),
                (126, 155, 129), (85, 143, 92), (49, 79, 32), (13, 12, 32),
            ),
        )

    def test_new_cga_scanline_matches_cga_image_studio_reference(self) -> None:
        self.assertEqual(
            decode_mode6_scanline(self.SAMPLE_BITS, COMPOSITE_PROFILE_NEW),
            (
                (15, 0, 0), (90, 0, 0), (115, 40, 109), (186, 185, 204),
                (255, 234, 255), (255, 236, 255), (255, 210, 255), (160, 159, 175),
                (107, 170, 139), (52, 178, 100), (139, 203, 139), (204, 205, 186),
                (119, 180, 145), (56, 178, 99), (21, 84, 20), (0, 0, 52),
            ),
        )

    def test_neighbor_transition_changes_pixels_inside_a_nominal_cell(self) -> None:
        decoded = decode_mode6_scanline(self.SAMPLE_BITS, COMPOSITE_PROFILE_NEW)

        # The first nominal 0000 cell is not flat black: the following 1111
        # transition bleeds color and luma left through the decoder kernel.
        self.assertGreater(len(set(decoded[:4])), 1)
        self.assertNotEqual(decoded[0], (0, 0, 0))

    def test_renderer_keeps_full_mode6_sample_width_and_rgba(self) -> None:
        bits = self.SAMPLE_BITS + self.SAMPLE_BITS
        rendered = render_composite_artifacts(
            bits,
            width=16,
            height=2,
            profile=COMPOSITE_PROFILE_NEW,
            channels=4,
        )

        self.assertEqual((rendered.width, rendered.height), (16, 2))
        self.assertEqual(rendered.channels, 4)
        self.assertEqual(rendered.mode, "composite-artifact")
        self.assertTrue(all(rendered.pixels[index] == 255 for index in range(3, len(rendered.pixels), 4)))

    def test_non_multiple_of_four_width_is_right_padded_then_cropped(self) -> None:
        rendered = render_composite_artifacts(
            (1, 0, 1, 0, 1),
            width=5,
            height=1,
            profile=COMPOSITE_PROFILE_OLD,
        )
        self.assertEqual((rendered.width, len(rendered.pixels)), (5, 15))

    def test_phase_offset_changes_color_without_changing_output_dimensions(self) -> None:
        phase_zero = render_composite_artifacts(
            self.SAMPLE_BITS,
            width=16,
            height=1,
            profile=COMPOSITE_PROFILE_OLD,
            phase_offset=0,
        )
        phase_one = render_composite_artifacts(
            self.SAMPLE_BITS,
            width=16,
            height=1,
            profile=COMPOSITE_PROFILE_OLD,
            phase_offset=1,
        )
        self.assertEqual(
            (phase_zero.width, phase_zero.height),
            (phase_one.width, phase_one.height),
        )
        self.assertNotEqual(phase_zero.pixels, phase_one.pixels)

    def test_phase_offset_rejects_values_outside_one_color_cycle(self) -> None:
        with self.assertRaises(ValueError):
            decode_mode6_scanline(
                self.SAMPLE_BITS,
                COMPOSITE_PROFILE_OLD,
                phase_offset=4,
            )


if __name__ == "__main__":
    unittest.main()
