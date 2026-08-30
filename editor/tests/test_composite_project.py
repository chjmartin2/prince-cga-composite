from __future__ import annotations

import base64
import json
from pathlib import Path
import struct
import tempfile
import unittest

from composite_project import (
    PHASES,
    PHASE_MANIFEST_VERSION,
    PHASE_PROFILE_PARITY_02,
    PROJECT_VERSION,
    CompositeProject,
    CompositeProjectError,
    encode_image_lzg,
    encode_lzg,
    format_hex_color,
    initial_mode6_bits,
    pack_bits,
    parse_hex_color,
    phase_manifest_dict,
    predicted_image_for_edit,
    rebuild_dat,
    render_edited_composite,
    replacement_contents,
    source_pixels_for_edit,
    write_patched_dat,
)
from engine_phase_usage import PHASE_POLICY_ENGINE, PHASE_POLICY_MANUAL
from prince_dat import (
    COMPOSITE_PROFILE_NEW,
    COMPOSITE_PROFILE_OLD,
    DEFAULT_COMPOSITE_PROFILE,
    DOSBOXX_CGA_COMPOSITE_NEW_COLORS,
    DatArchive,
    RGBI_COLORS,
    decode_prince_image,
    hardware_palette_for_resource,
    mode6_bit_at,
    render_display_mode,
    translated_index,
)


def image_resource(width: int, height: int, type_byte: int, payload: bytes) -> bytes:
    return struct.pack("<HHBB", height, width, 0, type_byte) + payload


def build_dat(resources: list[tuple[int, bytes]]) -> bytes:
    body = bytearray(6)
    records: list[tuple[int, int, int]] = []
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


def pack_cga(values: list[int]) -> bytes:
    assert len(values) == 64
    return bytes(
        (values[start] << 6)
        | (values[start + 1] << 4)
        | (values[start + 2] << 2)
        | values[start + 3]
        for start in range(0, 64, 4)
    )


def pack_ega(values: list[int]) -> bytes:
    assert len(values) == 64
    return bytes(
        (values[start] << 4) | values[start + 1]
        for start in range(0, 64, 2)
    )


def palette_resource(
    cga_groups: list[list[int]] | None = None,
    ega_groups: list[list[int]] | None = None,
) -> bytes:
    palette = bytearray(100)
    palette[0] = 1
    palette[1:4] = b"\x00\x00\x10"
    for index in range(16):
        # Six-bit values that remain distinct after expansion.
        palette[4 + index * 3 : 7 + index * 3] = bytes(
            (index * 4, 63 - index * 3, index * 2)
        )
    cga = cga_groups or [[index & 3 for index in range(16)] for _ in range(4)]
    ega = ega_groups or [[index for index in range(16)] for _ in range(4)]
    palette[52:68] = pack_cga([value for group in cga for value in group])
    palette[68:100] = pack_ega([value for group in ega for value in group])
    return bytes(palette)


