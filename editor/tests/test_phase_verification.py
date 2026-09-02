from __future__ import annotations

import unittest

from composite_project import CompositeEdit, CompositeProject
from phase_verification import (
    CARD_BACKGROUND,
    MISSING_BACKGROUND,
    render_phase_verification_sheet,
)
from prince_dat import png_bytes


def make_edit(resource_index, resource_id, phases, patterns):
    variants = {
        phase: bytearray(patterns[phase])
        for phase in phases
    }
    return CompositeEdit(
        resource_index=resource_index,
        resource_id=resource_id,
        source_width=4,
        height=2,
        source_depth=4,
        bit_width=8,
        bits=variants[phases[0]],
        signal_phase=phases[0],
        phase_variants=variants,
        enabled_phases=phases,
        fallback_phase=phases[0],
    )


class PhaseVerificationSheetTests(unittest.TestCase):
    def test_empty_project_is_rejected(self) -> None:
        project = CompositeProject("KID.DAT", 1, "0" * 64)
        with self.assertRaisesRegex(ValueError, "at least one editable image"):
            render_phase_verification_sheet(project)

    def test_sheet_contains_every_resource_and_union_phase(self) -> None:
        project = CompositeProject("KID.DAT", 1, "0" * 64)
        project.edits[1] = make_edit(
            1,
            401,
            (0, 2),
            {
                0: (1, 1, 0, 0, 1, 1, 0, 0) * 2,
                2: (0, 0, 1, 1, 0, 0, 1, 1) * 2,
            },
        )
        project.edits[2] = make_edit(
            2,
            402,
            (2,),
            {2: (1, 0, 1, 0, 1, 0, 1, 0) * 2},
        )

        sheet = render_phase_verification_sheet(project)

        # Two union-phase columns and two resource rows at 3x sprite scale.
        self.assertEqual((sheet.width, sheet.height), (168, 110))
        self.assertEqual(sheet.channels, 3)
        self.assertEqual(len(sheet.pixels), sheet.width * sheet.height * 3)
        self.assertIn(bytes(CARD_BACKGROUND), sheet.pixels)
        self.assertIn(bytes(MISSING_BACKGROUND), sheet.pixels)
        self.assertTrue(png_bytes(sheet.width, sheet.height, sheet.pixels).startswith(b"\x89PNG"))

    def test_render_is_deterministic_and_does_not_change_active_phase(self) -> None:
        project = CompositeProject("KID.DAT", 1, "0" * 64)
        edit = make_edit(
            1,
            401,
            (0, 2),
            {
                0: (1, 1, 0, 0, 1, 1, 0, 0) * 2,
                2: (0, 0, 1, 1, 0, 0, 1, 1) * 2,
            },
        )
        project.edits[1] = edit

        first = render_phase_verification_sheet(project)
        second = render_phase_verification_sheet(project)

        self.assertEqual(first, second)
        self.assertEqual(edit.signal_phase, 0)
        self.assertEqual(len(first.pixels), first.width * first.height * 3)

    def test_single_small_phase_still_fits_complete_header(self) -> None:
        project = CompositeProject("KID.DAT", 1, "0" * 64)
        project.edits[1] = make_edit(
            1,
            401,
            (0,),
            {0: (1, 0, 1, 0, 1, 0, 1, 0) * 2},
        )

        sheet = render_phase_verification_sheet(project)

        self.assertEqual(sheet.width, 168)
        self.assertEqual(len(sheet.pixels), sheet.width * sheet.height * 3)


if __name__ == "__main__":
    unittest.main()
