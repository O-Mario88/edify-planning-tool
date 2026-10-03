"""How a person's year is shared between staff and the Partner.

Owner, 2026-10-03. A Programme Lead plans at most 280 visits a year and a CCEO
560. The Core schools a person holds take theirs first, two each; the capacity
left takes one visit at each Client, Core Trained and Core Graduate school
until it runs out; every school past that is the Partner's. So the Partner's
target is the other two visits at each Core school plus the schools beyond
staff capacity: "the overflow should be the partner target". Trainings run
beside the visits and use none of the ceiling.

And the ceiling warns, it never refuses: "platform should not refuse just warn
and let it through". A visit planned past it is saved, counted and SHOWN.

Three things the Country Director's page got wrong before, each held here:

* a school a Partner held and had not dated was in neither "Schools Planned"
  nor "Not Yet Planned", so the two did not add up to the schools (279 of
  16,156 on the owner's screen);
* staff were measured against all four visits of a Core package, two of which
  are the Partner's (22% where the staff half stood at 43%);
* "Planned Twice" was one figure for a Core school's legitimate second staff
  visit gone to a third, and a client school booked twice.
"""

from __future__ import annotations

from django.test import RequestFactory, SimpleTestCase

from apps.activities.models import Activity
from apps.planning import staff_plan
from apps.planning.country_oversight import policy, rules
from apps.planning.country_oversight import service as svc
from apps.planning.planning_monitor import OfficerMonitor, SchoolState
from apps.planning.test_country_planning_oversight import FY, World, day
from apps.planning.test_standard_support_scheduling import StandardSupportBase
from apps.schools.models import School


class WorkloadRuleTest(SimpleTestCase):
    """The share-out itself: the figures of the owner's two examples."""

    def test_a_programme_lead_with_50_core_and_250_client_schools(self):
        share = rules.workload(rules.target_for(rules.PROGRAM_LEAD_ROLE), 50, 250)
        self.assertEqual(share.cap, 280)
        self.assertEqual(share.staff_core_visits, 100)
        self.assertEqual(share.staff_client_visits, 180)
        self.assertEqual(share.staff_visits, 280)
        self.assertEqual(share.partner_client_visits, 70)
        self.assertEqual(share.partner_core_visits, 100)
        self.assertEqual(share.partner_visits, 170)
        self.assertEqual(share.staff_core_trainings, 100)
        self.assertEqual(share.partner_core_trainings, 100)
        self.assertEqual(share.warning, "")

    def test_a_cceo_with_70_core_and_444_client_schools(self):
        share = rules.workload(rules.target_for(rules.CCEO_ROLE), 70, 444)
        self.assertEqual(share.cap, 560)
        self.assertEqual(share.staff_core_visits, 140)
        self.assertEqual(share.staff_client_visits, 420)
        self.assertEqual(share.staff_visits, 560)
        self.assertEqual(share.partner_client_visits, 24)
        self.assertEqual(share.partner_core_visits, 140)
        self.assertEqual(share.partner_core_trainings, 140)

    def test_core_schools_at_the_ceiling_leave_every_other_school_to_the_partner(self):
        # 140 Core schools are exactly a Lead's 280: nothing is over, and no
        # staff visit is left for a client school.
        at = rules.workload(280, 140, 30)
        self.assertEqual(at.warning, rules.OVER_CAPACITY_CORE_ONLY)
        self.assertEqual((at.core_over, at.staff_client_visits), (0, 0))
        self.assertEqual(at.partner_client_visits, 30)
        # One more Core school and two of its staff visits are past it.
        past = rules.workload(280, 141, 30)
        self.assertEqual(past.warning, rules.OVER_CAPACITY_CORE_ONLY)
        self.assertEqual((past.core_over, past.partner_client_visits), (2, 30))
        self.assertEqual(rules.workload(560, 279, 5).warning, "")
        self.assertEqual(
            rules.workload(560, 280, 5).warning, rules.OVER_CAPACITY_CORE_ONLY
        )

    def test_a_portfolio_below_the_ceiling_hands_no_client_school_over(self):
        share = rules.workload(560, 40, 300)
        self.assertEqual(share.staff_client_visits, 300)
        self.assertEqual(share.partner_client_visits, 0)
        self.assertEqual(share.staff_visits, 380)
        # The other half of each Core package is still the Partner's.
        self.assertEqual(share.partner_visits, 80)

    def test_nobody_else_has_a_ceiling_to_spend(self):
        share = rules.workload_for("Accountant", {"core": 3, "client": 4})
        self.assertEqual((share.cap, share.staff_client_visits), (0, 0))
        self.assertEqual(share.partner_client_visits, 4)
        self.assertEqual(share.warning, "")

    def test_core_trained_and_core_graduate_schools_share_the_client_capacity(self):
        share = rules.workload_for(
            rules.CCEO_ROLE,
            {"core": 100, "client": 300, "core_trained": 50, "core_graduate": 50},
        )
        self.assertEqual(share.client_schools, 400)
        self.assertEqual(share.staff_client_visits, 360)
        self.assertEqual(share.partner_client_visits, 40)

    def test_past_the_ceiling_is_a_number_never_a_refusal(self):
        self.assertEqual(rules.over_ceiling(560, 560), 0)
        self.assertEqual(rules.over_ceiling(694, 560), 134)
        self.assertEqual(rules.over_ceiling(50, 0), 0)

    def test_the_planning_monitor_reads_the_same_share(self):
        def officer(role, cap, core, client):
            row = OfficerMonitor(key="p", name="p", lead_id="", lead_name="", role=role)
            row.visits_target = cap
            row.schools = [
                SchoolState(
                    id=str(index),
                    code="",
                    name="",
                    school_type="core" if index < core else "client",
                    district="",
                    cluster_id="",
                    cluster_name="",
                    clustered=True,
                    officer_id="p",
                    officer_name="p",
                    lead_id="",
                    lead_name="",
                )
                for index in range(core + client)
            ]
            return row

        lead = officer("Program Lead", 280, 50, 250)
        share = rules.workload(280, 50, 250)
        self.assertEqual(lead.core_visit_target, share.staff_core_visits)
        self.assertEqual(lead.client_visit_target, share.staff_client_visits)
        self.assertEqual(lead.partner_needed, share.partner_client_visits)
        self.assertEqual(lead.core_partner_target, share.partner_core_visits)
        self.assertEqual(lead.core_only_people, 0)
        self.assertEqual(officer("Program Lead", 280, 140, 5).core_only_people, 1)
        over = officer("CCEO", 560, 10, 10)
        over.planned_core, over.planned_client = 20, 674
        self.assertEqual((over.over_ceiling, over.over_ceiling_people), (134, 1))
        self.assertEqual(over.visit_tone, "danger")


