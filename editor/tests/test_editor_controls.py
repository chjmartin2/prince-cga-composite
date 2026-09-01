from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from composite_project import (
    CompositeEdit,
    CompositeProject,
    render_edited_composite,
    render_edited_mode6,
)
from composite_converter import (
    CONVERSION_EXHAUSTIVE,
    CONVERSION_SIMPLE_PALETTE,
    CONVERSION_SIMULATED_NTSC,
    DITHER_FLOYD_STEINBERG,
    PHASE_ALL,
    ConversionResult,
    ConversionSettings,
    render_all_phase_grid,
)
from composite_signal import render_composite_artifacts
from editor_windows import (
    ARTIFACT_GIF_PALETTE,
    COMPOSITE_EDITOR_ZOOM_VALUES,
    COMPARISON_MODE_LABELS,
    COMPARISON_NTSC_LABEL,
    CONVERTER_PREVIEW_ZOOM_VALUES,
    DEFAULT_TRANSPARENCY_DISPLAY_COLOR,
    EDITABLE_GIF_MODES,
    EDITOR_PREVIEW_MODES,
    MODE6_ALPHA_GIF_PALETTE,
    MODE6_GIF_PALETTE,
    MODE6_TRANSPARENT_INDEX,
    PREVIEW_VIEW_VALUES,
    TRANSPARENCY_BRUSH,
    BulkGifAction,
    CompositeEditorWindow,
    CompositeConverterDialog,
    ConverterSource,
    RasterPane,
    ViewportRasterPane,
    bulk_mode6_gif_name,
    composite_cell_mode6_columns,
    composite_cell_source_columns,
    composite_indices_to_bits,
    editable_image_analyses,
    mode6_gif_import,
    mode6_gif_pixels,
    paint_mode6_dat_pixel,
    parse_bulk_mode6_gif_name,
    prepare_bulk_mode6_exports,
    prepare_bulk_mode6_imports,
    resource_choice_label,
    render_comparison_mode,
    render_mode6_editor_raster,
    sidecar_resource_ids_lost_by_replacement,
    viewport_source_bounds,
)
from indexed_gif import IndexedGif, IndexedGifError, write_indexed_gif
from prince_dat import (
    COMPOSITE_PROFILE_NEW,
    COMPOSITE_PROFILE_OLD,
    DOSBOXX_CGA_COMPOSITE_COLORS,
    DOSBOXX_CGA_COMPOSITE_NEW_COLORS,
    DatArchive,
    DatResource,
    DecodedImage,
    RenderedRaster,
    ResourceAnalysis,
    render_display_mode,
)


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value) -> None:
        self.value = value


class FakePane:
    def __init__(self) -> None:
        self.title = ""
        self.raster = None
        self.show_options = {}

    def configure(self, *, text: str) -> None:
        self.title = text

    def clear(self, _message: str) -> None:
        self.raster = None

    def show(self, raster, **options) -> None:
        self.raster = raster
        self.show_options = options


class FakeGridCanvas:
    def __init__(self) -> None:
        self.deleted = []
        self.lines = []

    def delete(self, tag: str) -> None:
        self.deleted.append(tag)

    def create_line(self, *coordinates, **options) -> None:
        self.lines.append((coordinates, options))


class FakeBindingCanvas:
    def __init__(self) -> None:
        self.bindings = {}

    def bind(self, sequence: str, callback) -> None:
        self.bindings[sequence] = callback


class FakeControl:
    def __init__(self) -> None:
        self.state_calls: list[list[str]] = []
        self.configuration: dict[str, object] = {}

    def state(self, values: list[str]) -> None:
        self.state_calls.append(values)

    def configure(self, **values: object) -> None:
        self.configuration.update(values)


class FakeContext:
    def __init__(self, mapping, *, is_room_set: bool) -> None:
        self.mapping = mapping
        self.is_room_set = is_room_set

    def analysis_for_display_mode(self, mode: str, _resource_id: int):
        return self.mapping.get(mode)

    def source_description(self, mode: str) -> str:
        resolved = self.mapping.get(mode)
        return resolved[0].path.name if resolved is not None else "unavailable"


def fake_archive_and_analysis(name: str, pixels: bytes):
    archive = SimpleNamespace(path=Path(name), embedded_palettes=[])
    resource = DatResource(0, 100, 6, 7, 0, 0, True, b"")
    image = DecodedImage(2, 1, 4, 0xB0, 0, b"", pixels)
    return archive, ResourceAnalysis(resource, "4-bit image", image=image)


def bulk_test_archive(name: str = "BULKTEST.DAT") -> DatArchive:
    resources = [
        DatResource(0, 100, 6, 7, 0, 0, True, b""),
        DatResource(1, 200, 6, 7, 0, 0, True, b""),
    ]
    analyses = [
        ResourceAnalysis(
            resources[0],
            "4-bit image",
            image=DecodedImage(2, 1, 4, 0xB0, 0, b"", bytes((1, 1))),
        ),
        ResourceAnalysis(
            resources[1],
            "4-bit image",
            image=DecodedImage(2, 1, 4, 0xB0, 0, b"", bytes((0, 1))),
        ),
    ]
    return DatArchive(Path(name), b"bulk fixture", 0, 0, resources, analyses, [])


