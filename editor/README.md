# Prince DAT Explorer 0.5.0

Prince DAT Explorer is a Windows desktop viewer and composite graphics editor
for DOS *Prince of Persia 1* `.DAT` archives. It decodes the game's indexed
resources, applies the embedded VGA/CGA/EGA hardware tables, compares display
modes, and safely writes composite edits to a new archive.

It uses only the Python standard library. No `pip` installation is required.

## Quick start on Windows

For the **Standalone Windows x64** ZIP, extract the entire archive and
double-click `PrinceDATExplorer.exe`. It carries a private Python/Tcl/Tk runtime,
does not modify `PATH`, needs no administrator access, and does not require
Python to be installed. A `.DAT` file can also be dragged onto the executable.

For the smaller source ZIP:

1. Install Python 3.10 or newer from <https://www.python.org/downloads/windows/>.
   Keep the default **Tcl/Tk and IDLE** feature enabled.
2. Unzip this release anywhere convenient.
3. Double-click `RUN_VIEWER.bat`.
4. Choose **Open DAT…** and open an archive from your copy of the game. For a
   room set, you may open any of `CDUNGEON`, `EDUNGEON`, `VDUNGEON`,
   `CPALACE`, `EPALACE`, or `VPALACE`.

You may also drag a `.DAT` onto `RUN_VIEWER.bat` or `PrinceDATViewer.pyw`.
The opened source is protected from overwrite throughout the editor.

## V22 Runtime Workspace

For V22 actor artwork, open the original Prince 1.3 `KID.DAT`, `GUARD.DAT`,
`FAT.DAT`, `VIZIER.DAT`, or `PV.DAT`, then choose **Editor…**. These five
families automatically open the V22 workspace instead of the old phase editor.
The editor links that read-only VGA source to a complete `ORIENT.DAT` (found
beside it or selected explicitly) and shows three synchronized views:

- original VGA reference;
- actual in-game Right/P0 output after Prince's source-pixel flip;
- actual in-game Left/P0 output on the native draw path.

Click or drag in either runtime view to edit that direction. **Generate Right**,
**Generate Left**, and **Generate Both** run the exhaustive New-CGA NTSC matcher
against the original VGA frame while preserving its index-zero silhouette.
GUARD exposes separate Dungeon and Palace contexts because V22 carries two
different hardware palette tables.
The five original source archives are authenticated by their standard Prince
1.3 SHA-256 values before editing begins.

This workspace intentionally contains no P1/P2/P3 slots, phase policy,
fallback selector, phase GIF family, phase manifest, or sparse patched-DAT
operation. **Export complete ORIENT.DAT…** is always Save-As and accepts only
the fixed V22 ABI: nine headers plus 880 images in exact runtime order. It
reopens and verifies resource IDs, checksums, image decoding, and translated
Mode-6 bits before replacing the destination. Unchanged resources retain their
original compressed bytes. **Runtime contact sheet…** exports only the two
views the executable can draw: Right/P0 and Left/P0.

Skeleton and Shadow are deliberately absent because V22 keeps both on their
shared native graphics paths. Legacy `.pdcproj` projects remain readable in
the explicitly labeled **Legacy phase editor…** for migration and non-V22 work.

## Viewer and mode comparison

The main display selector offers semantic video modes rather than cosmetic
palette substitutions:

- **VGA** uses the nearest embedded 16-color RGB palette.
- **EGA** applies the embedded four-phase EGA translation, then IBM RGBI.
- **CGA** applies the embedded four-phase CGA translation, then the normal
  high-intensity cyan/magenta/white palette used by Prince.
- **640×200** applies the CGA translation and expands every two-bit result into
  two monochrome bits.
- **Composite** groups four adjacent 640×200 bits into one of 16 artifact-color
  cells. The main viewer uses DOSBox-X `machine=cga_composite2` (New CGA); the
  editor can switch between the Old and New CGA models and includes a
  full-width signal-decoded preview with neighboring-pixel artifacts.
- **NTSC Composite** runs the full-width New-CGA signal simulation directly in
  the main preview, preserving neighboring-pixel color interactions.