class Bulk:
    """Portfolios and plans too large to make one row at a time."""

    def portfolio(self, owner, *, core, client):
        rows = []
        for index in range(core + client):
            type(self)._school_seq += 1
            rows.append(
                School(
                    school_id=f"WL-{owner.id[-6:]}-{self._school_seq:05d}",
                    name=f"Workload {self._school_seq:05d}",
                    school_type="core" if index < core else "client",
                    region=self.region,
                    district=self.district,
                    account_owner_id=owner.id,
                    account_owner_status="matched",
                )
            )
        return School.objects.bulk_create(rows)

    def visits(self, owner, schools, each=1):
        Activity.objects.bulk_create(
            [
                Activity(
                    activity_type="training_follow_up_visit",
                    school=school,
                    fy=FY,
                    quarter="Q1",
                    planned_date=day(20 + (index + n) % 200),
                    status="scheduled",
                    responsible_staff_id=owner.id,
                    delivery_type="staff",
                )
                for index, school in enumerate(schools)
                for n in range(each)
            ]
        )

    def snapshot(self, user=None, **params):
        request = RequestFactory().get(
            "/country-planning-oversight/", {"fy": FY, **params}
        )
        request.user = user or self.cd_user
        return svc.snapshot_for(request.user, svc.read_filters(request))


class AllocationTest(Bulk, World):
    """The same two examples, school by school through the page's engine."""

    def test_the_programme_lead_example_adds_up_to_exactly_280(self):
        self.portfolio(self.pl, core=50, client=250)
        tally = self.owner_row(self.snapshot().tree, self.pl).tally
        self.assertEqual(tally.core_staff_slots, 100)
        self.assertEqual(tally.client_staff_expected, 180)
        self.assertEqual(tally.staff_expected, 280)
        self.assertEqual(tally.client_partner_expected, 70)
        self.assertEqual(tally.core_partner_slots, 100)
        self.assertEqual(tally.partner_expected, 170)
        # Trainings follow the visits: two and two a Core school, and each
        # other school's one goes where its visit does.
        self.assertEqual(tally.training_staff_slots, 100 + 180)
        self.assertEqual(tally.training_partner_slots, 100 + 70)
        self.assertEqual(tally.training_slots, 4 * 50 + 250)
        self.assertEqual((tally.deficit, tally.core_only_people), (0, 0))

    def test_the_cceo_example_adds_up_to_exactly_560(self):
        self.portfolio(self.cceo, core=70, client=444)
        tally = self.owner_row(self.snapshot().tree, self.cceo).tally
        self.assertEqual(tally.core_staff_slots, 140)
        self.assertEqual(tally.client_staff_expected, 420)
        self.assertEqual(tally.staff_expected, 560)
        self.assertEqual(tally.client_partner_expected, 24)
        self.assertEqual(tally.partner_expected, 140 + 24)

    def test_the_spillover_is_whole_schools_each_named_once(self):
        self.portfolio(self.cceo, core=70, client=444)
        dataset = svc.dataset_for(self.cd_user, self.snapshot().tree.window)
        mine = [s for s in dataset.facts.values() if s.owner_key == self.cceo.id]
        partner_schools = [
            s
            for s in mine
            if s.school_type == "client"
            and dataset.allocations[s.id].partner
            and not dataset.allocations[s.id].staff
        ]
        staff_schools = [
            s
            for s in mine
            if s.school_type == "client" and dataset.allocations[s.id].staff
        ]
        self.assertEqual((len(staff_schools), len(partner_schools)), (420, 24))

    def test_core_schools_taking_the_whole_ceiling_are_flagged_not_hidden(self):
        self.portfolio(self.pl, core=140, client=10)
        snapshot = self.snapshot()
        row = self.owner_row(snapshot.tree, self.pl)
        self.assertEqual(row.tally.core_only_people, 1)
        self.assertEqual(row.tally.deficit, 0)
        self.assertEqual(row.tally.client_staff_expected, 0)
        self.assertEqual(row.tally.client_partner_expected, 10)
        self.assertEqual(snapshot.tree.country.core_only_people, 1)
        self.assertEqual(svc.capacity(snapshot)["core_only_people"], 1)
        rows = (
            self.as_user(self.cd_user)
            .get(
                f"/country-planning-oversight/rows?level=lead&key={self.pl.id}&fy={FY}",
                HTTP_HX_REQUEST="true",
            )
            .content.decode()
        )
        self.assertIn("Core schools take the whole ceiling", rows)

    def test_the_capacity_figures_are_the_tables_column_totals(self):
        self.portfolio(self.pl, core=50, client=250)
        self.portfolio(self.cceo, core=70, client=444)
        snapshot = self.snapshot()
        capacity = svc.capacity(snapshot)
        leads, cceos = capacity["gauges"]
        self.assertEqual((leads["people"], leads["cap"]), ("2", "560"))
        self.assertEqual((cceos["people"], cceos["cap"]), ("3", "1,680"))
        country = svc.row_cells(snapshot.tree.country)
        self.assertEqual(capacity["partner_target"], country["partner_target"])
        self.assertEqual(capacity["partner_target"], "334")
        self.assertEqual(capacity["beyond_staff"], country["beyond_staff"])
        self.assertEqual(capacity["beyond_staff"], "94")


