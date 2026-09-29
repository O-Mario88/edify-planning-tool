"""Country Execution & Completion Oversight — stages, hierarchy, follow-ups, page.

The second Country Oversight stage (owner, 2026-09-28): did the planned work
happen, on time, was it reviewed, verified and closed, and who holds what is
still open. These tests hold it to the platform's own delivery spine:

* four completion levels kept apart — executed, PL-reviewed (a CCEO's staff
  work only), verified, fully closed — and Partner work never waiting on a PL;
* overdue read against the approved scheduled date, always with its stage and
  the owner of the next action ("waiting on IA", never "PL behind");
* the hierarchy reconciling at every level, and every filter narrowing every
  figure together;
* required-slot completion read from the planning requirement;
* the schedule trail recording what moved, so the original plan stays visible;
* "Follow Up with PL" for execution: Director only, to the Lead, deduplicated,
  resolved by itself when the condition clears;
* the page, the two-stage tab strip, the Country Map and the CD's dashboard.

Dates are fixed against an explicit reporting day inside the operational year,
so no assertion depends on the day the suite runs.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from unittest.mock import patch

from django.db import connection
from django.test import RequestFactory, SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleChange
from apps.core.fy import get_operational_fy
from apps.notifications.models import Notification
from apps.planning.country_execution import dataset as ds
from apps.planning.country_execution import followups as efu
from apps.planning.country_execution import service as esvc
from apps.planning.country_execution import stages as st
from apps.planning.country_oversight import followups as planning_fu
from apps.planning.country_oversight.coverage import window_for
from apps.planning.country_oversight.service import system_scope
from apps.planning.country_oversight.todos import followup_todos
from apps.planning.followup_models import FollowUpStatus, PlanningOversightFollowUp
from apps.planning.test_country_planning_oversight import FY, FY_START, World

#: The reporting day the tests read from: well inside the operational year.
TODAY = FY_START + timedelta(days=200)


def on(offset: int) -> date:
    """A day `offset` days from the reporting day."""
    return TODAY + timedelta(days=offset)


def at(offset: int, hour: int = 9) -> datetime:
    """A moment on that day, in the deployment's time zone."""
    return timezone.make_aware(datetime.combine(on(offset), time(hour)))


# ── The classifier, one state at a time ──────────────────────────────────────
class StageClassifierTest(SimpleTestCase):
    def classify(
        self,
        status,
        *,
        partner=False,
        due=-3,
        start=None,
        reviewed=None,
        path="pl",
        operating=True,
        funds=False,
        closure="",
    ):
        return st.classify(
            status=status,
            partner=partner,
            due=on(due) if due is not None else None,
            start=on(start) if start is not None else None,
            pl_reviewed_at=reviewed,
            reviewer_path=path,
            school_operating=operating,
            funds_pending=funds,
            closure_owner=closure,
            today=TODAY,
        )

    def test_every_activity_status_has_a_stage(self):
        from apps.core.enums import ActivityStatus

        read = st.READ_STATES | st.NOT_A_PLAN
        for status in ActivityStatus.values:
            with self.subTest(status=status):
                self.assertIn(status, read)

    def test_not_started_past_its_date_is_execution_overdue_for_its_implementer(self):
        stage = self.classify("scheduled")
        self.assertEqual(
            (stage.stage, stage.overdue, stage.owner, stage.age),
            ("scheduled", "execution", "staff", 3),
        )
        self.assertEqual(
            self.classify("partner_scheduled", partner=True).owner, "partner"
        )
        self.assertEqual(self.classify("scheduled", operating=False).owner, "external")
        self.assertEqual(self.classify("scheduled", funds=True).owner, "finance")
        # Not yet due: nobody is behind.
        upcoming = self.classify("scheduled", due=4)
        self.assertEqual(
            (upcoming.overdue, upcoming.owner, upcoming.timing), ("", "", "upcoming")
        )

    def test_started_work_is_evidence_overdue_and_timed_by_its_start(self):
        stage = self.classify("completion_started", start=-3)
        self.assertEqual(
            (stage.started, stage.executed, stage.overdue, stage.timing),
            (True, False, "evidence", "on_time"),
        )
        self.assertEqual(self.classify("evidence_uploaded", start=-1).timing, "late")
        self.assertEqual(self.classify("in_progress").timing, "unknown")
        # The legacy staged "completed" still has to be submitted.
        self.assertFalse(self.classify("completed").executed)

    def test_review_waits_belong_to_the_reviewer_not_the_implementer(self):
        pl = self.classify("submitted_to_pl")
        self.assertEqual((pl.executed, pl.overdue, pl.owner), (True, "pl_review", "pl"))
        ia = self.classify("awaiting_ia_verification", path="ia")
        self.assertEqual((ia.executed, ia.overdue, ia.owner), (True, "ia_review", "ia"))
        returned = self.classify("returned_by_pl")
        self.assertEqual(
            (returned.returned, returned.executed, returned.overdue, returned.owner),
            (True, False, "correction", "staff"),
        )

    def test_partner_work_never_waits_on_a_programme_lead(self):
        for status in (
            "partner_scheduled",
            "evidence_uploaded",
            "awaiting_ia_verification",
            "ia_verified",
        ):
            with self.subTest(status=status):
                self.assertFalse(self.classify(status, partner=True).pl_applicable)
        # A Lead's own work goes straight to IA too.
        self.assertFalse(
            self.classify("awaiting_ia_verification", path="ia").pl_applicable
        )

    def test_past_the_lead_the_pl_stage_counts_only_when_the_lead_reviewed(self):
        reviewed = self.classify("awaiting_ia_verification", reviewed=timezone.now())
        self.assertEqual((reviewed.pl_applicable, reviewed.pl_reviewed), (True, True))
        direct = self.classify("ia_verified")
        self.assertEqual((direct.pl_applicable, direct.pl_reviewed), (False, False))
        # Before the Lead, a CCEO's staff work is always the Lead's to review.
        self.assertTrue(self.classify("scheduled").pl_applicable)

    def test_verified_and_closed_are_different_levels(self):
        verified = self.classify(
            "ia_verified", reviewed=timezone.now(), closure="finance"
        )
        self.assertEqual(
            (verified.verified, verified.closed, verified.pl_reviewed),
            (True, False, True),
        )
        # Past its date and not closed: open finance work, not "overdue".
        self.assertEqual(
            (verified.overdue, verified.finance_open, verified.owner),
            ("", True, "finance"),
        )
        closed = self.classify("closed")
        self.assertEqual(
            (closed.verified, closed.closed, closed.owner), (True, True, "")
        )

    def test_cancelled_work_is_counted_apart(self):
        stage = self.classify("cancelled")
        self.assertEqual(
            (stage.cancelled, stage.stage, stage.overdue), (True, "cancelled", "")
        )

    def test_overdue_ages_fall_into_the_design_groups(self):
        self.assertEqual(
            [st.age_group(n) for n in (1, 2, 3, 7, 8, 14, 15, 90)],
            [
                "age_1_2",
                "age_1_2",
                "age_3_7",
                "age_3_7",
                "age_8_14",
                "age_8_14",
                "age_15",
                "age_15",
            ],
        )


