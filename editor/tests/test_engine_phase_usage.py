from __future__ import annotations

import unittest

from engine_phase_usage import (
    PHASE_POLICY_ENGINE,
    archive_family_for_name,
    shifted_runtime_phases,
    usage_for_archive_resource,
)


class EnginePhaseUsageTests(unittest.TestCase):
    def phases(self, archive: str, resource_id: int) -> tuple[int, ...]:
        usage = usage_for_archive_resource(archive, resource_id)
        self.assertIsNotNone(usage)
        assert usage is not None
        return usage.required_phases

    def test_standard_and_suffixed_archive_names_resolve(self) -> None:
        self.assertEqual(archive_family_for_name("kid.dat"), "KID.DAT")
        self.assertEqual(
            archive_family_for_name("CDUNGEON_COMPOSITE.DAT"),
            "CDUNGEON.DAT",
        )
        self.assertIsNone(archive_family_for_name("MYKID.DAT"))

    def test_room_artwork_uses_only_normalized_p0(self) -> None:
        for archive, resource in (
            ("CDUNGEON.DAT", 232),
            ("CPALACE.DAT", 344),
            ("CDUNGEON.DAT", 361),
            ("CPALACE.DAT", 1301),
        ):
            with self.subTest(archive=archive, resource=resource):
                self.assertEqual(self.phases(archive, resource), (0,))

    def test_unreferenced_environment_slots_are_identified_as_unused(self) -> None:
        for resource in (207, 276, 1276, 1299):
            with self.subTest(resource=resource):
                usage = usage_for_archive_resource("CDUNGEON.DAT", resource)
                self.assertIsNotNone(usage)
                assert usage is not None
                self.assertFalse(usage.used)
                self.assertEqual(usage.required_phases, (0,))

    def test_prince_shared_and_fixed_exceptions_are_exact(self) -> None:
        self.assertEqual(self.phases("PRINCE.DAT", 151), (0, 2))
        self.assertEqual(self.phases("PRINCE.DAT", 160), (0,))
        self.assertEqual(self.phases("PRINCE.DAT", 164), (0,))
        self.assertEqual(self.phases("PRINCE.DAT", 166), (2,))
        self.assertEqual(self.phases("PRINCE.DAT", 173), (2,))
        self.assertEqual(self.phases("PRINCE.DAT", 734), (0, 2))

    def test_moving_sprite_and_hp_families_use_both_parities(self) -> None:
        for archive, resource in (
            ("KID.DAT", 401),
            ("KID.DAT", 617),
            ("KID.DAT", 619),
            ("GUARD.DAT", 751),
            ("FAT.DAT", 752),
            ("SKEL.DAT", 753),
            ("VIZIER.DAT", 784),
            ("SHADOW.DAT", 777),
        ):
            with self.subTest(archive=archive, resource=resource):
                self.assertEqual(self.phases(archive, resource), (0, 2))

    def test_unused_guard_slot_and_pv_placeholder_keep_one_compatibility_slot(self) -> None:
        for archive, resource in (("GUARD.DAT", 776), ("PV.DAT", 902)):
            usage = usage_for_archive_resource(archive, resource)
            self.assertIsNotNone(usage)
            assert usage is not None
            self.assertFalse(usage.used)
            self.assertEqual(usage.required_phases, (0,))

    def test_every_shipped_pv_image_has_an_exact_contract(self) -> None:
        resources = (
            *range(801, 818),
            *range(851, 889),
            *range(901, 931),
            *range(951, 963),
            981,
        )
        for resource in resources:
            with self.subTest(resource=resource):
                usage = usage_for_archive_resource("PV.DAT", resource)
                self.assertIsNotNone(usage)
                assert usage is not None
                self.assertIn(usage.required_phases, ((0,), (2,), (0, 2)))

    def test_title_is_fixed_and_unknown_custom_records_remain_manual(self) -> None:
        self.assertEqual(self.phases("TITLE.DAT", 55), (0,))
        self.assertIsNone(usage_for_archive_resource("KID.DAT", 20))
        self.assertIsNone(usage_for_archive_resource("UNKNOWN.DAT", 401))

    def test_global_bias_relabels_but_does_not_add_alignments(self) -> None:
        self.assertEqual(shifted_runtime_phases((0, 2), 0), (0, 2))
        self.assertEqual(shifted_runtime_phases((0, 2), 1), (1, 3))
        self.assertEqual(shifted_runtime_phases((2,), 3), (1,))
        self.assertEqual(PHASE_POLICY_ENGINE, "original-dos-engine")


if __name__ == "__main__":
    unittest.main()
