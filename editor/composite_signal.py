"""Artifact-accurate CGA composite scanline simulation.

This is a dependency-free port of the Reenigne/Jenner decoder used by
``chjmartin2/cga-image-studio`` (``cga_v165.py``, blob
``e8cf2bb074bcf707594bbb7d8070931bfb19715e``).  Unlike the editor's
160-column color-cell view, this decoder operates on every Mode-6 bit and
therefore preserves transition colors, ringing, and neighboring-pixel bleed.
"""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from functools import lru_cache
import math
from typing import Sequence

from prince_dat import (
    COMPOSITE_PROFILE_NEW,
    COMPOSITE_PROFILE_OLD,
    RenderedRaster,
)


# Sampled CGA chroma multiplexer values used by the Reenigne/Jenner model.
_CHROMA_MULTIPLEXER = (
    2, 2, 2, 2, 114, 174, 4, 3, 2, 1, 133, 135, 2, 113, 150, 4,
    133, 2, 1, 99, 151, 152, 2, 1, 3, 2, 96, 136, 151, 152, 151, 152,
    2, 56, 62, 4, 111, 250, 118, 4, 0, 51, 207, 137, 1, 171, 209, 5,
    140, 50, 54, 100, 133, 202, 57, 4, 2, 50, 153, 149, 128, 198, 198, 135,
    32, 1, 36, 81, 147, 158, 1, 42, 33, 1, 210, 254, 34, 109, 169, 77,
    177, 2, 0, 165, 189, 154, 3, 44, 33, 0, 91, 197, 178, 142, 144, 192,
    4, 2, 61, 67, 117, 151, 112, 83, 4, 0, 249, 255, 3, 107, 249, 117,
    147, 1, 50, 162, 143, 141, 52, 54, 3, 0, 145, 206, 124, 123, 192, 193,
    72, 78, 2, 0, 159, 208, 4, 0, 53, 58, 164, 159, 37, 159, 171, 1,
    248, 117, 4, 98, 212, 218, 5, 2, 54, 59, 93, 121, 176, 181, 134, 130,
    1, 61, 31, 0, 160, 255, 34, 1, 1, 58, 197, 166, 0, 177, 194, 2,
    162, 111, 34, 96, 205, 253, 32, 1, 1, 57, 123, 125, 119, 188, 150, 112,
    78, 4, 0, 75, 166, 180, 20, 38, 78, 1, 143, 246, 42, 113, 156, 37,
    252, 4, 1, 188, 175, 129, 1, 37, 118, 4, 88, 249, 202, 150, 145, 200,
    61, 59, 60, 60, 228, 252, 117, 77, 60, 58, 248, 251, 81, 212, 254, 107,
    198, 59, 58, 169, 250, 251, 81, 80, 100, 58, 154, 250, 251, 252, 252, 252,
)
_INTENSITY = (77.175381, 88.654656, 166.564623, 174.228438)
_TAU = 6.28318531


def _byte_clamp(value: int) -> int:
    """Match the reference decoder's ``(value >> 13).clamp(0, 255)``."""

    shifted = value >> 13
    return min(255, max(0, shifted))


