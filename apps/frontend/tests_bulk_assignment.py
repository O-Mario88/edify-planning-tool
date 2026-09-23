from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.geography.models import Region, District, SubCounty
from apps.schools.models import School
from apps.clusters.models import Cluster, ClusterSubCounty, SchoolClusterAssignment
from apps.accounts.models import StaffProfile, StaffSchoolAssignment


class BulkAssignmentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        # Admin is the right actor: cluster membership is registry data, which
        # Platform Operations maintains. Planning, scheduling, execution,
        # verification, approval and payment are what Admin cannot do.
        self.user = User.objects.create(
            id="user-1",
            email="cceo@edify.org",
            name="CCEO User",
            roles=["Admin"],
            active_role="Admin",
        )
        self.staff_profile = StaffProfile.objects.create(
            id="staff-1", user=self.user, title="Admin"
        )

        self.region = Region.objects.create(id="reg-1", name="Central Region")
        self.district = District.objects.create(
            id="dist-1", name="Mukono District", region=self.region
        )
        self.district_other = District.objects.create(
            id="dist-2", name="Wakiso District", region=self.region
        )

        self.sub_county_1 = SubCounty.objects.create(
            id="sc-1", name="Mukono Central", district=self.district
        )
        self.sub_county_2 = SubCounty.objects.create(
            id="sc-2", name="Mukono North", district=self.district
        )
        self.sub_county_other = SubCounty.objects.create(
            id="sc-3", name="Wakiso Central", district=self.district_other
        )

        self.school = School.objects.create(
            id="sch-1",
            school_id="S-1001",
            name="Mukono Primary School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_1,
            school_type="client",
            cluster_status="unclustered",
        )

        self.school_other = School.objects.create(
            id="sch-2",
            school_id="S-1002",
            name="Mukono Secondary School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_2,
            school_type="client",
            cluster_status="unclustered",
        )
        # Cluster creation is constrained to the actor's direct operational
        # portfolio. This test exercises that write path in Mukono.
        StaffSchoolAssignment.objects.create(
            staff=self.staff_profile, school_id=self.school_other.id
        )

        # School in a different district (Wakiso) to test district scoping
        self.school_in_other_district = School.objects.create(
            id="sch-3",
            school_id="S-1003",
            name="Wakiso Primary School",
            region=self.region,
            district=self.district_other,
            sub_county=self.sub_county_other,
            school_type="client",
            cluster_status="unclustered",
        )

        self.cluster = Cluster.objects.create(
            id="cl-1",
            name="Mukono Hub Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_1,
            status="active",
        )
        ClusterSubCounty.objects.create(
            cluster=self.cluster, sub_county=self.sub_county_1
        )

    def test_add_to_cluster_drawer_lists_the_owners_clusters_only(self):
        """The drawer lists the clusters belonging to the school's owner, and
        every one of them may be chosen; an unowned cluster is not listed.

        Owner, 2026-09-21: geography no longer narrows this. A cluster in
        another district used to be listed-but-unchoosable, then refused with
        a catchment reason — so a CCEO could see the right cluster for their
        own schools and be unable to pick it. The portfolio is the rule.
        """
        Cluster.objects.filter(id=self.cluster.id).update(
            responsible_staff_id=self.staff_profile.id
        )
        far = Cluster.objects.create(
            id="cl-far",
            name="Wakiso Owner Cluster",
            region=self.region,
            district=self.district_other,
            status="active",
            responsible_staff_id=self.staff_profile.id,
        )
        unowned = Cluster.objects.create(
            id="cl-unowned",
            name="Unowned Mukono Cluster",
            region=self.region,
            district=self.district,
            status="active",
        )
        self.client.force_login(self.user)
        response = self.client.get(f"/schools/{self.school_other.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)
        # `serves_school` survives as a catchment LABEL; it no longer decides
        # what is offered.
        listed = {c.id: c.serves_school for c in response.context["owner_clusters"]}
        self.assertEqual(listed, {self.cluster.id: True, far.id: False})
        self.assertNotContains(response, unowned.name)

        saved = self.client.post(
            f"/schools/{self.school_other.id}/add-to-cluster",
            {
                "cluster_action_type": "existing",
                "existing_cluster_id": far.id,
                "reason": "The centre these schools actually travel to.",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(saved, "added to")
        self.school_other.refresh_from_db()
        self.assertEqual(self.school_other.cluster_id, far.id)

    def test_create_new_cluster_multi_sub_counties(self):
        self.client.force_login(self.user)
        response = self.client.post(
            f"/schools/{self.school_other.id}/add-to-cluster",
            {
                "cluster_action_type": "new",
                "new_cluster_name": "New Mukono Extended Cluster",
                "new_district_id": "dist-1",
                "new_sub_county_ids": ["sc-2"],
                "notes": "Grouping Mukono sub-counties.",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)

        # Assert cluster was created and assigned
        self.school_other.refresh_from_db()
        self.assertEqual(self.school_other.cluster_status, "clustered")

        new_cluster = Cluster.objects.get(name="New Mukono Extended Cluster")
        self.assertEqual(self.school_other.cluster_id, new_cluster.id)

        # Assert ClusterSubCounty joins were created
        covered = ClusterSubCounty.objects.filter(cluster=new_cluster).values_list(
            "sub_county_id", flat=True
        )
        self.assertIn("sc-2", covered)

    def test_bulk_assign_drawer_candidate_list(self):
        self.client.force_login(self.user)
        # sc-2 is NOT linked to the cluster, but sch-2 is in Mukono District.
        # sch-3 is in Wakiso District.
        response = self.client.get(f"/clusters/{self.cluster.id}/bulk-assign-drawer")
        self.assertEqual(response.status_code, 200)

        schools = response.context["schools"]
        school_ids = [s.id for s in schools]
        # Should include unclustered schools in Mukono District (sch-1 and sch-2)
        self.assertIn("sch-1", school_ids)
        self.assertIn("sch-2", school_ids)
        # Should NOT include sch-3 because it is in Wakiso District
        self.assertNotIn("sch-3", school_ids)

    def test_bulk_assign_drawer_post(self):
        self.client.force_login(self.user)
        # sch-2 is in Mukono District so it can be assigned without prior sub-county linkage
        response = self.client.post(
            f"/clusters/{self.cluster.id}/bulk-assign-drawer",
            {"school_ids": ["sch-1", "sch-2"]},
        )
        self.assertEqual(response.status_code, 200)

        self.school.refresh_from_db()
        self.school_other.refresh_from_db()

        self.assertEqual(self.school.cluster_id, self.cluster.id)
        self.assertEqual(self.school.cluster_status, "clustered")
        self.assertEqual(self.school_other.cluster_id, self.cluster.id)
        self.assertEqual(self.school_other.cluster_status, "clustered")

        # Assert assignments recorded
        self.assertTrue(
            SchoolClusterAssignment.objects.filter(
                school=self.school, cluster=self.cluster
            ).exists()
        )
        self.assertTrue(
            SchoolClusterAssignment.objects.filter(
                school=self.school_other, cluster=self.cluster
            ).exists()
        )

    def test_cluster_detail_has_add_schools_button(self):
        """The cluster detail page provides the Add Schools to Cluster button."""
        self.client.force_login(self.user)
        response = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'hx-get="/clusters/{self.cluster.id}/bulk-assign-drawer"',
        )
        self.assertContains(response, "Add Schools to Cluster")

    def test_schools_directory_scopes_clusters_to_owner(self):
        """School directory assign-cluster modal scopes clusters to the staff owner."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        cceo = User.objects.create(
            id="user-cceo-1",
            email="cceo1@edify.org",
            name="CCEO Test User",
            roles=["CCEO"],
            active_role="CCEO",
        )
        cceo_staff = StaffProfile.objects.create(
            id="staff-cceo-1", user=cceo, title="CCEO"
        )
        # Cluster owned by this CCEO
        my_cluster = Cluster.objects.create(
            id="cl-cceo-1",
            name="CCEO Owned Cluster",
            region=self.region,
            district=self.district,
            responsible_staff_id=cceo_staff.id,
            status="active",
        )
        # Cluster owned by another staff member
        other_cluster = Cluster.objects.create(
            id="cl-other-1",
            name="Other Staff Cluster",
            region=self.region,
            district=self.district,
            responsible_staff_id="some-other-staff-id",
            status="active",
        )

        self.client.force_login(cceo)
        response = self.client.get("/schools")
        self.assertEqual(response.status_code, 200)
        clusters = list(response.context["clusters"])
        cluster_ids = [c.id for c in clusters]
        self.assertIn(my_cluster.id, cluster_ids)
        self.assertNotIn(other_cluster.id, cluster_ids)

    def test_add_to_cluster_drawer_preselects_the_owners_covering_cluster(self):
        StaffSchoolAssignment.objects.create(
            staff=self.staff_profile, school_id=self.school.id
        )
        Cluster.objects.filter(id=self.cluster.id).update(
            responsible_staff_id=self.staff_profile.id
        )
        self.client.force_login(self.user)
        # self.school is in sub_county_1 which is covered by self.cluster
        response = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preselected_cluster_id"], self.cluster.id)

    def test_add_to_cluster_drawer_preselects_per_school(self):
        """Only the cluster covering the school's sub-county opens selected.

        Every other school chooses from the same list with nothing selected,
        including one whose owner has a single cluster serving it: a choice
        made for the planner is the automatic routing this drawer removed.
        """
        StaffSchoolAssignment.objects.create(
            staff=self.staff_profile, school_id=self.school.id
        )
        Cluster.objects.filter(id=self.cluster.id).update(
            responsible_staff_id=self.staff_profile.id
        )
        self.client.force_login(self.user)
        covered = self.client.get(f"/schools/{self.school.id}/add-to-cluster")
        self.assertEqual(covered.context["preselected_cluster_id"], self.cluster.id)

        uncovered = self.client.get(f"/schools/{self.school_other.id}/add-to-cluster")
        self.assertEqual(uncovered.context["preselected_cluster_id"], "")
        self.assertIn(
            self.cluster.id, [c.id for c in uncovered.context["owner_clusters"]]
        )

    def test_choosing_an_owners_cluster_assigns_the_school_directly(self):
        """No automatic routing: the planner's choice is what is saved."""
        StaffSchoolAssignment.objects.create(
            staff=self.staff_profile, school_id=self.school.id
        )
        Cluster.objects.filter(id=self.cluster.id).update(
            responsible_staff_id=self.staff_profile.id
        )
        self.client.force_login(self.user)
        response = self.client.post(
            f"/schools/{self.school.id}/add-to-cluster",
            {"cluster_action_type": "existing", "existing_cluster_id": self.cluster.id},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.school.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.cluster.id)
        self.assertEqual(self.school.cluster_status, "clustered")

    def test_core_dashboard_pagination(self):
        self.client.force_login(self.user)

        # Delete existing core schools first to ensure predictable counts
        School.objects.filter(school_type="core").delete()

        # Create 15 core schools
        for i in range(15):
            School.objects.create(
                school_id=f"CS-{100 + i}",
                name=f"Core School {i}",
                region=self.region,
                district=self.district,
                sub_county=self.sub_county_1,
                school_type="core",
                current_fy_ssa_status="done",
            )

        # Get page 1. The default page size is 15, so this exact cohort fits on
        # one page. The explicit ?per_page=10 below still pins the paging
        # behaviour itself.
        response = self.client.get("/core-schools?page=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["matrix_rows"]), 15)
        self.assertFalse(response.context["is_paginated"])

        response = self.client.get("/core-schools?page=1&per_page=10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["matrix_rows"]), 10)
        self.assertContains(response, 'class="school-record-row__school-id"', count=10)
        self.assertContains(response, response.context["matrix_rows"][0]["school_id"])
        self.assertTrue(response.context["is_paginated"])
        self.assertIn(1, response.context["pages_list"])
        self.assertIn(2, response.context["pages_list"])

        # Get page 2
        response = self.client.get("/core-schools?page=2&per_page=10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["matrix_rows"]), 5)

    def test_next_missing_milestone_calculation(self):
        from apps.core_schools.models import (
            CorePlan,
            CoreActivitySlot,
            cplan_id,
            cslot_id,
        )

        self.client.force_login(self.user)

        # Delete existing core schools first to avoid interference
        School.objects.filter(school_type="core").delete()

        # 1. School without plan -> "Missing First Visit"
        School.objects.create(
            school_id="CS-999",
            name="No Plan School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_1,
            school_type="core",
            current_fy_ssa_status="done",
        )
        response = self.client.get("/core-schools")
        rows = {r["school_id"]: r for r in response.context["matrix_rows"]}
        self.assertEqual(
            rows["CS-999"]["next_missing_milestone"], "Missing First Visit"
        )

        # 2. School with plan, first visit completed -> "Missing First Training"
        school_plan = School.objects.create(
            school_id="CS-888",
            name="Plan School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county_1,
            school_type="core",
            current_fy_ssa_status="done",
        )
        plan = CorePlan.objects.create(
            id=cplan_id(school_plan.school_id),
            school_id=school_plan.school_id,
            fy="2026",
        )
        # Add a completed visit slot for first sequence
        CoreActivitySlot.objects.create(
            id=cslot_id(school_plan.school_id, "visit", 1),
            core_plan=plan,
            school_id=school_plan.school_id,
            intervention="Reading Fluency",
            activity_type="visit",
            sequence_number=1,
            status="completed",
        )
        response = self.client.get("/core-schools")
        rows = {r["school_id"]: r for r in response.context["matrix_rows"]}
        self.assertEqual(
            rows["CS-888"]["next_missing_milestone"], "Missing First Training"
        )


class ClusterMembershipEditingTest(TestCase):
    """Owner, 2026-09-15: the add-schools drawer's save button must be in
    view, and a school added by mistake must be removable — from the edit
    drawer (untick and save) and from the roster (Remove)."""

    def setUp(self):
        BulkAssignmentTests.setUp(self)
        from apps.clusters.services import set_school_cluster_membership

        for school in (self.school, self.school_other):
            set_school_cluster_membership(school, self.cluster, self.user.id)
        self.client.force_login(self.user)

    def test_the_add_schools_drawer_pins_its_save_button_to_the_footer(self):
        from apps.clusters.services import set_school_cluster_membership

        # Give the drawer something to list.
        set_school_cluster_membership(self.school, None, self.user.id)
        response = self.client.get(f"/clusters/{self.cluster.id}/bulk-assign-drawer")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="bulk-assign-save"')
        self.assertContains(response, "Save schools to cluster")
        self.assertContains(response, 'class="drawer-footer"')
        self.assertContains(response, "max-h-[42vh]")

    def test_the_edit_drawer_lists_the_member_schools_ticked(self):
        response = self.client.get(f"/clusters/{self.cluster.id}/edit-drawer")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="manage_members"')
        self.assertContains(response, 'name="member_school_ids"', count=2)
        self.assertContains(response, 'value="sch-1"')
        self.assertContains(response, 'value="sch-2"')
        self.assertContains(response, "Untick a school added by mistake")

    def _save_edit(self, **extra):
        return self.client.post(
            f"/clusters/{self.cluster.id}/edit",
            {
                "name": self.cluster.name,
                "district_id": self.district.id,
                "cluster_type": "mixed",
                **extra,
            },
        )

    def test_saving_the_edit_drawer_removes_the_unticked_schools(self):
        response = self._save_edit(manage_members="1", member_school_ids=["sch-2"])
        self.assertEqual(response.status_code, 302)
        self.school.refresh_from_db()
        self.school_other.refresh_from_db()
        self.assertIsNone(self.school.cluster_id)
        self.assertEqual(self.school.cluster_status, "unclustered")
        self.assertFalse(
            SchoolClusterAssignment.objects.filter(school=self.school).exists()
        )
        self.assertEqual(self.school_other.cluster_id, self.cluster.id)
        self.assertEqual(self.school_other.cluster_status, "clustered")

    def test_a_save_that_never_showed_the_list_keeps_every_school(self):
        """An API client or an older form must not empty the cluster by
        omission: only the drawer's own member list can remove."""
        response = self._save_edit()
        self.assertEqual(response.status_code, 302)
        self.school.refresh_from_db()
        self.school_other.refresh_from_db()
        self.assertEqual(self.school.cluster_id, self.cluster.id)
        self.assertEqual(self.school_other.cluster_id, self.cluster.id)

    def test_remove_from_the_roster_unclusters_the_school(self):
        response = self.client.post(
            f"/clusters/{self.cluster.id}/schools/sch-1/remove",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(
            f"cluster-schools-updated-{self.cluster.id}", response["HX-Trigger"]
        )
        self.school.refresh_from_db()
        self.assertIsNone(self.school.cluster_id)
        self.assertEqual(self.school.cluster_status, "unclustered")
        self.assertFalse(
            SchoolClusterAssignment.objects.filter(school=self.school).exists()
        )
        # Removing it again is refused by name, not silently accepted.
        again = self.client.post(
            f"/clusters/{self.cluster.id}/schools/sch-1/remove",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(again.status_code, 400)
        self.assertContains(again, "is not in", status_code=400)
        # A school outside the district (and the cluster) is not found.
        outside = self.client.post(
            f"/clusters/{self.cluster.id}/schools/sch-3/remove",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(outside.status_code, 400)
        # GET is not a removal.
        self.assertEqual(
            self.client.get(
                f"/clusters/{self.cluster.id}/schools/sch-2/remove"
            ).status_code,
            405,
        )

    def test_the_profile_and_the_card_roster_offer_remove(self):
        profile = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertEqual(profile.status_code, 200)
        self.assertContains(
            profile, f"/clusters/{self.cluster.id}/schools/sch-1/remove"
        )
        self.assertContains(profile, 'hx-confirm="Remove Mukono Primary School from')
        roster = self.client.get(f"/partials/clusters/{self.cluster.id}/schools")
        self.assertEqual(roster.status_code, 200)
        self.assertContains(roster, f"/clusters/{self.cluster.id}/schools/sch-2/remove")
        self.assertContains(roster, "school-record-action--danger")

    def test_a_plain_remove_redirects_to_a_fixed_destination(self):
        """Without htmx the view redirects: to the profile of the cluster
        the service resolved on success, and to the list on refusal --
        never to a URL built from the path value (CodeQL, PR #104)."""
        ok = self.client.post(f"/clusters/{self.cluster.id}/schools/sch-1/remove")
        self.assertEqual(ok.status_code, 302)
        self.assertEqual(ok["Location"], f"/clusters/{self.cluster.id}")
        refused = self.client.post(f"/clusters/{self.cluster.id}/schools/sch-1/remove")
        self.assertEqual(refused.status_code, 302)
        self.assertEqual(refused["Location"], "/clusters")
