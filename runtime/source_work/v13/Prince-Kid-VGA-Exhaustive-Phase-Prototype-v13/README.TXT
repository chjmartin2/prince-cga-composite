PRINCE OF PERSIA 1.3 - VGA EXHAUSTIVE PHASE-AWARE KID V13
======================================================

PURPOSE
-------

V13 corrects the stationary-turn frame map identified during DOS testing.
Prince 1.3 game frame 52 uses KID image 51. V12 incorrectly left image 51 on
the phase-0 fallback and treated image 64 as frame 52, so the last stationary-
turn image could visibly change phase. V13 maps the authoritative sequences:

  game frames 45..52  -> KID images 44..51  (stationary turn)
  game frames 53..65  -> KID images 64..76  (complete run-turn)

V13 retains V12's corrected right-facing storage transform: Prince reverses
original two-sample CGA pixels, not individual 640-column carrier bits.

The ordinary KID table now starts from the verified VGA/Exhaustive/No-Dither
phase-0 conversion. The 36 selected movement images then receive independent
direction/P0/P2 variants from the original VGA artwork. Thus every unselected
Kid image is optimized for phase 0 rather than copied from the original KID.

The build covers 36 stand, start-run, run, turn, and run-turn Kid images. Each
image has four independently encoded final-display cases:

                         even final X       odd final X
  moving/facing right    right / P0         right / P2
  moving/facing left     left / P0          left / P2

The selector runs after Prince computes the final 320-column screen X,
including the width subtraction on the right-facing path. Movement timing,
collision coordinates, clipping, and animation sequencing are unchanged.


WHAT IS INCLUDED
----------------

  CGA4K13.COM   Patched CGA composite launcher
  P4KX13.EXE    Patched US Prince 1.3 executable
  KID.DAT       Phase-0 KID baseline plus four-way selected-image variants
  MANIFEST.JSON Exact source hashes, image records, settings, and measurements

  visual-verification/VISUAL-RUN-STAND.png
  visual-verification/VISUAL-TURN.png
  visual-verification/VISUAL-RUN-TURN.png
  visual-verification/VISUAL-RIGHT-PHASE-TOGGLE.gif
  visual-verification/VISUAL-LEFT-PHASE-TOGGLE.gif
  visual-verification/VISUAL-RIGHT-STAND-CORRECTED.png

The deterministic builder, verifier, and visual renderer are in tools/.


INSTALLATION
------------

1. Use a backup copy of the converted New-CGA composite game folder.

2. Copy CGA4K13.COM, P4KX13.EXE, and KID.DAT into that folder. Leave every
   other DAT file in place.

3. Run CGA4K13. Do not start P4KX13.EXE or PRINCE.EXE directly.

4. Press Ctrl-V in the game. It must show:

      KID EXH V13       V1.3

   The launcher must print:

      KID EXHAUSTIVE V13 ACTIVE


VISUAL VERIFICATION FIRST
-------------------------

Open the three PNG contact sheets before running DOS. Every card contains:

  * the VGA target;
  * the independently optimized P0 result;
  * the independently optimized P2 result;
  * separate right- and left-facing rows.

Open the two GIFs to alternate the complete P0/P2 set. Look for major changes
in the Prince's hair, skin, belt, and white clothing. Small colored edge halos
are expected from the isolated black-background composite model.

VISUAL-RIGHT-STAND-CORRECTED.png enlarges the exact frame reported as purple
and shows the VGA target beside its corrected game-runtime P0 and P2 decodes.


DOS TEST ROUTE
--------------

At Level 1, exercise both directions:

  * stand after facing each way;
  * run through many X positions;
  * hold action and take individual steps;
  * turn in place repeatedly;
  * reverse direction while running.

For the reported regression, turn in place at several X positions and verify
that the final stationary-turn frame no longer changes color as it settles.

Expected behavior:

  * Prince points in the correct direction;
  * his dominant colors remain stable when X parity changes;
  * turns and run-turns use the same color family;
  * movement timing and geometry remain normal.

Jumping, climbing, crouching, sword fighting, falling, and all other unselected
Kid frames now use their single phase-0 VGA/Exhaustive/No-Dither conversion.
They are not yet phase-aware; a color change at an odd final X is expected
until each required action joins the P0/P2 runtime family.


ENCODING CONTRACT
-----------------

  source                 VGA rendering of original KID.DAT
  conversion             Exhaustive
  objective              exact minimum absolute RGB error for selected phase
  phase generation       independent P0 and P2 runs; no averaging/coupling
  composite model        New CGA
  dither                 none
  transparency           original source-index-zero silhouette locked exactly
  unselected images      VGA Exhaustive no-dither phase-0 baseline

The right-facing VGA target is mirrored before optimization. Its completed
Mode-6 rows are converted for storage by reversing two-sample CGA pixel groups
while preserving the bit order inside every group. This matches Prince's
source-pixel flip. Reversing individual carrier bits, as V11 did, causes the
purple/magenta right-facing error. Left-facing variants retain the native
stored Mode-6 order and use Prince's existing horizontal flip.


RUNTIME AND MEMORY
------------------

This remains an 8086 real-mode implementation:

  * no XMS, EMS, DPMI, or 286+ instructions;
  * no allocation or conversion during a draw;
  * one proven private slot-3 image table;
  * 108 packed private images for the three non-normal cases;
  * 53,259-byte conservative extra conventional-memory estimate;
  * unchanged 9,005-paragraph Prince MZ allocation.

The packed private alias ranges are:

  right / P2      0..35
  left / P0      64..99
  left / P2     128..163

The original KID slot supplies right/P0. Private data is loaded after normal
level sprites and is released through Prince's existing character-table
cleanup path.


CURRENT LIMITS AND NEXT ORDER
-----------------------------

This checkpoint deliberately covers only the already proven Prince movement
family. After it passes visual and DOS testing, the planned order is:

  1. remaining Kid jumps, climbs, falls, crouches, interactions, and deaths;
  2. carried/moving sword and actor-relative hurt splash;
  3. standard guard-family movement and combat;
  4. Shadow, mouse, cinematic actors, and shared P0/P2 flames.

Transparent sprite edges interact with whatever room signal is behind them.
The supplied previews use black, so final in-game edge color can vary slightly.


VERIFICATION
------------

The verifier checks the deterministic executable and launcher, exact 8086
selector byte stream, original native-flip path, MZ relocations, unchanged DOS
allocation, complete resource ordering, private aliases, geometry, stored
orientation, exact transparency silhouettes, the two-sample right-facing
transform, runtime Mode-6 hashes, independent P0/P2 decode measurements, and
byte-identical preservation of all 184 unselected normal resources from the
verified phase-0 baseline.

Run from tools/ with the original source paths supplied:

  python verify_four_way_kid.py --output-dir ../build-v13 ...
