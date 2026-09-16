"""The country portfolio and the cluster performance lenses (2026-09-16 brief).

Owner: "IA Team oversight should have all the schools in the entire country
portfolio but grouped by Program leads, which is further grouped by the CCEO
under them. IA should also track all the planning to know which schools have
been planned and which ones have not been planned. IA should also track all the
cluster activities, planning, SSA for the member schools, performance for each
cluster. Which cluster is more active and which cluster is less active."

Both lenses are folded from the same canonical records the rest of planning
reads — activities for what is planned, schedule cost lines for what it costs,
SSA records for what was assessed — so neither can disagree with the pages it
sits beside.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ClusterActivityAttendance,
)
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.planning.cluster_performance_service import cluster_performance
from apps.planning.portfolio_service import (
    NO_LEAD_KEY,
    NO_LEAD_LABEL,
    country_portfolio,
)
from apps.schools.models import School
from apps.ssa.models import SsaRecord

FY = get_operational_fy()


def _fy_day(month: int, day: int) -> datetime.date:
    year = int(FY) - 1 if month >= 10 else int(FY)
    return datetime.date(year, month, day)


class PortfolioFixture(TestCase):
    """One country: two Programme Leads, three CCEOs, and an orphan school."""

    def setUp(self):
        self.region = Region.objects.create(name="Portfolio Region")
        self.district = District.objects.create(
            name="Portfolio District", region=self.region
        )
        self.other_district = District.objects.create(
            name="Second District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Portfolio SC", district=self.district
        )

        self.lead_a = self._staff("pf-pl-a@edify.org", "Alice Lead", "Program Lead")
        self.lead_b = self._staff("pf-pl-b@edify.org", "Bruno Lead", "Program Lead")
        self.cceo_1 = self._staff("pf-cceo-1@edify.org", "Cara Officer", "CCEO")
        self.cceo_2 = self._staff("pf-cceo-2@edify.org", "Dan Officer", "CCEO")
        self.cceo_3 = self._staff("pf-cceo-3@edify.org", "Eve Officer", "CCEO")
        # Cara and Dan report to Alice; Eve reports to Bruno. Nobody reports to
        # the IA who reads the page — assurance is not a reporting line.
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_1, supervisor=self.lead_a
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_2, supervisor=self.lead_a
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_3, supervisor=self.lead_b
        )

        self.ia = self._staff("pf-ia@edify.org", "Grace Assurance", "ImpactAssessment")
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo_1, supervisor=self.ia
        )

        self.cluster = Cluster.objects.create(
            name="Alpha Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
            responsible_staff_id=self.cceo_1.id,
        )
        self.quiet_cluster = Cluster.objects.create(
            name="Zulu Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
            responsible_staff_id=self.cceo_3.id,
        )

        self.planned_school = self._school("PF-1", "Planned Primary", self.cceo_1)
        self.unplanned_school = self._school("PF-2", "Unplanned Primary", self.cceo_1)
        self.dan_school = self._school("PF-3", "Dan's Primary", self.cceo_2)
        self.eve_school = self._school("PF-4", "Eve's Primary", self.cceo_3)
        self.orphan_school = self._school("PF-5", "Orphan Primary", None)
        self.closed_school = self._school("PF-6", "Closed Primary", self.cceo_1)
        School.objects.filter(id=self.closed_school.id).update(
            operational_status="permanently_closed"
        )

    def _staff(self, email, name, role) -> StaffProfile:
        user = User.objects.create_user(
            email=email, name=name, roles=[role], active_role=role, password="x"
        )
        return StaffProfile.objects.create(user=user, country="Uganda")

    def _school(self, code, name, owner) -> School:
        # No sub-county: School.save() clusters a school by the sub-county its
        # cluster covers, so giving every school one would silently put them
        # all in Alpha Cluster and the membership these tests assert would be
        # the geography rule's, not the test's.
        school = School.objects.create(
            school_id=code,
            name=name,
            region=self.region,
            district=self.district,
            school_type="client",
            account_owner_id=owner.id if owner else None,
        )
        if owner:
            StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    def _activity(
        self,
        *,
        school=None,
        cluster=None,
        day,
        kind="school_visit",
        status="scheduled",
        cost=0,
        owner=None,
    ) -> Activity:
        activity = Activity.objects.create(
            activity_type=kind,
            school=school,
            cluster=cluster,
            fy=FY,
            quarter="Q1",
            planned_date=day,
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(9))
            ),
            status=status,
            responsible_staff_id=(owner or self.cceo_1).id,
            delivery_type="staff",
        )
        if cost:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="transport",
                label="Transport",
                unit_cost=cost,
                quantity=1,
                amount=cost,
            )
        return activity


class PortfolioGroupingTest(PortfolioFixture):
    def test_schools_group_by_programme_lead_then_by_their_cceo(self):
        portfolio = country_portfolio(self.ia.user, fy=FY)

        by_lead = {lead.name: lead for lead in portfolio["leads"]}
        self.assertIn("Alice Lead", by_lead)
        self.assertIn("Bruno Lead", by_lead)
        self.assertEqual(
            [o.name for o in by_lead["Alice Lead"].officers],
            ["Cara Officer", "Dan Officer"],
        )
        self.assertEqual(
            [o.name for o in by_lead["Bruno Lead"].officers], ["Eve Officer"]
        )

    def test_assurance_oversight_is_not_a_reporting_line(self):
        """The IA supervises Cara too. Filing her schools under the IA would
        put a CCEO's portfolio with whoever last reviewed it."""
        portfolio = country_portfolio(self.ia.user, fy=FY)

        self.assertNotIn("Grace Assurance", {lead.name for lead in portfolio["leads"]})

    def test_a_school_with_no_owner_is_surfaced_not_dropped(self):
        """A school nobody is carrying is what a country lens exists for."""
        portfolio = country_portfolio(self.ia.user, fy=FY)

        orphan = next(lead for lead in portfolio["leads"] if lead.key == NO_LEAD_KEY)
        self.assertEqual(orphan.name, NO_LEAD_LABEL)
        self.assertEqual(
            [s["name"] for o in orphan.officers for s in o.schools],
            ["Orphan Primary"],
        )
        # And it sorts last, after the people actually carrying schools.
        self.assertIs(portfolio["leads"][-1], orphan)

    def test_a_closed_school_is_not_an_unplanned_school(self):
        """A closed school takes no work, so counting it as "not planned"
        would be a red row nobody can ever clear."""
        portfolio = country_portfolio(self.ia.user, fy=FY)

        names = {
            s["name"]
            for lead in portfolio["leads"]
            for o in lead.officers
            for s in o.schools
        }
        self.assertNotIn("Closed Primary", names)
        self.assertEqual(portfolio["totals"]["schools"], 5)


