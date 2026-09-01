# Changelog

## Prince DAT Explorer v0.4.28 - 2026-08-31

- Added whole-archive Mode-6 GIF export/import from the Composite editor for
  fast external-art round trips. Single-phase files use numeric resource names
  such as `54.gif`; multi-phase families use complete sets such as
  `751_P0.gif` and `751_P2.gif`.
- Export includes every editable 1-bit/4-bit resource and every enabled phase
  without adding records to or dirtying the live sidecar.
- Folder import accepts a subset of resource families, validates every file,
  resource ID, required phase, palette, dimension, transparency mask, and CGA
  inverse mapping on detached records, then commits the complete folder as one
  undoable action.
- Added six focused bulk-interchange regressions and passed the complete
  175-test editor suite.
- Built deterministic Python-source and self-contained Windows x64 packages;
  the standalone bundle includes CPython 3.12.10, Tcl/Tk, editor source, runtime
  licenses, per-file checksums, and no game data.

## Runtime V20Z - 2026-08-31

- Recorded the V20Y DOSBox result: restored stencil coverage appeared only as
  a small yellow floor trace while the blade remained grey.
- Traced the active CGA mono renderer and found that nominal color 12 uses
  scanline bytes `AA AA AA AA`; under forced Mode 6, `10101010` is neutral
  grey rather than red.
- Evaluated all 256 byte patterns over the exact ten restored masks at their
  real offsets on all five rear and foreground blade frames. Selected `C4`
  (`11000100`) for all four scanline phases: predicted New-CGA mean RGB is
  `(181,56,51)` on the rear/floor pass and `(146,65,78)` on the narrow blade.
- Changed only the four mono-color-12 table bytes and the visible V20Z marker;
  every DAT archive and every other executable runtime byte preserves V20Y.
  Chris confirmed in DOSBox that both chomper blood and potion bottles render
  red.

## Runtime V20Y - 2026-08-31

- Restored all ten native one-bit chomper-blood stencils in `CDUNGEON.DAT`
  resources 1314-1323 byte-for-byte from the verified original archive.
- Corrected the conversion error that reduced those masks from 498 set bits to
  223; the recovered 275 bits are coverage/opacity data for Prince's mono
  blitter, not independently optimizable composite-color pixels.
- Traced the original draw path: hard-coded mono color 12 becomes repeating
  Mode-6 pattern `1100`, and every blood frame is drawn at
  `32*tile_column+12` (P0), so neither a color patch nor phase variants are
  required.
- Preserved every other CDUNGEON resource, every other DAT archive, and all
  V20X executable runtime code. DOSBox confirmed that stencil restoration
  alone was insufficient: a little yellow appeared on the floor, but the blade
  remained grey because mono color 12 still emitted pattern `AA`.

## Runtime V20X - 2026-08-31

- Corrected the climbing floor-overlay masks in `CDUNGEON.DAT` resources 232,
  350, and 351; resource 268 was confirmed to be the unrelated gate-top mask.
- Replaced 66 transparent index-zero holes with opaque source index 4, which
  has the same CGA `00` translation. The complete Mode-6 bitstreams and Amir's
  artifact colors remain byte-for-byte identical.
- Restored the exact original silhouettes, verified all other CDUNGEON
  resources and every other DAT archive unchanged, and preserved all V20W
  runtime and title behavior.
- Documented the separate original big-pillar-top draw-condition edge case.
  Chris confirmed in DOSBox that the reported tower-climb transparency defect
  is fixed by the mask repair.

## Runtime V20W - 2026-08-31

- Integrated Amir's 2026-08-30 `TITLE.DAT` and work-in-progress
  `CDUNGEON.DAT` over the confirmed V20V command-tail build.
- Fixed `TITLE.DAT` resource 54 by restoring its exact original 9,799-pixel
  index-zero transparency mask while preserving every Amir-authored pixel
  outside the mask, including 1,929 opaque-black outline pixels.
- Removed 3,775 temporarily baked-in background pixels from the title logo;
  verified DAT checksums, resource order, LZG decoding, exact source hashes,
  package contents, and deterministic ZIP output.
- Added a guarded exact-mirror V20W installer for the disposable
  `C:\DOS\POP_CP` directory. Title/high-score visual confirmation remains
  pending.

## Prince DAT Explorer v0.4.27 - 2026-08-30

- Added direct Mode-6 pencils for opaque white, opaque black, and transparent
  DAT source index 0; transparency strokes synchronize every stored phase and
  undo as one action.
- Replaced the ambiguous black display of transparent samples with a solid,
  user-selectable transparency color that is never written into the DAT.
- Documented the actual DAT representation: ordinary 4-bit transparency is
  source index 0, not a separate alpha layer; opaque black uses a representable
  nonzero source index. Native 1-bit resources cannot encode both states.
- Published deterministic Python source and self-contained Windows x64
  packages with the complete CPython 3.12.10/Tk runtime and no game data.
- Passed the complete 169-test editor suite.

