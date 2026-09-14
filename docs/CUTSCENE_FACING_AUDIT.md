# Native PV cutscene facing audit

2026-09-13. Read-only audit of the authenticated V26 engine and its unchanged
Prince 1.3 animation tables. No runtime/editor changes or ORIENT bank removal.

## Result

Both directions are required for the **PV/800 princess** and **PV/850 story
Vizier**, but not for every individual image. The currently scripted PV/900
princess poses use the native left-facing drawing state. A pose that appears
to turn around is not necessarily a change of the engine's drawing direction.

| PV resource family | Native left and right | Native left only | Not referenced by these scripts |
| --- | --- | --- | --- |
| 800: princess shared by intro and level scenes | 801 | 802–817 | None |
| 850: story Vizier | 851–856 | 857–888 | None |
| 900: late princess poses and reunion | None | 901, 903–930 | 902 |

Here **left** is `Char.direction = FFh`, the native unmirrored path; **right**
is `00h`, the mirrored drawing path. These labels describe executable state,
not an interpretation of where an artist has drawn a character looking.
The composite ORIENT selector supplies separately encoded images for those
two drawing paths.

This supports marking currently used directions in the editor. It does not
justify silently discarding existing sidecar artwork. Keep the complete banks
for compatibility with current exports and possible future script changes.

## Why the princess needs both directions

Native `init_princess` at `0000:2C2C` assigns character 5 and direction FFh.
`init_princess_right` at `0000:2BF6` calls it and changes the direction to 00h.
The shared standing sequence 94 displays frame 11, which selects **PV/801**.

- The opening story starts with the princess in the left state. Sequence 98
  displays frames 2–9, selecting PV/802–809, and then executes **FEh at
  DS:22B3**. She enters the right state and returns to standing PV/801.
- The story's sequence 99 flips her back to the left state at **DS:22BA**
  before the step-back poses PV/810–815. Its subsequent look-down sequence
  uses PV/816–817 in the same state.
- Pre-level scenes 2 and 6, the normal-time level-12 scene, and the start of
  the level-9 scene explicitly initialize her in the right state and use
  PV/801. The short-time level-12 variation starts left and uses the same
  turning sequence 98 as the intro.

Consequently, **PV/801 is a concrete image that must work in both directions**.
The other PV/800 images are currently reached only in the left state.

## Why the story Vizier needs both directions

Native `init_vizier` at `0000:2C4F` assigns character 6 and direction FFh.
The opening story calls the standing, walking, stopping, conjuring, and exit
sequences 95, 96, 97, 102, and 100. These use PV/850, not VIZIER.DAT.

Sequence 100 finishes the conjuring/turning poses, executes **FEh at
DS:229F**, and jumps into the ordinary walking sequence. Thus frames 48–53,
selecting **PV/851–856**, are reused with the opposite drawing direction
when he leaves. He approaches in the left state and exits in the right state.
The rest of PV/851–888 is reached in the left state in the original story.

**Combat Vizier is separate:** the level-13 fighter uses VIZIER.DAT/750,
gameplay guard slot 5 and ORIENT table 6000. This PV audit does not restrict
the fighter's direction support.

## PV/900 and the misleading turns

- Level 4 uses lying sequence 103: PV/901, left state.
- Level 8 starts crouching with sequence 110 and stands up with sequence 111.
  Its PV/920–930 poses remain left. Sequence 111 flips at **DS:2307**, but
  the next displayed pose is shared **PV/801**, now right; it does not draw
  a PV/900 image in the right state.
- Level 9 starts with right-state PV/801. Sequence 112 displays two standing
  frames, flips at **DS:2310**, then draws the PV/930-down-to-917 crouching
  and idle poses in the left state.
- The reunion initializes the princess left, uses standing sequence 109
  (PV/903), then turn-and-hug sequence 108 (PV/904–916). Sequence 108 contains
  no FEh direction command: the turn is represented by different artwork.
- The time-expired scene loads the PV tables but initializes no princess or
  Vizier actor after clearing the actor frames. Loaded resources alone are
  not evidence that an image is drawn.

Resource PV/902 has no entry in the native cutscene frame table. This is a
statement about the shipped tables, not a recommendation to remove it.

## Verification and limits

The audit reads the actual V26 EXE, SHA-256
`b2f2ffe2d390dc6bf4bdd9b376a4736907f79cc93e36a91e1804f81abbb78346`.
It verifies all **2,310 sequence bytes**, **115 sequence offsets**, and
**86 five-byte cutscene frame records** against the local documented original
tables, accounting for the Prince 1.3 data-address displacement. Native
locations are DS:1A80, DS:199A, and DS:1676 respectively. Sequence offset 0
retains its special zero value.

The native interpreter at `0000:73D4` implements FEh by loading
DS:3F21, complementing AL, and writing DS:3F21 back. Scene initialization and
sequence-selection sites were inspected in the executable; conclusions do
not rely on the modern SDL renderer or on sprite appearance.

Evidence under `runtime/build/cutscene-facing-audit/`:

- `audit.py`: read-only reproduction and native-table authentication.
- `FACING-AUDIT.JSON`: sequence traces, flip addresses, frame/resource mappings.
- `resource-facings.csv`: all 85 PV actor resources with direction and scene use.
- `NATIVE-DISASSEMBLY.TXT`: native initializer, scene, loader, and interpreter code.

This is static reachability through the original scripts. It deliberately
includes complete reachable sequences; sound timing or manually skipping a
scene can prevent some reachable frames from appearing in a particular run.
It is not a claim of exhaustive fresh DOSBox frame-by-frame observation.
