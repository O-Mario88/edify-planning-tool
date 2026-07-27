import datetime

from django.test import TestCase

from apps.analytics.subcounty_insight import boundary_key, subcounty_insight
from apps.core_schools.models import CorePlan, CoreSchoolProfile
from apps.geography.models import District, Region, SubCounty
from apps.geography.subregions import sync
from apps.schools.models import School
from apps.ssa.models import SsaRecord


class SubCountyInsightTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Mukono", region=self.region)
        sync()
        self.nama = SubCounty.objects.create(
            name="Nama",
            district=self.district,
            pcode="108107",
        )
        self.nakisunga = SubCounty.objects.create(
            name="Nakisunga",
            district=self.district,
            pcode="108106",
        )
        self.school = School.objects.create(
            school_id="MAP-101",
            name="Map School",
            region=self.region,
            district=self.district,
            sub_county=self.nama,
            school_type="client",
        )

    def _entry(self, result, sub_county):
        key = boundary_key(self.district.name, sub_county.name)
        return next(row for row in result["entries"] if row["key"] == key)

    def test_school_profile_subcounty_change_moves_the_map_pin_aggregate(self):
        before = subcounty_insight()
        self.assertEqual(self._entry(before, self.nama)["schools"], 1)
        self.assertEqual(
            self._entry(before, self.nama)["school_distribution"]["client"],
            1,
        )

        self.school.sub_county = self.nakisunga
        self.school.save()

        after = subcounty_insight()
        self.assertFalse(
            any(
                row["key"] == boundary_key("Mukono", "Nama") for row in after["entries"]
            )
        )
        self.assertEqual(self._entry(after, self.nakisunga)["schools"], 1)

    def test_scope_excludes_other_schools_without_dropping_unassigned_disclosure(self):
        other = School.objects.create(
            school_id="MAP-102",
            name="Other School",
            region=self.region,
            district=self.district,
            sub_county=self.nakisunga,
        )
        School.objects.create(
            school_id="MAP-103",
            name="Unassigned School",
            region=self.region,
            district=self.district,
        )

        result = subcounty_insight(schools=School.objects.filter(pk=self.school.pk))

        self.assertEqual(result["totals"]["assigned_schools"], 1)
        self.assertEqual(result["totals"]["unassigned_schools"], 0)
        self.assertNotIn(
            boundary_key("Mukono", "Nakisunga"),
            {row["key"] for row in result["entries"]},
        )
        self.assertNotEqual(other.pk, self.school.pk)

    def test_unassigned_schools_remain_visible_in_the_district_disclosure(self):
        School.objects.create(
            school_id="MAP-104",
            name="Missing Sub-county",
            region=self.region,
            district=self.district,
        )

        result = subcounty_insight()

        self.assertEqual(
            result["unassigned_by_district"]["Mukono"],
            {
                "schools": 1,
                "school_distribution": {
                    "core": 0,
                    "client": 1,
                    "champion": 0,
                    "core_trained": 0,
                },
            },
        )
        self.assertEqual(result["totals"]["unassigned_schools"], 1)

    def test_confirmed_ssa_is_aggregated_and_absent_is_not_zero(self):
        empty = subcounty_insight()
        self.assertIsNone(self._entry(empty, self.nama)["ssa_avg"])

        SsaRecord.objects.create(
            school=self.school,
            fy="FY2026",
            average_score=7.25,
            verification_status="confirmed",
            date_of_ssa=datetime.date(2026, 3, 1),
        )
        SsaRecord.objects.create(
            school=self.school,
            fy="FY2026",
            average_score=1.0,
            verification_status="pending",
            date_of_ssa=datetime.date(2026, 3, 2),
        )

        entry = self._entry(subcounty_insight("FY2026"), self.nama)
        self.assertEqual(entry["ssa_avg"], 7.25)
        self.assertEqual(entry["ssa_done"], 1)
        self.assertEqual(entry["ssa_total"], 1)

    def test_core_trained_is_a_distinct_completed_core_school_count(self):
        from apps.activities.models import Activity

        self.school.school_type = "core"
        self.school.save(update_fields=["school_type"])
        plan = CorePlan.objects.create(
            id="map-core-plan",
            school_id=self.school.school_id,
            fy="FY2026",
        )
        CoreSchoolProfile.objects.create(
            id="map-core-profile",
            school_id=self.school.school_id,
            core_plan=plan,
            core_start_fy="FY2026",
        )
        for _ in range(2):
            Activity.objects.create(
                school=self.school,
                activity_type="training",
                status="completed",
                fy="FY2026",
            )
        Activity.objects.create(
            school=self.school,
            activity_type="training",
            status="scheduled",
            fy="FY2026",
        )

        distribution = self._entry(
            subcounty_insight("FY2026"),
            self.nama,
        )["school_distribution"]

        self.assertEqual(distribution["core"], 1)
        self.assertEqual(distribution["core_trained"], 1)

    def test_query_count_is_constant_with_subcounty_cardinality(self):
        for index in range(25):
            sub_county = SubCounty.objects.create(
                name=f"Scale {index}",
                district=self.district,
            )
            School.objects.create(
                school_id=f"MAP-SCALE-{index}",
                name=f"Scale School {index}",
                region=self.region,
                district=self.district,
                sub_county=sub_county,
            )

        # Keep an active Core profile in the fixture so this measures the
        # worst-case path, including the unassigned Core-training disclosure.
        plan = CorePlan.objects.create(
            id="query-budget-core-plan",
            school_id=self.school.school_id,
            fy="FY2026",
        )
        CoreSchoolProfile.objects.create(
            id="query-budget-core-profile",
            school_id=self.school.school_id,
            core_plan=plan,
            core_start_fy="FY2026",
        )

        # Eight grouped queries; the count remains independent of the 26
        # sub-counties and schools in this fixture.
        with self.assertNumQueries(8):
            result = subcounty_insight("FY2026")

        self.assertEqual(result["totals"]["assigned_schools"], 26)

    def test_boundary_key_is_case_and_punctuation_stable(self):
        self.assertEqual(
            boundary_key("Madi-Okollo", "Seeta - Namuganga"),
            "MADIOKOLLO::SEETANAMUGANGA",
        )
