"""Country Planning Oversight — requirement, coverage, hierarchy and follow-up.

The owner's specification (2026-09-28) as tests: school families and the
eligible denominator, the 4C + L visit requirement and its staff/Partner
split, staff ceilings as capacity, Partner assigned versus scheduled, the
planned-state rule, school-training rosters, cluster and meeting coverage,
reconciliation up the hierarchy, the Country Director's "Follow Up with PL",
permissions, query budgets and the ten end-to-end journeys.

Dates sit inside the operational fiscal year the test runs in, counted from
its first day, so a run near the 1 October roll reads the year its work
lands in (see the FY-roll rule in the test-runner notes).
"""

from __future__ import annotations

import re

from datetime import date, timedelta

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster, SchoolClusterAssignment
from apps.core.fy import get_fy_date_range, get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.planning.country_oversight import followups as fu
from apps.planning.country_oversight import policy
from apps.planning.country_oversight import service as svc
from apps.planning.country_oversight.coverage import window_for
from apps.planning.followup_models import FollowUpStatus, PlanningOversightFollowUp
from apps.schools.models import School

FY = get_operational_fy()
FY_START = get_fy_date_range(FY)[0].date()


def day(offset: int) -> date:
    """A date `offset` days into the operational fiscal year."""
    return FY_START + timedelta(days=offset)