- **Auto** selects VGA, EGA, or CGA from the archive's conventional filename.

Use **Compare modes…** to keep any two modes open side by side. The comparison
updates whenever another image resource is selected in the main window. Its
mode selectors include both **Composite**, the idealized 160-column color-cell
view, and **NTSC Composite**, the full-width New-CGA signal simulation with
neighboring-pixel artifacts.

### Linked DUNGEON and PALACE archives

Room artwork does not share one source archive across all adapters. The viewer
therefore treats each room set as three independent files:

| Display | Dungeon source | Palace source | Access |
|---|---|---|---|
| VGA | `VDUNGEON.DAT` | `VPALACE.DAT` | Read-only reference |
| EGA | `EDUNGEON.DAT` | `EPALACE.DAT` | Read-only reference |
| CGA / 640×200 / Composite | `CDUNGEON.DAT` | `CPALACE.DAT` | Composite target |

Opening any member automatically discovers siblings in the same folder. The
main mode selector, **Compare modes…**, and the six-pane editor then take each
preview from the proper archive. Matching is by resource ID, not index position,
so archive ordering may differ. Missing EGA/VGA references can be selected from
the editor's **Room references** menu or source bar.

All GUI views normalize transformed pixel shapes to the ordinary source-image
width. For a 4-bit image, 640×200 bits are drawn at half pixel width and
160×200 Composite cells at double pixel width. Thus a 320-column source, its
640-column bitstream, and its 160-column Composite interpretation all occupy
the same apparent width. This is display scaling only: main-view PNG exports
and editor-pane GIF exports retain the exact 640- and 160-column raster
dimensions.

The resource browser also provides filtering, ID/type search, checksum status,
fit and integer zoom, a pixel grid, index-zero transparency, exact pixel hover
details, a hex view, PNG export, raw resource export, and full extraction with
`manifest.csv`.

## Composite editor

Select a 1-bit or 4-bit image and choose **Composite editor…**. Six synchronized
panes remain visible:

- VGA live patched preview (linked V reference for DUNGEON/PALACE)
- EGA live patched preview (linked E reference for DUNGEON/PALACE)
- CGA live patched target preview (linked C archive for DUNGEON/PALACE)
- editable 1-bit / Mode-6 bitstream
- editable 160-column Composite-cell view
- read-only full-width Composite signal simulation with edge artifacts

The editor has its own **DAT image** selector plus **Previous / Next** buttons,
so a multi-image project can be completed without returning to the main resource
browser. `Alt+Left` and `Alt+Right` provide the same navigation. The project
summary beside the selector always shows how many image records the sidecar
currently contains; **Save phase-aware sidecar (.pdcproj)** writes every one of
those records and every stored P0–P3 slot, not merely the image or phase visible
on screen. `Ctrl+S` always invokes this complete sidecar save.

Each edited resource is a **phase-aware graphic family** with up to four
independent Mode-6 variants. For recognized original 1.3 archives, the phase
bar now applies an exact engine-placement audit and creates only the slots that
resource can reach. Fixed room/title art is normally P0, potion bubbles and
some cinematic frames are P2, while moving actors and shared torch flames use
P0+P2. Manual policy retains arbitrary P0–P3 coverage for custom executable
work. The bar also selects the variant currently being edited and the one used
as the fallback in an ordinary unmodified-format DAT.

The editor keeps the save contract visible below the phase controls: a
`.pdcproj` is the recoverable authoring file and retains the whole graphic
family, while **Save patched DAT…** can write only the selected fallback. Use
**Help → How phase-aware saving works…** for the exact save/reopen sequence.

Each pane has its own **Original / Edited** selector and defaults to Edited.
The selection is independent, so—for example—you can keep VGA and Composite on
Original while watching the edited EGA, CGA, and 640×200 results. Original
always renders from the untouched source archive; Edited renders the current
predicted Save-As result. For linked DUNGEON/PALACE artwork, the independent V
and E reference files are unchanged in both positions, while the C-derived
panes switch between the original C image and the current edit. Composite
Original uses the current 16-color project palette so the comparison isolates
pixel-pattern changes. It is read-only; switch that pane back to Edited before
drawing. Switching views never discards or changes edits.

