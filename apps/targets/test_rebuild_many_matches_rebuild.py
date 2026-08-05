"""Rebuilding a roster must leave the ledger exactly where rebuilding each
person separately would have left it.

`rebuild` runs on ordinary page loads for every person in scope, so a
leadership page re-read the same four source tables once per head — roughly 290
round trips on a Country Director dashboard to answer four questions.
`rebuild_many` reads them once and hands each person's rebuild the rows its own
filters would have returned.

That is only a safe trade if the ledger is byte-identical afterwards, because
this ledger is what target achievement is computed from: a row that gains,
loses or mis-dates credit changes somebody's measured performance. So the
tests below build a roster whose members differ in the ways the grouping could
plausibly get wrong — work owned by staff-profile id rather than user id, a
partner-delivered activity that must never earn personal credit, an
out-of-year assessment, an unapproved story, and a person with no work at all
— then compare the two paths field by field.
"""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord
from apps.targets.models import (
    MonthlyPersonalTarget,
    MostSignificantChangeStory,
    TargetAchievementLedger,
    TargetArea,
)
from apps.targets.my_targets import (
    MyTargetQueryService,
    TargetAchievementService,
    active_target_areas,
    per_user_monthly_series,
)

FY = "2026"


def ledger_snapshot():
    """Everything about the ledger that a downstream number can depend on."""
    return sorted(
        (
            row.user_id,
            row.source_type,
            row.source_id,
            row.area_id,
            row.fy,
            row.activity_date,
            row.credited_month,
            row.credited_quarter,
            row.validation_status,
        )
        for row in TargetAchievementLedger.objects.all()
    )


