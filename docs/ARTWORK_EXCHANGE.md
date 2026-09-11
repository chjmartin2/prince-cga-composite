# V24Y editor-to-installer artwork exchange

Runtime release: **V24Y experimental**. Editor release: **0.6.0**.
Branch: `experiment/vga-walls-composite`. V23G remains the normal distribution.

Chris approved selectable dungeon/palace rooms plus wall boards, a complete
graphics-project exchange ZIP, a test folder and a separate experimental
INSTALL.EXE. The familiar editor is extended with preview buttons, exact
palace carrier swatches, resource names, active/legacy distinctions and
VGA reference mapping. User instructions: `editor/docs/ARTWORK_WORKSPACE.md`.

## Build and deliver

```powershell
.\.venv\Scripts\python.exe runtime\build_v24y.py
.\.venv\Scripts\python.exe runtime\verify_v24y.py
.\.venv\Scripts\python.exe runtime\verify_artwork_exchange.py
.\.venv\Scripts\python.exe scripts\build_editor_release.py --version 0.6.0
```

To consume VileR's edited exchange:

```powershell
.\.venv\Scripts\python.exe runtime\build_v24y.py --artwork C:\path\VileR-Artwork.zip --output runtime\build\Prince-Composite-V24Y-Artwork
```

The supplied package contains the preview recipes; a custom artwork build
does not require the local raw capture cache. Generating the initial default
package uses `runtime/capture_room_recipes.py 1 2 3 4 5 6 7 8 9 10 11 12 13 14`.
Its canonical recipe SHA-256 is pinned in the builder. Historical game ZIPs
and the V24X baseline are authenticated and never overwritten.

Outputs under `runtime/build/Prince-Composite-V24Y/`:

- `POP24Y/`: complete game test folder.
- `POP_Composite_V24Y.zip`: exactly one file, INSTALL.EXE.
- `Composite-Artwork-V24Y.zip`: complete editor exchange starter.
- `MANIFEST.JSON`, `VERIFICATION.JSON`, `EXCHANGE-VERIFICATION.JSON`.
- `editor-qa/`: actual Tk workflow checks and captured windows.

`runtime/dosdist/releases/V24Y.json` supplies the frozen experimental version.
The normal `release.json` remains V23G. Installed labels identify only V24Y;
Prince 1.3 remains the required source version. Credits retain RetroComputerist,
ChatGPT and VileR. Existing directory selection, both progress bars, fixed
composite video, sound settings and launch-menu behavior remain intact.

## Exchange contract and preservation

`editor/artwork_workspace.py` owns the versioned ZIP format. It carries source
and prepared DATs, editable project JSON, WALLS.JSON, PREVIEWS.JSON and a
SHA-256 manifest. Re-export is deterministic: source IDs/order remain stable,
and volatile sidecar timestamps are omitted. Import uses a new workspace
folder. Duplicate paths, traversal, unknown members, bad hashes, malformed
tables, unsupported profiles and project/output disagreement are rejected.

The runtime builder compares all supplied DATs to the authenticated baseline.
Only images in explicitly supported graphics archives can change; resource
IDs, order, geometry, depth and non-image records remain fixed. Sound data,
level layouts and existing phase tables remain protected. Original existing
DAT payloads are byte-identical in the default release.

Palace settings identify the eight slots 61h–64h and 66h–69h symbolically.
Each stores one 0–15 carrier, expanded into four identical bytes with repeated
nibbles. Reserved slots remain zero. RGB is advisory preview metadata; no
conversion or dither is added at build time. The installer embeds the verified
patched EXE; it never interprets arbitrary patch offsets from an author.

## Native wall placement correction

Native replay exposed a mistaken V24X assumption: the existing P0 hook is in
`draw_mid`, not a global transparent-image hook. New dungeon dividers in
back/fore tables were still allowed at odd logical X (P2). V24Y corrects only
bank 7 before it calls the ordinary image drawing routine.

- Replace 0000:B4BA's eight bytes `8B C8 8A 47 01 98 03 C8` with a FAR call
  to 231C:0380 plus three NOPs.
- The 18-byte shim reproduces CX = 8*xh + signed xl, then clears CX bit zero
  only when the queue entry's bank is 7.
- Add one MZ relocation at 0000:B4BD; update the relocation count.
- Keep image size, allocation fields and the protected region's size unchanged.
- Use the already unused 0380–0391 area, clear of the CRT arena boundary link.
- Palace carrier data remains at 231C:0340. V22G's old fill table at 0230,
  loading-screen black, mono blood/potion table and actor hooks are untouched.
- Marker becomes `WALLS VGA V24Y`. `v24y_engine.py` authenticates every byte
  changed, the source SHA-256, and the complete allowed modification set.

## Preview proof and limits

The test-only TSR calls authenticated native room-link, palette-generation,
redraw and table-draw routines for each of 24 room slots at fourteen numbered
starts. It saves the generated queues and physical CGA VRAM. For level 2 only,
the fixture loads its layout through level 1's identical dungeon type to avoid
the original copy-protection redirect. That substitution is never shipped.

`editor/wall_preview.py` replays those queues with live project pixels and
zero masks. Native one-bit masks double horizontally and paint their set bits;
mono colors use the separate blood/potion table. After those details and the
bank-7 P0 correction, every reference frame matches all 128,000 signal bits.
Composite decoding happens after full-screen assembly. Previews are static
environment frames, with no character movement or live level editing.

Verification covers the complete editor unit suite; real Tk live-edit,
color-edit, resource-switch and exchange workflows; all 336 reference frames;
the original DOS installation/browser/sound suite; fourteen gameplay starts;
all 65,536 fill-color inputs; protected code/data after allocations; and the
unskipped reunion returning to ending text. The ending fixture's observer now
uses free offset 03A0 to avoid the shipping wall shim at 0380.

A separate end-to-end author test changes CDUNGEON/1611 and palace slot 61,
exports/imports the package, builds a separate installer, installs in DOSBox,
and compares the installed DAT and EXE pattern bytes with the editor output.
Default build/ZIP hashes reproduce exactly. Chris's visual/playthrough
acceptance remains pending; automated checks do not replace that acceptance.

Pinned default hashes:

```text
POPGAME.EXE 943cdc105a141f530ab9150e2a66ac487f3bd832b4ff20c3b888e838dd5c0724
INSTALL.EXE 9a9a0470d20bbec4bb8fb815310f375b1b926b01ce8f18a8a7534d78df8e78d0
ZIP         52f328bf41e876f460cf5755bb7f37d6d966c284e083c3b1f750f19f48f2c9d5
```