class HardwareTranslationTests(unittest.TestCase):
    def test_palette_expands_four_distinct_cga_and_ega_phases(self) -> None:
        cga = [[phase] * 16 for phase in range(4)]
        ega = [list(range(16)), [5] * 16, [10] * 16, [15] * 16]
        graphic = image_resource(2, 2, 0xB0, b"\x77\x77")
        raw = build_dat([(1, palette_resource(cga, ega)), (2, graphic)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "KID.DAT"
            path.write_bytes(raw)
            archive = DatArchive.open(path)

        palette = archive.embedded_palettes[0]
        image = archive.analyses[1].image
        assert image is not None
        self.assertEqual(len(palette.cga_translation), 64)
        self.assertEqual(len(palette.ega_translation), 64)
        self.assertEqual(
            [translated_index(image, x, y, "cga", palette) for y in range(2) for x in range(2)],
            [0, 1, 2, 3],
        )
        self.assertEqual(
            [translated_index(image, x, y, "ega", palette) for y in range(2) for x in range(2)],
            [7, 5, 10, 15],
        )

    def test_mode6_bits_are_derived_after_cga_translation(self) -> None:
        cga = [[phase] * 16 for phase in range(4)]
        graphic = image_resource(2, 2, 0xB0, b"\x77\x77")
        raw = build_dat([(1, palette_resource(cga)), (2, graphic)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "KID.DAT"
            path.write_bytes(raw)
            archive = DatArchive.open(path)
        image = archive.analyses[1].image
        assert image is not None
        palette = archive.embedded_palettes[0]
        bits = [mode6_bit_at(image, x, y, palette)[0] for y in range(2) for x in range(4)]
        self.assertEqual(bits, [0, 0, 0, 1, 1, 0, 1, 1])

    def test_ega_renderer_uses_translated_rgbi_color(self) -> None:
        ega = [[index for index in range(16)], [5] * 16, [10] * 16, [15] * 16]
        raw = build_dat(
            [(1, palette_resource(ega_groups=ega)), (2, image_resource(2, 2, 0xB0, b"\x77\x77"))]
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "EDUNGEON.DAT"
            path.write_bytes(raw)
            archive = DatArchive.open(path)
        image = archive.analyses[1].image
        assert image is not None
        raster = render_display_mode(image, "ega", archive.embedded_palettes[0])
        expected = b"".join(bytes(RGBI_COLORS[index]) for index in (7, 5, 10, 15))
        self.assertEqual(raster.pixels, expected)


class CompositeColorValueTests(unittest.TestCase):
    def test_hex_color_round_trip_uses_canonical_uppercase_text(self) -> None:
        color = parse_hex_color("#006E2D")
        self.assertEqual(color, (0, 110, 45))
        self.assertEqual(format_hex_color(color), "#006E2D")

    def test_hex_color_accepts_lowercase_and_an_optional_hash(self) -> None:
        self.assertEqual(parse_hex_color("  1a2b3c  "), (26, 43, 60))
        self.assertEqual(format_hex_color((26, 43, 60)), "#1A2B3C")

    def test_hex_color_rejects_wrong_length_or_non_hex_digits(self) -> None:
        for value in ("", "#123", "#1234567", "#12GG34"):
            with self.subTest(value=value), self.assertRaises(CompositeProjectError):
                parse_hex_color(value)


class CompositeProjectTests(unittest.TestCase):
    def make_archive(self, folder: Path, name: str = "KID.DAT") -> DatArchive:
        # RLE stream expands to packed bytes 01 23 (source pixels 0,1,2,3).
        compressed = image_resource(4, 1, 0xB1, b"\x01\x01\x23")
        raw = build_dat(
            [
                (10, palette_resource()),
                (20, compressed),
                (30, b"unchanged binary payload"),
            ]
        )
        path = folder / name
        path.write_bytes(raw)
        return DatArchive.open(path)

    def make_standard_resource_archive(
        self,
        folder: Path,
        name: str,
        resource_id: int,
    ) -> DatArchive:
        raw = build_dat(
            [
                (10, palette_resource()),
                (resource_id, image_resource(4, 1, 0xB0, b"\x01\x23")),
            ]
        )
        path = folder / name
        path.write_bytes(raw)
        return DatArchive.open(path)

    def test_new_project_defaults_to_new_cga_without_changing_legacy_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            project = CompositeProject.for_archive(archive)

        self.assertEqual(DEFAULT_COMPOSITE_PROFILE, COMPOSITE_PROFILE_NEW)
        self.assertEqual(project.composite_profile, COMPOSITE_PROFILE_NEW)
        self.assertEqual(project.colors, list(DOSBOXX_CGA_COMPOSITE_NEW_COLORS))

    def test_standard_resources_start_with_exact_engine_audited_phases(self) -> None:
        cases = (
            ("TITLE.DAT", 41, (0,)),
            ("PRINCE.DAT", 166, (2,)),
            ("KID.DAT", 401, (0, 2)),
        )
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for archive_name, resource_id, phases in cases:
                with self.subTest(archive=archive_name, resource=resource_id):
                    archive = self.make_standard_resource_archive(
                        folder, archive_name, resource_id
                    )
                    image = archive.analyses[1].image
                    assert image is not None
                    project = CompositeProject.for_archive(archive)
                    edit = project.edit_for_image(archive, 1, image)
                    self.assertEqual(edit.phase_policy, PHASE_POLICY_ENGINE)
                    self.assertEqual(edit.enabled_phases, phases)
                    self.assertEqual(edit.variant_phases, phases)
                    self.assertEqual(edit.signal_phase, phases[0])

    def test_unknown_resource_stays_manual(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)

        self.assertEqual(edit.phase_policy, PHASE_POLICY_MANUAL)
        self.assertEqual(edit.enabled_phases, (0,))

    def test_sidecar_round_trip_preserves_bits_and_editable_colors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = self.make_archive(folder)
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.set_pattern(0, 0, 0b1111)
            edit.signal_phase = 3
            project.set_profile(COMPOSITE_PROFILE_OLD)
            project.set_color(15, (12, 34, 56))
            project.set_profile(COMPOSITE_PROFILE_NEW)
            project.set_color(15, (65, 43, 21))
            path = folder / "edit.pdcproj"
            project.save(path)
            loaded = CompositeProject.load(path)
            loaded.verify_archive(archive)

        self.assertEqual(loaded.composite_profile, COMPOSITE_PROFILE_NEW)
        self.assertEqual(loaded.colors[15], (65, 43, 21))
        loaded.set_profile(COMPOSITE_PROFILE_OLD)
        self.assertEqual(loaded.colors[15], (12, 34, 56))
        self.assertEqual(loaded.edits[1].bits, edit.bits)
        self.assertEqual(loaded.edits[1].signal_phase, 3)

    def test_sidecar_round_trip_preserves_multiple_image_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            raw = build_dat(
                [
                    (10, palette_resource()),
                    (41, image_resource(4, 1, 0xB0, b"\x01\x23")),
                    (42, image_resource(4, 1, 0xB0, b"\x45\x67")),
                ]
            )
            source = folder / "TITLE.DAT"
            source.write_bytes(raw)
            archive = DatArchive.open(source)
            project = CompositeProject.for_archive(archive)
            first = project.edit_for_image(archive, 1, archive.analyses[1].image)
            second = project.edit_for_image(archive, 2, archive.analyses[2].image)
            first.set_pattern(0, 0, 0b1111)
            second.set_pattern(0, 0, 0b0000)
            path = project.save(folder / "title.pdcproj")
            loaded = CompositeProject.load(path)

        self.assertEqual(sorted(loaded.edits), [1, 2])
        self.assertEqual(
            [loaded.edits[index].resource_id for index in sorted(loaded.edits)],
            [41, 42],
        )
        self.assertEqual(loaded.edits[1].bits, first.bits)
        self.assertEqual(loaded.edits[2].bits, second.bits)

    def test_phase_aware_sidecar_round_trip_preserves_independent_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = self.make_archive(folder)
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.set_enabled_phases((0, 2))
            phase_two = bytearray(edit.variant_bits(2))
            phase_two[2:4] = (1, 1)
            edit.mask_locked = True
            edit.set_variant_bits(2, phase_two, activate=False)
            edit.fallback_phase = 2
            edit.activate_phase(0, enable=False)
            path = project.save(folder / "phase-aware.pdcproj")
            loaded = CompositeProject.load(path)

        restored = loaded.edits[1]
        self.assertEqual(restored.phase_profile, PHASE_PROFILE_PARITY_02)
        self.assertEqual(restored.enabled_phases, (0, 2))
        self.assertEqual(restored.variant_phases, (0, 2))
        self.assertEqual(restored.fallback_phase, 2)
        self.assertEqual(restored.signal_phase, 0)
        self.assertTrue(restored.mask_locked)
        self.assertEqual(restored.variant_bits(0), edit.variant_bits(0))
        self.assertEqual(restored.variant_bits(2), phase_two)
        self.assertEqual(restored.source_zero_mask, edit.source_zero_mask)
        self.assertEqual(restored.mask_reference_bits, edit.mask_reference_bits)

    def test_sidecar_saves_every_phase_slot_for_every_edited_image(self) -> None:
        """One Ctrl+S payload must retain the complete multi-image phase project."""

        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            raw = build_dat(
                [
                    (10, palette_resource()),
                    (20, image_resource(4, 1, 0xB0, b"\x01\x23")),
                    (21, image_resource(4, 1, 0xB0, b"\x45\x67")),
                ]
            )
            source = folder / "CUSTOM.DAT"
            source.write_bytes(raw)
            archive = DatArchive.open(source)
            project = CompositeProject.for_archive(archive)
            first = project.edit_for_image(archive, 1, archive.analyses[1].image)
            second = project.edit_for_image(archive, 2, archive.analyses[2].image)

            first.set_enabled_phases((0, 1, 2, 3))
            for phase in PHASES:
                bits = bytearray(first.variant_bits(phase))
                bits[phase] ^= 1
                first.set_variant_bits(phase, bits, activate=False)
            first.activate_phase(3, enable=False)
            first.fallback_phase = 2

            # P0 remains stored after it is disabled. Sidecars preserve stored
            # work as well as the explicitly enabled runtime coverage.
            second.set_enabled_phases((1, 3))
            phase_three = bytearray(second.variant_bits(3))
            phase_three[-1] ^= 1
            second.set_variant_bits(3, phase_three, activate=False)
            second.activate_phase(1, enable=False)
            second.fallback_phase = 3

            expected = {
                index: {
                    phase: bytes(bits)
                    for phase, bits in edit.phase_variants.items()
                }
                for index, edit in project.edits.items()
            }
            destination = project.save(folder / "complete-phase-family.pdcproj")
            payload = json.loads(destination.read_text(encoding="utf-8"))
            loaded = CompositeProject.load(destination)
            loaded.verify_archive(archive)

        self.assertEqual(payload["version"], PROJECT_VERSION)
        self.assertEqual(len(payload["edits"]), 2)
        self.assertEqual(payload["edits"][0]["enabled_phases"], [0, 1, 2, 3])
        self.assertEqual(payload["edits"][1]["enabled_phases"], [1, 3])
        self.assertEqual(
            [item["phase"] for item in payload["edits"][0]["phase_variants"]],
            [0, 1, 2, 3],
        )
        self.assertEqual(
            [item["phase"] for item in payload["edits"][1]["phase_variants"]],
            [0, 1, 3],
        )
        self.assertEqual(loaded.edits[1].signal_phase, 3)
        self.assertEqual(loaded.edits[1].fallback_phase, 2)
        self.assertEqual(loaded.edits[2].signal_phase, 1)
        self.assertEqual(loaded.edits[2].fallback_phase, 3)
        for index, variants in expected.items():
            self.assertEqual(
                {
                    phase: bytes(bits)
                    for phase, bits in loaded.edits[index].phase_variants.items()
                },
                variants,
            )

    def test_version_three_sidecar_migrates_to_one_unlocked_fixed_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.signal_phase = 2
            payload = project.to_dict()
            payload["version"] = 3
            for item in payload["edits"]:
                for key in (
                    "enabled_phases",
                    "fallback_phase",
                    "mask_locked",
                    "source_zero_count",
                    "source_zero_base64",
                    "mask_reference_count",
                    "mask_reference_base64",
                    "phase_variants",
                ):
                    item.pop(key, None)
            loaded = CompositeProject.from_dict(payload)

        restored = loaded.edits[1]
        self.assertEqual(restored.signal_phase, 2)
        self.assertEqual(restored.enabled_phases, (2,))
        self.assertEqual(restored.variant_phases, (2,))
        self.assertEqual(restored.fallback_phase, 2)
        self.assertFalse(restored.mask_locked)
        self.assertFalse(restored.source_zero_mask)
        self.assertFalse(restored.mask_reference_bits)

    def test_version_four_sidecar_migrates_to_manual_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = self.make_standard_resource_archive(folder, "TITLE.DAT", 41)
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            project.edit_for_image(archive, 1, image)
            payload = project.to_dict()
            self.assertEqual(payload["version"], PROJECT_VERSION)
            payload["version"] = 4
            for item in payload["edits"]:
                item.pop("phase_policy", None)
            loaded = CompositeProject.from_dict(payload)

        self.assertEqual(loaded.edits[1].phase_policy, PHASE_POLICY_MANUAL)

    def test_profile_switch_keeps_bits_and_both_editable_palettes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.set_pattern(0, 0, 0b1011)
            expected_bits = bytearray(edit.bits)
            project.set_profile(COMPOSITE_PROFILE_OLD)
            project.set_color(1, (1, 2, 3))
            project.set_profile(COMPOSITE_PROFILE_NEW)
            project.set_color(1, (4, 5, 6))

        self.assertEqual(edit.bits, expected_bits)
        self.assertEqual(project.colors[1], (4, 5, 6))
        project.set_profile(COMPOSITE_PROFILE_OLD)
        self.assertEqual(project.colors[1], (1, 2, 3))
        self.assertEqual(edit.bits, expected_bits)

    def test_version_one_sidecar_migrates_to_old_cga_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            project = CompositeProject.for_archive(archive)
            project.set_profile(COMPOSITE_PROFILE_OLD)
            legacy = project.to_dict()
            legacy["version"] = 1
            legacy.pop("composite_profile")
            legacy.pop("composite_palettes")
            legacy["composite_palette"][1] = [9, 8, 7]
            for item in legacy["edits"]:
                item.pop("signal_phase", None)
            loaded = CompositeProject.from_dict(legacy)

        self.assertEqual(loaded.composite_profile, COMPOSITE_PROFILE_OLD)
        self.assertEqual(loaded.colors[1], (9, 8, 7))
        loaded.set_profile(COMPOSITE_PROFILE_NEW)
        self.assertEqual(loaded.colors, list(DOSBOXX_CGA_COMPOSITE_NEW_COLORS))

    def test_version_two_sidecar_defaults_signal_phase_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            project = CompositeProject.for_archive(archive)
            image = archive.analyses[1].image
            assert image is not None
            project.edit_for_image(archive, 1, image)
            legacy = project.to_dict()
            legacy["version"] = 2
            for item in legacy["edits"]:
                item.pop("signal_phase", None)
            loaded = CompositeProject.from_dict(legacy)

        self.assertEqual(loaded.edits[1].signal_phase, 0)

    def test_composite_renderer_uses_project_swatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.set_pattern(0, 0, 15)
            project.set_color(15, (12, 34, 56))
            raster = render_edited_composite(edit, project.colors)
        self.assertEqual(raster.pixels[:3], bytes((12, 34, 56)))

    def test_predicted_image_matches_save_inverse_and_changes_all_shared_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            hardware = hardware_palette_for_resource(archive, archive.resources[1])
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.set_pattern(0, 0, 0b1111)
            predicted = predicted_image_for_edit(image, edit, hardware)

        self.assertEqual(
            (predicted.width, predicted.height, predicted.bits, predicted.packed_pixels),
            (image.width, image.height, image.bits, image.packed_pixels),
        )
        self.assertNotEqual(predicted.pixels, image.pixels)
        self.assertEqual(
            [translated_index(predicted, x, 0, "cga", hardware) for x in (0, 1)],
            [3, 3],
        )
        for mode in ("vga", "ega", "cga"):
            with self.subTest(mode=mode):
                self.assertNotEqual(
                    render_display_mode(predicted, mode, hardware).pixels,
                    render_display_mode(image, mode, hardware).pixels,
                )

    def test_save_as_reencodes_only_changed_image_and_verifies_bits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = self.make_archive(folder)
            source_bytes = archive.path.read_bytes()
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.set_pattern(0, 0, 0b1111)
            destination = folder / "KID_COMPOSITE.DAT"
            written, changed = write_patched_dat(archive, project, destination)
            patched = DatArchive.open(written)

            self.assertEqual(changed, 1)
            self.assertEqual(archive.path.read_bytes(), source_bytes)
            self.assertEqual(patched.resources[0].data, archive.resources[0].data)
            self.assertEqual(patched.resources[2].data, archive.resources[2].data)
            self.assertEqual(patched.analyses[1].image.algorithm, 3)
            hardware = hardware_palette_for_resource(patched, patched.resources[1])
            self.assertEqual(initial_mode6_bits(patched.analyses[1].image, hardware), edit.bits)
            self.assertTrue(all(resource.checksum_ok for resource in patched.resources))

    def test_save_as_uses_explicit_fallback_instead_of_active_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.set_enabled_phases((0, 2))
            phase_two = bytearray(edit.variant_bits(2))
            phase_two[2:4] = (1, 1)
            edit.set_variant_bits(2, phase_two, activate=True)

            edit.fallback_phase = 0
            self.assertEqual(replacement_contents(archive, project), {})
            edit.fallback_phase = 2
            replacements = replacement_contents(archive, project)

        self.assertEqual(tuple(replacements), (1,))
        replacement_image = decode_prince_image(replacements[1])
        hardware = hardware_palette_for_resource(archive, archive.resources[1])
        self.assertEqual(initial_mode6_bits(replacement_image, hardware), phase_two)

    def test_locked_source_zero_mask_protects_every_variant_and_inverse_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            hardware = hardware_palette_for_resource(archive, archive.resources[1])
            edit.mask_locked = True

            self.assertEqual(edit.locked_bit_constraints()[:2], (0, 0))
            self.assertTrue(all(value == -1 for value in edit.locked_bit_constraints()[2:]))
            self.assertEqual(edit.set_bit(0, 0, 1), [])
            invalid = bytearray(edit.bits)
            invalid[0] = 1
            with self.assertRaises(CompositeProjectError):
                edit.set_variant_bits(2, invalid)

            legal = bytearray(edit.bits)
            legal[2:4] = (0, 0)
            pixels = source_pixels_for_edit(
                image,
                edit,
                hardware,
                bits=legal,
            )

        self.assertEqual(pixels[0], 0)
        self.assertNotEqual(pixels[1], 0)

    def test_phase_manifest_contains_lossless_bits_pixels_and_lzg_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            edit.set_enabled_phases((0, 2))
            phase_two = bytearray(edit.variant_bits(2))
            phase_two[2:4] = (1, 1)
            edit.mask_locked = True
            edit.set_variant_bits(2, phase_two, activate=False)
            edit.fallback_phase = 2
            manifest = phase_manifest_dict(archive, project, global_phase_bias=3)

        self.assertEqual(manifest["global_phase_bias"], 3)
        self.assertIn("destination_640_x", manifest["runtime_phase_formula"])
        self.assertEqual(len(manifest["resources"]), 1)
        family = manifest["resources"][0]
        self.assertEqual(family["enabled_phases"], [0, 2])
        self.assertEqual(family["phase_profile"], PHASE_PROFILE_PARITY_02)
        self.assertEqual(family["fallback_phase"], 2)
        self.assertTrue(family["mask_locked"])
        self.assertEqual(
            base64.b64decode(family["mask_reference_bits_base64"]),
            pack_bits(edit.mask_reference_bits),
        )
        self.assertEqual([item["phase"] for item in family["variants"]], [0, 2])
        hardware = hardware_palette_for_resource(archive, archive.resources[1])
        for item in family["variants"]:
            phase = item["phase"]
            expected_bits = edit.variant_bits(phase)
            expected_pixels = source_pixels_for_edit(
                image,
                edit,
                hardware,
                phase=phase,
            )
            self.assertEqual(
                base64.b64decode(item["packed_bits_base64"]),
                pack_bits(expected_bits),
            )
            self.assertEqual(
                base64.b64decode(item["source_pixels_base64"]),
                expected_pixels,
            )
            encoded = base64.b64decode(item["lzg_resource_base64"])
            self.assertEqual(decode_prince_image(encoded).pixels, expected_pixels)

    def test_engine_audited_manifest_records_contract_and_rejects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = self.make_standard_resource_archive(folder, "KID.DAT", 401)
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            edit = project.edit_for_image(archive, 1, image)
            manifest = phase_manifest_dict(archive, project)

            self.assertEqual(manifest["version"], PHASE_MANIFEST_VERSION)
            family = manifest["resources"][0]
            self.assertEqual(family["phase_policy"], PHASE_POLICY_ENGINE)
            self.assertEqual(family["enabled_phases"], [0, 2])
            self.assertEqual(
                family["engine_phase_usage"]["required_phases_at_global_bias_0"],
                [0, 2],
            )

            with self.assertRaises(CompositeProjectError):
                phase_manifest_dict(archive, project, global_phase_bias=1)

            edit.set_enabled_phases((0,))
            with self.assertRaises(CompositeProjectError):
                project.to_dict()

    def test_lzg_encoder_round_trips_literals_runs_and_initial_history(self) -> None:
        payloads = (
            b"\x00" * 2048,
            bytes(range(256)) * 4,
            (b"Prince of Persia composite graphics\x00" * 40)[:1024],
        )
        for payload in payloads:
            with self.subTest(length=len(payload), prefix=payload[:8]):
                encoded = encode_lzg(payload)
                content = image_resource(len(payload) * 2, 1, 0xB3, encoded)
                decoded = decode_prince_image(content)
                self.assertEqual(decoded.packed_pixels, payload)
        self.assertLess(len(encode_lzg(payloads[0])), len(payloads[0]) // 10)

    def test_lzg_image_encoder_preserves_transposed_orientation(self) -> None:
        original = image_resource(4, 2, 0xB4, b"\x0F\xAB\x12\xCD\x34")
        image = decode_prince_image(original)
        pixels = bytes((1, 2, 3, 4, 10, 11, 12, 13))
        encoded = encode_image_lzg(original, image, pixels)
        self.assertEqual(encoded[5] & 0x0F, 4)
        self.assertEqual(decode_prince_image(encoded).pixels, pixels)

    def test_rebuild_without_replacements_preserves_all_payloads_and_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            rebuilt = rebuild_dat(archive, {})
            path = Path(temp) / "rebuilt.dat"
            path.write_bytes(rebuilt)
            reopened = DatArchive.open(path)
        self.assertEqual(
            [(item.resource_id, item.data) for item in reopened.resources],
            [(item.resource_id, item.data) for item in archive.resources],
        )

    def test_unmodified_initialized_edit_does_not_replace_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            image = archive.analyses[1].image
            assert image is not None
            project = CompositeProject.for_archive(archive)
            project.edit_for_image(archive, 1, image)
            self.assertEqual(replacement_contents(archive, project), {})

    def test_project_rejects_different_source_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            archive = self.make_archive(folder)
            project = CompositeProject.for_archive(archive)
            other = self.make_archive(folder, "OTHER.DAT")
            # Change a non-structural byte and repair its resource checksum via rebuild.
            changed = rebuild_dat(other, {2: b"different payload"})
            other.path.write_bytes(changed)
            other = DatArchive.open(other.path)
            with self.assertRaises(CompositeProjectError):
                project.verify_archive(other)

    def test_source_dat_cannot_be_selected_as_save_as_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            archive = self.make_archive(Path(temp))
            project = CompositeProject.for_archive(archive)
            with self.assertRaises(CompositeProjectError):
                write_patched_dat(archive, project, archive.path)


if __name__ == "__main__":
    unittest.main()
