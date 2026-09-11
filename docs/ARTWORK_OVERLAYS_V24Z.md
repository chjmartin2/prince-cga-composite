# V24Z painted wall bases and overlay editor

Chris requested editable overlay variations without generated palace color fills,
and identified `C:\DOS\POP_V24Y` as the absolute latest artwork source. Its new
CPALACE has 225 standard resources (no experimental bank); its PRINCE.DAT is also
updated. `runtime/artwork_v24z.json` authenticates the full 33-DAT snapshot in
`runtime/build/Prince-Composite-V24Z/input`. Never replace it with older assets.

The builder preserves every input DAT byte except CPALACE's index/container:
every original CPALACE resource payload remains exact. It appends header 1600
with 19 images, current face copies 1601/1602, existing no-dither divider images
1603–1617, bottom copy 1618, and full painted wall 1619. The last concatenates
the current 364 and 363 indexed pixels (32×60 + 32×3), without conversion.
PRINCE.DAT remains byte-identical to the author snapshot.

## Native changes

`v24z_engine.py` authenticates the V24Y EXE before a closed set of changes.
At 0000:C831 the former five rectangle-fill calls are bypassed by one native
wall-image queue call for image 19, ending at draw_bottom_y (DS:4550).
At 0000:C9B7 image 18 replaces the bottom fill only for bottom/background passes;
foreground draws already include that strip in image 19. Native divider choices,
PRNG advancement, placement and transparent blitters remain in effect.

New bases consume image queue entries. The native redraw visits an above-screen
row too; keeping all its invisible decals caused the 200-entry foreground queue
to overflow in dense rooms during development. The final build redirects the
five palace decal enqueue calls through an 18-byte shim at 0000:C870, inside
the bypassed fill code. It skips a decal only when its bottom Y is negative,
after the PRNG draw. Otherwise it tail-jumps to the original queue function.
Caller arguments and Pascal far-return cleanup are preserved. No new allocation,
global queue changes, actor hooks or phase tables are introduced.

The V24Y P0 wall hook and all high-code allocation/fill tables are preserved,
apart from the version marker. Ordinary black/UI/cutscene fills still function;
the palace path queues no color fills. The old palace carrier table is dormant.
Static native captures across all 336 supported room slots have maximum queue
counts 176 back / 200 fore / 0 wipes / 1 mid. Custom level layouts outside this
fixed Prince 1.3 set would require their own queue-capacity audit.

## Editor and exchange

Explorer 0.6.1 adds a labeled browser, enlarged before/mask/after inspector,
base-only/full-room views, in-room outlines and direct pixel-editor access.
The mask distinguishes transparent holes from opaque black. Full CGA frames
are assembled and decoded before cropping; checkerboard/cyan are UI annotations.
See `editor/docs/EDITING_OVERLAYS.md` for usage.

Contract `pop13-composite-artwork-walls-p0-v1` distinguishes these DAT bases from
V24Y's fills. WALLS.JSON declares DAT artwork and an empty fill map; submitted
carrier settings are rejected. The builder validates complete package hashes,
geometry and protected records. Older V24Y packages and projects remain readable.
The new palace bases are P0-only and have no direct VGA bitmap counterpart.

Build with `runtime/build_v24z.py`; capture with `runtime/capture_v24z.py`;
verify with `runtime/verify_v24z.py` and `runtime/verify_overlay_exchange.py`.
Native JSON queue recipes and raw DS/VRAM evidence are retained.
Build outputs, the one-EXE installer ZIP and full artwork ZIP are under
`runtime/build/Prince-Composite-V24Z`. V23G and prior experiments are preserved.
Visual/playthrough acceptance by Chris remains pending.

Delivery and checks: 46 verified files in `C:\DOS\POP_V24Z`, standalone Explorer
0.6.1 and the installer/artwork ZIPs under `releases/`. 205 unit tests, the actual
Tk workflow under both development and bundled Python, standalone EXE launch,
336 exact room replays, installer regression suite, fourteen starts, full ending,
deterministic rebuild and modified overlay-mask/base installation pass.
