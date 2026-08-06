from __future__ import annotations

import tempfile
from datetime import date
from django.test import TestCase, override_settings
from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.core_schools.models import CorePlan, CoreActivitySlot
from apps.schools.models import School
from apps.schools.services import set_type
from apps.activities.services import partner_schedule, ia_confirm, ia_return
from apps.partners.models import Partner, PartnerAssignment
from apps.ssa.models import SsaRecord, SsaScore
from apps.geography.models import District, Region, SubCounty
from apps.core.exceptions import BadRequest

INTERVENTION_SCORES = [
    {"intervention": "teaching_environment", "score": 7},
    {"intervention": "financial_health", "score": 6},
    {"intervention": "christlike_behaviour", "score": 8},
    {"intervention": "exposure_to_word_of_god", "score": 7},
    {"intervention": "government_requirement", "score": 5},
    {"intervention": "leadership", "score": 6},
    {"intervention": "enrolment", "score": 4},
    {"intervention": "learning_environment", "score": 7},
]


@override_settings(EVIDENCE_STORAGE_DIR=tempfile.mkdtemp(prefix="edify-evidence-core-"))
class CoreSchoolWorkflowTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Core Region")
        self.district = District.objects.create(
            name="Core District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Core SubCounty", district=self.district
        )

        self.ia = User.objects.create_user(
            email="ia@core.test",
            name="IA Staff",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="pwd",
            is_active=True,
        )
        self.cceo = User.objects.create_user(
            email="cceo@core.test",
            name="CCEO Staff",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="pwd",
            is_active=True,
        )
        self.partner_user = User.objects.create_user(
            email="partner@core.test",
            name="Partner User",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            password="pwd",
            is_active=True,
        )

        self.ia_staff = StaffProfile.objects.create(user=self.ia, title="IA")
        self.cceo_staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.partner = Partner.objects.create(
            name="Partner Org",
            user=self.partner_user,
            active_status=True,
            contract_status="active",
            source="test",
        )

        self.school = School.objects.create(
            school_id="SCH-CORE-100",
            name="Test Client School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            enrollment=300,
        )

    def test_promote_to_core_and_partner_scheduling_and_ia_verification(self):
        # 1. Promote school to Core -> verify self-healing (CorePlan and slots
        # created). The self-heal auto-onboard SSA gate
        # (core_planning_services.py) only onboards a school it finds a real
        # SsaRecord for -- without one it now correctly skips rather than
        # fabricating a baseline, so seed one just for this step. It's
        # removed again immediately after: ia_confirm()'s own core-strict SSA
        # check (services.py:637-648) uses the identical "any non-deleted
        # SsaRecord exists" query, and this test deliberately exercises that
        # check failing further down before creating its own real baseline.
        onboarding_ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=date(2026, 6, 1),
            fy="2026",
            quarter="Q1",
            verification_status="confirmed",
        )
        SsaScore.objects.bulk_create(
            SsaScore(
                ssa_record=onboarding_ssa,
                intervention=s["intervention"],
                score=s["score"],
            )
            for s in INTERVENTION_SCORES
        )
        set_type(self.ia, self.school.school_id, "core")
        onboarding_ssa.soft_delete()

        self.school.refresh_from_db()
        self.assertEqual(self.school.school_type, "core")

        plan = CorePlan.objects.filter(school_id=self.school.school_id).first()
        self.assertIsNotNone(plan)
        # Mandated 9-slot package: 1 assessment + 4 visits + 4 trainings.
        self.assertEqual(plan.slots.count(), 9)

        # 2. Assign Core Activity to Partner
        pa = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cceo_staff.id,
            focus_intervention="teaching_environment",
            expected_activity_type="core_visit",
            support_type="Visit",
            visit_number="1",
            status="assigned",
        )

        # Partner schedules the assigned work
        scheduled_data = {"scheduledDate": "2026-07-15T10:00:00Z"}
        res = partner_schedule(pa.id, scheduled_data, self.partner_user)
        self.assertEqual(res["status"], "partner_scheduled")

        # Verify Activity created and CoreActivitySlot updated to Scheduled
        activity = Activity.objects.get(id=res["id"])
        self.assertEqual(activity.school, self.school)
        self.assertEqual(activity.delivery_type, "partner")

        slot = CoreActivitySlot.objects.filter(activity_id=activity.id).first()
        self.assertIsNotNone(slot)
        self.assertEqual(slot.status, "partner_scheduled")
        self.assertEqual(str(slot.scheduled_for), "2026-07-15")

        # 3. Complete activity requirements (Evidence + SF ID)
        activity.status = "completion_started"
        activity.save()

        # Try IA verification before completion -> raises BadRequest because not awaiting IA
        with self.assertRaises(BadRequest):
            ia_confirm(activity.id, principal=self.ia)

        # Upload evidence
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity_id=activity.id,
            uploaded_by=self.cceo.id,
            kind="photo",
            uri="evidence.jpg",
            original_name="evidence.jpg",
            file_size=1024,
            mime_type="image/jpeg",
            file_extension=".jpg",
        )

        # Try IA verification before complete -> raises BadRequest because status is completion_started
        with self.assertRaises(BadRequest):
            ia_confirm(activity.id, principal=self.ia)

        # CCEO completes activity
        activity.status = "awaiting_ia_verification"
        activity.salesforce_activity_id = "SV-12345678"
        activity.focus_intervention = "teaching_environment"
        activity.evidence_status = "accepted"
        activity.save()

        # Try IA verification without SSA baseline -> raises BadRequest
        with self.assertRaises(BadRequest):
            ia_confirm(activity.id, principal=self.ia)

        # Create SSA Baseline record
        ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa="2026-07-01",
            fy="2026",
            quarter="Q1",
            verification_status="confirmed",
        )
        for score in INTERVENTION_SCORES:
            SsaScore.objects.create(
                ssa_record=ssa, intervention=score["intervention"], score=score["score"]
            )

        # Try IA verification now -> succeeds!
        ia_confirm(activity.id, principal=self.ia)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")
        self.assertEqual(activity.ia_verification_status, "confirmed")

        slot.refresh_from_db()
        self.assertEqual(slot.status, "ia_verified")

        # 4. Test IA return
        # Mock status back to awaiting review
        activity.status = "awaiting_ia_verification"
        activity.save()

        ia_return(activity.id, {"reason": "Evidence photo is blurred"}, self.ia)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "returned")
        self.assertEqual(activity.ia_verification_status, "returned")
        self.assertEqual(activity.pl_review_note, "Evidence photo is blurred")

        slot.refresh_from_db()
        self.assertEqual(slot.status, "returned")

    def test_partner_schedule_sets_planned_date_and_no_staff_owner(self):
        """partner_schedule() must populate planned_date — the Partner
        Portal's /partner/today page filters Activity by planned_date, so a
        null value there would leave "Today" permanently empty even once the
        partner-identity resolver is correct. It must also NOT stamp the
        partner's own User id into responsible_staff_id: that field holds a
        StaffProfile id everywhere else (see activities.services.create(),
        which explicitly leaves responsible_staff_id unset/None for
        delivery_type="partner" activities — partner_schedule() creates the
        same kind of activity and must follow the same convention)."""
        pa = PartnerAssignment.objects.create(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cceo_staff.id,
            focus_intervention="teaching_environment",
            expected_activity_type="core_visit",
            support_type="Visit",
            visit_number="2",
            status="assigned",
        )

        scheduled_data = {"scheduledDate": "2026-07-20T10:00:00Z"}
        res = partner_schedule(pa.id, scheduled_data, self.partner_user)

        activity = Activity.objects.get(id=res["id"])
        self.assertEqual(activity.planned_date, date(2026, 7, 20))
        self.assertIsNone(activity.responsible_staff_id)
        self.assertNotEqual(activity.responsible_staff_id, self.partner_user.id)
