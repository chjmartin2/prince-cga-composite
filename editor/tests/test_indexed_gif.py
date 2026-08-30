from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from indexed_gif import (
    IndexedGifError,
    decode_indexed_gif,
    indexed_gif_bytes,
    read_indexed_gif,
    require_exact_format,
    write_indexed_gif,
)


class IndexedGifTests(unittest.TestCase):
    def setUp(self) -> None:
        # Duplicate RGB entries are intentional: Composite indices 5 and 10
        # can look identical while still representing different bit patterns.
        self.palette = tuple(
            (119, 115, 122) if index in (5, 10) else (index * 13, index * 7, index * 3)
            for index in range(16)
        )
        self.pixels = bytes((0, 1, 5, 10, 15, 10, 5, 0))

    def test_round_trip_preserves_exact_indices_and_duplicate_palette_entries(self) -> None:
        payload = indexed_gif_bytes(4, 2, self.palette, self.pixels)
        image = decode_indexed_gif(payload)

        self.assertEqual(payload[:6], b"GIF87a")
        self.assertEqual((image.width, image.height), (4, 2))
        self.assertEqual(image.palette, self.palette)
        self.assertEqual(image.pixels, self.pixels)
        self.assertEqual(image.palette[5], image.palette[10])
        self.assertNotEqual(image.pixels[2], image.pixels[3])

    def test_file_helpers_preserve_the_same_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "image.gif"
            write_indexed_gif(path, 4, 2, self.palette, self.pixels)
            image = read_indexed_gif(path)

        require_exact_format(image, width=4, height=2, palette=self.palette)
        self.assertEqual(image.pixels, self.pixels)

    def test_exact_format_rejects_dimensions_palette_size_color_and_order(self) -> None:
        image = decode_indexed_gif(
            indexed_gif_bytes(4, 2, self.palette, self.pixels)
        )
        with self.assertRaisesRegex(IndexedGifError, "requires exactly 8×1"):
            require_exact_format(image, width=8, height=1, palette=self.palette)
        with self.assertRaisesRegex(IndexedGifError, "requires exactly 4"):
            require_exact_format(
                image,
                width=4,
                height=2,
                palette=((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 0, 255)),
            )
        changed = list(self.palette)
        changed[3] = (1, 2, 3)
        with self.assertRaisesRegex(IndexedGifError, "palette entry 3"):
            require_exact_format(image, width=4, height=2, palette=changed)
        reordered = list(self.palette)
        reordered[1], reordered[2] = reordered[2], reordered[1]
        with self.assertRaisesRegex(IndexedGifError, "palette entry 1"):
            require_exact_format(image, width=4, height=2, palette=reordered)

    def test_transparency_animation_and_trailing_data_are_rejected(self) -> None:
        payload = indexed_gif_bytes(4, 2, self.palette, self.pixels)
        descriptor = 13 + len(self.palette) * 3
        transparent = (
            b"GIF89a"
            + payload[6:descriptor]
            + b"\x21\xF9\x04\x01\x00\x00\x00\x00"
            + payload[descriptor:]
        )
        with self.assertRaisesRegex(IndexedGifError, "Transparent"):
            decode_indexed_gif(transparent)

        image_block = payload[descriptor:-1]
        animated = payload[:-1] + image_block + b";"
        with self.assertRaisesRegex(IndexedGifError, "multi-frame"):
            decode_indexed_gif(animated)

        with self.assertRaisesRegex(IndexedGifError, "trailing data"):
            decode_indexed_gif(payload + b"extra")

    def test_writer_rejects_invalid_palette_dimensions_and_pixel_indices(self) -> None:
        with self.assertRaisesRegex(IndexedGifError, "power of two"):
            indexed_gif_bytes(1, 1, ((0, 0, 0),) * 3, b"\x00")
        with self.assertRaisesRegex(IndexedGifError, "dimensions"):
            indexed_gif_bytes(0, 1, ((0, 0, 0), (255, 255, 255)), b"")
        with self.assertRaisesRegex(IndexedGifError, "outside its palette"):
            indexed_gif_bytes(
                1,
                1,
                ((0, 0, 0), (255, 255, 255)),
                b"\x02",
            )
        with self.assertRaisesRegex(IndexedGifError, "between 0 and 255"):
            indexed_gif_bytes(
                1,
                1,
                ((0, 0, 0), (255, 255, 255)),
                [300],
            )


if __name__ == "__main__":
    unittest.main()
