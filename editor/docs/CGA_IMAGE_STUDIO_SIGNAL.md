# CGA Image Studio artifact-preview provenance

Prince DAT Explorer 0.4.8 added a full-width, read-only Composite signal preview
alongside its original 160-column color-cell editor. The implementation is a
dependency-free port of the Reenigne/Jenner decoder used by:

- repository: `chjmartin2/cga-image-studio`
- source file: `cga_v165.py`
- pinned Git blob: `e8cf2bb074bcf707594bbb7d8070931bfb19715e`
- relevant source section: “Composite (NTSC artifact) palettes & simulation”

## What was ported

`composite_signal.py` retains the source engine's sampled 256-entry chroma
multiplexer, four intensity levels, Old/New CGA voltage models, IQ adjustment,
and per-scanline luma/chroma filters. Each Prince Mode-6 bit becomes RGBI black
or white before decoding. The output has one RGB sample per input bit rather
than one flat RGB value per group of four.

The application uses the source engine's two default presets:

| Explorer profile | CGA Image Studio branch | Hue | Saturation | Brightness | Contrast | Sharpness |
|---|---|---:|---:|---:|---:|---:|
| Old CGA | `new_cga=False` | 0° | 100% | 0 | 100% | 0 |
| New CGA | `new_cga=True` | 0° | 100% | 0 | 100% | 0 |

The decoder mode selector is `0b0_0001`, matching CGA Image Studio's 160×200
Composite workflow. Rows use a black border. v0.4.9 added phase offsets 0–3 by
decoding the corresponding number of leading border samples and cropping them;
phase zero remains the default for older sidecars.

Prince DAT Explorer 0.4.28 displays this full-width signal at the editor's
selected 1×–20× zoom. A viewport renderer materializes only the visible source
crop while keeping the complete scrollable canvas, grid, and hover overlays.
The active P0–P3 graphic-family slot is decoded at its intended phase; the
runtime animation control cycles enabled variants without blending them.

Prince DAT Explorer 0.4.23 also exposes the New-CGA decoder as **NTSC
Composite** in both comparison-window mode selectors. It remains separate from
the idealized **Composite** choice and resolves linked room artwork from the CGA
archive.

Prince DAT Explorer 0.4.24 adds the same **NTSC Composite** choice to the main
Display selector. Main preview, PNG export, Extract All, hover reporting, and
linked-room source routing all use the full-width signal output.

Prince DAT Explorer 0.4.28 lets deterministic callers constrain each source
pixel to a nonempty subset of representable two-bit CGA codes during exhaustive
search. The row dynamic program enforces the completed two-bit pair while it
searches, so the result remains exact within the DAT palette's legal patterns;
it does not repair an illegal result after optimization.

## Why it differs from the rough editor

The rough editor groups bits as:

```text
cell = (bit0 << 3) | (bit1 << 2) | (bit2 << 1) | bit3
```

and looks up one editable RGB swatch. That flat view is useful for choosing and
painting patterns, but it cannot show boundaries. The signal decoder instead
uses pixels on both sides of a transition. It therefore exposes colors and
brightness changes inside a nominal cell, including leftward/rightward bleed
and ringing.

Custom RGB/HEX swatches affect only the rough view. The artifact pane is a
simulation of the bits themselves, so allowing swatch edits to recolor it would
make it less accurate.

## Scope and limits

The pane reproduces CGA Image Studio's decoder behavior, not a photographed
monitor. It does not model a particular television's bandwidth, comb filter,
CRT phosphors, scanlines, geometry, or user controls. A sprite's actual in-game
horizontal placement determines which independently prepared phase variant a
future draw hook must select. Version 0.4.28 supplies an exact audited contract
for recognized original 1.3 archives and leaves custom/modified executables in
Manual mode; see `ORIGINAL_ENGINE_PHASE_AUDIT.md` and
`PHASE_AWARE_GRAPHICS.md`.
