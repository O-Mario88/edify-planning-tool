"""Execution & Completion, counted by the planning rulebook (owner audit,
2026-10-02: "look at all the updates you made for planning monitor and apply
to the execution and completion. The correct data fetching, tracking the
right execution").

What the planning tab and the Planning Monitor were held to on 2026-10-01,
for the two execution pages — Country Execution & Completion Oversight
(apps.planning.country_execution) and the Planning Monitor's Execution &
Completion tab (apps.planning.execution_monitor):

* the visits counted toward a person's 280 or 560 are Follow up, In-school
  Training and SSA Support, on every page;
* a Partner's visit sits under one person on every page: who handed it over
  or monitors it, before who holds the school;
* a hand-over a Partner has not dated keeps waiting when the year turns;
* every card is a doorway to the table of the records it counts — its number
  IS the table's row count — grouped by Programme Lead, with the School ID;
* the two execution pages agree, person by person;
* the tab follows the work as it changes.
"""

from __future__ import annotations

import io
from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from apps.partners.models import PartnerAssignment
from apps.planning.country_execution import service as esvc
from apps.planning.country_execution import tables as etables
from apps.planning.country_oversight import freshness
from apps.planning.country_oversight import service as psvc
from apps.planning.execution_monitor import execution_monitor
from apps.planning.test_country_execution_oversight import ExecutionWorld
from apps.planning.test_country_planning_oversight import FY, World

RECORDS = "/country-planning-oversight/execution/records"
QUERY = f"view=execution&period=fy&fy={FY}"


def annual(**filters) -> esvc.ExecFilters:
    return esvc.ExecFilters(fy=FY, period="fy", **filters)


class RulebookWorld(World):
    """Officer One's year: a follow-up delivered, an in-school training still
    to deliver, a donor visit delivered and a story visit verified."""

    def setUp(self):
        self.school_a = self.school("client", self.cceo)
        self.school_b = self.school("client", self.cceo)
        self.follow_up = self.activity(
            self.school_a,
            "training_follow_up_visit",
            status="submitted_to_pl",
            owner=self.cceo,
        )
        self.training = self.activity(
            self.school_a, "in_school_training", owner=self.cceo, on=40
        )
        self.donor = self.activity(
            self.school_b, "donor_visit", status="submitted_to_pl", owner=self.cceo
        )
        self.story = self.activity(
            self.school_b,
            "school_visit",
            status="ia_verified",
            owner=self.cceo,
            purpose_type="story_gathering",
            on=35,
        )

    def snapshot(self, **filters):
        return esvc.snapshot_for(self.cd_user, annual(**filters), refresh=True)

    def monitor(self):
        return execution_monitor(self.cd_user, fy=FY)

    def monitored(self, profile):
        people = {p.key: p for team in self.monitor()["teams"] for p in team.people}
        return people[profile.id]

    def exec_row(self, snapshot, profile):
        return esvc.find_owner(snapshot, profile.id)


