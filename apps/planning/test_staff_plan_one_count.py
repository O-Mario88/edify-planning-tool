"""A CCEO's My Plan and their Programme Lead's pages count one plan.

Owner, 2026-10-02: "There is a discrepancy in the actual numbers seen by PL
Planning against target and planning oversight and the ones seen on CCEO my
plan. CCEO sees less and PL sees more. ... make sure those pages are picking
the actual planned activities by staff."

My Plan's tiles counted only what was still ahead, so a person's year shrank
the day after each activity was due while Team Plan and the Planning Monitor
went on counting all of it; and its visits tile counted by activity types of
its own. Both now read ``apps.planning.staff_plan``.
"""

from __future__ import annotations

from datetime import date

from freezegun import freeze_time

from apps.activities.models import Activity
from apps.frontend.views import oversight_views
from apps.my_plan import services as my_plan
from apps.planning import oversight_service as oversight
from apps.planning import staff_plan
from apps.planning.planning_monitor import planning_monitor
from apps.planning.test_planning_monitor import DAY, FY, MonitorFixture

#: A week after the fixture's day: everything Anna planned for it is past due.
LATER = "2026-11-10T09:00:00"


@freeze_time(LATER)
class OnePlanOnEveryPage(MonitorFixture):
    def _my_plan(self, user=None):
        return my_plan.get_frontend_context(user or self.anna_user, {"fy": FY})

    def _team_plan_rows(self):
        """Anna's tab on her Programme Lead's Team Plan, as the page files it."""
        scope = oversight.resolve_oversight_scope(self.pl_user)
        items = [
            item
            for item in oversight.build_items(self.pl_user, fy=FY)
            if not item.is_partner_work
        ]
        members = oversight_views._team_members(scope)
        _own, *theirs = oversight_views._items_owned_by(
            items, scope.own_ids, *(member["owner_ids"] for member in members)
        )
        position = next(
            index
            for index, member in enumerate(members)
            if self.anna.id in member["owner_ids"]
        )
        return theirs[position]

    def _monitor_row(self):
        return self._officer(planning_monitor(self.pl_user, fy=FY), self.anna)

    def _add(self, school, activity_type, *, status="scheduled", day=DAY, **fields):
        return Activity.objects.create(
            school=school,
            activity_type=activity_type,
            status=status,
            delivery_type="staff",
            fy=FY,
            planned_date=day,
            responsible_staff_id=self.anna.id,
            **fields,
        )

    def test_the_year_tile_counts_work_whose_date_has_passed(self):
        # Every activity in the fixture is dated a week ago and none of the
        # scheduled ones is delivered: the old tile read 0 of them.
        rows = self._team_plan_rows()
        self.assertGreater(len(rows), 0)
        self.assertEqual(self._my_plan()["kpis"]["planned_this_fy"], len(rows))

    def test_past_due_work_is_counted_and_named_not_dropped(self):
        context = self._my_plan()
        past_due = Activity.objects.filter(deleted_at__isnull=True, fy=FY).filter(
            staff_plan.own_plan_q([self.anna.id, self.anna_user.id])
        )
        past_due = past_due.filter(staff_plan.past_due_q(date(2026, 11, 10)))
        self.assertGreater(past_due.count(), 0)
        self.assertEqual(context["past_due_count"], past_due.count())

    def test_the_visits_tile_is_the_monitor_s_visits_planned(self):
        # An in-school training booked with no companion visit, a delivered
        # and closed visit, and a story visit that counts toward no target.
        self._add(self.core_b, "in_school_training", purpose_type="in_school_training")
        self._add(self.client_a, "training_follow_up_visit", status="closed")
        self._add(self.client_a, "story_gathering_visit")
        monitor = self._monitor_row()
        kpis = self._my_plan()["kpis"]
        self.assertEqual(kpis["visits_scheduled"], monitor.staff_visits)
        # Two core visits and the in-school training; the client visit and
        # the closed follow-up.
        self.assertEqual((monitor.core_visits, monitor.client_visits), (3, 2))

    def test_the_visits_tile_says_what_it_counts(self):
        self._add(self.client_a, "story_gathering_visit")
        tile = next(
            item
            for item in self._my_plan()["kpi_strip_items"]
            if item["metric_key"] == "my_plan_visits_scheduled_period"
        )
        self.assertEqual(tile["helper"], "of 560 a year · 2 Core, 1 Client")
        # The fixture's donor visit and the story visit added here.
        self.assertIn(
            "2 SSA Support, donor, story, social or invitation visits",
            tile["helper_exact"],
        )
        self.assertIn("not counted toward the target", tile["helper_exact"])

    def test_closed_work_is_on_both_counts(self):
        self._add(self.client_a, "training_follow_up_visit", status="closed")
        self.assertEqual(
            self._my_plan()["kpis"]["planned_this_fy"], len(self._team_plan_rows())
        )

    def test_abandoned_and_partner_work_is_on_neither(self):
        before = self._my_plan()["kpis"]["planned_this_fy"]
        self._add(self.client_a, "school_visit", status="cancelled")
        self._add(self.client_a, "school_visit", status="deferred")
        Activity.objects.create(
            school=self.loose,
            activity_type="school_visit",
            status="partner_scheduled",
            delivery_type="partner",
            fy=FY,
            planned_date=DAY,
            responsible_staff_id=self.anna.id,
        )
        self.assertEqual(self._my_plan()["kpis"]["planned_this_fy"], before)
        self.assertEqual(len(self._team_plan_rows()), before)

    def test_a_programme_lead_s_own_visits_count_toward_280(self):
        Activity.objects.create(
            school=self.client_a,
            activity_type="training_follow_up_visit",
            status="scheduled",
            delivery_type="staff",
            fy=FY,
            planned_date=DAY,
            responsible_staff_id=self.pl.id,
        )
        context = self._my_plan(self.pl_user)
        self.assertEqual(context["kpis"]["visits_scheduled"], 1)
        tile = next(
            item
            for item in context["kpi_strip_items"]
            if item["metric_key"] == "my_plan_visits_scheduled_period"
        )
        self.assertIn("of 280 a year", tile["helper"])
