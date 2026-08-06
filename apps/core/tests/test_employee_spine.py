"""A person needs a reporting line, an origin, and a way to leave.

`StaffSupervisorAssignment` had no writer outside the demo seeder and no field
on any form, so everyone provisioned through the real UI had no supervisor —
which simultaneously emptied their Program Lead's team scope, left their leave
with no authorized approver, and gave PD and debrief routing no target. The
same page reimplemented the provisioning service inline, so it wrote no audit
row and forced a plaintext password. And offboarding closed nothing.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    User,
    UserInvitation,
)
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region


def _user(email, name, role, **kw):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
        **kw,
    )


class ProvisioningWritesTheReportingLineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = _user("sp-admin@t.org", "Admin One", EdifyRole.ADMIN.value)
        cls.pl = _user("sp-pl@t.org", "Lead One", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.sp_pl = StaffProfile.objects.create(user=cls.pl, country="Uganda")
        region = Region.objects.create(name="SP Region")
        cls.district = District.objects.create(name="SP District", region=region)

    def test_create_assigns_the_supervisor(self):
        from apps.admin_users.services import create

        create(
            {
                "email": "newhire@t.org",
                "name": "New Hire",
                "role": EdifyRole.CCEO.value,
                "primaryDistrictId": self.district.id,
                "supervisorStaffId": self.sp_pl.id,
                "country": "Uganda",
            },
            self.admin,
        )
        new_sp = StaffProfile.objects.get(user__email="newhire@t.org")
        self.assertTrue(
            StaffSupervisorAssignment.objects.filter(
                supervisee=new_sp, supervisor=self.sp_pl
            ).exists(),
            "without a supervisor this person has no leave approver, no team "
            "scope, and no development-request routing",
        )

    def test_create_captures_country(self):
        from apps.admin_users.services import create

        create(
            {
                "email": "kenyan@t.org",
                "name": "Kenya Hire",
                "role": EdifyRole.CCEO.value,
                "country": "Kenya",
            },
            self.admin,
        )
        self.assertEqual(
            StaffProfile.objects.get(user__email="kenyan@t.org").country,
            "Kenya",
            "country defaulted to Uganda for everyone, making the "
            "country-scoped HR surfaces inert",
        )

    def test_a_provisioner_chosen_password_must_be_changed(self):
        from apps.admin_users.services import create

        create(
            {
                "email": "pw@t.org",
                "name": "Pw Hire",
                "role": EdifyRole.CCEO.value,
                "password": "Str0ng!Passw0rd42",
            },
            self.admin,
        )
        user = User.objects.get(email="pw@t.org")
        self.assertTrue(
            user.must_change_password,
            "a password someone else chose is known to someone else",
        )


class AdminPageDelegatesToTheServiceTests(TestCase):
    """The page was a hand-rolled copy that had drifted."""

    def setUp(self):
        self.admin = _user("pg-admin@t.org", "Admin Two", EdifyRole.ADMIN.value)
        StaffProfile.objects.create(user=self.admin, country="Uganda")
        self.client.force_login(self.admin)

    def test_creating_a_user_from_the_page_writes_an_audit_row(self):
        self.client.post(
            reverse("frontend:admin_users"),
            {
                "action": "create",
                "name": "Audited Hire",
                "email": "audited@t.org",
                "role": EdifyRole.CCEO.value,
            },
        )
        self.assertTrue(
            AuditLog.objects.filter(action="admin.user_created").exists(),
            "an account provisioned from this page had no recorded origin",
        )

    def test_omitting_the_password_sends_an_invitation(self):
        self.client.post(
            reverse("frontend:admin_users"),
            {
                "action": "create",
                "name": "Invited Hire",
                "email": "invited@t.org",
                "role": EdifyRole.CCEO.value,
            },
        )
        user = User.objects.get(email="invited@t.org")
        self.assertEqual(user.status, "pending_invited")
        self.assertTrue(UserInvitation.objects.filter(user=user).exists())

    def test_the_page_no_longer_reimplements_the_service(self):
        from apps.frontend.views import extended_views

        source = inspect.getsource(extended_views.admin_users_view)
        self.assertIn("create_user_service", source)
        self.assertNotIn("User.objects.create_user(", source)


class OffboardingClosesTheLoopTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr = _user("off-hr@t.org", "HR One", "HumanResources")
        StaffProfile.objects.create(user=cls.hr, country="Uganda")
        cls.leaver = _user("off-leaver@t.org", "Leaver", EdifyRole.CCEO.value)
        cls.sp = StaffProfile.objects.create(user=cls.leaver, country="Uganda")

    def _plan(self, last_working_day=None):
        from apps.hr.models import OffboardingPlan

        return OffboardingPlan.objects.create(
            staff=self.sp,
            status="Initiated",
            last_working_day=last_working_day or date.today() - timedelta(days=1),
        )

    def test_there_is_a_terminal_lifecycle_state(self):
        from apps.accounts.models import StaffOnboardingState

        self.assertIn("exited", [c[0] for c in StaffOnboardingState.choices])

    def test_completing_offboarding_disables_the_account(self):
        from apps.hr.offboarding_service import complete_offboarding

        plan = self._plan()
        complete_offboarding(plan.id, self.hr)

        self.leaver.refresh_from_db()
        self.sp.refresh_from_db()
        self.assertFalse(self.leaver.is_active, "the account outlived the exit date")
        self.assertEqual(self.sp.onboarding_state, "exited")
        self.assertTrue(
            AuditLog.objects.filter(action="hr.offboarding_completed").exists()
        )

    def test_it_refuses_while_work_still_points_at_the_person(self):
        from apps.activities.models import Activity
        from apps.hr.offboarding_service import complete_offboarding
        from apps.schools.models import School
        from django.utils import timezone

        region = Region.objects.create(name="Off Region")
        district = District.objects.create(name="Off District", region=region)
        school = School.objects.create(
            name="Off Primary",
            school_id="OFF-1",
            region_id=region.id,
            district_id=district.id,
        )
        Activity.objects.create(
            school_id=school.id,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=self.sp.id,
            planned_date=timezone.now(),
        )
        plan = self._plan()
        with self.assertRaises(BadRequest):
            complete_offboarding(plan.id, self.hr)

    def test_only_hr_may_complete_an_offboarding(self):
        from apps.hr.offboarding_service import complete_offboarding

        cceo = _user("off-cceo@t.org", "Somebody", EdifyRole.CCEO.value)
        plan = self._plan()
        with self.assertRaises(Forbidden):
            complete_offboarding(plan.id, cceo)

    def test_accounts_past_their_exit_date_are_detectable(self):
        from apps.hr.offboarding_service import accounts_past_last_working_day

        self._plan(last_working_day=date.today() - timedelta(days=10))
        self.assertEqual(
            accounts_past_last_working_day().count(),
            1,
            "nothing read last_working_day, so this condition was invisible",
        )


class HRAuditLogReadsTheRealChainTests(TestCase):
    def test_the_page_no_longer_reads_the_unchained_table(self):
        from apps.frontend.views import hr_views

        source = inspect.getsource(hr_views.hr_audit_log_view)
        self.assertIn("from apps.audit.models import AuditLog", source)
        self.assertNotIn(
            "HRAuditEvent.objects",
            source,
            "a second, hash-chain-less table with no writer was presented as "
            "the HR accountability record",
        )
