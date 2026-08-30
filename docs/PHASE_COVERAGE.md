# Phase Coverage

## Completed

All 219 KID images have stored phase-aware variants as of V19K. The 216 body
images were confirmed visually in V18F. The hurt splash uses the ordinary
moving-object selector. The two HP icons use a dedicated direct-blit hook and
need the V19L absolute-phase swap described in `PROJECT_STATUS.md`.

## Remaining live phase-sensitive graphics

| Archive | Resources | Content |
| --- | --- | --- |
| `PRINCE.DAT` | 151-159 | Torch flames used at different placements. |
| `PRINCE.DAT` | 701-734 | Carried and fighting sword overlay. |
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

