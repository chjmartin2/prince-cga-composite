# Phase-aware graphics and runtime interchange

Prince DAT Explorer 0.4.27 separates the artwork-authoring problem from the
eventual DOS executable patch. The editor can prepare and validate up to four
independent Composite variants for one original resource now, without assuming
where a future pointer table or added resource bank will live.

## Four physical phases, two original-engine alignments

NTSC artifact hue repeats every four 640-column Mode-6 signal samples. A local
bitstream optimized at phase 0 can therefore produce different colors when its
first visible sample lands at screen phase 1, 2, or 3.

The unmodified game does not place images at individual signal samples. Every
destination and crop boundary is an integral 320-column CGA pixel, equal to two
640-column samples. With a P0-normalized screen origin, original draws can
therefore reach only P0 and P2. P1/P3 remain available for an odd calibrated
screen bias or future sample-granular executable patch; they are not required
by the audited original coordinate paths.

The runtime phase for a draw is:

```text
phase = (global_phase_bias + destination_640_x - cropped_source_640_x) & 3
```

- `global_phase_bias` calibrates the emulator/card's screen origin.
- `destination_640_x` is the first visible destination signal sample.
- `cropped_source_640_x` is the first visible sample skipped from the graphic's
  left edge. It is zero for an unclipped draw.
- Both X values are in 640-column signal units. A one-pixel change in the
  ordinary 320-column coordinate system changes either value by two.

The subtraction is important for left clipping: the remaining bits keep the
phase they would have had inside the full source image.

## Automatic and manual coverage policies

For a recognized original 1.3 archive/resource, the editor defaults to
**Original DOS 1.3 engine (automatic)**. Its audited record enables exactly the
placements that occur:

- P0 for room artwork, title/story art, and fixed even-X cinematic art;
- P2 for potion bubbles and fixed odd-X cinematic art;
- P0+P2 for moving actors/swords and the flame frames shared between gameplay
  and princess-room cinematics;
- one P0 compatibility slot for a record proven unused.

Automatic coverage is locked, but its required variants remain independently
editable. The converter's single-phase choices are restricted to those audited
slots. **All** is available in every conversion model and scores one shared
pattern against exactly those audited slots—never automatically against four.
The phase bar shows the final-X evidence for the selected resource.
See `ORIGINAL_ENGINE_PHASE_AUDIT.md` for the complete 31-tile and cinematic
inventory.

**Manual / custom executable** exposes all coverage controls. Use it when the
DAT is renamed beyond a recognized family, the game executable changes a draw
contract, or calibrated hardware requires the P1/P3 parity pair.

The sidecar always has four addressable slots, P0 through P3, but a graphic
family enables only the alignments its draw path promises to use.

| Editor profile | Enabled slots | Recommended use |
|---|---|---|
| Fixed phase | one selected slot | Screen-aligned backgrounds, UI, fixed cinematic images |
| X parity: P0 + P2 | P0, P2 | First sprite pass when X moves in 320-column pixels |
| X parity: P1 + P3 | P1, P3 | The opposite two-sample origin parity |
| All four phases | P0, P1, P2, P3 | Sample-granular placement, mixed origins, or unrestricted clipping |
| Custom phases | any nonempty subset | A measured draw contract that does not match the presets |

These profiles describe Manual mode. P0+P2 is exact for the original integral
320-column placement paths, not merely a heuristic. A modified draw routine
must be re-audited; if it can place or crop at an odd 640-sample coordinate,
enable the corresponding P1/P3 slots or all four.

## Graphic-family state

Each schema-v6 `.pdcproj` edit stores:

- any stored P0–P3 Mode-6 bitstreams;
- the nonempty set of variants enabled for runtime use;
- the active slot shown by the editor and modified by painting/import;
- an enabled fallback slot for ordinary patched-DAT output;
- the original C-target source-index-zero mask and exact Mode-6 reference bits;
- whether that mask is currently locked and whether it was deliberately
  authored by direct Mode-6 transparency painting or a transparency-aware GIF
  import;
- the automatic-original-engine or manual coverage policy.

The legacy public `bits` member remains an alias of the active variant inside
the implementation. Switching P0–P3 changes that alias; it does not copy or
modify another slot.

Older v1–v3 sidecars load as one fixed variant at their saved preview phase.
Their mask begins unlocked so an old intentional index-zero edit is not changed
silently. Schema-v4 phase families retain all of their variants and coverage.
Every v1–v4 edit migrates to Manual: the new audit never silently adds, removes,
or replaces prior artwork. Opening an old image attaches mask/reference
metadata from the verified source DAT, after which the designer can opt into
locking it or explicitly select the automatic policy.

## Independent generation versus carrier phase all

These are deliberately different operations:

- **Generate enabled phase set** runs Exhaustive once for each enabled slot.
  P0 is optimized and decoded only at phase 0, P2 only at phase 2, and so on.
  Each run starts from the same selected VGA/EGA/CGA target and produces an
  independent bitstream. No target, decoded color, or error is averaged across
  slots. The complete set is validated and committed as one undo action.
- Carrier phase **all** in Simply Palette, Simulated NTSC, or Exhaustive
  searches for one bitstream whose total error is lowest across only the
  enabled runtime phases. For example, fixed room art scores P0 alone and a
  moving actor scores P0+P2. Each participating phase retains its own decoded
  color and, where applicable, dither target; nothing is averaged. **All** is a
  universal-compromise operation, not phase-set generation. Convert stores its
  one result in the currently active slot.

When the target mask is locked, the converter receives the C archive's exact
reference value for every protected Mode-6 bit. `-1` denotes an optimizable
position; `0` or `1` is a hard constraint in the row dynamic program. The
selected VGA/EGA source's index-zero shape cannot override this target contract.

