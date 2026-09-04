# Project Status

Updated: 2026-09-04

## Prince DAT Explorer v0.5.1 V22 Runtime Workspace implemented

The editor now opens an original Prince 1.3 actor DAT and complete V22
`ORIENT.DAT` as one linked workspace. It understands every dedicated mapping,
including dungeon/palace Guard contexts, and shows only the real Right/P0 and
Left/P0 runtime outputs beside the read-only VGA reference. Skeleton and
Shadow remain explicitly on their shared native paths.

Both direction views are directly editable. One-frame Right/Left/Both actions
use the exhaustive New-CGA optimizer and locked source-zero geometry. Export
always writes a complete 889-resource Save-As archive, preserves untouched
payload bytes, and verifies the V22 layout, checksums, decoding, and translated
bitstreams after reopen. The workspace contains none of the superseded phase
bank, fallback, sparse-DAT, phase GIF, or phase-manifest controls. Legacy
`.pdcproj` files remain available through the general editor for migration.

The runtime-only contact sheet contains actual Right/P0 and Left/P0 panels.
The normal Editor command routes all five mapped actor families directly into
this workspace; the old P0–P3 editor is explicitly labeled as legacy. Seven
new unit tests bring the complete editor suite to 191/191 passing.

The v0.5.1 correction removes the stock Prince 1.3 SHA restriction from
`KID.DAT`. An existing/custom KID archive is accepted when it contains the
complete 401–619 mapping and every frame matches the paired ORIENT geometry.
The other original-VGA actor sources retain their authentication. The complete
suite now passes 192/192.


## DOSBox-confirmed V21E original-memory ending diagnostic

Run
`runtime/build/Prince-1.3-New-CGA-V21E-Original-Memory-Ending-Test/CGA4K21E.COM improved 14`.

V21D's level-14 phase-bank bypass improved the symptom from a static first
frame to several reunion frames, but the animation still locked while the
music completed. The executable continued to reserve 9,036 DOS paragraphs and
768 startup-heap bytes for the resident phase extension.

V21E is an ending-only isolation build. It removes every phase hook and added
relocation, restores the original 9,005-paragraph allocation and original heap
start, and keeps the current V21B/V20Z DAT set, red pattern, torch placement,
and command-tail forwarding. It deliberately uses ordinary `KID.DAT` graphics
and is not yet a normal-play solution. Chris confirmed the complete reunion,
mouse entrance, fade, ending title, and music. The matrix-like corruption that
overlaid the loading screen in phase builds is also absent. This proves the
remaining resident phase-code/heap reservation is the failure source and that
the overlay was memory corruption rather than intentional artwork.

Deterministic V21E ZIP SHA-256:

```text
8f7d4d0ed89b4c5d8fc5437dd70a3183ea0fc4e77833eec75df9ae6b1f05f10b
```

## Rejected V21D ending-memory candidate

Run `runtime/build/Prince-1.3-New-CGA-V21D-Ending-Memory-Safe/CGA4K21D.COM`.
Test the final reunion directly with `CGA4K21D.COM improved 14`.

DOSBox-X bisection reproduced the final-reunion failure in V15C, V16F, V17,
V18F, V20V, V20X, and V20Z, while unmodified Prince 1.3 completed the hug,
mouse entrance, fade, and ending title under the same configuration. V14
showed a separate alternating-line corruption and was excluded as a control.

The bisection reached an explicit `Insufficient Memory` failure in V17 and
again when the current runtime used original `KID.DAT`. Replacing `PV.DAT` or
`KID.DAT` did not correct the ending. V21C's selector gate was also rejected in
DOSBox: it left a static first frame, let the music finish, and returned to DOS.
Together these results point to conventional-memory pressure rather than bad
compressed animation resources or selector use during the cutscene.

Prince frees graphics slots 3 through 9 while entering a level. V21D changes
the phase loader so that, on level 14 only, it does not repopulate slots 3, 4,
and 9 with the three decoded phase banks. The reunion therefore keeps that
memory available and uses ordinary `KID.DAT` graphics. Levels 1 through 13
retain the existing phase loader, selector, and HP helper unchanged.

All 32 DAT archives are byte-identical to V21B. V21B torch/holder positions,
V20Z blood/potion colors, V20U sword graphics, V20V command-tail forwarding,
and the V18F/V19L gameplay mappings are preserved. Static verification covers
the `current_level` signatures at `DS:10B0`, 24 modeled level/mode cases, exact
patch scope, hashes, package contents, and ZIP integrity. Chris must confirm
both the complete reunion and ordinary phase-aware gameplay in DOSBox before
V21D is called runtime-fixed.