# ── Which visits count ───────────────────────────────────────────────────────
class CountedVisitsTest(RulebookWorld):
    def test_every_activity_is_followed_and_only_the_rulebooks_visits_count(self):
        c = self.snapshot().tree.country
        # All four are execution to follow.
        self.assertEqual((c.due, c.executed, c.verified), (4, 3, 1))
        # Two are visits a person's 560 is made of: the follow-up, and the
        # in-school training (one visit and one training).
        self.assertEqual((c.v_planned, c.v_delivered, c.v_verified), (2, 1, 0))
        # The donor and the story visit are delivered, and not counted.
        self.assertEqual(c.v_outreach, 2)

    def test_the_visits_planned_are_the_planning_tabs(self):
        snapshot = self.snapshot()
        plan = psvc.snapshot_for(self.cd_user, psvc.Filters(fy=FY)).tree.country
        self.assertEqual(snapshot.tree.country.v_planned, plan.p_visits)
        # ... read against the same target: two Leads and three CCEOs.
        self.assertEqual(snapshot.targets[("country", "")], plan.target)
        self.assertEqual(plan.target, 2 * 280 + 3 * 560)
        self.assertEqual(snapshot.targets[("owner", self.cceo.id)], 560)
        self.assertEqual(snapshot.targets[("lead", self.pl.id)], 280 + 560 + 560)

    def test_a_week_has_no_target_of_its_own(self):
        week = timezone.localdate().strftime("%G-W%V")
        snapshot = esvc.snapshot_for(
            self.cd_user, esvc.ExecFilters(fy=FY, period="week", week=week)
        )
        self.assertEqual(snapshot.targets, {})

    def test_the_monitor_counts_the_same_visits(self):
        officer = self.monitored(self.cceo)
        self.assertEqual((officer.visits_planned, officer.visits_delivered), (2, 1))
        self.assertEqual((officer.outreach_planned, officer.outreach_delivered), (2, 2))
        # Every activity is still delivered work: due, delivered, overdue.
        self.assertEqual((officer.planned, officer.delivered), (4, 3))
        # An in-school training is one visit and one training.
        self.assertEqual(officer.trainings_planned, 1)
        self.assertEqual(officer.visits_target, 560)

    def test_the_monitors_overdue_is_named_for_what_it_counts(self):
        from apps.planning.execution_monitor import LIST_COLUMNS, LIST_LABELS

        self.assertEqual(LIST_LABELS["overdue"], "Past date, not delivered")
        self.assertEqual(
            dict((k, label) for k, label, _ in LIST_COLUMNS)["overdue"], "Past date"
        )
        body = (
            self.as_user(self.cd_user)
            .get(f"/planning-monitor/?view=execution&fy={FY}")
            .content.decode()
        )
        self.assertIn("Past Date, Not Delivered", body)
        self.assertNotIn("Overdue Work", body)

    def test_a_visit_sent_back_to_planning_is_not_a_visit_planned(self):
        self.activity(
            self.school_b, "school_visit", status="returned", owner=self.cceo, on=50
        )
        self.assertEqual(self.snapshot().tree.country.v_planned, 2)
        self.assertEqual(self.monitored(self.cceo).visits_planned, 2)

    def test_the_by_lead_charts_are_the_leads_rows(self):
        snapshot = self.snapshot()
        charts = {chart["id"]: chart for chart in esvc.lead_charts(snapshot)}
        delivery, visits = charts["cxo-delivery-chart"], charts["cxo-visits-chart"]
        self.assertEqual(delivery["categories"], ["Lead A", "Lead B"])
        for index, lead in enumerate(snapshot.tree.leads[:2]):
            # A bar is a partition: of the team's work in the period ...
            self.assertEqual(
                sum(series["data"][index] for series in delivery["series"]),
                lead.tally.due,
            )
            # ... and of the team's visit target.
            self.assertEqual(
                sum(series["data"][index] for series in visits["series"]),
                snapshot.targets[("lead", lead.key)],
            )
        # Lead A's bar is the Lead's own work and their CCEOs' together.
        self.assertEqual(delivery["table"]["rows"][0]["cells"][0], 4)
        self.assertEqual(visits["table"]["rows"][0]["cells"][:4], [1400, 2, 1, 0])

    def test_the_requirement_by_school_type_is_the_planning_tabs(self):
        self.school("core", self.cceo2)
        snapshot = self.snapshot()
        rows = {row["key"]: row for row in esvc.type_rows(snapshot)}
        plan = psvc.snapshot_for(self.cd_user, psvc.Filters(fy=FY)).tree
        self.assertEqual(rows["core"]["visit_slots"], plan.by_type["core"].visit_slots)
        self.assertEqual(rows["core"]["visit_slots"], 4)
        self.assertEqual(rows["client"]["visit_slots"], 2)
        # Nothing is verified against the requirement by a story visit.
        self.assertEqual(rows["client"]["visits_verified"], 0)
        self.assertEqual(rows["client"]["visits_left"], 2)
        self.assertEqual(rows[""]["visit_slots"], plan.country.visit_slots)
        self.assertTrue(rows[""]["is_total"])


