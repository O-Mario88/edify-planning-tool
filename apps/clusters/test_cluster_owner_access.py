"""Owners can edit their cluster even without a district portfolio."""

from apps.accounts.models import StaffSchoolAssignment
from apps.clusters.services import update_cluster
from apps.clusters.test_eligibility import EligibilityFixture
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole


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


class UnownedClusterClaimTest(EligibilityFixture):
    """An unowned cluster can be picked up only from inside your portfolio.

    The owner carve-out in `may_edit_cluster_profile` must not become a
    back door: without a district check, any planner anywhere could post an
    edit for an unowned cluster naming themselves as responsible staff.
    """

    def setUp(self):
        super().setUp()
        from apps.clusters.models import Cluster
        from apps.core.enums import ClusterRecordStatus
        from apps.geography.models import District, Region

        self.unowned = Cluster.objects.create(
            name="Unowned Apac Cluster",
            region=self.region,
            district=self.apac,
            sub_county=self.chegere,
            cluster_type="mixed",
            status=ClusterRecordStatus.ACTIVE,
            responsible_staff_id=None,
        )
        west = Region.objects.create(name="West")
        kabale = District.objects.create(name="Kabale", region=west)
        self.outsider, self.outsider_profile = self._staff("outsider@edify.test")
        from apps.schools.models import School

        school = School.objects.create(
            school_id="WEST-1",
            name="Kabale Primary",
            region=west,
            district=kabale,
            school_type="client",
            account_owner_id=self.outsider_profile.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.outsider_profile, school_id=school.id
        )

    def _claim(self, user):
        return update_cluster(
            self.unowned.id,
            {
                "name": "Claimed",
                "districtId": self.apac.id,
                "responsibleStaffId": user.id,
            },
            user,
        )

    def test_out_of_scope_cceo_cannot_claim_an_unowned_cluster(self):
        with self.assertRaises(Forbidden):
            self._claim(self.outsider)
        self.unowned.refresh_from_db()
        self.assertEqual(self.unowned.name, "Unowned Apac Cluster")
        self.assertFalse(self.unowned.responsible_staff_id)

    def test_out_of_scope_cceo_cannot_claim_through_the_edit_form(self):
        self.client.force_login(self.outsider)
        response = self.client.get(f"/clusters/{self.unowned.id}/edit-drawer")
        self.assertIn(response.status_code, (403, 404))
        self.client.post(
            f"/clusters/{self.unowned.id}/edit",
            {
                "name": "Claimed",
                "district_id": self.apac.id,
                "responsible_staff_id": self.outsider.id,
            },
        )
        self.unowned.refresh_from_db()
        self.assertEqual(self.unowned.name, "Unowned Apac Cluster")
        self.assertFalse(self.unowned.responsible_staff_id)

    def test_cceo_in_the_district_can_still_pick_it_up(self):
        self._claim(self.james)
        self.unowned.refresh_from_db()
        self.assertEqual(self.unowned.name, "Claimed")
        self.assertEqual(self.unowned.responsible_staff_id, self.james.id)


class CountryScopeOwnerBulkAssignTest(EligibilityFixture):
    """The owner's cross-district pool is for a field owner's own schools.

    A country-scope owner's pool is every unclustered school, so clearing the
    served-district filter for them listed schools from anywhere at all.
    """

    def test_country_scope_owner_sees_only_the_served_districts(self):
        from apps.geography.models import District, Region
        from apps.schools.models import School

        admin, _ = self._staff("country-owner@edify.test")
        admin.roles = [EdifyRole.ADMIN.value]
        admin.active_role = EdifyRole.ADMIN.value
        admin.save()
        self.chegere_north.responsible_staff_id = admin.id
        self.chegere_north.save(update_fields=["responsible_staff_id"])
        near = School.objects.create(
            school_id="APAC-UNCL",
            name="Apac Unclustered Primary",
            region=self.region,
            district=self.apac,
            school_type="client",
            cluster_status="unclustered",
        )
        elsewhere = Region.objects.create(name="Elsewhere")
        far_district = District.objects.create(name="Faraway", region=elsewhere)
        far = School.objects.create(
            school_id="FAR-UNCL",
            name="Faraway Unclustered Primary",
            region=elsewhere,
            district=far_district,
            school_type="client",
            cluster_status="unclustered",
        )
        self.client.force_login(admin)
        response = self.client.get(
            f"/clusters/{self.chegere_north.id}/bulk-assign-drawer"
        )
        self.assertEqual(response.status_code, 200)
        listed = {s.id for s in response.context["schools"]}
        self.assertIn(near.id, listed)
        self.assertNotIn(far.id, listed)
