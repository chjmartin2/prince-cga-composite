# Runtime Build Workflow

Run commands from the repository root using the `.venv` Python interpreter.

## Rebuild the current V20Z chomper-blood color test

```powershell
.\.venv\Scripts\python.exe runtime\build_v20z.py
```

V20Z verifies V20Y, preserves every DAT, and changes only the CGA mono
color-12 scanline table from `AA AA AA AA` to the mask-aware New-CGA pattern
`C4 C4 C4 C4`. Reproduce the 256-pattern in-use analysis with
`runtime\analyze_chomper_blood.py`. See `CHOMPER_BLOOD.md`.

## Rebuild the V20Y stencil baseline

```powershell
.\.venv\Scripts\python.exe runtime\build_v20y.py
```

V20Y verifies the complete V20X package and restores only `CDUNGEON.DAT`
resources 1314-1323 from the original archive. These are native one-bit
stencils painted by mono color 12, not ordinary images whose bits can be
composite-optimized. See `CHOMPER_BLOOD.md`.

## Rebuild the confirmed V20X floor-overlay baseline

```powershell
.\.venv\Scripts\python.exe runtime\build_v20x.py
```

V20X verifies the complete V20W package and changes only `CDUNGEON.DAT`
resources 232, 350, and 351. It restores their original transparency masks
while proving that every translated CGA/Mode-6 value remains unchanged. See
`FLOOR_OVERLAY_OCCLUSION.md`.

## Rebuild the V20W title-resource baseline

```powershell
.\.venv\Scripts\python.exe runtime\build_v20w.py
```

V20W verifies the complete V20V package, uses Amir's 2026-08-30 `TITLE.DAT`
and `CDUNGEON.DAT`, and restores only resource 54's original index-zero mask
over Amir's title artwork. The build proves that all authored pixels outside
the mask remain unchanged and that opaque black remains distinct from
transparency. See `TITLE_RESOURCE_54.md`.

## Rebuild the confirmed V20V command-tail baseline

```powershell
.\.venv\Scripts\python.exe runtime\build_v20v.py
```

V20V verifies the complete V20U package, keeps every DAT and all executable
runtime code unchanged, and repoints only the loader EXEC command-tail pointer
from `CS:0586` to the parent PSP tail at `CS:0080`. Use
`CGA4K2V.COM improved` to test cheat-parameter forwarding.

## Rebuild the confirmed V20U sword baseline

```powershell
.\.venv\Scripts\python.exe runtime\build_v20.py
```

V20U verifies the complete V19L package, preserves its runtime mappings, and
replaces only `PRINCE.DAT` resources 701-734. The exhaustive search uses one
shared P0/P2 objective and is constrained to each source pixel's actually
representable two-bit CGA codes.

## Rebuild the V19L baseline

V19L is a focused deterministic patch over the verified V19K package:

```powershell
.\.venv\Scripts\python.exe runtime\build_v19l.py
```

It verifies the complete V19K input manifest, changes only the HP parity branch
and visible version marker in the executable, preserves all DAT archives, and
checks the output ZIP.

## Install the current build into DOSBox

`C:\DOS\POP_CP` is the disposable DOSBox deployment directory. Install V20Z
with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-v20z-dosbox.ps1
```

The installer accepts no target argument. It verifies the V20Z package and
required-file hashes, resolves the target as exactly `C:\DOS\POP_CP`, removes all
existing contents, copies the complete current package, and then verifies that
every deployed file and hash matches the build. Never point this cleanup
workflow at an original game archive directory.

## Rebuild the V19K predecessor

The handoff includes the verified V18 predecessor, so the focused rebuild is:

```powershell
.\.venv\Scripts\python.exe runtime\build_v19.py
```

This is intentionally exhaustive and may take time. The builder validates
source hashes, mappings, transparency, binary hooks, resource counts, visual
verification output, and deterministic packaging.

## Rebuild the full incremental chain

```powershell
.\.venv\Scripts\python.exe runtime\build_v15c.py
.\.venv\Scripts\python.exe runtime\build_v16.py
.\.venv\Scripts\python.exe runtime\build_v17.py
.\.venv\Scripts\python.exe runtime\build_v18.py
.\.venv\Scripts\python.exe runtime\build_v19.py
.\.venv\Scripts\python.exe runtime\build_v19l.py
.\.venv\Scripts\python.exe runtime\build_v20.py
.\.venv\Scripts\python.exe runtime\build_v20v.py
.\.venv\Scripts\python.exe runtime\build_v20w.py
.\.venv\Scripts\python.exe runtime\build_v20x.py
.\.venv\Scripts\python.exe runtime\build_v20y.py
.\.venv\Scripts\python.exe runtime\build_v20z.py
```

Each later builder imports constants and helpers from its predecessor. Preserve
the filenames and execution order.

## Runtime acceptance

Static verification is necessary but not sufficient. A new version is not
confirmed until tested in DOSBox in both directions, at adjacent X positions,
through level transitions, restarts, cinematics, and the affected motion or HUD
path.