# ── On time, by the day the work was delivered ───────────────────────────────
class OnTimeTest(World):
    """Owner, 2026-10-02: "on time" is read from the recorded delivery date,
    not from the day the officer pressed Complete."""

    def timing(self, **fields) -> str:
        from apps.planning.test_country_planning_oversight import day

        school = self.school("client", self.cceo)
        activity = self.activity(school, owner=self.cceo, on=30, **fields)
        snapshot = esvc.snapshot_for(self.cd_user, annual(), refresh=True)
        self.assertEqual(day(30), activity.planned_date)
        return next(r for r in snapshot.dataset.records if r.id == activity.id).timing

    def keyed(self, offset: int):
        from datetime import datetime, time

        from apps.planning.test_country_planning_oversight import day

        return timezone.make_aware(datetime.combine(day(offset), time(9)))

    def test_delivered_on_its_day_and_keyed_later_is_on_time(self):
        from apps.planning.test_country_planning_oversight import day

        self.assertEqual(
            self.timing(
                status="submitted_to_pl",
                actual_delivery_date=day(30),
                execution_started_at=self.keyed(33),
            ),
            "on_time",
        )

    def test_delivered_after_its_day_is_late_whenever_it_was_keyed(self):
        from apps.planning.test_country_planning_oversight import day

        self.assertEqual(
            self.timing(
                status="submitted_to_pl",
                actual_delivery_date=day(32),
                execution_started_at=self.keyed(29),
            ),
            "late",
        )

    def test_until_a_delivery_date_is_recorded_the_start_is_read(self):
        self.assertEqual(
            self.timing(
                status="completion_started", execution_started_at=self.keyed(31)
            ),
            "late",
        )
        self.assertEqual(
            self.timing(
                status="completion_started", execution_started_at=self.keyed(30)
            ),
            "on_time",
        )

    def test_the_ring_and_the_cards_say_what_they_count(self):
        school = self.school("client", self.cceo)
        self.activity(school, owner=self.cceo)
        snapshot = esvc.snapshot_for(self.cd_user, annual(), refresh=True)
        labels = [part["label"] for part in esvc.charts(snapshot)["on_time"]["parts"]]
        self.assertNotIn("Started late", labels)
        cards = {card["key"]: card for card in esvc.kpis(snapshot)}
        # Everything dated in the period, the days to come included: planned.
        self.assertEqual(cards["due"]["label"], "Activities Planned")
        self.assertIn("of planned", cards["started"]["note"])
        funnel = esvc.charts(snapshot)["funnel"]
        self.assertEqual(funnel["categories"][0], "Planned")


# ── Who a Partner's visit belongs to ─────────────────────────────────────────
class PartnerCreditTest(World):
    def setUp(self):
        # Officer Three (Lead B's) holds the school; Lead A handed it over.
        self.held = self.school("client", self.cceo3)
        self.visit = self.activity(
            self.held,
            "school_visit",
            status="partner_scheduled",
            partner=self.partner,
            partner_date_set_by="partner",
        )
        self.handover(
            self.held,
            self.partner,
            status="partner_scheduled",
            assigning_staff_id=self.pl.id,
            monitoring_staff_id=self.pl.id,
            scheduled_activity=self.visit,
        )

    def partner_due(self, snapshot, profile) -> int:
        row = esvc.find_owner(snapshot, profile.id)
        if row is None:
            return 0
        return sum(t.due for key, t in row.partners.items() if key != "__staff__")

    def test_it_sits_under_who_handed_it_over_on_every_page(self):
        snapshot = esvc.snapshot_for(self.cd_user, annual(), refresh=True)
        self.assertEqual(self.partner_due(snapshot, self.pl), 1)
        self.assertEqual(self.partner_due(snapshot, self.cceo3), 0)
        people = {
            p.key: p
            for team in execution_monitor(self.cd_user, fy=FY)["teams"]
            for p in team.people
        }
        self.assertEqual(people[self.pl.id].partner_scheduled, 1)
        self.assertEqual(people[self.cceo3.id].partner_scheduled, 0)
        plan = self.tree()
        self.assertEqual(self.owner_row(plan, self.pl).tally.pp_work, 1)
        self.assertEqual(self.owner_row(plan, self.cceo3).tally.pp_work, 0)

    def test_with_no_hand_over_it_is_the_monitors_then_the_school_holders(self):
        other = self.school("client", self.cceo3)
        self.activity(
            other,
            "school_visit",
            status="partner_scheduled",
            partner=self.partner,
            monitored_by_staff_id=self.cceo.id,
            on=31,
        )
        bare = self.school("client", self.cceo3)
        self.activity(
            bare, "school_visit", status="partner_scheduled", partner=self.partner
        )
        snapshot = esvc.snapshot_for(self.cd_user, annual(), refresh=True)
        self.assertEqual(self.partner_due(snapshot, self.cceo), 1)
        self.assertEqual(self.partner_due(snapshot, self.cceo3), 1)
        people = {
            p.key: p
            for team in execution_monitor(self.cd_user, fy=FY)["teams"]
            for p in team.people
        }
        self.assertEqual(people[self.cceo.id].partner_scheduled, 1)
        self.assertEqual(people[self.cceo3.id].partner_scheduled, 1)

    def test_a_hand_over_from_an_earlier_year_still_waits(self):
        waiting = self.handover(
            self.school("client", self.cceo),
            self.partner2,
            status="pending_scheduling",
            assigning_staff_id=self.cceo.id,
        )
        PartnerAssignment.objects.filter(id=waiting.id).update(
            created_at=timezone.now() - timedelta(days=400)
        )
        snapshot = esvc.snapshot_for(self.cd_user, annual(), refresh=True)
        rows = {row["name"]: row for row in esvc.partner_rows(snapshot)}
        self.assertEqual(rows["Partner Beta"]["unscheduled"], 1)
        # ... under the person who made it, and nobody else.
        mine = esvc.snapshot_for(self.cd_user, annual(cceo=self.cceo.id))
        theirs = esvc.snapshot_for(self.cd_user, annual(cceo=self.cceo2.id))
        self.assertEqual(
            {r["name"]: r["unscheduled"] for r in esvc.partner_rows(mine)},
            {"Partner Beta": 1},
        )
        self.assertEqual(esvc.partner_rows(theirs), [])