class CompositeSignalDecoder:
    """One configured Old- or New-CGA composite signal decoder."""

    def __init__(self, *, new_cga: bool) -> None:
        self.new_cga = bool(new_cga)
        self.composite_table = [0] * 1024
        self.video_ri = 0
        self.video_rq = 0
        self.video_gi = 0
        self.video_gq = 0
        self.video_bi = 0
        self.video_bq = 0
        self.video_sharpness = 0
        self._configure()

    @staticmethod
    def _new_cga_mix(chroma: float, intensity: float, red: float, green: float, blue: float) -> float:
        return (
            (chroma / 0.72) * 0.29
            + (intensity / 0.28) * 0.32
            + (red / 0.28) * 0.10
            + (green / 0.28) * 0.22
            + (blue / 0.28) * 0.07
        )

    def _configure(self) -> None:
        """Configure the exact CGA Image Studio Old/New default preset."""

        red_i, red_q = 0.9563, 0.6210
        green_i, green_q = -0.2721, -0.6474
        blue_i, blue_q = -1.1069, 1.7046
        cga_mode = 0b0_0001

        if not self.new_cga:
            minimum = float(_CHROMA_MULTIPLEXER[0]) + _INTENSITY[0]
            maximum = float(_CHROMA_MULTIPLEXER[255]) + _INTENSITY[3]
        else:
            i0 = _INTENSITY[0]
            i3 = _INTENSITY[3]
            minimum = self._new_cga_mix(float(_CHROMA_MULTIPLEXER[0]), i0, i0, i0, i0)
            maximum = self._new_cga_mix(float(_CHROMA_MULTIPLEXER[255]), i3, i3, i3, i3)

        mode_contrast = 256.0 / (maximum - minimum)
        mode_brightness = -minimum * mode_contrast
        mode_hue = 14.0 if (cga_mode & 3) == 1 else 4.0
        mode_contrast *= 1.2 if self.new_cga else 1.0
        mode_brightness += -50.0 if self.new_cga else 0.0
        mode_saturation = 4.35 if self.new_cga else 2.9

        for index in range(1024):
            phase = index & 3
            right = (index >> 2) & 15
            left = (index >> 6) & 15
            chroma = float(
                _CHROMA_MULTIPLEXER[
                    ((left & 7) << 5) | ((right & 7) << 2) | phase
                ]
            )
            intensity = _INTENSITY[(left >> 3) | ((right >> 2) & 2)]
            if not self.new_cga:
                voltage = chroma + intensity
            else:
                red = _INTENSITY[((left >> 2) & 1) | ((right >> 1) & 2)]
                green = _INTENSITY[((left >> 1) & 1) | (right & 2)]
                blue = _INTENSITY[(left & 1) | ((right << 1) & 2)]
                voltage = self._new_cga_mix(chroma, intensity, red, green, blue)
            self.composite_table[index] = int(
                voltage * mode_contrast + mode_brightness
            )

        reference_i = float(
            self.composite_table[6 * 68] - self.composite_table[6 * 68 + 2]
        )
        reference_q = float(
            self.composite_table[6 * 68 + 1] - self.composite_table[6 * 68 + 3]
        )
        angle = _TAU * (33.0 + 90.0 + mode_hue) / 360.0
        cosine = math.cos(angle)
        sine = math.sin(angle)
        denominator = math.sqrt(reference_i * reference_i + reference_q * reference_q)
        scale = 0.0 if denominator == 0.0 else 256.0 * mode_saturation / denominator
        adjust_i = -(reference_i * cosine + reference_q * sine) * scale
        adjust_q = (reference_q * cosine - reference_i * sine) * scale

        self.video_ri = int(red_i * adjust_i + red_q * adjust_q)
        self.video_rq = int(-red_i * adjust_q + red_q * adjust_i)
        self.video_gi = int(green_i * adjust_i + green_q * adjust_q)
        self.video_gq = int(-green_i * adjust_q + green_q * adjust_i)
        self.video_bi = int(blue_i * adjust_i + blue_q * adjust_q)
        self.video_bq = int(-blue_i * adjust_q + blue_q * adjust_i)

    def decode_scanline(self, rgbi: Sequence[int], *, border: int = 0) -> tuple[tuple[int, int, int], ...]:
        """Decode a scanline of RGBI nibbles at one RGB result per input sample."""

        width = len(rgbi)
        if width < 4 or width % 4:
            raise ValueError("Composite scanlines must contain a multiple of four samples.")
        if not 0 <= border <= 15 or any(not 0 <= value <= 15 for value in rgbi):
            raise ValueError("Composite RGBI samples must be in the range 0–15.")

        temp = [0] * (width + 10)
        a_temp = [0] * (width + 2)
        b_temp = [0] * (width + 2)
        output_cursor = 0
        border_table = self.composite_table[border * 68 : border * 68 + 68]

        for x in range(4):
            temp[output_cursor] = border_table[(x + 3) & 3]
            output_cursor += 1
        temp[output_cursor] = self.composite_table[
            (border << 6) | ((rgbi[0] & 15) << 2) | 3
        ]
        output_cursor += 1
        for x in range(width - 1):
            left = rgbi[x] & 15
            right = rgbi[x + 1] & 15
            temp[output_cursor] = self.composite_table[
                (left << 6) | (right << 2) | (x & 3)
            ]
            output_cursor += 1
        temp[output_cursor] = self.composite_table[
            ((rgbi[-1] & 15) << 6) | (border << 2) | 3
        ]
        output_cursor += 1
        for x in range(5):
            temp[output_cursor] = border_table[x & 3]
            output_cursor += 1

        input_cursor = 4
        for x in range(width + 2):
            a_temp[x] = (
                temp[input_cursor - 4]
                - ((temp[input_cursor - 2] - temp[input_cursor] + temp[input_cursor + 2]) << 1)
                + temp[input_cursor + 4]
            )
            b_temp[x] = (
                temp[input_cursor - 3]
                - temp[input_cursor - 1]
                + temp[input_cursor + 1]
                - temp[input_cursor + 3]
            ) << 1
            input_cursor += 1

        input_cursor = 5
        a_cursor = 1
        b_cursor = 1
        temp[input_cursor - 1] = (temp[input_cursor - 1] << 3) - a_temp[a_cursor - 1]
        temp[input_cursor] = (temp[input_cursor] << 3) - a_temp[a_cursor]

        output: list[tuple[int, int, int]] = []
        for _block in range(width // 4):
            for rotation in range(4):
                temp[input_cursor + 1] = (temp[input_cursor + 1] << 3) - a_temp[a_cursor + 1]
                chroma_i = a_temp[a_cursor]
                chroma_q = b_temp[b_cursor]
                doubled = temp[input_cursor] + temp[input_cursor]
                adjacent = temp[input_cursor - 1] + temp[input_cursor + 1]
                luminance = (doubled + adjacent) << 8

                if rotation == 0:
                    red = luminance + self.video_ri * chroma_i + self.video_rq * chroma_q
                    green = luminance + self.video_gi * chroma_i + self.video_gq * chroma_q
                    blue = luminance + self.video_bi * chroma_i + self.video_bq * chroma_q
                elif rotation == 1:
                    red = luminance + self.video_ri * (-chroma_q) + self.video_rq * chroma_i
                    green = luminance + self.video_gi * (-chroma_q) + self.video_gq * chroma_i
                    blue = luminance + self.video_bi * (-chroma_q) + self.video_bq * chroma_i
                elif rotation == 2:
                    red = luminance + self.video_ri * (-chroma_i) + self.video_rq * (-chroma_q)
                    green = luminance + self.video_gi * (-chroma_i) + self.video_gq * (-chroma_q)
                    blue = luminance + self.video_bi * (-chroma_i) + self.video_bq * (-chroma_q)
                else:
                    red = luminance + self.video_ri * chroma_q + self.video_rq * (-chroma_i)
                    green = luminance + self.video_gi * chroma_q + self.video_gq * (-chroma_i)
                    blue = luminance + self.video_bi * chroma_q + self.video_bq * (-chroma_i)

                output.append(
                    (_byte_clamp(red), _byte_clamp(green), _byte_clamp(blue))
                )
                input_cursor += 1
                a_cursor += 1
                b_cursor += 1

        return tuple(output)


@lru_cache(maxsize=2)
def decoder_for_profile(profile: str) -> CompositeSignalDecoder:
    if profile == COMPOSITE_PROFILE_OLD:
        return CompositeSignalDecoder(new_cga=False)
    if profile == COMPOSITE_PROFILE_NEW:
        return CompositeSignalDecoder(new_cga=True)
    raise ValueError(f"Unknown composite CGA profile: {profile!r}.")


def decode_mode6_scanline(
    bits: Sequence[int],
    profile: str,
    *,
    border_bit: int = 0,
    phase_offset: int = 0,
) -> tuple[tuple[int, int, int], ...]:
    """Decode Mode-6 bits at one of the four CGA color-carrier phases.

    ``phase_offset`` is modeled by placing zero/white border samples before
    the resource and cropping them after signal decoding.  This preserves the
    reference decoder's transition kernel while shifting the first real bit to
    carrier phase 0, 1, 2, or 3.
    """

    if not bits:
        return ()
    if border_bit not in (0, 1) or any(bit not in (0, 1) for bit in bits):
        raise ValueError("Mode-6 composite input must contain only zero and one bits.")
    if phase_offset not in (0, 1, 2, 3):
        raise ValueError("Composite phase offset must be between 0 and 3.")
    original_width = len(bits)
    border_value = 15 if border_bit else 0
    shifted_width = original_width + phase_offset
    padded_width = max(4, (shifted_width + 3) & ~3)
    rgbi = [border_value] * phase_offset
    rgbi.extend(15 if bit else 0 for bit in bits)
    rgbi.extend([border_value] * (padded_width - shifted_width))
    decoded = decoder_for_profile(profile).decode_scanline(
        rgbi,
        border=border_value,
    )
    return decoded[phase_offset : phase_offset + original_width]


def render_composite_artifacts(
    bits: Sequence[int],
    width: int,
    height: int,
    profile: str,
    *,
    channels: int = 3,
    border_bit: int = 0,
    phase_offset: int = 0,
) -> RenderedRaster:
    """Render full-width signal-decoded composite output with edge artifacts."""

    if width <= 0 or height <= 0 or len(bits) != width * height:
        raise ValueError("Composite bit dimensions are inconsistent.")
    if channels not in (3, 4):
        raise ValueError("Composite signal rendering supports only RGB and RGBA pixels.")

    output = bytearray(width * height * channels)
    cursor = 0
    for y in range(height):
        row = bits[y * width : (y + 1) * width]
        for red, green, blue in decode_mode6_scanline(
            row,
            profile,
            border_bit=border_bit,
            phase_offset=phase_offset,
        ):
            output[cursor : cursor + 3] = bytes((red, green, blue))
            if channels == 4:
                output[cursor + 3] = 255
            cursor += channels
    return RenderedRaster(
        width,
        height,
        bytes(output),
        channels,
        "composite-artifact",
    )
