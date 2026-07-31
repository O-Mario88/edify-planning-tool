from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.audit.models import AuditLog
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_user_scope


class ProgramLeadTeamConfigurationTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin-team-config@edify.test",
            name="Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="password123",
        )
        self.pl_one = self._staff(
            "pl-one@edify.test",
            "Program Lead One",
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        )
        self.pl_two = self._staff(
            "pl-two@edify.test",
            "Program Lead Two",
            EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        )
        self.cceo_one = self._staff(
            "cceo-one@edify.test", "CCEO One", EdifyRole.CCEO.value
        )
        self.cceo_two = self._staff(
            "cceo-two@edify.test", "CCEO Two", EdifyRole.CCEO.value
        )
        self.client.force_login(self.admin)

    @staticmethod
    def _user_url(staff_profile):
        return f"/admin-panel/users/{staff_profile.user_id}"

    @staticmethod
    def _staff(email, name, role, *, country="Uganda"):
        user = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="password123",
        )
        return StaffProfile.objects.create(
            user=user,
            title=role,
            country=country,
        )

    def _save_team(self, program_lead, *cceos):
        return self.client.post(
            self._user_url(program_lead),
            {
                "action": "configure_program_lead_team",
                "cceo_ids": [cceo.id for cceo in cceos],
            },
        )

    def test_program_lead_user_page_lists_managed_cceos(self):
        response = self.client.get(self._user_url(self.pl_one))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Managed CCEOs")
        self.assertContains(response, self.cceo_one.user.name)
        self.assertContains(response, "Save managed CCEOs")

    def test_role_permissions_page_does_not_duplicate_team_editor(self):
        response = self.client.get("/admin-panel/roles-permissions")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Roles & Permissions Matrix")
        self.assertNotContains(response, "Managed CCEOs")
        self.assertNotContains(response, "Program Lead Team Assignments")

    def test_non_program_lead_user_page_has_no_team_editor(self):
        response = self.client.get(self._user_url(self.cceo_one))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Managed CCEOs")

    def test_save_assigns_team_and_updates_program_lead_scope(self):
        response = self._save_team(self.pl_one, self.cceo_one, self.cceo_two)

        self.assertRedirects(response, self._user_url(self.pl_one))
        self.assertSetEqual(
            set(
                StaffSupervisorAssignment.objects.filter(
                    supervisor=self.pl_one
                ).values_list("supervisee_id", flat=True)
            ),
            {self.cceo_one.id, self.cceo_two.id},
        )
        scope = resolve_user_scope(self.pl_one.user)
        self.assertSetEqual(
            set(scope.supervised_staff_ids),
            {self.cceo_one.id, self.cceo_two.id},
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.program_lead_team_configured",
                subject_id=self.pl_one.id,
                actor_id=self.admin.id,
            ).exists()
        )

    def test_selecting_cceo_under_another_lead_reassigns_them(self):
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_one,
            supervisee=self.cceo_one,
        )

        self._save_team(self.pl_two, self.cceo_one)

        link = StaffSupervisorAssignment.objects.get(supervisee=self.cceo_one)
        self.assertEqual(link.supervisor_id, self.pl_two.id)
        self.assertFalse(
            StaffSupervisorAssignment.objects.filter(
                supervisor=self.pl_one,
                supervisee=self.cceo_one,
            ).exists()
        )

    def test_saving_empty_team_only_clears_that_program_lead(self):
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_one,
            supervisee=self.cceo_one,
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_two,
            supervisee=self.cceo_two,
        )

        self._save_team(self.pl_one)

        self.assertFalse(
            StaffSupervisorAssignment.objects.filter(supervisor=self.pl_one).exists()
        )
        self.assertTrue(
            StaffSupervisorAssignment.objects.filter(
                supervisor=self.pl_two,
                supervisee=self.cceo_two,
            ).exists()
        )

    def test_cross_country_cceo_is_rejected_without_partial_change(self):
        kenya_cceo = self._staff(
            "kenya-cceo@edify.test",
            "Kenya CCEO",
            EdifyRole.CCEO.value,
            country="Kenya",
        )

        response = self._save_team(self.pl_one, self.cceo_one, kenya_cceo)

        self.assertRedirects(response, self._user_url(self.pl_one))
        self.assertFalse(StaffSupervisorAssignment.objects.exists())
        messages = [str(message) for message in response.wsgi_request._messages]
        self.assertIn(
            "A Program Lead can only manage CCEOs in the same country.",
            messages,
        )