Deterministic V21D ZIP SHA-256:

```text
a928bd11f92a6595700e56104095e1ad5b37dcf19af5e31a21f2a92ac34a6040
```

V21C remains documented as a rejected diagnostic in
`docs/ENDING_CUTSCENE_PHASE_SLOTS.md`.

## Statically verified V21B outward cinematic torches

Run `runtime/build/Prince-1.3-New-CGA-V21B-Cinematic-Torches-Outward/CGA4K21B.COM`.
For cheat-enabled testing, run `CGA4K21B.COM improved`.

V21/V21A moved both princess-room torch assemblies right. V21B instead moves
them outward from their original positions: the left flame moves X=93 to X=92
and the right moves X=211 to X=212. Both remain even-position P0 draws. The
matching holders baked into `PV.DAT` resource 951 move original-1/original+1.

Relative to V21A, only the left flame-coordinate byte and left holder pixels
change. The right assembly, other PV resources, other 31 DAT archives, runtime
code, command-tail forwarding, and every earlier fix remain unchanged. Static
and deterministic verification passes; Chris must confirm the spacing in DOSBox.

Deterministic V21B ZIP SHA-256:

```text
9c8591b30db6ac41126375078f96983776db313b998810eeb05dd5edc9120bc1
```

## DOSBox-tested V21A same-direction holder alignment

Run `runtime/build/Prince-1.3-New-CGA-V21A-Cinematic-Torch-Holders-Aligned/CGA4K21A.COM`.
For cheat-enabled testing, run `CGA4K21A.COM improved`.

Chris confirmed V21's animated flames have the correct color after moving to
X=94/212, but their static holders remained one pixel left. Those holders are
not separately positioned engine objects: both are baked into full-screen
`PV.DAT` resource 951. V21A moves only their 15-row shapes one source pixel
right while leaving the adjacent wall and rail texture fixed.

Exactly 90 decoded pixels change in resource 951. Every other PV resource, the
other 31 DAT archives, V21 flame coordinates, executable runtime code,
command-tail forwarding, and all earlier fixes are preserved. DOSBox testing
showed the holders follow the flames, but both complete assemblies moved right;
V21B corrects the pair spacing by moving the left assembly outward.

Deterministic V21A ZIP SHA-256:

```text
d1368e9ed8eeed0416a86fc26f93c48b8262cf47a35d1d3c86daf6a7986bb546
```

## DOSBox-confirmed V21 cinematic-flame P0 color

Run `runtime/build/Prince-1.3-New-CGA-V21-Cinematic-Torches-P0/CGA4K21.COM`.
For cheat-enabled testing, run `CGA4K21.COM improved`.

Gameplay torch flames use even X positions and therefore P0. The same
`PRINCE.DAT` resources 151-159 were drawn in princess-room cinematics at odd
X=93 and X=211, forcing P2. V21 changes only the two
`princess_torch_pos_xl` low bytes from 5/3 to 6/4, moving the flames one CGA
pixel right to X=94/212. All shared flame use is now P0, so no flame phase bank
is needed.

All 32 DAT archives and every other V20Z executable runtime byte remain
unchanged. The command-tail loader and every earlier confirmed fix are
preserved. Static verification and deterministic rebuild pass. Chris confirmed
the flame colors; V21A corrects the resulting holder-centering mismatch.

Deterministic V21 ZIP SHA-256:

```text
2af3893b0b70813b0b36ddb4a3c1b877e97e5f22549d3716a84cf75b66b54049
```

## DOSBox-confirmed V20Z chomper-blood NTSC pattern

Run `runtime/build/Prince-1.3-New-CGA-V20Z-Chomper-Blood-NTSC-Pattern/CGA4K2Z.COM`.
For cheat-enabled testing, run `CGA4K2Z.COM improved`.

V20Y proved that the original stencils were damaged, but DOSBox testing showed
that restoring them exposed a second defect: only a little yellow appeared on
the floor and the blade remained grey. The active CGA mono table maps nominal
red color 12 to `AA AA AA AA`; forced Mode 6 interprets repeating `10101010`
as neutral grey, with yellow transition ringing.