# ── The country, folded ──────────────────────────────────────────────────────
#: The live work ExecutionWorld schedules, by its offset from the reporting day
#: (the cancelled visit, at -2, is not among them).
LIVE_OFFSETS = (-20, -10, -5, -4, -3, 6, -8, -6, -30)


class ExecutionWorld(World):
    """A country with work at every stage, for one reporting day.

    Lead A holds Officer One (a Core and a Client school), Officer Two (idle)
    and a school of their own; Lead B holds Officer Three (a Client school).
    """

    def setUp(self):
        self.core = self.school("core", self.cceo)
        self.client_a = self.school("client", self.cceo)
        self.client_b = self.school("client", self.cceo3)
        self.personal = self.school("client", self.pl)
        # Verified by the Lead, closure open.
        self.plan(
            self.core,
            "core_visit",
            "ia_verified",
            -20,
            owner=self.cceo,
            execution_started_at=at(-21),
            pl_reviewed_at=at(-15),
            ia_confirmed_at=at(-15),
        )
        self.plan(self.core, "core_visit", "submitted_to_pl", -10, owner=self.cceo)
        self.plan(
            self.core, "core_visit", "partner_scheduled", -5, partner=self.partner
        )
        self.plan(
            self.core,
            "core_visit",
            "awaiting_ia_verification",
            -4,
            partner=self.partner2,
        )
        self.plan(self.client_a, "school_visit", "scheduled", -3, owner=self.cceo)
        self.plan(self.client_a, "school_visit", "scheduled", 6, owner=self.cceo)
        self.plan(self.client_b, "school_visit", "returned_by_pl", -8, owner=self.cceo3)
        self.plan(self.client_b, "school_visit", "cancelled", -2, owner=self.cceo3)
        self.plan(
            self.personal, "school_visit", "awaiting_ia_verification", -6, owner=self.pl
        )
        self.plan(self.personal, "school_visit", "closed", -30, owner=self.pl)

    def plan(self, school, kind, status, offset, *, owner=None, partner=None, **extra):
        day = on(offset)
        return Activity.objects.create(
            activity_type=kind,
            school=school,
            fy=FY,
            quarter="Q1",
            planned_date=day,
            planned_month=day.month,
            status=status,
            responsible_staff_id=owner.id if owner else None,
            delivery_type="partner" if partner else "staff",
            assigned_partner_id=partner.id if partner else None,
            **extra,
        )

    def dataset(self, period="fy", **kw):
        return ds.build(
            system_scope("Uganda"), window_for(FY, period, **kw), today=TODAY
        )

    def fold(self, **filters):
        return esvc.fold(
            self.dataset(), esvc.ExecFilters(fy=FY, period="fy", **filters)
        )

    def snapshot(self, **filters):
        dataset = self.dataset()
        chosen = esvc.ExecFilters(fy=FY, period="fy", **filters)
        return esvc.ExecSnapshot(
            tree=esvc.fold(dataset, chosen),
            filters=chosen,
            dataset=dataset,
            remaining={},
            unique_schools=0,
            required_slots=0,
        )

    def scope(self, **extra):
        window = window_for(FY, "fy")
        return efu.ExecScope(
            fy=FY,
            period_type="fy",
            period_start=window.start,
            period_end=window.end,
            lead_key=self.pl.id,
            country="Uganda",
            **extra,
        )

    def send(self, sender=None, issue="exec_not_started", **extra):
        """The Director's execution follow-up, read on the reporting day."""
        with self.on_the_reporting_day():
            return efu.send_follow_up(
                sender=sender or self.cd_user,
                scope=self.scope(**extra),
                issue_key=issue,
                instruction="Get the visit done or replan it",
                due_date=timezone.localdate() + timedelta(days=5),
                priority="high",
            )

    def on_the_reporting_day(self):
        """Follow-ups re-read the country through the page's fold; read it on
        the reporting day the world was built for."""
        real = ds.build

        def build(scope, window, **kw):
            kw["today"] = TODAY
            return real(scope, window, **kw)

        return patch.object(ds, "build", build)


