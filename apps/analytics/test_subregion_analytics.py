from django.test import TestCase

from apps.analytics.subregion_analytics import subregion_performance
from apps.geography.models import District, Region, SubRegion
from apps.geography.subregions import SUBREGIONS, check, district_to_subregion, sync


class SubRegionMappingTest(TestCase):
    """The mapping has to stay a clean partition of the 135 UBOS districts."""

    def test_mapping_is_a_partition_of_the_ubos_districts(self):
        check()  # raises if a district is doubled or the count drifts
        flat = district_to_subregion()
        self.assertEqual(len(flat), 135)
        self.assertEqual(len(SUBREGIONS), 10)

    def test_check_rejects_a_district_in_two_sub_regions(self):
        """A guard that cannot fail is not a guard."""
        original = SUBREGIONS["Acholi"]
        try:
            SUBREGIONS["Acholi"] = (original[0], original[1] + ["Kampala"])
            with self.assertRaises(ValueError) as ctx:
                check()
            self.assertIn("Kampala", str(ctx.exception))
        finally:
            SUBREGIONS["Acholi"] = original

    def test_every_sub_region_sits_wholly_inside_one_region(self):
        for name, (parent, districts) in SUBREGIONS.items():
            self.assertTrue(districts, f"{name} has no districts")
            self.assertIn(
                parent, {"Central", "Eastern", "Northern", "Western"}, name
            )


class SubRegionSyncTest(TestCase):
    def setUp(self):
        self.northern = Region.objects.create(name="Northern Region")
        for d in ("Gulu", "Kitgum", "Moroto"):
            District.objects.create(name=d, region=self.northern)

    def test_sync_attaches_districts_and_is_idempotent(self):
        first = sync()
        self.assertEqual(first["districts"], 3)
        self.assertEqual(
            District.objects.get(name="Gulu").sub_region.name, "Acholi"
        )
        self.assertEqual(
            District.objects.get(name="Moroto").sub_region.name, "Karamoja"
        )
        # Running twice must not duplicate sub-regions or change assignments.
        before = SubRegion.objects.count()
        second = sync()
        self.assertEqual(SubRegion.objects.count(), before)
        self.assertEqual(second["districts"], 3)

    def test_unknown_district_is_left_unassigned_not_guessed(self):
        District.objects.create(name="SMOKETEST District", region=self.northern)
        stats = sync()
        self.assertEqual(stats["unmatched"], 1)
        self.assertIsNone(
            District.objects.get(name="SMOKETEST District").sub_region
        )

    def test_sync_is_safe_before_geography_is_bootstrapped(self):
        """Migrations run before any geography exists; sync must not explode."""
        District.objects.all().delete()
        Region.objects.all().delete()
        SubRegion.objects.all().delete()
        stats = sync()
        self.assertEqual(stats, {
            "subregions": 0, "districts": 0, "unmatched": 0, "no_region": 0
        })


class SubRegionAnalyticsTest(TestCase):
    """The roll-up must weight by evidence and keep 'absent' distinct from 0."""

    def setUp(self):
        from apps.schools.models import School

        self.northern = Region.objects.create(name="Northern Region")
        self.gulu = District.objects.create(name="Gulu", region=self.northern)
        self.kitgum = District.objects.create(name="Kitgum", region=self.northern)
        self.moroto = District.objects.create(name="Moroto", region=self.northern)
        sync()
        # school_id is unique and has no default, so each fixture needs its own
        for i in range(3):
            School.objects.create(
                school_id=f"GULU-{i}",
                name=f"Gulu School {i}",
                region=self.northern,
                district=self.gulu,
            )
        School.objects.create(
            school_id="KIT-1",
            name="Kitgum School",
            region=self.northern,
            district=self.kitgum,
        )

    def _ssa(self, school, score, status="confirmed", fy="FY2026"):
        import datetime

        from apps.ssa.models import SsaRecord

        return SsaRecord.objects.create(
            school=school,
            fy=fy,
            average_score=score,
            verification_status=status,
            date_of_ssa=datetime.date(2026, 3, 1),
        )

    def test_school_counts_roll_up_from_district_to_sub_region(self):
        result = subregion_performance()
        acholi = next(s for s in result["subregions"] if s["name"] == "Acholi")
        self.assertEqual(acholi["schools"], 4)      # 3 Gulu + 1 Kitgum
        self.assertEqual(acholi["districts"], 2)

    def test_sub_region_without_confirmed_ssa_reports_none_not_zero(self):
        """A dash and a zero mean different things to a reader."""
        result = subregion_performance()
        karamoja = next(s for s in result["subregions"] if s["name"] == "Karamoja")
        self.assertEqual(karamoja["districts"], 1)
        self.assertIsNone(
            karamoja["ssa_avg"],
            "no confirmed assessment must stay absent, never collapse to 0.0",
        )

    def test_unconfirmed_ssa_is_excluded(self):
        from apps.schools.models import School

        school = School.objects.get(name="Kitgum School")
        self._ssa(school, 9.0, status="pending")
        result = subregion_performance()
        acholi = next(s for s in result["subregions"] if s["name"] == "Acholi")
        self.assertIsNone(acholi["ssa_avg"])
        self.assertEqual(acholi["ssa_n"], 0)

    def test_ssa_average_is_weighted_by_assessments_behind_each_district(self):
        """Three 2.0s in one district must outweigh a single 8.0 in another.

        An unweighted mean of district means gives (2.0 + 8.0) / 2 = 5.0, which
        lets one assessment count as much as three.
        """
        from apps.schools.models import School

        for s in School.objects.filter(district=self.gulu):
            self._ssa(s, 2.0)
        self._ssa(School.objects.get(name="Kitgum School"), 8.0)

        result = subregion_performance()
        acholi = next(s for s in result["subregions"] if s["name"] == "Acholi")
        self.assertEqual(acholi["ssa_n"], 4)
        # (2+2+2+8) / 4 = 3.5, not 5.0
        self.assertEqual(acholi["ssa_avg"], 3.5)

    def test_region_roll_up_agrees_with_its_sub_regions(self):
        """Sub-regions partition the region, so the totals must reconcile."""
        result = subregion_performance()
        northern = next(r for r in result["regions"] if r["name"] == "Northern Region")
        children = [
            s for s in result["subregions"] if s["name"] in {"Acholi", "Karamoja"}
        ]
        self.assertEqual(northern["schools"], sum(c["schools"] for c in children))
        self.assertEqual(northern["districts"], sum(c["districts"] for c in children))

    def test_engine_metadata_names_the_python_stack(self):
        engine = subregion_performance()["engine"]
        self.assertEqual(engine["domain"], "subregion_distribution")
        self.assertIn("pandas", engine["runtime"])
