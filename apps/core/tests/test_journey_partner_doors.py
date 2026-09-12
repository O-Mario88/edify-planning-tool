"""Journey 5 through the platform's own doors (2026-09-12).

The partner journey's HTTP coverage used to start at the payment door; the
assignment, the partner's own scheduling, start, evidence, submission and the
IA completion were exercised through services. This walks every door in
turn — CCEO hands over, the partner schedules and delivers from its workroom,
IA completes the SSA support, the accountant pays the advance and the
clearance — and asserts on the state each door leaves behind, never on the
status code alone (several doors turn a refusal into a flash message + 200).
"""

from __future__ import annotations

import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.enums import SsaIntervention
from apps.evidence.models import EvidenceRecord
from apps.fund_requests.finance_models import PartnerPayment
from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequest
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

PARTNER_VISIT_RATE = 40_000


def _schedulable_date() -> datetime.date:
    from apps.core.calendar_policy import SchedulingPolicyService

    day = timezone.localdate() + datetime.timedelta(days=7)
    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += datetime.timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks")


class PartnerJourneyThroughTheDoorsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="PD Region")
        cls.district = District.objects.create(
            name="PD District", region=cls.region, district_type="primary"
        )
        cls.sub_county = SubCounty.objects.create(name="PD Sub", district=cls.district)
        cls.school = School.objects.create(
            school_id="PD-SCH",
            name="PD Partner School",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type="client",
            enrollment=120,
        )

        def _person(uid, email, name, role):
            return User.objects.create(
                id=uid,
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                is_active=True,
            )

        cls.cceo = _person("pd-cceo", "pd-cceo@edify.org", "PD CCEO", "CCEO")
        cls.cceo_sp = StaffProfile.objects.create(
            user=cls.cceo, staff_number="PD-CCEO", country="Uganda", title="CCEO"
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)
        cls.ia = _person("pd-ia", "pd-ia@edify.org", "PD IA", "ImpactAssessment")
        StaffProfile.objects.create(
            user=cls.ia, staff_number="PD-IA", country="Uganda", title="IA"
        )
        cls.accountant = _person(
            "pd-acct", "pd-acct@edify.org", "PD Accountant", "Accountant"
        )
        cls.partner_user = _person(
            "pd-partner-user",
            "pd-partner@edify.org",
            "PD Partner",
            "PartnerFieldOfficer",
        )
        cls.partner = Partner.objects.create(
            name="PD Partner Org", user_id=cls.partner_user.id, active_status=True
        )
        catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy="2026", version=1, defaults={"is_active": True}
        )
        CostSetting.objects.update_or_create(
            key="client_partner_visit",
            catalogue=catalogue,
            defaults={
                "label": "Client Partner Visit",
                "unit_cost": PARTNER_VISIT_RATE,
                "approved_minimum": PARTNER_VISIT_RATE,
                "fy": "2026",
            },
        )
        cls.day = _schedulable_date()

    def _activity(self):
        return Activity.objects.get(
            assigned_partner_id=self.partner.id, deleted_at__isnull=True
        )

    def test_the_partner_journey_walks_every_door(self):
        # 1. The CCEO hands the school to the partner for SSA Support.
        self.client.force_login(self.cceo)
        self.client.post(
            "/planning/assign-partner-action",
            {
                "school_id": self.school.id,
                "partner_id": self.partner.id,
                "purpose_of_visit": "ssa_support",
            },
        )
        assignment = PartnerAssignment.objects.get(
            partner=self.partner, school=self.school
        )
        self.assertEqual(assignment.status, PartnerAssignment.STATUS_PENDING_SCHEDULING)
        self.assertEqual(assignment.purpose_of_visit, "ssa_support")
        self.assertIsNotNone(
            assignment.catalogue_item_id, "the door derives the catalogue item"
        )
        self.assertTrue(AuditLog.objects.filter(action="partner.assigned").exists())

        # 2. The partner sees the handover and schedules it from its workspace.
        self.client.force_login(self.partner_user)
        page = self.client.get("/partner/assignments")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "PD Partner School")
        self.client.post(
            f"/partner/assignments/{assignment.id}/schedule-action",
            {
                "scheduled_date": self.day.isoformat(),
                "delivery_contact_name": "Grace Partner",
            },
        )
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, "partner_scheduled")
        activity = self._activity()
        self.assertEqual(activity.delivery_type, "partner")
        self.assertEqual(activity.status, "partner_scheduled")
        self.assertTrue(activity.ssa_collection_expected)
        lines = list(
            ActivityScheduleCostLine.objects.filter(activity=activity).values_list(
                "cost_setting_key", "amount"
            )
        )
        self.assertEqual(lines, [("client_partner_visit", PARTNER_VISIT_RATE)])
        self.assertEqual(activity.est_cost_cents, PARTNER_VISIT_RATE)
        # Partner money never enters the staff advance channel.
        self.assertFalse(AdvanceRequest.objects.filter(activity=activity).exists())
        self.assertFalse(WeeklyFundRequest.objects.exists())

        # 3. It is on the partner's own plan; the partner starts the work.
        plan = self.client.get("/my-plan")
        self.assertEqual(plan.status_code, 200)
        self.assertContains(plan, "PD Partner School")
        self.client.post(f"/partner/activities/{activity.id}/start-action")
        activity.refresh_from_db()
        self.assertEqual(activity.status, "completion_started")

        # 4. Evidence goes up through the partner's workroom.
        self.client.post(
            f"/activities/{activity.id}/evidence/action",
            {
                "evidence_kind": "visit_form",
                "evidence_file": SimpleUploadedFile(
                    "visit-form.pdf",
                    b"%PDF-1.4 partner visit form",
                    content_type="application/pdf",
                ),
            },
        )
        self.assertEqual(
            EvidenceRecord.objects.filter(
                activity_id=activity.id, quarantined=False
            ).count(),
            1,
        )

        # 5. The partner submits the work to IA.
        submit = self.client.post(
            f"/partner/activities/{activity.id}/submit-action",
            {
                "actual_delivery_date": self.day.isoformat(),
                "teachers_attended": "4",
                "leaders_attended": "1",
                "other_participants": "0",
                "actual_outcome": "Scores collected with the head teacher.",
                "actual_observations": "Records in order.",
                "feedback_finding": "Attendance registers are complete.",
                "school_improvements": "Display learner work\nWeekly staff meeting",
            },
        )
        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "awaiting_ia_verification",
            f"the partner's submit door refused: {submit.content[:300]!r}",
        )

        # 6. The accountant pays the MOU advance (half of the plan) before IA.
        self.client.force_login(self.accountant)
        self.client.post(
            f"/accounts/partner-payments/{activity.id}/pay",
            {
                "partner_name": self.partner.name,
                "payment_method": "mobile_money",
                "payment_reference": "MM-ADV-1",
                "amount_paid": str(PARTNER_VISIT_RATE // 2),
                "payment_type": "advance",
            },
        )
        activity.refresh_from_db()
        self.assertEqual(activity.payment_status, "disbursed")
        self.assertEqual(
            list(
                PartnerPayment.objects.filter(activity=activity).values_list(
                    "payment_type", flat=True
                )
            ),
            ["advance"],
        )

        # 7. IA sees it in the partner-evidence queue and completes the SSA
        #    support with the scores, the enrolment and the Salesforce id.
        self.client.force_login(self.ia)
        queue = self.client.get("/ia/partner-evidence/")
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, "PD Partner School")
        scores = {f"score_{code}": "6" for code, _ in SsaIntervention.choices}
        self.client.post(
            f"/ia/partner-evidence/{activity.id}/complete-action",
            {
                **scores,
                "enrollment": "130",
                "salesforce_id": "SVE-PD-0001",
                "verification_note": "Verified.",
            },
        )
        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")
        self.assertEqual(activity.ia_verification_status, "confirmed")
        self.school.refresh_from_db()
        self.assertEqual(self.school.enrollment, 130)
        self.assertTrue(
            AuditLog.objects.filter(action="complete_partner_ssa_support").exists()
        )

        # The clearance door refuses while any finance blocker stands.
        from apps.fund_requests.finance_services import FinanceBlockedReasonService

        self.assertEqual(FinanceBlockedReasonService.get_blocked_reasons(activity), [])

        # 8. The accountant clears the balance; the work is closed and paid.
        self.client.force_login(self.accountant)
        self.client.post(
            f"/accounts/partner-payments/{activity.id}/pay",
            {
                "partner_name": self.partner.name,
                "payment_method": "mobile_money",
                "payment_reference": "MM-CLR-1",
                "amount_paid": str(PARTNER_VISIT_RATE - PARTNER_VISIT_RATE // 2),
                "payment_type": "clearance",
            },
        )
        activity.refresh_from_db()
        self.assertEqual(activity.payment_status, "paid")
        # Clearance closes the work itself once every closure requirement is
        # met (the accountant's payment is the finance proof for partner work).
        self.assertIn(activity.status, ("ia_verified", "closed"))
        self.assertEqual(
            sorted(
                PartnerPayment.objects.filter(activity=activity).values_list(
                    "payment_type", flat=True
                )
            ),
            ["advance", "clearance"],
        )
        self.assertTrue(AuditLog.objects.filter(action="finance.partner_paid").exists())

        # 9. Closed — by the clearance itself, or by the monitoring CCEO's door.
        from apps.activities.closure_services import ClosureEligibilityService

        if activity.status != "closed":
            self.client.force_login(self.cceo)
            self.client.post(f"/activities/{activity.id}/closure/close")
            activity.refresh_from_db()
        _checklist, blockers = ClosureEligibilityService.evaluate(activity)
        self.assertEqual(
            activity.status,
            "closed",
            "closure refused: "
            + "; ".join(
                f"{b.blocking_reason} ({b.responsible_role})" for b in blockers
            ),
        )
        self.assertTrue(AuditLog.objects.filter(action="activity.closed").exists())
