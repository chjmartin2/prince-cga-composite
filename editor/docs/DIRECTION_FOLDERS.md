# Editing both directions in folders

Prince DAT Explorer 0.6.4 adds **Export Left/Right folders** and
**Import Left/Right folders** to a linked ORIENT workspace. These controls
are visible beside the direction controls and in the Mode-6 folder menu.

1. Open the current KID.DAT, GUARD.DAT, FAT.DAT, VIZIER.DAT or PV.DAT and
   choose Editor. Link the latest complete ORIENT.DAT when prompted.
2. Choose **Export Left/Right folders** and select a parent directory.
   The editor creates a family directory such as `PV`, with `Left`, `Right`
   and `ORIENT-FOLDERS.JSON` inside it.
3. Edit the indexed GIFs in either direction folder. Filenames use the
   familiar source resource IDs, for example `PV/Left/801.gif` and
   `PV/Right/801.gif`. GUARD includes `Dungeon` and `Palace` subdirectories
   inside each direction because those contexts share source IDs.
4. Keep the JSON mapping unchanged. Choose **Import Left/Right folders**
   and select the family directory or its parent.
5. Check the left/right runtime previews. The complete import is one undo
   action. Then **Export complete ORIENT.DAT** to a new staging file and
   test it in the game. The base DAT and its backgrounds stay unchanged.

## Exact image format

The GIFs contain the native 640-column composite bit pattern, not an RGB
approximation. They use the existing exact Mode-6 indexed GIF format:

- Index 0: opaque black sample.
- Index 1: white sample.
- Index 2: transparency (magenta palette entry).
- Index 3: reserved cyan; do not paint it.

Keep the exported dimensions, four-entry palette and transparency index.
Do not convert to RGB, optimize/reorder the palette, resize, or dither.
For ordinary 4-bit Prince images, both samples belonging to one source
pixel must agree on transparency. The importer reports partial-pixel masks
and invalid native image combinations before accepting any changes.

Both folders show **runtime display order**. The right direction already
includes the engine's source-pixel-group reversal, and the importer reverses
that transform when storing the edit. Do not manually mirror the GIFs to
compensate for the engine: reversing individual bits changes composite colors.
Edit Left and Right independently and judge colors in the runtime preview.

## Preserving the rest of ORIENT

Export covers the selected actor family and both directions. Opening another
family and exporting to the same parent creates its own separate directory.
An export never modifies the linked DAT. Existing generated export files
require confirmation before replacement; unrelated files remain untouched.

Import validates the mapping and every supplied GIF before changing the
workspace. Missing GIFs leave those resources unchanged, so a handoff may
contain only edited files plus the original mapping. Unmapped or duplicate
GIFs are rejected. Other actor families and untouched resource payloads remain
intact when exporting the complete ORIENT.DAT.

Always open the latest complete ORIENT.DAT before importing edits. Folder
import preserves the other resources in the workspace you opened; it does
not merge separate older DAT snapshots automatically. Retain the source GIF
folders and mapping with your artwork backups.
