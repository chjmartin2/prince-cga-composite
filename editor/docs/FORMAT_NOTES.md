# POP1 DAT, hardware tables, and composite write-back

This note records the format decisions used by Prince DAT Explorer 0.4.22. All
multi-byte integers are little-endian.

## Archive structure

```text
offset  size  meaning
0       4     resource-index offset
4       2     resource-index size
6       ...   resource storage area
index   2     resource count
index+2 8*n   records: uint16 ID, uint32 offset, uint16 content size
```

At each record offset, a checksum byte precedes `content size` bytes. A resource
is valid when:

```text
(1 + stored_checksum + sum(content_bytes)) mod 256 == 0
```

The reader reports bad checksums without hiding otherwise addressable resources.
It rejects invalid indexes and out-of-range resource records before decoding.

## Image resource header and codecs

The checksum is outside the resource content. Image content starts with:

```text
offset  size  meaning
0       2     height
2       2     width
4       1     marker (observed 0 or 1)
5       1     type byte
6       ...   encoded packed pixels
```

Pixel depth is `(((type >> 4) & 7) + 1)`, yielding the observed `0x0?` one-bit,
`0xB?` four-bit, and `0xF?` eight-bit families. The low nibble selects:

| Value | Form |
|---:|---|
| 0 | RAW, row-major |
| 1 | RLE, row-major |
| 2 | RLE, top-to-bottom packed-byte order |
| 3 | LZG, row-major |
| 4 | LZG, top-to-bottom packed-byte order |

Four-bit pixels use the high nibble first. One-bit pixels use the most
significant bit first. Rows are padded to complete bytes.

### RLE

Interpret each control byte as signed. A negative value repeats the following
byte `-control` times. A non-negative value copies the following `control + 1`
bytes literally.

### LZG

LZG starts with a zero-filled 1,024-byte history. Mask bits are consumed least
significant first. A set bit copies a literal. A clear bit reads `first, second`:

```text
encoded_location = 66 + ((first & 3) << 8) + second
length           = 3 + (first >> 2)
distance         = (output_cursor - encoded_location) & 0x3ff
distance 0 becomes 0x400
```

Overlapping copies are allowed. For codec 2 or 4, sequential decoded packed
byte `i` is moved to `(i % height) * packed_row_width + i // height` before
individual pixels are unpacked.

## The 100-byte palette/hardware record

The record begins with the containing SHPL image count, then `dat_pal_type`:

```text
offset  size  meaning
0       1     image count
1       2     row_bits
3       1     color count (16)
4       48    16 VGA RGB triplets, six bits per component
52      16    packed CGA translation
68      32    packed EGA translation
```

Six-bit VGA components are expanded with `(v << 2) | (v >> 4)`.

The CGA and EGA regions are translation tables, not RGB palettes. Each expands
to four groups of 16 source-index mappings. Group selection follows a 2×2 pixel
phase:

```text
phase = ((y & 1) << 1) | (x & 1)
group 0 = even row, even column
group 1 = even row, odd column
group 2 = odd row,  even column
group 3 = odd row,  odd column
```

For source index `s` from 0 through 15:

```text
CGA byte  = raw_cga[phase * 4 + s // 4]
CGA shift = 6 - 2 * (s & 3)
CGA value = (CGA byte >> CGA shift) & 3

EGA byte  = raw_ega[phase * 8 + s // 2]
EGA value = high nibble when s is even, low nibble when s is odd
```

This ordering matches the original DOS conversion routines: two packed-byte
lookup tables use groups 0/1 for even rows and 2/3 for odd rows. Some shipped
records repeat all four groups; others, including title and palette-animation
records, contain genuinely different phase mappings.

VGA displays the source index through embedded RGB. EGA displays the translated
nibble through IBM RGBI. CGA displays the translated two-bit value through the
selected four-color hardware palette.

## 640×200 and composite interpretation

For ordinary four-bit resources, the CGA table is applied before digital
reinterpretation:

```text
translated CGA value  640×200 bits
0                     00
1                     01
2                     10
3                     11
```

The high bit is leftmost, so source width `w` becomes `2w` bits. Native one-bit
resources already contain the digital stream and keep their width.

Composite groups four adjacent digital bits, leftmost first:

```text
cell = (bit0 << 3) | (bit1 << 2) | (bit2 << 1) | bit3
```

Its width is `ceil(bit_width / 4)`. A 320-pixel four-bit row therefore becomes
640 digital pixels or 160 composite cells. Every GUI preview displays the
former with half-width pixels and the latter with double-width cells, giving
both the same apparent width as the 320-pixel VGA/EGA/CGA references. This
display normalization does not change raster data or PNG/GIF export dimensions.

