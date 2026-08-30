#!/usr/bin/env python3
"""Render deterministic contact sheets and phase-toggle GIFs for V13."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "engine"))

from make_four_way_kid import (  # noqa: E402
    MIRRORED_EVEN_ALIAS_BASE,
    MIRRORED_ODD_ALIAS_BASE,
    PRIVATE_RESOURCE_BASE,
    SOURCE_DISPLAY_MODE,
    STORED_ODD_ALIAS_BASE,
    runtime_display_bits,
    selected_image_ordinal,
)
from composite_project import initial_mode6_bits  # noqa: E402
from composite_signal import render_composite_artifacts  # noqa: E402
from prince_dat import (  # noqa: E402
    COMPOSITE_PROFILE_NEW,
    DatArchive,
    hardware_palette_for_resource,
    mode6_width,
    render_display_mode,
)


BACKGROUND = (19, 21, 25)
CARD = (31, 35, 42)
PANEL = (0, 0, 0)
TEXT = (238, 241, 246)
MUTED = (159, 170, 184)
ACCENT = (92, 190, 255)
GRID = (66, 74, 86)

GROUPS = (
    ("RUN-STAND", tuple(range(0, 15)), "Frames 1-15: start, run, and stand"),
    ("TURN", tuple(range(44, 52)), "Frames 45-52: standing turn"),
    ("RUN-TURN", tuple(range(64, 77)), "Frames 53-65: running turn"),
)


def font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def pil_raster(raster: object) -> Image.Image:
    channels = int(getattr(raster, "channels"))
    mode = "RGB" if channels == 3 else "RGBA"
    return Image.frombytes(
        mode,
        (int(getattr(raster, "width")), int(getattr(raster, "height"))),
        bytes(getattr(raster, "pixels")),
    ).convert("RGB")


def private_resource_id(alias_base: int, image_id: int) -> int:
    return PRIVATE_RESOURCE_BASE + 1 + alias_base + selected_image_ordinal(image_id)


def target_image(source: DatArchive, image_id: int, direction: str) -> Image.Image:
    analysis = source.analysis_by_id(401 + image_id)
    if analysis is None or analysis.image is None:
        raise ValueError(f"source Kid image {401 + image_id} does not decode")
    hardware = hardware_palette_for_resource(source, analysis.resource)
    image = pil_raster(
        render_display_mode(analysis.image, SOURCE_DISPLAY_MODE, hardware)
    )
    if direction == "right":
        image = image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return image.resize(
        (mode6_width(analysis.image), analysis.image.height),
        Image.Resampling.NEAREST,
    )


def variant_image(
    candidate: DatArchive,
    image_id: int,
    direction: str,
    phase: int,
) -> Image.Image:
    if direction == "right" and phase == 0:
        resource_id = 401 + image_id
    else:
        aliases = {
            ("right", 2): STORED_ODD_ALIAS_BASE,
            ("left", 0): MIRRORED_EVEN_ALIAS_BASE,
            ("left", 2): MIRRORED_ODD_ALIAS_BASE,
        }
        resource_id = private_resource_id(aliases[(direction, phase)], image_id)
    analysis = candidate.analysis_by_id(resource_id)
    if analysis is None or analysis.image is None:
        raise ValueError(f"variant Kid image {resource_id} does not decode")
    hardware = hardware_palette_for_resource(candidate, analysis.resource)
    stored = bytes(initial_mode6_bits(analysis.image, hardware))
    displayed = runtime_display_bits(
        stored,
        mode6_width(analysis.image),
        analysis.image.height,
        direction,
    )
    return pil_raster(
        render_composite_artifacts(
            displayed,
            mode6_width(analysis.image),
            analysis.image.height,
            COMPOSITE_PROFILE_NEW,
            phase_offset=phase,
        )
    )


def draw_centered(
    canvas: Image.Image,
    sprite: Image.Image,
    box: tuple[int, int, int, int],
    scale: int,
) -> None:
    scaled = sprite.resize(
        (sprite.width * scale, sprite.height * scale),
        Image.Resampling.NEAREST,
    )
    left, top, right, bottom = box
    x = left + (right - left - scaled.width) // 2
    y = top + (bottom - top - scaled.height) // 2
    canvas.paste(scaled, (x, y))


def contact_sheet(
    source: DatArchive,
    candidate: DatArchive,
    image_ids: tuple[int, ...],
    title: str,
    subtitle: str,
    destination: Path,
) -> None:
    scale = 3
    max_width = max(target_image(source, image_id, "left").width for image_id in image_ids)
    max_height = max(target_image(source, image_id, "left").height for image_id in image_ids)
    panel_width = max_width * scale + 16
    panel_height = max_height * scale + 12
    label_width = 28
    card_width = label_width + panel_width * 3 + 12
    card_height = 31 + (18 + panel_height) * 2 + 12
    columns = 3
    rows = (len(image_ids) + columns - 1) // columns
    header_height = 72
    margin = 16
    sheet = Image.new(
        "RGB",
        (
            margin * 2 + columns * card_width + (columns - 1) * 12,
            header_height + margin + rows * card_height + (rows - 1) * 12 + margin,
        ),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 10), title, font=font(25, bold=True), fill=TEXT)
    draw.text((margin, 42), subtitle, font=font(14), fill=MUTED)

    for ordinal, image_id in enumerate(image_ids):
        column = ordinal % columns
        row = ordinal // columns
        left = margin + column * (card_width + 12)
        top = header_height + margin + row * (card_height + 12)
        draw.rounded_rectangle(
            (left, top, left + card_width - 1, top + card_height - 1),
            radius=7,
            fill=CARD,
            outline=GRID,
        )
        draw.text(
            (left + 10, top + 6),
            f"Image {image_id:03d}  /  KID resource {401 + image_id}",
            font=font(14, bold=True),
            fill=ACCENT,
        )
        for direction_index, direction in enumerate(("right", "left")):
            row_top = top + 31 + direction_index * (18 + panel_height)
            draw.text(
                (left + 5, row_top + 20),
                "R" if direction == "right" else "L",
                font=font(14, bold=True),
                fill=TEXT,
            )
            images = (
                target_image(source, image_id, direction),
                variant_image(candidate, image_id, direction, 0),
                variant_image(candidate, image_id, direction, 2),
            )
            for panel_index, (label, sprite) in enumerate(
                zip((f"{SOURCE_DISPLAY_MODE.upper()} target", "P0", "P2"), images)
            ):
                panel_left = left + label_width + panel_index * panel_width
                draw.text(
                    (panel_left + 5, row_top),
                    label,
                    font=font(12),
                    fill=MUTED,
                )
                box = (
                    panel_left,
                    row_top + 18,
                    panel_left + panel_width - 2,
                    row_top + 18 + panel_height,
                )
                draw.rectangle(box, fill=PANEL, outline=GRID)
                draw_centered(sheet, sprite, box, scale)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    sheet.save(temporary, format="PNG", optimize=True)
    with Image.open(temporary) as check:
        check.load()
    temporary.replace(destination)


def right_stand_focus(
    source: DatArchive,
    candidate: DatArchive,
    destination: Path,
) -> None:
    """Render the standing frame large enough to inspect hair carrier color."""

    image_id = 14
    scale = 10
    sprites = (
        ("VGA target", target_image(source, image_id, "right")),
        ("Corrected runtime P0", variant_image(candidate, image_id, "right", 0)),
        ("Corrected runtime P2", variant_image(candidate, image_id, "right", 2)),
    )
    panel_width = max(sprite.width for _label, sprite in sprites) * scale + 28
    panel_height = max(sprite.height for _label, sprite in sprites) * scale + 24
    margin = 18
    header = 82
    sheet = Image.new(
        "RGB",
        (margin * 2 + len(sprites) * panel_width, header + panel_height + margin),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (margin, 10),
        "Right-facing stand — corrected CGA-pixel reversal",
        font=font(25, bold=True),
        fill=TEXT,
    )
    draw.text(
        (margin, 44),
        "Prince reverses two-sample CGA pixels, not individual carrier bits.",
        font=font(14),
        fill=MUTED,
    )
    for index, (label, sprite) in enumerate(sprites):
        left = margin + index * panel_width
        draw.text((left + 5, header - 20), label, font=font(13), fill=ACCENT)
        box = (left, header, left + panel_width - 6, header + panel_height - 4)
        draw.rectangle(box, fill=PANEL, outline=GRID)
        draw_centered(sheet, sprite, box, scale)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    sheet.save(temporary, format="PNG", optimize=True)
    with Image.open(temporary) as check:
        check.load()
    temporary.replace(destination)


def phase_grid(
    candidate: DatArchive,
    image_ids: tuple[int, ...],
    direction: str,
    phase: int,
) -> Image.Image:
    scale = 3
    columns = 6
    rows = (len(image_ids) + columns - 1) // columns
    max_width = max(variant_image(candidate, image_id, direction, phase).width for image_id in image_ids)
    max_height = max(variant_image(candidate, image_id, direction, phase).height for image_id in image_ids)
    cell_width = max_width * scale + 14
    cell_height = max_height * scale + 28
    header = 50
    grid = Image.new(
        "RGB",
        (columns * cell_width + 16, header + rows * cell_height + 12),
        BACKGROUND,
    )
    draw = ImageDraw.Draw(grid)
    draw.text(
        (10, 8),
        f"{direction.upper()} runtime variants — P{phase}",
        font=font(23, bold=True),
        fill=TEXT,
    )
    for ordinal, image_id in enumerate(image_ids):
        column = ordinal % columns
        row = ordinal // columns
        left = 8 + column * cell_width
        top = header + row * cell_height
        box = (left, top + 20, left + cell_width - 4, top + cell_height - 4)
        draw.rectangle(box, fill=PANEL, outline=GRID)
        draw.text((left + 4, top + 2), f"{image_id:03d}", font=font(12), fill=MUTED)
        draw_centered(
            grid,
            variant_image(candidate, image_id, direction, phase),
            box,
            scale,
        )
    return grid


def phase_toggle_gif(
    candidate: DatArchive,
    image_ids: tuple[int, ...],
    direction: str,
    destination: Path,
) -> None:
    p0 = phase_grid(candidate, image_ids, direction, 0)
    p2 = phase_grid(candidate, image_ids, direction, 2)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    p0.save(
        temporary,
        format="GIF",
        save_all=True,
        append_images=[p2],
        duration=[900, 900],
        loop=0,
        optimize=False,
    )
    with Image.open(temporary) as check:
        check.seek(1)
        check.load()
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-kid", type=Path, required=True)
    parser.add_argument("--candidate-kid", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source = DatArchive.open(args.source_kid)
    candidate = DatArchive.open(args.candidate_kid)

    for slug, image_ids, description in GROUPS:
        contact_sheet(
            source,
            candidate,
            image_ids,
            f"Prince Exhaustive Phase Verification — {slug}",
            f"{description}. Each P0/P2 waveform is independently optimized; no dither.",
            args.output_dir / f"VISUAL-{slug}.png",
        )
    all_images = tuple(image_id for _slug, ids, _description in GROUPS for image_id in ids)
    for direction in ("right", "left"):
        phase_toggle_gif(
            candidate,
            all_images,
            direction,
            args.output_dir / f"VISUAL-{direction.upper()}-PHASE-TOGGLE.gif",
        )
    right_stand_focus(
        source,
        candidate,
        args.output_dir / "VISUAL-RIGHT-STAND-CORRECTED.png",
    )
    print(f"wrote visual verification assets: {args.output_dir}")


if __name__ == "__main__":
    main()
