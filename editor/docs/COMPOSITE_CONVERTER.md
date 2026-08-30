# Composite conversion models

Prince DAT Explorer 0.4.22 can rebuild the selected image's active Mode-6
bitstream from an explicitly selected VGA, EGA, or CGA rendering with **Simply
Palette**, **Simulated NTSC**, or **Exhaustive**. The selector changes both the
conversion objective and preview; it is not a cosmetic view switch over one
shared result.

## Simply Palette

This mode deliberately models the idealized 160×200 Composite editing view.
Four adjacent Mode-6 bits form one independent palette cell. A normal 320×200
source is expanded to the corresponding 640×200 bit geometry, then each group
of four samples—two ordinary source pixels—is box-averaged into one target
cell. Native one-bit resources keep their own signal width.

Each target cell is assigned the closest of the selected profile's fixed 16
Old/New CGA colors. Carrier phase rotates the four-clock pattern through that
fixed lookup without adding neighbor bleed. The distance is ordinary
unweighted squared RGB distance:

```text
distance = (Rpalette - Rtarget)^2
         + (Gpalette - Gtarget)^2
         + (Bpalette - Btarget)^2
```

The exact average is used when selecting a color, with no integer-rounding
bias. Equal-distance candidates select the lower four-bit pattern, making the
result deterministic. Adjacent cells are never decoded together, so there is
no edge bleed, ringing, phase shift, or neighbor-dependent color.

Brightness, contrast, saturation, gamma, all dithering controls, color
emphasis, detail preservation, and search quality are disabled and absent from
this quantization path. Their stored dialog values therefore cannot influence
the output. Carrier phase remains active: P0–P3 optimizes the rotated lookup at
that alignment. **All** sums the separate squared RGB costs for only the
resource's enabled runtime phases and chooses one shared pattern; it never
averages palette colors or target colors. **Preserve source index-zero
background** remains available as an optional hard constraint: bits
corresponding to source index zero must remain zero, and the closest legal
pattern is selected from the remaining candidates.

The preview is the resulting fixed-palette cell raster at its natural
160-style width. It always uses the selected Old/New CGA profile's default
table rather than custom rough-editor swatches. **All** displays only the
enabled phase panels in ascending row-major order. This keeps conversion
results stable and makes the palette being optimized explicit.

## Simulated NTSC

This is the artifact-aware conversion introduced in earlier releases. For the
usual 320×200 four-bit Prince image, the destination is 640×200 bits and the
objective is the 640×200 RGB raster produced by the same Reenigne/Jenner
decoder used in the editor's Composite-signal pane. A 320-wide source pixel is
replicated across two signal samples before adjustment and optimization.

Every candidate is judged after composite decoding. Edge bleed, ringing,
luminance transitions, and neighboring-bit chroma all contribute to the score.
The flat 16-color rough-editing palette is not used by this search.

### Neighborhood model

One decoded output sample depends on twelve input bits, from `x - 5` through
`x + 6`. The converter precomputes the exact decoder result for all 4,096
twelve-bit windows at each of the four sample phases. A per-scanline beam search
then carries the last eleven bits as its state. Adding a trial bit completes a
window and scores one real decoded output pixel.

The test suite compares this table with full scanline decoding at the left
edge, interior, and right edge. Search quality changes the retained beam width;
it never changes the signal model or falls back to rough-cell RGB.

### Dithering and adjustments

- **None** leaves the adjusted 640-column objective unchanged.
- **Floyd–Steinberg** diffuses cell-average RGB error with the normal 7/16,
  3/16, 5/16, and 1/16 weights. Amount scales propagated error from zero to
  full strength. Serpentine mode reverses alternate rows.
- **Bayer** applies an ordered luminance displacement using a 2×2, 4×4, or 8×8
  matrix. Amount scales that displacement.

Brightness, contrast, saturation, and gamma are applied before resampling.
Color emphasis blends a luma-only distance with RGB distance. Detail
preservation raises score weight near horizontal or vertical luma edges.
Source-index-zero preservation constrains corresponding destination bits to
zero.

Carrier phase 0–3 changes both optimization and the simulated preview. A normal
Convert stores the result in that independent phase-family slot, creating and
enabling it when needed. Phase is not a field in the original Prince image;
actual in-game placement chooses which prepared slot the future draw hook must
use.

**All** is also available to Simulated NTSC. The beam search decodes every
candidate independently at each enabled runtime phase, applies the same color
emphasis and detail weighting to each comparison, and adds those costs. It does
not include disabled phases. Floyd–Steinberg creates a separate dithered target
for each participating phase because its nominal quantization error is
phase-dependent; those targets and decoded colors are never averaged. None,
Bayer, all input adjustments, and all three beam-quality levels work normally.

## Exhaustive

