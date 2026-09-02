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

GRAPHIC_PRESENTATION = {
    "sword": ("Sword table", "permanent", "startup anchor; slot 0 remains resident"),
    "flame_sword_potion": ("Flames, floor sword, potions", "permanent", "startup anchor; slot 1 remains resident"),
    "kid": ("Kid animation table", "character", "gameplay session; slot 2 remains through pre-level scenes and reunion"),
    "dungeon": ("Dungeon environment", "environment", "current level family; slot 6"),
    "dungeon_wall": ("Dungeon wall", "environment", "current level family; slot 7"),
    "palace": ("Palace environment", "environment", "current level family; slot 6"),
    "palace_wall": ("Palace wall", "environment", "current level family; slot 7"),
    "guard": ("Guard animation table", "character", "current level guard family; slot 5"),
    "fat": ("Fat guard animation table", "character", "level 6 guard family; slot 5"),
    "skeleton": ("Skeleton animation table", "character", "level 3 guard family; slot 5"),
    "vizier": ("Vizier animation table", "character", "level 13 guard family; slot 5"),
    "shadow": ("Shadow animation table", "character", "level 12 guard family; slot 5"),
    "pv_800": ("Princess-room actor table", "cutscene", "current PV scene; slot 3"),
    "pv_850": ("Opening/early actor table", "cutscene", "opening or early PV scene; slot 4"),
    "pv_900": ("Late/reunion actor table", "cutscene", "late PV scene or reunion; slot 4"),
    "pv_950": ("Full princess-room backdrop table", "cutscene", "background-load stage; slot 8"),
    "pv_980": ("Temporary bed image", "transition", "background-load stage only; slot 9"),
    "title_40": ("TITLE story table", "title", "title/story or ending display"),
    "title_50": ("TITLE card table", "title", "title/story or ending display"),
}

SLOT_BY_COMPONENT = {
    "sword": 0,
    "flame_sword_potion": 1,
    "kid": 2,
    "pv_800": 3,
    "pv_850": 4,
    "pv_900": 4,
    "guard": 5,
    "fat": 5,
    "skeleton": 5,
    "vizier": 5,
    "shadow": 5,
    "dungeon": 6,
    "palace": 6,
    "dungeon_wall": 7,
    "palace_wall": 7,
    "pv_950": 8,
    "pv_980": 9,
}

GUARD_COMPONENT = {
    "GUARD": "guard",
    "FAT": "fat",
    "SKEL": "skeleton",
    "SHADOW": "shadow",
    "VIZIER": "vizier",
}

LEVEL_SOUND_GROUPS = {
    0: ["chomper", "spikes"],
    1: ["skeleton", "spikes"],
    2: ["spikes"],
    3: ["skeleton", "chomper", "spikes"],
    4: ["mirror", "chomper", "spikes"],
    5: ["chomper", "spikes"],
    6: ["chomper", "spikes"],
    7: ["skeleton", "chomper", "spikes"],
    8: ["skeleton", "chomper", "spikes"],
    9: ["chomper", "spikes"],
    10: ["chomper", "spikes"],
    11: ["chomper", "spikes"],
    12: ["skeleton", "spikes"],
    13: [],
    14: [],
    15: [],
}

SOUND_GROUP_LOGICAL_IDS = {
    "skeleton": "44",
    "mirror": "45",
    "chomper": "46-47",
    "spikes": "48-49",
}

OPTIONAL_FAR_BLOCKS = {
    0: 14,
    1: 4,
    2: 4,
    3: 10,
    4: 12,
    5: 46,
    6: 34,
    7: 8,
}

OPTIONAL_POPULATED_RESOURCES = {
    0: "1201-1206, 1209",
    1: "1230-1231",
    2: "1275, 1277",
    3: "1278, 1280-1283",
    4: "1286-1291",
    5: "1301-1323",
    6: "1327-1343",
    7: "1210-1213",
}

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


