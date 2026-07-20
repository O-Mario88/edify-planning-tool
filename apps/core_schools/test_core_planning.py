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
from django.test import Client, TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
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
FY = get_operational_fy()

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


class CoreSchoolsPlanningTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Core R")
        self.district = District.objects.create(
            name="Core D", region=self.region, district_type="primary"
        )
        self.cluster = Cluster.objects.create(
            name="Core Cluster", region=self.region, district=self.district
        )

        self.cceo, self.cceo_sp = self._staff(
            "cc@core.org", "Core Cceo", EdifyRole.CCEO.value
        )
        self.other_cceo, self.other_sp = self._staff(
            "oc@core.org", "Other Cceo", EdifyRole.CCEO.value
        )
        self.pl, self.pl_sp = self._staff(
            "pl@core.org", "Core PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.other_pl, self.other_pl_sp = self._staff(
            "opl@core.org", "Other PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.ia, _ = self._staff(
            "ia@core.org", "Core IA", EdifyRole.IMPACT_ASSESSMENT.value
        )
        self.accountant, _ = self._staff(
            "acc@core.org", "Core Acc", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        self.partner_user, _ = self._staff(
            "pa@core.org", "Partner Admin", EdifyRole.PARTNER_ADMIN.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )

        self.school = self._school("CORE-1", "Alpha Core School", self.cceo_sp)
        self.other_school = self._school("CORE-2", "Beta Core School", self.other_sp)

        self.partner = Partner.objects.create(
            name="Core Helper Org", region_name="Core R"
        )

        self.plan = self._plan(self.school)
        self._plan(self.other_school)

        # Verified annual SSA with all eight interventions.
        self.ssa = SsaRecord.objects.create(
            school=self.school,
            fy=FY,
            quarter="Q1",
            average_score=5.6,
            verification_status="confirmed",
            date_of_ssa=date(int(FY) - 1, 11, 5),
            uploaded_by="test",
        )
        for code, score in SCORE_MAP.items():
            SsaScore.objects.create(ssa_record=self.ssa, intervention=code, score=score)

        # Costing so core visit scheduling can price.
        catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda",
            fy=FY,
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
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key,
                    "unit_cost": cost,
                    "fy": FY,
                    "catalogue": catalogue,
                    "version": 1,
                },
            )

    # ── fixtures ─────────────────────────────────────────────────────────────
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
        plan = CorePlan.objects.create(
            id=cplan_id(school.school_id),
            school_id=school.school_id,
            fy=FY,
            status="Active",
        )
        CoreSchoolProfile.objects.create(
            id=cprof_id(school.school_id),
            school_id=school.school_id,
            core_plan=plan,
            core_start_fy=FY,
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
        self, client=None, school=None, seq="1", when="2026-07-21", partner_id=None
    ):
        payload = {
            "school_id": (school or self.school).school_id,
            "visit_number": seq,
            "scheduled_date": when,
            "focus_intervention": "teaching_environment",
            "visit_purpose": "Core package recovery visit",
            "expected_outcome": "Slot fulfilled",
            "responsible_staff_id": self.cceo_sp.id,
        }
        if partner_id:
            payload["assigned_partner_id"] = partner_id
        return (client or self._client(self.cceo)).post(
            "/core-schools/schedule-visit/action",
            payload,
        )

    # ── 1–6: sidebar + scope ─────────────────────────────────────────────────
    def test_core_schools_sidebar_visible_to_authorized_roles(self):
        for user in (self.cceo, self.pl, self.ia):
            labels = [
                i["label"]
                for sec in build_sidebar_for_user(user, "/")
                for i in sec["items"]
            ]
            self.assertIn("Core Schools", labels, user.email)

    def test_core_schools_sidebar_hidden_from_unauthorized_roles(self):
        cd, _ = self._staff("cd@core.org", "Core CD", EdifyRole.COUNTRY_DIRECTOR.value)
        for user in (cd, self.accountant, self.partner_user):
            labels = [
                i["label"]
                for sec in build_sidebar_for_user(user, "/")
                for i in sec["items"]
            ]
            self.assertNotIn("Core Schools", labels, user.email)
            self.assertNotEqual(
                self._client(user).get("/core-schools").status_code, 200, user.email
            )

    def test_cceo_sees_only_assigned_core_schools(self):
        html = self._client(self.cceo).get("/core-schools").content.decode()
        self.assertIn("Alpha Core School", html)
        self.assertNotIn("Beta Core School", html)

    def test_pl_sees_own_and_supervised_core_portfolio(self):
        html = self._client(self.pl).get("/core-schools").content.decode()
        self.assertIn("Alpha Core School", html)  # supervised CCEO's school

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
        self.assertContains(response, "Staff Name:")
        self.assertContains(response, "Core Cceo")
        self.assertContains(response, ">Core<")
        self.assertContains(
            response, 'class="school-record-action school-record-action--schedule"'
        )
        self.assertContains(
            response, 'class="school-record-action school-record-action--assign"'
        )
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
        CoreActivitySlot.objects.filter(
            core_plan=self.plan, activity_type__in=["visit", "training"]
        ).update(status="Scheduled")

        response = self._client(self.cceo).get(
            f"/core-schools/schedule-activity?school_id={self.school.school_id}"
        )
        self.assertContains(response, "Package complete")
        # The chooser labels each exhausted option in place ("Core visit ·
        # no package slots available") rather than as a standalone
        # sentence. The behaviour under test is unchanged -- package slots
        # are gone, general activities remain -- only the wording moved.
        self.assertContains(response, "Core visit · no package slots available")
        self.assertContains(response, "Core training · no package slots available")
        self.assertContains(response, "Schedule other activity")
        self.assertContains(
            response,
            f"/planning/schedule-modal?school_id={self.school.school_id}",
        )

    def test_general_school_schedule_lists_everyday_visit_and_training_types(self):
        response = self._client(self.cceo).get(
            f"/planning/schedule-modal?school_id={self.school.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        # The drawer used to expose the raw ActivityType list. The
        # purpose-of-visit feature replaced that with a purpose select whose
        # choice derives the activity type (apps/partners/purposes.py), so the
        # question this test asks -- can a CCEO schedule everyday support work
        # from the general schedule modal -- is now answered by the purposes on
        # offer rather than by the activity-type labels.
        from apps.partners.purposes import STAFF_VISIT_PURPOSES

        for _value, label in STAFF_VISIT_PURPOSES:
            self.assertContains(response, label)

    def test_general_visit_type_saves_with_a_cost_snapshot(self):
        response = self._client(self.cceo).post(
            "/planning/schedule-action",
            {
                "school_id": self.school.school_id,
                "activity_type": "donor_visit",
                "scheduled_date": "2026-07-24",
                "delivery_type": "staff",
                "activity_purpose_text": "Introduce a donor to the school.",
            },
        )
        self.assertIn(response.status_code, (200, 302), response.content[:200])
        activity = Activity.objects.get(school=self.school, activity_type="donor_visit")
        self.assertEqual(activity.status, "scheduled")
        self.assertGreater(activity.est_cost_cents, 0)
        self.assertGreater(activity.schedule_cost_lines.count(), 0)

    def test_staff_core_support_is_limited_per_current_quarter_but_partner_is_not(self):
        first = self._schedule_visit(seq="1")
        self.assertIn(first.status_code, (200, 302), first.content[:200])

        blocked = self._schedule_visit(seq="2")
        self.assertEqual(blocked.status_code, 400)
        self.assertIn(
            "One staff-led core visit is already scheduled", blocked.content.decode()
        )

        # Partner delivery may use the next slot in another quarter of the
        # same fiscal package; the staff quarter release does not apply.
        partner_delivery = self._schedule_visit(
            seq="2", when="2026-04-21", partner_id=self.partner.id
        )
        self.assertIn(
            partner_delivery.status_code, (200, 302), partner_delivery.content[:200]
        )
        second_slot = CoreActivitySlot.objects.get(
            id=cslot_id(self.school.school_id, "v", 2)
        )
        self.assertEqual(second_slot.status, "Scheduled")
        self.assertEqual(second_slot.owner, "partner")

    def test_full_live_package_disables_actions_and_rejects_new_support(self):
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
        self.assertContains(response, 'disabled title="Package complete"')
        self.assertContains(
            response,
            f"/core-schools/schedule-activity?school_id={self.school.school_id}",
        )
        self.assertContains(response, "Package:")
        self.assertContains(response, "Complete")

        blocked_schedule = self._schedule_visit(seq="1")
        self.assertEqual(blocked_schedule.status_code, 400)
        self.assertIn("core package is complete", blocked_schedule.content.decode())

        blocked_assignment = self._client(self.cceo).post(
            "/core-schools/assign-partner/action",
            {
                "school_id": self.school.school_id,
                "support_type": "Visit",
                "visit_training_number": "1",
                "partner_id": self.partner.id,
                "focus_intervention": "teaching_environment",
            },
        )
        self.assertEqual(blocked_assignment.status_code, 400)
        self.assertIn("core package is complete", blocked_assignment.content.decode())

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
                "support_type": "Visit",
                "visit_training_number": "2",
                "partner_id": self.partner.id,
                "focus_intervention": "teaching_environment",
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

    def test_partner_schedule_updates_partner_and_staff_my_plan(self):
        from apps.activities import services as asvc

        result = asvc.create(
            {
                "activityType": "core_visit",
                "schoolId": self.school.school_id,
                "deliveryType": "partner",
                "assignedPartnerId": self.partner.id,
                "responsibleStaffId": self.cceo_sp.id,
                "scheduledDate": "2026-07-22",
                "activityPurposeText": "Partner core coaching",
            },
            principal=self.cceo,
        )
        act = Activity.objects.get(id=result["id"])
        self.assertEqual(act.delivery_type, "partner")
        self.assertEqual(act.assigned_partner_id, self.partner.id)
        self.assertTrue(act.monitored_by_staff_id)  # staff monitors read-only

    def test_staff_partner_activity_is_read_only_for_assigning_staff(self):
        from apps.my_plan.services import compute_next_action

        from apps.activities import services as asvc

        result = asvc.create(
            {
                "activityType": "core_visit",
                "schoolId": self.school.school_id,
                "deliveryType": "partner",
                "assignedPartnerId": self.partner.id,
                "responsibleStaffId": self.cceo_sp.id,
                "scheduledDate": "2026-07-23",
                "activityPurposeText": "Partner core coaching",
            },
            principal=self.cceo,
        )
        act = Activity.objects.get(id=result["id"])
        na = compute_next_action(act, date(2026, 7, 23))
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
        self.assertEqual(reco2["reason"], "Baseline Required")

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
    def test_package_complete_only_after_all_slots_verified(self):
        from apps.system_health.services import _workflow_issues

        CorePlan.objects.filter(id=self.plan.id).update(status="Package Complete")
        issues = _workflow_issues()
        self.assertGreaterEqual(issues["corePackageCompleteMissingSlots"], 1)
        CoreActivitySlot.objects.filter(core_plan=self.plan).update(
            status="Completed", salesforce_id="SF-OK", evidence_uri="e.jpg"
        )
        issues = _workflow_issues()
        self.assertEqual(issues["corePackageCompleteMissingSlots"], 0)

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
        resp = self._schedule_visit(client=self._client(self.other_cceo))
        self.assertIn(resp.status_code, (403, 404))  # not their school
        self.assertNotEqual(
            self._client(self.accountant)
            .get(f"/core-schools/schedule-visit?school_id={self.school.school_id}")
            .status_code,
            200,
        )

    # ── 24: real completion path advances the slot + package counters ───────
    def _complete_core_activity(self, act, sf_id, extra=None):
        """Drive an Activity through the REAL reachable completion path — the
        same complete()/PL-review/IA-verify functions the My Plan drawer and
        PL/IA queues call — rather than the DRF-only slot_action()."""
        from apps.activities.services import complete as complete_activity
        from apps.activities.services import ia_confirm, start_completion
        from apps.evidence.models import EvidenceRecord
        from apps.pl_review.services import confirm as pl_confirm

        start_completion(act.id, principal=self.cceo)
        EvidenceRecord.objects.create(
            activity=act, kind="photo", uri="core/evidence.jpg", uploaded_by="test"
        )
        payload = {"salesforceId": sf_id, **(extra or {})}
        complete_activity(act.id, payload, self.cceo)
        act.refresh_from_db()
        self.assertEqual(act.status, "submitted_to_pl")  # CCEO -> PL review first
        pl_confirm(act.id, self.pl)
        act.refresh_from_db()
        self.assertIsNotNone(act.submitted_to_ia_at)
        ia_confirm(act.id, principal=self.ia)
        act.refresh_from_db()
        self.assertEqual(act.status, "ia_verified")
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
                "scheduled_date": "2026-07-21",
                "focus_intervention": "teaching_environment",
                "training_purpose": "Core package recovery training",
                "expected_participants": "15",
                "responsible_staff_id": self.cceo_sp.id,
            },
        )
        self.assertIn(resp.status_code, (200, 302), resp.content[:200])
        act = Activity.objects.get(school=self.school, activity_type="core_training")
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

        core = CDDashboardService._core_on_track(FY)
        self.assertEqual(core["total"], 2)  # both core plans in this fixture
        self.assertEqual(core["on_track"], 1)  # only the completed + baselined plan

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
