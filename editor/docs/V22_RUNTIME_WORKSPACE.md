# V22 Runtime Workspace contract

Prince DAT Explorer 0.5.2 treats V22 actor graphics as one linked authoring
unit with two roles:

- the opened actor DAT is a read-only visual reference;
- the complete V22 `ORIENT.DAT` is the only editable/exported archive.

KID deliberately accepts the existing/custom `KID.DAT`; resources 401–619 and
every paired frame geometry are validated instead of imposing a stock-file
hash. GUARD, FAT, VIZIER, and PV retain their standard Prince 1.3 hash check
because those conversions explicitly use the original VGA art as authority.

V22 authoring is integrated into the established six-pane Composite Editor;
it is not a reduced or separate editor. The normal VGA/EGA/CGA inputs,
Mode-6/rough Composite/NTSC outputs, converter modes, per-pane GIF import and
export, transparency tools, palette controls, and undo/redo remain available.
An orientation selector chooses which ORIENT image those tools edit, while a
second in-window tab shows Right/P0 and Left/P0 together.

The UI renders the executable's actual P0 paths. Right-facing output reverses
whole two-sample Mode-6 groups because Prince flips 4-bit source pixels, not
individual carrier samples. Left-facing output uses stored order directly.
Native 1-bit placeholders reverse one-sample groups. This transform is also
inverted when a user paints the Right view, so the click changes the intended
on-screen sample rather than the opposite end of the stored row.

## Fixed resource map

| Original source | Context | Right/P0 | Left/P0 |
|---|---|---:|---:|
| KID 401–619 | all | 1001–1219 | 2001–2219 |
| GUARD 751–784 | dungeon | 3001–3034 | 3035–3068 |
| GUARD 751–784 | palace | 4001–4034 | 4035–4068 |
| FAT 751–784 | all | 5001–5034 | 5035–5068 |
| VIZIER 751–784 | all | 6001–6034 | 6035–6068 |
| PV 801–817 | early cinematic | 7001–7017 | 7018–7034 |
| PV 851–888 | early cinematic actors | 8001–8038 | 8039–8076 |
| PV 901–930 | late cinematic actors | 9001–9030 | 9031–9060 |

Headers 1000 through 9000 retain their embedded hardware tables. In
particular, table 3000 supplies the dungeon Guard translation and table 4000
the palace Guard translation. Skeleton and Shadow have no mapping because the
V22 executable deliberately leaves them on native shared graphics.

## Exhaustive conversion

Both directions target carrier phase P0 with the New-CGA signal decoder,
exhaustive row search, no dithering, full color/detail weighting, and an exact
index-zero silhouette. The left target is the original VGA raster. The right
target is its horizontal mirror; the resulting signal bits are then stored in
the compensating group-reversed order expected by Prince's right draw path.

## Complete export invariant

The workspace opens only a companion containing exactly 889 resources in the
fixed order above: nine 100-byte table headers and 880 images. Each header's
image count is checked. Every mapped source/right/left triple must decode and
have identical width, height, and depth.

Export is Save-As only and cannot overwrite either linked input. The writer
starts with the full companion, replaces only changed image payloads, and
preserves all other payload bytes. The temporary output is reopened before it
is installed. The editor verifies exact resource order/count, all checksums,
image decoding, and the translated Mode-6 stream of every visited/edited
resource. A structurally incomplete or sparse archive is never emitted.

Legacy `.pdcproj`, fallback phase selection, manual/engine phase policy,
P0–P3 cycling, phase GIF sets, and phase manifests remain supported by the
same Composite Editor for old projects, but none are presented as V22
authoring controls. The main **Editor…** command opens this integrated mode
for KID, GUARD, FAT, VIZIER, and PV when a complete ORIENT companion is linked;
cancelling companion selection leaves the established phase-sidecar workflow
available.
