# Project Status

Updated: 2026-08-30

## Runtime baseline: V19K

Run `runtime/build/Prince-1.3-New-CGA-Phase-Aware-V19-PHASE3-All-219-KID-Dungeon-Version-B-DAT-Set/CGA4K19.COM`.

V19K extends V18F so all 219 `KID.DAT` images have phase-aware coverage:

- Images 0-215: complete playable Prince body coverage from V18F.
- Images 216-217: full and empty Prince health icons.
- Image 218: Prince hurt/blood splash.
- `PHASE.DAT`, `PHASE2.DAT`, and `PHASE3.DAT` contain all alternate aliases.

Verified V19K ZIP SHA-256:

```text
864cd0f9147549f37d5d4c01b4c36b96512e32c7b599520b398d0500b370973a
```

### Known V19K defect

The health icons all render with the same apparent phase, proving the dedicated
HP selector is alternating the source data. Their absolute phase is reversed
for the direct-blit path. The planned V19L change is to swap only the HP rule:

- screen positions 1/3: use the PHASE3/P2 artwork;
- screen positions 2/4: use the KID/P0 artwork.

Do not change the hurt-splash mapper or any V18 motion mapping as part of this
fix. Chris chose to park this correction while organizing the repository.

## Confirmed runtime history

| Version | Confirmed result |
| --- | --- |
| V15C | Stable live native PHASE table; covered run, jumps, and turns. |
| V16F | Added fall and landing block. Held crouch confirmed correct. |
| V17 | Added full PHASE2 table: jump/grab/hang, stand-up, careful step, climb, draw-sword body. |
| V18F | Added PHASE3 and completed all 216 playable Prince body images. All tested motions worked. |
| V19K | Added health icons and hurt splash; health icons use the wrong absolute phase. |

V18F is the last fully runtime-confirmed visual baseline. V19K is structurally
verified but carries the health-icon defect above.

## Editor baseline: v0.4.22

Prince DAT Explorer v0.4.22 is under `editor/`.

- `Ctrl+S` saves a phase-aware `.pdcproj` sidecar.
- The sidecar stores every edited image and every stored P0-P3 slot, including
  disabled-but-retained slots.
- `Save patched DAT` writes only the chosen fallback variant.
- 151/151 tests passed at release.
- The standalone Windows x64 and Python packages are published in the
  [v0.4.22 GitHub release](https://github.com/chjmartin2/prince-cga-composite/releases/tag/v0.4.22).
- Local copies remain under `releases/` and are excluded from Git.
- The standalone executable is not code-signed.

Standalone release SHA-256:

```text
21daf813d33f1edc8e13e43802b6f19b17d8a40e595e26c266c5d6d6e7966d59
```

Source release SHA-256:

```text
d58dc7cfd3a0b38db5228ef93c366aef0234d00a479b3d81a70a2409d85d0cf0
```

## Remaining graphics after KID

The next high-value work is the separately drawn sword overlay in
`PRINCE.DAT`, followed by guards, fat guard, skeleton, Shadow, Jaffar, selected
torch/potion exceptions, and cinematic actors. See `docs/PHASE_COVERAGE.md`.
