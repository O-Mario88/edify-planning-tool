"""Autopilot slice 1 under test — with the constitution front and centre.

The load-bearing assertions: a machine draft creates NO Activity rows,
consumes no budget and feeds no metric until a human accepts it; the
generator respects the same calendar gate as manual scheduling; regeneration
supersedes rather than stacks; and acceptance routes through the canonical
create() funnel with per-item refusals surfaced, never forced.
"""

from datetime import date

from django.test import TestCase

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.exceptions import BadRequest
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

from .models import ProposedPlan, ProposedPlanStatus
from .services import (
    accept_plan,
    dismiss_plan,
    generate_week_proposal,
    live_proposal_for,
)

# A fixed Monday inside FY2027 keeps the week deterministic.
WEEK = date(2026, 10, 19)


class AutopilotFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="pilot@example.test",
            name="Pilot CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(user=cls.user, title="CCEO")
        cls.region = Region.objects.create(name="AP Region")
        cls.district = District.objects.create(name="AP District", region=cls.region)
        cls.sub_a = SubCounty.objects.create(name="Pilot SC A", district=cls.district)
        cls.sub_b = SubCounty.objects.create(name="Pilot SC B", district=cls.district)

    def _school(self, name, sub_county, **overrides):
        school = School.objects.create(
            school_id=f"AP-{name}",
            name=name,
            region=self.region,
            district=self.district,
            sub_county=sub_county,
            school_type="client",
            **overrides,
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=school.id)
        return school


class GenerationTests(AutopilotFixture):
    def test_a_draft_creates_no_real_work_anywhere(self):
        self._school("Constitution One", self.sub_a)
        self._school("Constitution Two", self.sub_b)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        self.assertGreater(plan.items.count(), 0)
        # The constitutional guard: zero Activity rows, therefore zero budget
        # lines, zero planned-output movement, zero To-Dos — by construction.
        self.assertEqual(Activity.objects.count(), 0)

    def test_ssa_outstanding_schools_lead_the_draft(self):
        self._school("Covered SSA", self.sub_a, current_fy_ssa_status="done")
        self._school("Needs SSA", self.sub_a)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        first = plan.items.order_by("proposed_date", "id").first()
        self.assertEqual(first.school_name, "Needs SSA")
        self.assertIn("SSA outstanding", first.reason)

    def test_days_are_route_coherent_by_sub_county(self):
        for index in range(2):
            self._school(f"Area A {index}", self.sub_a)
        self._school("Area B 0", self.sub_b)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        by_day: dict = {}
        for item in plan.items.all():
            by_day.setdefault(item.proposed_date, set()).add(item.area)
        for areas in by_day.values():
            self.assertEqual(len(areas), 1)

    def test_approved_leave_blocks_the_whole_week_honestly(self):
        self._school("Leave School", self.sub_a)
        Leave.objects.create(
            staff=self.staff,
            type="personal_time_off",
            start_date="2026-10-19",
            end_date="2026-10-24",
            days=6,
            status="approved",
        )
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        self.assertEqual(plan.items.count(), 0)
        self.assertEqual(plan.rationale["workableDays"], [])

    def test_regeneration_supersedes_the_previous_draft(self):
        self._school("Regen School", self.sub_a)
        first = generate_week_proposal(self.staff, week_start=WEEK)
        second = generate_week_proposal(self.staff, week_start=WEEK)
        first.refresh_from_db()
        self.assertEqual(first.status, ProposedPlanStatus.DISMISSED)
        self.assertEqual(second.status, ProposedPlanStatus.PROPOSED)
        self.assertEqual(live_proposal_for(self.staff).id, second.id)

    def test_schools_already_supported_this_month_are_not_proposed(self):
        school = self._school("Already Supported", self.sub_a)
        Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            planned_date=date.today(),
            fy="2027",
            school=school,
            responsible_staff_id=self.staff.id,
        )
        other = self._school("Untouched", self.sub_b)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        proposed_schools = {item.school_id for item in plan.items.all()}
        self.assertNotIn(school.id, proposed_schools)
        self.assertIn(other.id, proposed_schools)


class AcceptanceTests(AutopilotFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # The funnel prices at scheduling time: acceptance needs the CD rate
        # card exactly as a hand-built plan would.
        from apps.budget.models import CostCatalogue, CostSetting

        catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda",
            fy="2027",
            version=1,
            defaults={"is_active": True, "label": "Autopilot Test Catalogue"},
        )
        catalogue.is_active = True
        catalogue.save(update_fields=["is_active"])
        for key, cost in (
            ("staff_visit_transport_primary", 280000),
            ("lunch", 30000),
            ("primary_transport_per_day", 280000),
            ("primary_lunch_per_day", 30000),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key,
                    "unit_cost": cost,
                    "fy": "2027",
                    "catalogue": catalogue,
                    "version": 1,
                },
            )

    def test_only_the_owner_accepts(self):
        self._school("Owned", self.sub_a)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        stranger = User.objects.create_user(
            email="stranger@example.test",
            name="Stranger",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )
        StaffProfile.objects.create(user=stranger, title="CCEO")
        with self.assertRaises(BadRequest):
            accept_plan(plan, principal=stranger)

    def test_acceptance_routes_through_the_canonical_funnel(self):
        self._school("Funnel School", self.sub_a)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        self.assertEqual(plan.items.count(), 1)
        result = accept_plan(plan, principal=self.user)
        plan.refresh_from_db()
        self.assertEqual(plan.status, ProposedPlanStatus.ACCEPTED)
        # STRICT: a generator that proposes work its own funnel refuses is a
        # defect (the audit found every item refused on an identifier-space
        # mismatch that the earlier tautological assertion waved through).
        self.assertEqual(result["refused"], [])
        self.assertEqual(len(result["created"]), 1)
        for activity_id in result["created"]:
            activity = Activity.objects.get(id=activity_id)
            self.assertEqual(activity.status, "scheduled")
            self.assertEqual(activity.responsible_staff_id, str(self.staff.id))

    def test_fy_consumed_client_entitlement_is_never_proposed(self):
        # A client school visited earlier in the FY carries no remaining
        # visit entitlement — proposing it guarantees a refusal, so the
        # generator applies the funnel's own rule up front.
        visited = self._school("Visited Client", self.sub_a)
        Activity.objects.create(
            activity_type="school_visit",
            status="ia_verified",
            planned_date=date(2026, 10, 5),
            fy="2027",
            school=visited,
            responsible_staff_id=self.staff.id,
        )
        fresh = self._school("Fresh Client", self.sub_b)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        proposed = {item.school_id for item in plan.items.all()}
        self.assertNotIn(visited.id, proposed)
        self.assertIn(fresh.id, proposed)

    def test_an_accepted_week_cannot_be_regenerated_over(self):
        self._school("Final School", self.sub_a)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        accept_plan(plan, principal=self.user)
        with self.assertRaises(BadRequest):
            generate_week_proposal(self.staff, week_start=WEEK)

    def test_dismissal_is_final_for_that_draft(self):
        self._school("Dismissed School", self.sub_a)
        plan = generate_week_proposal(self.staff, week_start=WEEK)
        dismiss_plan(plan, principal=self.user)
        self.assertIsNone(live_proposal_for(self.staff))
        self.assertEqual(
            ProposedPlan.objects.get(id=plan.id).status,
            ProposedPlanStatus.DISMISSED,
        )
