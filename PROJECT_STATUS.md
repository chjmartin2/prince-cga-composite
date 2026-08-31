# Project Status

Updated: 2026-08-30

## Runtime candidate: V20V command-tail forwarding

Run `runtime/build/Prince-1.3-New-CGA-V20V-Command-Tail-Sword-Dungeon-Version-B-DAT-Set/CGA4K2V.COM`.
For cheat-enabled testing, run `CGA4K2V.COM improved`.

V20V changes only the loader and the executable's visible version marker. The
DOS EXEC parameter block now points to the parent PSP command tail at `CS:0080`
instead of its private empty tail at `CS:0586`, so launcher arguments reach
Prince. All 32 DAT archives, executable runtime code, V19L mappings, and the
confirmed V20U shared sword are byte-identical. DOSBox confirmation of normal
and `improved` startup remains pending.

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
`scripts\install-v20v-dosbox.ps1` to replace it with an exact, hash-verified
copy of V20V; the installed launcher is `CGA4K2V.COM`.

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
| V20V | Loader forwards its PSP command tail; static verification passed, DOSBox confirmation pending. |

V20U remains the current DOSBox-confirmed sword baseline. V20V is the current
test candidate layered over it. V19K is structurally verified but carries the
health-icon defect above; V19L's focused correction remains documented
separately.

## Editor baseline: v0.4.27

Prince DAT Explorer v0.4.27 source is under `editor/`.

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
- 169/169 tests pass for the current source baseline.
- The standalone Windows x64 and Python source packages are published as
  [v0.4.27](https://github.com/chjmartin2/prince-cga-composite/releases/tag/v0.4.27).
- Local copies remain under `releases/` and are excluded from Git.
- The standalone executable is not code-signed.

Standalone release SHA-256:

```text
c6745f4ac5f199d20259c0f7a35f52c94e0cf2f81aa19b0a51ff71739dc640d7
```

Source release SHA-256:

```text
defc1735d81bb46622bf0ce2911bef44f487629153b36d4aeeeaecb791fdff68
```

## Remaining graphics after KID

The moving sword is complete without phase variants. Continue with guards, fat
guard, skeleton, Shadow, Jaffar, selected torch/potion exceptions, and cinematic
actors. The skeleton audit suggests one shared black/white treatment may also
be sufficient. See `docs/PHASE_COVERAGE.md`.