class CompositeEditorControlTests(unittest.TestCase):
    def make_preview_editor(self, context, target_archive, target_analysis):
        editor = object.__new__(CompositeEditorWindow)
        editor.context = context
        editor.archive = target_archive
        editor.analysis = target_analysis
        editor.selected_resource_id = 100
        editor.grid_var = FakeVar(True)
        editor.preview_vars = {
            mode: FakeVar("edited") for mode in EDITOR_PREVIEW_MODES
        }
        editor.vga_pane = FakePane()
        editor.ega_pane = FakePane()
        editor.cga_pane = FakePane()
        return editor

    def test_zoom_choices_are_ordered_and_reach_twenty_times(self) -> None:
        levels = [int(value.rstrip("x")) for value in COMPOSITE_EDITOR_ZOOM_VALUES]
        self.assertEqual(levels, sorted(set(levels)))
        self.assertEqual(levels[-1], 20)

    def test_comparison_modes_offer_full_ntsc_composite(self) -> None:
        self.assertIn(COMPARISON_NTSC_LABEL, COMPARISON_MODE_LABELS)

    def test_comparison_ntsc_source_can_be_rendered_at_full_signal_width(self) -> None:
        _archive, analysis = fake_archive_and_analysis(
            "KID.DAT", bytes((0, 15))
        )
        image = analysis.image
        if image is None:
            self.fail("fixture did not decode as an image")
        raster, presentation_mode = render_comparison_mode(
            image, "ntsc-composite", None
        )

        self.assertEqual(raster.mode, "composite-artifact")
        self.assertEqual(raster.width, image.width * 2)
        self.assertEqual(raster.height, image.height)
        self.assertEqual(presentation_mode, "mode6")

    def test_converter_preview_uses_the_full_one_to_twenty_zoom_range(self) -> None:
        self.assertEqual(
            CONVERTER_PREVIEW_ZOOM_VALUES,
            COMPOSITE_EDITOR_ZOOM_VALUES,
        )
        self.assertEqual(CONVERTER_PREVIEW_ZOOM_VALUES[0], "1x")
        self.assertEqual(CONVERTER_PREVIEW_ZOOM_VALUES[-1], "20x")

    def test_converter_rejects_single_phases_outside_audited_choices(self) -> None:
        dialog = object.__new__(CompositeConverterDialog)
        dialog.selectable_phases = (0, 2)
        dialog.phase_var = FakeVar("1")
        with self.assertRaisesRegex(ValueError, "permits only"):
            dialog._phase_selection()

        dialog.phase_var.set("2")
        self.assertEqual(dialog._phase_selection(), 2)
        dialog.phase_var.set(PHASE_ALL)
        self.assertEqual(dialog._phase_selection(), PHASE_ALL)

    def test_simple_palette_keeps_only_phase_and_hard_mask_controls(self) -> None:
        dialog = object.__new__(CompositeConverterDialog)
        dialog.conversion_mode_var = FakeVar(CONVERSION_SIMPLE_PALETTE)
        dialog.dither_var = FakeVar(DITHER_FLOYD_STEINBERG)
        dialog.dither_method_buttons = [FakeControl() for _ in range(3)]
        dialog.dither_amount_scale = FakeControl()
        dialog.serpentine_check = FakeControl()
        dialog.bayer_combo = FakeControl()
        dialog.input_adjustment_scales = tuple(FakeControl() for _ in range(4))
        dialog.color_emphasis_scale = FakeControl()
        dialog.detail_scale = FakeControl()
        dialog.quality_combo = FakeControl()
        dialog.phase_spinbox = FakeControl()
        dialog.preserve_zero_check = FakeControl()

        dialog._update_conversion_control_states()

        self.assertTrue(
            all(button.state_calls[-1] == ["disabled"] for button in dialog.dither_method_buttons)
        )
        self.assertEqual(dialog.dither_amount_scale.configuration["state"], "disabled")
        self.assertEqual(dialog.serpentine_check.state_calls[-1], ["disabled"])
        self.assertEqual(dialog.bayer_combo.configuration["state"], "disabled")
        self.assertTrue(
            all(
                scale.configuration["state"] == "disabled"
                for scale in dialog.input_adjustment_scales
            )
        )
        self.assertEqual(dialog.color_emphasis_scale.configuration["state"], "disabled")
        self.assertEqual(dialog.detail_scale.configuration["state"], "disabled")
        self.assertEqual(dialog.quality_combo.configuration["state"], "disabled")
        self.assertEqual(dialog.phase_spinbox.configuration["state"], "normal")
        self.assertEqual(
            dialog.phase_spinbox.configuration["values"],
            ("0", "1", "2", "3", PHASE_ALL),
        )
        # This check box is a hard bit mask, not a distance or color bias.
        self.assertEqual(dialog.preserve_zero_check.state_calls[-1], ["!disabled"])

        dialog.conversion_mode_var.set(CONVERSION_SIMULATED_NTSC)
        dialog._update_conversion_control_states()
        self.assertTrue(
            all(button.state_calls[-1] == ["!disabled"] for button in dialog.dither_method_buttons)
        )
        self.assertEqual(dialog.dither_amount_scale.configuration["state"], "normal")
        self.assertEqual(dialog.serpentine_check.state_calls[-1], ["!disabled"])
        self.assertEqual(dialog.quality_combo.configuration["state"], "readonly")
        self.assertEqual(dialog.phase_spinbox.configuration["state"], "normal")
        self.assertEqual(
            dialog.phase_spinbox.configuration["values"],
            ("0", "1", "2", "3", PHASE_ALL),
        )

        dialog.conversion_mode_var.set(CONVERSION_EXHAUSTIVE)
        dialog._update_conversion_control_states()
        self.assertTrue(
            all(button.state_calls[-1] == ["!disabled"] for button in dialog.dither_method_buttons)
        )
        self.assertEqual(dialog.dither_amount_scale.configuration["state"], "normal")
        self.assertEqual(dialog.serpentine_check.state_calls[-1], ["!disabled"])
        self.assertTrue(
            all(
                scale.configuration["state"] == "normal"
                for scale in dialog.input_adjustment_scales
            )
        )
        self.assertEqual(dialog.color_emphasis_scale.configuration["state"], "disabled")
        self.assertEqual(dialog.detail_scale.configuration["state"], "disabled")
        self.assertEqual(dialog.quality_combo.configuration["state"], "disabled")
        # Every model exposes the same reachable-phase universal objective.
        self.assertEqual(dialog.phase_spinbox.configuration["state"], "normal")
        self.assertEqual(
            dialog.phase_spinbox.configuration["values"],
            ("0", "1", "2", "3", PHASE_ALL),
        )

    def test_all_selection_captures_only_enabled_runtime_phases(self) -> None:
        dialog = object.__new__(CompositeConverterDialog)
        dialog.enabled_phases = (0, 2)
        dialog.phase_var = FakeVar(PHASE_ALL)
        dialog.dither_var = FakeVar("none")
        dialog.dither_amount_var = FakeVar(0)
        dialog.serpentine_var = FakeVar(True)
        dialog.bayer_var = FakeVar("4x4")
        dialog.brightness_var = FakeVar(0)
        dialog.contrast_var = FakeVar(0)
        dialog.saturation_var = FakeVar(100)
        dialog.gamma_var = FakeVar(100)
        dialog.color_emphasis_var = FakeVar(65)
        dialog.detail_var = FakeVar(55)
        dialog.quality_var = FakeVar("fast")
        dialog.preserve_zero_var = FakeVar(True)

        settings = dialog._settings()

        self.assertEqual(settings.phase_offset, PHASE_ALL)
        self.assertEqual(settings.all_phase_offsets, (0, 2))

    def test_twenty_times_viewport_only_requests_visible_source_pixels(self) -> None:
        bounds = viewport_source_bounds(
            640,
            200,
            20,
            6010,
            1510,
            6810,
            2210,
        )

        self.assertEqual(bounds, (299, 74, 341, 111))
        left, top, right, bottom = bounds
        self.assertEqual((right - left) * 20, 840)
        self.assertEqual((bottom - top) * 20, 740)
        self.assertLess((right - left) * (bottom - top), 640 * 200)

    def test_viewport_source_bounds_clamp_to_the_full_raster(self) -> None:
        self.assertEqual(
            viewport_source_bounds(640, 200, 1, -100, -100, 1000, 500),
            (0, 0, 640, 200),
        )
        with self.assertRaises(ValueError):
            viewport_source_bounds(640, 200, 0, 0, 0, 800, 600)

    def test_viewport_renderer_draws_grid_at_its_full_logical_scale(self) -> None:
        pane = object.__new__(ViewportRasterPane)
        pane.canvas = FakeGridCanvas()
        pane.raster = RenderedRaster(2, 2, bytes(12), 3, "artifact")
        pane.origin = (10, 10)
        pane.scale = 20
        pane.x_zoom = 1
        pane.x_subsample = 1
        pane.cell_grid = True

        pane._draw_grid()

        self.assertEqual(pane.canvas.deleted, ["grid"])
        self.assertEqual(len(pane.canvas.lines), 6)
        self.assertEqual(pane.canvas.lines[0][0], (10, 10, 10, 50))
        self.assertEqual(pane.canvas.lines[-1][0], (10, 50, 50, 50))

    def test_original_edited_selectors_cover_all_six_editor_panes(self) -> None:
        self.assertEqual(
            EDITOR_PREVIEW_MODES,
            ("vga", "ega", "cga", "mode6", "composite", "artifact"),
        )
        self.assertEqual(PREVIEW_VIEW_VALUES, ("original", "edited"))

    def test_only_the_two_native_bit_views_accept_gif_imports(self) -> None:
        self.assertEqual(EDITABLE_GIF_MODES, ("mode6", "composite"))
        self.assertEqual(MODE6_GIF_PALETTE, ((0, 0, 0), (255, 255, 255)))
        self.assertEqual(len(ARTIFACT_GIF_PALETTE), 256)

    def test_bulk_mode6_names_are_numeric_and_phase_aware(self) -> None:
        edit = CompositeEdit(0, 751, 2, 1, 4, 4, bytearray(4))
        self.assertEqual(bulk_mode6_gif_name(edit, 0), "751.gif")
        edit.set_enabled_phases((0, 2), create_missing=True)
        self.assertEqual(bulk_mode6_gif_name(edit, 0), "751_P0.gif")
        self.assertEqual(bulk_mode6_gif_name(edit, 2), "751_P2.gif")
        self.assertEqual(parse_bulk_mode6_gif_name("751_p2.GIF"), (751, 2))
        with self.assertRaisesRegex(IndexedGifError, "not a bulk Mode-6 name"):
            parse_bulk_mode6_gif_name("KID_751.gif")

    def test_bulk_export_covers_all_editable_resources_without_mutating_project(self) -> None:
        archive = bulk_test_archive()
        project = CompositeProject.for_archive(archive)
        first = archive.analyses[0]
        if first.image is None:
            self.fail("bulk fixture did not decode as an image")
        edit = project.edit_for_image(archive, first.resource.index, first.image)
        edit.set_enabled_phases((0, 2), create_missing=True)
        edit.phase_policy = "manual"

        exports = prepare_bulk_mode6_exports(archive, project, archive.analyses)

        self.assertEqual(
            [name for name, _image in exports],
            ["100_P0.gif", "100_P2.gif", "200.gif"],
        )
        self.assertEqual(set(project.edits), {0})
        self.assertTrue(all(image.palette == MODE6_ALPHA_GIF_PALETTE for _name, image in exports))
        self.assertTrue(all(image.transparent_index == 2 for _name, image in exports))

    def test_bulk_import_returns_detached_validated_resource_edits(self) -> None:
        archive = bulk_test_archive()
        project = CompositeProject.for_archive(archive)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "200.gif"
            write_indexed_gif(
                path,
                4,
                1,
                MODE6_ALPHA_GIF_PALETTE,
                bytes((1, 1, 1, 1)),
                transparent_index=MODE6_TRANSPARENT_INDEX,
            )

            replacements, count = prepare_bulk_mode6_imports(
                archive,
                project,
                archive.analyses,
                (path,),
            )

        self.assertEqual(count, 1)
        self.assertEqual(project.edits, {})
        self.assertEqual(replacements[1].bits, bytearray((1, 1, 1, 1)))
        self.assertEqual(replacements[1].source_zero_mask, bytearray((0, 0)))
        self.assertTrue(replacements[1].mask_locked)
        self.assertTrue(replacements[1].mask_authored)

    def test_bulk_import_rejects_one_bad_file_without_mutating_project(self) -> None:
        archive = bulk_test_archive()
        project = CompositeProject.for_archive(archive)
        with tempfile.TemporaryDirectory() as temp:
            valid = Path(temp) / "200.gif"
            unknown = Path(temp) / "999.gif"
            for path in (valid, unknown):
                write_indexed_gif(
                    path,
                    4,
                    1,
                    MODE6_ALPHA_GIF_PALETTE,
                    bytes((1, 1, 1, 1)),
                    transparent_index=MODE6_TRANSPARENT_INDEX,
                )
            with self.assertRaisesRegex(IndexedGifError, "not an editable"):
                prepare_bulk_mode6_imports(
                    archive,
                    project,
                    archive.analyses,
                    (valid, unknown),
                )

        self.assertEqual(project.edits, {})

    def test_bulk_import_requires_complete_multi_phase_family(self) -> None:
        archive = bulk_test_archive()
        project = CompositeProject.for_archive(archive)
        analysis = archive.analyses[0]
        if analysis.image is None:
            self.fail("bulk fixture did not decode as an image")
        edit = project.edit_for_image(archive, 0, analysis.image)
        edit.set_enabled_phases((0, 2), create_missing=True)
        edit.phase_policy = "manual"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "100_P0.gif"
            image = prepare_bulk_mode6_exports(archive, project, archive.analyses)[0][1]
            write_indexed_gif(
                path,
                image.width,
                image.height,
                image.palette,
                image.pixels,
                transparent_index=image.transparent_index,
            )
            with self.assertRaisesRegex(IndexedGifError, r"complete P0\+P2 set"):
                prepare_bulk_mode6_imports(
                    archive,
                    project,
                    archive.analyses,
                    (path,),
                )

    def test_bulk_import_is_one_undoable_project_action(self) -> None:
        archive = bulk_test_archive()
        project = CompositeProject.for_archive(archive)
        analysis = archive.analyses[0]
        if analysis.image is None:
            self.fail("bulk fixture did not decode as an image")
        before = project.edit_for_image(archive, 0, analysis.image)
        after = CompositeEdit(
            0,
            100,
            2,
            1,
            4,
            4,
            bytearray((1, 1, 1, 1)),
        )
        added = CompositeEdit(1, 200, 2, 1, 4, 4, bytearray((1, 1, 1, 1)))
        action = BulkGifAction(
            edits_before={0: before, 1: None},
            edits_after={0: after, 1: added},
            file_count=2,
        )
        project.edits = {0: after, 1: added}
        editor = object.__new__(CompositeEditorWindow)
        editor.project = project
        editor.undo_stack = [action]
        editor.redo_stack = []
        editor.status_var = FakeVar("")
        editor._refresh_after_bulk_gif_action = lambda: None

        editor.undo()
        self.assertEqual(project.edits[0].bits, before.bits)
        self.assertNotIn(1, project.edits)
        editor.redo()
        self.assertEqual(project.edits[0].bits, after.bits)
        self.assertEqual(project.edits[1].bits, added.bits)

    def test_composite_gif_indices_expand_to_exact_mode6_patterns(self) -> None:
        palette = tuple((index, index, index) for index in range(16))
        image = IndexedGif(2, 1, palette, bytes((5, 10)))

        bits = composite_indices_to_bits(image, bit_width=8)

        self.assertEqual(bits, bytes((0, 1, 0, 1, 1, 0, 1, 0)))

    def test_composite_gif_rejects_nonzero_partial_cell_padding(self) -> None:
        palette = tuple((index, index, index) for index in range(16))
        image = IndexedGif(2, 1, palette, bytes((15, 1)))

        with self.assertRaisesRegex(IndexedGifError, "padding bits"):
            composite_indices_to_bits(image, bit_width=6)

    def test_composite_export_preserves_indices_with_duplicate_rgb_swatches(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        edit = CompositeEdit(
            0,
            100,
            4,
            1,
            4,
            8,
            bytearray((0, 1, 0, 1, 1, 0, 1, 0)),
        )
        colors = [(index, index, index) for index in range(16)]
        colors[5] = colors[10] = (119, 115, 122)
        editor = object.__new__(CompositeEditorWindow)
        editor.archive = archive
        editor.analysis = analysis
        editor.current_edit = edit
        editor.project = SimpleNamespace(colors=colors)
        editor.preview_vars = {
            mode: FakeVar("edited") for mode in EDITOR_PREVIEW_MODES
        }
        editor.composite_pane = FakePane()
        editor.composite_pane.raster = render_edited_composite(edit, colors)

        exported = editor._pane_gif_image("composite")

        self.assertEqual(exported.pixels, bytes((5, 10)))
        self.assertEqual(exported.palette[5], exported.palette[10])

    def test_phase_gif_helper_exports_requested_variant_not_active_variant(self) -> None:
        edit = CompositeEdit(
            0,
            100,
            2,
            1,
            4,
            4,
            bytearray((0, 0, 0, 0)),
        )
        edit.set_enabled_phases((0, 2))
        edit.set_variant_bits(2, (1, 0, 1, 0), activate=False)
        editor = object.__new__(CompositeEditorWindow)
        editor.current_edit = edit
        editor.project = SimpleNamespace(
            colors=list(DOSBOXX_CGA_COMPOSITE_COLORS),
        )

        mode6 = editor._phase_variant_gif_image("mode6", 2)
        composite = editor._phase_variant_gif_image("composite", 2)

        self.assertEqual(edit.signal_phase, 0)
        self.assertEqual(mode6.pixels, bytes((1, 0, 1, 0)))
        self.assertEqual(mode6.palette, MODE6_ALPHA_GIF_PALETTE)
        self.assertEqual(mode6.transparent_index, MODE6_TRANSPARENT_INDEX)
        self.assertEqual(composite.pixels, bytes((10,)))

    def test_mode6_transparency_gif_distinguishes_black_from_transparent(self) -> None:
        edit = CompositeEdit(
            0,
            54,
            2,
            1,
            4,
            4,
            bytearray((0, 0, 0, 1)),
            source_zero_mask=bytearray((1, 0)),
            mask_reference_bits=bytearray((0, 0, 0, 1)),
        )
        exported = mode6_gif_pixels(edit, edit.bits)
        self.assertEqual(exported, bytes((2, 2, 0, 1)))

        image = IndexedGif(
            4,
            1,
            MODE6_ALPHA_GIF_PALETTE,
            bytes((0, 0, 2, 2)),
            MODE6_TRANSPARENT_INDEX,
        )
        bits, mask = mode6_gif_import(image, edit)
        self.assertEqual(bits, bytes((0, 0, 0, 0)))
        self.assertEqual(mask, bytearray((0, 1)))

    def test_mode6_editor_uses_solid_selected_color_for_transparency(self) -> None:
        edit = CompositeEdit(
            0,
            54,
            2,
            1,
            4,
            4,
            bytearray((0, 0, 0, 0)),
            source_zero_mask=bytearray((1, 0)),
            mask_reference_bits=bytearray((0, 0, 0, 0)),
        )

        raster = render_mode6_editor_raster(
            edit,
            edit.bits,
            edit.source_zero_mask,
            (12, 34, 56),
        )

        self.assertEqual(raster.pixels[:6], bytes((12, 34, 56)) * 2)
        self.assertEqual(raster.pixels[6:], b"\x00" * 6)

    def test_transparent_brush_updates_shared_dat_index_zero_mask(self) -> None:
        edit = CompositeEdit(
            0,
            54,
            2,
            1,
            4,
            4,
            bytearray((1, 1, 0, 0)),
            phase_variants={
                0: bytearray((1, 1, 0, 0)),
                2: bytearray((0, 1, 0, 0)),
            },
            enabled_phases=(0, 2),
            source_zero_mask=bytearray((0, 0)),
            mask_reference_bits=bytearray((0, 0, 0, 0)),
        )

        changes, mask_changed, native_zero = paint_mode6_dat_pixel(
            edit,
            0,
            0,
            TRANSPARENCY_BRUSH,
            None,
        )

        self.assertEqual(changes, [(0, 1, 0), (1, 1, 0)])
        self.assertTrue(mask_changed)
        self.assertFalse(native_zero)
        self.assertEqual(edit.source_zero_mask, bytearray((1, 0)))
        self.assertEqual(edit.variant_bits(0)[:2], bytearray((0, 0)))
        self.assertEqual(edit.variant_bits(2)[:2], bytearray((0, 0)))
        self.assertTrue(edit.mask_locked)
        self.assertTrue(edit.mask_authored)

    def test_black_brush_turns_transparent_four_bit_pixel_opaque(self) -> None:
        edit = CompositeEdit(
            0,
            54,
            1,
            1,
            4,
            2,
            bytearray((0, 0)),
            source_zero_mask=bytearray((1,)),
            mask_reference_bits=bytearray((0, 0)),
            mask_locked=True,
            mask_authored=True,
        )

        changes, mask_changed, native_zero = paint_mode6_dat_pixel(
            edit,
            0,
            0,
            0,
            None,
        )

        self.assertEqual(changes, [])
        self.assertTrue(mask_changed)
        self.assertFalse(native_zero)
        self.assertEqual(edit.source_zero_mask, bytearray((0,)))

    def test_native_one_bit_black_is_the_transparent_dat_index(self) -> None:
        edit = CompositeEdit(
            0,
            268,
            1,
            1,
            1,
            1,
            bytearray((1,)),
            source_zero_mask=bytearray((0,)),
            mask_reference_bits=bytearray((0,)),
        )

        changes, mask_changed, native_zero = paint_mode6_dat_pixel(
            edit,
            0,
            0,
            0,
            None,
        )

        self.assertEqual(changes, [(0, 1, 0)])
        self.assertTrue(mask_changed)
        self.assertTrue(native_zero)
        self.assertEqual(edit.source_zero_mask, bytearray((1,)))

    def test_mode6_transparency_requires_complete_source_pixels(self) -> None:
        edit = CompositeEdit(
            0,
            54,
            1,
            1,
            4,
            2,
            bytearray((0, 0)),
        )
        image = IndexedGif(
            2,
            1,
            MODE6_ALPHA_GIF_PALETTE,
            bytes((MODE6_TRANSPARENT_INDEX, 0)),
            MODE6_TRANSPARENT_INDEX,
        )

        with self.assertRaisesRegex(IndexedGifError, "both samples"):
            mode6_gif_import(image, edit)

    def test_native_one_bit_mode6_gif_rejects_opaque_black(self) -> None:
        edit = CompositeEdit(0, 54, 1, 1, 1, 1, bytearray((1,)))
        image = IndexedGif(
            1,
            1,
            MODE6_ALPHA_GIF_PALETTE,
            b"\x00",
            MODE6_TRANSPARENT_INDEX,
        )

        with self.assertRaisesRegex(IndexedGifError, "cannot encode opaque black"):
            mode6_gif_import(image, edit)

    def test_transparency_brush_stroke_undo_restores_mask_and_all_phases(self) -> None:
        edit = CompositeEdit(
            0,
            54,
            2,
            1,
            4,
            4,
            bytearray((1, 1, 0, 0)),
            phase_variants={
                0: bytearray((1, 1, 0, 0)),
                2: bytearray((0, 1, 0, 0)),
            },
            enabled_phases=(0, 2),
            source_zero_mask=bytearray((0, 0)),
            mask_reference_bits=bytearray((0, 0, 0, 0)),
        )
        editor = object.__new__(CompositeEditorWindow)
        editor.current_edit = edit
        editor.analysis = None
        editor.project = SimpleNamespace(dirty=False, edits={0: edit})
        editor.context = SimpleNamespace(is_room_set=False)
        editor.preview_vars = {
            mode: FakeVar("edited") for mode in EDITOR_PREVIEW_MODES
        }
        editor.pencil_var = FakeVar(TRANSPARENCY_BRUSH)
        editor.zoom_var = FakeVar("2x")
        editor.status_var = FakeVar("")
        editor.undo_stack = []
        editor.redo_stack = []
        editor._hover_cell = None
        editor._hover_bit = None
        editor.mode6_pane = FakePane()
        editor.mode6_pane.scale = 2
        editor.mode6_pane.x_zoom = 1
        editor.mode6_pane.x_subsample = 1
        editor.mode6_pane.raster_coordinates = lambda _event: (0, 0)
        editor._schedule_edited_render = lambda: None

        editor._stroke_start(SimpleNamespace(), False, "mode6")
        editor._stroke_end(SimpleNamespace())

        self.assertEqual(edit.source_zero_mask, bytearray((1, 0)))
        self.assertEqual(edit.variant_bits(0)[:2], bytearray((0, 0)))
        self.assertEqual(edit.variant_bits(2)[:2], bytearray((0, 0)))
        self.assertEqual(len(editor.undo_stack), 1)

        CompositeEditorWindow._restore_edit_action(
            edit,
            editor.undo_stack[0],
            after=False,
        )
        self.assertEqual(edit.source_zero_mask, bytearray((0, 0)))
        self.assertEqual(edit.variant_bits(0)[:2], bytearray((1, 1)))
        self.assertEqual(edit.variant_bits(2)[:2], bytearray((0, 1)))

    def test_transparency_import_is_one_undoable_family_mask_edit(self) -> None:
        edit = CompositeEdit(
            0,
            54,
            2,
            1,
            4,
            4,
            bytearray((0, 0, 1, 1)),
            phase_variants={
                0: bytearray((0, 0, 1, 1)),
                2: bytearray((0, 0, 1, 1)),
            },
            enabled_phases=(0, 2),
            source_zero_mask=bytearray((1, 0)),
            mask_reference_bits=bytearray((0, 0, 1, 1)),
            mask_locked=True,
        )
        editor = object.__new__(CompositeEditorWindow)
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False)
        editor.undo_stack = []
        editor.redo_stack = []
        editor.status_var = FakeVar("")
        editor._hover_cell = None
        editor._hover_bit = None
        editor.render_all = lambda: None

        editor._commit_imported_bits(
            "mode6",
            bytes((0, 0, 0, 0)),
            "/tmp/title-mode6.gif",
            bytearray((0, 1)),
        )

        self.assertEqual(edit.source_zero_mask, bytearray((0, 1)))
        self.assertTrue(edit.mask_authored)
        self.assertTrue(edit.mask_locked)
        self.assertEqual(edit.variant_bits(2), bytearray((0, 0, 0, 0)))
        action = editor.undo_stack[0]
        CompositeEditorWindow._restore_edit_action(edit, action, after=False)
        self.assertEqual(edit.source_zero_mask, bytearray((1, 0)))
        self.assertFalse(edit.mask_authored)
        self.assertEqual(edit.variant_bits(2), bytearray((0, 0, 1, 1)))

    def test_matching_transparency_import_still_authors_and_locks_mask(self) -> None:
        edit = CompositeEdit(
            0,
            54,
            2,
            1,
            4,
            4,
            bytearray((0, 0, 1, 1)),
            source_zero_mask=bytearray((1, 0)),
            mask_reference_bits=bytearray((0, 0, 1, 1)),
        )
        editor = object.__new__(CompositeEditorWindow)
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False)
        editor.undo_stack = []
        editor.redo_stack = []
        editor.status_var = FakeVar("")
        editor._hover_cell = None
        editor._hover_bit = None
        editor.render_all = lambda: None

        editor._commit_imported_bits(
            "mode6",
            bytes(edit.bits),
            "/tmp/title-mode6.gif",
            bytearray(edit.source_zero_mask),
        )

        self.assertTrue(edit.mask_authored)
        self.assertTrue(edit.mask_locked)
        self.assertEqual(len(editor.undo_stack), 1)
        CompositeEditorWindow._restore_edit_action(
            edit,
            editor.undo_stack[0],
            after=False,
        )
        self.assertFalse(edit.mask_authored)
        self.assertFalse(edit.mask_locked)

    def test_gif_import_commit_is_one_undoable_action(self) -> None:
        edit = CompositeEdit(0, 100, 4, 1, 1, 4, bytearray((0, 0, 0, 0)))
        editor = object.__new__(CompositeEditorWindow)
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False)
        editor.undo_stack = []
        editor.redo_stack = [object()]
        editor.status_var = FakeVar("")
        editor._hover_cell = (0, 0)
        editor._hover_bit = (0, 0)
        renders: list[bool] = []
        editor.render_all = lambda: renders.append(True)

        editor._commit_imported_bits(
            "mode6",
            bytes((1, 0, 1, 1)),
            "/tmp/test-mode6.gif",
        )

        self.assertEqual(edit.bits, bytearray((1, 0, 1, 1)))
        self.assertEqual(len(editor.undo_stack), 1)
        self.assertEqual(editor.undo_stack[0].changes, {0: (0, 1), 2: (0, 1), 3: (0, 1)})
        self.assertEqual(editor.redo_stack, [])
        self.assertTrue(editor.project.dirty)
        self.assertEqual(renders, [True])
        self.assertIn("one undo action", editor.status_var.get())

    def test_mode6_import_dialog_round_trips_an_exact_exported_gif(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        edit = CompositeEdit(0, 100, 2, 1, 4, 4, bytearray((0, 0, 0, 0)))
        editor = object.__new__(CompositeEditorWindow)
        editor.archive = archive
        editor.analysis = analysis
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False, colors=[(0, 0, 0)] * 16)
        editor.undo_stack = []
        editor.redo_stack = []
        editor.status_var = FakeVar("")
        editor._hover_cell = None
        editor._hover_bit = None
        editor.preview_vars = {
            mode: FakeVar("edited") for mode in EDITOR_PREVIEW_MODES
        }
        renders: list[bool] = []
        editor.render_all = lambda: renders.append(True)

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mode6.gif"
            write_indexed_gif(
                path,
                4,
                1,
                MODE6_GIF_PALETTE,
                bytes((1, 0, 1, 0)),
            )
            with patch(
                "editor_windows.filedialog.askopenfilename",
                return_value=str(path),
            ), patch("editor_windows.messagebox.showerror") as show_error:
                editor.import_pane_gif("mode6")

        show_error.assert_not_called()
        self.assertEqual(edit.bits, bytearray((1, 0, 1, 0)))
        self.assertEqual(len(editor.undo_stack), 1)
        self.assertEqual(renders, [True])

    def test_editor_resource_navigator_lists_every_editable_image_in_dat_order(self) -> None:
        resources = [
            DatResource(index, 100 + index, 6, 7, 0, 0, True, b"")
            for index in range(4)
        ]
        analyses = [
            ResourceAnalysis(resources[0], "Palette"),
            ResourceAnalysis(
                resources[1],
                "1-bit image",
                image=DecodedImage(8, 2, 1, 0x80, 0, b"", bytes(16)),
            ),
            ResourceAnalysis(
                resources[2],
                "4-bit image",
                image=DecodedImage(3, 2, 4, 0xB0, 0, b"", bytes(6)),
            ),
            ResourceAnalysis(
                resources[3],
                "8-bit image",
                image=DecodedImage(3, 2, 8, 0xF0, 0, b"", bytes(6)),
            ),
        ]
        editable = editable_image_analyses(SimpleNamespace(analyses=analyses))

        self.assertEqual([item.resource.resource_id for item in editable], [101, 102])
        self.assertEqual(
            resource_choice_label(editable[1], 1, 2),
            "2 of 2  |  Resource 102 (index 2)  |  3×2  |  4-bit",
        )

    def test_sidecar_replacement_detects_image_records_that_would_be_lost(self) -> None:
        existing = CompositeProject("TITLE.DAT", 100, "same")
        replacement = CompositeProject("TITLE.DAT", 100, "same")
        existing.edits[1] = CompositeEdit(1, 41, 2, 1, 4, 4, bytearray(4))
        existing.edits[2] = CompositeEdit(2, 42, 2, 1, 4, 4, bytearray(4))
        replacement.edits[2] = existing.edits[2]

        self.assertEqual(
            sidecar_resource_ids_lost_by_replacement(existing, replacement),
            (41,),
        )

        other_source = CompositeProject("TITLE.DAT", 101, "different")
        with self.assertRaises(ValueError):
            sidecar_resource_ids_lost_by_replacement(existing, other_source)

    def test_enabling_all_pane_grid_raises_zoom_and_renders(self) -> None:
        editor = object.__new__(CompositeEditorWindow)
        editor.grid_var = FakeVar(True)
        editor.zoom_var = FakeVar("1x")
        editor.status_var = FakeVar("")
        renders: list[bool] = []
        editor.render_all = lambda: renders.append(True)

        editor._grid_changed()

        self.assertEqual(editor.zoom_var.get(), "4x")
        self.assertEqual(renders, [True])
        self.assertIn("grid enabled", editor.status_var.get().lower())

    def test_grid_keeps_manual_zoom_at_four_times_or_higher(self) -> None:
        editor = object.__new__(CompositeEditorWindow)
        editor.grid_var = FakeVar(True)
        editor.zoom_var = FakeVar("2x")
        editor.status_var = FakeVar("")
        renders: list[bool] = []
        editor.render_all = lambda: renders.append(True)

        editor._zoom_changed()

        self.assertEqual(editor.zoom_var.get(), "4x")
        self.assertEqual(renders, [True])
        self.assertIn("at least 4", editor.status_var.get())

    def test_four_bit_composite_cell_marks_four_bits_and_two_source_pixels(self) -> None:
        edit = CompositeEdit(0, 100, 3, 1, 4, 6, bytearray(6))

        self.assertEqual(composite_cell_mode6_columns(edit, 0), (0, 1, 2, 3))
        self.assertEqual(composite_cell_source_columns(edit, 0), (0, 1))
        self.assertEqual(composite_cell_mode6_columns(edit, 1), (4, 5))
        self.assertEqual(composite_cell_source_columns(edit, 1), (2,))

    def test_one_bit_composite_cell_marks_four_source_pixels(self) -> None:
        edit = CompositeEdit(0, 100, 5, 1, 1, 5, bytearray(5))

        self.assertEqual(composite_cell_source_columns(edit, 0), (0, 1, 2, 3))
        self.assertEqual(composite_cell_source_columns(edit, 1), (4,))

    def test_half_width_mode6_grid_edges_match_scaled_raster_width(self) -> None:
        pane = object.__new__(RasterPane)
        pane.origin = (10, 10)
        pane.scale = 4
        pane.x_zoom = 1
        pane.x_subsample = 2

        self.assertEqual([pane._x_edge(column) for column in range(5)], [10, 12, 14, 16, 18])

        pane.scale = 3
        self.assertEqual([pane._x_edge(column) for column in range(5)], [10, 12, 13, 15, 16])

    def test_shared_archive_uses_live_predicted_image_in_vga_ega_and_cga(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        predicted = DecodedImage(2, 1, 4, 0xB0, 0, b"", bytes((3, 3)))
        context = FakeContext(
            {mode: (archive, analysis) for mode in ("vga", "ega", "cga")},
            is_room_set=False,
        )
        editor = self.make_preview_editor(context, archive, analysis)

        editor._render_adapter_previews(4, predicted)

        for mode, pane in (
            ("vga", editor.vga_pane),
            ("ega", editor.ega_pane),
            ("cga", editor.cga_pane),
        ):
            with self.subTest(mode=mode):
                self.assertEqual(pane.raster.pixels, render_display_mode(predicted, mode).pixels)
                self.assertIn("live patched preview", pane.title)
                self.assertTrue(pane.show_options["cell_grid"])

    def test_shared_adapter_panes_choose_original_or_edited_independently(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        predicted = DecodedImage(2, 1, 4, 0xB0, 0, b"", bytes((3, 3)))
        context = FakeContext(
            {mode: (archive, analysis) for mode in ("vga", "ega", "cga")},
            is_room_set=False,
        )
        editor = self.make_preview_editor(context, archive, analysis)
        editor.preview_vars["vga"].set("original")
        editor.preview_vars["ega"].set("edited")
        editor.preview_vars["cga"].set("original")

        editor._render_adapter_previews(4, predicted)

        self.assertEqual(
            editor.vga_pane.raster.pixels,
            render_display_mode(analysis.image, "vga").pixels,
        )
        self.assertEqual(
            editor.ega_pane.raster.pixels,
            render_display_mode(predicted, "ega").pixels,
        )
        self.assertEqual(
            editor.cga_pane.raster.pixels,
            render_display_mode(analysis.image, "cga").pixels,
        )
        self.assertIn("ORIGINAL", editor.vga_pane.title)
        self.assertIn("EDITED", editor.ega_pane.title)
        self.assertIn("ORIGINAL", editor.cga_pane.title)

    def test_mode6_and_composite_choose_original_or_edited_independently(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        edit = CompositeEdit(0, 100, 2, 1, 4, 4, bytearray((1, 1, 1, 1)))
        colors = list(DOSBOXX_CGA_COMPOSITE_COLORS)
        editor = object.__new__(CompositeEditorWindow)
        editor.archive = archive
        editor.analysis = analysis
        editor.current_edit = edit
        editor.project = SimpleNamespace(
            colors=colors,
            composite_profile=COMPOSITE_PROFILE_OLD,
        )
        editor.grid_var = FakeVar(True)
        editor.preview_vars = {
            mode: FakeVar("edited") for mode in EDITOR_PREVIEW_MODES
        }
        editor.mode6_pane = FakePane()
        editor.composite_pane = FakePane()
        editor.artifact_pane = FakePane()

        editor.preview_vars["mode6"].set("original")
        editor.preview_vars["composite"].set("edited")
        editor._render_target_transformed_previews(4)

        self.assertEqual(
            editor.mode6_pane.raster.pixels,
            render_mode6_editor_raster(
                edit,
                bytes((0, 0, 0, 1)),
                bytearray((1, 0)),
                DEFAULT_TRANSPARENCY_DISPLAY_COLOR,
            ).pixels,
        )
        self.assertEqual(
            editor.composite_pane.raster.pixels,
            render_edited_composite(edit, colors).pixels,
        )
        self.assertEqual(
            editor.artifact_pane.raster.pixels,
            render_composite_artifacts(
                edit.bits,
                edit.bit_width,
                edit.height,
                COMPOSITE_PROFILE_OLD,
            ).pixels,
        )
        self.assertEqual(editor.artifact_pane.show_options["scale"], 4)
        self.assertIn("4×", editor.artifact_pane.title)

        editor.preview_vars["mode6"].set("edited")
        editor.preview_vars["composite"].set("original")
        editor._render_target_transformed_previews(4)

        self.assertEqual(
            editor.mode6_pane.raster.pixels,
            render_edited_mode6(edit).pixels,
        )
        self.assertEqual(
            editor.composite_pane.raster.pixels,
            render_display_mode(
                analysis.image,
                "composite",
                composite_colors=colors,
            ).pixels,
        )
        editor._render_target_transformed_previews(20)
        self.assertEqual(editor.artifact_pane.show_options["scale"], 20)
        self.assertIn("20×", editor.artifact_pane.title)

    def test_direct_mode6_paint_updates_the_shared_composite_bitstream(self) -> None:
        edit = CompositeEdit(0, 100, 4, 1, 1, 4, bytearray((0, 0, 0, 0)))
        editor = object.__new__(CompositeEditorWindow)
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False, edits={0: edit})
        editor.context = SimpleNamespace(is_room_set=False)
        editor.preview_vars = {
            mode: FakeVar("edited") for mode in EDITOR_PREVIEW_MODES
        }
        editor.pencil_var = FakeVar(1)
        editor.zoom_var = FakeVar("2x")
        editor.status_var = FakeVar("")
        editor._stroke_seen = set()
        editor._stroke_changes = {}
        editor._stroke_plane = "mode6"
        editor.undo_stack = []
        editor.redo_stack = []
        editor._hover_cell = None
        editor._hover_bit = None
        editor.mode6_pane = FakePane()
        editor.mode6_pane.scale = 2
        editor.mode6_pane.x_zoom = 1
        editor.mode6_pane.x_subsample = 1
        editor.mode6_pane.raster_coordinates = lambda _event: (2, 0)
        scheduled: list[bool] = []
        editor._schedule_edited_render = lambda: scheduled.append(True)

        before = render_composite_artifacts(
            edit.bits,
            edit.bit_width,
            edit.height,
            COMPOSITE_PROFILE_OLD,
        )
        editor._paint_mode6(SimpleNamespace(), erase=False)
        after = render_composite_artifacts(
            edit.bits,
            edit.bit_width,
            edit.height,
            COMPOSITE_PROFILE_OLD,
        )

        self.assertEqual(edit.bits, bytearray((0, 0, 1, 0)))
        self.assertTrue(editor.project.dirty)
        self.assertEqual(editor._stroke_changes, {2: (0, 1)})
        self.assertEqual(scheduled, [True])
        self.assertNotEqual(before.pixels, after.pixels)

        editor._stroke_end(SimpleNamespace())
        editor._render_edited = lambda: None
        self.assertEqual(len(editor.undo_stack), 1)
        editor.undo()
        self.assertEqual(edit.bits, bytearray((0, 0, 0, 0)))
        editor.redo()
        self.assertEqual(edit.bits, bytearray((0, 0, 1, 0)))

    def test_mode6_right_button_binds_black_erase_stroke(self) -> None:
        editor = object.__new__(CompositeEditorWindow)
        calls = []
        editor._stroke_start = lambda event, erase, plane: calls.append(
            ("start", event, erase, plane)
        )
        editor._stroke_move = lambda event, erase, plane: calls.append(
            ("move", event, erase, plane)
        )
        editor._stroke_end = lambda event: calls.append(("end", event))
        canvas = FakeBindingCanvas()
        event = SimpleNamespace(x=12, y=34)

        editor._bind_mode6_canvas_controls(canvas)
        canvas.bindings["<ButtonPress-3>"](event)
        canvas.bindings["<B3-Motion>"](event)
        canvas.bindings["<ButtonRelease-3>"](event)

        self.assertEqual(
            calls,
            [
                ("start", event, True, "mode6"),
                ("move", event, True, "mode6"),
                ("end", event),
            ],
        )

    def test_mode6_right_erase_ignores_selected_white_pencil(self) -> None:
        edit = CompositeEdit(0, 100, 4, 1, 1, 4, bytearray((0, 0, 1, 0)))
        editor = object.__new__(CompositeEditorWindow)
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False, edits={0: edit})
        editor.preview_vars = {
            mode: FakeVar("edited") for mode in EDITOR_PREVIEW_MODES
        }
        editor.pencil_var = FakeVar(1)
        editor.zoom_var = FakeVar("2x")
        editor.status_var = FakeVar("")
        editor._stroke_seen = set()
        editor._stroke_changes = {}
        editor._hover_cell = None
        editor._hover_bit = None
        editor.mode6_pane = FakePane()
        editor.mode6_pane.scale = 2
        editor.mode6_pane.x_zoom = 1
        editor.mode6_pane.x_subsample = 1
        editor.mode6_pane.raster_coordinates = lambda _event: (2, 0)
        editor._schedule_edited_render = lambda: None

        editor._paint_mode6(SimpleNamespace(), erase=True)

        self.assertEqual(edit.bits, bytearray((0, 0, 0, 0)))
        self.assertEqual(editor._stroke_changes, {2: (1, 0)})

    def test_conversion_commits_bits_and_phase_as_one_undo_action(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        edit = CompositeEdit(0, 100, 2, 1, 4, 4, bytearray((0, 0, 0, 0)))
        editor = object.__new__(CompositeEditorWindow)
        editor.archive = archive
        editor.analysis = analysis
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False, edits={0: edit})
        editor.undo_stack = []
        editor.redo_stack = []
        editor.preview_vars = {
            mode: FakeVar("original") for mode in EDITOR_PREVIEW_MODES
        }
        editor.status_var = FakeVar("")
        rendered: list[bool] = []
        editor._render_edited = lambda: rendered.append(True)
        preview = render_composite_artifacts(
            (1, 0, 1, 0),
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            phase_offset=2,
        )
        result = ConversionResult(b"\x01\x00\x01\x00", preview, 4, 1, 12.5)
        settings = ConversionSettings(phase_offset=2)
        source = ConverterSource(
            "vga",
            "VGA test source",
            render_display_mode(analysis.image, "vga"),
            (True, False),
        )

        self.assertTrue(
            editor._apply_conversion(
                result,
                settings,
                source,
                CONVERSION_SIMULATED_NTSC,
            )
        )
        self.assertEqual(edit.bits, bytearray((1, 0, 1, 0)))
        self.assertEqual(edit.signal_phase, 2)
        self.assertEqual(len(editor.undo_stack), 1)
        self.assertTrue(editor.project.dirty)
        self.assertTrue(all(editor.preview_vars[mode].get() == "edited" for mode in ("mode6", "composite", "artifact")))

        editor.undo()
        self.assertEqual(edit.bits, bytearray((0, 0, 0, 0)))
        self.assertEqual(edit.signal_phase, 0)
        editor.redo()
        self.assertEqual(edit.bits, bytearray((1, 0, 1, 0)))
        self.assertEqual(edit.signal_phase, 2)

    def test_simple_palette_conversion_targets_selected_phase(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        edit = CompositeEdit(
            0,
            100,
            2,
            1,
            4,
            4,
            bytearray((0, 0, 0, 0)),
            signal_phase=3,
        )
        editor = object.__new__(CompositeEditorWindow)
        editor.archive = archive
        editor.analysis = analysis
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False, edits={0: edit})
        editor.undo_stack = []
        editor.redo_stack = []
        editor.preview_vars = {
            mode: FakeVar("original") for mode in EDITOR_PREVIEW_MODES
        }
        editor.status_var = FakeVar("")
        editor._render_edited = lambda: None
        preview = RenderedRaster(1, 1, bytes((0, 0, 0)), 3, "simple-palette")
        result = ConversionResult(b"\x01\x00\x01\x00", preview, 4, 1, 8.0)
        # Simply Palette now rotates its fixed lookup for the selected phase.
        settings = ConversionSettings(phase_offset=1)
        source = ConverterSource(
            "ega",
            "EGA test source",
            render_display_mode(analysis.image, "ega"),
            (True, False),
        )

        self.assertTrue(
            editor._apply_conversion(
                result,
                settings,
                source,
                CONVERSION_SIMPLE_PALETTE,
            )
        )
        self.assertEqual(edit.bits, bytearray((1, 0, 1, 0)))
        self.assertEqual(edit.signal_phase, 1)
        self.assertEqual(len(editor.undo_stack), 1)
        self.assertEqual(editor.undo_stack[0].phase_before, 3)
        self.assertEqual(editor.undo_stack[0].phase_after, 1)
        self.assertIn("independent P1 variant", editor.status_var.get())

    def test_exhaustive_all_conversion_stores_universal_in_active_variant(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        edit = CompositeEdit(
            0,
            100,
            2,
            1,
            4,
            4,
            bytearray((0, 0, 0, 0)),
            signal_phase=3,
        )
        editor = object.__new__(CompositeEditorWindow)
        editor.archive = archive
        editor.analysis = analysis
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False, edits={0: edit})
        editor.undo_stack = []
        editor.redo_stack = []
        editor.preview_vars = {
            mode: FakeVar("original") for mode in EDITOR_PREVIEW_MODES
        }
        editor.status_var = FakeVar("")
        editor._render_edited = lambda: None
        converted_bits = b"\x01\x00\x01\x00"
        preview = render_all_phase_grid(
            converted_bits,
            4,
            1,
            COMPOSITE_PROFILE_OLD,
            (3,),
        )
        result = ConversionResult(converted_bits, preview, 4, 1, 18.0)
        settings = ConversionSettings(
            phase_offset=PHASE_ALL,
            all_phase_offsets=(3,),
        )
        source = ConverterSource(
            "ega",
            "EGA test source",
            render_display_mode(analysis.image, "ega"),
            (True, False),
        )

        self.assertTrue(
            editor._apply_conversion(
                result,
                settings,
                source,
                CONVERSION_EXHAUSTIVE,
            )
        )
        self.assertEqual(edit.bits, bytearray((1, 0, 1, 0)))
        self.assertEqual(edit.signal_phase, 3)
        self.assertEqual(editor.undo_stack[0].phase_before, 3)
        self.assertEqual(editor.undo_stack[0].phase_after, 3)
        self.assertIn("universal P3 pattern stored in active P3", editor.status_var.get())

    def test_phase_set_conversion_is_one_atomic_undoable_action(self) -> None:
        archive, analysis = fake_archive_and_analysis("KID.DAT", bytes((0, 1)))
        edit = CompositeEdit(
            0,
            100,
            2,
            1,
            4,
            4,
            bytearray((0, 0, 0, 0)),
        )
        edit.set_enabled_phases((0, 2))
        edit.fallback_phase = 2
        editor = object.__new__(CompositeEditorWindow)
        editor.archive = archive
        editor.analysis = analysis
        editor.current_edit = edit
        editor.project = SimpleNamespace(dirty=False, edits={0: edit})
        editor.undo_stack = []
        editor.redo_stack = []
        editor.preview_vars = {
            mode: FakeVar("original") for mode in EDITOR_PREVIEW_MODES
        }
        editor.status_var = FakeVar("")
        editor._render_edited = lambda: None
        phase_bits = {0: b"\x01\x00\x01\x00", 2: b"\x00\x01\x00\x01"}
        results = {
            phase: ConversionResult(
                bits,
                render_composite_artifacts(
                    bits,
                    4,
                    1,
                    COMPOSITE_PROFILE_OLD,
                    phase_offset=phase,
                ),
                4,
                1,
                10.0 + phase,
            )
            for phase, bits in phase_bits.items()
        }
        source = ConverterSource(
            "ega",
            "EGA test source",
            render_display_mode(analysis.image, "ega"),
            (True, False),
        )

        self.assertTrue(
            editor._apply_phase_set_conversion(
                results,
                ConversionSettings(phase_offset=0),
                source,
                CONVERSION_EXHAUSTIVE,
            )
        )
        self.assertEqual(bytes(edit.variant_bits(0)), phase_bits[0])
        self.assertEqual(bytes(edit.variant_bits(2)), phase_bits[2])
        self.assertEqual(edit.signal_phase, 0)
        self.assertEqual(edit.fallback_phase, 2)
        self.assertEqual(len(editor.undo_stack), 1)
        self.assertIn("no targets or decoded colors were averaged", editor.status_var.get())

        editor.undo()
        self.assertEqual(edit.variant_bits(0), bytearray((0, 0, 0, 0)))
        self.assertEqual(edit.variant_bits(2), bytearray((0, 0, 0, 0)))
        self.assertEqual(edit.fallback_phase, 2)
        editor.redo()
        self.assertEqual(bytes(edit.variant_bits(0)), phase_bits[0])
        self.assertEqual(bytes(edit.variant_bits(2)), phase_bits[2])
        self.assertEqual(edit.fallback_phase, 2)

    def test_old_new_cga_switch_updates_swatches_without_touching_bits(self) -> None:
        project = CompositeProject("KID.DAT", 0, "test")
        edit = CompositeEdit(0, 100, 2, 1, 4, 4, bytearray((1, 0, 1, 0)))
        project.edits[0] = edit
        editor = object.__new__(CompositeEditorWindow)
        editor.project = project
        editor.cga_profile_var = FakeVar(COMPOSITE_PROFILE_NEW)
        editor.pattern_var = FakeVar(6)
        editor.status_var = FakeVar("")
        selected: list[int] = []
        rendered: list[bool] = []
        editor._select_pattern = lambda index: selected.append(index)
        editor._render_edited = lambda: rendered.append(True)
        before = bytearray(edit.bits)

        editor._composite_profile_changed()

        self.assertEqual(project.composite_profile, COMPOSITE_PROFILE_NEW)
        self.assertEqual(project.colors, list(DOSBOXX_CGA_COMPOSITE_NEW_COLORS))
        self.assertEqual(edit.bits, before)
        self.assertEqual(selected, [6])
        self.assertEqual(rendered, [True])
        self.assertIn("New CGA", editor.status_var.get())

    def test_linked_room_vga_ega_stay_independent_while_cga_updates_live(self) -> None:
        c_archive, c_analysis = fake_archive_and_analysis("CDUNGEON.DAT", bytes((0, 1)))
        e_archive, e_analysis = fake_archive_and_analysis("EDUNGEON.DAT", bytes((1, 2)))
        v_archive, v_analysis = fake_archive_and_analysis("VDUNGEON.DAT", bytes((2, 3)))
        predicted = DecodedImage(2, 1, 4, 0xB0, 0, b"", bytes((3, 3)))
        context = FakeContext(
            {
                "vga": (v_archive, v_analysis),
                "ega": (e_archive, e_analysis),
                "cga": (c_archive, c_analysis),
            },
            is_room_set=True,
        )
        editor = self.make_preview_editor(context, c_archive, c_analysis)

        editor._render_adapter_previews(4, predicted)

        self.assertEqual(
            editor.vga_pane.raster.pixels,
            render_display_mode(v_analysis.image, "vga").pixels,
        )
        self.assertEqual(
            editor.ega_pane.raster.pixels,
            render_display_mode(e_analysis.image, "ega").pixels,
        )
        self.assertEqual(
            editor.cga_pane.raster.pixels,
            render_display_mode(predicted, "cga").pixels,
        )
        self.assertIn("independent read-only reference", editor.vga_pane.title)
        self.assertIn("independent read-only reference", editor.ega_pane.title)
        self.assertIn("live patched preview", editor.cga_pane.title)


if __name__ == "__main__":
    unittest.main()