The Mode-6 and rough Composite panes both accept drawing. The Mode-6 pencil
offers **1 (white)**, **0 (black)**, and **Transparent**. For ordinary 4-bit
DAT images, Transparent writes source index 0 while black writes a representable
nonzero source index whose CGA translation is black. Transparency is therefore
part of the DAT image's index plane, not a separate alpha layer. The sidecar
tracks that index-zero geometry separately from the Mode-6 signal bits so both
states remain editable. Right-click/drag always writes **opaque black**.
The selected solid transparency display color can be changed with **Select
transparent color…**; it is an editor-only aid and is not written to the DAT.
Native 1-bit resources have only source indices 0 and 1, so index 0 cannot be
both transparent and a distinct opaque black.
The rough Composite pane can write either a selected four-bit cell or one
sub-bit. A stroke in either pane redraws both Composite views immediately.

### Fixed-palette GIF interchange

Every pane has an **Export GIF…** button beside its Original/Edited selector.
It exports the currently visible view at its native raster dimensions, without
the GUI zoom, grid, or hover overlay. VGA, EGA, CGA, Mode-6, and rough
Composite exports use their exact indexed palettes. The signal simulation is
exported through one deterministic 256-color RGB332 palette because its analog
decoder can produce more than 256 distinct RGB values.

The two editable panes additionally provide **Import GIF…**. Mode-6 exports a
four-entry table: opaque black, opaque white, transparent magenta, and reserved
cyan. The transparent entry carries the source-pixel mask separately from the
black/white signal bits, so outlined art can contain both opaque black and a
transparent background. Legacy opaque two-entry black/white imports remain
accepted and preserve the current mask. Rough
Composite uses the current 16 project swatches and stores each GIF index as its
four-bit pattern; distinct pattern indices remain distinct even when two
swatches have the same RGB color. Each successful import is one undoable edit.

Import is deliberately strict. The pane must be showing **Edited**, and the
GIF must be single-frame, use one global indexed palette, have the exact
exported dimensions, and match every palette entry in the same order. Only the
Mode-6 contract accepts its exported index-2 transparency; other panes remain
opaque. The editor rejects truecolor files, animation, resized images, local or
reordered palettes, changed colors, invalid partial-cell transparency/padding,
and bit patterns the resource's CGA translation table cannot encode. It never
silently resizes, quantizes, remaps, or repairs an imported image. Export a
pane first and preserve that GIF's indexed format while editing it externally.
The file dialogs remember the last GIF import/export folder for the current
editor session.

Choose **Image → Export animation contact sheet…** to write one master PNG for
whichever DAT is currently open. Since DAT archives contain numbered images
rather than animation sequence metadata, the generic exporter includes every
editable 1-bit and 4-bit image in archive order and labels it by resource ID and
index. Every frame card shows right- and left-facing runtime orientation at P0
and P2. Stored project variants are used when available; otherwise the current
DAT bitstream is decoded at both carrier phases. KID resources 401–619 receive
the known run, jump, turn, hang, fall, sword, potion, death, HP, and hurt-family
labels; other DATs require no special filename mapping.

The separate **Export resource/phase matrix…** command writes the more compact
project-record matrix introduced in v0.4.29. Rows are resource IDs and columns
are enabled P0–P3 slots; it is not the animation contact sheet.

For whole-archive transport, use **Image â†’ Export all resources to Mode-6 GIF
folderâ€¦** and **Import resources from Mode-6 GIF folderâ€¦**. Every editable
1-bit or 4-bit resource uses the same strict transparency-aware Mode-6 format.
A single-phase resource uses its numeric ID (`54.gif`). A multi-phase family
uses one complete suffixed set (`751_P0.gif`, `751_P2.gif`). Import may contain
any subset of resource families, but every included multi-phase family must be
complete. The editor validates every filename, ID, phase, dimension, palette,
mask, and inverse CGA mapping before changing anything; the entire folder
import is one undoable action.

### Phase-aware graphic families