class PortfolioPlanningTest(PortfolioFixture):
    def setUp(self):
        super().setUp()
        self._activity(school=self.planned_school, day=_fy_day(11, 4), cost=50_000)
        self._activity(
            school=self.planned_school,
            day=_fy_day(2, 10),
            kind="cluster_training",
            cost=30_000,
        )
        self._activity(
            school=self.dan_school, day=_fy_day(12, 1), owner=self.cceo_2, cost=20_000
        )

    def _school_row(self, portfolio, name):
        return next(
            s
            for lead in portfolio["leads"]
            for o in lead.officers
            for s in o.schools
            if s["name"] == name
        )

    def test_planned_means_one_or_more_live_activities_in_the_year(self):
        portfolio = country_portfolio(self.ia.user, fy=FY)

        self.assertTrue(self._school_row(portfolio, "Planned Primary")["is_planned"])
        self.assertFalse(self._school_row(portfolio, "Unplanned Primary")["is_planned"])

    def test_a_verified_activity_counts_as_completed_on_a_school(self):
        """Same phantom-status trap on the portfolio side."""
        self._activity(
            school=self.unplanned_school, day=_fy_day(2, 3), status="ia_verified"
        )

        row = self._school_row(
            country_portfolio(self.ia.user, fy=FY), "Unplanned Primary"
        )
        self.assertEqual(row["activities"], 1)
        self.assertEqual(row["completed"], 1)

    def test_a_school_row_carries_what_is_planned_and_what_it_costs(self):
        row = self._school_row(
            country_portfolio(self.ia.user, fy=FY), "Planned Primary"
        )

        self.assertEqual(row["activities"], 2)
        self.assertEqual(row["visits"], 1)
        self.assertEqual(row["trainings"], 1)
        self.assertEqual(row["budget"], 80_000)
        self.assertEqual(row["first_date"], _fy_day(11, 4))

    def test_a_cancelled_activity_is_not_a_plan(self):
        self._activity(
            school=self.unplanned_school, day=_fy_day(1, 9), status="cancelled"
        )

        row = self._school_row(
            country_portfolio(self.ia.user, fy=FY), "Unplanned Primary"
        )
        self.assertFalse(row["is_planned"])
        self.assertEqual(row["activities"], 0)

    def test_totals_fold_from_the_rows_they_label(self):
        totals = country_portfolio(self.ia.user, fy=FY)["totals"]

        self.assertEqual(totals["schools"], 5)
        self.assertEqual(totals["planned"], 2)
        self.assertEqual(totals["unplanned"], 3)
        self.assertEqual(totals["coverage"], 40)
        self.assertEqual(totals["budget"], 100_000)

    def test_a_leads_numbers_are_the_sum_of_their_officers(self):
        portfolio = country_portfolio(self.ia.user, fy=FY)
        alice = next(lead for lead in portfolio["leads"] if lead.name == "Alice Lead")

        self.assertEqual(alice.count, sum(o.count for o in alice.officers))
        self.assertEqual(alice.planned, 2)
        self.assertEqual(alice.unplanned, 1)
        self.assertEqual(alice.budget, 100_000)

    def test_filtering_to_unplanned_narrows_the_list_not_the_finding(self):
        """A heading that reads "0 planned" because the reader asked to see the
        unplanned schools is the filter describing itself."""
        portfolio = country_portfolio(self.ia.user, fy=FY, planned="unplanned")

        alice = next(lead for lead in portfolio["leads"] if lead.name == "Alice Lead")
        cara = next(o for o in alice.officers if o.name == "Cara Officer")
        self.assertEqual([s["name"] for s in cara.visible], ["Unplanned Primary"])
        # The heading still states the real portfolio.
        self.assertEqual(cara.count, 2)
        self.assertEqual(cara.planned, 1)
        self.assertEqual(portfolio["totals"]["schools"], 5)
        self.assertEqual(portfolio["totals"]["coverage"], 40)

    def test_filtering_to_one_lead_leaves_the_others_out(self):
        portfolio = country_portfolio(
            self.ia.user, fy=FY, program_lead_id=self.lead_b.id
        )

        self.assertEqual([lead.name for lead in portfolio["leads"]], ["Bruno Lead"])

    def test_choosing_a_lead_does_not_empty_the_lead_filter(self):
        """The options are built before the filter is applied. Built after, the
        control that narrowed the page would be left offering one choice — the
        one already made."""
        from apps.planning.portfolio_service import program_lead_options

        narrowed = country_portfolio(
            self.ia.user, fy=FY, program_lead_id=self.lead_b.id
        )

        self.assertEqual(
            [option["name"] for option in program_lead_options(narrowed)],
            ["Alice Lead", "Bruno Lead", NO_LEAD_LABEL],
        )

    def test_a_district_filter_offers_only_districts_that_are_there(self):
        portfolio = country_portfolio(self.ia.user, fy=FY)

        self.assertEqual(
            [d["name"] for d in portfolio["districts"]], ["Portfolio District"]
        )

    def test_the_lens_costs_a_fixed_number_of_queries(self):
        """A country page's cost must not grow with the country. Twenty more
        schools must not be twenty more queries."""
        for index in range(20):
            school = self._school(f"PF-BULK-{index}", f"Bulk {index}", self.cceo_2)
            self._activity(school=school, day=_fy_day(1, 12), owner=self.cceo_2)

        with self.assertNumQueries(7):
            country_portfolio(self.ia.user, fy=FY)