class ExecutionFoldTest(ExecutionWorld):
    def test_the_country_counts_each_level_apart(self):
        c = self.fold().country
        self.assertEqual(c.due, 9)  # the cancelled visit is not due
        self.assertEqual(c.cancelled, 1)
        self.assertEqual(c.started, 6)
        self.assertEqual(c.executed, 5)
        self.assertEqual(c.verified, 2)
        self.assertEqual(c.closed, 1)
        self.assertEqual(c.returned, 1)
        self.assertEqual(c.upcoming, 1)

    def test_pl_review_is_only_for_a_cceos_staff_work(self):
        tree = self.fold()
        # Five CCEO staff activities are due; the Partner work and the Lead's
        # own go straight to IA.
        self.assertEqual(tree.country.pl_applicable, 5)
        self.assertEqual(tree.country.pl_reviewed, 1)
        self.assertEqual(tree.partner_channel.pl_applicable, 0)

    def test_each_wait_is_owned_by_whoever_holds_the_next_action(self):
        c = self.fold().country
        self.assertEqual((c.od_pl_review, c.own_pl), (1, 1))
        # Waiting on IA, never "the Lead is behind".
        self.assertEqual((c.od_ia_review, c.own_ia), (2, 2))
        self.assertEqual(c.od_execution, 2)
        self.assertEqual(c.own_partner, 1)
        self.assertEqual(c.od_correction, 1)
        self.assertEqual(c.overdue, 6)
        # Verified and not closed is open closure work, not overdue: with no
        # blocker naming the Accountant, the checklist is the staff's.
        self.assertEqual(c.finance_open, 1)
        # The scheduled visit, the returned one and the open closure.
        self.assertEqual(c.own_staff, 3)
        self.assertEqual(c.backlog, 7)

    def test_the_hierarchy_reconciles_at_every_level(self):
        tree = self.fold()
        width = len(tree.country.values)
        total = [0] * width
        for lead in tree.leads:
            people = [0] * width
            for owner in lead.owners:
                for i, v in enumerate(owner.tally.values):
                    people[i] += v
                if owner.partners:
                    channels = [0] * width
                    for tally in owner.partners.values():
                        for i, v in enumerate(tally.values):
                            channels[i] += v
                    self.assertEqual(channels, owner.tally.values, owner.name)
            self.assertEqual(people, lead.tally.values, lead.name)
            for i, v in enumerate(lead.tally.values):
                total[i] += v
        self.assertEqual(total, tree.country.values)
        staff_and_partner = [
            a + b for a, b in zip(tree.staff.values, tree.partner_channel.values)
        ]
        self.assertEqual(staff_and_partner, tree.country.values)

    def test_a_leads_own_work_is_its_own_row(self):
        tree = self.fold()
        lead = next(row for row in tree.leads if row.key == self.pl.id)
        personal = next(row for row in lead.owners if row.kind == "pl_personal")
        self.assertEqual(personal.label, "PL Personal Delivery")
        self.assertEqual(personal.tally.due, 2)
        officer = next(row for row in lead.owners if row.key == self.cceo.id)
        # Four staff activities, and the two Partner visits at the officer's
        # Core school.
        self.assertEqual(officer.tally.due, 6)
        self.assertEqual(officer.partners[ds.STAFF_KEY].due, 4)
        self.assertEqual(officer.partners[self.partner.id].due, 1)
        # An officer with nothing due is still a row under their Lead.
        idle = next(row for row in lead.owners if row.key == self.cceo2.id)
        self.assertEqual(idle.tally.due, 0)

    def test_every_filter_narrows_every_figure_together(self):
        partner_work = self.fold(channel="partner").country
        self.assertEqual((partner_work.due, partner_work.pl_applicable), (2, 0))
        tree = self.fold(program_lead=self.pl2.id)
        self.assertEqual(tree.country.due, 1)
        self.assertEqual([lead.key for lead in tree.leads], [self.pl2.id])
        self.assertEqual(self.fold(activity_type="core_visit").country.due, 4)
        self.assertEqual(self.fold(partner=self.partner.id).country.due, 1)
        self.assertEqual(self.fold(cceo=self.cceo.id).country.due, 6)
        self.assertEqual(self.fold(region=self.region.id).country.due, 9)

    def test_the_period_is_the_scheduled_date(self):
        month = on(-3)
        window = window_for(FY, "month", month=month.month)
        dataset = ds.build(system_scope("Uganda"), window, today=TODAY)
        tree = esvc.fold(
            dataset, esvc.ExecFilters(fy=FY, period="month", month=month.month)
        )
        expected = sum(
            1
            for offset in LIVE_OFFSETS
            if (on(offset).year, on(offset).month) == (month.year, month.month)
        )
        self.assertEqual(tree.country.due, expected)
        for record in dataset.records:
            self.assertEqual(
                (record.due.year, record.due.month), (month.year, month.month)
            )

    def test_the_charts_are_the_table(self):
        snapshot = self.snapshot()
        charts = esvc.charts(snapshot)
        c = snapshot.tree.country
        funnel = {s["name"]: s["data"] for s in charts["funnel"]["series"]}
        self.assertEqual(
            funnel["Total"],
            [c.due, c.started, c.executed, c.pl_reviewed, c.verified, c.closed],
        )
        self.assertIsNone(funnel["Partner"][3])  # no PL stage for Partner work
        self.assertEqual(charts["funnel"]["table"][3][3], "N/A")
        self.assertEqual(sum(p["value"] for p in charts["backlog"]["parts"]), c.backlog)
        self.assertEqual(sum(charts["age"]["data"]), c.overdue)
        self.assertEqual(charts["trend"]["series"][0]["data"][-1], c.due)
        self.assertEqual(
            sum(
                p["value"]
                for p in charts["on_time"]["parts"]
                if p["label"] != "Canceled"
            ),
            c.due,
        )

    def test_the_six_figures_read_the_country_row(self):
        snapshot = self.snapshot()
        cards = {card["key"]: card for card in esvc.kpis(snapshot)}
        self.assertEqual(
            list(cards), ["due", "started", "executed", "verified", "closed", "overdue"]
        )
        c = snapshot.tree.country
        self.assertEqual(cards["due"]["value"], str(c.due))
        self.assertEqual(cards["overdue"]["value"], str(c.overdue))
        self.assertEqual(cards["verified"]["share"], round(100 * c.verified / c.due))
        self.assertIn("stage=overdue", cards["overdue"]["href"])

    def test_top_issues_count_each_record_once(self):
        snapshot = self.snapshot()
        issues = {row["key"]: row["count"] for row in esvc.issues(snapshot)}
        c = snapshot.tree.country
        self.assertEqual(sum(issues.values()), c.overdue + c.finance_open)
        self.assertEqual(issues.get("ia_review"), 2)
        self.assertEqual(issues.get("partner"), 1)
        self.assertEqual(issues.get("closure"), 1)
        self.assertIsNone(issues.get("finance"))

    def test_the_drill_down_lists_the_records_behind_a_figure(self):
        snapshot = self.snapshot()
        overdue = esvc.activity_rows(snapshot, stage="overdue")
        self.assertEqual(overdue["total"], snapshot.tree.country.overdue)
        ages = [row["age"] for row in overdue["rows"]]
        self.assertEqual(ages, sorted(ages, reverse=True))  # oldest first
        waiting = esvc.activity_rows(snapshot, stage="overdue", blocker="ia")
        self.assertEqual({row["waiting_on"] for row in waiting["rows"]}, {"IA"})
        self.assertEqual(
            {row["overdue"] for row in waiting["rows"]}, {"IA review overdue"}
        )

    def test_partner_rows_never_wait_on_a_lead(self):
        rows = {row["key"]: row for row in esvc.partner_rows(self.snapshot())}
        alpha, beta = rows[self.partner.id], rows[self.partner2.id]
        self.assertEqual((alpha["due"], alpha["started"], alpha["overdue"]), (1, 0, 1))
        self.assertEqual((beta["due"], beta["executed"], beta["verified"]), (1, 1, 0))

    def test_a_reminder_is_suggested_only_for_work_the_lead_can_move(self):
        def tally(**owners):
            values = [0] * ds.BASE_WIDTH
            for owner, count in owners.items():
                values[ds.IDX[f"own_{owner}"]] = count
            return esvc.ExecTally(values)

        self.assertTrue(esvc.suggests_reminder(tally(staff=1), 0))
        self.assertTrue(esvc.suggests_reminder(tally(partner=2), 0))
        self.assertTrue(esvc.suggests_reminder(tally(pl=1), 0))
        # Waiting on IA, the Accountant or the school is not the Lead's to move.
        self.assertFalse(esvc.suggests_reminder(tally(ia=3, finance=1, external=2), 0))
        # Already asked: no second suggestion.
        self.assertFalse(esvc.suggests_reminder(tally(staff=4), 1))
        rows = {row["key"]: row for row in esvc.lead_rows(self.snapshot(), {})}
        self.assertTrue(rows[self.pl.id]["cells"]["suggested"])
        rows = {
            row["key"]: row
            for row in esvc.lead_rows(self.snapshot(), {("lead", self.pl.id): 1})
        }
        self.assertFalse(rows[self.pl.id]["cells"]["suggested"])

    def test_the_forecast_is_decision_support_with_its_own_floor(self):
        c = self.fold().country
        window = window_for(FY, "fy")
        self.assertEqual(esvc.forecast(c, window, TODAY)["status"], "insufficient")
        self.assertEqual(esvc.forecast(c, window, date(2100, 1, 1))["status"], "closed")