Exhaustive retains the complete 2,048-state decoder history at every bit
position. Because one decoded pixel depends only on the twelve input bits from
`x - 5` through `x + 6`, two partial rows with the same last eleven bits have
identical possible futures. The dynamic program merges only those equivalent
histories and never prunes a distinct state. It therefore produces the true
minimum-error row over all `2^width` possible bit patterns without literally
enumerating them.

The target is the full Mode-6 signal geometry. A normal 320×200 VGA, EGA, or
CGA source is scaled to 640×200 by exact two-sample horizontal replication;
there is no interpolation. Every resulting one-bit signal pixel is a separate
decision. Five black samples to the left and six to the right supply the same
isolated-resource boundary used by the signal preview.

### Selected-phase objective

For every candidate twelve-bit window, Exhaustive decodes the selected CGA
carrier offset and uses ordinary, unweighted RGB squared error:

```text
cost = (Rdecoded - Rtarget)^2
     + (Gdecoded - Gtarget)^2
     + (Bdecoded - Btarget)^2
```

Color emphasis, edge/detail weighting, and beam quality are disabled. Carrier
phase remains active because it defines both the exact bit objective and the
decoded preview. Changing phase reruns the row optimizer. This avoids the
chroma cancellation caused by averaging the four hue rotations and keeps
representable solid EGA colors spatially stable.

### All-phase objective

Exhaustive also provides **all**. The chosen Mode-6 row is still one shared bit
pattern, but every candidate window is decoded once for each phase enabled by
the current resource's audited or manual coverage. Its score is the total
absolute component error against that reachable set:

```text
cost = sum for phase p in enabled runtime phases of
       |Rdecoded,p - Rtarget,p|
     + |Gdecoded,p - Gtarget,p|
     + |Bdecoded,p - Btarget,p|
```

The decoded colors are never averaged into one color, and the targets are never
averaged into one target. With None or Bayer dithering the same adjusted source
target is compared independently at each participating phase. With error
diffusion, each phase can have a different target because its incoming residual
is retained separately. The exact row DP sums these phase-local costs across
the line and therefore finds the bit row with the lowest total absolute error
over every output pixel and every potentially used phase. A P0-only resource
therefore scores only P0; a moving P0+P2 resource scores exactly those two; a
manual four-phase resource scores P0–P3.

This objective does not claim that all phase rotations can reproduce the same
hue. It deliberately searches for the closest phase-independent compromise so
its limitations can be inspected directly.

### Exhaustive dithering

- **None** solves the adjusted replicated target directly.
- **Bayer** applies the selected 2×2, 4×4, or 8×8 luminance displacement to
  every individual signal target pixel before any row optimization.
- **Error diffusion** first solves the complete current row. Its RGB residual,
  measured against the decoded result, is then sent only into the following
  row: 8/16 down-forward, 5/16 directly down, and 3/16 down-backward. There is
  no horizontal propagation within the current row. Serpentine mode mirrors
  forward and backward on alternate rows. Incoming RGB error is added to the
  following row and clamped to 0–255 before that row is optimized. A selected
  phase uses one buffer. **All** uses one independent buffer per enabled
  runtime phase—one residual and adjusted next-row target per phase—and never
  combines them.

Dither Amount scales Bayer displacement or propagated residual. Brightness,
contrast, saturation, and gamma are applied before the 2× target expansion.
Preserve source index-zero background remains an optional hard bit constraint.
When the editor's target mask lock is active, its exact Mode-6 reference values
replace the selected source image's zero mask as the stronger constraint.

## Preview zoom

The single preview pane follows the selected conversion model and offers
integer zoom levels from 1× through 20×. At 20×, its canvas remains logically
the full image while only the visible source-pixel rectangle plus a one-pixel
margin becomes a Tk image. This preserves exact nearest-neighbor samples
without allocating an enormous full-frame bitmap.

**Converted** shows the current conversion result. **Current edit** renders the
existing Mode-6 bits through the selected model: independent fixed cells for
Simply Palette or the full signal decoder for Simulated NTSC and Exhaustive.
For **all** in any model, both choices show only the enabled phases in ascending
row-major order. One phase uses one panel, two use one row, and three or four
use two rows. Every panel pixel is copied directly from that phase's normal
fixed-palette or signal-decoder output; nothing is blended.

## Commit and safety

The dialog converts original adapter references, not a feedback copy of the
current edit. Before commit, the result passes through the same inverse CGA
translation used by patched-DAT Save-As. An unrepresentable result is rejected
without touching the edit.

A successful Convert replaces one phase-family bitstream as one undoable
action. A P0–P3 selection in any model targets that selected phase. **All** in
any model stores its one reachable-phase universal compromise in the currently
active slot. **Generate enabled phase set** runs Exhaustive once per enabled
runtime phase, validates all results first, and commits the independent set as
one undo action. The source DAT remains unchanged until the normal verified
Save-As workflow is used; that legacy DAT contains only the family's explicit
fallback phase. See `PHASE_AWARE_GRAPHICS.md` for the runtime contract.