class RosterFixture:
    """A roster whose members differ in the ways batching could get wrong."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.region = Region.objects.create(name="RM Region")
        cls.district = District.objects.create(name="RM District", region=cls.region)
        cls.school = School.objects.create(
            school_id="RM-1",
            name="RM School",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

        cls.users = []
        for i in range(4):
            user = User.objects.create(
                id=f"rm-user-{i}",
                email=f"rm{i}@edify.org",
                name=f"RM {i}",
                roles=["CCEO"],
                active_role="CCEO",
                is_active=True,
            )
            # `staff_profile_id` is a read-through property, so the profile
            # simply has to exist before the user is first asked for it.
            StaffProfile.objects.create(id=f"rm-sp-{i}", user=user)
            cls.users.append(user)

        visit_type = cls._visit_type()

        # Person 0: work owned by their USER id.
        cls._activity(cls.users[0].id, visit_type, date(2025, 11, 12), "completed")
        # Person 1: the same work owned by their STAFF PROFILE id instead —
        # `_user_ids` accepts either, so the grouping must key on both.
        cls._activity(cls.users[1].staff_profile.id, visit_type, date(2026, 2, 3), "completed")
        # Person 1 also has partner-delivered work, which is Partner
        # Contribution and must never reach a personal ledger.
        cls._activity(
            cls.users[1].staff_profile.id,
            visit_type,
            date(2026, 2, 4),
            "completed",
            delivery_type="partner",
        )
        # Person 2: SSA in the year, SSA outside it, and two stories in
        # different states.
        cls._ssa(cls.users[2].id, datetime(2026, 1, 9, tzinfo=dt_timezone.utc), "confirmed")
        cls._ssa(
            cls.users[2].id,
            datetime(2024, 1, 9, tzinfo=dt_timezone.utc),
            "confirmed",
        )
        MostSignificantChangeStory.objects.create(
            user_id=cls.users[2].id, story_date=date(2026, 3, 2), status="approved"
        )
        MostSignificantChangeStory.objects.create(
            user_id=cls.users[2].id, story_date=date(2026, 3, 9), status="draft"
        )
        # Person 3 has nothing at all — a roster member with no sources must
        # not be dropped from, or added to, the ledger.

        # An explicit monthly target for one person only, so the two target
        # paths (explicit rows vs the annual split) are both exercised and the
        # per-user lookup has to pick the right owner out of the batch.
        visits = TargetArea.objects.filter(key="school_visits").first()
        if visits:
            for month, value in ((2, 7), (5, 3)):
                MonthlyPersonalTarget.objects.create(
                    user_id=cls.users[0].id, fy=FY, area=visits, month_of_fy=month,
                    target=value,
                )

    @classmethod
    def _visit_type(cls):
        from apps.targets.my_targets import AREA_SOURCES

        return AREA_SOURCES["school_visits"][1][0]

    @classmethod
    def _activity(cls, owner_id, activity_type, when, status, delivery_type=""):
        return Activity.objects.create(
            school=cls.school,
            responsible_staff_id=owner_id,
            activity_type=activity_type,
            fy=FY,
            planned_date=when,
            status=status,
            delivery_type=delivery_type,
        )

    @classmethod
    def _ssa(cls, user_id, when, verification_status):
        return SsaRecord.objects.create(
            school=cls.school,
            collected_by_user_id=user_id,
            date_of_ssa=when,
            fy=FY,
            quarter="Q2",
            verification_status=verification_status,
            uploaded_by="tester",
        )

    def setUp(self):
        if not TargetArea.objects.exists():
            self.skipTest("no target areas configured in this database")


class RebuildManyEquivalenceTest(RosterFixture, TestCase):
    def _one_by_one(self):
        TargetAchievementLedger.objects.all().delete()
        for user in self.users:
            TargetAchievementService.rebuild(user, FY)
        return ledger_snapshot()

    def _batched(self):
        TargetAchievementLedger.objects.all().delete()
        TargetAchievementService.rebuild_many(self.users, FY)
        return ledger_snapshot()

    def test_the_two_paths_agree_row_for_row(self):
        self.assertEqual(self._one_by_one(), self._batched())

    def test_the_comparison_is_not_vacuous(self):
        """Guards the guard: if both paths wrote nothing, the test above would
        pass while proving nothing at all."""
        snapshot = self._batched()
        self.assertGreater(len(snapshot), 0)
        self.assertGreaterEqual(
            len({row[0] for row in snapshot}),
            3,
            "the fixture should credit at least three of the four people",
        )

    def test_partner_delivered_work_earns_no_personal_credit(self):
        self._batched()
        credited = set(
            TargetAchievementLedger.objects.filter(
                user_id=self.users[1].id
            ).values_list("source_id", flat=True)
        )
        partner = Activity.objects.get(delivery_type="partner")
        self.assertNotIn(str(partner.id), credited)

    def test_a_second_batched_run_changes_nothing(self):
        """Idempotence is what makes rebuilding on every page load safe."""
        first = self._batched()
        TargetAchievementService.rebuild_many(self.users, FY)
        self.assertEqual(first, ledger_snapshot())

    def test_a_repeated_user_in_the_roster_is_handled_once(self):
        # The ledger snapshot is read before any writes, so the same person
        # appearing twice would otherwise rebuild from a stale view of their
        # own rows.
        TargetAchievementLedger.objects.all().delete()
        TargetAchievementService.rebuild_many(
            [*self.users, self.users[0], self.users[2]], FY
        )
        self.assertEqual(ledger_snapshot(), self._one_by_one())

    SOURCE_TABLES = ("activity", "ssa_record", "mscs_story")

    def _source_reads(self, roster):
        """How many times the source tables are SELECTed for this roster.

        Deliberately counts reads only. Writes scale with how much uncredited
        work the roster has and always will — that is the job. What must not
        scale is the number of times the same four tables are interrogated.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        TargetAchievementLedger.objects.all().delete()
        with CaptureQueriesContext(connection) as cap:
            TargetAchievementService.rebuild_many(roster, FY)
        return [
            q["sql"]
            for q in cap.captured_queries
            if q["sql"].startswith("SELECT")
            and any(f'FROM "{t}"' in q["sql"] for t in self.SOURCE_TABLES)
        ]

    def test_source_reads_do_not_grow_with_roster_size(self):
        one = self._source_reads(self.users[:1])
        four = self._source_reads(self.users)
        self.assertEqual(
            len(four),
            len(one),
            "reading the source tables must cost the same for four people as "
            f"for one; got {len(one)} then {len(four)}",
        )
        self.assertEqual(
            len(one),
            len(self.SOURCE_TABLES),
            "each source table should be read exactly once per rebuild",
        )

    def test_the_unbatched_path_is_what_this_replaced(self):
        """Guards the guard: if `rebuild` had also become constant-cost, the
        test above would pass without `rebuild_many` doing anything."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        TargetAchievementLedger.objects.all().delete()
        with CaptureQueriesContext(connection) as cap:
            for user in self.users:
                TargetAchievementService.rebuild(user, FY)
        per_user = [
            q["sql"]
            for q in cap.captured_queries
            if q["sql"].startswith("SELECT")
            and any(f'FROM "{t}"' in q["sql"] for t in self.SOURCE_TABLES)
        ]
        self.assertEqual(len(per_user), len(self.SOURCE_TABLES) * len(self.users))


class PerUserSeriesBatchingTest(RosterFixture, TestCase):
    """`per_user_monthly_series` reads three tables for a whole roster.

    It used to call `monthly_targets` and `monthly_achievements` per person,
    which is three queries each — 144 on a Country Director dashboard. The
    batch shares its arithmetic with the per-user entry points rather than
    reimplementing it, and these tests hold the two to the same answer.
    """

    def _series_one_by_one(self):
        areas = active_target_areas()
        return {
            u.id: (
                {
                    area.key: list(
                        MyTargetQueryService.monthly_targets(u, FY).get(
                            area.key, [0] * 12
                        )
                    )
                    for area in areas
                },
                {
                    area.key: list(
                        MyTargetQueryService.monthly_achievements(u, FY).get(
                            area.key, [0] * 12
                        )
                    )
                    for area in areas
                },
            )
            for u in self.users
        }

    def test_the_batched_series_matches_the_per_user_series(self):
        TargetAchievementService.rebuild_many(self.users, FY)
        batched = per_user_monthly_series(self.users, FY, areas=active_target_areas())
        self.assertEqual(batched, self._series_one_by_one())

    def test_the_series_comparison_is_not_vacuous(self):
        """An all-zero roster would make the test above pass on any code.

        This is not hypothetical: run against the seeded local database the
        same comparison agreed perfectly while every one of the 48 CCEOs had
        nothing but zeros, which proved nothing at all.
        """
        TargetAchievementService.rebuild_many(self.users, FY)
        batched = per_user_monthly_series(self.users, FY, areas=active_target_areas())
        with_targets = [
            uid for uid, (t, _a) in batched.items() if any(any(v) for v in t.values())
        ]
        with_achievements = [
            uid for uid, (_t, a) in batched.items() if any(any(v) for v in a.values())
        ]
        self.assertTrue(with_targets, "no one in the fixture has a non-zero target")
        self.assertTrue(
            with_achievements, "no one in the fixture has a non-zero achievement"
        )

    def test_an_explicit_monthly_target_lands_on_its_own_owner(self):
        """The batch reads one table for everybody, so a mis-keyed group would
        hand one person's targets to another."""
        batched = per_user_monthly_series(self.users, FY, areas=active_target_areas())
        owner = batched[self.users[0].id][0]["school_visits"]
        self.assertEqual(owner[1], 7, "month 2 of the explicit row")
        self.assertEqual(owner[4], 3, "month 5 of the explicit row")
        for other in self.users[1:]:
            self.assertNotEqual(
                batched[other.id][0]["school_visits"],
                owner,
                "an explicit target must not leak to someone who has none",
            )

    def test_series_reads_do_not_grow_with_roster_size(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        TargetAchievementService.rebuild_many(self.users, FY)

        def reads(roster):
            with CaptureQueriesContext(connection) as cap:
                per_user_monthly_series(roster, FY, areas=active_target_areas())
            return [
                q["sql"]
                for q in cap.captured_queries
                if q["sql"].startswith("SELECT")
                and any(
                    f'FROM "{t}"' in q["sql"]
                    for t in (
                        "monthly_personal_target",
                        "staff_target_profile",
                        "target_achievement_ledger",
                    )
                )
            ]

        self.assertEqual(len(reads(self.users)), len(reads(self.users[:1])))
