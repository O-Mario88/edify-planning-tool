from django.test import TestCase
from apps.activities.cluster_attendance import (
    set_invited_schools,
    expected_participants,
)
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class InvitationDrivesTheHeadCountTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="R")
        self.district = District.objects.create(
            name="D", region=self.region, district_type="primary"
        )
        self.sub = SubCounty.objects.create(name="S", district=self.district)
        self.cluster = Cluster.objects.create(
            name="C", district=self.district, region=self.region, status="active"
        )
        self.schools = []
        for i in range(3):
            s = School.objects.create(
                school_id=f"S{i}",
                name=f"School {i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub,
                enrollment=100,
            )
            School.objects.filter(pk=s.pk).update(cluster_id=self.cluster.id)
            s.refresh_from_db()
            self.schools.append(s)
        self.activity = Activity.objects.create(
            activity_type="cluster_training",
            cluster_id=self.cluster.id,
            fy="2026",
            status="scheduled",
            teachers_per_school=2,
            leaders_per_school=1,
            other_per_school=0,
        )

    def test_unticking_a_school_lowers_the_priced_head_count(self):
        set_invited_schools(self.activity, [s.id for s in self.schools])
        self.activity.refresh_from_db()
        self.assertEqual(expected_participants(self.activity), 9)
        self.assertEqual(self.activity.expected_participants, 9)

        # Untick one school — the figure costing prices must follow.
        set_invited_schools(self.activity, [s.id for s in self.schools[:2]])
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.expected_participants, 6)

    def test_the_stored_total_never_disagrees_with_the_rows(self):
        set_invited_schools(self.activity, [self.schools[0].id])
        self.activity.refresh_from_db()
        self.assertEqual(
            self.activity.expected_participants,
            expected_participants(self.activity),
        )