class World(TestCase):
    """A small country: two Programme Leads, their CCEOs, Partners, clusters."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="CPO Central", country="Uganda")
        cls.district = District.objects.create(name="CPO Kampala", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="CPO SC", district=cls.district)
        cls.cd_user, cls.cd = cls.person(
            "cpo-cd", "Country Director", EdifyRole.COUNTRY_DIRECTOR
        )
        cls.ia_user, cls.ia = cls.person(
            "cpo-ia", "Impact Analyst", EdifyRole.IMPACT_ASSESSMENT
        )
        cls.rvp_user, cls.rvp = cls.person(
            "cpo-rvp", "Regional VP", EdifyRole.REGIONAL_VICE_PRESIDENT
        )
        cls.admin_user, cls.admin = cls.person("cpo-admin", "Admin", EdifyRole.ADMIN)
        cls.pl_user, cls.pl = cls.person(
            "cpo-pl", "Lead A", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.pl2_user, cls.pl2 = cls.person(
            "cpo-pl2", "Lead B", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.cceo_user, cls.cceo = cls.person("cpo-cceo", "Officer One", EdifyRole.CCEO)
        cls.cceo2_user, cls.cceo2 = cls.person(
            "cpo-cceo2", "Officer Two", EdifyRole.CCEO
        )
        cls.cceo3_user, cls.cceo3 = cls.person(
            "cpo-cceo3", "Officer Three", EdifyRole.CCEO
        )
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo2, supervisor=cls.pl
        )
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo3, supervisor=cls.pl2
        )
        cls.partner = Partner.objects.create(name="Partner Alpha", active_status=True)
        cls.partner2 = Partner.objects.create(name="Partner Beta", active_status=True)
        cls.cluster = Cluster.objects.create(
            name="CPO Cluster",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            status="active",
        )
        cls._school_seq = 0

    @classmethod
    def person(cls, key, name, role):
        user = User.objects.create(
            email=f"{key}@cpo.test",
            name=name,
            roles=[role.value],
            active_role=role.value,
            is_active=True,
        )
        return user, StaffProfile.objects.create(
            user=user, title=name, country="Uganda"
        )

    @classmethod
    def school(cls, school_type="client", owner=None, *, cluster=None, **extra):
        cls._school_seq += 1
        school = School.objects.create(
            school_id=f"CPO-{cls._school_seq:05d}",
            name=f"School {cls._school_seq:05d}",
            school_type=school_type,
            region=cls.region,
            district=cls.district,
            account_owner_id=owner.id if owner else None,
            account_owner_status="matched" if owner else "pending",
            cluster_id=cluster.id if cluster else None,
            cluster_status="clustered" if cluster else "unclustered",
            **extra,
        )
        if owner:
            StaffSchoolAssignment.objects.get_or_create(
                staff=owner, school_id=school.id
            )
        return school

    @staticmethod
    def activity(
        school,
        activity_type="school_visit",
        *,
        status="scheduled",
        on=30,
        owner=None,
        partner=None,
        cluster=None,
        **extra,
    ):
        planned = day(on) if on is not None else None
        return Activity.objects.create(
            activity_type=activity_type,
            school=school,
            cluster=cluster,
            fy=FY,
            quarter="Q1",
            planned_date=planned,
            planned_month=planned.month if planned else None,
            status=status,
            responsible_staff_id=owner.id if owner else None,
            delivery_type="partner" if partner else "staff",
            assigned_partner_id=partner.id if partner else None,
            **extra,
        )

    @staticmethod
    def handover(school, partner, *, status="assigned", kind="visit", **extra):
        fields = (
            {"support_type": "visit"}
            if school.school_type == "core" and kind == "visit"
            else {}
        )
        if kind == "training":
            fields = {"expected_activity_type": "in_school_training"}
        elif school.school_type != "core":
            fields = {"expected_activity_type": "school_visit"}
        fields.update(extra)
        return PartnerAssignment.objects.create(
            school=school, partner=partner, status=status, **fields
        )

    def session(
        self, activity_type, schools, *, status="scheduled", on=40, invited=True
    ):
        activity = Activity.objects.create(
            activity_type=activity_type,
            cluster=self.cluster,
            fy=FY,
            quarter="Q1",
            planned_date=day(on),
            status=status,
            responsible_staff_id=self.cceo.id,
        )
        for school in schools:
            ClusterActivityAttendance.objects.create(
                activity=activity, school=school, invited=invited
            )
        return activity

    def tree(self, user=None, **filters):
        user = user or self.cd_user
        params = {"fy": FY, **filters}
        from django.test import RequestFactory

        request = RequestFactory().get("/country-planning-oversight/", params)
        request.user = user
        return svc.snapshot_for(user, svc.read_filters(request)).tree

    def lead_row(self, tree, lead):
        return next(row for row in tree.leads if row.key == lead.id)

    def owner_row(self, tree, owner):
        for lead in tree.leads:
            for row in lead.owners:
                if row.key == owner.id:
                    return row
        raise AssertionError(f"{owner} has no row")

    def as_user(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client


# ── §26.1 School families and the denominator ────────────────────────────────
class FamilyAndDenominatorTest(World):
    def test_the_platform_families_come_from_the_target_engine(self):
        from apps.hr.target_distribution import CLIENT_FAMILY, CORE_FAMILY

        for school_type in CORE_FAMILY:
            self.assertEqual(policy.family_of(school_type), policy.CORE_FAMILY)
        for school_type in CLIENT_FAMILY:
            self.assertEqual(policy.family_of(school_type), policy.CLIENT_FAMILY)
        self.assertEqual(policy.family_of("core"), policy.CORE_FAMILY)
        self.assertEqual(policy.family_of("champion"), policy.CORE_FAMILY)
        self.assertEqual(policy.family_of("client"), policy.CLIENT_FAMILY)
        self.assertEqual(policy.family_of("core_trained"), policy.CLIENT_FAMILY)

    def test_core_graduate_follows_the_owners_client_decision(self):
        """Owner, 2026-09-28 (PR #163): Core Graduate follows the client rule
        for its visits and Partner work — Client-family by that recorded
        decision, not by guesswork — and, still untrained, its training slot
        is listed as undeliverable rather than read as a gap."""
        self.assertEqual(policy.family_of("core_graduate"), policy.CLIENT_FAMILY)
        self.assertIn("core_graduate", policy.GOVERNED_FAMILY_DECISIONS)
        self.assertNotIn("core_graduate", policy.PENDING_FAMILY_DECISIONS)
        self.school("core_graduate", self.cceo)
        self.school("client", self.cceo)
        tree = self.tree()
        self.assertEqual(tree.country.schools, 2)
        self.assertEqual(tree.country.client_schools, 2)
        self.assertEqual(tree.country.visit_slots, 2)
        self.assertEqual(tree.country.undeliverable_training, 1)
        self.assertEqual(tree.country.unmapped_schools, 0)

    def test_a_core_graduate_support_visit_fills_its_visit_slot(self):
        """Following the client rule for its visits means its support visit
        fills the slot, as a client school's does; a donor visit does not.
        Before, Core Graduate had no visit rule at all, so its slot read open
        whatever was planned there."""
        planned = self.school("core_graduate", self.cceo)
        donor_only = self.school("core_graduate", self.cceo)
        self.activity(planned, "follow_up_visit", owner=self.cceo)
        self.activity(donor_only, "donor_visit", owner=self.cceo)
        t = self.tree().country
        self.assertEqual(t.visit_slots, 2)
        self.assertEqual(t.staff, 1)
        self.assertEqual(t.any_staff, 1)
        self.assertEqual(t.unallocated, 1)
        self.assertEqual(t.fully_planned, 1)
        from apps.planning.country_oversight.coverage import VISIT_RULE_BY_TYPE

        governed = set(policy.SCHOOL_TYPE_FAMILY)
        self.assertEqual(governed - set(VISIT_RULE_BY_TYPE), set())

    def test_a_type_with_no_family_is_governed_rather_than_folded_in(self):
        """A blank or unknown type: outside every denominator, counted on its
        own, and named on the data-quality queue."""
        self.assertEqual(policy.family_of(""), policy.UNMAPPED_FAMILY)
        self.school("", self.cceo)
        self.school("client", self.cceo)
        tree = self.tree()
        self.assertEqual(tree.country.schools, 1)
        self.assertEqual(tree.country.visit_slots, 1)
        self.assertEqual(tree.country.unmapped_schools, 1)
        from apps.planning.country_oversight.data_quality import checks

        dataset = svc.dataset_for(self.cd_user, window_for(FY))
        found = {check.key: check for check in checks(dataset, tree)}
        self.assertEqual(found["unmapped_family"].count, 1)

    def test_closed_schools_leave_and_reopened_schools_count(self):
        self.school("client", self.cceo)
        self.school(
            "client",
            self.cceo,
            operational_status="permanently_closed",
            closure_effective_date=date.today() - timedelta(days=3),
        )
        self.school(
            "client",
            self.cceo,
            operational_status="reopened",
            reopened_at=timezone.now() - timedelta(days=2),
        )
        # Closing next week: still operating on the reporting date.
        self.school(
            "client",
            self.cceo,
            operational_status="temporarily_closed",
            closure_effective_date=date.today() + timedelta(days=7),
        )
        self.assertEqual(self.tree().country.schools, 3)

    def test_duplicates_are_outside_and_each_school_counts_once(self):
        self.school("client", self.cceo)
        self.school("client", self.cceo, duplicate_status="merged")
        self.school("client", self.cceo, duplicate_status="confirmed")
        self.school("client", self.cceo, duplicate_status="potential")
        tree = self.tree()
        self.assertEqual(tree.country.schools, 2)

    def test_portfolio_as_of_a_past_year_excludes_later_schools(self):
        from apps.planning.country_oversight.requirements import reporting_date

        past = str(int(FY) - 1)
        self.assertEqual(
            reporting_date(past), get_fy_date_range(past)[1].date() - timedelta(days=1)
        )
        self.assertEqual(
            reporting_date(FY),
            min(date.today(), get_fy_date_range(FY)[1].date() - timedelta(days=1)),
        )
        self.school("client", self.cceo)
        # Created today: not in the portfolio of a year that ended before it.
        self.assertEqual(self.tree(fy=past).country.schools, 0)


# ── §26.2 Visit requirements and §26.3 staff ceilings ────────────────────────
class RequirementTest(World):
    def test_core_family_needs_four_slots_two_each_side_and_client_one(self):
        self.school("core", self.cceo)
        self.school("champion", self.cceo)
        self.school("client", self.cceo)
        self.school("core_trained", self.cceo)
        t = self.tree().country
        self.assertEqual((t.core_schools, t.client_schools, t.schools), (2, 2, 4))
        self.assertEqual(t.visit_slots, 4 * 2 + 2)
        self.assertEqual(t.core_staff_slots, 2 * 2)
        self.assertEqual(t.core_partner_slots, 2 * 2)
        self.assertEqual(t.client_slots, 2)
        self.assertEqual(t.client_schools, t.schools - t.core_schools)
        self.assertEqual(t.staff_expected + t.partner_expected, t.visit_slots)
        self.assertEqual(t.training_slots, 4 * 2 + 2)

    def test_journey_two_cceo_capacity(self):
        """80 Core-family + 400 Client-family under one CCEO."""
        self._bulk(self.cceo, core=80, client=400)
        row = self.owner_row(self.tree(), self.cceo).tally
        self.assertEqual(row.core_staff_slots, 160)
        self.assertEqual(row.client_staff_expected, 400)
        self.assertEqual(row.staff_expected, 560)
        self.assertEqual(row.core_partner_slots, 160)
        self.assertEqual(row.client_partner_expected, 0)
        self.assertEqual(row.visit_slots, 720)
        self.assertEqual(row.deficit, 0)

    def test_client_slots_use_only_the_capacity_left_after_core(self):
        self._bulk(self.cceo, core=200, client=300)
        row = self.owner_row(self.tree(), self.cceo).tally
        self.assertEqual(row.core_staff_slots, 400)
        self.assertEqual(row.client_staff_expected, 160)
        self.assertEqual(row.client_partner_expected, 140)
        self.assertEqual(row.staff_expected, 560)
        self.assertEqual(row.partner_expected, 400 + 140)

    def test_a_ceiling_below_core_is_a_visible_deficit_never_a_partner_slot(self):
        self._bulk(self.cceo, core=300, client=10)
        row = self.owner_row(self.tree(), self.cceo).tally
        self.assertEqual(row.core_staff_slots, 600)
        self.assertEqual(row.deficit, 40)
        self.assertEqual(row.core_partner_slots, 600)
        self.assertEqual(row.client_staff_expected, 0)
        self.assertEqual(row.client_partner_expected, 10)

    def test_journey_three_pl_personal_capacity_and_the_team_stay_apart(self):
        self._bulk(self.pl, core=80, client=120)
        self._bulk(self.cceo, core=5, client=5)
        tree = self.tree()
        personal = self.owner_row(tree, self.pl)
        self.assertEqual(personal.kind, "pl_personal")
        self.assertEqual(personal.label, "PL Personal Delivery")
        self.assertEqual(personal.tally.schools, 200)
        self.assertEqual(personal.tally.staff_expected, 280)
        self.assertEqual(personal.ceiling, 280)
        officer = self.owner_row(tree, self.cceo)
        self.assertEqual(officer.tally.schools, 10)
        lead = self.lead_row(tree, self.pl)
        self.assertEqual(lead.tally.schools, 210)

    def _bulk(self, owner, *, core, client):
        rows = []
        for index in range(core + client):
            self.__class__._school_seq += 1
            rows.append(
                School(
                    school_id=f"BULK-{owner.id[-6:]}-{self._school_seq:05d}",
                    name=f"Bulk {self._school_seq:05d}",
                    school_type="core" if index < core else "client",
                    region=self.region,
                    district=self.district,
                    account_owner_id=owner.id,
                    account_owner_status="matched",
                )
            )
        School.objects.bulk_create(rows)


# ── §26.4 Partner requirements and §26.5 the planned-state rule ──────────────
class PartnerAndPlannedTest(World):
    def test_assigned_is_not_planned_until_the_partner_dates_it(self):
        core = self.school("core", self.cceo)
        self.handover(core, self.partner)
        t = self.tree().country
        self.assertEqual(t.partner_assigned, 1)
        self.assertEqual(t.partner_scheduled, 0)
        self.assertEqual(t.planned, 0)
        self.activity(
            core, "core_visit", status="partner_scheduled", partner=self.partner
        )
        t = self.tree().country
        self.assertEqual(t.partner_scheduled, 1)
        self.assertEqual(t.planned, 1)

    def test_a_returned_handover_holds_no_slot(self):
        client = self.school("client", self.cceo)
        self.handover(
            client, self.partner, status="returned_to_staff", returned_at=timezone.now()
        )
        t = self.tree().country
        self.assertEqual(t.partner_assigned, 0)
        self.assertEqual(t.partner_expected - t.partner_assigned, t.partner_gap + 0)
        # Counted where Partner work is read, never as a held slot.
        self.assertEqual(t.returned, 1)

    def test_the_partner_view_never_hands_a_staff_held_client_slot_to_a_partner(self):
        """Staff hold a client school's one slot once they plan it; a Partner's
        work there claims nothing — on the Partner view too, so filtering to a
        channel can only narrow the country's figures, never add to them."""
        dated = self.school("client", self.cceo)
        handed = self.school("client", self.cceo)
        for school in (dated, handed):
            self.activity(school, "school_visit", owner=self.cceo, on=20)
        self.activity(
            dated, "school_visit", status="partner_scheduled", partner=self.partner
        )
        self.handover(handed, self.partner)
        everything = self.tree().country
        partner_view = self.tree(channel="partner").country
        staff_view = self.tree(channel="staff").country
        self.assertEqual(everything.staff, 2)
        self.assertEqual(everything.partner_assigned, 0)
        self.assertEqual(partner_view.partner_assigned, 0)
        self.assertEqual(partner_view.partner_scheduled, 0)
        self.assertEqual(staff_view.staff, 2)
        for figure in ("partner_assigned", "partner_scheduled"):
            self.assertLessEqual(
                getattr(partner_view, figure), getattr(everything, figure)
            )

    def test_two_partners_at_a_core_school_never_exceed_two_partner_slots(self):
        core = self.school("core", self.cceo)
        self.activity(
            core, "core_visit", status="partner_scheduled", partner=self.partner, on=20
        )
        self.activity(
            core, "core_visit", status="partner_scheduled", partner=self.partner2, on=25
        )
        self.activity(
            core, "core_visit", status="partner_scheduled", partner=self.partner2, on=26
        )
        tree = self.tree()
        t = tree.country
        self.assertEqual(t.partner_scheduled, 2)
        owner = self.owner_row(tree, self.cceo)
        shares = [tally.partner_scheduled for key, tally in owner.partners.items()]
        self.assertEqual(sum(shares), 2)

    def test_client_partner_requirement_is_the_balance_staff_capacity_leaves(self):
        self.school("core", self.cceo)
        client = self.school("client", self.cceo)
        self.handover(client, self.partner)
        t = self.tree().country
        self.assertEqual(t.core_partner_slots, 2)
        self.assertEqual(t.client_partner_expected + t.client_staff_expected, 1)
        self.assertEqual(
            t.partner_expected, t.core_partner_slots + t.client_partner_expected
        )

    def test_which_states_count_as_planned(self):
        planned = (
            "scheduled",
            "in_progress",
            "evidence_uploaded",
            "submitted_to_pl",
            "awaiting_ia_verification",
            "ia_verified",
            "closed",
        )
        not_planned = (
            "not_planned",
            "awaiting_owner_approval",
            "assigned_to_partner",
            "returned",
            "cancelled",
            "rejected",
            "deferred",
        )
        for status in planned:
            with self.subTest(status=status):
                self.assertIn(status, policy.PLANNED_STATES)
        for status in not_planned:
            with self.subTest(status=status):
                self.assertNotIn(status, policy.PLANNED_STATES)
        policy.check()
        schools = [
            self.school("client", self.cceo)
            for _ in range(len(planned) + len(not_planned) + 2)
        ]
        for school, status in zip(schools, planned + not_planned):
            self.activity(school, status=status, owner=self.cceo)
        # A plan with no date is not planned; the same plan dated is.
        self.activity(schools[-2], status="planned", on=None, owner=self.cceo)
        self.activity(schools[-1], status="planned", owner=self.cceo)
        t = self.tree().country
        self.assertEqual(t.staff, len(planned) + 1)
        self.assertEqual(t.staff_verified, 2)

    def test_a_core_visit_fills_one_of_four_slots_and_one_school(self):
        """Journey 5: unique-school coverage and slot coverage differ."""
        core = self.school("core", self.cceo)
        self.activity(core, "core_visit", owner=self.cceo)
        t = self.tree().country
        self.assertEqual(t.any_visit, 1)
        self.assertEqual(t.planned, 1)
        self.assertEqual(t.visit_slots, 4)
        self.assertEqual(t.unallocated, 3)

    def test_rescheduling_moves_a_visit_and_never_adds_one(self):
        client = self.school("client", self.cceo)
        visit = self.activity(client, owner=self.cceo, on=10)
        visit.planned_date = day(60)
        visit.reschedule_count = 1
        visit.save()
        self.assertEqual(self.tree().country.staff, 1)

    def test_staff_cover_a_partner_slot_nobody_holds_but_never_one_a_partner_holds(
        self,
    ):
        core = self.school("core", self.cceo)
        for offset in (10, 20, 30):
            self.activity(core, "core_visit", owner=self.cceo, on=offset)
        t = self.tree().country
        self.assertEqual(t.staff, 3)
        self.assertEqual(t.staff_cover, 1)
        self.assertEqual(t.unallocated, 1)
        other = self.school("core", self.cceo2)
        self.handover(other, self.partner)
        self.handover(other, self.partner2)
        for offset in (10, 20, 30):
            self.activity(other, "core_visit", owner=self.cceo2, on=offset)
        row = self.owner_row(self.tree(), self.cceo2).tally
        self.assertEqual(row.staff, 2)
        self.assertEqual(row.partner_assigned, 2)
        self.assertEqual(row.unallocated, 0)


# ── §26.6 Training and §26.7 clusters and meetings ───────────────────────────
class TrainingAndClusterTest(World):
    def test_journey_six_a_session_fills_one_slot_per_school_on_its_roster(self):
        members = [
            self.school("client", self.cceo, cluster=self.cluster) for _ in range(25)
        ]
        self.session("cluster_training", members[:20])
        t = self.tree().country
        self.assertEqual(t.training, 20)
        self.assertEqual(t.any_training, 20)
        self.assertEqual(t.no_training, 5)
        self.assertEqual(t.training_gap, 5)

    def test_an_invited_school_off_the_roster_is_not_counted(self):
        members = [
            self.school("client", self.cceo, cluster=self.cluster) for _ in range(3)
        ]
        self.session("cluster_training", members[:1])
        self.session("cluster_training", members[1:2], invited=False)
        self.assertEqual(self.tree().country.any_training, 1)

    def test_training_slots_count_once_per_school_and_cap_at_its_requirement(self):
        client = self.school("client", self.cceo, cluster=self.cluster)
        core = self.school("core", self.cceo, cluster=self.cluster)
        self.activity(client, "in_school_training", owner=self.cceo, on=10)
        self.activity(client, "in_school_training", owner=self.cceo, on=20)
        self.session("cluster_training", [client, core])
        t = self.tree().country
        self.assertEqual(t.training_slots, 1 + 4)
        self.assertEqual(t.training, 1 + 1)
        self.assertEqual(t.any_training, 2)

    def test_journey_seven_meeting_coverage_is_the_planned_roster(self):
        members = [
            self.school("client", self.cceo, cluster=self.cluster) for _ in range(30)
        ]
        self.session("cluster_meeting", members[:22])
        t = self.tree().country
        self.assertEqual(t.clustered, 30)
        self.assertEqual(t.meeting_covered, 22)
        self.assertEqual(t.meeting_covered_clustered, 22)
        self.assertEqual(t.clustered_no_meeting, 8)

    def test_a_school_in_several_cluster_records_counts_once_and_is_flagged(self):
        school = self.school("client", self.cceo, cluster=self.cluster)
        other = Cluster.objects.create(
            name="Other",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
        )
        SchoolClusterAssignment.objects.get_or_create(
            school=school, cluster=self.cluster, defaults={"assigned_by": "t"}
        )
        SchoolClusterAssignment.objects.create(
            school=school, cluster=other, assigned_by="t"
        )
        tree = self.tree()
        self.assertEqual(tree.country.clustered, 1)
        from apps.planning.country_oversight.data_quality import checks

        found = {
            c.key: c
            for c in checks(svc.dataset_for(self.cd_user, window_for(FY)), tree)
        }
        self.assertEqual(found["several_clusters"].count, 1)

    def test_an_inactive_cluster_does_not_make_a_school_clustered(self):
        dormant = Cluster.objects.create(
            name="Dormant",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="inactive",
        )
        self.school("client", self.cceo, cluster=dormant)
        self.assertEqual(self.tree().country.unclustered, 1)


# ── §26.8 The hierarchy reconciles ───────────────────────────────────────────
class HierarchyTest(World):
    def test_country_equals_its_leads_and_each_lead_its_people(self):
        for owner, count in (
            (self.cceo, 3),
            (self.cceo2, 2),
            (self.cceo3, 4),
            (self.pl, 2),
        ):
            for index in range(count):
                school = self.school(
                    "core" if index == 0 else "client",
                    owner,
                    cluster=self.cluster if index % 2 else None,
                )
                self.activity(
                    school, "core_visit" if index == 0 else "school_visit", owner=owner
                )
        orphan_user, orphan = self.person("cpo-orphan", "Orphan", EdifyRole.CCEO)
        self.school("client", orphan)
        self.school("client", None)
        tree = self.tree()
        from apps.planning.country_oversight.data_quality import _reconciliation

        self.assertEqual(_reconciliation(tree), [])
        self.assertEqual(tree.country.schools, 3 + 2 + 4 + 2 + 2)
        no_lead = next(row for row in tree.leads if row.is_no_lead)
        self.assertEqual(no_lead.tally.schools, 2)
        self.assertEqual(self.lead_row(tree, self.pl).tally.schools, 3 + 2 + 2)
        self.assertEqual(self.lead_row(tree, self.pl2).tally.schools, 4)

    def test_an_officer_with_no_schools_is_still_a_row_under_their_lead(self):
        tree = self.tree()
        people = {row.key for row in self.lead_row(tree, self.pl).owners}
        self.assertIn(self.cceo.id, people)
        self.assertIn(self.cceo2.id, people)

    def test_partner_rows_and_staff_delivery_cover_the_officer(self):
        partnered = self.school("client", self.cceo)
        self.handover(partnered, self.partner)
        self.school("client", self.cceo)
        owner = self.owner_row(self.tree(), self.cceo)
        self.assertEqual(owner.partners[self.partner.id].schools, 1)
        self.assertEqual(owner.partners[svc.NO_PARTNER_KEY].schools, 1)
        self.assertEqual(
            sum(t.partner_assigned for t in owner.partners.values()),
            owner.tally.partner_assigned,
        )

    def test_charts_are_the_table(self):
        for owner in (self.cceo, self.cceo3):
            self.school("core", owner)
            self.school("client", owner, cluster=self.cluster)
        snapshot = svc.snapshot_for(self.cd_user, svc.Filters(fy=FY))
        charts = {chart["id"]: chart for chart in svc.charts(snapshot)}
        visit = charts["cpo-visit-chart"]
        for index, lead in enumerate(snapshot.tree.leads):
            parts = sum(series["data"][index] for series in visit["series"])
            self.assertEqual(parts, lead.tally.visit_slots, lead.name)
        unique = charts["cpo-unique-chart"]
        for index, lead in enumerate(snapshot.tree.leads):
            if lead.tally.schools:
                self.assertEqual(sum(s["data"][index] for s in unique["series"]), 100)
                self.assertEqual(
                    sum(s["counts"][index] for s in unique["series"]),
                    lead.tally.schools,
                )

    def test_filters_narrow_every_figure_together(self):
        self.school("core", self.cceo)
        self.school("client", self.cceo3)
        tree = self.tree(program_lead=self.pl.id)
        self.assertEqual(tree.country.schools, 1)
        self.assertEqual([lead.key for lead in tree.leads], [self.pl.id])
        self.assertEqual(self.tree(family=policy.CLIENT_FAMILY).country.schools, 1)
        self.assertEqual(self.tree(cceo=self.cceo3.id).country.schools, 1)


# ── §24.4 The rollup is the school-by-school fold ────────────────────────────
class RollupTest(World):
    """A filter change is answered from schools' figures summed into cells.
    These hold the cells to the school-by-school fold, figure for figure,
    under every filter — and the cached forms to the ones they came from."""

    def setUp(self):
        self.region2 = Region.objects.create(name="CPO East", country="Uganda")
        self.district2 = District.objects.create(name="CPO Jinja", region=self.region2)
        core = self.school("core", self.cceo)
        core2 = self.school("core", self.cceo, cluster=self.cluster)
        self.school("champion", self.cceo2)
        client = self.school("client", self.cceo, cluster=self.cluster)
        east_client = self.east(self.school("client", self.cceo2))
        trained = self.east(self.school("core_trained", self.cceo3))
        clustered = self.school("client", self.cceo3, cluster=self.cluster)
        personal = self.school("client", self.pl)
        self.school("", self.cceo)
        self.east(self.school("", self.cceo3))
        self.school("client", None)
        self.activity(core, "core_visit", owner=self.cceo, on=10)
        self.activity(core, "core_visit", owner=self.cceo, on=120)
        self.activity(
            core, "core_visit", partner=self.partner, status="partner_scheduled", on=200
        )
        self.handover(core2, self.partner)
        self.handover(core2, self.partner2)
        self.activity(client, "school_visit", owner=self.cceo, on=20)
        self.activity(
            east_client,
            "school_visit",
            partner=self.partner2,
            status="partner_scheduled",
            on=100,
        )
        self.handover(trained, self.partner)
        self.handover(
            clustered,
            self.partner,
            status="returned_to_staff",
            returned_at=timezone.now(),
        )
        self.activity(personal, "school_visit", owner=self.pl, on=300)
        self.session("cluster_meeting", [core2, clustered])
        self.session("cluster_training", [client, core])

    def east(self, school):
        School.objects.filter(pk=school.pk).update(
            region=self.region2, district=self.district2
        )
        return school

    def dataset(self, **period):
        filters = svc.Filters(fy=FY, **period)
        return svc.build_dataset(svc.system_scope("Uganda"), filters.window)

    def assertSameTree(self, got, want, label):
        self.assertEqual(got.country.values, want.country.values, label)
        self.assertEqual(
            [lead.key for lead in got.leads], [lead.key for lead in want.leads], label
        )
        for lead, other in zip(got.leads, want.leads):
            self.assertEqual(lead.tally.values, other.tally.values, (label, lead.name))
            self.assertEqual(
                [o.key for o in lead.owners],
                [o.key for o in other.owners],
                (label, lead.name),
            )
            for owner, twin in zip(lead.owners, other.owners):
                self.assertEqual(
                    owner.tally.values, twin.tally.values, (label, owner.name)
                )
                self.assertEqual(
                    {key: tally.values for key, tally in owner.partners.items()},
                    {key: tally.values for key, tally in twin.partners.items()},
                    (label, owner.name),
                )

    def test_every_filter_folds_the_same_from_the_cells(self):
        from apps.planning.country_oversight.requirements import (
            NO_LEAD_KEY,
            NO_OWNER_KEY,
        )

        choices = [
            {},
            {"region": self.region.id},
            {"region": self.region2.id},
            {"district": self.district2.id},
            {"program_lead": self.pl.id},
            {"program_lead": self.pl2.id},
            {"program_lead": NO_LEAD_KEY},
            {"cceo": self.cceo.id},
            {"cceo": NO_OWNER_KEY},
            {"family": policy.CORE_FAMILY},
            {"family": policy.CLIENT_FAMILY},
            {"cluster_status": "clustered"},
            {"cluster_status": "unclustered"},
            {"planning_status": "full"},
            {"planning_status": "partial"},
            {"planning_status": "none"},
            {"planning_status": "awaiting"},
            {"channel": "staff"},
            {"channel": "partner"},
            {"program_lead": self.pl.id, "family": policy.CLIENT_FAMILY},
            {"region": self.region2.id, "planning_status": "none"},
            {"cceo": self.cceo.id, "cluster_status": "clustered", "channel": "partner"},
            {
                "channel": "staff",
                "planning_status": "partial",
                "family": policy.CORE_FAMILY,
            },
        ]
        for period in (
            {},
            {"period": "quarter", "quarter": "Q1"},
            {"period": "month", "month": 10},
        ):
            dataset = self.dataset(**period)
            for choice in choices:
                filters = svc.Filters(fy=FY, **period, **choice)
                with self.subTest(period=period, filters=choice):
                    self.assertSameTree(
                        svc.fold(dataset, filters),
                        svc.fold(dataset, filters, placement=True),
                        f"{period} {choice}",
                    )
        # The world exercises what the cells split on.
        dataset = self.dataset()
        country = svc.fold(dataset, svc.Filters(fy=FY)).country
        for figure in (
            "fully_planned",
            "partially_planned",
            "not_planned",
            "awaiting_partner",
            "clustered",
            "unclustered",
            "returned",
        ):
            self.assertGreater(getattr(country, figure), 0, figure)
        self.assertEqual(country.unmapped_schools, 2)
        partner_keys = {key[-1] for key in dataset.cells[""][1]}
        self.assertEqual(
            partner_keys, {self.partner.id, self.partner2.id, svc.NO_PARTNER_KEY}
        )
        self.assertEqual(
            len({key[1] for key in dataset.cells[""][0]}), 2
        )  # both regions

    def test_a_filtered_school_list_reads_the_kept_figures_faithfully(self):
        from apps.planning.country_oversight.coverage import claims_for
        from apps.planning.country_oversight.hierarchy import IDX, school_values

        dataset = self.dataset()
        for record in dataset.facts.values():
            if record.is_governed:
                claims = claims_for(
                    record, dataset.allocations[record.id], dataset.window
                )
                self.assertEqual(
                    record.vector, tuple(school_values(record, claims)), record.name
                )
        for gap in ("", *svc.GAP_FIGURES):
            for scope in ({}, {"owner_key": self.cceo.id}, {"lead_key": self.pl.id}):
                for status in ("", "none", "awaiting"):
                    filters = svc.Filters(fy=FY, planning_status=status)
                    listing = svc.school_rows(dataset, filters, gap=gap, **scope)
                    want = []
                    for record in dataset.facts.values():
                        owner = dataset.owners.get(record.owner_key)
                        if not record.is_governed or not svc._keeps(
                            record, owner, filters
                        ):
                            continue
                        if (
                            scope.get("owner_key")
                            and record.owner_key != scope["owner_key"]
                        ):
                            continue
                        if (
                            scope.get("lead_key")
                            and (owner.lead_key if owner else "") != scope["lead_key"]
                        ):
                            continue
                        claims = claims_for(
                            record, dataset.allocations[record.id], dataset.window
                        )
                        if not svc._status_matches(claims, filters):
                            continue
                        values = school_values(record, claims)
                        amount = values[IDX[gap]] if gap else values[IDX["unallocated"]]
                        if gap and amount <= 0:
                            continue
                        want.append((-amount, record.name.casefold(), record.id))
                    want.sort()
                    with self.subTest(gap=gap, scope=scope, status=status):
                        self.assertEqual(listing["total"], len(want))
                        self.assertEqual(
                            [row["id"] for row in listing["rows"]],
                            [row[2] for row in want[: svc.SCHOOLS_PER_PAGE]],
                        )

    def test_the_cached_dataset_reads_back_as_it_was_built(self):
        import pickle

        from apps.planning.country_oversight.coverage import FactsTable, SchoolRecord

        dataset = self.dataset()
        # nosec B301 - the bytes are the ones this test just made, pickled the
        # way Django's cache pickles the dataset; nothing untrusted is read.
        restored = pickle.loads(pickle.dumps(dataset, pickle.HIGHEST_PROTOCOL))  # nosec B301
        self.assertIsInstance(restored.facts, FactsTable)
        self.assertEqual(restored.facts, dataset.facts)
        self.assertTrue(
            all(isinstance(r, SchoolRecord) for r in restored.facts.values())
        )
        self.assertEqual(restored.allocations, dataset.allocations)
        self.assertEqual(restored.cells, dataset.cells)
        self.assertEqual(
            sorted(len(schools) for schools in restored.by_owner.values()),
            sorted(len(schools) for schools in dataset.by_owner.values()),
        )
        filters = svc.Filters(fy=FY, program_lead=self.pl.id)
        self.assertSameTree(
            svc.fold(restored, filters), svc.fold(dataset, filters), "pickled"
        )
        rollup = svc.rollup_of(dataset)
        self.assertSameTree(
            svc.fold(pickle.loads(pickle.dumps(rollup)), filters),  # nosec B301
            svc.fold(dataset, filters),
            "rollup pickled",
        )
        with self.assertRaises(ValueError):
            svc.fold(rollup, svc.Filters(fy=FY, channel="staff"))

    def test_the_warmer_publishes_what_the_director_is_served(self):
        from unittest.mock import patch

        from django.core.cache import cache
        from django.test import override_settings

        with override_settings(DASHBOARD_CACHE_SECONDS=300):
            cache.clear()
            targets = svc.warm_targets()
            self.assertIn(("Uganda", svc.Filters(fy=FY)), targets)
            self.assertEqual(svc.warm(targets), 1)
            with patch.object(
                svc, "build_dataset", side_effect=AssertionError("built on open")
            ):
                snapshot = svc.snapshot_for(self.cd_user, svc.Filters(fy=FY))
                svc.snapshot_for(
                    self.cd_user, svc.Filters(fy=FY, program_lead=self.pl.id)
                )
                svc.dataset_for(self.cd_user, window_for(FY))
            self.assertSameTree(
                snapshot.tree, svc.fold(self.dataset(), svc.Filters(fy=FY)), "warmed"
            )
            # A window a country reader opens is kept warm for the next hour.
            svc.snapshot_for(
                self.cd_user, svc.Filters(fy=FY, period="quarter", quarter="Q2")
            )
            self.assertIn(
                ("Uganda", svc.Filters(fy=FY, period="quarter", quarter="Q2")),
                svc.warm_targets(),
            )
            cache.clear()
        with override_settings(DASHBOARD_CACHE_SECONDS=0):
            self.assertEqual(svc.warm(), 0)

    def test_a_worker_reuses_its_copy_only_while_it_is_the_published_build(self):
        from django.core.cache import cache
        from django.test import override_settings

        window = window_for(FY)
        with override_settings(DASHBOARD_CACHE_SECONDS=300):
            cache.clear()
            first = svc.dataset_for(self.cd_user, window)
            self.assertIs(svc.dataset_for(self.cd_user, window), first)
            # The warmer publishes a new build: every worker moves to it.
            svc.warm([("Uganda", svc.Filters(fy=FY))])
            second = svc.dataset_for(self.cd_user, window)
            self.assertNotEqual(second.stamp, first.stamp)
            self.assertIs(svc.dataset_for(self.cd_user, window), second)
            # Refresh rebuilds, and a worker still holding the old build
            # (another process, here simulated) reads the new one instead.
            third = svc.dataset_for(self.cd_user, window, refresh=True)
            self.assertNotEqual(third.stamp, second.stamp)
            svc._HELD.clear()
            svc._HELD[svc._key("facts", "country:Uganda", window)] = second
            self.assertEqual(svc.dataset_for(self.cd_user, window).stamp, third.stamp)
            cache.clear()
            svc._HELD.clear()


# ── §26.9 Follow Up with PL ──────────────────────────────────────────────────
class FollowUpTest(World):
    def setUp(self):
        self.gap_school = self.school("client", self.cceo)
        self.core_school = self.school("core", self.cceo)

    def scope(self, **extra):
        window = window_for(FY)
        return fu.Scope(
            fy=FY,
            period_type="fy",
            period_start=window.start,
            period_end=window.end,
            lead_key=self.pl.id,
            cceo_key=self.cceo.id,
            country="Uganda",
            **extra,
        )

    def send(self, sender=None, issue="staff_visit_gap", **extra):
        return fu.send_follow_up(
            sender=sender or self.cd_user,
            scope=self.scope(),
            issue_key=issue,
            instruction=extra.pop("instruction", "Plan the staff visits"),
            due_date=extra.pop("due", date.today() + timedelta(days=5)),
            priority=extra.pop("priority", "high"),
        )

    def test_the_director_asks_the_lead_and_nothing_else_moves(self):
        counts = (
            Activity.objects.count(),
            PartnerAssignment.objects.count(),
            School.objects.values_list("account_owner_id", flat=True).count(),
        )
        followup, created = self.send()
        self.assertTrue(created)
        self.assertEqual(followup.status, FollowUpStatus.SENT_TO_PL)
        self.assertEqual(followup.program_lead_user_id, self.pl_user.id)
        self.assertEqual(followup.cceo_staff_id, self.cceo.id)
        self.assertEqual(followup.metric_key, "staff_gap")
        self.assertEqual(
            followup.remaining_value, followup.required_value - followup.planned_value
        )
        self.assertEqual(
            counts,
            (
                Activity.objects.count(),
                PartnerAssignment.objects.count(),
                School.objects.values_list("account_owner_id", flat=True).count(),
            ),
        )
        from apps.notifications.models import Notification

        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.pl_user.id, context_id=followup.id
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(recipient_id=self.cceo_user.id).exists()
        )
        from apps.audit.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                action="planning_followup.sent", subject_id=followup.id
            ).exists()
        )

    def test_asking_again_reminds_on_the_same_record(self):
        first, _ = self.send()
        second, created = self.send(instruction="Still waiting")
        self.assertFalse(created)
        self.assertEqual(first.id, second.id)
        self.assertEqual(second.reminder_count, 1)
        self.assertEqual(
            [entry["instruction"] for entry in second.instruction_history],
            ["Plan the staff visits", "Still waiting"],
        )
        self.assertEqual(PlanningOversightFollowUp.objects.count(), 1)

    def test_only_the_country_director_asks(self):
        for user in (self.ia_user, self.rvp_user, self.admin_user, self.pl_user):
            with self.subTest(role=user.active_role):
                with self.assertRaises(fu.FollowUpError):
                    self.send(sender=user)
        response = self.as_user(self.ia_user).post(
            "/country-planning-oversight/follow-up",
            {
                "fy": FY,
                "lead": self.pl.id,
                "owner": self.cceo.id,
                "issue": "staff_visit_gap",
                "due_date": (date.today() + timedelta(days=3)).isoformat(),
                "priority": "normal",
                "instruction": "x",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)

    def test_a_follow_up_needs_a_type_a_date_and_an_instruction(self):
        with self.assertRaises(fu.FollowUpError):
            self.send(instruction="  ")
        with self.assertRaises(fu.FollowUpError):
            self.send(due=date.today() - timedelta(days=1))
        with self.assertRaises(fu.FollowUpError):
            fu.send_follow_up(
                sender=self.cd_user,
                scope=self.scope(),
                issue_key="nonsense",
                instruction="x",
                due_date=date.today(),
                priority="normal",
            )

    def test_the_lead_gets_a_to_do_that_opens_team_oversight_on_the_officer(self):
        from apps.command_center.todo_service import get_todos

        followup, _ = self.send()
        rows = [
            row
            for row in get_todos(self.pl_user)["todos"]
            if row["id"] == f"cpofu-{followup.id}"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Follow Up with CCEO on Planning Gap")
        self.assertIn("/team-planning-oversight/?followup=", rows[0]["action_url"])
        self.assertIn(f"owner={self.cceo.id}", rows[0]["action_url"])
        cceo_rows = [
            row
            for row in get_todos(self.cceo_user)["todos"]
            if str(row["id"]).startswith("cpofu-")
        ]
        self.assertEqual(cceo_rows, [])
        client = self.as_user(self.pl_user)
        page = client.get(rows[0]["action_url"])
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f"/planning-follow-ups/{followup.id}")
        banner = client.get(
            f"/planning-follow-ups/{followup.id}", HTTP_HX_REQUEST="true"
        )
        self.assertContains(banner, "Acknowledge")

    def test_journey_nine_the_gap_closes_and_so_does_everything_derived(self):
        from apps.command_center.todo_service import get_todos

        followup, _ = self.send()
        client = self.as_user(self.pl_user)
        client.post(
            f"/planning-follow-ups/{followup.id}/acknowledge", HTTP_HX_REQUEST="true"
        )
        followup.refresh_from_db()
        self.assertEqual(followup.status, FollowUpStatus.ACKNOWLEDGED)
        response = client.post(
            f"/planning-follow-ups/{followup.id}/ask",
            {"note": "please"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        followup.refresh_from_db()
        self.assertEqual(followup.status, FollowUpStatus.ACTION_LINKED)
        self.assertTrue(followup.linked_team_action_ids)
        from apps.planning.action_models import TeamAction

        actions = TeamAction.objects.filter(id__in=followup.linked_team_action_ids)
        self.assertTrue(all(a.recipient_id == self.cceo_user.id for a in actions))
        # The officer plans every staff slot: the gap reaches zero.
        self.activity(self.gap_school, owner=self.cceo)
        self.activity(self.core_school, "core_visit", owner=self.cceo, on=10)
        self.activity(self.core_school, "core_visit", owner=self.cceo, on=20)
        self.assertEqual(fu.sweep()["resolved"], 1)
        followup.refresh_from_db()
        self.assertEqual(followup.status, FollowUpStatus.RESOLVED_AUTOMATICALLY)
        self.assertTrue(followup.resolved_by_system)
        self.assertEqual(
            [
                row
                for row in get_todos(self.pl_user)["todos"]
                if str(row["id"]).startswith("cpofu-")
            ],
            [],
        )
        from apps.planning.action_service import resolve_due_actions

        resolve_due_actions()
        self.assertFalse(
            TeamAction.objects.filter(
                id__in=followup.linked_team_action_ids,
                state__in=["open", "acknowledged", "in_progress"],
            ).exists()
        )

    def test_closing_by_hand_needs_a_reason(self):
        followup, _ = self.send(issue="other")
        with self.assertRaises(fu.FollowUpError):
            fu.close_with_reason(followup, self.cd_user, "")
        fu.close_with_reason(
            followup, self.cd_user, "Discussed at the quarterly review"
        )
        self.assertEqual(followup.status, FollowUpStatus.CLOSED_BY_CD)

    def test_the_lead_can_return_it_and_the_director_sees_it(self):
        from apps.command_center.todo_service import get_todos

        followup, _ = self.send()
        with self.assertRaises(fu.FollowUpError):
            fu.return_for_clarification(followup, self.pl_user, "")
        fu.return_for_clarification(followup, self.pl_user, "Which schools?")
        rows = [
            row
            for row in get_todos(self.cd_user)["todos"]
            if row["id"] == f"cpofu-back-{followup.id}"
        ]
        self.assertEqual(len(rows), 1)
        again, created = self.send(instruction="These twelve")
        self.assertFalse(created)
        self.assertEqual(again.status, FollowUpStatus.SENT_TO_PL)

    def test_someone_else_cannot_act_for_the_lead(self):
        followup, _ = self.send()
        with self.assertRaises(fu.FollowUpError):
            fu.acknowledge(followup, self.pl2_user)
        response = self.as_user(self.cceo_user).get(
            f"/planning-follow-ups/{followup.id}", HTTP_HX_REQUEST="true"
        )
        self.assertNotEqual(response.status_code, 200)

    def test_there_is_nothing_to_send_when_there_is_no_gap(self):
        self.activity(self.gap_school, owner=self.cceo)
        self.activity(self.core_school, "core_visit", owner=self.cceo, on=10)
        self.activity(self.core_school, "core_visit", owner=self.cceo, on=20)
        with self.assertRaises(fu.FollowUpError):
            self.send()


# ── §26.10 Permissions ───────────────────────────────────────────────────────
class PermissionTest(World):
    ROUTES = (
        "/country-planning-oversight/",
        "/country-planning-oversight/rows?level=lead&key={pl}",
        "/country-planning-oversight/drawer?kind=lead&key={pl}",
        "/country-planning-oversight/drawer?kind=kpi&metric=cpo_staff_visit_planning",
        "/country-planning-oversight/schools?gap=unallocated",
        "/country-planning-oversight/follow-ups-panel",
        "/country-planning-oversight/coverage-export",
    )

    def setUp(self):
        self.school("client", self.cceo)

    def test_country_roles_read_and_field_roles_do_not(self):
        for user, allowed in (
            (self.cd_user, True),
            (self.ia_user, True),
            (self.rvp_user, True),
            (self.pl_user, False),
            (self.cceo_user, False),
        ):
            client = self.as_user(user)
            for route in self.ROUTES:
                with self.subTest(role=user.active_role, route=route):
                    response = client.get(
                        route.format(pl=self.pl.id), HTTP_HX_REQUEST="true"
                    )
                    if allowed:
                        self.assertEqual(response.status_code, 200)
                    else:
                        self.assertNotEqual(response.status_code, 200)

    def test_the_regional_vp_reads_figures_but_not_school_rows(self):
        client = self.as_user(self.rvp_user)
        response = client.get(
            "/country-planning-oversight/schools?gap=unallocated",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "not part of this role")
        self.assertNotContains(response, "CPO-00")

    def test_another_countrys_director_reads_none_of_these_schools(self):
        kenya_user, kenya_cd = self.person(
            "cpo-ke-cd", "Kenya Director", EdifyRole.COUNTRY_DIRECTOR
        )
        kenya_cd.country = "Kenya"
        kenya_cd.save()
        self.assertEqual(self.tree(user=kenya_user).country.schools, 0)
        self.assertEqual(self.tree().country.schools, 1)

    def test_only_the_director_sees_follow_up_controls(self):
        director = self.as_user(self.cd_user).get("/country-planning-oversight/")
        reviewer = self.as_user(self.ia_user).get("/country-planning-oversight/")
        self.assertContains(director, "Follow Up with PL")
        self.assertNotContains(reviewer, ">Follow Up with PL<")
        self.assertContains(reviewer, "Data Quality")

    def test_the_page_posts_nothing_itself(self):
        import re

        body = (
            self.as_user(self.cd_user)
            .get("/country-planning-oversight/", HTTP_HX_REQUEST="true")
            .content.decode()
        )
        self.assertEqual(re.findall(r'<form[^>]*method=["\']post["\']', body, re.I), [])


# ── §26.11 Query budgets ─────────────────────────────────────────────────────
class QueryBudgetTest(World):
    """The page's cost does not grow with the estate (the scale gate's rule)."""

    def estate(self, schools):
        for index in range(schools):
            owner = (self.cceo, self.cceo2, self.cceo3)[index % 3]
            school = self.school(
                "core" if index % 5 == 0 else "client",
                owner,
                cluster=self.cluster if index % 2 else None,
            )
            self.activity(
                school,
                "core_visit" if index % 5 == 0 else "school_visit",
                owner=owner,
                on=index % 200,
            )
            if index % 7 == 0:
                self.handover(
                    school, self.partner
                ) if school.school_type != "core" else None

    def count(self, client, url):
        with CaptureQueriesContext(connection) as context:
            response = client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200, url)
        return len(context.captured_queries)

    def test_page_and_expansions_cost_the_same_at_any_size(self):
        client = self.as_user(self.cd_user)
        urls = (
            "/country-planning-oversight/",
            f"/country-planning-oversight/rows?level=lead&key={self.pl.id}",
            f"/country-planning-oversight/rows?level=owner&key={self.cceo.id}",
            f"/country-planning-oversight/schools?owner={self.cceo.id}",
        )
        self.estate(12)
        small = {url: self.count(client, url) for url in urls}
        self.estate(60)
        large = {url: self.count(client, url) for url in urls}
        for url in urls:
            with self.subTest(url=url):
                self.assertLessEqual(large[url], small[url] + 2, (small, large))
                self.assertLess(large[url], 90)


# ── Journeys 1, 4, 8 and 10 ──────────────────────────────────────────────────
class JourneyTest(World):
    def test_journey_one_country_visit_requirement(self):
        for school_type in ("core", "champion", "client", "core_trained", "client"):
            self.school(school_type, self.cceo)
        t = self.tree().country
        self.assertEqual((t.core_schools, t.client_schools), (2, 3))
        self.assertEqual(t.visit_slots, 4 * 2 + 3)
        self.assertEqual((t.core_staff_slots, t.core_partner_slots), (4, 4))

    def test_journey_four_partner_assignment_then_schedule(self):
        core = self.school("core", self.cceo)
        before = self.tree().country
        self.assertEqual((before.partner_expected, before.partner_assigned), (2, 0))
        self.handover(core, self.partner)
        assigned = self.tree().country
        self.assertEqual(
            (assigned.partner_assigned, assigned.partner_scheduled, assigned.planned),
            (1, 0, 0),
        )
        self.activity(
            core, "core_visit", status="partner_scheduled", partner=self.partner
        )
        PartnerAssignment.objects.filter(school=core).update(status="partner_scheduled")
        scheduled = self.tree().country
        self.assertEqual(
            (
                scheduled.partner_assigned,
                scheduled.partner_scheduled,
                scheduled.planned,
            ),
            (1, 1, 1),
        )
        self.assertEqual(scheduled.unallocated, 3)

    def test_journey_eight_the_country_opens_all_the_way_down(self):
        school = self.school("core", self.cceo, cluster=self.cluster)
        self.activity(school, "core_visit", owner=self.cceo)
        self.handover(school, self.partner)
        client = self.as_user(self.cd_user)
        page = client.get("/country-planning-oversight/")
        self.assertContains(page, "Uganda (Total)")
        self.assertContains(page, "Lead A")
        self.assertContains(
            page, f"/country-planning-oversight/rows?level=lead&amp;key={self.pl.id}"
        )
        people = client.get(
            f"/country-planning-oversight/rows?level=lead&key={self.pl.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(people, "Officer One")
        channels = client.get(
            f"/country-planning-oversight/rows?level=owner&key={self.cceo.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(channels, "Partner Alpha")
        drawer = client.get(
            f"/country-planning-oversight/drawer?kind=partner&key={self.cceo.id}&partner_key={self.partner.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(drawer.status_code, 200)
        schools = client.get(
            f"/country-planning-oversight/schools?owner={self.cceo.id}&partner_key={self.partner.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(schools, school.name)
        slots = client.get(
            f"/country-planning-oversight/slots?school={school.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(slots, "Core Staff Visit 1")
        self.assertContains(slots, "Core Partner Visit 1")
        self.assertContains(slots, "Assigned")

    def test_journey_ten_a_slot_claimed_twice_is_counted_once_and_flagged(self):
        from apps.core_schools.models import (
            CorePlan,
            CoreActivitySlot,
            cplan_id,
            cslot_id,
        )
        from apps.planning.country_oversight.data_quality import checks

        school = self.school("core", self.cceo)
        visit = self.activity(school, "core_visit", owner=self.cceo)
        plan = CorePlan.objects.create(
            id=cplan_id(school.school_id, FY), school_id=school.school_id, fy=FY
        )
        for seq in (1, 2):
            CoreActivitySlot.objects.create(
                id=cslot_id(school.school_id, "v", seq, FY),
                core_plan=plan,
                school_id=school.school_id,
                intervention="christlike_behaviour",
                activity_type="visit",
                sequence_number=seq,
                activity_id=visit.id,
            )
        tree = self.tree()
        self.assertEqual(tree.country.staff, 1)
        found = {
            c.key: c
            for c in checks(svc.dataset_for(self.cd_user, window_for(FY)), tree)
        }
        self.assertGreaterEqual(found["over_claimed"].count, 1)


# ── The page ─────────────────────────────────────────────────────────────────
class PageTest(World):
    def test_the_dashboard_draws_the_owner_design(self):
        self.school("core", self.cceo)
        body = (
            self.as_user(self.cd_user)
            .get("/country-planning-oversight/")
            .content.decode()
        )
        for text in (
            "Country Planning Oversight",
            "Annual View",
            "Last updated",
            "Portfolio as of",
            "Apply Filters",
            "Staff Visit Planning",
            "Partner Planning",
            "Total Visit Coverage",
            "Training Planning",
            "Cluster Membership",
            "Cluster Meeting Planning",
            "Visit Requirement &amp; Planning by Program Lead",
            "Unique School Visit Coverage by Program Lead",
            "Training Planning by Program Lead",
            "Cluster &amp; Cluster-Meeting Coverage",
            "Partner Drill-down",
            "Open Follow-ups",
            "All values are for oversight only",
            # Two stages only (owner, 2026-09-28); the activity plan, the
            # planning monitor and the portfolio stay a row menu away.
            "Country General Planning Oversight",
            "Country Execution &amp; Completion Oversight",
            "Country Plan",
            "Planning Monitor",
            "Country Portfolio",
        ):
            with self.subTest(text=text):
                self.assertIn(text, body)

    def test_names_open_and_close_the_rows_under_them(self):
        # Like a cluster accordion (owner, 2026-09-30): a click on a Lead's
        # name opens their CCEOs, a click on a CCEO's their delivery
        # channels, and another click closes them; the chevron is the same
        # switch, and each set of rows is fetched on the first opening only.
        school = self.school("core", self.cceo, cluster=self.cluster)
        self.activity(school, "core_visit", owner=self.cceo)
        self.handover(school, self.partner)
        client = self.as_user(self.cd_user)
        body = client.get("/country-planning-oversight/").content.decode()
        lead = body[body.index(f'data-lead="{self.pl.id}"') :]
        lead = lead[: lead.index("</tbody>")]
        self.assertIn('<span data-opens-rows @click="toggle()">Lead A</span>', lead)
        self.assertRegex(lead, r'class="cpo-toggle"[^>]*\s@click="toggle\(\)"')
        self.assertIn("toggle() { this.open = !this.open; this.load(); }", body)
        self.assertIn("if (!this.loaded) { this.loaded = true;", body)
        self.assertIn("if (more && !more.dataset.asked)", body)
        people = client.get(
            f"/country-planning-oversight/rows?level=lead&key={self.pl.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        ).content.decode()
        opener = f"toggleOwner('{self.cceo.id}', 'p"
        self.assertIn(f'<span data-opens-rows @click.self="{opener}', people)
        self.assertRegex(
            people, rf'class="cpo-toggle"[^>]*\s@click="{re.escape(opener)}\d+\'\)"'
        )

    def test_two_line_headings_carry_their_own_break(self):
        # The design sets the table's headings on two short lines. The break
        # is written in, so each line keeps the platform's one-line rule: a
        # heading left to wrap on its own breaks differently at every width,
        # and the responsive contract counts it (e2e, team-oversight family).
        self.school("core", self.cceo)
        body = (
            self.as_user(self.cd_user)
            .get("/country-planning-oversight/")
            .content.decode()
        )
        for heading in (
            "Core<br>Schools",
            "Client<br>Schools",
            "Required<br>Visits",
            "Staff<br>Planned",
            "Partner<br>Assigned",
            "Partner<br>Scheduled",
            "Training<br>Coverage",
            "Cluster Meeting<br>Coverage",
            "Open<br>Follow-ups",
        ):
            with self.subTest(heading=heading):
                self.assertIn(f'<th scope="col">{heading}</th>', body)

    def test_a_phone_reads_short_stage_names_and_the_first_three_filters(self):
        # Both stage names side by side on a 390px phone (the second went
        # behind the rail's "More"); the full name stays the accessible name.
        # The four other filters wait behind More filters on a phone unless
        # set; the table's own actions keep their names as icons.
        self.school("core", self.cceo)
        client = self.as_user(self.cd_user)
        body = client.get("/country-planning-oversight/").content.decode()
        for short, full in (
            ("General Planning", "Country General Planning Oversight"),
            (
                "Execution &amp; Completion",
                "Country Execution &amp; Completion Oversight",
            ),
        ):
            with self.subTest(tab=short):
                self.assertIn(f'aria-label="{full}"', body)
                self.assertIn(f'<span class="sm:hidden">{short}</span>', body)
                self.assertIn(f'<span class="hidden sm:inline">{full}</span>', body)
        self.assertEqual(body.count("cpo-field--minor"), 4)
        self.assertIn(":data-more=", body)
        self.assertIn('<span class="cpo-tool-label">Data Quality</span>', body)
        # A set filter stays in view on a phone.
        narrowed = client.get(
            f"/country-planning-oversight/?cceo={self.cceo.id}"
        ).content.decode()
        self.assertIn("cpo-field--minor is-set", narrowed)

    def test_the_old_lenses_are_still_there(self):
        client = self.as_user(self.cd_user)
        self.assertContains(
            client.get("/country-planning-oversight/?view=plan"), 'role="tab"'
        )
        # The portfolio lives on the Country Map (owner, 2026-09-28): an old
        # link keeps its filters on the way there.
        moved = client.get("/country-planning-oversight/?view=portfolio&district=d1")
        self.assertEqual(moved.status_code, 302)
        self.assertEqual(
            moved["Location"], "/country-map/?district=d1#country-portfolio"
        )
        self.assertEqual(client.get("/country-map/").status_code, 200)
        # A link made on the activity lens still lands on it.
        self.assertContains(
            client.get(f"/country-planning-oversight/?lead={self.pl.id}"), 'role="tab"'
        )

    def test_the_metrics_are_registered(self):
        from apps.core.metrics.registry import get_metric

        for key in svc.KPI_KEYS:
            spec = get_metric(key)
            self.assertEqual(spec.owner_page, "country_planning_oversight")
            self.assertTrue(spec.denominator)

    def test_the_templates_do_no_arithmetic(self):
        from pathlib import Path

        folder = (
            Path(__file__).resolve().parents[2] / "templates/partials/country_oversight"
        )
        for path in folder.glob("*.html"):
            with self.subTest(path=path.name):
                source = path.read_text()
                self.assertNotIn("widthratio", source)
                self.assertNotIn("|div", source)
                self.assertNotIn("|mul", source)

    def test_the_export_names_its_row_grain_and_matches_the_page(self):
        school = self.school("client", self.cceo)
        self.activity(school, owner=self.cceo)
        response = self.as_user(self.cd_user).get(
            f"/country-planning-oversight/coverage-export?fy={FY}&format=csv"
        )
        self.assertEqual(response.status_code, 200)
        lines = response.content.decode().strip().splitlines()
        self.assertIn("School ID", lines[0])
        self.assertEqual(len(lines) - 1, self.tree().country.schools)