NTSC still has four physical sample phases, but the original game places and
crops images only in integral 320-column CGA pixels—two 640-column samples at a
time. With a normalized P0 screen origin, only P0 and P2 are reachable. The
**Original DOS 1.3 engine (automatic)** policy uses a resource-by-resource
audit of all 31 tiles, moving image banks, fixed screens, and scripted
cinematics. Its coverage controls are locked while the artwork in each required
slot remains editable.

Choose **Manual / custom executable** to use these profiles directly:

- **Fixed phase** stores one intended alignment. This is the right default for
  screen-aligned backgrounds and graphics whose draw position never changes.
- **X parity: P0 + P2** is the recommended first sprite workflow when the game
  moves or draws in ordinary 320-column pixel units. One source-pixel movement
  advances the 640-column signal by two samples, so those placements alternate
  between two carrier alignments.
- **X parity: P1 + P3** represents the other two-sample parity.
- **All four phases** covers patched code paths that can place or clip artwork
  at any individual 640-column sample alignment.
- **Custom phases** enables any explicit nonempty subset.

Enabling a missing slot clones the current variant only as a placeholder.
Choose **Exhaustive** in Convert and click **Generate enabled phase set** to run
one complete optimization independently for every enabled phase. Each result
uses that phase's own decoder and becomes its own bitstream; targets, decoded
colors, and errors are never averaged across slots. This is different from
carrier phase **all**, which is available in every conversion model and finds
one shared universal compromise pattern over only the phases enabled for the
current resource. The universal pattern is stored in the active slot.

The **Edit variant P0–P3** controls switch the active bitstream without changing
any other slot. **Animate runtime phase switching** cycles the intended variants
through every live pane so motion-color discontinuities are visible. **DAT
fallback** chooses the only slot written by **Save patched DAT…**, because the
original Prince image resource has room for one image, not a phase family.

For sprites and other masked artwork, enable **Lock source index-zero geometry
across variants**. The sidecar stores the original C-target mask plus its exact
Mode-6 reference bits. Painting, GIF import, conversion, inverse CGA mapping,
and manifest export must all preserve those positions. When a multi-phase
profile is first enabled, the editor turns this safety on automatically if the
current artwork already matches the source mask.

**Export GIF set…** writes one exact `_P0_` through `_P3_` fixed-palette file for
every enabled slot. **Import phase GIF set…** requires exactly that enabled set,
all in Mode-6 or all in rough Composite format, and validates every file before
changing any variant. The whole set is committed as one undoable action.

**Export runtime manifest…** writes a lossless JSON interchange file for the
future EXE/DAT packer. It includes enabled coverage, automatic/manual policy,
the original-engine placement evidence when known, fallback choice, mask,
packed Mode-6 bits, deterministic source indices, complete LZG image payloads,
and SHA-256 hashes for every enabled variant. The runtime alignment contract is:

```text
phase = (global_phase_bias + destination_640_x - cropped_source_640_x) & 3
```

Both X values are signal-sample coordinates. Ordinary 320-column source and
destination positions therefore advance by two. Runtime horizontal flipping is
a separate dimension for moving actor/sword banks; a future patch that demands
exact color in both facings should key those assets by phase and facing. See
`docs/ORIGINAL_ENGINE_PHASE_AUDIT.md` for the placement evidence and
`docs/PHASE_AWARE_GRAPHICS.md` for the designer/draw-hook contract.

### Fixed-palette, simulated, and exhaustive Convert

Choose **Convert** in the editor toolbar (or **Image → Convert current image…**)
to rebuild the current edited Composite image from its matching **VGA**, **EGA**,
or **CGA** source. Unavailable linked-room references are disabled instead of
silently falling back to another archive.

The **Conversion model** selector provides three genuinely different conversion
and preview paths:

- **Simply Palette** treats the destination as independent 160×200-style
  cells. Each cell is selected from the fixed 16-color Old/New CGA table by
  ordinary, unweighted nearest-RGB distance after box-averaging the source area.
  It has no dither, brightness, contrast, saturation, gamma, color/detail bias,
  signal search, edge bleed, or neighbor influence. Carrier phase rotates the
  fixed four-clock lookup; **all** adds the independent fixed-palette errors for
  only the enabled runtime phases. The unrelated controls are disabled in this
  mode, so they cannot change its result.
  **Preserve source index-zero background** remains available only as a hard
  bit constraint. The preview is the exact flat palette image being quantized.
