from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from composite_project import CompositeProject, write_patched_dat
from prince_dat import DatArchive
from room_sets import ArchiveContext, RoomSetError, identify_room_set


def image_resource(width: int, height: int, first_index: int = 0) -> bytes:
    pixels = [(first_index + index) & 0x0F for index in range(width * height)]
    packed = bytearray()
    for start in range(0, len(pixels), 2):
        high = pixels[start]
        low = pixels[start + 1] if start + 1 < len(pixels) else 0
        packed.append((high << 4) | low)
    return struct.pack("<HHBB", height, width, 0, 0xB0) + bytes(packed)


def build_dat(resources: list[tuple[int, bytes]]) -> bytes:
    body = bytearray(6)
    records: list[tuple[int, int, int]] = []
    for resource_id, content in resources:
        offset = len(body)
        checksum = (-1 - sum(content)) & 0xFF
        body.extend(bytes((checksum,)) + content)
        records.append((resource_id, offset, len(content)))
    index_offset = len(body)
    index_size = 2 + len(records) * 8
    struct.pack_into("<IH", body, 0, index_offset, index_size)
    body.extend(struct.pack("<H", len(records)))
    for record in records:
        body.extend(struct.pack("<HIH", *record))
    return bytes(body)


def write_archive(
    folder: Path,
    name: str,
    resources: list[tuple[int, bytes]] | None = None,
) -> DatArchive:
    path = folder / name
    path.write_bytes(
        build_dat(resources or [(100, image_resource(2, 1))])
    )
    return DatArchive.open(path)


class RoomSetIdentityTests(unittest.TestCase):
    def test_identifies_all_six_conventional_room_archives(self) -> None:
        expected = {
            "CDUNGEON.DAT": ("cga", "DUNGEON"),
            "edungeon.dat": ("ega", "DUNGEON"),
            "VDUNGEON.DAT": ("vga", "DUNGEON"),
            "CPALACE.DAT": ("cga", "PALACE"),
            "EPALACE.DAT": ("ega", "PALACE"),
            "vpalace.dat": ("vga", "PALACE"),
        }
        for filename, identity in expected.items():
            with self.subTest(filename=filename):
                member = identify_room_set(filename)
                self.assertIsNotNone(member)
                assert member is not None
                self.assertEqual((member.adapter, member.family), identity)
        self.assertIsNone(identify_room_set("KID.DAT"))


class ArchiveContextTests(unittest.TestCase):
    def test_discovers_siblings_and_matches_images_by_id_not_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cga = write_archive(
                folder,
                "CDUNGEON.DAT",
                [(100, image_resource(2, 1, 1)), (200, image_resource(4, 1, 2))],
            )
            write_archive(
                folder,
                "EDUNGEON.DAT",
                [(200, image_resource(6, 1, 3)), (100, image_resource(3, 1, 4))],
            )
            write_archive(
                folder,
                "VDUNGEON.DAT",
                [(200, image_resource(8, 1, 5)), (100, image_resource(5, 1, 6))],
            )
            context = ArchiveContext.discover(cga)

        self.assertTrue(context.is_room_set)
        self.assertEqual(context.composite_target.path.name, "CDUNGEON.DAT")
        vga_archive, vga = context.analysis_for_display_mode("vga", 100)  # type: ignore[misc]
        ega_archive, ega = context.analysis_for_display_mode("ega", 100)  # type: ignore[misc]
        cga_archive, cga_analysis = context.analysis_for_display_mode("composite", 100)  # type: ignore[misc]
        self.assertEqual((vga_archive.path.name, vga.resource.index, vga.image.width), ("VDUNGEON.DAT", 1, 5))
        self.assertEqual((ega_archive.path.name, ega.resource.index, ega.image.width), ("EDUNGEON.DAT", 1, 3))
        self.assertEqual((cga_archive.path.name, cga_analysis.resource.index, cga_analysis.image.width), ("CDUNGEON.DAT", 0, 2))

    def test_opening_vga_primary_still_binds_project_to_cga_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cga = write_archive(folder, "CPALACE.DAT")
            write_archive(folder, "EPALACE.DAT")
            vga = write_archive(folder, "VPALACE.DAT")
            context = ArchiveContext.discover(vga)
            project = CompositeProject.for_archive(context.composite_target)  # type: ignore[arg-type]

        self.assertIsNot(context.primary, context.composite_target)
        self.assertEqual(context.composite_target.path, cga.path)
        self.assertEqual(project.source_name, "CPALACE.DAT")

    def test_patched_room_output_rebuilds_only_c_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cga = write_archive(folder, "CDUNGEON.DAT")
            ega = write_archive(folder, "EDUNGEON.DAT", [(100, image_resource(4, 1, 4))])
            vga = write_archive(folder, "VDUNGEON.DAT", [(100, image_resource(6, 1, 8))])
            ega_before = ega.path.read_bytes()
            vga_before = vga.path.read_bytes()
            context = ArchiveContext.discover(vga)
            target = context.composite_target
            assert target is not None
            analysis = target.analysis_by_id(100)
            assert analysis is not None and analysis.image is not None
            project = CompositeProject.for_archive(target)
            edit = project.edit_for_image(
                target, analysis.resource.index, analysis.image
            )
            edit.set_pattern(0, 0, 0b1111)
            output, changed = write_patched_dat(
                target, project, folder / "CDUNGEON_COMPOSITE.DAT"
            )

            self.assertEqual(changed, 1)
            self.assertNotEqual(output.read_bytes(), cga.path.read_bytes())
            self.assertEqual(ega.path.read_bytes(), ega_before)
            self.assertEqual(vga.path.read_bytes(), vga_before)

    def test_missing_companion_is_explicit_and_does_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            vga = write_archive(Path(temp), "VDUNGEON.DAT")
            context = ArchiveContext.discover(vga)

        self.assertIsNone(context.composite_target)
        self.assertIsNone(context.analysis_for_display_mode("cga", 100))
        self.assertIn("CDUNGEON.DAT unavailable", context.source_description("composite"))
        self.assertEqual(context.archive_for_display_mode("vga"), vga)

    def test_manual_reference_rejects_wrong_family_and_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            cga = write_archive(folder, "CDUNGEON.DAT")
            wrong_family = write_archive(folder, "VPALACE.DAT")
            wrong_adapter = write_archive(folder, "EDUNGEON.DAT")
            context = ArchiveContext.discover(cga)
            with self.assertRaises(RoomSetError):
                context.attach("vga", wrong_family)
            with self.assertRaises(RoomSetError):
                context.attach("vga", wrong_adapter)

    def test_non_room_archive_uses_one_shared_source_for_every_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = write_archive(Path(temp), "KID.DAT")
            context = ArchiveContext.discover(archive)

        self.assertFalse(context.is_room_set)
        for mode in (
            "vga",
            "ega",
            "cga",
            "mode6",
            "composite",
            "ntsc-composite",
        ):
            with self.subTest(mode=mode):
                resolved = context.analysis_for_display_mode(mode, 100)
                self.assertIsNotNone(resolved)
                self.assertIs(resolved[0], archive)  # type: ignore[index]

    def test_analysis_by_id_returns_none_for_missing_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = write_archive(Path(temp), "KID.DAT")
        self.assertEqual(archive.analysis_by_id(100).resource.resource_id, 100)  # type: ignore[union-attr]
        self.assertIsNone(archive.analysis_by_id(999))


if __name__ == "__main__":
    unittest.main()
