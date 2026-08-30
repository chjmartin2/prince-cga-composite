"""Original DOS Prince of Persia CGA placement and carrier-phase audit.

The editor stores Mode-6 artwork in 640-column signal pixels, while the game
places every bitmap with integral 320-column X coordinates.  One game pixel is
therefore two signal pixels.  With the screen origin normalized to carrier P0,
an even final 320-column blit X selects P0 and an odd X selects P2.  P1 and P3
are unreachable unless the whole display has an odd global carrier bias or a
future executable patch introduces sample-granular placement.

This module is deliberately data-only.  It records the audited contract used
by the original DOS 1.3 data set and lets the UI keep manual coverage available
for renamed/custom engines without confusing it with the verified default.
"""

# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ENGINE_AUDIT_ID = "original-dos-pop-1.3"
ENGINE_AUDIT_LABEL = "Original DOS 1.3 engine (automatic)"
PHASE_POLICY_ENGINE = "original-dos-engine"
PHASE_POLICY_MANUAL = "manual"
PHASE_POLICY_LABELS = {
    PHASE_POLICY_ENGINE: ENGINE_AUDIT_LABEL,
    PHASE_POLICY_MANUAL: "Manual / custom executable",
}


@dataclass(frozen=True)
class EnginePhaseUsage:
    """Verified phase requirements for one standard DAT image record."""

    archive_family: str
    resource_id: int
    required_phases: tuple[int, ...]
    category: str
    summary: str
    placement: str
    evidence: str
    used: bool = True

    @property
    def phase_label(self) -> str:
        return "/".join(f"P{phase}" for phase in self.required_phases)

    def to_manifest_dict(self) -> dict:
        return {
            "audit": ENGINE_AUDIT_ID,
            "archive_family": self.archive_family,
            "resource_id": self.resource_id,
            "used_by_original_engine": self.used,
            "required_phases_at_global_bias_0": list(self.required_phases),
            "category": self.category,
            "summary": self.summary,
            "placement": self.placement,
            "evidence": self.evidence,
        }


STANDARD_ARCHIVES = (
    "CDUNGEON.DAT",
    "CPALACE.DAT",
    "FAT.DAT",
    "GUARD.DAT",
    "KID.DAT",
    "PRINCE.DAT",
    "PV.DAT",
    "SHADOW.DAT",
    "SKEL.DAT",
    "TITLE.DAT",
    "VIZIER.DAT",
)


def archive_family_for_name(name: str) -> str | None:
    """Return a standard graphics family for an original or suffixed DAT name."""

    basename = Path(name).name.upper()
    stem = basename[:-4] if basename.endswith(".DAT") else basename
    for archive in sorted(STANDARD_ARCHIVES, key=len, reverse=True):
        canonical_stem = archive[:-4]
        if stem == canonical_stem or any(
            stem.startswith(canonical_stem + separator)
            for separator in ("_", "-", " ")
        ):
            return archive
    return None


def _usage(
    archive: str,
    resource_id: int,
    phases: tuple[int, ...],
    category: str,
    summary: str,
    placement: str,
    evidence: str,
    *,
    used: bool = True,
) -> EnginePhaseUsage:
    return EnginePhaseUsage(
        archive,
        resource_id,
        phases,
        category,
        summary,
        placement,
        evidence,
        used,
    )


# Exact cinematic results produced by research/phase_audit.py from the original
# sequence bytes, frame tables, final 320/280 X transform, shipped image widths,
# and every original scripted scene.
_PV_BOTH = frozenset(
    {
        801,
        802,
        803,
        804,
        808,
        *range(851, 860),
    }
)
_PV_P0 = frozenset(
    {
        805,
        806,
        809,
        810,
        811,
        813,
        814,
        864,
        865,
        867,
        869,
        874,
        875,
        876,
        878,
        879,
        881,
        886,
        887,
        888,
        903,
        904,
        906,
        908,
        909,
        911,
        914,
        915,
        916,
        917,
        918,
        919,
        920,
        921,
        922,
        923,
        925,
        927,
        928,
        929,
        *range(951, 963),
        981,
    }
)
_PV_P2 = frozenset(
    {
        807,
        812,
        815,
        816,
        817,
        860,
        861,
        862,
        863,
        866,
        868,
        870,
        871,
        872,
        873,
        877,
        880,
        882,
        883,
        884,
        885,
        901,
        905,
        907,
        910,
        912,
        913,
        924,
        926,
        930,
    }
)
_PV_UNUSED = frozenset({902})


# Logical environment image numbers referenced by the original room renderer.
# A raw base-bank record is 200 + image number.  An optional replacement is
# 1200 + image number, but load_more_opt_graf() loads only the listed ranges.
_ENVIRONMENT_USED_IMAGE_IDS = frozenset(
    {
        *range(1, 7),
        *range(9, 14),
        *range(30, 76),
        77,
        78,
        *range(80, 152),
    }
)
_OPTIONAL_LOADED_IMAGE_IDS = frozenset(
    {
        *range(1, 14),
        30,
        31,
        *range(75, 84),
        *range(86, 92),
        *range(101, 124),
        *range(127, 144),
    }
)