- **Simulated NTSC** retains the artifact-aware converter. Converted and
  Current-edit previews use the full signal decoder, including edge bleed,
  ringing, and neighbor-dependent colors. For a normal 320×200 source, each
  source pixel is expanded to two color-clock samples and the optimizer judges
  every pixel of the actual **640×200 decoded output**. Fast/Balanced/High
  select an 8/32/96-state beam, respectively. **All** makes the same beam score
  every enabled carrier phase independently and sum those costs without
  averaging colors or targets; all dither and adjustment controls remain usable.
- **Exhaustive** uses the same explicit VGA/EGA/CGA source selector and 2×
  horizontal pixel replication, but retains all 2,048 possible eleven-bit
  decoder histories at every signal position. Dynamic programming therefore
  finds the globally minimum-error row without enumerating `2^640` rows or
  pruning candidates. Phase 0–3 uses ordinary squared RGB error at one real
  carrier alignment. **All** decodes every candidate independently at each
  enabled runtime phase, then sums the absolute RGB component errors. A fixed
  P0 resource therefore scores only P0, while a moving P0+P2 resource scores
  exactly P0 and P2. It never averages target or decoded colors.

All three modes emit a candidate Mode-6 bitstream into one phase-family slot.
Switching the selector rebuilds the preview with the chosen model rather than
merely recoloring the previous result. **Simply Palette** uses the profile's
fixed default table, not custom rough-editor swatches, so its nearest-color
mapping is reproducible.

The Convert preview has the same integer zoom choices from **1× through 20×**.
At high zoom it keeps the complete scrollable 640×200 signal but rasterizes only
the visible viewport, so 20× does not allocate a 12,800×4,000 Tk image. The
mouse wheel scrolls vertically and Shift+wheel scrolls horizontally.

Controls used by **Simulated NTSC** include:

- no dither, adjustable Floyd–Steinberg (with optional serpentine scanning), or
  adjustable 2×2 / 4×4 / 8×8 Bayer dithering
- brightness, contrast, saturation, and gamma input adjustment
- color emphasis and edge/detail preservation
- Fast, Balanced, and High signal-search quality
- CGA carrier phase 0–3 or **all enabled phases**
- source-index-zero background preservation

**Exhaustive** keeps the input-adjustment and dither controls but disables
color emphasis, detail preservation, and beam quality because its loss is
fixed: unweighted squared RGB error for phase 0–3, or summed absolute RGB
error for **all**. Bayer displacement is applied to each
individual 640-column target pixel before row optimization. Error diffusion
runs only after an entire optimal row has been selected: residual RGB error is
sent 8/16 down-forward, 5/16 straight down, and 3/16 down-backward, with no
same-row propagation. Serpentine mode mirrors the diagonal weights on alternate
rows, and the next row's adjusted RGB target is clamped to 0–255. In **all**
mode, one independent diffusion buffer preserves each enabled phase's own
residual; they are never combined. The decoded preview contains only enabled
phase panels in ascending row-major order. Changing phase selection reruns the
Exhaustive row solver.

Applicable controls update a debounced background conversion, so stale work is
cancelled when another dial moves. **Convert** applies the completed bitstream
to the current edited image only after the same inverse-CGA representability
check used by DAT Save-As succeeds. The full conversion is recorded as one
undoable action. P0–P3 in any model replaces the selected phase variant,
creating and enabling that slot when permitted. **All** in any model stores its
one reachable-phase universal compromise in the active slot. **Generate enabled
phase set** validates every independently solved Exhaustive variant before
committing the whole family as one undoable action. A locked C-target index-zero mask overrides the
selected reference image's mask and supplies exact per-bit constraints directly
to every optimizer. Conversion changes no DAT file until **Save patched DAT…**
is used.

