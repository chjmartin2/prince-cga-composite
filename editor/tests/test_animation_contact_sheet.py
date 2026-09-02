from __future__ import annotations

from pathlib import Path
import unittest

from animation_contact_sheet import (
    KID_ANIMATION_FAMILIES, _runtime_direction_bits, animation_image_records,
    render_animation_contact_sheet,
)
from composite_project import CompositeEdit, CompositeProject
from prince_dat import DatArchive, DatResource, DecodedImage, ResourceAnalysis, png_bytes


def image_archive(name: str = "KID.DAT") -> DatArchive:
    resources = [DatResource(index, 401 + index, 6, 7, 0, 0, True, b"") for index in range(3)]
    analyses = [
        ResourceAnalysis(
            resource, "4-bit image",
            image=DecodedImage(2, 2, 4, 0xB0, 0, b"", bytes((1, 1, 0, 0))),
        ) for resource in resources[:2]
    ]
    analyses.append(ResourceAnalysis(resources[2], "non-image resource"))
    return DatArchive(Path(name), b"fixture", 0, 0, resources, analyses, [])


class AnimationContactSheetTests(unittest.TestCase):
    def test_authoritative_families_cover_every_kid_image_once(self) -> None:
        image_ids = [image_id for family in KID_ANIMATION_FAMILIES for image_id in family.image_ids]
        self.assertEqual(image_ids, list(range(219)))

    def test_generic_discovery_uses_every_editable_image_in_archive_order(self) -> None:
        archive = image_archive("GUARD.DAT")
        self.assertEqual([record.resource.resource_id for record in animation_image_records(archive)], [401, 402])

    def test_non_kid_sheet_renders_without_mutating_active_phase(self) -> None:
        archive = image_archive("GUARD.DAT")
        project = CompositeProject("GUARD.DAT", 1, "0" * 64)
        edit = CompositeEdit(
            resource_index=0, resource_id=401, source_width=2, height=2,
            source_depth=4, bit_width=4, bits=bytearray((1, 1, 0, 0) * 2),
            signal_phase=0,
            phase_variants={0: bytearray((1, 1, 0, 0) * 2), 2: bytearray((0, 0, 1, 1) * 2)},
            enabled_phases=(0, 2), fallback_phase=0,
        )
        project.edits[0] = edit
        first = render_animation_contact_sheet(archive, project)
        second = render_animation_contact_sheet(archive, project)
        self.assertEqual(first, second)
        self.assertEqual(first.channels, 3)
        self.assertEqual(len(first.pixels), first.width * first.height * 3)
        self.assertEqual(edit.signal_phase, 0)
        self.assertTrue(png_bytes(first.width, first.height, first.pixels).startswith(b"\x89PNG"))

    def test_one_bit_flip_reverses_individual_samples(self) -> None:
        self.assertEqual(_runtime_direction_bits(bytes((1, 0, 0)), 3, 1, "right", 1), bytes((0, 0, 1)))

    def test_archive_without_images_is_rejected(self) -> None:
        archive = image_archive("SOUND.DAT")
        archive.analyses = [ResourceAnalysis(archive.resources[2], "sound")]
        with self.assertRaisesRegex(ValueError, "no editable"):
            render_animation_contact_sheet(archive, CompositeProject("SOUND.DAT", 1, "0" * 64))


if __name__ == "__main__":
    unittest.main()