class ExecutionWarmTest(ExecutionWorld):
    def test_the_warmer_publishes_what_the_director_is_served(self):
        from django.core.cache import cache
        from django.test import override_settings

        today = timezone.localdate()
        fy = get_operational_fy(today)
        month = esvc.ExecFilters(fy=fy, period="month", month=today.month)
        year = esvc.ExecFilters(fy=fy, period="fy")
        with override_settings(DASHBOARD_CACHE_SECONDS=300):
            cache.clear()
            esvc._HELD.clear()
            targets = esvc.warm_targets(today)
            self.assertIn(("Uganda", month), targets)
            self.assertIn(("Uganda", year), targets)
            self.assertEqual(esvc.warm(targets), 2)
            from apps.planning.country_oversight import service as planning

            with (
                patch.object(ds, "build", side_effect=AssertionError("built on open")),
                patch.object(
                    planning,
                    "build_dataset",
                    side_effect=AssertionError("built on open"),
                ),
            ):
                warmed = esvc.dataset_for(self.cd_user, year.window)
                esvc.dataset_for(self.cd_user, month.window)
                # The planning figures behind the month's Remaining Slots.
                planning.dataset_for(self.cd_user, month.planning().window)
            fresh = ds.build(system_scope("Uganda"), year.window)
            self.assertEqual(sorted(warmed.records), sorted(fresh.records))
            self.assertEqual(warmed.cells, fresh.cells)
            # A window a country reader opens is kept warm for the next hour.
            quarter = esvc.ExecFilters(fy=fy, period="quarter", quarter="Q2")
            esvc.dataset_for(self.cd_user, quarter.window)
            self.assertIn(("Uganda", quarter), esvc.warm_targets(today))
            cache.clear()
            esvc._HELD.clear()
            planning._HELD.clear()
        with override_settings(DASHBOARD_CACHE_SECONDS=0):
            self.assertEqual(esvc.warm(), 0)

    def test_the_cached_dataset_reads_back_as_it_was_built(self):
        import pickle

        dataset = self.dataset()
        # nosec B301 - the bytes are the ones this test just made, pickled the
        # way Django's cache pickles the dataset; nothing untrusted is read.
        restored = pickle.loads(pickle.dumps(dataset, pickle.HIGHEST_PROTOCOL))  # nosec B301
        self.assertIsInstance(restored.records, ds.RecordTable)
        self.assertEqual(list(restored.records), list(dataset.records))
        self.assertTrue(all(isinstance(r, ds.ActivityRecord) for r in restored.records))
        filters = esvc.ExecFilters(fy=FY, period="fy", program_lead=self.pl.id)
        self.assertEqual(
            esvc.fold(restored, filters).country.values,
            esvc.fold(dataset, filters).country.values,
        )


class TargetLedgerTest(ExecutionWorld):
    """Spec §23: planned output, validated actual and the gap come from the
    canonical helper CD Analytics, My Targets and Team Targets share; the
    helper's own arithmetic is tested where it lives."""

    def test_targets_are_read_through_the_canonical_helper(self):
        from apps.analytics.cd_analytics_service import CDAnalyticsService

        calls = []

        def canonical(fy, period, user_ids, staff_ids, **kwargs):
            calls.append((fy, period, set(staff_ids)))
            return 62, 31, 50

        with patch.object(
            CDAnalyticsService, "_weighted_achievement", staticmethod(canonical)
        ):
            year = esvc.target_position(
                self.dataset(), esvc.ExecFilters(fy=FY, period="fy")
            )
            self.assertEqual(
                year,
                {"status": "ok", "target": 50, "achieved": 31, "gap": 19, "pct": 62},
            )
            # Every Lead and their people, with or without work this period.
            self.assertEqual(
                calls[-1],
                (
                    FY,
                    None,
                    {
                        self.pl.id,
                        self.pl2.id,
                        self.cceo.id,
                        self.cceo2.id,
                        self.cceo3.id,
                    },
                ),
            )
            month = on(-3).month
            month_data = self.dataset("month", month=month)
            esvc.target_position(
                month_data, esvc.ExecFilters(fy=FY, period="month", month=month)
            )
            self.assertEqual(calls[-1][1], list(month_data.window.months_of_fy))
            esvc.target_position(
                self.dataset(),
                esvc.ExecFilters(fy=FY, period="fy", program_lead=self.pl2.id),
            )
            self.assertEqual(calls[-1][2], {self.pl2.id, self.cceo3.id})
            # A target is a person's: region, channel, Partner and type do not
            # divide it, and a week has none.
            self.assertEqual(
                esvc.target_position(
                    self.dataset(),
                    esvc.ExecFilters(fy=FY, period="fy", channel="partner"),
                )["status"],
                "people_only",
            )
            page = self.as_user(self.cd_user).get(
                f"/country-planning-oversight/?view=execution&period=fy&fy={FY}"
            )
            self.assertContains(
                page,
                "planned output 50 · validated actual 31 · remaining gap 19 · 62% achieved",
            )


class RequiredSlotsTest(ExecutionWorld):
    def test_remaining_slots_come_from_the_planning_requirement(self):
        request = RequestFactory().get(
            "/", {"fy": FY, "period": "fy", "view": "execution"}
        )
        request.user = self.cd_user
        filters = esvc.read_filters(request)
        remaining, required = esvc.remaining_slots(self.cd_user, filters)
        # Core: four visits and four trainings; three Client schools: one each.
        self.assertEqual(required, 4 + 4 + 3 * (1 + 1))
        # Two visits are verified (the Core school's, and the Lead's closed one).
        self.assertEqual(remaining[("country", "")], required - 2)
        self.assertEqual(
            remaining[("country", "")],
            sum(value for (level, _key), value in remaining.items() if level == "lead"),
        )
        rows = esvc.school_completion_rows(self.cd_user, filters)
        core = next(row for row in rows["rows"] if row["id"] == self.core.id)
        self.assertEqual(core["visit_slots"], 4)
        self.assertEqual(core["staff"], (1, 2))
        self.assertEqual(core["visits_verified"], 1)


