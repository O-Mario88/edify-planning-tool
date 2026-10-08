"""Core Schools Planning — the annual service-package operating page (§45).

Covers: sidebar/role gating, portfolio scoping (CCEO / PL / partner), the
Assessment + 4 Visits + 4 Trainings package, slot scheduling through the real
costed activity funnel (Activity + budget lines + My Plan), the school staying
on the page while its package is open, the partner two-step (assignment ≠
budget), slot completion gates (evidence + Activity SF ID + IA), the eight
official SSA interventions, the §17 recommendation split (2 Partner + 2
Staff), annual-only impact, package-completion integrity, and Champion
criteria.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from freezegun import freeze_time

from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.budget.models import CostCatalogue, CostSetting
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.core.navigation import build_sidebar_for_user
from apps.core.rbac import EdifyRole
from apps.core_schools.models import (
    CoreActivitySlot,
    CorePlan,
    CoreSchoolProfile,
    cplan_id,
    cprof_id,
    cslot_id,
)
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

User = get_user_model()
# The year of the frozen clock the tests below run on (`@freeze_time`), not of
# the real one: from 1 October 2026 the module-level call read FY2027 while
# every view under the frozen clock read FY2026.
FROZEN_TODAY = "2026-04-01"
FY = get_operational_fy(date.fromisoformat(FROZEN_TODAY))

# Varied scores → deterministic 4 weakest: TE(2) < GR(3) < LE(4) < Lship(5).
SCORE_MAP = {
    "christlike_behaviour": 9.0,
    "word_of_god": 8.5,
    "financial_health": 7.0,
    "leadership": 5.0,
    "learning_environment": 4.0,
    "government_requirement": 3.0,
    "teaching_environment": 2.0,
    "enrollment": 6.0,
}


def core_planning_setup(case):
    """The Core planning fixture, as a plain function.

    CoreSchoolsPlanningTest freezes its clock, and two other modules borrow
    this setup by assignment. Borrowing the decorated method would hand them
    freezegun's wrapper, which starts that clock without the tearDown that
    stops it — silently moving "today" for every test in those modules. They
    borrow this instead, and the class calls it.
    """
    # The clock this setUp runs on, frozen or not: test_core_visit_purposes
    # borrows this fixture on the real clock, test_core_planning on a frozen
    # one, and a package of the wrong year is "no active core package".
    fy = get_operational_fy()
    case.region = Region.objects.create(name="Core R")
    case.district = District.objects.create(
        name="Core D", region=case.region, district_type="primary"
    )
    case.cluster = Cluster.objects.create(
        name="Core Cluster", region=case.region, district=case.district
    )

    case.cceo, case.cceo_sp = case._staff(
        "cc@core.org", "Core Cceo", EdifyRole.CCEO.value
    )
    case.other_cceo, case.other_sp = case._staff(
        "oc@core.org", "Other Cceo", EdifyRole.CCEO.value
    )
    case.pl, case.pl_sp = case._staff(
        "pl@core.org", "Core PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
    )
    case.other_pl, case.other_pl_sp = case._staff(
        "opl@core.org", "Other PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
    )
    case.ia, _ = case._staff(
        "ia@core.org", "Core IA", EdifyRole.IMPACT_ASSESSMENT.value
    )
    case.accountant, _ = case._staff(
        "acc@core.org", "Core Acc", EdifyRole.PROGRAM_ACCOUNTANT.value
    )
    case.partner_user, _ = case._staff(
        "pa@core.org", "Partner Admin", EdifyRole.PARTNER_ADMIN.value
    )
    StaffSupervisorAssignment.objects.create(
        supervisor=case.pl_sp, supervisee=case.cceo_sp
    )

    case.school = case._school("CORE-1", "Alpha Core School", case.cceo_sp)
    case.other_school = case._school("CORE-2", "Beta Core School", case.other_sp)

    case.partner = Partner.objects.create(name="Core Helper Org", region_name="Core R")

    case.plan = case._plan(case.school)
    case._plan(case.other_school)
    case.core_visit_item = ActivityCatalogueItem.objects.get(
        stable_code="CORE_SCHOOL_FOLLOWUP_VISIT"
    )
    case.core_training_item = ActivityCatalogueItem.objects.get(
        stable_code="EARLY_CHILDHOOD_EDUCATION_PROJECT"
    )

    # Verified annual SSA with all eight interventions.
    case.ssa = SsaRecord.objects.create(
        school=case.school,
        fy=fy,
        quarter="Q1",
        average_score=5.6,
        verification_status="confirmed",
        date_of_ssa=date(int(fy) - 1, 11, 5),
        uploaded_by="test",
    )
    for code, score in SCORE_MAP.items():
        SsaScore.objects.create(ssa_record=case.ssa, intervention=code, score=score)

    # Costing so core visit scheduling can price.
    catalogue, _ = CostCatalogue.objects.get_or_create(
        country="Uganda",
        fy=fy,
        version=1,
        defaults={"is_active": True, "label": "Core Test Catalogue"},
    )
    catalogue.is_active = True
    catalogue.save(update_fields=["is_active"])
    for key, cost in (
        ("staff_visit_transport_primary", 250000),
        ("lunch", 30000),
        ("primary_transport_per_day", 250000),
        ("primary_lunch_per_day", 30000),
        ("partner_visit_lump_sum", 40000),
        ("partner_training_lump_sum", 60000),
        ("group_training_facilitation_fee", 50000),
        ("group_training_venue_cost", 80000),
        ("group_training_participant_meal_cost_per_head", 15000),
    ):
        # Scoped to this catalogue: from 1 October the post_migrate reference
        # data also seeds the new operational year's catalogue, so a key alone
        # matches two rows.
        CostSetting.objects.update_or_create(
            key=key,
            catalogue=catalogue,
            defaults={
                "label": key,
                "unit_cost": cost,
                "fy": fy,
                "version": 1,
            },
        )


# ── fixtures ─────────────────────────────────────────────────────────────


# Scheduling refuses a date that has passed (owner, 2026-09-16), and staff
# core support is released in the CURRENT quarter only — so "today" has to
# sit inside the quarter these slots are scheduled in, FY2026 Q3. The partner
# booking keeps a later quarter, which is the rule it exists to prove.
@freeze_time(FROZEN_TODAY)
class CoreSchoolsPlanningTest(TestCase):
    def setUp(self):
        core_planning_setup(self)

    def _staff(self, email, name, role):
        u = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return u, StaffProfile.objects.create(user=u, title=role)

    def _school(self, sid, name, owner_sp):
        s = School.objects.create(
            school_id=sid,
            name=name,
            region=self.region,
            district=self.district,
            school_type="core",
            current_fy_ssa_status="done",
            enrollment=200,
            account_owner_id=owner_sp.user_id,
        )
        School.objects.filter(id=s.id).update(cluster_id=self.cluster.id)
        StaffSchoolAssignment.objects.create(staff=owner_sp, school_id=s.id)
        return School.objects.get(id=s.id)

    def _plan(self, school):
        fy = get_operational_fy()
        plan = CorePlan.objects.create(
            id=cplan_id(school.school_id),
            school_id=school.school_id,
            fy=fy,
            status="Active",
        )
        CoreSchoolProfile.objects.create(
            id=cprof_id(school.school_id),
            school_id=school.school_id,
            core_plan=plan,
            core_start_fy=fy,
        )
        # Build the canonical 9-slot package (1 assessment + 4v + 4t) via the
        # production helper so fixtures never drift from real onboarding.
        from apps.core_schools.services import create_package_slots

        create_package_slots(plan, school.school_id, ["leadership"])
        return plan

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _schedule_visit(
        self,
        client=None,
        school=None,
        seq="1",
        when="2026-04-21",
        partner_id=None,
        responsible_staff_id=None,
    ):
        payload = {
            "school_id": (school or self.school).school_id,
            "visit_number": seq,
            "scheduled_date": when,
            "focus_intervention": "teaching_environment",
            # A package visit is a Training Follow Up: data collection (SSA
            # Support), the old default, is outside the package since
            # 2026-10-02.
            "purpose_of_visit": "training_follow_up",
            "visit_purpose": "Core package recovery visit",
            "expected_outcome": "Slot fulfilled",
            # "" asks the view to resolve it, which is what the drawer does
            # when nobody is picked; None keeps the historic default.
            "responsible_staff_id": (
                self.cceo_sp.id
                if responsible_staff_id is None
                else responsible_staff_id
            ),
            "catalogue_item_id": self.core_visit_item.id,
            "recommendation_reason": (
                "Current unresolved Teacher's Environment SSA need."
            ),
        }
        if partner_id:
            payload["assigned_partner_id"] = partner_id
        return (client or self._client(self.cceo)).post(
            "/core-schools/schedule-visit/action",
            payload,
        )

    def _hand_over_visit(self, seq="", *, client=None):
        """Assign one of the package's visits to the partner, who dates it
        (owner, 2026-10-05: staff no longer schedule for a partner)."""
        return (client or self._client(self.cceo)).post(
            "/core-schools/assign-partner/action",
            {
                "school_id": self.school.school_id,
                "partner_id": self.partner.id,
                "purpose_of_visit": "training_follow_up",
                "visit_training_number": seq,
            },
            HTTP_HX_REQUEST="true",
        )

    # ── 1–6: sidebar + scope ─────────────────────────────────────────────────
    def test_core_schools_sidebar_visible_to_field_roles(self):
        for user in (self.cceo, self.pl):
            labels = [
                i["label"]
                for sec in build_sidebar_for_user(user, "/")
                for i in sec["items"]
            ]
            self.assertIn("Core Schools", labels, user.email)

    def test_ia_keeps_core_school_access_without_the_sidebar_entry(self):
        """Sidebar information architecture is narrower than authorization.

        IA was moved out of the field-operations nav group (navigation.
        FIELD_NAV_ROLES) because its day-to-day work is verification, not
        planning. That is a presentation decision and it must stay one — an
        IA that can no longer REACH core-school data has lost a capability,
        not a menu item, and the sidebar change would have hidden the
        regression rather than caused a visible failure.
        """
        labels = [
            i["label"]
            for sec in build_sidebar_for_user(self.ia, "/")
            for i in sec["items"]
        ]
        self.assertNotIn("Core Schools", labels)
        self.assertEqual(self._client(self.ia).get("/core-schools").status_code, 200)

    def test_core_schools_sidebar_hidden_from_unauthorized_roles(self):
        """The sidebar entry belongs to the field roles. The CD and the
        Accountant reach the page anyway since 2026-09-02 — the Planning Core
        tab is their door — because a core visit they schedule is filed as a
        request the school's owner approves (apps.planning.visit_requests).
        Partners are still refused outright."""
        cd, _ = self._staff("cd@core.org", "Core CD", EdifyRole.COUNTRY_DIRECTOR.value)
        for user in (cd, self.accountant, self.partner_user):
            labels = [
                i["label"]
                for sec in build_sidebar_for_user(user, "/")
                for i in sec["items"]
            ]
            self.assertNotIn("Core Schools", labels, user.email)
        for user in (cd, self.accountant):
            self.assertEqual(
                self._client(user).get("/core-schools").status_code, 200, user.email
            )
        self.assertNotEqual(
            self._client(self.partner_user).get("/core-schools").status_code, 200
        )

    def test_cceo_sees_only_assigned_core_schools(self):
        html = self._client(self.cceo).get("/core-schools").content.decode()
        self.assertIn("Alpha Core School", html)
        self.assertNotIn("Beta Core School", html)

    def test_pl_operational_core_list_excludes_a_supervised_cceos_school(self):
        """Supervision is not ownership.

        This asserted the opposite until the direct-portfolio rule landed: the
        Programme Lead's *operational* Core list showed their CCEOs' core
        schools with Schedule, Assign and Upload Assessment live on every one.
        The work is still visible — on the read-only oversight lens, where the
        next step is to ask the CCEO who owns it.
        """
        html = self._client(self.pl).get("/core-schools").content.decode()
        self.assertNotIn("Alpha Core School", html)
        self.assertIn("No Core Schools in your portfolio", html)
        self.assertIn("lens=oversight", html)

    def test_pl_sees_the_supervised_core_school_on_the_oversight_lens(self):
        response = self._client(self.pl).get("/core-schools?lens=oversight")
        html = response.content.decode()
        self.assertIn("Alpha Core School", html)
        self.assertIn("Read-Only Team Oversight", html)
        self.assertNotIn("/core-schools/schedule-", html)
        self.assertNotIn("/core-schools/assign-partner", html)

    def test_pl_cannot_see_other_pl_core_schools(self):
        html = self._client(self.other_pl).get("/core-schools").content.decode()
        self.assertNotIn("Alpha Core School", html)

    def test_partner_sees_only_assigned_core_work(self):
        other_partner = Partner.objects.create(name="Unrelated Org")
        PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cceo_sp.id,
            status="assigned",
        )
        mine = PartnerAssignment.objects.filter(partner=self.partner)
        self.assertEqual(mine.count(), 1)
        self.assertEqual(
            PartnerAssignment.objects.filter(partner=other_partner).count(), 0
        )
        self.assertNotEqual(
            self._client(self.partner_user).get("/core-schools").status_code, 200
        )

    # ── 7: the package definition ────────────────────────────────────────────
    def test_core_school_requires_assessment_four_visits_four_trainings(self):
        slots = CoreActivitySlot.objects.filter(core_plan=self.plan)
        # The mandated 9-slot package: 1 assessment + 4 visits + 4 trainings.
        self.assertEqual(slots.filter(activity_type="assessment").count(), 1)
        self.assertEqual(slots.filter(activity_type="visit").count(), 4)
        self.assertEqual(slots.filter(activity_type="training").count(), 4)
        self.assertEqual(slots.count(), 9)
        self.assertEqual(self.plan.visits_target, 4)
        self.assertEqual(self.plan.trainings_target, 4)
        self.assertIsNone(self.plan.baseline_average)  # assessment still required
        html = self._client(self.cceo).get("/core-schools").content.decode()
        self.assertIn("Visits:", html)
        self.assertIn("Trainings:", html)
        self.assertIn("0/4", html)
        self.assertNotIn("Core service package", html)
        self.assertNotIn("Create Core Plan", html)

    def test_core_school_expansion_shows_real_grouped_ssa_recommendations(self):
        """The core matrix must use its confirmed saved scores, not a summary."""
        self.school.shipping_address = "Plot 12, Kampala Road"
        self.school.save(update_fields=["shipping_address"])
        response = self._client(self.cceo).get(f"/core-schools?fy={FY}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'x-data="{ openSchoolId: null }"')
        self.assertContains(response, '@click.outside="openSchoolId = null"')
        self.assertContains(response, "SSA interventions needing urgent attention")
        self.assertContains(response, "SSA interventions performing well")
        self.assertContains(response, "SSA interventions to watch")
        self.assertContains(response, "Teacher&#x27;s Environment")
        self.assertContains(response, "(2/10)")
        self.assertContains(response, "Christlike Behaviour")
        self.assertContains(response, "(9/10)")
        self.assertContains(response, "Plot 12, Kampala Road")
        self.assertContains(response, "Owner:")
        self.assertContains(response, "Core Cceo")
        self.assertContains(response, ">Core<")
        # Schedule and Assign are entries in the row's one Actions menu
        # (owner, 2026-09-26), not buttons that wrap on a tablet.
        self.assertContains(response, "data-row-actions")
        self.assertContains(response, 'class="row-menu__item" role="menuitem"')
        self.assertContains(response, ">Schedule<")
        self.assertContains(response, ">Assign<")

        row = next(
            item
            for item in response.context["matrix_rows"]
            if item["school_id"] == self.school.school_id
        )
        self.assertTrue(row["has_ssa_scores"])
        self.assertEqual(row["ssa_average"], 5.6)
        self.assertEqual(row["staff_name"], "Core Cceo")

    # ── 8–11: scheduling through the real funnel ─────────────────────────────
    def test_scheduling_core_slot_creates_activity(self):
        resp = self._schedule_visit()
        self.assertIn(resp.status_code, (200, 302), resp.content[:200])
        act = Activity.objects.filter(
            school=self.school, activity_type="core_visit"
        ).first()
        self.assertIsNotNone(act)
        self.assertEqual(act.status, "scheduled")
        slot = CoreActivitySlot.objects.get(id=cslot_id(self.school.school_id, "v", 1))
        self.assertEqual(slot.status, "Scheduled")
        self.assertEqual(slot.activity_id, act.id)

    def test_core_school_list_uses_live_support_counts(self):
        from apps.core_schools.core_planning_services import CorePackageProgressService

        response = self._schedule_visit()
        self.assertIn(response.status_code, (200, 302), response.content[:200])

        row = CorePackageProgressService.get_matrix_data(
            School.objects.filter(id=self.school.id), FY
        )[0]
        self.assertEqual(row["scheduled_visit_count"], 1)
        self.assertEqual(row["scheduled_training_count"], 0)
        self.assertFalse(row["package_complete"])

        html = self._client(self.cceo).get("/core-schools").content.decode()
        self.assertIn("1/4", html)
        self.assertNotIn("Core service package", html)

    def test_core_slot_dropdowns_use_plain_language_and_hide_used_slots(self):
        visit_drawer = self._client(self.cceo).get(
            f"/core-schools/schedule-visit?school_id={self.school.school_id}"
        )
        self.assertContains(visit_drawer, "First Visit")
        self.assertContains(visit_drawer, "Second Visit")
        self.assertNotContains(visit_drawer, "V1 Visit")

        scheduled = self._schedule_visit(seq="1")
        self.assertIn(scheduled.status_code, (200, 302), scheduled.content[:200])
        remaining_visit_drawer = self._client(self.cceo).get(
            f"/core-schools/schedule-visit?school_id={self.school.school_id}"
        )
        self.assertNotContains(remaining_visit_drawer, "First Visit")
        self.assertContains(remaining_visit_drawer, "Second Visit")

        CoreActivitySlot.objects.filter(
            core_plan=self.plan, activity_type="training", sequence_number=1
        ).update(status="Scheduled")
        training_drawer = self._client(self.cceo).get(
            f"/core-schools/schedule-training?school_id={self.school.school_id}"
        )
        self.assertNotContains(training_drawer, "First Training")
        self.assertContains(training_drawer, "Second Training")

    def test_core_chooser_keeps_general_activities_available_after_package_completion(
        self,
    ):
        # The staff half of the package taken (owner, 2026-09-30: two staff
        # visits and two staff trainings).
        for activity_type in (
            "core_visit",
            "core_visit",
            "core_training",
            "core_training",
        ):
            Activity.objects.create(
                activity_type=activity_type,
                school=self.school,
                fy=FY,
                quarter="Q3",
                status="scheduled",
                delivery_type="staff",
            )

        response = self._client(self.cceo).get(
            f"/core-schools/schedule-activity?school_id={self.school.school_id}"
        )
        # The chooser labels each exhausted option in place. The behaviour
        # under test is unchanged -- the staff's package work is used up,
        # general activities remain.
        self.assertContains(response, "Core visit · staff visits complete (2/2)")
        self.assertContains(response, "Core training · staff trainings complete (2/2)")
        self.assertContains(response, "Schedule other activity")
        self.assertContains(
            response,
            f"/planning/schedule-modal?school_id={self.school.school_id}",
        )

    def test_general_school_schedule_uses_ssa_evidence_and_a_visit_purpose(self):
        response = self._client(self.cceo).get(
            f"/planning/schedule-modal?school_id={self.school.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recommended interventions")
        # The SSA evidence is the list under that heading (it replaced "SSA
        # interventions performing poorly"): the weakest confirmed scores.
        recommendations = (
            response.content.decode()
            .split('aria-labelledby="top-ssa-recommendation-title"', 1)[1]
            .split("</section>", 1)[0]
        )
        self.assertIn("Teacher&#x27;s Environment", recommendations)
        self.assertIn("/10", recommendations)
        self.assertContains(response, "Purpose of visit")
        self.assertContains(response, "In-school Training")
        self.assertContains(response, "SSA Support")
        self.assertContains(response, "Teacher&#x27;s Environment")
        self.assertNotContains(response, "Recommended Activities")
        self.assertNotContains(response, 'name="activity_name"')

    def test_general_free_text_visit_type_is_rejected(self):
        response = self._client(self.cceo).post(
            "/planning/schedule-action",
            {
                "school_id": self.school.school_id,
                "activity_type": "donor_visit",
                "scheduled_date": "2026-04-24",
                "delivery_type": "staff",
                "activity_purpose_text": "Introduce a donor to the school.",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            Activity.objects.filter(
                school=self.school, activity_type="donor_visit"
            ).exists()
        )

    def test_staff_take_two_visits_and_the_partner_two(self):
        """Owner, 2026-09-30: the package is "4 visits and 4 trainings (2 each
        for staff and the other 2 for partners)" — replacing 2026-09-28's
        "staff may plan more core schools visits but only if the partner has
        not planned". A third staff visit is refused whether or not a partner
        has planned, and so is a third partner visit."""
        first = self._schedule_visit(seq="1", when="2026-04-21")
        self.assertIn(first.status_code, (200, 302), first.content[:200])
        second = self._schedule_visit(seq="2", when="2026-04-28")
        self.assertIn(second.status_code, (200, 302), second.content[:200])
        third = self._schedule_visit(seq="3", when="2026-05-05")
        self.assertEqual(third.status_code, 400)
        self.assertIn("2 staff core visits", third.content.decode())

        for seq in ("3", "4"):
            partner = self._hand_over_visit(seq)
            self.assertIn(partner.status_code, (200, 302), partner.content[:200])
        third_partner = self._hand_over_visit("5")
        self.assertEqual(third_partner.status_code, 400)
        self.assertIn("2 partner core visits", third_partner.content.decode())

    def test_staff_do_not_schedule_a_visit_for_the_partner(self):
        """Owner, 2026-10-05: "Block any potential scheduling for the partner
        visit." The drawer offers no partner, and a POST that still names one
        is told where the work goes instead."""
        drawer = self._client(self.cceo).get(
            "/core-schools/schedule-visit", {"school_id": self.school.school_id}
        )
        self.assertEqual(drawer.status_code, 200)
        self.assertNotContains(drawer, 'name="assigned_partner_id"')
        self.assertNotContains(drawer, "Partner agency")
        self.assertContains(drawer, "data-partner-dates-own-work")

        refused = self._schedule_visit(
            seq="1", when="2026-06-09", partner_id=self.partner.id
        )

        self.assertEqual(refused.status_code, 403)
        self.assertIn("Core Helper Org chooses the date", refused.content.decode())
        self.assertFalse(
            Activity.objects.filter(
                school=self.school, assigned_partner_id=self.partner.id
            ).exists()
        )
        self.assertFalse(
            CoreActivitySlot.objects.filter(
                core_plan=self.plan, assigned_partner_id=self.partner.id
            ).exists()
        )

    def test_a_partner_may_still_take_the_package_beyond_the_staff_cap(self):
        """The cap is the staff share, not the school's need."""
        self._schedule_visit(seq="1", when="2026-04-21")
        self._schedule_visit(seq="2", when="2026-04-28")

        partner_delivery = self._hand_over_visit("3")

        self.assertIn(
            partner_delivery.status_code, (200, 302), partner_delivery.content[:200]
        )
        self.assertTrue(
            CoreActivitySlot.objects.filter(
                core_plan=self.plan, activity_type="visit", owner="partner"
            ).exists()
        )

    def test_core_support_may_be_scheduled_outside_the_packages_year(self):
        """The fiscal-year refusal is gone. It was the report that started
        this: "it is returning 'Core support must be scheduled within this
        package's fiscal year'"."""
        # A follow-up needs no earlier training in a year whose policy says
        # so, as Uganda's do (apps.planning.reference).
        from apps.core.tests.fy_windows import open_fy_for_planning

        policy = open_fy_for_planning("2028")
        policy.follow_up_visit_requires_prior_training = False
        policy.save(update_fields=["follow_up_visit_requires_prior_training"])
        response = self._schedule_visit(seq="1", when="2028-03-15")

        self.assertIn(response.status_code, (200, 302), response.content[:300])
        self.assertNotIn(b"fiscal year", response.content)

    def test_a_full_package_still_reads_complete_but_no_longer_refuses(self):
        """Owner, 2026-09-17: lift the package restrictions.

        A package whose 4 + 4 are all placed still SAYS so — that is the
        reading the matrix is for, and a lead needs it. What it no longer does
        is refuse: a school that needs a ninth piece of support gets one, from
        a partner, because the ceiling was a number and the need is not.
        """
        CoreActivitySlot.objects.filter(
            core_plan=self.plan, activity_type__in=["visit", "training"]
        ).update(status="Scheduled")

        response = self._client(self.cceo).get("/core-schools")
        row = next(
            item
            for item in response.context["matrix_rows"]
            if item["school_id"] == self.school.school_id
        )
        self.assertTrue(row["package_complete"])
        self.assertEqual(row["package_status"], "Package complete")

        beyond = self._hand_over_visit("1")

        self.assertIn(beyond.status_code, (200, 302), beyond.content[:300])
        self.assertNotIn(b"core package is complete", beyond.content)

    def test_scheduling_core_slot_creates_budget_line(self):
        self._schedule_visit()
        act = Activity.objects.filter(
            school=self.school, activity_type="core_visit"
        ).first()
        self.assertIsNotNone(act)
        self.assertGreater(act.schedule_cost_lines.count(), 0)
        self.assertGreater(act.est_cost_cents, 0)

    def test_scheduled_core_activity_appears_in_my_plan(self):
        from apps.my_plan.services import get as my_plan_get

        self._schedule_visit()
        act = Activity.objects.get(school=self.school, activity_type="core_visit")
        feed = my_plan_get(self.cceo, {"period": "fy"})
        self.assertIn(act.id, [i["id"] for i in feed["items"]])

    def test_core_school_remains_on_page_after_activity_scheduled(self):
        self._schedule_visit()
        html = self._client(self.cceo).get("/core-schools").content.decode()
        self.assertIn("Alpha Core School", html)  # package still open → stays

    # ── 12–14: partner two-step ──────────────────────────────────────────────
    def test_partner_assignment_does_not_create_final_budget_until_scheduled(self):
        acts_before = Activity.objects.count()
        resp = self._client(self.cceo).post(
            "/core-schools/assign-partner/action",
            {
                "school_id": self.school.school_id,
                # The support is chosen by its purpose (owner, 2026-09-15).
                # A follow up: this school has the year's SSA, so SSA
                # Support is not handed over for it (owner, 2026-10-08).
                "purpose_of_visit": "training_follow_up",
                "visit_training_number": "2",
                "partner_id": self.partner.id,
                "notes": "core support",
            },
        )
        self.assertIn(resp.status_code, (200, 302))
        self.assertTrue(
            PartnerAssignment.objects.filter(
                school=self.school, partner=self.partner
            ).exists()
        )
        self.assertEqual(Activity.objects.count(), acts_before)  # no budget yet

    def _partner_core_visit(self):
        return {
            "activityType": "core_visit",
            "catalogueItemId": self.core_visit_item.id,
            "requireCatalogue": True,
            "focusIntervention": "teaching_environment",
            "schoolId": self.school.school_id,
            "deliveryType": "partner",
            "assignedPartnerId": self.partner.id,
            "responsibleStaffId": self.cceo_sp.id,
            "activityPurposeText": "Partner core coaching",
        }

    def test_work_created_for_a_partner_takes_no_date_from_staff(self):
        """Owner, 2026-10-05: the partner dates their own work. Created for
        them it waits, undated, with the staff member as its monitor."""
        from apps.activities import services as asvc
        from apps.core.exceptions import Forbidden

        with self.assertRaises(Forbidden) as refused:
            asvc.create(
                {**self._partner_core_visit(), "scheduledDate": "2026-04-22"},
                principal=self.cceo,
                core_slot_verified=True,
            )
        self.assertIn("Core Helper Org chooses the date", str(refused.exception))
        self.assertFalse(Activity.objects.filter(school=self.school).exists())

        result = asvc.create(
            self._partner_core_visit(), principal=self.cceo, core_slot_verified=True
        )
        act = Activity.objects.get(id=result["id"])
        self.assertEqual(act.delivery_type, "partner")
        self.assertEqual(act.assigned_partner_id, self.partner.id)
        self.assertEqual(act.status, "assigned_to_partner")
        self.assertIsNone(act.scheduled_date)
        self.assertTrue(act.monitored_by_staff_id)  # staff monitors read-only

    def test_staff_partner_activity_is_read_only_for_assigning_staff(self):
        from apps.my_plan.services import compute_next_action

        from apps.activities import services as asvc

        result = asvc.create(
            self._partner_core_visit(), principal=self.cceo, core_slot_verified=True
        )
        act = Activity.objects.get(id=result["id"])
        na = compute_next_action(act, date(2026, 4, 23))
        self.assertNotIn(na["action"], ("start", "complete", "evidence", "sf_id"))

    # ── 15: slot completion gates ────────────────────────────────────────────
    def test_core_slot_requires_evidence_activity_sf_id_and_ia(self):
        from apps.core.exceptions import BadRequest
        from apps.core_schools.services import slot_action

        slot_id = cslot_id(self.school.school_id, "v", 1)
        with self.assertRaises(BadRequest):  # no SF ID
            slot_action(slot_id, "complete", {}, self.cceo)
        with self.assertRaises(BadRequest):  # SF ID but no evidence
            slot_action(slot_id, "complete", {"salesforceId": "SF-C1"}, self.cceo)
        slot_action(slot_id, "evidence", {"evidenceUri": "core/v1.jpg"}, self.cceo)
        out = slot_action(slot_id, "complete", {"salesforceId": "SF-C1"}, self.cceo)
        self.assertEqual(out["status"], "Completed")
        slot_action(slot_id, "iaVerify", {}, self.ia)
        slot = CoreActivitySlot.objects.get(id=slot_id)
        self.assertEqual(slot.ia_verification_status, "confirmed")

    # ── 16–18: interventions + recommendations ───────────────────────────────
    def test_all_eight_ssa_interventions_are_used(self):
        from django.utils.html import escape

        from apps.core.enums import SsaIntervention

        self.assertEqual(len(SsaIntervention.choices), 8)
        html = self._client(self.cceo).get("/core-schools").content.decode()
        for _code, label in SsaIntervention.choices:
            # Django auto-escapes template output (e.g. "Teacher's
            # Environment" -> "Teacher&#x27;s Environment") — compare against
            # the escaped form so this doesn't false-fail on labels with
            # apostrophes.
            self.assertIn(escape(str(label)), html)

    def test_intervention_impact_is_batched_across_all_eight_rows(self):
        from apps.core_schools.core_planning_services import (
            CoreInterventionImpactService,
        )

        core_schools = School.objects.filter(school_id=self.school.school_id)
        with CaptureQueriesContext(connection) as queries:
            rows = CoreInterventionImpactService.get_intervention_impact(
                core_schools, FY
            )

        self.assertEqual(len(rows), 8)
        self.assertLessEqual(
            len(queries),
            9,
            "Intervention impact must aggregate by intervention, not query per row",
        )

    def test_the_page_reads_shared_scores_once_with_the_same_answers(self):
        """Intervention Impact and the staff/partner comparison total the same
        scores, and the KPI strip and the benchmark ask the same average: a
        request reads each once (2026-09-24 A+ audit), and every figure is
        still the one the single-intervention definition gives."""
        from apps.core.request_cache import scoped
        from apps.core_schools.core_planning_services import (
            CoreAssessmentService,
            CoreInterventionImpactService,
            CoreStaffPartnerPerformanceService,
        )

        # One partner-led school and one staff-led one, both assessed.
        CoreActivitySlot.objects.filter(school_id=self.school.school_id).update(
            owner="partner"
        )
        other = SsaRecord.objects.create(
            school=self.other_school,
            fy=FY,
            quarter="Q1",
            average_score=4.4,
            verification_status="confirmed",
            date_of_ssa=date(int(FY) - 1, 11, 6),
            uploaded_by="test",
        )
        for code, score in SCORE_MAP.items():
            SsaScore.objects.create(
                ssa_record=other, intervention=code, score=score - 1.25
            )
        core_schools = School.objects.filter(school_type="core")
        codes = list(core_schools.values_list("school_id", flat=True))
        intervention_codes = set(
            CoreActivitySlot.objects.values_list("intervention", flat=True)
        )

        splits = CoreInterventionImpactService.staff_partner_splits(core_schools, FY)
        expected = {
            code: CoreInterventionImpactService._staff_partner_split_for_intervention(
                core_schools, FY, code, codes
            )
            for code in intervention_codes
        }
        self.assertTrue(any(pair != (None, None) for pair in expected.values()))
        self.assertEqual(
            {code: splits.get(code, (None, None)) for code in intervention_codes},
            expected,
        )
        unshared = (
            CoreInterventionImpactService.get_intervention_impact(core_schools, FY),
            CoreStaffPartnerPerformanceService.get_staff_vs_partner_performance(
                core_schools, FY
            ),
            CoreStaffPartnerPerformanceService.get_intervention_comparison_rows(
                core_schools, FY
            ),
            CoreAssessmentService.get_average_score(core_schools),
        )
        with scoped(), CaptureQueriesContext(connection) as queries:
            shared = (
                CoreInterventionImpactService.get_intervention_impact(core_schools, FY),
                CoreStaffPartnerPerformanceService.get_staff_vs_partner_performance(
                    core_schools, FY
                ),
                CoreStaffPartnerPerformanceService.get_intervention_comparison_rows(
                    core_schools, FY
                ),
                CoreAssessmentService.get_average_score(core_schools),
            )
        self.assertEqual(shared, unshared)
        sql = [q["sql"] for q in queries.captured_queries]
        self.assertEqual(sum('SUM("ssa_score"."score")' in q for q in sql), 1)
        self.assertEqual(
            sum(q.startswith('SELECT AVG("ssa_record"."average_score")') for q in sql),
            1,
        )

    def test_core_school_lists_have_a_total_order(self):
        """Schools created in the same instant (an import) and the Attention
        Needed plans come back in one fixed order on every load (F-G)."""
        from django.utils import timezone

        from apps.core_schools.core_planning_services import (
            CoreRecommendationService,
            CoreSchoolsService,
        )

        extra = [
            self._school(f"CORE-T{n}", f"Tied Core School {n}", self.cceo_sp)
            for n in range(4)
        ]
        for school in extra:
            self._plan(school)
        stamp = timezone.now()
        School.objects.filter(id__in=[s.id for s in extra]).update(created_at=stamp)

        listed = list(
            CoreSchoolsService.get_core_schools(self.cceo, {"fy": FY}).values_list(
                "id", "created_at"
            )
        )
        tied = [school_id for school_id, created in listed if created == stamp]
        self.assertTrue({s.id for s in extra} <= set(tied))
        self.assertEqual(tied, sorted(tied))
        self.assertEqual(
            [created for _id, created in listed],
            sorted((created for _id, created in listed), reverse=True),
        )

        card = CoreRecommendationService.get_recommendation_card(
            School.objects.filter(school_type="core")
        )
        codes = [row["school_id"] for row in card["attention_needed"]]
        self.assertEqual(codes, sorted(codes))
        self.assertGreater(len(codes), 1)

    def test_four_weakest_interventions_are_recommended(self):
        from apps.core_schools.core_planning_services import (
            CoreInterventionRecommendationService,
        )

        reco = CoreInterventionRecommendationService.recommend(self.school)
        self.assertTrue(reco["available"])
        codes = [r["code"] for r in reco["rows"]]
        self.assertEqual(
            codes,
            [
                "teaching_environment",
                "government_requirement",
                "learning_environment",
                "leadership",
            ],
        )

    def test_two_partner_and_two_staff_recommendations_created(self):
        from apps.core_schools.core_planning_services import (
            CoreInterventionRecommendationService,
        )

        reco = CoreInterventionRecommendationService.recommend(self.school)
        owners = [r["owner"] for r in reco["rows"]]
        self.assertEqual(owners, ["Partner", "Partner", "Staff", "Staff"])
        # No verified baseline → guidance instead of forced support.
        bare = self._school("CORE-3", "Gamma Core School", self.cceo_sp)
        reco2 = CoreInterventionRecommendationService.recommend(bare)
        self.assertFalse(reco2["available"])
        self.assertEqual(reco2["reason"], "SSA Required")

    # ── 19–20: annual impact only ────────────────────────────────────────────
    def test_annual_ssa_used_for_core_impact(self):
        follow = SsaRecord.objects.create(
            school=self.school,
            fy=str(int(FY) + 1),
            quarter="Q1",
            average_score=7.1,
            verification_status="confirmed",
            date_of_ssa=date(int(FY), 11, 5),
            uploaded_by="test",
        )
        CorePlan.objects.filter(id=self.plan.id).update(
            baseline_average=5.6,
            baseline_ssa_record_id=self.ssa.id,
            follow_up_average=7.1,
            follow_up_ssa_record_id=follow.id,
        )
        plan = CorePlan.objects.get(id=self.plan.id)
        self.assertEqual(round(plan.follow_up_average - plan.baseline_average, 1), 1.5)

    def test_monthly_ssa_impact_not_generated(self):
        from apps.core_schools.core_planning_services import CoreAssessmentService

        trend = CoreAssessmentService.get_monthly_trend(
            School.objects.filter(id=self.school.id)
        )
        self.assertEqual(trend, [])  # one month of data → no fake trend
        html = self._client(self.cceo).get("/core-schools").content.decode()
        self.assertNotIn("monthly SSA improvement", html.lower())

    # ── 21–22: package completion + champions ────────────────────────────────
    def test_package_complete_is_computed_from_verified_slots(self):
        from apps.core_schools.core_planning_services import (
            CorePackageSchedulingService,
        )

        # Package completion is a derived fact, not a second lifecycle status
        # somebody must remember to write.  CorePlan.status continues through
        # Impact Measured / Champion Candidate while this answer stays true.
        self.assertFalse(
            CorePackageSchedulingService.summary(self.plan)["package_complete"]
        )
        CoreActivitySlot.objects.filter(core_plan=self.plan).update(
            status="Completed", salesforce_id="SF-OK", evidence_uri="e.jpg"
        )
        self.assertTrue(
            CorePackageSchedulingService.summary(self.plan)["package_complete"]
        )

    def test_champion_candidate_requires_verified_criteria(self):
        from apps.core_schools.champion_services import ChampionEligibilityService

        bare = self._school("CORE-4", "Delta Core School", self.cceo_sp)
        result = ChampionEligibilityService.calculate_score(bare)
        self.assertFalse(result["eligible"])  # no plan / no SSA → never proposed
        result2 = ChampionEligibilityService.calculate_score(self.school)
        self.assertIn("score", result2)
        self.assertLess(result2["score"], 80)  # weak interventions block champion

    def test_assessment_slot_counts_toward_completion(self):
        # The assessment slot is the 9th mandatory slot; completing it moves
        # the plan's assessment counter and package-completion math.
        from apps.core_schools.services import resync_plan_completion

        a_slot = CoreActivitySlot.objects.get(
            core_plan=self.plan, activity_type="assessment"
        )
        a_slot.status = "ia_verified"
        a_slot.save(update_fields=["status"])
        resync_plan_completion(self.plan)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.assessment_completed, 1)

    def test_champion_eligibility_needs_all_nine_slots(self):
        from apps.core_schools.champion_services import ChampionEligibilityService

        # Complete only the 8 visit/training slots — the assessment is still
        # outstanding, so the package (and champion eligibility) is incomplete.
        CoreActivitySlot.objects.filter(
            core_plan=self.plan, activity_type__in=["visit", "training"]
        ).update(status="accountant_confirmed")
        result = ChampionEligibilityService.calculate_score(self.school)
        self.assertEqual(result["completed_slots"], 8)
        self.assertFalse(result["eligible"])  # 8 of 9 — assessment missing

    # ── 23: HTMX scope ───────────────────────────────────────────────────────
    def test_core_htmx_endpoints_enforce_scope(self):
        # A visit at somebody else's school is open since 2026-09-21, but
        # naming THEIR staff member as responsible is delegation and still
        # follows the supervision chain: this payload hands the visit to
        # `cceo_sp`, who does not report to the other CCEO.
        resp = self._schedule_visit(client=self._client(self.other_cceo))
        self.assertIn(resp.status_code, (403, 404))
        # The Accountant opens the drawer since 2026-09-02 — only to ASK: at a
        # school somebody owns it is the visit-request form the owner must
        # approve (apps.planning.visit_requests), never a plan of their own.
        drawer = self._client(self.accountant).get(
            f"/core-schools/schedule-visit?school_id={self.school.school_id}"
        )
        self.assertEqual(drawer.status_code, 200)
        self.assertContains(drawer, 'name="visit_justification"')
        # Core trainings stay the owner's: refused outright.
        training = self._client(self.accountant).get(
            f"/core-schools/schedule-training?school_id={self.school.school_id}"
        )
        self.assertEqual(training.status_code, 403)

    def test_a_core_visit_of_their_own_at_another_cceos_school_is_admitted(self):
        """The lift itself: the same post, taken by the person making it."""
        resp = self._schedule_visit(
            client=self._client(self.other_cceo), responsible_staff_id=""
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])

    # ── 24: real completion path advances the slot + package counters ───────
    def _complete_core_activity(self, act, sf_id, extra=None):
        """Drive an Activity through the REAL reachable completion path — the
        same complete()/PL-review functions the My Plan drawer and the PL
        queue call — rather than the DRF-only slot_action(). Since
        f0debc2 the Program Lead's confirmation verifies the work; Impact
        Assessment certifies partner-delivered work only."""
        from apps.activities.services import complete as complete_activity
        from apps.activities.services import start_completion
        from apps.evidence.models import EvidenceRecord
        from apps.pl_review.services import confirm as pl_confirm

        start_completion(act.id, principal=self.cceo)
        EvidenceRecord.objects.create(
            activity=act, kind="photo", uri="core/evidence.jpg", uploaded_by="test"
        )
        payload = {"salesforceId": sf_id, **(extra or {})}
        if act.purpose_type == "training_follow_up":
            # A follow-up is completed against the training it answers.
            source = Activity.objects.create(
                activity_type="in_school_training",
                school=act.school,
                fy=act.fy,
                quarter=act.quarter,
                planned_date=act.planned_date,
                status="completed",
                delivery_type="staff",
                responsible_staff_id=act.responsible_staff_id,
            )
            payload.setdefault("followUpOfActivityId", source.id)
        if act.ssa_collection_expected:
            # The first Core visit of the FY is SSA Support (owner,
            # 2026-09-15): completion answers the SSA question, and the
            # scores it collected are keyed on the visit.
            payload.setdefault("ssaCollected", True)
            SsaRecord.objects.create(
                school=act.school,
                fy=FY,
                quarter="Q1",
                average_score=5.6,
                verification_status="pending",
                date_of_ssa=act.planned_date,
                uploaded_by="test",
                source_activity=act,
            )
        complete_activity(act.id, payload, self.cceo)
        act.refresh_from_db()
        self.assertEqual(act.status, "submitted_to_pl")  # CCEO -> PL review first
        pl_confirm(act.id, self.pl)
        act.refresh_from_db()
        self.assertEqual(act.status, "ia_verified")
        self.assertEqual(act.ia_verification_status, "confirmed")
        return act

    def test_completing_core_visit_advances_slot_and_plan_counters(self):
        self._schedule_visit()
        act = Activity.objects.get(school=self.school, activity_type="core_visit")
        self._complete_core_activity(act, "SVE-CORE1")

        slot = CoreActivitySlot.objects.get(id=cslot_id(self.school.school_id, "v", 1))
        self.assertEqual(
            slot.status, "ia_verified"
        )  # mirrored, not stuck at "Scheduled"

        plan = CorePlan.objects.get(id=self.plan.id)
        self.assertEqual(plan.visits_completed, 1)
        self.assertEqual(plan.trainings_completed, 0)

    def test_completing_core_training_advances_plan_training_counter(self):
        resp = self._client(self.cceo).post(
            "/core-schools/schedule-training/action",
            {
                "school_id": self.school.school_id,
                "training_number": "1",
                "scheduled_date": "2026-04-21",
                "focus_intervention": "teaching_environment",
                "catalogue_item_id": self.core_training_item.id,
                "recommendation_reason": (
                    "Current unresolved Teacher's Environment SSA need."
                ),
                "training_purpose": "Core package recovery training",
                "expected_participants": "15",
                "responsible_staff_id": self.cceo_sp.id,
            },
        )
        self.assertIn(resp.status_code, (200, 302), resp.content[:200])
        # The course names the training; the standard In-school Training
        # workflow delivers it (owner, 2026-09-15: any catalogue training).
        act = Activity.objects.get(
            school=self.school,
            training_course=self.core_training_item,
        )
        self.assertEqual(act.activity_type, "in_school_training")
        self._complete_core_activity(
            act, "TS-CORE1", extra={"teachersAttended": 5, "leadersAttended": 2}
        )

        slot = CoreActivitySlot.objects.get(id=cslot_id(self.school.school_id, "t", 1))
        self.assertEqual(slot.status, "ia_verified")

        plan = CorePlan.objects.get(id=self.plan.id)
        self.assertEqual(plan.trainings_completed, 1)
        self.assertEqual(
            plan.visits_completed, 0
        )  # visits and trainings don't cross-count

    def test_plan_counters_recompute_idempotently_on_repeat_saves(self):
        """Saving an already-verified Activity again must not double-count —
        resync_plan_completion recomputes from the slots, it doesn't += 1."""
        self._schedule_visit()
        act = Activity.objects.get(school=self.school, activity_type="core_visit")
        self._complete_core_activity(act, "SVE-CORE9")
        act.save()
        act.save()
        plan = CorePlan.objects.get(id=self.plan.id)
        self.assertEqual(plan.visits_completed, 1)

    def test_core_tracker_reads_real_completed_counts_without_fallback(self):
        """apps.frontend.views.staff_views._build_core_tracker no longer masks
        plan.visits_completed/trainings_completed with a slot-status fallback —
        it must reflect the real, now-populated counters directly."""
        from apps.frontend.views.staff_views import _build_core_tracker

        self._schedule_visit()
        act = Activity.objects.get(school=self.school, activity_type="core_visit")
        self._complete_core_activity(act, "SVE-CORE2")

        data = _build_core_tracker(self.cceo)
        row = next(r for r in data["rows"] if r["school"] == "Alpha Core School")
        self.assertEqual(row["visits_done"], 1)
        self.assertEqual(row["trainings_done"], 0)

    def test_team_targets_reflect_core_completion(self):
        from apps.targets.team_targets import PLTeamTargetsService

        self._schedule_visit()
        act = Activity.objects.get(school=self.school, activity_type="core_visit")
        self._complete_core_activity(act, "SVE-CORE3")
        CorePlan.objects.filter(id=self.plan.id).update(baseline_average=5.6)

        page = PLTeamTargetsService.get_page(self.pl, fy=FY)
        core_kpi = next(k for k in page["kpis"] if k["key"] == "core")
        # Only Alpha Core School is on the PL's supervised team.
        self.assertIn("of 1 packages", core_kpi["delta_unit"])
        # Package score = baseline(1) + visits(1) + trainings(0) of 9 units —
        # this is the number that was permanently stuck at 0 before the fix
        # (visits_completed/trainings_completed never wrote). Assert the raw
        # package percentage rather than the fiscal-year-pace-thresholded
        # on-track flag, since that threshold depends on today's date.
        cceo_member = next(m for m in page["members"] if m["user_id"] == self.cceo.id)
        self.assertEqual(cceo_member["core_pct"], round(2 / 9 * 100))

    def test_cd_dashboard_reflects_core_completion(self):
        from apps.analytics.cd_dashboard_service import CDDashboardService

        self._schedule_visit()
        act = Activity.objects.get(school=self.school, activity_type="core_visit")
        self._complete_core_activity(act, "SVE-CORE4")
        CorePlan.objects.filter(id=self.plan.id).update(baseline_average=5.6)

        cd, _ = self._staff(
            "cd-core@core.org", "Core CD", EdifyRole.COUNTRY_DIRECTOR.value
        )
        core = CDDashboardService._core_on_track(FY, cd)
        self.assertEqual(core["total"], 2)  # both core plans in this fixture
        # One definition, shared with the Core School Health page: a package
        # is on track within two slots of done. One visit of nine is behind.
        self.assertEqual(core["on_track"], 0)
        from apps.core_schools.leadership_service import core_school_health

        self.assertEqual(
            core["on_track"], core_school_health(cd, {"fy": FY})["onTrackCount"]
        )

    # ── 25: self-heal SSA gate + audit provenance ────────────────────────────
    def test_self_heal_skips_core_school_without_ssa_record(self):
        """The self-healing auto-onboard in CoreSchoolsService.get_core_schools
        must not fabricate a CorePlan (with a fake 0.0 baseline) for a core
        school that has no SSA record on file yet — that would silently skip
        the same SSA gate the official onboard() path requires."""
        from apps.core_schools.core_planning_services import CoreSchoolsService

        bare = self._school("CORE-9", "No-SSA Core School", self.cceo_sp)
        self.assertFalse(CorePlan.objects.filter(school_id=bare.school_id).exists())

        CoreSchoolsService.get_core_schools(self.cceo, {"fy": FY})

        self.assertFalse(CorePlan.objects.filter(school_id=bare.school_id).exists())

    def test_self_heal_creates_audited_plan_when_ssa_exists(self):
        """When a core school genuinely is missing its CorePlan for the FY but
        does have a real SSA baseline, self-heal may create it — but must
        record who/what created it (created_by_id/created_by_name), same as
        the audited onboard() path, rather than leaving a provenance gap."""
        from apps.core_schools.core_planning_services import CoreSchoolsService

        healed = self._school("CORE-10", "Healable Core School", self.cceo_sp)
        SsaRecord.objects.create(
            school=healed,
            fy=FY,
            quarter="Q1",
            average_score=6.2,
            verification_status="confirmed",
            date_of_ssa=date(int(FY) - 1, 11, 5),
            uploaded_by="test",
        )
        self.assertFalse(CorePlan.objects.filter(school_id=healed.school_id).exists())

        CoreSchoolsService.get_core_schools(self.cceo, {"fy": FY})

        plan = CorePlan.objects.get(school_id=healed.school_id)
        self.assertEqual(plan.baseline_average, 6.2)
        self.assertEqual(plan.created_by_id, self.cceo.user_id)
        self.assertTrue(plan.created_by_name)
        # Self-heal creates the full 9-slot package (1 assessment + 4v + 4t).
        self.assertEqual(CoreActivitySlot.objects.filter(core_plan=plan).count(), 9)
        self.assertEqual(
            CoreActivitySlot.objects.filter(
                core_plan=plan, activity_type="assessment"
            ).count(),
            1,
        )

    def test_self_heal_loads_latest_ssa_for_the_cohort_in_one_query(self):
        """Adding schools must not add one reverse-FK read per school."""
        from apps.core_schools.core_planning_services import CoreSchoolsService

        for index in range(3):
            school = self._school(
                f"CORE-BULK-{index}", f"Bulk Core {index}", self.cceo_sp
            )
            SsaRecord.objects.create(
                school=school,
                fy=FY,
                quarter="Q1",
                average_score=5.0 + index,
                verification_status="confirmed",
                date_of_ssa=date(int(FY) - 1, 11, 5),
                uploaded_by="test",
            )

        with CaptureQueriesContext(connection) as queries:
            CoreSchoolsService.get_core_schools(self.cceo, {"fy": FY})

        # Statements that READ the SSA table. The candidate query also names
        # it, inside an EXISTS that skips schools with no confirmed SSA (so
        # they cannot starve the batch), but its top-level FROM is the school.
        ssa_reads = [
            query["sql"]
            for query in queries.captured_queries
            if query["sql"].split(" FROM ", 1)[-1].startswith('"ssa_record"')
        ]
        self.assertEqual(
            len(ssa_reads),
            1,
            f"Expected one cohort SSA read, saw {len(ssa_reads)}: {ssa_reads}",
        )
