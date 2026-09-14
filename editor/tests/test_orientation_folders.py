"""Real indexed-GIF folder round trips for independently painted directions."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from composite_project import CompositeProjectError
from indexed_gif import IndexedGifError, read_indexed_gif, write_indexed_gif
from editor_windows import CompositeEditorWindow
from mode6_interchange import MODE6_ALPHA_GIF_PALETTE
from orientation_workspace import DIRECTION_FOLDER_MANIFEST, TABLES, V22OrientationWorkspace
from prince_dat import DatArchive
from test_orientation_workspace import build_dat, image_resource, orient_resources


def workspace_at(folder, family="KID", special=None):
    source = sorted({(table.source_first + i, image_resource())
                     for table in TABLES if table.archive == family
                     for i in range(table.count)})
    source_path, orient_path = folder / f"{family}.DAT", folder / "ORIENT.DAT"
    source_path.write_bytes(build_dat(source))
    orient_path.write_bytes(build_dat([
        (rid, special.get(rid, raw) if special else raw) for rid, raw in orient_resources()]))
    return V22OrientationWorkspace.open(source_path, orient_path)


def export_at(workspace, folder, names=None):
    folder.mkdir()
    manifest, exports = workspace.prepare_direction_folder_exports()
    (folder / DIRECTION_FOLDER_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    for name, image in exports:
        if names is not None and name not in names:
            continue
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        write_indexed_gif(path, image.width, image.height, image.palette, image.pixels,
                          transparent_index=image.transparent_index)
    return manifest


def replace_pixels(path, pixels, *, palette=MODE6_ALPHA_GIF_PALETTE, width=None):
    image = read_indexed_gif(path)
    write_indexed_gif(path, image.width if width is None else width, image.height,
                      palette, bytes(pixels), transparent_index=2)


class OrientationFolderTests(unittest.TestCase):
    def test_family_mapping_uses_source_ids_and_separate_guard_contexts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root, "PV")
            manifest, exports = workspace.prepare_direction_folder_exports()
            by_name = {item["file"]: item for item in manifest["records"]}
            self.assertEqual(len(exports), 170)
            self.assertEqual(by_name["Right/801.gif"]["orient_resource_id"], 7001)
            self.assertEqual(by_name["Left/801.gif"]["orient_resource_id"], 7018)
            self.assertEqual(by_name["Left/851.gif"]["orient_resource_id"], 8039)
            self.assertEqual(by_name["Left/901.gif"]["orient_resource_id"], 9031)
            self.assertEqual(manifest["pixel_order"], "runtime-display")
            self.assertEqual(workspace.project.edits, {})
            self.assertFalse(workspace.project.dirty)
            workspace = workspace_at(root, "GUARD")
            manifest, exports = workspace.prepare_direction_folder_exports()
            by_name = {item["file"]: item for item in manifest["records"]}
            self.assertEqual(len(exports), 136)
            self.assertEqual(by_name["Right/Dungeon/751.gif"]["orient_resource_id"], 3001)
            self.assertEqual(by_name["Right/Palace/751.gif"]["orient_resource_id"], 4001)

    def test_runtime_direction_and_transparency_reverse_groups_not_bits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root, special={1001: image_resource(0x01), 2001: image_resource(0x01)})
            exported = dict(workspace.prepare_direction_folder_exports()[1])
            self.assertEqual(exported["Left/401.gif"].pixels, bytes((2, 2, 0, 1)))
            self.assertEqual(exported["Right/401.gif"].pixels, bytes((0, 1, 2, 2)))
            # A bitstream mirror would incorrectly change the visible 01 to 10.
            self.assertNotEqual(exported["Right/401.gif"].pixels, bytes((1, 0, 2, 2)))
            folder = root / "images"
            export_at(workspace, folder, {"Right/401.gif"})
            replace_pixels(folder / "Right/401.gif", (1, 1, 2, 2))
            replacements, count = workspace.prepare_direction_folder_imports(folder)
            self.assertEqual(count, 1)
            edit = next(iter(replacements.values()))
            self.assertEqual(edit.resource_id, 1001)
            self.assertEqual(edit.bits, bytearray((0, 0, 1, 1)))
            self.assertEqual(edit.source_zero_mask, bytearray((1, 0)))
            self.assertEqual(workspace.project.edits, {})

    def test_full_round_trip_is_no_op_and_does_not_recompress_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root, "PV")
            folder = root / "images"
            export_at(workspace, folder)
            replacements, count = workspace.prepare_direction_folder_imports(folder)
            self.assertEqual(count, 170)
            self.assertEqual(replacements, {})
            target = root / "out.dat"
            _, changed, _ = workspace.export(target)
            self.assertEqual(changed, 0)
            self.assertEqual(target.read_bytes(), workspace.orient.data)

    def test_partial_import_preserves_other_direction_missing_images_and_families(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root, "PV")
            # Simulate an existing edit elsewhere in the complete companion.
            unrelated = workspace.orient.analysis_by_id(3001)
            edit = workspace.project.edit_for_image(workspace.orient, unrelated.resource.index, unrelated.image)
            edit.bits[0] = 1
            workspace.project.dirty = True
            existing = copy.deepcopy(workspace.project)
            folder = root / "images"
            export_at(workspace, folder, {"Left/801.gif"})
            replace_pixels(folder / "Left/801.gif", (1, 1, 0, 1))
            replacements, count = workspace.prepare_direction_folder_imports(folder)
            self.assertEqual(count, 1)
            self.assertEqual([item.resource_id for item in replacements.values()], [7018])
            self.assertEqual(workspace.project.edits, existing.edits)
            self.assertEqual(workspace.project.dirty, existing.dirty)
            workspace.project.edits.update(replacements)
            target = root / "edited.dat"
            workspace.export(target)
            output = DatArchive.open(target)
            changed = {old.resource_id for old, new in zip(workspace.orient.resources, output.resources)
                       if old.data != new.data}
            self.assertEqual(changed, {3001, 7018})
            self.assertEqual(workspace.source.path.read_bytes(), workspace.source.data)

    def test_bad_last_file_rejects_whole_batch_without_touching_live_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root)
            pair = workspace.pair(401)
            workspace.edit(pair, "left")
            before = copy.deepcopy(workspace.project)
            folder = root / "images"
            export_at(workspace, folder, {"Left/401.gif", "Right/401.gif"})
            replace_pixels(folder / "Left/401.gif", (1, 1, 0, 1))
            replace_pixels(folder / "Right/401.gif", (1, 0), width=2)
            with self.assertRaisesRegex(IndexedGifError, "expected exactly"):
                workspace.prepare_direction_folder_imports(folder)
            self.assertEqual(workspace.project.edits, before.edits)
            self.assertEqual(workspace.project.dirty, before.dirty)

    def test_palette_reserved_index_and_partial_mask_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root)
            folder = root / "images"
            export_at(workspace, folder, {"Left/401.gif"})
            path = folder / "Left/401.gif"
            palette = list(MODE6_ALPHA_GIF_PALETTE)
            palette[0], palette[1] = palette[1], palette[0]
            replace_pixels(path, (0, 1, 0, 1), palette=palette)
            with self.assertRaisesRegex(IndexedGifError, "four-entry palette"):
                workspace.prepare_direction_folder_imports(folder)
            replace_pixels(path, (0, 3, 0, 1))
            with self.assertRaisesRegex(IndexedGifError, "reserved"):
                workspace.prepare_direction_folder_imports(folder)
            replace_pixels(path, (2, 1, 0, 1))
            with self.assertRaisesRegex(IndexedGifError, "part of source pixel"):
                workspace.prepare_direction_folder_imports(folder)
            self.assertEqual(workspace.project.edits, {})

    def test_imported_transparency_is_visible_in_both_runtime_previews_and_saved_dat(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root)
            pair = workspace.pair(401)
            folder = root / "images"
            export_at(workspace, folder, {"Left/401.gif", "Right/401.gif"})
            for direction in ("Left", "Right"):
                replace_pixels(folder / direction / "401.gif", (2, 2, 0, 1))
            replacements, count = workspace.prepare_direction_folder_imports(folder)
            self.assertEqual(count, 2)
            workspace.project.edits.update(replacements)
            for direction in ("left", "right"):
                raster = workspace.runtime_raster(pair, direction, transparent=True)
                self.assertEqual(raster.pixels[:6], bytes((232, 232, 232)) * 2)
                self.assertNotEqual(raster.pixels[6:12], bytes((232, 232, 232)) * 2)
            target = root / "new-orient.dat"
            workspace.export(target)
            reopened = V22OrientationWorkspace.open(workspace.source.path, target)
            for direction in ("left", "right"):
                self.assertEqual(reopened.runtime_raster(reopened.pair(401), direction, transparent=True).pixels,
                                 workspace.runtime_raster(pair, direction, transparent=True).pixels)
            self.assertEqual(workspace.source.path.read_bytes(), workspace.source.data)

    def test_wrong_mapping_or_unknown_image_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root)
            folder = root / "images"
            manifest = export_at(workspace, folder, {"Left/401.gif"})
            original = json.dumps(manifest)
            manifest["records"][0]["orient_resource_id"] = 1001
            (folder / DIRECTION_FOLDER_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(CompositeProjectError, "mapping"):
                workspace.prepare_direction_folder_imports(folder)
            (folder / DIRECTION_FOLDER_MANIFEST).write_text(original, encoding="utf-8")
            (folder / "Left/401.gif").rename(folder / "Left/999.gif")
            with self.assertRaisesRegex(CompositeProjectError, "Unmapped"):
                workspace.prepare_direction_folder_imports(folder)
            self.assertEqual(workspace.project.edits, {})

    def test_linked_import_callback_accepts_parent_and_undo_redo_restores_both_directions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = workspace_at(root)
            folder = root / "KID"
            export_at(workspace, folder, {"Left/401.gif", "Right/401.gif"})
            replace_pixels(folder / "Left/401.gif", (1, 1, 0, 1))
            replace_pixels(folder / "Right/401.gif", (0, 1, 1, 1))
            editor = object.__new__(CompositeEditorWindow)
            editor.orientation_workspace = workspace
            editor.project = workspace.project
            editor.undo_stack, editor.redo_stack = [], []
            editor._gif_initial_directory = lambda mode: root
            editor._refresh_after_bulk_gif_action = lambda: None
            messages = []
            editor.status_var = SimpleNamespace(set=messages.append)
            with patch("editor_windows.filedialog.askdirectory", return_value=str(root)):
                editor.import_bulk_mode6_gifs()
            self.assertEqual(len(editor.undo_stack), 1)
            changed = copy.deepcopy(editor.project.edits)
            self.assertEqual({edit.resource_id for edit in changed.values()}, {1001, 2001})
            editor.undo()
            self.assertEqual(editor.project.edits, {})
            editor.redo()
            self.assertEqual(editor.project.edits, changed)
            self.assertTrue(any("one undo action" in text for text in messages))


if __name__ == "__main__":
    unittest.main()
