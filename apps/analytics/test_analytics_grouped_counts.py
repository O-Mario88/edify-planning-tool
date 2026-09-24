"""The /analytics grouped counts must group by their key alone.

A scoped activity queryset is `.distinct()` (apps.hr.contribution_scope.
scope_activities: the country, Programme Lead team and staff paths). Activity
is ordered by `-created_at`, and on a DISTINCT query Django adds the ordering
column to the SELECT list, and with it to the GROUP BY. A
`.values("planned_month").annotate(Count(...))` then returned one row per
(month, creation time), and folding those rows into a dict keyed by month
kept only one creation-time slice of each month. On the 50,000-school estate
the FY2026 month query returned 272 rows instead of one per month, and the
Country Director's Target Achievement by District read Mukono as 1 planned
and 0 achieved instead of 1,009 and 72.

Every activity below is created at a different moment, as real work is, so
each grouped figure is checked against the true count.
"""

from __future__ import annotations

import datetime
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.analytics.analytics_dashboard_service import AnalyticsDashboardService
from apps.clusters.models import Cluster
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()
FY = "2026"


class GroupedCountsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Grouped Central", country="Uganda")
        cls.d1 = District.objects.create(
            name="Grouped D1", region=region, district_type="primary"
        )
        cls.d2 = District.objects.create(
            name="Grouped D2", region=region, district_type="primary"
        )
        cls.cluster = Cluster.objects.create(
            name="Grouped Cluster", region=region, district=cls.d1
        )
        s1 = School.objects.create(
            school_id="GC-1",
            name="Grouped One",
            region=region,
            district=cls.d1,
            cluster_id=cls.cluster.id,
        )
        s2 = School.objects.create(
            school_id="GC-2", name="Grouped Two", region=region, district=cls.d2
        )
        cls.region = region

        def staff(email, role):
            user = User.objects.create_user(
                email=email,
                name=email.split("@")[0].title(),
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            return user, StaffProfile.objects.create(
                user=user, title=role, country="Uganda"
            )

        cls.cd, _ = staff("gc-cd@t.org", "CountryDirector")
        cls.pl, pl_sp = staff("gc-pl@t.org", "Program Lead")
        _, cceo_sp = staff("gc-cceo@t.org", "CCEO")
        StaffSupervisorAssignment.objects.create(supervisor=pl_sp, supervisee=cceo_sp)
        for s in (s1, s2):
            StaffSchoolAssignment.objects.create(staff=cceo_sp, school_id=s.id)

        # April work at two schools in two districts, created over a fortnight.
        work = [
            (s1, "school_visit", "ia_verified"),
            (s1, "school_visit", "ia_verified"),
            (s1, "school_visit", "closed"),
            (s1, "school_visit", "scheduled"),
            (s1, "cluster_training", "ia_verified"),
            (s1, "cluster_training", "scheduled"),
            (s2, "school_visit", "accountant_confirmed"),
            (s2, "school_visit", "scheduled"),
            (s2, "school_visit", "scheduled"),
        ]
        first = timezone.make_aware(datetime.datetime(2026, 3, 20, 8))
        for i, (school, atype, status) in enumerate(work):
            day = date(2026, 4, 6 + i)
            activity = Activity.objects.create(
                school=school,
                activity_type=atype,
                delivery_type="staff",
                status=status,
                responsible_staff_id=cceo_sp.id,
                fy=FY,
                quarter="Q3",
                planned_date=day,
                planned_month=4,
                scheduled_date=timezone.make_aware(
                    datetime.datetime(day.year, day.month, day.day, 9)
                ),
            )
            Activity.objects.filter(id=activity.id).update(
                created_at=first + datetime.timedelta(days=i, minutes=7 * i)
            )
        assert Activity.objects.values("created_at").distinct().count() == len(
            work
        ), "every activity must carry its own creation time"

    def data(self, principal):
        return AnalyticsDashboardService.get_analytics_data(principal, {"fy": FY})

    def test_the_performance_overview_counts_every_activity_in_the_month(self):
        for principal in (self.pl, self.cd):
            with self.subTest(role=principal.active_role):
                chart = self.data(principal)["performance_overview"]
                april = chart["labels"].index("Apr")
                self.assertEqual(chart["planned"][april], 9)
                self.assertEqual(chart["achieved"][april], 5)
                self.assertEqual(chart["pct"][april], 56)
                self.assertEqual(sum(chart["planned"]), 9)

    def test_target_by_district_counts_every_activity_in_the_district(self):
        for principal in (self.pl, self.cd):
            with self.subTest(role=principal.active_role):
                rows = {
                    row["id"]: row for row in self.data(principal)["target_by_district"]
                }
                self.assertEqual(
                    (rows[self.d1.id]["planned"], rows[self.d1.id]["achieved"]), (6, 4)
                )
                self.assertEqual(
                    (rows[self.d2.id]["planned"], rows[self.d2.id]["achieved"]), (3, 1)
                )
                self.assertEqual(rows[self.d1.id]["pct"], 67)
                self.assertEqual(rows[self.d2.id]["pct"], 33)
                # School reach is one school per district, whichever slice.
                for district in (self.d1, self.d2):
                    self.assertEqual(rows[district.id]["schools_planned"], 1)
                    self.assertEqual(rows[district.id]["schools_achieved"], 1)

    def test_regional_and_cluster_rows_count_every_activity(self):
        for principal in (self.pl, self.cd):
            with self.subTest(role=principal.active_role):
                data = self.data(principal)
                region = next(
                    r for r in data["regional_performance"] if r["id"] == self.region.id
                )
                self.assertEqual(region["completed"], 5)
                self.assertEqual(region["pct"], 56)
                cluster = next(
                    c for c in data["cluster_performance"] if c["id"] == self.cluster.id
                )
                self.assertEqual((cluster["trainings"], cluster["visits"]), (2, 4))