V20Z evaluates all 256 byte patterns over all ten exact masks at their actual
positions on the five bottom/front blade frames. It changes the four color-12
rows to `C4 C4 C4 C4` (`11000100`). Predicted New-CGA mean RGB is `(181,56,51)`
on the wider rear/floor pass and `(146,65,78)` on the narrow foreground blade.
Every DAT archive and every other executable runtime byte preserves V20Y.
Static verification passes; Chris confirmed that chomper blood and potion
bottles both render red in DOSBox.

Deterministic V20Z ZIP SHA-256:

```text
598fef7ed39702ba7d85cee778df3022ed04f05ed9eceb741dc0f2127eab2b5c
```

## DOSBox-tested V20Y stencil restoration (color insufficient)

Run `runtime/build/Prince-1.3-New-CGA-V20Y-Chomper-Blood-Stencils/CGA4K2Y.COM`.
For cheat-enabled testing, run `CGA4K2Y.COM improved`.

V20Y restores `CDUNGEON.DAT` resources 1314-1323 byte-for-byte from the
verified original game archive. These ten native one-bit images are stencils:
Prince's mono blitter paints their set bits with hard-coded color 12, which the
New-CGA Mode-6 driver expands to repeating pattern `1100`. The composite
conversion had incorrectly optimized the masks themselves, reducing them from
498 set bits to 223. V20Y recovers all 275 missing bits.

All blood frames are drawn at `32*tile_column+12`, always P0, so no phase
variants are required. Every other CDUNGEON resource, every other DAT archive,
and all V20X executable runtime code are preserved. Chris tested V20Y in
DOSBox: the blade stayed grey and only a little yellow appeared on the floor,
proving that the mono color pattern also needed correction.

Deterministic repaired `CDUNGEON.DAT` SHA-256:

```text
b5459688c0d4618208fe6a3d233b0eaea18f51153b861195940fe940ea4d8536
```

Deterministic V20Y ZIP SHA-256:

```text
cf2f522bf8ef344de44de980ea42d97ae604d935962725d1b58806505eead7a8
```

See `docs/CHOMPER_BLOOD.md` for the engine and resource trace.

## DOSBox-confirmed V20X floor-overlay occlusion

Run `runtime/build/Prince-1.3-New-CGA-V20X-Floor-Overlay-Occlusion/CGA4K2X.COM`.
For cheat-enabled testing, run `CGA4K2X.COM improved`.

V20X repairs `CDUNGEON.DAT` resources 232, 350, and 351, which are the
transparent overlays drawn in front of Prince during climbing frames. Amir's
artwork used index zero for 66 black signal samples inside the original opaque
silhouettes. Those samples now use opaque index 4, which translates to the same
CGA `00` value. The complete Mode-6 bitstreams are unchanged, the original
masks are restored exactly, and resource 268 remains byte-identical because it
is the gate-top mask. Chris confirmed in DOSBox that the reported transparent
floor during the tower climb is fixed.

Deterministic repaired `CDUNGEON.DAT` SHA-256:

```text
1466914150b8f66494240e20486b236d3b7b648ec0a3d1cbb093223614569a14
```

Deterministic V20X ZIP SHA-256:

```text
7c1832b147304b39b6dc2b8967165523d14d1aa0709c58296e08cb5def579867
```

If only a big-pillar-top tower arrangement still fails, the remaining cause is
the original engine's floor-overlay draw condition, not the DAT mask. See
`docs/FLOOR_OVERLAY_OCCLUSION.md`.

## Preserved V20W title resource 54 transparency

Run `runtime/build/Prince-1.3-New-CGA-V20W-Amir-Title-R54-Transparency-CDungeon-WIP/CGA4K2W.COM`.
For cheat-enabled testing, run `CGA4K2W.COM improved`.

V20W integrates Amir's 2026-08-30 `TITLE.DAT` and current work-in-progress
`CDUNGEON.DAT`. Resource 54 restores the original 9,799-pixel index-zero mask
over Amir's title logo, removing 3,775 baked-background pixels while preserving
every authored pixel outside the mask, including 1,929 opaque-black outline
pixels. All other DAT archives and all executable runtime code are preserved
from V20V. Static verification passes; the normal title and high-score screen
still require DOSBox visual confirmation.

Deterministic repaired `TITLE.DAT` SHA-256:

```text
56e8fadd3b418bf2b73c2ca3233535fa936a8a910e8d253790f7b4af7fa04b62
```

