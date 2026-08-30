# Third-party notices

Prince DAT Explorer is a Python reimplementation informed by the reverse
engineering and open-source work of the Princed Development Team.

## Princed Graphics Extractor (PGE) 1.0 Alpha 1

The source supplied for this project identifies itself as:

> Princed Graphics library (c) 2003 — Tammo Jan Dijkema, Enrique P. Calot

Its B0–B4 decompression work was interpreted for this application. The original
files were `pg.c`, `pg.h`, and `bmp.c`.

## Princed Resources

The maintained reference implementation is **Princed Resources**, copyright
2003–2025 Enrique P. Calot and contributors:

<https://github.com/NagyD/PR>

It is distributed under the GNU General Public License, version 2 or (at your
option) any later version. Its archive definitions and decoder output were used
to verify this independent Python implementation.

Prince DAT Explorer is consequently distributed under GPL-2.0-or-later. The
complete license text is in `LICENSE.txt`.

## SDLPoP

The maintained **SDLPoP** source provides the original POP1 palette structure,
including the 16 packed CGA bytes and 32 packed EGA bytes, plus GPL test data
used only during development validation:

<https://github.com/NagyD/SDLPoP>

No SDLPoP game-data fixture is included in this release.

## DOSBox-X

The built-in Old CGA and New CGA Composite RGB swatches were calculated from the
two CGA composite models in **DOSBox-X 2026.08.02**:

<https://github.com/joncampbell123/dosbox-x>

DOSBox-X is distributed under GPL-2.0-or-later. Prince DAT Explorer does not
redistribute DOSBox-X binaries or source files. The pinned source locations,
configuration, and derived RGB values are recorded in
`docs/DOSBOXX_COMPOSITE_PALETTE.md`.

## CGA Image Studio composite signal decoder

The full-width artifact preview is ported from the Reenigne/Jenner composite
decoder in **CGA Image Studio**, repository `chjmartin2/cga-image-studio`, file
`cga_v165.py` (Git blob
`e8cf2bb074bcf707594bbb7d8070931bfb19715e`):

<https://github.com/chjmartin2/cga-image-studio>

The port is dependency-free and limited to the Old/New CGA default signal
models and scanline decoding needed by Prince DAT Explorer. The source
project's converter UI, image optimizers, exporters, and bundled environment
are not redistributed.

## Game assets

Prince of Persia is the property of its respective rights holders. No game DAT,
art, palette, level, sound, or other asset is included with this application.