The 16 cell values address editable RGB swatches. Two profiles are derived from
the steady repeating-pattern output of DOSBox-X: `machine=cga_composite`
(Old/early CGA) and `machine=cga_composite2` (New/late CGA), both at mode
control `1Ah`, foreground `F`, and default hue. The fixed tables and exact pinned
source are documented in `DOSBOXX_COMPOSITE_PALETTE.md`. Changing profiles
changes only the RGB interpretation; the 4-bit patterns and 640-bit project
stream remain identical. The non-overlapping cell renderer does not reproduce
DOSBox-X's neighboring-bit transition colors.

## Inverting an edit

The project stores the digital bitstream as its editable source of truth. To
write a four-bit image, each bit pair supplies the requested CGA value. The
writer selects source-index candidates from the appropriate phase group whose
CGA translation equals that value.

Selection is deterministic:

1. retain the original source index if it still translates to the requested
   value;
2. otherwise minimize squared RGB distance from the original embedded VGA
   color;
3. break a remaining tie by the lower source index.

If a phase group cannot represent the requested two-bit value, save stops with
the exact source coordinate. One-bit images require no inverse translation.

The six-pane editor runs this same inverse selection after every stroke in
either editable representation. For a shared archive, the predicted source
indices are rendered through
the VGA, EGA, and CGA paths immediately; therefore the live previews and the
eventual RAW replacement use the same decision, including RGB-distance and
tie-breaking rules. For linked room sets, only the C archive uses this predicted
image because V and E are independent files.

Each of the six panes independently selects Original or Edited. Original
adapter views render the untouched decoded source image. Edited shared-adapter
views render the predicted source-index image above. Original mode-6 and
Composite views are regenerated from the untouched source through the embedded
CGA table, while their Edited views render the project's bitstream. Both
Composite views use the current project swatches so switching isolates changes
to bit patterns rather than palette changes. Selecting Original never mutates or
discards the saved edit state; the Original Composite view is intentionally
read-only to prevent invisible strokes.

The Mode-6 and rough Composite panes are two coordinate systems over the same
`CompositeEdit.bits` array. Mode-6 painting changes one bit directly. Rough
Composite painting changes either all four bits of a color cell or one selected
sub-bit. Both routes create the same offset-based undo records, mark the same
project dirty flag, and enter the same write-back path.

### Indexed GIF interchange

Each pane exports its selected Original/Edited raster as one opaque, single-frame
indexed GIF at native dimensions. Mode-6 exports the edit bits directly through
the ordered palette `(black, white)`. Rough Composite exports `pattern_at(x,y)`
directly through the current ordered 16-swatch project palette. It does not
recover indices from rendered RGB, because two distinct patterns can legally
share the same swatch color. VGA/EGA/CGA exports use their active physical
palette; the signal-decoded pane is quantized to a fixed 256-entry RGB332 table
for export only.

Only Mode-6 and rough Composite accept imports. The decoder requires one global
color table, one full-screen image frame, no transparency, exact dimensions,
and entry-for-entry palette equality including order. Composite indices expand
most-significant bit first into four Mode-6 bits; nonzero padding beyond a
partial final cell is rejected. The complete candidate stream must also pass
the same inverse CGA representability check used by DAT write-back. A valid
import is committed as one `EditAction`; no resizing, color conversion, palette
remapping, or best-fit recovery occurs.

One composite cell covers four mode-6 bits. Hover markers map those bits back to
two adjacent source pixels for ordinary 4-bit images, or up to four source pixels
for native 1-bit images. The all-pane grid uses each raster's displayed pixel
width, including the 1/2-width mode-6 transform and widened composite cells; it
does not modify decoded pixels or saved output.

## Full-width Composite signal preview

The sixth pane is a read-only `bit_width × height` raster generated by the
Reenigne/Jenner scanline decoder port from CGA Image Studio. It converts each
zero/one Mode-6 bit to RGBI black/white, constructs the sampled Composite
signal, and applies the neighboring-sample chroma and luma kernels before RGB
conversion. Consequently, four bits that form one rough cell need not display
as four identical RGB samples, and an edge in the next cell can affect samples
in the preceding cell.

