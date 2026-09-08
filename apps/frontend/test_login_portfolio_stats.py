"""The sign-in strip counts schools against one portfolio.

THE DEFECT THIS FIXES (owner, 2026-09-07)

"From the login page should have schools reached, schools visited, Schools
trained, and SSA Completed out of the total portfolio in the system and should
fetch from the DB."

The strip used to mix four different kinds of number — a school count, an
activity count and two percentages — so nothing on it could be read against
anything else on it. All four are now shares of the SAME denominator: every
school the programme currently operates in.

THE ONE THAT IS EASY TO GET WRONG

Schools trained. A third of TRAINING_TYPES is cluster training, which names a
CLUSTER and records who attended in `attended_school_ids` — its `school` field
is null. Counting the foreign key alone returns a plausible, quiet undercount,
so the test below trains a school only through cluster attendance and expects
it to be counted.
"""

from datetime import timedelta

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.activities.models import Activity
from apps.core.enums import ActivityType, VerificationStatus
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord


# A per-process cache, so this suite writes nothing to the Redis the dev server
# reads. Its four-school fixture was being cached as the real sign-in page's
# figures — "0 of 4" on /login for five minutes after every run — and its
# `cache.clear()` was signing every dev session out (2026-09-07).
@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "login-portfolio-stats",
        }
    }
)
class LoginPortfolioStatsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        region = Region.objects.create(name="Central", code="C")
        cls.district = District.objects.create(name="Wakiso", region=region)
        cls.schools = [
            School.objects.create(
                school_id=f"LOGIN-STAT-{n}",
                name=f"School {n}",
                region=region,
                district=cls.district,
                operational_status="active",
            )
            for n in range(4)
        ]
        # A closed school is neither reached nor part of the portfolio to
        # reach: it leaves both halves of every fraction.
        cls.closed = School.objects.create(
            school_id="LOGIN-STAT-CLOSED",
            name="Closed School",
            region=region,
            district=cls.district,
            operational_status="closed",
        )

    def setUp(self):
        cache.clear()

    def _activity(self, *, school=None, kind, attended=None):
        return Activity.objects.create(
            activity_type=kind,
            status="completed",
            fy=self.fy,
            quarter="Q1",
            scheduled_date=timezone.now() - timedelta(days=1),
            school=school,
            attended_school_ids=attended or [],
        )

    def _stats(self):
        from apps.frontend.views.auth_views import _login_stats

        return _login_stats()

    def test_every_figure_is_a_share_of_the_operating_portfolio(self):
        stats = self._stats()
        # Four active schools; the closed one is not in the denominator.
        self.assertEqual(stats["stat_portfolio"], "4")
        for key in (
            "stat_schools_reached",
            "stat_schools_visited",
            "stat_schools_trained",
            "stat_ssa_completed",
        ):
            self.assertEqual(stats[key], "0")

    def test_a_visit_counts_its_school_once_however_many_visits(self):
        self._activity(school=self.schools[0], kind=ActivityType.SCHOOL_VISIT)
        self._activity(school=self.schools[0], kind=ActivityType.COACHING_VISIT)
        self._activity(school=self.schools[1], kind=ActivityType.SCHOOL_VISIT)

        stats = self._stats()
        self.assertEqual(stats["stat_schools_visited"], "2")
        # A visit is also completed work, so it reaches the school too.
        self.assertEqual(stats["stat_schools_reached"], "2")
        self.assertEqual(stats["stat_schools_trained"], "0")

    def test_a_cluster_training_counts_the_schools_that_attended_it(self):
        """The whole reason this is not a `school_id` count."""

        self._activity(
            kind=ActivityType.CLUSTER_TRAINING,
            attended=[self.schools[0].id, self.schools[1].id, self.schools[2].id],
        )
        stats = self._stats()
        self.assertEqual(stats["stat_schools_trained"], "3")
        self.assertEqual(stats["stat_schools_reached"], "3")

    def test_work_at_a_closed_school_counts_for_nothing(self):
        self._activity(school=self.closed, kind=ActivityType.SCHOOL_VISIT)
        self._activity(kind=ActivityType.CLUSTER_TRAINING, attended=[self.closed.id])
        stats = self._stats()
        self.assertEqual(stats["stat_portfolio"], "4")
        self.assertEqual(stats["stat_schools_visited"], "0")
        self.assertEqual(stats["stat_schools_trained"], "0")

    def test_uncompleted_work_reaches_nobody(self):
        Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT,
            status="planned",
            fy=self.fy,
            quarter="Q1",
            scheduled_date=timezone.now() + timedelta(days=3),
            school=self.schools[0],
        )
        self.assertEqual(self._stats()["stat_schools_visited"], "0")

    def test_only_a_confirmed_ssa_is_a_completed_one(self):
        SsaRecord.objects.create(
            school=self.schools[0],
            date_of_ssa=timezone.now(),
            fy=self.fy,
            quarter="Q1",
            uploaded_by="tester",
            verification_status=VerificationStatus.CONFIRMED,
        )
        SsaRecord.objects.create(
            school=self.schools[1],
            date_of_ssa=timezone.now(),
            fy=self.fy,
            quarter="Q1",
            uploaded_by="tester",
            verification_status=VerificationStatus.PENDING,
        )
        self.assertEqual(self._stats()["stat_ssa_completed"], "1")

    def test_the_strip_renders_the_four_metrics_against_the_portfolio(self):
        self._activity(school=self.schools[0], kind=ActivityType.SCHOOL_VISIT)
        html = self.client.get("/login").content.decode()
        for label in (
            "Schools reached",
            "Schools visited",
            "Schools trained",
            "SSA completed",
        ):
            self.assertIn(label, html)
        # The denominator is said once per metric, quietly, beside the count.
        self.assertEqual(html.count('data-component="context-metric"'), 4)
        self.assertEqual(html.count('>of 4 ·'), 4)
        self.assertNotIn("Field visits", html)
        self.assertNotIn("Target progress", html)