## Runtime V20V - 2026-08-30

- Changed the `.COM` launcher's DOS EXEC command-tail pointer from its private
  empty tail at `CS:0586` to the parent PSP tail at `CS:0080`.
- Arguments now reach Prince, so `CGA4K2V.COM improved` enables the game's
  cheat/testing commands; Chris confirmed normal and cheat-enabled launches in
  DOSBox.
- Preserved all 32 DAT archives and all executable runtime code from the
  DOSBox-confirmed V20U shared-sword build.
- Verified the exact EXEC parameter block and segment initializer, constrained
  binary changes, deterministic rebuild, ZIP hashes, contents, and integrity.

## Prince DAT Explorer v0.4.26 - 2026-08-30

- Added transparency-aware Mode-6 GIF import/export with distinct opaque-black,
  opaque-white, and transparent indices, including atomic phase-set mask edits.
- Preserved legacy opaque black/white GIF imports and all v1-v5 sidecar mask
  behavior; schema v6 records deliberately authored transparency masks.
- Added full mask-state undo/redo and remembered the last GIF folder during an
  editor session.
- Passed the complete 164-test editor suite.

## Runtime V20U - 2026-08-30

- Re-encoded `PRINCE.DAT` resources 701-734 as one shared moving-sword pattern
  per frame, optimized exhaustively over reachable P0 and P2.
- Added no sword phase selector, sidecar DAT, or runtime code; V19L's KID, HP,
  and hurt-splash mappings remain byte-identical.
- Constrained the exact search to the sword palette's representable CGA codes
  (`00`, `10`, and `11`) and restored the original index-zero transparency
  masks, correcting 70 drifted mask pixels across 24 baseline sword frames.
- Reduced the matching two-phase mean absolute RGB objective from 18.822 to
  17.768; RMSE is essentially tied (48.964 baseline, 49.294 V20U), so DOSBox
  visual testing—not the metric—decides whether this shared treatment wins.
- Static resource, hash, executable-marker, package, and ZIP verification pass.
- Chris confirmed in DOSBox that the shared sword looks great, including the
  colored hilt/detail sequence; sword phase variants are not needed.

## Prince DAT Explorer v0.4.25 - 2026-08-30

- Added optional exact two-bit representability constraints to the exhaustive
  encoder so runtime builders cannot request CGA codes absent from a DAT
  bank's embedded translation palette.
- Added focused exhaustive constraint and validation tests.

## Runtime V19L - 2026-08-30

- Swapped only the Prince health-icon direct-blit absolute-phase branch:
  screen positions 1/3 select PHASE3/P2 and 2/4 select KID/P0.
- Preserved all 32 DAT archives, the confirmed V18 body mapper, the V19 hurt
  splash route, and both HP call hooks byte-for-byte.
- Verified 80 machine-helper cases, 10 PHASE3 lazy-load cases, executable
  signatures, package contents, deterministic ZIP output, and ZIP integrity.
- Added a guarded, hash-verifying exact-mirror installer for the disposable
  `C:\DOS\POP_CP` DOSBox working directory.
- DOSBox runtime confirmation remains pending.

## Prince DAT Explorer v0.4.24 - 2026-08-30

- Added **NTSC Composite** to the main Display selector.
- Routed main preview, PNG export, Extract All, hover details, and linked-room
  selection through the full-width New-CGA signal decoder.
- Passed the complete 154-test editor suite.

## Prince DAT Explorer v0.4.23 - 2026-08-30

- Added **NTSC Composite** to both comparison-window mode selectors.
- The new comparison mode uses the full-width New-CGA signal decoder with
  neighboring-pixel artifacts; the existing **Composite** mode remains the
  idealized 160-column cell view.
- Passed the complete 153-test editor suite.

## Public editor release - 2026-08-30

- Published Prince DAT Explorer v0.4.22 as standalone Windows x64 and Python
  source packages.
- Verified both package hashes, archive contents, licensing notices, and the
  complete 151-test editor suite before publication.
- Documented that the editor release contains no game data and is distinct
  from the planned full-install composite conversion utility.

## Workspace setup - 2026-08-30

- Consolidated Prince DAT Explorer v0.4.22 and runtime V15C-V19K into one
  VS Code-ready Git workspace.
- Added Codex project instructions, VS Code tasks, Windows setup scripts, and
  private-binary Git exclusions.
- Recorded the parked V19K health-icon absolute-phase defect.

## Prince DAT Explorer v0.4.22

- Clarified phase-aware sidecar saving throughout the UI.
- Added complete four-slot/schema-v5 save/reload regression coverage.
- Passed 151 tests and standalone Windows packaging verification.

## Runtime V19K

- Filled PHASE3 aliases 210-218 with images 216-218.
- Added direct health-icon selection and ordinary hurt-splash mapping.
- Known issue: direct health icons use the wrong absolute phase.

## Runtime V18F

- Added PHASE3 in native slot 9.
- Completed phase-aware coverage for all 216 playable Prince body images.
