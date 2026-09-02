# Original DOS engine placement and CGA phase audit

This is the placement contract used by Prince DAT Explorer 0.4.29's
**Original DOS 1.3 engine (automatic)** policy. It answers two separate
questions:

1. Which original draw paths can display each image resource?
2. Which NTSC carrier alignments can the left edge of that image reach?

The short result is: the composite waveform has four physical sample phases,
but the unmodified game can place image pixels only at integral 320-column CGA
coordinates. One CGA pixel is two 640-column signal samples. Consequently, a
given image can reach at most two alignments. With the screen origin normalized
to P0, those alignments are P0 and P2. P1/P3 require an odd whole-screen carrier
bias or new sample-granular draw code.

## Scope and evidence

The code audit uses SDLPoP commit
`3c5add5fb7f83d4ceb542823ab66d00146c4271b`. SDLPoP is based on the DOS
disassembly and preserves original code addresses in comments. The relevant
source is:

- [`seg008.c`](https://github.com/NagyD/SDLPoP/blob/3c5add5fb7f83d4ceb542823ab66d00146c4271b/src/seg008.c): room draw order, tile table, back/fore/mid tables, final actor X transform, flip, and wall paths
- [`seg006.c`](https://github.com/NagyD/SDLPoP/blob/3c5add5fb7f83d4ceb542823ab66d00146c4271b/src/seg006.c): Kid/guard frame tables, sword table, object coordinates, and clipping
- [`seg007.c`](https://github.com/NagyD/SDLPoP/blob/3c5add5fb7f83d4ceb542823ab66d00146c4271b/src/seg007.c): falling loose-floor objects
- [`seg001.c`](https://github.com/NagyD/SDLPoP/blob/3c5add5fb7f83d4ceb542823ab66d00146c4271b/src/seg001.c): every original scripted cinematic, princess-room background, torches, and hourglass
- [`seg000.c`](https://github.com/NagyD/SDLPoP/blob/3c5add5fb7f83d4ceb542823ab66d00146c4271b/src/seg000.c) and [`data.h`](https://github.com/NagyD/SDLPoP/blob/3c5add5fb7f83d4ceb542823ab66d00146c4271b/src/data.h): image-bank loading and fixed title/story placements
- [`seqtbl.c`](https://github.com/NagyD/SDLPoP/blob/3c5add5fb7f83d4ceb542823ab66d00146c4271b/src/seqtbl.c): original animation bytecode and offsets

The audit was checked against the shipped 1.3 `CDUNGEON`, `CPALACE`,
`PRINCE`, `KID`, `GUARD`, `FAT`, `SKEL`, `VIZIER`, `SHADOW`, `PV`, and
`TITLE` image inventories. `research/phase_audit.py` reproducibly replays the
original cinematic sequences through the original frame tables and the shipped
image widths.

This is an original-engine contract, not a promise about SDLPoP extensions,
custom level features, or a future patched executable.

## Coordinate proof

### Static room images

The room loop sets:

```text
draw_xh = {0,4,8,12,16,20,24,28,32,36}[column]
final_x_320 = 8 * xh + xl
```

Therefore each tile column begins at `32 * column`: 0, 32, 64, ..., 288.
Every CGA environment call supplies an `xl` and/or `xh` adjustment whose final
320-column X is even. Examples that initially look suspicious are still even:

```text
wall stripe:       8*(draw_xh + 3)     = 32*c + 24
level door:        8*(draw_xh + 1)     = 32*c + 8
chomper blood:     8*(draw_xh + 1) + 4 = 32*c + 12
potion bottle:     8*(draw_xh + 2) + 6 = 32*c + 22
potion bubble:     8*(draw_xh + 3) + 1 = 32*c + 25  (the exception)
gameplay flame:    8*(draw_xh + 1)     = 32*c + 8
```

Multiplying by two signal samples gives phase `2*X mod 4`: even X is P0 and
odd X is P2. Vertical position, draw layer, transparency mode, and animation
frame do not alter horizontal phase.

### Moving actors

The actor path first derives an object position in the game's 280-unit logical
coordinate system, then `draw_mid()` applies:

```text
final_x_320 = trunc(logical_x * 320 / 280)
if horizontally flipped: final_x_320 -= image_width
```

The runtime must choose a phase variant only after this transform and the
post-flip width subtraction. An actor can reach both X parities, so its normal
contract is P0+P2. The shadow is conclusive: the engine deliberately draws the
same image at X and X+1 (OR followed by XOR), guaranteeing both alignments in
one displayed frame.

### Clipping

Let `destination_640_x` be the first visible destination sample and
`cropped_source_640_x` the number of source samples skipped at the left edge.
The local image origin would have landed at their difference, so the general
selection formula is:

```text
phase = (global_phase_bias
       + destination_640_x
       - cropped_source_640_x) & 3
```

The original engine's destination and crop boundaries are integral 320-column
pixels, hence both terms are even in 640-sample units. Clipping does not create
P1 or P3. For an unclipped actor hook this simplifies to:

```text
phase = (global_phase_bias + 2*(final_x_320 & 1)) & 3
```

## All 31 tile types

In the table below, `E:n` is environment image number `n`: normally DAT
resource `200+n`, optionally replaced by `1200+n`. `W:n` is a logical wall-bank
image loaded from the resource-360 bank. `P:n` is image number `n` in the
`PRINCE.DAT` resource-150 flame/sword/potion bank. Repeated floor/right/bottom
pieces are listed because the renderer really redraws them through different
layers and neighboring-tile passes.

Every `E:` and `W:` component below is P0. The only non-P0 tile subcomponent is
the potion bubble/mask in `PRINCE.DAT`.

| Tile | Original name | Shipped level occurrences | Drawn components and behavior | Required phase |
|---:|---|---:|---|---|
| 0 | Empty | 3,256 | Usually no bitmap. Modifier blue-line variants use E124–126 and E44–45 through the right-neighbor pass. | P0 |
| 1 | Floor | 1,123 | E41 base, E42 right/floor-right, E145 stripe, E43 bottom; E44–45 blue-line variants and E32/E150–151 climbing overlays. | P0 |
| 2 | Spikes | 121 | Static E127/E133/E145/E43 plus animated left E128–132, right E134–138, and foreground E139–143. | P0 |
| 3 | Pillar | 596 | E92 base, E93 right, E94 top-right, E43 bottom, E95 foreground at `32*c+8`. | P0 |
| 4 | Gate | 94 | E46–68 across base, sides, top mask, moving slices, back, and foreground passes. All slices retain the tile boundary X. | P0 |
| 5 | Stuck floor | 0 | Generated from a closer tile with modifier `0xFF`; E41/E35/E145/E36 plus the same climbing-overlay family. | P0 |
| 6 | Closer/drop button | 29 | E41/E42/E145 with E96 button bottom. | P0 |
| 7 | Door top with floor/tapestry | 10 | E46 base, E43 bottom, E49 foreground; palace top/bottom variants E78/E80–83. | P0 |
| 8 | Big-pillar bottom | 19 | E86 base, E87 right, E43 bottom, E88 foreground at `32*c+8`. | P0 |
| 9 | Big-pillar top | 19 | E89 right, E90 top-right, E91 foreground at `32*c+8`. | P0 |
| 10 | Potion | 64 | Floor E41/E42/E145/E43; bottle P12–15 (`PRINCE` 162–165) at `32*c+22`; bubble P16–22 plus mask P23 (`PRINCE` 166–173) at `32*c+25`. | Bottle P0; bubble/mask P2 |
| 11 | Loose floor | 174 | Static/shaking E41–43 and E69–74/E145. Falling loose-floor objects keep `xh=4*column`, `xl=0`; their right piece is `xh+4`. | P0 |
| 12 | Door top/tapestry top | 55 | E85 bottom and E49 foreground, with E78/E80–83 top/bottom variants when appropriate. | P0 |
| 13 | Mirror | 0 | Inserted by the level-4 mirror event; E75 base, E42 right, E43 bottom, E77 mirror face. The reflected Kid is a separate moving KID draw. | Tile P0; reflected actor P0+P2 |
| 14 | Debris/broken floor | 111 | E97/E98/E145/E43/E100. Also produced when a loose floor lands and breaks a floor-like tile. | P0 |
| 15 | Opener/raise button | 102 | E147 base (E148 when left side is open in dungeon), E42/E145/E149. | P0 |
| 16 | Level-door left/exit | 29 | E41/E37/E38/E43 plus stairs E99/E144 and moving door E33/E34, all at `32*c+8`. | P0 |
| 17 | Level-door right | 29 | E39 right, E40 top-right, E43 bottom. | P0 |
| 18 | Chomper | 40 | Floor E42/E145/E43; animated E101–113; blood E114–123 at `32*c+12`. | P0 |
| 19 | Torch | 370 | Floor E41/E42/E43, torch base E146; animated P1–9 (`PRINCE` 151–159) at `32*c+8`. | P0 in gameplay |
| 20 | Wall | 4,002 | W1–10 select connections/top/bottom/main pieces; palace stripe E84 is `32*c+24`. Original CGA skips the random VGA/EGA wall-detail pass. | P0 |
| 21 | Skeleton | 8 | E30/E31 corpse pieces and E43 bottom. | P0 |
| 22 | Sword | 3 | Floor E41/E42/E145/E43; lying sword P10–11 (`PRINCE` 160–161) at `32*c`. Carried/fighting swords use the separate resource-700 actor bank. | Floor sword P0; moving sword P0+P2 |
| 23 | Balcony left | 3 | E41 base, E10 right, E11 top-right, E43 bottom. | P0 |
| 24 | Balcony right | 3 | E12 right, E13 top-right, E43 bottom. | P0 |
| 25 | Lattice pillar | 60 | Pillar/floor family E92/E42/E145/E43/E95. | P0 |
| 26 | Lattice down/support | 60 | E1 base, E2 bottom, E9 foreground; E6 is the lattice/door junction. | P0 |
| 27 | Lattice small | 31 | E3 base and E9 foreground. | P0 |
| 28 | Lattice left | 22 | E4 base and E9 foreground. | P0 |
| 29 | Lattice right | 22 | E5 base and E9 foreground. | P0 |
| 30 | Torch with debris | 0 | Runtime result when a falling loose floor hits a torch tile; debris E97/E98/E43/E100, torch base E146, and gameplay flame P1–9. | P0 |

Counts are raw tile-type occurrences in the shipped level records. Zero does
not mean unreachable: tile 5 is synthesized from tile 6, tile 13 is inserted
by the mirror event, and tile 30 is produced by falling-floor logic. Tile value
31 is not in the 31-entry tile table and is not a normal drawable tile type.

### Room-bank resource rule

For the shipped CGA room DATs, every decodable image in the base environment
bank and optional replacement bank corresponds to a referenced logical image.
The complete referenced logical set is:

```text
1–6, 9–13, 30–75, 77–78, 80–151
```

Optional `1200+n` graphics are loaded only for these original ranges:

```text
1–13, 30–31, 75–83, 86–91, 101–123, 127–143
```

Slots outside the intersection are classified as unused compatibility slots
by the editor rather than gameplay artwork.

## Non-room image banks

| Archive/resources | Original use | Required phase at bias 0 |
|---|---|---|
| `PRINCE` 151–159 | Flame animation shared by gameplay torches and cinematic torches | P0+P2 |
| `PRINCE` 160–161 | Sword lying on floor | P0 |
| `PRINCE` 162–165 | Potion bottles | P0 |
| `PRINCE` 166–173 | Potion bubbles and bubble mask | P2 |
| `PRINCE` 701–734 | Moving/carried sword frames | P0+P2 |
| `KID` 401–616 | Every Kid and mouse frame-table image | P0+P2 |
| `KID` 617–618 | Kid hit-point icons at `X=7*i` | P0+P2 |
| `KID` 619 | Actor-relative hurt splash | P0+P2 |
| `GUARD`, `FAT`, `SKEL`, `VIZIER`, `SHADOW` 751 | Guard hit points at `X=314-7*i` | P0+P2 |
| Same archives, 752 | Actor-relative hurt splash | P0+P2 |
| Same archives, 753–775 and 777–784 when present | Moving guard-family frame-table images | P0+P2 |
| Same archives, 776 | Frame-table image 25 is unreferenced | Unused; P0 compatibility slot |
| `SHADOW` visible actor frames | Each is drawn at both X and X+1 | P0+P2 necessarily |
| `TITLE` 41–45, 51–55 | Title, story, credits, and Hall of Fame at X=0/24/48/96 | P0 |

The Kid frame table references every image index 0–215. The guard frame table
references 2–24 and 26–33; indices 0 and 1 are the separately drawn HP and
hurt graphics, while index 25 (`resource 776`) has no original reference.

## Cinematics

The princess-room torch positions are `(xh,xl)=(11,5)` and `(26,3)`, producing
X=93 and X=211. Both are odd, so the very same flame resources that are P0 in
gameplay are P2 in cinematics. This explains the observed red/blue torch color
change without requiring four independent alignments.

Fixed princess-room images are all P0:

- `PV` 951 background at X=0
- `PV` 952 pillar at X=240
- `PV` 953–959 hourglass at X=152
- `PV` 960–962 sand at X=160
- `PV` 981 bed at X=0

For the scripted `PV` actor banks, the replay audit includes exact sequence
DX, frame DX, `320/280` conversion, facing, image width, and the post-flip
subtraction. Every shipped PV image has this contract:

```text
P0+P2:
801–804, 808, 851–859

P0 only:
805–806, 809–811, 813–814,
864–865, 867, 869, 874–876, 878–879, 881, 886–888,
903–904, 906, 908–909, 911, 914–923, 925, 927–929,
951–962, 981

P2 only:
807, 812, 815–817,
860–863, 866, 868, 870–873, 877, 880, 882–885,
901, 905, 907, 910, 912–913, 924, 926, 930

Unused compatibility slot:
902
```

The opening, level 2/4/6/8/9/12 scenes, ending, Kid, mouse, princess, and Jaffar
draws are included. Sound-wait loops settle on a fixed animation frame; the
moving scripted loops are replayed for their exact frame counts.

## What the editor now does

When a recognized original archive/resource is first edited, schema-v6
projects select **Original DOS 1.3 engine (automatic)** and create only the
audited slots:

- P0 for fixed room/title/background resources;
- P2 for potion bubbles and the exact P2-only cinematic records;
- P0+P2 for moving actors, moving swords, shared flames, and exact two-parity
  cinematic records;
- one P0 compatibility slot for an image proven unused.

Coverage controls are locked while the automatic policy is selected. The
designer can still edit each required variant, choose the legacy DAT fallback,
lock transparency geometry, import/export GIFs, and generate each enabled
phase independently. **Manual / custom executable** restores P0–P3 coverage
controls. Older schema-v1 through schema-v4 projects migrate to Manual so a
new audit never silently changes previously authored artwork.

The exported manifest records the policy, audit ID, per-resource evidence, and
both the normalized and selected phase contracts. Automatic manifests require
global bias zero; a calibrated odd bias requires Manual P1/P3 artwork.

## Runtime patch recommendation

For each draw, retain the original engine's final 320-column X calculation,
including the right-facing image-width subtraction. Select the resource family
after that value is known:

```text
slot = (global_phase_bias + 2*(final_x_320 & 1)) & 3
```

For a left-clipped low-level blit, use the full destination-minus-source formula
instead. Missing slots should fall back to the manifest's explicit
`fallback_phase`, never to a nearest-color average.

Horizontal flipping is a separate transform dimension. Chtabs 0 and 2–5
(moving sword, Kid, cinematic actors, and guards) are runtime-flippable, while
environment, flame/potion, princess-room, and title banks are not. A P0/P2
bank solves carrier placement but does not mathematically make an optimized
pattern invariant under horizontal reversal. If exact color in both facings is
required, the eventual executable format should key those moving banks by
`(phase, facing)` or store preflipped direction variants. Version 0.4.29 does
not pretend that a phase-only bank solves this separate issue.

## Known limit in the available source

SDLPoP's `parse_grmode()` currently forces VGA, and portions of the original
CGA image/mask pairing in `draw_back_fore()` and `draw_mid()` remain commented.
The resource-360 wall palette reports four raw CGA image records while the
shared logical wall table names more draw IDs, consistent with original
driver-side image/mask expansion. The exact raw wall mask-to-logical-slot
identity therefore cannot be proven from the active SDL loader alone.

This does not weaken the placement result: every wall call supplies an even
final X, and the VGA/EGA-only random wall-detail calls are explicitly skipped
for CGA/Hercules. All four raw wall records are consequently P0 regardless of
their original driver-side image/mask pairing.
