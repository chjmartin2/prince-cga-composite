# Prince of Persia 1.3 CGA conventional-memory atlas

**Scope:** original US DOS Prince of Persia 1.3, CGA, DOSBox 0.74-3,
640 KiB conventional memory, no EMS, XMS, or UMB. Sound paths examined:
PC speaker, Sound Blaster, and Roland MT-32 (`MIDI`).

**Report date:** 2026-09-02

**Best shareable overview:** [interactive memory map](memory-map.html)

**Static overview:** [SVG memory map](memory-map.svg)
**Machine-readable results:** [JSON model](data/memory-model.json),
[level CSV](data/levels.csv), [scene CSV](data/scenes.csv),
[state asset-block CSV](data/state-asset-blocks.csv),
[sound CSV](data/sound-profiles.csv), [archive CSV](data/archives.csv)

## Interactive block map

The interactive map now has one selector for all 16 gameplay levels and each
distinct title or cutscene state, including separate pre-level entries for
levels 2, 4, 6, 8, 9, and 12. It redraws the retained far and known near
allocations for PC speaker, Sound Blaster, or MT-32. Hovering, focusing, or
selecting a readable block exposes its exact live bytes, native slot, lifetime,
storage mode, DAT/resource provenance, and confidence. The inspector links to
a persistent DAT/resource directory on the same page.

The far strip is deliberately an **address-free block inventory**. Its widths
are proportional to exact live allocator bytes, but grouped DAT regions are
aggregates of many independent blocks. Left-to-right order does not claim a
physical address, and the hatched remainder sums arena-local holes rather than
inventing one contiguous free block. The arena diagram below it shows the exact
startup count and payload capacity while leaving internal placement visibly
unknown. Cutscene states separately show their retained actor stage and their
transition-only background or decode blocks, because those allocations occur
at different instants.

## Executive conclusion

The original game does **not** load a complete `.DAT` at the beginning of the
program or keep every archive resident. It opens an archive, allocates a small
index/handle, reads only the requested resource records, then closes the file.
The important memory boundaries are startup, title/story transitions, level
transitions, princess-room cutscenes, the final reunion, and the ending-title
transition. Ordinary room changes do not load or unload a DAT.

The most important discovery is that Prince intentionally claims nearly all
available DOS memory at startup. It repeatedly requests a 65,472-byte far
allocation until failure and then frees those allocations **inside the C
runtime heap**. The DOS memory-control blocks remain owned by Prince. Thus:

1. A falling DOS `MEM` value is not the relevant symptom after startup; most
   memory already belongs to Prince.
2. Resource frees make holes inside independent, sub-64-KiB far arenas.
3. Total free bytes can be large while the largest usable hole is too small.
4. The reunion's first major operation is unusually demanding: CGA
   `PV.DAT` resource 951 creates a 32,006-byte image and a separate
   32,006-byte mask. Both must coexist.

Sound Blaster is the largest **live resource-data** case when digitized sound
is active: its 0–43 core is 89,148 live bytes, versus 10,690 for MT-32 and
3,388 for PC speaker. MT-32 is different in another way. Its transient
21,152-byte Roland SysEx bank expands the bootstrap far arena from 8 KiB to
32 KiB before the memory-exhaustion probe, so startup ends with seven far
arenas rather than eight and 42,304 bytes still free to DOS.

For the phase-aware builds, “memory leak” is therefore the wrong model. The
confirmed risk is a combination of:

- very high live far-heap occupancy from the three phase banks;
- arena-local fragmentation after those banks are freed;
- reuse of native sprite slots 3, 4, and 9 by both the phase runtime and the
  princess-room loader; and
- two back-to-back 32,006-byte `PV/951` allocations at cutscene entry.

The experiments support a combined cause. V21C bypassed phase selection during
cinematics but retained the level-14 phase banks and still failed. V21D omitted
the level-14 banks but retained the selector interaction and still failed.
V21G combined both controls, and Chris confirmed the complete hug, mouse
entrance, fade, ending title, and high-score transition. The phase-free V21F
pair also proved that the enlarged executable and its protected near-heap gap
are not sufficient causes by themselves.

## What is exact, measured, derived, or still path-dependent

This report uses four labels deliberately:

- **Exact:** obtained from the authenticated binary, exact DAT bytes,
  disassembly, or integer allocator arithmetic.
- **Measured:** observed in the isolated stock DOSBox 0.74-3 control with the
  supplied tracer.
- **Derived:** arithmetic combination of exact values, with its inclusions and
  exclusions stated.
- **Path-dependent:** the rule is understood, but the exact value depends on
  the preceding allocation/free order. The distribution of free holes among
  far arenas is the main example.

The report does not turn an aggregate free-byte count into a fictitious
“largest block” number. DOS calls are traced exactly; allocations and frees
inside already-owned CRT arenas are reconstructed from the binary and resource
sizes. A fully exact hole-by-hole snapshot at one arbitrary gameplay instant
would require instrumenting the internal allocator in that run.

## Authenticated test corpus

### Game

