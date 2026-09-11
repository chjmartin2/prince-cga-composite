# V24Y artwork workspace

For V24Z and DAT Explorer 0.6.1, see [Editing overlays](EDITING_OVERLAYS.md).
V24Z replaces the palace fill settings described below with painted DAT bases.
This page retains the older V24Y workflow for existing packages.

Prince DAT Explorer 0.6.0 retains the existing composite image editor and adds
a complete graphics workspace for the experimental V24Y engine.

## Open, edit and exchange

1. Import `Composite-Artwork-V24Y.zip`, choosing a parent folder for a new
   workspace. Alternatively open `CDUNGEON.DAT` or `CPALACE.DAT` from the
   V24Y game test folder. The folder supplies its room preview metadata.
2. Choose **Dungeon Preview** or **Palace Preview**. **Game room** offers
   all 24 room slots in each applicable level. **Wall test board** displays
   the seventeen active pieces individually at their original dimensions.
3. Hover over a visible component for its DAT/resource name. Click it to
   select that image in the regular editor. Unsaved image and mask edits
   update the preview. Switching archives retains the workspace's edits.
4. In Palace Preview, select one of eight brick-fill slots, then choose one
   of the sixteen solid New-CGA swatches. Clicking a generated brick selects
   its fill slot. These settings are independent of image palettes.
5. Use **Export artwork ZIP** to save the complete workspace, including all
   DATs, editable projects, prepared DATs and palace settings. Send that ZIP
   back for the installer build. Importing it elsewhere restores the projects.

Closing an image editor retains its edits in the open workspace. Closing the
application offers to export unsaved workspace changes. Export a workspace
ZIP to preserve both images and palace colors; a standalone DAT export cannot
carry the EXE fill settings. Existing source DATs are protected.

## What the preview represents

The preview replays static draw instructions captured from the native DOS
engine: image order, fills, masks, clipping, wall-neighbor choices and room
decoration placement. It assembles the 640x200 signal before New-CGA NTSC
decoding and displays it at 4:3. The reference set matches all 336 captured
room-slot frames bit for bit. Characters, gameplay and animation playback
are outside this static artwork preview. Some unused room slots are empty.

Resource 1600 governs new wall images 1601–1617. The editor labels those
images, maps them to VGA/EGA reference IDs 361–377, and enforces P0 in the
matching wall profile. Original wall images 361–364 remain visible as inactive
legacy resources. Their edits do not change the active V24Y walls.

V24Y is the first version that normalizes the new back/foreground wall draws
to P0. The older V24X experiment only inherited the moving-sprite P0 hook;
its odd-X dungeon decorations could still land at P2. Use the matching V24Y
engine when judging these previews.

## Exchange contents

- Root DATs: protected source archives, including reference/runtime companions.
- `projects/*.json`: editable image, phase and transparency data.
- `patched/*.DAT`: prepared images that the builder installs.
- `WALLS.JSON`: eight exact four-bit palace carrier choices and preview RGBs.
- `PREVIEWS.JSON`: the authenticated native room draw recipes.
- `ARTWORK.JSON`: format/engine contract, source identities and file hashes.

The exact carrier is authoritative; RGB swatches are previews. No EXE offsets,
code bytes, or executable are supplied by the artwork package. The supported
builder validates the package, verifies resource geometry and protected DAT
tables, patches the known EXE table, and embeds the outputs in INSTALL.EXE.

The DOS game folder calls its editor metadata `WALLS.JSN` and `PREVIEW.CPR`
to obey 8.3 filenames. The latter is compressed room recipe data. The editor
reads these automatically and restores the ordinary JSON names on ZIP export.