In a shared sprite archive such as `KID.DAT`, every stroke is immediately
inverted through the same deterministic source-index
selection used by **Save patched DAT…**. VGA, EGA, and CGA then redraw from that
predicted source image, so they show the exact adapter impact before saving.
For a linked room set, only the C target redraws from the edit; the E and V
archives are genuinely separate read-only references and remain unchanged.
For equal apparent widths, 640×200 is displayed at half horizontal scale and
Composite at double horizontal scale for ordinary 4-bit resources.

Hovering a Composite cell outlines it in yellow, marks all four underlying
Mode-6 bits, and marks every corresponding source pixel in the VGA, EGA, and
CGA panes. It also marks all four affected samples in the artifact pane.
Hovering one Mode-6 bit performs the inverse mapping: it marks that signal
sample, its rough Composite cell, and its source pixel across the adapter
panes. A normal 4-bit cell maps to two adjacent source pixels; a native
1-bit cell maps to as many as four. Linked room references use the same direct
pixel coordinates and clip markers that fall outside a differently sized image.

Two rough-Composite drawing tools are available:

- **Composite cell** writes the selected four-bit composite pattern.
- **Composite bit** changes an individual bit within a cell. Selecting it at 1×
  automatically increases zoom to 2× so all four bits are addressable.

The separate Mode-6 pane always uses the **Mode-6 pencil** controls. Left-drag
paints opaque white, opaque black, or DAT index-zero transparency. Right-click
or right-drag writes opaque black. A transparency stroke updates the shared
source-index mask and every stored phase variant atomically. Choose Composite
swatch **0** for whole-cell black in the rough Composite pane. Undo and redo
operate per stroke or imported GIF regardless of which representation created
the change.
The 16 swatches are labeled with both hexadecimal and four-bit values. Select a
swatch to paint, then enter exact 0–255 R/G/B values with **Apply RGB**, enter a
CSS-style `#RRGGBB` value such as `#006300` with **Apply HEX**, or double-click
it to use the Windows color picker. Applying RGB updates the HEX field, and
applying HEX updates all three RGB fields. These colors control the rough
Composite-cell preview and are stored in the sidecar project; the physical
signal preview is calculated from bits and does not use custom swatches.

At the top of the palette, **Old CGA** selects DOSBox-X
`machine=cga_composite` and **New CGA** selects `machine=cga_composite2`.
The same selection chooses the artifact decoder's corresponding early/late CGA
branch. Switching redraws Original and Edited Composite immediately but does not alter
the 640-bit edit stream, source indices, undo history, or patched-DAT output.
Each model has its own editable 16-swatch table; custom values are retained when
you switch away and back. New projects and unsaved viewer/export paths start on
New CGA. A sidecar's explicitly selected model is restored when it is reopened.

The editor zoom selector provides integer levels through **20×**, and all six
panes—including the full-width Composite signal preview—follow the selected
scale. The signal pane uses a cropped viewport renderer, so its logical
12,800×4,000 view at 20× does not allocate one enormous Tk image. Enable
**Grid** in the toolbar (or press **Ctrl+G**) to overlay cell boundaries in all
six panes. Enabling it below 4× automatically selects 4× so the half-width
Mode-6 cells remain visible. Grid and hover overlays remain synchronized above
the viewport-rendered signal, and neither is written into project or DAT data.

## Saving safely

The two-part workflow keeps editing recoverable and the original archive safe:

1. **Save phase-aware sidecar (.pdcproj)** (or `Ctrl+S`) writes a JSON sidecar
   containing every edited image and every stored P0–P3 slot—including stored
   work that is not currently enabled—plus the selected CGA model, both
   editable 16-swatch RGB tables, enabled runtime coverage, active and fallback
   phases, and transparency-mask metadata for each touched resource. It records
   the source DAT's SHA-256
   digest and refuses to attach to a different file. Schema v5 still loads
   v1–v4 sidecars. V1–v3 edits migrate to one unlocked fixed-phase variant;
   v4 retains its independent variants, coverage, fallback, and mask state.
   Every legacy edit migrates to Manual policy so the original-engine audit
   never silently changes prior artwork.
2. **Save patched DAT…** creates a new `.DAT`. The source filename is explicitly
   rejected as a destination. Only the selected fallback variant can enter this
   legacy format; use the runtime manifest for all enabled variants.

