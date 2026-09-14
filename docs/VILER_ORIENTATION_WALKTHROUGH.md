# Editing cinematic and two-direction artwork

**Current: Explorer 0.6.4 / runtime V29.** Linked workspaces now offer
**Export Left/Right folders** and **Import Left/Right folders**. Select a
parent folder to export the current family, edit the indexed GIFs under
Left and Right, retain ORIENT-FOLDERS.JSON, then import the family folder.
Missing images and other families stay unchanged; the batch is one undo
action. Finally export the complete ORIENT.DAT. See
[the folder walkthrough](../editor/docs/DIRECTION_FOLDERS.md).

The native audit confirms both directions are required for princess PV/801
and story-Vizier walking PV/851-856. Other scripted poses do not all need
both, but complete ORIENT banks remain preserved. See
[the scene and resource evidence](CUTSCENE_FACING_AUDIT.md).

The earlier walkthrough below was checked against Explorer 0.6.3 and runtime V25 on
2026-09-12. V25 uses the V24Z game engine and graphics unchanged.

## What comes from which file

ORIENT.DAT holds both Right/P0 and Left/P0 versions of the mapped Kid,
ordinary guards, Fat Guard, Vizier, and PV animated actor families. It is not
just a collection of mirrored alternatives. For those mappings the game
replaces the native actor tables with ORIENT tables. Static PV backgrounds
remain in PV.DAT. Skeleton and Shadow retain their separate native paths.

Mapped PV image ranges are 801-817, 851-888 and 901-930. Example: original
PV frame 801 maps to ORIENT 7001 for Right/P0 and 7018 for Left/P0. PV's
950 background table is not replaced by these actor mappings.

Both actor directions draw at P0. Right-facing rendering still applies the
engine's source-pixel-group reversal, and its stored artwork compensates for
that operation. Left draws in stored order. Mirroring the composite bitstream
can change its colors, so use the editor's Left / Right runtime preview to
judge the actual result; do not manually reverse the DAT bytes.

## Customized source archives are supported

Editor 0.6.3 removes the default stock whole-file SHA-256 restriction for PV,
GUARD, FAT and VIZIER, extending the custom-source workflow already available
for KID. Valid edited backgrounds and actor pixels are accepted. Resource
checksums, complete mapped actor images and matching width/height/depth against
ORIENT remain required. A damaged or structurally incompatible resource gives
a specific compatibility error rather than requiring stock artwork.

The linked source remains a read-only visual/conversion reference in this
workspace. Opening a customized PV does not automatically copy its actor
pixels into ORIENT, and exporting ORIENT does not rewrite the PV backgrounds.

## Working sequence in the current editor

1. Keep a backup of your modified PV.DAT and latest complete ORIENT.DAT.
   Use those current working files; a separate stock PV reference is optional.
2. Open your modified PV.DAT and choose Editor. Select the latest ORIENT.DAT
   when prompted, or let the editor find the copy beside PV.DAT.
3. Select a mapped frame, for example PV resource 801. In the orientation bar
   choose Right / P0 or Left / P0. The normal editing/import/conversion tools
   operate on that direction's ORIENT image.
4. Use Left / Right runtime, or Show Left / Right runtime, to inspect both
   actual game-facing results. Edit the other direction separately. Do not
   expect changing one direction to update the other automatically.
5. Export complete ORIENT.DAT to a new staging destination. This writes all
   nine tables and 880 images; untouched resources retain their compressed
   payload bytes. It does not modify PV.DAT or replace the backgrounds.
6. Test using the patched PV.DAT plus this newly exported ORIENT.DAT in the
   same game folder. For the next editing session, link to the newest export,
   rather than the earlier distributed ORIENT.DAT.
7. When moving between actor families, close the old editing workspace and
   open the next family against that latest complete export. Exports from
   two sessions opened against an older file are separate snapshots, not an
   automatic merge; an older export could discard another session's edits.

For an existing hand-painted composite actor, opening a customized base DAT
is not an automatic import of those pixels into ORIENT. The mapped runtime
artwork is already in ORIENT and must be edited/imported there. Likewise,
conversion from the selected source reference is an explicit operation; it should
not be run over completed hand-painted directions unless desired.

The partial PV attachment mentioned in the report was not available in this
session, so its particular resource changes have not been inspected/applied.
