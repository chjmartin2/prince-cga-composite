#!/usr/bin/env python3
"""Build the shareable Prince 1.3 CGA memory-map artifacts.

All byte counts in this file are derived from the authenticated US Prince of
Persia 1.3 executable and the DAT set documented in ../REPORT.md.  The script
contains no game data and writes only CSV, JSON, SVG, and HTML summaries.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"

SOURCE_EXE_SHA256 = "24fdc79b4de563348313b50d717e171919191e5c38559f5bdd6a4751d39b7158"
NOMINAL_CONVENTIONAL_BYTES = 640 * 1024

# Exact MCB snapshot made by MCBMAP.COM after it shrank itself.  DOS MEM rounds
# this environment to "632 Kb free"; the MCB values are the authoritative
# byte-level measurements used below.
MCB_PROBE_FREE_BYTES = 0x9E2B * 16
MCB_PROBE_LARGEST_FREE_BYTES = 0x9E27 * 16
MCB_PROBE_PAYLOAD_BYTES = (0x09 + 0x45) * 16
DOS_SHELL_PAYLOAD_BYTES = 0x16F0 + (0x01 + 0x10) * 16
MCB_PROBE_HEADER_BYTES = 6 * 16
CONVENTIONAL_TOP_GUARD_BYTES = 16

# MEMTRACE.COM is deliberately a small resident EXEC parent.  These values let
# the 640-KiB trace reconcile byte-for-byte and disclose observer overhead.
TRACE_PARENT_PAYLOAD_BYTES = (0x09 + 0x69) * 16
TRACE_BASE_FREE_PARAGRAPHS = 40455
TRACE_BASE_FREE_BYTES = TRACE_BASE_FREE_PARAGRAPHS * 16
CHILD_ENVIRONMENT_BYTES = 0x09 * 16

# Borland/Microsoft-compatible C startup: PSP + load-module-to-DGROUP + one
# 64-KiB DGROUP window.  The runtime AH=4Ah shrink is verified in REPORT.md.
MAIN_DOS_BLOCK_PARAGRAPHS = 0x10 + 0x1BA3 + 0x1000
MAIN_DOS_BLOCK_BYTES = MAIN_DOS_BLOCK_PARAGRAPHS * 16

FAR_PROBE_REQUEST_BYTES = 0xFFC0
FAR_ARENA_PARAGRAPHS = 0x0FFD
FAR_ARENA_PAYLOAD_BYTES = FAR_ARENA_PARAGRAPHS * 16

STARTUP_POOLS = {
    "pc": {
        "bootstrap_far_arena_payload": 0x0200 * 16,
        "probe_full_far_arena_count": 7,
        "total_far_arena_count": 8,
        "far_arena_payload_each": FAR_ARENA_PAYLOAD_BYTES,
        "far_pool_payload": 0x0200 * 16 + 7 * FAR_ARENA_PAYLOAD_BYTES,
        "fixed_far_arena_metadata_and_padding": 12 + 7 * 14,
        "far_block_chain_extent_capacity": 466_498,
        "dos_free_payload_after_probe": 86 * 16,
        "mcb_count_after_probe": 16,
        "child_block_count": 10,
        "child_owned_payload": (
            CHILD_ENVIRONMENT_BYTES
            + MAIN_DOS_BLOCK_BYTES
            + 0x0200 * 16
            + 7 * FAR_ARENA_PAYLOAD_BYTES
        ),
        "child_owned_payload_plus_its_mcb_headers": 645_904,
        "note": "One 8-KiB bootstrap arena plus seven full probe arenas are retained.",
    },
    "sb": {
        "bootstrap_far_arena_payload": 0x0200 * 16,
        "probe_full_far_arena_count": 7,
        "total_far_arena_count": 8,
        "far_arena_payload_each": FAR_ARENA_PAYLOAD_BYTES,
        "far_pool_payload": 0x0200 * 16 + 7 * FAR_ARENA_PAYLOAD_BYTES,
        "fixed_far_arena_metadata_and_padding": 12 + 7 * 14,
        "far_block_chain_extent_capacity": 466_498,
        "dos_free_payload_after_probe": 86 * 16,
        "mcb_count_after_probe": 16,
        "child_block_count": 10,
        "child_owned_payload": (
            CHILD_ENVIRONMENT_BYTES
            + MAIN_DOS_BLOCK_BYTES
            + 0x0200 * 16
            + 7 * FAR_ARENA_PAYLOAD_BYTES
        ),
        "child_owned_payload_plus_its_mcb_headers": 645_904,
        "note": "Same startup arena geometry as PC speaker; later samples use far-pool space.",
    },
    "mt32": {
        "bootstrap_far_arena_payload": 0x0800 * 16,
        "probe_full_far_arena_count": 6,
        "total_far_arena_count": 7,
        "far_arena_payload_each": FAR_ARENA_PAYLOAD_BYTES,
        "far_pool_payload": 0x0800 * 16 + 6 * FAR_ARENA_PAYLOAD_BYTES,
        "fixed_far_arena_metadata_and_padding": 12 + 6 * 14,
        "far_block_chain_extent_capacity": 425_600,
        "dos_free_payload_after_probe": 2644 * 16,
        "mcb_count_after_probe": 15,
        "child_block_count": 9,
        "child_owned_payload": (
            CHILD_ENVIRONMENT_BYTES
            + MAIN_DOS_BLOCK_BYTES
            + 0x0800 * 16
            + 6 * FAR_ARENA_PAYLOAD_BYTES
        ),
        "child_owned_payload_plus_its_mcb_headers": 604_976,
        "note": (
            "PRINCE.DAT/65535 grows the bootstrap far arena to 32 KiB for the "
            "transient MT-32 SysEx bank before the probe, so only six additional "
            "full arenas fit."
        ),
    },
}

SURFACES = {
    "gameplay": {
        "width": 320,
        "height": 192,
        "near_request": 48 + 192 * 2,
        "near_live": 50 + 386,
        "far_request": 320 // 4 * 192,
        "far_live": 320 // 4 * 192 + 2,
    },
    "full_screen": {
        "width": 320,
        "height": 200,
        "near_request": 48 + 200 * 2,
        "near_live": 50 + 402,
        "far_request": 320 // 4 * 200,
        "far_live": 320 // 4 * 200 + 2,
    },
}

SOUND_PROFILES = {
    "pc": {
        "label": "PC speaker",
        "cli_token": "STDSND",
        "cli_mode": 0,
        "dynamic_resource_path_observed": True,
        "core_request": 3280,
        "core_live": 3388,
        "core_blocks": 44,
        "core_handle_peak_live": 438,
        "core_load_peak_live": 3826,
        "title_request": 1047,
        "title_live": 1062,
        "core_plus_title_load_peak_live": 4640,
        "ending_request": 1847,
        "ending_live": 1850,
        "core_plus_ending_load_peak_live": 5428,
        "optional_all_request": 3659,
        "optional_all_live": 3692,
        "event_groups": {
            "skeleton": [62, 64],
            "mirror": [149, 152],
            "chomper": [235, 240],
            "spikes": [319, 324],
        },
        "lookup": "IBM_SND*.DAT",
        "note": "Smallest retained sound set; STDSND command-line branch.",
    },
    "sb": {
        "label": "Sound Blaster",
        "cli_token": "SBLAST",
        "cli_mode": 3,
        "dynamic_resource_path_observed": False,
        "core_request": 89042,
        "core_live": 89148,
        "core_blocks": 45,
        "core_handle_peak_live": 1016,
        "core_load_peak_live": 90164,
        "title_request": 11507,
        "title_live": 11522,
        "core_plus_title_load_peak_live": 101136,
        "ending_request": 13587,
        "ending_live": 13590,
        "core_plus_ending_load_peak_live": 103204,
        "optional_all_request": 51251,
        "optional_all_live": 51284,
        "event_groups": {
            "skeleton": [2679, 2682],
            "mirror": [4245, 4248],
            "chomper": [9748, 9752],
            "spikes": [9485, 9490],
        },
        "lookup": "DIGISND3 > DIGISND1 > MIDISND1 > IBM_SND1",
        "note": (
            "Worst exact resource-selected steady case; includes the retained 1,201-byte "
            "OPL bank. The isolated DOSBox run selected mode 3 but did not set sfDigi."
        ),
    },
    "mt32": {
        "label": "MT-32",
        "cli_token": "MIDI",
        "cli_mode": 6,
        "dynamic_resource_path_observed": False,
        "core_request": 10573,
        "core_live": 10690,
        "core_blocks": 44,
        "core_handle_peak_live": 930,
        "core_load_peak_live": 11620,
        "title_request": 5611,
        "title_live": 5626,
        "core_plus_title_load_peak_live": 16782,
        "ending_request": 13587,
        "ending_live": 13590,
        "core_plus_ending_load_peak_live": 24746,
        "optional_all_request": 19954,
        "optional_all_live": 19988,
        "event_groups": {
            "skeleton": [134, 136],
            "mirror": [101, 104],
            "chomper": [281, 286],
            "spikes": [240, 246],
        },
        "lookup": "MT32SND1 > MIDISND1 > IBM_SND1",
        "note": (
            "A 21,152-byte SysEx patch bank is transient during setup and freed before assets "
            "load. The hooked run proves early geometry but stalled before resource opens."
        ),
    },
}

GRAPHIC_COMPONENTS = [
    # key, archive/base, images, shift, mode, near request, far request,
    # total request, total live allocator-block bytes, far blocks, note
    ("sword", "PRINCE/700", 34, 0, "unpacked", 142, 2601, 2743, 2824, 34,
     "Permanent slot 0"),
    ("flame_sword_potion", "PRINCE/150", 23, 1, "unpacked", 190, 4316, 4506, 4608, 46,
     "Permanent slot 1; image and mask pointers"),
    ("kid", "KID/400", 219, 0, "packed", 882, 35061, 35943, 36484, 219,
     "Gameplay slot 2; retained compressed records"),
    ("dungeon", "CDUNGEON/200", 151, 1, "unpacked", 1214, 30406, 31620, 31884, 126,
     "Dungeon environment slot 6; 88 null pointers"),
    ("dungeon_wall", "CDUNGEON/360", 4, 1, "unpacked", 38, 4014, 4052, 4072, 8,
     "Dungeon wall slot 7"),
    ("palace", "CPALACE/200", 151, 1, "unpacked", 1214, 31142, 32356, 32620, 128,
     "Palace environment slot 6; 87 null pointers"),
    ("palace_wall", "CPALACE/360", 4, 1, "unpacked", 38, 4014, 4052, 4072, 8,
     "Palace wall slot 7"),
    ("guard", "GUARD/750", 34, 0, "unpacked", 142, 18427, 18569, 18648, 34,
     "Whole-level normal guard family"),
    ("fat", "FAT/750", 34, 0, "unpacked", 142, 17567, 17709, 17790, 34,
     "Whole-level fat guard family"),
    ("skeleton", "SKEL/750", 28, 0, "unpacked", 118, 15058, 15176, 15240, 28,
     "Whole-level skeleton family"),
    ("vizier", "VIZIER/750", 34, 0, "unpacked", 142, 17353, 17495, 17576, 34,
     "Whole-level vizier family"),
    ("shadow", "SHADOW/750", 32, 0, "unpacked", 134, 14873, 15007, 15084, 32,
     "Whole-level level-12 shadow family"),
    ("pv_800", "PV/800", 17, 0, "unpacked", 74, 8065, 8139, 8184, 17,
     "Princess-room actor table"),
    ("pv_850", "PV/850", 38, 0, "unpacked", 158, 22001, 22159, 22244, 38,
     "Opening-story actor table"),
    ("pv_900", "PV/900", 30, 0, "unpacked", 126, 13761, 13887, 13956, 30,
     "Later cutscene/reunion actor table"),
    ("pv_950", "PV/950", 12, 1, "unpacked", 102, 68880, 68982, 69032, 24,
     "Princess-room backdrop; resource 951 image and mask are 32,006 bytes each"),
    ("pv_980", "PV/980", 1, 0, "unpacked", 10, 4926, 4936, 4940, 1,
     "Temporary bed image"),
    ("title_40", "TITLE/40", 5, 0, "packed", 26, 11783, 11809, 11824, 5,
     "Packed full-screen story images"),
    ("title_50", "TITLE/50", 5, 0, "packed", 26, 24700, 24726, 24742, 5,
     "Packed title images"),
]

ISOLATED_GRAPHIC_LOAD_PEAK_LIVE = {
    "sword": 4992,
    "flame_sword_potion": 6406,
    "kid": 38844,
    "dungeon": 35200,
    "dungeon_wall": 7422,
    "palace": 36096,
    "palace_wall": 7586,
    "guard": 20704,
    "fat": 19830,
    "skeleton": 17218,
    "vizier": 19618,
    "shadow": 17058,
    "pv_800": 10788,
    "pv_850": 23816,
    "pv_900": 16568,
    "pv_950": 73228,
    "pv_980": 9062,
    "title_40": 12520,
    "title_50": 25438,
}

OPTIONAL_GRAPHICS = [
    (0, "1-9", "palace", 8232, 8260),
    (1, "30-31", "dungeon", 1178, 1188),
    (2, "75-77", "palace", 3264, 3272),
    (3, "78-83", "palace", 6264, 6284),
    (4, "86-91", "dungeon", 7546, 7572),
    (4, "86-91", "palace", 7978, 8004),
    (5, "101-123", "both", 12194, 12296),
    (6, "127-143", "both", 7936, 8012),
    (7, "10-13", "palace", 5152, 5168),
]

ARCHIVES = [
    # name, file bytes, index bytes, resource count, payload bytes, handle request, target use
    ("CDUNGEON.DAT", 9407, 1642, 205, 7554, 1724, "CGA dungeon"),
    ("CPALACE.DAT", 12889, 1802, 225, 10856, 1884, "CGA palace"),
    ("EDUNGEON.DAT", 10165, 1746, 218, 8195, 1828, "Not opened in CGA"),
    ("EPALACE.DAT", 13876, 1874, 234, 11762, 1956, "Not opened in CGA"),
    ("VDUNGEON.DAT", 10933, 1746, 218, 8963, 1828, "Not opened in CGA"),
    ("VPALACE.DAT", 14212, 1906, 238, 12062, 1988, "Not opened in CGA"),
    ("DIGISND1.DAT", 50101, 162, 20, 49913, 244, "SB core lookup"),
    ("DIGISND2.DAT", 32426, 58, 7, 32355, 140, "SB optional lookup"),
    ("DIGISND3.DAT", 31008, 34, 4, 30964, 116, "SB core lookup; highest priority"),
    ("FAT.DAT", 6521, 282, 35, 6198, 364, "Level 6 family"),
    ("GUARD.DAT", 6950, 274, 34, 6636, 356, "Normal guard family"),
    ("GUARD1.DAT", 117, 10, 1, 100, 92, "Palace guard palette overlay"),
    ("GUARD2.DAT", 117, 10, 1, 100, 92, "Dungeon guard palette overlay"),
    ("IBM_SND1.DAT", 3684, 354, 44, 3280, 436, "PC/core fallback"),
    ("IBM_SND2.DAT", 3784, 106, 13, 3659, 188, "PC/optional fallback"),
    ("KID.DAT", 37149, 1762, 220, 35161, 1844, "Gameplay Kid table"),
    ("LEVELS.DAT", 37031, 130, 16, 36879, 212, "One 2,305-byte resource copied per level"),
    ("MIDISND1.DAT", 7096, 130, 16, 6944, 212, "MIDI/core fallback"),
    ("MIDISND2.DAT", 18958, 50, 6, 18896, 132, "MIDI/optional fallback"),
    ("MT32SND1.DAT", 3833, 194, 24, 3609, 276, "MT-32 core lookup"),
    ("MT32SND2.DAT", 1129, 58, 7, 1058, 140, "MT-32 optional lookup"),
    ("PRINCE.DAT", 25600, 514, 64, 25016, 596, "Permanent graphics and device data"),
    ("PV.DAT", 25829, 826, 103, 24894, 908, "Princess-room cutscenes"),
    ("SHADOW.DAT", 4715, 266, 33, 4410, 348, "Level 12 family"),
    ("SKEL.DAT", 3868, 234, 29, 3599, 316, "Level 3 family"),
    ("TITLE.DAT", 36799, 98, 12, 36683, 180, "Title/story/high-score"),
    ("VIZIER.DAT", 6111, 282, 35, 5788, 364, "Level 13 family"),
]

# Exact retained allocations for the stock executable/DATs.  Totals include
# graphics and selected sound resources but exclude the fixed EXE block,
# offscreen surfaces, loader scratch, DAT handles, and arena/MCB overhead.
LEVEL_ROWS = [
    # level, env, guard, optional image rows, graphics req/live, PC req/live,
    # SB req/live, MT-32 req/live, memory-neutral special/event summary
    (0, "Dungeon", "GUARD", "4|5|6", 125109, 126400, 128943, 130352, 233384, 234790, 136203, 137622,
     "Demo; chomper and spike sounds preloaded"),
    (1, "Dungeon", "GUARD", "1|6", 106547, 107720, 110208, 111496, 207753, 209040, 117494, 118792,
     "Falling entry; skeleton-tile and spike sounds preloaded"),
    (2, "Dungeon", "GUARD", "4|6", 112915, 114104, 116514, 117816, 211442, 212742, 123728, 125040,
     "Early pre-level princess cutscene; spike sounds preloaded"),
    (3, "Dungeon", "SKEL", "1|5|6", 115348, 116608, 119244, 120624, 226302, 227680, 126576, 127966,
     "Skeleton wakes/reappears; family already resident"),
    (4, "Palace", "GUARD", "0|2|3|5|6", 136059, 137380, 140042, 141484, 248579, 250018, 147254, 148706,
     "Mirror and shadow emergence; no event-time DAT load"),
    (5, "Palace", "GUARD", "0|3|4|5|6", 140773, 142112, 144607, 146064, 249048, 250502, 151867, 153334,
     "Shadow steals potion using KID frames"),
    (6, "Palace", "FAT", "0|3|5|6|7", 137087, 138418, 140921, 142370, 245362, 246808, 148181, 149640,
     "Fat guard resident; scripted shadow uses KID frames"),
    (7, "Dungeon", "GUARD", "1|5|6", 118741, 120016, 122637, 124032, 229695, 231088, 129969, 131374,
     "Ordinary dungeon gameplay"),
    (8, "Dungeon", "GUARD", "1|5|6", 118741, 120016, 122637, 124032, 229695, 231088, 129969, 131374,
     "Mouse event uses KID frames; no event-time load"),
    (9, "Dungeon", "GUARD", "4|5|6", 125109, 126400, 128943, 130352, 233384, 234790, 136203, 137622,
     "Late pre-level princess cutscene"),
    (10, "Palace", "GUARD", "0|3|4|5|6", 140773, 142112, 144607, 146064, 249048, 250502, 151867, 153334,
     "Largest stock retained-asset state (tie with level 5)"),
    (11, "Palace", "GUARD", "3|5|6", 124563, 125848, 128397, 129800, 232838, 234238, 135657, 137070,
     "Ordinary palace gameplay"),
    (12, "Dungeon", "SHADOW", "1|4|6", 110531, 111728, 114192, 115504, 211737, 213048, 121478, 122800,
     "Shadow fight/unite; SHADOW family resident for whole level"),
    (13, "Dungeon", "VIZIER", "4", 103905, 105020, 107185, 108408, 192947, 194168, 114478, 115710,
     "Vizier fight; VIZIER family resident for whole level"),
    (14, "Palace", "NONE", "0|3|7", 99248, 100320, 102528, 103708, 188290, 189468, 109821, 111010,
     "Princess room; reunion starts in room 5"),
    (15, "Dungeon", "NONE", "", 78864, 79872, 82144, 83260, 167906, 169020, 89437, 90562,
     "Copy-protection level; dialog uses transient peel memory"),
]

LEVEL_NEAR_LIVE = {
    "GUARD": 2620,
    "FAT": 2620,
    "SKEL": 2596,
    "SHADOW": 2612,
    "VIZIER": 2620,
    "NONE": 2476,
}

CUTSCENE_LEVELS = {2: "early", 4: "late", 6: "late", 8: "late", 9: "late", 12: "late"}

SCENE_GRAPHICS = {
    "opening_title": [43784, 43998, 392],
    "opening_pv": [74523, 74884, 676],
    "early_pv_gameplay": [110466, 111368, 1560],
    "late_pv_gameplay": [102194, 103080, 1528],
    "late_pv_no_kid": [66251, 66596, 644],
    "ending_title": [43784, 43998, 392],
}

SCENE_LOAD_PEAK_LIVE = {
    # Includes loader scratch/handles and, for a maximizing decoded LZG
    # resource, the 1,026-byte live near dictionary. Excludes surface and EXE.
    "opening_title": {"pc": 49144, "sb": 145364, "mt32": 61010},
    "opening_pv": {"pc": 89976, "sb": 186196, "mt32": 101842},
    "early_pv_gameplay": {"pc": 125398, "sb": 211158, "mt32": 132700},
    # Early/late actor selection happens only after the shared PV950/PV980
    # background peak, so all gameplay PV callers have the same load maximum.
    "late_pv_gameplay": {"pc": 125398, "sb": 211158, "mt32": 132700},
    "late_pv_no_kid": {"pc": 88914, "sb": 174674, "mt32": 96216},
    "ending_title": {"pc": 49932, "sb": 147432, "mt32": 68974},
}

TITLE_DRAW_TRANSIENT_LIVE = 33_034

PHASE_BANKS_V21B = {
    "phase": {"file_bytes": 44577, "request": 108123, "live": 108632, "far_live": 107748},
    "phase2": {"file_bytes": 37695, "request": 87159, "live": 87656, "far_live": 86772},
    "phase3": {"file_bytes": 39877, "request": 88206, "live": 88688, "far_live": 87804},
}


def round_even(value: int) -> int:
    return (value + 1) & ~1


def block_live(request: int) -> int:
    return round_even(request) + 2


def arena_owned_bytes(request: int) -> int:
    """Owned data bytes in a newly requested DOS far-heap arena."""

    capacity = max(240, round_even(request))
    return 16 * math.ceil((capacity + 14) / 16)


def level_dicts() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in LEVEL_ROWS:
        (
            level, environment, guard, optional_rows, graphics_request,
            graphics_live, pc_request, pc_live, sb_request, sb_live,
            mt_request, mt_live, special,
        ) = row
        near_live = LEVEL_NEAR_LIVE[guard]
        values = {
            "pc": (pc_request, pc_live),
            "sb": (sb_request, sb_live),
            "mt32": (mt_request, mt_live),
        }
        item: dict[str, Any] = {
            "level": level,
            "environment": environment,
            "guard_family": guard,
            "optional_graphic_rows": optional_rows,
            "graphics_request": graphics_request,
            "graphics_live": graphics_live,
            "near_graphics_live": near_live,
            "cutscene_before": CUTSCENE_LEVELS.get(level, "none"),
            "special": special,
            "devices": {},
        }
        for device, (request, live) in values.items():
            far_asset_live = live - near_live
            surface = SURFACES["gameplay"]
            far_live_with_surface = far_asset_live + surface["far_live"]
            pool = STARTUP_POOLS[device]
            item["devices"][device] = {
                "asset_request": request,
                "asset_live": live,
                "far_asset_live": far_asset_live,
                "surface_far_live": surface["far_live"],
                "far_live_with_surface": far_live_with_surface,
                "startup_far_pool_payload": pool["far_pool_payload"],
                "startup_far_block_chain_extent_capacity": pool["far_block_chain_extent_capacity"],
                "aggregate_free_block_extent_before_hole_contiguity": (
                    pool["far_block_chain_extent_capacity"] - far_live_with_surface
                ),
                "dos_free_payload_outside_crt_pools_after_startup_probe": (
                    pool["dos_free_payload_after_probe"]
                ),
            }
        result.append(item)
    return result


def scene_dicts() -> list[dict[str, Any]]:
    definitions = [
        ("opening_title", "Opening title/story cards", "opening_title", "title", "full_screen",
         "TITLE 40/50 are resident; title sounds 50-55 are resident."),
        ("opening_pv", "Opening princess/Jaffar story", "opening_pv", "title", "full_screen",
         "load_intro(free_sounds=0): title sounds remain while PV tables load."),
        ("pre_level_2", "Pre-level 2 cutscene", "early_pv_gameplay", "core", "gameplay",
         "KID and gameplay buffer remain; slots 3+ and optional sounds are replaced."),
        ("pre_levels_4_6_8_9_12", "Pre-level 4/6/8/9/12 cutscenes", "late_pv_gameplay", "core", "gameplay",
         "Uses PV/900 rather than PV/850; no room or event reload occurs inside the level."),
        ("ending_reunion", "Level 14 reunion animation", "late_pv_gameplay", "core", "gameplay",
         "Level assets/optional sounds are freed; KID remains until the post-hug clear."),
        ("time_expired", "Time-expired princess scene", "late_pv_no_kid", "core", "full_screen",
         "A global clear precedes a full-screen buffer and the late PV scene."),
        ("ending_title", "Ending title/high score", "ending_title", "ending", "full_screen",
         "A global clear follows the reunion; then sound 56 and TITLE 40/50 load."),
    ]
    result: list[dict[str, Any]] = []
    for key, label, graphics_key, sound_kind, surface_kind, note in definitions:
        graphics_request, graphics_live, near_graphics_live = SCENE_GRAPHICS[graphics_key]
        item: dict[str, Any] = {
            "key": key,
            "label": label,
            "graphics_request": graphics_request,
            "graphics_live": graphics_live,
            "near_graphics_live": near_graphics_live,
            "surface": surface_kind,
            "note": note,
            "devices": {},
        }
        for device, sound in SOUND_PROFILES.items():
            sound_request = sound["core_request"]
            sound_live = sound["core_live"]
            if sound_kind == "title":
                sound_request += sound["title_request"]
                sound_live += sound["title_live"]
            elif sound_kind == "ending":
                sound_request += sound["ending_request"]
                sound_live += sound["ending_live"]
            asset_request = graphics_request + sound_request
            asset_live = graphics_live + sound_live
            far_asset_live = asset_live - near_graphics_live
            surface = SURFACES[surface_kind]
            far_live_with_surface = far_asset_live + surface["far_live"]
            pool = STARTUP_POOLS[device]
            device_info: dict[str, Any] = {
                "sound_request": sound_request,
                "sound_live": sound_live,
                "asset_request": asset_request,
                "asset_live": asset_live,
                "far_asset_live": far_asset_live,
                "surface_far_live": surface["far_live"],
                "far_live_with_surface": far_live_with_surface,
                "startup_far_pool_payload": pool["far_pool_payload"],
                "startup_far_block_chain_extent_capacity": pool["far_block_chain_extent_capacity"],
                "aggregate_free_block_extent_before_hole_contiguity": (
                    pool["far_block_chain_extent_capacity"] - far_live_with_surface
                ),
                "dos_free_payload_outside_crt_pools_after_startup_probe": (
                    pool["dos_free_payload_after_probe"]
                ),
            }
            peak_group = SCENE_LOAD_PEAK_LIVE.get(graphics_key)
            if peak_group is not None:
                device_info["asset_load_peak_live"] = peak_group[device]
                device_info["load_peak_live_with_surface"] = (
                    peak_group[device] + surface["near_live"] + surface["far_live"]
                )
            if graphics_key in {"opening_title", "ending_title"}:
                device_info["draw_peak_live_with_surface"] = (
                    asset_live
                    + surface["near_live"]
                    + surface["far_live"]
                    + TITLE_DRAW_TRANSIENT_LIVE
                )
            item["devices"][device] = device_info
        result.append(item)
    return result


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_data_files(model: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "memory-model.json").write_text(
        json.dumps(model, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    level_rows: list[dict[str, Any]] = []
    for item in model["levels"]:
        row = {key: value for key, value in item.items() if key != "devices"}
        for device, values in item["devices"].items():
            for key, value in values.items():
                row[f"{device}_{key}"] = value
        level_rows.append(row)
    write_csv(
        DATA_DIR / "levels.csv",
        list(level_rows[0]),
        level_rows,
    )

    scene_rows: list[dict[str, Any]] = []
    for item in model["scenes"]:
        row = {key: value for key, value in item.items() if key != "devices"}
        for device, values in item["devices"].items():
            for key, value in values.items():
                row[f"{device}_{key}"] = value
        scene_rows.append(row)
    write_csv(DATA_DIR / "scenes.csv", list(scene_rows[0]), scene_rows)

    component_rows = []
    for row in GRAPHIC_COMPONENTS:
        keys = [
            "key", "archive_base", "images", "shift", "storage_mode",
            "near_request", "far_request", "total_request", "total_live",
            "far_blocks", "note",
        ]
        component = dict(zip(keys, row))
        component["isolated_load_peak_live"] = ISOLATED_GRAPHIC_LOAD_PEAK_LIVE[component["key"]]
        component_rows.append(component)
    write_csv(DATA_DIR / "graphic-components.csv", list(component_rows[0]), component_rows)

    optional_rows = [
        {
            "row": row,
            "logical_image_indices": indices,
            "environment": environment,
            "request": request,
            "live": live,
        }
        for row, indices, environment, request, live in OPTIONAL_GRAPHICS
    ]
    write_csv(DATA_DIR / "optional-graphics.csv", list(optional_rows[0]), optional_rows)

    archive_rows = [
        dict(
            zip(
                ["archive", "file_bytes", "index_bytes", "resource_count", "payload_bytes", "handle_request", "use"],
                row,
            )
        )
        for row in ARCHIVES
    ]
    write_csv(DATA_DIR / "archives.csv", list(archive_rows[0]), archive_rows)

    sound_rows: list[dict[str, Any]] = []
    for key, profile in SOUND_PROFILES.items():
        sound_rows.append({
            "device": key,
            "label": profile["label"],
            "cli_token": profile["cli_token"],
            "cli_mode": profile["cli_mode"],
            "dynamic_resource_path_observed": profile["dynamic_resource_path_observed"],
            "core_request": profile["core_request"],
            "core_live": profile["core_live"],
            "core_blocks": profile["core_blocks"],
            "core_handle_peak_live": profile["core_handle_peak_live"],
            "core_load_peak_live": profile["core_load_peak_live"],
            "title_50_55_request": profile["title_request"],
            "title_50_55_live": profile["title_live"],
            "core_plus_title_load_peak_live": profile["core_plus_title_load_peak_live"],
            "ending_56_request": profile["ending_request"],
            "ending_56_live": profile["ending_live"],
            "core_plus_ending_load_peak_live": profile["core_plus_ending_load_peak_live"],
            "optional_44_56_request": profile["optional_all_request"],
            "optional_44_56_live": profile["optional_all_live"],
            "lookup": profile["lookup"],
            "note": profile["note"],
        })
    write_csv(DATA_DIR / "sound-profiles.csv", list(sound_rows[0]), sound_rows)


def format_kib(value: int) -> str:
    return f"{value / 1024:.1f} KiB"


def write_static_svg(model: dict[str, Any]) -> None:
    """Write a self-contained, presentation-ready summary graphic."""

    width, height = 1600, 1220
    colors = {
        "bg": "#081018",
        "panel": "#101c28",
        "ink": "#eef6ff",
        "muted": "#a9b8c8",
        "grid": "#2d4052",
        "system": "#6b7b8c",
        "main": "#2f8fff",
        "boot": "#f3c64e",
        "arenas": "#35c7a0",
        "free": "#293746",
        "pc": "#f3c64e",
        "sb": "#ff6978",
        "mt32": "#58a6ff",
        "phase": "#c77dff",
        "critical": "#ff9f43",
    }
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<title>Prince of Persia 1.3 CGA conventional-memory atlas</title>",
        "<desc>Startup DOS allocation, per-level retained assets for three sound devices, and the final reunion allocation hazard.</desc>",
        "<style>",
        "text{font-family:Segoe UI,Arial,sans-serif;fill:#eef6ff}",
        ".title{font-size:36px;font-weight:500}.subtitle{font-size:17px;fill:#a9b8c8}",
        ".h2{font-size:23px;font-weight:500}.label{font-size:15px}.small{font-size:13px;fill:#a9b8c8}",
        ".num{font-variant-numeric:tabular-nums}.axis{stroke:#2d4052;stroke-width:1}",
        "</style>",
        f'<rect width="{width}" height="{height}" fill="{colors["bg"]}"/>',
        '<text x="70" y="62" class="title">Prince of Persia 1.3 — CGA conventional-memory atlas</text>',
        '<text x="70" y="92" class="subtitle">Authenticated US 1.3 binary · stock DOSBox 0.74-3 · 640 KiB conventional · no EMS, XMS, or UMB</text>',
    ]

    # Startup MCB allocation bars.
    out.extend([
        '<text x="70" y="145" class="h2">1 · What DOS owns immediately after Prince preallocates its CRT far heap</text>',
        '<text x="70" y="171" class="small">Exact MEMTRACE MCB accounting. The observer occupies 1.8 KiB and is shown with DOS/shell overhead.</text>',
    ])
    bar_x, bar_w, bar_h = 220, 1270, 46
    for row_index, device in enumerate(("pc", "sb", "mt32")):
        pool = STARTUP_POOLS[device]
        y = 202 + row_index * 67
        label = SOUND_PROFILES[device]["label"]
        out.append(f'<text x="70" y="{y + 29}" class="label">{label}</text>')
        fixed = (
            DOS_SHELL_PAYLOAD_BYTES
            + TRACE_PARENT_PAYLOAD_BYTES
            + pool["mcb_count_after_probe"] * 16
            + CONVENTIONAL_TOP_GUARD_BYTES
            + CHILD_ENVIRONMENT_BYTES
        )
        segments = [
            ("DOS + trace", fixed, colors["system"]),
            ("EXE main", MAIN_DOS_BLOCK_BYTES, colors["main"]),
            ("bootstrap", pool["bootstrap_far_arena_payload"], colors["boot"]),
            ("full arenas", pool["probe_full_far_arena_count"] * FAR_ARENA_PAYLOAD_BYTES, colors["arenas"]),
            ("DOS free", pool["dos_free_payload_after_probe"], colors["free"]),
        ]
        x = bar_x
        for name, value, color in segments:
            seg_w = bar_w * value / NOMINAL_CONVENTIONAL_BYTES
            out.append(f'<rect x="{x:.2f}" y="{y}" width="{seg_w:.2f}" height="{bar_h}" fill="{color}"/>')
            if seg_w >= 76:
                out.append(f'<text x="{x + seg_w / 2:.2f}" y="{y + 28}" text-anchor="middle" class="small num">{format_kib(value)}</text>')
            x += seg_w
        out.append(f'<text x="1490" y="{y + 62}" text-anchor="end" class="small num">DOS free after probe: {format_kib(pool["dos_free_payload_after_probe"])}</text>')
    legend = [
        ("DOS/shell + observer + MCB", colors["system"]),
        ("PSP + EXE + DGROUP", colors["main"]),
        ("bootstrap far arena", colors["boot"]),
        ("full far arenas", colors["arenas"]),
        ("still free to DOS", colors["free"]),
    ]
    lx = 220
    for label, color in legend:
        out.append(f'<rect x="{lx}" y="407" width="16" height="16" fill="{color}"/>')
        out.append(f'<text x="{lx + 23}" y="420" class="small">{label}</text>')
        lx += 238

    # Per-level exact retained assets.
    chart_x, chart_y, chart_w, chart_h = 110, 515, 1380, 300
    out.extend([
        '<text x="70" y="476" class="h2">2 · Retained graphics + selected sound resources by level</text>',
        '<text x="70" y="502" class="small">Exact live allocator-block bytes. Surface, fixed EXE, loader scratch, and arena slack are deliberately separate.</text>',
    ])
    y_min, y_max = 70 * 1024, 260 * 1024
    for tick_kib in (80, 120, 160, 200, 240):
        y = chart_y + chart_h - ((tick_kib * 1024 - y_min) / (y_max - y_min)) * chart_h
        out.append(f'<line x1="{chart_x}" y1="{y:.2f}" x2="{chart_x + chart_w}" y2="{y:.2f}" class="axis"/>')
        out.append(f'<text x="{chart_x - 12}" y="{y + 5:.2f}" text-anchor="end" class="small num">{tick_kib} KiB</text>')
    for item in model["levels"]:
        level = item["level"]
        x = chart_x + level * chart_w / 15
        out.append(f'<line x1="{x:.2f}" y1="{chart_y + chart_h}" x2="{x:.2f}" y2="{chart_y + chart_h + 7}" class="axis"/>')
        out.append(f'<text x="{x:.2f}" y="{chart_y + chart_h + 26}" text-anchor="middle" class="small num">{level}</text>')
    out.append(f'<text x="{chart_x + chart_w / 2}" y="{chart_y + chart_h + 52}" text-anchor="middle" class="small">Level</text>')
    for device in ("pc", "sb", "mt32"):
        points = []
        for item in model["levels"]:
            x = chart_x + item["level"] * chart_w / 15
            value = item["devices"][device]["asset_live"]
            y = chart_y + chart_h - ((value - y_min) / (y_max - y_min)) * chart_h
            points.append(f"{x:.2f},{y:.2f}")
        out.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{colors[device]}" stroke-width="4"/>')
        for point in points:
            x, y = point.split(",")
            out.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{colors[device]}"/>')
    out.extend([
        f'<line x1="1020" y1="472" x2="1052" y2="472" stroke="{colors["pc"]}" stroke-width="4"/><text x="1062" y="477" class="small">PC speaker</text>',
        f'<line x1="1170" y1="472" x2="1202" y2="472" stroke="{colors["sb"]}" stroke-width="4"/><text x="1212" y="477" class="small">Sound Blaster</text>',
        f'<line x1="1360" y1="472" x2="1392" y2="472" stroke="{colors["mt32"]}" stroke-width="4"/><text x="1402" y="477" class="small">MT-32</text>',
    ])

    # Lifecycle and reunion hazard.
    out.extend([
        '<text x="70" y="900" class="h2">3 · Allocation boundaries—not rooms—define the lifecycle</text>',
    ])
    stages = [
        ("Startup", "Permanent slots 0–1\ncore sounds + heap anchor"),
        ("Title", "TITLE 40/50\nfull-screen surface"),
        ("Gameplay", "KID + one environment\n+ one guard family"),
        ("PV cutscene", "free slots 3–9\nload PV 950/980/800/900"),
        ("Ending title", "global suffix reset\nTITLE + sound 56"),
    ]
    box_y, box_w, gap = 930, 250, 42
    for i, (head, body) in enumerate(stages):
        x = 70 + i * (box_w + gap)
        out.append(f'<rect x="{x}" y="{box_y}" width="{box_w}" height="104" rx="8" fill="{colors["panel"]}"/>')
        out.append(f'<text x="{x + 18}" y="{box_y + 31}" class="label">{head}</text>')
        for line_i, line in enumerate(body.split("\n")):
            out.append(f'<text x="{x + 18}" y="{box_y + 58 + line_i * 21}" class="small">{line}</text>')
        if i < len(stages) - 1:
            ax = x + box_w + 8
            out.append(f'<path d="M {ax} {box_y + 52} h 25 l -8 -7 m 8 7 l -8 7" fill="none" stroke="{colors["muted"]}" stroke-width="2"/>')

    mt_level14 = model["levels"][14]["devices"]["mt32"]["far_live_with_surface"]
    phase_far = model["phase_banks_v21b_totals"]["far_live"]
    kid_delta = model["phase_banks_v21b_totals"]["modified_kid_far_live_delta"]
    phase_total = mt_level14 + phase_far + kid_delta
    phase_capacity = STARTUP_POOLS["mt32"]["far_block_chain_extent_capacity"]
    phase_free = phase_capacity - phase_total
    out.extend([
        '<text x="70" y="1080" class="h2">4 · Why the level-14 phase build is fragile in the intended MT-32 configuration</text>',
        f'<text x="70" y="1110" class="label num">Stock level-14 far live + surface  {format_kib(mt_level14)}   +   phase banks  {format_kib(phase_far)}   +   KID delta  {format_kib(kid_delta)}   =   {format_kib(phase_total)}</text>',
    ])
    phase_x, phase_y, phase_w, phase_h = 70, 1130, 1130, 34
    pool_total = phase_capacity
    x = phase_x
    for value, color in ((mt_level14, colors["main"]), (phase_far, colors["phase"]), (kid_delta, colors["critical"]), (max(0, phase_free), colors["free"])):
        seg_w = phase_w * value / pool_total
        out.append(f'<rect x="{x:.2f}" y="{phase_y}" width="{seg_w:.2f}" height="{phase_h}" fill="{color}"/>')
        x += seg_w
    out.extend([
        f'<text x="{phase_x + phase_w + 20}" y="{phase_y + 24}" class="label num">{format_kib(phase_free)} aggregate free-block extent</text>',
        f'<text x="70" y="1195" class="small">At reunion, PV/951 immediately needs two separate 32,006-byte blocks. Freed phase bytes are split among arena-local holes; the CRT never returns arenas to DOS.</text>',
        f'<text x="1530" y="1195" text-anchor="end" class="small">Exact / measured / derived values are distinguished in REPORT.md</text>',
        "</svg>",
    ])
    (ROOT / "memory-map.svg").write_text(
        "\n".join(out) + "\n", encoding="utf-8", newline="\n"
    )


def write_interactive_html(model: dict[str, Any]) -> None:
    """Write a dependency-free interactive atlas for collaborators."""

    model_json = json.dumps(model, separators=(",", ":")).replace("</", "<\\/")
    template = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Evidence-backed memory atlas for the original DOS Prince of Persia 1.3 in CGA mode.">
<title>Prince 1.3 CGA Memory Atlas</title>
<style>
:root{color-scheme:dark;--bg:#071019;--surface:#0e1b27;--surface2:#142536;--ink:#eff7ff;--muted:#a6b8c9;--line:#2a4053;--blue:#4ea1ff;--yellow:#f3ca52;--green:#3bd0a2;--red:#ff6b78;--purple:#c383ff;--orange:#ffab52;--free:#293949;--max:1180px}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.5}main{max-width:var(--max);margin:auto;padding:42px 24px 72px}h1,h2,h3{font-weight:500;line-height:1.2;margin:0}h1{font-size:clamp(2rem,5vw,3.6rem);letter-spacing:-.035em;max-width:900px}h2{font-size:1.45rem;margin-bottom:14px}h3{font-size:1.02rem}.eyebrow{color:var(--green);font-size:.78rem;letter-spacing:.15em;text-transform:uppercase;margin-bottom:13px}.lede{color:var(--muted);font-size:1.08rem;max-width:880px;margin:18px 0 0}.stamp{margin-top:18px;color:var(--muted);font-size:.82rem}.stamp code{color:var(--ink)}section{border-top:1px solid var(--line);padding-top:30px;margin-top:38px}.finding-grid,.metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.finding{padding:18px 0;border-top:3px solid var(--blue)}.finding:nth-child(2){border-color:var(--red)}.finding:nth-child(3){border-color:var(--purple)}.finding p,.note,p.secondary{color:var(--muted)}.finding p{margin:8px 0 0}.metric{background:var(--surface);padding:15px 16px;min-height:96px}.metric .k{color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.08em}.metric .v{font-size:1.35rem;margin-top:5px;font-variant-numeric:tabular-nums}.metric .s{font-size:.79rem;color:var(--muted);margin-top:3px}.controls{display:flex;gap:12px 24px;align-items:center;flex-wrap:wrap;margin:18px 0}.controls fieldset{border:0;padding:0;margin:0;display:flex;gap:8px;flex-wrap:wrap}.controls legend{position:absolute;clip:rect(0 0 0 0)}label.choice,button.level{border:1px solid var(--line);background:transparent;color:var(--ink);padding:8px 12px;cursor:pointer;min-height:40px}label.choice:has(input:checked),button.level[aria-pressed=true]{background:var(--surface2);border-color:var(--blue)}label.choice input{margin-right:7px}.switch{margin-left:auto}.level-grid{display:grid;grid-template-columns:repeat(16,minmax(36px,1fr));gap:5px;margin:18px 0}.level{padding:8px 4px!important;font:inherit;font-variant-numeric:tabular-nums}.pool{height:42px;background:var(--free);display:flex;overflow:hidden;margin:18px 0 9px}.pool>span{display:flex;align-items:center;justify-content:center;min-width:0;white-space:nowrap;overflow:hidden;font-size:.76rem;font-variant-numeric:tabular-nums;transition:width .25s ease}.pool-used{background:var(--blue);color:#06111b}.pool-phase{background:var(--purple);color:#10051b}.pool-delta{background:var(--orange);color:#1b0d00}.pool-free{background:var(--free)}.pool-over{background:var(--red);color:#210207}.bar-caption{display:flex;justify-content:space-between;gap:18px;color:var(--muted);font-size:.82rem}.chart-wrap{margin-top:25px}.chart-wrap svg{width:100%;height:auto;display:block}.chart-axis{stroke:var(--line);stroke-width:1}.chart-label{fill:var(--muted);font-size:12px}.chart-line{fill:none;stroke:var(--blue);stroke-width:3}.chart-dot{fill:var(--blue)}.timeline{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:26px;margin-top:24px}.stage{position:relative;background:var(--surface);padding:17px 15px;min-height:130px}.stage:not(:last-child)::after{content:'→';position:absolute;right:-22px;top:48px;color:var(--muted);font-size:1.5rem}.stage p{color:var(--muted);font-size:.85rem;margin:8px 0 0}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:.86rem}th,td{text-align:left;padding:10px 9px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:500}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.arena-row{display:grid;grid-template-columns:repeat(8,1fr);gap:7px;margin:19px 0}.arena{height:92px;background:var(--surface);position:relative;overflow:hidden}.arena::before{content:'';position:absolute;left:0;bottom:0;width:100%;height:var(--fill,30%);background:var(--green);opacity:.78}.arena span{position:absolute;inset:8px;font-size:.74rem;z-index:1}.critical-pair{display:flex;gap:7px;margin-top:12px}.critical-pair span{height:28px;width:32%;background:var(--orange);display:flex;align-items:center;justify-content:center;color:#1a0b00;font-size:.74rem}.phase-equation{font-size:clamp(1rem,2.2vw,1.3rem);font-variant-numeric:tabular-nums;margin:18px 0}.callout{border-left:4px solid var(--orange);padding:4px 0 4px 18px;margin:20px 0}.callout strong{font-weight:500}.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:.8rem}.swatch{display:inline-block;width:11px;height:11px;margin-right:6px}.evidence{display:grid;grid-template-columns:1fr 1fr;gap:20px}.evidence code{word-break:break-all}.links{display:flex;gap:18px;flex-wrap:wrap}.links a{color:var(--blue)}footer{color:var(--muted);font-size:.8rem;margin-top:45px;padding-top:20px;border-top:1px solid var(--line)}
@media(max-width:800px){.finding-grid,.metric-grid{grid-template-columns:1fr}.timeline{grid-template-columns:1fr}.stage:not(:last-child)::after{content:'↓';right:16px;top:auto;bottom:-25px}.level-grid{grid-template-columns:repeat(8,1fr)}.evidence{grid-template-columns:1fr}.switch{margin-left:0}.arena-row{grid-template-columns:repeat(4,1fr)}}
@media(max-width:420px){main{padding:28px 15px 55px}.level-grid{grid-template-columns:repeat(4,1fr)}.bar-caption{display:block}.arena-row{grid-template-columns:repeat(2,1fr)}}
@media(prefers-reduced-motion:reduce){.pool>span{transition:none}}
@media print{:root{color-scheme:light;--bg:#fff;--surface:#eef3f7;--surface2:#e1ebf4;--ink:#101820;--muted:#425466;--line:#aab8c5;--free:#d9e1e8}main{max-width:none;padding:20px}section{break-inside:avoid}.controls{display:none}}
</style>
</head>
<body>
<main>
<header>
  <div class="eyebrow">Binary-derived + DOSBox-measured</div>
  <h1>Prince of Persia 1.3 CGA memory atlas</h1>
  <p class="lede">The game does not load each DAT wholesale. It streams individual resources into a CRT heap that has already claimed nearly all conventional RAM. Level and cutscene boundaries change the live blocks; room changes do not.</p>
  <p class="stamp">Scope: original US 1.3 · CGA · 640 KiB · no EMS/XMS/UMB · EXE <code>24fdc79b…7158</code></p>
</header>

<section aria-labelledby="findings-title">
  <h2 id="findings-title">The three conclusions that matter</h2>
  <div class="finding-grid">
    <article class="finding"><h3>Memory is preclaimed, not leaked to DOS</h3><p>The startup probe creates large far-heap arenas, frees their internal blocks, and never releases their MCBs. Later frees recycle holes inside those arenas.</p></article>
    <article class="finding"><h3>Sound Blaster is the largest live-data path</h3><p>When digitized sound is active, the retained core is 89.1 KiB versus 10.4 KiB for MT-32 and 3.3 KiB for PC speaker. MT-32 instead changes startup arena geometry.</p></article>
    <article class="finding"><h3>The reunion needs contiguous holes</h3><p><code>PV.DAT/951</code> needs an image and mask of 32,006 bytes each. Plenty of aggregate free memory can still be unusable when it is split between arena-local holes.</p></article>
  </div>
</section>

<section aria-labelledby="explore-title">
  <h2 id="explore-title">Explore the level states</h2>
  <div class="controls">
    <fieldset aria-label="Sound device">
      <legend>Sound device</legend>
      <label class="choice"><input type="radio" name="device" value="pc">PC speaker</label>
      <label class="choice"><input type="radio" name="device" value="sb">Sound Blaster</label>
      <label class="choice"><input type="radio" name="device" value="mt32" checked>MT-32</label>
    </fieldset>
    <label class="choice switch"><input id="phaseToggle" type="checkbox">Overlay V21B phase payload</label>
  </div>
  <div id="levelGrid" class="level-grid" aria-label="Select a level"></div>
  <div class="metric-grid" aria-live="polite">
    <div class="metric"><div class="k">Selected state</div><div id="stateName" class="v"></div><div id="stateMeta" class="s"></div></div>
    <div class="metric"><div class="k">Retained asset blocks</div><div id="assetLive" class="v"></div><div class="s">Graphics + chosen sounds; exact live bytes</div></div>
    <div class="metric"><div class="k">Aggregate free-block extent</div><div id="poolFree" class="v"></div><div id="poolFreeNote" class="s"></div></div>
  </div>
  <div id="poolBar" class="pool" role="img" aria-label="Far heap occupancy"></div>
  <div class="bar-caption"><span id="poolLeft"></span><span id="poolRight"></span></div>
  <div class="legend">
    <span><i class="swatch" style="background:var(--blue)"></i>stock far live + surface</span>
    <span><i class="swatch" style="background:var(--purple)"></i>phase banks</span>
    <span><i class="swatch" style="background:var(--orange)"></i>modified KID delta</span>
    <span><i class="swatch" style="background:var(--free)"></i>free-block extent</span>
  </div>
  <div class="chart-wrap"><svg id="levelChart" viewBox="0 0 1080 320" role="img" aria-labelledby="chartTitle chartDesc"><title id="chartTitle">Retained assets by level</title><desc id="chartDesc">A line plot for the selected sound device.</desc></svg></div>
  <div class="table-wrap">
    <table aria-label="Selected level details"><tbody>
      <tr><th>Environment</th><td id="environment"></td><th>Guard family</th><td id="guard"></td></tr>
      <tr><th>Optional graphic rows</th><td id="optional"></td><th>Pre-level cutscene</th><td id="cutscene"></td></tr>
      <tr><th>Special event behavior</th><td id="special" colspan="3"></td></tr>
    </tbody></table>
  </div>
</section>

<section aria-labelledby="startup-title">
  <h2 id="startup-title">Startup: how 640 KiB becomes reusable arena space</h2>
  <div class="table-wrap"><table><thead><tr><th>Mode</th><th class="num">Bootstrap arena</th><th class="num">Full probe arenas</th><th class="num">Far-pool payload</th><th class="num">DOS-free payload after probe</th></tr></thead><tbody id="startupRows"></tbody></table></div>
  <p class="note">PC speaker and SBLAST mode keep one 8 KiB bootstrap arena plus seven 65,488-byte arenas. MIDI/MT-32 first expands the bootstrap arena to 32 KiB for its transient 21,152-byte SysEx resource, leaving room for six additional full arenas. The resource is freed, but the larger arena remains.</p>
</section>

<section aria-labelledby="life-title">
  <h2 id="life-title">Lifecycle and reload boundaries</h2>
  <div class="timeline">
    <article class="stage"><h3>Startup prefix</h3><p>Load permanent sword and flame/floor-sword/potion tables, core sounds, palette translations; then set heap anchors.</p></article>
    <article class="stage"><h3>Title / story</h3><p>Load sounds 50–55, a 320×200 surface, and TITLE 40/50. Opening PV follows while title sounds remain.</p></article>
    <article class="stage"><h3>Gameplay</h3><p>Keep KID slot 2 and a 320×192 surface. At a level boundary, replace environment, guard family, optional graphics, and event sounds.</p></article>
    <article class="stage"><h3>PV cutscene</h3><p>Free optional sounds and slots 3–9. Load PV 950 and temporary 980, retain the backdrop mask, then load actor tables 800 + 850/900.</p></article>
    <article class="stage"><h3>Ending title</h3><p>After the reunion, reset the transient suffix, load sound 56 plus TITLE 40/50, then show ending and high-score screens.</p></article>
  </div>
  <p class="callout"><strong>Rooms are memory-neutral boundaries:</strong> the 2,305-byte level resource is copied once into a fixed global structure; movement between rooms indexes that resident structure. Skeleton wake-up, shadow events, mouse, mirror, chomper, spikes, fat guard, and vizier do not open a DAT at event time.</p>
</section>

<section aria-labelledby="scene-title">
  <h2 id="scene-title">Cutscene and title states</h2>
  <div class="table-wrap"><table><thead><tr><th>State</th><th class="num">Retained assets</th><th class="num">Modeled peak + surface</th><th>What changes</th></tr></thead><tbody id="sceneRows"></tbody></table></div>
  <p class="note">A modeled peak includes the maximizing loader allocation or full-screen draw allocation and, for LZG graphics, the 1,026-byte decoder dictionary. It is not a DOS MCB total: the arenas were already committed at startup.</p>
</section>

<section aria-labelledby="arena-title">
  <h2 id="arena-title">Why “free bytes” is not the same as “can allocate”</h2>
  <p class="secondary">Each far arena is its own sub-64-KiB address space. First-fit allocation splits blocks; free coalesces adjacent blocks only inside the same arena. There is no allocator call that releases an arena MCB to DOS.</p>
  <div class="arena-row" aria-label="Schematic fragmented CRT arenas">
    <div class="arena" style="--fill:76%"><span>arena 0<br>small holes</span></div><div class="arena" style="--fill:48%"><span>arena 1<br>split</span></div><div class="arena" style="--fill:71%"><span>arena 2<br>split</span></div><div class="arena" style="--fill:55%"><span>arena 3<br>split</span></div><div class="arena" style="--fill:83%"><span>arena 4<br>split</span></div><div class="arena" style="--fill:42%"><span>arena 5<br>split</span></div><div class="arena" style="--fill:68%"><span>arena 6<br>split</span></div><div class="arena" style="--fill:57%"><span>arena 7<br>split</span></div>
  </div>
  <div class="critical-pair" aria-label="Two required PV 951 allocations"><span>PV/951 image<br>32,006 B</span><span>PV/951 mask<br>32,006 B</span></div>
  <p class="note">The arena fills above are schematic; exact hole placement is play-history dependent. The block sizes, allocator rules, and startup arena geometry are exact.</p>
</section>

<section aria-labelledby="phase-title">
  <h2 id="phase-title">Current phase-bank liability at the final reunion</h2>
  <p id="phaseEquation" class="phase-equation"></p>
  <p class="secondary">V21B’s three phase archives add 284,976 live allocator bytes, 282,324 of them far. Its modified KID table adds another 4,010 far bytes over stock. In MT-32 level 14 that leaves only about 15.0 KiB of aggregate free-block extent inside the startup far arenas before cutscene loading—and the useful largest hole can be smaller.</p>
  <div class="callout"><strong>Evidence-backed diagnosis:</strong> V21C removed cinematic selector use but still failed; V21D removed the level-14 banks but still failed; V21G combined both changes and Chris confirmed the full hug, mouse, fade, ending title, and high-score transition. The active failure therefore requires the phase-table interaction; the enlarged EXE/near reservation alone was excluded by the successful phase-free V21F pair.</div>
</section>

<section aria-labelledby="sound-title">
  <h2 id="sound-title">Sound-device memory comparison</h2>
  <div class="table-wrap"><table><thead><tr><th>Path</th><th class="num">Core live</th><th class="num">All optional live</th><th class="num">Ending sound 56</th><th>Startup geometry / caveat</th></tr></thead><tbody id="soundRows"></tbody></table></div>
  <p class="note">The digitized Sound Blaster row is the exact resource-selected path when <code>sfDigi</code> is active. In the isolated stock 0.74-3 probe, <code>SBLAST</code> selected driver mode 3 but hardware detection did not set that resource flag, so the dynamic run followed the smaller MIDI/MT-32 fallback. The report keeps measured driver startup and binary-derived digitized payloads separate.</p>
</section>

<section aria-labelledby="evidence-title">
  <h2 id="evidence-title">Evidence and reproducibility</h2>
  <div class="evidence">
    <div><h3>Authenticated inputs</h3><p class="secondary">PRINCE.EXE: 125,115 bytes<br><code>24fdc79b4de563348313b50d717e171919191e5c38559f5bdd6a4751d39b7158</code></p><p class="secondary">DOSBox 0.74-3: 3,745,792 bytes<br><code>dcfd46fa521f5ce89dce3bf026056f3a1d15533f80321ee887403e30d7949f5e</code></p></div>
    <div><h3>Confidence vocabulary</h3><p class="secondary"><strong>Exact</strong>: authenticated bytes, disassembly, DAT arithmetic, or allocator arithmetic.<br><strong>Measured</strong>: isolated stock DOSBox trace.<br><strong>Derived</strong>: arithmetic combination of exact values.<br><strong>Path-dependent</strong>: arena-hole topology depends on prior allocation order.</p></div>
  </div>
  <div class="links"><a href="REPORT.md">Full technical report</a><a href="memory-map.svg">Static shareable map</a><a href="data/memory-model.json">JSON model</a><a href="data/levels.csv">Level CSV</a><a href="data/scenes.csv">Scene CSV</a><a href="dynamic/README.md">DOSBox probe notes</a></div>
</section>
<footer>Generated from exact constants checked by <code>tools/build_memory_map.py</code>. No original game binary or DAT payload is embedded.</footer>
</main>
<script>
const model=__MODEL_JSON__;
const devices={pc:'PC speaker',sb:'Sound Blaster',mt32:'MT-32'};
let selectedLevel=14;
let selectedDevice='mt32';
let showPhase=false;
const fmt=b=>`${(b/1024).toFixed(1)} KiB`;
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function buildLevelGrid(){
  const grid=document.getElementById('levelGrid');
  model.levels.forEach(l=>{const b=document.createElement('button');b.type='button';b.className='level';b.textContent=l.level;b.setAttribute('aria-label',`Level ${l.level}`);b.addEventListener('click',()=>{selectedLevel=l.level;render()});grid.appendChild(b)});
}
function segment(cls,width,text){return `<span class="${cls}" style="width:${Math.max(0,width)}%">${text||''}</span>`}
function render(){
  const l=model.levels[selectedLevel],d=l.devices[selectedDevice],pool=d.startup_far_block_chain_extent_capacity;
  const phase=model.phase_banks_v21b_totals.far_live,delta=model.phase_banks_v21b_totals.modified_kid_far_live_delta;
  const extra=showPhase?phase+delta:0,used=d.far_live_with_surface+extra,free=pool-used;
  document.querySelectorAll('button.level').forEach((b,i)=>b.setAttribute('aria-pressed',i===selectedLevel?'true':'false'));
  document.getElementById('stateName').textContent=`Level ${l.level} · ${devices[selectedDevice]}`;
  document.getElementById('stateMeta').textContent=`${l.environment} · ${l.guard_family} · ${model.allocator.startup_pools[selectedDevice].total_far_arena_count} startup far arenas`;
  document.getElementById('assetLive').textContent=fmt(d.asset_live);
  document.getElementById('poolFree').textContent=(free<0?'−':'')+fmt(Math.abs(free));
  document.getElementById('poolFree').style.color=free<0?'var(--red)':'';
  document.getElementById('poolFreeNote').textContent=free<0?'aggregate overflow; fallback/new-arena behavior becomes decisive':'before hole count/contiguity; largest hole may be smaller';
  const stockPct=100*d.far_live_with_surface/pool,phasePct=showPhase?100*phase/pool:0,deltaPct=showPhase?100*delta/pool:0,freePct=Math.max(0,100-stockPct-phasePct-deltaPct),overPct=Math.max(0,-100*free/pool);
  document.getElementById('poolBar').innerHTML=segment('pool-used',Math.min(stockPct,100),stockPct>13?fmt(d.far_live_with_surface):'')+(showPhase?segment('pool-phase',Math.min(phasePct,Math.max(0,100-stockPct)),phasePct>13?fmt(phase):'')+segment('pool-delta',Math.min(deltaPct,Math.max(0,100-stockPct-phasePct)),''):'')+segment('pool-free',freePct,freePct>12?fmt(Math.max(0,free)):'')+(overPct?segment('pool-over',Math.min(overPct,100),'overflow'):'');
  document.getElementById('poolBar').setAttribute('aria-label',`${fmt(used)} far live against ${fmt(pool)} startup far block-chain capacity; ${free<0?fmt(-free)+' over':fmt(free)+' aggregate free-block extent'}`);
  document.getElementById('poolLeft').textContent=`Far live + surface${showPhase?' + phase overlay':''}: ${fmt(used)}`;
  document.getElementById('poolRight').textContent=`Block-chain capacity: ${fmt(pool)}; committed MCB payload: ${fmt(d.startup_far_pool_payload)}; DOS still free: ${fmt(d.dos_free_payload_outside_crt_pools_after_startup_probe)}`;
  document.getElementById('environment').textContent=l.environment;document.getElementById('guard').textContent=l.guard_family;document.getElementById('optional').textContent=l.optional_graphic_rows||'none';document.getElementById('cutscene').textContent=l.cutscene_before;document.getElementById('special').textContent=l.special;
  renderChart();renderScenes();
}
function renderChart(){
  const svg=document.getElementById('levelChart'),W=1080,H=320,L=65,R=22,T=18,B=45,vals=model.levels.map(l=>l.devices[selectedDevice].asset_live+(showPhase?model.phase_banks_v21b_totals.live:0));
  const min=60*1024,max=Math.max(275*1024,Math.max(...vals)*1.08),x=i=>L+i*(W-L-R)/15,y=v=>T+(max-v)*(H-T-B)/(max-min);
  let s='';for(const k of [80,120,160,200,240,280,320,360]){if(k*1024>max)continue;const yy=y(k*1024);s+=`<line class="chart-axis" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/><text class="chart-label" x="${L-10}" y="${yy+4}" text-anchor="end">${k}</text>`}for(let i=0;i<16;i++){s+=`<text class="chart-label" x="${x(i)}" y="${H-15}" text-anchor="middle">${i}</text>`}const points=vals.map((v,i)=>`${x(i)},${y(v)}`).join(' ');s+=`<polyline class="chart-line" points="${points}"/>`;vals.forEach((v,i)=>s+=`<circle class="chart-dot" cx="${x(i)}" cy="${y(v)}" r="${i===selectedLevel?6:3.5}"/>`);s+=`<text class="chart-label" x="15" y="18">KiB</text><text class="chart-label" x="${W/2}" y="${H-1}" text-anchor="middle">Level</text>`;svg.innerHTML=`<title>Retained assets by level for ${devices[selectedDevice]}</title><desc>Level ${selectedLevel} is emphasized. Values include graphics and sound resource blocks, excluding surfaces and the fixed executable.</desc>${s}`;
}
function renderScenes(){
  document.getElementById('sceneRows').innerHTML=model.scenes.map(s=>{const d=s.devices[selectedDevice],peak=Math.max(d.load_peak_live_with_surface||0,d.draw_peak_live_with_surface||0);return `<tr><td>${esc(s.label)}</td><td class="num">${fmt(d.asset_live)}</td><td class="num">${peak?fmt(peak):'—'}</td><td>${esc(s.note)}</td></tr>`}).join('');
}
function initTables(){
  document.getElementById('startupRows').innerHTML=Object.entries(model.allocator.startup_pools).map(([k,p])=>`<tr><td>${devices[k]}</td><td class="num">${fmt(p.bootstrap_far_arena_payload)}</td><td class="num">${p.probe_full_far_arena_count}</td><td class="num">${fmt(p.far_pool_payload)}</td><td class="num">${fmt(p.dos_free_payload_after_probe)}</td></tr>`).join('');
  document.getElementById('soundRows').innerHTML=Object.entries(model.sound_profiles).map(([k,p])=>`<tr><td>${esc(p.label)}</td><td class="num">${fmt(p.core_live)}</td><td class="num">${fmt(p.optional_all_live)}</td><td class="num">${fmt(p.ending_live)}</td><td>${esc(model.allocator.startup_pools[k].note)} ${esc(p.note)}</td></tr>`).join('');
  const l14=model.levels[14].devices.mt32.far_live_with_surface,p=model.phase_banks_v21b_totals;document.getElementById('phaseEquation').textContent=`MT-32 level 14: ${fmt(l14)} stock far live + ${fmt(p.far_live)} phase banks + ${fmt(p.modified_kid_far_live_delta)} KID delta = ${fmt(l14+p.far_live+p.modified_kid_far_live_delta)} inside ${fmt(model.allocator.startup_pools.mt32.far_block_chain_extent_capacity)} of startup block-chain capacity.`;
}
document.querySelectorAll('input[name=device]').forEach(r=>r.addEventListener('change',e=>{selectedDevice=e.target.value;render()}));document.getElementById('phaseToggle').addEventListener('change',e=>{showPhase=e.target.checked;render()});buildLevelGrid();initTables();render();
</script>
</body>
</html>
'''
    (ROOT / "memory-map.html").write_text(
        template.replace("__MODEL_JSON__", model_json),
        encoding="utf-8",
        newline="\n",
    )


def write_artifact_checksums() -> None:
    paths = [
        ROOT / "REPORT.md",
        ROOT / "memory-map.html",
        ROOT / "memory-map.svg",
        DATA_DIR / "memory-model.json",
        DATA_DIR / "levels.csv",
        DATA_DIR / "scenes.csv",
        DATA_DIR / "sound-profiles.csv",
        DATA_DIR / "graphic-components.csv",
        DATA_DIR / "optional-graphics.csv",
        DATA_DIR / "archives.csv",
        ROOT / "dynamic/README.md",
        ROOT / "dynamic/stock-cga-640k.conf",
        ROOT / "dynamic/trace-pcspeaker-startup.csv",
        ROOT / "dynamic/trace-soundblaster-startup.csv",
        ROOT / "dynamic/trace-mt32-startup.csv",
    ]
    lines = []
    for path in paths:
        if path.exists():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(ROOT).as_posix()}")
    (ROOT / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="ascii", newline="\n"
    )


def validate_model(model: dict[str, Any]) -> None:
    assert MAIN_DOS_BLOCK_PARAGRAPHS == 0x2BB3
    assert MAIN_DOS_BLOCK_BYTES == 178_992
    assert MCB_PROBE_FREE_BYTES == 647_856
    assert (
        DOS_SHELL_PAYLOAD_BYTES
        + MCB_PROBE_HEADER_BYTES
        + CONVENTIONAL_TOP_GUARD_BYTES
        + MCB_PROBE_PAYLOAD_BYTES
        + MCB_PROBE_FREE_BYTES
        == NOMINAL_CONVENTIONAL_BYTES
    )
    assert STARTUP_POOLS["pc"]["child_owned_payload"] == 645_744
    assert STARTUP_POOLS["sb"]["child_owned_payload"] == 645_744
    assert STARTUP_POOLS["mt32"]["child_owned_payload"] == 604_832
    assert SURFACES["gameplay"]["far_request"] == 15360
    assert SURFACES["full_screen"]["far_request"] == 16000
    assert sum(bank["request"] for bank in PHASE_BANKS_V21B.values()) == 283_488
    assert sum(bank["live"] for bank in PHASE_BANKS_V21B.values()) == 284_976
    for item in model["levels"]:
        for device, values in item["devices"].items():
            assert values["asset_live"] >= item["graphics_live"]
            assert values["far_asset_live"] == values["asset_live"] - item["near_graphics_live"]
            assert values["aggregate_free_block_extent_before_hole_contiguity"] > 0, (item["level"], device)
    level_5 = model["levels"][5]
    assert level_5["devices"]["sb"]["asset_live"] == 250502
    assert level_5["devices"]["sb"]["aggregate_free_block_extent_before_hole_contiguity"] == 203254


def build_model() -> dict[str, Any]:
    return {
        "schema": 1,
        "scope": "Original US Prince of Persia 1.3, CGA, 640 KiB conventional, no EMS/XMS/UMB",
        "source": {
            "path": r"C:\DOS\PRINCE13",
            "executable": "PRINCE.EXE",
            "sha256": SOURCE_EXE_SHA256,
            "packed_file_bytes": 125115,
            "unpacked_file_bytes": 129664,
            "unpacked_header_bytes": 2560,
            "unpacked_module_bytes": 127104,
        },
        "dosbox": {
            "version": "0.74-3",
            "binary_sha256": "dcfd46fa521f5ce89dce3bf026056f3a1d15533f80321ee887403e30d7949f5e",
            "machine": "cga",
            "xms": False,
            "ems": False,
            "umb": False,
            "nominal_conventional_bytes": NOMINAL_CONVENTIONAL_BYTES,
            "mem_utility_display": "632 Kb free conventional memory",
            "mcb_probe_free_payload": MCB_PROBE_FREE_BYTES,
            "mcb_probe_largest_free_payload": MCB_PROBE_LARGEST_FREE_BYTES,
            "dos_and_shell_payload": DOS_SHELL_PAYLOAD_BYTES,
            "mcb_probe_payload": MCB_PROBE_PAYLOAD_BYTES,
            "mcb_header_bytes_at_probe": MCB_PROBE_HEADER_BYTES,
            "conventional_top_guard_bytes": CONVENTIONAL_TOP_GUARD_BYTES,
            "trace_parent_payload": TRACE_PARENT_PAYLOAD_BYTES,
            "trace_base_free_payload": TRACE_BASE_FREE_BYTES,
        },
        "main_dos_block": {
            "paragraphs": MAIN_DOS_BLOCK_PARAGRAPHS,
            "bytes": MAIN_DOS_BLOCK_BYTES,
            "formula": "0x10 PSP + 0x1BA3 load-to-DGROUP + 0x1000 DGROUP window",
            "psp_bytes": 256,
            "load_module_before_dgroup_bytes": 0x1BA3 * 16,
            "dgroup_window_bytes": 0x1000 * 16,
            "dgroup": {
                "loaded_static_bytes": 0x364E,
                "zero_fill_bytes": 0x6790 - 0x364E,
                "stack_reserve_bytes": 0x778E - 0x6790,
                "gross_near_heap_tail_bytes": 0x10000 - 0x778E,
            },
            "confidence": "exact binary-derived under the measured >=64 KiB startup headroom",
        },
        "allocator": {
            "block_live_formula": "even_up(request) + 2",
            "new_far_arena_capacity": "max(240, even_up(request))",
            "new_far_arena_owned_bytes": "16 * ceil((capacity + 14) / 16)",
            "dos_mcb_bytes_per_arena": 16,
            "startup_far_probe_request": FAR_PROBE_REQUEST_BYTES,
            "startup_far_arena_paragraphs": FAR_ARENA_PARAGRAPHS,
            "startup_far_arena_payload_each": FAR_ARENA_PAYLOAD_BYTES,
            "startup_pools": STARTUP_POOLS,
            "dos_release_calls_in_allocator": 0,
            "full_arena_fixed_bytes_outside_block_chain": 14,
            "grown_bootstrap_arena_fixed_bytes_outside_block_chain": 12,
            "warning": (
                "The startup probe commits and retains large arenas. Freeing a resource "
                "returns a block to the CRT pool, not to DOS; aggregate free-block extent "
                "does not prove that one contiguous allocation can succeed, and each free "
                "hole itself retains a two-byte header."
            ),
        },
        "surfaces": SURFACES,
        "peels": {
            "maximum_live_objects_per_frame": 50,
            "far_request_formula": "height * ceil((((x - surface_x) mod 4) + width) / 4)",
            "near_request_formula": "26 + 2 * height",
            "total_live_formula": "30 + 2 * height + even_up(far_request)",
            "safe_max_live_by_family": {
                "kid": 604,
                "guard_fat_vizier": 576,
                "skeleton": 534,
                "shadow": 548,
                "pv_800": 460,
                "pv_850": 606,
                "pv_900": 630,
                "hourglass": 254,
            },
            "structural_actor_only_upper_bound": 50 * 630,
            "note": "Actual frame peak is the sum of clipped rectangles and phases for objects drawn in that frame.",
        },
        "sound_profiles": SOUND_PROFILES,
        "graphic_components": [
            {
                **dict(zip([
                    "key", "archive_base", "images", "shift", "storage_mode",
                    "near_request", "far_request", "total_request", "total_live",
                    "far_blocks", "note",
                ], row)),
                "isolated_load_peak_live": ISOLATED_GRAPHIC_LOAD_PEAK_LIVE[row[0]],
            }
            for row in GRAPHIC_COMPONENTS
        ],
        "optional_graphics": [
            {
                "row": row,
                "logical_image_indices": indices,
                "environment": environment,
                "request": request,
                "live": live,
            }
            for row, indices, environment, request, live in OPTIONAL_GRAPHICS
        ],
        "archives": [
            dict(zip(
                ["archive", "file_bytes", "index_bytes", "resource_count", "payload_bytes", "handle_request", "use"],
                row,
            ))
            for row in ARCHIVES
        ],
        "levels": level_dicts(),
        "scenes": scene_dicts(),
        "phase_banks_v21b": PHASE_BANKS_V21B,
        "phase_banks_v21b_totals": {
            "file_bytes": sum(bank["file_bytes"] for bank in PHASE_BANKS_V21B.values()),
            "request": sum(bank["request"] for bank in PHASE_BANKS_V21B.values()),
            "live": sum(bank["live"] for bank in PHASE_BANKS_V21B.values()),
            "far_live": sum(bank["far_live"] for bank in PHASE_BANKS_V21B.values()),
            "modified_kid_far_live_delta": 4010,
        },
        "critical_allocation": {
            "resource": "PV.DAT resource 951",
            "one_request_bytes": 32006,
            "two_simultaneous_request_bytes": 64012,
            "two_simultaneous_live_bytes": 64016,
            "reason": "CGA slot 8 shift=1 retains a separately allocated image and mask.",
        },
        "level_record_loading": {
            "levels_0_through_14_resource_bytes": 2305,
            "level_15_resource_bytes": 2304,
            "dat_handle_request": 212,
            "dat_handle_live": 214,
            "levels_0_through_14_peak_live": 2522,
            "level_15_peak_live": 2520,
            "retained_after_copy": 0,
        },
        "confidence": {
            "exact": "Authenticated binary disassembly, exact DAT bytes, or exact allocator arithmetic.",
            "measured": "Observed in the isolated stock DOSBox 0.74-3 control profile.",
            "derived": "Arithmetic combination of exact values with assumptions stated beside the value.",
            "path_dependent": (
                "The startup DOS commitment is measured; which free holes remain inside each "
                "CRT arena after a particular play history still depends on allocation order."
            ),
        },
    }


def verify_source(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SOURCE_EXE_SHA256:
        raise SystemExit(f"unexpected PRINCE.EXE SHA-256: {digest}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-source", type=Path)
    args = parser.parse_args()
    if args.verify_source:
        verify_source(args.verify_source)
    model = build_model()
    validate_model(model)
    write_data_files(model)
    write_static_svg(model)
    write_interactive_html(model)
    write_artifact_checksums()
    print(json.dumps({
        "data_dir": str(DATA_DIR),
        "html": str(ROOT / "memory-map.html"),
        "svg": str(ROOT / "memory-map.svg"),
        "levels": len(model["levels"]),
        "scenes": len(model["scenes"]),
        "source_sha256": model["source"]["sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