Deterministic V20W ZIP SHA-256:

```text
08921b5f52f8cd2f69613b485810e217fdcb6c0c2c3fad5e95b396907c3dc069
```

## Confirmed V20V command-tail forwarding baseline

Run `runtime/build/Prince-1.3-New-CGA-V20V-Command-Tail-Sword-Dungeon-Version-B-DAT-Set/CGA4K2V.COM`.
For cheat-enabled testing, run `CGA4K2V.COM improved`.

V20V changes only the loader and the executable's visible version marker. The
DOS EXEC parameter block now points to the parent PSP command tail at `CS:0080`
instead of its private empty tail at `CS:0586`, so launcher arguments reach
Prince. All 32 DAT archives, executable runtime code, V19L mappings, and the
confirmed V20U shared sword are byte-identical. Chris confirmed both normal
startup and `CGA4K2V.COM improved`; pressing `C` in a level displayed the room
numbers, proving that the cheat parameter reached Prince.

Deterministic V20V ZIP SHA-256:

```text
c1fcf28ab2af1341025368bd4270a76368a7faf6c1dfe5c89d531eb3d50631b2
```

### Confirmed V20U shared moving sword baseline

Run `runtime/build/Prince-1.3-New-CGA-V20-Shared-P0-P2-Sword-Dungeon-Version-B-DAT-Set/CGA4K20.COM`.

V20U confirms the no-variant sword hypothesis. It preserves all
V19L runtime code and phase tables, and changes only moving-sword resources
701-734 in `PRINCE.DAT`. Each frame has one palette-representable exhaustive
pattern optimized jointly over reachable P0 and P2; no sword selector or new
sidecar DAT was added. The original index-zero transparency masks are restored.

The exact two-phase absolute-error objective improves from 18.822 to 17.768;
RMSE is effectively tied at 48.964 versus 49.294. Chris confirmed in DOSBox
that the sword looks great, including the colored hilt/detail sequence.

Deterministic V20U ZIP SHA-256:

```text
0e14fdb102c58aa45ab3944ac8ede99eadb12ec6cfc2e971dedf2f43b1b1cb2a
```

### Preserved V19L baseline

Run `runtime/build/Prince-1.3-New-CGA-Phase-Aware-V19L-HP-Absolute-Phase-Fix-Dungeon-Version-B-DAT-Set/CGA4K1L.COM`.

V19L retains V19K's phase-aware coverage for all 219 `KID.DAT` images and swaps
only the Prince health-icon direct-blit phase rule:

- Images 0-215: complete playable Prince body coverage from V18F.
- Images 216-217: full and empty Prince health icons; screen positions 1/3 now
  select PHASE3/P2 and positions 2/4 select KID/P0.
- Image 218: Prince hurt/blood splash.
- `PHASE.DAT`, `PHASE2.DAT`, and `PHASE3.DAT` contain all alternate aliases.
- All 32 DAT archives, the ordinary body mapper, the hurt-splash route, and both
  HP call hooks are byte-identical to V19K.

Verified deterministic V19L ZIP SHA-256:

```text
b133c33e243c8695be96973a3b9eda3ff7e78a51c0fec0c97d55df1dd545ba5b
```

### V19L runtime acceptance pending

Static/resource/machine-helper verification passes, including all 80 HP helper
cases and 10 lazy-load cases. Chris must still confirm the health icons and
hurt splash in DOSBox before V19L is called runtime-fixed.

The disposable DOSBox working directory is `C:\DOS\POP_CP`. Use
`scripts\install-v21c-dosbox.ps1` to replace it with an exact, hash-verified
copy of V21C; the installed launcher is `CGA4K21C.COM`.

## Confirmed runtime history