# ── The two execution pages agree ────────────────────────────────────────────
class OneReadingTest(RulebookWorld):
    def test_the_monitor_and_the_directors_tab_agree_person_by_person(self):
        held = self.school("client", self.cceo3)
        self.activity(
            held,
            "school_visit",
            status="awaiting_ia_verification",
            partner=self.partner,
            monitored_by_staff_id=self.cceo2.id,
        )
        self.activity(
            held,
            "school_visit_ssa_collection",
            status="awaiting_ia_verification",
            owner=self.pl,
            on=45,
        )
        snapshot = self.snapshot()
        people = {p.key: p for team in self.monitor()["teams"] for p in team.people}
        checked = 0
        for lead in snapshot.tree.leads:
            for owner in lead.owners:
                person = people.get(owner.key)
                if person is None:
                    continue
                checked += 1
                partner_due = sum(
                    t.due for key, t in owner.partners.items() if key != "__staff__"
                )
                with self.subTest(person=owner.name):
                    self.assertEqual(
                        (
                            person.visits_planned,
                            person.visits_delivered,
                            person.outreach_delivered,
                            person.partner_scheduled,
                        ),
                        (
                            owner.tally.v_planned,
                            owner.tally.v_delivered,
                            owner.tally.v_outreach,
                            partner_due,
                        ),
                    )
        self.assertGreaterEqual(checked, 3)
        totals, c = self.monitor()["totals"], snapshot.tree.country
        self.assertEqual(totals.visits_delivered, c.v_delivered)
        self.assertEqual(totals.visits_planned, c.v_planned)
        self.assertEqual(totals.partner_scheduled, snapshot.tree.partner_channel.due)


