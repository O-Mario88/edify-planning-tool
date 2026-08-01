from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.audit.models import AuditLog
from apps.admin_users.services import create as create_user
from apps.accounts.supervisor_service import assign_supervisor
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
        self.ia = self._staff(
            "ia@edify.test", "Impact Lead", EdifyRole.IMPACT_ASSESSMENT.value
        )
        self.rvp = self._staff(
            "rvp@edify.test",
            "Regional Vice President",
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        )
        self.cd = self._staff(
            "cd@edify.test", "Country Director", EdifyRole.COUNTRY_DIRECTOR.value
        )
        self.accountant = self._staff(
            "accountant@edify.test",
            "Programme Accountant",
            EdifyRole.PROGRAM_ACCOUNTANT.value,
        )
        self.hr = self._staff(
            "hr@edify.test", "People Lead", EdifyRole.HUMAN_RESOURCES.value
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

    def _save_managed_people(self, manager, *people):
        return self.client.post(
            self._user_url(manager),
            {
                "action": "configure_managed_people",
                "managed_staff_ids": [person.id for person in people],
            },
        )

    def test_program_lead_user_page_lists_managed_cceos(self):
        response = self.client.get(self._user_url(self.pl_one))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "People Managed")
        self.assertContains(response, self.cceo_one.user.name)
        self.assertContains(response, "Save managed people")

    def test_role_permissions_page_does_not_duplicate_team_editor(self):
        response = self.client.get("/admin-panel/roles-permissions")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Roles & Permissions Matrix")
        self.assertNotContains(response, "People Managed")
        self.assertNotContains(response, "Program Lead Team Assignments")

    def test_non_program_lead_user_page_has_no_team_editor(self):
        response = self.client.get(self._user_url(self.cceo_one))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "People Managed")

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
        self.assertSetEqual(
            set(
                StaffSupervisorAssignment.objects.filter(
                    supervisor=self.pl_one
                ).values_list("supervisee_id", flat=True)
            ),
            {self.cceo_one.id, self.cceo_two.id},
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

    def test_ia_can_be_assigned_same_country_people_without_changing_supervisor(self):
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_one,
            supervisee=self.cceo_one,
        )

        response = self._save_managed_people(
            self.ia, self.pl_one, self.cceo_one, self.accountant
        )

        self.assertRedirects(response, self._user_url(self.ia))
        self.assertSetEqual(
            set(
                StaffSupervisorAssignment.objects.filter(
                    supervisor=self.ia
                ).values_list("supervisee_id", flat=True)
            ),
            {self.pl_one.id, self.cceo_one.id, self.accountant.id},
        )
        self.assertTrue(
            StaffSupervisorAssignment.objects.filter(
                supervisor=self.pl_one,
                supervisee=self.cceo_one,
            ).exists()
        )
        scope = resolve_user_scope(self.ia.user)
        self.assertSetEqual(
            set(scope.managed_staff_ids),
            {self.pl_one.id, self.cceo_one.id, self.accountant.id},
        )

    def test_direct_supervisor_change_preserves_ia_oversight(self):
        self._save_managed_people(self.ia, self.cceo_one)

        assign_supervisor(
            self.cceo_one.id,
            {"supervisorId": self.pl_one.id},
            self.admin,
        )
        self._save_team(self.pl_two, self.cceo_one)

        self.assertTrue(
            StaffSupervisorAssignment.objects.filter(
                supervisor=self.ia,
                supervisee=self.cceo_one,
            ).exists()
        )
        self.assertTrue(
            StaffSupervisorAssignment.objects.filter(
                supervisor=self.pl_two,
                supervisee=self.cceo_one,
            ).exists()
        )
        self.assertFalse(
            StaffSupervisorAssignment.objects.filter(
                supervisor=self.pl_one,
                supervisee=self.cceo_one,
            ).exists()
        )

    def test_rvp_can_be_assigned_same_country_people(self):
        response = self._save_managed_people(
            self.rvp, self.cd, self.pl_one, self.cceo_one
        )

        self.assertRedirects(response, self._user_url(self.rvp))
        self.assertSetEqual(
            set(resolve_user_scope(self.rvp.user).managed_staff_ids),
            {self.cd.id, self.pl_one.id, self.cceo_one.id},
        )

    def test_country_director_automatically_manages_required_country_roles(self):
        response = self.client.get(self._user_url(self.cd))

        self.assertContains(
            response, "automatically manage every PL, IA, Accountant, and CCEO"
        )
        scope = resolve_user_scope(self.cd.user)
        self.assertSetEqual(
            set(scope.managed_staff_ids),
            {
                self.pl_one.id,
                self.pl_two.id,
                self.cceo_one.id,
                self.cceo_two.id,
                self.ia.id,
                self.accountant.id,
            },
        )
        self.assertNotIn(self.hr.id, scope.managed_staff_ids)

    def test_country_director_manual_management_change_is_rejected(self):
        response = self._save_managed_people(self.cd, self.cceo_one)

        self.assertRedirects(response, self._user_url(self.cd))
        self.assertFalse(
            StaffSupervisorAssignment.objects.filter(supervisor=self.cd).exists()
        )
        messages = [str(message) for message in response.wsgi_request._messages]
        self.assertTrue(any("automatically manage" in message for message in messages))

    def test_ia_cross_country_assignment_is_rejected_atomically(self):
        kenya_cceo = self._staff(
            "kenya-managed@edify.test",
            "Kenya Managed Person",
            EdifyRole.CCEO.value,
            country="Kenya",
        )

        self._save_managed_people(self.ia, self.cceo_one, kenya_cceo)

        self.assertFalse(
            StaffSupervisorAssignment.objects.filter(supervisor=self.ia).exists()
        )

    def test_new_management_user_can_be_provisioned_with_managed_people(self):
        result = create_user(
            {
                "email": "new-ia-manager@edify.test",
                "name": "New IA Manager",
                "role": EdifyRole.IMPACT_ASSESSMENT.value,
                "password": "Strong!Pass-2026",
                "managedStaffIds": [self.pl_one.id, self.cceo_one.id],
            },
            self.admin,
        )

        manager = StaffProfile.objects.get(user_id=result["user"]["id"])
        self.assertSetEqual(
            set(
                StaffSupervisorAssignment.objects.filter(
                    supervisor=manager
                ).values_list("supervisee_id", flat=True)
            ),
            {self.pl_one.id, self.cceo_one.id},
        )