## Designer workflow

1. Select the resource in the C-target editor and inspect the placement-audit
   line.
2. Keep the automatic policy for the original engine. For a patched/custom
   path, switch to Manual and choose Fixed, P0+P2, P1+P3, All four, or Custom.
3. Keep source index-zero locking enabled for sprites/masked overlays.
4. Open Convert, select the intended VGA/EGA/CGA reference, choose Exhaustive,
   and configure adjustment/dither controls.
5. Click **Generate enabled phase set**. Do not use phase **all** when the goal
   is independent variants.
6. Switch among **Edit variant** P0–P3 for detailed retouching. Painting and
   individual GIF import affect only the active slot.
7. Use **Animate runtime phase switching** to look for color or silhouette
   discontinuities across intended placements.
8. Export an exact GIF set for external pixel editing when useful, then import
   the complete set atomically.
9. Choose a representative **DAT fallback** for testing without the EXE hook.
10. Press `Ctrl+S` or choose **Project → Save phase-aware sidecar (.pdcproj)**.
    This saves every edited image and every stored phase slot, not only the
    image/phase currently displayed. Export the runtime manifest for the
    code-side packer.

## Saving and reopening the complete phase project

The `.pdcproj` sidecar is the recoverable authoring file. One save contains all
edited resource records, all stored P0–P3 bitstreams (including stored slots
not currently enabled), runtime coverage, the active editing slot, the explicit
legacy-DAT fallback, mask/reference state, and both Composite palettes.

Use this sequence:

1. Press `Ctrl+S` or choose **Project → Save phase-aware sidecar (.pdcproj)**.
2. Choose a `.pdcproj` filename beside the source DAT or in another backed-up
   project folder.
3. Confirm the status bar reports the expected image, stored-variant, and
   enabled-variant counts.
4. To resume, open the unchanged original DAT, open the Composite editor, and
   choose **Project → Open phase-aware sidecar…**. The saved source identity is
   verified before any edit is attached.

**Save patched DAT…** is not a substitute for this sidecar. A legacy image
resource has only one payload, so that command writes the selected fallback
variant for each edited family. **Export phase-aware runtime manifest…** is the
lossless interchange for a game-side packer and contains every enabled variant.

## Fixed-palette GIF-set contract

An enabled Mode-6 set uses names containing `_P0_` through `_P3_` and
`_mode6.gif`; a rough Composite set uses `_composite.gif`. Import requires
exactly one file for every enabled phase and rejects a mixed set.

The normal strict GIF rules still apply: native dimensions, one indexed frame,
one global palette, and exact ordered palette entries. Mode-6 exports use
opaque black at index 0, opaque white at index 1, transparent magenta at index
2, and reserved cyan at index 3. Index 2 authors source-pixel transparency;
both Mode-6 samples of a 4-bit source pixel must agree. Legacy opaque two-color
sets remain accepted and preserve the existing mask. Rough Composite sets are
still opaque. The editor reads indices directly; it never quantizes rendered
RGB. Every candidate also passes mask and inverse-CGA representability checks
before any slot changes.

## Runtime manifest

**Export phase-aware runtime manifest** writes JSON with kind
`prince-dat-phase-aware-manifest`, currently version 3. It is an interchange
format, not a mandated final DOS storage layout.

Top-level fields record the verified source DAT identity, selected Composite
profile, phase period, global bias, selector formula, packing order, and
missing-phase fallback policy. Each resource family records:

- original resource index and ID;
- source width, height, depth, and Mode-6 width;
- enabled slots, profile, policy, fallback slot, and mask status;
- the original-engine audit ID, used/unused state, normalized required phases,
  category, summary, placement formula, and source evidence when known;
- the packed source-zero mask, exact mask-reference Mode-6 bits, and their
  SHA-256 hashes;
- one entry for every enabled phase.

Each variant entry contains three lossless representations:

1. `packed_bits_base64`: row-major Mode-6 bits, MSB first within each byte;
2. `source_pixels_base64`: one deterministic inverse-mapped Prince palette
   index per source pixel, row major;
3. `lzg_resource_base64`: a complete B3/B4 Prince image resource, including
   its six-byte image header but excluding the DAT checksum byte.

Counts, byte sizes, and SHA-256 hashes accompany those payloads. A packer can
therefore choose to store packed bits, unpacked source indices, or already
encoded image resources. The original resource format has only one payload, so
**Save patched DAT** writes the chosen fallback slot and cannot replace the
manifest/EXE integration.

## Suggested draw-hook behavior

For each patched graphic family:

1. Calculate the phase with the formula above after final clipping is known.
2. Look up that exact enabled variant.
3. If the slot is absent, use `fallback_phase` for safe compatibility and log
   or count the miss during development. A shipping phase-aware path should
   normally have zero misses.
4. Draw with the original width, height, transparency, and clipping semantics.

The original renderer horizontally flips moving sword, Kid, cinematic-actor,
and guard banks at runtime. Facing is independent of carrier placement: a
P0/P2 bank does not make an optimized waveform invariant under reversal. If
both facings must reproduce exactly the same intended colors, extend the final
runtime key to `(phase, facing)` or store preflipped direction variants. The
v0.4.27 audit deliberately reports phase requirements without claiming to have
solved that separate transform.

The editor intentionally does not prescribe added DAT IDs, segment placement,
pointer-table width, decompression lifetime, or cache strategy. Those choices
depend on the final reverse-engineered draw path; the sidecar and manifest keep
the artwork recoverable while that implementation evolves.
