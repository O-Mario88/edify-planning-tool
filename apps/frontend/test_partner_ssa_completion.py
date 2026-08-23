"""Partner SSA Support completes by recording scores and pupil enrolment."""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivitySalesforceReference
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School, SchoolChangeLog, SchoolEnrollmentHistory
from apps.ssa.models import SsaRecord


class PartnerSsaCompletionTest(TestCase):
    def setUp(self):
        region = Region.objects.create(name="Partner SSA Region")
        district = District.objects.create(
            name="Partner SSA District", region=region, district_type="primary"
        )
        self.monitor = User.objects.create_user(
            email="partner-ssa-monitor@example.org",
            password="test-password",
            name="Partner SSA Monitor",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        self.monitor_profile = StaffProfile.objects.create(
            user=self.monitor, title="CCEO"
        )
        self.other_staff = User.objects.create_user(
            email="other-partner-ssa-staff@example.org",
            password="test-password",
            name="Other Staff",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        StaffProfile.objects.create(user=self.other_staff, title="CCEO")
        self.ia = User.objects.create_user(
            email="partner-ssa-ia@example.org",
            password="test-password",
            name="Partner SSA IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
        )
        partner_user = User.objects.create_user(
            email="partner-ssa-officer@example.org",
            password="test-password",
            name="Partner SSA Officer",
            roles=[EdifyRole.PARTNER_FIELD_OFFICER.value],
            active_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
        )
        self.partner = Partner.objects.create(
            name="SSA Delivery Partner",
            user=partner_user,
            active_status=True,
        )
        self.school = School.objects.create(
            school_id="PARTNER-SSA-1",
            name="Partner SSA Primary",
            region=region,
            district=district,
            enrollment=120,
            account_owner_id=self.monitor_profile.id,
        )

    def _activity(self, *, ssa=True):
        today = date.today()
        activity = Activity.objects.create(
            school=self.school,
            activity_type=(
                "school_visit_ssa_collection" if ssa else "in_school_training"
            ),
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            monitored_by_staff_id=self.monitor_profile.id,
            purpose_type="ssa_support" if ssa else "in_school_training",
            # False deliberately: historical partner assignments missed this
            # stamp and must still route to the governed SSA drawer.
            ssa_collection_expected=False,
            status="awaiting_ia_verification",
            actual_delivery_date=today,
            planned_date=today,
            fy=get_operational_fy(today),
            quarter=get_quarter_for_date(today),
        )
        EvidenceRecord.objects.create(
            activity=activity,
            kind="assessment_form",
            uri=f"evidence/{activity.id}.pdf",
            original_name="completed-ssa.pdf",
            mime_type="application/pdf",
            uploaded_by=self.partner.user_id,
            uploader_role=EdifyRole.PARTNER_FIELD_OFFICER.value,
            quarantined=False,
        )
        return activity

    def _payload(self, *, enrollment="420", salesforce_id="SVE-SSA-001"):
        payload = {
            "enrollment": enrollment,
            "salesforce_id": salesforce_id,
            "verification_note": "Assessment checked against the partner form.",
        }
        payload.update(
            {
                f"score_{code}": str(index)
                for index, (code, _label) in enumerate(SsaIntervention.choices, start=1)
            }
        )
        return payload

    def test_monitor_drawer_is_scores_and_enrolment_not_generic_completion(self):
        activity = self._activity()
        self.client.force_login(self.monitor)

        response = self.client.get(f"/my-plan/{activity.id}/complete-drawer")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Update SSA Scores &amp; Complete")
        self.assertContains(response, 'name="enrollment"')
        self.assertContains(response, "Pupil enrolment")
        self.assertContains(response, ">CB</span>")
        self.assertContains(response, "Christlike Behaviour")
        self.assertContains(response, ">WOG</span>")
        self.assertContains(response, "Exposure to the Word of God")
        for code, _label in SsaIntervention.choices:
            self.assertContains(response, f'name="score_{code}"')
        self.assertNotContains(response, 'name="ssa_not_collected_reason"')
        self.assertNotContains(response, 'name="evidence_file"')

    def test_monitor_completion_updates_scores_enrolment_and_activity_atomically(self):
        activity = self._activity()
        self.client.force_login(self.monitor)

        response = self.client.post(
            f"/activities/{activity.id}/partner-ssa-complete/action",
            self._payload(),
        )

        self.assertEqual(
            response.status_code,
            200,
            response.content.decode("utf-8", errors="replace"),
        )
        activity.refresh_from_db()
        self.school.refresh_from_db()
        record = SsaRecord.objects.get(school=self.school)
        self.assertEqual(record.collector_type, "staff")
        self.assertEqual(record.verification_status, "confirmed")
        self.assertEqual(record.scores.count(), 8)
        self.assertIsNone(record.new_enrollment)
        self.assertEqual(self.school.enrollment, 420)
        self.assertEqual(
            self.school.last_enrollment_date, activity.actual_delivery_date
        )
        history = SchoolEnrollmentHistory.objects.get(school=self.school)
        self.assertEqual(history.enrollment, 420)
        change = SchoolChangeLog.objects.get(
            school=self.school, field_name="enrollment"
        )
        self.assertEqual((change.old_value, change.new_value), ("120", "420"))
        self.assertEqual(activity.status, "ia_verified")
        self.assertTrue(activity.ssa_collection_expected)
        self.assertEqual(activity.salesforce_activity_id, "SVE-SSA-001")
        reference = ActivitySalesforceReference.objects.get(activity=activity)
        self.assertEqual(reference.entry_source, "managing_staff_for_partner")

    def test_ia_uses_the_same_drawer_and_records_ia_provenance(self):
        activity = self._activity()
        self.client.force_login(self.ia)

        drawer = self.client.get(f"/ia/partner-evidence/{activity.id}/complete-drawer")
        response = self.client.post(
            f"/ia/partner-evidence/{activity.id}/complete-action",
            self._payload(enrollment="360", salesforce_id="SVE-SSA-IA-1"),
        )

        self.assertEqual(drawer.status_code, 200)
        self.assertContains(drawer, "Update SSA Scores &amp; Complete")
        self.assertEqual(response.status_code, 200)
        record = SsaRecord.objects.get(school=self.school)
        self.assertEqual(record.collector_type, "ia")
        reference = ActivitySalesforceReference.objects.get(activity=activity)
        self.assertEqual(reference.entry_source, "ia_confirmation")

    def test_unrelated_staff_cannot_complete_partner_ssa_support(self):
        activity = self._activity()
        self.client.force_login(self.other_staff)

        drawer = self.client.get(f"/activities/{activity.id}/partner-ssa-complete")
        response = self.client.post(
            f"/activities/{activity.id}/partner-ssa-complete/action",
            self._payload(),
        )

        self.assertEqual(drawer.status_code, 403)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SsaRecord.objects.filter(school=self.school).exists())

    def test_invalid_scores_roll_back_enrolment_and_completion(self):
        activity = self._activity()
        self.client.force_login(self.monitor)
        payload = self._payload(enrollment="999")
        payload.pop(f"score_{SsaIntervention.LEADERSHIP.value}")

        response = self.client.post(
            f"/activities/{activity.id}/partner-ssa-complete/action", payload
        )

        self.assertEqual(response.status_code, 400)
        activity.refresh_from_db()
        self.school.refresh_from_db()
        self.assertEqual(activity.status, "awaiting_ia_verification")
        self.assertEqual(self.school.enrollment, 120)
        self.assertFalse(SsaRecord.objects.filter(school=self.school).exists())
        self.assertFalse(
            ActivitySalesforceReference.objects.filter(activity=activity).exists()
        )

    def test_non_ssa_partner_activity_keeps_salesforce_confirmation_drawer(self):
        activity = self._activity(ssa=False)
        self.client.force_login(self.ia)

        response = self.client.get(
            f"/ia/partner-evidence/{activity.id}/complete-drawer"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirm Salesforce Entry")
        self.assertNotContains(response, 'name="enrollment"')