The selected Old/New profile chooses the decoder's early/late CGA coefficient
branch. Editable 16-swatch tables are deliberately not inputs to this pane;
they remain controls for the flat 160-column editing model only. Each isolated
variant has a selected color phase from zero through three and a black border.
This offsets the signal decoder, not the original DAT image format. A v5
sidecar may hold independent variants for several phases; an ordinary patched
DAT still receives only the explicit fallback variant. Non-multiple-of-four
rows are padded with black solely for decoder alignment and cropped back to the
exact Mode-6 width. See `CGA_IMAGE_STUDIO_SIGNAL.md` for pinned provenance.

Changed images retain their original marker and pixel-depth nibble and are
encoded with LZG. Source B0/B1/B3 resources use row-major B3 output; source
B2/B4 resources preserve their transposed byte order as B4. The encoder uses
the original zero-filled 1 KiB history, 3–66-byte matches, least-significant
mask-bit order, and a dynamic parse that accounts for the shared mask byte.
Every encoded resource is decoded immediately and compared with the intended
pixel indices before it can enter the rebuilt archive.

## Sidecar and DAT safety

`.pdcproj` is UTF-8 JSON. Version 5 records a format/version marker, the source
filename, size, SHA-256 digest, active Old/New CGA profile, two independent sets
of 16 RGB triples, and each edited image's identity, dimensions, and depth. Each
edit then contains:

- one or more P0–P3 variants as MSB-first packed base64 bitstreams;
- an active editor phase, nonempty enabled phase set, and enabled legacy-DAT
  fallback phase;
- a packed source-index-zero mask and packed Mode-6 reference stream;
- a mask-lock flag;
- `phase_policy`, either the exact original-engine audit or a manual/custom
  coverage contract.

The active stream is repeated as a readable legacy snapshot and must match its
named phase variant when loading. Version-1 files are accepted: their one
palette is migrated into Old CGA and New CGA receives its DOSBox-X defaults.
Version-2 files default their signal phase to zero. Version-3 files retain their
saved phase. Every v1–v3 edit becomes one unlocked fixed-phase variant so a
previously intentional index-zero edit is not changed during migration.
Version-4 files retain their independent variants, coverage, fallback, and mask
state. Every v1–v4 edit migrates to Manual policy so the new placement audit
cannot silently change existing artwork. The next save writes version 5.

The separate phase-aware runtime manifest is JSON kind
`prince-dat-phase-aware-manifest`, version 2. For every enabled variant it
contains packed Mode-6 bits, inverse-mapped source indices, and a complete LZG
image resource plus counts and SHA-256 hashes. Each recognized resource also
records its policy and original-engine audit evidence. It records the selector:

```text
(global_phase_bias + destination_640_x - cropped_source_640_x) & 3
```

See `PHASE_AWARE_GRAPHICS.md` for field semantics and draw-hook guidance.
See `ORIGINAL_ENGINE_PHASE_AUDIT.md` for the complete placement proof and the
per-tile/per-cinematic resource matrix.

Saving a patched DAT:

- rejects the source path as the target;
- verifies the sidecar digest against the currently opened source;
- chooses each edit's explicit fallback phase and ignores the active UI phase;
- preserves resource order, IDs, and every unchanged content payload;
- LZG-compresses every changed 1-bit or 4-bit image as B3 or B4;
- recomputes offsets, index size, and all one-byte checksums;
- writes to a temporary file in the destination directory;
- reopens it, validates checksums and resource order, decodes every replacement,
  and compares its translated bitstream with the project;
- atomically replaces the chosen Save-As target only after validation succeeds.

## Independent room-set archives

`DUNGEON` and `PALACE` graphics are adapter-specific archives rather than one
shared image set. The editor resolves them as follows:

```text
VGA                    V{DUNGEON|PALACE}.DAT
EGA                    E{DUNGEON|PALACE}.DAT
CGA/mode 6/composite   C{DUNGEON|PALACE}.DAT
```

Corresponding records are joined by the 16-bit resource ID. Index positions
and image dimensions are allowed to differ. The C archive is the sole sidecar
source and Save-As target. V and E companions are preview-only and are never
passed to the DAT rebuilder. This deliberately permits C source indices to be
optimized for composite output without treating their incidental VGA/EGA
interpretations as authoritative or modifying the real V/E artwork.

## Research lineage

The attached 2003 Princed Graphics Extractor alpha established the B0–B4 codec
family, RLE controls, 1 KiB LZG history, and transposed storage. The complete DAT
index and palette structures are documented by the later Princed Resources and
SDLPoP projects. The phase ordering was checked against the original POP1 DOS
palette and packed-pixel conversion routines. See `THIRD_PARTY_NOTICES.md`.