def build_asset_catalog() -> list[dict[str, Any]]:
    """Describe every block that can appear in the interactive state map."""

    catalog: list[dict[str, Any]] = []
    for row in GRAPHIC_COMPONENTS:
        (
            key, archive_base, images, _shift, storage_mode, near_request,
            _far_request, _total_request, total_live, far_blocks, note,
        ) = row
        archive_stem, table_text = archive_base.split("/")
        table_resource = int(table_text)
        near_live = block_live(near_request)
        label, category, lifetime = GRAPHIC_PRESENTATION[key]
        catalog.append({
            "id": key.replace("_", "-"),
            "component_key": key,
            "label": label,
            "short_label": archive_base,
            "category": category,
            "archive": f"{archive_stem}.DAT",
            "resource_selector": (
                f"table {table_resource}; image resources "
                f"{table_resource + 1}-{table_resource + images}"
            ),
            "slot": SLOT_BY_COMPONENT.get(key),
            "storage_mode": storage_mode,
            "near_live": near_live,
            "far_live": total_live - near_live,
            "far_blocks": far_blocks,
            "total_live": total_live,
            "isolated_load_peak_live": ISOLATED_GRAPHIC_LOAD_PEAK_LIVE[key],
            "lifetime": lifetime,
            "confidence": "exact",
            "report_href": "REPORT.md#graphic-table-allocations",
            "note": note,
        })

    guard_item = next(item for item in catalog if item["component_key"] == "guard")
    guard_item["archive_refs"] = ["GUARD.DAT", "GUARD1.DAT", "GUARD2.DAT"]
    guard_item["resource_selector"] = (
        "GUARD.DAT resources 751-784; palette resource 750 is selected from "
        "GUARD1.DAT (palace) or GUARD2.DAT (dungeon)"
    )

    # PV/951's decoded image is freed after the room background is drawn.  The
    # table's near pointer block and the other 23 image/mask far blocks remain.
    full_pv = next(item for item in catalog if item["component_key"] == "pv_950")
    pv_951_one_live = block_live(32_006)
    catalog.append({
        **full_pv,
        "id": "pv-950-backdrop-retained",
        "component_key": "pv_950_backdrop_retained",
        "label": "Retained princess-room backdrop",
        "short_label": "PV/950 retained",
        "resource_selector": (
            "table 950 after freeing the resource 951 image copy; its mask "
            "and the remaining image/mask records stay resident"
        ),
        "far_live": full_pv["far_live"] - pv_951_one_live,
        "far_blocks": full_pv["far_blocks"] - 1,
        "total_live": full_pv["total_live"] - pv_951_one_live,
        "isolated_load_peak_live": full_pv["isolated_load_peak_live"],
        "lifetime": "PV actor stage; slot 8 backdrop remainder",
        "note": "Exact 37,024-byte remainder after one 32,008-byte live far block is freed.",
    })

    for row, indices, environment, _request, live in OPTIONAL_GRAPHICS:
        environments = ("dungeon", "palace") if environment == "both" else (environment,)
        for concrete_environment in environments:
            archive = "CDUNGEON.DAT" if concrete_environment == "dungeon" else "CPALACE.DAT"
            catalog.append({
                "id": f"optional-{concrete_environment}-row-{row}",
                "component_key": f"optional_{concrete_environment}_{row}",
                "label": f"{concrete_environment.title()} optional row {row}",
                "short_label": f"optional {indices}",
                "category": "optional",
                "archive": archive,
                "resource_selector": (
                    f"slot-6 table 200 logical indices {indices}; populated from "
                    f"resources {OPTIONAL_POPULATED_RESOURCES[row]}"
                ),
                "slot": 6,
                "storage_mode": "unpacked",
                "near_live": 0,
                "far_live": live,
                "far_blocks": OPTIONAL_FAR_BLOCKS[row],
                "total_live": live,
                "lifetime": "selected at the level boundary; retained for that level",
                "confidence": "exact",
                "report_href": "REPORT.md#per-level-retained-resource-map",
                "note": "The index range is a logical table slice; no room-time DAT load occurs.",
            })

    for key, surface in SURFACES.items():
        catalog.append({
            "id": f"surface-{key.replace('_', '-')}",
            "component_key": f"surface_{key}",
            "label": f"{surface['width']}x{surface['height']} off-screen surface",
            "short_label": f"surface {surface['width']}x{surface['height']}",
            "category": "surface",
            "archive": None,
            "resource_selector": "runtime-created surface; not stored in a DAT",
            "slot": None,
            "storage_mode": "runtime buffer",
            "near_live": surface["near_live"],
            "far_live": surface["far_live"],
            "far_blocks": 1,
            "total_live": surface["near_live"] + surface["far_live"],
            "lifetime": "current gameplay or full-screen display state",
            "confidence": "exact",
            "report_href": "REPORT.md#off-screen-surfaces",
            "note": "The visible B800 CGA framebuffer is video memory and is not part of this block.",
        })

    sound_assets = {
        "pc": (
            "PC speaker sound resources",
            ["IBM_SND1.DAT", "IBM_SND2.DAT"],
            "IBM_SND1 resources 10000-10043; selected logical sounds 44-56 use IBM_SND2",
        ),
        "sb": (
            "Sound Blaster sound resources",
            ["DIGISND3.DAT", "DIGISND1.DAT", "DIGISND2.DAT", "MIDISND1.DAT", "IBM_SND1.DAT"],
            "DIGISND3/1 digitized core plus PRINCE resource 1 OPL bank; DIGISND2/MIDISND2 optional resources and MIDI/IBM fallbacks",
        ),
        "mt32": (
            "MT-32 sound resources",
            ["MT32SND1.DAT", "MT32SND2.DAT", "MIDISND1.DAT", "MIDISND2.DAT", "IBM_SND1.DAT"],
            "MT32SND1 resources 10000-10023, MIDISND1/IBM core fallbacks, then MT32SND2/MIDISND2 optional resources",
        ),
    }
    for key, (label, archives, selector) in sound_assets.items():
        catalog.append({
            "id": f"sound-{key}",
            "component_key": f"sound_{key}",
            "label": label,
            "short_label": f"{SOUND_PROFILES[key]['label']} sound",
            "category": "sound",
            "archive": None,
            "archive_refs": archives,
            "resource_selector": selector,
            "slot": None,
            "storage_mode": "selected sound blocks",
            "near_live": 0,
            "far_live": 0,
            "far_blocks": 0,
            "total_live": 0,
            "lifetime": "core sounds persist; title, ending, and event sounds follow state boundaries",
            "confidence": "exact resource-selected totals; see the Sound Blaster detection caveat",
            "report_href": "REPORT.md#sound-paths",
            "note": SOUND_PROFILES[key]["note"],
        })

    catalog.extend([
        {
            "id": "levels-record",
            "component_key": "levels_record",
            "label": "LEVELS record copy",
            "short_label": "LEVELS/2000+level",
            "category": "transition",
            "archive": "LEVELS.DAT",
            "resource_selector": "resource 2000 + level; copied into the fixed global level structure",
            "slot": None,
            "storage_mode": "temporary resource plus DAT handle",
            "near_live": 0,
            "far_live": 0,
            "far_blocks": 0,
            "total_live": 2522,
            "lifetime": "level boundary only; zero retained bytes after the copy",
            "confidence": "exact",
            "report_href": "REPORT.md#entering-and-changing-a-level",
            "note": "2,522-byte peak for levels 0-14; 2,520 bytes for level 15.",
        },
        {
            "id": "title-draw-workspace",
            "component_key": "title_draw_workspace",
            "label": "TITLE decode/draw workspace",
            "short_label": "TITLE draw workspace",
            "category": "transition",
            "archive": "TITLE.DAT",
            "resource_selector": "temporary decoded output and 1,026-byte LZG dictionary",
            "slot": None,
            "storage_mode": "temporary decoded buffer",
            "near_live": 1026,
            "far_live": TITLE_DRAW_TRANSIENT_LIVE - 1026,
            "far_blocks": 1,
            "total_live": TITLE_DRAW_TRANSIENT_LIVE,
            "lifetime": "only while a packed TITLE image is drawn",
            "confidence": "exact maximizing draw allocation",
            "report_href": "REPORT.md#graphic-table-allocations",
            "note": "Maximum is TITLE resource 41/51: 32,008-byte decoded image plus dictionary.",
        },
        {
            "id": "phase-banks-v21b",
            "component_key": "phase_banks_v21b",
            "label": "V21B phase sidecar banks",
            "short_label": "PHASE/2/3 banks",
            "category": "phase",
            "archive": None,
            "resource_selector": "modified-build PHASE.DAT, PHASE2.DAT, and PHASE3.DAT decoded tables",
            "slot": None,
            "storage_mode": "modified-build decoded tables",
            "near_live": sum(bank["live"] - bank["far_live"] for bank in PHASE_BANKS_V21B.values()),
            "far_live": sum(bank["far_live"] for bank in PHASE_BANKS_V21B.values()),
            "far_blocks": 0,
            "total_live": sum(bank["live"] for bank in PHASE_BANKS_V21B.values()),
            "lifetime": "experimental gameplay overlay; excluded from stock and scene-state totals",
            "confidence": "exact V21B sidecar arithmetic",
            "report_href": "REPORT.md#phase-aware-footprint-and-ending-diagnosis",
            "note": "Shown only when the optional gameplay overlay is enabled.",
        },
        {
            "id": "phase-kid-delta",
            "component_key": "phase_kid_delta",
            "label": "Modified KID far-memory delta",
            "short_label": "KID phase delta",
            "category": "phase",
            "archive": "KID.DAT",
            "resource_selector": "modified KID table growth over the authenticated stock KID.DAT table",
            "slot": 2,
            "storage_mode": "modified packed table delta",
            "near_live": 0,
            "far_live": 4010,
            "far_blocks": 0,
            "total_live": 4010,
            "lifetime": "experimental gameplay overlay; excluded from stock and scene-state totals",
            "confidence": "exact V21B difference",
            "report_href": "REPORT.md#phase-aware-footprint-and-ending-diagnosis",
            "note": "This is a delta, not a separate stock DAT allocation.",
        },
    ])
    return catalog


