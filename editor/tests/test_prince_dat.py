from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
import struct
import tempfile
import unittest

from prince_dat import (
    BUILTIN_PALETTES,
    COMPOSITE_PROFILE_NEW,
    COMPOSITE_PROFILE_OLD,
    DEFAULT_COMPOSITE_COLORS,
    DEFAULT_COMPOSITE_PROFILE,
    DOSBOXX_CGA_COMPOSITE_COLORS,
    DOSBOXX_CGA_COMPOSITE_NEW_COLORS,
    DOSBOXX_CGA_COMPOSITE_OLD_COLORS,
    DOSBOXX_CGA_COMPOSITE_PROFILES,
    DatArchive,
    DatFormatError,
    ImageDecodeError,
    NTSC_COMPOSITE_MODE,
    choose_auto_palette,
    composite_pattern_at,
    decode_prince_image,
    display_colors,
    display_horizontal_factors,
    extract_all,
    mode6_bit_at,
    normalized_display_width,
    png_bytes,
    render_preview_rgb,
    render_display_mode,
    write_image_png,
)


def image_resource(width: int, height: int, type_byte: int, payload: bytes) -> bytes:
    return struct.pack("<HHBB", height, width, 0, type_byte) + payload


def build_dat(resources: list[tuple[int, bytes]]) -> bytes:
    body = bytearray(b"\x00" * 6)
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


class ImageCodecTests(unittest.TestCase):
    def test_b0_raw_4bit_uses_high_nibble_first(self) -> None:
        image = decode_prince_image(image_resource(3, 2, 0xB0, b"\xAB\xC0\x12\x30"))
        self.assertEqual((image.width, image.height, image.bits), (3, 2, 4))
        self.assertEqual(image.pixels, bytes((10, 11, 12, 1, 2, 3)))

    def test_b1_rle_literal_and_repeat_blocks(self) -> None:
        # Packed result AB AB CD EF: one repeat and one literal block.
        image = decode_prince_image(
            image_resource(4, 2, 0xB1, b"\xFE\xAB\x01\xCD\xEF")
        )
        self.assertEqual(image.packed_pixels, b"\xAB\xAB\xCD\xEF")
        self.assertEqual(image.pixels, bytes((10, 11, 10, 11, 12, 13, 14, 15)))

    def test_b2_rle_top_to_bottom_transposes_packed_bytes(self) -> None:
        # Desired rows are AB CD / 12 34; the encoded column order is AB 12 CD 34.
        image = decode_prince_image(
            image_resource(4, 2, 0xB2, b"\x03\xAB\x12\xCD\x34")
        )
        self.assertEqual(image.packed_pixels, b"\xAB\xCD\x12\x34")
        self.assertEqual(image.pixels, bytes((10, 11, 12, 13, 1, 2, 3, 4)))

    def test_b3_lzg_literal_packet(self) -> None:
        image = decode_prince_image(
            image_resource(4, 2, 0xB3, b"\x0F\xAB\xCD\x12\x34")
        )
        self.assertEqual(image.packed_pixels, b"\xAB\xCD\x12\x34")

    def test_b3_lzg_overlapping_back_reference(self) -> None:
        # One AB literal followed by a distance-one, length-three copy.
        image = decode_prince_image(
            image_resource(8, 1, 0xB3, b"\x01\xAB\x03\xBE")
        )
        self.assertEqual(image.packed_pixels, b"\xAB\xAB\xAB\xAB")

    def test_b4_lzg_top_to_bottom(self) -> None:
        image = decode_prince_image(
            image_resource(4, 2, 0xB4, b"\x0F\xAB\x12\xCD\x34")
        )
        self.assertEqual(image.packed_pixels, b"\xAB\xCD\x12\x34")

    def test_one_bit_raw_is_msb_first(self) -> None:
        image = decode_prince_image(image_resource(10, 1, 0x00, b"\xAA\xC0"))
        self.assertEqual(image.bits, 1)
        self.assertEqual(image.pixels, bytes((1, 0, 1, 0, 1, 0, 1, 0, 1, 1)))

    def test_eight_bit_raw(self) -> None:
        image = decode_prince_image(image_resource(3, 1, 0xF0, b"\x00\x7F\xFF"))
        self.assertEqual(image.bits, 8)
        self.assertEqual(image.pixels, b"\x00\x7F\xFF")

    def test_truncated_stream_is_rejected(self) -> None:
        with self.assertRaises(ImageDecodeError):
            decode_prince_image(image_resource(4, 2, 0xB1, b"\x03\xAB"))


