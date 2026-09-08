"""Impact Assessment verifies its country's work, and never its own.

Owner, 2026-09-03. The queue, workspace, returned list, history and
dashboard stop at the country border; nobody certifies or returns work they
are responsible for; and the Country Director is the fallback verifier for
the one case the IA cannot handle — an IA officer's own field visit — and
for nothing else.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.ia_services import _assert_may_certify
from apps.activities.models import Activity
from apps.core.exceptions import Forbidden
from apps.core.permissions import RolePermissionService
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, name, role, country="Uganda"):
    u = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=u, title=role, country=country)
    return u


def _awaiting(school, responsible, code):
    return Activity.objects.create(
        activity_type="school_visit",
        status="awaiting_ia_verification",
        school=school,
        fy="2026",
        planned_date=date(2026, 3, 2),
        responsible_staff_id=responsible.staff_profile.id,
        salesforce_activity_id=code,
    )


class IaReachAndSelfVerificationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        ug = Region.objects.create(name="IA Central", country="Uganda")
        ke = Region.objects.create(name="IA Nairobi", country="Kenya")
        ug_d = District.objects.create(name="IA Wakiso", region=ug)
        ke_d = District.objects.create(name="IA Kiambu", region=ke)
        cls.ug_school = School.objects.create(
            name="IA Kampala Primary", school_id="IA-UG-1", region=ug, district=ug_d
        )
        cls.ke_school = School.objects.create(
            name="IA Nairobi Primary", school_id="IA-KE-1", region=ke, district=ke_d
        )
        cls.ia = _user("ia-ug@t.org", "Ida UG", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.ia2 = _user("ia-ug2@t.org", "Ivan UG", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.ke_ia = _user(
            "ia-ke@t.org", "Ida KE", EdifyRole.IMPACT_ASSESSMENT.value, "Kenya"
        )
        cls.cd = _user("cd-ug@t.org", "Dan CD", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.cceo = _user("cceo-ug@t.org", "Cara CCEO", EdifyRole.CCEO.value)
        cls.ke_cceo = _user("cceo-ke@t.org", "Kip CCEO", EdifyRole.CCEO.value, "Kenya")
        cls.cceo_work = _awaiting(cls.ug_school, cls.cceo, "SF-CCEO")
        cls.ia_own = _awaiting(cls.ug_school, cls.ia, "SF-IA-OWN")
        cls.ke_work = _awaiting(cls.ke_school, cls.ke_cceo, "SF-KE")

    def test_the_queue_and_its_pages_stop_at_the_border(self):
        self.client.force_login(self.ia)
        for url in (
            "/ia/verification/",
            "/ia/dashboard/",
            "/ia/returned/",
            "/ia/history/",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertNotContains(response, "IA Nairobi Primary", msg_prefix=url)
        queue = self.client.get("/ia/verification/")
        self.assertContains(queue, "IA Kampala Primary")
        self.assertEqual(
            self.client.get(f"/ia/verification/{self.ke_work.id}/").status_code, 404
        )

    def test_nobody_verifies_their_own_work(self):
        self.assertFalse(RolePermissionService.can_verify_ia(self.ia, self.ia_own))
        with self.assertRaises(Forbidden):
            _assert_may_certify(str(self.ia.id), self.ia_own)
        # A colleague can.
        self.assertTrue(RolePermissionService.can_verify_ia(self.ia2, self.ia_own))
        _assert_may_certify(str(self.ia2.id), self.ia_own)
        # And ordinary work is unaffected.
        self.assertTrue(RolePermissionService.can_verify_ia(self.ia, self.cceo_work))

    def test_the_country_director_is_the_fallback_verifier_for_ia_work_only(self):
        self.assertTrue(RolePermissionService.can_verify_ia(self.cd, self.ia_own))
        _assert_may_certify(str(self.cd.id), self.ia_own)
        self.assertFalse(RolePermissionService.can_verify_ia(self.cd, self.cceo_work))
        with self.assertRaises(Forbidden):
            _assert_may_certify(str(self.cd.id), self.cceo_work)
        self.client.force_login(self.cd)
        queue = self.client.get("/ia/verification/")
        self.assertEqual(queue.status_code, 200)
        self.assertContains(queue, f"/ia/verification/{self.ia_own.id}/")
        self.assertNotContains(queue, f"/ia/verification/{self.cceo_work.id}/")
        self.assertEqual(
            self.client.get(f"/ia/verification/{self.cceo_work.id}/").status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/ia/verification/{self.ia_own.id}/").status_code, 200
        )

    def test_a_kenya_verifier_cannot_reach_uganda_work(self):
        self.assertTrue(RolePermissionService.can_verify_ia(self.ke_ia, self.cceo_work))
        self.client.force_login(self.ke_ia)
        self.assertEqual(
            self.client.get(f"/ia/verification/{self.cceo_work.id}/").status_code, 404
        )
