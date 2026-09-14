# Editing wall overlays in DAT Explorer 0.6.1

## V27 / Explorer 0.6.4 update

V27 keeps dungeon overlays and disables palace overlays. Its **Palace Preview**
opens **Game room**, displays **Palace overlays disabled**, and offers the four
active base images (1601, 1602, 1618, 1619). Dungeon Preview retains its overlay
inspector and variations. The unused palace overlay images remain in the DAT
for artwork preservation. Older overlay-enabled workspaces still use the
full inspector described below.

Use the prepared **V24Z** test folder or `Composite-Artwork-V24Z.zip`.
The latest standalone CPALACE artwork supplied on September 9 contains 225
standard resources, so it has no experimental overlays by itself. V24Z retains
all of those payloads and adds the needed wall resources. An older V24Y engine
and that standard CPALACE file are not a matching preview/game package.

## Find and understand a variation

1. Open `CPALACE.DAT` or `CDUNGEON.DAT` from `POP24Z` / `C:\DOS\POP_V24Z`.
   Alternatively use **Import artwork ZIP** and select the V24Z artwork package.
2. Click **Palace Preview** or **Dungeon Preview**. The window opens in
   **Overlay inspector**, with a resource list on the left.
3. Select a named variation. The inspector uses its first occurrence in the
   chosen room. **Find in room** locates an example when it is absent there.
   Selecting a variation automatically finds a room if necessary.
4. Read the three panes: **Before overlay**, **Transparency mask**, and
   **Combined result**. Cyan means the image writes those pixels, including
   opaque black. Checkerboard means the background survives. The checkerboard
   is only a UI annotation; it never enters the game's composite signal.
5. Choose **Game room** to see the complete room, with occurrences of the
   selected resource outlined. **Base walls only** removes wall overlays.
   **Wall test board** shows the complete resource inventory.

The inspector shows one actual drawing operation, before later objects can
cover it. It decodes complete CGA frames before cropping, preserving composite
interactions with neighboring patterns. The game-room view shows final layering.

## Paint and exchange

Double-click a variation or choose **Edit selected image…** to open the existing
composite editor. **Composite bit** and the **1 / 0 / Transparent** brushes edit
the picture and its transparency. **0 (black)** is opaque; **Transparent** leaves
the underlying wall visible. The **Select transparent color…** control changes
only how transparency is displayed in the pixel editor.

Keep the preview open while painting. Unsaved pixel and mask edits update it.
Each named variation is its own DAT image. Switching to another resource retains
edits in the current workspace. **Export artwork ZIP** saves all DATs, projects,
prepared images and matching preview data for exchange and INSTALL.EXE builds.

Palace resources:

| IDs | Role |
| --- | --- |
| 1601–1602 | Current painted wall faces |
| 1603–1605 | Upper divider, variations 1–3 |
| 1606–1608 | Middle-upper divider, variations 1–3 |
| 1609–1611 | Middle-lower divider, variations 1–3 |
| 1612–1614 | Lower divider, variations 1–3 |
| 1615–1617 | Bottom-strip divider, variations 1–3 |
| 1618 | Painted bottom strip |
| 1619 | Painted full wall, including its bottom strip |

Dungeon resources 1611–1612 are transparent dividers; 1614–1617 are surface
marks. Resource 1613 is an **opaque replacement block**, labeled separately.
The original 361–364 resources are preserved; edit the active copies above to
change this engine's walls. Palace 1618 and the bottom of 1619 are separate
images, used in different drawing passes; keep their artwork coordinated.

There are no palace fill swatches in a V24Z workspace. The old swatches remain
visible only for older V24Y packages. V24Z's fifteen starting divider shapes are
the prior exhaustive, no-dither conversions; VileR can refine these over his
latest painted bases. This build supplies the composition and editing workflow,
with visual/playthrough acceptance still pending.
