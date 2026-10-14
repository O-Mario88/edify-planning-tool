"""Who completes a partner activity (owner, 2026-09-12).

"The IA and Staff can enter partner visits into Salesforce and use the
Salesforce ID to complete partner activities. Partner just have to upload the
visit form or training attendance."

So the Salesforce-ID door completes partner work for Impact Assessment and for
the staff member named as the activity's monitor — and for nobody else. Every
other door on a partner activity stays the partner's.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

User = get_user_model()


class PartnerConfirmationAuthorityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="PC Region")
        district = District.objects.create(name="PC District", region=region)
        cls.school = School.objects.create(
            school_id="PC-SCH", name="PC School", region=region, district=district
        )

        def _person(uid, email, role):
            user = User.objects.create(
                id=uid,
                email=email,
                name=email,
                roles=[role],
                active_role=role,
                is_active=True,
            )
            profile = StaffProfile.objects.create(
                user=user, staff_number=uid.upper(), country="Uganda", title=role
            )
            return user, profile

        cls.monitor, cls.monitor_sp = _person(
            "pc-monitor", "pc-monitor@edify.org", "CCEO"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.monitor_sp, school_id=cls.school.id
        )
        cls.other, cls.other_sp = _person("pc-other", "pc-other@edify.org", "CCEO")
        StaffSchoolAssignment.objects.create(
            staff=cls.other_sp, school_id=cls.school.id
        )
        cls.ia, _ = _person("pc-ia", "pc-ia@edify.org", "ImpactAssessment")
        cls.partner_user = User.objects.create(
            id="pc-partner-user",
            email="pc-partner@edify.org",
            name="PC Partner",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            is_active=True,
        )
        cls.partner = Partner.objects.create(
            name="PC Partner Org", user_id=cls.partner_user.id, active_status=True
        )

    def _activity(self, **kwargs):
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy="2026",
            quarter="Q1",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            responsible_staff_id=None,
            monitored_by_staff_id=self.monitor_sp.id,
            status="awaiting_ia_verification",
            scheduled_date=timezone.now(),
            **kwargs,
        )
        EvidenceRecord.objects.create(
            activity=activity,
            kind="visit_form",
            uri="pc/visit-form.pdf",
            uploaded_by=self.partner_user.id,
        )
        return activity

    def _record(self, user, activity, sf_id):
        self.client.force_login(user)
        return self.client.post(
            f"/activities/{activity.id}/salesforce-id/action", {"salesforce_id": sf_id}
        )

    def test_the_monitoring_staff_member_completes_it_with_the_salesforce_id(self):
        activity = self._activity()
        response = self._record(self.monitor, activity, "SVE-PC-0001")
        activity.refresh_from_db()
        self.assertEqual(
            activity.status,
            "ia_verified",
            f"door said {response.status_code}: {response.content[:200]!r}",
        )
        self.assertEqual(activity.ia_verification_status, "confirmed")
        self.assertEqual(activity.salesforce_activity_id, "SVE-PC-0001")
        self.assertEqual(activity.payment_status, "ia_confirmed")

    def test_impact_assessment_completes_it_the_same_way(self):
        activity = self._activity()
        self._record(self.ia, activity, "SVE-PC-0002")
        activity.refresh_from_db()
        self.assertEqual(activity.status, "ia_verified")
        self.assertEqual(activity.salesforce_activity_id, "SVE-PC-0002")

    def test_a_staff_member_who_is_not_the_monitor_is_refused(self):
        activity = self._activity()
        response = self._record(self.other, activity, "SVE-PC-0003")
        self.assertEqual(response.status_code, 403)
        activity.refresh_from_db()
        self.assertEqual(activity.status, "awaiting_ia_verification")
        self.assertFalse(activity.salesforce_activity_id)

    def test_the_delivering_partner_cannot_confirm_its_own_work(self):
        from apps.core.permissions import RolePermissionService

        activity = self._activity()
        self.assertFalse(
            RolePermissionService.can_confirm_partner_activity(
                self.partner_user, activity
            )
        )

    def test_staff_delivered_work_is_still_impact_assessment_only(self):
        from apps.core.exceptions import Forbidden
        from apps.activities.services import ia_confirm

        staff_activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy="2026",
            quarter="Q1",
            delivery_type="staff",
            responsible_staff_id=self.other.id,
            status="awaiting_ia_verification",
            scheduled_date=timezone.now(),
        )
        with self.assertRaises(Forbidden):
            ia_confirm(staff_activity.id, {"salesforceId": "SVE-PC-0004"}, self.monitor)

    def test_ssa_support_keeps_its_own_drawer(self):
        activity = self._activity(
            purpose_type="ssa_support", ssa_collection_expected=True
        )
        response = self._record(self.monitor, activity, "SVE-PC-0005")
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"SSA Support", response.content)
        activity.refresh_from_db()
        self.assertEqual(activity.status, "awaiting_ia_verification")

    def test_the_monitor_still_cannot_upload_the_partners_evidence(self):
        activity = self._activity()
        self.client.force_login(self.monitor)
        response = self.client.post(
            f"/activities/{activity.id}/evidence/action",
            {"evidence_kind": "visit_form"},
        )
        self.assertEqual(response.status_code, 403)

    def test_the_detail_page_offers_the_monitor_the_salesforce_door(self):
        activity = self._activity()
        self.client.force_login(self.monitor)
        page = self.client.get(f"/my-plan/{activity.id}")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Record Salesforce ID")
        self.assertContains(page, f"/activities/{activity.id}/salesforce-id")

    def test_the_detail_page_offers_it_to_nobody_else(self):
        activity = self._activity()
        self.client.force_login(self.other)
        page = self.client.get(f"/my-plan/{activity.id}")
        self.assertNotContains(page, "Record Salesforce ID")

    def test_the_drawer_says_recording_the_id_completes_the_work(self):
        activity = self._activity()
        self.client.force_login(self.monitor)
        drawer = self.client.get(f"/activities/{activity.id}/salesforce-id")
        self.assertEqual(drawer.status_code, 200)
        self.assertContains(drawer, "completes this partner activity")