class ClusterPerformanceTest(PortfolioFixture):
    def setUp(self):
        super().setUp()
        School.objects.filter(
            id__in=[self.planned_school.id, self.unplanned_school.id]
        ).update(cluster_id=self.cluster.id, cluster_status="clustered")
        School.objects.filter(id=self.eve_school.id).update(
            cluster_id=self.quiet_cluster.id, cluster_status="clustered"
        )
        # `ia_verified`, not "completed": the bare status is a phantom no
        # production transition writes, and a fixture that used it would let a
        # delivery count filtered on it pass while reading zero in production
        # (apps.core.tests.test_verification_criticals).
        session = self._activity(
            cluster=self.cluster,
            day=_fy_day(11, 6),
            kind="cluster_training",
            status="ia_verified",
            cost=40_000,
        )
        ClusterActivityAttendance.objects.create(
            activity=session, school=self.planned_school, attended=True
        )
        self._activity(cluster=self.cluster, day=_fy_day(3, 4), kind="cluster_meeting")
        self._activity(school=self.planned_school, day=_fy_day(12, 2), cost=10_000)
        SsaRecord.objects.create(
            school=self.planned_school,
            date_of_ssa=timezone.now(),
            fy=FY,
            quarter="Q1",
            uploaded_by=self.ia.id,
        )

    def _rows(self, principal=None):
        performance = cluster_performance(principal or self.ia.user, fy=FY)
        return {entry["row"].name: entry for entry in performance["rows"]}, performance

    def test_a_cluster_carries_its_sessions_visits_ssa_and_budget(self):
        rows, _ = self._rows()
        alpha = rows["Alpha Cluster"]["row"]

        self.assertEqual(alpha.schools, 2)
        self.assertEqual(alpha.sessions_planned, 2)
        self.assertEqual(alpha.sessions_done, 1)
        self.assertEqual(alpha.trainings, 1)
        self.assertEqual(alpha.meetings, 1)
        self.assertEqual(alpha.visits_planned, 1)
        self.assertEqual(alpha.ssa_schools, 1)
        self.assertEqual(alpha.budget, 50_000)

    def test_delivery_counts_the_whole_verified_chain(self):
        """A session that reached `ia_verified` or `closed` was delivered. Only
        the seed writes the bare "completed" status, so a count filtered on it
        reads zero for work people actually did."""
        self._activity(
            cluster=self.cluster,
            day=_fy_day(12, 9),
            kind="cluster_meeting",
            status="closed",
        )

        rows, _ = self._rows()
        alpha = rows["Alpha Cluster"]["row"]

        self.assertEqual(alpha.sessions_planned, 3)
        self.assertEqual(alpha.sessions_done, 2)

    def test_reach_counts_member_schools_the_work_actually_touched(self):
        rows, _ = self._rows()
        alpha = rows["Alpha Cluster"]["row"]

        # One of two member schools: invited to the session and visited.
        self.assertEqual(alpha.schools_reached, 1)
        self.assertEqual(alpha.reach, 50)

    def test_the_busiest_cluster_leads_and_is_named(self):
        rows, performance = self._rows()

        self.assertEqual(performance["rows"][0]["row"].name, "Alpha Cluster")
        self.assertEqual(rows["Alpha Cluster"]["rank"], 1)
        self.assertEqual(rows["Alpha Cluster"]["superlative"], "Most active")

    def test_a_cluster_with_nothing_planned_is_dormant_not_merely_last(self):
        rows, performance = self._rows()
        zulu = rows["Zulu Cluster"]

        self.assertTrue(zulu["row"].is_dormant)
        self.assertEqual(zulu["band"], "dormant")
        self.assertEqual(zulu["band_label"], "Nothing planned")
        self.assertEqual(performance["totals"]["dormant"], 1)

    def test_a_dormant_cluster_is_never_the_least_active(self):
        """ "Least active" ranks the clusters that are doing something. A
        cluster doing nothing is a different finding and says so."""
        rows, _ = self._rows()

        self.assertEqual(rows["Zulu Cluster"]["superlative"], "")

    def test_a_share_with_nothing_behind_it_is_absent_not_zero(self):
        rows, _ = self._rows()
        zulu = rows["Zulu Cluster"]["row"]

        self.assertIsNone(zulu.delivery)
        self.assertEqual(zulu.reach, 0)

    def test_totals_carry_both_halves_of_every_share(self):
        """The metric registry refuses a percentage with no denominator, and a
        reader cannot check one either."""
        _, performance = self._rows()
        totals = performance["totals"]

        self.assertEqual(totals["clusters"], 2)
        self.assertEqual(totals["schools"], 3)
        self.assertEqual(totals["reached"], 1)
        self.assertEqual(totals["ssa_schools"], 1)
        self.assertEqual(totals["budget"], 50_000)

    def test_an_activity_on_both_a_school_and_a_cluster_is_counted_once(self):
        """Both columns are nullable and nothing forbids a row setting each.
        Counted on the cluster's calendar and again through its member school,
        one plan would be worth twice its cost."""
        self._activity(
            school=self.planned_school,
            cluster=self.cluster,
            day=_fy_day(1, 20),
            kind="school_visit",
            cost=25_000,
        )

        rows, _ = self._rows()
        alpha = rows["Alpha Cluster"]["row"]

        self.assertEqual(alpha.budget, 75_000)
        self.assertEqual(alpha.visits_planned, 1)

    def test_the_lens_costs_a_fixed_number_of_queries(self):
        for index in range(10):
            cluster = Cluster.objects.create(
                name=f"Bulk Cluster {index}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county,
                status="active",
                responsible_staff_id=self.cceo_2.id,
            )
            self._activity(cluster=cluster, day=_fy_day(1, 8), kind="cluster_meeting")

        with self.assertNumQueries(15):
            cluster_performance(self.ia.user, fy=FY)