def usage_for_archive_resource(
    archive_name: str,
    resource_id: int,
) -> EnginePhaseUsage | None:
    """Return the audited original-engine contract, or ``None`` if unknown.

    Phase names are normalized to a P0 screen origin.  A global bias shifts all
    listed phases together but does not increase the number of required slots.
    """

    archive = archive_family_for_name(archive_name)
    resource_id = int(resource_id)
    if archive is None:
        return None

    if archive in ("CDUNGEON.DAT", "CPALACE.DAT"):
        logical_id: int | None = None
        loaded = False
        if 201 <= resource_id <= 351:
            logical_id = resource_id - 200
            loaded = logical_id in _ENVIRONMENT_USED_IMAGE_IDS
        elif 1201 <= resource_id <= 1351:
            logical_id = resource_id - 1200
            loaded = (
                logical_id in _ENVIRONMENT_USED_IMAGE_IDS
                and logical_id in _OPTIONAL_LOADED_IMAGE_IDS
            )
        if logical_id is not None:
            if not loaded:
                return _usage(
                    archive,
                    resource_id,
                    (0,),
                    "unused environment slot",
                    "The original renderer never loads and draws this environment image slot.",
                    "No original placement; P0 is retained only as a compatibility editing slot.",
                    "seg008 tile_table and special frame arrays; seg000 load_more_opt_graf ranges.",
                    used=False,
                )
            return _usage(
                archive,
                resource_id,
                (0,),
                "room tile component",
                "Fixed room artwork; the original CGA renderer reaches P0 only.",
                "X = 8*xh + xl, with xh based on 4*column and every CGA bitmap xl even; room columns begin at 0,32,...,288.",
                "seg008 tile_table and draw_tile* / add_backtable / add_foretable; CGA skips wall_pattern decal offsets.",
            )
        if 361 <= resource_id <= 364:
            return _usage(
                archive,
                resource_id,
                (0,),
                "room wall component",
                "Fixed wall artwork; every original CGA wall placement reaches P0 only.",
                "Wall components use X = 8*xh + xl with tile xh based on 4*column and even xl; CGA skips the VGA/EGA random wall-pattern pass.",
                "seg008 draw_tile_topright/right/bottom/fore and wall_pattern guard.",
            )
        return None

    if archive == "PRINCE.DAT":
        if 151 <= resource_id <= 159:
            return _usage(
                archive,
                resource_id,
                (0, 2),
                "shared animated flame",
                "The same flame frame is P0 in gameplay and P2 in princess-room cinematics.",
                "Gameplay X = 32*column + 8 (even); cinematic torches are X=93 and X=211 (odd).",
                "seg008 draw_tile_anim_right; seg001 princess_room_torch and princess_torch_pos_xh/xl.",
            )
        if 160 <= resource_id <= 161:
            return _usage(
                archive,
                resource_id,
                (0,),
                "floor sword",
                "Sword lying on a floor is tile-aligned at P0.",
                "X = 32*column; chtab 1 bypasses actor X scaling and flipping.",
                "seg008 draw_tile_anim, tiles_22_sword.",
            )
        if 162 <= resource_id <= 165:
            return _usage(
                archive,
                resource_id,
                (0,),
                "potion bottle",
                "Dungeon/palace potion bottles are fixed at P0.",
                "X = 8*(4*column + 2) + 6 = 32*column + 22 (even).",
                "seg008 draw_tile_fore, tiles_10_potion.",
            )
        if 166 <= resource_id <= 173:
            return _usage(
                archive,
                resource_id,
                (2,),
                "potion bubble/mask",
                "Potion bubble frames and their mask are fixed at P2.",
                "X = 8*(4*column + 3) + 1 = 32*column + 25 (odd).",
                "seg008 draw_tile_anim, potion_fram_bubb and bubble mask image 23.",
            )
        if 701 <= resource_id <= 734:
            return _usage(
                archive,
                resource_id,
                (0, 2),
                "moving sword sprite",
                "A carried/fighting sword follows an actor and reaches both X parities.",
                "Actor X is converted to final 320-column X, then the sword-frame offset is applied; one 320-column step toggles P0/P2.",
                "seg006 add_sword_to_objtable and sword_tbl; seg008 draw_mid.",
            )
        return None

    if archive == "KID.DAT":
        if 401 <= resource_id <= 616:
            return _usage(
                archive,
                resource_id,
                (0, 2),
                "moving Kid/mouse frame",
                "Player and mouse frames can land on either 320-column X parity.",
                "Final X = trunc(((2*(Char.x +/- frame.dx)-116)+flag)*320/280), with image-width subtraction after a right-facing flip.",
                "seg006 frame_table_kid; seg008 load_frame_to_obj and draw_mid; gameplay and cinematic sequences.",
            )
        if resource_id in (617, 618):
            return _usage(
                archive,
                resource_id,
                (0, 2),
                "Kid hit-point icon",
                "Successive hit points alternate between P0 and P2.",
                "X = 7*hit_point_index, so X parity alternates.",
                "seg000 draw_kid_hp.",
            )
        if resource_id == 619:
            return _usage(
                archive,
                resource_id,
                (0, 2),
                "moving Kid hurt splash",
                "The hurt splash is actor-relative and reaches both X parities.",
                "Final actor X plus a direction-aware 5-unit offset.",
                "seg006 draw_hurt_splash; seg008 draw_objtable_item.",
            )
        return None

    if archive in ("GUARD.DAT", "FAT.DAT", "SKEL.DAT", "VIZIER.DAT", "SHADOW.DAT"):
        if resource_id == 776:
            return _usage(
                archive,
                resource_id,
                (0,),
                "unused guard-table slot",
                "Image index 25 has no reference in the original guard frame table.",
                "No original draw placement; P0 is retained only as a compatibility editing slot.",
                "seg006 frame_tbl_guard contains image indices 2-24 and 26-33, but not 25.",
                used=False,
            )
        if 751 <= resource_id <= 784:
            if archive == "SHADOW.DAT" and resource_id >= 753:
                summary = (
                    "Shadow artwork needs both slots: each visible frame is drawn at X and X+1, "
                    "in addition to ordinary movement."
                )
                placement = "Two passes use final 320-column X and X+1 (OR then XOR), guaranteeing both P0 and P2."
                evidence = "seg008 draw_objtable_item shadow branch and draw_mid."
            elif resource_id == 751:
                summary = "Guard hit-point positions reach both P0 and P2."
                placement = "X = 314 - 7*hit_point_index, so X parity alternates."
                evidence = "seg000 draw_guard_hp."
            elif resource_id == 752:
                summary = "The guard-family hurt splash is actor-relative and reaches both X parities."
                placement = "Final actor X plus a direction-aware offset."
                evidence = "seg006 draw_hurt_splash; seg008 draw_objtable_item."
            else:
                summary = "A moving guard-family frame can land on either 320-column X parity."
                placement = "Final actor X uses the 320/280 transform and post-flip image-width subtraction."
                evidence = "seg006 frame_tbl_guard; seg008 load_frame_to_obj and draw_mid."
            return _usage(
                archive,
                resource_id,
                (0, 2),
                "moving guard-family graphic",
                summary,
                placement,
                evidence,
            )
        return None

    if archive == "PV.DAT":
        if resource_id in _PV_BOTH:
            return _usage(
                archive,
                resource_id,
                (0, 2),
                "scripted cinematic actor frame",
                "This exact cinematic record is drawn at both final X parities.",
                "Final X includes scripted Char.x/dx, the 320/280 transform, facing, and post-flip image width.",
                "All original seg001 scenes replayed through original_seqtbl and frame_tbl_cuts by research/phase_audit.py.",
            )
        if resource_id in _PV_P0:
            if resource_id >= 951:
                summary = "Fixed princess-room background, pillar, hourglass, sand, or bed artwork at P0."
                placement = "Fixed even X: 0, 152, 160, or 240 depending on the record."
                evidence = "seg001 load_intro, draw_princess_room_bg, and draw_hourglass."
            else:
                summary = "This exact cinematic actor record is reached only at P0."
                placement = "Every original scripted occurrence has an even final 320-column blit X."
                evidence = "Original seg001 scenes replayed by research/phase_audit.py."
            return _usage(
                archive,
                resource_id,
                (0,),
                "fixed cinematic graphic",
                summary,
                placement,
                evidence,
            )
        if resource_id in _PV_P2:
            return _usage(
                archive,
                resource_id,
                (2,),
                "fixed cinematic actor frame",
                "This exact cinematic record is reached only at P2.",
                "Every original scripted occurrence has an odd final 320-column blit X.",
                "All original seg001 scenes replayed through original_seqtbl and frame_tbl_cuts by research/phase_audit.py.",
            )
        if resource_id in _PV_UNUSED:
            return _usage(
                archive,
                resource_id,
                (0,),
                "unused cinematic placeholder",
                "The 1x1 PV2 image index 1 has no frame-table reference.",
                "No original draw placement; P0 is retained only as a compatibility editing slot.",
                "seg006 frame_tbl_cuts PV2 image indices skip index 1.",
                used=False,
            )
        return None

    if archive == "TITLE.DAT" and (
        41 <= resource_id <= 45 or 51 <= resource_id <= 55
    ):
        return _usage(
            archive,
            resource_id,
            (0,),
            "fixed title/story graphic",
            "Title, story, credit, and Hall-of-Fame artwork is fixed at P0.",
            "All configured X positions are even: 0, 24, 48, or 96.",
            "data.h full_image table; seg000 draw_full_image and show_title; seg001 ending screens.",
        )

    return None


def shifted_runtime_phases(
    phases_at_bias_zero: tuple[int, ...], global_phase_bias: int
) -> tuple[int, ...]:
    """Shift an audited normalized phase set by one installation's bias."""

    if global_phase_bias not in (0, 1, 2, 3):
        raise ValueError("Global carrier bias must be between 0 and 3.")
    return tuple(sorted({(phase + global_phase_bias) & 3 for phase in phases_at_bias_zero}))
