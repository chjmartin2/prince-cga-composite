from __future__ import annotations

from pathlib import Path
import struct
import tempfile
import unittest

from composite_project import CompositeProjectError, initial_mode6_bits
from orientation_workspace import (
    EXPECTED_ORIENT_IDS,
    TABLES,
    V22OrientationWorkspace,
    reverse_mode6_cga_pixel_rows,
    uses_v22_workspace,
)
from prince_dat import DatArchive, hardware_palette_for_resource


def build_dat(resources: list[tuple[int, bytes]]) -> bytes:
    body = bytearray(6)
    records = []
    for resource_id, content in resources:
        offset = len(body)
        body.extend(bytes(((-1 - sum(content)) & 0xFF,)) + content)
        records.append((resource_id, offset, len(content)))
    index_offset = len(body)
    index_size = 2 + len(records) * 8
    struct.pack_into("<IH", body, 0, index_offset, index_size)
    body.extend(struct.pack("<H", len(records)))
    for record in records:
        body.extend(struct.pack("<HIH", *record))
    return bytes(body)


def palette_resource(count: int) -> bytes:
    palette = bytearray(100)
    palette[0] = count
    palette[1:4] = b"\x00\x00\x10"
    for index in range(16):
        palette[4 + index * 3 : 7 + index * 3] = bytes((index * 4, index * 3, index * 2))
    values = [index & 3 for _phase in range(4) for index in range(16)]
    palette[52:68] = bytes(
        (values[i] << 6) | (values[i + 1] << 4) | (values[i + 2] << 2) | values[i + 3]
        for i in range(0, 64, 4)
    )
    palette[68:100] = bytes(
        (values[i] << 4) | values[i + 1] for i in range(0, 64, 2)
    )
    return bytes(palette)


def image_resource(payload: int = 0x11) -> bytes:
    return struct.pack("<HHBB", 1, 2, 0, 0xB0) + bytes((payload,))


def orient_resources() -> list[tuple[int, bytes]]:
    headers = {table.header_id: table for table in TABLES}
    result = []
    for resource_id in EXPECTED_ORIENT_IDS:
        table = headers.get(resource_id)
        if table is None:
            result.append((resource_id, image_resource()))
        else:
            count = table.count if not (table.right_first and table.left_first) else table.count * 2
            result.append((resource_id, palette_resource(count)))
    return result


class V22OrientationWorkspaceTests(unittest.TestCase):
    def test_normal_editor_routes_dedicated_actor_families_to_v22(self) -> None:
        for name in ("KID.DAT", "GUARD-custom.DAT", "FAT.DAT", "VIZIER.DAT", "PV.DAT"):
            self.assertTrue(uses_v22_workspace(name))
        for name in ("SKEL.DAT", "SHADOW.DAT", "CDUNGEON.DAT"):
            self.assertFalse(uses_v22_workspace(name))

    def make_workspace(self, temp: str, family: str = "KID") -> V22OrientationWorkspace:
        source_table = next(table for table in TABLES if table.archive == family)
        source = [
            (source_table.source_first + index, image_resource())
            for index in range(source_table.count)
        ]
        source_path = Path(temp) / f"{family}.DAT"
        orient_path = Path(temp) / "ORIENT.DAT"
        source_path.write_bytes(build_dat(source))
        orient_path.write_bytes(build_dat(orient_resources()))
        return V22OrientationWorkspace.open(
            source_path, orient_path, require_standard_source=False
        )

    def test_exact_layout_and_family_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(temp)
            self.assertEqual(len(workspace.orient.resources), 889)
            self.assertEqual(len(workspace.pairs), 219)
            first = workspace.pairs[0]
            last = workspace.pairs[-1]
            self.assertEqual((first.source_resource_id, first.right_resource_id, first.left_resource_id), (401, 1001, 2001))
            self.assertEqual((last.source_resource_id, last.right_resource_id, last.left_resource_id), (619, 1219, 2219))

    def test_guard_contexts_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(temp, "GUARD")
            self.assertEqual(len(workspace.pairs), 68)
            dungeon = workspace.pair(751, context="Dungeon")
            palace = workspace.pair(751, context="Palace")
            self.assertEqual((dungeon.right_resource_id, dungeon.left_resource_id), (3001, 3035))
            self.assertEqual((palace.right_resource_id, palace.left_resource_id), (4001, 4035))
            with self.assertRaises(CompositeProjectError):
                workspace.pair(751)

    def test_sparse_companion_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(temp)
            workspace.orient.path.write_bytes(build_dat(orient_resources()[:-1]))
            with self.assertRaisesRegex(CompositeProjectError, "complete V22 companion"):
                V22OrientationWorkspace.open(
                    workspace.source.path,
                    workspace.orient.path,
                    require_standard_source=False,
                )

    def test_existing_custom_kid_is_accepted_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(temp)
            reopened = V22OrientationWorkspace.open(
                workspace.source.path, workspace.orient.path
            )
            self.assertEqual(len(reopened.pairs), 219)

    def test_nonstandard_non_kid_source_is_rejected_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(temp, "GUARD")
            with self.assertRaisesRegex(CompositeProjectError, "not the standard Prince 1.3"):
                V22OrientationWorkspace.open(workspace.source.path, workspace.orient.path)

    def test_right_runtime_and_display_edit_apply_group_reversal(self) -> None:
        self.assertEqual(
            reverse_mode6_cga_pixel_rows(bytes((0, 1, 1, 0)), 4, 1),
            bytearray((1, 0, 0, 1)),
        )
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(temp)
            pair = workspace.pairs[0]
            edit = workspace.edit(pair, "right")
            before = bytes(edit.bits)
            stored_x = workspace.display_to_stored_x(edit, "right", 0)
            self.assertEqual(stored_x, 2)
            workspace.set_display_bit(pair, "right", 0, 0, 0 if before[stored_x] else 1)
            self.assertNotEqual(bytes(edit.bits), before)

    def test_export_is_complete_verified_and_save_as_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = self.make_workspace(temp)
            pair = workspace.pairs[0]
            edit = workspace.edit(pair, "left")
            editable_x = next(
                x for x in range(edit.bit_width)
                if not edit.bit_is_mask_locked(x)
            )
            workspace.set_display_bit(
                pair, "left", editable_x, 0, 0 if edit.bits[editable_x] else 1
            )
            with self.assertRaisesRegex(CompositeProjectError, "Save-As"):
                workspace.export(workspace.orient.path)
            output = Path(temp) / "ORIENT-EDITED.DAT"
            target, changed, digest = workspace.export(output)
            self.assertEqual(target, output)
            self.assertEqual(changed, 1)
            self.assertEqual(len(digest), 64)
            reopened = DatArchive.open(output)
            self.assertEqual(tuple(r.resource_id for r in reopened.resources), EXPECTED_ORIENT_IDS)
            analysis = reopened.analysis_by_id(pair.left_resource_id)
            assert analysis is not None and analysis.image is not None
            palette = hardware_palette_for_resource(reopened, analysis.resource)
            self.assertEqual(initial_mode6_bits(analysis.image, palette), edit.bits)


if __name__ == "__main__":
    unittest.main()