# ── The schedule trail ───────────────────────────────────────────────────────
class ScheduleTrailTest(World):
    def test_a_move_a_cancellation_and_a_restoration_are_recorded(self):
        school = self.school("client", self.cceo)
        first, moved = FY_START + timedelta(days=40), FY_START + timedelta(days=70)
        created = Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy=FY,
            quarter="Q1",
            planned_date=first,
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )
        activity = Activity.objects.get(pk=created.pk)
        activity.planned_date = moved
        activity.status = "rescheduled"
        activity.last_reason = "School closed for exams"
        activity.save()
        activity.status = "cancelled"
        activity.save(update_fields=["status"])
        activity.status = "planned"
        activity.save(update_fields=["status"])
        # A save that moves nothing records nothing.
        activity.save(update_fields=["updated_at"])
        rows = list(
            ActivityScheduleChange.objects.filter(activity=activity)
            .order_by("changed_at")
            .values_list("kind", "from_day", "to_day", "reason")
        )
        self.assertEqual(
            rows,
            [
                ("rescheduled", first, moved, "School closed for exams"),
                ("cancelled", moved, moved, ""),
                ("restored", moved, moved, ""),
            ],
        )

    def test_a_narrow_read_never_pays_for_the_trail(self):
        school = self.school("client", self.cceo)
        Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy=FY,
            quarter="Q1",
            planned_date=FY_START,
            status="scheduled",
            delivery_type="staff",
        )
        with CaptureQueriesContext(connection) as ctx:
            list(Activity.objects.only("id", "status"))
        self.assertEqual(len(ctx.captured_queries), 1)

    def test_work_moved_out_of_a_tracked_period_is_carried_forward(self):
        # A week that begins after the trail began (the test database's
        # migration), with one activity moved out of it.
        today = timezone.localdate()
        week_start = today + timedelta(days=7 - today.weekday())
        fy = get_operational_fy(week_start)
        window = window_for(fy, "week", week_start=week_start)
        school = self.school("client", self.cceo)
        was, now = week_start + timedelta(days=1), week_start + timedelta(days=15)
        moved = Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy=fy,
            quarter="Q1",
            planned_date=was,
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )
        ActivityScheduleChange.objects.create(
            activity=moved,
            kind="rescheduled",
            from_day=was,
            to_day=now,
            from_status="scheduled",
            to_status="rescheduled",
            changed_at=timezone.make_aware(datetime.combine(week_start, time(9))),
        )
        Activity.objects.filter(pk=moved.pk).update(
            planned_date=now, status="rescheduled"
        )
        dataset = ds.build(
            system_scope("Uganda"), window, today=week_start + timedelta(days=3)
        )
        integrity = dataset.integrity
        self.assertTrue(integrity["tracked"])
        self.assertEqual(
            (integrity["original"], integrity["moved_out"], integrity["current"]),
            (1, 1, 0),
        )
        tree = esvc.fold(
            dataset,
            esvc.ExecFilters(fy=fy, period="week", week=week_start.strftime("%G-W%V")),
        )
        self.assertEqual((tree.country.carried_forward, tree.country.due), (1, 0))

    def test_a_period_that_began_before_the_trail_says_so(self):
        dataset = ds.build(system_scope("Uganda"), window_for(FY, "fy"), today=TODAY)
        self.assertFalse(dataset.integrity["tracked"])
        self.assertIsNotNone(dataset.integrity["tracking_since"])