To reopen the work, load the original source DAT, open the Composite editor,
then choose **Project → Open phase-aware sidecar…**. The editor verifies the
source size and SHA-256 before attaching the project.

Saving an already opened sidecar updates that complete multi-image project.
**Save phase-aware sidecar as…** does not silently merge two separate editing
sessions. If its destination is an existing sidecar containing image records
absent from the current project, the editor refuses to replace it and tells you
to open that sidecar first or choose another filename. This prevents a
one-image/new project from accidentally erasing a larger project.

During DAT creation, changed 1-bit or 4-bit images are converted back through
the embedded CGA translation and recompressed with Prince's 1 KiB-window LZG
codec. The source resource's row-major or transposed storage orientation is
preserved as B3 or B4. If several 4-bit source indices produce the requested CGA value, the
original index is retained when possible; otherwise the nearest embedded VGA
color is selected deterministically. Untouched resource payloads remain
byte-for-byte identical, resource IDs and order are retained, offsets and
checksums are rebuilt, and the completed archive is reopened to verify every
edited bit before it replaces the Save-As target.

Because one CGA value can have several inverse source indices, a painted cell
may change a VGA or EGA reference color in the patched archive even though its
CGA/640/Composite result is exact. For shared archives such as `KID.DAT`, the
editor now shows these predicted VGA/EGA changes live. The save dialog also
calls out this hardware-format limitation.

For DUNGEON and PALACE work, this compromise is confined to the patched C
archive. The independently loaded E and V reference files are never rebuilt,
opened for writing, or included in the sidecar's editable state. A patched
`CDUNGEON` therefore cannot damage `EDUNGEON` or `VDUNGEON`, and likewise for
the three PALACE archives.

## Composite preview scope

Both built-in 16-entry Composite palettes are derived from DOSBox-X 2026.08.02:
`machine=cga_composite` for **Old CGA** and `machine=cga_composite2` for
**New CGA**, with mode control `1Ah`, foreground `F`, and default hue. The exact
source, model coefficients, assumptions, derivation, both RGB tables, and
pinned commit are in `docs/DOSBOXX_COMPOSITE_PALETTE.md`. Existing v0.4.4
sidecars retain their saved table as Old CGA; **Reset palette** restores only
the currently selected model.

The 160-cell Composite pane remains the intentionally flat editing model. It
uses DOSBox-X's steady color for each repeating four-bit pattern and therefore
keeps cell selection easy.

The additional full-width **Composite signal** pane decodes every Mode-6 sample
with the Reenigne/Jenner engine port used by `chjmartin2/cga-image-studio`.
Neighboring bits feed the chroma/luma kernel, so transition colors, edge bleed,
and ringing are visible rather than collapsed into one swatch per cell. It
follows the selected Old/New CGA model but intentionally ignores custom
rough-view swatch RGB values because those values are not part of the simulated
signal. The converter can preview and optimize carrier phases 0–3. Every model
also has an **all** objective that scores only the current resource's enabled
phase decodes and shows only those panels in a grid. The sidecar can instead
store independently optimized variants for any phase subset. Phase is a placement-dependent simulation
alignment rather than a field in the original image format: the ordinary
patched DAT still contains one fallback bitstream, while a future draw hook can
select the intended sidecar/manifest variant from the final screen X. Exact
decoder provenance is in `docs/CGA_IMAGE_STUDIO_SIGNAL.md`; converter details
are in `docs/COMPOSITE_CONVERTER.md`.

## Supported formats

- POP1 DAT archives with the six-byte header and eight-byte index records.
- 1-bit, 4-bit, and 8-bit decoding.
- RAW, RLE, transposed RLE, LZG, and transposed LZG image forms.
- VGA, EGA, and CGA rendering from the embedded 100-byte hardware record.
- Linked C/E/V DUNGEON and PALACE comparison by resource ID.
- Composite editing and write-back for 1-bit and 4-bit images.
- Four-slot phase-family authoring, exact indexed-GIF sets, and a lossless
  runtime interchange manifest.

POP2 archives, 8-bit write-back, arbitrary truecolor resource import, the final
EXE draw hook/variant packer, and monitor-specific postprocessing are outside
this release.

