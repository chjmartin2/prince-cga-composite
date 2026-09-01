# Chomper Blood Stencils

## Engine path

Prince does not draw the chomper blood as ordinary indexed artwork. In the
original `draw_tile_anim()` and `draw_tile_fore()` paths, it selects image
numbers `114-118` and `119-123` from the dungeon environment character table.
Those map to `CDUNGEON.DAT` resources 1314-1323.

Each resource is a native one-bit image. `draw_image()` recognizes blitter
value `0x4C` as a mono draw and calls the graphics driver's mono-image routine
with color 12. The New-CGA Mode-6 implementation expands color 12 to the
repeating screen-bit pattern `1100`. The image's zero bits remain transparent;
its one bits select where that pattern is painted.

The final horizontal placement is:

```text
8 * (draw_xh + 1) + 4 = 32 * tile_column + 12
```

It therefore always starts at P0 and needs no runtime phase variants.

## Defect

The work-in-progress composite conversion optimized the native one-bit
resources as though their bits directly described artifact colors. That is not
their runtime meaning. It reduced the ten masks from 498 set bits to 223,
discarding 275 positions that the mono blitter was supposed to paint.

| Resource | Size | Converted set bits | Original set bits |
| --- | ---: | ---: | ---: |
| 1314 | 6x29 | 61 | 134 |
| 1315 | 6x25 | 50 | 111 |
| 1316 | 6x18 | 33 | 75 |
| 1317 | 6x9 | 13 | 30 |
| 1318 | 4x5 | 5 | 11 |
| 1319 | 2x29 | 24 | 51 |
| 1320 | 2x25 | 18 | 39 |
| 1321 | 2x18 | 11 | 26 |
| 1322 | 2x9 | 6 | 14 |
| 1323 | 2x5 | 2 | 7 |

## V20Y repair

V20Y restores the complete resource contents for 1314-1323 byte-for-byte from
the hash-verified original `CDUNGEON.DAT`. It does not alter the color argument,
the mono renderer, the phase tables, or any other resource. Static verification
proves the following:

- the ten decoded one-bit masks equal the originals;
- all 498 original set bits are present;
- DAT resource order and checksums remain valid;
- every other CDUNGEON resource is byte-identical to V20X;
- all other DAT archives and executable runtime code are byte-identical to
  V20X.

DOSBox showed that restoring the masks alone was insufficient: a little yellow
appeared on the floor, but the blade remained grey.

## Active mono-pattern analysis and V20Z

The active `gmCga` mono renderer does not send the nominal RGBI color directly
to Mode 6. Its fixed four-row table maps color 12 to `AA AA AA AA`. Repeating
`10101010` is neutral grey in New-CGA composite, while transitions against the
floor can ring yellow. This exactly matches the V20Y DOSBox result.

`runtime/analyze_chomper_blood.py` overlays every candidate byte on the masks
where the engine actually uses them:

- resources 1314-1318 are the 6-pixel rear/floor masks over bottom-blade
  resources 1301-1305;
- resources 1319-1323 are the 2-pixel foreground masks over front-blade
  resources 1306-1310;
- every mask uses X `32*column+12`; all five frames and all three tile rows are
  evaluated with the New-CGA NTSC signal decoder.

Of all 256 byte patterns, `C4` (`11000100`) gives the best balanced red for the
two very different backgrounds. Its `1100` prefix colors the narrow blade,
while the trailing `0100` darkens the wider spill over the rear/floor. Predicted
in-use means are RGB `(146,65,78)` on the foreground blade and `(181,56,51)` on
the rear/floor pass.

V20Z changes the four color-12 scanline bytes to `C4 C4 C4 C4`. It preserves
the restored masks and all DAT archives. Because red potion bubbles also ask
the mono renderer for color 12, they inherit the corrected red pattern. DOSBox
visual confirmation remains required.
