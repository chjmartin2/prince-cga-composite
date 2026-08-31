# Changelog

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
- Arguments now reach Prince, so `CGA4K2V.COM improved` can enable the game's
  cheat/testing commands; DOSBox confirmation remains pending.
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
