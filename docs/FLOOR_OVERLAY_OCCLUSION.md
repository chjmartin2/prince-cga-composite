# Dungeon climbing floor-overlay occlusion

The climbing floor mask is not `CDUNGEON.DAT` resource 268. Resource 268 is a
one-bit gate-top mask used when a gate is below an empty, big-pillar-top, or
door-top tile.

For Prince climbing frames 137 through 144, the engine's
`floor_left_overlay` table selects environment image numbers 32, 150, and 151.
Because the dungeon environment table starts at DAT resource 200, those are
`CDUNGEON.DAT` resources 232, 350, and 351. They are drawn as transparent
mid-table overlays to put the diagonal floor edge back in front of Prince.

Amir's 2026-08-30 artwork preserved the desired CGA/Mode-6 values but stored
some black samples as source index zero:

| Resource | Size | Opaque samples lost |
| ---: | ---: | ---: |
| 232 | 18x8 | 16 |
| 350 | 22x10 | 25 |
| 351 | 21x10 | 25 |

Index zero is transparent to the engine, so those 66 positions became holes
through which Prince could be seen. V20X replaces only those positions with
source index 4. In this CDUNGEON hardware table, indices 0 and 4 both translate
to CGA value `00`, but index 4 is opaque. Thus the original mask is restored
without changing any Mode-6 signal bit or artifact color.

There is a separate original-engine edge case when climbing right with a
big-pillar-top tile to the left. The original draw condition accepts only an
empty tile there, so it can omit the overlay entirely. V20X first tests the
proven asset-mask defect. If the tower still fails only in the big-pillar-top
arrangement, the next fix should extend that engine condition; changing the
graphic again would not solve an overlay that was never drawn.
