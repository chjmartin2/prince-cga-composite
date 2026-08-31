# Phase Coverage

## Completed

All 219 KID images have stored phase-aware variants. The 216 body images were
confirmed visually in V18F. The hurt splash uses the ordinary moving-object
selector. V19L swaps the dedicated HP direct-blit rule so screen positions 1/3
use P2 and 2/4 use P0. Static verification passes; V19L still needs DOSBox
confirmation before the KID set is considered completely runtime-confirmed.

V20U converts `PRINCE.DAT` resources 701-734 with one shared exhaustive P0/P2
pattern per moving-sword frame. Chris confirmed the result looks great in
DOSBox, including the colored hilt/detail frames. The sword therefore needs no
runtime phase selector or variant bank.

## Remaining live phase-sensitive graphics

| Archive | Resources | Content |
| --- | --- | --- |
| `PRINCE.DAT` | 151-159 | Torch flames used at different placements. |
| `GUARD.DAT` | 751-775, 777-784 | Normal guard, HP, and hurt splash. |
| `FAT.DAT` | 751-775, 777-784 | Fat guard. |
| `SKEL.DAT` | 751-775, 777-778 | Skeleton. |
| `VIZIER.DAT` | 751-775, 777-784 | Jaffar/final combat actor. |
| `SHADOW.DAT` | 751-775, 777-782 | Shadow Prince. |
| `PV.DAT` | 801-804, 808, 851-859 | Moving cinematic actors. |

## Fixed P2 conversions

- `PRINCE.DAT` resources 166-173: potion bubbles and mask.
- Selected fixed cinematic records in `PV.DAT` identified in the prior engine
  phase audit.

## Static room art

Dungeon and palace tiles remain on even horizontal coordinates and therefore
do not need live phase variants. This includes gates, spikes, chompers, loose
floors, buttons, doors, torch bases, walls, mirrors, floor swords, and bottles.