# ── Every card is a doorway to its records ───────────────────────────────────
class ExecutionTablesTest(ExecutionWorld):
    def live(self, **filters):
        """The page's own read (the reporting day is today)."""
        return esvc.snapshot_for(self.cd_user, annual(**filters), refresh=True)

    def test_a_cards_number_is_its_tables_row_count(self):
        for filters in (
            {},
            {"program_lead": self.pl.id},
            {"channel": "partner"},
            {"cceo": self.cceo.id},
            {"activity_type": "core_visit"},
        ):
            snapshot = self.live(**filters)
            for card in esvc.kpis(snapshot):
                key = card["key"]
                with self.subTest(filters=filters, card=key):
                    self.assertEqual(
                        len(etables.build(snapshot, key).rows),
                        int(card["value"].replace(",", "")),
                    )
                    self.assertIn(f"/execution/records/{key}?", card["href"])

    def test_the_visits_table_is_the_visits_planned(self):
        snapshot = self.live()
        table = etables.build(snapshot, "visits")
        self.assertEqual(len(table.rows), snapshot.tree.country.v_planned)
        self.assertTrue(all(row["staff"] != etables.NOBODY for row in table.rows))

    def test_rows_sit_under_their_lead_and_person_with_the_school_id(self):
        table = etables.build(self.live(), "due")
        self.assertEqual(table.spec.groups, ("lead", "staff"))
        self.assertEqual(
            [column.label for column in table.shown_columns][:6],
            [
                "Delivered By",
                "Activity",
                "Counts Toward Target",
                "School ID",
                "School / Cluster",
                "School Type",
            ],
        )
        leads = [row["lead"] for row in table.rows]
        self.assertEqual(leads, sorted(leads, key=["Lead A", "Lead B"].index))
        for row in table.rows:
            with self.subTest(row=row["school"]):
                self.assertTrue(row["school_id"].startswith("CPO-"))
        partner = next(row for row in table.rows if row["by"].startswith("Partner"))
        self.assertEqual(partner["staff"], "Officer One")  # the school's holder
        self.assertEqual(partner["counted"], "")
        # A heading states the balance at its level.
        self.assertIn("delivered", table.notes[("Lead A",)])
        self.assertIn("overdue", table.notes[("Lead A", "Officer One")])

    def test_a_table_opens_with_its_groups_and_exports_every_column(self):
        import openpyxl

        client = self.as_user(self.cd_user)
        for key in etables.TAB_ORDER:
            with self.subTest(table=key):
                page = client.get(f"{RECORDS}/{key}?{QUERY}")
                self.assertEqual(page.status_code, 200)
                body = page.content.decode()
                self.assertIn(etables.SPECS[key].title, body)
                if etables.build(self.live(), key).rows:
                    self.assertIn(f'data-consolidated-table="{key}"', body)
                    self.assertIn(">School ID</th>", body)
                else:
                    self.assertIn("Nothing in this selection.", body)
                export = client.get(f"{RECORDS}-export/{key}?{QUERY}")
                self.assertEqual(export.status_code, 200)
                sheet = openpyxl.load_workbook(io.BytesIO(export.content)).active
                headers = [cell.value for cell in sheet[1]]
                self.assertEqual(headers[0], "Programme Lead")
                self.assertIn("School ID", headers)
        body = client.get(f"{RECORDS}/due?{QUERY}").content.decode()
        self.assertIn("Lead A", body)
        self.assertIn("CPO-", body)
        self.assertIn('class="edify-group-head"', body)

    def test_an_unknown_table_is_not_found_and_schools_stay_withheld(self):
        client = self.as_user(self.cd_user)
        self.assertEqual(client.get(f"{RECORDS}/nope?{QUERY}").status_code, 404)
        self.assertEqual(client.get(f"{RECORDS}-export/nope?{QUERY}").status_code, 404)
        body = self.as_user(self.rvp_user).get(f"{RECORDS}/due?{QUERY}")
        if body.status_code == 200:
            text = body.content.decode()
            self.assertIn("Activity-level rows are not part of this role", text)
            self.assertNotIn("CPO-", text)

    def test_the_activity_lists_and_the_workbook_carry_the_school_id(self):
        import openpyxl

        client = self.as_user(self.cd_user)
        drawer = client.get(
            f"/country-planning-oversight/execution/drawer?kind=activities&stage=due&{QUERY}",
            HTTP_HX_REQUEST="true",
        ).content.decode()
        self.assertIn(">School ID</th>", drawer)
        self.assertIn(self.core.school_id, drawer)
        book = openpyxl.load_workbook(
            io.BytesIO(
                client.get(
                    f"/country-planning-oversight/execution/export?{QUERY}"
                ).content
            )
        )
        activities = next(s for s in book.worksheets if s.title.startswith("Activit"))
        self.assertEqual([c.value for c in activities[1]][:3][1], "School ID")

    def test_the_page_draws_the_new_sections(self):
        body = (
            self.as_user(self.cd_user)
            .get(f"/country-planning-oversight/?{QUERY}")
            .content.decode()
        )
        for text in (
            "Delivery by Program Lead",
            "Visits Delivered Against Target by Program Lead",
            "Verified Against the Requirement by School Type",
            f'href="{RECORDS}/overdue?',
            "Open the table of these visits",
        ):
            with self.subTest(text=text):
                self.assertIn(text, body)
        charts = body[body.index('<section class="cxo-charts"') :]
        charts = charts[: charts.index("</section>")]
        self.assertEqual(charts.count('<figure class="cpo-chart cxo-chart"'), 4)
        self.assertEqual(charts.count('<details class="cpo-chart-data" open>'), 4)


# ── The tab follows the work ─────────────────────────────────────────────────
@override_settings(DASHBOARD_CACHE_SECONDS=300)
class ExecutionFreshnessTest(World):
    def setUp(self):
        cache.clear()
        esvc._HELD.clear()
        psvc._HELD.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(esvc._HELD.clear)
        self.addCleanup(psvc._HELD.clear)

    def started(self) -> int:
        return esvc.snapshot_for(self.cd_user, annual()).tree.country.started

    def test_work_started_reaches_the_tab_without_waiting_for_the_cache(self):
        school = self.school("client", self.cceo)
        with patch.object(freshness, "SETTLE_SECONDS", 0):
            self.assertEqual(self.started(), 0)
            self.activity(
                school, "school_visit", status="completion_started", owner=self.cceo
            )
            self.assertEqual(self.started(), 1)

    def test_nothing_is_rebuilt_while_nothing_changes(self):
        from apps.planning.country_execution import dataset as ds

        self.school("client", self.cceo)
        with patch.object(freshness, "SETTLE_SECONDS", 0):
            self.assertEqual(self.started(), 0)
            with patch.object(ds, "build", side_effect=AssertionError("rebuilt")):
                self.assertEqual(self.started(), 0)