| Version | Confirmed result |
| --- | --- |
| V15C | Stable live native PHASE table; covered run, jumps, and turns. |
| V16F | Added fall and landing block. Held crouch confirmed correct. |
| V17 | Added full PHASE2 table: jump/grab/hang, stand-up, careful step, climb, draw-sword body. |
| V18F | Added PHASE3 and completed all 216 playable Prince body images. All tested motions worked. |
| V19K | Added health icons and hurt splash; health icons use the wrong absolute phase. |
| V19L | Swapped only the HP absolute-phase branch; static verification passed, DOSBox confirmation pending. |
| V20U | Shared P0/P2 sword overlay confirmed visually; no variants or runtime selector needed. |
| V20V | Loader forwards its PSP command tail; normal and `improved` launches confirmed in DOSBox. |
| V20W | Amir title/CDUNGEON integrated; title resource 54 mask statically verified, DOSBox visual check pending. |
| V20X | Floor-overlay masks restored without changing Mode-6 bits; tower climb confirmed fixed. |
| V20Y | Original chomper-blood stencils restored; DOSBox showed grey blade and a small yellow floor trace. |
| V20Z | Mono color 12 changed from grey `AA` to mask-aware red `C4`; chomper blood and potion bottles confirmed red. |
| V21 | Princess-room flames shifted from X=93/211 to X=94/212 so all torch use is P0; colors confirmed, holders became visibly off-center. |
| V21A | Baked holders shifted right to match V21 flames; alignment followed, but both assemblies moved in the same direction. |
| V21B | Left/right assemblies moved outward to original-1/original+1; static verification passed, DOSBox confirmation pending. |
| V21C | Added a cinematic guard to keep Kid draws out of phase-table slots reused by princess-room tables; static verification passed, DOSBox reunion confirmation pending. |

V20U remains the current DOSBox-confirmed sword baseline. V20V is the confirmed
loader baseline, V20W preserves the title fix, V20X is the confirmed floor fix,
V20Z is the confirmed chomper-blood correction layered over V20Y's restored
masks, and V21C is the current ending-safety test layered over V21B. V19K is
structurally verified but carries the
health-icon defect above; V19L's focused correction remains documented
separately.

## Editor source baseline: v0.5.2

Prince DAT Explorer v0.5.2 source is under `editor/`.

- For V22 actor archives, the established Composite Editor now links the
  original/custom source DAT and complete ORIENT companion directly. The
  reduced secondary editor introduced in v0.5.0 has been removed.
- Right/P0 and Left/P0 select the target behind the complete six-pane editor,
  converter dialogue, GIF interchange, transparency tools, palettes, and
  undo/redo. A second in-window tab shows both actual runtime outputs together.
- Right-facing screen/stored transforms are applied consistently during
  painting, hover inspection, conversion, rendering, and GIF round trips.
- Complete ORIENT export remains 889-resource, verified, and Save-As only.
- The main preview and comparison window offer a full-width, neighbor-aware
  **NTSC Composite** mode alongside the idealized 160-column **Composite** cell
  view.
- `Ctrl+S` saves a phase-aware `.pdcproj` sidecar.
- The sidecar stores every edited image and every stored P0-P3 slot, including
  disabled-but-retained slots.
- `Save patched DAT` writes only the chosen fallback variant.
- The exact encoder can restrict each source pixel to the CGA codes its DAT
  translation palette can actually represent.
- Mode-6 GIF import/export distinguishes opaque black from transparent black;
  phase sets share one validated authored mask, and mask changes undo atomically.
- The Mode-6 pane directly paints opaque white, opaque black, or DAT index-zero
  transparency and displays transparency in a user-selected solid color.
- GIF dialogs remember the last import/export folder for the editor session.
- Whole-archive Mode-6 GIF interchange exports every editable resource using
  numeric IDs, imports complete phase families atomically, and supports one-step
  bulk undo/redo.
- The generic animation contact-sheet export writes every editable image from
  whichever DAT is open, in stable archive order, with right/left and P0/P2
  panels. KID additionally receives its authoritative animation-family labels.
- The distinct resource/phase matrix remains available under its corrected
  name.
- 194/194 tests pass for the current source baseline.
- v0.5.2 standalone Windows x64 and Python source packages are deterministically
  built and ZIP-verified locally. The standalone GitHub release is published.
- Local copies remain under `releases/` and are excluded from Git.
- The standalone executable is not code-signed.

v0.5.2 standalone release SHA-256:

```text
0e7f008021a3a57c8fc75248db8cff7ada1b59659935b6d48219fdc7e86639a4
```

v0.5.2 source release SHA-256:

```text
aa5356f131616a0b86d335d88cb45b6f97e74d3446d233340532df637b1ee8e8
```

## Remaining graphics after KID

The moving sword and shared torch flames are complete without phase variants.
Continue with guards, fat guard, skeleton, Shadow, Jaffar, and cinematic actors.
The skeleton audit suggests one shared black/white treatment may also be
sufficient. See `docs/PHASE_COVERAGE.md`.