class CeilingWarnsTest(Bulk, World):
    def test_a_plan_past_the_ceiling_is_counted_and_shown(self):
        schools = self.portfolio(self.pl, core=20, client=241)
        self.visits(self.pl, schools[:20], each=2)
        self.visits(self.pl, schools[20:])
        snapshot = self.snapshot()
        row = self.owner_row(snapshot.tree, self.pl)
        self.assertEqual((row.tally.p_visits, row.tally.target), (281, 280))
        self.assertEqual(
            (row.tally.p_core_visits, row.tally.p_client_visits), (40, 241)
        )
        self.assertEqual((row.tally.over_cap, row.tally.over_cap_people), (1, 1))
        cells = svc.row_cells(row.tally)
        self.assertEqual(cells["plan_tone"], "over")
        self.assertEqual(cells["client_plan_tone"], "over")
        # A team and the country are sums of their people, so a colleague
        # still short of their own ceiling cancels nothing.
        lead = self.lead_row(snapshot.tree, self.pl)
        self.assertEqual((lead.tally.over_cap, lead.tally.over_cap_people), (1, 1))
        self.assertEqual(snapshot.tree.country.over_cap, 1)
        capacity = svc.capacity(snapshot)
        self.assertEqual((capacity["over_cap_people"], capacity["over_cap"]), (1, "1"))
        client = self.as_user(self.cd_user)
        page = client.get(f"/country-planning-oversight/?fy={FY}").content.decode()
        self.assertIn("1 over the ceiling by 1", page)
        rows = client.get(
            f"/country-planning-oversight/rows?level=lead&key={self.pl.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        ).content.decode()
        self.assertIn("1 over the 280 ceiling", rows)

    def test_at_the_ceiling_nothing_is_flagged(self):
        schools = self.portfolio(self.pl, core=0, client=280)
        self.visits(self.pl, schools)
        row = self.owner_row(self.snapshot().tree, self.pl)
        self.assertEqual((row.tally.p_visits, row.tally.over_cap), (280, 0))
        self.assertEqual(svc.row_cells(row.tally)["plan_tone"], "good")
        self.assertEqual(staff_plan.ceiling_notice(self.pl_user, FY), "")

    def test_the_person_is_told_and_the_sentence_says_what_to_do(self):
        schools = self.portfolio(self.cceo, core=0, client=561)
        self.visits(self.cceo, schools)
        notice = staff_plan.ceiling_notice(self.cceo_user, FY)
        self.assertIn("561 visits", notice)
        self.assertIn("1 past the 560", notice)
        self.assertIn("Partner", notice)
        # Somebody with no ceiling is never told anything.
        self.assertEqual(staff_plan.ceiling_notice(self.cd_user, FY), "")

    def test_a_quarter_is_not_read_against_the_years_ceiling(self):
        schools = self.portfolio(self.pl, core=0, client=281)
        self.visits(self.pl, schools)
        row = self.owner_row(
            self.snapshot(period="quarter", quarter="Q1").tree, self.pl
        )
        self.assertEqual(row.tally.over_cap, 0)

    def test_the_confirmation_carries_the_warning(self):
        from apps.frontend.views.planning_views import (
            _ceiling_notice,
            _saved_without_leaving,
        )

        schools = self.portfolio(self.cceo, core=0, client=561)
        self.visits(self.cceo, schools)
        request = RequestFactory().post("/planning/schedule")
        request.user = self.cceo_user
        notice = _ceiling_notice(request, day(30).isoformat())
        self.assertIn("past the 560", notice)
        body = _saved_without_leaving(
            "Visit scheduled.", notice=notice
        ).content.decode()
        self.assertIn("Visit scheduled.", body)
        self.assertIn("data-ceiling-notice", body)
        self.assertIn("past the 560", body)
        self.assertNotIn(
            "data-ceiling-notice",
            _saved_without_leaving("Visit scheduled.").content.decode(),
        )


class SchedulingPastTheCeilingTest(StandardSupportBase):
    """The door itself: the 561st visit is saved like the first."""

    def test_the_visit_that_passes_the_ceiling_is_saved(self):
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.core.enums import SsaIntervention
        from apps.core.fy import get_operational_fy
        from apps.planning.test_standard_support_scheduling import (
            _at,
            _schedulable_date,
        )

        when = _schedulable_date()
        fy = get_operational_fy(when)
        others = list(School.objects.filter(school_id__startswith="STD-MEM-"))
        Activity.objects.bulk_create(
            [
                Activity(
                    activity_type="training_follow_up_visit",
                    school=others[index % len(others)],
                    fy=fy,
                    planned_date=when,
                    status="scheduled",
                    responsible_staff_id=self.staff.id,
                    delivery_type="staff",
                )
                for index in range(560)
            ]
        )
        self.assertEqual(staff_plan.ceiling_notice(self.user, fy), "")
        result = self.schedule(
            schoolId=self.school.school_id,
            scheduledDate=_at(when).isoformat(),
            catalogueItemId=resolve_item_for_workflow_kind("school_visit").id,
            focusIntervention=SsaIntervention.LEADERSHIP,
            activityPurposeText="One past the ceiling",
        )
        saved = Activity.objects.get(id=result["id"])
        self.assertEqual(saved.status, "scheduled")
        self.assertEqual(
            staff_plan.visit_tally([self.staff.id, self.user.id], fy).total, 561
        )
        self.assertIn("1 past the 560", staff_plan.ceiling_notice(self.user, fy))

    def test_the_planning_page_saves_it_and_says_so(self):
        from django.test import Client

        from apps.activity_catalogue.services import resolve_item_for_workflow_kind
        from apps.core.enums import SsaIntervention
        from apps.core.fy import get_operational_fy
        from apps.planning.test_standard_support_scheduling import _schedulable_date

        when = _schedulable_date()
        fy = get_operational_fy(when)
        others = list(School.objects.filter(school_id__startswith="STD-MEM-"))
        Activity.objects.bulk_create(
            [
                Activity(
                    activity_type="training_follow_up_visit",
                    school=others[index % len(others)],
                    fy=fy,
                    planned_date=when,
                    status="scheduled",
                    responsible_staff_id=self.staff.id,
                    delivery_type="staff",
                )
                for index in range(560)
            ]
        )
        School.objects.filter(id=self.school.id).update(
            account_owner_id=self.staff.id, account_owner_status="matched"
        )
        client = Client()
        client.force_login(self.user)
        response = client.post(
            "/planning/schedule-action",
            {
                "school_id": self.school.school_id,
                "activity_type": "school_visit",
                "scheduled_date": str(when),
                "catalogue_item_id": resolve_item_for_workflow_kind("school_visit").id,
                "require_catalogue": "yes",
                "focus_intervention": SsaIntervention.LEADERSHIP,
                "activity_goal": "One past the ceiling",
                "delivery_type": "staff",
                "executor_type": "staff",
            },
            HTTP_HX_REQUEST="true",
        )
        body = response.content.decode()
        self.assertEqual(response.status_code, 200, body[:600])
        self.assertIn("scheduled", body)
        self.assertIn("data-ceiling-notice", body)
        self.assertIn("561 visits", body)
        self.assertIn("1 past the 560", body)
        self.assertEqual(
            staff_plan.visit_tally([self.staff.id, self.user.id], fy).total, 561
        )


class SchoolsAddUpTest(Bulk, World):
    """Every school that needs a visit is in exactly one of four places."""

    STATUS = ("planned_full", "planned_part", "awaiting_partner", "unplanned")

    def world(self):
        # Core: nothing, one staff visit, both staff visits, the whole
        # package, and one a Partner holds and has not dated.
        core = [self.school("core", self.cceo) for _ in range(5)]
        self.activity(core[1], "core_visit", owner=self.cceo)
        for n in range(2):
            self.activity(core[2], "core_visit", owner=self.cceo, on=30 + n)
            self.activity(core[3], "core_visit", owner=self.cceo, on=30 + n)
            self.activity(
                core[3],
                "core_visit",
                partner=self.partner,
                status="partner_scheduled",
                partner_date_set_by="partner",
                on=50 + n,
            )
        self.handover(core[4], self.partner, status="pending_scheduling")
        # Client-rule schools: nobody, staff, a Partner waiting, a Partner
        # dated, and one booked twice.
        nobody = self.school("client", self.cceo2)
        staff = self.school("client", self.cceo2)
        waiting = self.school("core_trained", self.cceo2)
        dated = self.school("core_graduate", self.cceo3)
        twice = self.school("client", self.cceo3)
        self.activity(staff, "training_follow_up_visit", owner=self.cceo2)
        self.handover(waiting, self.partner2, status="pending_scheduling")
        self.activity(
            dated,
            "training_follow_up_visit",
            partner=self.partner,
            status="partner_scheduled",
            partner_date_set_by="partner",
        )
        self.activity(twice, "training_follow_up_visit", owner=self.cceo3)
        self.activity(twice, "training_follow_up_visit", owner=self.cceo3, on=60)
        self.school("champion", self.cceo3)
        self.school("client", None)
        return {"nobody": nobody, "waiting": waiting, "core": core}

    def number(self, text) -> int:
        return int(str(text).replace(",", ""))

    def assertAddsUp(self, rows):
        for row in rows:
            with self.subTest(row=row["label"]):
                self.assertTrue(row["adds_up"], row)
                self.assertEqual(row["unaccounted"], 0)

    def test_the_four_statuses_add_up_to_the_schools_of_every_type(self):
        self.world()
        snapshot = self.snapshot()
        rows = svc.type_rows(snapshot)
        self.assertAddsUp(rows)
        by_key = {row["key"]: row for row in rows}
        for key, schools in (("core", 5), ("client", 4), ("core_trained", 1)):
            with self.subTest(school_type=key):
                row = by_key[key]
                self.assertEqual(self.number(row["schools"]), schools)
                self.assertEqual(
                    sum(self.number(row[name]) for name in self.STATUS), schools
                )
        core = by_key["core"]
        self.assertEqual(
            tuple(core[name] for name in self.STATUS), ("1", "2", "1", "1")
        )
        # A school a Partner holds and has not dated is in the count, under
        # its own heading: it used to be in none of them.
        self.assertEqual(by_key["core_trained"]["awaiting_partner"], "1")
        self.assertEqual(by_key["core_trained"]["unplanned"], "0")
        total = rows[-1]
        self.assertTrue(total["is_total"])
        for name in ("schools", *self.STATUS):
            with self.subTest(column=name):
                self.assertEqual(
                    self.number(total[name]),
                    sum(self.number(row[name]) for row in rows[:-1]),
                )
        # The Champion school needs no visit: in the schools, in no status.
        self.assertEqual(
            sum(self.number(total[name]) for name in self.STATUS),
            self.number(total["schools"]) - 1,
        )

    def test_they_add_up_under_every_filter_and_period(self):
        self.world()
        for params in (
            {"channel": "staff"},
            {"channel": "partner"},
            {"school_type": "core"},
            {"cluster_status": "unclustered"},
            {"program_lead": self.pl.id},
            {"partner": self.partner.id},
            {"planning_status": "partial"},
            {"period": "quarter", "quarter": "Q1"},
            {"period": "quarter", "quarter": "Q3"},
            {"period": "month", "month": "11"},
        ):
            with self.subTest(params=params):
                self.assertAddsUp(svc.type_rows(self.snapshot(**params)))

    def test_every_person_and_team_adds_up_too(self):
        self.world()
        tree = self.snapshot().tree
        tallies = [tree.country]
        for lead in tree.leads:
            tallies.append(lead.tally)
            tallies.extend(owner.tally for owner in lead.owners)
        for tally in tallies:
            self.assertEqual(
                tally.planned_full
                + tally.planned_part
                + tally.partner_to_plan
                + tally.unplanned,
                tally.visit_schools,
            )

    def test_each_count_is_the_list_it_opens(self):
        from apps.planning.country_oversight import tables

        world = self.world()
        snapshot = self.snapshot()
        rows = {row["key"]: row for row in svc.type_rows(snapshot)}
        request = RequestFactory().get(
            "/country-planning-oversight/table/not-planned", {"fy": FY}
        )
        request.user = self.cd_user
        table = tables.build(request.user, svc.read_filters(request), "not-planned")
        listed = {row["school_id"] for row in table.rows}
        self.assertEqual(len(listed), self.number(rows[""]["unplanned"]))
        self.assertIn(world["nobody"].school_id, listed)
        self.assertNotIn(world["waiting"].school_id, listed)

    def test_a_second_core_visit_is_not_a_duplicate_and_a_third_is_named(self):
        world = self.world()
        third = world["core"][2]
        self.activity(third, "core_visit", owner=self.cceo, on=90)
        rows = {row["key"]: row for row in svc.type_rows(self.snapshot())}
        core = rows["core"]
        # Both staff visits planned at two schools: the staff half is done.
        self.assertEqual(core["core_staff_done"], "2")
        self.assertEqual((core["duplicate_bookings"], core["over_package"]), (0, 1))
        self.assertEqual(
            (rows["client"]["duplicate_bookings"], rows["client"]["over_package"]),
            (1, 0),
        )
        total = rows[""]
        self.assertEqual((total["duplicate_bookings"], total["over_package"]), (1, 1))
        self.assertEqual(
            total["duplicate_bookings"] + total["over_package"], total["duplicates"]
        )


class EachSideAgainstItsOwnTargetTest(Bulk, World):
    def test_staff_are_measured_against_two_visits_a_core_school_not_four(self):
        schools = [self.school("core", self.cceo) for _ in range(4)]
        for school in schools[:2]:
            for n in range(2):
                self.activity(school, "core_visit", owner=self.cceo, on=30 + n)
        core = next(r for r in svc.type_rows(self.snapshot()) if r["key"] == "core")
        self.assertEqual((core["visit_slots"], core["staff_target"]), ("16", "8"))
        self.assertEqual((core["staff"], core["staff_share"]), ("4", 50))
        # All four visits together are still read, beside it.
        self.assertEqual(core["slot_share"], 25)
        self.assertEqual(core["partner_target"], "8")

    def test_a_school_with_a_partner_shows_under_the_partners_target(self):
        """The Partner side read 0 while Partners held schools, because only
        a visit the Partner had dated was shown. What a Partner holds is now
        beside it, against the same target."""
        core = self.school("core", self.cceo)
        self.handover(core, self.partner, status="pending_scheduling")
        snapshot = self.snapshot()
        row = next(r for r in svc.type_rows(snapshot) if r["key"] == "core")
        self.assertEqual(
            (row["partner_target"], row["partner_assigned"], row["partner_scheduled"]),
            ("2", "1", "0"),
        )
        self.assertEqual(row["partner_assigned_share"], 50)
        self.assertEqual(row["with_partner"], "1")
        cells = svc.row_cells(self.owner_row(snapshot.tree, self.cceo).tally)
        self.assertEqual(cells["partner_assigned_of"], "1 / 2")
        self.assertEqual(cells["partner_scheduled"], "0")
        # Dated by the Partner, it is planned as well as assigned.
        self.activity(
            core,
            "core_visit",
            partner=self.partner,
            status="partner_scheduled",
            partner_date_set_by="partner",
        )
        row = next(r for r in svc.type_rows(self.snapshot()) if r["key"] == "core")
        self.assertEqual(
            (row["partner_assigned"], row["partner_scheduled"]), ("2", "1")
        )
        self.assertEqual(row["partner_scheduled_share"], 50)

    def test_the_partners_target_is_core_halves_plus_the_spillover(self):
        self.portfolio(self.cceo, core=70, client=444)
        snapshot = self.snapshot()
        rows = {row["key"]: row for row in svc.type_rows(snapshot)}
        self.assertEqual(rows["core"]["partner_target"], "140")
        self.assertEqual(rows["client"]["staff_target"], "420")
        self.assertEqual(rows["client"]["partner_target"], "24")
        self.assertEqual(rows["client"]["beyond_staff"], "24")
        self.assertEqual(rows[""]["partner_target"], "164")
        cells = svc.row_cells(self.owner_row(snapshot.tree, self.cceo).tally)
        self.assertEqual(
            (cells["core_target"], cells["client_target"], cells["partner_target"]),
            ("140", "420", "164"),
        )

    def test_staff_planning_a_spillover_school_reads_as_past_the_staff_target(self):
        schools = self.portfolio(self.pl, core=140, client=3)
        self.visits(self.pl, schools[140:])
        row = next(r for r in svc.type_rows(self.snapshot()) if r["key"] == "client")
        self.assertEqual((row["staff_target"], row["staff"]), ("0", "3"))
        self.assertEqual(row["partner_target"], "3")

    def test_trainings_are_split_like_the_visits(self):
        core = self.school("core", self.cceo, cluster=self.cluster)
        client = self.school("client", self.cceo, cluster=self.cluster)
        # Staff deliver a group training both schools are on; a Partner has
        # dated one in-school training at the Core school and holds another.
        self.session("cluster_training", [core, client])
        self.activity(
            core,
            "in_school_training",
            partner=self.partner,
            status="partner_scheduled",
            partner_date_set_by="partner",
        )
        self.handover(core, self.partner, kind="training", status="pending_scheduling")
        tally = self.snapshot().tree.country
        self.assertEqual(
            (tally.training_staff_slots, tally.training_partner_slots), (2 + 1, 2)
        )
        self.assertEqual((tally.training_staff, tally.training_partner), (2, 1))
        self.assertEqual(tally.training_partner_assigned, 2)
        self.assertEqual(tally.training, tally.training_staff + tally.training_partner)
        self.assertEqual(
            tally.training_slots,
            tally.training_staff_slots + tally.training_partner_slots,
        )
        row = next(r for r in svc.type_rows(self.snapshot()) if r["key"] == "core")
        self.assertEqual(
            (
                row["training_staff_target"],
                row["training_staff"],
                row["training_partner_target"],
                row["training_partner_assigned"],
                row["training_partner"],
            ),
            ("2", "1", "2", "2", "1"),
        )

    def test_a_group_training_a_partner_delivers_is_on_the_partners_half(self):
        core = self.school("core", self.cceo, cluster=self.cluster)
        session = self.session("cluster_training", [core])
        Activity.objects.filter(id=session.id).update(
            delivery_type="partner", assigned_partner_id=self.partner.id
        )
        tally = self.snapshot().tree.country
        self.assertEqual((tally.training_staff, tally.training_partner), (0, 1))

    def test_a_spillover_schools_training_is_the_partners_too(self):
        self.portfolio(self.pl, core=140, client=3)
        tally = self.owner_row(self.snapshot().tree, self.pl).tally
        self.assertEqual(tally.training_staff_slots, 280)
        self.assertEqual(tally.training_partner_slots, 280 + 3)


class PageTest(Bulk, World):
    def page(self):
        return (
            self.as_user(self.cd_user)
            .get(f"/country-planning-oversight/?fy={FY}")
            .content.decode()
        )

    def test_each_table_is_read_one_way_at_a_time(self):
        self.school("core", self.cceo)
        body = self.page()
        types = body[body.index('aria-labelledby="cpo-types-name"') :]
        types = types[: types.index("</section>")]
        for label in ("Schools", "Visits", "Trainings"):
            with self.subTest(tab=label):
                self.assertRegex(types, rf"<button[^>]*data-edify-tab[^>]*>{label}<")
        self.assertEqual(types.count("<table"), 1)
        # The first reading is drawn at once; the others wait for their tab.
        self.assertIn(
            '<th scope="col" data-col="schools" x-show="view === \'schools\'">Schools</th>',
            types,
        )
        self.assertRegex(
            types,
            r'<th scope="col" data-col="visits" x-show="view === \'visits\'" x-cloak[^>]*>Visits<br>Needed</th>',
        )
        people = body[body.index('aria-labelledby="cpo-drill-name"') :]
        people = people[: people.index("</section>")]
        for label in ("Workload", "Schools", "Trainings &amp; Clusters"):
            with self.subTest(tab=label):
                self.assertRegex(people, rf"<button[^>]*data-edify-tab[^>]*>{label}<")
        self.assertEqual(people.count("<table"), 1)
        for heading in (
            "Core<br>Visits",
            "Client<br>Visits",
            "Partner<br>Target",
            "Client<br>Spillover",
            "Assigned<br>to Partner",
            "Staff<br>Trainings",
            "Partner<br>Trainings",
        ):
            with self.subTest(heading=heading):
                self.assertIn(f">{heading}</th>", people)

    def test_the_capacity_figures_stand_over_the_people(self):
        self.portfolio(self.cceo, core=70, client=444)
        body = self.page()
        strip = body[body.index('class="cpo-capacity"') :]
        strip = strip[: strip.index("</dl>")]
        for text in (
            "Programme Leads",
            "CCEOs",
            "3 × 560",
            "Partner target",
            "140 Core + 24 beyond staff capacity",
            "Past the ceiling",
            "nobody has planned past 280 or 560",
        ):
            with self.subTest(text=text):
                self.assertIn(text, strip)

    def test_a_row_that_does_not_add_up_says_so(self):
        from django.template.loader import render_to_string

        row = svc._type_row(
            "client", "Client", svc.Tally(), rules.requirement_for("client")
        )
        row.update(adds_up=False, unaccounted=3)
        html = render_to_string(
            "partials/country_oversight/_types.html",
            {"type_rows": [row], "type_views": svc.TYPE_VIEWS, "type_query": ""},
        )
        self.assertIn("3 schools not accounted for", html)
        self.assertNotIn(
            "not accounted for",
            render_to_string(
                "partials/country_oversight/_types.html",
                {
                    "type_rows": svc.type_rows(self.snapshot()),
                    "type_views": svc.TYPE_VIEWS,
                    "type_query": "",
                },
            ),
        )

    def test_the_export_carries_the_share_out(self):
        self.portfolio(self.cceo, core=70, client=444)
        from apps.frontend.views.country_oversight_views import (
            HIERARCHY_HEADERS,
            _hierarchy_sheet,
        )

        sheet = _hierarchy_sheet(self.snapshot(), {})
        self.assertEqual(sheet["headers"], HIERARCHY_HEADERS)
        for row in sheet["rows"]:
            self.assertEqual(len(row), len(HIERARCHY_HEADERS))
        officer = next(
            dict(zip(sheet["headers"], row))
            for row in sheet["rows"]
            if row[3] == "Officer One"
        )
        self.assertEqual(officer["Staff Core visit target"], 140)
        self.assertEqual(officer["Staff client visit target"], 420)
        self.assertEqual(officer["Partner visit target"], 164)
        self.assertEqual(
            officer["Schools beyond staff capacity (client spillover)"], 24
        )
        self.assertEqual(officer["Visits planned past the ceiling"], 0)

    def test_the_rulebook_and_the_engine_keep_one_ceiling(self):
        policy.check()
        self.assertEqual(policy.STAFF_CEILINGS, rules.VISIT_TARGETS)


class ChartsFollowTheShareOutTest(Bulk, World):
    def charts(self):
        return {chart["id"]: chart for chart in svc.charts(self.snapshot())}

    def test_the_schools_chart_adds_up_with_the_partners_own_band(self):
        nobody = self.school("client", self.cceo)
        waiting = self.school("client", self.cceo)
        planned = self.school("client", self.cceo)
        self.handover(waiting, self.partner, status="pending_scheduling")
        self.activity(planned, "training_follow_up_visit", owner=self.cceo)
        chart = self.charts()["cpo-unique-chart"]
        index = chart["keys"].index(self.pl.id)
        counts = {s["name"]: s["counts"][index] for s in chart["series"]}
        self.assertEqual(counts["Awaiting a Partner's Date"], 1)
        self.assertEqual(counts["Not Yet Planned"], 1)
        self.assertEqual(counts["Staff Plan Only"], 1)
        self.assertEqual(sum(counts.values()), 3)
        self.assertEqual(sum(s["data"][index] for s in chart["series"]), 100)
        self.assertIn("Awaiting a\nPartner's date", chart["table"]["columns"])
        self.assertIsNotNone(nobody)

    def test_the_visit_chart_names_what_is_past_the_ceiling(self):
        schools = self.portfolio(self.pl, core=0, client=283)
        self.visits(self.pl, schools)
        chart = self.charts()["cpo-visit-chart"]
        row = next(r for r in chart["table"]["rows"] if r["label"] == "Lead A")
        cells = dict(zip(chart["table"]["columns"], row["cells"]))
        self.assertEqual(cells["Past the\nceiling"], 3)
        self.assertEqual(cells["Client visits\nof target"], "283 / 280")
        self.assertEqual(cells["Partner\ntarget"], 3)

    def test_the_training_chart_reads_each_side_against_its_own_target(self):
        core = self.school("core", self.cceo, cluster=self.cluster)
        self.session("cluster_training", [core])
        chart = self.charts()["cpo-training-chart"]
        index = chart["keys"].index(self.pl.id)
        series = {s["name"]: s["data"][index] for s in chart["series"]}
        self.assertEqual(
            series,
            {
                "Staff Target": 2,
                "Planned by Staff": 1,
                "Partner Target": 2,
                "Planned by Partners": 0,
            },
        )


class EveryPageSaysTheSameTest(Bulk, World):
    """The share-out on the pages beside Country Planning Oversight."""

    def test_a_planners_own_year_is_shared_out(self):
        schools = self.portfolio(self.cceo, core=70, client=444)
        self.visits(self.cceo, schools[:3], each=2)
        mine = staff_plan.own_workload(self.cceo_user, FY)
        self.assertEqual((mine["ceiling"], mine["planned"]), (560, 6))
        self.assertEqual((mine["core_planned"], mine["core_target"]), (6, 140))
        self.assertEqual(mine["client_target"], 420)
        self.assertEqual(mine["partner_schools"], 24)
        self.assertEqual(mine["partner_target"], 164)
        self.assertEqual((mine["over"], mine["core_only"]), (0, False))
        self.assertIsNone(staff_plan.own_workload(self.cd_user, FY))

    def test_the_planning_page_tells_the_planner(self):
        from django.template.loader import render_to_string

        self.portfolio(self.pl, core=140, client=5)
        html = render_to_string(
            "partials/planning/_workload_line.html",
            {"workload": staff_plan.own_workload(self.pl_user, FY)},
        )
        self.assertIn("data-planning-workload", html)
        self.assertIn("0 of 280 planned", html)
        self.assertIn("5 of your Client schools are beyond your 280", html)
        self.assertIn("Your Core schools alone take your whole 280", html)
        self.assertEqual(
            render_to_string(
                "partials/planning/_workload_line.html", {"workload": None}
            ).strip(),
            "",
        )

    def test_the_monitor_carries_the_partners_whole_target(self):
        row = OfficerMonitor(key="p", name="p", lead_id="", lead_name="")
        row.visits_target = 560
        row.schools = [
            SchoolState(
                id=str(index),
                code="",
                name="",
                school_type="core" if index < 70 else "client",
                district="",
                cluster_id="",
                cluster_name="",
                clustered=True,
                officer_id="p",
                officer_name="p",
                lead_id="",
                lead_name="",
                core_staff_trainings=2 if index < 10 else 0,
            )
            for index in range(70 + 444)
        ]
        self.assertEqual(row.partner_visit_target, 140 + 24)
        self.assertEqual(row.core_staff_training_target, 140)
        self.assertEqual(row.core_staff_trainings, 20)
        self.assertEqual(row.core_staff_trainings_tone, "warning")

    def test_a_school_list_says_who_its_visits_are_expected_from(self):
        from apps.planning.country_oversight import tables

        self.assertEqual(tables._expected_from(2, 2), "Staff 2 · Partner 2")
        self.assertEqual(tables._expected_from(1, 0), "Staff")
        self.assertEqual(tables._expected_from(0, 1), "Partner")
        self.assertEqual(tables._expected_from(0, 0), "")
        self.portfolio(self.pl, core=140, client=2)
        request = RequestFactory().get("/x", {"fy": FY, "school_type": "client"})
        request.user = self.cd_user
        table = tables.build(request.user, svc.read_filters(request), "not-planned")
        self.assertEqual({row["expected_from"] for row in table.rows}, {"Partner"})
        self.assertIn("Expected From", tables.sheet(table)["headers"])

    def test_project_capacity_shows_each_persons_visits_against_their_ceiling(self):
        from apps.projects.capacity import Allocation, attach_visit_load

        schools = self.portfolio(self.pl, core=0, client=282)
        self.visits(self.pl, schools)
        rows = attach_visit_load(
            [
                Allocation("c1", "p1", "Project", "P", self.pl.id, "Lead A", 10, 2),
                Allocation(
                    "c2", "p1", "Project", "P", self.cceo.id, "Officer One", 10, 0
                ),
            ],
            FY,
        )
        lead, officer = rows
        self.assertEqual(
            (lead.visits_planned, lead.visits_ceiling, lead.visits_over), (282, 280, 2)
        )
        self.assertEqual(
            (officer.visits_planned, officer.visits_ceiling, officer.visits_over),
            (0, 560, 0),
        )

    def test_the_execution_tab_reads_each_side_against_its_own_target(self):
        from apps.planning.country_execution import service as esvc

        self.school("core", self.cceo)
        request = RequestFactory().get("/x", {"fy": FY, "period": "fy"})
        request.user = self.cd_user
        snapshot = esvc.snapshot_for(request.user, esvc.read_filters(request))
        core = next(r for r in esvc.type_rows(snapshot) if r["key"] == "core")
        self.assertEqual((core["visit_slots"], core["staff_target"]), (4, 2))
        self.assertEqual(core["partner_target"], 2)
