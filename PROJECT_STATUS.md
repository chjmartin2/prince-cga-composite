# Project Status

Updated: 2026-08-31

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
`scripts\install-v20z-dosbox.ps1` to replace it with an exact, hash-verified
copy of V20Z; the installed launcher is `CGA4K2Z.COM`.

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

V20U remains the current DOSBox-confirmed sword baseline. V20V is the confirmed
loader baseline, V20W preserves the title fix, V20X is the confirmed floor fix,
and V20Z is the confirmed chomper-blood correction layered over V20Y's restored masks. V19K is
structurally verified but carries the
health-icon defect above; V19L's focused correction remains documented
separately.

## Editor source baseline: v0.4.28

Prince DAT Explorer v0.4.28 source is under `editor/`.

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
- 175/175 tests pass for the current source baseline.
- The standalone Windows x64 and Python source packages are published as
  [v0.4.28](https://github.com/chjmartin2/prince-cga-composite/releases/tag/v0.4.28).
- Local copies remain under `releases/` and are excluded from Git.
- The standalone executable is not code-signed.

Standalone release SHA-256:

```text
65bf58570ee479bfba1c7cbc80e9edce69dcffe91c447a093d06435d18ddf976
```

Source release SHA-256:

```text
42d622275e355562e654730524180e3d6d21980d7073c11f9aefd6e37def9f82
```

## Remaining graphics after KID

The moving sword is complete without phase variants. Continue with guards, fat
guard, skeleton, Shadow, Jaffar, selected torch/potion exceptions, and cinematic
actors. The skeleton audit suggests one shared black/white treatment may also
be sufficient. See `docs/PHASE_COVERAGE.md`.