| Item | Exact value |
| --- | ---: |
| Source directory | `C:\DOS\PRINCE13` |
| `PRINCE.EXE` size | 125,115 bytes |
| `PRINCE.EXE` SHA-256 | `24FDC79B4DE563348313B50D717E171919191E5C38559F5BDD6A4751D39B7158` |
| Original DAT archives | 27 resource archives; 29 `.DAT`-named files including `CONFIG.DAT` and `SETUP.DAT` |
| `CONFIG.DAT` / `SETUP.DAT` | 28 bytes each; configuration records, not DAT archives |

No original game executable, archive, or resource payload is included in this
analysis directory.

### Emulator

The executable currently named `dosbox.exe` in the installed directory is a
newer custom build, and the active `SDL.dll` was replaced with it. To avoid
mixing components, the control used the preserved stock trio copied to
`runtime/build/dosbox-stock-control/`:

| File | Size | SHA-256 / version |
| --- | ---: | --- |
| `DOSBox.exe` | 3,745,792 | `DCFD46FA521F5CE89DCE3BF026056F3A1D15533F80321EE887403E30D7949F5E`, 0.74.3.0 |
| `SDL.dll` | 448,231 | `69037EBC43755296C0CC292D57D560028D7F2265F7B86CA84E714835C19BBD58`, SDL 1.2.13 |
| `SDL_net.dll` | 13,312 | `2F39DC04ACBECF47EFA45034891602B6EA7BF6FD2F27B5C0A5CA8D7FB155C929` |

The isolated profile is
[`dynamic/stock-cga-640k.conf`](dynamic/stock-cga-640k.conf):

- `machine=cga`
- `memsize=16` (irrelevant to the 640-KiB conventional ceiling)
- `xms=false`, `ems=false`, `umb=false`
- Sound Blaster at 220h, IRQ 7, DMA 1; intelligent MPU-401; PC speaker enabled
- normal CPU core, fixed 3,000 cycles

DOS `MEM /C` prints `632 Kb free conventional memory`. The MCB walker gives
the byte-accurate picture below; the textual MEM number includes/rounds its own
measurement context.

### Source cross-checks