# ── Locked period snapshots (spec §22) ───────────────────────────────────────
class PeriodSnapshotTest(ExecutionWorld):
    def april(self):
        """The month the world's work falls in, and the day after it ends."""
        month = on(-3)
        window = window_for(FY, "month", month=month.month)
        return window, window.end

    def test_the_periods_that_have_just_ended(self):
        from apps.planning.country_execution import snapshots

        windows = snapshots.ended_windows(date(2026, 10, 5))  # a Monday
        self.assertEqual(
            [(w.period, w.start, w.end) for w in windows],
            [
                ("week", date(2026, 9, 28), date(2026, 10, 5)),
                ("month", date(2026, 9, 1), date(2026, 10, 1)),
                ("quarter", date(2026, 7, 1), date(2026, 10, 1)),
                ("fy", date(2025, 10, 1), date(2026, 10, 1)),
            ],
        )
        self.assertEqual(len(snapshots.due_windows(date(2026, 10, 5))), 4)
        # Past the grace, a period is left without a snapshot rather than
        # given one read long after it ended.
        self.assertEqual(
            [w.period for w in snapshots.due_windows(date(2026, 10, 20))], ["week"]
        )

    def test_a_period_is_locked_as_it_stood_at_its_end(self):
        from apps.planning.country_execution import snapshots

        window, closed = self.april()
        followup, _ = self.send(cceo_key=self.cceo.id)
        locked = snapshots.take("Uganda", window, today=closed)
        self.assertEqual(
            (locked.version, locked.kind, locked.as_of), (1, "original", closed)
        )
        self.assertEqual(locked.stage_policy, st.STAGE_POLICY)
        dataset = ds.build(system_scope("Uganda"), window, today=closed)
        c = esvc.fold(
            dataset, esvc.ExecFilters(fy=FY, period="month", month=window.month)
        ).country
        f = locked.figures
        self.assertEqual(
            (
                f["due"],
                f["executed"],
                f["verified"],
                f["closed"],
                f["overdue"],
                f["cancelled"],
            ),
            (c.due, c.executed, c.verified, c.closed, c.overdue, c.cancelled),
        )
        self.assertEqual(f["current_plan"], c.due)
        self.assertEqual(f["carryover"], c.due - c.verified)
        # At the close nothing due in the period is "not yet due": whatever
        # was not verified by the end is overdue at its stage.
        self.assertEqual(c.upcoming, 0)
        self.assertEqual(f["overdue"], f["carryover"])
        # The period began before the schedule trail: no original plan claimed.
        self.assertIsNone(f["original_plan"])
        self.assertFalse(f["plan_tracked"])
        # Staff and Partner, and the hierarchy, add up to the country.
        self.assertEqual(
            locked.channels["staff"]["due"] + locked.channels["partner"]["due"],
            f["due"],
        )
        self.assertEqual(
            sum(lead["figures"]["due"] for lead in locked.hierarchy), f["due"]
        )
        for lead in locked.hierarchy:
            self.assertEqual(
                sum(owner["figures"]["due"] for owner in lead["owners"]),
                lead["figures"]["due"],
            )
        self.assertEqual([item["id"] for item in locked.follow_ups], [followup.id])
        self.assertIsNotNone(f["slots"])

    def test_a_locked_period_never_changes(self):
        from apps.planning.country_execution import snapshots
        from apps.planning.execution_snapshot_models import LockedSnapshotError

        window, closed = self.april()
        locked = snapshots.take("Uganda", window, today=closed)
        locked.figures["due"] = 999
        with self.assertRaises(LockedSnapshotError):
            locked.save()
        with self.assertRaises(LockedSnapshotError):
            locked.delete()
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.take("Uganda", window, today=closed)
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.take("Uganda", window_for(FY, "fy"), today=TODAY)  # not ended

    def test_a_revision_is_recorded_beside_the_original(self):
        from apps.planning.country_execution import snapshots
        from apps.planning.execution_snapshot_models import ExecutionPeriodSnapshot

        window, closed = self.april()
        original = snapshots.take("Uganda", window, today=closed)
        verified_then = original.figures["verified"]
        # A correction through the governed workflow: late verification.
        Activity.objects.filter(status="submitted_to_pl").update(status="ia_verified")
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.revise(original, self.cd_user, "The Lead approved late")
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.revise(original, self.admin_user, "  ")
        revision = snapshots.revise(original, self.admin_user, "The Lead approved late")
        self.assertEqual((revision.version, revision.kind), (2, "revision"))
        self.assertEqual(revision.revises_id, original.id)
        self.assertEqual(revision.reason, "The Lead approved late")
        self.assertEqual(revision.taken_by_id, self.admin_user.id)
        self.assertEqual(revision.figures["verified"], verified_then + 1)
        original.refresh_from_db()
        self.assertEqual(original.figures["verified"], verified_then)
        self.assertEqual(
            [s.version for s in snapshots.for_window("Uganda", window)], [1, 2]
        )
        self.assertEqual(ExecutionPeriodSnapshot.objects.count(), 2)

    def test_the_nightly_close_locks_each_period_once(self):
        from apps.core.fy import get_fy_date_range
        from apps.planning.country_execution import snapshots
        from apps.realtime.jobs import _do_execution_period_snapshots

        after_the_year = get_fy_date_range(FY)[1].date() + timedelta(days=4)
        self.assertEqual(snapshots.lock_ended_periods(after_the_year), 4)
        self.assertEqual(snapshots.lock_ended_periods(after_the_year), 0)
        periods = {
            s.period_type for s in snapshots.listing("Uganda") for s in [s["original"]]
        }
        self.assertEqual(periods, {"week", "month", "quarter", "fy"})
        # The job reads today's close: nothing new to lock twice in a day.
        _do_execution_period_snapshots()
        _do_execution_period_snapshots()
        from apps.planning.execution_snapshot_models import ExecutionPeriodSnapshot

        self.assertEqual(
            ExecutionPeriodSnapshot.objects.values("period_type", "period_start")
            .distinct()
            .count(),
            ExecutionPeriodSnapshot.objects.count(),
        )

    def test_the_director_reads_them_and_only_policy_may_revise(self):
        from apps.planning.country_execution import snapshots

        window, closed = self.april()
        locked = snapshots.take("Uganda", window, today=closed)
        director = self.as_user(self.cd_user)
        listing = director.get(
            "/country-planning-oversight/execution/snapshots", HTTP_HX_REQUEST="true"
        )
        self.assertContains(listing, locked.period_label)
        self.assertContains(
            listing, f"/country-planning-oversight/execution/snapshots/{locked.id}"
        )
        detail = director.get(
            f"/country-planning-oversight/execution/snapshots/{locked.id}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(detail, "Original committed plan")
        self.assertContains(detail, "PL Personal Delivery")
        self.assertNotContains(detail, "Record a revision")
        refused = director.post(
            f"/country-planning-oversight/execution/snapshots/{locked.id}",
            {"reason": "Not mine"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(snapshots.for_window("Uganda", window), [locked])
        admin = self.as_user(self.admin_user)
        revised = admin.post(
            f"/country-planning-oversight/execution/snapshots/{locked.id}",
            {"reason": "A return reversed a verification"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(
            revised, "Recorded revision 1. The original stays beside it."
        )
        self.assertContains(revised, "A return reversed a verification")
        self.assertEqual(len(snapshots.for_window("Uganda", window)), 2)
        # The regional VP reads figures; field roles do not reach them.
        self.assertEqual(
            self.as_user(self.rvp_user)
            .get("/country-planning-oversight/execution/snapshots")
            .status_code,
            200,
        )
        self.assertIn(
            self.as_user(self.cceo_user)
            .get("/country-planning-oversight/execution/snapshots")
            .status_code,
            (302, 403),
        )
        # The period's page says it is locked and opens the locked figures.
        page = director.get(
            f"/country-planning-oversight/?view=execution&period=month&month={window.month}&fy={FY}"
        )
        self.assertContains(
            page, f"/country-planning-oversight/execution/snapshots/{locked.id}"
        )
        self.assertContains(page, "View the locked figures")


# ── Follow Up with PL, for execution ─────────────────────────────────────────
class ExecutionFollowUpTest(ExecutionWorld):
    def test_the_director_asks_the_lead_and_nobody_else(self):
        before = list(
            Activity.objects.order_by("id").values_list("id", "status", "planned_date")
        )
        followup, created = self.send(cceo_key=self.cceo.id)
        self.assertTrue(created)
        self.assertEqual(followup.module, "execution")
        self.assertEqual(followup.program_lead_staff_id, self.pl.id)
        self.assertEqual(followup.status, FollowUpStatus.SENT_TO_PL)
        # The officer's staff visit and the Partner visit at their Core school.
        self.assertEqual(followup.remaining_value, 2)
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl_user.id, context_id=followup.id
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                recipient_id=self.cceo_user.id, context_id=followup.id
            ).exists()
        )
        after = list(
            Activity.objects.order_by("id").values_list("id", "status", "planned_date")
        )
        self.assertEqual(before, after)

    def test_asking_again_reminds_on_the_same_record(self):
        first, _ = self.send(cceo_key=self.cceo.id)
        second, created = self.send(cceo_key=self.cceo.id)
        self.assertFalse(created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.reminder_count, 1)
        self.assertEqual(len(second.instruction_history), 2)
        self.assertEqual(
            PlanningOversightFollowUp.objects.filter(module="execution").count(), 1
        )

    def test_only_the_director_may_ask(self):
        for user in (self.ia_user, self.admin_user, self.rvp_user, self.pl_user):
            with (
                self.subTest(role=user.active_role),
                self.assertRaises(efu.FollowUpError),
            ):
                self.send(sender=user)

    def test_there_must_be_something_to_follow_up(self):
        with self.assertRaises(efu.FollowUpError):
            self.send(issue="exec_returned", cceo_key=self.cceo.id)

    def test_it_closes_itself_when_the_work_starts(self):
        followup, _ = self.send(cceo_key=self.cceo.id)
        Activity.objects.filter(
            school__in=(self.core, self.client_a),
            status__in=("scheduled", "partner_scheduled"),
        ).update(status="completion_started")
        with self.on_the_reporting_day():
            self.assertTrue(
                efu.refresh(PlanningOversightFollowUp.objects.get(pk=followup.pk))
            )
        followup.refresh_from_db()
        self.assertEqual(followup.status, FollowUpStatus.RESOLVED_AUTOMATICALLY)
        self.assertTrue(followup.resolved_by_system)

    def test_it_stays_open_while_any_of_the_gap_remains(self):
        followup, _ = self.send(cceo_key=self.cceo.id)
        Activity.objects.filter(school=self.client_a, status="scheduled").update(
            status="completion_started"
        )
        with self.on_the_reporting_day():
            self.assertFalse(
                efu.refresh(PlanningOversightFollowUp.objects.get(pk=followup.pk))
            )
        followup.refresh_from_db()
        self.assertEqual(
            (followup.status, followup.live_remaining), (FollowUpStatus.SENT_TO_PL, 1)
        )

    def test_the_lead_gets_an_execution_to_do_and_can_say_what_it_waits_on(self):
        followup, _ = self.send(cceo_key=self.cceo.id)
        rows = followup_todos(self.pl_user, "Program Lead", timezone.localdate())
        mine = next(row for row in rows if row["id"] == f"cpofu-{followup.id}")
        self.assertEqual(mine["title"], "Follow Up with CCEO on Execution Gap")
        efu.mark_waiting_on(
            followup, self.pl_user, "partner", "Partner schedules next week"
        )
        followup.refresh_from_db()
        self.assertEqual(followup.status, FollowUpStatus.WAITING_FOR_PARTNER)
        self.assertTrue(followup.is_open)
        with self.assertRaises(efu.FollowUpError):
            efu.mark_waiting_on(followup, self.cceo_user, "external", "Not mine to say")

    def test_the_lead_answers_on_team_oversight(self):
        followup, _ = self.send(cceo_key=self.cceo.id)
        lead = self.as_user(self.pl_user)
        banner = lead.get(f"/planning-follow-ups/{followup.id}", HTTP_HX_REQUEST="true")
        self.assertContains(banner, "2 open when sent")
        self.assertContains(banner, 'name="waiting_on"')
        self.assertNotContains(banner, "required ")
        answered = lead.post(
            f"/planning-follow-ups/{followup.id}/waiting",
            {"waiting_on": "external", "note": "The school is closed for exams"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(answered, "Marked as waiting on an external dependency.")
        followup.refresh_from_db()
        self.assertEqual(followup.status, FollowUpStatus.WAITING_FOR_EXTERNAL)
        self.assertEqual(followup.linked_note, "The school is closed for exams")
        # Nobody but the Lead it was sent to answers it.
        other = self.as_user(self.pl2_user).post(
            f"/planning-follow-ups/{followup.id}/waiting",
            {"waiting_on": "partner", "note": "Not mine"},
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(other.status_code, (403, 404))

    def test_the_director_closes_or_cancels_it_from_the_register(self):
        followup, _ = self.send(cceo_key=self.cceo.id)
        director = self.as_user(self.cd_user)
        refused = director.post(
            f"/country-planning-oversight/follow-up/{followup.id}/close",
            {"reason": ""},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(refused, "needs a reason")
        # Only the Director closes the Director's follow-up.
        self.assertIn(
            self.as_user(self.pl_user)
            .post(
                f"/country-planning-oversight/follow-up/{followup.id}/close",
                {"reason": "Done"},
                HTTP_HX_REQUEST="true",
            )
            .status_code,
            (302, 403),
        )
        closed = director.post(
            f"/country-planning-oversight/follow-up/{followup.id}/close",
            {"reason": "Replanned with the Lead"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(closed, "Closed. The reason is on the record.")
        followup.refresh_from_db()
        self.assertEqual(followup.status, FollowUpStatus.CLOSED_BY_CD)
        again, created = self.send(cceo_key=self.cceo.id)
        self.assertTrue(created)  # the closed one is history, not reopened
        cancelled = director.post(
            f"/country-planning-oversight/follow-up/{again.id}/cancel",
            {"reason": "Sent by mistake"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(cancelled, "Cancelled.")
        again.refresh_from_db()
        self.assertEqual(again.status, FollowUpStatus.CANCELLED)

    def test_a_follow_up_past_its_due_date_can_be_escalated_to_the_lead(self):
        followup, _ = self.send(cceo_key=self.cceo.id)
        director = self.as_user(self.cd_user)
        early = director.post(
            f"/country-planning-oversight/follow-up/{followup.id}/escalate",
            {"reason": "Still nothing"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(
            early, "Only a follow-up past its due date can be escalated."
        )
        PlanningOversightFollowUp.objects.filter(pk=followup.pk).update(
            due_date=timezone.localdate() - timedelta(days=1)
        )
        # The register reads an execution follow-up in its own terms, and
        # Remind reopens the execution ask.
        register = director.get(
            f"/country-planning-oversight/drawer?kind=followups&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(register, "When sent: 2 open")
        self.assertContains(
            register, "/country-planning-oversight/execution/follow-up?"
        )
        self.assertContains(
            register, f"/country-planning-oversight/follow-up/{followup.id}/escalate"
        )
        escalated = director.post(
            f"/country-planning-oversight/follow-up/{followup.id}/escalate",
            {"reason": "Nothing has moved since the due date"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(escalated, "Escalated.")
        followup.refresh_from_db()
        self.assertEqual(
            (followup.status, followup.priority), (FollowUpStatus.ESCALATED, "critical")
        )
        self.assertTrue(followup.is_open)
        # Back in the Lead's queue.
        rows = followup_todos(self.pl_user, "Program Lead", timezone.localdate())
        self.assertIn(f"cpofu-{followup.id}", [row["id"] for row in rows])

    def test_the_two_stages_count_their_own_follow_ups(self):
        self.send(cceo_key=self.cceo.id)
        self.assertEqual(efu.open_counts(FY).get(("country", "")), 1)
        self.assertEqual(efu.open_counts(FY).get(("owner", self.cceo.id)), 1)
        self.assertIsNone(planning_fu.open_counts(FY).get(("country", "")))


# ── The page ─────────────────────────────────────────────────────────────────
class ExecutionPageTest(ExecutionWorld):
    QUERY = f"view=execution&period=fy&fy={FY}"
    URL = f"/country-planning-oversight/?{QUERY}"

    def test_the_design_is_on_the_page(self):
        response = self.as_user(self.cd_user).get(self.URL)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for text in (
            "Execution &amp; Completion",
            "Country General Planning Oversight",
            "Country Execution &amp; Completion Oversight",
            "Activities Due",
            "Started",
            "Execution Completed",
            "IA Verified",
            "Fully Closed",
            "Overdue",
            "Execution Funnel",
            "Planned vs Executed vs Verified",
            "On-Time Execution",
            "Backlog by Owner",
            "Overdue by Age",
            "Completion Forecast",
            "Quick Actions",
            "Send Reminder to PL",
            "Program Leads",
            "CCEOs",
            "Remaining Slots",
            "Open Reminders",
            "Top Execution Issues",
            "Recent Activity",
            "Open Follow-ups",
            "Uganda Total",
        ):
            with self.subTest(text=text):
                self.assertIn(text, body)
        # Two stages only: the portfolio moved to the Country Map.
        self.assertNotIn("view=portfolio", body)

    def test_a_rows_chevron_rides_on_its_name(self):
        # On a phone the name column pins and stacks a row's lines: a chevron
        # beside the name's span stood on a line of its own above the name.
        # Inside the span it keeps the name's line, the row's note under both.
        body = (
            self.as_user(self.cd_user)
            .get(
                f"/country-planning-oversight/execution/table?table=lead&{self.QUERY}",
                HTTP_HX_REQUEST="true",
            )
            .content.decode()
        )
        self.assertIn('<span><button type="button" class="cpo-toggle"', body)

    def test_every_table_view_and_drill_down_answers(self):
        client = self.as_user(self.cd_user)
        for table in ("lead", "cceo", "partner", "school", "activity"):
            with self.subTest(table=table):
                response = client.get(
                    f"/country-planning-oversight/execution/table?table={table}&{self.QUERY}",
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(response.status_code, 200)
        for stage in ("due", "overdue", "verified", "finance"):
            with self.subTest(stage=stage):
                response = client.get(
                    f"/country-planning-oversight/execution/drawer?kind=activities&stage={stage}&{self.QUERY}",
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(response.status_code, 200)
        rows = client.get(
            f"/country-planning-oversight/execution/rows?level=lead&key={self.pl.id}&{self.QUERY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(rows, "PL Personal Delivery")
        export = client.get(
            f"/country-planning-oversight/execution/export?{self.QUERY}"
        )
        self.assertEqual(export.status_code, 200)
        self.assertIn("spreadsheetml", export["Content-Type"])

    def test_only_the_director_sees_follow_up_controls(self):
        director = self.as_user(self.cd_user).get(self.URL)
        reviewer = self.as_user(self.ia_user).get(self.URL)
        self.assertContains(director, "Send Reminder to PL")
        self.assertEqual(reviewer.status_code, 200)
        self.assertNotContains(reviewer, "Send Reminder to PL")
        drawer = self.as_user(self.ia_user).get(
            f"/country-planning-oversight/execution/follow-up?lead={self.pl.id}&{self.QUERY}"
        )
        self.assertEqual(drawer.status_code, 403)

    def test_field_roles_cannot_open_it(self):
        for user in (self.pl_user, self.cceo_user):
            with self.subTest(role=user.active_role):
                self.assertIn(self.as_user(user).get(self.URL).status_code, (302, 403))

    def test_the_rvp_reads_figures_not_records(self):
        client = self.as_user(self.rvp_user)
        self.assertEqual(client.get(self.URL).status_code, 200)
        drawer = client.get(
            f"/country-planning-oversight/execution/drawer?kind=activities&stage=due&{self.QUERY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(drawer, "Activity rows are not shown for your role")

    def test_the_page_changes_nothing(self):
        before = list(
            Activity.objects.order_by("id").values_list("id", "status", "planned_date")
        )
        client = self.as_user(self.cd_user)
        client.get(self.URL)
        client.get(f"/country-planning-oversight/execution/export?{self.QUERY}")
        after = list(
            Activity.objects.order_by("id").values_list("id", "status", "planned_date")
        )
        self.assertEqual(before, after)
        self.assertFalse(ActivityScheduleChange.objects.exists())


class CountryOversightHomeTest(World):
    def test_the_directors_dashboard_is_country_oversight(self):
        client = self.as_user(self.cd_user)
        response = client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/country-planning-oversight/")
        # The former command dashboard still answers when a link names a view.
        self.assertEqual(client.get("/dashboard?view=operations").status_code, 200)

    def test_whos_online_sits_under_the_planning_tab(self):
        director = (
            self.as_user(self.cd_user)
            .get("/country-planning-oversight/")
            .content.decode()
        )
        self.assertIn('hx-get="/dashboard/whos-online"', director)
        reviewer = (
            self.as_user(self.ia_user)
            .get("/country-planning-oversight/")
            .content.decode()
        )
        self.assertNotIn('hx-get="/dashboard/whos-online"', reviewer)
        execution = (
            self.as_user(self.cd_user)
            .get("/country-planning-oversight/?view=execution")
            .content.decode()
        )
        self.assertNotIn('hx-get="/dashboard/whos-online"', execution)
        operations = (
            self.as_user(self.cd_user)
            .get("/dashboard?view=operations")
            .content.decode()
        )
        self.assertNotIn('hx-get="/dashboard/whos-online"', operations)

    def test_whos_online_filters_in_place_and_reopens_where_it_was(self):
        body = (
            self.as_user(self.cd_user)
            .get(
                "/country-planning-oversight/?presence_period=week&presence_groups_page=2&fy="
                + FY
            )
            .content.decode()
        )
        # The panel's filter and pager swap into the host that loads it.
        self.assertIn(
            '<div class="presence-host" data-presence-host data-pager-fragment="/dashboard/whos-online"',
            body,
        )
        self.assertIn(
            'hx-get="/dashboard/whos-online?presence_period=week&amp;presence_groups_page=2"',
            body,
        )
        panel = self.as_user(self.cd_user).get(
            "/dashboard/whos-online?presence_period=week"
        )
        self.assertContains(panel, "data-admin-presence")
        self.assertEqual(
            self.as_user(self.ia_user).get("/dashboard/whos-online").status_code, 403
        )

    def test_the_country_map_carries_the_portfolio(self):
        self.school("client", self.cceo)
        response = self.as_user(self.cd_user).get("/country-map/")
        self.assertContains(response, "Country Map")
        self.assertContains(response, 'id="country-portfolio"')
        self.assertIn(
            self.as_user(self.cceo_user).get("/country-map/").status_code, (302, 403)
        )
        legacy = self.as_user(self.cd_user).get(
            "/country-planning-oversight/?view=portfolio"
        )
        self.assertEqual(legacy.status_code, 302)
        self.assertTrue(legacy["Location"].startswith("/country-map/"))

    def test_the_sidebar_takes_the_director_to_country_oversight(self):
        from apps.core.navigation import CD, SIDEBAR_ITEMS

        items = [item for group in SIDEBAR_ITEMS for item in group["items"]]
        dashboard = next(item for item in items if item.get("page_key") == "dashboard")
        self.assertEqual(dashboard["role_urls"][CD], "/country-planning-oversight/")
        country_map = next(
            item for item in items if item.get("page_key") == "country_map"
        )
        self.assertEqual(country_map["url"], "/country-map/")