class ArchiveTests(unittest.TestCase):
    def test_index_resources_checksums_and_image_classification(self) -> None:
        graphic = image_resource(3, 2, 0xB0, b"\xAB\xC0\x12\x30")
        raw = build_dat([(100, graphic), (200, b"not an image")])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "VDUNGEON.DAT"
            path.write_bytes(raw)
            archive = DatArchive.open(path)

        self.assertEqual([r.resource_id for r in archive.resources], [100, 200])
        self.assertTrue(all(r.checksum_ok for r in archive.resources))
        self.assertIsNotNone(archive.analyses[0].image)
        self.assertEqual(archive.analyses[1].kind, "Binary data")
        self.assertEqual(choose_auto_palette(archive, archive.resources[0], archive.analyses[0].image).key, "rgbi")

    def test_embedded_six_bit_palette_is_detected_and_selected(self) -> None:
        palette = bytearray(100)
        palette[1:4] = b"\x00\x00\x10"
        palette[4:10] = bytes((0, 0, 0, 63, 32, 16))
        graphic = image_resource(2, 1, 0xB0, b"\x10")
        raw = build_dat([(10, bytes(palette)), (11, graphic)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "VDUNGEON.DAT"
            path.write_bytes(raw)
            archive = DatArchive.open(path)

        self.assertEqual(len(archive.embedded_palettes), 1)
        self.assertEqual(archive.embedded_palettes[0].colors[1], (255, 130, 65))
        selected = choose_auto_palette(
            archive, archive.resources[1], archive.analyses[1].image
        )
        self.assertEqual(selected.key, "embedded-0")

    def test_c_prefixed_archive_uses_cga_preview(self) -> None:
        graphic = image_resource(2, 1, 0xB0, b"\x12")
        raw = build_dat([(10, graphic)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "CDUNGEON.DAT"
            path.write_bytes(raw)
            archive = DatArchive.open(path)
        selected = choose_auto_palette(
            archive, archive.resources[0], archive.analyses[0].image
        )
        self.assertEqual(selected.key, "cga4-high")

    def test_bad_checksum_is_reported_without_hiding_resource(self) -> None:
        raw = bytearray(build_dat([(7, b"payload")]))
        raw[6] ^= 0x01
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "BAD.DAT"
            path.write_bytes(raw)
            archive = DatArchive.open(path)
        self.assertFalse(archive.resources[0].checksum_ok)

    def test_malformed_index_is_rejected(self) -> None:
        with self.assertRaises(DatFormatError):
            DatArchive.open(Path(__file__))

    def test_extract_all_writes_png_binary_and_manifest(self) -> None:
        graphic = image_resource(3, 2, 0xB0, b"\xAB\xC0\x12\x30")
        raw = build_dat([(100, graphic), (200, b"not an image")])
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            dat_path = temp_path / "VDUNGEON.DAT"
            dat_path.write_bytes(raw)
            archive = DatArchive.open(dat_path)
            images, others = extract_all(archive, temp_path / "out")
            output_files = {p.name for p in (temp_path / "out").iterdir()}
            manifest_text = (temp_path / "out" / "manifest.csv").read_text(
                encoding="utf-8-sig"
            )

        self.assertEqual((images, others), (1, 1))
        self.assertEqual(output_files, {"res00100.png", "res00200.bin", "manifest.csv"})
        rows = list(csv.DictReader(StringIO(manifest_text)))
        self.assertEqual(rows[0]["resource_id"], "100")
        self.assertEqual(rows[0]["compression"], "RAW")


class PngTests(unittest.TestCase):
    def test_dependency_free_png_header(self) -> None:
        encoded = png_bytes(2, 1, b"\x00\x00\x00\xFF\xFF\xFF")
        self.assertTrue(encoded.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(encoded[12:16], b"IHDR")
        width, height = struct.unpack(">II", encoded[16:24])
        self.assertEqual((width, height), (2, 1))


class CgaPreviewTests(unittest.TestCase):
    @staticmethod
    def palette(key: str):
        return next(palette for palette in BUILTIN_PALETTES if palette.key == key)

    def test_old_composite_table_matches_dosbox_x_cga_composite_mode6(self) -> None:
        expected_hex = (
            "000000", "006300", "0042E2", "009FFD",
            "A6005E", "77737A", "D14DFF", "99ACFF",
            "4D4000", "00B900", "77737A", "00EB91",
            "FF4400", "DFC400", "FF85F0", "FFFCFF",
        )
        actual_hex = tuple("".join(f"{component:02X}" for component in color)
                           for color in DOSBOXX_CGA_COMPOSITE_OLD_COLORS)
        self.assertEqual(actual_hex, expected_hex)
        self.assertIs(DOSBOXX_CGA_COMPOSITE_COLORS, DOSBOXX_CGA_COMPOSITE_OLD_COLORS)

    def test_new_composite_defaults_match_dosbox_x_cga_composite2_mode6(self) -> None:
        expected_hex = (
            "000000", "006629", "0047FF", "0094FF",
            "BE0030", "77737A", "FF41FF", "BF9CFF",
            "1E5200", "00CC00", "77737A", "00EFBC",
            "FF5500", "B9D600", "FF7FC6", "FFFCFF",
        )
        actual_hex = tuple(
            "".join(f"{component:02X}" for component in color)
            for color in DOSBOXX_CGA_COMPOSITE_NEW_COLORS
        )
        self.assertEqual(actual_hex, expected_hex)
        self.assertEqual(
            DOSBOXX_CGA_COMPOSITE_PROFILES,
            {
                COMPOSITE_PROFILE_OLD: DOSBOXX_CGA_COMPOSITE_OLD_COLORS,
                COMPOSITE_PROFILE_NEW: DOSBOXX_CGA_COMPOSITE_NEW_COLORS,
            },
        )

    def test_every_unsaved_composite_render_default_uses_new_cga(self) -> None:
        self.assertEqual(DEFAULT_COMPOSITE_PROFILE, COMPOSITE_PROFILE_NEW)
        self.assertIs(DEFAULT_COMPOSITE_COLORS, DOSBOXX_CGA_COMPOSITE_NEW_COLORS)
        self.assertIs(
            display_colors("composite"),
            DOSBOXX_CGA_COMPOSITE_NEW_COLORS,
        )
        self.assertEqual(
            self.palette("composite-simple").colors,
            DOSBOXX_CGA_COMPOSITE_NEW_COLORS,
        )
        image = decode_prince_image(image_resource(2, 1, 0xB0, b"\x12"))
        rendered = render_display_mode(image, "composite")
        self.assertEqual(
            rendered.pixels,
            bytes(DOSBOXX_CGA_COMPOSITE_NEW_COLORS[0b0110]),
        )

    def test_mode6_reinterprets_each_2bit_pixel_as_two_1bit_pixels(self) -> None:
        image = decode_prince_image(image_resource(4, 1, 0xB0, b"\x01\x23"))
        rendered = render_preview_rgb(image, self.palette("mono"))

        self.assertEqual((rendered.width, rendered.height, rendered.mode), (8, 1, "mode6"))
        bits = [mode6_bit_at(image, x, 0)[0] for x in range(rendered.width)]
        self.assertEqual(bits, [0, 0, 0, 1, 1, 0, 1, 1])

    def test_native_1bit_resource_keeps_its_width_in_mode6(self) -> None:
        image = decode_prince_image(image_resource(8, 1, 0x00, b"\xA5"))
        rendered = render_preview_rgb(image, self.palette("mono"))
        self.assertEqual((rendered.width, rendered.height), (8, 1))

    def test_simple_composite_groups_four_mode6_bits_per_color_cell(self) -> None:
        # Source indices 1 and 2 become 01 10, selecting pattern 0110 (index 6).
        image = decode_prince_image(image_resource(2, 1, 0xB0, b"\x12"))
        rendered = render_preview_rgb(image, self.palette("composite-simple"))
        pattern, source_start, source_end = composite_pattern_at(image, 0, 0)

        self.assertEqual((rendered.width, rendered.height), (1, 1))
        self.assertEqual((pattern, source_start, source_end), (0b0110, 0, 1))
        self.assertEqual(
            rendered.pixels, bytes(DOSBOXX_CGA_COMPOSITE_NEW_COLORS[0b0110])
        )

    def test_full_cga_scanline_becomes_640_digital_or_160_composite_pixels(self) -> None:
        image = decode_prince_image(image_resource(320, 1, 0xB0, bytes(160)))
        digital = render_preview_rgb(image, self.palette("mono"))
        composite = render_preview_rgb(image, self.palette("composite-simple"))
        self.assertEqual(digital.width, 640)
        self.assertEqual(composite.width, 160)

    def test_ntsc_composite_renders_every_mode6_sample_with_neighbor_artifacts(self) -> None:
        image = decode_prince_image(image_resource(2, 1, 0xB0, b"\x12"))
        rendered = render_display_mode(image, NTSC_COMPOSITE_MODE)

        self.assertEqual((rendered.width, rendered.height), (4, 1))
        self.assertEqual(rendered.mode, "composite-artifact")
        self.assertNotEqual(rendered.pixels[:3], rendered.pixels[3:6])
        self.assertEqual(
            normalized_display_width(rendered.width, NTSC_COMPOSITE_MODE, image.bits),
            image.width,
        )

    def test_transformed_4bit_previews_normalize_to_source_display_width(self) -> None:
        self.assertEqual(display_horizontal_factors("mode6", 4), (1, 2))
        self.assertEqual(display_horizontal_factors("composite", 4), (2, 1))
        self.assertEqual(normalized_display_width(640, "mode6", 4), 320)
        self.assertEqual(normalized_display_width(160, "composite", 4), 320)

    def test_native_1bit_previews_normalize_to_source_display_width(self) -> None:
        self.assertEqual(display_horizontal_factors("mode6", 1), (1, 1))
        self.assertEqual(display_horizontal_factors("composite", 1), (4, 1))
        self.assertEqual(normalized_display_width(640, "mode6", 1), 640)
        self.assertEqual(normalized_display_width(160, "composite", 1), 640)

    def test_png_export_uses_transformed_preview_dimensions(self) -> None:
        image = decode_prince_image(image_resource(4, 1, 0xB0, b"\x01\x23"))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mode6.png"
            write_image_png(path, image, self.palette("mono"))
            encoded = path.read_bytes()
        width, height = struct.unpack(">II", encoded[16:24])
        self.assertEqual((width, height), (8, 1))


if __name__ == "__main__":
    unittest.main()
