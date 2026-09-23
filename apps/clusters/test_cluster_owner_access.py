"""Owners can edit their cluster even without a district portfolio."""

from apps.accounts.models import StaffSchoolAssignment
from apps.clusters.services import update_cluster
from apps.clusters.test_eligibility import EligibilityFixture
from apps.core.exceptions import Forbidden


class ClusterOwnerAccessTest(EligibilityFixture):
    def test_owner_without_district_assignment_can_save_existing_district(self):
        StaffSchoolAssignment.objects.filter(staff=self.james_profile).delete()
        self.school.account_owner_id = None
        self.school.save(update_fields=["account_owner_id"])
        update_cluster(
            self.chegere_north.id,
            {
                "name": "Owner update",
                "districtId": self.apac.id,
            },
            self.james,
        )
        self.chegere_north.refresh_from_db()
        self.assertEqual(self.chegere_north.name, "Owner update")

    def test_profile_id_owner_remains_selected_in_edit_drawer(self):
        self.chegere_north.responsible_staff_id = self.james_profile.id
        self.chegere_north.save(update_fields=["responsible_staff_id"])
        self.client.force_login(self.james)
        response = self.client.get(f"/clusters/{self.chegere_north.id}/edit-drawer")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{self.james.id}" selected')

    def test_team_members_do_not_gain_edit_permission(self):
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.core.rbac import EdifyRole

        lead, profile = self._staff("owner-access-lead@test.local")
        lead.active_role = EdifyRole.COUNTRY_PROGRAM_LEAD.value
        lead.save()
        for staff in (self.james_profile, self.mary_profile):
            StaffSupervisorAssignment.objects.create(
                supervisee=staff, supervisor=profile
            )
        for user in (self.mary, lead):
            with self.assertRaises(Forbidden):
                update_cluster(self.chegere_north.id, {"name": "No"}, user)

    def test_owner_can_add_own_school_from_another_district(self):
        far_school = self._school(
            "OWNER-FAR",
            "Owner distant school",
            self.james_profile,
            district=self.kole,
            sub_county=None,
        )
        self.client.force_login(self.james)
        url = f"/clusters/{self.chegere_north.id}/bulk-assign-drawer"
        response = self.client.get(url)
        self.assertContains(response, far_school.name)
        response = self.client.post(url, {"school_ids": [far_school.id]})
        self.assertEqual(response.status_code, 200)
        far_school.refresh_from_db()
        self.assertEqual(far_school.cluster_id, self.chegere_north.id)

    def test_non_owner_lead_does_not_receive_an_edit_control(self):
        from apps.accounts.models import StaffSupervisorAssignment
        from apps.core.rbac import EdifyRole

        lead, profile = self._staff("drawer-lead@test.local")
        lead.active_role = EdifyRole.COUNTRY_PROGRAM_LEAD.value
        lead.save()
        StaffSupervisorAssignment.objects.create(
            supervisee=self.james_profile, supervisor=profile
        )
        self.client.force_login(lead)
        response = self.client.get(f"/clusters/{self.chegere_north.id}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_edit_cluster"])
        response = self.client.get(f"/clusters/{self.chegere_north.id}/edit-drawer")
        self.assertEqual(response.status_code, 403)