The executable and DAT files are authoritative. Function names and high-level
control flow were cross-checked against the official
[SDLPoP repository](https://github.com/NagyD/SDLPoP), including its early
reverse-engineering commit
[`a3d98893`](https://github.com/NagyD/SDLPoP/tree/a3d98893c0d8d8b63f36e5dabf70458b7110ff17),
and DAT structure against [PR](https://github.com/NagyD/PR). Modern SDLPoP has
added frees and features, so its current C code is never used to override what
the original 1.3 binary actually does.

## The 640-KiB DOS map before Prince

`INT 12h` reports 0x280 KiB = 655,360 bytes. The read-only `MCBMAP.COM` probe
shrinks itself and walks the chain returned by DOS `INT 21h/AH=52h`.

| Segment | Type | Owner | Payload paragraphs | Interpretation |
| ---: | :---: | ---: | ---: | --- |
| 016F | M | 0008 | 0001 | DOS-owned block |
| 0171 | M | 0000 | 0004 | 64-byte low free hole |
| 0176 | M | 0040 | 0010 | resident DOSBox shell block |
| 0187 | M | 0192 | 0009 | probe environment, 144 bytes |
| 0191 | M | 0192 | 0045 | probe PSP/code/data, 1,104 bytes |
| 01D7 | Z | 0000 | 9E27 | largest free block, 647,792 bytes |

Exact reconciliation while that probe is resident:

| Category | Bytes |
| --- | ---: |
| Low reserved area through segment 016F + DOS/shell payload | 6,144 |
| Six MCB headers | 96 |
| Conventional top guard | 16 |
| Probe environment + probe program payload | 1,248 |
| Free MCB payload (`9E2B` paragraphs total) | 647,856 |
| **Total** | **655,360** |

The execution tracer is 36 paragraphs larger than the snapshot probe. Its
pre-EXEC state therefore has 647,280 bytes of free payload and 7,968 bytes of
combined DOS/system/tracer payload. The tracer is a resident parent and its
overhead is explicitly retained in all measured startup reconciliations.

## Executable load and the fixed main block

### MZ image

The original is EXEPACK-compressed. Deterministic expansion gives:

| Field | Packed file | Expanded analysis image |
| --- | ---: | ---: |
| File bytes | 125,115 | 129,664 |
| Header bytes | 512 | 2,560 |
| Load-module bytes | 124,603 | 127,104 |
| Minimum extra paragraphs | `04C1` | `0425` |
| Maximum extra paragraphs | `FFFF` | `FFFF` |
| Entry | `1E0E:0012` unpacker | `0CC8:8EAC` C startup |
| Relocations | packed stub | 583 restored entries |

Both forms have the same loader floor: `232D` paragraphs excluding the PSP.
The startup receives more than the floor because `e_maxalloc=FFFF`, then
shrinks the main DOS block itself.

### Exact startup shrink

At `0CC8:8EAC`, the relocated DGROUP is load segment + `1BA3`. The startup
caps the space above DGROUP at `1000` paragraphs, installs SS at DGROUP, sets
the top-of-near-memory word to `FFFF`, rewrites PSP:2, and calls
`INT 21h/AH=4Ah` on the PSP block.

```text
main MCB paragraphs
  = 0010 PSP
  + 1BA3 load-module bytes before DGROUP
  + 1000 64-KiB DGROUP window
  = 2BB3 paragraphs
  = 178,992 bytes (PSP included)
```

The child environment is a separate 9-paragraph/144-byte MCB.

DGROUP itself divides as follows:

| DGROUP range | Bytes | Meaning |
| --- | ---: | --- |
| `0000..364D` | 13,902 | loaded/static data |
| `364E..678F` | 12,610 | zero-filled BSS |
| `6790..778D` | 4,094 | structural stack reserve |
| `778E..FFFF` | 34,930 | gross near-heap tail |

This 178,992-byte main block is constant across PC speaker, Sound Blaster, and
MT-32 in the measured configuration. The device-specific difference is in
the separate far arenas.

## The allocator Prince actually uses

The relevant code is the Microsoft C 5.x-style runtime embedded in the game,
not DOS `malloc` folklore and not a modern allocator.

### Block rules

- Far malloc entry: `0CC8:8C9B`; far free: `0CC8:8C5A`.
- Near malloc: `0CC8:8E50`; near free: `0CC8:8E2C`.
- Generic first-fit/coalescer: `0CC8:94E5`.
- Every requested byte count is rounded up to even.
- A live block occupies `even_up(request) + 2` bytes; the two bytes are the
  block header.
- Header low bit 0 means allocated, low bit 1 means free; `FFFE` is the arena
  sentinel.
- Coalescing is lazy and only joins adjacent free blocks in one arena.
- A far request at or above `FFF1` is rejected.
- If normal far growth fails, the far wrapper can fall back to near memory.

### New-arena rule

For request `R`:

```text
B = max(240, even_up(R))
DOS MCB payload = 16 × ceil((B + 14) / 16)
physical DOS cost adds one 16-byte MCB header
```

The 14 bytes cover arena metadata, sentinel, and paragraph rounding. A grown
bootstrap arena has 12 fixed bytes outside the block chain; every untouched
full probe arena has 14.

### The startup exhaustion-and-retain probe

At `0000:01B1`, Prince calls `0CC8:1517`:

```c
while ((p[n] = fmalloc(0xFFC0)) != 0) n++;
for (i = n - 1; i >= 0; --i) ffree(p[i]);
```

For `R=FFC0`, DOS receives `FFD` paragraphs = 65,488 bytes of MCB payload.
Inside each pristine arena the free user block is 65,472 bytes. The final
failed request is intentional and occurs before the game installs its
“Insufficient Memory” callback, so startup does not display an error.

Crucially, `_ffree` marks/coalesces the internal block but contains no
`INT 21h/AH=49h` path. The arenas remain DOS-owned. The anchor/reset routines
also never return MCBs to DOS.

### Exact post-probe DOS commitment

| Category | PC speaker / SBLAST | MIDI / MT-32 |
| --- | ---: | ---: |
| Environment payload | 144 | 144 |
| PSP + EXE + DGROUP main payload | 178,992 | 178,992 |
| Bootstrap far-arena payload | 8,192 | 32,768 |
| Full 65,488-byte arenas | 7 | 6 |
| Total far-arena MCB payload | 466,608 | 425,696 |
| Child-owned payload | **645,744** | **604,832** |
| Child MCB headers | 160 (10 blocks) | 144 (9 blocks) |
| DOS-free payload after probe | **1,376** | **42,304** |
| Whole-chain MCB count | 16 | 15 |

Whole 640-KiB check:

```text
PC/SB: 7,968 baseline payload + 645,744 child + 1,376 free
       + 16×16 MCB headers + 16 top guard = 655,360

MT-32: 7,968 baseline payload + 604,832 child + 42,304 free
       + 15×16 MCB headers + 16 top guard = 655,360
```

The 42,304-byte MT-32 residual is not generosity by design. After its 32-KiB
bootstrap arena, the remaining largest DOS hole is 42,240 bytes—too small for
another 65,488-byte probe arena. Later smaller far-arena growth can still use
that DOS hole if internal arenas cannot satisfy a request.

### Anchors and global clears

After loading permanent graphics slots 0 and 1, sounds 0–43, and palette
translations, startup calls the near and far **anchor** routines. Each anchor
moves the allocator's active-start/rover boundary past the last allocated
object. `clear_screen_and_sounds` later invokes the paired **reset** routines,
which collapse only the post-anchor suffix into free space and reset the rover.

That explains two otherwise confusing facts:

- permanent assets survive a global clear; and
- transient resources disappear without DOS `AH=49h` calls.

In CGA, graphics-driver method 7 calls with `FFFF` at startup and `FFFE` at
clear are sentinels/no-ops, not a hidden allocator. Real CGA surfaces pass
ordinary byte sizes through the same method.

## DAT files: open, index, one resource, close

A DAT file has a six-byte outer header, one checksum byte per resource payload,
the payload bytes, and the index. The file-size identity is:

```text
file bytes = 6 + Σ(payload bytes + 1 checksum byte) + index bytes
```

`open_dat` allocates `82 + index_size` bytes for the handle/index, reads it,
and leaves the resource payloads on disk. A requested resource is then loaded
separately. Closing the DAT frees only that temporary handle/index. See
[`data/archives.csv`](data/archives.csv) for all 27 archives with their exact
file, index, payload, resource-count, and handle sizes. The unused EGA/VGA
archives are listed for inventory integrity but are never opened on the CGA
path.

Representative examples:

| Archive | File | Index | Resources | Payload | Handle request | CGA use |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `CDUNGEON.DAT` | 9,407 | 1,642 | 205 | 7,554 | 1,724 | dungeon environment |
| `CPALACE.DAT` | 12,889 | 1,802 | 225 | 10,856 | 1,884 | palace environment |
| `KID.DAT` | 37,149 | 1,762 | 220 | 35,161 | 1,844 | compressed Kid frames |
| `LEVELS.DAT` | 37,031 | 130 | 16 | 36,879 | 212 | one level resource at a time |
| `PV.DAT` | 25,829 | 826 | 103 | 24,894 | 908 | princess-room scenes |
| `TITLE.DAT` | 36,799 | 98 | 12 | 36,683 | 180 | title/story/ending |
| `DIGISND1.DAT` | 50,101 | 162 | 20 | 49,913 | 244 | digitized sounds |

### Graphic table allocations

The sprite-table loader is at `0CC8:104A`. Its near pointer-table request is:

```text
6 + 4 × image_count × (2 ^ slot_shift)
```

The ten native table slots have shifts `{0,1,0,0,0,0,1,1,1,0}`. Slots 1, 6,
7, and 8 therefore retain image and mask pointers.

For an unpacked image:

```text
request = 6 + height × max(source_stride, CGA_target_stride)
source_stride = ceil(width × source_bits_per_pixel / 8)
CGA_target_stride = ceil(width / 4)
```

The `max` matters: a 4-bpp source retains its 4-bpp-sized buffer even though
the CGA target is two bits per pixel. Packed KID and TITLE tables retain the
compressed record bytes; drawing decodes a temporary image.

The LZG decoder allocates a 1,024-byte near dictionary, occupying 1,026 live
bytes with its header. Stock KID draws only one decoded output at a time. Its
largest case is resource 424: 954 live output bytes + 1,026 dictionary =
1,980 transient bytes before the current peel is added. Previous objects'
peels can coexist, but the current peel follows decoding; it does not overlap
that dictionary.

TITLE has a larger draw peak. Resources 41/51 decode to a 32,008-byte live
full-screen source buffer, with the dictionary for a 33,034-byte transient.
Resource 54's special mode can hold two decoded 8,848-byte buffers plus the
dictionary (18,722), which is still lower. Packed TITLE table loading itself
uses a 514-byte live near scratch buffer and the 182-byte live DAT handle; it
does not decode the records at load time.

Peels (saved background rectangles) are also per-frame allocations. For a
half-open rectangle of width `w`, height `h`, and CGA byte phase
`q=(x-surface_x) mod 4`:

```text
far request  F = h × ceil((q + w) / 4)
near request   = 26 + 2h
total live     = 30 + 2h + even_up(F)
```

At most 50 peel objects can be live in one frame; they are restored/freed only
after the update, so earlier objects' peels coexist. Safe maxima from the
actual tables are 604 bytes for KID, 576 for GUARD/FAT/VIZIER, 534 for SKEL,
548 for SHADOW, 460/606/630 for PV800/850/900, and 254 for each 19×28
hourglass resource PV953–958. The structural actor-only ceiling is therefore
31,500 live bytes, but an exact frame uses the sum of the actual clipped
rectangles/phases drawn in that frame. KID's decode dictionary is freed before
its own peel is added; previous objects' peels can overlap the current decode.

Exact component totals are in
[`data/graphic-components.csv`](data/graphic-components.csv).

For audit convenience, the retained/live total and the isolated
`load_chtab` peak are:

| Component | Retained live | Isolated loader peak live |
| --- | ---: | ---: |
| PRINCE/700 sword | 2,824 | 4,992 |
| PRINCE/150 flame/sword/potion | 4,608 | 6,406 |
| KID/400 | 36,484 | 38,844 |
| CDUNGEON/200 + /360 | 31,884 + 4,072 | 35,200 + 7,422 |
| CPALACE/200 + /360 | 32,620 + 4,072 | 36,096 + 7,586 |
| GUARD / FAT / SKEL | 18,648 / 17,790 / 15,240 | 20,704 / 19,830 / 17,218 |
| VIZIER / SHADOW | 17,576 / 15,084 | 19,618 / 17,058 |
| PV/800 /850 /900 | 8,184 / 22,244 / 13,956 | 10,788 / 23,816 / 16,568 |
| PV/950 /980 | 69,032 / 4,940 | 73,228 / 9,062 |
| TITLE/40 /50 packed | 11,824 / 24,742 | 12,520 / 25,438 |

### Off-screen surfaces

The visible CGA framebuffer at segment `B800` is video memory and is excluded
from the 640-KiB conventional-RAM totals. The off-screen buffers are ordinary
allocator objects:

| Surface | Near request / live | Far pixels request / live | Total live |
| --- | ---: | ---: | ---: |
| Gameplay, 320×192 | 432 / 436 | 15,360 / 15,362 | **15,798** |
| Full screen, 320×200 | 448 / 452 | 16,000 / 16,002 | **16,454** |

## Complete state and transition map

### Startup prefix

The original sequence is:

1. DOS loads the MZ image and environment.
2. C startup shrinks the main MCB to 178,992 bytes.
3. The graphics and sound command lines are parsed and devices initialized.
4. The first far arena is created. MIDI/MT-32 temporarily loads
   `PRINCE.DAT/65535` (21,152 bytes, an `MThd`/Roland MT-32 SysEx bank), which
   grows that arena to 32 KiB; it is then freed internally.
5. The exhaustion-and-retain probe creates seven full arenas for PC/SB or six
   for MT-32.
6. `PRINCE.DAT/700` (sword) enters permanent slot 0.
7. `PRINCE.DAT/150` (flame, floor sword, potion) enters permanent slot 1.
8. Sounds 0–43 and palette translations load.
9. Near and far heap anchors mark that prefix permanent.
10. `start_game` chooses title/story or direct level startup.

The command `PRINCE CGA MIDI IMPROVED 14` takes the direct-level path after
the permanent prefix. It avoids the normal title/story allocation history,
which is why a warp test and a complete playthrough need not leave identical
arena holes even when their live level-14 objects match.

### Normal title and opening story

The normal path loads sounds 50–55, a 320×200 off-screen surface, and packed
TITLE tables 40/50. It draws the title/story sequence, releases those TITLE
tables, runs `load_intro(0, pv_scene, 0)` while the title sounds remain,
reloads TITLE for the remaining story/credits/high-score pages, and finally
resets the transient state before `init_game(0)`.

### Entering and changing a level

`init_game` creates the 320×192 surface and loads `KID.DAT/400` into slot 2.
At each actual level transition, `load_lev_spr`:

1. frees optional sounds and sprite tables 3–9;
2. loads `CDUNGEON.DAT/200` or `CPALACE.DAT/200` into slot 6;
3. loads only the optional graphics rows selected for that level;
4. loads one whole guard-family table in slot 5;
5. loads environment wall resource 360 in slot 7; and
6. loads the event sounds selected for the level.

`load_level` then opens `LEVELS.DAT`, reads resource `2000 + level`, copies
exactly 2,305 bytes into the fixed global `level` structure, and closes the
archive. Levels 0–14 have a 2,305-byte record (2,308 live as a temporary
block); level 15 has 2,304 bytes (2,306 live). With the 214-byte live DAT
handle, the boundary-only transient is 2,522 bytes, or 2,520 for level 15.
The resource block is freed after the copy, so none of it remains as a retained
far asset.

A same-level restart reloads the 2,305-byte level structure but can retain the
already selected environment/guard resource family. A transition to another
level replaces the level-family assets.

### Room changes and special events

No room transition opens a DAT. These special events use data already resident
for the whole level:

| State/event | Level(s) | Memory behavior |
| --- | --- | --- |
| Skeleton wake/reappearance | 3 | `SKEL.DAT/750` is the resident level guard family; sound 44 was selected at level load |
| Mirror and shadow emergence | 4 | mirror graphics/sound are selected at level load; scripted shadow uses KID frame pointers |
| Shadow steals potion | 5 | uses resident KID frames; no `SHADOW.DAT` event load |
| Scripted shadow | 6 | uses KID frames while FAT is the resident guard family |
| Fat guard | 6 | `FAT.DAT/750` loaded for the whole level |
| Mouse | 8 | uses KID frames; no mouse sprite archive load |
| Shadow fight/unite | 12 | `SHADOW.DAT/750` loaded for the whole level |
| Vizier fight | 13 | `VIZIER.DAT/750` loaded for the whole level |
| Chompers/spikes | selected levels | optional graphics and sounds are chosen at level load |

### Pre-level cutscenes

Only levels 2, 4, 6, 8, 9, and 12 have a pre-level princess-room cutscene.
Level 2 uses the early actor set; the others use the late set. `load_intro`:

1. optionally frees sounds 44–56;
2. frees sprite slots 3–9;
3. loads `PV/950` into slot 8 (shift 1) and `PV/980` into slot 9;
4. draws the room and bed;
5. frees slot 9 and only slot-8 image 0, retaining slot-8 mask 0/backdrop data;
6. loads `PV/800` into slot 3 and `PV/850` (early) or `PV/900` (late) into
   slot 4;
7. runs the scene; then frees slots 3–9.

KID and the gameplay surface remain resident for pre-level and reunion scenes.
The time-expired path performs a global reset first, so KID does not remain;
it creates a full-screen surface and runs the late scene.

### Final reunion and ending

When level 14 reaches room 5, `end_sequence` calls
`load_intro(1, end_sequence_anim, 1)`. The reunion therefore enters the same
late PV load path while KID remains resident. After the hug/mouse/fade, the
game performs the global suffix reset, loads ending sound 56, creates a
320×200 surface, reloads TITLE 40/50, and displays the success/high-score
sequence before returning through `start_game`.

## Per-level retained resource map

The table below is **live allocator-block bytes for graphics plus selected
sounds**. It excludes the fixed 178,992-byte main block, the off-screen
surface, temporary DAT handles/scratch, fixed arena metadata, free holes, and
DOS/system memory. That separation is intentional: adding unrelated categories
would obscure the arena-contiguity issue.

The Sound Blaster column is the exact digitized-resource path when `sfDigi` is
active; see the measured detection caveat in the sound section.

| L | Env. | Guard family | Optional rows | Graphics live | PC live | SB live | MT-32 live | Notable state |
| --: | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 0 | Dungeon | GUARD | 4,5,6 | 126,400 | 130,352 | 234,790 | 137,622 | demo; chomper/spike assets |
| 1 | Dungeon | GUARD | 1,6 | 107,720 | 111,496 | 209,040 | 118,792 | falling entry |
| 2 | Dungeon | GUARD | 4,6 | 114,104 | 117,816 | 212,742 | 125,040 | early pre-level PV |
| 3 | Dungeon | SKEL | 1,5,6 | 116,608 | 120,624 | 227,680 | 127,966 | skeleton family resident |
| 4 | Palace | GUARD | 0,2,3,5,6 | 137,380 | 141,484 | 250,018 | 148,706 | mirror/shadow emergence |
| 5 | Palace | GUARD | 0,3,4,5,6 | 142,112 | 146,064 | **250,502** | 153,334 | largest stock state (tie L10) |
| 6 | Palace | FAT | 0,3,5,6,7 | 138,418 | 142,370 | 246,808 | 149,640 | fat guard |
| 7 | Dungeon | GUARD | 1,5,6 | 120,016 | 124,032 | 231,088 | 131,374 | ordinary dungeon |
| 8 | Dungeon | GUARD | 1,5,6 | 120,016 | 124,032 | 231,088 | 131,374 | mouse event |
| 9 | Dungeon | GUARD | 4,5,6 | 126,400 | 130,352 | 234,790 | 137,622 | late pre-level PV |
| 10 | Palace | GUARD | 0,3,4,5,6 | 142,112 | 146,064 | **250,502** | 153,334 | largest stock state (tie L5) |
| 11 | Palace | GUARD | 3,5,6 | 125,848 | 129,800 | 234,238 | 137,070 | ordinary palace |
| 12 | Dungeon | SHADOW | 1,4,6 | 111,728 | 115,504 | 213,048 | 122,800 | shadow family resident |
| 13 | Dungeon | VIZIER | 4 | 105,020 | 108,408 | 194,168 | 115,710 | vizier family resident |
| 14 | Palace | none | 0,3,7 | 100,320 | 103,708 | 189,468 | 111,010 | reunion in room 5 |
| 15 | Dungeon | none | none | 79,872 | 83,260 | 169,020 | 90,562 | copy-protection dialog |

The level environment pattern for 0–15 is
`0000111000100010` (1 = palace). Guard families are normal GUARD on
0,1,2,4,5,7,8,9,10,11; SKEL on 3; FAT on 6; SHADOW on 12; VIZIER on 13; and
none on 14/15.

## Scene retained states and peaks

Each triplet below is PC speaker / Sound Blaster digitized path / MT-32.

| State | Retained assets, live bytes | Maximizing modeled live peak including surface | Main reason for peak |
| --- | ---: | ---: | --- |
| Opening TITLE | 48,448 / 144,668 / 60,314 | **97,936 / 194,156 / 109,802** | steady TITLE + full-screen surface + 33,034 decoded draw buffer/workspace |
| Opening PV | 79,334 / 175,554 / 91,200 | 106,430 / 202,650 / 118,296 | PV/951 load + LZG dictionary + full-screen surface |
| Early PV with KID | 114,756 / 200,516 / 122,058 | 141,196 / 226,956 / 148,498 | KID remains; shared PV/950+980 background-load peak |
| Late PV/reunion with KID | 106,468 / 192,228 / 113,770 | 141,196 / 226,956 / 148,498 | KID remains; the background peak precedes early/late actor selection |
| Time-expired late PV, no KID | 69,984 / 155,744 / 77,286 | 105,368 / 191,128 / 112,670 | reset removes KID; full-screen surface |
| Ending TITLE/high score | 49,236 / 146,736 / 68,278 | **98,724 / 196,224 / 117,766** | ending TITLE draw buffer + sound 56 |

The title loader-only peaks are lower than the title draw peaks: opening
65,598 / 161,818 / 77,464 including surface; ending 66,386 / 163,886 /
85,428. These distinctions matter because compressed TITLE records stay packed
until they are drawn.

## Sound paths

### Retained resource allocations

| Configuration | Core 0–43 request / live | All optional 44–56 request / live | Title 50–55 live | Ending 56 live |
| --- | ---: | ---: | ---: | ---: |
| PC speaker | 3,280 / **3,388** | 3,659 / 3,692 | 1,062 | 1,850 |
| Sound Blaster, digitized path | 89,042 / **89,148** | 51,251 / 51,284 | 11,522 | 13,590 |
| MT-32 | 10,573 / **10,690** | 19,954 / 19,988 | 5,626 | 13,590 |

The Sound Blaster core includes 44 selected sound blocks plus the retained
1,201-byte OPL instrument bank (45 blocks total). The largest individual
digitized sample is `DIGISND3/10001`: 12,032 requested, 12,034 live.

Temporary open-DAT handles add these exact live peaks while a load pass is in
progress:

| Load pass | PC | SB digitized | MT-32 |
| --- | ---: | ---: | ---: |
| Core handles | 438 | 1,016 | 930 |
| Optional/title/end handles | 190 | 466 | 466 |
| Core total at load peak | 3,826 | 90,164 | 11,620 |
| Core + title-sound load peak | 4,640 | 101,136 | 16,782 |
| Core + ending-sound load peak | 5,428 | 103,204 | 24,746 |

### What the isolated DOSBox run actually detected

The binary command decoder was checked directly:

- `STDSND` selects mode 0;
- `SBLAST` selects mode 3;
- `MIDI` selects mode 6, whose MPU initialization is at port 330h/IRQ 2 and
  whose setup resource identifies Roland MT-32.

In the instrumented stock 0.74-3 profile, `SBLAST` definitely selected mode 3,
but the detected flags did not enter the digitized-resource branch. Its file
trace opened `IBM_SND1`, `MIDISND1`, and `MT32SND1`, not `DIGISND1/3`, even
with SB16 and SB2 emulation attempts. Therefore two separate facts are kept:

1. the mode-3 startup arena geometry is **measured** and matches PC speaker;
2. the 89,148-byte digitized payload is **exact binary/DAT-derived** for a run
   in which `sfDigi` is active, but it was not dynamically reached by this
   isolated DOSBox probe.

This does not make the digitized case irrelevant. It is the true resource
upper bound and the worst steady-memory sound path. It does mean that any claim
about Chris's active Sound Blaster resource path should first be verified from
the files actually opened in that run.

## The PV/951 contiguity hurdle

`load_intro` places `PV/950` in slot 8. Slot 8 has shift 1, so resource 951 is
decoded twice: image plus mask.

| Quantity | Exact bytes |
| --- | ---: |
| One request | 32,006 |
| One live block including header | 32,008 |
| Two simultaneous requests | 64,012 |
| Two simultaneous live extents | **64,016** |

A pristine full probe arena has a 65,472-byte free user block. It can just hold
both live extents, leaving 1,456 bytes of block-chain extent. But consider two
arena-local holes of 40,000 and 30,000 bytes. Their aggregate is 70,000; the
first 32,006-byte request fits, while the second cannot fit in either remaining
hole. Coalescing never crosses an arena boundary.

The initial `PV/950` and temporary `PV/980` tables reach 73,806 bytes of far
payload plus block headers. After drawing the room, the loader frees `PV/980`
and only the first `PV/951` copy, retaining approximately 36.9 KiB of the
backdrop table. It then loads `PV/800` and `PV/850` or `PV/900`.

This proves the mechanism by which a run can report insufficient memory or
freeze despite a reassuring aggregate-free calculation. It does **not**, by
itself, prove the exact arena containing every block in one failed phase run;
that last topology is play-history dependent.

## Phase-aware footprint and ending diagnosis

The current V21B phase sidecars have these exact decoded allocations:

| Bank | File bytes | Requests | Live blocks | Far live |
| --- | ---: | ---: | ---: | ---: |
| `PHASE.DAT` | 44,577 | 108,123 | 108,632 | 107,748 |
| `PHASE2.DAT` | 37,695 | 87,159 | 87,656 | 86,772 |
| `PHASE3.DAT` | 39,877 | 88,206 | 88,688 | 87,804 |
| **Total** | **122,149** | **283,488** | **284,976** | **282,324** |

The modified KID table adds another 4,010 far-live bytes over the original.
In the intended MT-32 level-14 state:

```text
stock far-live assets + gameplay surface    123,896
three phase banks                           282,324
modified-KID delta                            4,010
                                            -------
total far live                              410,230

startup far block-chain capacity            425,600
aggregate free-block extent                  15,370  (before hole topology)
```

For the fully digitized Sound Blaster resource path, the same phase overlay
exceeds the startup far block-chain capacity before accounting for fallback;
the far allocator may spill a request into the roughly 34.9-KiB gross near
tail or seek new DOS arena space, but the measured PC/SB startup leaves only
1,376 DOS-free payload bytes. That is a severe, deterministic liability even
before the reunion.

At cutscene entry the phase-bank blocks may be marked free, but those frees do
not erase the arena boundaries or guarantee two 32,008-byte free extents.
Simultaneously, native slots 3, 4, and 9 change meaning:

| Slot | Phase gameplay | Princess-room loader |
| ---: | --- | --- |
| 3 | `PHASE.DAT` | `PV/800` princess-in-story table |
| 4 | `PHASE2.DAT` | `PV/900` ending-princess table |
| 9 | `PHASE3.DAT` | temporary `PV/980` bed table |

The controlled build history separates the hypotheses:

| Build | Controlled difference | DOSBox result |
| --- | --- | --- |
| V21C | cutscene selector gate only | failed/static; gate not sufficient |
| V21D | omit level-14 phase banks only | advanced farther but locked; memory policy not sufficient alone |
| V21E | original phase-free allocation path | full ending; loading-screen matrix corruption absent |
| V21FA / FB | phase-free enlarged EXE, with/without protected near gap | both full endings; EXE size/gap not sufficient cause |
| V21G | omit level-14 banks + cutscene selector bypass | full hug, mouse, fade, ending/high-score confirmed |
| V21IA | phase banks retained + selector bypass, no P0 hook | failed/static |
| V21IB | no-bank policy + P0 hook | ending succeeded, but level-14 Kid lost ordinary phase behavior |

The defensible conclusion is not “one leak was fixed.” V21G avoids both the
arena-pressure history and the slot-meaning collision. The next architecture
should remove the need for resident phase images rather than trying to squeeze
more of them into the same allocator.

## Design implication for the phase-aware runtime

The lowest-liability direction is the same technique already demonstrated by
the corrected torches:

1. Store one normalized phase-0 image for an animation frame.
2. At draw time, shift its placement by the phase correction required for the
   current X coordinate.
3. Keep cinematic drawing on the ordinary native sprite tables, with the same
   phase-0 placement normalization.
4. Apply this to Kid and then the guard families, including fat guard, shadow,
   and vizier.
5. Exclude skeletons from phase-aware encoding as planned; their black/white
   silhouette does not justify another resident phase family.

This removes the known 284,976-byte phase-bank allocation, eliminates the
3/4/9 slot conflict, and makes the final animation use the same data lifetime
as stock Prince. It also avoids making correctness depend on the exact
fragment pattern left by a playthrough.

The remaining phase-aware liability is therefore concrete:

- **Current resident liability:** 284,976 live bytes in the three phase banks,
  plus 4,010 far-live bytes from the expanded KID table.
- **Future sprite-family liability if implemented as more banks:** guard,
  fat, shadow, and vizier would add new persistent far allocations and should
  not be designed that way.
- **Skeleton liability:** zero if it remains excluded/shared as requested.
- **Runtime-code liability:** comparatively small, but every selector must be
  gated away from cinematic/native slot reuse. Eliminating sidecar selection
  is safer than accumulating more gates.

## Binary address audit index

These are load-module segment:offset addresses in the deterministically
expanded executable. Names are behavioral labels, not claims about original
vendor symbols.

| Address | Verified role |
| --- | --- |
| `0000:01B1 → 0CC8:1517` | startup far-arena exhaustion/retain probe |
| `0000:20BD` | `clear_screen_and_sounds`; near/far reset calls at 20DD/20E2 |
| `0000:22C6` | TITLE loader; open 22D1, tables 40/50 at 22E0–2305, close 2308 |
| `0000:3638` | `load_intro`; free slots 3–9 at 3656; PV950/980/800/850-or-900 at 365F–3721 |
| `0000:B4D8` | KID draw; decode B5AE, add peel B6E3, free B71E |
| `0CC8:104A` | sprite-table loader; 512-byte scratch at 10E4, free at 118E |
| `0CC8:1216` | inner raw-copy/decode resource path |
| `0CC8:1661` | surface constructor |
| `0CC8:345E / 347B` | CGA method-7 allocate / method-8 free |
| `0CC8:3B81` | peel capture; near allocation 3BE5, far allocation 3C1A |
| `0CC8:79C0 / 7A73` | LZG 1-KiB workspace management |
| `0CC8:81B6` | image decoder; output allocation at 8251 |
| `0CC8:8C5A / 8C9B` | far free / far malloc |
| `0CC8:8CFF` | far-arena constructor |
| `0CC8:8D84 / 8DA3` | far reset / far anchor |
| `0CC8:8DBF / 8DD0` | near reset / near anchor |
| `0CC8:8DE1 / 8DFE` | generic suffix reset / anchor |
| `0CC8:8EAC` | C startup and main-MCB shrink |
| `0CC8:94E5` | first-fit allocation, split, lazy coalescing |
| `0CC8:95C8 → 9624 → 9698/9706` | arena growth policy and DOS AH48/AH4A bridge |

## Reproduction and audit trail

The dynamic evidence, tracer source, parser, and isolated configuration are in
[`dynamic/`](dynamic/). See [`dynamic/README.md`](dynamic/README.md) for the
exact PowerShell/DOSBox commands and the observer limitations.

Regenerate the data model and shareable views from the repository root:

```powershell
.\.venv\Scripts\python.exe `
  docs\prince-1.3-cga-memory-map\tools\build_memory_map.py `
  --verify-source C:\DOS\PRINCE13\PRINCE.EXE
```

The builder verifies the source SHA-256 and asserts core accounting identities,
including the 640-KiB MCB reconciliation, startup pool sizes, surface sizes,
phase-bank totals, and the largest stock level state.

## Bottom line

Prince 1.3 is a streaming resource loader inside a deliberately preallocated,
arena-based memory pool. Levels choose resident families; rooms and scripted
events mostly reuse them. The final reunion is special because it replaces
slots 3–9 and immediately asks for two nearly half-arena PV blocks while KID
is still live. The phase sidecars consume roughly 278 KiB total, about 276 KiB
of it in far block extents, and reuse those same native slots, turning a stock-safe transition into a
history-sensitive one.

The robust fix is not to “free harder” at the ending. It is to normalize
animated assets to one phase and express phase as draw-position adjustment,
including the guard/vizier families and the final cinematic, while leaving
skeletons shared. That preserves phase-aware placement without carrying the
resident-bank and slot-collision liabilities into the ending.
