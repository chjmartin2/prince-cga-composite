# DOSBox-X Old/New CGA composite palette provenance

Prince DAT Explorer 0.4.8 derives both default 16-color Composite profiles from
**DOSBox-X 2026.08.02**, tag `dosbox-x-v2026.08.02`, commit
`784240ad6d9cf3ae3f02fab819e2ed5cf5117dd4`.

## Fixed configuration

| Setting | Old CGA | New CGA |
|---|---|---|
| DOSBox-X machine | `cga_composite` | `cga_composite2` |
| DOSBox-X flag | `new_cga = false` | `new_cga = true` |
| Physical model | Early IBM CGA | Late IBM CGA |
| Mode-control register `3D8h` | `1Ah` | `1Ah` |
| Color-select register `3D9h` | `0Fh` | `0Fh` |
| Hue offset | `0.0` degrees | `0.0` degrees |
| TV brightness | `0.0` | `0.0` |
| TV saturation | `0.6` | `0.7` |

`1Ah` means 640×200 graphics with color burst enabled; `0Fh` selects white as
the one-bit foreground. DOSBox-X maps `cga_composite` and `cga_composite2` to
the two values of `new_cga` in
[`dosbox.cpp`](https://github.com/joncampbell123/dosbox-x/blob/784240ad6d9cf3ae3f02fab819e2ed5cf5117dd4/src/dosbox.cpp#L1229-L1233).

DOSBox-X does not store either result as a literal 16-entry palette. Its
[`update_cga16_color()`](https://github.com/joncampbell123/dosbox-x/blob/784240ad6d9cf3ae3f02fab819e2ed5cf5117dd4/src/hardware/vga_other.cpp#L452-L625)
signal model changes these coefficients when `new_cga` is true:

| Coefficient | Old CGA | New CGA |
|---|---:|---:|
| Chroma | 0.72 | 0.29 |
| Blue RGBI | 0.00 | 0.07 |
| Green RGBI | 0.00 | 0.22 |
| Red RGBI | 0.00 | 0.10 |
| Intensity RGBI | 0.28 | 0.32 |

The same routine then performs its YIQ decode, NTSC-to-sRGB conversion, gamma
handling, clipping, and C++ integer truncation. The scanline renderer chooses
phase-specific entries from neighboring video bits in
[`VGA_Draw_CGA16_Line()`](https://github.com/joncampbell123/dosbox-x/blob/784240ad6d9cf3ae3f02fab819e2ed5cf5117dd4/src/hardware/vga_draw.cpp#L800-L828).

## Extracted repeating-pattern values

For the Explorer's deliberately simplified 160-cell renderer, each four-bit
pattern is repeated over one color-carrier cycle and its steady DOSBox-X RGB
value becomes the flat cell color.

| Pattern | Old CGA RGB | Old HEX | New CGA RGB | New HEX |
|:---:|---:|:---:|---:|:---:|
| `0000` | 0, 0, 0 | `#000000` | 0, 0, 0 | `#000000` |
| `0001` | 0, 99, 0 | `#006300` | 0, 102, 41 | `#006629` |
| `0010` | 0, 66, 226 | `#0042E2` | 0, 71, 255 | `#0047FF` |
| `0011` | 0, 159, 253 | `#009FFD` | 0, 148, 255 | `#0094FF` |
| `0100` | 166, 0, 94 | `#A6005E` | 190, 0, 48 | `#BE0030` |
| `0101` | 119, 115, 122 | `#77737A` | 119, 115, 122 | `#77737A` |
| `0110` | 209, 77, 255 | `#D14DFF` | 255, 65, 255 | `#FF41FF` |
| `0111` | 153, 172, 255 | `#99ACFF` | 191, 156, 255 | `#BF9CFF` |
| `1000` | 77, 64, 0 | `#4D4000` | 30, 82, 0 | `#1E5200` |
| `1001` | 0, 185, 0 | `#00B900` | 0, 204, 0 | `#00CC00` |
| `1010` | 119, 115, 122 | `#77737A` | 119, 115, 122 | `#77737A` |
| `1011` | 0, 235, 145 | `#00EB91` | 0, 239, 188 | `#00EFBC` |
| `1100` | 255, 68, 0 | `#FF4400` | 255, 85, 0 | `#FF5500` |
| `1101` | 223, 196, 0 | `#DFC400` | 185, 214, 0 | `#B9D600` |
| `1110` | 255, 133, 240 | `#FF85F0` | 255, 127, 198 | `#FF7FC6` |
| `1111` | 255, 252, 255 | `#FFFCFF` | 255, 252, 255 | `#FFFCFF` |

The Old and New tables were evaluated through the same equations and truncation
path; evaluating the Old branch reproduces every v0.4.4 value exactly before
the New branch is accepted. Automated tests pin all 32 RGB triples.

## Editor semantics

The **Old CGA / New CGA** selector changes only which 16 RGB values interpret
the same patterns. It does not change the 640-bit edit stream, the inverse CGA
translation, source indices, undo history, or patched DAT. The sidecar stores a
separate editable palette for each model and remembers the active model.
Version 0.4.16 and later use New CGA for new projects and unsaved viewer/export renders.
An existing sidecar's stored selection is never overridden.
Version-1 sidecars are migrated by treating their sole palette as Old CGA and
initializing New CGA from the table above.

## Simplification boundary

DOSBox-X normally produces one color for every 640-mode hdot and includes the
four-bit neighborhood and carrier phase. Prince DAT Explorer's rough editing
pane intentionally uses one flat RGB value for each non-overlapping four-bit
cell. Consequently, the swatches match DOSBox-X's stable repeating-pattern
colors, while that pane omits transition colors. Editable RGB/HEX controls
remain available for intentional rough-view overrides.

Version 0.4.8 adds a separate full-width signal pane that does show edge bleed,
ringing, and neighboring-bit effects through the CGA Image Studio decoder port.
That decoder's provenance and scope are documented in
`CGA_IMAGE_STUDIO_SIGNAL.md`.