def build_memory_states(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build selectable gameplay/scene states from exact retained components."""

    known_ids = {item["id"] for item in catalog}

    def require(refs: list[str]) -> list[str]:
        assert set(refs) <= known_ids
        return refs

    states: list[dict[str, Any]] = []
    for level in level_dicts():
        environment = level["environment"].lower()
        refs = [
            "sword",
            "flame-sword-potion",
            "kid",
            environment,
            f"{environment}-wall",
        ]
        guard_ref = GUARD_COMPONENT.get(level["guard_family"])
        if guard_ref:
            refs.append(guard_ref)
        if level["optional_graphic_rows"]:
            refs.extend(
                f"optional-{environment}-row-{row}"
                for row in level["optional_graphic_rows"].split("|")
            )
        refs.append("surface-gameplay")
        states.append({
            "id": f"level-{level['level']}",
            "kind": "level",
            "source_key": level["level"],
            "label": (
                f"Level {level['level']} - {level['environment']} / "
                f"{level['guard_family'] if level['guard_family'] != 'NONE' else 'no guard'}"
            ),
            "retained_asset_ids": require(refs),
            "transient_asset_ids": ["levels-record"],
            "sound_logical_ids": ["0-43"] + [
                SOUND_GROUP_LOGICAL_IDS[group] for group in LEVEL_SOUND_GROUPS[level["level"]]
            ],
            "load_steps": [
                "Free optional sounds and native sprite slots 3-9.",
                f"Open {('CDUNGEON.DAT' if environment == 'dungeon' else 'CPALACE.DAT')} and load table 200.",
                "Load the level-selected optional image rows.",
                f"Load {level['guard_family']} guard-family table when the level has one.",
                "Load wall table 360, then the selected event sounds.",
                f"Read LEVELS.DAT resource {2000 + level['level']}, copy it, and free the temporary block.",
            ],
            "note": level["special"],
        })

    scene_refs = {
        "opening_title": ["sword", "flame-sword-potion", "title-40", "title-50", "surface-full-screen"],
        "opening_pv": ["sword", "flame-sword-potion", "pv-950-backdrop-retained", "pv-800", "pv-850", "surface-full-screen"],
        "pre_level_2": ["sword", "flame-sword-potion", "kid", "pv-950-backdrop-retained", "pv-800", "pv-850", "surface-gameplay"],
        "pre_levels_4_6_8_9_12": ["sword", "flame-sword-potion", "kid", "pv-950-backdrop-retained", "pv-800", "pv-900", "surface-gameplay"],
        "ending_reunion": ["sword", "flame-sword-potion", "kid", "pv-950-backdrop-retained", "pv-800", "pv-900", "surface-gameplay"],
        "time_expired": ["sword", "flame-sword-potion", "pv-950-backdrop-retained", "pv-800", "pv-900", "surface-full-screen"],
        "ending_title": ["sword", "flame-sword-potion", "title-40", "title-50", "surface-full-screen"],
    }
    pv_steps = [
        "Free optional sounds as requested and clear native sprite slots 3-9.",
        "Load full PV.DAT table 950 and temporary bed table 980 for the background peak.",
        "Draw the room and bed; free PV/980 and the PV/951 image copy while retaining its mask/backdrop data.",
        "Load PV/800 plus the early PV/850 or late PV/900 actor table.",
        "Run the scene, then free native slots 3-9.",
    ]
    scene_sequences = {
        "opening_title": [
            "Load title sounds 50-55 and create the 320x200 surface.",
            "Load packed TITLE.DAT tables 40 and 50.",
            "Decode only the image currently being drawn; release its temporary output afterward.",
        ],
        "opening_pv": pv_steps,
        "pre_level_2": pv_steps,
        "pre_levels_4_6_8_9_12": pv_steps,
        "ending_reunion": pv_steps + [
            "After hug, mouse, and fade, reset the transient suffix before ending TITLE assets load.",
        ],
        "time_expired": ["Perform a global reset and create a 320x200 surface."] + pv_steps,
        "ending_title": [
            "Reset the transient suffix after the reunion.",
            "Load ending sound 56 and create the 320x200 surface.",
            "Load TITLE.DAT tables 40 and 50; decode one displayed image at a time.",
        ],
    }
    scene_sound_ids = {
        "opening_title": ["0-43", "50-55"],
        "opening_pv": ["0-43", "50-55"],
        "pre_level_2": ["0-43"],
        "pre_levels_4_6_8_9_12": ["0-43"],
        "ending_reunion": ["0-43"],
        "time_expired": ["0-43"],
        "ending_title": ["0-43", "56"],
    }
    for scene in scene_dicts():
        transient = ["title-draw-workspace"] if scene["key"] in {"opening_title", "ending_title"} else ["pv-950", "pv-980"]
        variants = [(scene["key"], scene["label"])]
        if scene["key"] == "pre_levels_4_6_8_9_12":
            variants = [
                (f"pre_level_{level}", f"Pre-level {level} cutscene")
                for level in (4, 6, 8, 9, 12)
            ]
        for variant_key, variant_label in variants:
            states.append({
                "id": f"scene-{variant_key.replace('_', '-')}",
                "kind": "scene",
                "source_key": scene["key"],
                "label": variant_label,
                "retained_asset_ids": require(scene_refs[scene["key"]]),
                "transient_asset_ids": require(transient),
                "sound_logical_ids": scene_sound_ids[scene["key"]],
                "load_steps": scene_sequences[scene["key"]],
                "note": scene["note"],
            })
    return states


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

    catalog = {item["id"]: item for item in model["asset_catalog"]}
    levels = {item["level"]: item for item in model["levels"]}
    scenes = {item["key"]: item for item in model["scenes"]}
    state_asset_rows: list[dict[str, Any]] = []
    for state in model["memory_states"]:
        source = levels[state["source_key"]] if state["kind"] == "level" else scenes[state["source_key"]]
        for device in ("pc", "sb", "mt32"):
            values = source["devices"][device]
            sound_live = (
                values["asset_live"] - source["graphics_live"]
                if state["kind"] == "level"
                else values["sound_live"]
            )
            asset_ids = list(state["retained_asset_ids"]) + [f"sound-{device}"]
            for asset_id in asset_ids:
                asset = catalog[asset_id]
                near_live = asset["near_live"]
                far_live = sound_live if asset_id == f"sound-{device}" else asset["far_live"]
                total_live = sound_live if asset_id == f"sound-{device}" else asset["total_live"]
                state_asset_rows.append({
                    "state_id": state["id"],
                    "state_kind": state["kind"],
                    "state_label": state["label"],
                    "device": device,
                    "asset_id": asset_id,
                    "category": asset["category"],
                    "archive": asset.get("archive") or " | ".join(asset.get("archive_refs", [])),
                    "resource_selector": asset["resource_selector"],
                    "near_live": near_live,
                    "far_live": far_live,
                    "total_live": total_live,
                    "lifetime": asset["lifetime"],
                    "confidence": asset["confidence"],
                })
    write_csv(
        DATA_DIR / "state-asset-blocks.csv",
        list(state_asset_rows[0]),
        state_asset_rows,
    )


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
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.5}main{max-width:var(--max);margin:auto;padding:42px 24px 72px}h1,h2,h3{font-weight:500;line-height:1.2;margin:0}h1{font-size:clamp(2rem,5vw,3.6rem);letter-spacing:-.035em;max-width:900px}h2{font-size:1.45rem;margin-bottom:14px}h3{font-size:1.02rem}.eyebrow{color:var(--green);font-size:.78rem;letter-spacing:.15em;text-transform:uppercase;margin-bottom:13px}.lede{color:var(--muted);font-size:1.08rem;max-width:880px;margin:18px 0 0}.stamp{margin-top:18px;color:var(--muted);font-size:.82rem}.stamp code{color:var(--ink)}section{border-top:1px solid var(--line);padding-top:30px;margin-top:38px}.finding-grid,.metric-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.finding{padding:18px 0;border-top:3px solid var(--blue)}.finding:nth-child(2){border-color:var(--red)}.finding:nth-child(3){border-color:var(--purple)}.finding p,.note,p.secondary{color:var(--muted)}.finding p{margin:8px 0 0}.metric{background:var(--surface);padding:15px 16px;min-height:96px}.metric .k{color:var(--muted);font-size:.76rem;text-transform:uppercase;letter-spacing:.08em}.metric .v{font-size:1.35rem;margin-top:5px;font-variant-numeric:tabular-nums}.metric .s{font-size:.79rem;color:var(--muted);margin-top:3px}.controls{display:flex;gap:12px 24px;align-items:end;flex-wrap:wrap;margin:18px 0}.controls fieldset{border:0;padding:0;margin:0;display:flex;gap:8px;flex-wrap:wrap}.controls legend{position:absolute;clip:rect(0 0 0 0)}label.choice,button.level{border:1px solid var(--line);background:transparent;color:var(--ink);padding:8px 12px;cursor:pointer;min-height:40px}label.choice:has(input:checked),button.level[aria-pressed=true]{background:var(--surface2);border-color:var(--blue)}label.choice input{margin-right:7px}.switch{margin-left:auto}.level-grid{display:grid;grid-template-columns:repeat(16,minmax(36px,1fr));gap:5px;margin:12px 0 18px}.level{padding:8px 4px!important;font:inherit;font-variant-numeric:tabular-nums}.bar-caption{display:flex;justify-content:space-between;gap:18px;color:var(--muted);font-size:.82rem}.chart-wrap{margin-top:25px}.chart-wrap svg{width:100%;height:auto;display:block}.chart-axis{stroke:var(--line);stroke-width:1}.chart-label{fill:var(--muted);font-size:12px}.chart-line{fill:none;stroke:var(--blue);stroke-width:3}.chart-dot{fill:var(--blue)}.timeline{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:26px;margin-top:24px}.stage{position:relative;background:var(--surface);padding:17px 15px;min-height:130px}.stage:not(:last-child)::after{content:'→';position:absolute;right:-22px;top:48px;color:var(--muted);font-size:1.5rem}.stage p{color:var(--muted);font-size:.85rem;margin:8px 0 0}.table-wrap{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:.86rem}th,td{text-align:left;padding:10px 9px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:500}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.arena-row{display:grid;grid-template-columns:repeat(8,1fr);gap:7px;margin:19px 0}.arena{height:92px;background:repeating-linear-gradient(135deg,var(--surface),var(--surface) 8px,var(--surface2) 8px,var(--surface2) 16px);position:relative;overflow:hidden;border:1px solid var(--line)}.arena span{position:absolute;inset:8px;font-size:.74rem;z-index:1}.critical-pair{display:flex;gap:7px;margin-top:12px}.critical-pair span{min-height:38px;width:32%;background:var(--orange);display:flex;align-items:center;justify-content:center;color:#1a0b00;font-size:.74rem;padding:4px;text-align:center}.phase-equation{font-size:clamp(1rem,2.2vw,1.3rem);font-variant-numeric:tabular-nums;margin:18px 0}.callout{border-left:4px solid var(--orange);padding:4px 0 4px 18px;margin:20px 0}.callout strong{font-weight:500}.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:.8rem}.swatch{display:inline-block;width:11px;height:11px;margin-right:6px}.evidence{display:grid;grid-template-columns:1fr 1fr;gap:20px}.evidence code{word-break:break-all}.links{display:flex;gap:18px;flex-wrap:wrap}.links a,.asset-inspector a,.asset-directory a,.load-flow a{color:var(--blue)}footer{color:var(--muted);font-size:.8rem;margin-top:45px;padding-top:20px;border-top:1px solid var(--line)}
.state-field{display:grid;gap:5px;min-width:min(100%,340px);color:var(--muted);font-size:.8rem}.state-field select{width:100%;min-height:42px;background:var(--surface);border:1px solid var(--line);color:var(--ink);font:inherit;padding:8px 34px 8px 10px}.state-field select:focus{outline:2px solid var(--blue);outline-offset:2px}.phase-hint{display:block;color:var(--muted);font-size:.74rem;margin-top:3px}.map-caveat{color:var(--muted);font-size:.84rem;margin:14px 0}.allocation-lane{margin-top:20px}.lane-head{display:flex;justify-content:space-between;gap:14px;align-items:end;margin-bottom:7px}.lane-head strong{font-weight:500}.lane-head span{color:var(--muted);font-size:.78rem;text-align:right}.allocation-strip{display:flex;position:relative;height:72px;background:var(--surface);overflow:hidden}.memory-segment{height:100%;padding:5px 4px;border:0;border-right:2px solid var(--bg);color:#071019;font:inherit;font-size:.7rem;line-height:1.15;overflow:hidden;cursor:pointer;text-align:left;min-width:0;white-space:normal}.memory-segment:focus{outline:3px solid var(--ink);outline-offset:-4px;z-index:3}.memory-segment small{display:block;font-size:.66rem;margin-top:3px}.category-permanent{background:var(--blue)}.category-character{background:var(--purple)}.category-environment{background:var(--green)}.category-optional{background:var(--yellow)}.category-cutscene{background:var(--orange)}.category-title{background:var(--yellow)}.category-sound{background:var(--red)}.category-surface{background:#7e98ad}.category-phase{background:#df8dff}.category-transition{background:var(--orange)}.aggregate-free{height:100%;background:repeating-linear-gradient(135deg,var(--free),var(--free) 8px,var(--surface2) 8px,var(--surface2) 16px);color:var(--ink);display:flex;align-items:center;justify-content:center;font-size:.72rem;padding:5px;overflow:hidden}.capacity-marker{position:absolute;top:0;bottom:0;border-right:2px solid var(--ink);pointer-events:none}.near-strip{height:54px}.map-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(270px,340px);gap:22px;align-items:start;margin-top:22px}.asset-inventory h3,.asset-inspector h3,.load-area h3{margin-bottom:9px}.asset-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px}.asset-tile{min-height:58px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-top:4px solid var(--line);font:inherit;padding:8px;text-align:left;cursor:pointer}.asset-tile[data-category=permanent]{border-top-color:var(--blue)}.asset-tile[data-category=character]{border-top-color:var(--purple)}.asset-tile[data-category=environment]{border-top-color:var(--green)}.asset-tile[data-category=optional],.asset-tile[data-category=title]{border-top-color:var(--yellow)}.asset-tile[data-category=cutscene],.asset-tile[data-category=transition]{border-top-color:var(--orange)}.asset-tile[data-category=sound]{border-top-color:var(--red)}.asset-tile[data-category=surface]{border-top-color:#7e98ad}.asset-tile[data-category=phase]{border-top-color:#df8dff}.asset-tile[aria-pressed=true]{background:var(--surface2);border-color:var(--blue)}.asset-tile .tile-name{display:block;font-size:.8rem}.asset-tile .tile-meta{display:block;color:var(--muted);font-size:.72rem;margin-top:3px}.asset-inspector{background:var(--surface);padding:17px;min-height:250px;position:sticky;top:12px}.inspector-type{color:var(--green);font-size:.72rem;letter-spacing:.08em;text-transform:uppercase}.inspector-source{color:var(--muted);margin:7px 0 12px;overflow-wrap:anywhere}.inspector-values{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}.inspector-values div{background:var(--surface2);padding:8px}.inspector-values span{display:block;color:var(--muted);font-size:.68rem;text-transform:uppercase}.inspector-values strong{font-weight:500;font-size:.85rem;font-variant-numeric:tabular-nums}.inspector-detail{font-size:.82rem;color:var(--muted);margin:7px 0}.load-area{margin-top:26px}.transition-assets{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:12px}.transition-assets .asset-tile{flex:0 1 230px}.peak-note{color:var(--muted);font-size:.82rem;margin:8px 0 14px}.load-flow{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:22px;counter-reset:loadstep}.load-step{background:var(--surface);padding:13px;min-height:94px;position:relative;color:var(--muted);font-size:.8rem}.load-step::before{counter-increment:loadstep;content:counter(loadstep);display:block;color:var(--ink);font-size:.72rem;margin-bottom:6px}.load-step:not(:last-child)::after{content:'→';position:absolute;right:-17px;top:34px;color:var(--muted);font-size:1.25rem}.comparison-heading{margin-top:30px}.state-context{margin:8px 0;color:var(--muted)}.asset-directory tr[id]{scroll-margin-top:16px}.asset-directory .source-cell{overflow-wrap:anywhere}.asset-directory code{color:var(--ink)}
@media(max-width:800px){.finding-grid,.metric-grid{grid-template-columns:1fr}.timeline{grid-template-columns:1fr}.stage:not(:last-child)::after{content:'↓';right:16px;top:auto;bottom:-25px}.level-grid{grid-template-columns:repeat(8,1fr)}.evidence{grid-template-columns:1fr}.switch{margin-left:0}.arena-row{grid-template-columns:repeat(4,1fr)}}
@media(max-width:420px){main{padding:28px 15px 55px}.level-grid{grid-template-columns:repeat(4,1fr)}.bar-caption{display:block}.arena-row{grid-template-columns:repeat(2,1fr)}}
@media(max-width:800px){.map-layout{grid-template-columns:1fr}.asset-inspector{position:static}.asset-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.controls{align-items:stretch}}
@media(max-width:520px){.load-flow{grid-template-columns:1fr;gap:20px}.load-step:not(:last-child)::after{content:'↓';right:12px;top:auto;bottom:-20px}}
@media(max-width:420px){.asset-tiles{grid-template-columns:1fr}.allocation-strip{height:64px}.memory-segment{font-size:.66rem}.state-field{min-width:100%}.lane-head{display:block}.lane-head span,.bar-caption span{display:block;text-align:left;margin-top:3px}}
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
  <h2 id="explore-title">Explore gameplay and cutscene memory</h2>
  <div class="controls">
    <label class="state-field">Memory state
      <select id="statePicker" aria-label="Select a gameplay level or cutscene"></select>
    </label>
    <fieldset aria-label="Sound device">
      <legend>Sound device</legend>
      <label class="choice"><input type="radio" name="device" value="pc">PC speaker</label>
      <label class="choice"><input type="radio" name="device" value="sb">Sound Blaster</label>
      <label class="choice"><input type="radio" name="device" value="mt32" checked>MT-32</label>
    </fieldset>
    <label class="choice switch"><input id="phaseToggle" type="checkbox">Overlay V21B gameplay payload<span id="phaseHint" class="phase-hint">Modified build; excluded from stock totals</span></label>
  </div>
  <div class="metric-grid" aria-live="polite">
    <div class="metric"><div class="k">Selected state</div><div id="stateName" class="v"></div><div id="stateMeta" class="s"></div></div>
    <div class="metric"><div class="k">Retained asset blocks</div><div id="assetLive" class="v"></div><div class="s">Graphics + chosen sounds; exact live bytes</div></div>
    <div class="metric"><div class="k">Aggregate free-block extent</div><div id="poolFree" class="v"></div><div id="poolFreeNote" class="s"></div></div>
  </div>

  <p class="map-caveat"><strong>How to read this:</strong> widths and byte counts are exact aggregate live allocations. Their left-to-right order is an inventory, not a physical address map. Each DAT-colored region can contain many independent allocator blocks; the hatched remainder is the sum of free holes, not one contiguous hole.</p>
  <div class="allocation-lane">
    <div class="lane-head"><strong>Far CRT heap block inventory</strong><span id="farScale"></span></div>
    <div id="farLane" class="allocation-strip" role="group" aria-label="Selected state's proportional far-heap block inventory"></div>
  </div>
  <div class="bar-caption"><span id="poolLeft"></span><span id="poolRight"></span></div>
  <div class="allocation-lane">
    <div class="lane-head"><strong>Known near-heap allocations</strong><span>Separate scale; no unsupported free-capacity claim</span></div>
    <div id="nearLane" class="allocation-strip near-strip" role="group" aria-label="Selected state's known near allocation blocks"></div>
  </div>
  <div class="legend">
    <span><i class="swatch" style="background:var(--blue)"></i>permanent</span>
    <span><i class="swatch" style="background:var(--purple)"></i>character</span>
    <span><i class="swatch" style="background:var(--green)"></i>environment</span>
    <span><i class="swatch" style="background:var(--yellow)"></i>optional/title</span>
    <span><i class="swatch" style="background:var(--orange)"></i>cutscene</span>
    <span><i class="swatch" style="background:var(--red)"></i>sound</span>
    <span><i class="swatch" style="background:var(--free)"></i>aggregate free</span>
  </div>

  <div class="map-layout">
    <div class="asset-inventory">
      <h3>Readable asset blocks</h3>
      <p class="note">Hover or focus for details; select on touch or keyboard. The inspector links to the exact DAT/resource record below.</p>
      <div id="assetTiles" class="asset-tiles"></div>
    </div>
    <aside id="assetInspector" class="asset-inspector" aria-labelledby="inspectorTitle">
      <div id="inspectorType" class="inspector-type">Asset block</div>
      <h3 id="inspectorTitle"></h3>
      <div id="inspectorSource" class="inspector-source"></div>
      <div class="inspector-values">
        <div><span>Near live</span><strong id="inspectorNear"></strong></div>
        <div><span>Far live</span><strong id="inspectorFar"></strong></div>
        <div><span>Total live</span><strong id="inspectorTotal"></strong></div>
      </div>
      <p id="inspectorPlacement" class="inspector-detail"></p>
      <p id="inspectorLifetime" class="inspector-detail"></p>
      <p id="inspectorConfidence" class="inspector-detail"></p>
      <a id="inspectorLink" href="#asset-directory">Open DAT/resource record ↓</a>
    </aside>
  </div>

  <div class="load-area">
    <h3>Transition-only blocks and modeled peak</h3>
    <div id="transitionAssets" class="transition-assets"></div>
    <p id="peakNote" class="peak-note"></p>
    <h3>How this state is reached</h3>
    <div id="loadFlow" class="load-flow"></div>
  </div>

  <h3 class="comparison-heading">Compare gameplay levels</h3>
  <p id="stateContext" class="state-context"></p>
  <div id="levelGrid" class="level-grid" aria-label="Select a gameplay level"></div>
  <div class="chart-wrap"><svg id="levelChart" viewBox="0 0 1080 320" role="img" aria-labelledby="chartTitle chartDesc"><title id="chartTitle">Retained assets by level</title><desc id="chartDesc">A line plot for the selected sound device.</desc></svg></div>
  <div id="levelDetails" class="table-wrap">
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
  <div id="arenaRow" class="arena-row" aria-label="Exact retained CRT arena geometry with path-dependent internal placement"></div>
  <div class="critical-pair" aria-label="Two required PV 951 allocations"><span>PV/951 image<br>32,006 B</span><span>PV/951 mask<br>32,006 B</span></div>
  <p id="arenaNote" class="note"></p>
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

<section id="asset-directory" class="asset-directory" aria-labelledby="asset-directory-title">
  <h2 id="asset-directory-title">DAT asset and runtime-block directory</h2>
  <p class="note">These are provenance links, not bundled game data. DAT archives remain excluded from GitHub and the download ZIP.</p>
  <div class="table-wrap"><table><thead><tr><th>Asset/block</th><th>DAT and resources</th><th>Slot / lifetime</th><th class="num">Stock live</th><th>Evidence</th></tr></thead><tbody id="assetDirectoryRows"></tbody></table></div>
  <p><a href="#explore-title">Back to the selected block map ↑</a></p>
</section>

<section aria-labelledby="evidence-title">
  <h2 id="evidence-title">Evidence and reproducibility</h2>
  <div class="evidence">
    <div><h3>Authenticated inputs</h3><p class="secondary">PRINCE.EXE: 125,115 bytes<br><code>24fdc79b4de563348313b50d717e171919191e5c38559f5bdd6a4751d39b7158</code></p><p class="secondary">DOSBox 0.74-3: 3,745,792 bytes<br><code>dcfd46fa521f5ce89dce3bf026056f3a1d15533f80321ee887403e30d7949f5e</code></p></div>
    <div><h3>Confidence vocabulary</h3><p class="secondary"><strong>Exact</strong>: authenticated bytes, disassembly, DAT arithmetic, or allocator arithmetic.<br><strong>Measured</strong>: isolated stock DOSBox trace.<br><strong>Derived</strong>: arithmetic combination of exact values.<br><strong>Path-dependent</strong>: arena-hole topology depends on prior allocation order.</p></div>
  </div>
  <div class="links"><a href="REPORT.md">Full technical report</a><a href="memory-map.svg">Static shareable map</a><a href="data/memory-model.json">JSON model</a><a href="data/levels.csv">Level CSV</a><a href="data/scenes.csv">Scene CSV</a><a href="data/state-asset-blocks.csv">State asset-block CSV</a><a href="dynamic/README.md">DOSBox probe notes</a></div>
</section>
<footer>Generated from exact constants checked by <code>tools/build_memory_map.py</code>. No original game binary or DAT payload is embedded.</footer>
</main>
<script>
const model=__MODEL_JSON__;
const devices={pc:'PC speaker',sb:'Sound Blaster',mt32:'MT-32'};
const assets=Object.fromEntries(model.asset_catalog.map(asset=>[asset.id,asset]));
const levelsByNumber=Object.fromEntries(model.levels.map(level=>[level.level,level]));
const scenesByKey=Object.fromEntries(model.scenes.map(scene=>[scene.key,scene]));
let selectedStateId='level-14';
let selectedLevel=14;
let selectedDevice='mt32';
let showPhase=false;
let selectedAssetId=null;
let inspectableBlocks=[];
const fmt=b=>`${(b/1024).toFixed(1)} KiB`;
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function currentState(){return model.memory_states.find(state=>state.id===selectedStateId)}
function sourceFor(state){return state.kind==='level'?levelsByNumber[state.source_key]:scenesByKey[state.source_key]}
function archiveText(asset){
  const refs=[asset.archive,...(asset.archive_refs||[])].filter(Boolean);
  return [...new Set(refs)].join(' / ')||'Runtime-created block';
}
function logicalResourceText(ids){
  return ids.map(value=>{
    const parts=value.split('-').map(Number);
    return parts.length===1?`R${10000+parts[0]}`:`R${10000+parts[0]}-R${10000+parts[1]}`;
  }).join(', ');
}
function logicalResourceCount(ids){
  return ids.reduce((count,value)=>{const parts=value.split('-').map(Number);return count+(parts.length===1?1:parts[1]-parts[0]+1)},0);
}

function buildStatePicker(){
  const picker=document.getElementById('statePicker');
  const gameplay=document.createElement('optgroup');gameplay.label='Gameplay levels';
  const scenes=document.createElement('optgroup');scenes.label='Cutscenes and title states';
  model.memory_states.forEach(state=>{const option=document.createElement('option');option.value=state.id;option.textContent=state.label;(state.kind==='level'?gameplay:scenes).appendChild(option)});
  picker.append(gameplay,scenes);picker.value=selectedStateId;
  picker.addEventListener('change',()=>{selectedStateId=picker.value;const state=currentState();if(state.kind==='level')selectedLevel=state.source_key;render()});
}

function buildLevelGrid(){
  const grid=document.getElementById('levelGrid');
  model.levels.forEach(level=>{const button=document.createElement('button');button.type='button';button.className='level';button.textContent=level.level;button.setAttribute('aria-label',`Level ${level.level}`);button.addEventListener('click',()=>{selectedLevel=level.level;selectedStateId=`level-${level.level}`;document.getElementById('statePicker').value=selectedStateId;render()});grid.appendChild(button)});
}

function resolvedBlocks(state,source){
  const retained=state.retained_asset_ids.map(id=>({...assets[id]}));
  const surfaceIndex=retained.findIndex(asset=>asset.category==='surface');
  const surface=retained.splice(surfaceIndex,1)[0];
  const values=source.devices[selectedDevice];
  const soundLive=state.kind==='level'?values.asset_live-source.graphics_live:values.sound_live;
  const soundBase=assets[`sound-${selectedDevice}`];
  const sound={...soundBase,far_live:soundLive,total_live:soundLive,far_blocks:model.sound_profiles[selectedDevice].core_blocks+logicalResourceCount(state.sound_logical_ids.slice(1)),resource_selector:`${soundBase.resource_selector}. This state selects logical sounds ${state.sound_logical_ids.join(', ')} (${logicalResourceText(state.sound_logical_ids)}).`};
  const blocks=[...retained,sound];
  if(showPhase&&state.kind==='level')blocks.push({...assets['phase-banks-v21b']},{...assets['phase-kid-delta']});
  blocks.push(surface);
  return blocks;
}

function wireAssetControl(control,asset){
  control.setAttribute('aria-controls','assetInspector');
  control.addEventListener('pointerenter',()=>renderInspector(asset));
  control.addEventListener('focus',()=>renderInspector(asset));
  control.addEventListener('click',()=>renderInspector(asset));
}

function makeMemorySegment(asset,bytes,scale,heap){
  const button=document.createElement('button');button.type='button';button.className=`memory-segment category-${asset.category}`;button.dataset.asset=asset.id;button.style.width=`${100*bytes/scale}%`;
  const pct=100*bytes/scale;button.setAttribute('aria-label',`${asset.label}: ${fmt(bytes)} ${heap} live; inspect asset`);
  if(pct>=4){const name=document.createElement('span');name.textContent=asset.short_label;button.appendChild(name);if(pct>=8){const value=document.createElement('small');value.textContent=fmt(bytes);button.appendChild(value)}}
  wireAssetControl(button,asset);return button;
}

function makeAssetTile(asset,extraClass=''){
  const button=document.createElement('button');button.type='button';button.className=`asset-tile ${extraClass}`.trim();button.dataset.asset=asset.id;button.dataset.category=asset.category;button.setAttribute('aria-pressed',asset.id===selectedAssetId?'true':'false');button.setAttribute('aria-label',`${asset.label}; ${fmt(asset.total_live)} live; inspect details`);
  const name=document.createElement('span');name.className='tile-name';name.textContent=asset.short_label;
  const meta=document.createElement('span');meta.className='tile-meta';meta.textContent=`${asset.category} · ${fmt(asset.total_live)}`;
  button.append(name,meta);wireAssetControl(button,asset);return button;
}

function renderInspector(asset){
  selectedAssetId=asset.id;
  document.querySelectorAll('[data-asset]').forEach(control=>control.setAttribute('aria-pressed',control.dataset.asset===asset.id?'true':'false'));
  document.getElementById('inspectorType').textContent=`${asset.category} block${asset.slot===null||asset.slot===undefined?'':` · native slot ${asset.slot}`}`;
  document.getElementById('inspectorTitle').textContent=asset.label;
  document.getElementById('inspectorSource').textContent=`${archiveText(asset)} · ${asset.resource_selector}`;
  document.getElementById('inspectorNear').textContent=asset.near_live?fmt(asset.near_live):'—';
  document.getElementById('inspectorFar').textContent=asset.far_live?fmt(asset.far_live):'—';
  document.getElementById('inspectorTotal').textContent=fmt(asset.total_live);
  const blockCount=asset.far_blocks||0;
  document.getElementById('inspectorPlacement').textContent=blockCount>1?`Far value is the aggregate of ${blockCount} independently allocated blocks; it is not one contiguous extent.`:blockCount===1?'Far value is one contiguous allocator block; its arena/address still depends on allocation history.':'No single physical placement is asserted for this aggregate or transition value.';
  document.getElementById('inspectorLifetime').textContent=`Lifetime: ${asset.lifetime}. ${asset.note||''}`;
  document.getElementById('inspectorConfidence').textContent=`Confidence: ${asset.confidence}. Storage: ${asset.storage_mode}.`;
  document.getElementById('inspectorLink').href=`#asset-${asset.id}`;
}

function renderBlockMap(state,source){
  const values=source.devices[selectedDevice],pool=values.startup_far_block_chain_extent_capacity;
  const blocks=resolvedBlocks(state,source),used=blocks.reduce((sum,asset)=>sum+asset.far_live,0),free=pool-used,scale=Math.max(pool,used);
  const far=document.getElementById('farLane');far.replaceChildren();
  blocks.filter(asset=>asset.far_live>0).forEach(asset=>far.appendChild(makeMemorySegment(asset,asset.far_live,scale,'far')));
  if(free>0){const freeBlock=document.createElement('div');freeBlock.className='aggregate-free';freeBlock.style.width=`${100*free/scale}%`;freeBlock.textContent=free/pool>.13?`${fmt(free)} aggregate free`:'';freeBlock.setAttribute('role','img');freeBlock.setAttribute('aria-label',`${fmt(free)} aggregate free-block extent, not one contiguous hole`);far.appendChild(freeBlock)}
  if(used>pool){const marker=document.createElement('span');marker.className='capacity-marker';marker.style.left=`${100*pool/scale}%`;marker.setAttribute('aria-hidden','true');far.appendChild(marker)}
  document.getElementById('farScale').textContent=used>pool?`${fmt(scale)} shown; vertical marker = ${fmt(pool)} startup capacity`:`Scale = ${fmt(pool)} startup block-chain capacity`;
  document.getElementById('poolLeft').textContent=`Selected far blocks + surface${showPhase&&state.kind==='level'?' + V21B overlay':''}: ${fmt(used)}`;
  document.getElementById('poolRight').textContent=`Committed far-arena payload: ${fmt(values.startup_far_pool_payload)} · DOS still free: ${fmt(values.dos_free_payload_outside_crt_pools_after_startup_probe)}`;
  const nearBlocks=blocks.filter(asset=>asset.near_live>0),nearTotal=nearBlocks.reduce((sum,asset)=>sum+asset.near_live,0),near=document.getElementById('nearLane');near.replaceChildren();nearBlocks.forEach(asset=>near.appendChild(makeMemorySegment(asset,asset.near_live,nearTotal,'near')));
  const tiles=document.getElementById('assetTiles');tiles.replaceChildren();blocks.forEach(asset=>tiles.appendChild(makeAssetTile(asset)));
  const transient=state.transient_asset_ids.map(id=>({...assets[id]}));
  if(state.kind==='level'&&state.source_key===15)transient[0]={...transient[0],total_live:2520,note:'2,520-byte level-15 peak; no bytes remain after the copy.'};
  const transitionArea=document.getElementById('transitionAssets');transitionArea.replaceChildren();transient.forEach(asset=>transitionArea.appendChild(makeAssetTile(asset)));
  inspectableBlocks=[...blocks,...transient];
  const preferred=inspectableBlocks.find(asset=>asset.id===selectedAssetId)||blocks.find(asset=>['character','cutscene','title'].includes(asset.category))||blocks[0];renderInspector(preferred);
  const surface=blocks.find(asset=>asset.category==='surface'),steady=values.asset_live+surface.total_live;
  if(state.kind==='scene'){
    const peak=Math.max(values.load_peak_live_with_surface||0,values.draw_peak_live_with_surface||0);
    document.getElementById('peakNote').textContent=`Modeled peak envelope: ${fmt(peak)} including the surface, versus ${fmt(steady)} in the retained state shown above. Transition tiles describe different instants and must not all be added to the retained bar.`;
  }else{
    const levelPeak=state.source_key===15?2520:2522;
    document.getElementById('peakNote').textContent=`LEVELS.DAT's record plus handle add ${fmt(levelPeak)} at the level boundary, then return to zero retained bytes. Frame peels vary with the objects, clipping, and phases actually drawn (31.5 KiB is only a structural ceiling).`;
  }
  const flow=document.getElementById('loadFlow');flow.innerHTML=state.load_steps.map(step=>`<div class="load-step">${esc(step)}</div>`).join('');
}

function render(){
  const state=currentState(),source=sourceFor(state),values=source.devices[selectedDevice];
  const phaseActive=showPhase&&state.kind==='level';
  const phaseFar=phaseActive?model.phase_banks_v21b_totals.far_live+model.phase_banks_v21b_totals.modified_kid_far_live_delta:0;
  const phaseTotal=phaseActive?model.phase_banks_v21b_totals.live+model.phase_banks_v21b_totals.modified_kid_far_live_delta:0;
  const free=values.startup_far_block_chain_extent_capacity-values.far_live_with_surface-phaseFar;
  document.getElementById('statePicker').value=selectedStateId;
  document.querySelectorAll('button.level').forEach((button,index)=>button.setAttribute('aria-pressed',state.kind==='level'&&index===state.source_key?'true':'false'));
  document.getElementById('stateName').textContent=`${state.label} · ${devices[selectedDevice]}`;
  document.getElementById('stateMeta').textContent=state.kind==='level'?`${source.environment} · ${source.guard_family} · ${state.note}`:`Cutscene/title · ${source.surface.replace('_',' ')} surface · ${state.note}`;
  document.getElementById('assetLive').textContent=fmt(values.asset_live+phaseTotal);
  document.getElementById('poolFree').textContent=(free<0?'−':'')+fmt(Math.abs(free));
  document.getElementById('poolFree').style.color=free<0?'var(--red)':'';
  document.getElementById('poolFreeNote').textContent=free<0?'aggregate overflow; allocator fallback and hole topology become decisive':'sum of arena-local holes; largest useful hole can be smaller';
  const phaseToggle=document.getElementById('phaseToggle');phaseToggle.disabled=state.kind!=='level';document.getElementById('phaseHint').textContent=state.kind==='level'?'Modified build; excluded from stock totals':'Scene map is stock; gameplay overlay is not counted here';
  document.getElementById('levelDetails').hidden=state.kind!=='level';
  document.getElementById('stateContext').textContent=state.kind==='level'?`Level ${state.source_key} is selected above and emphasized in the comparison.`:'A scene is selected above; choose a numbered level here to switch back to gameplay.';
  if(state.kind==='level'){
    document.getElementById('environment').textContent=source.environment;document.getElementById('guard').textContent=source.guard_family;document.getElementById('optional').textContent=source.optional_graphic_rows||'none';document.getElementById('cutscene').textContent=source.cutscene_before;document.getElementById('special').textContent=source.special;
  }
  renderBlockMap(state,source);renderChart();renderScenes();renderArenaGeometry();
}
function renderChart(){
  const state=currentState(),svg=document.getElementById('levelChart'),W=1080,H=320,L=65,R=22,T=18,B=45,vals=model.levels.map(level=>level.devices[selectedDevice].asset_live+(showPhase?model.phase_banks_v21b_totals.live+model.phase_banks_v21b_totals.modified_kid_far_live_delta:0));
  const min=60*1024,max=Math.max(275*1024,Math.max(...vals)*1.08),x=i=>L+i*(W-L-R)/15,y=v=>T+(max-v)*(H-T-B)/(max-min);
  let s='';for(const k of [80,120,160,200,240,280,320,360,400,440]){if(k*1024>max)continue;const yy=y(k*1024);s+=`<line class="chart-axis" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/><text class="chart-label" x="${L-10}" y="${yy+4}" text-anchor="end">${k}</text>`}for(let i=0;i<16;i++){s+=`<text class="chart-label" x="${x(i)}" y="${H-15}" text-anchor="middle">${i}</text>`}const points=vals.map((v,i)=>`${x(i)},${y(v)}`).join(' ');s+=`<polyline class="chart-line" points="${points}"/>`;vals.forEach((v,i)=>s+=`<circle class="chart-dot" cx="${x(i)}" cy="${y(v)}" r="${state.kind==='level'&&i===state.source_key?6:3.5}"/>`);s+=`<text class="chart-label" x="15" y="18">KiB</text><text class="chart-label" x="${W/2}" y="${H-1}" text-anchor="middle">Level</text>`;svg.innerHTML=`<title>Retained assets by level for ${devices[selectedDevice]}</title><desc>${state.kind==='level'?`Level ${state.source_key} is emphasized.`:'No level is emphasized while a scene is selected.'} Values include graphics and sound resource blocks, excluding surfaces and the fixed executable.</desc>${s}`;
}
function renderScenes(){
  document.getElementById('sceneRows').innerHTML=model.scenes.map(s=>{const d=s.devices[selectedDevice],peak=Math.max(d.load_peak_live_with_surface||0,d.draw_peak_live_with_surface||0);return `<tr><td>${esc(s.label)}</td><td class="num">${fmt(d.asset_live)}</td><td class="num">${peak?fmt(peak):'—'}</td><td>${esc(s.note)}</td></tr>`}).join('');
}
function initTables(){
  document.getElementById('startupRows').innerHTML=Object.entries(model.allocator.startup_pools).map(([k,p])=>`<tr><td>${devices[k]}</td><td class="num">${fmt(p.bootstrap_far_arena_payload)}</td><td class="num">${p.probe_full_far_arena_count}</td><td class="num">${fmt(p.far_pool_payload)}</td><td class="num">${fmt(p.dos_free_payload_after_probe)}</td></tr>`).join('');
  document.getElementById('soundRows').innerHTML=Object.entries(model.sound_profiles).map(([k,p])=>`<tr><td>${esc(p.label)}</td><td class="num">${fmt(p.core_live)}</td><td class="num">${fmt(p.optional_all_live)}</td><td class="num">${fmt(p.ending_live)}</td><td>${esc(model.allocator.startup_pools[k].note)} ${esc(p.note)}</td></tr>`).join('');
  const l14=model.levels[14].devices.mt32.far_live_with_surface,p=model.phase_banks_v21b_totals;document.getElementById('phaseEquation').textContent=`MT-32 level 14: ${fmt(l14)} stock far live + ${fmt(p.far_live)} phase banks + ${fmt(p.modified_kid_far_live_delta)} KID delta = ${fmt(l14+p.far_live+p.modified_kid_far_live_delta)} inside ${fmt(model.allocator.startup_pools.mt32.far_block_chain_extent_capacity)} of startup block-chain capacity.`;
}

function renderArenaGeometry(){
  const pool=model.allocator.startup_pools[selectedDevice],row=document.getElementById('arenaRow');row.replaceChildren();
  for(let index=0;index<pool.total_far_arena_count;index++){
    const arena=document.createElement('div');arena.className='arena';const label=document.createElement('span');label.innerHTML=index===0?`arena 0<br>${fmt(pool.bootstrap_far_arena_payload)} bootstrap<br>placement unknown`:`arena ${index}<br>${fmt(pool.far_arena_payload_each)} payload<br>placement unknown`;arena.appendChild(label);row.appendChild(arena);
  }
  document.getElementById('arenaNote').textContent=`${devices[selectedDevice]} retains ${pool.total_far_arena_count} far arenas: one ${fmt(pool.bootstrap_far_arena_payload)} bootstrap payload plus ${pool.probe_full_far_arena_count} full ${fmt(pool.far_arena_payload_each)} payloads. The outlines and capacities are exact; selected asset addresses, ordering, and free-hole shapes are path-dependent and intentionally not invented.`;
}

function renderAssetDirectory(){
  document.getElementById('assetDirectoryRows').innerHTML=model.asset_catalog.map(asset=>{
    const source=`<code>${esc(archiveText(asset))}</code><br>${esc(asset.resource_selector)}`;
    const slot=asset.slot===null||asset.slot===undefined?'no native slot':`native slot ${asset.slot}`;
    const live=asset.total_live?fmt(asset.total_live):'state-dependent';
    return `<tr id="asset-${esc(asset.id)}"><td><strong>${esc(asset.label)}</strong><br><code>${esc(asset.short_label)}</code></td><td class="source-cell">${source}</td><td>${esc(slot)}<br>${esc(asset.lifetime)}</td><td class="num">${esc(live)}</td><td><a href="${esc(asset.report_href)}">Technical evidence</a></td></tr>`;
  }).join('');
}

document.querySelectorAll('input[name=device]').forEach(radio=>radio.addEventListener('change',event=>{selectedDevice=event.target.value;render()}));
document.getElementById('phaseToggle').addEventListener('change',event=>{showPhase=event.target.checked;render()});
buildStatePicker();buildLevelGrid();initTables();renderAssetDirectory();render();
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
        DATA_DIR / "state-asset-blocks.csv",
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
    catalog = {item["id"]: item for item in model["asset_catalog"]}
    assert len(catalog) == len(model["asset_catalog"])
    assert catalog["pv-950-backdrop-retained"]["near_live"] == 104
    assert catalog["pv-950-backdrop-retained"]["far_live"] == 36_920
    assert catalog["pv-950-backdrop-retained"]["total_live"] == 37_024
    assert catalog["pv-950-backdrop-retained"]["far_blocks"] == 23
    known_archives = {row[0] for row in ARCHIVES}
    for asset in model["asset_catalog"]:
        if asset.get("archive"):
            assert asset["archive"] in known_archives
        assert set(asset.get("archive_refs", [])) <= known_archives
    levels_by_id = {item["level"]: item for item in model["levels"]}
    scenes_by_key = {item["key"]: item for item in model["scenes"]}
    assert len(model["memory_states"]) == 27
    for state in model["memory_states"]:
        source = levels_by_id[state["source_key"]] if state["kind"] == "level" else scenes_by_key[state["source_key"]]
        blocks = [catalog[asset_id] for asset_id in state["retained_asset_ids"]]
        asset_blocks = [block for block in blocks if block["category"] != "surface"]
        assert sum(block["total_live"] for block in asset_blocks) == source["graphics_live"], state["id"]
        assert sum(block["near_live"] for block in asset_blocks) == source["near_graphics_live"], state["id"]
        for device in ("pc", "sb", "mt32"):
            values = source["devices"][device]
            sound_live = (
                values["asset_live"] - source["graphics_live"]
                if state["kind"] == "level"
                else values["sound_live"]
            )
            assert sum(block["total_live"] for block in blocks) + sound_live == (
                values["asset_live"] + next(block["total_live"] for block in blocks if block["category"] == "surface")
            ), (state["id"], device)
            assert sum(block["far_live"] for block in blocks) + sound_live == values["far_live_with_surface"], (state["id"], device)
    for level in model["levels"]:
        for device, profile in SOUND_PROFILES.items():
            optional_live = sum(profile["event_groups"][group][1] for group in LEVEL_SOUND_GROUPS[level["level"]])
            assert level["devices"][device]["asset_live"] - level["graphics_live"] == profile["core_live"] + optional_live
    for item in model["levels"]:
        for device, values in item["devices"].items():
            assert values["asset_live"] >= item["graphics_live"]
            assert values["far_asset_live"] == values["asset_live"] - item["near_graphics_live"]
            assert values["aggregate_free_block_extent_before_hole_contiguity"] > 0, (item["level"], device)
    level_5 = model["levels"][5]
    assert level_5["devices"]["sb"]["asset_live"] == 250502
    assert level_5["devices"]["sb"]["aggregate_free_block_extent_before_hole_contiguity"] == 203254


def build_model() -> dict[str, Any]:
    asset_catalog = build_asset_catalog()
    memory_states = build_memory_states(asset_catalog)
    return {
        "schema": 2,
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
        "asset_catalog": asset_catalog,
        "memory_states": memory_states,
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