## Verification

Run `RUN_TESTS.bat` to execute 175 deterministic tests. They cover all five image
codecs, LZG encoding and B3/B4 round trips, palette parsing, four distinct CGA/EGA phases, translated mode-6 bits,
all raster and normalized display dimensions, project serialization, editable
RGB/HEX values, exact Old/New DOSBox-X tables, New-CGA defaults, v1 sidecar migration, independent
per-model custom palettes, profile switching without pixel changes, direct
1-bit painting, exact Old/New artifact scanline output, all four carrier phases,
transition bleed, exact 12-bit converter neighborhoods, full-signal conversion,
globally optimal selected-phase and reachable-phase summed-absolute row encoding,
unblended phase-subset preview layouts, independent reachable-phase diffusion buffers,
solid-color EGA regression,
per-signal-pixel Bayer displacement, vertical-only serpentine diffusion,
fixed-palette nearest-RGB conversion and hard zero-mask behavior,
Floyd–Steinberg/Bayer/no-dither behavior, index-zero preservation, one-action
conversion undo/redo, independent phase-set conversion and atomic undo/redo,
exact target-mask constraints, complete multi-image/all-slot schema-v6
serialization, authored transparency masks, v5 source-mask preservation,
v4 phase-family preservation, v3 migration,
fallback-only DAT creation, and lossless manifest bits/source indices/LZG
payloads, plus memory-safe 20× converter and editor signal zoom,
viewport clamping and grid overlays, all-pane geometry, composite-to-source
hover mapping, independent Original/Edited pane rendering, live predicted
adapter rendering, inverse mapping, source identity checks, source-overwrite rejection,
unchanged payload preservation, checksums, verified DAT reopening, all six room
archive names, sibling discovery, resource-ID matching across reordered files,
missing-reference handling, and strict family/adapter validation.
They also cover dependency-free indexed-GIF encoding/decoding, exact palette
and dimension rejection, duplicate-color index preservation, transparency
round trips, multi-frame rejection, partial-cell padding/transparency, and
one-action GIF import and mask undo.
They also cover numeric bulk-GIF naming, non-mutating whole-archive export,
complete multi-phase family enforcement, detached all-or-nothing folder
validation, and one-action bulk undo/redo.
An explicit isolation test also patches `CDUNGEON` through a workspace opened
from `VDUNGEON` and verifies that the E and V files remain byte-for-byte intact.

The writer was additionally exercised against a real 12-resource `TITLE.DAT`:
all ten edited graphics were recompressed as LZG, the archive remained below
its original RAW-expanded size, every checksum passed, and every reopened
composite bitstream matched the project exactly. No game data is included in
this package.

## Files

- `PrinceDATViewer.pyw` — main Windows application.
- `editor_windows.py` — comparison workspace and six-pane editor.
- `indexed_gif.py` — strict dependency-free indexed GIF interchange codec.
- `composite_signal.py` — full-width Old/New CGA artifact scanline decoder.
- `composite_converter.py` — fixed-palette and 640-column artifact-aware
  conversion, preview rendering, and dithering.
- `prince_dat.py` — DAT parser, codecs, hardware translations, renderers, PNG
  writer, and extraction API.
- `composite_project.py` — sidecar format, editing model, inverse mapping, and
  safe DAT rebuilder.
- `room_sets.py` — linked C/E/V room discovery, validation, and resource-ID
  resolution.
- `tests/` — self-contained deterministic tests.
- `docs/FORMAT_NOTES.md` — exact binary and translation-table interpretation.
- `docs/DOSBOXX_COMPOSITE_PALETTE.md` — pinned Composite RGB provenance.
- `docs/CGA_IMAGE_STUDIO_SIGNAL.md` — artifact-preview engine provenance and scope.
- `docs/COMPOSITE_CONVERTER.md` — converter controls, objective, and search model.
- `docs/PHASE_AWARE_GRAPHICS.md` — phase-family authoring and future draw-hook
  interchange contract.
- `THIRD_PARTY_NOTICES.md` and `LICENSE.txt` — attribution and GPL terms.

This project is distributed under GPL-2.0-or-later and without warranty.
